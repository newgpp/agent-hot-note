import logging
import asyncio

from agent_hot_note.crew.sequential import SequentialCrew


def test_sequential_logs_order(caplog) -> None:
    crew = SequentialCrew()

    with caplog.at_level(logging.INFO):
        output = asyncio.run(crew.run("测试主题"))

    assert output.research
    assert output.draft
    assert output.edited

    messages = [record.getMessage() for record in caplog.records]
    assert messages[-3:] == ["research", "write", "edit"]
