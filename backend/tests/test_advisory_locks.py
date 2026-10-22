"""Advisory-lock keys are declared once and never collide by accident."""

import re
from pathlib import Path

from off_key_core.db import locks

BACKEND = Path(__file__).resolve().parents[1]


def test_lock_keys_are_unique_except_the_documented_membership_share():
    keys = {
        name: value
        for name, value in vars(locks).items()
        if name.endswith("_LOCK") and isinstance(value, int)
    }
    assert len(set(keys.values())) == len(keys) - 1
    assert keys["MEMBERSHIP_LOCK"] == keys["MIGRATION_LOCK"]
    assert 73128002 not in keys.values()


def test_numeric_lock_keys_appear_only_in_the_registry():
    literal = re.compile(r"\b7312800\d\b")
    offenders = [
        path.relative_to(BACKEND)
        for path in BACKEND.glob("**/src/**/*.py")
        if path.name != "locks.py" and literal.search(path.read_text())
    ]
    assert offenders == []
