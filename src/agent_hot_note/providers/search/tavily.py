import logging
import json
from typing import Any

import httpx

from agent_hot_note.config import Settings

logger = logging.getLogger(__name__)
PAYLOAD_LOG_LIMIT = 4000


class TavilySearch:
    """Tavily search provider with compact input/output logs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.search_depth = settings.tavily_search_depth
        self.max_results = settings.tavily_max_results
        self.search_url = "https://api.tavily.com/search"
        self.extract_url = "https://api.tavily.com/extract"

    async def search(self, topic: str, include_domains: list[str] | None = None) -> dict[str, Any]:
        request_payload = {
            "query": topic,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
        }
        if include_domains:
            request_payload["include_domains"] = include_domains
        logger.info(
            "tavily.request query=%s depth=%s max_results=%d include_domains=%s",
            self._clip(topic, 80),
            self.search_depth,
            self.max_results,
            include_domains or [],
        )
        logger.info(
            "tavily.request.payload=%s",
            self._clip(self._to_json(request_payload), PAYLOAD_LOG_LIMIT),
        )

        request_body = {
            "api_key": self.settings.tavily_api_key,
            "query": topic,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
        }
        if include_domains:
            request_body["include_domains"] = include_domains
        async with httpx.AsyncClient(timeout=30.0) as client:
            http_response = await client.post(self.search_url, json=request_body)
            http_response.raise_for_status()
            response = http_response.json()
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

    async def extract(self, urls: list[str]) -> dict[str, Any]:
        request_payload = {"urls": urls}
        logger.info("tavily.extract.request count=%d", len(urls))
        logger.info(
            "tavily.extract.request.payload=%s",
            self._clip(self._to_json(request_payload), PAYLOAD_LOG_LIMIT),
        )

        request_body = {
            "api_key": self.settings.tavily_api_key,
            "urls": urls,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            http_response = await client.post(self.extract_url, json=request_body)
            http_response.raise_for_status()
            response = http_response.json()

        results = response.get("results", [])
        contents: dict[str, str] = {}
        failed_urls: list[str] = []
        for item in results:
            url = str(item.get("url", "")).strip()
            raw = str(item.get("raw_content", "") or item.get("content", "")).strip()
            if url and raw:
                contents[url] = raw
            elif url:
                failed_urls.append(url)
        unresolved = [url for url in urls if url not in contents and url not in failed_urls]
        if unresolved:
            failed_urls.extend(unresolved)
        logger.info(
            "tavily.extract.response success=%d failed=%d",
            len(contents),
            len(failed_urls),
        )
        logger.info(
            "tavily.extract.response.payload=%s",
            self._clip(self._to_json(response), PAYLOAD_LOG_LIMIT),
        )
        return {"contents": contents, "failed_urls": failed_urls}

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
