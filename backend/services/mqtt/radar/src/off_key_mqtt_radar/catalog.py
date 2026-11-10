"""Generate the control-plane catalog from the pinned RADAR runtime.

Run ``python -m off_key_mqtt_radar.catalog --write`` after changing the Aberrant
pin or RADAR policy. CI and container builds use ``--check`` to detect drift.
"""

import argparse
import json
from importlib.resources import files
from itertools import product

from aberrant import __version__
from aberrant.catalog import (
    TRANSFORMER_CATALOG,
    get_forecaster_spec,
    get_model_spec,
    get_similarity_engine_spec,
)
from off_key_core.models.adaptive import (
    BOUND_PARAMETER_NAMES,
    FORECASTER_IDS,
    FORECASTER_LIMITS,
    MODEL_DEFAULTS,
    MODEL_IDS,
    PARAMETER_LIMITS,
    RESIDUAL_DETECTOR,
    forecaster_parameters,
)


def constrain_retained_readiness(schema, spec, defaults):
    """Export finite parameter-dependent runtime warm-up rules as JSON Schema.

    Control-plane validation consumes the generated constructor contract, so it
    never needs to import the numerical runtime or duplicate detector names.
    """
    if spec.capabilities(defaults).warmup.unit.value != "retained_values":
        return
    properties = schema["properties"]
    if "window_size" not in properties:
        raise ValueError(f"No retained-window capacity contract for {spec.id}")
    domains = {
        name: [False, True] if field.get("type") == "boolean" else field["enum"]
        for name, field in properties.items()
        if field.get("type") == "boolean" or "enum" in field
    }
    requirements = []
    for values in product(*domains.values()):
        params = dict(zip(domains, values, strict=True))
        warmup = spec.capabilities(defaults | params).warmup
        if warmup.unit.value != "retained_values":
            raise ValueError(
                f"Parameter-dependent warm-up units unsupported: {spec.id}"
            )
        requirements.append((params, warmup.minimum))
    minimum = min(count for _, count in requirements)
    properties["window_size"]["minimum"] = max(
        properties["window_size"].get("minimum", 1), minimum
    )
    for params, count in requirements:
        if count > minimum:
            schema.setdefault("allOf", []).append(
                {
                    "if": {
                        "properties": {
                            name: {"const": value} for name, value in params.items()
                        },
                        "required": list(params),
                    },
                    "then": {"properties": {"window_size": {"minimum": count}}},
                }
            )


def _bind(properties: dict) -> list[str]:
    """Remove the parameters RADAR binds from the features a detector reads."""
    bound_parameters = sorted(set(properties) & set(BOUND_PARAMETER_NAMES))
    for name in bound_parameters:
        del properties[name]
    return bound_parameters


def _limit(properties: dict, defaults: dict, limits: dict) -> None:
    for name, field in properties.items():
        field.update(limits.get(name, {}))
        if name in defaults:
            field["default"] = defaults[name]


def _supported(catalog_id: str, spec, capabilities: dict) -> None:
    if capabilities["warmup"]["unit"] not in {"events", "retained_values"}:
        raise ValueError(f"RADAR does not support {catalog_id}'s warm-up unit")
    if capabilities["higher_is_more_anomalous"] is not True or not spec.declarative:
        raise ValueError(f"RADAR requires a declarative anomaly score: {catalog_id}")


def _forecaster_entry(forecaster_id: str) -> dict:
    """A forecaster step: the forecaster's settings, a lead and a score.

    Its horizon is not a setting: the forecaster forecasts as far as the lead.
    """
    spec = get_model_spec(RESIDUAL_DETECTOR)
    forecaster = get_forecaster_spec(forecaster_id)
    detector = spec.parameter_schema()["properties"]
    schema = forecaster.parameter_schema()
    properties = schema["properties"]
    del properties["horizon"]
    properties["lead"] = {"type": "integer", "default": 1}
    properties["score"] = detector["score"]
    bound_parameters = _bind(detector)
    if set(detector) != {"model", "lead", "score"}:
        raise ValueError("The residual detector has settings RADAR does not map")
    defaults = {
        name: field["default"]
        for name, field in properties.items()
        if "default" in field
    }
    _limit(
        properties,
        defaults,
        PARAMETER_LIMITS | FORECASTER_LIMITS.get(forecaster_id, {}),
    )
    capabilities = spec.capabilities(
        forecaster_parameters(forecaster_id, defaults)
    ).as_dict()
    _supported(RESIDUAL_DETECTOR, spec, capabilities)
    if capabilities["warmup"]["unit"] != "events":
        raise ValueError(f"RADAR needs {forecaster_id} to warm up in events")
    return {
        "catalog_id": RESIDUAL_DETECTOR,
        "forecaster_id": forecaster_id,
        "name": f"Aberrant {forecaster.display_name} forecaster",
        "import_path": forecaster.import_path,
        "algorithm_family": spec.family,
        "available": spec.available and forecaster.available,
        "parameter_schema": schema,
        "default_parameters": defaults,
        "default_capabilities": capabilities,
        "bound_parameters": bound_parameters,
    }


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
        bound_parameters = _bind(properties)
        defaults = {
            name: field["default"]
            for name, field in properties.items()
            if "default" in field
        }
        defaults.update(MODEL_DEFAULTS.get(catalog_id, {}))
        _limit(properties, defaults, PARAMETER_LIMITS)
        available = spec.available
        if "similarity_engine" in properties:
            engine = properties["similarity_engine"]
            engine["properties"]["id"]["enum"] = ["faiss"]
            engine["properties"]["params"] = engine_schema
            engine["required"] = ["id", "params"]
            available = available and engine_spec.available
        capabilities = spec.capabilities(defaults).as_dict()
        constrain_retained_readiness(schema, spec, defaults)
        _supported(catalog_id, spec, capabilities)
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
    for model_type, forecaster_id in FORECASTER_IDS.items():
        models[model_type] = _forecaster_entry(forecaster_id)
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
    from .calibration_catalog import generate_calibration_catalog

    for name, generate in (
        ("adaptive_catalog.json", generate_catalog),
        ("calibration_catalog.json", generate_calibration_catalog),
    ):
        target = files("off_key_core.models").joinpath(name)
        rendered = (
            json.dumps(generate(), indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        if args.write:
            target.write_text(rendered)
        elif not target.is_file() or target.read_text() != rendered:
            parser.exit(
                1, f"RADAR catalog differs from the runtime; regenerate {name}\n"
            )


if __name__ == "__main__":
    main()
