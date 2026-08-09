# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Map projections (spec J.11, criterion F.25).

`GET /graph` and `GET /trails` hand a caller a whole region at once. That
is a shape, not a new authority — so the tests that matter are the ones
that prove it discloses nothing a node-by-node walk would not.

Two of them are load-bearing:

* `test_graph_leaks_no_out_of_scope_id` sweeps the WHOLE payload for ids the
  principal may not see, in the same spirit as the leak suite: field-by-field
  assertions only catch the leaks you thought of.
* `test_degree_is_recomputed_from_returned_edges` recomputes every degree
  from the response's own edges. The Catalog knows the real degree, and
  publishing it would leak the size of what was withheld.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
GRANT = "projects/"


@pytest.fixture(scope="session")
def map_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("map-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(map_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=map_root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, caps=("read",), principal="alice", **grant):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), **grant)
    return {"Authorization": f"Bearer {key}"}


def _strings(blob):
    if isinstance(blob, str):
        yield blob
    elif isinstance(blob, dict):
        for k, v in blob.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(blob, (list, tuple)):
        for item in blob:
            yield from _strings(item)


# -- shape ------------------------------------------------------------------


def test_graph_returns_nodes_edges_and_the_forest_dialect(station):
    client, registry = station
    r = client.get(f"/v1/forests/{FOREST}/graph", headers=_key(registry))
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) > 50 and len(body["edges"]) > 20
    assert body["truncated"] is False
    # C.6.1: the projection says it is derived, so a consumer reindexes
    # rather than reconciling.
    assert body["derived"] is True
    # A legend names what THIS forest holds (J.5.4): the dialect travels
    # with the payload instead of being compiled into a console.
    assert "branch" in body["types"] and "dataset" in body["types"]
    assert "part-of" in body["rels"] and "discovered-shortcut" in body["rels"]
    node = next(n for n in body["nodes"] if n["id"] == "_index")
    assert node["type"] == "branch" and node["title"]


def test_graph_carries_link_confidence(station):
    """A proposal is not an assertion (J.5.4). The channel that separates
    them has to exist in the payload, or a console cannot draw it."""
    client, registry = station
    body = client.get(f"/v1/forests/{FOREST}/graph",
                      headers=_key(registry)).json()
    assert all("confidence" in e for e in body["edges"])
    assert all(0.0 <= e["confidence"] <= 1.0 for e in body["edges"])


def test_trails_reports_persistent_heat_only(station, map_root):
    """Session heat belongs to a hunt in flight and never to a map."""
    from monkeyllm import Vine

    with Vine(map_root / FOREST, writable=False) as v:
        v.trails.add_heat(["concepts/rag"], amount=0.4)
        v.trails.add_heat(["concepts/bm25"], amount=0.9, scope="session-xyz")

    client, registry = station
    body = client.get(f"/v1/forests/{FOREST}/trails",
                      headers=_key(registry)).json()
    warm = {row["id"]: row["heat"] for row in body["heat"]}
    assert warm.get("concepts/rag") == pytest.approx(0.4)
    assert "concepts/bm25" not in warm
    assert body["stats"]["rows"] == len(body["heat"])


def test_graph_carries_heat_for_its_nodes(station, map_root):
    from monkeyllm import Vine

    with Vine(map_root / FOREST, writable=False) as v:
        v.trails.add_heat(["people/jimmy-wesley"], amount=0.6)

    client, registry = station
    body = client.get(f"/v1/forests/{FOREST}/graph",
                      headers=_key(registry)).json()
    hot = next(n for n in body["nodes"] if n["id"] == "people/jimmy-wesley")
    assert hot["heat"] >= 0.6
    assert all(n["heat"] >= 0.0 for n in body["nodes"])


# -- scoping (F.25) ---------------------------------------------------------


def test_graph_leaks_no_out_of_scope_id(station, map_root):
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/graph", headers=headers).json()

    from monkeyllm import Vine

    with Vine(map_root / FOREST, writable=False) as v:
        all_ids = {r["id"] for r in v.catalog.conn.execute("SELECT id FROM nodes")}

    leaked = {s for s in _strings(body)
              if s in all_ids and not s.startswith(GRANT)}
    assert not leaked, f"map disclosed out-of-scope ids: {sorted(leaked)[:8]}"
    assert body["nodes"], "the grant must still return its own subtree"


def test_every_returned_id_is_reachable_by_look(station):
    """F.25: an id on the map is an id the same principal can open."""
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/graph", headers=headers).json()
    for node in body["nodes"][:12]:
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": node["id"]}, headers=headers)
        assert r.status_code == 200, f"{node['id']} is on the map but not readable"


