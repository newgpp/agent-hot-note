import logging
from dataclasses import dataclass
from typing import Any

from agent_hot_note.config import Settings, get_settings
from agent_hot_note.retrieval.fallback import FallbackDecision
from agent_hot_note.retrieval.search_orchestrator import SearchOrchestrator
from agent_hot_note.providers.llm.deepseek import DeepSeekProvider

logger = logging.getLogger(__name__)
ERROR_LOG_LIMIT = 1000


@dataclass
class GenerationResult:
    research: str
    draft: str
    edited: str
    search_results: dict[str, Any]
    fallback_decision: FallbackDecision


class GenerationWorkflow:
    """Sequential generation workflow implemented with LangGraph nodes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_provider = DeepSeekProvider(self.settings)
        self.llm_provider.apply_env()
        self.search_orchestrator = SearchOrchestrator(self.settings)
        self.llm_model = self._normalize_model(self.settings.openai_model)
        self._llm: Any | None = None

    async def run(self, topic: str, profile_id: str | None = None) -> GenerationResult:
        logger.info("research")
        resolved_profile = profile_id or await self._classify_topic_profile(topic)
        search_results, fallback_decision = await self.search_orchestrator.search_with_profile(
            topic,
            profile_id=resolved_profile,
        )
        research, draft, edited = await self._run_with_langgraph_async(topic, search_results)
        return GenerationResult(
            research=research,
            draft=draft,
            edited=edited,
            search_results=search_results,
            fallback_decision=fallback_decision,
        )

    async def _classify_topic_profile(self, topic: str) -> str:
        default_profile = self.settings.topic_default_profile
        profile_ids = sorted(self.settings.topic_domain_profiles.keys())
        if not profile_ids:
            return default_profile

        keyword_hints = self._keyword_prompt_hints(profile_ids)
        prompt = (
            "You are a topic router.\n"
            f"Choose one profile id from: {', '.join(profile_ids)}.\n"
            "Follow keyword routing hints first, then infer by intent.\n"
            f"{keyword_hints}\n"
            f"If unsure, choose {default_profile}.\n"
            "Output only the profile id.\n"
            f"Topic: {topic}"
        )
        try:
            choice = (await self._ask_llm(prompt)).strip().lower()
            normalized = choice.splitlines()[0].strip().strip("`").strip()
            if normalized in self.settings.topic_domain_profiles:
                logger.info("topic.profile classified=%s topic=%s", normalized, self._clip(topic, 80))
                return normalized
            logger.info("topic.profile invalid=%s fallback=%s", normalized, default_profile)
        except Exception as exc:
            logger.warning(
                "topic.profile.classify_failed type=%s detail=%s",
                exc.__class__.__name__,
                self._extract_error_detail(exc),
            )
        return default_profile

    @staticmethod
    def _keyword_prompt_hints(profile_ids: list[str]) -> str:
        hints: list[str] = []
        if "job" in profile_ids:
            hints.append(
                "job keywords: 招聘/求职/找工作/岗位/面试/简历/薪资/JD/工程师/内推/校招/社招 -> choose job."
            )
        if "finance" in profile_ids:
            hints.append(
                "finance keywords: 财经/金融/股票/基金/债券/财报/估值/研报/A股/港股/美股 -> choose finance."
            )
        if "general" in profile_ids:
            hints.append("general keywords or lifestyle/travel/general intent -> choose general.")
        return " ".join(hints) if hints else "Classify by topic intent."

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
            title = GenerationWorkflow._clip(str(item.get("title", "")).strip(), self.settings.search_title_chars)
            content = GenerationWorkflow._clip(str(item.get("content", "")).strip(), self.settings.search_content_chars)
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
