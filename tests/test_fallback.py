from agent_hot_note.pipeline.fallback import FallbackDecision, FallbackPlanner


def test_fallback_decision_as_meta_shape() -> None:
    decision = FallbackDecision(
        triggered=True,
        reason="insufficient_results",
        queries=["q1", "q2"],
        domains=[["a.com"], ["b.com"]],
    )

    meta = decision.as_meta()
    assert meta["fallback_triggered"] is True
    assert meta["fallback_reason"] == "insufficient_results"
    assert meta["fallback_queries"] == ["q1", "q2"]
    assert meta["fallback_domains"] == [["a.com"], ["b.com"]]


def test_fallback_planner_not_triggered() -> None:
    planner = FallbackPlanner(min_results=2)

    decision = planner.plan(
        topic="春节减肥",
        result_count=2,
        primary_domains=["xiaohongshu.com"],
        secondary_domains=["zhihu.com", "bilibili.com"],
    )

    assert decision.triggered is False
    assert decision.reason == "enough_results"
    assert decision.queries == ["春节减肥"]
    assert decision.domains == [["xiaohongshu.com"]]


def test_fallback_planner_triggered_with_three_steps() -> None:
    planner = FallbackPlanner(min_results=2)

    decision = planner.plan(
        topic="春节减肥",
        result_count=1,
        primary_domains=["xiaohongshu.com"],
        secondary_domains=["zhihu.com", "bilibili.com"],
    )

    assert decision.triggered is True
    assert decision.reason == "insufficient_results"
    assert decision.queries == ["春节减肥", "春节减肥", "春节减肥"]
    assert decision.domains == [["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []]
