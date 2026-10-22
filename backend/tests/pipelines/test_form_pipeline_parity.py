"""Form monitors run as pipelines with the detections the form detectors produced."""

from itertools import pairwise

import numpy as np
import pytest
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    form_inputs,
)
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from off_key_core.schemas.radar import RadarStartConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.service import RadarService
from off_key_tactic_middleware.services.pipelines.library import legacy_definition

# Unsorted on purpose: form detectors order features by sensor key.
TOPICS = ["telemetry/c1/L2", "telemetry/c1/L1"]
STANDARD = {"type": "standard_scaler", "with_std": True}


def static_form():
    params = {"n_estimators": 50, "contamination": 0.1, "random_state": 42}
    return {
        "container_name": "radar-c1",
        "mqtt_topics": TOPICS,
        "strategy": "static_baseline",
        "model_type": "pyod_iforest",
        "model_params": params,
        "static_baseline_config": {
            "model_type": "pyod_iforest",
            "model_params": params,
            "training_window_size": 60,
            "calibration_window_size": 20,
            "martingale_config": {
                "trackers": [
                    {
                        "tracker_id": "primary",
                        "betting_function": "power",
                        "alarm_statistic": "restarted_martingale",
                        "threshold_config": {"mode": "manual", "value": 5},
                        "epsilon": 0.5,
                    }
                ]
            },
        },
    }


def adaptive_form(*steps):
    # Aberrant forests draw an unseeded state unless the form sets one.
    params = {"seed": 7}
    return {
        "container_name": "radar-c1",
        "mqtt_topics": TOPICS,
        "strategy": "adaptive_stream",
        "model_type": "aberrant_online_isolation_forest",
        "model_params": params,
        "adaptive_stream_config": {
            "model_type": "aberrant_online_isolation_forest",
            "model_params": params,
            "training_window_size": 40,
            "calibration_window_size": 20,
            "preprocessing_steps": list(steps),
            "threshold_config": {"mode": "calibrated_quantile", "quantile": 0.95},
        },
    }


def detectors(form):
    config = RadarStartConfig.model_validate(form)
    definition = compile_pipeline(
        legacy_definition(config.model_dump(mode="json"))
    ).definition
    bindings = [
        dict(
            slot_id=slot.id,
            reading_id=f"reading-{key}",
            entity_id="c1",
            accepted_topic=topic,
            input_key=key,
        )
        for slot, (key, topic) in zip(
            definition.input_slots, form_inputs(config), strict=True
        )
    ]
    execution = PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )
    form_config = AnomalyDetectionConfig(monitoring=config.monitoring)
    pipeline_config = AnomalyDetectionConfig(pipeline=execution)
    services = [
        RadarService._detector_service_class(item)(item)
        for item in (form_config, pipeline_config)
    ]
    return [key for key, _ in form_inputs(config)], services


def trace(service, keys, count=140):
    rng = np.random.default_rng(7)
    rows = []
    try:
        for index in range(count):
            values = rng.normal(size=2) + (8.0 if index in {110, 125} else 0.0)
            sample = dict(zip(keys, map(float, values), strict=True))
            result = service.process_data_point(sample)
            future = getattr(service, "_training_future", None)
            if future is not None:
                future.result(timeout=60)
                service._complete_training_if_ready()
            context = result.context.get("static_conformal") or result.context.get(
                "adaptive_stream"
            )
            rows.append((context["phase"], result.anomaly_score, result.is_anomaly))
    finally:
        service.shutdown()
    return rows


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(static_form(), id="static"),
        pytest.param(adaptive_form(), id="adaptive-raw"),
        pytest.param(adaptive_form(STANDARD), id="adaptive-standard"),
        pytest.param(
            adaptive_form({"type": "min_max_scaler", "feature_range": [0, 1]}),
            id="adaptive-min-max",
        ),
        pytest.param(
            adaptive_form(
                STANDARD, {"type": "random_projection", "n_components": 2, "seed": 3}
            ),
            id="adaptive-random-projection",
        ),
    ],
)
def test_form_preset_matches_its_pipeline_exactly(form):
    keys, (form_detector, pipeline_detector) = detectors(form)
    assert type(pipeline_detector).__name__.endswith("PipelineDetectionService")
    expected = trace(form_detector, keys)
    assert expected[-1][0] in {"ready", "operational"}
    assert trace(pipeline_detector, keys) == expected


