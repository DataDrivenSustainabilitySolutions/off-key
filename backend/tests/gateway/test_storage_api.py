from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from off_key_core.db.models import User
from off_key_core.schemas.storage import RetentionPolicyStatus, StorageStatus
from off_key_tactic_middleware.services.catalogue import system as system_service

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app
from tests.support.http import asgi_client
from tests.support.tokens import access_token


@pytest.mark.asyncio
async def test_storage_requires_a_verified_user_and_returns_database_measurements(
    monkeypatch,
):
    set_auth_env(monkeypatch)
    user = User(
        id=1,
        email="user@example.com",
        is_verified=False,
        is_active=True,
        session_version=0,
    )
    session = AsyncMock()
    session.scalar.return_value = user
    status = StorageStatus(
        database_size_bytes=12345678,
        retention_policies=[
            RetentionPolicyStatus(table="telemetry", retention_days=30, scheduled=True)
        ],
        checked_at=datetime.now(UTC),
    )
    read = AsyncMock(return_value=status)
    monkeypatch.setattr(system_service, "read_storage_status", read)
    app = gateway_app(session=session)
    token = access_token(user, session_version=0)
    async with asgi_client(app) as client:
        assert (await client.get("/v1/storage")).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/v1/storage", headers=headers)).status_code == 401
        read.assert_not_awaited()
        user.is_verified = True
        response = await client.get("/v1/storage", headers=headers)
        assert response.status_code == 200
        assert response.json() == status.model_dump(mode="json")
        read.assert_awaited_once_with(session)
