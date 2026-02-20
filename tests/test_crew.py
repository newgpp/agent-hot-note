import logging
import asyncio

from litellm.types.utils import ModelResponse

from agent_hot_note.crew.sequential import SequentialCrew
from agent_hot_note.providers.search.tavily import TavilySearch


def test_sequential_logs_order(caplog, monkeypatch) -> None:
    async def fake_search(self, topic: str) -> dict:
        return {
            "query": topic,
            "results": [{"title": "t1", "content": "c1"}, {"title": "t2", "content": "c2"}],
        }

    def fake_completion(**kwargs):
        return ModelResponse(
            model=str(kwargs.get("model", "deepseek-chat")),
            choices=[{"message": {"role": "assistant", "content": "Thought: ok\n\nFinal Answer: ok"}}],
        )

    monkeypatch.setattr(TavilySearch, "search", fake_search)
    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)

    crew = SequentialCrew()

    with caplog.at_level(logging.INFO):
        output = asyncio.run(crew.run("测试主题"))

    assert output.research
    assert output.draft
    assert output.edited

    messages = [record.getMessage() for record in caplog.records]
    research_idx = messages.index("research")
    write_idx = messages.index("write")
    edit_idx = messages.index("edit")
    assert research_idx < write_idx < edit_idx

    assert any(message.startswith("llm.request") for message in messages)
    assert any(message.startswith("llm.response") for message in messages)
