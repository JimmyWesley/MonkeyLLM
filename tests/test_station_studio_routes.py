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


# -- what the page is allowed to load (J.5) --------------------------------


def _csp(response) -> dict[str, str]:
    """The policy as directive -> sources, so a test names what it means."""
    return {part.split(" ")[0]: part
            for part in response.headers["content-security-policy"].split("; ")}


def test_the_console_says_what_it_may_load(built):
    """Studio renders model output and ingested document bodies as markdown,
    and both are untrusted by the product's own premise. Whatever such text
    talks the page into fetching is fetched by the operator's authenticated
    browser, and the Station is not on that path — so no server-side check
    can be the control here. This header is."""
    directives = _csp(built.get("/", headers=DOCUMENT))

    # The link that breaks the chain: a legitimate image is fetched through
    # J.14 with the viewer's credential and rendered from a blob, so remote
    # addresses are never needed and never allowed.
    assert directives["img-src"] == "img-src 'self' data: blob:"
    assert directives["connect-src"] == "connect-src 'self'"
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"
    assert directives["object-src"] == "object-src 'none'"
    assert directives["base-uri"] == "base-uri 'none'"
    assert "'unsafe-eval'" not in directives["script-src"]
    assert "'unsafe-inline'" not in directives["script-src"]


def test_every_response_carries_the_baseline_headers(built):
    """Not only the shell: a JSON envelope sniffed as HTML is a stored-XSS
    primitive, and forest content is what fills those envelopes."""
    for path, headers in (("/", DOCUMENT), ("/v1/health", ASSET),
                          ("/assets/app.js", ASSET)):
        res = built.get(path, headers=headers)
        assert res.headers["x-content-type-options"] == "nosniff", path
        assert res.headers["referrer-policy"] == "no-referrer", path
        assert res.headers["x-frame-options"] == "DENY", path


def test_the_inline_script_allowance_is_read_from_the_build(tmp_path):
    """The shell boots the saved theme inline, before first paint. Its hash is
    computed from the built file rather than written down, so editing that
    script can never leave a stale digest behind — which fails silently, with
    the page still loading and the script simply not running."""
    from monkeyllm_station.app import _inline_script_hashes

    shell = tmp_path / "index.html"
    shell.write_text("<script>var a = 1</script><script src=/x.js></script>",
                     encoding="utf-8")
    hashes = _inline_script_hashes(shell)
    # One allowance for the inline script, none for the one with a src.
    assert len(hashes) == 1 and hashes[0].startswith("'sha256-")

    shell.write_text("<script>var a = 2</script>", encoding="utf-8")
    assert _inline_script_hashes(shell) != hashes

    assert _inline_script_hashes(tmp_path / "absent.html") == []


def test_the_real_build_may_run_its_own_inline_scripts(tmp_path):
    """End to end against `apps/studio/dist`, when this checkout has one.

    The pair that has to agree is the shell the Station serves and the policy
    it serves alongside it. Nothing else in the suite compares them, and the
    failure is quiet: the console still loads, the theme just stops applying
    before first paint, which nobody notices until a dark-mode user does.
    """
    import base64
    import hashlib
    import re

    from monkeyllm_station import app as app_module

    if not (app_module.STUDIO_DIST / "index.html").is_file():
        pytest.skip("no Studio build in this checkout")

    root = tmp_path / "registry"
    root.mkdir()
    with _client(root, tmp_path / "station.db", app_module.STUDIO_DIST) as client:
        res = client.get("/", headers=DOCUMENT)
        assert res.status_code == 200
        policy = res.headers["content-security-policy"]

    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                        res.text, re.IGNORECASE | re.DOTALL)
    assert inline, "the shell boots the theme inline; if that ever stops, drop this"
    for body in inline:
        digest = base64.b64encode(
            hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in policy, (
            "an inline script in the served shell is not allowed by the policy "
            "served with it — the console would silently stop running it")


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
