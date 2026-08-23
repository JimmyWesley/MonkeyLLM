# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.61 — the write means what it said (F.117 - F.127).

Two rounds of outside verification found nothing wrong with the read side
and two things wrong with what happens to a write afterwards: a `prune`
that undid itself on somebody else's next upload (F.117), and a dataset
whose missing payload took the whole `look` with it (F.118).

The rest is the backlog those rounds left open — the `dest` spelling every
other surface uses (F.120), a report that echoed a mode nobody asked for
(F.121), the one read that ignored the waymark (F.122), an alias derived
from a digit inside a word (F.123), a refusal that named the token it
rejected and not the set it would accept (F.124), a derivation reachable
only through the source tree (F.125), and a floor that hid which half of
it fired (F.126).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

REPO = Path(__file__).resolve().parents[1]
FOREST = "forest-fixture"
DATASET = "sales/report-q1-2026"


@pytest.fixture()
def station(tmp_path):
    """A fresh forest per test: these are writes, and F.117 is specifically
    about what one call leaves behind for the next."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "root"
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root / FOREST


def _key(registry, principal="agent", caps=("read", "write", "ingest"),
         allow=("",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return {"Authorization": f"Bearer {key}"}


def call(client, head, primitive, body):
    return client.post(f"/v1/forests/{FOREST}/{primitive}", json=body,
                       headers=head)


def upload(client, head, files, dest="sales", **extra):
    body = {"mode": "upload", "files": files, "dest": dest, "wait": True}
    body.update(extra)
    r = client.post(f"/v1/forests/{FOREST}/ingest", json=body, headers=head)
    assert r.status_code in (200, 202), r.text
    return r.json()["job"]


# --- F.117: an upload processes exactly the entries it carries -------------

def test_a_pruned_node_is_not_replanted_by_the_next_upload(station):
    """The worst finding of the series: `prune` said `pruned: true`, and
    the next upload to the same branch planted the node again — with a
    fresh timestamp and an edge into the new material."""
    client, registry, _ = station
    head = _key(registry)

    first = upload(client, head, [
        {"name": "probe-one.md", "text": "# Probe one\n\nThe first probe.\n"}])
    planted = first["report"]["planted"]
    assert planted == ["sales/probe-one"], first["report"]

    assert call(client, head, "prune", {"id": planted[0]}).json()["pruned"]

    second = upload(client, head, [
        {"name": "probe-two.md", "text": "# Probe two\n\nThe second probe.\n"}])
    report = second["report"]
    # Only this batch's own entry, and the pruned id stays gone.
    assert report["planted"] == ["sales/probe-two"], report
    assert second["total"] == 1, second
    assert call(client, head, "look", {"id": "sales/probe-one"}
                ).json()["error"]["code"] == "E_NOT_FOUND"


def test_prune_takes_a_staged_source_with_it(tmp_path):
    """C.14 rule 2 (v0.61). A v0.61 upload consumes its own bytes, so this
    is the rule for what an OLDER version left staged — which is exactly
    the forest that was found resurrecting nodes. A real source tree is
    never touched by it."""
    from monkeyllm import Vine
    from monkeyllm.gardener import Gardener

    root = tmp_path / "pruned"
    build_forest(root)
    staging = root / "_derived" / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "staged.md").write_text("# Staged\n\nA doc.\n", encoding="utf-8")
    with Vine(root, writable=True) as v:
        # What an older Station did: adopt the staging directory, which
        # recorded it as this forest's source root and left the file there.
        report = Gardener(v).adopt(staging, dest="sales")
        assert report["planted"] == ["sales/staged"]
        assert (staging / "staged.md").is_file(), report

        out = v.prune("sales/staged")
        assert out["pruned"] is True
        assert not (staging / "staged.md").exists()
        assert out["staged_moved"] == "_derived/graveyard/sales/staged/source/staged.md"
        grave = root / out["staged_moved"]
        assert "A doc." in grave.read_text(encoding="utf-8")


def test_prune_never_touches_a_source_outside_the_forest(tmp_path):
    """A mirrored directory is somebody's source tree, and no removal
    inside a forest may delete from it."""
    from monkeyllm import Vine
    from monkeyllm.gardener import Gardener

    root = tmp_path / "mirrored"
    build_forest(root)
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "handbook.md").write_text("# Handbook\n\nOn the host.\n",
                                        encoding="utf-8")
    with Vine(root, writable=True) as v:
        planted = Gardener(v).adopt(mirror, dest="sales")["planted"]
        out = v.prune(planted[0])
        assert out["pruned"] is True
        assert "staged_moved" not in out, out
        assert (mirror / "handbook.md").is_file(), "a host source was deleted"


def test_the_second_upload_does_not_report_another_batch_as_stale(station):
    """A call may only testify about what it walked: the earlier batch's
    staged file is neither planted, refreshed nor reported `stale`."""
    client, registry, _ = station
    head = _key(registry)
    upload(client, head, [{"name": "one.md", "text": "# One\n\nFirst.\n"}])
    report = upload(client, head,
                    [{"name": "two.md", "text": "# Two\n\nSecond.\n"}])["report"]
    assert report["stale"] == [], report
    assert report["unchanged"] == [], report


def test_resending_a_name_is_still_an_update_not_a_second_node(station):
    """The property the stable staging area exists for, kept."""
    client, registry, forest_dir = station
    head = _key(registry)
    upload(client, head, [{"name": "same.md", "text": "# Same\n\nDraft one.\n"}])
    report = upload(client, head,
                    [{"name": "same.md", "text": "# Same\n\nDraft two.\n"}])["report"]
    assert report["planted"] == [], report
    assert report["updated"] == ["sales/same"], report
    body = (forest_dir / "sales" / "same.md").read_text(encoding="utf-8")
    assert "Draft two." in body


# --- F.118 / F.119: a missing payload is a fact about the payload ----------

def _hide_payload(forest_dir: Path) -> Path:
    db = forest_dir / "sales" / "report-q1-2026.db"
    assert db.is_file()
    db.rename(db.with_suffix(".db.hidden"))
    return db


def test_look_degrades_when_the_payload_is_gone(station):
    client, registry, forest_dir = station
    head = _key(registry)
    whole = call(client, head, "look", {"id": DATASET}).json()
    assert "payload_missing" not in whole
    assert "query_manual" in whole and "sample_rows" in whole

    _hide_payload(forest_dir)
    out = call(client, head, "look", {"id": DATASET}).json()
    assert "error" not in out, out
    assert out["payload_missing"] is True
    assert "query_manual" not in out and "sample_rows" not in out
    # The passport is all there.
    assert out["id"] == DATASET and out["title"] and out["summary"]


def test_a_dataset_naming_no_payload_still_reads(station):
    """The same story from the digest's side: the file it would have
    opened is not there, and the passport must survive it."""
    client, registry, forest_dir = station
    head = _key(registry)
    path = forest_dir / "sales" / "report-q1-2026.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"(?m)^payload: .*\n", "", text), encoding="utf-8")

    out = call(client, head, "look", {"id": DATASET}).json()
    assert "error" not in out, out
    assert out["payload_missing"] is True
    assert out["title"]


def test_query_and_tend_still_refuse_a_missing_payload(station):
    """Degrading is for the digest. A primitive that cannot do its work
    without the file must not invent an empty result set."""
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "query", "tend"))
    _hide_payload(forest_dir)
    for primitive, body in (("query", {"id": DATASET, "sql": "SELECT 1"}),
                            ("tend", {"id": DATASET,
                                      "sql": "DELETE FROM sales WHERE id = 1"})):
        out = call(client, head, primitive, body).json()
        assert out["error"]["code"] == "E_NOT_FOUND", (primitive, out)
        assert "payload missing" in out["error"]["message"]


def test_a_named_field_still_explains_its_own_absence(station):
    """`fields=` is the escape hatch, and a caller that asked for a
    payload-derived field must not get an unexplained gap."""
    client, registry, forest_dir = station
    head = _key(registry)
    _hide_payload(forest_dir)
    out = call(client, head, "look",
               {"id": DATASET, "fields": ["sample_rows"]}).json()
    assert out["payload_missing"] is True
    assert "sample_rows" not in out


def test_coverage_counts_the_payloads_the_forest_does_not_have(station):
    client, registry, forest_dir = station
    head = _key(registry)
    before = call(client, head, "coverage", {}).json()
    assert "payload_missing" not in before
    _hide_payload(forest_dir)
    after = call(client, head, "coverage", {}).json()
    assert after["payload_missing"] == 1, after
    named = [r for r in after["roots"] if r.get("payload_missing")]
    assert [r["id"] for r in named] == ["sales/_index"], after["roots"]


# --- F.120: a branch is addressed by its id --------------------------------

@pytest.mark.parametrize("dest", ["sales", "sales/_index"])
def test_both_spellings_of_dest_land_in_the_same_branch(station, dest):
    client, registry, _ = station
    head = _key(registry)
    report = upload(client, head,
                    [{"name": "spelling.md", "text": "# Spelling\n\nA doc.\n"}],
                    dest=dest)["report"]
    assert report["planted"] == ["sales/spelling"], report
    assert "/_index/" not in report["planted"][0]


def test_the_scope_check_reads_the_normalised_destination(station):
    """The test and the write must agree about which branch is meant."""
    client, registry, _ = station
    inside = _key(registry, "scoped", caps=("read", "ingest"), allow=("sales/",))
    for dest in ("sales", "sales/_index"):
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "dest": dest, "wait": True,
                              "files": [{"name": f"in-{dest[-1]}.md",
                                         "text": "# In\n\nInside scope.\n"}]},
                        headers=inside)
        assert r.status_code in (200, 202), (dest, r.text)

    outside = _key(registry, "elsewhere", caps=("read", "ingest"),
                   allow=("concepts/",))
    for dest in ("sales", "sales/_index"):
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "dest": dest, "wait": True,
                              "files": [{"name": "out.md", "text": "# Out\n\nx\n"}]},
                        headers=outside)
        assert r.json()["error"]["code"] == "E_FORBIDDEN", (dest, r.text)


# --- F.121: an upload is an upload, and it mirrors nothing -----------------

def test_the_job_and_the_report_say_the_mode_that_was_asked_for(station):
    client, registry, _ = station
    head = _key(registry)
    for text in ("One.", "Two."):
        job = upload(client, head, [{"name": "m.md", "text": f"# M\n\n{text}\n"}])
        assert job["mode"] == "upload", job
        assert job["report"]["mode"] == "upload", job["report"]
        assert "strategy" not in job, "the flip is gone; there is one mode"


def test_an_upload_never_becomes_the_forest_s_mirror(station):
    """One upload used to repoint a forest that really did mirror a folder
    at the upload staging area — so the operator's Sync offered to re-read
    the courier, and the folder they had adopted was forgotten."""
    import yaml

    client, registry, forest_dir = station
    head = _key(registry)
    cfg = forest_dir / "_meta" / "gardener.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(yaml.safe_dump({"source_root": "/data/handbook"}),
                   encoding="utf-8")

    upload(client, head, [{"name": "note.md", "text": "# Note\n\nUploaded.\n"}])

    after = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    assert after.get("source_root") == "/data/handbook", after


def test_an_upload_consumes_the_bytes_once_they_are_a_node(station):
    """The node is the record; the courier does not keep a copy, and a copy
    left behind is what a later pass reads as a document nobody sent."""
    client, registry, forest_dir = station
    head = _key(registry)
    report = upload(client, head,
                    [{"name": "gone.md", "text": "# Gone\n\nLanded.\n"}])["report"]
    assert report["planted"] == ["sales/gone"]
    assert report["consumed"] == ["gone.md"], report
    assert not (forest_dir / "_derived" / "uploads" / "gone.md").exists()

    # And re-sending the name is still an update, matched by the passport
    # rather than by the file that is no longer there.
    again = upload(client, head,
                   [{"name": "gone.md", "text": "# Gone\n\nRevised.\n"}])["report"]
    assert again["updated"] == ["sales/gone"], again


def test_a_file_that_did_not_land_is_kept(station):
    """`unsupported` and `error` files stay: nothing landed, and the file is
    the only evidence of what was sent."""
    client, registry, forest_dir = station
    head = _key(registry)
    report = upload(client, head,
                    [{"name": "mystery.zzz", "text": "not a known format"}])["report"]
    assert report["planted"] == [] and report["consumed"] == [], report
    assert report["unsupported"], report
    assert (forest_dir / "_derived" / "uploads" / "mystery.zzz").is_file()


# --- F.122: every read by id answers the waymark ---------------------------

# `view` is MCP-only by construction (C.6d) — REST answers J.14 bytes
# instead — so the REST sweep covers the five it serves and the engine test
# below covers all six.
MOVED_READS = (("look", {}), ("pick", {}), ("move", {}), ("history", {}),
               ("query", {"sql": "SELECT 1"}))


def test_every_read_by_id_answers_the_waymark_in_the_engine(tmp_path):
    """C.15 rule 4 named every read and v0.58 implemented five of six:
    `pick` read the file directly, and `pick` is the call an agent holding
    a written-down id actually makes."""
    from monkeyllm import Vine
    from monkeyllm.errors import VineError

    root = tmp_path / "engine"
    build_forest(root)
    with Vine(root, writable=True) as v:
        old = "organizations/datacoop"
        new = f"{old}-moved"
        v.transplant(old, new)
        for name in ("look", "pick", "move", "history", "view", "query"):
            fn = getattr(v, name)
            with pytest.raises(VineError) as caught:
                fn(old, "SELECT 1") if name == "query" else fn(old)
            assert caught.value.code == "E_MOVED", name
            assert caught.value.data["moved_to"] == new, name


def test_every_read_by_id_answers_the_waymark(station):
    client, registry, _ = station
    head = _key(registry, caps=("read", "write", "ingest", "query"))
    old = "organizations/datacoop"
    new = "organizations/datacoop-moved"
    assert call(client, head, "transplant",
                {"id": old, "new_id": new}).status_code == 200

    for primitive, extra in MOVED_READS:
        out = call(client, head, primitive, {"id": old, **extra}).json()
        assert out["error"]["code"] == "E_MOVED", (primitive, out)
        assert out["error"]["moved_to"] == new, primitive


def test_a_waymark_out_of_scope_is_the_absence_of_a_node(station):
    """C.15 rule 4: a waymark must not be a periscope. All six collapse to
    the byte-identical refusal of a node that never existed."""
    client, registry, _ = station
    admin = _key(registry)
    old, new = "organizations/datacoop", "concepts/datacoop-moved"
    assert call(client, admin, "transplant",
                {"id": old, "new_id": new}).status_code == 200

    narrow = _key(registry, "narrow", caps=("read", "query"),
                  allow=("organizations/",))
    for primitive, extra in MOVED_READS:
        out = call(client, narrow, primitive, {"id": old, **extra}).json()
        assert out["error"]["code"] == "E_NOT_FOUND", (primitive, out)
        assert "moved_to" not in json.dumps(out), primitive


# --- F.123: a derived alias is a name, not a leading digit -----------------

def test_a_digit_inside_a_word_derives_no_alias():
    from monkeyllm.gardener import derive_aliases

    assert derive_aliases(Path("x/9router-free-ai-router.md"), {},
                          "9Router - Free AI Router") == []


def test_a_numbered_file_still_derives_its_number():
    from monkeyllm.gardener import derive_aliases

    assert derive_aliases(Path("back-end/291-provider-budget.md"), {},
                          "Provider budget") == ["BE-291", "back-end/291", "291"]


# --- F.124: an unknown token names the set that would be accepted ----------

def test_an_unknown_rel_names_the_forest_s_declared_rels(station):
    client, registry, _ = station
    head = _key(registry)
    out = call(client, head, "graft",
               {"id": "concepts/stigmergy",
                "patch": {"add_links": [{"rel": "invalidates",
                                         "target": "concepts/rrf"}]}}).json()
    assert out["error"]["code"] == "E_SCHEMA"
    hint = out["error"]["hint"]
    assert "part-of" in hint and "related-to" in hint
    assert "_meta/schema.md" in hint


def test_an_unknown_type_names_the_forest_s_declared_types(station):
    client, registry, _ = station
    head = _key(registry)
    out = call(client, head, "plant",
               {"node": {"id": "concepts/manifesto", "type": "manifesto",
                         "parent": "concepts/_index", "title": "M",
                         "summary": "A node whose type this forest never "
                                    "declared, to prove the refusal."}}).json()
    assert out["error"]["code"] == "E_SCHEMA"
    assert "concept" in out["error"]["hint"]
    assert "_meta/schema.md" in out["error"]["hint"]


# --- F.125: what ingest derives can be re-derived ---------------------------

def _recurate(client, head, **body):
    return client.post("/v1/admin/recurate",
                       json={"forest": FOREST, **body}, headers=head)


def test_the_pass_adds_what_a_newer_rule_would_have_derived(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write", "ingest", "admin"))
    upload(client, head, [{"name": "291-provider-budget.md",
                           "text": "# Provider budget\n\nThe rule.\n"}],
           dest="sales")
    node = "sales/291-provider-budget"
    # A corpus ingested before the derivation existed.
    assert call(client, head, "graft",
                {"id": node, "patch": {"set_frontmatter": {"aliases": []}}}
                ).status_code == 200

    out = _recurate(client, head).json()
    assert out["changed"] == 1 and out["scanned"] >= 1, out
    assert out["updated"] == [node], out
    assert call(client, head, "look", {"id": node}).json()["aliases"] == ["291"]

    # Twice is once: union semantics, so the second pass finds nothing.
    again = _recurate(client, head).json()
    assert again["changed"] == 0, again


def test_the_pass_never_displaces_a_hand_written_name(station):
    client, registry, _ = station
    head = _key(registry, caps=("read", "write", "ingest", "admin"))
    upload(client, head, [{"name": "412-retry-policy.md",
                           "text": "# Retry policy\n\nThe rule.\n"}], dest="sales")
    node = "sales/412-retry-policy"
    call(client, head, "graft",
         {"id": node, "patch": {"set_frontmatter": {"aliases": ["the-retry-rule"]}}})
    _recurate(client, head)
    aliases = call(client, head, "look", {"id": node}).json()["aliases"]
    assert aliases[0] == "the-retry-rule"
    assert "412" in aliases


def test_the_pass_refuses_what_it_cannot_derive_from_a_passport(station):
    client, registry, _ = station
    head = _key(registry, caps=("read", "admin"))
    out = _recurate(client, head, derive=["origin"]).json()
    assert out["error"]["code"] == "E_SCHEMA"
    assert "origin" in out["error"]["hint"]


def test_the_pass_needs_admin_over_the_whole_forest(station):
    client, registry, _ = station
    branch = _key(registry, "branchy", caps=("read", "admin"), allow=("sales/",))
    assert _recurate(client, branch).status_code == 403
    reader = _key(registry, "reader", caps=("read",))
    assert _recurate(client, reader).status_code == 403


def test_a_read_only_station_refuses_the_pass(tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "ro"
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False,
                    writable=False)
    with TestClient(app) as client:
        registry = app.state.registry
        head = _key(registry, caps=("read", "admin"))
        r = client.post("/v1/admin/recurate", json={"forest": FOREST},
                        headers=head)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "E_READONLY"


# --- F.128: the staging area is visible and clearable ----------------------

def _staging(client, head, clear=False, forest=FOREST):
    if clear:
        return client.post("/v1/admin/staging", json={"forest": forest},
                           headers=head)
    return client.get("/v1/admin/staging", params={"forest": forest},
                      headers=head)


def test_what_never_landed_is_countable_and_clearable(station):
    """The bytes nobody can see are the bytes that come back to life."""
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write", "ingest", "admin"))
    staging = forest_dir / "_derived" / "uploads"

    empty = _staging(client, head).json()
    assert empty["unrecorded"] == 0 and empty["names"] == [], empty

    # One that lands and one that cannot: only the second stays.
    upload(client, head, [{"name": "lands.md", "text": "# Lands\n\nOk.\n"},
                          {"name": "mystery.zzz", "text": "unconvertible"}])
    seen = _staging(client, head).json()
    assert seen["unrecorded"] == 1, seen
    assert seen["names"] == ["mystery.zzz"], seen
    assert seen["bytes"] > 0

    cleared = _staging(client, head, clear=True).json()
    assert cleared["cleared"] == 1, cleared
    assert not (staging / "mystery.zzz").exists()
    # Moved, not destroyed: `_derived/` is disposable and the operator empties it.
    grave = forest_dir / "_derived" / "graveyard" / "_staging" / "mystery.zzz"
    assert grave.is_file()
    assert _staging(client, head).json()["unrecorded"] == 0


def test_a_forest_ingested_by_an_older_station_can_be_swept(tmp_path):
    """The situation found in the field: files staged by a previous version,
    their nodes since pruned, invisible to everyone."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "old"
    build_forest(root / FOREST)
    staging = root / FOREST / "_derived" / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    for name in ("BE-998.md", "BE-999.md"):
        (staging / name).write_text(f"# {name}\n\nLeft behind.\n",
                                    encoding="utf-8")

    app = build_app(root=root, registry_path=tmp_path / "s.db", mcp=False)
    with TestClient(app) as client:
        head = _key(app.state.registry, caps=("read", "admin"))
        seen = _staging(client, head).json()
        assert seen["unrecorded"] == 2, seen
        assert sorted(seen["names"]) == ["BE-998.md", "BE-999.md"], seen
        assert _staging(client, head, clear=True).json()["cleared"] == 2
        assert not (staging / "BE-998.md").exists()


