from fastapi.testclient import TestClient

from agent_hot_note.api.app import app, service

client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generate_markdown_shape(monkeypatch) -> None:
    async def fake_generate(topic: str, topic_profile: str | None = None) -> dict:
        return {
            "markdown": "\n".join(
                [
                    f"# {topic}",
                    "## 研究要点",
                    "research",
                    "## 正文",
                    "draft",
                    "## 发布版",
                    "edited",
                ]
            ),
            "meta": {
                "stages": ["research", "write", "edit"],
                "requested_topic_profile": topic_profile,
                "topic_profile": topic_profile or "general",
                "query": topic,
                "queries": [topic],
            },
        }

    monkeypatch.setattr(service, "generate", fake_generate)

    resp = client.post("/generate", json={"topic": "AI 笔记"})
    assert resp.status_code == 200
    data = resp.json()
    assert "markdown" in data
    assert "meta" in data
    markdown = data["markdown"]
    assert "# AI 笔记" in markdown
    assert "## 研究要点" in markdown
    assert "## 正文" in markdown
    assert "## 发布版" in markdown


def test_generate_with_topic_profile(monkeypatch) -> None:
    captured: dict[str, str | None] = {"topic_profile": None}

    async def fake_generate(topic: str, topic_profile: str | None = None) -> dict:
        captured["topic_profile"] = topic_profile
        return {"markdown": f"# {topic}", "meta": {"topic_profile": topic_profile}}

    monkeypatch.setattr(service, "generate", fake_generate)

    resp = client.post("/generate", json={"topic": "AI 笔记", "topic_profile": "job"})
    assert resp.status_code == 200
    assert captured["topic_profile"] == "job"
    assert resp.json()["meta"]["topic_profile"] == "job"
