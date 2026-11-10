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
from aberrant.base import ConfigurationError
from off_key_core.config.resource_budget import DEFAULT_RADAR_MEMORY_MB
from off_key_core.models.adaptive import ABERRANT_VERSION
from off_key_core.models.pipelines import pipeline_catalog_id
from off_key_core.schemas.pipelines import PipelineExecutionConfig, PipelineIssue
from off_key_core.utils.json_budget import bounded_utf8_text
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .boundary import ScoreBoundary, adapts
from .config.config import AnomalyDetectionConfig
from .mixed_detector import learning_ids, streaming_ids
from .pipelines.adapters import adaptive_graph, resolved_detector_config
from .pipelines.batch import BatchFeatureGraph
from .pipelines.plan import ExecutionPlan
from .pipelines.prepare import PrepareStage
from .pipelines.pyod import node_detector
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
    # ExecutionPlan rejects a fingerprint that differs from the design.
    plan = ExecutionPlan(execution)
    settings = (
        PreflightSettings()
        if memory_limit_mb is None
        else PreflightSettings(RADAR_MEMORY_LIMIT_MB=memory_limit_mb)
    )
    config = AnomalyDetectionConfig(
        pipeline=execution, memory_limit_mb=settings.RADAR_MEMORY_LIMIT_MB
    )
    resources = estimate_resources(plan, config.memory_limit_mb)
    if plan.stage is not None:
        PrepareStage(plan)
    readiness, capabilities = _build_detectors(plan, config)
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


def _build_detectors(
    plan: ExecutionPlan, config: AnomalyDetectionConfig
) -> tuple[list[dict], dict | None]:
    """Build every detector and the calibration step as the run will."""
    boundary = adapts(plan)
    if boundary:
        ScoreBoundary(plan)
    online, fitted_once = streaming_ids(plan), learning_ids(plan, "batch")
    if not online and not boundary:
        return _static_preflight(plan, config)
    readiness, capabilities = [], None
    if online:
        # Detectors that learn in different ways: build each as its run will.
        readiness, capabilities = _adaptive_preflight(
            plan, online if fitted_once else None
        )
    if fitted_once:
        BatchFeatureGraph(plan, fitted_once)
        seed = plan.compiled.definition.settings.seed
        for identifier in fitted_once:
            with _detector(identifier):
                node_detector(plan.nodes[identifier], seed)
    return readiness, capabilities


def _static_preflight(
    plan: ExecutionPlan, config: AnomalyDetectionConfig
) -> tuple[list[dict], dict | None]:
    from .detector import StaticConformalDetectionService

    BatchFeatureGraph(plan)
    detector = StaticConformalDetectionService(config)
    try:
        if plan.fused:
            for identifier in plan.detector_ids:
                with _detector(identifier):
                    detector._create_pyod_detector(plan.nodes[identifier])
        else:
            detector._create_pyod_detector()
    finally:
        detector.shutdown()
    return [], None


class DetectorConfigurationError(Exception):
    """A detector's configuration failed; carries which detector it was."""

    def __init__(self, node_id: str, error: ConfigurationError):
        super().__init__(str(error))
        self.node_id = node_id
        self.error = error


class _detector:
    """Name the detector whose constructor raised a configuration error."""

    def __init__(self, node_id: str):
        self.node_id = node_id

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if isinstance(error, ConfigurationError):
            raise DetectorConfigurationError(self.node_id, error) from error
        return False


def _adaptive_preflight(
    plan: ExecutionPlan, detector_ids: list[str] | None = None
) -> tuple[list[dict], dict | None]:
    """Build every detector's graph, as the run will; report steps once each."""
    readiness: dict[str, dict] = {}
    capabilities = {}
    for identifier in plan.detector_ids if detector_ids is None else detector_ids:
        with _detector(identifier):
            config = resolved_detector_config(plan, identifier)
            graph, _ = adaptive_graph(plan, config=config, detector_id=identifier)
        capabilities[identifier] = config.capabilities.as_dict()
        for item in graph.node_states:
            readiness.setdefault(
                item.node_id,
                dict(
                    node_id=item.node_id,
                    ready=item.readiness.ready,
                    observed=item.readiness.observed,
                    required=item.readiness.required,
                    reason=item.readiness.reason,
                ),
            )
    # One detector reports its capabilities as before; several by detector.
    return list(readiness.values()), (
        capabilities if plan.fused else capabilities[plan.detector_id]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    execution = None
    try:
        raw = (
            args.config.read_text(encoding="utf-8")
            if args.config
            else os.environ.get("RADAR_PIPELINE_CONFIG", "")
        )
        execution = PipelineExecutionConfig.model_validate_json(raw)
        report = preflight(execution)
    except Exception as error:
        issues = []
        node_id = None
        if isinstance(error, DetectorConfigurationError):
            node_id, error = error.node_id, error.error
        if isinstance(error, ConfigurationError) and execution is not None:
            node_id = node_id or min(
                node.id
                for node in execution.definition.nodes
                if node.kind == "detector"
            )
            for issue in error.issues[:64]:
                path = (
                    list(issue.loc[2:])
                    if issue.loc[:2] == ("model", "params")
                    else None
                )
                issues.append(
                    PipelineIssue(
                        code=issue.code,
                        message=bounded_utf8_text(issue.message, 1024),
                        node_id=node_id,
                        parameter_path=path,
                    ).model_dump(mode="json")
                )
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [
                        bounded_utf8_text(f"{type(error).__name__}: {error}", 4000)
                    ],
                    "issues": issues,
                }
            )
        )
        sys.exit(1)
    print(json.dumps(report, allow_nan=False, ensure_ascii=False))


if __name__ == "__main__":
    main()
