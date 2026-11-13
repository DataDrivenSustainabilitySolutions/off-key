"""A Mute alarms step: the run learns and scores as usual and raises no alarm."""

import math
import pickle

import pytest
from off_key_core.models.pipeline_catalog import pipeline_components
from off_key_core.models.pipeline_combine import Mute, row_step
from off_key_core.models.pipeline_prepare import stage_split
from off_key_core.models.pipelines import compile_pipeline, validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineRuntimeState
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.calibration_comparison import CalibrationComparison
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.pipelines.diagnostics import (
    DiagnosticLimits,
    PipelineDiagnostics,
)
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import (
    PrepareRejected,
    PrepareStage,
    Withheld,
)
from off_key_mqtt_radar.result_records import ResultProjector

from tests.support.conformal_run import (
    ControlledExecutor,
    FakeConformalDetector,
    tracker,
)
from tests.support.fused_pipeline import KEYS, bound, reading
from tests.support.rule_pipeline import CALIBRATION, rule_definition

pytestmark = pytest.mark.radar_integration

# A flag that is 1 where reading a is above 5; reading b decides the mute.
LIMIT = "if(a > 5, 1, 0) + 0 * b"
MUTE = "b > 0"
BOUNDARY = {
    "calibration": "calibrate.aci",
    "calibration_params": {"alpha": 0.1},
    "policy": "policy.exceedance",
}


def limit_definition(**options) -> PipelineDefinition:
    """The flag alarms from the fourth observation on; b > 0 mutes it."""
    return rule_definition(expression=LIMIT, calibration_window=3, mute=MUTE, **options)


def issues(definition):
    return [
        (item.severity, item.code, item.node_id, item.parameter_path, item.message)
        for item in validate_pipeline(definition).issues
    ]


def outcome(result):
    context = result.context["adaptive_stream"]
    return (
        result.is_anomaly,
        context["alarm_fired"],
        context.get("alarm_muted", False),
    )


def static_outcome(result):
    context = result.context["static_conformal"]
    return (result.is_anomaly, context["alarm_fired"], context["alarm_muted"])


RAISED, MUTED, QUIET = (True, True, False), (False, False, True), (False,) * 3


def test_the_catalog_offers_a_step_with_one_condition_that_learns_nothing():
    offered = {item.id: item for item in pipeline_components()}["prepare.mute"]

    assert (offered.kind, offered.label, offered.learning) == (
        "transform",
        "Mute alarms",
        "none",
    )
    assert [(field.name, field.required) for field in offered.fields] == [
        ("condition", True)
    ]


def test_the_step_passes_its_features_on_unchanged_and_runs_before_learning():
    compiled = compile_pipeline(limit_definition(others=("mad",)))

    # Each continues the feature before the step, and nothing else changes.
    assert [
        (item.name, item.slots, item.raw, item.previous)
        for item in compiled.features["mute"]
    ] == [("a", ["a"], True, "input.a"), ("b", ["b"], True, "input.b")]
    split = stage_split(compiled)
    assert split is not None
    assert split.steps[:2] == ("mute", "gap")
    step = row_step("prepare.mute", {"condition": "b > 0 and a < 9"}, ["a", "b"])
    assert isinstance(step, Mute)
    assert step.holds({"a": 1.0, "b": 1.0})
    assert not step.holds({"a": 9.0, "b": 1.0})


@pytest.mark.parametrize(
    ("condition", "severity", "code", "message"),
    [
        ("b >", "error", "formula", ""),
        ("b", "error", "formula", "Write a condition, such as dc_current > 1"),
        ("c > 0", "error", "formula", ""),
        (
            "b > 0 or b <= 0",
            "error",
            "values",
            "The condition is always true, so no alarm would ever be raised.",
        ),
        (
            "b > 0 and b < 0",
            "warning",
            "values",
            "The condition is never true, so the step mutes no alarm.",
        ),
    ],
)
def test_the_compiler_checks_the_condition(condition, severity, code, message):
    found = [
        item for item in issues(rule_definition(mute=condition)) if item[2] == "mute"
    ]

    assert [(item[0], item[1], item[3]) for item in found] == [
        (severity, code, ["condition"])
    ]
    assert message in found[0][4]


