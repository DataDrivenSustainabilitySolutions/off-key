"""Setup-form launches become pipeline activations bound to catalogue readings."""

from types import SimpleNamespace

import pytest
from off_key_core.schemas.radar import FormMonitorConfig, PerformanceConfig
from off_key_tactic_middleware.domain import ConflictError, ValidationError
from off_key_tactic_middleware.services.pipelines import forms


def stream(topic, reading_id, value_type="number"):
    return SimpleNamespace(
        accepted_topic=topic,
        value_type=value_type,
        definition=SimpleNamespace(id=reading_id),
    )


@pytest.fixture
def submitted(monkeypatch):
    calls = []

    class Activations:
        def __init__(self, session, workloads=None):
            pass

        async def apply_form(self, request, performance):
            calls.append((request, performance))
            return SimpleNamespace(id="activation", service_id="service")

        async def form_launch(self, request, saved):
            if saved.container_name == "unapplied":
                raise ConflictError("Wait for the collection configuration")
            calls.append((request, saved))
            return "launch", "metadata"

    async def snapshot(_session):
        streams = [
            stream("telemetry/c1/L1", "reading-l1"),
            stream("telemetry/c1/L2", "reading-l2"),
            stream("telemetry/c1/state", "reading-state", value_type="string"),
        ]
        return SimpleNamespace(
            catalog=SimpleNamespace(streams=lambda selected_only: streams)
        )

    monkeypatch.setattr(forms, "PipelineActivations", Activations)
    monkeypatch.setattr(forms, "read_collection_runtime", snapshot)
    return calls


def form(**changes):
    return FormMonitorConfig.model_validate(
        {
            "container_name": "radar-c1-1",
            "mqtt_topics": ["telemetry/c1/L2", "telemetry/c1/L1"],
            "performance_config": {"sensor_freshness_seconds": 12},
            **changes,
        }
    )


@pytest.mark.asyncio
async def test_form_binds_slots_in_sensor_key_order_and_keeps_performance(submitted):
    activation = await forms.start_form_monitor(None, form(display_name="Pump"))

    assert activation.service_id == "service"
    [(request, performance)] = submitted
    assert [slot.label for slot in request.definition.input_slots] == ["L1", "L2"]
    assert request.bindings == {"input_1": "reading-l1", "input_2": "reading-l2"}
    assert request.display_name == "Pump"
    assert request.idempotency_key.startswith("form-")
    assert performance == PerformanceConfig(sensor_freshness_seconds=12)


@pytest.mark.asyncio
async def test_form_without_display_name_uses_its_container_name(submitted):
    await forms.start_form_monitor(None, form())

    assert submitted[0][0].display_name == "radar-c1-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topics", [["telemetry/c1/L1", "telemetry/c1/L9"], ["telemetry/c1/state"]]
)
async def test_form_rejects_topics_without_a_selected_numeric_reading(
    submitted, topics
):
    with pytest.raises(ValidationError, match="Select these topics"):
        await forms.start_form_monitor(None, form(mqtt_topics=topics))

    assert submitted == []


@pytest.mark.asyncio
async def test_saved_form_monitor_converts_to_the_equivalent_pipeline(submitted):
    saved = form(display_name="Pump").model_dump(mode="json")

    assert await forms.convert_saved_form_monitor(None, saved) == (
        "launch",
        "metadata",
    )
    [(request, parsed)] = submitted
    assert request.bindings == {"input_1": "reading-l1", "input_2": "reading-l2"}
    assert parsed.container_name == "radar-c1-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "saved",
    [
        {"mqtt_topics": ["telemetry/c1/L9"]},
        {"monitoring": {"strategy": "unsupported"}},
    ],
)
async def test_saved_form_monitor_without_its_readings_is_retired(submitted, saved):
    launch = form().model_dump(mode="json") | saved

    with pytest.raises(forms.UnconvertibleFormMonitor):
        await forms.convert_saved_form_monitor(None, launch)
    assert submitted == []


@pytest.mark.asyncio
async def test_unapplied_collection_blocks_the_release_instead_of_retiring(
    submitted,
):
    saved = form(container_name="unapplied").model_dump(mode="json")

    with pytest.raises(ValueError, match="Wait") as error:
        await forms.convert_saved_form_monitor(None, saved)
    assert not isinstance(error.value, forms.UnconvertibleFormMonitor)
