"""Read Compose files without Docker."""

from pathlib import Path

import yaml


class ComposeLoader(yaml.SafeLoader):
    """Reads Compose merge tags such as !reset and !override as plain YAML."""


ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_scalar(node)
    ),
)


def load_compose(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=ComposeLoader)


def environment_keys(service: dict) -> list[str]:
    """The variable names of a service's list- or mapping-form environment."""
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return list(environment)
    return [entry.split("=", 1)[0] for entry in environment]
