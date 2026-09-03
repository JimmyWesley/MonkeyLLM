# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.75 — tags are edited, applied and browsed (spec J.5.18, criterion F.168).

Tags are one of the four columns `locate` ranks by (C.6.1), which makes them
the cheapest correction anybody can make to a forest's findability. Until
v0.75 Studio surfaced them as a comma-separated text field on a screen
reachable from exactly one console, and there was no way to see what a
forest was tagged BY at all.

F.168's clauses split cleanly by what can be checked where, and this file
is deliberately explicit about the line:

* **The route is engine-checkable and is checked here.** `TestVocabulary`
  proves the counts are computed over the caller's whole scope in SQL —
  against a hand count taken off the passports on disk, so a count that came
  from a page instead of a GROUP BY fails — and that changing the page size
  changes the listing and never a count. `TestScope` proves a scoped
  principal is counted inside their own region and nowhere else.
  `TestSurface` covers the refusals a route owes: an unknown query
  parameter, a `limit` that is not a number, the `read` capability, GET
  only, and no MCP twin.

* **Union and subtract are proven at the graft level** (`TestMerge`),
  running the console's own sequence against the real engine: read the
  node's tags, merge, graft the merged list. Applying twice is idempotent, a
  remove subtracts only what was named, and neither ever replaces the set a
  node already carried.

* **A refusal names the tag** (`TestRefusal`), and the grandfathering that
  makes the read-then-merge sequence safe is pinned with it: a node's own
  pre-v0.75 tags go back untouched, so a bulk apply cannot be refused for
  tags it did not add.

* **One node's refusal does not abandon the rest** (`TestPartialRun`) — the
  engine half of rule 2: each graft is its own commit, so the nodes that
  landed are committed and the one that refused changed nothing.

* **The console's own clauses live in `apps/studio/check-tags.mjs`**
  (`TestConsole`), the construction `check-hands.mjs` and `check-skill.mjs`
  already use. What that checker CAN see is the arithmetic (imported and
  exercised: union, subtract, the fold, and the summary that decides whether
  a run may call itself complete) and the structural facts — the read before
  the write, the merged list on the wire, a loop with no break, the
  vocabulary read off the documented route, nothing folded on the way to the
  engine. What it cannot see, and what stays normative text with no test on
  F.137's stated boundary, is that the progress bar moves, that a click
  re-renders the listing, and that a refusal is visible on screen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import build_forest

REPO = Path(__file__).resolve().parents[1]
STATION = REPO / "apps" / "station"
STUDIO = REPO / "apps" / "studio"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
NODE = "concepts/rag"
OTHER = "concepts/mcp"

MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


# -- fixtures ---------------------------------------------------------------


@pytest.fixture()
def station(tmp_path):
    """A registry and a forest of its own per test: these tests commit."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry, root


@pytest.fixture()
def readonly_station(tmp_path):
    """The same forest, served by a Station that may not write (J.13.3's
    rule, restated: reviewing a vocabulary is reading)."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    writable=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _key(registry, caps=("read", "write"), principal="curator", **grant):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), **grant)
    return {"Authorization": f"Bearer {key}"}


def _tags(client, headers, **params):
    r = client.get(f"/v1/forests/{FOREST}/tags", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _look_tags(client, headers, node_id):
    r = client.post(f"/v1/forests/{FOREST}/look", headers=headers,
                    json={"id": node_id, "fields": ["tags"]})
    assert r.status_code == 200, r.text
    return r.json()["tags"]


def _graft_tags(client, headers, node_id, tags):
    return client.post(f"/v1/forests/{FOREST}/graft", headers=headers,
                       json={"id": node_id,
                             "patch": {"set_frontmatter": {"tags": tags}}})


def _write_tags_behind_the_engine(client, registry, root, node_id, tags):
    """A passport as an older engine could have written it.

    Behind `graft` on purpose: both callers need a `tags` value no engine
    would accept today — a duplicate, and a spelling G.4.2 rule 2 refuses —
    and the point of each test is that the arithmetic and the grandfathering
    are right even when the data on disk is not. Serialized through the
    parser's own writer, so the file is the shape the parser produces rather
    than the shape a string splice happened to leave.
    """
    from monkeyllm.parser import serialize_node, split_frontmatter

    path = root / FOREST / f"{node_id}.md"
    fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    fm["tags"] = tags
    path.write_text(serialize_node(fm, body), encoding="utf-8")
    subprocess.run(["git", "-C", str(root / FOREST), "add", "-A"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root / FOREST), "commit", "-m", "legacy"],
                   check=True, capture_output=True)
    r = client.post("/v1/admin/reindex",
                    headers=_key(registry, caps=("read", "admin"),
                                 principal=f"root-{node_id.replace('/', '-')}"),
                    json={"forest": FOREST})
    assert r.status_code == 200, r.text


