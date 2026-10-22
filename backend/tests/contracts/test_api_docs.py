import re
from urllib.parse import unquote
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.api_docs import router


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
