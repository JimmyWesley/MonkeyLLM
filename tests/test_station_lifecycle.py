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


@pytest.fixture()
def ingest_station(tmp_path, monkeypatch):
    """A Station that has been told which directory it may read (J.8.2).

    The env var is set before the app is built on purpose: the roots are a
    boot-time property, so a test that patched it afterwards would be
    testing something the deployment cannot do.
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("MONKEYLLM_INGEST_ROOTS", str(inbox))
    client, registry, root = _station(tmp_path)
    with client:
        yield client, registry, root, inbox


def test_admin_may_adopt_a_host_path_inside_the_ingest_roots(ingest_station):
    client, registry, _, inbox = ingest_station
    src = inbox / "handbook"
    src.mkdir()
    (src / "policy.md").write_text("# Policy\n\nExpenses are filed monthly.\n")

    head = _key(registry, ["read", "ingest", "admin"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "adopt", "path": str(src), "dest": "handbook"},
                    headers=head)
    assert r.status_code == 200, r.text
    assert len(r.json()["planted"]) == 1


class TestIngestRoots:
    """J.8.2 / F.29: the capability says who may ask, the roots say what
    exists to be asked for."""

    def test_unconfigured_station_reads_no_host_path(self, station, tmp_path):
        client, registry, _ = station
        src = tmp_path / "handbook"
        src.mkdir()
        (src / "policy.md").write_text("# Policy\n\nMonthly.\n", encoding="utf-8")

        head = _key(registry, ["read", "ingest", "admin"])
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "adopt", "path": str(src)}, headers=head)
        assert r.status_code == 403, r.text
        # The operator who DID mean to mirror a folder learns the one thing
        # they need from the refusal itself.
        assert "MONKEYLLM_INGEST_ROOTS" in r.json()["error"]["hint"]

    def test_upload_still_works_with_no_roots(self, station):
        """Deny-by-default must not mean a Station that cannot ingest: the
        modes that carry their own bytes are untouched."""
        client, registry, _ = station
        head = _key(registry, ["read", "ingest"])
        r = client.post(
            f"/v1/forests/{FOREST}/ingest",
            json={"mode": "upload", "dest": "uploads",
                  "files": [{"name": "n.md", "text": "# N\n\nA fact.\n"}]},
            headers=head)
        assert r.status_code == 200, r.text
        assert len(r.json()["planted"]) == 1

    def test_path_outside_the_roots_is_refused(self, ingest_station, tmp_path):
        client, registry, _, _ = ingest_station
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "x.md").write_text("# X\n\nBody.\n", encoding="utf-8")

        head = _key(registry, ["read", "ingest", "admin"])
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "adopt", "path": str(outside)}, headers=head)
        assert r.status_code == 403, r.text
        assert "outside this Station's ingest roots" in r.json()["error"]["message"]

    def test_traversal_out_of_a_root_is_refused(self, ingest_station, tmp_path):
        """The check is made after resolution, so `..` is collapsed first —
        a lexical comparison would accept this."""
        client, registry, _, inbox = ingest_station
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "x.md").write_text("# X\n\nBody.\n", encoding="utf-8")

        head = _key(registry, ["read", "ingest", "admin"])
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "adopt", "path": f"{inbox}/../elsewhere"},
                        headers=head)
        assert r.status_code == 403, r.text

    def test_a_root_holding_the_registry_is_dropped(self, tmp_path, monkeypatch):
        """One forest reading the volume that holds every forest is the
        tenant boundary failing in the direction that counts."""
        from monkeyllm_station.app import IngestRoots

        root = tmp_path / "registry"
        root.mkdir()
        gate = IngestRoots([tmp_path, root], root)
        assert gate.roots == []
        assert sorted(gate.rejected) == sorted([tmp_path.resolve(), root.resolve()])
        assert gate.check(tmp_path) is not None

    def test_a_missing_root_is_a_boot_error(self, tmp_path):
        from monkeyllm_station.app import IngestRoots

        with pytest.raises(ValueError) as e:
            IngestRoots([tmp_path / "nope"], tmp_path / "registry")
        assert "MONKEYLLM_INGEST_ROOTS" in str(e.value)


class TestSyncHasASource:
    """G.3 / F.29: the refresh of a forest that never adopted reads nothing."""

    def test_bare_sync_without_an_adopted_source_is_refused(self, station):
        client, registry, root = station
        head = _key(registry, ["read", "ingest", "admin"])
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "sync"}, headers=head)
        assert r.status_code == 400, r.text
        assert "no adopted source" in r.json()["error"]["message"]
        # and it recorded nothing on the way out
        assert not (root / FOREST / "_meta" / "gardener.yaml").exists()

    def test_targeted_sync_cannot_leave_the_source_root(self, ingest_station,
                                                        tmp_path):
        client, registry, _, inbox = ingest_station
        src = inbox / "docs"
        src.mkdir()
        (src / "a.md").write_text("# A\n\nAdopted body.\n", encoding="utf-8")
        (tmp_path / "secret.md").write_text("# S\n\nhunter2\n", encoding="utf-8")

        head = _key(registry, ["read", "ingest", "admin"])
        assert client.post(f"/v1/forests/{FOREST}/ingest",
                           json={"mode": "adopt", "path": str(src), "dest": "docs"},
                           headers=head).status_code == 200

        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "sync", "path": "../../secret.md"},
                        headers=head)
        assert r.status_code == 400, r.text
        assert "leaves the source root" in r.json()["error"]["message"]

    def test_narrowing_the_roots_stops_a_recorded_sync(self, ingest_station,
                                                       tmp_path, monkeypatch):
        """The recorded root was vetted when it was adopted; it need not be
        allowed today, and narrowing the list has to take effect."""
        from monkeyllm_station.app import IngestRoots

        client, registry, root, inbox = ingest_station
        src = inbox / "docs"
        src.mkdir()
        (src / "a.md").write_text("# A\n\nAdopted body.\n", encoding="utf-8")
        head = _key(registry, ["read", "ingest", "admin"])
        assert client.post(f"/v1/forests/{FOREST}/ingest",
                           json={"mode": "adopt", "path": str(src), "dest": "docs"},
                           headers=head).status_code == 200

        narrowed = tmp_path / "other-inbox"
        narrowed.mkdir()
        client.app.state.ingest_roots.roots = IngestRoots([narrowed], root).roots
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "sync"}, headers=head)
        assert r.status_code == 403, r.text


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


class TestIngestStatus:
    """J.8: a refresh names what it will re-read, or is not offered."""

    def test_a_fresh_forest_reports_nothing_to_refresh(self, station):
        client, registry, _ = station
        head = _key(registry, ["read", "ingest"])
        r = client.get(f"/v1/forests/{FOREST}/ingest", headers=head)
        assert r.status_code == 200, r.text
        assert r.json() == {"source": None, "can_sync": False, "host_paths": False}

    def test_it_names_the_source_after_an_adopt(self, ingest_station):
        client, registry, _, inbox = ingest_station
        src = inbox / "docs"
        src.mkdir()
        (src / "a.md").write_text("# A\n\nAdopted body.\n", encoding="utf-8")

        head = _key(registry, ["read", "ingest", "admin"])
        assert client.post(f"/v1/forests/{FOREST}/ingest",
                           json={"mode": "adopt", "path": str(src), "dest": "docs"},
                           headers=head).status_code == 200

        body = client.get(f"/v1/forests/{FOREST}/ingest", headers=head).json()
        assert body["source"] == src.resolve().as_posix()
        assert body["can_sync"] is True and body["host_paths"] is True

    def test_it_needs_the_ingest_capability(self, station):
        client, registry, _ = station
        head = _key(registry, ["read"])
        r = client.get(f"/v1/forests/{FOREST}/ingest", headers=head)
        assert r.status_code == 403, r.text


class TestBranchCreation:
    """J.5.7 / F.30: the console shapes the forest through `plant` and
    nothing else, so these are the engine's guarantees seen from the wire."""

    def _branch(self, client, head, *, id, parent, title, summary):
        return client.post(
            f"/v1/forests/{FOREST}/plant",
            json={"node": {"id": id, "parent": parent, "type": "branch",
                           "title": title, "summary": summary,
                           "source": "manual",
                           "body": f"# {title}\n\n> {summary}\n\n"
                                   "## Sub-branches\n\n## Direct bananas\n\n"
                                   "## Cross trails\n"}},
            headers=head)

    def test_a_branch_is_planted_and_the_parent_index_gains_one_entry(self, station):
        client, registry, root = station
        head = _key(registry, ["read", "write"])
        r = self._branch(client, head, id="contracts/_index", parent="_index",
                         title="Contracts",
                         summary="Signed client contracts by year, with their "
                                 "amendments and termination notices.")
        assert r.status_code == 200, r.text
        assert r.json()["commit"], "a branch is a commit like any other write"

        look = client.post(f"/v1/forests/{FOREST}/look",
                           json={"id": "contracts/_index"}, headers=head).json()
        assert look["type"] == "branch"

        # The entry is the engine's work, not the console's — the point of
        # going through `plant` rather than writing files.
        master = (root / FOREST / "_index.md").read_text(encoding="utf-8")
        assert master.count("[[contracts/_index]]") == 1
        assert "## Sub-branches" in master

    def test_a_duplicate_id_is_refused(self, station):
        client, registry, _ = station
        head = _key(registry, ["read", "write"])
        args = dict(id="contracts/_index", parent="_index", title="Contracts",
                    summary="Signed client contracts by year, with amendments.")
        assert self._branch(client, head, **args).status_code == 200
        again = self._branch(client, head, **args)
        assert again.status_code == 400, again.text
        assert "already exists" in again.json()["error"]["message"]

    def test_a_summary_that_breaks_a4_is_refused_not_truncated(self, station):
        client, registry, _ = station
        head = _key(registry, ["read", "write"])
        r = self._branch(client, head, id="wide/_index", parent="_index",
                         title="Wide", summary="word " * 200)
        assert r.status_code == 400, r.text
        assert "summary" in r.json()["error"]["message"]

    def test_an_id_that_does_not_live_under_its_parent_is_refused(self, station):
        """The console composes the id from the chosen parent, so this is the
        engine catching a client that got it wrong."""
        client, registry, _ = station
        head = _key(registry, ["read", "write"])
        r = self._branch(client, head, id="elsewhere/_index", parent="people/_index",
                         title="Elsewhere",
                         summary="A branch whose id does not sit under the "
                                 "parent it names.")
        assert r.status_code == 400, r.text

    def test_a_scoped_principal_cannot_create_at_the_root(self, station):
        """Creating a top-level branch grafts an entry into the master index —
        a node a scoped principal may not even read."""
        client, registry, _ = station
        head = _key(registry, ["read", "write"], principal="bob", allow=("people/",))
        r = self._branch(client, head, id="contracts/_index", parent="_index",
                         title="Contracts",
                         summary="Signed client contracts by year, with amendments.")
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "E_FORBIDDEN"

    def test_a_scoped_principal_creates_inside_its_own_grant(self, station):
        client, registry, _ = station
        head = _key(registry, ["read", "write"], principal="bob", allow=("people/",))
        r = self._branch(client, head, id="people/contractors/_index",
                         parent="people/_index", title="Contractors",
                         summary="External contractors, their agreements and "
                                 "the teams they report into.")
        assert r.status_code == 200, r.text
