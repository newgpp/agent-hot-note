import logging
from dataclasses import dataclass
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
    """Sequential crew implemented with LangGraph workflow nodes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_provider = DeepSeekProvider(self.settings)
        self.llm_provider.apply_env()
        self.search_provider = TavilySearch(self.settings)
        self.llm_model = self._normalize_model(self.settings.openai_model)
        self._llm: Any | None = None

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
        research, draft, edited = await self._run_with_langgraph_async(topic, search_results)
        return CrewOutput(
            research=research,
            draft=draft,
            edited=edited,
            search_results=search_results,
            fallback_decision=fallback_decision,
        )

    async def _search_with_fallback(self, topic: str) -> tuple[dict[str, Any], FallbackDecision]:
        primary_result = await self.search_provider.search(topic, include_domains=self.primary_domains or None)
        primary_count = len(primary_result.get("results", []))
        primary_decision = self.fallback_planner.plan(
            topic=topic,
            results=primary_result.get("results", []),
            primary_domains=self.primary_domains,
            secondary_domains=self.secondary_domains,
        )
        logger.info(
            "fallback.evaluate step=primary results=%d reason=%s domains=%s",
            primary_count,
            primary_decision.reason,
            self.primary_domains,
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
            logger.info("fallback.attempt domains=%s", domains)
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
            logger.info(
                "fallback.evaluate step=followup merged_results=%d reason=%s domains=%s",
                len(merged_results),
                merged_decision.reason,
                domains,
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
            logger.info("extract.skipped reason=disabled")
            search_results["extracted_urls"] = []
            search_results["extract_failed_urls"] = []
            return search_results

        candidate_urls = self._select_extract_urls(results)
        logger.info(
            "extract.candidates total_results=%d candidate_urls=%d allowed_domains=%s",
            len(results),
            len(candidate_urls),
            self.extract_allowed_domains,
        )
        if not candidate_urls:
            logger.info("extract.skipped reason=no_candidates")
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
            logger.info(
                "extract.applied success=%d failed=%d",
                len(search_results["extracted_urls"]),
                len(failed_urls),
            )
            return search_results
        except Exception as exc:
            logger.warning("extract.failed type=%s detail=%s", exc.__class__.__name__, str(exc))
            search_results["extracted_urls"] = []
            search_results["extract_failed_urls"] = candidate_urls
            return search_results

    async def _run_with_langgraph_async(self, topic: str, search_results: dict[str, Any]) -> tuple[str, str, str]:
        from typing import TypedDict
        from langgraph.graph import END, START, StateGraph

        class WorkflowState(TypedDict):
            topic: str
            search_context: str
            research: str
            draft: str
            edited: str

        search_context = self._build_search_context(search_results)

        async def research_node(state: WorkflowState) -> dict[str, str]:
            prompt = (
                f"Analyze topic: {state['topic']}. Give concise Chinese findings using snippets.\\n"
                f"Snippets:\\n{state['search_context']}"
            )
            logger.info("llm.request.full stage=research model=%s\\n%s", self.llm_model, prompt)
            text = await self._ask_llm(prompt)
            logger.info("llm.response.full stage=research model=%s\\n%s", self.llm_model, text)
            return {"research": text}

        async def write_node(state: WorkflowState) -> dict[str, str]:
            logger.info("write")
            prompt = (
                f"Topic: {state['topic']}\\n"
                "Write concise Chinese body with sections, based on research below.\\n"
                f"Research:\\n{state['research']}"
            )
            logger.info("llm.request.full stage=write model=%s\\n%s", self.llm_model, prompt)
            text = await self._ask_llm(prompt)
            logger.info("llm.response.full stage=write model=%s\\n%s", self.llm_model, text)
            return {"draft": text}

        async def edit_node(state: WorkflowState) -> dict[str, str]:
            logger.info("edit")
            prompt = (
                f"Topic: {state['topic']}\\n"
                "Polish draft and output 3 Chinese titles + 10 Chinese tags.\\n"
                f"Draft:\\n{state['draft']}"
            )
            logger.info("llm.request.full stage=edit model=%s\\n%s", self.llm_model, prompt)
            text = await self._ask_llm(prompt)
            logger.info("llm.response.full stage=edit model=%s\\n%s", self.llm_model, text)
            return {"edited": text}

        graph = StateGraph(WorkflowState)
        graph.add_node("research_step", research_node)
        graph.add_node("write_step", write_node)
        graph.add_node("edit_step", edit_node)
        graph.add_edge(START, "research_step")
        graph.add_edge("research_step", "write_step")
        graph.add_edge("write_step", "edit_step")
        graph.add_edge("edit_step", END)

        app = graph.compile()
        logger.info(
            "llm.call model=%s timeout=%.1fs retries=%d",
            self.llm_model,
            self.settings.llm_timeout_seconds,
            self.settings.llm_num_retries,
        )

        try:
            final_state = await app.ainvoke(
                {
                    "topic": topic,
                    "search_context": search_context,
                    "research": "",
                    "draft": "",
                    "edited": "",
                }
            )
        except Exception as exc:
            logger.error(
                "llm.error model=%s type=%s detail=%s",
                self.llm_model,
                exc.__class__.__name__,
                self._extract_error_detail(exc),
            )
            raise

        return (
            str(final_state.get("research", "")).strip(),
            str(final_state.get("draft", "")).strip(),
            str(final_state.get("edited", "")).strip(),
        )

    async def _ask_llm(self, prompt: str) -> str:
        llm = self._get_llm()
        response = await llm.ainvoke(prompt)
        return self._message_text(getattr(response, "content", response))

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=self._strip_provider_prefix(self.llm_model),
                api_key=self.settings.openai_api_key or None,
                base_url=self.settings.openai_base_url,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_num_retries,
            )
        return self._llm

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return "\\n".join(parts).strip()
        return str(content).strip()

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
        return "\\n".join(snippets) or "- no snippets"

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}...(truncated)"

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
    def _strip_provider_prefix(model: str) -> str:
        if "/" not in model:
            return model
        return model.split("/", 1)[1]

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
