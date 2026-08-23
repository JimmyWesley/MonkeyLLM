# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.62 — the cold scan was never the corpus (F.129 - F.131).

The memo of C.6b.1 made a repeated `sniff` proportional to its matches and
left the first one — a term the forest has never been asked for — paying a
full scan. That cost was assumed to be the corpus and was deferred until it
could be measured. Measured, two thirds of it was not the corpus at all: the
fold was a Python loop over every character of every body, and the marker
that decides whether a body is inline was a MULTILINE regex over whole files
to find a line that can only exist in the frontmatter.

Both are cost rules under C.6b.1's first rule — the answer stays
byte-identical — so what these criteria pin is the identity, not a clock.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unicodedata

import pytest

from monkeyllm.vine import _FOLD_LIMIT, _fold


def reference_fold(text: str) -> str:
    """The fold as C.6b defines it, one character at a time."""
    return "".join(unicodedata.normalize("NFD", ch)[0].lower() for ch in text)


# --- F.129: the fold is a table, and the table is its definition -----------

class TestFoldIsItsDefinition:
    @pytest.mark.parametrize("text", [
        "MonkeyLLM", "Relatório de Latência", "ÁÉÎÕÜ Çedilha ñ", "straße",
        "ΣΊΣΥΦΟΣ", "ЖУРНАЛ", "日本語のノート",
        "\U00010400\U0001E921",              # Deseret, Adlam — cased, astral
        "\U0002F800",                        # CJK compatibility, decomposes
        "emoji \U0001F600 and \U000E0041",   # above the table, folds to itself
        "", "---\nid: x\n---\n",
    ])
    def test_matches_the_per_character_definition(self, text):
        assert _fold(text) == reference_fold(text)

    def test_length_is_preserved(self):
        """C.6b reports a position into the ORIGINAL line, so a fold that
        changed a string's length would move every snippet window."""
        for text in ("Latência", "\U0002F800\U00010400", "ß İ ﬁ", "AaÀà", ""):
            assert len(_fold(text)) == len(text)

    def test_the_table_limit_covers_every_folding_code_point(self):
        """`str.translate` leaves a code point beyond the table alone, so
        nothing beyond it may fold to anything but itself. Asked in bulk —
        two C-level passes — rather than a million times, and asked against
        the Unicode version in use so a later one cannot move the line in
        silence."""
        above = "".join(chr(o) for o in range(_FOLD_LIMIT, 0x110000)
                        if not 0xD800 <= o <= 0xDFFF)
        assert above.lower() == above, "a cased code point above the table"
        assert unicodedata.normalize("NFD", above) == above, \
            "a decomposable code point above the table"

    def test_the_fold_survives_a_round_trip_through_sniff(self, vine_ro):
        """The fold is not a private helper: it decides what `sniff`
        matches, in both spellings of the same word."""
        for term in ("MIXER-LANG", "mixer-lang"):
            assert vine_ro.sniff([term])["results"]


# --- F.130: the content marker is frontmatter ------------------------------

def test_a_marker_in_the_body_does_not_make_a_node_foreign(tmp_path):
    """G.7's marker says where a node's FLESH lives, and it is frontmatter.
    Searching whole files for it was a scan of the corpus to answer a
    question about its first few lines — and it also read a body that merely
    quotes the marker as a node whose body lives somewhere else."""
    from conftest import build_forest

    from monkeyllm import Vine

    root = build_forest(tmp_path / "forest")
    with Vine(root, writable=True) as v:
        v.plant({
            "id": "notes/tiered-storage-note",
            "parent": "notes/_index",
            "type": "note",
            "title": "Tiered storage, quoted",
            "summary": "A note that quotes the G.7 frontmatter marker.",
            "body": ("# Tiered storage\n\nA cached body is declared like "
                     "this:\n\ncontent: cached\n\nand the peculiar word "
                     "here is quetzalcoatl.\n"),
        })
        r = v.sniff(["quetzalcoatl"])
        assert [x["id"] for x in r["results"]] == ["notes/tiered-storage-note"]
        # Twice, because the first call is the one that fills the memo and
        # the second is the one that must agree with it.
        assert v.sniff(["quetzalcoatl"])["results"] == r["results"]


# --- F.131: a cold scan reads and folds each body once ---------------------

def test_a_cold_sniff_reads_and_folds_each_body_once(tmp_path, monkeypatch):
    from conftest import build_forest

    from monkeyllm import Vine
    from monkeyllm import vine as vine_mod

    root = build_forest(tmp_path / "forest")
    with Vine(root, writable=False) as v:
        folded: list[int] = []
        real_fold = vine_mod._fold
        monkeypatch.setattr(
            vine_mod, "_fold",
            lambda text: (folded.append(len(text)), real_fold(text))[1])
        r = v.sniff(["quetzalcoatl-absent-everywhere"])
        assert r["results"] == []
        # One fold for the term, then at most one per body scanned. The old
        # path folded each body twice — once to test the term, once to walk
        # the lines — and a per-character loop each time.
        assert len(folded) <= r["scanned_nodes"] + 1, len(folded)


def test_the_fold_table_is_built_on_first_use(tmp_path):
    """A `plant` or a `look` folds nothing, so neither may pay for the
    table. Asked in a fresh interpreter: the module-level state is global
    and any earlier test in this process would already have built it."""
    probe = textwrap.dedent("""
        import monkeyllm.vine as V
        assert V._FOLD_TABLE is None, "built at import"
        V._fold("an ordinary ascii title")
        assert V._FOLD_TABLE is None, "built for ASCII, which needs no table"
        V._fold("Relatório")
        assert V._FOLD_TABLE is not None, "never built"
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
