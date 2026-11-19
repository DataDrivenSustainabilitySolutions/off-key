"""What a finished run's scores and alarms say without labels."""

import random

import pytest
from off_key_core.schemas.dojo import RunDiagnostics, ScoreFollows
from off_key_tactic_middleware.services.dojo.diagnostics import (
    findings,
    rank_correlation,
    ranks,
)


def test_ranks_share_ties_and_rank_correlation_ignores_scale():
    assert ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]
    values = [float(index) for index in range(50)]
    assert rank_correlation(values, [value**3 for value in values]) == pytest.approx(1)
    assert rank_correlation(values, [-value for value in values]) == pytest.approx(-1)
    assert rank_correlation(values, [1.0] * 50) is None
    assert rank_correlation([1.0, 2.0], [1.0, 2.0]) is None
    noise = random.Random(1)
    unrelated = [noise.random() for _ in range(2000)]
    assert abs(rank_correlation(unrelated, [noise.random() for _ in unrelated])) < 0.1


def calm(**changes) -> RunDiagnostics:
    usual = {
        "results": 1000,
        "scored_share": 0.9,
        "warm_up_seconds": 600,
        "alarm_share": 0.01,
        "alarm_episodes": 4,
        "episodes_after_gaps": 0,
        "after_gap_share": 0.02,
        "score_trend": 0.1,
        "commonest_score_share": 0.01,
    }
    return RunDiagnostics.model_validate(usual | changes)


def test_a_calm_run_has_no_findings_and_each_outlier_has_one():
    assert findings(calm()) == []
    assert (
        "warm-up took 2 h" in findings(calm(scored_share=0.3, warm_up_seconds=7200))[0]
    )
    assert "threshold" in findings(calm(alarm_share=0.2))[0]
    [gaps] = findings(calm(alarm_episodes=4, episodes_after_gaps=3))
    assert gaps.startswith("3 of 4 alarms began right after a gap")
    # As many after gaps as chance would put there is no finding.
    assert (
        findings(calm(alarm_episodes=10, episodes_after_gaps=3, after_gap_share=0.3))
        == []
    )
    assert "gather at the end" in findings(calm(score_trend=0.8))[0]
    assert "gather at the start" in findings(calm(score_trend=-0.8))[0]
    follows = [
        ScoreFollows(series="speed", correlation=-0.9),
        ScoreFollows(series="load", correlation=0.3),
    ]
    [level] = findings(calm(follows=follows))
    assert "value of speed (-0.90)" in level and "how low it is" in level
    assert "one and the same" in findings(calm(commonest_score_share=0.8))[0]
    assert "flaps" in findings(calm(quick_returns=0.75))[0]
    # Few alarms that come back quickly are not yet a pattern.
    assert findings(calm(alarm_episodes=3, quick_returns=1.0)) == []
