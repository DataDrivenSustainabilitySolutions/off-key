import re
from urllib.parse import unquote
from xml.etree import ElementTree

import pytest
from aberration_core.api_docs import (
    DOCS_CONTENT_SECURITY_POLICY,
    REDOC_JS,
    SWAGGER_CSS,
    SWAGGER_JS,
    router,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("root_path", ["", "/api"])
def test_documentation_keeps_schema_and_oauth_links_with_embedded_favicon(root_path):
    app = FastAPI(
        title="aberration", docs_url=None, redoc_url=None, root_path=root_path
    )
    app.include_router(router)
    client = TestClient(app)

    icons = []
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert f"{root_path}/openapi.json" in response.text
        icon = re.search(r'<link rel="shortcut icon" href="([^"]+)"', response.text)
        assert icon is not None
        url = icon.group(1)
        assert url.startswith("data:image/svg+xml,")
        svg = ElementTree.fromstring(unquote(url.split(",", 1)[1]))
        assert svg.tag == "{http://www.w3.org/2000/svg}svg"
        assert svg.find("{http://www.w3.org/2000/svg}path") is not None
        icons.append(url)

    assert icons[0] == icons[1]
    assert f"{root_path}/docs/oauth2-redirect" in client.get("/docs").text
    assert client.get("/docs/oauth2-redirect").status_code == 200
    assert client.get("/openapi.json").json()["paths"] == {}


def _asset_tags(html):
    return re.findall(r"<(?:script|link)\b[^>]*\b(?:src|href)=\"https?://[^>]*>", html)


@pytest.mark.parametrize(
    ("path", "assets"),
    [("/docs", (SWAGGER_JS, SWAGGER_CSS)), ("/redoc", (REDOC_JS,))],
)
def test_documentation_loads_only_pinned_assets_with_integrity(path, assets):
    app = FastAPI(title="aberration", docs_url=None, redoc_url=None)
    app.include_router(router)
    response = TestClient(app).get(path)

    assert response.headers["content-security-policy"] == (DOCS_CONTENT_SECURITY_POLICY)
    assert "frame-ancestors 'none'" in DOCS_CONTENT_SECURITY_POLICY
    tags = _asset_tags(response.text)
    assert len(tags) == len(assets)
    for asset in assets:
        assert re.search(r"@\d+\.\d+\.\d+/", asset.url), asset.url
        assert asset.integrity.startswith("sha384-")
        (tag,) = [tag for tag in tags if f'"{asset.url}"' in tag]
        assert f'integrity="{asset.integrity}"' in tag
        assert 'crossorigin="anonymous"' in tag
    assert "fonts.googleapis.com" not in response.text
