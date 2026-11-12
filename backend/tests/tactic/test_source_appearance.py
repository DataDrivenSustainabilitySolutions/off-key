"""Portable cosmetic metadata cannot alter recording identities or connections."""

import pytest
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import (
    SourceAppearance,
    SystemDocument,
    TopicAppearance,
)
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
    runtime_fingerprint,
)

from tests.support.system_document import document


def test_appearance_roundtrips_without_changing_recording_fingerprint():
    before = document()
    before.streams[0].policy = CollectionPolicy(mode="original")
    after = before.model_copy(deep=True)
    for item in [*after.connections, *after.devices, *after.streams, *after.groups]:
        item.appearance = SourceAppearance(icon="pump", color="sage")
    after.topic_appearances = [
        TopicAppearance(
            broker_id="broker-1",
            topic="home",
            appearance=SourceAppearance(icon="house"),
        )
    ]
    restored = SystemDocument.model_validate_json(after.model_dump_json(by_alias=True))
    assert restored == after
    old = SystemCollectionDefinition(document=before, bindings=build_bindings(before))
    new = SystemCollectionDefinition(document=after, bindings=build_bindings(after))
    assert runtime_fingerprint(old) == runtime_fingerprint(new)
    assert old.bindings == new.bindings


@pytest.mark.parametrize(
    "appearance",
    [
        {"icon": "https://example.com/icon.svg"},
        {"icon": "<svg/>"},
        {"icon": "x" * 41},
        {"color": "neon"},
        {"markup": "svg"},
    ],
)
def test_invalid_appearance_metadata_is_rejected(appearance):
    data = document().model_dump(mode="json")
    data["connections"][0]["appearance"] = appearance
    with pytest.raises(ValueError):
        SystemDocument.model_validate(data)


def test_future_icon_names_are_portable_and_topic_references_are_checked():
    assert SourceAppearance(icon="future-sensor", color="teal").icon == "future-sensor"
    data = document().model_dump(mode="json")
    entry = {"broker_id": "broker-1", "topic": "home", "appearance": {"icon": "house"}}
    data["topic_appearances"] = [entry, entry]
    with pytest.raises(ValueError, match="unique"):
        SystemDocument.model_validate(data)
    data["topic_appearances"] = [{**entry, "broker_id": "missing"}]
    with pytest.raises(ValueError, match="broker does not exist"):
        SystemDocument.model_validate(data)


@pytest.mark.parametrize("topic", ["plant/#", "plant/+", "bad\x00topic", "💧" * 129])
def test_topic_appearance_requires_a_concrete_bounded_path(topic):
    with pytest.raises(ValueError):
        TopicAppearance(
            broker_id="broker-1", topic=topic, appearance=SourceAppearance()
        )


def test_topic_appearance_supports_an_empty_first_path_level():
    assert TopicAppearance(broker_id="broker-1", topic="", appearance={}).topic == ""
