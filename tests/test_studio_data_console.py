# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""J.5.10 (spec v0.44): the Data console makes, imports, leaves and colours.

Read as source, for the reason `test_studio_calls` and `test_studio_i18n`
already give: the console is JavaScript, CI has no node, and the rules worth
guarding here are all visible in the text — which primitive a control calls,
which one it must NOT call, and whether a second rendering of the same
characters is hidden from a screen reader.
"""

from __future__ import annotations

import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
DATA = (STUDIO / "views" / "Data.jsx").read_text(encoding="utf-8")
UI = (STUDIO / "design" / "ui.jsx").read_text(encoding="utf-8")
CSS = (STUDIO / "index.css").read_text(encoding="utf-8")
INGEST = (STUDIO / "views" / "Ingest.jsx").read_text(encoding="utf-8")
EDITOR = (STUDIO / "views" / "editor.jsx").read_text(encoding="utf-8")

# The formats a dataset can be born from (G.2.2 + G.2.4 + the tabular
# built-ins). Both consoles must accept the same set: a file the Data
# console refuses and the ingest console takes is one rule told twice.
DATASET_EXTENSIONS = (".db", ".sqlite", ".sqlite3", ".csv", ".json",
                      ".xls", ".xlsx")


def code(text: str) -> str:
    """The source with its comments removed — prose about SQL is not SQL."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_creating_a_dataset_is_one_plant_carrying_a_schema():
    calls = re.findall(r"api\.call\(forest, 'plant', \{(.*?)\n      \}\)",
                       DATA, re.S)
    assert len(calls) == 1, "the Data console plants once, or not at all"
    assert "type: 'dataset'" in calls[0]
    assert "schema," in calls[0]


def test_the_console_never_writes_ddl():
    """C.7.1 rule 1: the schema is data and the CREATE TABLE is the Vine's.

    `columnsFromDdl` reads a stored declaration to show column types in the
    Structure tab — reading one is not writing one, so the guard looks for
    DDL being *built*, not for the word appearing.
    """
    for verb in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
        built = [line for line in code(DATA).splitlines()
                 if verb in line and "sqlite_master" not in line]
        assert not built, f"the console appears to compose {verb}: {built}"


def test_importing_is_the_ingest_surface_and_nothing_else():
    """J.5.10: the console does not parse the file and does not plant it."""
    assert "api.ingest(forest, {" in DATA
    assert "mode: 'upload'" in DATA
    # One `plant` in the whole file, and it is the creation dialog's.
    assert code(DATA).count("'plant'") == 1
    # Bytes go up as the wire contract's `b64`; nothing reads them here.
    assert "b64: await toBase64(" in DATA


def test_both_consoles_accept_the_same_dataset_formats():
    accept = re.search(r"IMPORT_ACCEPT = '([^']+)'", DATA).group(1).split(",")
    assert sorted(accept) == sorted(DATASET_EXTENSIONS)
    ingest_accept = "".join(re.findall(r"const ACCEPT = ('[^;]+)", INGEST, re.S))
    for ext in DATASET_EXTENSIONS:
        assert f"{ext}," in ingest_accept or f"{ext}'" in ingest_accept, ext


def test_leaving_a_dataset_clears_the_selection_and_keeps_a_draft():
    body = DATA.split("function disconnect()")[1].split("\n  }")[0]
    assert "if (changes > 0) return" in body, "a staged write must survive"
    assert "setId('')" in body and "setTable('')" in body


def test_source_is_coloured_wherever_it_is_typed():
    """J.5.10: the SQL box and the markdown body editor both — the second
    is what the rich editor hands back whenever a body holds a table, which
    every dataset's does."""
    assert '<CodeArea lang="sql"' in DATA
    assert "<textarea" not in DATA, "the SQL box is the CodeArea now"
    assert '<CodeArea ref={srcRef} lang="markdown"' in EDITOR
    assert "<textarea" not in EDITOR, "the markdown box is the CodeArea now"
    # The mirror renders the same characters a second time; a screen reader
    # must not read them twice.
    mirror = UI.split("CodeArea = forwardRef")[1]
    assert 'aria-hidden="true"' in mirror
    assert "pointer-events-none" in mirror
    # …and the ref has to reach the real input, or dictation loses the caret.
    assert "useImperativeHandle(outer, () => box.current" in mirror
    # Selection over a transparent input has to be translucent or it hides
    # the very characters being selected.
    assert ".codearea::selection" in CSS


def test_teaching_the_agent_is_one_graft_into_the_node():
    """C.2.1: a side store would be teaching the agent cannot read."""
    notes = DATA.split("function Notes(")[1].split("\n}")[0]
    # Read whole through `pick`, never from the digest — `look` clips notes
    # to their budget and editing a clipped copy would save the clip.
    assert "'pick', { id, section: NOTES_SECTION }" in notes
    assert "'graft'" in notes
    assert "append_section" in notes and "replace_section" in notes
    # The heading is a contract token: `look` reads this exact section back.
    assert "const NOTES_SECTION = 'Notes'" in DATA
    # And the tab has to be in the allow list or the address bounces (J.5.8).
    allow = re.search(r"allow: \[([^\]]*)\]", DATA).group(1)
    assert "'notes'" in allow
