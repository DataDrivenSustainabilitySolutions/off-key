"""Translate downstream service failures at the HTTP API boundary."""

from typing import Never

from fastapi import HTTPException, status

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
