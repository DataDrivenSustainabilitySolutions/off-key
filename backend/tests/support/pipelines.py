"""Small executable pipelines for tests that need a real bound execution."""

import math
import pickle
from itertools import pairwise

from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    pipeline_catalog,
)
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineExecutionConfig
from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService


def minimal_static_execution(topic="telemetry/entity/a"):
    """Bind one reading to source, Isolation Forest, martingale and evidence."""
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            dict(
                strategy="static_baseline",
                input_slots=[dict(id="a", label="Power")],
                nodes=[
                    dict(id="input", kind="source", component="source.aligned"),
                    dict(
                        id="model",
                        kind="detector",
                        component="detector:pyod_iforest",
                        params={"n_estimators": 10},
                    ),
                    dict(id="policy", kind="policy", component="policy.martingale"),
                    dict(id="output", kind="output", component="output.evidence"),
                ],
                edges=[
                    dict(source="input", target="model"),
                    dict(source="model", target="policy"),
                    dict(source="policy", target="output"),
                ],
                settings=dict(training_window_size=20, calibration_window_size=5),
            )
        )
    ).definition
    bindings = [
        dict(
            slot_id="a",
            reading_id="r-a",
            entity_id="entity",
            accepted_topic=topic,
            input_key=derive_monitoring_sensor_keys(
                [topic], sensor_key_strategy="full_hierarchy"
            )[0],
        )
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id="revision",
        run_id="run",
    )


def bundled(strategy="adaptive_stream"):
    """A copy of the bundled template for a strategy, as an editor opens it."""
    return next(
        item.definition.model_copy(deep=True)
        for item in pipeline_catalog().templates
        if item.id == strategy
    )


def template(strategy="adaptive_stream"):
    """The bundled template without its example steps: source to output.

    The stream's template carries a Lags step as an example. Tests build on
    the bare chain, source, detector, policy and output, and add what they test.
    """
    definition = bundled(strategy)
    steps = {node.id for node in definition.nodes if node.kind == "transform"}
    if not steps:
        return definition
    data = definition.model_dump(mode="json")
    data["nodes"] = [node for node in data["nodes"] if node["id"] not in steps]
    # The source's wire goes straight to the detector, where it was before.
    data["edges"] = [
        {"source": "input", "target": "detector"} if edge["source"] == "input" else edge
        for edge in data["edges"]
        if edge["source"] not in steps
    ]
    return compile_pipeline(PipelineDefinition.model_validate(data)).definition


def branched(strategy="adaptive_stream"):
    """Select, scale and project two readings; keep the third raw; merge."""
    definition = template(strategy)
    family = "adaptive" if strategy == "adaptive_stream" else "static"
    projection = "uncentered_pca" if family == "adaptive" else "pca"
    data = definition.model_dump(mode="json")
    data["input_slots"] = [
        {"id": "voltage", "label": "Voltage"},
        {"id": "current", "label": "Current"},
        {"id": "temperature", "label": "Temperature"},
    ]
    data["nodes"].extend(
        [
            {
                "id": "scaled_inputs",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["voltage", "current"]},
            },
            {
                "id": "scaler",
                "kind": "transform",
                "component": f"{family}.standard_scaler",
            },
            {
                "id": "projection",
                "kind": "transform",
                "component": f"{family}.{projection}",
                "params": {"n_components": 1},
            },
            {
                "id": "raw",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["temperature"]},
            },
            {"id": "merge", "kind": "merge", "component": "features.merge"},
        ]
    )
    data["edges"] = [edge for edge in data["edges"] if edge["target"] != "detector"] + [
        {"source": "input", "target": "scaled_inputs"},
        {"source": "scaled_inputs", "target": "scaler"},
        {"source": "scaler", "target": "projection"},
        {"source": "input", "target": "raw"},
        {"source": "projection", "target": "merge", "order": 0},
        {"source": "raw", "target": "merge", "order": 1},
        {"source": "merge", "target": "detector"},
    ]
    return PipelineDefinition.model_validate(data)


def quick(strategy="adaptive_stream"):
    """``branched`` with learning windows a test can fill in a few hundred steps."""
    data = branched(strategy).model_dump(mode="json")
    data["settings"].update(training_window_size=60, calibration_window_size=40)
    return PipelineDefinition.model_validate(data)


def chained(strategy="adaptive_stream", steps=(), slots=("a", "b")):
    """A design whose steps run one after another between the input and a small
    detector; each step is (id, component, params)."""
    data = template(strategy).model_dump(mode="json")
    data["input_slots"] = [{"id": key, "label": key.upper()} for key in slots]
    data["settings"].update(training_window_size=20, calibration_window_size=5)
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    if strategy == "adaptive_stream":
        detector.update(
            component="detector:aberrant_moving_mahalanobis_distance",
            params={"window_size": 5},
        )
    else:
        detector["params"] = {"n_estimators": 10}
    data["nodes"].extend(
        {"id": key, "kind": "transform", "component": component, "params": params}
        for key, component, params in steps
    )
    data["edges"] = [edge for edge in data["edges"] if edge["source"] != "input"] + [
        {"source": source, "target": target}
        for source, target in pairwise(
            ["input", *(key for key, _, _ in steps), "detector"]
        )
    ]
    return PipelineDefinition.model_validate(data)


def chained_execution(strategy="adaptive_stream", steps=(), slots=("a", "b")):
    """What RADAR runs for ``chained``, with a reading bound to every slot."""
    definition = compile_pipeline(chained(strategy, steps, slots)).definition
    bindings = [
        dict(
            slot_id=key,
            reading_id=key,
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{key}",
            input_key=key,
        )
        for key in slots
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )


def errors(result):
    """A validation's errors as (code, parameter path, message)."""
    return [
        (item.code, item.parameter_path, item.message)
        for item in result.issues
        if item.severity == "error"
    ]


def feature_names(result, node):
    """The features a compiled or validated design gives one node, by name."""
    return {item.name: item for item in result.features[node]}


def assert_resumes_identically(
    strategy, pipeline, observations, *, warm, compared=6, process=None, after=None
):
    """Run a design in RADAR's detector service up to its first score, then
    check a service restored from its checkpoint scores the next observations
    as the original does. Returns the first scored result.

    ``observations`` is indexable; ``process(service, index)`` overrides how
    one observation is fed, and ``after(restored, process)`` runs before the
    services shut down.
    """
    static = strategy == "static_baseline"
    constructor = (
        StaticConformalDetectionService if static else AdaptiveStreamDetectionService
    )
    if process is None:

        def process(service, index):
            return service.process_data_point(observations[index])

    config = AnomalyDetectionConfig(pipeline=pipeline, checkpoint_interval=10000)
    service = constructor(config)
    restored = None
    try:
        for index in range(warm):
            process(service, index)
        # Training may already have finished and been taken in while the last
        # points were processed, which leaves no future to wait on.
        if static and service._training_future is not None:
            service._training_future.result(timeout=30)
        result = process(service, warm)
        assert result.should_persist and math.isfinite(result.anomaly_score)
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for index in range(warm + 1, warm + 1 + compared):
            actual, expected = process(restored, index), process(service, index)
            assert (
                actual.anomaly_score,
                actual.is_anomaly,
                actual.processed_features,
            ) == (
                expected.anomaly_score,
                expected.is_anomaly,
                expected.processed_features,
            )
        if after is not None:
            after(restored, process)
        return result
    finally:
        if static:
            service.shutdown()
            if restored is not None:
                restored.shutdown()
