# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Clipper build the Station hands out (spec J.15).

One shared zip at `GET /clipper.zip`, unauthenticated like the console
shell beside it: the artifact carries no secrets and no origin — pairing
supplies both (J.2.6) — and distribution must be as self-service as
pairing is, or the administrator becomes the gatekeeper the pair route
exists to remove.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))


@pytest.fixture()
def station(tmp_path, monkeypatch):
    """No forest is needed: the artifact is host furniture, like the shell."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    (tmp_path / "forests").mkdir()
    app = build_app(root=tmp_path / "forests",
                    registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client


def test_the_zip_is_the_real_build_and_needs_no_key(station):
    r = station.get("/clipper.zip")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]

    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    # The load-bearing pieces of an MV3 extension, not an exhaustive list.
    for required in ("manifest.json", "background.js", "popup.html",
                     "vendor/turndown.js", "icons/icon128.png"):
        assert required in names, f"{required} missing from the zip"
    assert z.testzip() is None  # every member reads back clean


def test_the_etag_answers_304_on_a_repeat(station):
    first = station.get("/clipper.zip")
    etag = first.headers["etag"]
    again = station.get("/clipper.zip", headers={"If-None-Match": etag})
    assert again.status_code == 304
    # Same build, same bytes, same tag: the ETag means what it says.
    assert station.get("/clipper.zip").headers["etag"] == etag


def test_a_deployment_without_a_build_says_so(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    monkeypatch.setenv("MONKEYLLM_STATION_CLIPPER_DIR",
                       str(tmp_path / "nowhere"))
    (tmp_path / "forests").mkdir()
    app = build_app(root=tmp_path / "forests",
                    registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        r = client.get("/clipper.zip")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"
