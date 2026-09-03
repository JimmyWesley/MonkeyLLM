# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.75 — a person can confirm a proposal (spec H.2.1 + J.18, criterion F.165).

H.2 has managed link-level `confidence < 1.0` since v0.10, and it managed it
on HEAT alone: both endpoints warm -> promote, both fully evaporated ->
prune, anything in between left alone. That is the right evidence for a link
nobody vouched for, and it is the ONLY evidence there was — so a correct
`related-to` proposal between two nodes nobody has walked could never be
confirmed by anything. In a freshly ingested forest every node is cold by
definition, which is exactly when the proposals are worth reading.

F.165 is the acceptance for the vote, and its clauses are the classes below:

* the Ranger provably leaves a cold proposal where it is (`TestRangerFirst`);
* `accept` writes 1.0 in ONE `.md` commit stamped with the acting principal,
  and a later Ranger run does not touch it (`TestAccept`);
* `reject` removes the link (`TestReject`);
* voting again on a settled link answers `unchanged`, never an error
  (`TestIdempotence`);
* fifty votes with one pruned target settle forty-nine and report one
  `missing` (`TestBatch`);
* an endpoint outside the caller's scope is absent from the listing and
  refused by the vote byte-identically to a link that does not exist
  (`TestScope`);
* a `confidence: 1.0` link and a structural edge are refused
  (`TestPopulation`);
* and the MCP tool list contains no name that can cast a vote
  (`TestNoAgentVote`) — the surface is the host's, and F.165 asserts its
  ABSENCE, which is the one thing a feature test never asserts by itself.

A note on the first class, because the setup looks arbitrary and is not.
H.2's cold-prune rule fires on `confidence <= prune_below` (default **0.5**)
with both heats at zero — so under the shipped defaults a 0.3 proposal
between two cold nodes is exactly what the Ranger REMOVES, which is
G.4.2.1 rule 5's stated lifecycle ("a proposal nobody ever walks costs one
frontmatter line and dies by H.2"). F.165's premise — the population the
Ranger leaves alone — therefore needs a forest whose `prune_below` sits
below the proposal, so the link is neither hot enough to promote nor cold
enough to prune. That is H.2's own "patience is a feature" case, it is one
line of `_meta/ranger.yaml`, and `test_the_default_ranger_can_never_say_yes`
pins the other half: under the DEFAULTS the Ranger can prune a cold
proposal and can never promote one. Either way heat cannot say yes, which is
the whole reason the vote exists.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
SRC = "projects/mixerllm/architecture"
TGT = "concepts/rag"
NOTE = "both stand on retrieval"

MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}

# Words a tool would have to wear to cast a vote. Checked as a vocabulary
# rather than as one name, because the failure this guards against is
# somebody adding the convenience later under a friendlier spelling.
VOTE_WORDS = ("vote", "link", "confirm", "approve", "accept", "promote",
              "settle", "confidence")


# -- fixtures ---------------------------------------------------------------


