from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from off_key_core.db.models import Anomaly, AnomalyIdentity
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.schemas import AnomalyCreateRequest
from off_key_tactic_middleware.services.data.anomalies import AnomalyService


def test_anomaly_payload_table_has_no_anomaly_id_column():
    assert "anomaly_id" not in Anomaly.__table__.columns.keys()


def test_anomaly_identity_table_owns_global_anomaly_id_primary_key():
    assert "anomaly_id" in AnomalyIdentity.__table__.columns.keys()
    assert AnomalyIdentity.__table__.columns["anomaly_id"].primary_key is True
    assert AnomalyIdentity.__table__.columns["anomaly_id"].server_default is not None


@pytest.mark.asyncio
async def test_create_anomaly_returns_repository_identity_id():
    session = AsyncMock()
    repository = MagicMock()
    generated_id = str(uuid.uuid4())
    repository.add = AsyncMock(return_value=generated_id)

    service = AnomalyService(session, repository)
    payload = AnomalyCreateRequest(
        charger_id="charger-1",
        timestamp=datetime.now(timezone.utc),
        telemetry_type="voltage",
        anomaly_type="ml_detected",
        anomaly_value=0.91,
    )

    result = await service.create_anomaly(payload=payload)

    assert result["anomaly_id"] == generated_id
    repository.add.assert_awaited_once()
    call_args = repository.add.await_args.args
    assert len(call_args) == 1
    assert call_args[0].charger_id == payload.charger_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_anomaly_maps_integrity_error_to_conflict():
    session = AsyncMock()
    repository = MagicMock()
    repository.add = AsyncMock(
        side_effect=IntegrityError(
            statement="INSERT INTO anomaly_identity ...",
            params={},
            orig=Exception("duplicate key value violates unique constraint"),
        )
    )

    service = AnomalyService(session, repository)
    payload = AnomalyCreateRequest(
        charger_id="charger-1",
        timestamp=datetime.now(timezone.utc),
        telemetry_type="voltage",
        anomaly_type="ml_detected",
        anomaly_value=0.91,
    )

    with pytest.raises(ConflictError, match="Anomaly already exists"):
        await service.create_anomaly(payload=payload)

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_anomaly_uses_identity_lookup_and_delete():
    session = AsyncMock()
    repository = MagicMock()
    anomaly = SimpleNamespace(
        charger_id="charger-1",
        timestamp=datetime.now(timezone.utc),
    )
    repository.get_by_anomaly_id = AsyncMock(return_value=("id-1", anomaly))
    repository.delete = AsyncMock()

    service = AnomalyService(session, repository)
    response = await service.delete_anomaly(anomaly_id="id-1")

    assert response == {"message": "Anomaly deleted"}
    repository.delete.assert_awaited_once_with(anomaly)
    session.commit.assert_awaited_once()
