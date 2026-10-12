import pytest
from fastapi import HTTPException
from off_key_api_gateway.api.v1 import auth as gateway_auth


@pytest.mark.asyncio
async def test_public_registration_is_closed():
    with pytest.raises(HTTPException) as denied:
        await gateway_auth.register()
    assert denied.value.status_code == 403
