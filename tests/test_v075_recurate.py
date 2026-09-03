# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.75 — re-curating the scent (spec J.13.6.1, criterion F.166).

G.4.2 and G.4.3 changed a derivation that is not arithmetic: the tags and
aliases the Curator writes from the DOCUMENT. Without a path to it, the
whole of v0.75's ingest work would apply only to documents nobody has
ingested yet — and the forests that need it most are the oldest ones.

`derive: ["scent"]` is that path, and it is the only member of J.13.6's
closed list allowed a model call. So these tests are written around the two
things that separates it from its neighbour `aliases`: it spends one model
call per node (which is why the cost is stated before it is spent, and why
a forest with nothing bound is refused before a job exists), and it
REPLACES the summary while UNIONING tags and aliases (which is why a
person's tag and a derived alias have to survive it).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"

# The document every test ingests: it introduces itself the way a technical
# corpus does — a ticket, a standard and a component — none of which the
# v0.74 curator ever wrote down (G.4.3's opening complaint).
DOC = {
    "name": "291-provider-budget.md",
    "text": ("# Provider budget\n\n"
             "Ticket BE-291 caps the provider budget. The rate limiter "
             "enforces the ISO 27001 quota on every call.\n"),
}
NODE = "sales/291-provider-budget"

# What the v0.74 curator produced: a summary, one generic tag, no aliases.
THIN = json.dumps({"summary": "A note about the provider budget rules.",
                   "tags": ["notes"]})

# What v0.75's curator produces from the same body. `made-up-code` is the
# negative control: the model proposes it and the document does not contain
# it, so G.4.3 rule 2's structural guard must refuse it.
RICH = json.dumps({
    "summary": "Ticket BE-291 caps the provider budget and the rate limiter "
               "enforces the ISO 27001 quota.",
    "tags": ["be-291", "iso-27001", "rate-limit"],
    "aliases": ["BE-291", "ISO 27001", "made-up-code"],
})


# --- the harness -------------------------------------------------------------

def _build(tmp_path, *, writable=True):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False,
                    writable=writable)
    return TestClient(app), root


@pytest.fixture()
def station(tmp_path):
    client, root = _build(tmp_path)
    with client:
        yield client, client.app.state.registry, root / FOREST


def _key(registry, principal="alice", caps=("read", "ingest", "admin"),
         allow=("",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return {"Authorization": f"Bearer {key}"}


def _bind(registry, model="curator-1"):
    registry.put_provider("p", "http://127.0.0.1:9/v1", "sk-test")
    registry.bind_model(FOREST, "ingest", "p", model)


class Scripted:
    """A chat that answers with whatever is set on it, counting completed
    calls — the counter is what makes "before any model call is spent"
    (rule 5) checkable rather than asserted."""

    def __init__(self, reply=THIN):
        self.reply = reply
        self.calls = 0
        self.gate: threading.Event | None = None

    def install(self, monkeypatch):
        from monkeyllm_station import inference

        def fake_chat_from_binding(binding, *, timeout=180.0):
            return self, binding["model"]

        monkeypatch.setattr(inference, "chat_from_binding",
                            fake_chat_from_binding)
        return self

    def __call__(self, messages):
        if self.gate is not None:
            self.gate.wait(timeout=20)
        self.calls += 1
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _call(client, head, primitive, body):
    return client.post(f"/v1/forests/{FOREST}/{primitive}", json=body,
                       headers=head)


def _upload(client, head, files=(DOC,), dest="sales"):
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": list(files), "dest": dest,
                          "wait": True}, headers=head)
    assert r.status_code in (200, 202), r.text
    return r.json()["job"]


def _scent(client, head, **extra):
    return client.post("/v1/admin/recurate",
                       json={"forest": FOREST, "derive": ["scent"], **extra},
                       headers=head)


