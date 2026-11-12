"""A detector that follows a rule: the value of one feature is its score.

Nothing is learned. A step before the detector computes the feature, such as a
flag that is 1 where a limit is crossed, or how far a reading is from what it
should be. The calibration step and the alarm policy read the score as they
read a learned detector's, so a rule alarms, is recorded and is reviewed like
any other detector.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aberrant.base import BaseModel
from aberrant.base.protocols import FeatureMap
from aberrant.catalog import (
    ComponentConfig,
    DetectorConfig,
    EventKind,
    FeatureCount,
    FeatureSchemaKind,
    ModelCapabilities,
    ScoreKind,
    StateKind,
    WarmupRequirement,
    WarmupUnit,
)


class FeatureScore(BaseModel):
    """Scores an observation with the value of the feature named ``key``."""

    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("key must name the feature whose value is the score")
        super().__init__()
        self.key = key

    def learn_one(self, x: FeatureMap) -> None:
        """Nothing to learn: the score depends on the observation alone."""

    def score_one(self, x: FeatureMap) -> float:
        return float(x[self.key])

    def __repr__(self) -> str:
        return f"FeatureScore(key={self.key!r})"


@dataclass(frozen=True)
class ResolvedRuleDetector:
    """What RADAR reads of a resolved detector, for a rule detector."""

    config: DetectorConfig
    capabilities: ModelCapabilities
    fingerprint: str

    def build(self) -> FeatureScore:
        return FeatureScore(self.config.model.params["key"])


def resolve_rule_detector(model: Mapping[str, Any]) -> ResolvedRuleDetector:
    """Resolve a rule detector step, given the feature it reads as ``key``."""
    config = DetectorConfig(model=ComponentConfig(model["id"], model["params"]))
    capabilities = ModelCapabilities(
        event_kind=EventKind.UNIVARIATE,
        feature_count=FeatureCount(1, 1),
        feature_schema=FeatureSchemaKind.FIXED,
        # A feature can be negative; only its order matters to calibration.
        score_kind=ScoreKind.SIGNED,
        higher_is_more_anomalous=True,
        warmup=WarmupRequirement(0, WarmupUnit.EVENTS),
        state=StateKind.STATELESS,
        resettable=True,
        requires_unit_interval=False,
    )
    serialized = json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":"))
    resolved = ResolvedRuleDetector(
        config, capabilities, hashlib.sha256(serialized.encode()).hexdigest()
    )
    # A step without a feature to read fails here, before a run subscribes.
    resolved.build()
    return resolved
