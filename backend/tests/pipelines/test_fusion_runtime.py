"""Runs whose policy combines several detectors by rank, in both strategies."""

from __future__ import annotations

import pickle

import numpy as np
import pytest
from aberrant.compose import GraphExecutionError, GraphStateUncertainError
from aberration_core.schemas.pipelines import PipelineDefinition, PipelineRuntimeState
from aberration_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from aberration_mqtt_radar.detector import (
    StaticConformalDetectionService,
    StaticConformalState,
)
from aberration_mqtt_radar.execution_errors import FatalExecutionError, StepRejected
from aberration_mqtt_radar.fusion import RankFusion, threshold_count
from aberration_mqtt_radar.pipelines.diagnostics import DiagnosticLimits
from aberration_mqtt_radar.pipelines.plan import ExecutionPlan
from aberration_mqtt_radar.pipelines.resources import estimate_resources
from aberration_mqtt_radar.preflight import preflight
from aberration_mqtt_radar.result_records import ResultProjector
from scipy import stats

from tests.support.fused_pipeline import bound, fused_definition, reading

pytestmark = pytest.mark.radar_integration


def _calm(generator, count):
    return [reading(*generator.normal(size=2)) for _ in range(count)]


def _static(definition):
    return StaticConformalDetectionService(bound(definition))


def _feed(service, points):
    results = []
    for point in points:
        results.append(service.process_data_point(point))
        future = getattr(service, "_training_future", None)
        if future is not None:
            future.result()
            service.refresh_background_state()
    return results


@pytest.mark.parametrize("fusion", ["max", "mean"])
@pytest.mark.parametrize("scores", ["continuous", "tied"])
def test_fused_p_values_are_uniform_without_a_change(fusion, scores):
    """Over 10,000 fresh calibrations, the fused rank is uniform on 1 to n + 1."""
    generator = np.random.default_rng(20)
    ties = np.random.default_rng(21)
    size = 19
    values = []
    for _ in range(10_000):
        rows = (
            generator.normal(size=(size + 1, 3))
            if scores == "continuous"
            else generator.integers(0, 4, size=(size + 1, 3)).astype(float)
        )
        p_value = RankFusion(rows[:size], fusion).p_value(rows[size], ties)
        assert p_value * (size + 1) == pytest.approx(round(p_value * (size + 1)))
        # Spread each rank over its interval, so the test sees a continuous law.
        values.append((p_value * (size + 1) - generator.random()) / (size + 1))

    assert stats.kstest(values, "uniform").pvalue > 0.01


def test_one_detector_repeated_gives_one_detectors_threshold_rule():
    generator = np.random.default_rng(3)
    calibration = generator.normal(size=50)
    fusion = RankFusion(np.column_stack([calibration, calibration]), "max")
    for quantile in (1.0, 0.9, 0.5):
        threshold = np.quantile(calibration, quantile, method="higher")
        count = threshold_count(fusion, quantile)
        for score in generator.normal(size=500):
            fused = int(fusion.combined(fusion.counts([score, score])))
            assert (fused > count) == (score > threshold)


def test_static_detectors_fit_on_their_own_features_and_combine():
    service = _static(fused_definition())
    generator = np.random.default_rng(5)
    results = _feed(service, _calm(generator, 70))
    ready = [
        item for item in results if item.context["static_conformal"]["phase"] == "ready"
    ]

    assert service.state == StaticConformalState.READY
    fitted = service.conformal_detector
    assert list(fitted.detectors) == ["detector", "detector_2"]
    assert fitted.fusion.calibration.shape == (20, 2)
    # Fused p-values take the values one detector's do: k / (n + 1).
    for result in ready:
        assert result.anomaly_score * 21 == pytest.approx(
            round(result.anomaly_score * 21)
        )
        detectors = result.context["static_conformal"]["detectors"]
        assert [item["detector_id"] for item in detectors] == ["detector", "detector_2"]
        assert all(0 <= item["surprise"] <= 1 for item in detectors)
    assert set(result.processed_features) == {"detector", "detector_2"}
    nodes = service.get_pipeline_state()["nodes"]
    assert (
        nodes["detector"]["score_count"]
        == nodes["detector_2"]["score_count"]
        == len(ready)
    )
    info = service.get_model_info()
    assert info["fusion"] == "max"
    assert [item["model_type"] for item in info["detectors"]] == [
        "pyod_iforest",
        "pyod_knn",
    ]
    service.shutdown()


