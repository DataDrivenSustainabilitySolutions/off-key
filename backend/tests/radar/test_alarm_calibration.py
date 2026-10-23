"""Tests for finite-horizon automatic martingale threshold calibration."""

import pickle
from typing import get_args

import numpy as np
import pytest
from off_key_core.schemas.radar import MartingaleTrackerConfig, StaticMartingaleConfig
from off_key_mqtt_radar.alarm_calibration import (
    _calibrated_threshold,
    _maximum_log_statistic,
    _simulate_split_conformal_p_values,
    resolve_tracker_thresholds,
)
from off_key_mqtt_radar.betting import BETTING_FUNCTIONS
from off_key_mqtt_radar.martingales import MartingaleAlarmController

SCHEMA_BETTING_FUNCTIONS = sorted(
    get_args(tracker.model_fields["betting_function"].annotation)[0]
    for tracker in get_args(get_args(MartingaleTrackerConfig)[0])
)


def _automatic_tracker(
    *,
    tracker_id: str,
    betting_function: str,
    alarm_statistic: str,
) -> dict:
    tracker = {
        "tracker_id": tracker_id,
        "betting_function": betting_function,
        "alarm_statistic": alarm_statistic,
        "threshold_config": {"mode": "automatic"},
    }
    if betting_function == "power":
        tracker["epsilon"] = 0.4
    elif betting_function == "simple_mixture":
        tracker["n_grid"] = 8
        tracker["min_epsilon"] = 0.05
    else:
        tracker["jump"] = 0.03
    return tracker


@pytest.mark.parametrize(
    ("betting_function", "alarm_statistic"),
    [
        (betting_function, alarm_statistic)
        for betting_function in SCHEMA_BETTING_FUNCTIONS
        for alarm_statistic in ("cusum", "shiryaev_roberts")
    ],
)
def test_vectorized_calibration_replays_native_martingale_recurrences(
    betting_function,
    alarm_statistic,
):
    from nonconform.martingales import AlarmConfig

    config = StaticMartingaleConfig(
        trackers=[
            _automatic_tracker(
                tracker_id="automatic",
                betting_function=betting_function,
                alarm_statistic=alarm_statistic,
            )
        ],
        automatic_threshold_calibration={
            "false_alarm_probability": 0.1,
            "horizon": 12,
            "simulation_count": 100,
        },
    )
    tracker = config.trackers[0]
    p_values = _simulate_split_conformal_p_values(
        calibration_size=17,
        horizon=12,
        simulation_count=6,
        rng=np.random.default_rng(1234),
    )

    actual = _maximum_log_statistic(p_values, tracker)
    expected = []
    for path in p_values:
        native = BETTING_FUNCTIONS[betting_function].build(tracker, AlarmConfig())
        expected.append(
            max(
                getattr(native.update(float(p_value)), f"log_{alarm_statistic}")
                for p_value in path
            )
        )

    assert actual == pytest.approx(expected)


def test_every_schema_betting_function_has_a_runtime_entry():
    assert sorted(BETTING_FUNCTIONS) == SCHEMA_BETTING_FUNCTIONS


@pytest.mark.parametrize("betting_function", SCHEMA_BETTING_FUNCTIONS)
def test_tracker_pickles_hold_only_their_own_state(betting_function):
    config = StaticMartingaleConfig(
        trackers=[
            {
                **_automatic_tracker(
                    tracker_id="primary",
                    betting_function=betting_function,
                    alarm_statistic="cusum",
                ),
                "threshold_config": {"mode": "manual", "value": 5.0},
            }
        ]
    )
    controller = MartingaleAlarmController.from_config(config)
    controller.update(0.2)
    tracker = controller.trackers[0]

    # Checkpoints pickle these controllers; the attribute set is the contract.
    assert sorted(vars(tracker)) == [
        "_alarm_active",
        "_martingale",
        "alarm_count",
        "config",
        "tested_count",
        "threshold",
        "threshold_horizon",
        "threshold_window_position",
    ]
    restored = pickle.loads(pickle.dumps(controller))
    assert restored.update(0.01) == controller.update(0.01)
    assert restored.tested_count == 2


