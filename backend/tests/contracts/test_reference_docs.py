"""Reference pages name every env key, table and gateway route, and nothing else."""

import re
import subprocess
from pathlib import Path

from fastapi import FastAPI
from off_key_api_gateway.api.v1.routes import router
from off_key_core.db.models import Base

REPOSITORY = Path(__file__).resolve().parents[3]
REFERENCE = REPOSITORY / "docs/reference"
# Documented names that are not ORM tables.
EXTRA_TABLES = {"off_key_schema_migrations"}


def page(name: str) -> str:
    return (REFERENCE / name).read_text()


def env_keys() -> list[str]:
    lines = (REPOSITORY / ".env.example").read_text().splitlines()
    return [
        line.split("=", 1)[0] for line in lines if re.match(r"[A-Z][A-Z0-9_]*=", line)
    ]


def test_environment_page_covers_env_example_and_names_only_real_variables():
    text = page("environment-variables.md")
    tokens = set(re.findall(r"`([A-Z][A-Z0-9_]*\*?)`", text))
    keys = env_keys()
    assert [key for key in keys if key not in tokens] == []
    unknown = []
    for token in sorted(tokens - set(keys)):
        if token.endswith("*"):
            if not any(key.startswith(token[:-1]) for key in keys):
                unknown.append(token)
            continue
        found = subprocess.run(
            [
                "git",
                "grep",
                "-q",
                "-w",
                token,
                "--",
                "backend",
                "dev",
                "infra",
                "frontend/src",
                "docker-compose*.yml",
            ],
            cwd=REPOSITORY,
        )
        if found.returncode:
            unknown.append(token)
    assert unknown == []


def test_data_model_page_names_every_table_and_no_other():
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", page("data-model.md"), re.M))
    assert documented == set(Base.metadata.tables) | EXTRA_TABLES


def normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def gateway_routes() -> set[tuple[str, str]]:
    app = FastAPI()
    app.include_router(router)
    return {
        (method.upper(), normalise(path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def documented_gateway_routes() -> tuple[set[tuple[str, str]], set[str]]:
    text = page("backend-api.md")
    section = text.split("## Gateway API", 1)[1].split("## TACTIC API", 1)[0]
    rows = {
        (method, normalise(path))
        for method, path in re.findall(
            r"^\| `([A-Z]+)` \| `(/[^`]*)` \|", section, re.M
        )
        if path != "/health"
    }
    families = set()
    for row in re.findall(r"^\| [A-Z][a-z ]+ \| (`/.*?) \|", section, re.M):
        families |= {
            normalise("/monitors" + path.split("?", 1)[0])
            for path in re.findall(r"`(/[^`]*)`", row)
        }
    return rows, families


def test_api_page_documents_every_gateway_route_and_no_other():
    routes = gateway_routes()
    rows, families = documented_gateway_routes()
    assert (
        sorted(
            route for route in routes if route not in rows and route[1] not in families
        )
        == []
    )
    assert sorted(rows - routes) == []
    assert sorted(families - {path for _, path in routes}) == []
