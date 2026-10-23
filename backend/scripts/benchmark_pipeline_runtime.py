"""Reproducible real numeric graph timing and sustained diagnostic bounds.

Run in the RADAR environment, for example:
    python backend/scripts/benchmark_pipeline_runtime.py --samples 1000 --repeats 5

This measures the numeric execution and diagnostic collector, excluding MQTT,
PostgreSQL and health-publication I/O. Observation-off and observation-on runs
use the same seeded components, observations, warm-up and frozen quantile policy.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import aberrant
import numpy as np
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.diagnostics import (
    DiagnosticLimits,
    PipelineDiagnostics,
)
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from pydantic import BaseModel, ConfigDict, Field


class BenchmarkSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    samples: int = Field(default=1000, ge=100, le=100_000)
    repeats: int = Field(default=5, ge=3, le=25)
    warmup: int = Field(default=512, ge=64, le=10_000)
    bounds_samples: int = Field(default=2000, ge=100, le=100_000)
    seed: int = 42
    timing_only: bool = False


def _node(identifier, component, *, kind="transform", params=None):
    return {
        "id": identifier,
        "kind": kind,
        "component": component,
        "params": params or {},
    }


def _edge(source, target, order=0):
    return {"source": source, "target": target, "order": order}


def build_workload(name: str, *, trees: int = 100) -> PipelineExecutionConfig:
    """Representative default forest, cheap model and exact boundary fixtures."""
    width = (
        100
        if name in {"maximum_edges", "maximum_width"}
        else 1
        if name == "light"
        else 8
    )
    slots = [f"f{index}" for index in range(width)]
    nodes = [_node("source", "source.aligned", kind="source")]
    edges = []
    if name == "maximum_edges":
        output = _maximum_edges(nodes, edges)
    elif name == "maximum_width":
        output = "source"
        for index in range(60):
            identifier = f"pass{index}"
            nodes.append(_node(identifier, "features.passthrough"))
            edges.append(_edge(output, identifier))
            output = identifier
    elif name == "light":
        nodes.append(_node("scale", "adaptive.standard_scaler"))
        edges.append(_edge("source", "scale"))
        output = "scale"
    elif name == "representative":
        nodes.extend(
            [
                _node("selected", "features.select", params={"features": slots[:6]}),
                _node("scale", "adaptive.standard_scaler"),
                _node(
                    "projection",
                    "adaptive.uncentered_pca",
                    params={"n_components": 3, "n0": 16},
                ),
                _node("raw", "features.select", params={"features": slots[6:]}),
                _node("merged", "features.merge", kind="merge"),
            ]
        )
        edges.extend(
            [
                _edge("source", "selected"),
                _edge("selected", "scale"),
                _edge("scale", "projection"),
                _edge("source", "raw"),
                _edge("projection", "merged", 0),
                _edge("raw", "merged", 1),
            ]
        )
        output = "merged"
    else:
        raise ValueError(f"Unknown workload {name!r}")
    model = (
        "aberrant_moving_average"
        if name == "light"
        else "aberrant_online_isolation_forest"
    )
    params = (
        {"window_size": 128}
        if name == "light"
        else {
            "num_trees": trees,
            "max_leaf_samples": 16,
            "window_size": 512,
            "n_jobs": 1,
            "seed": 42,
        }
    )
    nodes.extend(
        [
            _node("model", f"detector:{model}", kind="detector", params=params),
            _node("policy", "policy.quantile", kind="policy"),
            _node("output", "output.evidence", kind="output"),
        ]
    )
    edges.extend(
        [_edge(output, "model"), _edge("model", "policy"), _edge("policy", "output")]
    )
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            {
                "strategy": "adaptive_stream",
                "input_slots": [{"id": slot, "label": slot} for slot in slots],
                "nodes": nodes,
                "edges": edges,
                "settings": {
                    "training_window_size": 2,
                    "calibration_window_size": 32,
                    "seed": 42,
                },
            }
        )
    ).definition
    bindings = [
        BoundInput(
            slot_id=slot,
            reading_id=slot,
            entity_id="benchmark",
            accepted_topic=f"telemetry/benchmark/{slot}",
            input_key=slot,
        )
        for slot in slots
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id=name,
        run_id=name,
        fingerprint=execution_fingerprint(definition, bindings),
    )


def _maximum_edges(nodes, edges):
    """64 nodes, 128 edges, 100 source features, with valid reconvergence."""
    nodes.append(_node("shared", "features.select", params={"features": ["f0"]}))
    edges.append(_edge("source", "shared"))
    for index in range(40):
        identifier = f"rename{index}"
        nodes.append(
            _node(
                identifier,
                "features.rename",
                params={"mapping": {"f0": f"branch{index}"}},
            )
        )
        edges.append(_edge("shared", identifier))
    for group in range(9):
        merged, selected = f"merge{group}", f"select{group}"
        width = 7 if group < 6 else 8
        indices = [((group * 5) + offset) % 40 for offset in range(width)]
        nodes.append(_node(merged, "features.merge", kind="merge"))
        for order, index in enumerate(indices):
            edges.append(_edge(f"rename{index}", merged, order))
        chosen = indices[1] if group == 8 else indices[0]
        nodes.append(
            _node(selected, "features.select", params={"features": [f"branch{chosen}"]})
        )
        edges.append(_edge(merged, selected))
        edges.append(_edge(selected, "final_merge", group))
    nodes.append(_node("final_merge", "features.merge", kind="merge"))
    return "final_merge"


def observations(width: int, count: int, seed: int) -> list[dict[str, float]]:
    random = np.random.default_rng(seed)
    noise = random.normal(0.0, 0.05, size=(count, width))
    return [
        {
            f"f{column}": math.sin(index / 17 + column) + float(noise[index, column])
            for column in range(width)
        }
        for index in range(count)
    ]


class StreamRunner:
    """Run actual score/learn calls and actual bounded diagnostic collection."""

    def __init__(self, execution, *, observed, capture_every_observation=False):
        self.plan = ExecutionPlan(execution)
        limits = (
            DiagnosticLimits(sample_interval_seconds=1e-12)
            if capture_every_observation
            else None
        )
        self.diagnostics = PipelineDiagnostics(execution, limits) if observed else None
        self.graph, _ = adaptive_graph(
            self.plan, self.diagnostics.observe if self.diagnostics else None
        )
        self.threshold = 0.0
        self.sequence = 0

    def prepare(self, values):
        for data in values:
            if self.diagnostics:
                self.diagnostics.select_pass("learn")
            self.graph.learn_one(data)
        if not self.graph.readiness.ready:
            raise RuntimeError("Benchmark warm-up did not establish a ready graph")
        scores = []
        for data in values[-32:]:
            if self.diagnostics:
                self.diagnostics.select_pass("score")
            scores.append(self.graph.score_one(data))
            if self.diagnostics:
                self.diagnostics.select_pass("learn")
            self.graph.learn_one(data)
        self.threshold = float(np.quantile(scores, 0.99, method="higher"))

    def step(self, data):
        self.sequence += 1
        diagnostic = self.diagnostics
        if diagnostic:
            diagnostic.begin(self.sequence, "operational")
            diagnostic.select_pass("score")
            diagnostic.record(self.plan.source_id, data, data)
        score = self.graph.score_one(data)
        alarm = score > self.threshold
        if diagnostic:
            diagnostic.record(self.plan.policy_id, {"score": score}, float(alarm))
            diagnostic.record(self.plan.output_id, {"alarm": float(alarm)}, score)
            diagnostic.select_pass("learn")
            diagnostic.record(self.plan.source_id, data, data)
        self.graph.learn_one(data)
        if diagnostic:
            diagnostic.readiness(self.graph.node_states, self.graph)
            diagnostic.finish()
        return score, alarm


def benchmark(execution, settings: BenchmarkSettings) -> dict:
    values = observations(
        len(execution.bindings), settings.warmup + settings.samples, settings.seed
    )
    timings = {False: [], True: []}
    reference = None
    for repeat in range(settings.repeats):
        runners = {
            observed: StreamRunner(execution, observed=observed)
            for observed in (False, True)
        }
        for runner in runners.values():
            runner.prepare(values[: settings.warmup])
        gc.collect()
        measurements, outputs = _paired_measurement(
            runners, values[settings.warmup :], repeat
        )
        for observed in (False, True):
            timings[observed].append(measurements[observed])
        if reference is None:
            reference = outputs[False]
        if outputs[True] != reference or outputs[False] != reference:
            raise AssertionError("Observation changed real detector scores or alarms")
    disabled = statistics.median(item["cpu_ns"] for item in timings[False])
    enabled = statistics.median(item["cpu_ns"] for item in timings[True])
    wall_disabled = statistics.median(item["wall_ns"] for item in timings[False])
    wall_enabled = statistics.median(item["wall_ns"] for item in timings[True])
    return {
        "nodes": len(execution.definition.nodes),
        "edges": len(execution.definition.edges),
        "input_features": len(execution.bindings),
        "fingerprint": execution.fingerprint,
        "detector": next(
            node.model_dump(mode="json")
            for node in execution.definition.nodes
            if node.kind == "detector"
        ),
        "feature_components": [
            node.model_dump(mode="json")
            for node in execution.definition.nodes
            if node.kind in {"transform", "merge"}
        ],
        "comparison_method": "Paired states, alternating 10-observation chunks",
        "cpu_overhead_percent": (enabled / disabled - 1) * 100,
        "cpu_ns_per_observation_disabled": disabled / settings.samples,
        "cpu_ns_per_observation_enabled": enabled / settings.samples,
        "wall_overhead_percent": (wall_enabled / wall_disabled - 1) * 100,
        "wall_ns_per_observation_disabled": wall_disabled / settings.samples,
        "wall_ns_per_observation_enabled": wall_enabled / settings.samples,
        "timings": {"disabled": timings[False], "enabled": timings[True]},
        "equal_scores_and_alarms": True,
    }


def _paired_measurement(runners, values, repeat):
    """Balance order and slow CPU/VM drift within each trial, not across minutes."""
    measurements = {observed: {"wall_ns": 0, "cpu_ns": 0} for observed in (False, True)}
    outputs = {False: [], True: []}
    for chunk, start in enumerate(range(0, len(values), 10)):
        order = (False, True) if (chunk + repeat) % 2 == 0 else (True, False)
        for observed in order:
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            outputs[observed].extend(
                runners[observed].step(data) for data in values[start : start + 10]
            )
            measurements[observed]["cpu_ns"] += time.process_time_ns() - cpu
            measurements[observed]["wall_ns"] += time.perf_counter_ns() - wall
    return measurements, outputs


def _retained_size(value, seen=None) -> int:
    """Count collector-owned reachable objects without tracing numeric kernels."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(
            _retained_size(key, seen) + _retained_size(item, seen)
            for key, item in value.items()
        )
    elif isinstance(value, list | tuple | set | frozenset):
        total += sum(_retained_size(item, seen) for item in value)
    elif isinstance(value, PipelineDiagnostics | BaseModel):
        total += _retained_size(vars(value), seen)
    return total


