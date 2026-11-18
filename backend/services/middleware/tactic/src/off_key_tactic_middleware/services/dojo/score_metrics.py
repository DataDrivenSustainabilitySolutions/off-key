"""Threshold-free metrics of a run's scores against its dataset's labels.

PR-AUC, AUROC and VUS-PR rank the scored results; the UCR top-1 hit asks
where the single highest score lies. Everything is aggregated in PostgreSQL:
results are grouped by score, so only one row per distinct score is summed,
and nothing per result leaves the database.

``reference`` computes the same numbers from Python lists. The tests hold
the SQL to it, and to scikit-learn where they overlap.
"""

import math
from collections.abc import Sequence
from datetime import datetime

from off_key_core.schemas.dojo import ScoreMetrics
from sqlalchemy import text

# Range-PR buffers in typical intervals: 0 is the labels as they are.
BUFFERS = tuple(range(0, 101, 10))
# The UCR archive counts a series as solved when the top score lies within
# 100 positions of its anomaly.
TOP1_TOLERANCE = 100


def soft_weight(distance: float, buffer: int) -> float:
    """A result's share of being labelled, ``distance`` intervals outside one.

    Inside a label it is 1. Within half the buffer on either side it fades
    with a square root, as range-AUC does (Paparrizos et al., VLDB 2022).
    """
    if distance <= 0:
        return 1.0
    half = buffer // 2
    if distance > half:
        return 0.0
    return math.sqrt(1 - distance / (half + 1))


def _average_precision(
    scores: Sequence[float], weights: Sequence[float]
) -> float | None:
    total = sum(weights)
    if total <= 0:
        return None
    groups: dict[float, list[float]] = {}
    for score, weight in zip(scores, weights, strict=True):
        groups.setdefault(score, []).append(weight)
    area = seen = hits = 0.0
    for score in sorted(groups, reverse=True):
        group = groups[score]
        seen += len(group)
        hits += sum(group)
        area += sum(group) / total * hits / seen
    return area


def reference(
    scores: Sequence[float], distances: Sequence[float]
) -> tuple[float | None, float | None, float | None]:
    """(pr_auc, auroc, vus_pr) of scores whose results lie ``distances``
    typical intervals outside the nearest label, 0 inside one."""
    labelled = [distance <= 0 for distance in distances]
    pr_auc = _average_precision(scores, [float(item) for item in labelled])
    positives = sum(labelled)
    negatives = len(labelled) - positives
    auroc = None
    if positives and negatives:
        groups: dict[float, list[int]] = {}
        for score, inside in zip(scores, labelled, strict=True):
            counts = groups.setdefault(score, [0, 0])
            counts[0 if inside else 1] += 1
        below = 0
        total = 0.0
        for score in sorted(groups):
            inside, outside = groups[score]
            total += inside * (below + outside / 2)
            below += outside
        auroc = total / (positives * negatives)
    ranges = [
        _average_precision(scores, [soft_weight(d, buffer) for d in distances])
        for buffer in BUFFERS
    ]
    vus_pr = (
        None
        if any(item is None for item in ranges)
        else (sum(item for item in ranges if item is not None) / len(ranges))
    )
    return pr_auc, auroc, vus_pr


def _weights_sql() -> str:
    columns = []
    for index, buffer in enumerate(BUFFERS):
        half = buffer // 2
        columns.append(
            f"CASE WHEN distance <= 0 THEN 1.0 "
            f"WHEN distance <= {half} THEN sqrt(1 - distance / {half + 1}.0) "
            f"ELSE 0.0 END AS w{index}"
        )
    return ",\n".join(columns)