@pytest.fixture()
def station(tmp_path):
    """A registry and a forest of its own per test: these tests commit."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "forests"
    root.mkdir()
    forest = build_forest(root / FOREST)
    # See the module docstring: F.165's premise is the population H.2 leaves
    # alone, and with the shipped `prune_below: 0.5` a cold 0.3 proposal is
    # not that population — it is the one the Ranger deletes.
    (forest / "_meta" / "ranger.yaml").write_text(
        "prune_below: 0.2\n", encoding="utf-8")
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _key(registry, caps=("read", "write"), principal="curator", **grant):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), **grant)
    return {"Authorization": f"Bearer {key}"}


def _close_pool(client):
    """Release the Station's writer locks so a test may open the forest
    itself. The pool reopens on the next call."""
    state = client.app.state
    for entry in state.pool.list()["forests"]:
        if entry["active"]:
            fid = entry["id"]
            state.forest_lane(fid).submit(
                lambda fid=fid: state.pool.close_one(fid)).result()


def _ranger(client, root, **config):
    """One full Ranger cycle, on the forest the Station is serving."""
    from monkeyllm import Vine
    from monkeyllm.ranger import Ranger

    _close_pool(client)
    with Vine(root / FOREST, writable=True) as vine:
        ranger = Ranger(vine)
        ranger.config.update(config)
        return ranger.run()


def _frontmatter(root, node_id: str) -> dict:
    from monkeyllm.parser import split_frontmatter

    path = root / FOREST / f"{node_id}.md"
    return split_frontmatter(path.read_text(encoding="utf-8"))[0]


def _link(root, node_id: str, rel: str, target: str) -> dict | None:
    for link in _frontmatter(root, node_id).get("links") or []:
        if link.get("rel") == rel and link.get("target") == target:
            return link
    return None


def _git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root / FOREST), *args],
                          capture_output=True, text=True).stdout


def _propose(client, headers, target=TGT, source=SRC, confidence=0.3,
             note=NOTE, rel="related-to"):
    """A G.4.2.1-shaped proposal, planted through the ordinary `graft` the
    Curator itself uses — never by writing frontmatter behind the engine."""
    link = {"rel": rel, "target": target}
    if confidence is not None:
        link["confidence"] = confidence
    if note is not None:
        link["note"] = note
    r = client.post(f"/v1/forests/{FOREST}/graft", headers=headers,
                    json={"id": source, "patch": {"add_links": [link]}})
    assert r.status_code == 200, r.text
    return link


def _uncertain(client, headers, **params):
    r = client.get(f"/v1/forests/{FOREST}/links/uncertain", headers=headers,
                   params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _vote(client, headers, votes):
    r = client.post(f"/v1/forests/{FOREST}/links/vote", headers=headers,
                    json={"votes": votes})
    return r


def _one(id=SRC, rel="related-to", target=TGT, vote="accept") -> dict:
    return {"id": id, "rel": rel, "target": target, "vote": vote}


# -- F.165: the Ranger provably leaves it alone ------------------------------


class TestRangerFirst:
    def test_a_cold_proposal_survives_a_full_cycle(self, station):
        """The premise of the whole criterion: this is the population the
        vote exists for, and a test that did not verify it would be proving
        the vote settles something heat had already settled."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)

        assert _uncertain(client, headers)["total"] == 1
        report = _ranger(client, root)
        assert report["links"] == {"promoted": [], "pruned": []}

        link = _link(root, SRC, "related-to", TGT)
        assert link is not None and link["confidence"] == 0.3

    def test_both_endpoints_are_cold_and_the_listing_says_so(self, station):
        """J.18: the heat is in the listing because it is the answer to
        *why has this not been promoted already*. Zero is the interesting
        value, so it has to be present and not merely omitted."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)
        _ranger(client, root)

        group = _uncertain(client, headers)["groups"][0]
        assert group["source"]["id"] == SRC
        assert group["source"]["heat"] == 0.0
        assert group["links"][0]["target"]["id"] == TGT
        assert group["links"][0]["target"]["heat"] == 0.0

    def test_the_default_ranger_can_never_say_yes(self, station):
        """The other half, on the SHIPPED configuration: heat can delete a
        cold proposal and can never confirm one. That asymmetry is H.2.1's
        opening complaint, and it is why 0.8 would not do (rule 2)."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)

        report = _ranger(client, root, prune_below=0.5)
        assert report["links"]["promoted"] == []
        assert report["links"]["pruned"] == [f"{SRC} related-to->{TGT}"]
        assert _link(root, SRC, "related-to", TGT) is None


# -- F.165: accept ----------------------------------------------------------


