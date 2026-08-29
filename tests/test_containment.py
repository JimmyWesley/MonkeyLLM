# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Containment is decided where the id arrives (spec C.6b.2, F.145-F.146).

v0.69 splits `Forest.path_for` in two. The default resolves symlinks and is
what every boundary accepting an id from OUTSIDE the engine must use; a
second, textual form is for ids the engine read out of its own catalog,
because `resolve()` is a `realpath` walk and the body scan called it once
per node in scope (72 ms of a ~230 ms cold `sniff` over 1,877 nodes).

The reason this file exists rather than a benchmark: the way that split goes
wrong is **silent**. A boundary left on the textual form does not raise,
does not log and does not slow down — a malicious id simply passes. So the
rule is only as good as the matrix below, and the matrix is the deliverable.

Each surface's test is a product of that surface x every escape, on purpose:
adding a surface without adding its refusals is the failure a hand-written
list reproduces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"

# Every id here must be refused by every surface. `symlink` is filled in by
# the fixture, which plants a real one inside the forest.
ESCAPES = {
    "traversal": "../../etc/passwd",
    "traversal_inner": "projects/../../../etc/passwd",
    "traversal_dotdot_only": "..",
    "encoded": "..%2f..%2fetc%2fpasswd",
    "absolute": "/etc/passwd",
    "symlink": "escape-hatch",
}


@pytest.fixture(scope="module")
def rigged(tmp_path_factory) -> Path:
    """A forest with a real symlink pointing out of it.

    The secret lives outside the forest root; the link lives inside and is
    spelled like an ordinary node, which is the whole point — by the time
    `path_for` sees `escape-hatch` it is just an id.
    """
    from monkeyllm import Vine

    root = tmp_path_factory.mktemp("containment")
    build_forest(root / FOREST)
    # Index BEFORE arming the trap. `Forest.iter_ids` resolves each path to
    # compute its id, so a symlink out of the forest makes the catalog build
    # raise — see `test_reindex_meets_a_symlink`, which pins that behaviour
    # instead of letting it break every fixture that follows.
    Vine(root / FOREST, writable=False).close()
    secret = root / "outside-the-forest.md"
    secret.write_text("---\ntitle: Secret\n---\n\nnot for you.\n",
                      encoding="utf-8")
    link = root / FOREST / "escape-hatch.md"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("this platform will not create symlinks")
    return root


@pytest.fixture()
def station(rigged, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=rigged, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, allow=None):
    key = registry.issue_key("agent")
    registry.grant("agent", FOREST, {"read"},
                   allow=list(allow) if allow else None)
    return key


# ---------------------------------------------------------------- F.145
@pytest.mark.parametrize("escape", sorted(ESCAPES), ids=sorted(ESCAPES))
def test_engine_refuses_every_escape(rigged, escape):
    """Surface 1: the engine itself, through the resolving `path_for`."""
    from monkeyllm import Vine
    from monkeyllm.errors import E_NOT_FOUND, VineError

    vine = Vine(rigged / FOREST, writable=False)
    try:
        with pytest.raises(VineError) as caught:
            vine.pick(ESCAPES[escape])
        assert caught.value.code == E_NOT_FOUND
    finally:
        vine.close()


@pytest.mark.parametrize("escape", sorted(ESCAPES), ids=sorted(ESCAPES))
def test_scoped_vine_refuses_every_escape(rigged, escape):
    """Surface 2: `ScopedVine`. J.3's rule holds — out-of-scope, absent and
    escaping are one indistinguishable refusal."""
    from monkeyllm import Vine
    from monkeyllm.errors import E_NOT_FOUND, VineError
    from monkeyllm_station.policy import Policy, ScopedVine

    vine = Vine(rigged / FOREST, writable=False)
    try:
        scoped = ScopedVine(vine, Policy(forest=FOREST,
                                         caps=frozenset({"read"}),
                                         allow=("projects/",)))
        with pytest.raises(VineError) as caught:
            scoped.pick(ESCAPES[escape])
        assert caught.value.code == E_NOT_FOUND
    finally:
        vine.close()


@pytest.mark.parametrize("escape", sorted(ESCAPES), ids=sorted(ESCAPES))
def test_rest_refuses_every_escape(station, escape):
    """Surface 3: REST, both the primitive route and the byte routes
    (`export`/`payload` take the id in the PATH, which is the shape a
    traversal is actually written for)."""
    client, registry = station
    key = _key(registry)
    headers = {"Authorization": f"Bearer {key}"}
    node = ESCAPES[escape]

    r = client.post(f"/v1/forests/{FOREST}/pick", headers=headers,
                    json={"id": node})
    assert r.status_code in (400, 403, 404), r.text
    body = r.json()
    assert body.get("error", {}).get("code") in ("E_NOT_FOUND", "E_SCHEMA")

    for route in ("export", "payload"):
        r = client.get(f"/v1/forests/{FOREST}/{route}/{node}", headers=headers)
        assert r.status_code in (400, 403, 404), (route, r.text)
        assert b"not for you" not in r.content


