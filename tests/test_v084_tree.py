# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.2.8 — a document that becomes a branch (spec v0.84).

F.239-F.246. Everything here runs on a PRIVATE forest with a stub
tree-returning converter registered through the ordinary converter seam:
the shared fixture stays at 82 nodes (two suites assert that), and a stub is
also the only way to test the refusals — no built-in returns a tree, and the
engine never decides where a document divides.

The negative controls are what this file is for. A `markdown` conversion is
untouched (F.239); a forest declaring no `succeeds` gets the children and
says so rather than failing (F.242); every malformed tree plants NOTHING
while the rest of the batch lands (F.243); and `sync` never deletes a part
(F.245).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.forest import Forest, init_forest
from monkeyllm.gardener import (
    TREE_CHILDREN_MAX,
    Conversion,
    Gardener,
    demote_index_headings,
    validate_tree,
)
from monkeyllm.parser import extract_section
from monkeyllm.vine import Vine

CHAPTERS = [
    ("Opening the plant", "The Recife line started in March 2026."),
    ("Wiring the sensors", "Each cabinet carries nine sensors."),
    ("Commissioning", "The commissioning window closed in June."),
]


class TreeConverter:
    """A stub converter that answers with whatever tree the test wrote."""

    extensions = {".book"}

    def __init__(self):
        self.trees: dict[str, Conversion] = {}

    def teach(self, name: str, title: str, markdown: str, children) -> None:
        def as_child(item):
            if isinstance(item, dict):
                return dict(item)
            title_, body = item
            return {"title": title_, "markdown": body}

        self.trees[name] = Conversion(
            kind="tree", title=title, markdown=markdown,
            children=(None if children is None
                      else [as_child(c) for c in children]))

    def convert(self, path: Path) -> Conversion:
        return self.trees[path.name]


class PlainConverter:
    """The control: the same file extension, answering `markdown`."""

    extensions = {".book"}

    def convert(self, path: Path) -> Conversion:
        return Conversion(kind="markdown", title=path.stem,
                          markdown=f"# {path.stem}\n\nOne node, as before.\n")


def book(children=CHAPTERS, title="The Maracatu handbook",
         markdown="# The Maracatu handbook\n\nAn outline of the work.\n"):
    return {"title": title, "markdown": markdown, "children": children}


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Tree Forest")
    vine = Vine(root, writable=True)
    conv = TreeConverter()
    g = Gardener(vine, converters=[conv], hooks=[])
    src = tmp_path / "dump"
    src.mkdir()
    yield g, vine, root, src, conv
    vine.close()


def write_book(src: Path, conv: TreeConverter, name: str, **kw) -> Path:
    spec = book(**kw)
    conv.teach(f"{name}.book", spec["title"], spec["markdown"],
               spec["children"])
    f = src / f"{name}.book"
    f.write_text(f"binary-ish source for {name}\n", encoding="utf-8")
    return f


def subjects(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "log", "--format=%s"],
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


# ===========================================================================
# F.239 — a `markdown` conversion is untouched
# ===========================================================================

def test_a_markdown_conversion_is_byte_identical(tmp_path):
    """The same source, the same converter answering the old kind, twice —
    before and after this round is not reachable from here, so what is
    asserted is that the tree path is not on the way: one node, one id, one
    passport, and no branch anywhere."""
    root = tmp_path / "plain"
    init_forest(root, title="Plain")
    vine = Vine(root, writable=True)
    src = tmp_path / "dump"
    src.mkdir()
    (src / "report.book").write_text("bytes", encoding="utf-8")
    try:
        g = Gardener(vine, converters=[PlainConverter()], hooks=[])
        report = g.adopt(src)
        assert report["planted"] == ["report"]
        assert report["branches"] == []
        assert report["headings_demoted"] == 0
        assert report["sequence_skipped"] == []
        node = Forest(root).read("report")
        assert node.frontmatter["type"] == "document"
        assert "source_part" not in node.frontmatter
        assert not Forest(root).exists("report/_index")
    finally:
        vine.close()


# ===========================================================================
# F.240 — a tree plants a branch and its children
# ===========================================================================

