import asyncio

from agent_hot_note.retrieval.fallback import FallbackDecision
from agent_hot_note.service.generator import GenerateService


class _FakeWorkflow:
    async def run(self, topic: str, profile_id: str | None = None):
        class _Output:
            research = "research"
            draft = "draft"
            edited = "edited"
            search_results = {
                "query": topic,
                "results": [],
                "profile_id": "job",
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
    service = GenerateService(workflow=_FakeWorkflow())  # type: ignore[arg-type]
    result = asyncio.run(service.generate("AI 笔记"))
    meta = result["meta"]
    assert meta["topic_profile"] == "job"
    assert meta["fallback_triggered"] is True
    assert meta["fallback_reason"] == "insufficient_results"
    assert meta["fallback_queries"] == ["AI 笔记", "AI 笔记", "AI 笔记"]
    assert meta["fallback_domains"] == [["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []]
    assert meta["extracted_urls"] == ["https://xiaohongshu.com/p/1"]
    assert meta["extract_failed_urls"] == ["https://zhihu.com/p/2"]
    assert meta["queries"] == ["AI 笔记", "AI 笔记", "AI 笔记"]
