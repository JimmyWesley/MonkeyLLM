# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The reading surface tells the scent from the document (spec J.5.4 /
J.14 / J.14.1).

An operator opened a PDF an extension had ingested and read the passport's
`summary` as the model's summary of it. He was reading the right field and
the wrong thing: a summary is the SCENT — 60 tokens of curated metadata,
the only text `locate` searches (C.6b) — and the document was underneath it,
whole, as the body. He then copied that body out of the rich editor, which
round-trips markdown through HTML, and got one flattened paragraph with
`\\_` inside every identifier, plus a `replace_body` nobody had typed sitting
in the pending patch. Nothing was committed and nothing in the engine was
wrong: every surface simply failed to say which of the three layers it was
showing, and the one surface that rewrites bytes never checked whether it
could give them back.

Studio has no test runner, so this follows `tests/test_v076_window.py`: the
criteria live in `apps/studio/check-reading.mjs`, next to the code they
describe, and are run from here so they cannot quietly stop being true.

The boundary is F.137's, with one deliberate exception. The round trip is a
pure function of a body, it lives in `apps/studio/src/roundtrip.js` with no
React in it, and it is the rule that failed — so the checker RUNS it against
real bodies (the PDF shape included) instead of asserting that a string is
present. Everything else — a rendered panel, a clipboard, a download — wants
a browser and is read off the decision layer in the source.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
CHECKER = STUDIO / "check-reading.mjs"
LANGS = ("en", "pt", "es")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_reading_surface_meets_its_criteria():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run: a
    # checker that exits 0 because it stopped early is a passing test about
    # nothing.
    assert r.stdout.count("PASS") >= 30, r.stdout


def _files_locale(lang: str) -> dict:
    path = STUDIO / "src" / "locales" / "files" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_three_layers_are_named_in_every_language():
    """The cheap half, needing no toolchain: scent, body and original are
    three labels in three languages, and the scent's label carries its own
    budget — a token count with no maximum beside it is a number nobody can
    read."""
    for lang in LANGS:
        d = _files_locale(lang)
        for key in ("files.scent", "files.scent_hint", "files.body_label",
                    "files.body_line", "files.original",
                    "files.original_missing", "files.copy_markdown"):
            assert d.get(key), f"{lang} is missing {key}"
        assert "{n}" in d["files.scent"] and "{max}" in d["files.scent"], lang
        assert "{sections}" in d["files.body_line"], lang
        assert "{tokens}" in d["files.body_line"], lang


def test_the_lock_hint_no_longer_names_only_tables():
    """J.5.4's rich lock used to be two shapes, so its hint named them. The
    criterion is mechanical now — the round trip is run and compared — and a
    hint that still says "tables or raw HTML" would send an operator looking
    for a table in a body that has none."""
    for lang in LANGS:
        path = STUDIO / "src" / "locales" / "editor" / f"{lang}.json"
        hint = json.loads(path.read_text(encoding="utf-8"))["editor.rich_locked"]
        assert hint
        assert not any(word in hint.lower() for word in ("table", "tabela", "tabla"))


def test_the_copy_reads_the_export_and_the_editor_reads_the_round_trip():
    """The two halves of the same rule, asserted without node: the clipboard
    is served by the J.14.1 export (the planted file verbatim) and never by
    the surface that re-serialises it, and the rich editor's admission is the
    round trip itself rather than a list of shapes."""
    files = (STUDIO / "src" / "views" / "files.jsx").read_text(encoding="utf-8")
    assert "api.exportNode(forest, id)" in files
    assert "<CopyExport forest={forest} id={file.id} />" in files

    roundtrip = (STUDIO / "src" / "roundtrip.js").read_text(encoding="utf-8")
    assert "normalised(toMarkdown(toHtml(md))) !== normalised(md)" in roundtrip
    editor = (STUDIO / "src" / "views" / "editor.jsx").read_text(encoding="utf-8")
    assert "const lossy = useMemo(() => richLossy(orig), [orig])" in editor
    assert "const start = lossy ? 'source' : 'rich'" in editor
    # The schema has to hold what a body carries: every node body in this
    # repository's own forests opens with `# <title>`, and a level outside
    # the configured list is dropped by ProseMirror — silently, as a
    # `replace_body` that demotes the title to a paragraph.
    assert "levels: HEADING_LEVELS" in editor
    assert "export const HEADING_LEVELS = [1, 2, 3, 4, 5, 6]" in roundtrip


def test_the_archive_is_hidden_from_the_tree_and_from_nothing_else():
    """`_assets/` is per-branch (G.5.1), so it is a directory name at any
    depth — and it is dropped from the LISTING alone: the catalog, the map
    projection and the J.14 route all still see it, which is what makes the
    passport's `Original · download` reach the same bytes."""
    files = (STUDIO / "src" / "views" / "files.jsx").read_text(encoding="utf-8")
    assert "const ASSETS_DIR = /(?:^|\\/)_assets\\//" in files
    assert "if (inAssets(path)) continue" in files
    assert "await api.payload(forest, d.id)" in files