class TestTheTree:
    def test_twelve_children_plant_a_branch_and_twelve_nodes(self, garden):
        g, vine, root, src, conv = garden
        chapters = [(f"Chapter {i}", f"The body of chapter {i}, at length.")
                    for i in range(1, 13)]
        write_book(src, conv, "handbook", children=chapters)
        report = g.adopt(src)

        assert report["branches"] == ["handbook/_index"]
        assert len(report["planted"]) == 13
        forest = Forest(root)
        # Rule 4: three-digit padding, fixed — id order IS document order for
        # the life of the forest, because ids are immutable and a width that
        # grows would sort `1, 10, 2`.
        assert forest.exists("handbook/001-chapter-1")
        assert forest.exists("handbook/012-chapter-12")
        branch = forest.read("handbook/_index")
        assert branch.frontmatter["type"] == "branch"
        assert branch.frontmatter["source_path"] == "handbook.book"

        shared = branch.frontmatter["source_hash"]
        for n in range(1, 13):
            child = forest.read(f"handbook/{n:03d}-chapter-{n}")
            fm = child.frontmatter
            assert vine.catalog.get(child.id)["parent"] == "handbook/_index"
            assert fm["type"] == "document"
            assert fm["source_part"] == f"{n:03d}"
            assert fm["source_path"] == "handbook.book"
            assert fm["source_hash"] == shared
            assert fm["origin"] == branch.frontmatter["origin"]
            assert fm["origin"].startswith("file://")

        # Rule 5: the three A.5 sections still parse, with the document's own
        # front matter above them.
        for section in ("Sub-branches", "Direct bananas", "Cross trails"):
            assert extract_section(branch.body, section) is not None
        assert "An outline of the work." in branch.body
        digest = vine.look("handbook/_index")
        assert digest["coverage"] == {"notes": 12, "branches": 0}

        # `scan(after: "")` is the table of contents, in document order.
        listed = vine.scan("handbook/_index", after="")
        ids = [n["id"] for n in listed["nodes"]]
        while listed.get("next"):
            listed = vine.scan("handbook/_index", after=listed["next"])
            ids += [n["id"] for n in listed["nodes"]]
        assert ids == [f"handbook/{n:03d}-chapter-{n}" for n in range(1, 13)]

    def test_a_colliding_heading_is_demoted_counted_and_the_index_parses(
            self, garden):
        g, vine, root, src, conv = garden
        write_book(src, conv, "manual", markdown=(
            "# Manual\n\n## Sub-branches of the argument\n\nThe author's own "
            "section, which would have captured the index's entries.\n"))
        report = g.adopt(src)
        assert report["headings_demoted"] == 1
        branch = Forest(root).read("manual/_index")
        # The words are kept; the `##` is not.
        assert "**Sub-branches of the argument**" in branch.body
        assert "## Sub-branches of the argument" not in branch.body
        # …and the index's own section is the one the parser finds.
        section = extract_section(branch.body, "Sub-branches")
        assert section is not None and "the argument" not in section

    def test_the_branch_body_is_always_inline(self, garden):
        """A branch's body is the indexer's render; moving it to
        `_derived/` would leave the index unreadable by the one thing that
        maintains it. The children obey the policy."""
        g, vine, root, src, conv = garden
        g.config["content"] = "cached"
        write_book(src, conv, "cached-book")
        g.adopt(src)
        branch = Forest(root).read("cached-book/_index")
        assert branch.frontmatter.get("content") is None
        assert extract_section(branch.body, "Direct bananas") is not None
        child = Forest(root).read("cached-book/001-opening-the-plant")
        assert child.frontmatter["content"] == "cached"


# ===========================================================================
# F.241 — the sequence walks
# ===========================================================================

class TestTheSequence:
    def test_move_walks_the_document_both_ways(self, garden):
        g, vine, root, src, conv = garden
        write_book(src, conv, "handbook")
        g.adopt(src)
        first = "handbook/001-opening-the-plant"
        second = "handbook/002-wiring-the-sensors"
        third = "handbook/003-commissioning"

        forward = vine.move(first, rel="precedes", direction="in")
        assert [n["id"] for n in forward["neighbors"]] == [second]
        forward = vine.move(second, rel="precedes", direction="in")
        assert [n["id"] for n in forward["neighbors"]] == [third]
        back = vine.move(third, rel="succeeds")
        assert [n["id"] for n in back["neighbors"]] == [second]

    def test_a_sequence_link_is_never_in_the_managed_population(self, garden):
        from monkeyllm.links import is_managed, uncertain_links

        g, vine, root, src, conv = garden
        write_book(src, conv, "handbook")
        g.adopt(src)
        node = Forest(root).read("handbook/002-wiring-the-sensors")
        links = node.frontmatter["links"]
        assert links == [{"rel": "succeeds",
                          "target": "handbook/001-opening-the-plant"}]
        # H.2.1 rule 3: `None` is not `1.0` — a structural edge is OUTSIDE
        # the managed population rather than settled inside it.
        assert not any(is_managed(l) for l in links)
        assert uncertain_links(vine)["groups"] == []


