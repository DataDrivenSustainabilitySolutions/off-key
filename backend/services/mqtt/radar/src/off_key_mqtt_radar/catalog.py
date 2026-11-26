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
    get_forecaster_spec,
    get_model_spec,
    model_capabilities,
)
from off_key_core.models.adaptive import (
    BOUND_PARAMETER_NAMES,
    COMPONENT_DEFAULTS,
    COMPONENT_SETTINGS,
    FORECASTER_IDS,
    FORECASTER_LIMITS,
    MODEL_DEFAULTS,
    MODEL_IDS,
    PARAMETER_LIMITS,
    RESIDUAL_DETECTOR,
    UNSUPPORTED_PARAMETERS,
    forecaster_parameters,
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
    if capabilities["warm_up"]["unit"] != "events":
        raise ValueError(f"RADAR needs {catalog_id} to warm up in events")
    if not spec.declarative:
        raise ValueError(f"RADAR requires a declarative detector: {catalog_id}")


def _choice(component_ids: tuple[str, ...], definitions: dict) -> dict:
    """One of several components, told apart by its ``id`` beside its settings."""
    for component_id in component_ids:
        if component_id not in definitions:
            definitions[component_id] = {}
            definitions[component_id] = _held_schema(component_id, definitions)
    return {
        "oneOf": [{"$ref": f"#/$defs/{item}"} for item in component_ids],
        "discriminator": {
            "propertyName": "id",
            "mapping": {item: f"#/$defs/{item}" for item in component_ids},
        },
    }


def _component_schema(component_id: str, definitions: dict) -> dict:
    """A component's own settings, with those it holds chosen by ``id``.

    Its horizon is not a setting: every forecaster forecasts as far as the lead.
    """
    schema = get_forecaster_spec(component_id).parameter_schema()
    properties = schema["properties"]
    properties.pop("horizon", None)
    for name, component_ids in COMPONENT_SETTINGS.items():
        if name not in properties:
            continue
        default = COMPONENT_DEFAULTS[component_id][name]
        if properties[name].get("type") == "array":
            properties[name] = {
                "type": "array",
                "items": _choice(component_ids, definitions),
                "default": default,
            }
        else:
            properties[name] = {
                **_choice(component_ids, definitions),
                "default": default,
            }
        schema["required"] = [item for item in schema["required"] if item != name]
        if not schema["required"]:
            del schema["required"]
    defaults = {
        name: field["default"]
        for name, field in properties.items()
        if "default" in field
    }
    _limit(
        properties,
        defaults,
        PARAMETER_LIMITS | FORECASTER_LIMITS.get(component_id, {}),
    )
    return schema


def _held_schema(component_id: str, definitions: dict) -> dict:
    """A held component's settings with its ``id``, as one variant of a choice."""
    schema = _component_schema(component_id, definitions)
    return {
        **schema,
        "properties": {"id": {"const": component_id}, **schema["properties"]},
        "required": ["id", *schema.get("required", [])],
    }


def _forecaster_entry(forecaster_id: str) -> dict:
    """A forecaster step: the forecaster's settings, a lead and a score.

    Its horizon is not a setting: the forecaster forecasts as far as the lead.
    """
    spec = get_model_spec(RESIDUAL_DETECTOR)
    forecaster = get_forecaster_spec(forecaster_id)
    detector = spec.parameter_schema()["properties"]
    definitions: dict = {}
    schema = _component_schema(forecaster_id, definitions)
    if definitions:
        schema["$defs"] = definitions
    properties = schema["properties"]
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
    # The target is bound when a step is built; any name gives the same warm-up.
    capabilities = model_capabilities(
        RESIDUAL_DETECTOR,
        forecaster_parameters(forecaster_id, defaults) | {"target": "value"},
    ).as_dict()
    _supported(RESIDUAL_DETECTOR, spec, capabilities)
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
    for model_type, catalog_id in MODEL_IDS.items():
        spec = get_model_spec(catalog_id)
        schema = spec.parameter_schema()
        properties = schema["properties"]
        bound_parameters = _bind(properties)
        for name in UNSUPPORTED_PARAMETERS:
            properties.pop(name, None)
        defaults = {
            name: field["default"]
            for name, field in properties.items()
            if "default" in field
        }
        defaults.update(MODEL_DEFAULTS.get(catalog_id, {}))
        _limit(properties, defaults, PARAMETER_LIMITS)
        capabilities = model_capabilities(catalog_id, defaults).as_dict()
        _supported(catalog_id, spec, capabilities)
        models[model_type] = {
            "catalog_id": catalog_id,
            "name": f"Aberrant {spec.display_name}",
            "import_path": spec.import_path,
            "algorithm_family": spec.family,
            "available": spec.available,
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
