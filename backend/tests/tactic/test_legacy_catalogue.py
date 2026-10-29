"""The frozen v1 catalogue format that migration 005 converts."""

from copy import deepcopy

import pytest
from off_key_core.db.catalogue_v1 import adapt_ambibox_catalog, legacy_stream_id
from off_key_core.schemas.collection_policy import CollectionPolicy
from pydantic import ValidationError

from tests.support.legacy_catalogue import LegacyCatalog, legacy_catalog


def test_catalog_rejects_wildcards_duplicate_endpoints_and_invalid_local_binding():
    data = legacy_catalog().model_dump(mode="json")
    data["sources"][0]["chargers"][0]["sensors"][0]["upstream_topic"] = (
        "device/evCharger/+/#"
    )
    with pytest.raises(ValidationError):
        LegacyCatalog.model_validate(data)
    data = legacy_catalog().model_dump(mode="json")
    data["sources"].append(data["sources"][0])
    with pytest.raises(ValidationError):
        LegacyCatalog.model_validate(data)
    data = legacy_catalog().model_dump(mode="json")
    data["sources"][0]["chargers"][0]["local_id"] = "1"
    with pytest.raises(ValidationError):
        LegacyCatalog.model_validate(data)


@pytest.mark.parametrize(
    "key,fingerprint",
    [
        ("nested/path", "6ad8194d784007ad"),
        ("t" * 160, "0d1ce30ce33d173a"),
        ("温度", "95fa69cf89ff6a76"),
    ],
)
def test_legacy_complex_stream_ids_match_existing_scene_algorithm(key, fingerprint):
    charger_id = "00000000-0000-0000-0000-000000000001"
    assert (
        legacy_stream_id(charger_id, key)
        == f"ambibox:sensor:{charger_id}:key-{fingerprint}"
    )


def test_legacy_adapter_preserves_identity_topics_and_policies_without_mutation():
    original = legacy_catalog("sample")
    original.sources[0].chargers[0].sensors[0].policy = CollectionPolicy(
        mode="original"
    )
    before = deepcopy(original.model_dump(mode="json"))
    converted = adapt_ambibox_catalog(original)
    source, charger = original.sources[0], original.sources[0].chargers[0]
    assert converted.connections[0].id == f"ambibox:broker:{source.id}"
    assert converted.devices[0].id == f"ambibox:charger:{charger.id}"
    assert converted.streams[0].id == f"ambibox:sensor:{charger.id}:temperature"
    assert converted.groups[0].id == f"ambibox:group:{charger.id}"
    assert converted.streams[0].topic == charger.sensors[0].upstream_topic
    assert converted.streams[0].policy.mode == "original"
    assert converted.connections[0].host == source.host
    assert original.model_dump(mode="json") == before
