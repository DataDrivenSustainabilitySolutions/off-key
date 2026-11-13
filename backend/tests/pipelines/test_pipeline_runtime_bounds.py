"""Boundary-sized real graphs and sustained diagnostic retention."""

import json

import pytest
from aberrant.compose import NodeState, Readiness
from backend.scripts.benchmark_pipeline_runtime import (
    StreamRunner,
    build_workload,
    observations,
    sustained_bounds,
)
from off_key_mqtt_radar.pipelines.diagnostics import PipelineDiagnostics

pytestmark = pytest.mark.radar_integration


@pytest.mark.parametrize(
    "workload,edges",
    [("maximum_edges", 128), pytest.param("maximum_width", 63, marks=pytest.mark.slow)],
)
def test_maximum_graph_executes_once_per_node_with_observation_equivalence(
    workload, edges
):
    execution = build_workload(workload, trees=2)
    # The schema 1 form: the policy still combines the detectors.
    design = execution.definition.model_dump()
    assert len(design["nodes"]) == 64
    assert len(design["edges"]) == edges
    assert len(execution.bindings) == 100
    values = observations(100, 128, seed=42)
    clean = StreamRunner(execution, observed=False)
    observed = StreamRunner(execution, observed=True)
    clean.prepare(values[:64])
    observed.prepare(values[:64])
    for data in values[64:]:
        assert observed.step(data) == clean.step(data)
    assert clean.graph.model_updates == observed.graph.model_updates == 160
    assert all(state.updates == 160 for state in observed.graph.node_states)
    snapshot = observed.diagnostics.snapshot()
    assert len(snapshot["nodes"]) == 64
    assert all(
        metrics["learn_count"] == 160
        for node, metrics in snapshot["nodes"].items()
        if node not in {"source", "policy", "output"}
    )


def test_prepare_workload_scores_the_same_with_observation():
    execution = build_workload("prepare")
    values = observations(8, 240, seed=42)
    clean = StreamRunner(execution, observed=False)
    observed = StreamRunner(execution, observed=True)
    clean.prepare(values[:160])
    observed.prepare(values[:160])
    for data in values[160:]:
        assert observed.step(data) == clean.step(data)
    # Despike 11, Smooth 10, Change 1 and a 60-value spread lead by 79.
    assert clean.stage.status() == {
        "ready": True,
        "observed": 80,
        "required": 80,
        "rejected": 0,
        "held_back": 0,
        "muted": 0,
    }
    nodes = observed.diagnostics.snapshot()["nodes"]
    # 192 warm-up runs and 80 timed ones; each step starts once its input does.
    assert [nodes[step]["learn_count"] for step in ("despike", "smooth", "change")] == [
        272,
        262,
        253,
    ]
    assert nodes["spread"]["learn_count"] == 252


@pytest.mark.parametrize(
    "workload", ["maximum_edges", pytest.param("maximum_width", marks=pytest.mark.slow)]
)
def test_sustained_boundary_graph_keeps_previews_and_retained_storage_bounded(workload):
    result = sustained_bounds(build_workload(workload, trees=2), samples=100)
    assert result["observations"] == 200
    assert result["node_count"] == 64
    assert result["node_keys_stable"]
    assert result["maximum_preview_values"] <= 8
    assert result["maximum_snapshot_bytes"] <= result["snapshot_budget_bytes"]
    assert result["late_diagnostic_growth_bytes"] < 64 * 1024


@pytest.mark.parametrize("character", ["💥", "é", "\x00"])
def test_multibyte_errors_keep_all_maximum_node_statuses_within_snapshot_budget(
    character,
):
    diagnostics = PipelineDiagnostics(build_workload("maximum_width", trees=2))
    for identifier in diagnostics.nodes:
        diagnostics.fail(identifier, RuntimeError(character * 10_000))
    snapshot = diagnostics.snapshot()
    assert len(snapshot["nodes"]) == 64
    assert len(json.dumps(snapshot, allow_nan=False).encode()) <= 128 * 1024
    assert all(
        len(node["error"].encode("utf-8")) <= 256
        and node["state"] == "failed"
        and not node["ready"]
        for node in snapshot["nodes"].values()
    )


@pytest.mark.parametrize("character", ["💥", "é", "\x00"])
def test_readiness_reasons_and_dependencies_stay_bounded_at_graph_limits(character):
    execution = build_workload("maximum_edges", trees=2)
    # Exercise the schema's maximum identifier lengths as well as maximum edge
    # count. This is a detached diagnostic serialization probe, without inference.
    identifiers = {
        node.id: node.id + "x" * (100 - len(node.id))
        for node in execution.definition.nodes
    }
    # The stored form, as this runtime reports it: the policy reads the detectors.
    design = execution.definition.model_dump()
    parents = {
        identifiers[node["id"]]: tuple(
            identifiers[edge["source"]]
            for edge in design["edges"]
            if edge["target"] == node["id"]
        )
        for node in design["nodes"]
    }
    for node in execution.definition.nodes:
        node.id = identifiers[node.id]
    for edge in execution.definition.edges:
        edge.source, edge.target = identifiers[edge.source], identifiers[edge.target]
    diagnostics = PipelineDiagnostics(execution)
    diagnostics.readiness(
        [
            NodeState(
                identifier,
                123,
                Readiness(False, 123, 100_000, character * 10_000),
                sources,
            )
            for identifier, sources in parents.items()
        ]
    )
    snapshot = diagnostics.snapshot()
    assert len(json.dumps(snapshot, allow_nan=False).encode()) <= 128 * 1024
    assert sum(len(node["blocked_by"]) for node in snapshot["nodes"].values()) == 128
    for identifier in diagnostics.nodes:
        diagnostics.fail(identifier, RuntimeError(character * 10_000))
    snapshot = diagnostics.snapshot()
    assert len(json.dumps(snapshot, allow_nan=False).encode()) <= 128 * 1024
    assert all(
        len(node["readiness_reason"].encode("utf-8")) <= 128
        and node["readiness_observed"] == 123
        and node["readiness_required"] == 100_000
        and node["learned_updates"] == 123
        for node in snapshot["nodes"].values()
    )