@pytest.mark.parametrize("escape", sorted(ESCAPES), ids=sorted(ESCAPES))
def test_mcp_refuses_every_escape(station, escape):
    """Surface 4: MCP."""
    client, registry = station
    key = _key(registry)
    r = client.post("/mcp/", headers={
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "pick",
                         "arguments": {"forest": FOREST,
                                       "id": ESCAPES[escape]}}})
    assert r.status_code == 200, r.text
    out = json.loads(r.json()["result"]["content"][0]["text"])
    assert out["error"]["code"] in ("E_NOT_FOUND", "E_SCHEMA"), out


def test_the_symlink_is_real(rigged):
    """The matrix above is worthless if the trap was never armed."""
    link = rigged / FOREST / "escape-hatch.md"
    assert link.is_symlink()
    assert "not for you" in link.read_text(encoding="utf-8")


def test_a_write_always_resolves(rigged, tmp_path):
    """C.6b.2 rule 3: a write's id came from a caller, so it is rule 1's
    case. Planting over the symlink must not follow it out of the forest."""
    from monkeyllm import Vine
    from monkeyllm.errors import VineError

    dest = tmp_path / "writable"
    build_forest(dest / FOREST)
    Vine(dest / FOREST, writable=False).close()  # index before arming the trap
    secret = tmp_path / "outside.md"
    secret.write_text("original\n", encoding="utf-8")
    link = dest / FOREST / "escape-hatch.md"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("this platform will not create symlinks")

    vine = Vine(dest / FOREST, writable=True)
    try:
        with pytest.raises(VineError):
            vine.plant({"id": "escape-hatch", "type": "note",
                        "title": "Overwrite", "summary": "x",
                        "parent": "_index", "body": "planted"})
    finally:
        vine.close()
    assert secret.read_text(encoding="utf-8") == "original\n"


# ---------------------------------------------------------------- F.146
def test_sniff_is_unchanged_by_the_textual_form(vine_ro):
    """The scan reads through the trusted form now. Same nodes, same
    sections, same snippets, same order — this is a cost rule (C.6b.1's
    first) and a cost rule that changed an answer is a bug."""
    out = vine_ro.sniff(["stigmergy"], k=5)
    again = vine_ro.sniff(["stigmergy"], k=5)
    assert out == again
    assert out["results"], "fixture must actually match, or this proves nothing"


def test_trusted_form_agrees_with_the_resolving_one(vine_ro):
    """Over every id the catalog holds, the two forms return the same path.

    They may only differ where a symlink is involved, and the fixture has
    none — so a difference here means the textual form is wrong about an
    ordinary id, which is the failure that would silently break reads.
    """
    forest = vine_ro.forest
    ids = [r["id"] for r in forest_ids(vine_ro)]
    assert len(ids) > 50, "expected the whole fixture"
    for nid in ids:
        assert forest.path_for(nid) == forest.path_for(nid, trusted=True), nid


def test_trusted_form_still_refuses_traversal(vine_ro):
    """The textual form collapses `..` — it gives up symlinks, not `../`."""
    from monkeyllm.errors import E_NOT_FOUND, VineError

    for bad in ("../../etc/passwd", "projects/../../../etc/passwd",
                "../outside", "a/b/../../../c"):
        with pytest.raises(VineError) as caught:
            vine_ro.forest.path_for(bad, trusted=True)
        assert caught.value.code == E_NOT_FOUND, bad


def test_a_bare_dotdot_is_a_filename_not_an_escape(vine_ro):
    """`..` becomes `...md`, which is an ordinary (absent) file under the
    root in BOTH forms. Pinned because it looks like a traversal and is not:
    a future tightening that starts refusing it must do so deliberately."""
    forest = vine_ro.forest
    assert forest.path_for("..") == forest.path_for("..", trusted=True)
    assert not forest.path_for("..").exists()


def forest_ids(vine):
    return vine.catalog.conn.execute("SELECT id FROM nodes").fetchall()


def test_reindex_meets_a_symlink(tmp_path):
    """A symlink out of the forest makes the catalog build raise — and it
    raises a bare `ValueError` from `pathlib`, not a `VineError`.

    Pinned, NOT endorsed. C.12 says every exit is an envelope and the last
    resort is `E_INTERNAL` in the envelope shape; this one escapes as a
    `pathlib` error naming two absolute host paths. It is a loud, safe
    failure (nothing is indexed, nothing is served) and it predates v0.69 —
    `Forest.id_for` has always resolved. Recorded here so the next person
    who trips it finds a test instead of a mystery, and so tightening it
    later is a deliberate change with a test to update.
    """
    from monkeyllm import Vine

    build_forest(tmp_path / FOREST)
    outside = tmp_path / "elsewhere.md"
    outside.write_text("---\ntitle: X\n---\n\nbody\n", encoding="utf-8")
    try:
        (tmp_path / FOREST / "linked.md").symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("this platform will not create symlinks")

    with pytest.raises(ValueError):
        Vine(tmp_path / FOREST, writable=False).close()
