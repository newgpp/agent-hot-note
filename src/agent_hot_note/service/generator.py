import logging
from typing import Any

from agent_hot_note.workflow.generation import GenerationWorkflow

logger = logging.getLogger(__name__)


class GenerateService:
    def __init__(self, workflow: GenerationWorkflow | None = None) -> None:
        self.workflow = workflow or GenerationWorkflow()

    async def generate(self, topic: str, topic_profile: str | None = None) -> dict:
        try:
            requested_profile = (topic_profile or "").strip().lower() or None
            output = await self.workflow.run(topic, profile_id=requested_profile)
            markdown = self._to_markdown(topic, output.research, output.draft, output.edited)
            logger.info("generated markdown chars=%d topic=%s", len(markdown), topic)
            logger.info("generated markdown full:\n%s", markdown)
            query = output.search_results.get("query")
            fallback_meta = output.fallback_decision.as_meta()
            logger.info(
                "generate.meta topic=%s fallback_triggered=%s fallback_reason=%s extracted=%d extract_failed=%d",
                topic,
                fallback_meta["fallback_triggered"],
                fallback_meta["fallback_reason"],
                len(output.search_results.get("extracted_urls", [])),
                len(output.search_results.get("extract_failed_urls", [])),
            )
            return {
                "markdown": markdown,
                "meta": {
                    "stages": ["research", "write", "edit"],
                    "requested_topic_profile": requested_profile,
                    "topic_profile": output.search_results.get("profile_id"),
                    "query": query,
                    "queries": fallback_meta["fallback_queries"] if query else [],
                    "extracted_urls": output.search_results.get("extracted_urls", []),
                    "extract_failed_urls": output.search_results.get("extract_failed_urls", []),
                    **fallback_meta,
                },
            }
        except Exception as exc:
            logger.exception("generate.failed topic=%s", topic)
            return {
                "markdown": "",
                "meta": {
                    "stages": ["research", "write", "edit"],
                    "error": self._error_payload(exc),
                },
            }

    @staticmethod
    def _error_payload(exc: Exception) -> dict[str, Any]:
        message = str(exc)
        hint = "请检查 OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL 以及网络连通性"
        if "Connection error" not in message:
            hint = "请查看服务日志中的 llm.error 详情"
        return {
            "type": exc.__class__.__name__,
            "message": message,
            "hint": hint,
        }

    def _to_markdown(self, topic: str, research: str, draft: str, edited: str) -> str:
        research_text = research.strip() or "（暂无研究内容）"
        draft_text = draft.strip() or "（暂无正文草稿）"
        edited_text = edited.strip() or "（暂无润色内容）"
        return "\n".join(
            [
                f"# {topic}",
                "",
                "## 研究要点",
                research_text,
                "",
                "## 正文",
                draft_text,
                "",
                "## 发布版",
                edited_text,
                "",
                "<!-- source-stages: research,draft,edited -->",
            ]
        )
