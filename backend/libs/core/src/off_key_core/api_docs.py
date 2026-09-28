"""Shared browser documentation for the application's FastAPI services."""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)

FAVICON_URL = "data:image/svg+xml," + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#090909"/>'
    '<path d="M37 12h9L27 52h-9Z" fill="#f2f2f2"/>'
    "</svg>"
)

router = APIRouter(include_in_schema=False)


@router.get("/docs")
async def swagger_ui(request: Request):
    app = request.app
    root_path = request.scope.get("root_path", "").rstrip("/")
    return get_swagger_ui_html(
        openapi_url=root_path + app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_favicon_url=FAVICON_URL,
        oauth2_redirect_url=root_path + "/docs/oauth2-redirect",
        init_oauth=app.swagger_ui_init_oauth,
        swagger_ui_parameters=app.swagger_ui_parameters,
    )


@router.get("/docs/oauth2-redirect")
async def swagger_oauth_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@router.get("/redoc")
async def redoc(request: Request):
    app = request.app
    root_path = request.scope.get("root_path", "").rstrip("/")
    return get_redoc_html(
        openapi_url=root_path + app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_favicon_url=FAVICON_URL,
    )
