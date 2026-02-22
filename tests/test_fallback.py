from agent_hot_note.pipeline.fallback import FallbackDecision, FallbackPlanner


def _results(
    titles: list[str],
    content: str = "这是一段足够长的摘要内容，用于质量判定和回退策略测试，长度超过默认阈值。",
) -> list[dict]:
    return [{"title": title, "content": content} for title in titles]


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
        results=_results(["A", "B"]),
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


def test_fallback_triggered_by_short_summary() -> None:
    planner = FallbackPlanner(min_results=2, min_avg_summary_chars=20)

    decision = planner.plan(
        topic="春节减肥",
        results=[{"title": "A", "content": "太短"}, {"title": "B", "content": "也短"}],
        primary_domains=["xiaohongshu.com"],
        secondary_domains=["zhihu.com", "bilibili.com"],
    )

    assert decision.triggered is True
    assert decision.reason == "summary_too_short"
    assert decision.domains == [["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []]


def test_fallback_triggered_by_title_duplication() -> None:
    planner = FallbackPlanner(min_results=2, max_title_dup_ratio=0.4)

    decision = planner.plan(
        topic="春节减肥",
        results=_results(["同一个标题", "同一个标题", "同一个标题", "不同标题"]),
        primary_domains=["xiaohongshu.com"],
        secondary_domains=["zhihu.com", "bilibili.com"],
    )

    assert decision.triggered is True
    assert decision.reason == "title_duplication_high"
    assert decision.queries == ["春节减肥", "春节减肥", "春节减肥"]
