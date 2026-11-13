"""Keys for agents: how a key is made and kept, and which routes it opens.

An agent signs in with a key in place of a member's token. A route is closed
to keys unless it says otherwise, so a new route belongs to members until
someone decides to open it.
"""

import secrets
from enum import StrEnum
from hashlib import sha256

AGENT_KEY_PREFIX = "offkey_"
# The key under a route's `openapi_extra`, so the API document shows it too.
AGENT_ACCESS = "x-agent-access"


class AgentAccess(StrEnum):
    """What a route asks of a key."""

    any_key = "any"
    start = "start"


class AgentStarts(StrEnum):
    """What a key may start without a member's decision."""

    nothing = "nothing"
    shadow = "shadow"
    live = "live"


OPEN_TO_AGENTS = {AGENT_ACCESS: AgentAccess.any_key.value}
"""`openapi_extra` of a route every key may call."""
STARTS_SERVICES = {AGENT_ACCESS: AgentAccess.start.value}
"""`openapi_extra` of a route only a key that may start services may call,
in shadow or live."""


def new_agent_key() -> str:
    return AGENT_KEY_PREFIX + secrets.token_urlsafe(32)


def is_agent_key(credential: str) -> bool:
    return credential.startswith(AGENT_KEY_PREFIX)


def agent_key_digest(key: str) -> str:
    """What is stored in place of a key. A key is long and random, so a plain
    digest cannot be searched for it."""
    return sha256(key.encode()).hexdigest()


def agent_key_hint(key: str) -> str:
    """The end of a key, enough to tell one from another."""
    return key[-4:]


def agent_refusal(route: object, *, starts: str) -> str | None:
    """Why a key may not call ``route``, or None where it may."""
    access = (getattr(route, "openapi_extra", None) or {}).get(AGENT_ACCESS)
    if access is None:
        return "A key for an agent cannot do this. It needs a member."
    if access == AgentAccess.start and starts == AgentStarts.nothing:
        return (
            "This key may not start monitoring services. "
            "A member who manages members can allow it."
        )
    return None


def shadow_refusal(*, starts: str, shadow: bool) -> str | None:
    """Why a key may not start a service that raises alarms, or None where it may."""
    if starts == AgentStarts.shadow and not shadow:
        return (
            "This key may start monitoring services in shadow only. Start with "
            "`shadow` set, or propose the design for a member to start it live."
        )
    return None
