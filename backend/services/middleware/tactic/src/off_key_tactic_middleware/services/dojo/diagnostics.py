"""What a finished run's scores and alarms say without labels.

Most monitored data has no labels, so a run must also be judged by itself.
Every figure here describes the run and assumes nothing about how its scores
are distributed: monitored series rarely stay stationary, and a check that
needs exchangeable scores would mislead on them. Ranks, counts and shares
stay honest when the level moves.

The whole run is counted in PostgreSQL; rank correlations read an even sample
of the scored results.
"""

from collections.abc import Sequence
from typing import Any

from off_key_core.schemas.dojo import RunDiagnostics, ScoreFollows
from sqlalchemy import text

from .score_metrics import Unusual

DAY_SECONDS = 86_400.0
# Scored results the rank correlations read, evenly spaced over the run.
SAMPLE = 4000
# A pause this many usual intervals long is a gap in the data, and an episode
# that begins within this many results after one began at the gap.
GAP_FACTOR = 5
AFTER_GAP = 5
# Where a figure becomes a finding.
LOW_SCORED_SHARE = 0.5
HIGH_ALARM_SHARE = 0.05
GAP_EPISODES = 3
GAP_EXCESS = 5
TREND = 0.5
FOLLOWS = 0.7
COMMONEST = 0.5

COUNTS = text(
    """
WITH ordered AS (
    SELECT sequence, timestamp, score, alarm,
           coalesce(lag(alarm) OVER w, false) AS alarm_before,
           extract(epoch FROM timestamp - lag(timestamp) OVER w) AS pause
    FROM dojo_run_results WHERE run_id = :run_id
    WINDOW w AS (ORDER BY sequence)
), usual AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY pause) AS pause
    FROM ordered WHERE pause > 0
), stretched AS (
    SELECT ordered.*,
           sum(CASE WHEN ordered.pause > :gap_factor * usual.pause THEN 1 ELSE 0 END)
             OVER (ORDER BY sequence) AS stretch
    FROM ordered, usual
), placed AS (
    SELECT stretched.*,
           row_number() OVER (PARTITION BY stretch ORDER BY sequence) AS since_gap,
           sum(CASE WHEN alarm AND NOT alarm_before THEN 1 ELSE 0 END)
             OVER (ORDER BY sequence) AS episode
    FROM stretched
), episodes AS (
    SELECT extract(epoch FROM max(timestamp) - min(timestamp)) AS seconds
    FROM placed WHERE alarm GROUP BY episode
)
SELECT count(*),
       count(score),
       min(timestamp),
       min(timestamp) FILTER (WHERE score IS NOT NULL),
       max(timestamp) FILTER (WHERE score IS NOT NULL),
       count(*) FILTER (WHERE alarm AND score IS NOT NULL),
       count(*) FILTER (WHERE alarm AND NOT alarm_before),
       count(*) FILTER (
           WHERE alarm AND NOT alarm_before AND stretch > 0
             AND since_gap <= :after_gap
       ),
       count(*) FILTER (
           WHERE score IS NOT NULL AND stretch > 0 AND since_gap <= :after_gap
       ),
       (SELECT max(seconds) FROM episodes)
FROM placed
"""
)
COMMONEST_SCORE = text(
    """
SELECT count(*) FROM dojo_run_results
WHERE run_id = :run_id AND score IS NOT NULL
GROUP BY score ORDER BY count(*) DESC LIMIT 1
"""
)
SAMPLED = text(
    """
SELECT timestamp, score FROM (
    SELECT timestamp, score, row_number() OVER (ORDER BY sequence) AS position
    FROM dojo_run_results WHERE run_id = :run_id AND score IS NOT NULL
) AS scored WHERE position % :every = 0 ORDER BY position
"""
)
# Each sampled result beside the series' value at or before its time, as the
# run saw it.
INPUT = text(
    """
SELECT (
    SELECT p.value FROM dojo_dataset_points p
    WHERE p.series_id = :series_id AND p.timestamp <= sampled.at
    ORDER BY p.timestamp DESC LIMIT 1
)
FROM unnest(CAST(:times AS timestamptz[])) WITH ORDINALITY AS sampled(at, position)
ORDER BY position
"""
)


def ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1, ties sharing the mean of their places."""
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for index in order[start : end + 1]:
            result[index] = (start + end) / 2 + 1
        start = end + 1
    return result


def rank_correlation(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Spearman's rho; None for fewer than three pairs or a constant side."""
    if len(first) < 3 or len(first) != len(second):
        return None
    a, b = ranks(first), ranks(second)
    mean = (len(a) + 1) / 2
    cross = sum((x - mean) * (y - mean) for x, y in zip(a, b, strict=True))
    spread_a = sum((x - mean) ** 2 for x in a)
    spread_b = sum((y - mean) ** 2 for y in b)
    if spread_a <= 0 or spread_b <= 0:
        return None
    return cross / (spread_a * spread_b) ** 0.5


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:.3g} h" if seconds >= 3600 else f"{seconds / 60:.3g} min"


