"""Translate downstream service failures at the HTTP API boundary."""

from collections.abc import Callable, Coroutine
from typing import Any, Never

from fastapi import HTTPException, Request, Response, status
from fastapi.routing import APIRoute

from ..facades.tactic import TacticError


def tactic_error_detail(error: TacticError) -> str:
    """Extract a stable API detail from a downstream TACTIC failure."""
    if isinstance(error.body, dict):
        detail = error.body.get("detail")
        if detail:
            return str(detail)
    return str(error)


def raise_tactic_http_error(error: TacticError) -> Never:
    """Raise the canonical gateway response for a downstream TACTIC failure."""
    raise HTTPException(
        status_code=error.status or status.HTTP_502_BAD_GATEWAY,
        detail=tactic_error_detail(error),
    ) from error


class TacticErrorRoute(APIRoute):
    """Route whose handler may let a TacticError propagate."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except TacticError as exc:
                raise_tactic_http_error(exc)

        return route_handler
