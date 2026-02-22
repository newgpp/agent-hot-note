import asyncio

from agent_hot_note.pipeline.fallback import FallbackDecision
from agent_hot_note.service.generator import GenerateService


class _FakeCrew:
    async def run(self, topic: str):
        class _Output:
            research = "research"
            draft = "draft"
            edited = "edited"
            search_results = {
                "query": topic,
                "results": [],
                "extracted_urls": ["https://xiaohongshu.com/p/1"],
                "extract_failed_urls": ["https://zhihu.com/p/2"],
            }
            fallback_decision = FallbackDecision(
                triggered=True,
                reason="insufficient_results",
                queries=[topic, topic, topic],
                domains=[["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []],
            )

        return _Output()


def test_generate_meta_contains_fallback_fields() -> None:
    service = GenerateService(crew=_FakeCrew())  # type: ignore[arg-type]
    result = asyncio.run(service.generate("AI 笔记"))
    meta = result["meta"]
    assert meta["fallback_triggered"] is True
    assert meta["fallback_reason"] == "insufficient_results"
    assert meta["fallback_queries"] == ["AI 笔记", "AI 笔记", "AI 笔记"]
    assert meta["fallback_domains"] == [["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []]
    assert meta["extracted_urls"] == ["https://xiaohongshu.com/p/1"]
    assert meta["extract_failed_urls"] == ["https://zhihu.com/p/2"]
    assert meta["queries"] == ["AI 笔记", "AI 笔记", "AI 笔记"]