def _poll(client, head, job_id, *, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/v1/forests/{FOREST}/jobs/{job_id}", headers=head)
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never settled")


def _run(client, head, chat, reply=RICH):
    """The pass, start to settle, with `reply` as the model's answer."""
    chat.reply = reply
    started = _scent(client, head)
    assert started.status_code == 202, started.text
    body = started.json()
    return body, _poll(client, head, body["job"]["id"])


def _ingested(client, registry, monkeypatch, files=(DOC,)):
    """A forest as a v0.74 Station left it: thin tags, no model aliases."""
    head = _key(registry)
    _bind(registry)
    chat = Scripted(THIN).install(monkeypatch)
    _upload(client, head, files)
    return head, chat


# --- F.166: the repair reaches a forest already ingested ---------------------

def test_the_pass_gives_an_old_forest_the_scent_v075_would_have_written(
        station, monkeypatch):
    """The acceptance, end to end: a node ingested by the old curator is
    found by an identifier it carries only in its BODY — which `locate`
    never reads — and after the pass `locate` answers for it."""
    client, registry, _ = station
    head, chat = _ingested(client, registry, monkeypatch)

    before = _call(client, head, "look", {"id": NODE}).json()
    assert before["tags"] == ["notes"], before
    # G.2.6 derived `291` from the filename; nothing wrote the ticket code.
    assert "BE-291" not in before.get("aliases", [])
    assert _call(client, head, "locate", {"query": "BE-291"}
                 ).json()["results"] == [], "the old scent cannot answer this"

    started, job = _run(client, head, chat)
    assert job["state"] == "done", job
    report = job["report"]
    assert report["changed"] == 1 and report["updated"] == [NODE], report
    assert report["fallbacks"] == 0 and report["errors"] == [], report

    after = _call(client, head, "look", {"id": NODE}).json()
    assert after["summary"].startswith("Ticket BE-291")
    assert {"be-291", "iso-27001", "rate-limit"} <= set(after["tags"])
    assert "BE-291" in after["aliases"] and "ISO 27001" in after["aliases"]
    # G.4.3 rule 2: the guard is structural, so a plausible invented name
    # the document does not contain is refused rather than written.
    assert "made-up-code" not in after["aliases"]

    hit = _call(client, head, "locate", {"query": "BE-291"}).json()["results"]
    assert [r["id"] for r in hit] == [NODE], hit


def test_the_pass_unions_and_never_deletes_what_a_person_wrote(
        station, monkeypatch):
    """Rule 3: the summary is the field this pass exists to improve, so it
    is replaced. Tags and aliases are not — they may have been corrected by
    a person or taught by the operator's map, and removing a bad tag stays a
    human act with a human's authority behind it."""
    client, registry, _ = station
    head, chat = _ingested(client, registry, monkeypatch)

    assert _call(client, head, "graft", {
        "id": NODE,
        "patch": {"set_frontmatter": {
            "tags": ["notes", "reviewed-by-ana"],
            "aliases": ["291", "the-budget-rule"]}}}).status_code == 200

    _run(client, head, chat)

    after = _call(client, head, "look", {"id": NODE}).json()
    assert "reviewed-by-ana" in after["tags"], "a person's tag survives"
    assert "notes" in after["tags"], "the old tag is not displaced either"
    assert "291" in after["aliases"], "the derived alias survives"
    assert "the-budget-rule" in after["aliases"], "the taught name survives"
    # …and the model's own contribution is beside them, not instead of them.
    assert "BE-291" in after["aliases"]
    assert after["summary"].startswith("Ticket BE-291")


def test_a_node_whose_model_call_fails_is_byte_identical_and_counted(
        station, monkeypatch):
    """Rule 4: a re-curation pass MUST NOT be able to leave a forest worse
    than it found it. The failure is silent by contract (G.4 rule 6), which
    is exactly why it has to be counted."""
    client, registry, forest = station
    head, chat = _ingested(client, registry, monkeypatch)

    passport = forest / "sales" / "291-provider-budget.md"
    was = passport.read_bytes()
    head_before = _git(forest, "rev-parse", "HEAD")

    _, job = _run(client, head, chat, reply=RuntimeError("the endpoint is down"))
    report = job["report"]
    assert report["fallbacks"] == 1, report
    assert report["changed"] == 0 and report["updated"] == [], report
    assert report["unchanged"] == [NODE], report
    assert passport.read_bytes() == was, "the node is left exactly as it was"
    assert _git(forest, "rev-parse", "HEAD") == head_before, "nothing committed"
    # The two silences stay apart (J.8): this one is the endpoint, not a
    # model whose every answer was refused.
    assert report["curation"]["transport_errors"] > 0
    assert report["curated"] is False and report["bound"] is True


def test_the_cost_is_stated_before_it_is_spent(station, monkeypatch):
    """Rule 5: the response that STARTS the job carries how many nodes are
    in scope, because that number is also the number of model calls the
    operator is about to pay for. Checked against a model that cannot
    answer until the test lets it — so "before" is a fact, not a race."""
    client, registry, _ = station
    docs = [{"name": f"note-{i}.md", "text": f"# Note {i}\n\nBody {i}.\n"}
            for i in range(4)]
    head, chat = _ingested(client, registry, monkeypatch, files=docs)
    assert chat.calls >= 4, "the ingest itself curated every document"

    chat.reply = RICH
    chat.calls = 0
    chat.gate = threading.Event()
    try:
        started = _scent(client, head)
        assert started.status_code == 202, started.text
        body = started.json()
        assert body["nodes"] == 4, body
        assert body["job"]["total"] == 4 and body["job"]["done"] == 0
        assert body["derive"] == ["scent"]
        assert chat.calls == 0, "not one model call had completed yet"
    finally:
        chat.gate.set()
    job = _poll(client, head, body["job"]["id"])
    assert job["state"] == "done" and job["report"]["scanned"] == 4


def test_the_scope_is_the_documents_the_gardener_planted(station, monkeypatch):
    """Branches are G.4.4's rollup (a region's summary comes from its
    children's entry lines, never from a body), `_meta/` is machinery, and
    a hand-planted node's summary is curation a human wrote. The count in
    the starting response is what says so out loud."""
    client, registry, _ = station
    head, chat = _ingested(client, registry, monkeypatch)

    assert _call(client, head, "plant", {"node": {
        "id": "sales/typed-by-hand", "type": "note", "parent": "sales/_index",
        "title": "Typed by hand",
        "summary": "A note a person wrote, whose summary is theirs to change.",
        "body": "# Typed by hand\n\nWritten by a person, not by the Gardener.\n",
    }}).status_code == 200

    started, job = _run(client, head, chat)
    assert started["nodes"] == 1, started
    assert job["report"]["updated"] == [NODE], job["report"]
    kept = _call(client, head, "look", {"id": "sales/typed-by-hand"}).json()
    assert kept["summary"].startswith("A note a person wrote")


def test_the_commit_names_the_pass_and_who_asked_for_it(station, monkeypatch):
    """J.13.6 rule 3, extended: one `.md` commit per changed node with the
    pass in the subject, and J.4's principal stamped on it like every other
    Station write."""
    client, registry, forest = station
    head, chat = _ingested(client, registry, monkeypatch)
    _run(client, head, chat)

    subject = _git(forest, "log", "-1", "--format=%s")
    assert subject == f"recurate(scent): {NODE}", subject
    assert "station-principal: alice" in _git(forest, "log", "-1", "--format=%B")
    # `.md` only, and the parent index too — a summary is replicated
    # verbatim into every index that lists the node (A.5), so a passport
    # rewritten alone would leave the map answering with the old scent.
    files = _git(forest, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == ["sales/291-provider-budget.md", "sales/_index.md"]
    index = (forest / "sales" / "_index.md").read_text(encoding="utf-8")
    assert "Ticket BE-291 caps the provider budget" in index


def test_a_second_pass_over_the_same_answer_changes_nothing(station,
                                                            monkeypatch):
    """A node whose curation produces no change is not rewritten and not
    committed — the answer an operator running it twice should get."""
    client, registry, forest = station
    head, chat = _ingested(client, registry, monkeypatch)
    _run(client, head, chat)
    settled = _git(forest, "rev-parse", "HEAD")

    _, job = _run(client, head, chat)
    assert job["report"]["changed"] == 0, job["report"]
    assert job["report"]["unchanged"] == [NODE], job["report"]
    assert _git(forest, "rev-parse", "HEAD") == settled
    assert job["report"]["commit"] is None, "no HEAD moved, so none is claimed"


# --- the refusals ------------------------------------------------------------

def test_a_forest_with_no_ingest_model_is_refused_before_a_job_exists(station):
    """A job that would fall back on every node spends nothing and repairs
    nothing, and reports `done` over a forest that did not change."""
    client, registry, _ = station
    head = _key(registry)
    out = _scent(client, head)
    assert out.status_code == 400, out.text
    assert out.json()["error"]["code"] == "E_SCHEMA"
    assert "ingest" in out.json()["error"]["message"]
    jobs = client.get(f"/v1/forests/{FOREST}/jobs", headers=head).json()
    assert jobs["jobs"] == [], "a refusal must not leave a record behind"


def test_a_read_only_station_refuses_the_pass(tmp_path):
    client, root = _build(tmp_path, writable=False)
    with client:
        registry = client.app.state.registry
        head = _key(registry)
        _bind(registry)
        out = _scent(client, head)
        assert out.status_code == 403
        assert out.json()["error"]["code"] == "E_READONLY"


def test_the_pass_needs_admin_over_the_whole_forest(station):
    client, registry, _ = station
    _bind(registry)
    branch = _key(registry, "branchy", caps=("read", "ingest", "admin"),
                  allow=("sales/",))
    assert _scent(client, branch).status_code == 403
    reader = _key(registry, "reader", caps=("read",))
    assert _scent(client, reader).status_code == 403


def test_the_two_derivations_are_not_mixable(station):
    """One is arithmetic the caller waits for and one answers with a job:
    one response cannot be both, so the refusal says which is which."""
    client, registry, _ = station
    head = _key(registry)
    _bind(registry)
    out = client.post("/v1/admin/recurate",
                      json={"forest": FOREST, "derive": ["aliases", "scent"]},
                      headers=head)
    assert out.status_code == 400
    assert out.json()["error"]["code"] == "E_SCHEMA"
    assert "scent" in out.json()["error"]["message"]


def test_the_aliases_pass_is_untouched_by_the_new_member(station, monkeypatch):
    """J.13.6 rule 1 is a guarantee about `aliases` and it stays exactly as
    written: no source tree, no converter, no model, no network."""
    client, registry, _ = station
    head, chat = _ingested(client, registry, monkeypatch)
    assert _call(client, head, "graft", {
        "id": NODE, "patch": {"set_frontmatter": {"aliases": []}}}
    ).status_code == 200
    chat.calls = 0

    out = client.post("/v1/admin/recurate", json={"forest": FOREST},
                      headers=head)
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["changed"] == 1 and body["updated"] == [NODE], body
    assert "job" not in body, "the arithmetic half still answers in place"
    assert chat.calls == 0, "no model was called"
    assert _call(client, head, "look", {"id": NODE}).json()["aliases"] == ["291"]


def test_a_running_batch_and_the_pass_refuse_each_other(station, monkeypatch):
    """One batch per forest at a time (J.9). A re-curation and an ingest
    write the same passports, so they share the lock — and the refusal
    names the job that holds it."""
    client, registry, _ = station
    head, chat = _ingested(client, registry, monkeypatch)
    chat.reply = RICH
    chat.gate = threading.Event()
    try:
        started = _scent(client, head).json()
        blocked = client.post(f"/v1/forests/{FOREST}/ingest",
                              json={"mode": "upload", "dest": "sales",
                                    "files": [{"name": "later.md",
                                               "text": "# Later\n\nx.\n"}]},
                              headers=head)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "E_LOCKED"
        assert started["job"]["id"] in blocked.json()["error"]["message"]
    finally:
        chat.gate.set()
    _poll(client, head, started["job"]["id"])

    # …and the other way round, which is the half a new job could break.
    def naps(draft):
        time.sleep(0.4)
        return draft

    monkeypatch.setattr("monkeyllm.gardener.discover_hooks", lambda: [naps])
    running = client.post(f"/v1/forests/{FOREST}/ingest",
                          json={"mode": "upload", "dest": "sales",
                                "files": [{"name": f"slow-{i}.md",
                                           "text": f"# Slow {i}\n\nx.\n"}
                                          for i in range(4)]},
                          headers=head)
    assert running.status_code == 202, running.text
    refused = _scent(client, head)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "E_LOCKED"
    _poll(client, head, running.json()["job"]["id"], timeout=60)


def test_the_pass_can_be_cancelled_and_keeps_what_it_committed(station,
                                                               monkeypatch):
    """Cancellation is honoured at step boundaries: a node is curated and
    committed, or untouched — never half-written."""
    client, registry, _ = station
    docs = [{"name": f"note-{i}.md", "text": f"# Note {i}\n\nBody {i}.\n"}
            for i in range(6)]
    head, chat = _ingested(client, registry, monkeypatch, files=docs)

    from monkeyllm_station import inference

    def crawl(messages):
        time.sleep(0.3)
        return RICH

    monkeypatch.setattr(inference, "chat_from_binding",
                        lambda binding, *, timeout=180.0: (crawl,
                                                           binding["model"]))

    started = _scent(client, head).json()
    assert started["nodes"] == 6
    time.sleep(0.4)
    client.post(f"/v1/forests/{FOREST}/jobs/{started['job']['id']}/cancel",
                headers=head)
    job = _poll(client, head, started["job"]["id"], timeout=60)
    assert job["state"] == "cancelled", job
    report = job["report"]
    assert report["scanned"] < 6, report
    assert report["changed"] == len(report["updated"])


# --- the engine's own half ---------------------------------------------------

def test_the_synchronous_pass_refuses_the_member_that_costs_a_model(tmp_path):
    """`Gardener.recurate` is the passport arithmetic and says so: folding
    `scent` into it would make rule 1 a sentence about a method that no
    longer holds it."""
    from monkeyllm import Vine
    from monkeyllm.errors import VineError
    from monkeyllm.gardener import Gardener

    root = tmp_path / "forest"
    build_forest(root)
    with Vine(root, writable=True) as v:
        with pytest.raises(VineError) as caught:
            Gardener(v).recurate(["scent"])
        assert caught.value.code == "E_SCHEMA"
        assert "J.13.6.1" in caught.value.hint
        assert "scent" in Gardener.DERIVABLE


def test_the_operators_alias_map_survives_the_pass(tmp_path):
    """G.2.6's other input: what only an operator knows — that `back-end`
    is spelled `BE`. It lives in the forest's own `gardener.yaml`, and a
    model that never heard of it must not be able to drop it."""
    import yaml

    from monkeyllm import Vine
    from monkeyllm.curator import Curator
    from monkeyllm.gardener import Gardener

    root = tmp_path / "forest"
    build_forest(root)
    (root / "_meta" / "gardener.yaml").write_text(
        yaml.safe_dump({"aliases": {"back-end": "BE"}}), encoding="utf-8")
    src = tmp_path / "dump" / "back-end"
    src.mkdir(parents=True)
    (src / "291-provider-budget.md").write_text(DOC["text"], encoding="utf-8")

    with Vine(root, writable=True) as v:
        planted = Gardener(v, hooks=[Curator(lambda m: THIN)]).adopt(
            tmp_path / "dump", dest="sales")["planted"]
        node_id = planted[0]
        assert "BE-291" in v.look(node_id)["aliases"]

    with Vine(root, writable=True) as v:
        out = Gardener(v, hooks=[Curator(lambda m: RICH)]).recurate_scent()
        assert out["changed"] == 1, out
        aliases = v.look(node_id)["aliases"]
        # The map's own spelling is first and unmoved; the model's picks
        # joined it (G.2.6 rule 3's union, applied to a second writer).
        assert aliases[0] == "BE-291"
        assert "ISO 27001" in aliases and "made-up-code" not in aliases


def test_a_dataset_is_re_curated_from_its_map(tmp_path):
    """G.4.6: the dataset's scent comes from its map — structure and three
    rows per table, already the passport's own body — so a 5 MB CSV and a
    5 GB database cost the model the same few hundred tokens. The two
    generated sections stay the Gardener's (rule 3)."""
    from monkeyllm import Vine
    from monkeyllm.curator import Curator
    from monkeyllm.gardener import Gardener

    root = tmp_path / "forest"
    build_forest(root)
    src = tmp_path / "dump"
    src.mkdir()
    (src / "orders.csv").write_text(
        "region,total\nNorth,10\nSouth,20\n", encoding="utf-8")

    reply = json.dumps({"summary": "Orders by region, with totals per row.",
                        "tags": ["orders", "region"]})
    with Vine(root, writable=True) as v:
        node_id = Gardener(v, hooks=[Curator(lambda m: THIN)]).adopt(
            src, dest="sales")["planted"][0]
        body_before = v.pick(node_id)["body"]

    with Vine(root, writable=True) as v:
        out = Gardener(v, hooks=[Curator(lambda m: reply)]).recurate_scent()
        assert node_id in out["updated"], out
        node = v.look(node_id)
        assert node["summary"].startswith("Orders by region")
        assert {"orders", "region"} <= set(node["tags"])
        assert v.pick(node_id)["body"] == body_before, "the map is untouched"


# --- the console (J.13.6.1 rule 7) -------------------------------------------

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"


def test_the_card_names_what_separates_it_from_its_neighbours():
    """Rule 7: its own card in Optimize, and it MUST name the two things
    that set it apart — it spends model calls, and it changes what a node
    SAYS rather than what finds it. A static source check, on F.137's
    boundary: the rendered card is not verifiable from here, but a card
    that stopped saying either of those things is.
    """
    import json as _json

    view = (STUDIO / "views" / "Ingest.jsx").read_text(encoding="utf-8")
    assert "<Rescent" in view, "the card is not mounted in the Optimize tab"
    # Mounted beside the repairs it must not be confused with.
    for neighbour in ("<Rebuild", "<Rederive", "<Staging", "<DenseLayer"):
        assert neighbour in view

    catalogue = _json.loads(
        (STUDIO / "locales" / "ingest" / "en.json").read_text(encoding="utf-8"))
    cost = catalogue["ingest.rescent_cost"].lower()
    assert "model call" in cost, "the spend is not stated"
    assert "says about itself" in cost and "finds it" in cost, (
        "the card does not distinguish what a node says from what finds it")
    assert "{n}" in catalogue["ingest.rescent_scope"], (
        "rule 5: the count in scope is what the card states as the cost")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True).stdout.strip()
