# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Forest lifecycle and the ingest surface (spec J.7/J.8, criterion F.20).

Two host additions to Part G and A.5, and both are only worth having if
their guard rails hold: creating a forest must not let an id become a path
traversal, and ingesting must not become a way to write where the principal
cannot read — or to read the host filesystem with the Station's authority.

Each test builds its own registry root: these tests create and mutate
forests, and a shared root would make them order-dependent.
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


def _station(tmp_path, *, writable=True):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "registry"
    if not root.exists():
        root.mkdir()
        build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    writable=writable, mcp=False)
    return TestClient(app), app.state.registry, root


@pytest.fixture()
def station(tmp_path):
    """(client, registry, root) on a private registry root."""
    client, registry, root = _station(tmp_path)
    with client:
        yield client, registry, root


@pytest.fixture()
def readonly_station(tmp_path):
    client, registry, root = _station(tmp_path, writable=False)
    with client:
        yield client, registry, root


def _key(registry, caps, principal="alice", allow=None, forest=FOREST):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, set(caps), allow=allow)
    return {"Authorization": f"Bearer {key}"}


# -- J.7 forest lifecycle ---------------------------------------------------


def test_create_forest_produces_a_servable_forest(station):
    client, registry, root = station
    head = _key(registry, ["admin", "read"])

    r = client.post("/v1/admin/forests",
                    json={"id": "new-forest", "title": "New Forest"}, headers=head)
    assert r.status_code == 200, r.text
    assert r.json()["forest"]["commit"]

    # A.5 skeleton, git and all — the same thing `vine init` produces.
    assert (root / "new-forest" / "_index.md").is_file()
    assert (root / "new-forest" / "_meta" / "schema.md").is_file()
    assert (root / "new-forest" / ".git").is_dir()

    # And it is immediately usable by its creator, through the normal surface.
    listed = client.get("/v1/forests", headers=head).json()["forests"]
    assert "new-forest" in [f["id"] for f in listed]
    look = client.post("/v1/forests/new-forest/look", json={"id": "_index"},
                       headers=head)
    assert look.status_code == 200 and look.json()["title"] == "New Forest"


@pytest.mark.parametrize("bad", [
    "../escape", "a/b", "a\\b", "/abs", ".", "..", "", "UPPER", "trailing/",
    "x" * 64, "sp ace",
])
def test_create_forest_refuses_ids_that_are_not_names(station, bad):
    """The id is validated as a name, before it is joined to anything: a
    check that runs after the join has already built the traversal."""
    client, registry, root = station
    head = _key(registry, ["admin"])
    r = client.post("/v1/admin/forests", json={"id": bad, "title": "T"},
                    headers=head)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "E_SCHEMA"
    # Nothing was created anywhere near the root.
    assert sorted(p.name for p in root.iterdir()) == [FOREST]


def test_create_forest_refuses_an_existing_id(station):
    client, registry, _ = station
    head = _key(registry, ["admin"])
    r = client.post("/v1/admin/forests", json={"id": FOREST, "title": "Mine"},
                    headers=head)
    assert r.status_code == 400 and "already exists" in r.json()["error"]["message"]


def test_create_forest_needs_admin(station):
    client, registry, root = station
    head = _key(registry, ["read", "write", "ingest"])
    r = client.post("/v1/admin/forests", json={"id": "sneaky", "title": "T"},
                    headers=head)
    assert r.status_code == 403
    assert not (root / "sneaky").exists()


# -- J.8 ingest -------------------------------------------------------------


DOCS = [
    {"name": "onboarding.md", "text": "# Onboarding\n\nThe laptop request "
                                      "form lives on the intranet.\n"},
    {"name": "team/rituals.md", "text": "# Rituals\n\nRetro is on Thursdays "
                                        "at 16:00.\n"},
]