def sustained_bounds(execution, *, samples=2000, seed=42) -> dict:
    values = observations(len(execution.bindings), 512 + samples * 2, seed)
    runner = StreamRunner(execution, observed=True, capture_every_observation=True)
    runner.prepare(values[:512])
    maximum = 0
    before = 0
    for index, data in enumerate(values[512:]):
        runner.step(data)
        payload = runner.diagnostics.snapshot()
        encoded = len(json.dumps(payload, allow_nan=False).encode())
        maximum = max(maximum, encoded)
        if index + 1 == samples:
            before = _retained_size(runner.diagnostics)
    after = _retained_size(runner.diagnostics)
    return {
        "observations": samples * 2,
        "node_count": len(payload["nodes"]),
        "maximum_snapshot_bytes": maximum,
        "snapshot_budget_bytes": runner.diagnostics.limits.maximum_bytes,
        "late_diagnostic_growth_bytes": after - before,
        "retained_diagnostic_bytes": after,
        "retention_measurement": "Collector-owned Python objects, counted once",
        "node_keys_stable": set(payload["nodes"])
        == {node.id for node in execution.definition.nodes},
        "maximum_preview_values": max(
            (
                len(preview[side])
                for phase in payload["observation"]["passes"].values()
                for preview in phase.values()
                for side in ("input", "output")
                if isinstance(preview[side], dict)
            ),
            default=0,
        )
        if payload["observation"]
        else 0,
    }


