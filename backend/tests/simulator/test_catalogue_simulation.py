"""Real local MQTT fixtures preserve catalogue topology and bounded publishing."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location(
    "catalogue_fixture", ROOT / "dev/local/catalog_fixture.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def document():
    return {
        "connections": [
            {
                "id": "one",
                "host": "one.example.ts.net",
                "transport": "tcp",
                "tls": False,
                "port": 1883,
            },
            {
                "id": "two",
                "host": "two.example.ts.net",
                "transport": "tcp",
                "tls": False,
                "port": 1883,
            },
        ],
        "streams": [],
    }


def test_separate_brokers_preserve_saved_endpoints_without_public_ports(tmp_path):
    saved = document()
    original = deepcopy(saved)
    result = fixture.compose_fixture(
        saved, ROOT, tmp_path / "private.json", "local-publisher"
    )
    assert saved == original
    for index, connection in enumerate(saved["connections"]):
        broker = result["services"][f"catalogue-broker-{index:03}"]
        assert broker["networks"]["app-network"]["aliases"] == [connection["host"]]
        assert "ports" not in broker
        assert broker["mem_limit"] == "32m"
    publisher = result["services"]["catalogue-publisher"]
    assert len(publisher["depends_on"]) == 2
    assert all(mount.endswith(":ro") for mount in publisher["volumes"])


def test_fixture_rejects_tls_instead_of_simulating_insecure_tls(tmp_path):
    saved = document()
    saved["connections"][0]["tls"] = True
    with pytest.raises(ValueError):
        fixture.compose_fixture(saved, ROOT, tmp_path / "private.json", "publisher")


def test_fixture_rejects_ip_endpoints_and_preserves_private_generated_files(tmp_path):
    saved = document()
    fixture.generate(saved, tmp_path, "publisher")
    for name in ["catalog-fixture.json", "catalog-fixture.compose.json"]:
        assert (tmp_path / "dev/local/state" / name).stat().st_mode & 0o777 == 0o600
    saved["connections"][0]["host"] = "100.100.10.2"
    with pytest.raises(ValueError):
        fixture.compose_fixture(saved, ROOT, tmp_path / "private.json", "publisher")


@pytest.mark.parametrize(
    "kind, expected_type",
    [("number", float), ("boolean", bool), ("text", str), ("identifier", str)],
)
def test_fixture_emits_correct_value_types_and_json_pointer_fields(kind, expected_type):
    stream = {
        "id": "reading",
        "value_type": kind,
        "payload_pointer": "/data~1values/latest~0value",
    }
    payload = fixture.topic_payload([stream], 10)
    assert isinstance(payload["data/values"]["latest~value"], expected_type)
