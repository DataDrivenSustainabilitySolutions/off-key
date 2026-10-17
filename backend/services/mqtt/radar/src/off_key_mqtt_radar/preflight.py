"""Credential-free, bounded constructor preflight in the target worker image.

``python -m off_key_mqtt_radar.preflight`` consumes RADAR_PIPELINE_CONFIG, or
``--config`` pointing to a JSON file, and writes one machine-readable report.
No broker client, database session, or service supervision is constructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

from aberrant import __version__ as aberrant_version
from off_key_core.config.resource_budget import DEFAULT_RADAR_MEMORY_MB
from off_key_core.models.adaptive import ABERRANT_VERSION
from off_key_core.models.pipelines import execution_fingerprint, pipeline_catalog_id
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config.config import AnomalyDetectionConfig
from .pipelines.adapters import adaptive_graph
from .pipelines.batch import BatchFeatureGraph
from .pipelines.plan import ExecutionPlan
from .pipelines.resources import estimate_resources


class PreflightSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_MEMORY_LIMIT_MB: int = Field(
        default=DEFAULT_RADAR_MEMORY_MB, ge=128, le=16384
    )


def preflight(execution: PipelineExecutionConfig, *, memory_limit_mb=None) -> dict:
    if aberrant_version != ABERRANT_VERSION:
        raise ValueError(
            "Target worker's Aberrant version differs from its generated catalog"
        )
    plan = ExecutionPlan(execution)
    if execution.fingerprint != execution_fingerprint(
        execution.definition, execution.bindings
    ):
        raise ValueError(
            "Bound executable fingerprint does not match its definition and bindings"
        )
    settings = (
        PreflightSettings()
        if memory_limit_mb is None
        else PreflightSettings(RADAR_MEMORY_LIMIT_MB=memory_limit_mb)
    )
    config = AnomalyDetectionConfig(
        pipeline=execution, memory_limit_mb=settings.RADAR_MEMORY_LIMIT_MB
    )
    resources = estimate_resources(plan, config.memory_limit_mb)
    readiness = []
    capabilities = None
    if execution.definition.strategy == "adaptive_stream":
        graph, detector = adaptive_graph(plan)
        capabilities = detector.capabilities().as_dict()
        readiness = [
            dict(
                node_id=item.node_id,
                ready=item.readiness.ready,
                observed=item.readiness.observed,
                required=item.readiness.required,
                reason=item.readiness.reason,
            )
            for item in graph.node_states
        ]
    else:
        from .pipelines.static import StaticPipelineDetectionService

        BatchFeatureGraph(plan)
        detector = StaticPipelineDetectionService(config, automatic_checkpoints=False)
        try:
            detector._create_pyod_detector()
        finally:
            detector.shutdown()
    return dict(
        ok=True,
        fingerprint=execution.fingerprint,
        catalog_id=pipeline_catalog_id(),
        runtime_versions={
            name: version(name)
            for name in ("numpy", "scipy", "scikit-learn", "pyod", "nonconform")
        }
        | {"aberrant": aberrant_version},
        definition_fingerprint=plan.compiled.fingerprint,
        feature_schemas={
            identifier: {
                "width": len(columns),
                "preview_names": [
                    item.name.encode()[:40].decode(errors="ignore")
                    for item in columns[:8]
                ],
                "preview_names_truncated": any(
                    len(item.name.encode()) > 40 for item in columns[:8]
                ),
                "fingerprint": hashlib.sha256(
                    json.dumps(
                        [item.model_dump(mode="json") for item in columns],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            for identifier, columns in plan.compiled.features.items()
        },
        readiness=readiness,
        capabilities=capabilities,
        resources=resources.model_dump(),
        fitting_validated=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        raw = (
            args.config.read_text(encoding="utf-8")
            if args.config
            else os.environ.get("RADAR_PIPELINE_CONFIG", "")
        )
        execution = PipelineExecutionConfig.model_validate_json(raw)
        report = preflight(execution)
    except Exception as error:
        print(json.dumps({"ok": False, "errors": [f"{type(error).__name__}: {error}"]}))
        sys.exit(1)
    print(json.dumps(report, allow_nan=False, ensure_ascii=False))


if __name__ == "__main__":
    main()