def test_upload_ingest_creates_nodes_without_any_model(station):
    """A forest with no `ingest` binding still ingests: curation falls back
    to the deterministic G.4 derivation (J.8)."""
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["curated"] is False
    assert len(body["planted"]) == 2
    assert body["errors"] == []
    assert body["commit"] and body["commit"] != body["commit_before"]

    # The staged bytes live outside git, under the disposable _derived tree.
    staged = root / FOREST / "_derived" / "uploads"
    assert (staged / "onboarding.md").is_file()
    assert (staged / "team" / "rituals.md").is_file()

    # And the documents are now reachable as forest, with a real summary.
    node = client.post(f"/v1/forests/{FOREST}/look",
                       json={"id": body["planted"][0]}, headers=head).json()
    assert node["summary"]
    hit = client.post(f"/v1/forests/{FOREST}/sniff",
                      json={"terms": ["Thursdays"]}, headers=head).json()
    assert hit["results"], "an uploaded body must be searchable"


def test_ingest_needs_the_ingest_capability(station):
    client, registry, _ = station
    head = _key(registry, ["read", "write"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS}, headers=head)
    assert r.status_code == 403
    assert "ingest" in r.json()["error"]["message"]


def test_ingest_refuses_a_dest_outside_scope(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"], allow=["projects/"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "people"},
                    headers=head)
    assert r.status_code == 403
    assert "outside this principal's scope" in r.json()["error"]["message"]


def test_scoped_principal_must_say_where(station):
    """Defaulting to the root would let a narrowly scoped principal write
    where it cannot read."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"], allow=["projects/"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS}, headers=head)
    assert r.status_code == 400
    assert "projects" in r.json()["error"]["hint"]


def test_scoped_principal_ingests_into_its_own_subtree(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"], allow=["projects/"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "projects"},
                    headers=head)
    assert r.status_code == 200, r.text
    planted = r.json()["planted"]
    assert planted and all(p.startswith("projects/") for p in planted)


def test_naming_a_host_path_needs_admin(station, tmp_path):
    """`path` is read with the Station's authority, not the caller's, so
    'ingest' alone must not turn into arbitrary host reads."""
    client, registry, _ = station
    secrets = tmp_path / "outside"
    secrets.mkdir()
    (secrets / "keys.md").write_text("# Keys\n\nroot password is hunter2\n")

    head = _key(registry, ["read", "ingest"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "adopt", "path": str(secrets)}, headers=head)
    assert r.status_code == 403
    assert "admin" in r.json()["error"]["message"]

    # Nothing about the host tree leaked into the forest.
    read = _key(registry, ["read"], principal="reader")
    hit = client.post(f"/v1/forests/{FOREST}/sniff",
                      json={"terms": ["hunter2"]}, headers=read).json()
    assert hit["results"] == []


def test_admin_may_adopt_a_host_path(station, tmp_path):
    client, registry, _ = station
    src = tmp_path / "handbook"
    src.mkdir()
    (src / "policy.md").write_text("# Policy\n\nExpenses are filed monthly.\n")

    head = _key(registry, ["read", "ingest", "admin"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "adopt", "path": str(src), "dest": "handbook"},
                    headers=head)
    assert r.status_code == 200, r.text
    assert len(r.json()["planted"]) == 1


@pytest.mark.parametrize("name", ["../outside.md", "/etc/passwd", "a/../../up.md"])
def test_upload_refuses_names_that_escape_the_staging_area(station, name):
    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    r = client.post(
        f"/v1/forests/{FOREST}/ingest",
        json={"mode": "upload", "files": [{"name": name, "text": "x"}]},
        headers=head)
    assert r.status_code == 400, r.text
    assert not (root / FOREST).parent.joinpath("outside.md").exists()
    assert not (root / FOREST / "up.md").exists()


def test_sync_after_upload_sees_an_edit(station):
    """The staging area is stable per forest, so a second upload of the same
    name is an update rather than a duplicate — which is what makes `sync`
    meaningful for browser-only operators."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    first = [{"name": "note.md", "text": "# Note\n\nThe old fact.\n"}]
    r1 = client.post(f"/v1/forests/{FOREST}/ingest",
                     json={"mode": "upload", "files": first, "dest": "uploads"},
                     headers=head)
    assert r1.status_code == 200 and len(r1.json()["planted"]) == 1

    second = [{"name": "note.md", "text": "# Note\n\nThe new fact entirely.\n"}]
    r2 = client.post(f"/v1/forests/{FOREST}/ingest",
                     json={"mode": "upload", "files": second, "dest": "uploads"},
                     headers=head)
    assert r2.status_code == 200, r2.text
    assert r2.json()["planted"] == [], "a re-upload must not duplicate the node"

    hit = client.post(f"/v1/forests/{FOREST}/sniff",
                      json={"terms": ["entirely"]}, headers=head).json()
    assert hit["results"], "the refreshed body must be searchable"