def test_incremental_pca_pipeline_warms_the_projection_before_the_model():
    n0 = 30
    keys, (form_detector, pipeline_detector) = detectors(
        adaptive_form(
            STANDARD,
            {"type": "incremental_pca", "n_components": 2, "n0": n0, "tol": 1e-7},
        )
    )

    def calibration_start(service):
        phases = [phase for phase, _, _ in trace(service, keys)]
        return phases.index("calibration")

    # The form detector counted projection initialisation as model warm-up; the
    # pipeline only feeds the model once the projection is ready.
    assert calibration_start(pipeline_detector) == (
        calibration_start(form_detector) + n0 - 1
    )


# Pin the graph each setup form lowers to.
SLOTS = [{"id": "input_1", "label": "L1"}, {"id": "input_2", "label": "L2"}]
SOURCE = {"id": "input", "kind": "source", "component": "source.aligned"}
OUTPUT = {"id": "output", "kind": "output", "component": "output.evidence"}


def lowered(form):
    config = RadarStartConfig.model_validate(form).model_dump(mode="json")
    return legacy_definition(config).model_dump(mode="json", exclude_defaults=True)


def chain(*node_ids):
    return [
        {"source": source, "target": target} for source, target in pairwise(node_ids)
    ]


def test_static_form_lowers_to_a_martingale_graph():
    assert lowered(static_form()) == {
        "input_slots": SLOTS,
        "nodes": [
            SOURCE,
            {
                "id": "detector",
                "kind": "detector",
                "component": "detector:pyod_iforest",
                "params": {
                    "n_estimators": 50,
                    "contamination": 0.1,
                    "random_state": 42,
                },
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": "policy.martingale",
                "params": {
                    "trackers": [
                        {
                            "tracker_id": "primary",
                            "alarm_statistic": "restarted_martingale",
                            "threshold_config": {"mode": "manual", "value": 5.0},
                            "betting_function": "power",
                            "epsilon": 0.5,
                        }
                    ],
                    "automatic_threshold_calibration": {
                        "false_alarm_probability": 0.01,
                        "horizon": 1000,
                        "simulation_count": 5000,
                    },
                },
            },
            OUTPUT,
        ],
        "edges": chain("input", "detector", "policy", "output"),
        "settings": {"training_window_size": 60, "calibration_window_size": 20},
    }


def test_adaptive_form_lowers_steps_in_order_and_renames_incremental_pca():
    pca = {"type": "incremental_pca", "n_components": 2, "n0": 30, "tol": 1e-7}
    assert lowered(adaptive_form(STANDARD, pca)) == {
        "strategy": "adaptive_stream",
        "input_slots": SLOTS,
        "nodes": [
            SOURCE,
            {
                "id": "transform_1",
                "kind": "transform",
                "component": "adaptive.standard_scaler",
                "params": {"with_std": True},
            },
            {
                "id": "transform_2",
                "kind": "transform",
                "component": "adaptive.uncentered_pca",
                "params": {
                    "n_components": 2,
                    "n0": 30,
                    "tol": 1e-07,
                    "forgetting_factor": None,
                },
            },
            {
                "id": "detector",
                "kind": "detector",
                "component": "detector:aberrant_online_isolation_forest",
                "params": {
                    "branching_factor": 2,
                    "max_leaf_samples": 32,
                    "metric": "axisparallel",
                    "n_jobs": 1,
                    "num_trees": 100,
                    "seed": 7,
                    "subsample": 1.0,
                    "tree_type": "adaptive",
                    "window_size": 2048,
                },
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": "policy.quantile",
                "params": {"mode": "calibrated_quantile", "quantile": 0.95},
            },
            OUTPUT,
        ],
        "edges": chain(
            "input", "transform_1", "transform_2", "detector", "policy", "output"
        ),
        "settings": {"training_window_size": 40, "calibration_window_size": 20},
    }
