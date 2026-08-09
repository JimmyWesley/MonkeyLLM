"""Two-phase compose: review before planting (spec J.8.1, criterion F.27).

The property worth testing is negative and easy to lose: the staging call
writes *nothing*. Not a node, not a commit, not a catalog row, not a branch,
not a body cache, not a line of the Gardener's config. Every assertion about
"nothing happened" here is one a future refactor can quietly break, because
a stray write still returns 200 and still looks right in the report.

The other half is that a reviewed draft is a **client payload**. It went to a
browser and came back, so the accepting call has to re-apply G.4.2.1 as if
the reviewer had authored every link themselves — which, in the console, is
exactly what they may have done.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
TEXT = ("Retro moved to Thursdays at 16:00 in the Amsterdam office, and the "
        "laptop request form now lives on the intranet under Equipment.")


@pytest.fixture()
def station(tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "registry"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    writable=True, mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _key(registry, caps, principal="alice", allow=None):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=allow)
    return {"Authorization": f"Bearer {key}"}


def _head(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root / FOREST,
                          capture_output=True, text=True).stdout.strip()


def _ingest(client, head, **body):
    return client.post(f"/v1/forests/{FOREST}/ingest", json=body, headers=head)


def _stage(client, head, **extra):
    r = _ingest(client, head, mode="compose", title="Office update",
                text=TEXT, stage=True, **extra)
    assert r.status_code == 200, r.text
    return r.json()


# -- the staging call writes nothing ---------------------------------------


def test_staging_returns_a_draft_and_writes_nothing(station):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    before = _head(root)
    count_before = client.post(f"/v1/forests/{FOREST}/scan", json={},
                               headers=head).json()

    body = _stage(client, head)

    assert body["preview"] is True
    assert body["planted"] == []
    assert body["commit"] is None, "a preview must not claim a commit"
    assert len(body["drafts"]) == 1
    draft = body["drafts"][0]
    assert draft["title"] == "Office update"
    assert draft["summary"], "a draft with no scent is not reviewable"
    assert "body" not in draft, "a passport is scent, not flesh"

    # Nothing moved.
    assert _head(root) == before
    assert client.post(f"/v1/forests/{FOREST}/look", json={"id": draft["id"]},
                       headers=head).status_code == 404
    assert client.post(f"/v1/forests/{FOREST}/scan", json={},
                       headers=head).json() == count_before


def test_staging_leaves_no_body_cache_and_no_gardener_config(station):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    forest = root / FOREST
    config = forest / "_meta" / "gardener.yaml"
    before = config.read_text(encoding="utf-8") if config.is_file() else None

    _stage(client, head)

    cache = forest / "_derived" / "bodies"
    assert not list(cache.rglob("*office-update*"))
    after = config.read_text(encoding="utf-8") if config.is_file() else None
    assert after == before, "a preview recorded a source root"


def test_staging_does_not_create_the_destination_branch(station):
    """`_ensure_branch` plants. A preview into a new branch must report the
    branch it *would* create, not create it."""
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    before = _head(root)

    body = _stage(client, head, dest="newsroom")
    assert body["branches"] == ["newsroom/_index"]
    assert body["drafts"][0]["parent"] == "newsroom/_index"

    assert _head(root) == before
    assert client.post(f"/v1/forests/{FOREST}/look", json={"id": "newsroom/_index"},
                       headers=head).status_code == 404


# -- accepting plants what was approved -------------------------------------


def test_the_accepted_draft_is_the_one_that_was_staged(station):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    draft = _stage(client, head)["drafts"][0]

    draft["summary"] = "Operations note: retro is Thursdays 16:00, Amsterdam."
    draft["tags"] = ["operations", "retro"]
    r = _ingest(client, head, mode="compose", title="Office update", text=TEXT,
                draft=draft)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["planted"] == [draft["id"]], "the previewed id must be the planted id"
    assert body["commit"] and body["commit"] != body["commit_before"]

    node = client.post(f"/v1/forests/{FOREST}/look", json={"id": draft["id"]},
                       headers=head).json()
    assert node["summary"] == draft["summary"], "the approved scent was not planted"
    assert set(node["tags"]) >= {"operations", "retro"}


def test_an_emptied_summary_falls_back_instead_of_planting_a_scentless_node(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    draft = _stage(client, head)["drafts"][0]
    derived = draft["summary"]

    draft["summary"] = "   "
    body = _ingest(client, head, mode="compose", title="Office update",
                   text=TEXT, draft=draft).json()
    node = client.post(f"/v1/forests/{FOREST}/look", json={"id": body["planted"][0]},
                       headers=head).json()
    assert node["summary"] == derived


def test_an_over_long_summary_is_trimmed_not_refused(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    draft = _stage(client, head)["drafts"][0]

    draft["summary"] = ("The retro has moved to Thursday afternoons. " * 20).strip()
    body = _ingest(client, head, mode="compose", title="Office update",
                   text=TEXT, draft=draft).json()
    assert body["errors"] == []
    node = client.post(f"/v1/forests/{FOREST}/look", json={"id": body["planted"][0]},
                       headers=head).json()
    assert len(node["summary"]) < len(draft["summary"])


# -- the reviewed draft is not trusted (G.4.2.1 re-applied) -----------------


def _links_of(root: Path, node_id: str) -> list[dict]:
    """Straight from the planted file. `look` reports `edges_out` without the
    link-level confidence, and confidence is half of what is under test."""
    from monkeyllm.parser import parse_node

    path = root / FOREST / f"{node_id}.md"
    node = parse_node(node_id, path.read_text(encoding="utf-8"), path)
    return list(node.frontmatter.get("links") or [])


def _accept_with_links(client, head, root, links):
    draft = _stage(client, head)["drafts"][0]
    draft["links"] = links
    body = _ingest(client, head, mode="compose", title="Office update",
                   text=TEXT, draft=draft).json()
    assert body["planted"], body
    return body["planted"][0], _links_of(root, body["planted"][0])


def test_a_reviewer_may_keep_a_link_and_it_stays_at_confidence_0_3(station):
    """Kept, not promoted: a glance is not evidence of use, and 0.3 is
    exactly the population the Ranger manages (H.2)."""
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])

    _, links = _accept_with_links(client, head, root, [
        {"rel": "related-to", "target": "concepts/rag", "confidence": 1.0},
    ])
    kept = [l for l in links if l["target"] == "concepts/rag"]
    assert kept, "an in-scope, existing, non-branch target must survive"
    assert kept[0]["confidence"] == 0.3, "confidence is not the reviewer's to raise"


@pytest.mark.parametrize("bad", [
    "does/not/exist",                 # invented target
    "_index",                         # a branch
    "projects/_index",                # a branch, deeper
])
def test_links_that_break_the_closed_candidate_rules_are_dropped(station, bad):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    _, links = _accept_with_links(client, head, root,
                                  [{"rel": "related-to", "target": bad}])
    assert all(l["target"] != bad for l in links)


def test_a_rel_other_than_related_to_is_dropped(station):
    """Structure is `graft`'s business; a reviewer approves proposals."""
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    _, links = _accept_with_links(client, head, root, [
        {"rel": "discovered-shortcut", "target": "concepts/rag"},
    ])
    assert all(l["target"] != "concepts/rag" for l in links)


