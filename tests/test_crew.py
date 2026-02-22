import logging
import asyncio

from agent_hot_note.crew.sequential import SequentialCrew
from agent_hot_note.providers.search.tavily import TavilySearch


def test_sequential_logs_order(caplog, monkeypatch) -> None:
    async def fake_search(self, topic: str, include_domains: list[str] | None = None) -> dict:
        return {
            "query": topic,
            "results": [
                {"title": "t1", "content": "this is a long enough summary for fallback quality evaluation in tests"},
                {"title": "t2", "content": "this is a long enough summary for fallback quality evaluation in tests"},
            ],
        }

    async def fake_run_with_crewai(self, topic: str, search_results: dict) -> tuple[str, str, str]:
        logger = logging.getLogger("agent_hot_note.crew.sequential")
        logger.info("write")
        logger.info("edit")
        return "r", "d", "e"

    monkeypatch.setattr(TavilySearch, "search", fake_search)
    monkeypatch.setattr(SequentialCrew, "_run_with_crewai_async", fake_run_with_crewai)
    crew = SequentialCrew()

    with caplog.at_level(logging.INFO):
        output = asyncio.run(crew.run("测试主题"))

    assert output.research
    assert output.draft
    assert output.edited
    assert output.fallback_decision.triggered is False
    assert output.search_results["extracted_urls"] == []
    assert output.search_results["extract_failed_urls"] == []

    messages = [record.getMessage() for record in caplog.records]
    research_idx = messages.index("research")
    write_idx = messages.index("write")
    edit_idx = messages.index("edit")
    assert research_idx < write_idx < edit_idx


def test_extract_success_enriches_content(monkeypatch) -> None:
    crew = SequentialCrew()
    crew.extract_allowed_domains = ["xiaohongshu.com"]

    base = {
        "query": "topic",
        "results": [
            {"title": "a", "url": "https://xiaohongshu.com/p/1", "content": "short"},
            {"title": "b", "url": "https://example.com/p/2", "content": "short2"},
        ],
    }

    async def fake_extract(urls: list[str]) -> dict:
        assert urls == ["https://xiaohongshu.com/p/1"]
        return {"contents": {"https://xiaohongshu.com/p/1": "long extracted content"}, "failed_urls": []}

    monkeypatch.setattr(crew.search_provider, "extract", fake_extract)
    enriched = asyncio.run(crew._enrich_results_with_extract(base))

    assert enriched["extracted_urls"] == ["https://xiaohongshu.com/p/1"]
    assert enriched["extract_failed_urls"] == []
    assert enriched["results"][0]["content"] == "long extracted content"
    assert enriched["results"][1]["content"] == "short2"


def test_extract_failure_degrades_to_snippets(monkeypatch) -> None:
    crew = SequentialCrew()
    crew.extract_allowed_domains = ["xiaohongshu.com"]

    base = {
        "query": "topic",
        "results": [{"title": "a", "url": "https://xiaohongshu.com/p/1", "content": "short"}],
    }

    async def fake_extract(urls: list[str]) -> dict:
        raise RuntimeError("extract timeout")

    monkeypatch.setattr(crew.search_provider, "extract", fake_extract)
    enriched = asyncio.run(crew._enrich_results_with_extract(base))

    assert enriched["extracted_urls"] == []
    assert enriched["extract_failed_urls"] == ["https://xiaohongshu.com/p/1"]
    assert enriched["results"][0]["content"] == "short"
