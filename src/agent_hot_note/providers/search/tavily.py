import logging
import json
from typing import Any

from agent_hot_note.config import Settings

logger = logging.getLogger(__name__)
PAYLOAD_LOG_LIMIT = 4000


class TavilySearch:
    """Tavily search provider with compact input/output logs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.search_depth = settings.tavily_search_depth
        self.max_results = settings.tavily_max_results

    async def search(self, topic: str) -> dict[str, Any]:
        request_payload = {
            "query": topic,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
        }
        logger.info(
            "tavily.request query=%s depth=%s max_results=%d",
            self._clip(topic, 80),
            self.search_depth,
            self.max_results,
        )
        logger.info(
            "tavily.request.payload=%s",
            self._clip(self._to_json(request_payload), PAYLOAD_LOG_LIMIT),
        )

        try:
            from tavily import TavilyClient
        except ImportError as exc:
            raise RuntimeError("tavily-python is required") from exc

        client = TavilyClient(api_key=self.settings.tavily_api_key or None)
        response = client.search(query=topic, search_depth=self.search_depth, max_results=self.max_results)
        results = response.get("results", [])
        logger.info(
            "tavily.response results=%d top_titles=%s",
            len(results),
            ", ".join(
                [self._clip(str(item.get("title", "")), self.settings.tavily_title_chars) for item in results[:3]]
            )
            or "none",
        )
        logger.info(
            "tavily.response.payload=%s",
            self._clip(self._to_json(response), PAYLOAD_LOG_LIMIT),
        )
        return {"query": topic, "results": results}

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}...(truncated)"

    @staticmethod
    def _to_json(payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(payload)