def test_a_shift_one_detector_sees_drives_strongest_harder_than_average():
    """Reading b jumps; only the second detector (nearest neighbours) reads it."""
    p_values = {}
    for fusion in ("max", "mean"):
        service = _static(fused_definition(fusion=fusion))
        generator = np.random.default_rng(8)
        _feed(service, _calm(generator, 50))
        shifted = [
            reading(generator.normal(), 9.0 + generator.normal()) for _ in range(20)
        ]
        results = _feed(service, shifted)
        p_values[fusion] = [item.anomaly_score for item in results]
        for item in results:
            detectors = item.context["static_conformal"]["detectors"]
            assert detectors[1]["surprise"] == 1.0
        service.shutdown()

    # With Strongest the shifted detector alone sets the p-value: at most one
    # calibration observation can tie with it, so p is 1/21 or 2/21.
    assert max(p_values["max"]) <= 2 / 21
    # Averaged with the calm first detector, the same jump weighs less.
    assert np.mean(p_values["mean"]) > 2 * np.mean(p_values["max"])


@pytest.mark.parametrize("stop", [35, 60])
def test_static_checkpoints_restore_combined_detectors(stop):
    """Restored during calibration or while scoring, the run goes on unchanged."""
    generator = np.random.default_rng(13)
    points = _calm(generator, 80)
    reference = _static(fused_definition())
    expected = [item.anomaly_score for item in _feed(reference, points)]
    reference.shutdown()

    service = _static(fused_definition())
    _feed(service, points[:stop])
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    service.shutdown()
    restored = StaticConformalDetectionService.from_checkpoint_data(
        checkpoint, bound(fused_definition())
    )
    resumed = [item.anomaly_score for item in _feed(restored, points[stop:])]
    restored.shutdown()

    assert resumed == expected[stop:]


def _adaptive(definition=None, **options):
    return AdaptiveStreamDetectionService(
        bound(definition or fused_definition("adaptive_stream", **options))
    )


def _phase(result):
    return result.context["adaptive_stream"]["phase"]


def test_adaptive_detectors_learn_their_own_copy_of_a_shared_step():
    service = _adaptive(training=5, calibration=10)
    first, second = service.pipelines
    copies = [
        next(node for node in graph.nodes if node.id == "scale").transformer
        for graph in (first, second)
    ]
    assert copies[0] is not copies[1]
    assert {node.id for node in second.nodes} == {"scale", "only_b"}

    generator = np.random.default_rng(1)
    _feed(service, _calm(generator, 30))

    probe = {"a": 0.4, "b": -1.2}
    assert copies[0].transform_one(probe) == copies[1].transform_one(probe)
    nodes = service.get_pipeline_state()["nodes"]
    # The shared step counts once, though both detectors learn it.
    assert nodes["scale"]["learn_count"] == service.processed_count == 30
    assert service.state == AdaptiveStreamState.OPERATIONAL


def test_adaptive_threshold_is_the_quantile_of_combined_calibration_surprises():
    service = _adaptive(training=5, calibration=20)
    generator = np.random.default_rng(2)
    results = _feed(service, _calm(generator, 40))
    calibration = np.asarray(service.calibration_scores)

    assert calibration.shape == (20, 2)
    fusion = RankFusion(calibration, "max")
    assert service.threshold == fusion.value(threshold_count(fusion, 1.0)) == 19 / 20
    operational = [item for item in results if _phase(item) == "operational"]
    for item in operational:
        context = item.context["adaptive_stream"]
        surprises = [entry["surprise"] for entry in context["detectors"]]
        assert item.anomaly_score == max(surprises)
        assert item.is_anomaly == (item.anomaly_score > service.threshold)


def test_adaptive_strongest_alarms_on_a_shift_one_detector_sees_average_needs_more():
    results = {}
    for fusion in ("max", "mean"):
        service = _adaptive(fusion=fusion, training=5, calibration=30)
        generator = np.random.default_rng(4)
        _feed(service, _calm(generator, 45))
        assert service.state == AdaptiveStreamState.OPERATIONAL
        [results[fusion]] = _feed(service, [reading(25.0, generator.normal())])

    strongest, average = results["max"], results["mean"]
    surprises = [
        item["surprise"] for item in strongest.context["adaptive_stream"]["detectors"]
    ]
    # Only the first detector sees the jump: it is beyond all its calibration.
    assert surprises[0] == 1.0
    assert strongest.anomaly_score == 1.0 and strongest.is_anomaly
    # Averaged with a calm second detector the same jump stays below 1, and
    # below the threshold: Average needs more than one detector to agree.
    assert average.anomaly_score < strongest.anomaly_score
    assert not average.is_anomaly


