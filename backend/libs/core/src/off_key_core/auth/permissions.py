"""What a member may change. Permissions are fixed here; roles bundle them.

Every member can read the organization's data. A permission allows changes in
one area, and a role grants a set of them. ``admin`` always holds every
permission, including ones a later release adds, and cannot be edited, so an
installation can always be managed. ``user`` starts with none.
"""

from collections.abc import Iterable
from enum import StrEnum


class Permission(StrEnum):
    manage_sources = "manage_sources"
    manage_monitors = "manage_monitors"
    manage_alarms = "manage_alarms"
    use_dojo = "use_dojo"
    manage_members = "manage_members"


PERMISSION_DESCRIPTIONS = {
    Permission.manage_sources: (
        "Edit the catalogue and brokers, control recording and open live views."
    ),
    Permission.manage_monitors: (
        "Design pipelines, start, rename and stop monitors, and arrange their layout."
    ),
    Permission.manage_alarms: "Record and delete alarms.",
    Permission.use_dojo: (
        "Import datasets into the Dojo and replay them through detectors offline."
    ),
    Permission.manage_members: (
        "Invite, change and remove members, and define roles. Holders also hold "
        "the keys to every other permission, since they can assign any role."
    ),
}

ADMIN_ROLE = "admin"
MEMBER_ROLE = "user"
BUILT_IN_ROLES = {ADMIN_ROLE: "Administrator", MEMBER_ROLE: "Member"}
ROLE_ID_PATTERN = r"^[a-z][a-z0-9-]{1,39}$"


def known_permissions(granted: Iterable[str]) -> list[Permission]:
    """Known permissions among ``granted``, once each, in a stable order."""
    granted = set(granted)
    return [permission for permission in Permission if permission in granted]


def role_permissions(role: str, granted: Iterable[str]) -> list[Permission]:
    """The permissions a role grants; admin holds all."""
    return list(Permission) if role == ADMIN_ROLE else known_permissions(granted)