def _on_disk(root, prefix: str | None = None) -> dict[str, int]:
    """The vocabulary as the PASSPORTS hold it: one hand count, taken off
    the files, never off the catalog the route reads.

    This is what makes `TestVocabulary` a test of the arithmetic rather than
    of the query: a count assembled from a page, or read off the FTS row
    (which is tokenized, so it folds diacritics away), disagrees with this.
    """
    from monkeyllm.parser import split_frontmatter

    counts: dict[str, int] = {}
    for path in sorted((root / FOREST).rglob("*.md")):
        rel = path.relative_to(root / FOREST).as_posix()
        if rel.startswith("_derived/"):
            continue
        node_id = rel[: -len(".md")]
        if prefix is not None and not node_id.startswith(prefix):
            continue
        try:
            fm = split_frontmatter(path.read_text(encoding="utf-8"))[0]
        except Exception:  # noqa: BLE001 — a file with no passport is not a node
            continue
        for tag in dict.fromkeys(fm.get("tags") or []):
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    return counts


# -- F.168: the vocabulary is counted over the scope, in SQL -----------------


class TestVocabulary:
    def test_the_route_answers_the_tags_that_actually_occur(self, station):
        client, registry, root = station
        headers = _key(registry, caps=("read",))

        payload = _tags(client, headers)
        got = {e["tag"]: e["nodes"] for e in payload["tags"]}
        assert got, "the fixture carries tags, so an empty vocabulary is a bug"
        assert got == _on_disk(root), (
            "the route disagrees with the passports on disk")
        assert payload["returned"] == len(payload["tags"])
        assert payload["total"] == len(got)
        assert payload["truncated"] is False

    def test_the_listing_is_ordered_by_count_then_name(self, station):
        client, registry, _ = station
        headers = _key(registry, caps=("read",))
        entries = _tags(client, headers)["tags"]
        keys = [(-e["nodes"], e["tag"]) for e in entries]
        assert keys == sorted(keys), entries

    def test_changing_the_page_size_does_not_change_a_count(self, station):
        """F.168's own sentence, and J.4.3's reason for it: a total computed
        from what is on screen moves when somebody changes the page size,
        which makes it a number about the console rather than the forest."""
        client, registry, _ = station
        headers = _key(registry, caps=("read",))

        whole = _tags(client, headers)
        assert len(whole["tags"]) > 3, "the fixture is too small to cut"

        for limit in (1, 2, 3):
            page = _tags(client, headers, limit=limit)
            assert page["returned"] == limit
            assert page["truncated"] is True
            # The cap cut the LISTING. Every count in it, the vocabulary's
            # size, and the order are the whole scope's.
            assert page["tags"] == whole["tags"][:limit]
            assert page["total"] == whole["total"]
            assert page["cap"] == limit

    def test_a_clipped_vocabulary_says_so_and_says_how_much(self, station):
        """C.6.2's pattern: never in silence. The flag AND the size of what
        was not received, or a truncated list reads as a complete one."""
        client, registry, _ = station
        headers = _key(registry, caps=("read",))

        page = _tags(client, headers, limit=2)
        assert page["truncated"] is True
        assert page["total"] > page["returned"]
        assert _tags(client, headers)["truncated"] is False

    def test_a_tag_keeps_its_spelling_in_the_vocabulary(self, station):
        """G.4.2 rule 2: diacritics are NOT stripped. `nodes_fts` is
        tokenized `remove_diacritics 2`, so a vocabulary read off the FTS
        row would report `producao` for a passport that says `produção` —
        which is the exact spelling the rule exists to keep."""
        client, registry, _ = station
        headers = _key(registry)

        current = _look_tags(client, headers, NODE)
        r = _graft_tags(client, headers, NODE, [*current, "produção"])
        assert r.status_code == 200, r.text

        got = {e["tag"]: e["nodes"] for e in _tags(client, headers)["tags"]}
        assert "produção" in got and got["produção"] == 1
        assert "producao" not in got

    def test_the_count_is_nodes_and_not_occurrences(self, station):
        """`count(DISTINCT nodes.id)`: a passport that somehow carried one
        tag twice is one node carrying it, and a vocabulary that said 2
        would be counting rows rather than material."""
        client, registry, root = station
        headers = _key(registry, caps=("read",))
        before = {e["tag"]: e["nodes"] for e in _tags(client, headers)["tags"]}
        dropped = _look_tags(client, headers, NODE)

        _write_tags_behind_the_engine(client, registry, root, NODE,
                                      ["twice", "twice"])

        after = {e["tag"]: e["nodes"] for e in _tags(client, headers)["tags"]}
        assert after["twice"] == 1, after
        # And nothing else invented a count: the node's own former tags each
        # lost exactly the one node that stopped carrying them.
        expected = dict(before)
        for tag in dropped:
            expected[tag] -= 1
            if not expected[tag]:
                del expected[tag]
        assert {k: v for k, v in after.items() if k != "twice"} == expected


