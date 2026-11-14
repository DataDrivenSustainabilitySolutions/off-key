"""The design check names the warm-up RADAR will require, before a run starts."""

import pytest
from aberrant.catalog import DetectorConfig
from off_key_core.models.adaptive import ADAPTIVE_MODELS_BY_TYPE, detector_warmup

CASES = [
    ("aberrant_half_space_trees", {}),
    ("aberrant_half_space_trees", {"window_size": 100}),
    ("aberrant_stream_random_histogram_forest", {"window_size": 50}),
    ("aberrant_asd_isolation_forest", {}),
    ("aberrant_asd_isolation_forest", {"window_size": 100}),
    ("aberrant_asd_isolation_forest", {"max_samples": 2}),
    ("aberrant_asd_isolation_forest", {"max_samples": 64, "window_size": 32}),
    ("aberrant_half_space_trees", {"window_size": 2}),
    ("aberrant_random_cut_forest", {"sample_size": 64}),
    ("aberrant_random_cut_forest", {"sample_size": 256, "warmup_samples": 100}),
    ("aberrant_random_cut_forest", {"sample_size": 64, "warmup_samples": 300}),
    ("aberrant_x_stream", {"window_size": 300}),
    ("aberrant_x_stream", {"window_size": 64, "init_sample_size": 128}),
    ("aberrant_seasonal_residual_detector", {"season_length": 24}),
]


@pytest.mark.parametrize(("model_type", "params"), CASES)
def test_the_estimate_matches_what_aberrant_requires(model_type, params):
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    config = DetectorConfig.from_mapping(
        {"version": 1, "model": {"id": definition["catalog_id"], "params": params}}
    ).resolve()
    assert detector_warmup(model_type, params) == config.capabilities.warmup.minimum


def test_an_unknown_warmup_is_left_to_radar():
    assert detector_warmup("aberrant_online_isolation_forest", {}) == 0
    assert detector_warmup("not_a_model", {}) == 0
