"""Compose hands each first-party service only variables its code reads, and the
environment reference documents only variables something reads or sets.

infra/tests/test_deployment.py applies the same rule to the Swarm environment.
"""

import re
from pathlib import Path

import pytest

from tests.support.compose import environment_keys, load_compose

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
SERVICES = {
    "api-gateway": "services/api/gateway",
    "tactic-middleware": "services/middleware/tactic",
    "mqtt-proxy": "services/mqtt/proxy",
    "mqtt-radar": "services/mqtt/radar",
    "db-sync": "services/db/sync",
}
COMPOSE_FILES = ("docker-compose.yml", "dev/local/compose.yml")
# Everything that reads or sets a documented variable.
DOC_SOURCES = (
    BACKEND / "libs",
    BACKEND / "services",
    ROOT / "infra/ansible",
    ROOT / "infra/stack",
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.cluster.yml",
    ROOT / "dev/local/compose.yml",
    ROOT / ".env.example",
)


def source_text(*paths: Path) -> str:
    files = ([path] if path.is_file() else sorted(path.rglob("*")) for path in paths)
    return "\n".join(
        file.read_text()
        for group in files
        for file in group
        if file.suffix in {".py", ".yaml", ".yml", ".j2", ".example"}
    )


def documented_variables() -> set[str]:
    """Backticked names in the first column of the reference tables."""
    reference = ROOT / "docs/reference/environment-variables.md"
    return {
        name
        for line in reference.read_text().splitlines()
        if line.startswith("| `")
        for name in re.findall(r"`([A-Z][A-Z0-9_]*\*?)`", line.split("|")[1])
    }


@pytest.mark.parametrize("compose_file", COMPOSE_FILES)
@pytest.mark.parametrize("service", SERVICES)
def test_compose_passes_only_variables_the_service_reads(compose_file, service):
    definition = load_compose(ROOT / compose_file)["services"].get(service) or {}
    code = source_text(BACKEND / SERVICES[service] / "src", BACKEND / "libs/core/src")
    unread = [
        key
        for key in environment_keys(definition)
        if not re.search(rf"\b{re.escape(key)}\b", code)
    ]
    assert unread == []


def test_environment_reference_names_only_read_or_set_variables():
    text = source_text(*DOC_SOURCES)
    unknown = sorted(
        name
        for name in documented_variables()
        if not re.search(
            r"\b" + re.escape(name.rstrip("*")) + ("" if name.endswith("*") else r"\b"),
            text,
        )
    )
    assert unknown == []