def _statement() -> str:
    """One sort of every scored result by score; the rest only near labels.

    Each result learns how many score at least as high (``seen``) and how many
    tie with it. Only results within the widest buffer of a label carry a
    weight, so only those are grouped and summed: a result with no weight adds
    nothing to any average precision, and the AUROC needs the labelled ones.
    """
    weights = _weights_sql()
    widest = max(BUFFERS) // 2
    sums = ", ".join(f"sum(w{i}) AS w{i}" for i in range(len(BUFFERS)))
    running = ", ".join(
        f"sum(w{i}) OVER (ORDER BY score DESC) AS c{i}" for i in range(len(BUFFERS))
    )
    areas = ", ".join(
        f"sum(w{i} * c{i} / seen) / nullif(sum(w{i}), 0)" for i in range(len(BUFFERS))
    )
    return f"""
WITH bounds AS (
    SELECT CAST(:starts AS timestamptz[]) AS starts,
           CAST(:ends AS timestamptz[]) AS ends
), ranked AS (
    SELECT r.timestamp, r.score,
           count(*) OVER (ORDER BY r.score DESC) AS seen,
           count(*) OVER (ORDER BY r.score DESC
                          RANGE BETWEEN CURRENT ROW AND CURRENT ROW) AS ties
    FROM dojo_run_results r
    WHERE r.run_id = :run_id AND r.score IS NOT NULL
), bucketed AS (
    SELECT ranked.*, width_bucket(ranked.timestamp, bounds.starts) AS bucket,
           bounds.starts, bounds.ends
    FROM ranked, bounds
), placed AS (
    SELECT score, seen, ties,
           CASE
             WHEN bucket > 0 AND timestamp <= ends[bucket] THEN 0.0
             ELSE least(
               CASE WHEN bucket > 0
                 THEN extract(epoch FROM timestamp - ends[bucket]) END,
               CASE WHEN bucket < :label_count
                 THEN extract(epoch FROM starts[bucket + 1] - timestamp) END
             ) / :interval
           END AS distance
    FROM bucketed
), weighted AS (
    SELECT score, seen, ties, {weights}
    FROM placed WHERE distance <= {widest}
), grouped AS (
    SELECT score, max(seen) AS seen, max(ties) AS ties,
           sum(CASE WHEN w0 >= 1 THEN 1 ELSE 0 END) AS inside, {sums}
    FROM weighted GROUP BY score
), running AS (
    SELECT *, sum(inside) OVER (ORDER BY score ASC) - inside AS inside_below,
           {running}
    FROM grouped
)
SELECT sum(inside),
       sum(inside * ((:scored - seen) - inside_below + (ties - inside) / 2.0)),
       {areas}
FROM running
"""


STATEMENT = text(_statement())
SPAN = text(
    """
SELECT count(*), min(timestamp), max(timestamp) FROM dojo_run_results
WHERE run_id = :run_id AND score IS NOT NULL
"""
)
TOP = text(
    """
SELECT timestamp FROM dojo_run_results
WHERE run_id = :run_id AND score IS NOT NULL
ORDER BY score DESC, timestamp ASC LIMIT 1
"""
)


async def score_metrics(
    session, run_id: str, labels: Sequence[tuple[datetime, datetime]]
) -> ScoreMetrics | None:
    """``labels`` in time order, not overlapping."""
    results, scored_from, scored_to = (
        await session.execute(SPAN, {"run_id": run_id})
    ).one()
    if not results or scored_from is None or scored_to is None:
        return None
    # The typical interval between scored results turns times into
    # positions, as the archive counts them.
    span = (scored_to - scored_from).total_seconds()
    interval = max(span / max(results - 1, 1), 1e-6)
    row = (
        await session.execute(
            STATEMENT,
            {
                "run_id": run_id,
                "starts": [start for start, _ in labels],
                "ends": [end for _, end in labels],
                "label_count": len(labels),
                "interval": interval,
                "scored": results,
            },
        )
    ).one()
    inside, rank_sum, *areas = row
    scored, inside = int(results), int(inside or 0)
    outside = scored - inside
    auroc = float(rank_sum) / (inside * outside) if inside and outside else None
    ranges = [None if area is None else float(area) for area in areas]
    top_at = await session.scalar(TOP, {"run_id": run_id})
    top1 = None
    if len(labels) == 1 and top_at is not None:
        start, end = labels[0]
        tolerance = TOP1_TOLERANCE * interval
        top1 = (
            start.timestamp() - tolerance
            <= top_at.timestamp()
            <= end.timestamp() + tolerance
        )
    return ScoreMetrics(
        scored_results=scored,
        labelled_results=inside,
        pr_auc=ranges[0] if inside else None,
        auroc=auroc,
        vus_pr=(
            sum(item for item in ranges if item is not None) / len(ranges)
            if inside and all(item is not None for item in ranges)
            else None
        ),
        top_score_at=top_at,
        top1_hit=top1,
    )