def test_readonly_station_refuses_before_staging_anything(readonly_station):
    """The Gardener catches per-file write failures and reports them as
    `errors`, so an unguarded ingest on a read-only deployment returns a list
    of identical "read-only" lines with a 200 — and leaves the uploads on
    disk. One refusal, before anything is written, is the honest answer."""
    client, registry, root = readonly_station
    head = _key(registry, ["read", "ingest", "admin"])

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "E_READONLY"
    assert not (root / FOREST / "_derived" / "uploads").exists()

    created = client.post("/v1/admin/forests", json={"id": "nope", "title": "N"},
                          headers=head)
    assert created.status_code == 403
    assert not (root / "nope").exists()


def _bind_ingest(registry, endpoint, model="some-model", name="p"):
    registry.put_provider(name, endpoint, "sk-test")
    registry.bind_model(FOREST, "ingest", name, model)


def test_a_silent_ingest_model_is_reported_as_silent(station):
    """The Curator falls back on any transport failure and never blocks
    (G.4 rule 6) — so a wrong key or a dead endpoint plants exactly what no
    model at all would plant. Reporting `curated` off the binding made those
    two states identical on screen, which is how an ingest looks like it
    worked while the model was never called."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _bind_ingest(registry, "http://127.0.0.1:9/v1")  # discard port: nothing listens

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["planted"], "a dead model must not stop the ingest"
    assert body["bound"] is True
    assert body["curated"] is False, "nothing was curated, so nothing may claim it was"
    assert body["curation"]["llm_summaries"] == 0
    assert body["curation"]["transport_errors"] > 0
    assert body["curation"]["error"], "the operator needs to know what failed"


def test_a_model_that_answers_badly_is_not_reported_as_unreachable(
        station, monkeypatch):
    """The failure the operator actually hits: the endpoint is fine, the
    model replies, and nothing it says survives A.4 validation. Reporting
    that as 'it never answered' sends them to debug the network."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _bind_ingest(registry, "http://127.0.0.1:9/v1", model="thinker")

    from monkeyllm_station import inference

    def fake_chat_from_binding(binding, *, timeout=180.0):
        # A reasoning model that spent its whole budget thinking.
        return (lambda messages: ""), binding["model"]

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat_from_binding)

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 200, r.text
    stats = r.json()["curation"]
    assert r.json()["curated"] is False and r.json()["bound"] is True
    assert stats["transport_errors"] == 0, "the endpoint answered every time"
    assert "error" not in stats, "there was no connection problem to report"
    assert stats["rejected"] > 0 and stats["retries"] > 0
    assert stats["rejected_because"] == "the model returned an empty message"
    assert stats["last_reply"] == ""


def test_a_verbose_model_is_trimmed_rather_than_discarded(station, monkeypatch):
    """The failure Jimmy hit end to end: the model answers, the summary is
    real but over the A.4 budget, and three retries do not shrink it. Giving
    up there files the document with a first-sentences heuristic — worse
    text, for tokens already spent."""
    import json as _json

    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _bind_ingest(registry, "http://127.0.0.1:9/v1", model="chatty")

    from monkeyllm_station import inference

    long_summary = (
        "Onboarding handbook 2026: the laptop request form lives on the "
        "intranet and is approved by the hiring manager. It also covers "
        "badge collection, the first-week buddy assignment, the payroll "
        "forms due before day five, and the security training that every "
        "new joiner must finish inside the first calendar month.")

    def fake_chat_from_binding(binding, *, timeout=180.0):
        return (lambda messages: _json.dumps({"summary": long_summary,
                                              "tags": ["onboarding"]}),
                binding["model"])

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat_from_binding)

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["curated"] is True, "a trimmed model summary is still curated"
    assert body["curation"]["llm_summaries"] == len(DOCS)
    assert body["curation"]["rejected"] == 0
    # Documents plus the region rollups: the repair has to reach both, or
    # every branch keeps the template summary the Gardener planted.
    assert body["curation"]["repaired"] >= len(DOCS)
    assert body["curation"]["branch_fallbacks"] == 0

    node = client.post(f"/v1/forests/{FOREST}/look",
                       json={"id": body["planted"][0]}, headers=head).json()
    assert node["summary"].startswith("Onboarding handbook 2026")
    assert "pending curation" not in node["summary"]
    assert "onboarding" in node["tags"]