# ===========================================================================
# F.242 — a forest that does not declare `succeeds`
# ===========================================================================

def test_no_succeeds_means_children_and_no_sequence(tmp_path):
    root = tmp_path / "old"
    init_forest(root, title="Pre-v0.58")
    # A forest whose `_meta/schema.md` predates v0.58 legitimately declares
    # nine rels. The runtime authority is the FILE (A.2).
    schema = root / "_meta" / "schema.md"
    text = schema.read_text(encoding="utf-8")
    text = "\n".join(l for l in text.splitlines()
                     if not l.strip().startswith("| `succeeds`"))
    schema.write_text(text, encoding="utf-8")

    vine = Vine(root, writable=True)
    src = tmp_path / "dump"
    src.mkdir()
    try:
        assert "succeeds" not in vine.forest.dialect.rels
        conv = TreeConverter()
        g = Gardener(vine, converters=[conv], hooks=[])
        write_book(src, conv, "handbook")
        report = g.adopt(src)
        assert report["errors"] == []
        assert report["sequence_skipped"] == ["handbook/_index"]
        assert len(report["planted"]) == 4
        for n, (title, _body) in enumerate(CHAPTERS, start=1):
            fm = Forest(root).read(
                f"handbook/{n:03d}-{title.lower().replace(' ', '-')}"
            ).frontmatter
            assert not fm.get("links")
    finally:
        vine.close()


# ===========================================================================
# F.243 — every malformed tree plants nothing, and the batch lands
# ===========================================================================

class TestRefusals:
    @pytest.mark.parametrize("children,why", [
        ([("Only", "One part")], "one child"),
        ([], "no children"),
        (None, "not a list"),
        ([("", "A body"), ("Two", "Another")], "empty title"),
        ([("One", ""), ("Two", "Another")], "empty body"),
    ])
    def test_a_bad_tree_plants_nothing_and_the_rest_lands(self, garden,
                                                          children, why):
        g, vine, root, src, conv = garden
        write_book(src, conv, "bad", children=children)
        write_book(src, conv, "good")
        report = g.adopt(src)
        assert any("bad.book" in e for e in report["errors"]), report["errors"]
        forest = Forest(root)
        assert not forest.exists("bad/_index")
        assert not any(i.startswith("bad/") for i in forest.iter_ids())
        # …and the rest of the batch is planted.
        assert forest.exists("good/_index")
        assert forest.exists("good/001-opening-the-plant")

    def test_over_the_ceiling_is_refused(self, garden):
        g, vine, root, src, conv = garden
        too_many = [(f"Part {i}", f"Body {i}")
                    for i in range(TREE_CHILDREN_MAX + 1)]
        write_book(src, conv, "huge", children=too_many)
        report = g.adopt(src)
        assert any("huge.book" in e for e in report["errors"])
        assert not Forest(root).exists("huge/_index")

    def test_the_validator_names_what_is_wrong(self):
        assert validate_tree(Conversion(kind="tree", title="t",
                                        children=[{"title": "a",
                                                   "markdown": "b"},
                                                  {"title": "c",
                                                   "markdown": "d"}])) is None
        assert "at least two" in validate_tree(
            Conversion(kind="tree", title="t",
                       children=[{"title": "a", "markdown": "b"}]))
        assert "list" in validate_tree(Conversion(kind="tree", title="t"))

    def test_a_caller_cannot_claim_to_be_part_of_a_document(self, garden):
        g, vine, root, src, conv = garden
        with pytest.raises(VineError) as e:
            vine.plant({"id": "forged", "type": "note", "parent": "_index",
                        "title": "Forged", "summary": "A node claiming to be "
                        "part of a document nobody converted.",
                        "source_part": "007"})
        assert e.value.code == E_SCHEMA
        assert "source_part is written by ingest" in e.value.message

    def test_an_integer_part_is_refused_never_coerced(self):
        from monkeyllm.models import validate_source_part

        # YAML 1.1 reads an unquoted 012 as 10, so a hand-edited passport can
        # renumber a chapter with no edit visible in the diff.
        with pytest.raises(VineError) as e:
            validate_source_part(10)
        assert "STRING of digits" in e.value.message
        assert validate_source_part("012") == "012"


# ===========================================================================
# F.244 — a tree larger than a batch, and an abandoned run
# ===========================================================================

