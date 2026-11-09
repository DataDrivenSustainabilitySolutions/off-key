"""Fail the RADAR image build when the trimmed environment misses a runtime import.

backend/Dockerfile leaves matplotlib, and the packages only it needs, out of the
RADAR image. This imports every RADAR module and every detector, transformer and
similarity engine RADAR offers, so a change that needs them breaks the build
instead of a running monitor.
"""

import importlib
import pkgutil
import sys


def import_everything_radar_runs():
    import aberration_mqtt_radar
    from aberrant.catalog import (
        TRANSFORMER_CATALOG,
        get_model_spec,
        get_similarity_engine_spec,
    )
    from aberration_core.models.adaptive import MODEL_IDS
    from aberration_core.models.static import STATIC_MODELS

    # RADAR imports these lazily, so walking its modules alone does not reach them.
    importlib.import_module("nonconform")
    importlib.import_module("nonconform.martingales")

    for module in pkgutil.walk_packages(
        aberration_mqtt_radar.__path__, f"{aberration_mqtt_radar.__name__}."
    ):
        if not module.name.endswith(".__main__"):
            importlib.import_module(module.name)

    for definition in STATIC_MODELS.values():
        module_name, _, class_name = definition.import_path.rpartition(".")
        getattr(importlib.import_module(module_name), class_name)

    for catalog_id in MODEL_IDS.values():
        get_model_spec(catalog_id).load()
    for spec in TRANSFORMER_CATALOG.values():
        spec.load()
    get_similarity_engine_spec("faiss").load()


if __name__ == "__main__":
    try:
        import_everything_radar_runs()
    except ModuleNotFoundError as error:
        sys.exit(
            f"RADAR imports {error.name!r}, which its image does not contain. "
            "backend/Dockerfile leaves matplotlib and the packages only it needs "
            "out; keep RADAR off that code path or keep the package in the image."
        )
