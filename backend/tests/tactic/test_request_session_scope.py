"""A write is committed before TACTIC answers it."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.db.base import get_db_async
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.provider import RequestSession, get_system_service

TACTIC = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "middleware"
    / "tactic"
    / "src"
    / "off_key_tactic_middleware"
)


@pytest.mark.asyncio
async def test_session_ends_before_the_response_starts():
    events: list[str] = []

    async def session():
        events.append("open")
        yield object()
        events.append("commit")

    app = FastAPI()
    app.dependency_overrides[get_db_async] = session

    @app.put("/saved")
    async def save(first=RequestSession, second=RequestSession):
        assert first is second
        events.append("route")
        return {"saved": True}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(message["type"])

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "http",
            "path": "/saved",
            "raw_path": b"/saved",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )

    assert events == [
        "open",
        "route",
        "commit",
        "http.response.start",
        "http.response.body",
    ]


def test_a_failed_commit_is_answered_as_a_failure():
    """Before, the caller had already received its 200 when the commit failed."""

    async def session():
        yield object()
        raise RuntimeError("commit failed")

    app = FastAPI()
    app.dependency_overrides[get_db_async] = session

    @app.put("/saved")
    async def save(_=RequestSession):
        return {"saved": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.put("/saved").status_code == 500


def test_members_and_services_share_the_request_session():
    """Both would otherwise open their own session and transaction."""
    for provider in (current_member, get_system_service):
        defaults = provider.__defaults__ or ()
        assert any(default is RequestSession for default in defaults), provider


def test_every_tactic_session_dependency_uses_the_request_session():
    offenders = [
        str(path.relative_to(TACTIC))
        for path in sorted(TACTIC.rglob("*.py"))
        if "Depends(get_db_async)" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
