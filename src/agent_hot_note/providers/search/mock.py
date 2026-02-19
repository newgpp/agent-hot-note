from typing import Any


class MockSearch:
    """Phase 1 mock search provider with fixed structure."""

    async def search(self, topic: str) -> dict[str, Any]:
        return {
            "query": topic,
            "results": [
                {
                    "title": f"{topic} 趋势观察",
                    "url": "https://example.com/trend",
                    "content": f"{topic} 在近期讨论中热度提升，用户关注点集中在实用方法与对比。",
                },
                {
                    "title": f"{topic} 实操总结",
                    "url": "https://example.com/practice",
                    "content": f"关于 {topic} 的内容偏好是短结论 + 可直接复制的步骤。",
                },
            ],
        }
