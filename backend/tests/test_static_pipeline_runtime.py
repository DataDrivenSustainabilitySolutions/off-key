"""Real batch fitting, frozen calibration, checkpoint and preview contracts."""

import pickle

import numpy as np
import pytest
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineExecutionConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.execution_errors import FatalExecutionError, ObservationRejected
from off_key_mqtt_radar.pipelines.batch import BatchFeatureGraph
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources
from off_key_mqtt_radar.pipelines.static import StaticPipelineDetectionService
from off_key_mqtt_radar.preflight import preflight
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


def execution(*, projection=False):
    nodes = [
        dict(id="input", kind="source", component="source.aligned"),
        dict(
            id="select",
            kind="transform",
            component="features.select",
            params={"features": ["z"]},
        ),
        dict(id="scale", kind="transform", component="static.standard_scaler"),
        dict(
            id="raw",
            kind="transform",
            component="features.select",
            params={"features": ["a"]},
        ),
        dict(id="merge", kind="merge", component="features.merge"),
        dict(
            id="model",
            kind="detector",
            component="detector:pyod_iforest",
            params={"n_estimators": 10},
        ),
        dict(id="policy", kind="policy", component="policy.martingale"),
        dict(id="output", kind="output", component="output.evidence"),
    ]
    edges = [
        dict(source=left, target=right, order=order)
        for left, right, order in [
            ("input", "select", 0),
            ("select", "scale", 0),
            ("input", "raw", 0),
            ("scale", "merge", 0),
            ("raw", "merge", 1),
            ("merge", "model", 0),
            ("model", "policy", 0),
            ("policy", "output", 0),
        ]
    ]
    if projection:
        nodes.insert(
            5,
            dict(
                id="pca",
                kind="transform",
                component="static.pca",
                params={"n_components": 2},
            ),
        )
        edges = [edge for edge in edges if edge["source"] != "merge"]
        edges.extend(
            [dict(source="merge", target="pca"), dict(source="pca", target="model")]
        )
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            dict(
                strategy="static_baseline",
                input_slots=[
                    dict(id="z", label="Temperature"),
                    dict(id="a", label="Power"),
                ],
                nodes=nodes,
                edges=edges,
                settings=dict(training_window_size=20, calibration_window_size=5),
            )
        )
    ).definition
    bindings = [
        dict(
            slot_id=slot,
            reading_id=f"r-{slot}",
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{slot}",
            input_key=f"sensor/{slot}",
        )
        for slot in ("a", "z")
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id="revision",
        run_id="run",
    )


def test_batch_branching_matches_reference_and_freezes_training_statistics():
    plan = ExecutionPlan(execution(projection=True))
    graph = BatchFeatureGraph(plan)
    training = np.array(
        [[index * 3 + (index % 3), index**2] for index in range(20)], dtype=float
    )
    scaler = StandardScaler().fit(training[:, [0]])
    merged = np.column_stack([scaler.transform(training[:, [0]]), training[:, 1]])
    reference = PCA(n_components=2, random_state=42).fit(merged)
    np.testing.assert_allclose(
        graph.fit_transform(training), reference.transform(merged), atol=1e-10
    )
    calibration = training[:5] + 10000
    frozen = graph.components["scale"].mean_.copy()
    expected = reference.transform(
        np.column_stack([scaler.transform(calibration[:, [0]]), calibration[:, 1]])
    )
    np.testing.assert_allclose(graph.transform(calibration), expected, atol=1e-10)
    np.testing.assert_array_equal(graph.components["scale"].mean_, frozen)
    with pytest.raises(RuntimeError, match="already frozen"):
        graph.fit_transform(calibration)


def test_real_static_run_checkpoint_preview_and_fatal_policy_boundary(monkeypatch):
    config = AnomalyDetectionConfig(pipeline=execution(), checkpoint_interval=10000)
    service = StaticPipelineDetectionService(config)
    restored = None
    try:
        for index in range(25):
            service.process_data_point({"sensor/z": index, "sensor/a": index % 4})
        service._training_future.result(timeout=30)
        service.diagnostics._last_sample = float("-inf")
        result = service.process_data_point({"sensor/z": 5, "sensor/a": 2})
        assert result.should_persist
        assert result.raw_data == {"sensor/z": 5, "sensor/a": 2}
        assert set(result.processed_features) == {"z", "a"}
        state = service.get_pipeline_state()
        assert state["batch_training"]["frozen"]
        assert (
            state["observation"]["passes"]["score"]["model"]["output"]
            == result.anomaly_score
        )
        assert (
            state["observation"]["passes"]["learn"]["scale"]["state"] == "not_executed"
        )
        snapshot = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = StaticPipelineDetectionService.from_checkpoint_data(snapshot, config)
        assert (
            restored.process_data_point({"sensor/z": 5, "sensor/a": 2}).anomaly_score
            == result.anomaly_score
        )
        with pytest.raises(ObservationRejected):
            restored.process_data_point({"sensor/z": float("nan"), "sensor/a": 2})
        original = restored.alarm_controller.update

        def mutate_then_fail(value):
            original(value)
            raise RuntimeError("injected failure after policy mutation")

        monkeypatch.setattr(restored.alarm_controller, "update", mutate_then_fail)
        with pytest.raises(FatalExecutionError, match="policy mutation"):
            restored.process_data_point({"sensor/z": 5, "sensor/a": 2})
        assert restored.get_pipeline_state()["nodes"]["policy"]["state"] == "failed"
        with pytest.raises(FatalExecutionError, match="checkpointed"):
            restored.export_checkpoint()
    finally:
        service.shutdown()
        if restored is not None:
            restored.shutdown()


