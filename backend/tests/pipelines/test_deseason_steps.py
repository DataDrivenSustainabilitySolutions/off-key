"""Deseason: each feature less its usual level at this time of day or week."""

import math
import pickle
import random
from datetime import UTC, datetime
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from off_key_core.models.pipeline_prepare import (
    default_suffix,
    kernel,
    prepared_bounds,
    reads_time,
)
from off_key_core.models.pipelines import compile_pipeline, validate_pipeline
from off_key_core.schemas.pipelines import (
    DeseasonParameters,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import PrepareStage
from pydantic import ValidationError

from tests.support.pipelines import template

pytestmark = pytest.mark.radar_integration

# A Monday at midnight UTC.
MONDAY = datetime(2026, 1, 5, tzinfo=UTC).timestamp()
HOUR = 3600.0


def daily(hour):
    return 10 * math.sin(2 * math.pi * (hour % 24) / 24)


def run(step, values, start=MONDAY, spacing=HOUR):
    state, outputs = step.initial(), []
    for index, value in enumerate(values):
        before = pickle.dumps(state)
        state, output = step.advance(state, value, start + index * spacing)
        assert step.accepts(state)
        # The earlier state is left as it was, so a rejection can keep it.
        assert pickle.dumps(pickle.loads(before)) == before
        outputs.append(output)
    return state, outputs


def test_a_daily_pattern_is_taken_out_after_one_day():
    step = kernel("prepare.deseason", {})
    state, outputs = run(step, [daily(hour) for hour in range(24 * 10)])
    assert all(item is None for item in outputs[:24])
    assert step.waiting(step.initial()) and not step.waiting(state)
    assert max(abs(item) for item in outputs[24:]) < 1e-9
    assert (
        default_suffix("prepare.deseason", {}),
        reads_time("prepare.deseason", {}),
    ) == (
        "deseasoned",
        True,
    )
    assert prepared_bounds("prepare.deseason", {}, (-1.0, 4.0)) == (-5.0, 5.0)
    assert prepared_bounds("prepare.deseason", {}, (None, 4.0)) == (None, None)


def test_an_unusual_day_stands_out_and_barely_moves_the_profile():
    step = kernel("prepare.deseason", {})
    noise = random.Random(3)
    values = [daily(hour) + noise.gauss(0, 0.5) for hour in range(24 * 21)]
    for hour in range(24 * 14, 24 * 15):
        values[hour] += 40
    _, outputs = run(step, values)
    unusual = outputs[24 * 14 : 24 * 15]
    assert min(unusual) > 30
    # Four spreads at most move each slot, so the next day is near its usual.
    assert max(abs(item) for item in outputs[24 * 15 : 24 * 16]) < 5
    assert max(abs(item) for item in outputs[24 * 20 :]) < 2


def test_a_weekly_pattern_keeps_weekdays_and_weekends_apart():
    def level(hour):
        weekend = (hour // 24) % 7 >= 5
        return 1.0 if weekend else 20.0 + daily(hour)

    weekly = kernel("prepare.deseason", {"cycle": "week"})
    _, by_week = run(weekly, [level(hour) for hour in range(24 * 7 * 4)])
    daily_only = kernel("prepare.deseason", {})
    _, by_day = run(daily_only, [level(hour) for hour in range(24 * 7 * 4)])
    later = slice(24 * 7 * 2, None)
    assert max(abs(item) for item in by_week[later]) < 1e-9
    assert max(abs(item) for item in by_day[later]) > 5


def test_with_trend_a_drifting_series_keeps_its_pattern_and_a_shift_shows():
    noise = random.Random(5)
    # A daily pattern on a drift of 0.5 per hour, 120 over the twenty days.
    values = [daily(hour) + 0.5 * hour + noise.gauss(0, 0.3) for hour in range(24 * 20)]
    plain = kernel("prepare.deseason", {"memory": 3})
    _, without = run(plain, values)
    trended = kernel("prepare.deseason", {"trend": True, "memory": 3})
    state, outputs = run(trended, values)
    later = slice(24 * 14, None)
    # Without trend the drift piles up in the output; with it, once the levels
    # have settled on the trend, the output is near the noise.
    assert sum(without[later]) / len(without[later]) > 10
    assert max(abs(item) for item in outputs[later]) < 1.5
    assert len(state[0]) == 3 and trended.window == 3 * 24 + 3
    assert prepared_bounds("prepare.deseason", {"trend": True}, (-1.0, 4.0)) == (
        None,
        None,
    )
    # A step of 20 the trend has not followed yet shows at once.
    after = [daily(hour) + 0.5 * hour + 20 for hour in range(24 * 20, 24 * 20 + 3)]
    _, shifted = run(trended, [*values, *after])
    assert min(shifted[-3:]) > 15


def test_a_daily_and_a_weekly_step_stack():
    def level(hour):
        weekend = (hour // 24) % 7 >= 5
        return daily(hour) + (0.0 if weekend else 15.0)

    values = [level(hour) for hour in range(24 * 7 * 5)]
    day = kernel("prepare.deseason", {})
    week = kernel("prepare.deseason", {"cycle": "week", "slot_minutes": 360})
    _, by_day = run(day, values)
    state, outputs = week.initial(), []
    for hour, value in enumerate(by_day):
        if value is not None:
            state, value = week.advance(state, value, MONDAY + hour * HOUR)
        outputs.append(value)
    # The day step leaves most of the weekday shift of 15; the week step on its
    # output takes out what repeats each week. A little stays, because the
    # daily levels themselves move between weekdays and weekends.
    later = slice(24 * 7 * 3, None)
    assert max(abs(item) for item in by_day[later]) > 10
    assert max(abs(item) for item in outputs[later]) < 3


def test_the_cycle_follows_the_clock_of_its_time_zone():
    berlin = ZoneInfo("Europe/Berlin")
    step = kernel("prepare.deseason", {"timezone": "Europe/Berlin", "memory": 2})
    # A value that follows Berlin's hour, across the change to summer time.
    start = datetime(2026, 3, 20, tzinfo=UTC).timestamp()
    values = [
        float(datetime.fromtimestamp(start + hour * HOUR, berlin).hour)
        for hour in range(24 * 20)
    ]
    _, outputs = run(step, values, start=start)
    assert max(abs(item) for item in outputs[24:]) < 1e-9


def test_settings_divide_a_day_and_name_a_known_clock():
    assert DeseasonParameters().model_dump() == {
        "apply_to": None,
        "result": "replace",
        "suffix": None,
        "cycle": "day",
        "slot_minutes": 60,
        "memory": 7,
        "timezone": "UTC",
        "trend": False,
    }
    with pytest.raises(ValidationError, match="divides a day"):
        DeseasonParameters(slot_minutes=7)
    with pytest.raises(ValidationError, match="Unknown time zone"):
        DeseasonParameters(timezone="Mars/Olympus")
    assert (
        kernel("prepare.deseason", {"cycle": "week", "slot_minutes": 5}).slots == 2016
    )


def design(steps):
    data = template("adaptive_stream").model_dump(mode="json")
    data["input_slots"] = [{"id": "a", "label": "A"}]
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


STEP = [("deseason", "prepare.deseason", {"memory": 3})]


def test_a_deseason_step_replaces_its_feature_and_carries_time():
    result = validate_pipeline(design(STEP))
    assert result.valid, result.issues
    assert [item.name for item in result.features["deseason"]] == ["a"]
    # It carries time, so the forest after it is not warned about raw values.
    assert "point_detector_without_time" not in {item.code for item in result.issues}


def test_the_stage_waits_a_cycle_and_resumes_identically():
    definition = compile_pipeline(design(STEP)).definition
    bindings = [
        dict(
            slot_id="a",
            reading_id="a",
            entity_id="entity",
            accepted_topic="telemetry/entity/a",
            input_key="a",
        )
    ]
    from off_key_core.models.pipelines import execution_fingerprint

    config = PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )
    stage = PrepareStage(ExecutionPlan(config))
    outputs = []
    for hour in range(30):
        outputs.append(stage.run({"a": daily(hour)}, timestamp=MONDAY + hour * HOUR))
        assert stage.ready == isinstance(outputs[-1], dict)
    assert not isinstance(outputs[23], dict)
    assert abs(outputs[24]["deseason.a"]) < 1e-9
    restored = PrepareStage(ExecutionPlan(config))
    restored.load_state(pickle.loads(pickle.dumps(stage.export_state())))
    later = MONDAY + 30 * HOUR
    assert restored.run({"a": 3.0}, timestamp=later) == stage.run(
        {"a": 3.0}, timestamp=later
    )
