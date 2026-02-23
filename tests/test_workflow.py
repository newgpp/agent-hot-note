import logging
import asyncio

from agent_hot_note.workflow.generation import GenerationWorkflow
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

    async def fake_run_with_langgraph(self, topic: str, search_results: dict) -> tuple[str, str, str]:
        logger = logging.getLogger("agent_hot_note.workflow.generation")
        logger.info("write")
        logger.info("edit")
        return "r", "d", "e"

    monkeypatch.setattr(TavilySearch, "search", fake_search)
    monkeypatch.setattr(GenerationWorkflow, "_run_with_langgraph_async", fake_run_with_langgraph)
    async def fake_profile(self, topic: str) -> str:
        return "general"
    monkeypatch.setattr(GenerationWorkflow, "_classify_topic_profile", fake_profile)
    workflow = GenerationWorkflow()

    with caplog.at_level(logging.INFO):
        output = asyncio.run(workflow.run("测试主题"))

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
    workflow = GenerationWorkflow()
    orchestrator = workflow.search_orchestrator
    orchestrator.extract_allowed_domains = ["xiaohongshu.com"]

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

    monkeypatch.setattr(orchestrator.search_provider, "extract", fake_extract)
    enriched = asyncio.run(orchestrator._enrich_results_with_extract(base))

    assert enriched["extracted_urls"] == ["https://xiaohongshu.com/p/1"]
    assert enriched["extract_failed_urls"] == []
    assert enriched["results"][0]["content"] == "long extracted content"
    assert enriched["results"][1]["content"] == "short2"


def test_extract_failure_degrades_to_snippets(monkeypatch) -> None:
    workflow = GenerationWorkflow()
    orchestrator = workflow.search_orchestrator
    orchestrator.extract_allowed_domains = ["xiaohongshu.com"]

    base = {
        "query": "topic",
        "results": [{"title": "a", "url": "https://xiaohongshu.com/p/1", "content": "short"}],
    }

    async def fake_extract(urls: list[str]) -> dict:
        raise RuntimeError("extract timeout")

    monkeypatch.setattr(orchestrator.search_provider, "extract", fake_extract)
    enriched = asyncio.run(orchestrator._enrich_results_with_extract(base))

    assert enriched["extracted_urls"] == []
    assert enriched["extract_failed_urls"] == ["https://xiaohongshu.com/p/1"]
    assert enriched["results"][0]["content"] == "short"


def test_profile_domain_resolution_uses_configured_profile() -> None:
    workflow = GenerationWorkflow()
    profile_id, primary, secondary, extract_allowed = workflow.search_orchestrator._resolve_profile_domains("job")
    assert profile_id == "job"
    assert "bosszhipin.com" in primary
    assert "51job.com" in secondary
    assert "bosszhipin.com" in extract_allowed


def test_classify_topic_profile_uses_llm_result(monkeypatch) -> None:
    workflow = GenerationWorkflow()

    async def fake_ask_llm(prompt: str) -> str:
        return "job"

    monkeypatch.setattr(workflow, "_ask_llm", fake_ask_llm)
    profile = asyncio.run(workflow._classify_topic_profile("Python Agent工程师技能要求"))
    assert profile == "job"


def test_classify_topic_profile_prompt_contains_keyword_hints(monkeypatch) -> None:
    workflow = GenerationWorkflow()
    captured = {"prompt": ""}

    async def fake_ask_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "general"

    monkeypatch.setattr(workflow, "_ask_llm", fake_ask_llm)
    _ = asyncio.run(workflow._classify_topic_profile("示例话题"))
    assert "job keywords:" in captured["prompt"]
    assert "finance keywords:" in captured["prompt"]
