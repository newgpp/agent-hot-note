from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FallbackDecision:
    """Fallback output contract for Phase 3.

    Fields are kept intentionally small and stable so later PRs can extend
    fallback behavior without changing response shape.
    """

    triggered: bool
    reason: str
    queries: list[str]
    domains: list[list[str]]

    def as_meta(self) -> dict:
        return {
            "fallback_triggered": self.triggered,
            "fallback_reason": self.reason,
            "fallback_queries": self.queries,
            "fallback_domains": self.domains,
        }


class FallbackPlanner:
    """Phase 3 PR-2: domain-pool strategy + quality rules."""

    def __init__(
        self,
        min_results: int = 2,
        min_avg_summary_chars: int = 30,
        max_title_dup_ratio: float = 0.5,
    ) -> None:
        self.min_results = min_results
        self.min_avg_summary_chars = min_avg_summary_chars
        self.max_title_dup_ratio = max_title_dup_ratio

    def plan(
        self,
        topic: str,
        result_count: int | None = None,
        results: list[dict[str, Any]] | None = None,
        primary_domains: list[str] | None = None,
        secondary_domains: list[str] | None = None,
    ) -> FallbackDecision:
        primary = primary_domains or []
        secondary = secondary_domains or []
        effective_count = result_count if result_count is not None else len(results or [])
        reason = self._quality_reason(result_count=effective_count, results=results or [])

        if reason == "enough_results":
            return FallbackDecision(
                triggered=False,
                reason=reason,
                queries=[topic],
                domains=[primary],
            )

        return FallbackDecision(
            triggered=True,
            reason=reason,
            queries=[topic, topic, topic],
            domains=[primary, secondary, []],
        )

    def _quality_reason(self, result_count: int, results: list[dict[str, Any]]) -> str:
        if result_count < self.min_results:
            return "insufficient_results"

        if self._is_summary_too_short(results):
            return "summary_too_short"

        if self._is_title_duplication_high(results):
            return "title_duplication_high"

        return "enough_results"

    def _is_summary_too_short(self, results: list[dict[str, Any]]) -> bool:
        if not results:
            return True
        snippets = [str(item.get("content", "")).strip() for item in results]
        avg_chars = sum(len(text) for text in snippets) / max(len(snippets), 1)
        return avg_chars < self.min_avg_summary_chars

    def _is_title_duplication_high(self, results: list[dict[str, Any]]) -> bool:
        if not results:
            return True
        normalized_titles = [
            " ".join(str(item.get("title", "")).lower().split()).strip()
            for item in results
            if str(item.get("title", "")).strip()
        ]
        if not normalized_titles:
            return True
        unique_count = len(set(normalized_titles))
        duplication_ratio = 1 - (unique_count / len(normalized_titles))
        return duplication_ratio > self.max_title_dup_ratio
