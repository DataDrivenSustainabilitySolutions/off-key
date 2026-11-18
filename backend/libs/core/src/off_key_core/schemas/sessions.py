from pydantic import BaseModel, Field

# Every browser sign-in keeps a revocable session behind an HttpOnly cookie, so
# open tabs renew their short access tokens silently. Its lifetime is absolute:
# renewals never extend it, and the member signs in again when it ends.
# "Remember this device" keeps the cookie across browser restarts for 30 days.
REMEMBERED_SESSION_SECONDS = 30 * 24 * 60 * 60
# Otherwise the cookie ends with the browser, and at the latest after a working day.
BROWSER_SESSION_SECONDS = 12 * 60 * 60


def session_lifetime_seconds(persistent: bool) -> int:
    return REMEMBERED_SESSION_SECONDS if persistent else BROWSER_SESSION_SECONDS


class RememberedSessionToken(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
