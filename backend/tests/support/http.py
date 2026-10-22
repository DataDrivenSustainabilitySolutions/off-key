"""In-process HTTP clients for ASGI apps."""

from httpx import ASGITransport, AsyncClient


def asgi_client(
    app, base_url: str = "http://test", client: tuple[str, int] | None = None
) -> AsyncClient:
    """An AsyncClient that calls the app directly, optionally from a peer address."""
    transport = (
        ASGITransport(app=app)
        if client is None
        else ASGITransport(app=app, client=client)
    )
    return AsyncClient(transport=transport, base_url=base_url)
