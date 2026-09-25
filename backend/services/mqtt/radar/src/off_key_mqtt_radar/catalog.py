"""Generate the control-plane catalog from the pinned RADAR runtime.

Run ``python -m off_key_mqtt_radar.catalog --write`` after changing the Aberrant
pin or RADAR policy. CI and container builds use ``--check`` to detect drift.
"""

import argparse
import json
from importlib.resources import files

from aberrant import __version__
from aberrant.catalog import (
    TRANSFORMER_CATALOG,
    get_model_spec,
    get_similarity_engine_spec,
)
from off_key_core.models.adaptive import MODEL_DEFAULTS, MODEL_IDS, PARAMETER_LIMITS


def generate_catalog() -> dict:
    models = {}
    engine_spec = get_similarity_engine_spec("faiss")
    engine_schema = engine_spec.parameter_schema()
    for name, schema in engine_schema["properties"].items():
        schema.update(PARAMETER_LIMITS.get(name, {}))

    for model_type, catalog_id in MODEL_IDS.items():
        spec = get_model_spec(catalog_id)
        schema = spec.parameter_schema()
        properties = schema["properties"]
        bound_parameters = sorted(set(properties) & {"key", "keys", "abs_diff"})
        for name in bound_parameters:
            del properties[name]
        defaults = {
            name: field["default"]
            for name, field in properties.items()
            if "default" in field
        }
        defaults.update(MODEL_DEFAULTS.get(catalog_id, {}))
        for name, field in properties.items():
            field.update(PARAMETER_LIMITS.get(name, {}))
            if name in defaults:
                field["default"] = defaults[name]
        available = spec.available
        if "similarity_engine" in properties:
            engine = properties["similarity_engine"]
            engine["properties"]["id"]["enum"] = ["faiss"]
            engine["properties"]["params"] = engine_schema
            engine["required"] = ["id", "params"]
            available = available and engine_spec.available
        capabilities = spec.capabilities(defaults).as_dict()
        if capabilities["warmup"]["unit"] != "events":
            raise ValueError(f"RADAR does not support {catalog_id}'s warm-up unit")
        if capabilities["higher_is_more_anomalous"] is not True or not spec.declarative:
            raise ValueError(
                f"RADAR requires a declarative anomaly score: {catalog_id}"
            )
        models[model_type] = {
            "catalog_id": catalog_id,
            "name": f"Aberrant {spec.display_name}",
            "import_path": spec.import_path,
            "algorithm_family": spec.family,
            "available": available,
            "parameter_schema": schema,
            "default_parameters": defaults,
            "default_capabilities": capabilities,
            "bound_parameters": bound_parameters,
        }
    return json.loads(
        json.dumps(
            {
                "aberrant_version": __version__,
                "models": models,
                "transformers": {
                    name: spec.as_dict() for name, spec in TRANSFORMER_CATALOG.items()
                },
            },
            allow_nan=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = files("off_key_core.models").joinpath("adaptive_catalog.json")
    rendered = json.dumps(generate_catalog(), indent=2, sort_keys=True) + "\n"
    if args.write:
        target.write_text(rendered)
    elif target.read_text() != rendered:
        parser.exit(
            1,
            "RADAR catalog differs from the runtime; "
            "regenerate adaptive_catalog.json\n",
        )


if __name__ == "__main__":
    main()