def test_adaptive_warm_up_ends_when_every_detector_is_ready():
    service = _adaptive(training=2, calibration=5, slow_second=True)
    generator = np.random.default_rng(6)
    first, second = service.pipelines
    phases, updates = [], []
    for point in _calm(generator, 12):
        phases.append(_phase(service.process_data_point(point)))
        updates.append((first.model_updates, second.model_updates))
    end = phases.index("calibration")

    # The first detector alone would be ready after two observations; the
    # second reads b through a robust scaling that needs six first.
    assert end >= 6
    assert phases[:end] == ["warmup"] * end
    first_updates, second_updates = updates[end - 1]
    assert first_updates > second_updates == service.warmup_count == 2


def _calibrating():
    service = _adaptive(training=3, calibration=10)
    generator = np.random.default_rng(7)
    _feed(service, _calm(generator, 6))
    assert service.state == AdaptiveStreamState.CALIBRATING
    return service, generator


def test_a_failed_score_skips_the_observation_for_every_detector():
    service, generator = _calibrating()
    before = (service.processed_count, service.calibration_count)
    learned = [graph.model_updates for graph in service.pipelines]

    def fail(_data):
        raise GraphExecutionError("$model", "score", "boom")

    service.pipelines[1].score_one = fail
    with pytest.raises(StepRejected):
        service.process_data_point(reading(*generator.normal(size=2)))

    assert (service.processed_count, service.calibration_count) == before
    assert [graph.model_updates for graph in service.pipelines] == learned
    rejections = service.get_pipeline_state()["nodes"]["detector_2"]["rejections"]
    assert rejections == {"error": 1}


def test_a_detector_failing_to_learn_after_another_misses_only_that_observation():
    service, generator = _calibrating()
    learned = [graph.model_updates for graph in service.pipelines]
    original = service.pipelines[1].learn_one

    def fail(_data):
        raise GraphExecutionError("$model", "learn", "boom")

    service.pipelines[1].learn_one = fail
    result = service.process_data_point(reading(*generator.normal(size=2)))
    service.pipelines[1].learn_one = original

    assert _phase(result) == "calibration"
    assert [graph.model_updates for graph in service.pipelines] == [
        learned[0] + 1,
        learned[1],
    ]
    rejections = service.get_pipeline_state()["nodes"]["detector_2"]["rejections"]
    assert rejections == {"error": 1}
    service.process_data_point(reading(*generator.normal(size=2)))
    assert service.pipelines[1].model_updates == learned[1] + 1


def test_the_first_detector_failing_to_learn_skips_the_observation():
    service, generator = _calibrating()
    before = service.calibration_count

    def fail(_data):
        raise GraphExecutionError("scale", "learn", "boom")

    service.pipelines[0].learn_one = fail
    with pytest.raises(StepRejected):
        service.process_data_point(reading(*generator.normal(size=2)))
    assert service.calibration_count == before


def test_uncertain_detector_state_still_stops_the_run():
    service, generator = _calibrating()

    def fail(_data):
        raise GraphStateUncertainError("$model", "learn", "boom")

    service.pipelines[1].learn_one = fail
    with pytest.raises(FatalExecutionError):
        service.process_data_point(reading(*generator.normal(size=2)))
    with pytest.raises(FatalExecutionError):
        service.export_checkpoint()


@pytest.mark.parametrize("stop", [8, 25])
def test_adaptive_checkpoints_restore_every_detector(stop):
    """Restored during calibration or operation, the run goes on unchanged."""
    generator = np.random.default_rng(9)
    points = _calm(generator, 40)
    reference = _adaptive(training=3, calibration=10)
    expected = [
        (item.anomaly_score, item.is_anomaly) for item in _feed(reference, points)
    ]

    service = _adaptive(training=3, calibration=10)
    _feed(service, points[:stop])
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    assert len(checkpoint["pipelines"]) == 2 and "pipeline" not in checkpoint
    restored = AdaptiveStreamDetectionService.from_checkpoint_data(
        checkpoint,
        bound(fused_definition("adaptive_stream", training=3, calibration=10)),
    )
    resumed = [
        (item.anomaly_score, item.is_anomaly) for item in _feed(restored, points[stop:])
    ]

    assert resumed == expected[stop:]


