"""Permission checks trust the stored role, never the client."""

import pytest


@pytest.mark.asyncio
async def test_permission_checks_follow_the_stored_role():
    from fastapi import HTTPException
    from off_key_api_gateway.api.access import require_permission
    from off_key_core.auth.permissions import ADMIN_ROLE, MEMBER_ROLE, Permission
    from off_key_core.db.models import MemberRole, User

    manage_alarms = require_permission(Permission.manage_alarms)
    assert require_permission(Permission.manage_alarms) is manage_alarms
    with pytest.raises(HTTPException) as error:
        await manage_alarms(User(role=MEMBER_ROLE))
    assert error.value.status_code == 403
    assert "manage_alarms" in error.value.detail
    admin = User(role=ADMIN_ROLE)
    assert await manage_alarms(admin) is admin
    # A stored grant counts; an unknown value a later release dropped does not.
    operator = User(
        role="operator",
        member_role=MemberRole(id="operator", permissions=["manage_alarms", "gone"]),
    )
    assert await manage_alarms(operator) is operator
    assert operator.permissions == [Permission.manage_alarms]