class TestAccept:
    def test_accept_writes_one_point_zero_in_one_stamped_commit(self, station):
        client, registry, root = station
        headers = _key(registry, principal="ana")
        _propose(client, headers)
        _ranger(client, root)
        before = _git(root, "rev-list", "--count", "HEAD").strip()

        r = _vote(client, headers, [_one()])
        assert r.status_code == 200, r.text
        record = r.json()["votes"][0]
        assert record["outcome"] == "accepted"
        assert record["confidence"] == 1.0
        assert record["commit"]

        # H.2.1 rule 2: 1.0, not `promoted_confidence` — the value H.2
        # already declares untouchable.
        assert _link(root, SRC, "related-to", TGT)["confidence"] == 1.0

        # ONE commit, and only the passport in it (H.2.1 rule 1 / A.3.1).
        after = _git(root, "rev-list", "--count", "HEAD").strip()
        assert int(after) == int(before) + 1
        touched = _git(root, "show", "--name-only", "--format=", "HEAD").split()
        assert touched == [f"{SRC}.md"]

        subject = _git(root, "log", "-1", "--format=%s").strip()
        assert subject == f"vote(accept): {SRC} related-to->{TGT} 1.0"
        # J.4: stamped INTO the commit, never amended on afterwards.
        assert "station-principal: ana" in _git(root, "log", "-1", "--format=%b")

    def test_the_accepted_link_leaves_the_managed_population(self, station):
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)
        _vote(client, headers, [_one()])

        listing = _uncertain(client, headers)
        assert listing["total"] == 0 and listing["groups"] == []

    def test_a_later_ranger_run_does_not_touch_it(self, station):
        """H.2.1 rule 7: the Ranger is unchanged — it now runs over the same
        population minus whatever a person has settled."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)
        _vote(client, headers, [_one()])

        report = _ranger(client, root)
        assert report["links"] == {"promoted": [], "pruned": []}
        assert _link(root, SRC, "related-to", TGT)["confidence"] == 1.0

        # And with the SHIPPED prune_below too: a vote that a configuration
        # change can still sweep is not a vote (rule 2).
        report = _ranger(client, root, prune_below=0.5)
        assert report["links"] == {"promoted": [], "pruned": []}
        assert _link(root, SRC, "related-to", TGT)["confidence"] == 1.0

    def test_the_vote_is_audited_per_vote(self, station):
        """J.18: audited like every other hosted write, one row per
        decision — a row per BATCH could not say which link was settled."""
        client, registry, root = station
        headers = _key(registry, principal="ana", caps=("read", "write", "admin"))
        _propose(client, headers)
        _vote(client, headers, [_one()])

        rows = client.get(f"/v1/admin/audit?forest={FOREST}",
                          headers=headers).json()["entries"]
        votes = [r for r in rows if r["primitive"] == "vote"]
        assert len(votes) == 1
        assert votes[0]["principal"] == "ana" and votes[0]["result"] == "ok"
        assert votes[0]["commit_sha"]


# -- F.165: reject ----------------------------------------------------------


class TestReject:
    def test_reject_removes_the_link(self, station):
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)

        record = _vote(client, headers, [_one(vote="reject")]).json()["votes"][0]
        assert record["outcome"] == "rejected" and record["commit"]
        assert _link(root, SRC, "related-to", TGT) is None
        assert _git(root, "log", "-1", "--format=%s").strip() == \
            f"vote(reject): {SRC} related-to->{TGT}"
        assert _uncertain(client, headers)["total"] == 0

    def test_a_rejected_link_is_missing_the_second_time(self, station):
        """`missing` is J.18's word for gone, and a removed link is gone."""
        client, registry, _ = station
        headers = _key(registry)
        _propose(client, headers)
        _vote(client, headers, [_one(vote="reject")])

        record = _vote(client, headers, [_one(vote="reject")]).json()["votes"][0]
        assert record == {"id": SRC, "rel": "related-to", "target": TGT,
                          "vote": "reject", "outcome": "missing"}


# -- F.165: idempotence ------------------------------------------------------


class TestIdempotence:
    def test_voting_again_on_a_settled_link_is_unchanged_not_an_error(
            self, station):
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)
        _vote(client, headers, [_one()])
        head = _git(root, "rev-parse", "HEAD").strip()

        r = _vote(client, headers, [_one()])
        assert r.status_code == 200
        record = r.json()["votes"][0]
        assert record["outcome"] == "unchanged"
        assert record["confidence"] == 1.0
        assert "commit" not in record
        # Nothing was written: an idempotent vote is not a second commit.
        assert _git(root, "rev-parse", "HEAD").strip() == head


# -- F.165: the batch --------------------------------------------------------


