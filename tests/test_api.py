from fastapi.testclient import TestClient

from agent_hot_note.api.app import app, service

client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generate_markdown_shape(monkeypatch) -> None:
    async def fake_generate(topic: str) -> dict:
        return {
            "markdown": "\n".join(
                [
                    "# 标题（3个）",
                    "- t1",
                    "- t2",
                    "- t3",
                    "# 正文",
                    "body",
                    "# 标签（10个）",
                    "#a #b #c #d #e #f #g #h #i #j",
                ]
            ),
            "meta": {"stages": ["research", "write", "edit"], "query": topic, "queries": [topic]},
        }

    monkeypatch.setattr(service, "generate", fake_generate)

    resp = client.post("/generate", json={"topic": "AI 笔记"})
    assert resp.status_code == 200
    data = resp.json()
    assert "markdown" in data
    assert "meta" in data
    markdown = data["markdown"]
    assert "# 标题（3个）" in markdown
    assert "# 正文" in markdown
    assert "# 标签（10个）" in markdown
    assert markdown.count("#") >= 10