def test_constructor_preflight_uses_compiled_identity_and_reports_known_costs():
    report = preflight(execution())
    assert report["ok"] and not report["fitting_validated"]
    assert report["resources"]["known_numeric_bytes"] > 0
    assert report["fingerprint"] == execution().fingerprint
    assert report["feature_schemas"]["model"]["preview_names"] == ["z", "a"]


def test_preflight_accounts_for_retained_python_collection_buffers():
    config = execution()
    config.definition.settings.training_window_size = 1_000_000
    config.fingerprint = execution_fingerprint(config.definition, config.bindings)
    with pytest.raises(ValueError, match="memory limit"):
        estimate_resources(ExecutionPlan(config), 128)
    with pytest.raises(ValueError, match="memory limit"):
        AnomalyDetectionConfig(pipeline=config, memory_limit_mb=128)


def parallel_pca_execution(*, n0, width=1):
    nodes = [dict(id="input", kind="source", component="source.aligned")]
    edges = []
    for index in range(58):
        identifier = f"pca{index}"
        nodes.append(
            dict(
                id=identifier,
                kind="transform",
                component="adaptive.uncentered_pca",
                params={"n_components": 1, "n0": n0},
            )
        )
        edges.extend(
            [
                dict(source="input", target=identifier),
                dict(source=identifier, target="merge", order=index),
            ]
        )
    nodes.extend(
        [
            dict(id="merge", kind="merge", component="features.merge"),
            dict(
                id="model",
                kind="detector",
                component="detector:aberrant_online_isolation_forest",
                params={"num_trees": 4, "max_leaf_samples": 4},
            ),
            dict(id="policy", kind="policy", component="policy.quantile"),
            dict(id="output", kind="output", component="output.evidence"),
        ]
    )
    edges.extend(
        dict(source=left, target=right)
        for left, right in (
            ("merge", "model"),
            ("model", "policy"),
            ("policy", "output"),
        )
    )
    slots = [f"f{index}" for index in range(width)]
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            dict(
                strategy="adaptive_stream",
                input_slots=[dict(id=slot, label=slot) for slot in slots],
                nodes=nodes,
                edges=edges,
                settings=dict(training_window_size=2, calibration_window_size=2),
            )
        )
    ).definition
    bindings = [
        dict(
            slot_id=slot,
            reading_id=f"r-{slot}",
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{slot}",
            input_key=f"sensor/{slot}",
        )
        for slot in slots
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id="revision",
        run_id="run",
    )


@pytest.mark.parametrize("memory_limit_mb", [128, 384])
def test_parallel_pca_warmup_headers_and_transactional_lists_exceed_memory_limit(
    memory_limit_mb,
):
    config = parallel_pca_execution(n0=100_000)
    plan = ExecutionPlan(config)
    report = estimate_resources(plan, 4096)
    # Numeric data alone fits 384 MiB, but the actual list of individual NumPy
    # rows does not. Reject before any of the 5.8 million rows are allocated.
    assert report.known_numeric_bytes < 384 * 1024 * 1024
    assert report.projection_state_container_bytes > 384 * 1024 * 1024
    with pytest.raises(ValueError, match="memory limit"):
        estimate_resources(plan, memory_limit_mb)
    with pytest.raises(ValueError, match="memory limit"):
        AnomalyDetectionConfig(pipeline=config, memory_limit_mb=memory_limit_mb)


def test_preflight_honors_a_larger_explicit_worker_memory_budget():
    config = parallel_pca_execution(n0=100_000)
    report = preflight(config, memory_limit_mb=4096)
    assert report["ok"]
    assert report["resources"]["memory_limit_mb"] == 4096
    assert report["resources"]["known_minimum_bytes"] > 384 * 1024 * 1024


def test_ordinary_parallel_pca_and_boundary_graphs_fit_admission_budget():
    from backend.scripts.benchmark_pipeline_runtime import build_workload

    configurations = [parallel_pca_execution(n0=50, width=100)] + [
        build_workload(name, trees=2) for name in ("maximum_edges", "maximum_width")
    ]
    for config in configurations:
        report = estimate_resources(ExecutionPlan(config), 128)
        assert report.known_minimum_bytes < 128 * 1024 * 1024
        assert AnomalyDetectionConfig(pipeline=config, memory_limit_mb=128).pipeline


def test_input_binding_list_order_does_not_change_slot_order():
    plan = ExecutionPlan(execution())
    assert list(plan.bind({"sensor/a": 3, "sensor/z": 4})) == ["z", "a"]
