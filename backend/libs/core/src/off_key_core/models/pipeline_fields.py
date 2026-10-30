"""Compile a bounded, tested parameter editor vocabulary from catalog schemas."""

from typing import Any

from ..schemas.pipelines import ComponentField, FieldType

Schema = dict[str, Any]
SCALAR_TYPES = {"number", "integer", "boolean", "string"}
SPECIAL_TYPES: dict[str, FieldType] = {
    "features": "features",
    "mapping": "rename",
    "feature_range": "number_pair",
}


def _resolve(schema: Schema, definitions: Schema) -> Schema:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    if not reference.startswith("#/$defs/"):
        raise ValueError(
            f"Unsupported external parameter schema reference: {reference}"
        )
    name = reference.rsplit("/", 1)[-1]
    if name not in definitions:
        raise ValueError(f"Unresolved parameter schema reference: {reference}")
    return definitions[name]


def _unwrap_nullable(schema: Schema, definitions: Schema) -> tuple[Schema, bool]:
    resolved = _resolve(schema, definitions)
    if "anyOf" not in resolved:
        return resolved, False
    choices = [item for item in resolved["anyOf"] if item.get("type") != "null"]
    if len(choices) != 1:
        raise ValueError(
            "A parameter union requires one supported type and optional null"
        )
    return _resolve(choices[0], definitions), len(choices) != len(resolved["anyOf"])


def _array_kind(schema: Schema, definitions: Schema) -> FieldType:
    fixed = schema.get("prefixItems", [])
    if len(fixed) == 2 and all(
        item.get("type") in {"number", "integer"} for item in fixed
    ):
        return "number_pair"
    item = _resolve(schema.get("items", {}), definitions)
    if item.get("type") == "object" or "oneOf" in item:
        return "object_list"
    if item.get("type") in {"number", "integer"}:
        return "number_list"
    raise ValueError(
        "Only numeric lists and allowlisted object lists have editor controls"
    )


def _field_kind(name: str, schema: Schema, definitions: Schema) -> FieldType:
    if schema.get("x-aberrant-component-kind"):
        return "component"
    if name in SPECIAL_TYPES:
        return SPECIAL_TYPES[name]
    if schema.get("enum") or "const" in schema:
        return "enum"
    if "oneOf" in schema and "discriminator" in schema:
        return "object"
    if _integer_adjacency(schema):
        return "integer_adjacency"
    kind = schema.get("type")
    if kind in SCALAR_TYPES:
        return kind
    if kind == "array":
        return _array_kind(schema, definitions)
    if kind == "object" and (
        "properties" in schema or schema.get("additionalProperties") is False
    ):
        return "object"
    raise ValueError(f"No bounded parameter control for {name!r}: {kind!r}")


def _integer_adjacency(schema: Schema) -> bool:
    values = schema.get("additionalProperties", {})
    return (
        schema.get("type") == "object"
        and schema.get("x-python-key-type") == "builtins.int"
        and isinstance(values, dict)
        and values.get("type") == "array"
        and values.get("items", {}).get("type") == "integer"
    )


def _variants(
    schema: Schema, definitions: Schema
) -> tuple[str | None, dict[str, list[ComponentField]] | None]:
    discriminator = schema.get("discriminator", {})
    mapping = discriminator.get("mapping", {})
    variants = {
        key: component_fields(_resolve({"$ref": reference}, definitions), definitions)
        for key, reference in mapping.items()
    }
    return discriminator.get("propertyName"), variants or None


def _describe(
    name: str, original: Schema, definitions: Schema, *, required: bool
) -> ComponentField:
    schema, nullable = _unwrap_nullable(original, definitions)
    kind = _field_kind(name, schema, definitions)
    nested = (
        _resolve(schema.get("items", {}), definitions)
        if kind == "object_list"
        else schema
    )
    discriminator, variants = _variants(nested, definitions)
    options = schema.get("enum", [schema["const"]] if "const" in schema else None)
    return ComponentField(
        name=name,
        label=original.get("title", name.replace("_", " ").title()),
        type=kind,
        default=original.get("default", schema.get("default")),
        required=required,
        has_default="default" in original or "default" in schema,
        nullable=nullable,
        minimum=original.get("minimum", schema.get("minimum")),
        maximum=original.get("maximum", schema.get("maximum")),
        exclusive_minimum=original.get(
            "exclusiveMinimum", schema.get("exclusiveMinimum")
        ),
        exclusive_maximum=original.get(
            "exclusiveMaximum", schema.get("exclusiveMaximum")
        ),
        options=options,
        description=original.get("description", ""),
        fields=component_fields(
            schema.get("properties", {}).get("params", {}), definitions
        )
        if kind == "component"
        else component_fields(nested, definitions)
        if kind in {"object", "object_list"}
        else [],
        discriminator=discriminator,
        variants=variants,
    )


def component_fields(
    schema: Schema, definitions: Schema | None = None
) -> list[ComponentField]:
    definitions = schema.get("$defs", {}) if definitions is None else definitions
    return [
        _describe(
            name, original, definitions, required=name in schema.get("required", [])
        )
        for name, original in schema.get("properties", {}).items()
    ]


def parameter_path(
    loc: tuple[str | int, ...], fields: list[ComponentField]
) -> list[str | int]:
    """Remove Pydantic discriminator labels using metadata, never error text."""
    result = []
    field = None
    for part in loc:
        if (
            field is not None
            and field.variants is not None
            and isinstance(part, str)
            and part in field.variants
        ):
            fields = field.variants[part]
            field = None
            continue
        result.append(part)
        if isinstance(part, int):
            continue
        selected = next((item for item in fields if item.name == part), None)
        if selected is not None:
            field = selected
            fields = selected.fields
    return result
