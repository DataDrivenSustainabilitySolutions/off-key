import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aberration_core.db.models import Anomaly, AnomalyIdentity
from aberration_core.schemas.alarms import AlarmCreate
from aberration_core.schemas.system import SystemDocument, SystemRuntime, SystemSnapshot
from aberration_tactic_middleware.domain import ConflictError, NotFoundError
from aberration_tactic_middleware.repositories.data import AnomalyRepository
from aberration_tactic_middleware.services.data.alarms import AlarmService
from sqlalchemy.exc import IntegrityError


def test_anomaly_payload_table_has_no_anomaly_id_column():
    assert "anomaly_id" not in Anomaly.__table__.columns


def test_anomaly_payload_table_includes_sensor_set_column():
    assert "sensor_set" in Anomaly.__table__.columns


def test_anomaly_identity_table_owns_global_anomaly_id_primary_key():
    assert "anomaly_id" in AnomalyIdentity.__table__.columns
    assert AnomalyIdentity.__table__.columns["anomaly_id"].primary_key is True
    assert AnomalyIdentity.__table__.columns["anomaly_id"].server_default is not None


CATALOGUE = SystemSnapshot(
    revision=1,
    storage_origin="saved",
    document=SystemDocument(
        connections=[{"id": "broker", "label": "Site", "host": "broker"}],
        devices=[{"id": "charger", "label": "Charger", "connection_id": "broker"}],
        streams=[
            {
                "id": key,
                "label": key.title(),
                "connection_id": "broker",
                "device_id": "charger",
                "topic": f"charger/{key}",
            }
            for key in ("voltage", "current")
        ],
    ),
    runtime=SystemRuntime(
        bindings={
            key: {"entity_id": "charger-1", "telemetry_key": f"key-{key}"}
            for key in ("voltage", "current")
        }
    ),
)


def alarm(**fields) -> AlarmCreate:
    return AlarmCreate(
        **{
            "reading_ids": ["voltage"],
            "timestamp": datetime.now(UTC),
            "alarm_type": "ml_detected",
            "value": 0.91,
        }
        | fields
    )


@pytest.mark.asyncio
async def test_create_alarm_returns_repository_identity_id():
    session = AsyncMock()
    repository = MagicMock()
    generated_id = str(uuid.uuid4())
    repository.add = AsyncMock(return_value=generated_id)

    service = AlarmService(session, repository)
    result = await service.create_alarm(alarm(), CATALOGUE)

    assert result.alarm_id == generated_id
    assert (result.device_id, result.reading_ids) == ("charger", ["voltage"])
    repository.add.assert_awaited_once()
    call_args = repository.add.await_args.args
    assert len(call_args) == 1
    assert call_args[0].charger_id == "charger-1"
    assert call_args[0].telemetry_type == "key-voltage"
    assert call_args[0].value_type == "zscore"
    assert call_args[0].service_id == ""
    session.commit.assert_awaited_once()


async def persisted(**fields):
    """The anomaly row AlarmService hands to the repository for a payload."""
    repository = MagicMock()
    repository.add = AsyncMock(return_value="id-1")
    await AlarmService(AsyncMock(), repository).create_alarm(
        alarm(value=0.0012, **fields), CATALOGUE
    )
    return repository.add.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alarm_type", "value_type", "expected"),
    [
        ("ml_tailprob_univariate", "tail_pvalue", "tail_pvalue"),
        ("ml_tailprob_multivariate", None, "tail_pvalue"),
        ("ml_conformal_static_multivariate", None, "conformal_pvalue"),
    ],
)
async def test_create_alarm_persists_explicit_or_derived_value_type(
    alarm_type, value_type, expected
):
    row = await persisted(alarm_type=alarm_type, value_type=value_type)
    assert row.value_type == expected


@pytest.mark.asyncio
async def test_create_alarm_records_each_named_reading_once():
    row = await persisted(
        reading_ids=["current", "voltage", "current"],
        alarm_type="ml_conformal_static_multivariate",
        value_type="conformal_pvalue",
    )
    assert row.telemetry_type == "__multivariate__"
    assert row.sensor_set == ["key-current", "key-voltage"]


