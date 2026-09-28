from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from jose import jwt
from off_key_api_gateway.api.v1 import collection as gateway
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.schemas.storage import RetentionPolicyStatus, StorageStatus
from off_key_tactic_middleware.api.v1 import collection

from .test_gateway_auth_token_types import _set_auth_env


@pytest.mark.asyncio
async def test_storage_requires_a_verified_user_and_returns_database_measurements(
    monkeypatch,
):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    user = User(id=1, email="user@example.com", is_verified=False)
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
    monkeypatch.setattr(collection, "read_storage_status", read)
    app = FastAPI()
    app.include_router(collection.router)
    app.dependency_overrides[get_db_async] = lambda: session
    token = jwt.encode(
        {
            "sub": user.email,
            "user_id": user.id,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/collection/storage")).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            await client.get("/collection/storage", headers=headers)
        ).status_code == 403
        read.assert_not_awaited()
        user.is_verified = True
        response = await client.get("/collection/storage", headers=headers)
        assert response.status_code == 200
        assert response.json() == status.model_dump(mode="json")
        read.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_gateway_forwards_storage_token_and_denies_anonymous_requests(
    monkeypatch,
):
    request = AsyncMock(return_value={"database_size_bytes": 123})
    monkeypatch.setattr(gateway.tactic, "_make_request", request)
    with pytest.raises(HTTPException) as denied:
        await gateway.get_storage(None)
    assert denied.value.status_code == 401
    request.assert_not_awaited()
    assert await gateway.get_storage("Bearer access-token") == {
        "database_size_bytes": 123
    }
    request.assert_awaited_once_with(
        "GET",
        "/api/v1/collection/storage",
        json_data=None,
        headers={"Authorization": "Bearer access-token"},
    )
