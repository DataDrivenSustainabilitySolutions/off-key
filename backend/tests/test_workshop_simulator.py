"""The opt-in generic fixture publishes the values described by its catalog."""

import json
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.schemas.system import SystemDocument
from off_key_mqtt_simulator.__main__ import SimulatorService
from off_key_mqtt_simulator.config import SimulatorSettings
from off_key_mqtt_simulator.workshop import build_workshop_messages

WORKSHOP_FIXTURE = (
    Path(__file__).resolve().parents[2] / "dev" / "local" / "workshop-system.json"
)


def test_workshop_is_disabled_by_default_and_can_be_enabled_in_environment(monkeypatch):
    monkeypatch.delenv("SIMULATOR_WORKSHOP_ENABLED", raising=False)
    assert SimulatorSettings(_env_file=None).config.workshop_enabled is False
    monkeypatch.setenv("SIMULATOR_WORKSHOP_ENABLED", "true")
    assert SimulatorSettings(_env_file=None).config.workshop_enabled is True


def test_workshop_fixture_validates_and_keeps_storage_off():
    document = SystemDocument.model_validate_json(WORKSHOP_FIXTURE.read_text())
    assert document.default_policy.mode == "off"
    assert all(
        stream.policy is None or stream.policy.mode == "off"
        for stream in document.streams
    )
    assert {stream.value_type for stream in document.streams} == {
        "number",
        "boolean",
        "text",
        "identifier",
    }
    assert len(document.connections) == 1
    connection = document.connections[0]
    assert (connection.host, connection.port, connection.tls) == (
        "source-broker",
        1883,
        False,
    )
    assert connection.credential_ref is None


@pytest.mark.parametrize("tick", [0, 1, 29, 30, 39, 40, 1000])
def test_workshop_messages_match_all_fixture_topics_pointers_and_types(tick):
    document = SystemDocument.model_validate_json(WORKSHOP_FIXTURE.read_text())
    messages = dict(build_workshop_messages(tick, 1.0))
    assert {stream.topic for stream in document.streams} == set(messages)
    assert len(messages) == 3
    for stream in document.streams:
        pointer = stream.payload_pointer
        assert pointer is not None and pointer.startswith("/")
        value = messages[stream.topic][pointer[1:]]
        if stream.value_type == "number":
            assert type(value) is float and math.isfinite(value)
        elif stream.value_type == "boolean":
            assert type(value) is bool
        else:
            assert isinstance(value, str) and value
    assert all(len(json.dumps(payload)) < 256 for payload in messages.values())


def test_workshop_values_follow_configurable_elapsed_time_and_change():
    early = dict(build_workshop_messages(0, 1.0))
    later = dict(build_workshop_messages(15, 2.0))
    assert later == dict(build_workshop_messages(30, 1.0))
    assert early["workshop/office/environment"] != later["workshop/office/environment"]
    assert early["workshop/workbench/status"]["running"] is True
    assert later["workshop/workbench/status"]["running"] is False
    assert later["workshop/workbench/status"]["mode"] == "Idle"
    assert (
        dict(build_workshop_messages(40, 1.0))["workshop/workbench/status"]["cycle_id"]
        == "cycle-0002"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_run_transmits_workshop_only_when_enabled_without_changing_charging(
    monkeypatch, enabled
):
    config = SimulatorSettings(
        _env_file=None, SIMULATOR_WORKSHOP_ENABLED=enabled
    ).config
    service = SimulatorService(config)
    service.start = AsyncMock()
    service.stop = AsyncMock()
    service._build_value = MagicMock(return_value=12.34567)
    service._inject_blip = lambda value: (value, False)
    service._client = MagicMock()

    async def end_after_tick(_):
        service.request_shutdown()

    monkeypatch.setattr("off_key_mqtt_simulator.__main__.asyncio.sleep", end_after_tick)
    await service.run()
    messages = {
        call.args[0]: json.loads(call.args[1])
        for call in service._client.publish.call_args_list
    }
    charging_topics = {
        service._build_topic(charger, feature)
        for charger in config.charger_ids
        for feature in config.features
    }
    assert {
        topic for topic in messages if not topic.startswith("workshop/")
    } == charging_topics
    assert all(messages[topic] == 12.3457 for topic in charging_topics)
    expected_workshop = (
        dict(build_workshop_messages(0, config.interval_seconds)) if enabled else {}
    )
    assert {
        topic: payload
        for topic, payload in messages.items()
        if topic.startswith("workshop/")
    } == expected_workshop
    assert all(
        call.kwargs == {"qos": config.qos, "retain": False}
        for call in service._client.publish.call_args_list
    )


def test_simulator_client_has_a_bounded_pending_publish_queue(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "off_key_mqtt_simulator.__main__.mqtt.Client", lambda **_: client
    )
    SimulatorService(SimulatorSettings(_env_file=None).config)
    client.max_queued_messages_set.assert_called_once_with(64)
