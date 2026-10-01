from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.encoders import jsonable_encoder
from off_key_core.db.models import CollectionConfiguration, User
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.v1 import collection

from .test_collection import catalog


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [collection.get_catalog, collection.get_status])
async def test_sensor_activity_reports_live_and_retained_receipts_for_members(
    endpoint, monkeypatch
):
    monkeypatch.setattr(
        collection,
        "get_ambibox_settings",
        lambda: SimpleNamespace(AMBIBOX_INGRESS_ENABLED=True),
    )
    received = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    state = {"revision": 1, "status": "applied"}
    result = MagicMock()
    result.first.return_value = (1, state, state)
    result.__iter__.return_value = [
        ("charger-a", "temperature", received, False),
        ("charger-b", "temperature", received, True),
    ]
    session = AsyncMock()
    session.execute.return_value = result
    session.scalar.return_value = CollectionConfiguration(
        id=1,
        revision=1,
        document=catalog().model_dump(mode="json"),
        ingress_status=state,
        collection_status=state,
        updated_at=received,
        updated_by="admin@example.com",
    )

    response = jsonable_encoder(
        await endpoint(user=User(role=RoleEnum.user), session=session)
    )
    activity = response["sensor_activity"]
    assert set(activity) == {"charger-a", "charger-b"}
    for charger_id, retained in (("charger-a", False), ("charger-b", True)):
        observation = activity[charger_id]["temperature"]
        assert set(observation) == {"received_at", "is_snapshot"}
        assert datetime.fromisoformat(observation["received_at"]) == received
        assert observation["is_snapshot"] is retained
    if endpoint is collection.get_catalog:
        assert response["can_edit"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [collection.get_catalog, collection.get_status])
@pytest.mark.parametrize(
    "state",
    [
        {},
        {"revision": 0, "status": "applied"},
        {"revision": 1, "status": "applying"},
        {"revision": 1, "status": "error"},
    ],
)
async def test_unapplied_catalogs_do_not_expose_previous_sensor_activity(
    endpoint, state, monkeypatch
):
    monkeypatch.setattr(
        collection,
        "get_ambibox_settings",
        lambda: SimpleNamespace(AMBIBOX_INGRESS_ENABLED=True),
    )
    result = MagicMock()
    result.first.return_value = (1, {}, state)
    result.__iter__.return_value = [
        ("old-charger", "temperature", datetime.now(UTC), False)
    ]
    session = AsyncMock()
    session.execute.return_value = result
    session.scalar.return_value = CollectionConfiguration(
        id=1,
        revision=1,
        document=catalog().model_dump(mode="json"),
        ingress_status={},
        collection_status=state,
        updated_at=datetime.now(UTC),
        updated_by="admin@example.com",
    )

    response = await endpoint(user=User(role=RoleEnum.user), session=session)
    assert response["sensor_activity"] == {}
