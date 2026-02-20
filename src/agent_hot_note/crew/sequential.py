import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_hot_note.config import Settings, get_settings
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


class SequentialCrew:
    """Sequential crew with compact IO logging."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_provider = DeepSeekProvider(self.settings)
        self.llm_provider.apply_env()
        self.search_provider = TavilySearch(self.settings)
        self.llm_model = self._normalize_model(self.settings.openai_model)

    async def run(self, topic: str) -> CrewOutput:
        logger.info("research")
        search_results = await self.search_provider.search(topic)
        research, draft, edited = await self._run_with_crewai_async(topic, search_results)
        return CrewOutput(research=research, draft=draft, edited=edited, search_results=search_results)

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