def test_the_step_comes_before_every_step_that_learns():
    design = rule_definition(("mad",)).model_dump(mode="json")
    design["nodes"].append(
        {
            "id": "late",
            "kind": "transform",
            "component": "prepare.mute",
            "params": {"condition": "b > 0"},
        }
    )
    design["edges"] = [
        edge
        for edge in design["edges"]
        if (edge["source"], edge["target"]) != ("scale_b", "mad")
    ] + [
        {"source": "scale_b", "target": "late"},
        {"source": "late", "target": "mad"},
    ]

    found = issues(PipelineDefinition.model_validate(design))

    assert [(item[0], item[1], item[2]) for item in found] == [
        ("error", "stage", "late")
    ]
    assert found[0][4].startswith("Mute alarms must come before")


def test_the_stage_marks_the_observations_whose_condition_holds():
    plan = ExecutionPlan(bound(limit_definition()).pipeline)
    stage = PrepareStage(plan)

    marks = []
    for a, b in [(1, 0), (1, 1), (9, 1), (9, 0)]:
        row = stage.run(plan.bind(reading(a, b)))
        marks.append((row, stage.muting))

    assert marks == [
        ({"gap.gap": 0.0}, False),
        ({"gap.gap": 0.0}, True),
        ({"gap.gap": 1.0}, True),
        ({"gap.gap": 1.0}, False),
    ]
    assert stage.status()["muted"] == 2
    # A learned step skipped the last observation: the stage takes it back.
    stage.run(plan.bind(reading(9, 1)))
    stage.revert()
    assert (stage.muted, stage.muting, stage.accepted) == (2, False, 4)


def test_an_observation_the_detectors_do_not_see_is_not_counted_as_muted():
    # The mute reads the gap behind a Gate and a window that is still filling.
    design = rule_definition(
        before="prepare.mute", before_params={"condition": "gap > 2"}
    ).model_dump(mode="json")
    design["nodes"] += [
        {
            "id": "gate",
            "kind": "transform",
            "component": "prepare.gate",
            "params": {"condition": "gap < 9"},
        },
        {
            "id": "smooth",
            "kind": "transform",
            "component": "prepare.smooth",
            "params": {"window_size": 2},
        },
    ]
    design["edges"] = [
        edge
        for edge in design["edges"]
        if (edge["source"], edge["target"]) != ("before", "rule")
    ] + [
        {"source": "before", "target": "gate"},
        {"source": "gate", "target": "smooth"},
        {"source": "smooth", "target": "rule"},
    ]
    plan = ExecutionPlan(bound(PipelineDefinition.model_validate(design)).pipeline)
    stage = PrepareStage(plan)

    seen = []
    for a in (3, 9, 3, 1, 4):
        row = stage.run(plan.bind(reading(a, 0)))
        seen.append((row if isinstance(row, Withheld) else "scored", stage.muting))

    assert seen == [
        (Withheld("preparing"), False),
        (Withheld("held_back", "gate"), False),
        ("scored", True),
        ("scored", False),
        ("scored", True),
    ]
    assert stage.status()["muted"] == 2


def test_a_condition_that_cannot_be_read_skips_the_observation():
    plan = ExecutionPlan(bound(rule_definition(mute="a / b > 2")).pipeline)
    stage = PrepareStage(plan)

    assert stage.run(plan.bind(reading(6, 2))) == {"gap.gap": 4.0}
    assert stage.muting
    with pytest.raises(PrepareRejected) as rejected:
        stage.run(plan.bind(reading(6, 0)))

    assert (rejected.value.node_id, rejected.value.reason) == (
        "mute",
        "out_of_domain",
    )
    assert (stage.muting, stage.muted, stage.rejected) == (False, 1, 1)


def test_muted_counts_survive_a_checkpoint_and_older_checkpoints_load():
    plan = ExecutionPlan(bound(limit_definition()).pipeline)
    stage = PrepareStage(plan)
    for b in (0, 1, 1, 0, 1):
        stage.run(plan.bind(reading(1, b)))
    state = pickle.loads(pickle.dumps(stage.export_state()))
    assert state["muted"] == 3

    restored = PrepareStage(plan)
    restored.load_state(state)
    assert restored.status() == stage.status()
    # Checkpoints from before Mute alarms steps carry no muted count.
    older = PrepareStage(plan)
    older.load_state({key: value for key, value in state.items() if key != "muted"})
    assert (older.muted, older.accepted) == (0, 5)
    with pytest.raises(ValueError, match="counts are invalid"):
        PrepareStage(plan).load_state({**state, "muted": -1})


