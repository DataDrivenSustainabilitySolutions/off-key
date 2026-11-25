"""What the composer says about each detector, for whoever chooses one.

The detectors' own catalogs carry class names and constructor schemas. Here is a
plain name, one line on what the detector is good at and what it costs, the
settings worth a first look, and help for every setting. A test keeps this
complete as detectors are added, so none reaches the composer without it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DetectorGuide:
    label: str
    description: str
    # The settings listed first; every other one sits under More settings.
    key: tuple[str, ...]
    # Help where the shared text for a setting's name does not fit. A nested
    # setting is named with its parent, such as threshold_config.value.
    settings: Mapping[str, str] = field(default_factory=dict)


_TREES = "Trees in the forest. More give steadier scores and cost time and memory."
_WINDOW = (
    "Recent observations the detector keeps. A longer window is steadier and "
    "slower to adapt."
)
_REPLACED_WINDOW = (
    "Observations per window. Each completed window replaces what the detector "
    "compares against."
)
_PROFILE_WINDOW = (
    "Values kept to compare against. Empty uses 16 times the subsequence length."
)
_SEASON = "Observations in one cycle, such as 24 for hourly values with a daily rhythm."

# The settings online ECOD and COPOD share.
_TAILS = {
    "memory": (
        "How each feature's distribution is kept: a sketch of everything seen, "
        "a window of recent values, or both."
    ),
    "window_size": "Recent values kept per feature, with a window.",
    "half_life": (
        "Observations after which a value counts half in the sketch. Empty "
        "keeps everything alike."
    ),
    "compression": "Detail of the sketch. More is closer and costs memory.",
    "tail": "Read the tails as they are, or fit a Pareto tail beyond a quantile.",
    "tail_quantile": "Where the fitted Pareto tail starts.",
    "warm_up": "Observations before scores start.",
    "aggregation": (
        "Combine the features' tail scores as the paper does, or as PyOD does."
    ),
}

# Help for a setting by its name, where a detector's own schema has none.
SETTINGS: dict[str, str] = {
    "window_size": _WINDOW,
    "seed": "Seed for the random choices. Empty uses the design's seed.",
    "n_estimators": _TREES,
    "n_trees": _TREES,
    "bias": "Divide by the number of observations when on, by one less when off.",
    "lead": (
        "How many observations ahead a forecast is made. It is compared with "
        "the value that arrives then."
    ),
    "score": (
        "Scaled divides the miss by the typical forecast error; absolute "
        "reports it in the feature's units."
    ),
    "min_scale": (
        "Smallest spread a miss is divided by, in the feature's units. It keeps "
        "a flat signal from scoring every small miss."
    ),
    "residual_alpha": (
        "How fast the typical forecast error follows new errors, above 0 up to 1."
    ),
    "season_length": _SEASON,
    "alpha": "How fast the level follows new values, from 0 to 1.",
    "beta": "How fast the trend follows new values, from 0 to 1.",
    "gamma": (
        "How fast the cycle follows new values, from 0 to 1 minus the level weight."
    ),
    "subsequence_length": "Consecutive values compared as one shape.",
    "normalize": (
        "Compare shapes regardless of level and amplitude. Off also scores "
        "changes of level."
    ),
    "exclusion_zone": (
        "Earlier stretches that start this close to the latest one are not "
        "compared. Empty uses a quarter of the subsequence length."
    ),
}

_ONE = "For one feature"
_MOVING = ("window_size",)


DETECTORS: dict[str, DetectorGuide] = {
    # Fitted once on the training window.
    "pyod_iforest": DetectorGuide(
        "Isolation forest",
        "Score by how easily random splits isolate an observation. A fast, "
        "robust first choice for several features.",
        ("n_estimators",),
    ),
    "pyod_knn": DetectorGuide(
        "k-nearest neighbors",
        "Score by the distance to the nearest training observations. Finds "
        "isolated points; slower on long training windows.",
        ("n_neighbors", "method"),
    ),
    "pyod_lof": DetectorGuide(
        "Local outlier factor",
        "Score by how sparse the surroundings are compared with those of the "
        "neighbors. Finds points that are unusual for their region.",
        ("n_neighbors",),
    ),
    "pyod_ocsvm": DetectorGuide(
        "One-class SVM",
        "Score by the distance from a boundary learned around the training "
        "data. Fits curved shapes; slow on long training windows.",
        ("kernel", "nu"),
    ),
    "pyod_hbos": DetectorGuide(
        "Histogram-based outlier score",
        "Score each feature by how rare its value is in a histogram. Very "
        "fast; does not see relations between features.",
        ("n_bins",),
    ),
    "pyod_pca": DetectorGuide(
        "Principal components",
        "Score by the distance from the main directions of the training data. "
        "For features that move together.",
        ("n_components",),
        {
            "n_components": "Directions to keep. Empty keeps all of them.",
            "weighted": (
                "Weigh each direction's distance by how little the training "
                "data varies along it."
            ),
            "standardization": "Scale every feature to unit variance first.",
        },
    ),
    # Learning continuously.
    "aberrant_asd_isolation_forest": DetectorGuide(
        "Sliding-window isolation forest",
        "Retrain an isolation forest on a recent window at fixed intervals. "
        "Steady between retrains; follows a drift only at the next one.",
        ("window_size", "retrain_interval", "n_trees"),
        {
            "max_samples": "Observations from the window used to build each tree.",
            "window_size": (
                "Recent observations kept for retraining. Empty uses the "
                "samples per tree."
            ),
            "retrain_interval": (
                "New observations between retrains. Empty retrains once per window."
            ),
        },
    ),
    "aberrant_half_space_trees": DetectorGuide(
        "Half-space trees",
        "Count how often recent observations fall into random regions of the "
        "feature space. Very fast; expects features scaled to 0 to 1.",
        ("n_trees", "height", "window_size"),
        {
            "height": (
                "Depth of each tree. Deeper trees separate finer regions and "
                "need more data."
            ),
            "window_size": (
                "Observations per reference window. The counts start over after each."
            ),
        },
    ),
    "aberrant_holt_winters_forecaster": DetectorGuide(
        "Holt-Winters forecaster",
        "Forecast from a level, a trend and a repeating cycle, and score the miss.",
        ("season_length", "lead"),
    ),
    "aberrant_adaptive_one_class_svm": DetectorGuide(
        "Adaptive-kernel one-class SVM",
        "Keep a budget of support vectors and tune the kernel width to recent "
        "data. Follows curved shapes at a higher cost per observation. "
        "Experimental.",
        ("nu", "sv_budget"),
        {
            "nu": "Scale of the support-vector weights, above 0 up to 1.",
            "initial_gamma": "Kernel width the model starts from.",
            "gamma_bounds": (
                "Smallest and largest kernel width the adaptation may reach."
            ),
            "adaptation_rate": (
                "How far each adaptation moves the kernel width toward its "
                "estimate, above 0 up to 1."
            ),
            "buffer_size": "Recent observations used to estimate the kernel width.",
            "sv_budget": (
                "Most support vectors kept. More follow finer shapes and cost "
                "more per observation."
            ),
            "tolerance": (
                "Margin within which an observation counts as inside the boundary."
            ),
        },
    ),
    "aberrant_knn": DetectorGuide(
        "k-nearest neighbors",
        "Score by the mean distance to the nearest recent observations. "
        "Simple and exact; the cost grows with the window.",
        ("k", "window_size"),
        {
            "k": "Neighbors the distance is averaged over.",
            "window_size": "Recent observations kept to search in.",
        },
    ),
    "aberrant_local_outlier_factor": DetectorGuide(
        "Local outlier factor",
        "Score by how sparse the surroundings are compared with those of the "
        "neighbors in a recent window. Finds points unusual for their region.",
        ("k", "window_size"),
        {
            "k": "Neighbors used to estimate how dense the surroundings are.",
            "distance": (
                "How distance is measured: in a straight line (euclidean) or "
                "along the axes (manhattan)."
            ),
        },
    ),
    "aberrant_mondrian_isolation_forest": DetectorGuide(
        "Mondrian isolation forest",
        "Isolation scores from trees that grow with every observation. Adapts "
        "at once; set a window to bound its memory.",
        ("n_trees", "window_size"),
        {
            "subspace_size": "Features each tree samples.",
            "lifetime": (
                "Lifetime budget of the trees. Larger values allow more splits."
            ),
            "window_size": (
                "Rebuild the trees from this many recent observations. Empty "
                "learns for the whole run, and memory then keeps growing."
            ),
        },
    ),
    "aberrant_moving_zscore": DetectorGuide(
        "Moving z-score",
        "Score how many standard deviations a new value lies from the mean of "
        f"a recent window. {_ONE} with a stable level; very fast.",
        ("window_size", "warm_up"),
        {
            "warm_up": (
                "Values learned before scores start. Empty waits for a full window."
            ),
            "min_std": (
                "Smallest spread a value is divided by. It keeps a flat signal "
                "from scoring every small change."
            ),
        },
    ),
    "aberrant_moving_mad": DetectorGuide(
        "Moving median deviation",
        "Score how far a new value lies from the median of a recent window, "
        f"measured in its median absolute deviation. {_ONE}; a few outliers "
        "barely move it.",
        ("window_size", "warm_up"),
        {
            "warm_up": (
                "Values learned before scores start. Empty waits for a full window."
            ),
            "min_mad": (
                "Smallest deviation a value is divided by. It keeps a flat "
                "signal from scoring every small change."
            ),
        },
    ),
    "aberrant_moving_correlation_coefficient": DetectorGuide(
        "Moving correlation",
        "Score how much a new observation changes the correlation of two "
        "features over a recent window. For exactly two features that move "
        "together.",
        _MOVING,
    ),
    "aberrant_moving_covariance": DetectorGuide(
        "Moving covariance",
        "Score how much a new observation changes the covariance of two "
        "features over a recent window. For exactly two features.",
        _MOVING,
    ),
    "aberrant_moving_mahalanobis_distance": DetectorGuide(
        "Moving Mahalanobis distance",
        "Score the distance from the recent mean, measured in the spread and "
        "correlation of the features. A simple, strong baseline for several "
        "related features.",
        _MOVING,
    ),
    "aberrant_multivariate_rolling_matrix_profile": DetectorGuide(
        "Matrix profile, several features",
        "Score how unlike the latest stretch of values is to every earlier "
        "stretch in the window, across all features at once. Finds unusual "
        "shapes; costs more per observation.",
        ("subsequence_length", "window_size"),
        {"window_size": _PROFILE_WINDOW},
    ),
    "aberrant_online_isolation_forest": DetectorGuide(
        "Online isolation forest",
        "Isolation trees that learn each observation and forget the oldest. A "
        "strong general choice for several features.",
        ("n_trees", "window_size", "max_leaf_samples"),
        {
            "max_leaf_samples": "Observations a leaf holds before it may split.",
            "tree_type": (
                "Fixed keeps that leaf size at every depth; adaptive doubles "
                "it with each level."
            ),
            "subsample": (
                "Share of the observations each tree learns, above 0 up to 1."
            ),
            "window_size": (
                "Recent observations the trees keep. Older ones are unlearned."
            ),
            "branching_factor": "Children created at each split.",
            "metric": "Geometry of the splits. Only axis-parallel is available.",
        },
    ),
    "aberrant_random_cut_forest": DetectorGuide(
        "Random cut forest",
        "Score by how much an observation would change a forest of random "
        "cuts over a recent sample. Robust on noisy streams; shingles catch "
        "short patterns.",
        ("n_trees", "sample_size", "shingle_size"),
        {
            "sample_size": "Most recent points each tree holds.",
            "shingle_size": (
                "Consecutive observations joined into one point, to score "
                "short patterns. 1 scores single observations."
            ),
            "warm_up": "Points before scores start. Empty waits for a full sample.",
        },
    ),
    "aberrant_damp": DetectorGuide(
        "DAMP discords",
        "Score how unlike the latest stretch of values is to its nearest match "
        "far back, fast. Finds odd shapes made of normal values in one feature.",
        ("subsequence_length", "x_lag"),
        {
            "subsequence_length": (
                "Values in one stretch: about one cycle, or the length of the "
                "shape an anomaly takes."
            ),
            "x_lag": (
                "Values searched back for a match. Empty uses 16 times the "
                "subsequence length."
            ),
            "start_index": (
                "Value at which scoring starts. Empty starts four subsequences in."
            ),
            "min_std": "Smallest spread a stretch may have; flatter ones are skipped.",
        },
    ),
    "aberrant_online_ecod": DetectorGuide(
        "Online ECOD",
        "Score how far into the tails of each feature's own distribution the "
        "values fall. Has nothing to tune and suits many features; treats them "
        "as unrelated.",
        ("memory", "warm_up"),
        _TAILS,
    ),
    "aberrant_online_copod": DetectorGuide(
        "Online COPOD",
        "Like online ECOD, with the tails combined as a copula. Has nothing to "
        "tune and suits many features.",
        ("memory", "warm_up"),
        _TAILS,
    ),
    "aberrant_loda": DetectorGuide(
        "LODA",
        "Score how rare an observation is in many random one-dimensional views, "
        "each with its own histogram. Fast on many features.",
        ("n_projections", "warm_up"),
        {
            "n_projections": "Random views. More give steadier scores and cost time.",
            "n_bins": "Bins of each view's histogram.",
            "sparsity": (
                "Share of features each view leaves out. Empty uses the paper's "
                "choice for the number of features."
            ),
            "warm_up": (
                "Observations that fix the histograms' bins before scores start."
            ),
            "decay": (
                "How much the histograms keep of the past at each observation; "
                "1 keeps everything."
            ),
            "pseudocount": "Count every bin starts with, so no bin is impossible.",
        },
    ),
    "aberrant_rolling_matrix_profile": DetectorGuide(
        "Matrix profile",
        "Score how unlike the latest stretch of values is to every earlier "
        f"stretch in the window. {_ONE} with repeating shapes.",
        ("subsequence_length", "window_size"),
        {"window_size": _PROFILE_WINDOW},
    ),
    "aberrant_seasonal_naive_forecaster": DetectorGuide(
        "Seasonal naive forecaster",
        "Forecast the value of one cycle ago, and score the miss.",
        ("season_length", "lead"),
        {"season_length": "Observations in one cycle. 1 repeats the last value."},
    ),
    "aberrant_rhf": DetectorGuide(
        "Random histogram forest",
        "Trees that split where the values are most heavy-tailed, replaced "
        "with each new window. Good at rare extremes across several features.",
        ("n_trees", "window_size"),
        {
            "max_depth": "Deepest level of each tree.",
            "window_size": _REPLACED_WINDOW,
        },
    ),
    "aberrant_xstream": DetectorGuide(
        "xStream",
        "Random projections and chains of half-space cuts over a rolling "
        "window. Handles many features, and features that come and go.",
        ("window_size", "n_chains", "depth"),
        {
            "k": "Dimensions the features are projected to.",
            "n_chains": "Chains in the ensemble. More give steadier scores.",
            "depth": "Levels in each chain.",
            "sketch_width": (
                "Counters per row of each count sketch. More reduce collisions."
            ),
            "n_hashes": "Rows per count sketch.",
            "window_size": _REPLACED_WINDOW,
            "warm_up": (
                "Observations used to set the chains' scales before scoring starts."
            ),
            "density": (
                "Share of the projected dimensions each feature contributes "
                "to, above 0 up to 1."
            ),
            "max_feature_cache_size": (
                "Most feature names whose projections are cached."
            ),
        },
    ),
    # Ready from the first values.
    "forecast.timestral": DetectorGuide(
        "Timestral forecaster",
        "Forecast with a pretrained model from the recent values, and score the miss.",
        ("checkpoint", "lead"),
        {
            "checkpoint": (
                "The model's size. Larger checkpoints forecast better and "
                "need more memory and time."
            ),
            "context_length": "Recent values the model reads for each forecast.",
            "minimum_context": "Values that must arrive before the first forecast.",
        },
    ),
    # Learns nothing: a step before it states what the score is.
    "rule.score": DetectorGuide(
        "Rule detector",
        "Take one feature's value as the score, with no training. A step "
        "before it states the rule, such as a 1 where a limit is crossed.",
        (),
    ),
}


# What each calibration method does to the boundary, for whoever chooses one.
# What it promises about the alarm rate is its coverage, which editors show
# beside it. The method's own summary, with its formula, stays as its details.
CALIBRATIONS: dict[str, str] = {
    "split": (
        "Rank each score against the most recent scores, so the boundary "
        "follows slow change. Slow to react to a sudden shift."
    ),
    "aci": (
        "Rank against recent scores at a level that rises after each crossing "
        "and falls a little otherwise."
    ),
    "dtaci": (
        "ACI at several speeds at once, trusting whichever has done best. "
        "No step size to choose."
    ),
    "agaci": (
        "Several ACI trackers combined by how well each has predicted the "
        "scores so far."
    ),
    "qt": (
        "Move the boundary itself: up after a crossing, down a little "
        "otherwise. The simplest tracker, with one step size."
    ),
    "pid": (
        "A quantile tracker that also corrects for a run of past misses in "
        "one direction."
    ),
    "nexcp": (
        "Rank each score against past scores, counting recent ones more. "
        "Robust to gradual drift."
    ),
    "eci": (
        "A quantile tracker that also weighs how far a score fell from the "
        "boundary. A tighter boundary, without a rate guarantee."
    ),
    "sfogd": (
        "Track the boundary with steps that scale themselves to the scores. "
        "No step size to choose."
    ),
    "saocp": (
        "Trackers over short and long stretches, combined so the boundary "
        "does well on every stretch, also right after a shift."
    ),
    "belief": (
        "Set the boundary from a prior belief blended with recent scores, "
        "older ones counting less."
    ),
    "bocpd_aci": (
        "Model the scores of the current regime, start over when they change, "
        "and adjust the level as ACI does."
    ),
    "cpcp": (
        "Rank each score against past scores, counting each by how likely it "
        "belongs to the current regime."
    ),
    "bocpd": (
        "Model the scores of the current regime and start over when they change."
    ),
    "nig": (
        "Model the scores as a bell curve whose mean and spread follow the "
        "data, older scores counting less."
    ),
}


_LEVEL_STEP = (
    "How far the level moves after each observation. Larger follows change "
    "faster and wobbles more."
)

# Help for the settings of steps whose schemas come without it: the calibration
# methods' own catalog and the alarm policies as RADAR defines them. A nested
# setting is named with its parents, such as trackers.threshold_config.value.
STEPS: dict[str, dict[str, str]] = {
    "calibrate.aci": {"gamma": _LEVEL_STEP},
    "calibrate.bocpd_aci": {"gamma": _LEVEL_STEP},
    "calibrate.pid": {
        "lr": (
            "How far the boundary moves after each observation. Larger follows "
            "change faster and wobbles more."
        ),
    },
    "policy.martingale": {
        "trackers": (
            "The evidence series that can raise an alarm. Each bets on the "
            "p-values in its own way."
        ),
        "trackers.tracker_id": (
            "A lasting name for this series, stored with its evidence and "
            "shown in charts."
        ),
        "trackers.alarm_statistic": (
            "The running value compared with the threshold: all evidence so "
            "far, evidence since the last restart, CUSUM or Shiryaev-Roberts."
        ),
        "trackers.threshold_config": (
            "Set the threshold by hand, or let training calibrate it. "
            "Automatic needs CUSUM or Shiryaev-Roberts."
        ),
        "trackers.threshold_config.mode": (
            "Manual uses the value entered; automatic calibrates one during training."
        ),
        "trackers.threshold_config.value": (
            "The value to cross. Above 1 for the two martingale statistics; "
            "larger asks for stronger evidence."
        ),
        "trackers.betting_function": (
            "How a p-value becomes a bet. Power uses one epsilon, simple "
            "mixture averages many, simple jumper moves capital between a few."
        ),
        "trackers.epsilon": (
            "The power bet's exponent, above 0 up to 1. Smaller values bet "
            "more on small p-values."
        ),
        "trackers.epsilons": (
            "The epsilon values to average. Empty uses an even grid from the "
            "smallest epsilon to 1."
        ),
        "trackers.n_grid": (
            "How many epsilon values the mixture averages. More cost more per "
            "observation."
        ),
        "trackers.min_epsilon": (
            "The smallest epsilon of the mixture's grid, above 0 up to 1."
        ),
        "trackers.jump": (
            "How much capital moves between the jumper's bettors at each observation."
        ),
        "automatic_threshold_calibration": (
            "How automatic thresholds are calibrated during training."
        ),
        "automatic_threshold_calibration.false_alarm_probability": (
            "The chance of a false alarm within one window, shared by all "
            "automatic trackers."
        ),
        "automatic_threshold_calibration.simulation_count": (
            "Simulated runs the thresholds are estimated from. More allow "
            "smaller probabilities and take longer."
        ),
    },
    "policy.threshold": {
        "value": (
            "A score at or above it alarms. It is not calibrated, so set it in "
            "the score's own units."
        ),
    },
    "policy.quantile": {
        "mode": "How the threshold is set: from the calibration scores.",
        "quantile": (
            "The share of calibration scores the threshold lies above. 1 puts "
            "it at the highest score."
        ),
    },
}


def library(model_type: str) -> str | None:
    """The library a detector's model comes from, as its name is written."""
    if model_type.startswith("pyod_"):
        return "PyOD"
    if model_type.startswith("aberrant_"):
        return "Aberrant"
    return None