def findings(diagnostics: RunDiagnostics) -> list[str]:
    """The figures far enough from the usual to act on, in words."""
    found = []
    share = diagnostics.scored_share
    if share is not None and share < LOW_SCORED_SHARE:
        found.append(
            f"Only {share:.0%} of the results have a score: the warm-up took "
            f"{_hours(diagnostics.warm_up_seconds or 0)}. Shorten the training "
            "and calibration windows, or test on a longer dataset."
        )
    alarms = diagnostics.alarm_share
    if alarms is not None and alarms > HIGH_ALARM_SHARE:
        found.append(
            f"{alarms:.0%} of the scored results alarm: the threshold lies "
            "among ordinary values. Raise it, ask for several in a row, or "
            "calibrate to a lower alarm rate."
        )
    episodes, after = diagnostics.alarm_episodes, diagnostics.episodes_after_gaps
    chance = diagnostics.after_gap_share or 0.0
    if after >= GAP_EPISODES and after / episodes >= max(0.5, GAP_EXCESS * chance):
        found.append(
            f"{after} of {episodes} alarms began right after a gap in the data, "
            f"where by chance {chance:.0%} would: the detector reacts to the "
            "gap. Hold or fill values over gaps, or restart learning after one."
        )
    trend = diagnostics.score_trend
    if trend is not None and abs(trend) >= TREND:
        later = "end" if trend > 0 else "start"
        found.append(
            f"The scores grow {'more' if trend > 0 else 'less'} unusual over the "
            f"run (rank correlation with time {trend:.2f}), so alarms gather at "
            f"the {later}: the detector or its calibration does not keep up "
            "with a level that moves. Take time out before the detector, or "
            "calibrate on a rolling window."
        )
    for item in diagnostics.follows:
        if abs(item.correlation) >= FOLLOWS:
            side = "high" if item.correlation > 0 else "low"
            found.append(
                f"The scores rank with the value of {item.series} "
                f"({item.correlation:.2f}): the detector scores how {side} it "
                "is rather than what is unusual. Unless that is what you watch "
                "for, take the level out first with Change, Deseason or a "
                "forecaster."
            )
    common = diagnostics.commonest_score_share
    if common is not None and common >= COMMONEST:
        found.append(
            f"{common:.0%} of the scores are one and the same value, so the "
            "scores cannot rank most results against each other. Expected of "
            "a rule; for a detector, its input may hold too little that varies."
        )
    return found


async def run_diagnostics(
    session,
    run_id: str,
    series: Sequence[dict[str, Any]],
    *,
    unusual: Unusual = "high",
) -> RunDiagnostics:
    """``series`` are the run's inputs as its config keeps them: id and name."""
    (
        results,
        scored,
        first,
        scored_from,
        scored_to,
        alarmed,
        episodes,
        after_gaps,
        near_gaps,
        longest,
    ) = (
        await session.execute(
            COUNTS,
            {"run_id": run_id, "gap_factor": GAP_FACTOR, "after_gap": AFTER_GAP},
        )
    ).one()
    span = (
        (scored_to - scored_from).total_seconds()
        if scored_from is not None and scored_to is not None
        else 0.0
    )
    diagnostics = RunDiagnostics(
        results=results,
        scored_share=round(scored / results, 3) if results else None,
        warm_up_seconds=(scored_from - first).total_seconds()
        if scored_from is not None
        else None,
        alarm_share=round(alarmed / scored, 4) if scored else None,
        alarm_episodes=episodes,
        episodes_per_day=round(episodes * DAY_SECONDS / span, 3) if span > 0 else None,
        longest_episode_seconds=None if longest is None else float(longest),
        episodes_after_gaps=after_gaps,
        after_gap_share=round(near_gaps / scored, 4) if scored else None,
    )
    if not scored:
        return diagnostics
    commonest = await session.scalar(COMMONEST_SCORE, {"run_id": run_id})
    diagnostics.commonest_score_share = round((commonest or 0) / scored, 3)
    rows = (
        await session.execute(
            SAMPLED, {"run_id": run_id, "every": max(scored // SAMPLE, 1)}
        )
    ).all()
    sign = 1.0 if unusual == "high" else -1.0
    times = [at for at, _ in rows]
    scores = [sign * score for _, score in rows]
    trend = rank_correlation([at.timestamp() for at in times], scores)
    diagnostics.score_trend = None if trend is None else round(trend, 3)
    for item in series:
        values = (
            await session.scalars(INPUT, {"series_id": item["id"], "times": times})
        ).all()
        paired = [
            (value, score)
            for value, score in zip(values, scores, strict=True)
            if value is not None
        ]
        follows = rank_correlation(
            [value for value, _ in paired], [score for _, score in paired]
        )
        if follows is not None:
            diagnostics.follows.append(
                ScoreFollows(series=item["name"], correlation=round(follows, 3))
            )
    diagnostics.follows.sort(key=lambda item: -abs(item.correlation))
    diagnostics.findings = findings(diagnostics)
    return diagnostics
