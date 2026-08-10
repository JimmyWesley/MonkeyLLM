# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The host answers the console's own addresses (spec J.5.8, F.34).

Studio's URLs are real paths — `/f/{forest}/explore` — so a reload, a
bookmark or a link somebody was sent arrives at the Station as a GET of a
path with no file behind it. Answering 404 there is what made F5 lose the
place: the application that could have read the address never loaded.

The fallback is deliberately narrow. Only a request that accepts HTML gets
the shell; a script, a stylesheet or a `fetch` that misses must keep its
404, because an HTML body served under a JavaScript MIME type fails later,
elsewhere, and unrecognisably. And `/v1` is not Studio's: an unrouted API
path stays the JSON envelope of J.1.

The build is a fixture rather than `apps/studio/dist`, so these hold whether
or not somebody has run `npm run build` in this checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

DOCUMENT = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
ASSET = {"accept": "*/*"}


def _client(root: Path, registry: Path, dist: Path | None):
    from starlette.testclient import TestClient

    from monkeyllm_station import app as app_module

    original = app_module.STUDIO_DIST
    app_module.STUDIO_DIST = dist if dist is not None else root / "no-build-here"
    try:
        app = app_module.build_app(root=root, registry_path=registry, mcp=False)
    finally:
        app_module.STUDIO_DIST = original
    return TestClient(app)


@pytest.fixture()
def built(tmp_path):
    """A Station serving a Studio build, over an empty registry.

    No forest: these are the host's routes, and which forests exist decides
    nothing about them — a deep link into a forest that does not exist still
    has to reach the console, which is what says so (J.5.8).
    """
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>Studio</title><script src=/assets/app.js></script>",
        encoding="utf-8")
    (dist / "assets" / "app.js").write_text("export default 1\n", encoding="utf-8")
    root = tmp_path / "registry"
    root.mkdir()
    with _client(root, tmp_path / "station.db", dist) as client:
        yield client


@pytest.mark.parametrize("path", [
    "/",
    "/f/forest-fixture/explore",
    "/f/forest-fixture/data",
    "/f/forest-fixture/explore?node=projects/_index&mode=files",
    "/f/a-forest-that-does-not-exist/ask",
])
def test_a_console_address_is_answered_with_the_console(built, path):
    res = built.get(path, headers=DOCUMENT)
    assert res.status_code == 200, path
    assert res.headers["content-type"].startswith("text/html")
    assert "<title>Studio</title>" in res.text


def test_the_shell_is_not_cached(built):
    """It names one build's hashed assets, so a copy kept across a deploy
    asks for files the Station no longer has."""
    assert built.get("/f/x/ask", headers=DOCUMENT).headers["cache-control"] == "no-cache"


def test_the_build_is_still_served_as_files(built):
    res = built.get("/assets/app.js", headers=ASSET)
    assert res.status_code == 200
    assert res.text.strip() == "export default 1"


def test_a_missing_asset_stays_missing(built):
    """The failure mode the `accept` rule exists for: answering this with the
    shell would hand the browser HTML under a JavaScript MIME type."""
    assert built.get("/assets/gone-in-the-last-build.js", headers=ASSET).status_code == 404
    assert built.get("/favicon-32x32.png", headers=ASSET).status_code == 404


def test_an_unrouted_api_path_is_still_the_api(built):
    """`/v1` is not Studio's, and a client expecting JSON must not be handed
    the console (J.1)."""
    for headers in (ASSET, DOCUMENT):
        res = built.get("/v1/nope", headers=headers)
        assert res.status_code == 404
        assert res.json()["error"]["code"]


def test_the_api_answers_before_the_console(built):
    """The catch-all is last on purpose: a routed endpoint keeps answering
    for a request that would have accepted HTML."""
    res = built.get("/v1/health", headers=DOCUMENT)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_without_a_build_a_deep_link_says_so(tmp_path):
    """A Station with no console answers a console address with the reason it
    has nothing to serve, not with a bare 404 that reads like a broken route.
    """
    root = tmp_path / "registry"
    root.mkdir()
    with _client(root, tmp_path / "station.db", None) as client:
        for path in ("/", "/f/forest-fixture/explore"):
            res = client.get(path, headers=DOCUMENT)
            assert res.status_code == 404
            assert "Studio build" in res.json()["error"]["message"]
        assert client.get("/v1/nope", headers=DOCUMENT).json()["error"]["code"]