class TestBatches:
    def test_twenty_five_children_land_in_order_and_complete(self, garden):
        g, vine, root, src, conv = garden
        chapters = [(f"Part {i:02d}", f"The body of part {i}.")
                    for i in range(1, 26)]
        write_book(src, conv, "long", children=chapters)
        report = g.adopt(src)
        assert len(report["planted"]) == 26
        planted = [s for s in subjects(root) if s.startswith("plant(")]
        assert len(planted) >= 2, planted
        forest = Forest(root)
        for i in range(1, 26):
            assert forest.exists(f"long/{i:03d}-part-{i:02d}")

    def test_an_abandoned_run_is_finished_by_sync(self, garden):
        g, vine, root, src, conv = garden
        chapters = [(f"Part {i:02d}", f"The body of part {i}.")
                    for i in range(1, 26)]
        write_book(src, conv, "long", children=chapters)
        steps = g.adopt_iter(src)
        for _ in steps:
            break          # the consumer stops mid-document (J.9's cancel)
        forest = Forest(root)
        assert forest.exists("long/_index"), "the branch is planted first"
        present = sorted(i for i in forest.iter_ids() if i.startswith("long/"))
        assert len(present) < 26

        report = g.sync(src)
        forest = Forest(root)
        after = sorted(i for i in forest.iter_ids() if i.startswith("long/"))
        assert len(after) == 26
        assert len(set(after)) == len(after), "no id duplicated"
        # The sequence is complete over the parts that exist.
        last = forest.read("long/025-part-25").frontmatter["links"]
        assert last == [{"rel": "succeeds", "target": "long/024-part-24"}]


# ===========================================================================
# F.245 — `sync` reconciles by part and deletes nothing
# ===========================================================================

class TestRefresh:
    def _adopted(self, garden):
        g, vine, root, src, conv = garden
        f = write_book(src, conv, "handbook")
        g.adopt(src)
        return g, vine, root, src, conv, f

    def test_an_edited_part_refreshes_in_place(self, garden):
        g, vine, root, src, conv, f = self._adopted(garden)
        node_id = "handbook/002-wiring-the-sensors"
        # Somebody curated this part by hand.
        vine.graft(node_id, {"set_frontmatter": {
            "summary": "A curated scent a refresh must not overwrite.",
            "tags": ["sensors"]}})
        conv.teach("handbook.book", "The Maracatu handbook",
                   "# The Maracatu handbook\n\nAn outline of the work.\n",
                   [{"title": t, "markdown": (b if t != "Wiring the sensors"
                                              else "Rewritten body entirely.")}
                    for t, b in CHAPTERS])
        f.write_text("changed bytes\n", encoding="utf-8")

        report = g.sync(src)
        node = Forest(root).read(node_id)
        assert node_id in report["updated"]
        assert "Rewritten body entirely." in node.body
        # A refresh never curates (G.3): the scent somebody approved stays,
        # and so does the title, because the id carries the old slug and ids
        # are immutable.
        assert node.frontmatter["summary"].startswith("A curated scent")
        assert node.frontmatter["tags"] == ["sensors"]
        assert node.frontmatter["title"] == "Wiring the sensors"
        assert node.frontmatter["source_part"] == "002"

    def test_an_added_part_plants_and_joins_the_sequence(self, garden):
        g, vine, root, src, conv, f = self._adopted(garden)
        conv.teach("handbook.book", "The Maracatu handbook",
                   "# The Maracatu handbook\n\nAn outline of the work.\n",
                   [{"title": t, "markdown": b} for t, b in CHAPTERS]
                   + [{"title": "Handover", "markdown": "The handover notes."}])
        f.write_text("changed bytes\n", encoding="utf-8")
        g.sync(src)
        added = Forest(root).read("handbook/004-handover")
        assert added.frontmatter["source_part"] == "004"
        assert added.frontmatter["links"] == [
            {"rel": "succeeds", "target": "handbook/003-commissioning"}]

    def test_a_removed_part_is_stale_and_still_readable(self, garden):
        g, vine, root, src, conv, f = self._adopted(garden)
        conv.teach("handbook.book", "The Maracatu handbook",
                   "# The Maracatu handbook\n\nAn outline of the work.\n",
                   [{"title": t, "markdown": b} for t, b in CHAPTERS[:2]])
        f.write_text("changed bytes\n", encoding="utf-8")
        report = g.sync(src)
        assert "handbook/003-commissioning" in report["stale"]
        # The Gardener never deletes nodes (G.3).
        assert Forest(root).exists("handbook/003-commissioning")
        assert vine.look("handbook/003-commissioning")["id"] == \
            "handbook/003-commissioning"

    def test_a_rewritten_sequence_goes_through_the_audited_path(self, garden):
        g, vine, root, src, conv, f = self._adopted(garden)
        # The source lost its middle part, so what follows it must now
        # succeed what precedes it.
        conv.teach("handbook.book", "The Maracatu handbook",
                   "# The Maracatu handbook\n\nAn outline of the work.\n",
                   [{"title": CHAPTERS[0][0], "markdown": CHAPTERS[0][1]},
                    {"title": CHAPTERS[2][0], "markdown": CHAPTERS[2][1]}])
        f.write_text("changed bytes\n", encoding="utf-8")
        report = g.sync(src)
        second = Forest(root).read("handbook/002-wiring-the-sensors")
        # Part 002's body is now Commissioning's text — the identity is
        # (source_path, source_part), never the title: a converter that
        # renamed a chapter must not renumber the forest.
        assert "commissioning window" in second.body
        assert second.frontmatter["title"] == "Wiring the sensors"
        assert "handbook/003-commissioning" in report["stale"]
        # …and the part the source lost keeps its own edges: it is no longer
        # part of the document, and they are the record of where it sat.
        assert Forest(root).exists("handbook/003-commissioning")

    def test_the_sequence_rewrite_is_read_back_by_history(self, garden):
        g, vine, root, src, conv, f = self._adopted(garden)
        node_id = "handbook/002-wiring-the-sensors"
        # Remove its predecessor's link by hand, then let a refresh restore
        # the sequence through the audited write.
        from monkeyllm.links import rewrite_link

        node = Forest(root).read(node_id)
        rewrite_link(vine, node_id, node.frontmatter["links"][0], remove=True,
                     by="gardener")
        f.write_text("changed bytes\n", encoding="utf-8")
        g.sync(src)
        restored = Forest(root).read(node_id)
        assert restored.frontmatter["links"] == [
            {"rel": "succeeds", "target": "handbook/001-opening-the-plant"}]
        past = vine.history(node_id)
        messages = [e["message"] for e in past["entries"]]
        assert any(m.startswith("gardener(sequence):") for m in messages), messages
        assert all(e["action"] == "gardener" for e in past["entries"]
                   if e["message"].startswith("gardener(sequence):"))