def test_edges_need_both_endpoints_visible(station):
    """One visible end would disclose the other."""
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/graph", headers=headers).json()
    ids = {n["id"] for n in body["nodes"]}
    dangling = [e for e in body["edges"] if e["src"] not in ids or e["dst"] not in ids]
    assert not dangling, f"edges with a hidden endpoint: {dangling[:4]}"


def test_degree_is_recomputed_from_returned_edges(station):
    """The Catalog's degree counted the hidden edges too."""
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/graph", headers=headers).json()
    expected: dict[str, int] = {}
    for e in body["edges"]:
        expected[e["src"]] = expected.get(e["src"], 0) + 1
        expected[e["dst"]] = expected.get(e["dst"], 0) + 1
    wrong = [(n["id"], n["degree"], expected.get(n["id"], 0))
             for n in body["nodes"] if n["degree"] != expected.get(n["id"], 0)]
    assert not wrong, f"degree not derived from the projection: {wrong[:4]}"


def test_parent_pointer_never_names_a_hidden_branch(station):
    """`parent` is an id like any other: outside the scope it is absent."""
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/graph", headers=headers).json()
    ids = {n["id"] for n in body["nodes"]}
    assert all(n["parent"] is None or n["parent"] in ids for n in body["nodes"])


def test_trails_hides_out_of_scope_heat(station, map_root):
    from monkeyllm import Vine

    with Vine(map_root / FOREST, writable=False) as v:
        v.trails.add_heat(["sales/targets-2026"], amount=0.7)
        v.trails.add_heat(["projects/audio-pipeline"], amount=0.5)

    client, registry = station
    headers = _key(registry, allow=[GRANT])
    body = client.get(f"/v1/forests/{FOREST}/trails", headers=headers).json()
    warm = {row["id"] for row in body["heat"]}
    assert "projects/audio-pipeline" in warm
    assert "sales/targets-2026" not in warm
    # Stats over the whole forest would be the same disclosure in aggregate.
    assert body["stats"]["rows"] == len(body["heat"])


# -- region, bounds and refusals --------------------------------------------


def test_scope_narrows_to_one_branch(station):
    client, registry = station
    headers = _key(registry)
    body = client.get(f"/v1/forests/{FOREST}/graph?scope=projects",
                      headers=headers).json()
    ids = {n["id"] for n in body["nodes"]}
    assert ids and all(i == "projects/_index" or i.startswith("projects/")
                       for i in ids)
    # The branch id names the same region as the bare branch.
    same = client.get(f"/v1/forests/{FOREST}/graph?scope=projects/_index",
                      headers=headers).json()
    assert {n["id"] for n in same["nodes"]} == ids


def test_out_of_scope_region_is_absent_not_forbidden(station):
    """J.3: an authorization error here would be an existence oracle."""
    client, registry = station
    headers = _key(registry, allow=[GRANT])
    r = client.get(f"/v1/forests/{FOREST}/graph?scope=sales", headers=headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"


def test_limit_truncates_and_says_so(station):
    client, registry = station
    body = client.get(f"/v1/forests/{FOREST}/graph?limit=10",
                      headers=_key(registry)).json()
    assert len(body["nodes"]) == 10 and body["truncated"] is True
    # Still coherent after the cut: no edge may name a dropped node.
    ids = {n["id"] for n in body["nodes"]}
    assert all(e["src"] in ids and e["dst"] in ids for e in body["edges"])


def test_map_requires_read(station):
    client, registry = station
    headers = _key(registry, caps=("ingest",))
    r = client.get(f"/v1/forests/{FOREST}/graph", headers=headers)
    assert r.status_code == 403


def test_map_requires_a_key(station):
    client, _ = station
    assert client.get(f"/v1/forests/{FOREST}/graph").status_code == 401


def test_unknown_forest_is_not_an_oracle(station):
    client, registry = station
    r = client.get("/v1/forests/nope/graph", headers=_key(registry))
    assert r.status_code == 404 and "unknown forest" in r.json()["error"]["message"]


def test_unknown_projection_is_404_not_a_primitive(station):
    client, registry = station
    r = client.get(f"/v1/forests/{FOREST}/look", headers=_key(registry))
    assert r.status_code == 404
    assert "graph" in r.json()["error"]["hint"]


def test_primitives_still_post_to_the_same_path(station):
    """The GET route sits above the primitive catch-all; it must not shadow
    it."""
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                    headers=_key(registry))
    assert r.status_code == 200 and r.json()["id"] == "_index"
