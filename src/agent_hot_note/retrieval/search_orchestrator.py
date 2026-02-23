import logging
from typing import Any
from urllib.parse import urlparse

from agent_hot_note.config import Settings
from agent_hot_note.retrieval.fallback import FallbackDecision, FallbackPlanner
from agent_hot_note.providers.search.tavily import TavilySearch

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    """Coordinates Tavily search fallback and optional extract enrichment."""

    def __init__(
        self,
        settings: Settings,
        search_provider: TavilySearch | None = None,
        fallback_planner: FallbackPlanner | None = None,
    ) -> None:
        self.settings = settings
        self.search_provider = search_provider or TavilySearch(settings)
        self.primary_domains = self._parse_domains(settings.fallback_primary_domains)
        self.secondary_domains = self._parse_domains(settings.fallback_secondary_domains)
        self.extract_allowed_domains = self._parse_domains(settings.tavily_extract_allowed_domains)
        self.fallback_planner = fallback_planner or FallbackPlanner(
            min_results=settings.fallback_min_results,
            min_avg_summary_chars=settings.fallback_min_avg_summary_chars,
            max_title_dup_ratio=settings.fallback_max_title_dup_ratio,
        )

    async def search_with_fallback(self, topic: str) -> tuple[dict[str, Any], FallbackDecision]:
        default_profile = self.settings.topic_default_profile
        return await self.search_with_profile(topic, profile_id=default_profile)

    async def search_with_profile(self, topic: str, profile_id: str | None = None) -> tuple[dict[str, Any], FallbackDecision]:
        resolved_profile, primary_domains, secondary_domains, extract_allowed_domains = self._resolve_profile_domains(
            profile_id
        )

        primary_result = await self.search_provider.search(topic, include_domains=primary_domains or None)
        primary_count = len(primary_result.get("results", []))
        primary_decision = self.fallback_planner.plan(
            topic=topic,
            results=primary_result.get("results", []),
            primary_domains=primary_domains,
            secondary_domains=secondary_domains,
        )
        logger.info(
            "fallback.evaluate step=primary profile=%s results=%d reason=%s domains=%s",
            resolved_profile,
            primary_count,
            primary_decision.reason,
            primary_domains,
        )
        if not primary_decision.triggered:
            logger.info("fallback.not_triggered reason=%s", primary_decision.reason)
            enriched = await self._enrich_results_with_extract(primary_result, extract_allowed_domains)
            enriched["profile_id"] = resolved_profile
            return enriched, primary_decision

        logger.info("fallback.triggered reason=%s", primary_decision.reason)
        attempted_queries: list[str] = [topic]
        attempted_domains: list[list[str]] = [primary_domains]
        result_batches: list[list[dict[str, Any]]] = [primary_result.get("results", [])]

        followup_domain_steps: list[list[str]] = []
        if secondary_domains:
            followup_domain_steps.append(secondary_domains)
        followup_domain_steps.append([])

        merged_results = self._merge_results(result_batches, max_items=self.settings.tavily_max_results)
        for domains in followup_domain_steps:
            logger.info("fallback.attempt domains=%s", domains)
            followup_result = await self.search_provider.search(topic, include_domains=domains or None)
            attempted_queries.append(topic)
            attempted_domains.append(domains)
            result_batches.append(followup_result.get("results", []))
            merged_results = self._merge_results(result_batches, max_items=self.settings.tavily_max_results)
            merged_decision = self.fallback_planner.plan(
                topic=topic,
                results=merged_results,
                primary_domains=primary_domains,
                secondary_domains=secondary_domains,
            )
            logger.info(
                "fallback.evaluate step=followup merged_results=%d reason=%s domains=%s",
                len(merged_results),
                merged_decision.reason,
                domains,
            )
            if not merged_decision.triggered:
                logger.info("fallback.resolved step_domains=%s", domains)
                break

        merged_result = {"query": topic, "results": merged_results}
        final_decision = FallbackDecision(
            triggered=True,
            reason=primary_decision.reason,
            queries=attempted_queries,
            domains=attempted_domains,
        )
        enriched = await self._enrich_results_with_extract(merged_result, extract_allowed_domains)
        enriched["profile_id"] = resolved_profile
        return enriched, final_decision

    async def _enrich_results_with_extract(
        self,
        search_results: dict[str, Any],
        extract_allowed_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        enriched = dict(search_results)
        results = list(enriched.get("results", []))
        effective_extract_allowed = extract_allowed_domains or self.extract_allowed_domains
        if not self.settings.tavily_extract_enabled:
            logger.info("extract.skipped reason=disabled")
            enriched["extracted_urls"] = []
            enriched["extract_failed_urls"] = []
            return enriched

        candidate_urls = self._select_extract_urls(results, effective_extract_allowed)
        logger.info(
            "extract.candidates total_results=%d candidate_urls=%d allowed_domains=%s",
            len(results),
            len(candidate_urls),
            effective_extract_allowed,
        )
        if not candidate_urls:
            logger.info("extract.skipped reason=no_candidates")
            enriched["extracted_urls"] = []
            enriched["extract_failed_urls"] = []
            return enriched

        try:
            extract_result = await self.search_provider.extract(candidate_urls)
            contents: dict[str, str] = extract_result.get("contents", {})
            failed_urls = extract_result.get("failed_urls", [])
            enriched["results"] = self._apply_extracted_content(results, contents)
            enriched["extracted_urls"] = list(contents.keys())
            enriched["extract_failed_urls"] = failed_urls
            logger.info(
                "extract.applied success=%d failed=%d",
                len(enriched["extracted_urls"]),
                len(failed_urls),
            )
            return enriched
        except Exception as exc:
            logger.warning("extract.failed type=%s detail=%s", exc.__class__.__name__, str(exc))
            enriched["extracted_urls"] = []
            enriched["extract_failed_urls"] = candidate_urls
            return enriched

    @staticmethod
    def _parse_domains(raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def _merge_results(result_batches: list[list[dict[str, Any]]], max_items: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for batch in result_batches:
            for item in batch:
                key = str(item.get("url") or item.get("title") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= max_items:
                    return merged
        return merged

    def _select_extract_urls(self, results: list[dict[str, Any]], extract_allowed_domains: list[str] | None = None) -> list[str]:
        allowed = set(extract_allowed_domains or self.extract_allowed_domains)
        urls: list[str] = []
        for item in results:
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if allowed and host not in allowed:
                continue
            if url in urls:
                continue
            urls.append(url)
            if len(urls) >= self.settings.tavily_extract_max_urls:
                break
        return urls

    def _resolve_profile_domains(self, profile_id: str | None) -> tuple[str, list[str], list[str], list[str]]:
        requested = (profile_id or self.settings.topic_default_profile).strip().lower()
        default_profile = self.settings.topic_default_profile
        profiles = self.settings.topic_domain_profiles
        profile = profiles.get(requested) or profiles.get(default_profile)
        if profile is None:
            return default_profile, self.primary_domains, self.secondary_domains, self.extract_allowed_domains
        return requested if requested in profiles else default_profile, profile.primary, profile.secondary, profile.extract_allowed

    @staticmethod
    def _apply_extracted_content(results: list[dict[str, Any]], contents: dict[str, str]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for item in results:
            row = dict(item)
            url = str(row.get("url", "")).strip()
            extracted = contents.get(url)
            if extracted:
                row["content"] = extracted
            enriched.append(row)
        return enriched
