import logging

from agent_hot_note.crew.sequential import SequentialCrew

logger = logging.getLogger(__name__)


class GenerateService:
    def __init__(self, crew: SequentialCrew | None = None) -> None:
        self.crew = crew or SequentialCrew()

    async def generate(self, topic: str) -> dict:
        output = await self.crew.run(topic)
        markdown = self._to_markdown(topic, output.research, output.draft, output.edited)
        logger.info("generated markdown:\n%s", markdown)
        return {
            "markdown": markdown,
            "meta": {
                "stages": ["research", "write", "edit"],
                "query": output.search_results.get("query"),
            },
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
