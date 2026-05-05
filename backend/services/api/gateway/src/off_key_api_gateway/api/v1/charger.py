from fastapi import APIRouter, HTTPException, status

from ...facades.tactic import TacticError, tactic

router = APIRouter()


def _get_tactic_error_detail(error: TacticError) -> str:
    """Extract API detail from TACTIC error body when available."""
    if isinstance(error.body, dict):
        detail = error.body.get("detail")
        if detail:
            return str(detail)
    return str(error)


def _raise_tactic_http_error(error: TacticError) -> None:
    raise HTTPException(
        status_code=error.status or status.HTTP_502_BAD_GATEWAY,
        detail=_get_tactic_error_detail(error),
    )


@router.get("/available", tags=["chargers"])
async def get_all_chargers(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)
    except TacticError as e:
        _raise_tactic_http_error(e)


@router.get("/active", tags=["chargers"])
async def get_active_chargers(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)
    except TacticError as e:
        _raise_tactic_http_error(e)


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_active_charger_ids(skip=skip, limit=limit)
    except TacticError as e:
        _raise_tactic_http_error(e)