def runtime_environment() -> dict:
    """Record hardware and process bounds so timing results stay interpretable."""

    def read(path):
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    cpu_info = read("/proc/cpuinfo") or ""
    model = next(
        (
            line.partition(":")[2].strip()
            for line in cpu_info.splitlines()
            if line.startswith("model name")
        ),
        platform.processor(),
    )
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "aberrant": aberrant.__version__,
        "cpu_model": model,
        "logical_cpus_visible": os.cpu_count(),
        "cgroup_cpu_max": read("/sys/fs/cgroup/cpu.max"),
        "cgroup_memory_max_bytes": read("/sys/fs/cgroup/memory.max"),
        "thread_controls": {
            name: os.environ.get(name)
            for name in (
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=512)
    parser.add_argument("--bounds-samples", type=int, default=2000)
    parser.add_argument("--timing-only", action="store_true")
    parser.add_argument("--output", type=Path)
    options = vars(parser.parse_args())
    output = options.pop("output")
    settings = BenchmarkSettings.model_validate(options)
    report = {
        "environment": runtime_environment(),
        "settings": settings.model_dump(),
        "timing_scope": "Numeric score/learn and bounded diagnostics; excludes I/O",
        "workloads": {},
        "bounds": {},
    }
    for name in ("representative", "light"):
        print(f"Timing real numeric workload: {name}", file=sys.stderr, flush=True)
        report["workloads"][name] = benchmark(build_workload(name), settings)
    for name in () if settings.timing_only else ("maximum_edges", "maximum_width"):
        print(f"Checking sustained bounds: {name}", file=sys.stderr, flush=True)
        report["bounds"][name] = sustained_bounds(
            build_workload(name, trees=2),
            samples=settings.bounds_samples,
            seed=settings.seed,
        )
    report["representative_target_met"] = (
        report["workloads"]["representative"]["cpu_overhead_percent"] <= 10.0
    )
    encoded = json.dumps(report, indent=2, allow_nan=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
