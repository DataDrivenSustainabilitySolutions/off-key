import pytest

from off_key_tactic_middleware.config import (
    TacticSettings,
    RadarDefaultsConfig,
)


def test_split_constraints_parses_csv():
    settings = TacticSettings(
        TACTIC_DOCKER_DEFAULT_CONSTRAINTS=" 'node.role == worker' , rack==1,,"
    )
    assert settings._parse_default_constraints() == ["node.role == worker", "rack==1"]


def test_threshold_ordering_validation():
    with pytest.raises(ValueError):
        RadarDefaultsConfig(
            anomaly_threshold_medium=0.9,
            anomaly_threshold_high=0.5,
            anomaly_threshold_critical=0.7,
        )