def test_diagnostics_say_when_the_condition_holds():
    config = bound(limit_definition()).pipeline
    plan = ExecutionPlan(config)
    stage = PrepareStage(plan)
    diagnostics = PipelineDiagnostics(
        config, DiagnosticLimits(sample_interval_seconds=1e-9)
    )
    diagnostics.external = frozenset(stage.frontier)
    reasons = []
    for index, b in enumerate((0, 1), start=1):
        diagnostics.begin(index, "operational")
        stage.run(plan.bind(reading(1, b)), diagnostics)
        diagnostics.finish()
        step = diagnostics.snapshot()["observation"]["passes"]["learn"]["mute"]
        reasons.append(
            (step["state"], step["output"] == step["input"], step.get("reason"))
        )

    assert reasons == [
        ("ready", True, None),
        ("ready", True, "The condition holds, so no alarm is raised"),
    ]


@pytest.mark.parametrize("others", [(), ("mad",), ("knn",)])
def test_a_threshold_run_scores_a_muted_observation_and_raises_no_alarm(others):
    config = bound(limit_definition(others=others))
    unmuted = bound(rule_definition(others, expression=LIMIT, calibration_window=3))
    service = detector_service_class(config)(config)
    reference = type(service)(unmuted)
    values = [(1, 0)] * 40 + [(9, 0), (9, 1), (1, 1), (9, 0)]
    try:
        results, expected = [], []
        for a, b in values:
            results.append(service.process_data_point(reading(a, b)))
            expected.append(reference.process_data_point(reading(a, b)))
            service.wait_for_background()
            reference.wait_for_background()

        # The mute changes nothing but the alarm: scores and thresholds agree.
        assert [item.anomaly_score for item in results] == [
            item.anomaly_score for item in expected
        ]
        for (_, b), item, plain in zip(values, results, expected, strict=True):
            raised = outcome(plain)
            assert raised in (RAISED, QUIET)
            # Where the condition holds, what the plain run raises is muted.
            assert outcome(item) == (raised if b <= 0 or raised == QUIET else MUTED)
        assert outcome(results[-3]) == MUTED
        assert outcome(results[-1]) == outcome(results[-4]) == RAISED
        assert results[-3].severity == "low"
        assert service.anomaly_count == sum(
            plain.is_anomaly and b <= 0
            for (_, b), plain in zip(values, expected, strict=True)
        )
        assert reference.anomaly_count > service.anomaly_count
        state = PipelineRuntimeState.model_validate(service.get_pipeline_state())
        assert state.preparation is not None
        assert state.preparation.muted == 2
    finally:
        service.shutdown()
        reference.shutdown()


def test_an_adapting_boundary_learns_a_muted_score_and_raises_no_alarm():
    config = bound(rule_definition(mute=MUTE, **BOUNDARY))
    service = BoundaryDetectionService(config)
    reference = BoundaryDetectionService(bound(rule_definition(**BOUNDARY)))
    values = [(math.sin(index / 5), 0) for index in range(CALIBRATION)]
    values += [(0.5, 0), (51, 1), (90, 0), (0.5, 1)]

    results = [service.process_data_point(reading(a, b)) for a, b in values]
    expected = [reference.process_data_point(reading(a, b)) for a, b in values]

    assert [
        (item.anomaly_score, item.context["adaptive_stream"]["threshold"])
        for item in results
    ] == [
        (item.anomaly_score, item.context["adaptive_stream"]["threshold"])
        for item in expected
    ]
    assert [outcome(item) for item in expected[-4:]] == [QUIET, RAISED, RAISED, QUIET]
    assert [outcome(item) for item in results[-4:]] == [QUIET, MUTED, RAISED, QUIET]
    assert (service.anomaly_count, reference.anomaly_count) == (1, 2)
    # The checkpoint keeps the stage's count; the boundary came back as it was.
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    restored = BoundaryDetectionService.from_checkpoint_data(checkpoint, config)
    assert restored.get_pipeline_state()["preparation"]["muted"] == 2
    assert outcome(restored.process_data_point(reading(200, 1))) == MUTED


def test_a_muted_observation_alarms_under_no_compared_calibration_method():
    config = bound(limit_definition())
    service = AdaptiveStreamDetectionService(config)
    service.comparison = CalibrationComparison(
        service.plan, ["fixed_split"], alpha=0.1, consecutive=1
    )

    results = [
        service.process_data_point(reading(a, b))
        for a, b in [(1, 0), (2, 0), (3, 0), (9, 0), (9, 1), (1, 1)]
    ]

    assert [
        item.context["adaptive_stream"].get("method_alarms") for item in results
    ] == [None, None, None, 1, 0, 0]