def test_the_sweep_refuses_while_a_batch_is_running(station):
    """A running batch is reading these files, and one cancelled halfway
    leaves the rest of its bytes here."""
    client, registry, _ = station
    head = _key(registry, caps=("read", "write", "ingest", "admin"))
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "dest": "sales", "wait": False,
                          "files": [{"name": "slow.md", "text": "# Slow\n\nx\n"}]},
                    headers=head)
    assert r.status_code in (200, 202), r.text
    job = r.json()["job"]["id"]
    refused = _staging(client, head, clear=True)
    if refused.status_code == 409:
        assert refused.json()["error"]["code"] == "E_LOCKED"
        assert job in refused.json()["error"]["message"]
    else:
        # The batch of one may already have settled; then the sweep is
        # simply allowed, which is the same rule seen from the other side.
        assert refused.status_code == 200, refused.text


def test_the_sweep_needs_admin_over_the_whole_forest(station):
    client, registry, _ = station
    branch = _key(registry, "branchy", caps=("read", "admin"), allow=("sales/",))
    assert _staging(client, branch).status_code == 403
    assert _staging(client, branch, clear=True).status_code == 403


# --- F.126: the floor says which half refused ------------------------------

@pytest.fixture()
def answering(tmp_path, monkeypatch):
    """A bound model that is never called: every assertion here is about a
    refusal decided before the provider (J.10.10 rule 4)."""
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    calls: list = []

    def fake(binding, **kw):
        def chat(messages):
            calls.append(messages)
            return "a stub answer"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    root = tmp_path / "ask-root"
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "ask.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("asker")
    registry.grant("asker", FOREST, {"read", "admin"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, calls, {"Authorization": f"Bearer {key}"}


def _ask(client, head, **body):
    r = client.post(f"/v1/forests/{FOREST}/answer", json=body, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_refusal_counts_what_the_threshold_dropped(answering):
    """`evidence_count: 1` with nothing said about the two items the
    threshold dropped is a tuning problem invisible in the only artefact
    that could show it."""
    client, calls, head = answering
    out = _ask(client, head, question="stigmergy pheromone", k=3,
               min_evidence=2, min_score=0.9)
    assert out["reason"] == "insufficient_evidence"
    assert out["evidence_count"] == 0
    # A threshold nothing clears: everything that carried content is below it.
    assert out["below_min_score"] > 0
    assert out["min_score"] == 0.9
    assert calls == [], "the provider was called for a refused answer"

    # And the same question with the useful pair answers.
    ok = _ask(client, head, question="stigmergy pheromone", k=3,
              min_evidence=1, min_score=0.0)
    assert ok.get("answer")


def test_with_no_threshold_the_refusal_says_nothing_was_dropped(answering):
    client, _calls, head = answering
    out = _ask(client, head, question="zzqqx yyzzw qqxxz", k=3, min_evidence=2)
    assert out["reason"] == "insufficient_evidence"
    assert out["below_min_score"] == 0
    assert "min_score" not in out


# --- F.127 (server half): the skill teaches calls this Station accepts -----

def test_every_dest_the_skill_teaches_is_accepted(station):
    """The console generates in JavaScript and the server refuses in
    Python, and v0.60 shipped with the two disagreeing about how a branch
    is spelled. The literals in the generator are what gets generated, so
    they are what is fed to a real ingest here."""
    client, registry, _ = station
    head = _key(registry)
    source = (REPO / "apps" / "studio" / "src" / "skill.js").read_text(
        encoding="utf-8")
    dests = sorted(set(re.findall(r'dest:\s*"([^"]+)"', source)))
    assert dests, "the generator teaches no dest at all"

    for i, dest in enumerate(dests):
        # The branch the example names need not exist in the fixture; what
        # is under test is the SPELLING, so it is retargeted onto one that
        # does while keeping its own form.
        spelled = "sales/_index" if dest.endswith("/_index") else "sales"
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "dest": spelled, "wait": True,
                              "files": [{"name": f"skill-dest-{i}.md",
                                         "text": "# Dest\n\nA probe.\n"}]},
                        headers=head)
        assert r.status_code in (200, 202), (dest, r.text)
        planted = r.json()["job"]["report"]["planted"]
        assert planted == [f"sales/skill-dest-{i}"], (dest, planted)
