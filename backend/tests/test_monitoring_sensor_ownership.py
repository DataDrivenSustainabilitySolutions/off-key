from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)


def _query_result(active_services):
    result = MagicMock()
    result.scalars.return_value.all.return_value = active_services
    return result


def _service_with_session(session):
    service = object.__new__(RadarOrchestrationService)
    service.session = session
    service.model_registry = MagicMock()
    service._get_docker_status_and_labels = AsyncMock(return_value=("running", {}))
    return service


@pytest.mark.asyncio
async def test_sensor_claim_rejects_overlapping_wildcard():
    session = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    session.execute.side_effect = [
        MagicMock(),
        _query_result(
            [
                SimpleNamespace(
                    container_name="radar-existing",
                    mqtt_topic=["charger/charger-1/live-telemetry/#"],
                )
            ]
        ),
    ]
    service = _service_with_session(session)

    with pytest.raises(ValueError, match="one monitoring service"):
        await service._assert_topics_available(
            mqtt_topics=["charger/charger-1/live-telemetry/L1"],
            container_name="radar-new",
        )

    assert "pg_advisory_xact_lock" in str(session.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_sensor_claim_preserves_literal_namespace_boundaries():
    session = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute.return_value = _query_result(
        [
            SimpleNamespace(
                container_name="radar-existing",
                mqtt_topic=["charger/charger-1/telemetry/#"],
            )
        ]
    )
    service = _service_with_session(session)

    await service._assert_topics_available(
        mqtt_topics=["charger/charger-1/live-telemetry/L1"],
        container_name="radar-new",
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_sensor_claim_ignores_current_container_for_idempotent_start():
    session = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute.return_value = _query_result(
        [
            SimpleNamespace(
                container_name="radar-same",
                mqtt_topic=["charger/+/live-telemetry/#"],
            )
        ]
    )
    service = _service_with_session(session)

    await service._assert_topics_available(
        mqtt_topics=["charger/charger-1/live-telemetry/L1"],
        container_name="radar-same",
    )


@pytest.mark.asyncio
async def test_sensor_claim_releases_missing_workload_before_overlap_check():
    session = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    stale_service = SimpleNamespace(
        container_name="radar-dead",
        container_id="missing-container",
        mqtt_topic=["charger/charger-1/live-telemetry/L1"],
        status=True,
        operational_status={},
        operational_stage="operational",
        operational_updated_at=None,
    )
    session.execute.return_value = _query_result([stale_service])
    service = _service_with_session(session)
    service._get_docker_status_and_labels.return_value = ("not_found", {})

    await service._assert_topics_available(
        mqtt_topics=["charger/charger-1/live-telemetry/L1"],
        container_name="radar-replacement",
    )

    assert stale_service.status is False
    session.flush.assert_awaited_once()
