"""Translate domain errors raised by route handlers into HTTP responses."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from ..domain import (
    AuthenticationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)

# Infrastructure failures keep their cause out of the response.
_STATUS: tuple[tuple[type[DomainError], int, str | None], ...] = (
    (NotFoundError, 404, None),
    (ConflictError, 409, None),
    (AuthenticationError, 401, None),
    (ForbiddenError, 403, None),
    (ValidationError, 422, None),
    (InfrastructureError, 500, "Internal infrastructure error"),
)


def http_error(error: DomainError) -> HTTPException:
    for error_type, status_code, detail in _STATUS:
        if isinstance(error, error_type):
            return HTTPException(status_code, detail or str(error))
    return HTTPException(500, "Unexpected domain error")


class DomainErrorRoute(APIRoute):
    """Route whose handler may raise DomainError instead of HTTPException."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except DomainError as exc:
                raise http_error(exc) from exc
            except PoolTimeoutError as exc:
                raise HTTPException(
                    503, "The database is busy. Try again shortly."
                ) from exc
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) != "53300":
                    raise
                raise HTTPException(
                    503, "The database is busy. Try again shortly."
                ) from exc

        return route_handler
