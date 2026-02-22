import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_hot_note.config import Settings, get_settings
from agent_hot_note.pipeline.fallback import FallbackDecision, FallbackPlanner
from agent_hot_note.providers.llm.deepseek import DeepSeekProvider
from agent_hot_note.providers.search.tavily import TavilySearch

logger = logging.getLogger(__name__)
ERROR_LOG_LIMIT = 1000


@dataclass
class CrewOutput:
    research: str
    draft: str
    edited: str
    search_results: dict[str, Any]
    fallback_decision: FallbackDecision


class SequentialCrew:
    """Sequential crew with compact IO logging.

    Pattern note:
    - Follows Anthropic's "Workflow / Prompt Chaining" pattern:
      fixed stages (research -> write -> edit), each stage consuming prior output.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_provider = DeepSeekProvider(self.settings)
        self.llm_provider.apply_env()
        self.search_provider = TavilySearch(self.settings)
        self.llm_model = self._normalize_model(self.settings.openai_model)
        self.primary_domains = self._parse_domains(self.settings.fallback_primary_domains)
        self.secondary_domains = self._parse_domains(self.settings.fallback_secondary_domains)
        self.fallback_planner = FallbackPlanner(
            min_results=self.settings.fallback_min_results,
            min_avg_summary_chars=self.settings.fallback_min_avg_summary_chars,
            max_title_dup_ratio=self.settings.fallback_max_title_dup_ratio,
        )
        self.extract_allowed_domains = self._parse_domains(self.settings.tavily_extract_allowed_domains)

    async def run(self, topic: str) -> CrewOutput:
        logger.info("research")
        search_results, fallback_decision = await self._search_with_fallback(topic)
        research, draft, edited = await self._run_with_crewai_async(topic, search_results)
        return CrewOutput(
            research=research,
            draft=draft,
            edited=edited,
            search_results=search_results,
            fallback_decision=fallback_decision,
        )

    async def _search_with_fallback(self, topic: str) -> tuple[dict[str, Any], FallbackDecision]:
        primary_result = await self.search_provider.search(topic, include_domains=self.primary_domains or None)
        primary_decision = self.fallback_planner.plan(
            topic=topic,
            results=primary_result.get("results", []),
            primary_domains=self.primary_domains,
            secondary_domains=self.secondary_domains,
        )
        if not primary_decision.triggered:
            logger.info("fallback.not_triggered reason=%s", primary_decision.reason)
            enriched = await self._enrich_results_with_extract(primary_result)
            return enriched, primary_decision

        logger.info("fallback.triggered reason=%s", primary_decision.reason)
        attempted_queries: list[str] = [topic]
        attempted_domains: list[list[str]] = [self.primary_domains]
        result_batches: list[list[dict[str, Any]]] = [primary_result.get("results", [])]

        followup_domain_steps: list[list[str]] = []
        if self.secondary_domains:
            followup_domain_steps.append(self.secondary_domains)
        followup_domain_steps.append([])

        merged_results = self._merge_results(result_batches, max_items=self.settings.tavily_max_results)
        for domains in followup_domain_steps:
            followup_result = await self.search_provider.search(topic, include_domains=domains or None)
            attempted_queries.append(topic)
            attempted_domains.append(domains)
            result_batches.append(followup_result.get("results", []))
            merged_results = self._merge_results(result_batches, max_items=self.settings.tavily_max_results)
            merged_decision = self.fallback_planner.plan(
                topic=topic,
                results=merged_results,
                primary_domains=self.primary_domains,
                secondary_domains=self.secondary_domains,
            )
            if not merged_decision.triggered:
                logger.info("fallback.resolved step_domains=%s", domains)
                break

        merged_result = {"query": topic, "results": merged_results}
        final_decision = FallbackDecision(
            triggered=True,
            reason=primary_decision.reason,
            queries=attempted_queries,
            domains=attempted_domains,
        )
        enriched = await self._enrich_results_with_extract(merged_result)
        return enriched, final_decision

    async def _enrich_results_with_extract(self, search_results: dict[str, Any]) -> dict[str, Any]:
        results = list(search_results.get("results", []))
        if not self.settings.tavily_extract_enabled:
            search_results["extracted_urls"] = []
            search_results["extract_failed_urls"] = []
            return search_results

        candidate_urls = self._select_extract_urls(results)
        if not candidate_urls:
            search_results["extracted_urls"] = []
            search_results["extract_failed_urls"] = []
            return search_results

        try:
            extract_result = await self.search_provider.extract(candidate_urls)
            contents: dict[str, str] = extract_result.get("contents", {})
            failed_urls = extract_result.get("failed_urls", [])
            search_results["results"] = self._apply_extracted_content(results, contents)
            search_results["extracted_urls"] = list(contents.keys())
            search_results["extract_failed_urls"] = failed_urls
            return search_results
        except Exception as exc:
            logger.warning("extract.failed type=%s detail=%s", exc.__class__.__name__, str(exc))
            search_results["extracted_urls"] = []
            search_results["extract_failed_urls"] = candidate_urls
            return search_results

    async def _run_with_crewai_async(self, topic: str, search_results: dict[str, Any]) -> tuple[str, str, str]:
        os.environ.setdefault("OTEL_SDK_DISABLED", str(self.settings.otel_sdk_disabled).lower())
        os.environ.setdefault("CREWAI_STORAGE_DIR", self.settings.crewai_storage_dir)
        Path(self.settings.crewai_storage_dir).mkdir(parents=True, exist_ok=True)

        from crewai import Agent, Crew, Process, Task

        search_context = self._build_search_context(search_results)
        llm_model = self.llm_model
        agent = Agent(
            role="Hot Note Strategist",
            goal="Generate practical and concise Chinese hot-note content",
            backstory="You are a content strategist focused on actionable short-form notes.",
            llm=llm_model,
            verbose=False,
            allow_delegation=False,
        )

        research_task = Task(
            description=(
                "Analyze topic: {topic}. Give concise Chinese findings using the snippets.\n"
                f"Snippets:\n{search_context}"
            ),
            expected_output="Concise Chinese summary with 3 key angles.",
            agent=agent,
        )

        logger.info("write")
        write_task = Task(
            description="Write concise Chinese body with sections, based on research.",
            expected_output="Chinese draft with clear sections and actionable steps.",
            agent=agent,
            context=[research_task],
        )

        logger.info("edit")
        edit_task = Task(
            description="Polish draft and output 3 Chinese titles + 10 Chinese tags.",
            expected_output="Chinese edits including 3 titles and 10 tags.",
            agent=agent,
            context=[write_task],
        )

        crew = Crew(
            agents=[agent],
            tasks=[research_task, write_task, edit_task],
            process=Process.sequential,
            verbose=False,
        )
        logger.info(
            "llm.call model=%s timeout=%.1fs retries=%d",
            self.llm_model,
            self.settings.llm_timeout_seconds,
            self.settings.llm_num_retries,
        )
        try:
            with self._litellm_logging_context():
                result = await crew.kickoff_async(inputs={"topic": topic})
        except Exception as exc:
            logger.error(
                "llm.error model=%s type=%s detail=%s",
                self.llm_model,
                exc.__class__.__name__,
                self._extract_error_detail(exc),
            )
            raise
        task_outputs = getattr(result, "tasks_output", None) or getattr(crew, "tasks_output", None)
        if not task_outputs or len(task_outputs) < 3:
            raise RuntimeError("CrewAI did not return all stage outputs")

        research = self._stringify_task_output(task_outputs[0])
        draft = self._stringify_task_output(task_outputs[1])
        edited = self._stringify_task_output(task_outputs[2])
        return research, draft, edited

    @staticmethod
    def _stringify_task_output(task_output: Any) -> str:
        raw = getattr(task_output, "raw", None)
        if raw is not None:
            return str(raw).strip()
        return str(task_output).strip()

    def _build_search_context(self, search_results: dict[str, Any]) -> str:
        snippets: list[str] = []
        for item in search_results.get("results", [])[: self.settings.search_context_results]:
            title = SequentialCrew._clip(str(item.get("title", "")).strip(), self.settings.search_title_chars)
            content = SequentialCrew._clip(str(item.get("content", "")).strip(), self.settings.search_content_chars)
            snippets.append(f"- {title}: {content}")
        return "\n".join(snippets) or "- no snippets"

    @contextmanager
    def _litellm_logging_context(self):
        import litellm

        original_completion = litellm.completion

        def wrapped_completion(**params: Any):
            params.setdefault("timeout", self.settings.llm_timeout_seconds)
            params.setdefault("num_retries", self.settings.llm_num_retries)
            params.setdefault("base_url", self.settings.openai_base_url)
            if self.settings.openai_api_key:
                params.setdefault("api_key", self.settings.openai_api_key)
            params["model"] = self._normalize_model(str(params.get("model", self.llm_model)))

            model = str(params.get("model", self.llm_model))
            request_text = self._extract_prompt(params.get("messages", []))
            logger.info("llm.request.full model=%s\n%s", model, request_text)

            response = original_completion(**params)
            response_text = self._extract_response_text(response)
            logger.info("llm.response.full model=%s\n%s", model, response_text)
            return response

        litellm.completion = wrapped_completion
        try:
            yield
        finally:
            litellm.completion = original_completion

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}...(truncated)"

    @staticmethod
    def _extract_prompt(messages: Any) -> str:
        if not isinstance(messages, list):
            return str(messages)
        parts: list[str] = []
        for message in messages:
            if isinstance(message, dict):
                parts.append(str(message.get("content", "")))
            else:
                parts.append(str(message))
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        try:
            choices = getattr(response, "choices", None) or response.get("choices", [])
            if not choices:
                return str(response)
            message = choices[0].get("message", {})
            return str(message.get("content", ""))
        except Exception:
            return str(response)

    def _extract_error_detail(self, exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        message = getattr(exc, "message", None) or str(exc)
        body = getattr(exc, "body", None)
        details = [f"status_code={status_code}" if status_code is not None else ""]
        if body is not None:
            details.append(f"body={body}")
        details.append(f"message={message}")
        return self._clip(" ".join([part for part in details if part]).strip(), ERROR_LOG_LIMIT)

    @staticmethod
    def _normalize_model(model: str) -> str:
        stripped = model.strip()
        if "/" in stripped:
            return stripped
        return f"openai/{stripped}"

    @staticmethod
    def _parse_domains(raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def _merge_results(result_batches: list[list[dict[str, Any]]], max_items: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for batch in result_batches:
            for item in batch:
                key = str(item.get("url") or item.get("title") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= max_items:
                    return merged
        return merged

    def _select_extract_urls(self, results: list[dict[str, Any]]) -> list[str]:
        allowed = set(self.extract_allowed_domains)
        urls: list[str] = []
        for item in results:
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if allowed and host not in allowed:
                continue
            if url in urls:
                continue
            urls.append(url)
            if len(urls) >= self.settings.tavily_extract_max_urls:
                break
        return urls

    @staticmethod
    def _apply_extracted_content(results: list[dict[str, Any]], contents: dict[str, str]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for item in results:
            row = dict(item)
            url = str(row.get("url", "")).strip()
            extracted = contents.get(url)
            if extracted:
                row["content"] = extracted
            enriched.append(row)
        return enriched
