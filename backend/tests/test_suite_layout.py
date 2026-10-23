"""Every environment-gated test belongs to a CI lane that runs it without skips."""

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).parent

# Gate variable -> marker of the lane that provides it. Database tests are marked
# automatically from their fixtures (conftest.DATABASE_FIXTURES).
LANES = {
    "TEST_RADAR_DOCKER": "radar_integration",
    "TEST_RADAR_SWARM_IMAGE": "radar_integration",
    "TEST_PIPELINE_DATABASE_CONTAINER": "radar_integration",
    "OFFKEY_COLLECTION_INTEGRATION": "collection_stack",
    "OFFKEY_DEPLOYMENT_REHEARSAL": "deployment",
    "RUN_ADAPTIVE_E2E": "deployment",
}


def module_marks(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            return {
                item.attr
                for item in ast.walk(node.value)
                if isinstance(item, ast.Attribute)
                and isinstance(item.value, ast.Attribute)
                and item.value.attr == "mark"
            }
    return set()


def gated_modules():
    for path in sorted(TESTS.rglob("*.py")):
        source = path.read_text()
        lanes = {lane for gate, lane in LANES.items() if gate in source}
        if lanes and path.name.startswith("test_") and path != Path(__file__):
            yield pytest.param(path, lanes, id=str(path.relative_to(TESTS)))


@pytest.mark.parametrize(("path", "lanes"), gated_modules())
def test_gated_module_is_selected_by_its_lane(path, lanes):
    marks = module_marks(ast.parse(path.read_text()))
    assert lanes <= marks, f"{path.name} needs pytestmark {sorted(lanes - marks)}"


def test_test_modules_share_code_only_through_support():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                names = [node.module or "", *(alias.name for alias in node.names)]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "tests."
            ):
                names = [node.module]
            else:
                continue
            if any(
                part.startswith("test_") for name in names for part in name.split(".")
            ):
                offenders.append(f"{path.relative_to(TESTS)}:{node.lineno}")
    assert offenders == [], "Move shared helpers to tests/support: " + ", ".join(
        offenders
    )