class TestScope:
    """J.3 / C.13.3's rule, applied to a vocabulary: a global count here
    would name and size a region nobody granted — the tag names themselves
    are the leak, before the numbers are."""

    def test_a_scoped_principal_is_counted_inside_their_own_region(self, station):
        client, registry, root = station
        whole = _key(registry, caps=("read",), principal="wide")
        narrow = _key(registry, caps=("read",), principal="narrow",
                      allow=["projects/"])

        everything = {e["tag"]: e["nodes"] for e in _tags(client, whole)["tags"]}
        region = {e["tag"]: e["nodes"] for e in _tags(client, narrow)["tags"]}

        assert region == _on_disk(root, prefix="projects/")
        assert region != everything, "the fixture must differ across the scope"
        assert set(region) < set(everything)
        # The counts are the region's, not the forest's trimmed to it.
        assert any(region[tag] < everything[tag] for tag in region), region

    def test_a_tag_that_lives_only_outside_the_scope_is_absent(self, station):
        client, registry, root = station
        narrow = _key(registry, caps=("read",), principal="narrow",
                      allow=["projects/"])
        outside = set(_on_disk(root)) - set(_on_disk(root, prefix="projects/"))
        assert outside, "the fixture must have tags outside projects/"
        got = {e["tag"] for e in _tags(client, narrow)["tags"]}
        assert not (got & outside)

    def test_the_scoped_count_is_not_a_page_of_the_global_one(self, station):
        """The failure mode this rule names: counting globally and trimming
        afterwards. It is invisible in the listing and visible in a number,
        so the number is what is compared."""
        client, registry, root = station
        narrow = _key(registry, caps=("read",), principal="narrow",
                      allow=["concepts/"])
        region = {e["tag"]: e["nodes"] for e in _tags(client, narrow)["tags"]}
        assert region == _on_disk(root, prefix="concepts/")


