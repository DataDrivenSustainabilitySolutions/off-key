"""The local test API answers what the local deployment guide says to read."""

import importlib.util
from pathlib import Path
from threading import Thread

import pytest
from off_key_core.schemas.system import SystemConnection, SystemStream
from off_key_core.utils.payload_decode import decode_value
from off_key_tactic_middleware.services.catalogue.system_live_http import HttpSession

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "api_fixture", ROOT / "dev/local/api_fixture.py"
)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)

STATION = "/v1/stations/roof/latest"


@pytest.fixture
def api():
    server = fixture.serve(0)
    Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    connection = SystemConnection(
        id="api",
        label="Test API",
        protocol="http",
        host="127.0.0.1",
        port=server.server_address[1],
    )
    session = HttpSession(connection, None, None)
    yield session
    session.close()
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("path", "pointer", "value_type", "kind"),
    [
        (STATION, "/temperature", "number", float),
        (STATION, "/humidity", "number", float),  # Sent as text.
        (STATION, "/wind/speed", "number", float),
        (STATION, "/wind/gusting", "boolean", bool),
        (STATION, "/sky", "text", str),
        (STATION + "?units=metric", "/temperature", "number", float),
        ("/v1/meters/main", "/power_kw", "number", float),
        ("/v1/meters/main", "/energy_kwh", "number", float),
    ],
)
def test_a_reading_decodes_from_the_reply_at_its_path(
    api, path, pointer, value_type, kind
):
    reading = SystemStream.model_validate(
        {
            "id": "reading",
            "label": "Reading",
            "connection_id": "api",
            "topic": path,
            "payload_pointer": pointer,
            "value_type": value_type,
        }
    )
    status, body, _ = api.get(path)
    assert status == 200
    assert type(decode_value(body, reading)) is kind


def test_other_paths_are_not_found(api):
    assert api.get("/health")[0] == 200
    assert api.get("/v1/stations/cellar/latest")[0] == 404


def test_the_station_repeats_an_observation_until_it_measures_again():
    first = fixture.station(1_000_000_000)
    assert first["observed_at"] == "2001-09-09T01:46:30Z"
    assert fixture.station(1_000_000_004) == first
    assert fixture.station(1_000_000_005)["observed_at"] == "2001-09-09T01:46:45Z"
    # The meter names no time, so two polls differ.
    assert fixture.meter(1_000_000_000) != fixture.meter(1_000_000_004)