@pytest.mark.asyncio
async def test_create_alarm_maps_integrity_error_to_conflict():
    session = AsyncMock()
    repository = MagicMock()
    repository.add = AsyncMock(
        side_effect=IntegrityError(
            statement="INSERT INTO anomaly_identity ...",
            params={},
            orig=Exception("duplicate key value violates unique constraint"),
        )
    )

    service = AlarmService(session, repository)

    with pytest.raises(ConflictError, match="Alarm already exists"):
        await service.create_alarm(alarm(), CATALOGUE)

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_alarm_uses_identity_lookup_and_delete():
    session = AsyncMock()
    repository = MagicMock()
    anomaly = SimpleNamespace(
        charger_id="charger-1",
        timestamp=datetime.now(UTC),
    )
    repository.get_by_anomaly_id = AsyncMock(return_value=("id-1", anomaly))
    repository.delete = AsyncMock()

    service = AlarmService(session, repository)
    await service.delete_alarm(alarm_id="id-1")

    repository.delete.assert_awaited_once_with(anomaly)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_alarm_of_unknown_id_is_not_found():
    repository = MagicMock()
    repository.get_by_anomaly_id = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError, match="Alarm not found"):
        await AlarmService(AsyncMock(), repository).delete_alarm(alarm_id="id-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("service_id", ["", "monitor-1"])
async def test_list_alarms_includes_value_type_and_monitor(service_id):
    session = AsyncMock()
    repository = MagicMock()
    timestamp = datetime.now(UTC)
    anomaly = SimpleNamespace(
        charger_id="charger-1",
        timestamp=timestamp,
        telemetry_type="key-voltage",
        anomaly_type="ml_tailprob_univariate",
        anomaly_value=0.0025,
        value_type="tail_pvalue",
        sensor_set=["key-voltage"],
        service_id=service_id,
    )
    repository.page = AsyncMock(return_value=[("anomaly-1", anomaly)])

    service = AlarmService(session, repository)
    rows = await service.list_alarms(
        CATALOGUE, device_id="charger", stream_ids=None, service_id=None, limit=10
    )

    assert [row.model_dump() for row in rows] == [
        {
            "alarm_id": "anomaly-1",
            "timestamp": timestamp,
            "device_id": "charger",
            "device_label": "Charger",
            "reading_ids": ["voltage"],
            "reading_labels": {"voltage": "Voltage"},
            "multivariate": False,
            "alarm_type": "ml_tailprob_univariate",
            "value": 0.0025,
            "value_type": "tail_pvalue",
            "monitor_id": service_id or None,
        }
    ]
    filters = repository.page.await_args.args[0]
    assert filters.scope.pairs == {
        ("charger-1", "key-voltage"),
        ("charger-1", "key-current"),
    }
    assert filters.scope.whole_entities == {"charger-1"}


@pytest.mark.asyncio
async def test_repository_add_reuses_trigger_created_identity():
    session = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    identity_result = MagicMock()
    identity_result.scalar_one_or_none.return_value = "existing-id"
    session.execute = AsyncMock(return_value=identity_result)

    repository = AnomalyRepository(session)
    anomaly = SimpleNamespace(
        charger_id="charger-1",
        timestamp=datetime.now(UTC),
        telemetry_type="voltage",
        service_id="monitor-1",
    )

    anomaly_id = await repository.add(anomaly)

    assert anomaly_id == "existing-id"
    assert session.add.call_count == 1
    session.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_add_falls_back_when_identity_missing():
    session = MagicMock()
    session.flush = AsyncMock()

    async def _refresh(identity):
        identity.anomaly_id = "generated-id"

    session.refresh = AsyncMock(side_effect=_refresh)
    identity_result = MagicMock()
    identity_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=identity_result)

    repository = AnomalyRepository(session)
    anomaly = SimpleNamespace(
        charger_id="charger-1",
        timestamp=datetime.now(UTC),
        telemetry_type="voltage",
        service_id="monitor-1",
    )

    anomaly_id = await repository.add(anomaly)

    assert anomaly_id == "generated-id"
    assert session.add.call_count == 2
    assert session.add.call_args.args[0].service_id == "monitor-1"
    session.refresh.assert_awaited_once()
