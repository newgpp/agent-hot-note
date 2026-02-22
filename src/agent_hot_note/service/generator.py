import logging
from typing import Any

from agent_hot_note.crew.sequential import SequentialCrew

logger = logging.getLogger(__name__)


class GenerateService:
    def __init__(self, crew: SequentialCrew | None = None) -> None:
        self.crew = crew or SequentialCrew()

    async def generate(self, topic: str) -> dict:
        try:
            output = await self.crew.run(topic)
            markdown = self._to_markdown(topic, output.research, output.draft, output.edited)
            logger.info("generated markdown chars=%d topic=%s", len(markdown), topic)
            logger.info("generated markdown full:\n%s", markdown)
            query = output.search_results.get("query")
            fallback_meta = output.fallback_decision.as_meta()
            return {
                "markdown": markdown,
                "meta": {
                    "stages": ["research", "write", "edit"],
                    "query": query,
                    "queries": fallback_meta["fallback_queries"] if query else [],
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
        return "\n".join(
            [
                f"# 标题（3个）",
                f"- {topic}：3步搭建你的高效流程",
                f"- {topic}：从0到1跑通最小闭环",
                f"- {topic}：减少试错的实战清单",
                "",
                "# 正文",
                research,
                "",
                draft,
                "",
                "# 标签（10个）",
                "#效率 #方法论 #实操 #复盘 #热点 #内容创作 #增长 #清单 #教程 #经验",
                "",
                "<!-- edit-summary -->",
                edited,
            ]
        )