# ===========================================================================
# F.246 — reading it whole
# ===========================================================================

class TestReadingItWhole:
    def test_sniff_names_the_part_and_does_not_rank_the_branch_above_it(
            self, garden):
        g, vine, root, src, conv = garden
        write_book(src, conv, "handbook")
        g.adopt(src)
        hits = vine.sniff(["commissioning"], scope="handbook/_index")
        ids = [h["id"] for h in hits["results"]]
        assert "handbook/003-commissioning" in ids
        # C.6b: an index node ranks below every content node in the same set.
        if "handbook/_index" in ids:
            assert ids.index("handbook/_index") > ids.index(
                "handbook/003-commissioning")

    def test_derived_aliases_sit_on_the_branch_and_on_no_child(self, garden):
        g, vine, root, src, conv = garden
        write_book(src, conv, "be-291-handbook", title="BE-291 handbook")
        g.adopt(src)
        branch = Forest(root).read("be-291-handbook/_index").frontmatter
        assert branch.get("aliases"), "the document's own code names the book"
        for n, (title, _body) in enumerate(CHAPTERS, start=1):
            child = Forest(root).read(
                f"be-291-handbook/{n:03d}-{title.lower().replace(' ', '-')}")
            # Copying the document's code onto every chapter would make
            # `locate("BE-291")` answer with N results of equal weight.
            assert not [a for a in (child.frontmatter.get("aliases") or [])
                        if "291" in str(a)]

    def test_export_reads_the_chapters_in_order(self, garden):
        g, vine, root, src, conv = garden
        write_book(src, conv, "handbook")
        g.adopt(src)
        ids = sorted(i for i in Forest(root).iter_ids()
                     if i.startswith("handbook/") and not i.endswith("_index"))
        assert ids == ["handbook/001-opening-the-plant",
                       "handbook/002-wiring-the-sensors",
                       "handbook/003-commissioning"]
        for node_id in ids:
            assert vine.export(node_id).startswith("---")


# ===========================================================================
# The demotion helper, on its own
# ===========================================================================

def test_demotion_matches_the_parser_prefix_rule():
    body, n = demote_index_headings(
        "# B\n\n### direct bananas and other fruit\n\ntext\n")
    assert n == 1
    assert "**direct bananas and other fruit**" in body
    assert extract_section(body, "Direct bananas") is None
    assert demote_index_headings("# B\n\n## Chapters\n")[1] == 0
