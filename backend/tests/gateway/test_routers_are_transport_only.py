"""The API's routers receive services from providers and never touch persistence."""

import re
from pathlib import Path

import pytest

ROUTERS = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "api"
    / "gateway"
    / "src"
    / "off_key_api_gateway"
    / "api"
    / "v1"
)

FORBIDDEN = [
    # Catching a database error to answer 503 is transport; querying is not.
    re.compile(r"from sqlalchemy(?!\.exc import)"),
    re.compile(r"\bAsyncSession\b"),
    re.compile(r"\bget_db_async\b"),
    re.compile(r"\bselect\("),
    re.compile(r"\.execute\("),
    re.compile(r"\.scalars\("),
    re.compile(r"\.commit\("),
    re.compile(r"\.add\("),
    re.compile(r"session\.get\("),
]


def test_the_routers_are_found():
    assert len(list(ROUTERS.glob("*.py"))) > 5


@pytest.mark.parametrize(
    "router_file", sorted(ROUTERS.glob("*.py")), ids=lambda path: path.name
)
def test_routers_are_transport_only(router_file):
    contents = router_file.read_text(encoding="utf-8")
    for pattern in FORBIDDEN:
        assert not pattern.search(contents), (
            f"{router_file.name} must not contain {pattern.pattern!r}"
        )