def test_a_working_ingest_model_reports_what_it_wrote(station, monkeypatch):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _bind_ingest(registry, "http://127.0.0.1:9/v1")

    import json as _json

    from monkeyllm_station import inference

    def fake_chat_from_binding(binding, *, timeout=180.0):
        def chat(messages):
            return _json.dumps({"summary": "Onboarding facts: the laptop "
                                           "request form lives on the intranet.",
                                "tags": ["onboarding"]})
        return chat, binding["model"]

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat_from_binding)

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                    headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["curated"] is True and body["bound"] is True
    assert body["curation"]["llm_summaries"] == len(DOCS)
    assert body["curation"]["transport_errors"] == 0
    assert "error" not in body["curation"]


def test_a_later_upload_lands_where_the_operator_said(station):
    """The second upload of a batch flips to `sync` because the staging area
    is stable — but it is still an upload, and the operator picked a
    destination for THESE files. Taking the first batch's dest from config
    filed every later document in the wrong branch, silently."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])

    first = client.post(f"/v1/forests/{FOREST}/ingest", headers=head, json={
        "mode": "upload", "dest": "uploads",
        "files": [{"name": "first.md", "text": "# First\n\nAlpha fact.\n"}]})
    assert first.json()["planted"] == ["uploads/first"]

    second = client.post(f"/v1/forests/{FOREST}/ingest", headers=head, json={
        "mode": "upload", "dest": "projects",
        "files": [{"name": "second.md", "text": "# Second\n\nBeta fact.\n"}]})
    assert second.status_code == 200, second.text
    assert second.json()["planted"] == ["projects/second"]

    # A re-send of a known name still updates in place rather than moving it.
    third = client.post(f"/v1/forests/{FOREST}/ingest", headers=head, json={
        "mode": "upload", "dest": "people",
        "files": [{"name": "first.md", "text": "# First\n\nAlpha fact, revised.\n"}]})
    assert third.json()["planted"] == []
    assert third.json()["updated"] == ["uploads/first"]


def test_upload_accepts_bytes_so_binary_converters_are_reachable(station):
    """`.docx`/`.xlsx` converters read bytes (G.2). A text-only upload path
    left them usable from a shell and from nowhere else — which is the
    opposite of who the Station's ingest surface is for."""
    import base64

    client, registry, root = station
    head = _key(registry, ["read", "ingest"])
    raw = b"PK\x03\x04 not really a docx"

    r = client.post(f"/v1/forests/{FOREST}/ingest", headers=head, json={
        "mode": "upload", "dest": "uploads",
        "files": [{"name": "report.docx", "b64": base64.b64encode(raw).decode()}]})
    assert r.status_code == 200, r.text
    staged = root / FOREST / "_derived" / "uploads" / "report.docx"
    assert staged.read_bytes() == raw, "the bytes must survive the round trip"


def test_upload_refuses_undecodable_bytes(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = client.post(f"/v1/forests/{FOREST}/ingest", headers=head, json={
        "mode": "upload", "dest": "uploads",
        "files": [{"name": "report.docx", "b64": "not base64 at all!!"}]})
    assert r.status_code == 400
    assert "base64" in r.json()["error"]["message"]


def test_ingest_is_audited(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest", "admin"])
    client.post(f"/v1/forests/{FOREST}/ingest",
                json={"mode": "upload", "files": DOCS, "dest": "uploads"},
                headers=head)
    entries = client.get("/v1/admin/audit", headers=head).json()["entries"]
    ingest = [e for e in entries if e["primitive"] == "ingest"]
    assert ingest and ingest[0]["result"] == "ok"
    assert ingest[0]["commit_sha"], "the resulting head is the batch's record"
