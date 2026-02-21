from dataclasses import dataclass


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
    """Phase 3 skeleton planner.

    This PR only defines the contract and minimal deterministic planning.
    Domain strategy and quality rules will be expanded in follow-up PRs.
    """

    def __init__(self, min_results: int = 2) -> None:
        self.min_results = min_results

    def plan(
        self,
        topic: str,
        result_count: int,
        primary_domains: list[str] | None = None,
        secondary_domains: list[str] | None = None,
    ) -> FallbackDecision:
        primary = primary_domains or []
        secondary = secondary_domains or []

        if result_count >= self.min_results:
            return FallbackDecision(
                triggered=False,
                reason="enough_results",
                queries=[topic],
                domains=[primary],
            )

        return FallbackDecision(
            triggered=True,
            reason="insufficient_results",
            queries=[topic, topic, topic],
            domains=[primary, secondary, []],
        )
