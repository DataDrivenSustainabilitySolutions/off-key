"""Scope ownership, future admission and legacy compatibility regressions."""

from unittest.mock import AsyncMock

import pytest
from off_key_core.db.collection_runtime import CollectionRuntimeSnapshot
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.collection_rules import (
    CollectionRule,
    CollectionRuleEdit,
    CollectionRuleScope,
)
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_core.utils.collection_rules import CollectionRuleResolver
from off_key_tactic_middleware.services.catalogue import (
    system_collection as collection_module,
)
from off_key_tactic_middleware.services.catalogue.collection_rule_edits import (
    apply_rule_edits,
)
from off_key_tactic_middleware.services.catalogue.system_collection import (
    SystemCollectionService,
)

from tests.support.system_document import document


def definition():
    doc = document()
    doc.streams[0].topic = "building/floor1/temperature"
    doc.streams.extend(
        [
            doc.streams[0].model_copy(
                update={"id": "power", "topic": "building/floor1/power"}
            ),
            doc.streams[0].model_copy(
                update={"id": "floor10", "topic": "building/floor10/temperature"}
            ),
            doc.streams[0].model_copy(
                update={"id": "field", "payload_pointer": "/other"}
            ),
        ]
    )
    return SystemCollectionDefinition(
        document=doc,
        bindings=build_bindings(doc),
        rules_version=1,
        registered_at={stream.id: 1 for stream in doc.streams},
        registration_clock=1,
    )


def scope(kind="broker", **fields):
    return CollectionRuleScope(kind=kind, connection_id="broker-1", **fields)


def edit(target, mode="original", **fields):
    return CollectionRuleEdit(
        scope=target, policy=CollectionPolicy(mode=mode), **fields
    )


def modes(value):
    return {stream.id: stream.policy.mode for stream in value.document.streams}


def test_topic_rule_includes_payload_fields_and_complete_segments_only():
    value = definition()
    apply_rule_edits(value, [edit(scope("topic", topic_prefix="building/floor1"))])
    assert modes(value) == {
        "temperature-1": "original",
        "power": "original",
        "floor10": "off",
        "field": "original",
    }
    unrelated = value.document.streams[0].model_copy(update={"connection_id": "other"})
    assert CollectionRuleResolver(value).resolve(unrelated)[0].mode == "off"


def test_parent_changes_preserve_exceptions_and_restoring_inheritance():
    value = definition()
    apply_rule_edits(
        value,
        [
            edit(scope()),
            edit(scope("topic", topic_prefix="building/floor1"), "sample"),
            edit(scope("reading", reading_id="power"), "off"),
        ],
    )
    apply_rule_edits(value, [edit(scope(), "off")])
    assert modes(value)["temperature-1"] == "sample"
    assert modes(value)["power"] == "off"
    apply_rule_edits(
        value,
        [
            CollectionRuleEdit(
                scope=scope("reading", reading_id="power"), operation="inherit"
            )
        ],
    )
    assert modes(value)["power"] == "sample"


def test_excluded_additions_remain_off_after_rate_changes_and_can_be_admitted():
    value = definition()
    apply_rule_edits(value, [edit(scope())])
    value.registration_clock = 2
    value.registered_at["power"] = 2
    apply_rule_edits(value, [edit(scope(), "sample")])
    resolver = CollectionRuleResolver(value)
    assert resolver.resolve(value.document.streams[1])[1]["needs_review"]
    assert modes(value)["power"] == "off"
    apply_rule_edits(value, [CollectionRuleEdit(scope=scope(), operation="include")])
    assert modes(value)["power"] == "sample"
    apply_rule_edits(value, [edit(scope(), "original")])
    assert modes(value)["power"] == "original"


def test_disabling_future_admission_preserves_current_members():
    value = definition()
    apply_rule_edits(value, [edit(scope(), include_future_readings=True)])
    value.registration_clock = 2
    value.registered_at["power"] = 2
    apply_rule_edits(value, [edit(scope(), include_future_readings=False)])
    assert modes(value)["power"] == "original"
    value.registration_clock = 3
    value.registered_at["power"] = 3
    CollectionRuleResolver(value).materialize()
    assert modes(value)["power"] == "off"


def test_legacy_active_selections_survive_but_default_off_is_not_an_exception():
    value = definition()
    value.document.streams[0].policy = CollectionPolicy(
        mode="sample", interval_seconds=7
    )
    legacy = SystemCollectionDefinition.model_validate(
        {"document": value.document.model_dump(), "bindings": value.bindings}
    )
    apply_rule_edits(legacy, [edit(scope())])
    assert modes(legacy)["temperature-1"] == "sample"
    assert modes(legacy)["power"] == "original"
    restored = SystemCollectionDefinition.model_validate(legacy.model_dump())
    assert (
        restored.rules == legacy.rules
    )  # Materialized parents must not become leaf overrides.


@pytest.mark.parametrize(
    ("prefix", "topic", "matches"),
    [
        ("a/", "a//b", True),
        ("a/", "a/b", False),
        ("$SYS", "$SYS/uptime", True),
        ("λ/測定", "λ/測定/value", True),
        ("room", "Room/value", False),
        ("room", "room", True),
    ],
)
def test_topic_identity_is_preserved(prefix, topic, matches):
    assert (
        scope("topic", topic_prefix=prefix).matches(
            definition().document.streams[0].model_copy(update={"topic": topic})
        )
        is matches
    )


def test_restore_preserves_admission_boundary():
    value = definition()
    original = CollectionRule(
        scope=scope(), policy=CollectionPolicy(mode="sample"), admitted_before=0
    )
    apply_rule_edits(value, [edit(scope(), include_future_readings=True)])
    apply_rule_edits(
        value,
        [CollectionRuleEdit(scope=scope(), operation="restore", restore_rule=original)],
    )
    assert all(mode == "off" for mode in modes(value).values())


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "mode"), [("set", "sample"), ("inherit", "off")])
async def test_full_legacy_catalogue_avoids_quadratic_leaf_matching(
    monkeypatch, operation, mode
):
    doc = SystemDocument.model_validate(
        {
            "connections": [{"id": "b", "label": "Broker", "host": "localhost"}],
            "streams": [
                {
                    "id": f"r{index}",
                    "label": "Reading",
                    "connection_id": "b",
                    "topic": "x",
                    "payload_pointer": f"/v{index}",
                    "policy": {"mode": "original"},
                }
                for index in range(4096)
            ],
        }
    )
    legacy = SystemCollectionDefinition(document=doc, bindings=build_bindings(doc))
    runtime = CollectionRuntimeSnapshot(
        revision=1, catalog=legacy, ingress={}, collection={}
    )
    monkeypatch.setattr(
        collection_module, "read_collection_runtime", AsyncMock(return_value=runtime)
    )
    match_calls = 0
    matches = CollectionRuleScope.matches

    def counted_matches(self, stream):
        nonlocal match_calls
        match_calls += 1
        return matches(self, stream)

    monkeypatch.setattr(CollectionRuleScope, "matches", counted_matches)
    _, proposed = await SystemCollectionService(None).current(doc)
    assert len(proposed.rules) == 4096
    assert match_calls <= len(doc.streams)
    apply_rule_edits(
        proposed,
        [
            CollectionRuleEdit(
                scope=CollectionRuleScope(
                    kind="reading", connection_id="b", reading_id=stream.id
                ),
                operation=operation,
                policy=CollectionPolicy(mode="sample") if operation == "set" else None,
            )
            for stream in doc.streams
        ],
    )
    assert all(policy_mode == mode for policy_mode in modes(proposed).values())
    assert match_calls <= 2 * len(doc.streams)
