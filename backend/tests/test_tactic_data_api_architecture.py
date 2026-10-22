from pathlib import Path

import pytest

ROUTERS = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "middleware"
    / "tactic"
    / "src"
    / "off_key_tactic_middleware"
    / "api"
    / "v1"
)

FORBIDDEN_TOKENS = [
    "from sqlalchemy",
    "AsyncSession",
    "get_db_async",
    "select(",
    ".execute(",
    ".scalars(",
    ".commit(",
    ".add(",
    "session.get(",
]


@pytest.mark.parametrize(
    "router_file", sorted(ROUTERS.glob("*.py")), ids=lambda path: path.name
)
def test_routers_are_transport_only(router_file):
    """Routers receive services from provider.py and never touch persistence."""
    contents = router_file.read_text(encoding="utf-8")
    for token in FORBIDDEN_TOKENS:
        assert token not in contents, f"{router_file.name} must not contain '{token}'"
