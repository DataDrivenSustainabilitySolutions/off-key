import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_mqtt_simulator.__main__ import SimulatorService
from off_key_mqtt_simulator.config import SimulatorSettings


@pytest.mark.asyncio
async def test_simulator_publishes_ambibox_scalars_for_each_sensor(monkeypatch):
    service = SimulatorService(SimulatorSettings(_env_file=None).config)
    service.start = AsyncMock()
    service.stop = AsyncMock()
    service._build_value = MagicMock(return_value=12.34567)
    service._inject_blip = lambda value: (value, False)
    service._client = MagicMock()

    async def end_after_tick(_):
        service.request_shutdown()

    monkeypatch.setattr("off_key_mqtt_simulator.__main__.asyncio.sleep", end_after_tick)
    await service.run()
    expected_topics = {
        service._build_topic(charger, feature)
        for charger in service.config.charger_ids
        for feature in service.config.features
    }
    published = service._client.publish.call_args_list
    assert {call.args[0] for call in published} == expected_topics
    assert all(json.loads(call.args[1]) == 12.3457 for call in published)
