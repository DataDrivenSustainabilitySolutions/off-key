STATIC_MODEL_FAMILY = "static_pyod"
RETIRED_MODEL_FAMILY = "retired"
STATIC_MONITORING_STRATEGY = "static_baseline"

BUILTIN_STATIC_MODEL_TYPES = frozenset(
    {
        "pyod_iforest",
        "pyod_knn",
        "pyod_lof",
        "pyod_ocsvm",
        "pyod_hbos",
        "pyod_pca",
    }
)