class TestBatch:
    N = 50

    HUB = "notes/hub"

    def _many(self, client, headers):
        """One fresh source carrying fifty proposals, each to its own target
        — so pruning ONE target strips exactly one link. Fresh because
        `MAX_LINKS_PER_NODE` is 50 and every fixture document already has a
        few of its own."""
        nodes = [{"id": self.HUB, "type": "note", "parent": "notes/_index",
                  "title": "Proposal hub",
                  "summary": "A note the ingest hung fifty proposals on.",
                  "body": "Evidence."}]
        targets = [f"notes/probe-{i:02d}" for i in range(self.N)]
        nodes += [{"id": t, "type": "note", "parent": "notes/_index",
                   "title": f"Probe {t[-2:]}",
                   "summary": f"A throwaway note, number {t[-2:]}.",
                   "body": "Evidence."}
                  for t in targets]
        for start in range(0, len(nodes), 20):   # C.7.4: ≤20 nodes per plant
            r = client.post(f"/v1/forests/{FOREST}/plant", headers=headers,
                            json={"node": nodes[start:start + 20]})
            assert r.status_code == 200, r.text
        r = client.post(f"/v1/forests/{FOREST}/graft", headers=headers, json={
            "id": self.HUB,
            "patch": {"add_links": [{"rel": "related-to", "target": t,
                                     "confidence": 0.3} for t in targets]}})
        assert r.status_code == 200, r.text
        return targets

    def test_fifty_votes_with_one_pruned_target_settle_forty_nine(self, station):
        client, registry, root = station
        headers = _key(registry, caps=("read", "write"))
        targets = self._many(client, headers)

        # `force`, because the proposal itself is the anchor (C.14): the
        # backlink leaves in the same commit, which is precisely how a
        # reviewer's page goes stale under them.
        r = client.post(f"/v1/forests/{FOREST}/prune", headers=headers,
                        json={"id": targets[0], "force": True})
        assert r.status_code == 200, r.text

        votes = [_one(id=self.HUB, target=t) for t in targets]
        r = _vote(client, headers, votes)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["votes"]) == self.N
        assert body["counts"] == {"accepted": self.N - 1, "missing": 1}

        gone = [v for v in body["votes"] if v["outcome"] == "missing"]
        assert [v["target"] for v in gone] == [targets[0]]
        # And the work a person actually did was kept: forty-nine commits.
        for t in targets[1:]:
            assert _link(root, self.HUB, "related-to", t)["confidence"] == 1.0

    def test_a_batch_over_fifty_is_refused_whole(self, station):
        """J.18 bounds the batch; the bound is the envelope's, not a per-vote
        outcome — nothing was decided, so nothing is reported."""
        client, registry, _ = station
        headers = _key(registry)
        r = _vote(client, headers, [_one(target=f"notes/x{i}")
                                    for i in range(51)])
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "E_SCHEMA"

    def test_a_malformed_vote_refuses_alone(self, station):
        """Not all-or-nothing (J.18): one bad item must not discard the
        decision beside it."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers)
        r = _vote(client, headers, [{"id": SRC, "rel": "related-to"}, _one()])
        assert r.status_code == 200
        outcomes = [v["outcome"] for v in r.json()["votes"]]
        assert outcomes == ["refused", "accepted"]
        assert _link(root, SRC, "related-to", TGT)["confidence"] == 1.0


# -- F.165: the scope --------------------------------------------------------


class TestScope:
    def test_an_out_of_scope_endpoint_is_absent_and_missing(self, station):
        """H.2.1 rule 6: accepting publishes the target's id into a node
        other principals may read, so an endpoint the voter cannot see makes
        the link invisible AND unvotable — byte-identically to a link that
        does not exist, or the refusal becomes the periscope."""
        client, registry, root = station
        boss = _key(registry, caps=("read", "write", "admin"), principal="boss")
        _propose(client, boss)
        # The link is real: the unrestricted principal sees it.
        assert _uncertain(client, boss)["total"] == 1

        scoped = _key(registry, caps=("read", "write"), principal="scoped",
                      allow=["projects/"])
        assert _uncertain(client, scoped) == {
            "groups": [], "total": 0, "returned": 0, "links": 0,
            "truncated": False}

        # `concepts/rag` exists and is out of scope; `projects/ghost` is in
        # scope and does not exist. One answer, and the same one.
        out_of_scope = _vote(client, scoped, [_one()]).json()["votes"][0]
        absent = _vote(client, scoped,
                       [_one(target="projects/ghost")]).json()["votes"][0]
        assert out_of_scope["outcome"] == "missing"
        assert {k: v for k, v in out_of_scope.items() if k != "target"} == \
            {k: v for k, v in absent.items() if k != "target"}
        # And nothing was written for either.
        assert _link(root, SRC, "related-to", TGT)["confidence"] == 0.3

    def test_a_scoped_principal_settles_what_is_inside_its_own_scope(
            self, station):
        """J.18: `write` at the caller's OWN scope, never `admin`. A
        principal who may write inside a branch may settle the proposals
        inside it."""
        client, registry, root = station
        boss = _key(registry, caps=("read", "write", "admin"), principal="boss")
        inside = "projects/monkeyllm/primitives"
        _propose(client, boss, target=inside)

        scoped = _key(registry, caps=("read", "write"), principal="scoped",
                      allow=["projects/"])
        listing = _uncertain(client, scoped)
        assert listing["total"] == 1
        assert listing["groups"][0]["links"][0]["target"]["id"] == inside

        record = _vote(client, scoped,
                       [_one(target=inside)]).json()["votes"][0]
        assert record["outcome"] == "accepted"
        assert _link(root, SRC, "related-to", inside)["confidence"] == 1.0

    def test_read_without_write_reaches_neither_route(self, station):
        client, registry, _ = station
        reader = _key(registry, caps=("read",), principal="reader")
        assert client.get(f"/v1/forests/{FOREST}/links/uncertain",
                          headers=reader).status_code == 403
        assert _vote(client, reader, [_one()]).status_code == 403

    def test_both_routes_need_a_key(self, station):
        client, _, _ = station
        assert client.get(
            f"/v1/forests/{FOREST}/links/uncertain").status_code == 401
        assert client.post(f"/v1/forests/{FOREST}/links/vote",
                           json={"votes": [_one()]}).status_code == 401


# -- F.165: only the managed population --------------------------------------


class TestPopulation:
    def test_a_confidence_one_link_is_refused(self, station):
        """H.2.1 rule 3. `reject` is the direction that matters: rule 2 makes
        1.0 permanent, so a vote cannot walk one back — while `accept` on the
        same link is the idempotent case J.18 names `unchanged`."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers, target="concepts/stigmergy", confidence=1.0,
                 note=None)

        record = _vote(client, headers, [_one(target="concepts/stigmergy",
                                              vote="reject")]).json()["votes"][0]
        assert record["outcome"] == "refused"
        assert record["code"] == "E_READONLY"
        assert _link(root, SRC, "related-to", "concepts/stigmergy") is not None
        # It was never in the managed population to begin with.
        assert _uncertain(client, headers)["total"] == 0

    def test_a_structural_edge_is_refused_in_both_directions(self, station):
        """A link with no confidence field is not a proposal, and calling it
        `unchanged` would claim somebody had decided it."""
        client, registry, root = station
        headers = _key(registry)
        _propose(client, headers, target="projects/_index", rel="part-of",
                 confidence=None, note=None)

        for direction in ("accept", "reject"):
            record = _vote(client, headers,
                           [_one(rel="part-of", target="projects/_index",
                                 vote=direction)]).json()["votes"][0]
            assert record["outcome"] == "refused", direction
            assert record["code"] == "E_READONLY", direction
        assert _link(root, SRC, "part-of", "projects/_index") is not None
        assert _uncertain(client, headers)["total"] == 0


