"""Collection administration trusts the stored role, never the client."""

import pytest


@pytest.mark.asyncio
async def test_require_admin_does_not_trust_client_role():
    from fastapi import HTTPException
    from off_key_core.db.models import User
    from off_key_core.utils.enum import RoleEnum
    from off_key_tactic_middleware.api.collection_auth import require_admin

    with pytest.raises(HTTPException) as error:
        await require_admin(User(role=RoleEnum.user))
    assert error.value.status_code == 403
    admin = User(role=RoleEnum.admin)
    assert await require_admin(admin) is admin
