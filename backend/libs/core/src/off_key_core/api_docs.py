"""Shared browser documentation for the application's FastAPI services.

The pages run on the application's own origin, next to the remembered-session
cookie, so every script and stylesheet they load is pinned to one exact release
and checked by the browser against its Subresource Integrity hash. A changed
file on the CDN is then refused instead of run. The response also carries a
Content-Security-Policy that admits nothing beyond those files, the page's own
inline bootstrap and same-origin requests.

To move to a newer release, change the version and recompute the hash from the
file in the package's npm tarball, for example
``openssl dgst -sha384 -binary swagger-ui-bundle.js | openssl base64 -A``.
"""

from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse

FAVICON_URL = "data:image/svg+xml," + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#090909"/>'
    '<path d="M37 12h9L27 52h-9Z" fill="#f2f2f2"/>'
    "</svg>"
)

CDN = "https://cdn.jsdelivr.net"


@dataclass(frozen=True)
class PinnedAsset:
    """One exact CDN file and the hash the browser must find in it."""

    url: str
    integrity: str


SWAGGER_JS = PinnedAsset(
    f"{CDN}/npm/swagger-ui-dist@5.34.0/swagger-ui-bundle.js",
    "sha384-9Td7MKiIr2S83E1kZyyVi8KdJw/S8CpAvu0llLyMeg0xq/hDGiZJfVn0fV4llCmK",
)
SWAGGER_CSS = PinnedAsset(
    f"{CDN}/npm/swagger-ui-dist@5.34.0/swagger-ui.css",
    "sha384-4c3vsE5f+trhFyHrFrLM1fFGUn531NIaC7dcqEWIJdoRQJ5CkJbSuSCwXLpaS1KF",
)
REDOC_JS = PinnedAsset(
    f"{CDN}/npm/redoc@2.5.4/bundles/redoc.standalone.js",
    "sha384-w447zOpYfw/1Tv/5AK9NfHTlQIqE3RVR6KY62jCyy9zNDgO64cMwGGP1Fj0zJVf5",
)

# Both UIs bootstrap from an inline script and set inline styles, and ReDoc
# renders in a blob worker; everything else is limited to the pinned files and
# this origin. Swagger's "Try it out" calls the API on the same origin.
DOCS_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'unsafe-inline' {CDN}",
        f"style-src 'unsafe-inline' {CDN}",
        "img-src 'self' data:",
        "font-src data:",
        "connect-src 'self'",
        "worker-src blob:",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)

router = APIRouter(include_in_schema=False)


def _pinned(response: HTMLResponse, *assets: PinnedAsset) -> HTMLResponse:
    """Add the integrity check to each asset tag and send the page's CSP."""
    html = bytes(response.body).decode()
    for asset in assets:
        for attribute in ("src", "href"):
            tag = f'{attribute}="{asset.url}"'
            if tag in html:
                break
        else:
            raise RuntimeError(f"documentation page does not load {asset.url}")
        html = html.replace(
            tag,
            f'{tag} integrity="{asset.integrity}" crossorigin="anonymous"',
            1,
        )
    return HTMLResponse(
        html, headers={"Content-Security-Policy": DOCS_CONTENT_SECURITY_POLICY}
    )


@router.get("/docs")
async def swagger_ui(request: Request):
    app = request.app
    root_path = request.scope.get("root_path", "").rstrip("/")
    page = get_swagger_ui_html(
        openapi_url=root_path + app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url=SWAGGER_JS.url,
        swagger_css_url=SWAGGER_CSS.url,
        swagger_favicon_url=FAVICON_URL,
        oauth2_redirect_url=root_path + "/docs/oauth2-redirect",
        init_oauth=app.swagger_ui_init_oauth,
        swagger_ui_parameters=app.swagger_ui_parameters,
    )
    return _pinned(page, SWAGGER_JS, SWAGGER_CSS)


@router.get("/docs/oauth2-redirect")
async def swagger_oauth_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@router.get("/redoc")
async def redoc(request: Request):
    app = request.app
    root_path = request.scope.get("root_path", "").rstrip("/")
    page = get_redoc_html(
        openapi_url=root_path + app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url=REDOC_JS.url,
        redoc_favicon_url=FAVICON_URL,
        with_google_fonts=False,
    )
    return _pinned(page, REDOC_JS)