def test_threshold_resolution_is_deterministic_and_builds_mixed_ensemble():
    config = StaticMartingaleConfig(
        trackers=[
            {
                "tracker_id": "manual",
                "betting_function": "power",
                "alarm_statistic": "restarted_martingale",
                "threshold_config": {"mode": "manual", "value": 100},
            },
            _automatic_tracker(
                tracker_id="cusum",
                betting_function="simple_mixture",
                alarm_statistic="cusum",
            ),
            _automatic_tracker(
                tracker_id="sr",
                betting_function="simple_jumper",
                alarm_statistic="shiryaev_roberts",
            ),
        ],
        automatic_threshold_calibration={
            "false_alarm_probability": 0.1,
            "horizon": 20,
            "simulation_count": 100,
        },
    )

    first = resolve_tracker_thresholds(config, calibration_size=25, seed=42)
    second = resolve_tracker_thresholds(config, calibration_size=25, seed=42)

    assert first == second
    assert first["manual"] == 100.0
    assert all(np.isfinite(value) and value > 0.0 for value in first.values())

    controller = MartingaleAlarmController.from_config(config, first)
    result = controller.update(0.5)
    assert [item["tracker_id"] for item in result["tracker_results"]] == [
        "manual",
        "cusum",
        "sr",
    ]


def test_stricter_false_alarm_target_never_reduces_threshold():
    tracker = _automatic_tracker(
        tracker_id="cusum",
        betting_function="power",
        alarm_statistic="cusum",
    )
    common = {
        "horizon": 20,
        "simulation_count": 200,
    }
    lenient = StaticMartingaleConfig(
        trackers=[tracker],
        automatic_threshold_calibration={
            **common,
            "false_alarm_probability": 0.2,
        },
    )
    strict = StaticMartingaleConfig(
        trackers=[tracker],
        automatic_threshold_calibration={
            **common,
            "false_alarm_probability": 0.05,
        },
    )

    lenient_threshold = resolve_tracker_thresholds(
        lenient,
        calibration_size=30,
        seed=7,
    )["cusum"]
    strict_threshold = resolve_tracker_thresholds(
        strict,
        calibration_size=30,
        seed=7,
    )["cusum"]

    assert strict_threshold >= lenient_threshold


def test_calibrated_threshold_is_strictly_above_linear_cutoff():
    # This value is a regression case where nudging in log space is lost when
    # exponentiated back to the linear statistic used by the runtime.
    log_cutoff = -0.038046877934107215
    linear_cutoff = float(np.exp(log_cutoff))

    threshold = _calibrated_threshold(
        np.full(100, log_cutoff),
        false_alarm_probability=0.1,
    )

    assert threshold == np.nextafter(linear_cutoff, float("inf"))
    assert threshold > linear_cutoff


def test_automatic_tracker_resets_at_each_calibrated_horizon():
    horizon = 10
    config = StaticMartingaleConfig(
        trackers=[
            {
                "tracker_id": "sr",
                "betting_function": "power",
                "alarm_statistic": "shiryaev_roberts",
                "threshold_config": {"mode": "automatic"},
                "epsilon": 1.0,
            }
        ],
        automatic_threshold_calibration={
            "false_alarm_probability": 0.1,
            "horizon": horizon,
            "simulation_count": 100,
        },
    )
    thresholds = resolve_tracker_thresholds(
        config,
        calibration_size=20,
        seed=42,
    )
    controller = MartingaleAlarmController.from_config(config, thresholds)

    tracker_results = [
        controller.update(0.5)["tracker_results"][0] for _ in range(2 * horizon + 5)
    ]

    assert np.isfinite(thresholds["sr"])
    assert not any(result["alarm_fired"] for result in tracker_results)
    assert [result["threshold_window_reset"] for result in tracker_results].count(
        True
    ) == 2
    assert tracker_results[horizon]["statistic_value"] == pytest.approx(1.0)
    assert tracker_results[horizon]["threshold_window_position"] == 1
    assert tracker_results[-1]["threshold_window_position"] == 5
    assert controller.tested_count == 2 * horizon + 5


def test_automatic_controller_requires_calibration_result():
    config = StaticMartingaleConfig(
        trackers=[
            _automatic_tracker(
                tracker_id="cusum",
                betting_function="power",
                alarm_statistic="cusum",
            )
        ]
    )

    with pytest.raises(ValueError, match="requires automatic threshold calibration"):
        MartingaleAlarmController.from_config(config)