# -- J.18: the listing carries what a decision needs -------------------------


class TestListing:
    def test_the_group_carries_both_scents_and_the_note(self, station):
        client, registry, _ = station
        headers = _key(registry)
        _propose(client, headers)

        group = _uncertain(client, headers)["groups"][0]
        for scent in (group["source"], group["links"][0]["target"]):
            assert set(scent) == {"id", "type", "title", "summary", "heat"}
            assert scent["title"] and scent["summary"]
        item = group["links"][0]
        assert item["rel"] == "related-to" and item["confidence"] == 0.3
        assert item["note"] == NOTE
        # No bodies: a decision about adjacency is made on the scent.
        assert "body" not in json.dumps(group)

    def test_a_proposal_without_a_note_carries_no_empty_one(self, station):
        client, registry, _ = station
        headers = _key(registry)
        _propose(client, headers, note=None)
        assert "note" not in _uncertain(client, headers)["groups"][0]["links"][0]

    def test_the_page_is_grouped_by_source_and_walks_by_cursor(self, station):
        client, registry, _ = station
        headers = _key(registry)
        sources = ["projects/mixerllm/architecture",
                   "projects/monkeyllm/primitives",
                   "concepts/stigmergy"]
        for s in sources:
            _propose(client, headers, source=s, target="concepts/rag"
                     if s != "concepts/rag" else "concepts/stigmergy")

        first = _uncertain(client, headers, limit=2)
        assert first["total"] == 3 and first["returned"] == 2
        assert first["truncated"] is True
        assert [g["source"]["id"] for g in first["groups"]] == sorted(sources)[:2]
        assert first["next"] == sorted(sources)[1]

        second = _uncertain(client, headers, after=first["next"], limit=2)
        assert [g["source"]["id"] for g in second["groups"]] == sorted(sources)[2:]
        assert second["truncated"] is False and "next" not in second

    def test_an_unknown_query_parameter_is_refused(self, station):
        """A listing URL is pasted and hand-edited; a silently ignored
        parameter is a lie about what was listed (J.14.1's rule)."""
        client, registry, _ = station
        headers = _key(registry)
        r = client.get(f"/v1/forests/{FOREST}/links/uncertain",
                       headers=headers, params={"page": "2"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "E_SCHEMA"

    def test_an_empty_queue_is_a_shape_not_an_error(self, station):
        client, registry, _ = station
        assert _uncertain(client, _key(registry)) == {
            "groups": [], "total": 0, "returned": 0, "links": 0,
            "truncated": False}


# -- J.18: a read-only Station serves the GET and refuses the POST -----------


class TestReadOnlyStation:
    @pytest.fixture()
    def frozen(self, tmp_path):
        from starlette.testclient import TestClient

        from monkeyllm_station.app import build_app

        root = tmp_path / "forests"
        root.mkdir()
        forest = build_forest(root / FOREST)
        # The proposal is planted before the Station is frozen — a read-only
        # Station cannot make one.
        from monkeyllm import Vine
        with Vine(forest, writable=True) as vine:
            vine.graft(SRC, {"add_links": [{"rel": "related-to", "target": TGT,
                                            "confidence": 0.3}]})
        app = build_app(root=root, registry_path=tmp_path / "station.db",
                        mcp=False, writable=False)
        with TestClient(app) as client:
            yield client, app.state.registry

    def test_the_listing_is_served_and_the_vote_is_not(self, frozen):
        client, registry = frozen
        headers = _key(registry)
        assert _uncertain(client, headers)["total"] == 1
        r = _vote(client, headers, [_one()])
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "E_READONLY"


# -- F.165: no agent can cast a vote -----------------------------------------


class TestNoAgentVote:
    """H.2.1 rule 5, and the reason it is a rule rather than an omission: the
    entire purpose of link-level 0.3 is that a model asserted the link and
    something ELSE has to confirm it. An agent-callable accept would let the
    proposer close its own loop, and the confidence would stop recording
    anything at all.
    """

    def _tools(self, client, registry):
        headers = _key(registry, caps=("read", "write", "admin", "ingest",
                                       "query", "tend"), principal="agent")
        client.post("/mcp/", headers={**MCP_HEADERS, **headers},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}}})
        r = client.post("/mcp/", headers={**MCP_HEADERS, **headers},
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        return headers, r.json()["result"]["tools"]

    def test_no_registered_tool_can_cast_a_vote(self, station):
        client, registry, _ = station
        _, tools = self._tools(client, registry)
        names = {t["name"] for t in tools}
        assert len(names) >= 16, "the tool list did not load, so this is vacuous"

        offenders = sorted(n for n in names
                           if any(w in n.lower() for w in VOTE_WORDS))
        assert not offenders, f"the MCP surface offers {offenders}"

        # And the surface gained nothing at all: it is exactly the primitives
        # the REST route already serves, plus MCP's own two.
        from monkeyllm_station.app import SERVED_PRIMITIVES

        assert names <= set(SERVED_PRIMITIVES) | {"forests", "view"}

    def test_no_tool_takes_a_confidence_or_a_vote_argument(self, station):
        """A name is half of it: a `graft` that had been widened into a link
        editor (H.2.1 rule 4) would carry the argument under an old name."""
        client, registry, _ = station
        _, tools = self._tools(client, registry)
        offenders = []
        for tool in tools:
            props = (tool.get("inputSchema") or {}).get("properties") or {}
            offenders += [f"{tool['name']}.{p}" for p in props
                          if p.lower() in ("vote", "confidence")]
        assert not offenders, f"agent-reachable vote arguments: {offenders}"

    def test_calling_vote_as_a_tool_fails(self, station):
        client, registry, _ = station
        headers, _tools = self._tools(client, registry)
        r = client.post("/mcp/", headers={**MCP_HEADERS, **headers},
                        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "vote", "arguments": {
                                  "forest": FOREST, "id": SRC,
                                  "rel": "related-to", "target": TGT,
                                  "vote": "accept"}}})
        body = r.json()
        assert "error" in body or body.get("result", {}).get("isError") is True

    def test_the_instructions_never_teach_a_vote(self, station):
        """J.1.2 rule 5: the instructions are the one description every
        client receives unasked, so a surface named there is a surface
        agents will try."""
        from monkeyllm_station.mcp_surface import INSTRUCTIONS

        text = INSTRUCTIONS.lower()
        assert "vote" not in text and "confidence" not in text