def decisions(controller, steps):
    seen = []
    for p_value, muted in steps:
        context = controller.update(p_value, muted=muted)
        seen.append(
            (context["alarm_fired"], context["alarm_muted"], context["alarm_active"])
        )
    return seen


def test_a_tracker_raises_a_muted_crossing_when_the_mute_ends():
    controller = tracker()

    # The statistic crosses while muted, stays above and the mute ends.
    assert decisions(
        controller, [(1e-6, True), (1e-6, True), (1e-6, False), (1e-6, False)]
    ) == [
        (False, True, True),
        (False, False, True),
        (True, False, True),
        (False, False, True),
    ]
    assert controller.alarm_count == 1


def test_a_tracker_drops_a_muted_crossing_that_falls_back_first():
    controller = tracker()

    # The statistic is below its threshold after the second p-value of 1.
    seen = decisions(controller, [(1e-6, True), *[(1.0, True)] * 2, (1.0, False)])

    assert seen == [
        (False, True, True),
        (False, False, True),
        (False, False, False),
        (False, False, False),
    ]
    assert controller.alarm_count == 0
    # A later crossing is an alarm of its own.
    assert decisions(controller, [(1e-6, False)]) == [(True, False, True)]


def test_a_tracker_from_before_mute_steps_holds_no_alarm_back():
    controller = tracker()
    for item in controller.trackers:
        del item.__dict__["_held_alarm"]

    restored = pickle.loads(pickle.dumps(controller))

    assert decisions(restored, [(1e-6, False)]) == [(True, False, True)]


def test_a_conformal_run_holds_a_muted_alarm_until_the_mute_ends():
    design = rule_definition(
        mute=MUTE, rule="detector:pyod_iforest", policy="policy.martingale"
    ).model_dump(mode="json")
    design["settings"].update(training_window_size=20, calibration_window_size=5)
    config = bound(PipelineDefinition.model_validate(design))
    service = StaticConformalDetectionService(config)
    service._training_executor = ControlledExecutor()
    fitted = FakeConformalDetector()
    restored = None
    try:
        for index in range(25):
            service.process_data_point(reading(math.sin(index), 0))
        service._training_executor.future.set_result((fitted, tracker()))
        results = []
        for p_value, b in [(1.0, 0), (1e-6, 1), (1e-6, 1)]:
            fitted.p_value = p_value
            results.append(service.process_data_point(reading(1, b)))
        # A checkpoint taken while the alarm is held back keeps it held.
        restored = StaticConformalDetectionService.from_checkpoint_data(
            pickle.loads(pickle.dumps(service.export_checkpoint())), config
        )
        results += [service.process_data_point(reading(1, 0)) for _ in range(2)]
        resumed = restored.process_data_point(reading(1, 0))

        assert [static_outcome(item) for item in results] == [
            QUIET,
            MUTED,
            QUIET,
            RAISED,
            QUIET,
        ]
        assert static_outcome(resumed) == RAISED
        assert [item.severity for item in results] == [
            "low",
            "low",
            "low",
            "critical",
            "low",
        ]
        raised = results[3].context["static_conformal"]
        assert raised["fired_tracker_ids"] == ["primary"]
        assert (service.anomaly_count, restored.anomaly_count) == (1, 1)
        assert service.get_pipeline_state()["preparation"]["muted"] == 2
    finally:
        service.shutdown()
        if restored is not None:
            restored.shutdown()


def test_the_evidence_keeps_a_muted_alarm_and_stores_no_anomaly():
    service = AdaptiveStreamDetectionService(bound(limit_definition()))
    results = [
        service.process_data_point(reading(a, b))
        for a, b in [(1, 0), (2, 0), (3, 0), (9, 1), (9, 0)]
    ]
    stamp = "2026-08-06T10:00:00Z"
    for item in results:
        item.context["alignment"] = {
            "aligned_vector": True,
            "required_sensors": list(KEYS.values()),
            "input_timestamps": dict.fromkeys(KEYS.values(), stamp),
        }
    projector = ResultProjector(service_id="monitor")

    muted, raised = (projector.prepare(item) for item in results[-2:])

    assert [(row["alarm"], row["muted"]) for row in muted.evidence] == [(False, True)]
    assert muted.anomalies == []
    assert [(row["alarm"], row["muted"]) for row in raised.evidence] == [(True, False)]
    assert len(raised.anomalies) == 1