def test_the_proposal_cap_survives_the_round_trip(station):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    ids = ["concepts/rag", "concepts/bm25", "concepts/rrf", "concepts/mcp",
           "concepts/slm", "concepts/stigmergy"]

    _, links = _accept_with_links(
        client, head, root, [{"rel": "related-to", "target": i} for i in ids])
    proposals = [l for l in links if l.get("confidence") == 0.3]
    assert len(proposals) == 3, "the G.4.2.1 cap must survive the round trip"


def test_a_self_or_parent_link_is_dropped(station):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    draft = _stage(client, head)["drafts"][0]
    draft["links"] = [{"rel": "related-to", "target": draft["id"]},
                      {"rel": "related-to", "target": draft["parent"]}]
    body = _ingest(client, head, mode="compose", title="Office update",
                   text=TEXT, draft=draft).json()
    links = _links_of(root, body["planted"][0])
    assert all(l["target"] != draft["id"] for l in links)
    assert all(not (l["rel"] == "related-to" and l["target"] == draft["parent"])
               for l in links), "the parent is structure, not a proposal"


def test_an_out_of_scope_target_is_dropped(station):
    """The reviewer holds `projects/`; naming a node outside it must not be
    a way to write an id they cannot read into a node they can."""
    client, registry, root = station
    head = _key(registry, ["read", "ingest"], allow=["projects/"])
    draft = _stage(client, head, dest="projects")["drafts"][0]
    draft["links"] = [{"rel": "related-to", "target": "people/_index"},
                      {"rel": "related-to", "target": "people/ana-castro"}]
    body = _ingest(client, head, mode="compose", title="Office update",
                   text=TEXT, dest="projects", draft=draft).json()
    assert body["planted"], body

    links = _links_of(root, body["planted"][0])
    assert all(not l["target"].startswith("people/") for l in links)


# -- the shape of the two calls ---------------------------------------------


def test_stage_and_draft_together_are_refused(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = _ingest(client, head, mode="compose", title="x", text=TEXT,
                stage=True, draft={"summary": "s"})
    assert r.status_code == 400
    assert "not both" in r.json()["error"]["message"]


@pytest.mark.parametrize("mode", ["adopt", "sync", "upload"])
def test_review_is_compose_only(station, mode):
    """Refused rather than silently ignored: a console that asked for a
    preview and got an ingest would have planted a batch nobody read."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest", "admin"])
    r = _ingest(client, head, mode=mode, stage=True, path="/tmp",
                files=[{"name": "a.md", "text": "# A\n\nbody\n"}])
    assert r.status_code == 400
    assert "compose" in r.json()["error"]["hint"]


def test_a_draft_that_is_not_an_object_is_refused(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = _ingest(client, head, mode="compose", title="x", text=TEXT, draft="yes")
    assert r.status_code == 400


def test_staging_still_needs_the_ingest_capability(station):
    """A preview reads the forest through the Curator and reports ids; it is
    not a way around the capability that guards ingest."""
    client, registry, _ = station
    head = _key(registry, ["read", "write"])
    r = _ingest(client, head, mode="compose", title="x", text=TEXT, stage=True)
    assert r.status_code == 403


def test_staging_is_refused_on_a_read_only_station(tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "registry"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    writable=False, mcp=False)
    with TestClient(app) as client:
        registry = app.state.registry
        head = _key(registry, ["read", "ingest"])
        r = _ingest(client, head, mode="compose", title="x", text=TEXT, stage=True)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "E_READONLY"
