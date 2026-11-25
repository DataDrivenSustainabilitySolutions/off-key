"""The design check names the warm-up RADAR will require, before a run starts."""

import pytest
from aberrant.catalog import DetectorConfig
from off_key_core.models.adaptive import ADAPTIVE_MODELS_BY_TYPE, detector_warmup

CASES = [
    ("aberrant_half_space_trees", {}),
    ("aberrant_half_space_trees", {"window_size": 100}),
    ("aberrant_half_space_trees", {"window_size": 2}),
    ("aberrant_rhf", {"window_size": 50}),
    ("aberrant_asd_isolation_forest", {}),
    ("aberrant_asd_isolation_forest", {"window_size": 100}),
    ("aberrant_asd_isolation_forest", {"max_samples": 2}),
    ("aberrant_asd_isolation_forest", {"max_samples": 64, "window_size": 64}),
    ("aberrant_random_cut_forest", {"sample_size": 64}),
    ("aberrant_random_cut_forest", {"sample_size": 256, "warm_up": 100}),
    ("aberrant_random_cut_forest", {"sample_size": 64, "warm_up": 300}),
    ("aberrant_xstream", {}),
    ("aberrant_xstream", {"window_size": 64, "warm_up": 128}),
    ("aberrant_moving_zscore", {}),
    ("aberrant_moving_zscore", {"window_size": 50}),
    ("aberrant_moving_mad", {"window_size": 50, "warm_up": 10}),
    ("aberrant_damp", {"subsequence_length": 32}),
    ("aberrant_damp", {"subsequence_length": 10, "start_index": 100}),
    ("aberrant_online_ecod", {}),
    ("aberrant_online_copod", {"warm_up": 10}),
    ("aberrant_loda", {}),
    ("aberrant_loda", {"warm_up": 20}),
]


@pytest.mark.parametrize(("model_type", "params"), CASES)
def test_the_estimate_matches_what_aberrant_requires(model_type, params):
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    # RADAR builds a detector from its preset defaults and the settings given.
    settings = definition["default_parameters"] | params
    config = DetectorConfig.from_mapping(
        {"version": 2, "model": {"id": definition["catalog_id"], "params": settings}}
    ).resolve()
    assert detector_warmup(model_type, params) == config.capabilities.warmup


def test_an_unknown_warmup_is_left_to_radar():
    assert detector_warmup("aberrant_online_isolation_forest", {}) == 0
    assert detector_warmup("not_a_model", {}) == 0
