"""Stand-ins that put a conformal run where a test needs it."""

import concurrent.futures

from off_key_core.schemas.radar import StaticMartingaleConfig
from off_key_mqtt_radar.martingales import MartingaleAlarmController


class FakeConformalDetector:
    """Gives the p-value a test sets for the next observation."""

    last_features = None
    p_value = 1.0

    def compute_p_values(self, _matrix):
        return [self.p_value]


class ControlledExecutor:
    def __init__(self):
        self.future: concurrent.futures.Future = concurrent.futures.Future()

    def submit(self, *_args, **_kwargs):
        return self.future

    def shutdown(self, *_args, **_kwargs):
        return None


def tracker(threshold: float = 100.0) -> MartingaleAlarmController:
    """One restarted martingale that a p-value of 1e-6 takes above its threshold."""
    return MartingaleAlarmController.from_config(
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "primary",
                    "betting_function": "power",
                    "alarm_statistic": "restarted_martingale",
                    "threshold_config": {"mode": "manual", "value": threshold},
                    "epsilon": 0.5,
                }
            ]
        )
    )