class TestSurface:
    def test_an_unknown_query_parameter_is_refused(self, station):
        client, registry, _ = station
        headers = _key(registry, caps=("read",))
        r = client.get(f"/v1/forests/{FOREST}/tags", headers=headers,
                       params={"scope": "projects/_index"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "E_SCHEMA"
        assert "scope" in r.json()["error"]["message"]

    def test_a_limit_that_is_not_a_number_is_refused(self, station):
        client, registry, _ = station
        headers = _key(registry, caps=("read",))
        r = client.get(f"/v1/forests/{FOREST}/tags", headers=headers,
                       params={"limit": "all"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "E_SCHEMA"

    def test_it_rides_the_read_capability(self, station):
        client, registry, _ = station
        headers = _key(registry, caps=("write",), principal="writer")
        r = client.get(f"/v1/forests/{FOREST}/tags", headers=headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "E_FORBIDDEN"

    def test_a_forest_the_key_cannot_reach_answers_as_unknown(self, station):
        client, registry, _ = station
        headers = _key(registry, caps=("read",))
        r = client.get("/v1/forests/nowhere/tags", headers=headers)
        assert r.status_code == 404

    def test_a_read_only_station_serves_it(self, readonly_station):
        """Browsing a vocabulary is reading, so the Station that may not
        commit still answers — the same rule `reindex` and the J.18 review
        listing are held to."""
        client, registry, _ = readonly_station
        headers = _key(registry, caps=("read",))
        assert _tags(client, headers)["tags"]

    def test_the_route_is_not_registered_behind_the_map_catch_all(self, station):
        """`GET /v1/forests/{f}/{kind}` would read `tags` as a map
        projection and refuse it as one, so the ordering is the feature."""
        client, registry, _ = station
        headers = _key(registry, caps=("read",))
        r = client.get(f"/v1/forests/{FOREST}/tags", headers=headers)
        assert r.status_code == 200
        assert "no such endpoint" not in r.text

    def test_there_is_no_agent_facing_tags_tool(self, station):
        """A console surface, not a primitive: an agent already has `locate`
        (which ranks tags) and `scan` (which filters on them), and a tool
        description is charged to every client in every session."""
        client, registry, _ = station
        headers = _key(registry, caps=("read", "write", "admin", "ingest",
                                       "query", "tend"), principal="agent")
        client.post("/mcp/", headers={**MCP_HEADERS, **headers},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}}})
        r = client.post("/mcp/", headers={**MCP_HEADERS, **headers},
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert len(names) >= 16, "the tool list did not load, so this is vacuous"
        assert "tags" not in names, names

        # And it is not a primitive either: the POST path is the primitive
        # catch-all, and nothing there answers to this name.
        r = client.post(f"/v1/forests/{FOREST}/tags", headers=headers, json={})
        assert r.status_code >= 400, r.text


# -- F.168: adding is not replacing ------------------------------------------


def _bulk(client, headers, ids, wanted, mode="apply"):
    """The console's own sequence, run against the real engine (J.5.18
    rules 2 and 3): read each node's tags, MERGE, graft the merged list.

    Deliberately not a helper that writes what it was given: the whole rule
    is that the typed set never reaches a passport on its own, so the test
    has to perform the merge the console performs.
    """
    from monkeyllm.models import tag_key

    report = {"changed": 0, "unchanged": 0, "failures": []}
    for node_id in ids:
        r = client.post(f"/v1/forests/{FOREST}/look", headers=headers,
                        json={"id": node_id, "fields": ["tags"]})
        if r.status_code != 200:
            report["failures"].append((node_id, r.json()["error"]))
            continue
        current = r.json()["tags"]
        keys = {tag_key(t) for t in current}
        if mode == "apply":
            merged = [*current, *(t for t in wanted if tag_key(t) not in keys)]
        else:
            gone = {tag_key(t) for t in wanted}
            merged = [t for t in current if tag_key(t) not in gone]
        if merged == current:
            report["unchanged"] += 1
            continue
        w = _graft_tags(client, headers, node_id, merged)
        if w.status_code != 200:
            report["failures"].append((node_id, w.json()["error"]))
        else:
            report["changed"] += 1
    return report


class TestMerge:
    def test_a_bulk_apply_unions_and_leaves_what_was_there(self, station):
        client, registry, _ = station
        headers = _key(registry)
        before = {n: _look_tags(client, headers, n) for n in (NODE, OTHER)}
        assert all(before.values()), "both nodes must start with tags"

        report = _bulk(client, headers, [NODE, OTHER], ["invoice"])
        assert report == {"changed": 2, "unchanged": 0, "failures": []}

        for node_id, was in before.items():
            now = _look_tags(client, headers, node_id)
            assert now == [*was, "invoice"], (node_id, was, now)

    def test_applying_twice_is_applying_once(self, station):
        client, registry, _ = station
        headers = _key(registry)
        _bulk(client, headers, [NODE], ["invoice"])
        after_one = _look_tags(client, headers, NODE)

        report = _bulk(client, headers, [NODE], ["invoice"])
        # Nothing to write: a node that already carries the tag must not be
        # given a commit that changes none of its bytes.
        assert report == {"changed": 0, "unchanged": 1, "failures": []}
        assert _look_tags(client, headers, NODE) == after_one

    def test_a_case_variant_is_the_same_tag(self, station):
        """G.4.2 rule 2 decides uniqueness under NFC + case folding, and the
        console's merge asks the same question — so an apply of `Invoice`
        over a node carrying `invoice` writes nothing and does not create a
        second spelling of one tag."""
        client, registry, _ = station
        headers = _key(registry)
        _bulk(client, headers, [NODE], ["invoice"])
        report = _bulk(client, headers, [NODE], ["Invoice"])
        assert report["changed"] == 0 and report["unchanged"] == 1
        assert _look_tags(client, headers, NODE).count("invoice") == 1
        assert "Invoice" not in _look_tags(client, headers, NODE)

    def test_a_bulk_remove_subtracts_only_what_was_named(self, station):
        client, registry, _ = station
        headers = _key(registry)
        before = _look_tags(client, headers, NODE)
        _bulk(client, headers, [NODE], ["invoice"])

        report = _bulk(client, headers, [NODE], ["invoice"], mode="remove")
        assert report["changed"] == 1 and not report["failures"]
        assert _look_tags(client, headers, NODE) == before

    def test_a_remove_of_something_absent_writes_nothing(self, station):
        client, registry, _ = station
        headers = _key(registry)
        before = _look_tags(client, headers, NODE)
        report = _bulk(client, headers, [NODE], ["nothing-here"], mode="remove")
        assert report == {"changed": 0, "unchanged": 1, "failures": []}
        assert _look_tags(client, headers, NODE) == before

    def test_the_vocabulary_follows_the_bulk_write(self, station):
        """The two halves agree: what the bulk wrote is what the counted
        vocabulary reports, with no reindex in between."""
        client, registry, _ = station
        headers = _key(registry)
        _bulk(client, headers, [NODE, OTHER], ["invoice"])
        got = {e["tag"]: e["nodes"] for e in _tags(client, headers)["tags"]}
        assert got["invoice"] == 2


# -- F.168: a typed tag is validated, and the refusal names it ---------------


class TestRefusal:
    @pytest.mark.parametrize("tag,why", [
        ("rate limit", "whitespace"),
        ("-leading", "must start with a letter or a digit"),
        ("x" * 41, "characters"),
    ])
    def test_an_invalid_tag_is_refused_naming_it(self, station, tag, why):
        client, registry, _ = station
        headers = _key(registry)
        before = _look_tags(client, headers, NODE)

        r = _graft_tags(client, headers, NODE, [*before, tag])
        assert r.status_code == 400, r.text
        error = r.json()["error"]
        assert error["code"] == "E_FRONTMATTER"
        # G.4.2 rule 2 / J.5.18 rule 5: the refusal names the TAG, so a
        # console can render it instead of rewriting it into something
        # acceptable.
        assert tag in error["message"], error
        assert why in error["message"], error
        assert error.get("hint"), "the rule itself must ride the refusal"
        assert _look_tags(client, headers, NODE) == before

    def test_a_nodes_own_tags_go_back_untouched(self, station):
        """G.4.2 rule 6's grandfathering is what makes read-then-merge safe:
        a bulk apply re-sends every tag the node already carried, and a node
        ingested before v0.75 may carry one the rule would now refuse. If
        that were refused, the console could not tag such a node at all."""
        client, registry, root = station
        headers = _key(registry)

        _write_tags_behind_the_engine(
            client, registry, root, NODE,
            [*_look_tags(client, headers, NODE), "legacy tag"])

        current = _look_tags(client, headers, NODE)
        assert "legacy tag" in current
        report = _bulk(client, headers, [NODE], ["invoice"])
        assert report == {"changed": 1, "unchanged": 0, "failures": []}
        now = _look_tags(client, headers, NODE)
        assert "legacy tag" in now and "invoice" in now


class TestPartialRun:
    """Rule 2's engine half. The console must report a node that refused and
    still complete the others; what makes that possible is that each graft
    is its own commit, so a refusal in the middle leaves everything before
    and after it written."""

    def test_one_refusal_leaves_the_others_committed(self, station):
        client, registry, _ = station
        headers = _key(registry)
        missing = "concepts/was-pruned-since-the-listing"

        report = _bulk(client, headers, [NODE, missing, OTHER], ["invoice"])
        assert report["changed"] == 2
        assert len(report["failures"]) == 1
        assert report["failures"][0][0] == missing
        assert report["failures"][0][1]["code"] == "E_NOT_FOUND"

        # The two that landed are committed; the run was not rolled back.
        assert "invoice" in _look_tags(client, headers, NODE)
        assert "invoice" in _look_tags(client, headers, OTHER)
        assert {e["tag"]: e["nodes"]
                for e in _tags(client, headers)["tags"]}["invoice"] == 2

    def test_each_node_is_its_own_commit(self, station):
        client, registry, root = station
        headers = _key(registry)
        before = subprocess.run(
            ["git", "-C", str(root / FOREST), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        _bulk(client, headers, [NODE, OTHER], ["invoice"])
        after = subprocess.run(
            ["git", "-C", str(root / FOREST), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert int(after) - int(before) == 2, (before, after)


# -- F.168: the console's own clauses ---------------------------------------


class TestConsole:
    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_the_tag_console_meets_its_criteria(self):
        r = subprocess.run(["node", str(STUDIO / "check-tags.mjs")],
                           capture_output=True, text=True, cwd=STUDIO)
        assert r.returncode == 0, r.stdout + r.stderr
        # Every criterion reported, not just the ones that happened to run:
        # a checker that exits 0 because it stopped early is a passing test
        # about nothing.
        assert r.stdout.count("PASS") >= 45, r.stdout

    def test_the_scent_is_editable_from_the_read_console(self):
        """J.5.18 rule 1, on the wiring rather than on the component — the
        cheap half, so it runs where node does not exist. Reuse is the
        claim: Read mounts the editor module's own component rather than a
        second copy of the same three fields."""
        text = (STUDIO / "src" / "views" / "Read.jsx").read_text(encoding="utf-8")
        assert "ScentEditor" in text
        assert "from './editor.jsx'" in text

    def test_no_console_writes_the_typed_set_as_a_nodes_tags(self):
        """J.5.18 rule 3, as a whole-app grep: every `tags:` inside a
        `set_frontmatter` must be a merged list, never the parsed input.
        One careless action must not be able to erase curation across a
        selection."""
        src = STUDIO / "src"
        offenders = [
            f"{path.relative_to(src)}:{n}"
            for path in src.rglob("*.jsx")
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "set_frontmatter" in line and "tags:" in line
            and "tags: next" not in line
        ]
        assert not offenders, offenders

    def test_the_vocabulary_is_read_from_the_documented_route(self):
        """J.5 stands: the console gains no aggregate of its own. It asks
        the same GET any API client with that key could ask."""
        api = (STUDIO / "src" / "api.js").read_text(encoding="utf-8")
        assert "/tags" in api
        view = (STUDIO / "src" / "views" / "tags.jsx").read_text(encoding="utf-8")
        assert "api.tags(forest)" in view

    def test_the_webhook_sample_matches_what_the_host_sends(self):
        """A leftover from J.13.6.1: the scent re-curation emits `fallbacks`
        and `job` beside the two counts, and the console's preview of
        `recurate.finished` still showed the aliases pass's older shape. A
        preview that is not the real shape is worse than no preview."""
        app = (STATION / "monkeyllm_station" / "app.py").read_text(encoding="utf-8")
        block = app[app.index('hooks.emit(prep.forest, "recurate.finished"'):]
        emitted = set()
        for field in ("scanned", "changed", "fallbacks", "derive", "job"):
            if f'"{field}"' in block[:400]:
                emitted.add(field)
        assert emitted == {"scanned", "changed", "fallbacks", "derive", "job"}

        console = (STUDIO / "src" / "views" / "Webhooks.jsx").read_text(encoding="utf-8")
        line = next(x for x in console.splitlines()
                    if "'recurate.finished':" in x)
        for field in emitted:
            assert f"{field}:" in line, (field, line)


def test_the_route_is_registered_before_the_map_catch_all():
    """Ordering as source, not as behaviour: Starlette matches in order and
    `{kind:str}` is a single segment, so a `/tags` registered after it would
    be answered as a map projection that does not exist. The behavioural
    half is `TestSurface`; this is the rule (J.13.6)."""
    app = (STATION / "monkeyllm_station" / "app.py").read_text(encoding="utf-8")
    tags_at = app.index('Route("/v1/forests/{forest}/tags"')
    catch_at = app.index('Route("/v1/forests/{forest}/{kind:str}"')
    assert tags_at < catch_at


def test_the_engine_never_counts_tags_off_the_fts_row():
    """G.4.2 rule 2's consequence, pinned at the source: `nodes_fts` is
    tokenized `unicode61 remove_diacritics 2`, so a vocabulary read there
    would report `producao` for a passport that says `produção`."""
    from monkeyllm import catalog

    text = Path(catalog.__file__).read_text(encoding="utf-8")
    body = text[text.index("def tag_counts"):text.index("def subtree_stats")]
    # The statement, not the prose: the docstring names `nodes_fts` because
    # explaining why it is not read is the whole point of the comment.
    sql = "\n".join(line for line in body.splitlines()
                    if "nodes_fts" in line and "FROM" in line)
    assert not sql, sql
    assert "json_each" in body and "count(DISTINCT nodes.id)" in body
    assert "nodes.tags" in body
