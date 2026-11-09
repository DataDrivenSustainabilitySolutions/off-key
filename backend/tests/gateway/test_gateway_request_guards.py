"""Gateway body size and per-client rate limits applied before routing."""

from aberration_api_gateway.api.request_guards import (
    DEFAULT_MAX_BODY_BYTES,
    BodySizeLimitMiddleware,
    ClientRateLimitMiddleware,
)
from aberration_core.schemas.dojo import MAX_UPLOAD_BYTES
from fastapi import Depends, FastAPI, HTTPException, Request

from tests.support.http import asgi_client


def _deny():
    raise HTTPException(status_code=401)


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/protected", dependencies=[Depends(_deny)])
    async def protected(request: Request):
        return {"size": len(await request.body())}

    @app.post("/v1/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    return app


def test_only_the_csv_import_accepts_large_uploads():
    limit = BodySizeLimitMiddleware.limit_for
    assert limit("POST", "/v1/dojo/datasets/csv") == MAX_UPLOAD_BYTES
    assert limit("POST", "/v1/dojo/datasets/csv/") == MAX_UPLOAD_BYTES
    assert limit("PUT", "/v1/dojo/datasets/csv") == DEFAULT_MAX_BODY_BYTES
    assert limit("POST", "/v1/auth/login") == DEFAULT_MAX_BODY_BYTES


async def test_declared_oversized_bodies_are_refused_before_authentication():
    app = _app()
    app.add_middleware(BodySizeLimitMiddleware, limits=lambda *_: 10)

    async with asgi_client(app) as client:
        response = await client.post("/v1/protected", content=b"x" * 11)
        small = await client.post("/v1/echo", content=b"x" * 10)

    assert response.status_code == 413
    assert small.json() == {"size": 10}


async def test_streamed_bodies_stop_at_the_limit():
    app = _app()
    app.add_middleware(BodySizeLimitMiddleware, limits=lambda *_: 10)

    async def chunks():
        for _ in range(4):
            yield b"x" * 5

    async with asgi_client(app) as client:
        response = await client.post("/v1/echo", content=chunks())

    assert response.status_code == 413


async def test_invalid_content_length_is_rejected():
    app = _app()
    app.add_middleware(BodySizeLimitMiddleware)

    async with asgi_client(app) as client:
        response = await client.post(
            "/v1/echo", content=b"{}", headers={"content-length": "abc"}
        )

    assert response.status_code == 400


async def test_each_client_gets_its_own_window():
    now = [0.0]
    app = _app()
    app.add_middleware(
        ClientRateLimitMiddleware, limit=3, window=60, clock=lambda: now[0]
    )

    async with asgi_client(app) as client:
        statuses = [(await client.post("/v1/protected")).status_code for _ in range(4)]
        limited = await client.post("/v1/unknown")
        other = await client.post(
            "/v1/echo", headers={"x-forwarded-for": "198.51.100.7"}
        )
        now[0] = 60
        reset = await client.post("/v1/echo")

    # Anonymous requests to protected and unknown paths count too.
    assert statuses == [401, 401, 401, 429]
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) == 60
    assert other.status_code == 200
    assert reset.status_code == 200
