"""Forward collection requests with the user's token for server-side authorization."""

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from off_key_core.schemas.collection import CatalogChange

from ...facades.tactic import TacticError, tactic
from ..errors import raise_tactic_http_error

router = APIRouter()


async def collection_request(
    method: str,
    authorization: str | None,
    path: str = "",
    body: dict | None = None,
):
    if not authorization:
        raise HTTPException(401, "Sign in to view data sources")
    try:
        return await tactic._make_request(
            method,
            f"/api/v1/collection{path}",
            json_data=body,
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)


@router.get("")
async def get_catalog(authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization)


@router.post("/preview")
async def preview_catalog(
    change: CatalogChange, authorization: str | None = Header(default=None)
):
    return await collection_request(
        "POST", authorization, "/preview", change.model_dump(mode="json")
    )


@router.get("/status")
async def get_status(authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization, "/status")


@router.put("")
async def apply_catalog(
    change: CatalogChange, authorization: str | None = Header(default=None)
):
    return await collection_request(
        "PUT", authorization, body=change.model_dump(mode="json")
    )


@router.get("/revisions")
async def list_revisions(authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization, "/revisions")


@router.get("/ambibox-template")
async def get_ambibox_template(authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization, "/ambibox-template")


@router.get("/revisions/{revision}")
async def get_revision(revision: int, authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization, f"/revisions/{revision}")


@router.get("/state/{charger_id}")
async def get_state(charger_id: UUID, authorization: str | None = Header(default=None)):
    return await collection_request("GET", authorization, f"/state/{charger_id}")