def test_a_checkpoint_with_a_changed_detector_is_refused():
    service = _adaptive(training=3, calibration=10)
    _feed(service, _calm(np.random.default_rng(10), 5))
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    first, _second = checkpoint["detector_fingerprints"]
    checkpoint["detector_fingerprints"] = [first, "changed"]

    with pytest.raises(ValueError, match="detector configuration"):
        AdaptiveStreamDetectionService(service.config, checkpoint=checkpoint)


def _robust_before_the_split():
    """Both detectors read the robust scaling, so each learns its own copy."""
    design = fused_definition("adaptive_stream", slow_second=True).model_dump(
        mode="json"
    )
    design["edges"] = [
        {"source": "input", "target": "scale"},
        {"source": "scale", "target": "robust"},
        {"source": "robust", "target": "only_a"},
        {"source": "robust", "target": "only_b"},
        {"source": "only_a", "target": "detector"},
        {"source": "only_b", "target": "detector_2"},
        {"source": "detector", "target": "policy", "order": 0},
        {"source": "detector_2", "target": "policy", "order": 1},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(design)


def test_admission_counts_each_adaptive_copy_and_the_calibration_scores():
    def estimate(definition):
        return estimate_resources(ExecutionPlan(bound(definition).pipeline), 512)

    static = estimate(fused_definition())
    one_copy = estimate(fused_definition("adaptive_stream", slow_second=True))
    two_copies = estimate(_robust_before_the_split())

    # Rank fusion keeps n x K scores, a sorted copy, the counts and two
    # scoring matrices; an adaptive run first collects them as lists.
    assert static.fusion_state_bytes == 5 * 20 * 2 * 8
    assert one_copy.fusion_state_bytes > static.fusion_state_bytes
    # Before the split the scaling holds windows for two features, twice over.
    assert (
        two_copies.projection_state_numeric_bytes
        == 4 * one_copy.projection_state_numeric_bytes
        > 0
    )


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_preflight_builds_every_detector(strategy):
    execution = bound(fused_definition(strategy)).pipeline

    report = preflight(execution)

    assert report["ok"]
    if strategy == "adaptive_stream":
        assert set(report["capabilities"]) == {"detector", "detector_2"}
        steps = [item["node_id"] for item in report["readiness"]]
        assert len(steps) == len(set(steps))
        assert "scale" in steps


def test_evidence_names_each_detector_beside_the_fused_value():
    service = _adaptive(training=3, calibration=10)
    results = _feed(service, _calm(np.random.default_rng(12), 20))
    operational = next(item for item in results if _phase(item) == "operational")
    operational.context["alignment"] = {
        "aligned_vector": True,
        "required_sensors": ["a", "b"],
        "input_timestamps": {"a": "2026-11-02T10:00:00Z", "b": "2026-11-02T10:00:00Z"},
    }

    records = ResultProjector(service_id="svc")._build_evidence_records([operational])

    assert [item["detector_id"] for item in records[0]["detector_results"]] == [
        "detector",
        "detector_2",
    ]
    assert records[0]["anomaly_score"] == operational.anomaly_score


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_the_sampled_observation_shows_each_detector(strategy):
    """The live inspector reads each detector's score and surprise from the sample."""
    if strategy == "static_baseline":
        service = _static(fused_definition())
        points = 60
    else:
        service = _adaptive(training=3, calibration=10)
        points = 20
    service.diagnostics.limits = DiagnosticLimits(sample_interval_seconds=1e-12)
    [result] = _feed(service, _calm(np.random.default_rng(14), points))[-1:]
    state = PipelineRuntimeState.model_validate(service.get_pipeline_state())

    observation = state.observation
    assert observation is not None and observation.detectors is not None
    key = "static_conformal" if strategy == "static_baseline" else "adaptive_stream"
    expected = result.context[key]["detectors"]
    assert [item.model_dump() for item in observation.detectors] == expected
    # Each detector's own sample keeps its features and its score.
    for item in expected:
        sample = observation.passes.score[item["detector_id"]]
        assert sample.output == item["score"]
        assert sample.input == result.processed_features[item["detector_id"]]
    if strategy == "static_baseline":
        service.shutdown()
