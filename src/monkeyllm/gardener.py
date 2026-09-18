# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Gardener (spec v0.9, Part G): brownfield ingest — adopt + sync.

Four stages, only stage 2 ever needs an LLM (and v1 runs without one):

    0 archive  ->  1 convert  ->  2 curate  ->  3 plant

Trusted infrastructure: it writes through the same audited mechanics as
everything else (nodes via C.7 plant, datasets via C.7.1, sync updates via
a `.md`-only git commit). Converters are pluggable (G.2): forest-config
command hooks > `monkeyllm.converters` entry points > built-ins.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

import yaml

from monkeyllm import indexer
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import (
    MANUAL_SECTION, MAX_ALIASES, SAMPLE_ROWS, SAMPLE_SECTION,
    dataset_map, rows_label, validate_frontmatter, validate_summary,
    validate_tag,
)
from monkeyllm.parser import (
    HEADER_RE, append_section, extract_section, replace_section,
    serialize_node,
)
from monkeyllm.fetch import (
    STORE_TIMEOUT_S, head_object, put_object, resolve_store,
)
from monkeyllm.links import rewrite_link
from monkeyllm.sources import is_bucket_source, open_bucket_source
from monkeyllm.tokens import estimate_tokens
from monkeyllm.vine import MAX_BATCH_PLANT, Vine

GARDENER_CONFIG = "gardener.yaml"  # lives in _meta/ (not a node: non-.md)
FOREST_MARKER = "_index.md"  # A.5: what makes a directory a forest root
DEFAULT_IGNORES = (".git", ".svn", ".hg", "__pycache__", "node_modules",
                   "_derived", "_assets")
DEFAULT_IGNORE_GLOBS = ("~$*", "*.tmp", "*.lock", ".DS_Store", "Thumbs.db")
ASSETS_DIR = "_assets"
SUMMARY_TARGET_TOKENS = 50
INGEST_CONFIDENCE = 0.7  # G.4: unreviewed by an LLM or a human

# G.10.1: the phases a document passes through inside its one step. Closed
# and ordered on purpose — a consumer renders position as index/len, which
# is the only reason a one-document batch can show progress at all.
STAGE_CONVERT = "convert"
STAGE_CURATE = "curate"
STAGE_PLANT = "plant"
STAGES = (STAGE_CONVERT, STAGE_CURATE, STAGE_PLANT)

PAYLOAD_TYPE_BY_EXT = {
    ".pdf": "pdf", ".docx": "docx",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
    ".flac": "audio",
    # A.3/G.5.1 (v0.84): a recording was typed `document` for one reason —
    # the enum had no word for it.
    ".mp4": "video", ".m4v": "video", ".mkv": "video", ".mov": "video",
    ".webm": "video", ".avi": "video", ".mpg": "video", ".mpeg": "video",
}

# G.5.1: the extensions the media stub claims — exactly the image, audio and
# (v0.84) video halves of PAYLOAD_TYPE_BY_EXT, kept as named sets because the
# typing rule and the staging-archive rule test the same membership.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".mov", ".webm", ".avi",
                    ".mpg", ".mpeg"}

# G.5.1's typing rule, in ONE predicate: image, audio and video sources are
# `media` whatever the converter handed back. Both the adopt path and the
# refresh path read it, because two spellings of one membership test is how
# the v0.78 archive rule nearly diverged.
MEDIA_PAYLOAD_TYPES = ("image", "audio", "video")


def is_media_ext(ext: str) -> bool:
    return PAYLOAD_TYPE_BY_EXT.get(str(ext).lower()) in MEDIA_PAYLOAD_TYPES


# G.2.8 rule 2 (v0.84): how many parts one document may become. The hard
# ceiling is 999 and not a preference: rule 4 fixes the id padding at three
# digits so that a tree's order IS its id order for the life of the forest
# (ids are immutable, so they cannot be widened afterwards), and 1000 parts
# would need a fourth. 200 is the working default — a converter that cuts a
# document into more than that has probably detected something other than
# chapters.
TREE_CHILDREN_MAX = 200
TREE_CHILDREN_CEILING = 999
TREE_PART_WIDTH = 3

# G.2.8 rule 5: the A.5 headings a document's own front matter must not be
# able to capture. `parser.extract_section` matches case-insensitively, at
# any level, exact first and then BY PREFIX, taking the first match — so a
# document heading named like one of these captures the index's own entries,
# silently.
INDEX_SECTIONS = (indexer.SUBBRANCH_SECTION, indexer.BANANAS_SECTION,
                  "Cross trails")

# G.3.1 rule 6 (v0.84): where an object downloaded from a bucket waits while
# it is converted. A SIBLING of the Station's `_derived/uploads/` and never
# the same directory: J.13.7 asks one question of a staging area — which
# files no live passport records — and the two have opposite answers. An
# upload's unrecorded bytes are the only copy in existence and are the
# evidence of a batch that failed; a bucket download's are a cache of
# something the store still holds.
STAGING_DIR = ("_derived", "staging")

# G.3.2 (v0.84): how many DIRECT files a source directory or prefix may hold
# before `adopt` groups them into sub-branches. A source tree mirrors
# one-to-one, so a flat prefix of ten thousand keys mirrors into one branch
# with ten thousand direct children; A.5 flags `needs_split` at 150, which is
# advice to a Ranger that never splits anything, so it fires 9,850 entries
# too late to prevent anything. `0` disables the mechanism for an operator
# who would rather have the flat mirror and the wall.
BUCKET_ABOVE_ENV = "MONKEYLLM_ADOPT_BUCKET_ABOVE"
BUCKET_ABOVE_DEFAULT = 200

# The three rules, in the order they are tried — by how much the material
# itself said. `initial` always terminates, which is why it is last and why
# it is used anyway when nothing splits to size (G.3.2 rule 2).
BUCKET_RULES = ("name-prefix", "year-month", "initial")


def bucket_above() -> int:
    try:
        return max(0, int(os.environ.get(BUCKET_ABOVE_ENV,
                                         BUCKET_ABOVE_DEFAULT)))
    except (TypeError, ValueError):
        return BUCKET_ABOVE_DEFAULT


def _group_key(rule: str, name: str, created: str) -> str:
    """Which group one file's name (and date) puts it in."""
    if rule == "name-prefix":
        return re.split(r"[-_.]", name, maxsplit=1)[0] or "other"
    if rule == "year-month":
        return (created or "")[:7] or "undated"
    first = (slugify(Path(name).stem) or "other")[:1]
    return first if first.isalnum() else "other"


def choose_bucketing(names: list[str], created: dict[str, str],
                     above: int) -> str | None:
    """The first of the three rules that yields groups of at most `above`.

    Rule a additionally requires at least two groups and no group of one: a
    corpus that encodes its own grouping (`invoice_…`, `2024Q1-…`) is
    telling us where it wants to sit, and a name somebody chose beats a name
    we invent — but a "grouping" that gives every file its own branch is not
    one. If NO rule fits, the last is used anyway (rule 2): ten thousand
    files all beginning with `2024` is a real corpus, and refusing to adopt
    it would be refusing the case this section was written for. The wall that
    catches what grouping could not is A.5's rendering cap, which is why the
    two ship together.
    """
    if above <= 0 or len(names) <= above:
        return None
    for rule in BUCKET_RULES:
        groups: dict[str, int] = {}
        for name in names:
            key = _group_key(rule, name, created.get(name, ""))
            groups[key] = groups.get(key, 0) + 1
        if len(groups) < 2:
            continue
        if max(groups.values()) > above:
            continue
        if rule == "name-prefix" and min(groups.values()) < 2:
            continue
        return rule
    return BUCKET_RULES[-1]


# ===========================================================================
# G.2 — the converter contract (public plugin API v1)
# ===========================================================================

@dataclass
class Conversion:
    """What a converter hands back: markdown, a dataset description, the
    payload itself for a format the forest already speaks (G.2.2), or — as
    of v0.84 — a TREE (G.2.8).

    `tables`/`samples`/`counts` describe a `payload` conversion for the
    G.2.3 map: the structure read from the source, three rows per table,
    and the row counts. They are never the data — a payload conversion
    reads the shape of a database, never the whole of it.

    `children` describes a `tree`: the document's own front matter is
    `markdown` and its parts are `children`, in the document's order. Where
    a document divides is the converter's decision and never the engine's —
    dividing it requires knowing the format and usually the subject, and
    this package carries no content vocabulary, not even in a hint.
    """

    kind: str  # "markdown" | "dataset" | "payload" | "tree"
    title: str
    markdown: str = ""
    schema: dict | None = None          # C.7.1 declarative schema
    rows: dict[str, list[list]] | None = None
    tables: dict[str, dict[str, str]] | None = None
    samples: dict[str, list[list]] | None = None
    counts: dict[str, int] | None = None
    # G.2.8 (v0.84): [{title, markdown}, …], ordered, at least two.
    children: list[dict] | None = None


class Converter(Protocol):
    extensions: set[str]

    def convert(self, path: Path) -> Conversion: ...


class MarkdownConverter:
    """Built-in: .md/.txt pass through — the body IS the content."""

    extensions = {".md", ".markdown", ".txt"}

    def convert(self, path: Path) -> Conversion:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem.replace("_", " ").replace("-", " ")
        return Conversion(kind="markdown", title=title, markdown=text)


def _infer_column_type(values: list[str]) -> str:
    """INTEGER < REAL < TEXT, judged over the sampled non-empty values.

    A native `float` is never INTEGER, whatever its fractional part: a
    spreadsheet hands over `99.5` as a number, and `int(99.5)` truncates
    silently where `int("99.5")` raises — so a column typed from strings
    and the same column typed from a workbook would disagree, and the
    workbook's version would lose money by rounding it.
    """
    kind = "INTEGER"
    seen = False
    for v in values:
        if v is None or v == "":
            continue
        seen = True
        if isinstance(v, (bool, int)):
            continue
        if isinstance(v, float):
            kind = "REAL" if kind != "TEXT" else kind
            continue
        try:
            int(str(v))
            continue
        except (TypeError, ValueError):
            pass
        try:
            float(str(v))
            kind = "REAL" if kind != "TEXT" else kind
        except (TypeError, ValueError):
            return "TEXT"
    return kind if seen else "TEXT"


def _coerce(value, sql_type: str):
    if value is None or value == "":
        return None
    try:
        if sql_type == "INTEGER":
            return int(value)
        if sql_type == "REAL":
            return float(value)
    except (TypeError, ValueError):
        pass
    return str(value)


def slugify(text: str) -> str:
    """Deterministic id segment: lowercase, ASCII-folded, [a-z0-9._-]."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9._-]+", "-", folded.lower()).strip("-.")
    return slug or "node"


def _column_names(header: list[str]) -> list[str]:
    cols: list[str] = []
    used: set[str] = set()
    for i, name in enumerate(header):
        col = slugify(str(name) or f"col{i}").replace(".", "_").replace("-", "_")[:48]
        if not re.match(r"^[a-z_]", col):
            col = f"c_{col}"
        while col in used:
            col += "_"
        used.add(col)
        cols.append(col)
    return cols


def _tables_conversion(title: str,
                       tables: list[tuple[str, list[str], list[list]]]) -> Conversion:
    """One `dataset` conversion out of one or more (name, header, records)
    tables — a workbook's sheets (G.2.4) or a single delimited file."""
    schema: dict = {}
    rows: dict[str, list[list]] = {}
    for table, header, records in tables:
        cols = _column_names(header)
        types = {
            col: _infer_column_type([r[i] if i < len(r) else None for r in records])
            for i, col in enumerate(cols)
        }
        schema[table] = {"columns": types}
        rows[table] = [
            [_coerce(r[i] if i < len(r) else None, types[col])
             for i, col in enumerate(cols)]
            for r in records
        ]
    return Conversion(kind="dataset", title=title, schema=schema, rows=rows)


def _tabular_conversion(title: str, table: str, header: list[str],
                        records: list[list]) -> Conversion:
    return _tables_conversion(title, [(table, header, records)])


def _table_name(path: Path) -> str:
    return _sql_name(path.stem)


def _sql_name(text: str) -> str:
    """A table name out of arbitrary text — a filename, a sheet's tab."""
    name = slugify(text).replace(".", "_").replace("-", "_")[:48]
    return name if re.match(r"^[a-z_]", name) else f"t_{name}"


def _sheet_tables(sheets: list[tuple[str, list[list]]], path: Path,
                  ) -> list[tuple[str, list[str], list[list]]]:
    """G.2.4: every sheet becomes a table. Empty sheets are skipped.

    No count limit here (G.2.5): C.7.1's ≤10 tables and ≤50 columns bound
    what a MODEL declares, and a workbook somebody exported is not a
    declaration. Taking sheet one and dropping the rest — or refusing a
    141-column ERP export — is the tool telling the operator their data is
    wrong. The map's own caps (G.2.3) are what keep the body bounded.
    """
    tables: list[tuple[str, list[str], list[list]]] = []
    used: set[str] = set()
    for sheet_name, data in sheets:
        data = [row for row in data if any(v not in (None, "") for v in row)]
        if len(data) < 2:
            continue
        table = _sql_name(sheet_name) or _table_name(path)
        while table in used:
            table += "_"
        used.add(table)
        header = [str(v) if v not in (None, "") else f"col{i}"
                  for i, v in enumerate(data[0])]
        tables.append((table, header, data[1:]))
    if not tables:
        raise VineError(
            E_SCHEMA, f"workbook has no data rows: {path.name}",
            hint="Every sheet was empty or held only a header row.")
    return tables


class CsvConverter:
    """Built-in: .csv -> dataset (C.7.1 birth with inferred column types)."""

    extensions = {".csv"}

    def convert(self, path: Path) -> Conversion:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(text.splitlines(), dialect)
        data = [row for row in reader if row]
        if len(data) < 2:
            raise VineError(E_SCHEMA, f"csv has no data rows: {path.name}")
        return _tabular_conversion(path.stem.replace("-", " ").replace("_", " "),
                                   _table_name(path), data[0], data[1:])


class JsonConverter:
    """Built-in: tabular .json (list of flat dicts) -> dataset;
    anything else -> markdown with the JSON embedded."""

    extensions = {".json"}

    def convert(self, path: Path) -> Conversion:
        title = path.stem.replace("-", " ").replace("_", " ")
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        if (isinstance(data, list) and data
                and all(isinstance(r, dict) for r in data)
                and all(not isinstance(v, (dict, list)) for r in data for v in r.values())):
            header = list(dict.fromkeys(k for r in data for k in r))
            records = [[r.get(k) for k in header] for r in data]
            return _tabular_conversion(title, _table_name(path), header, records)
        body = f"# {title}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n"
        return Conversion(kind="markdown", title=title, markdown=body)


class XlsxConverter:
    """Built-in when openpyxl is importable: one table per sheet (G.2.4)."""

    extensions = {".xlsx"}

    def convert(self, path: Path) -> Conversion:
        from openpyxl import load_workbook  # optional dependency

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = []
            for ws in wb.worksheets:
                # A read-only worksheet trusts the file's own `<dimension>`
                # record, and files written by anything other than Excel
                # routinely declare `A1:A1` or omit it — openpyxl then
                # yields ONE row of a hundred and the converter reports a
                # workbook with no data. `reset_dimensions` makes it infer
                # the extent from the rows that are actually there, which
                # is the only source that cannot be wrong.
                if hasattr(ws, "reset_dimensions"):
                    ws.reset_dimensions()
                sheets.append(
                    (ws.title, [list(row) for row in ws.iter_rows(values_only=True)]))
        finally:
            wb.close()
        return _tables_conversion(path.stem.replace("-", " ").replace("_", " "),
                                  _sheet_tables(sheets, path))


class XlsConverter:
    """Built-in when xlrd is importable (G.2.4; xlrd is BSD-3, optional
    `ingest` extra — same gating as the openpyxl and python-docx built-ins).
    xlrd 2.x reads the legacy `.xls` format and only that, which is exactly
    the gap openpyxl leaves."""

    extensions = {".xls"}

    def convert(self, path: Path) -> Conversion:
        import xlrd  # optional dependency (ingest extra)

        book = xlrd.open_workbook(str(path))
        try:
            sheets = [
                (sheet.name,
                 [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                  for r in range(sheet.nrows)])
                for sheet in book.sheets()
            ]
        finally:
            if hasattr(book, "release_resources"):
                book.release_resources()
        return _tables_conversion(path.stem.replace("-", " ").replace("_", " "),
                                  _sheet_tables(sheets, path))


SQLITE_MAGIC = b"SQLite format 3\x00"


class SqliteConverter:
    """Built-in (G.2.2): a SQLite file IS a dataset payload, so it is
    adopted rather than converted.

    Nothing here reads the data: the structure of every table and its first
    `SAMPLE_ROWS` rows are what the G.2.3 map needs, and the largest thing
    this holds is `3 x columns` values per table. The bytes themselves are
    the Gardener's to install — copying a database is O(bytes), while
    rebuilding it row by row is unbounded in the source's size and lossy
    wherever its declared types, views, indexes or BLOBs do not survive a
    TEXT|INTEGER|REAL|BLOB round trip.
    """

    extensions = {".db", ".sqlite", ".sqlite3"}

    def convert(self, path: Path) -> Conversion:
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
                raise VineError(
                    E_SCHEMA, f"not a SQLite database: {path.name}",
                    hint="The file's header is not 'SQLite format 3'. An "
                         "encrypted or truncated database reads the same way.")
        tables, samples, counts = read_sqlite_map(path)
        if not tables:
            raise VineError(E_SCHEMA, f"database has no tables: {path.name}")
        return Conversion(
            kind="payload", title=path.stem.replace("-", " ").replace("_", " "),
            tables=tables, samples=samples, counts=counts)


def read_sqlite_map(db: Path) -> tuple[dict, dict, dict]:
    """The G.2.3 map of a SQLite file: structure, first rows, row counts.

    Tables only, and in name order: `look`'s `query_manual` (C.2) reads the
    payload the same way, and a body claiming a view the digest never
    mentions is two answers to "what is in this dataset". Name order also
    keeps the map stable, so a `sync` rewrites it only when the data moved.

    Read-only (`mode=ro`), and every per-table read is guarded on its own:
    one unreadable table (a virtual table whose module is not loaded here)
    costs its own row, never the whole map.
    """
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.text_factory = bytes_or_str
    tables: dict[str, dict[str, str]] = {}
    samples: dict[str, list[list]] = {}
    counts: dict[str, int] = {}
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            quoted = '"' + str(name).replace('"', '""') + '"'
            try:
                info = list(conn.execute(f"PRAGMA table_info({quoted})"))
            except sqlite3.Error:
                continue
            if not info:
                continue
            tables[str(name)] = {str(c[1]): str(c[2] or "") for c in info}
            try:
                cur = conn.execute(f"SELECT * FROM {quoted} LIMIT {SAMPLE_ROWS}")
                samples[str(name)] = [list(r) for r in cur.fetchall()]
                counts[str(name)] = conn.execute(
                    f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            except sqlite3.Error:
                samples[str(name)] = []
    finally:
        conn.close()
    return tables, samples, counts


def bytes_or_str(raw: bytes):
    """SQLite's text factory for a foreign database: decode when it is text,
    keep the bytes when it is not. A source nobody in this project created
    may hold any encoding, and a UnicodeDecodeError inside the map would
    lose a table that reads perfectly well through `query`."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw


class DocxConverter:
    """Built-in when python-docx is importable (G.2.1, MIT/BSD-clean):
    single-pass w:t traversal in document order — heading-styled paragraphs,
    pipe tables, and text inside embedded text boxes (wps:txbx/v:textbox);
    headers/footers excluded (letterhead boilerplate is scent noise).
    Technique derived from the owner's pdf-replace reader."""

    extensions = {".docx"}

    def convert(self, path: Path) -> Conversion:
        from docx import Document  # optional dependency (ingest extra)
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph

        doc = Document(str(path))
        tag_p, tag_tbl = qn("w:p"), qn("w:tbl")
        tag_t, tag_tr, tag_tc = qn("w:t"), qn("w:tr"), qn("w:tc")

        def text_of(el) -> str:
            # joining EVERY descendant w:t merges runs Word fragmented
            # mid-word and captures text living inside embedded text boxes
            joined = "".join(t.text or "" for t in el.iter(tag_t))
            return re.sub(r"\s+", " ", joined).strip()

        title = ""
        lines: list[str] = []
        for block in doc.element.body.iterchildren():
            if block.tag == tag_p:
                text = text_of(block)
                if not text:
                    continue
                level = self._heading_level(Paragraph(block, doc))
                if level == 1 and not title:
                    title = text
                # node title owns "#"; document headings start at "##"
                lines.append(f"{'#' * min(level + 1, 6)} {text}" if level else text)
                lines.append("")
            elif block.tag == tag_tbl:
                # direct children only: nested tables flatten into cell text
                rows = [
                    [text_of(tc).replace("|", "\\|") for tc in tr.findall(tag_tc)]
                    for tr in block.findall(tag_tr)
                ]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + " --- |" * width)
                lines.extend("| " + " | ".join(r) + " |" for r in rows[1:])
                lines.append("")
        title = title or path.stem.replace("_", " ").replace("-", " ")
        content = "\n".join(lines).strip()
        body = f"# {title}\n\n{content}\n" if content else f"# {title}\n"
        return Conversion(kind="markdown", title=title, markdown=body)

    @staticmethod
    def _heading_level(para) -> int:
        name = (para.style.name if para.style is not None else "") or ""
        if name == "Title":
            return 1
        m = re.match(r"Heading (\d)$", name)
        return int(m.group(1)) if m else 0


class CommandConverter:
    """G.2 discovery source 1: an external command template from the forest
    config converts the file — any tool, any license, never our dependency."""

    def __init__(self, extension: str, template: str):
        self.extensions = {extension.lower()}
        self.template = template

    def convert(self, path: Path) -> Conversion:
        with tempfile.TemporaryDirectory(prefix="gardener-") as tmp:
            out = Path(tmp) / (path.stem + ".md")
            # non-posix split keeps Windows backslashes; strip the quotes it
            # leaves around tokens, then substitute placeholders post-split
            parts = [
                p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p
                for p in shlex.split(self.template, posix=False)
            ]
            cmd = [part.replace("{input}", str(path)).replace("{output}", str(out))
                   for part in parts]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise VineError(
                    E_SCHEMA,
                    f"converter command failed for {path.name} (exit {r.returncode})",
                    hint=(r.stderr or r.stdout or "").strip()[:200],
                )
            text = out.read_text(encoding="utf-8", errors="replace") if out.is_file() else r.stdout
            if not text.strip():
                raise VineError(E_SCHEMA, f"converter command produced no markdown: {path.name}")
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem.replace("_", " ").replace("-", " ")
        return Conversion(kind="markdown", title=title, markdown=text)


# G.5.1 / H.3 (v0.54): the stub's admission, shared with the Ranger's
# `needs_description` check — two spellings of a sentinel agree only where
# somebody compared them.
MEDIA_STUB_SENTINEL = "No description has been generated for this media yet."


class MediaStubConverter:
    """Built-in (G.5.1): the model-free floor for image, audio and video.

    Before this existed an image was `unsupported` — no converter claimed
    it, so a screenshot fell out of the report entirely. The stub returns
    the only markdown that needs no model: what the file is called, what
    format it is, how big it is, and the plain admission that nothing has
    described it yet. A richer converter injected ahead of this one (the
    `extra_converters` seam) replaces the body; the stub is what guarantees
    the node exists either way.
    """

    # v0.84: video joins, for the reason the typing rule does — a recording
    # with no converter fell out of the report entirely, which is the exact
    # failure this stub was written to end for images.
    extensions = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

    def convert(self, path: Path) -> Conversion:
        title = path.stem.replace("_", " ").replace("-", " ")
        size = path.stat().st_size
        fmt = path.suffix.lstrip(".").upper()
        body = (
            f"# {title}\n\n"
            f"Media file `{path.name}` ({fmt} format, {size} bytes).\n\n"
            f"{MEDIA_STUB_SENTINEL}\n"
        )
        return Conversion(kind="markdown", title=title, markdown=body)


def builtin_converters() -> list:
    # SQLite needs no optional dependency: it is the standard library and it
    # is already this project's payload format (G.2.2).
    convs: list = [MarkdownConverter(), CsvConverter(), JsonConverter(),
                   SqliteConverter()]
    try:
        import openpyxl  # noqa: F401

        convs.append(XlsxConverter())
    except ImportError:
        pass
    try:
        import xlrd  # noqa: F401

        convs.append(XlsConverter())
    except ImportError:
        pass
    try:
        import docx  # noqa: F401

        convs.append(DocxConverter())
    except ImportError:
        pass
    # G.5.1: last on purpose — the stub is the floor every richer media
    # converter (a command hook, an injected describer) stands above.
    convs.append(MediaStubConverter())
    return convs


def discover_converters(config: dict, extra: list | None = None,
                        registry=None) -> list:
    """G.2/L.3 order: config command hooks > extensions (install order) >
    injected extras (G.5.1) > entry points > built-ins.

    `extra` is the seam a host uses to inject converters it holds (the
    vision describer): AFTER the operator's command hooks — an operator who
    configured their own `.png` hook keeps it — and BEFORE entry points and
    built-ins, so everyone else gets the injected converter over the stub.

    `registry` is Part L's seam (v0.80): an extension the operator installed
    and enabled on this forest outranks anything this project ships,
    because installing it was a deliberate act and the built-in is the
    fallback. It sits below a command hook for exactly the reason `extra`
    does — the operator's own `_meta/gardener.yaml` is the most local
    statement of intent there is.
    """
    convs: list = [
        CommandConverter(ext, tpl)
        for ext, tpl in (config.get("converters") or {}).items()
    ]
    if registry is not None:
        from monkeyllm.extensions.converters import from_registry
        convs.extend(from_registry(registry))
    convs.extend(extra or [])
    for ep in entry_points(group="monkeyllm.converters"):
        try:
            loaded = ep.load()
            convs.append(loaded() if isinstance(loaded, type) else loaded)
        except Exception:  # a broken plugin never blocks the pipeline
            continue
    convs.extend(builtin_converters())
    return convs


def supported_formats(config: dict, extra: list | None = None,
                      registry=None) -> list[dict]:
    """G.2 (v0.83): which extensions the chain claims, and who claims each.

    The SAME discovery `discover_converters` runs, read instead of run: one
    entry per file extension in precedence order, naming the first claimant
    the way a report would — `hook` (a G.6 command hook), `ext:<id>` (a
    Part L extension), `describer` (a host-injected extra), `plugin:<name>`
    (an entry point) or `builtin`. No Vine, no file opened.

    It exists so that no surface keeps a list of its own: a copied list is
    what let a `.pdf` stay greyed out in a console while the converter for
    it was installed, enabled and loaded.
    """
    seen: dict[str, str] = {}

    def claim(converter, via: str) -> None:
        for ext in sorted(getattr(converter, "extensions", ()) or ()):
            seen.setdefault(str(ext).lower(), via)

    for ext, tpl in (config.get("converters") or {}).items():
        claim(CommandConverter(ext, tpl), "hook")
    if registry is not None:
        from monkeyllm.extensions.converters import from_registry
        for conv in from_registry(registry):
            claim(conv, f"ext:{conv.ext_id}")
    for conv in extra or []:
        claim(conv, "describer")
    for ep in entry_points(group="monkeyllm.converters"):
        try:
            loaded = ep.load()
            claim(loaded() if isinstance(loaded, type) else loaded,
                  f"plugin:{ep.name}")
        except Exception:  # a broken plugin never blocks the pipeline
            continue
    for conv in builtin_converters():
        claim(conv, "builtin")
    return [{"extension": ext, "via": via}
            for ext, via in sorted(seen.items())]


def discover_hooks() -> list[Callable]:
    """G.4.3: `on_curate` hooks from the `monkeyllm.hooks` entry-point group."""
    hooks: list[Callable] = []
    for ep in entry_points(group="monkeyllm.hooks"):
        if ep.name != "on_curate":
            continue
        try:
            hooks.append(ep.load())
        except Exception:
            continue
    return hooks


# ===========================================================================
# G.4.1 — LLM-free curation
# ===========================================================================

_MD_NOISE = re.compile(r"^#+\s+.*$|^[-*>|`].*$|!\[[^\]]*\]\([^)]*\)", re.MULTILINE)
_MD_INLINE = re.compile(r"\[([^\]]*)\]\([^)]*\)|[*_`]{1,3}")


# A code a document states about ITSELF: two to six capitals, a hyphen, a
# number. Matched in the title (which G.2.1 takes from the H1), never in
# the body — a code inside prose is usually a reference to a different
# document, which is the neighbour-instead-of-target failure this rule
# exists to end.
_SELF_CODE_RE = re.compile(r"\b([A-Z]{2,6})-(\d{1,6})\b")

# A file stem that IS numbered, as opposed to one that merely starts with a
# digit: the number is followed by a separator or by nothing (G.2.6 rule 5).
_LEADING_NUMBER_RE = re.compile(r"(\d+)(?=[-_.\s]|$)")


def validate_tree(conversion: Conversion) -> str | None:
    """G.2.8 rule 2: what a tree must be, or the sentence that refuses it.

    Every refusal is per FILE and none is fatal to a batch: the caller
    reports it exactly as any other conversion failure, the document is not
    planted, and the rest of the batch proceeds. A partial tree is never
    planted — the document's parts ARE the document, and half of one is a
    forest claiming to hold a book it does not.
    """
    children = conversion.children
    if not isinstance(children, list):
        return "a tree conversion carries a list of children"
    if len(children) < 2:
        # A converter that found no second cut is describing a document that
        # is one node, and `kind: "markdown"` says that already. Accepting
        # one child would leave two spellings of one outcome — a node, and a
        # branch with a node under it — and the two would drift in `scan`,
        # in `coverage`, in every count and in every reader's habits.
        return (f"a tree needs at least two children, got {len(children)} "
                f"(a document that is one node is a markdown conversion)")
    if len(children) > TREE_CHILDREN_MAX:
        return (f"a tree carries at most {TREE_CHILDREN_MAX} children, got "
                f"{len(children)}")
    for i, child in enumerate(children, start=1):
        if not isinstance(child, dict):
            return f"child {i} is not an object"
        if not str(child.get("title") or "").strip():
            return f"child {i} has no title"
        if not str(child.get("markdown") or "").strip():
            return f"child {i} has no body"
    return None


def demote_index_headings(markdown: str) -> tuple[str, int]:
    """G.2.8 rule 5: keep the words, lose the `##` (returns body, count).

    A heading in the document's own front matter named like one of the A.5
    sections captures the index's own entries — the failure is silent, and
    entries are appended to whatever section matched first. Demoted to plain
    emphasis it keeps every word it had; DROPPED it would be the kind of
    filter this project forbids (G.4.2 rule 1's rule, applied to a body).
    """
    demoted = 0

    def replace(m: re.Match) -> str:
        nonlocal demoted
        text = m.group(2).strip()
        low = text.lower()
        for section in INDEX_SECTIONS:
            want = section.strip().lower()
            if low == want or low.startswith(want):
                demoted += 1
                # HEADER_RE's trailing `\s*` is greedy across newlines, so
                # what it swallowed is put back: a demotion may not also
                # close the paragraph break under the heading.
                raw = m.group(0)
                return f"**{text}**" + raw[len(raw.rstrip()):]
        return m.group(0)

    return HEADER_RE.sub(replace, markdown), demoted


def unmet_store(config: dict, stores=None) -> str | None:
    """The forest's `assets:` binding, when the deployment does not have it.

    G.6 rule 2 (v0.84): `_meta` declares EXPECTATION and never a grant, so a
    forest naming a store nobody configured keeps working — the archive falls
    back to `_assets/` (J.19.6) — and every surface that can say so MUST:
    `validate` prints it, H.3 reports it, the batch report names the
    fallback per file. L.12's rule for an extension a forest expects, said
    about a destination.
    """
    binding = str((config or {}).get("assets") or "").strip()
    if not binding:
        return None
    return None if resolve_store(name=binding, stores=stores) is not None else binding


def normalize_dest(dest: str | None) -> str | None:
    """G.3 (v0.61): a branch is addressed by its id, in either spelling.

    A branch's id ends in `/_index` and that is how every other surface
    names it — `scan("tasks/_index")`, `parent: "notes/_index"`,
    `coverage`'s roots. `dest` accepted only the bare form, so the
    canonical one built `tasks/_index/_index` and was refused with an
    `expected_parent` that named the exact string the caller had sent: the
    advice was to do what had just been done. Both forms mean the same
    branch here, and `_index` alone means the forest root.
    """
    if dest is None:
        return None
    d = str(dest).strip().strip("/")
    if d.endswith("/_index"):
        d = d[: -len("/_index")]
    if d == "_index":
        d = ""
    return d or None


def _folder_initials(folder: str) -> str | None:
    """`back-end` -> `BE`. A single-word folder derives nothing: one letter
    is not a name, and `T-291` out of `tasks` would put noise in the field
    the forest is most often searched by."""
    parts = [part for part in re.split(r"[-_]", folder) if part]
    if len(parts) < 2:
        return None
    return "".join(part[0] for part in parts).upper()


def derive_aliases(rel: Path, alias_map: dict,
                   title: str | None = None) -> list[str]:
    """G.2.6: the team's own name for a document (v0.54, widened v0.59).

    The first version required the operator's `aliases:` map for anything
    at all, and the field showed what that costs: in a forest where every
    document has a canonical code, 1,877 of 1,877 ingested nodes carried no
    aliases, and the most frequent access in that forest fell through to
    `sniff` — measured ~100x slower than the `locate` that should have
    answered it.

    The boundary is not "no map, no aliases"; it is **who knows the name**.
    A code the document prints in its own title is provenance, and reading
    it back is not the engine acquiring content vocabulary — no word is
    invented here and no table of conventions ships with the engine. What
    only an operator knows — that `back-end` is spelled `BE` — still lives
    in the forest's own `gardener.yaml`.
    """
    out: list[str] = []
    folder = rel.parent.name
    # G.2.6 rule 5 (v0.61): the leading digits must END — a whole segment,
    # not a prefix inside a word. `9router-free-ai-router` derived the alias
    # `9`, and a single digit in the one index searched by curated metadata
    # alone matches broadly and ranks: noise with authority, in the field
    # this rule exists to make trustworthy.
    m = _LEADING_NUMBER_RE.match(rel.stem)
    if m is not None:
        num = m.group(1)
        prefix = (alias_map or {}).get(folder) if isinstance(alias_map, dict) else None
        if isinstance(prefix, str) and prefix:
            # The operator's declaration wins AND suppresses the derived
            # initials: a convention stated is not one to be guessed beside.
            out.append(f"{prefix}-{num}")
        else:
            initials = _folder_initials(folder)
            if initials:
                out.append(f"{initials}-{num}")
        if folder:
            out.append(f"{folder}/{num}")
        out.append(num)
    for letters, digits in _SELF_CODE_RE.findall(title or ""):
        out.append(f"{letters}-{digits}")
    seen: set[str] = set()
    ordered = [a for a in out if not (a in seen or seen.add(a))]
    return ordered[:MAX_ALIASES]


def derive_summary(markdown: str, title: str) -> str:
    """First meaningful sentences of the content, <= 60 tokens (A.4)."""
    text = _MD_INLINE.sub(r"\1", _MD_NOISE.sub("", markdown))
    text = re.sub(r"\s+", " ", text).strip()
    summary = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = f"{summary} {sentence}".strip()
        if summary and estimate_tokens(candidate) > SUMMARY_TARGET_TOKENS:
            break
        summary = candidate
        if estimate_tokens(summary) > SUMMARY_TARGET_TOKENS:
            words = summary.split()
            while words and estimate_tokens(" ".join(words)) > SUMMARY_TARGET_TOKENS:
                words.pop()
            summary = " ".join(words).rstrip(",;") + "…"
            break
    summary = summary or f"Adopted content '{title}'; pending curation."
    try:
        validate_summary(summary)
    except VineError:
        summary = f"Adopted content '{title}'; pending curation."
    return summary


def derive_branch_summary(title: str, child_titles: list[str]) -> str:
    """Deterministic G.4.4 fallback: compose the region's scent from child
    titles, <= 60 tokens (A.4). Never raises."""
    names = [t.strip() for t in child_titles if t and t.strip()]
    summary = f"Region '{title}' with {len(names)} entries."
    listing: list[str] = []
    for name in names:
        candidate = (f"Region '{title}': " + ", ".join(listing + [name])
                     + f" (+{len(names) - len(listing) - 1} more).")
        if listing and estimate_tokens(candidate) > SUMMARY_TARGET_TOKENS:
            break
        listing.append(name)
    if listing:
        more = len(names) - len(listing)
        tail = f" (+{more} more)." if more > 0 else "."
        summary = f"Region '{title}': " + ", ".join(listing) + tail
    try:
        validate_summary(summary)
    except VineError:
        summary = f"Region '{title}' with {len(names)} entries."
    return summary


# ===========================================================================
# The Gardener
# ===========================================================================

@dataclass
class IngestReport:
    planted: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Dry-run only (spec J.8.1): the passports a real run would have planted,
    # in the order it would have planted them. Empty on every ordinary run,
    # so `as_dict` keeps reporting the same shape it always did.
    drafts: list[dict] = field(default_factory=list)
    # G.2.6 (v0.56): derived alias forms that no longer fit the 16-alias
    # cap beside hand-added ones — dropped, and said, never silently.
    # G.4.3 (v0.75) adds the Curator's overflowing proposals to the same
    # count: one condition, one number.
    aliases_clipped: int = 0
    # G.4.2 rule 1 (v0.75): tags the Curator's validator refused or the
    # passport budget clipped. Zero on a run that dropped nothing, so
    # "the model wrote no tags" and "a filter ate them" are distinguishable.
    tags_dropped: int = 0
    # J.8 (v0.61): sources the caller declared disposable and that became a
    # node, removed after they landed. Empty on every ordinary run.
    consumed: list[str] = field(default_factory=list)
    # J.19.6 (v0.84): originals this run put in an object store, and the
    # ones a store refused. The fallback is NAMED per file — bytes the
    # courier is about to delete are the only copy that will exist, so a
    # store that could not take them is the one thing an operator has to be
    # told. Zero and empty on every deployment that configured no store.
    archived_remote: int = 0
    archive_fallbacks: list[str] = field(default_factory=list)
    # G.10.2 rule 8 (v0.84): documents converted, rehearsed and waiting in
    # the open batch. `planted` names what is in GIT at the close, as it
    # always did, so a deferred plant must not be counted as durable while
    # it is still deferred — and an abandoned run leaves these here, which
    # is the honest record of the conversion work `sync` will redo.
    queued: list[str] = field(default_factory=list)
    # G.7 rule 7 (v0.84): nodes whose requested `content: reference` was
    # degraded to `cached`. A reference body is read back from its source at
    # every `pick`, and for a bucket that is a network round trip inside the
    # primitive with the tightest budget in the spec — the bill K.2 moved out
    # of the read path in v0.42, and it must not walk back in through the
    # content policy. Degraded is fine; degraded in silence is not.
    content_degraded: int = 0
    # G.2.8 rule 5 (v0.84): headings in a document's own front matter that
    # would have captured the index's own entries, demoted to emphasis with
    # their words intact.
    headings_demoted: int = 0
    # G.2.8 rule 7 (v0.84): tree branches whose forest declares no
    # `succeeds`, so the parts are there and the sequence is not. Told,
    # never silent: a chapter list nobody can walk is otherwise
    # indistinguishable from a converter that lost the order, and the repair
    # is one line in `_meta/schema.md` followed by a `sync`.
    sequence_skipped: list[str] = field(default_factory=list)
    # G.4.7 rule 2 (v0.84): why a model wrote nothing, when one did not.
    # Empty on a batch that curated — the host fills the rest of the block
    # (whether a model is bound at all is the host's knowledge, never the
    # engine's).
    curation: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, list) else v)
                for k, v in self.__dict__.items()}


# J.8 (v0.61): the outcomes that mean "these bytes are now a node in this
# forest" — the condition for consuming a disposable source. `unsupported`
# and `error` are deliberately absent: nothing landed, and the file is the
# only evidence of what was sent.
_LANDED = frozenset({"planted", "updated", "unchanged"})


# G.10: which report list a step grew names what the step did. Ordered by
# precedence — a planted file may also record its branch, and the branch is
# not the action. A draft counts as `planted`: a preview steps exactly as
# the run it previews.
_STEP_ACTIONS = (("planted", "planted"), ("queued", "planted"),
                 ("updated", "updated"),
                 ("unchanged", "unchanged"), ("unsupported", "unsupported"),
                 ("errors", "error"), ("stale", "stale"), ("drafts", "planted"))


# G.4.2 rule 1 / G.4.3 rule 3 (v0.75): the counters a curation hook may
# keep and the report knows how to read. A hook is an arbitrary callable
# (G.4 rule 3), so the report reads only the names it declares here, and
# reads them as a DELTA — one Curator serves a whole batch, and its stats
# are a running total across every document in it.
_HOOK_COUNTS = ("tags_dropped", "aliases_clipped")


def _hook_counts(hook) -> dict[str, int] | None:
    stats = getattr(hook, "stats", None)
    if not isinstance(stats, dict):
        return None
    return {k: stats.get(k, 0) for k in _HOOK_COUNTS}


def _collect_hook_counts(hook, before: dict[str, int] | None,
                         report: IngestReport) -> None:
    if before is None:
        return
    stats = getattr(hook, "stats", None)
    if not isinstance(stats, dict):
        return
    for name in _HOOK_COUNTS:
        grew = stats.get(name, 0) - before[name]
        if grew > 0:
            setattr(report, name, getattr(report, name) + grew)


def _counts(report: IngestReport) -> dict:
    return {attr: len(getattr(report, attr)) for attr, _ in _STEP_ACTIONS}


def _step(file: str, index: int, total: int, report: IngestReport,
          before: dict, committed: int | None = None) -> dict:
    """G.10: one document. `committed` (v0.84) is how many of this run's
    documents are in git at the moment this step yielded — at most `index`.

    Two numbers because they are two facts: a consumer rendering "N of M
    done" from `index` is rendering CONVERSIONS, and one that says
    "committed" must read `committed`. A single number would have to choose
    which one to be wrong about.
    """
    action = "skipped"
    for attr, name in _STEP_ACTIONS:
        if len(getattr(report, attr)) > before[attr]:
            action = name
            break
    out = {"file": file, "index": index, "total": total, "action": action}
    if committed is not None:
        out["committed"] = committed
    return out


def _drain(steps: "IngestSteps") -> dict:
    for _ in steps:
        pass
    return steps.result


def _scent_dict(report: IngestReport, stats: dict,
                remaining: int = 0) -> dict:
    """J.13.6.1's report: what the pass touched, and what it did not.

    `fallbacks` and `skipped` are separate on purpose. A fallback is a model
    that failed, refused or answered invalidly (rule 4) — a node left
    byte-identical for a reason somebody may want to fix. A skip is a node
    with no body this pass may read, which is not a failure of anything and
    has no fix. Reported as one number they would send an operator to debug
    a model that was never asked, which is J.8's own lesson.
    """
    out = report.as_dict()
    out.update({
        "derived": ["scent"],
        "scanned": (len(report.updated) + len(report.unchanged)
                    + len(report.errors)),
        "changed": len(report.updated),
        "fallbacks": int(stats.get("fallbacks", 0)),
        "skipped": int(stats.get("skipped", 0)),
        # J.13.6.1 rule 9 (v0.84): what a bounded run did not reach. Zero on
        # an unbounded pass, which visited everything in scope.
        "remaining": int(remaining),
    })
    return out


def scent_result(steps: "IngestSteps") -> dict:
    """The scent pass's report, finished or partial (J.13.6.1).

    A cancelled run has a report too — it committed everything it stepped
    through — and the caller that cancelled it is exactly the one who needs
    to read what it managed to do.
    """
    if steps.result is not None:
        return dict(steps.result)
    return _scent_dict(steps.report,
                       getattr(steps, "scent_stats", {}) or {})


class IngestSteps:
    """G.10 step iterator: one document per `next()`, the report at the end.

    Construction is eager where iteration is lazy — the source is resolved
    and walked before this exists, so `total` is known up front and a bad
    source fails before any step runs (spec J.9 needs both to refuse before
    accepting). `report` is the live `IngestReport` the steps are filling —
    what a consumer that died mid-batch can still account from — and
    `result` is its final dict once the iterator is exhausted, None until
    then.
    """

    def __init__(self, total: int, steps, report: IngestReport):
        self.total = total
        self.report = report
        self.result: dict | None = None
        self._steps = steps

    def __iter__(self) -> "IngestSteps":
        return self

    def __next__(self) -> dict:
        try:
            return next(self._steps)
        except StopIteration as done:
            self.result = done.value
            raise


class Gardener:
    """Adopts a directory into forest (Part G).

    `dry_run` makes the whole object incapable of writing: it converts,
    curates and proposes exactly as a real run does, and then collects the
    drafts instead of planting them (spec J.8.1). The flag lives here rather
    than on `adopt`/`sync` on purpose — a per-call flag is forgotten by the
    next call somebody adds, and the guarantee this exists to give ("nothing
    was written") has to hold for the object, not for one entry point.
    """

    def __init__(self, vine: Vine, converters: list | None = None,
                 hooks: list[Callable] | None = None, *, dry_run: bool = False,
                 on_stage: Callable[[str, str], None] | None = None,
                 extra_converters: list | None = None,
                 ext_registry=None,
                 stores=None,
                 curate: bool | None = None,
                 provenance: dict[str, str] | None = None):
        self.vine = vine
        self.forest = vine.forest
        self.config = self._load_config()
        # J.19.8 (v0.84): the object-store resolver, keyword-only and
        # host-supplied — the G.2.5 construction that already keeps
        # `adopted=` and `visible=` off the wire, for the same reason: a
        # credential an agent can name is not a credential. Inherited from
        # the Vine when the caller does not override it, because a host
        # that gave one to the Vine gave it to this forest.
        self.stores = stores if stores is not None else getattr(vine, "stores", None)
        # G.3.1 (v0.84): the object source of a bucket run, set by
        # `adopt_iter`/`sync_iter`. `None` is a directory source, which is
        # every v0.83 run.
        self._remote_source = None
        # G.10.2 (v0.84): the open batch. Documents plant in batches of up to
        # `MAX_BATCH_PLANT` through C.7.4's list form — one commit per batch
        # instead of one per document — while the STEP stays one document,
        # because the step is what a progress bar counts.
        self._batch: list[dict] = []
        self._batch_ids: set[str] = set()
        # J.8 (v0.48): source path -> URL, for sources whose origin is an
        # address rather than a directory (a clipped page, a saved image).
        # A MAP handed at construction, deliberately not an `on_curate`
        # hook: curation never runs on refreshes (G.3), so provenance
        # recorded there would vanish with the first `sync` — the map is
        # consulted on adopt and on every body refresh alike. Keys are the
        # relative posix paths `source_path` records; the URL is data, not
        # vocabulary, so nothing here reads it.
        self.provenance = dict(provenance or {})
        # L.3 seam (v0.80): the extension registry a host loaded for this
        # forest. Keyword-only and host-supplied, the G.2.5 construction —
        # an agent must never be able to name the converters it is judged
        # by. `None` is a host that runs no extensions, which is every
        # engine-only caller that has not asked for them.
        self.ext_registry = ext_registry
        # G.5.1 seam: `extra_converters` joins discovery between the
        # operator's command hooks and everything else. An explicit
        # `converters` list bypasses discovery entirely (tests do this),
        # so the extras are ignored there — the caller already said
        # exactly what runs.
        self.converters = (converters if converters is not None
                           else discover_converters(self.config,
                                                    extra=extra_converters,
                                                    registry=ext_registry))
        self.hooks = hooks if hooks is not None else discover_hooks()
        # G.4.7 (v0.84): curating later is a DECISION, not a failure.
        # `False` means the model is never called — not "called and
        # ignored", not "called for branches": no `on_curate` hook runs and
        # every node's summary is G.4 rule 1's derived one. `True` and
        # `None` are v0.83's behaviour to the byte. Keyword-only and
        # host-supplied: what it changes is what is written into the forest
        # and what the deployment is billed, so it is the batch's decision
        # and never a preference this object invents.
        self.curate = curate
        self.dry_run = bool(dry_run)
        self.on_stage = on_stage

    def _stage(self, file: str, stage: str) -> None:
        """G.10.1: name the phase, never pause in it.

        A step is still a whole document — nothing here is a suspension
        point — but a batch of ONE document would otherwise show a consumer
        nothing until it shows everything, which is indistinguishable from
        a hang. An observer that raises is swallowed: progress reporting
        that can abort the work it reports on is worse than none.
        """
        if self.on_stage is None:
            return
        try:
            self.on_stage(file, stage)
        except Exception:
            pass

    # -- config (G.6) -------------------------------------------------------

    def _config_path(self) -> Path:
        return self.forest.root / "_meta" / GARDENER_CONFIG

    def _load_config(self) -> dict:
        p = self._config_path()
        if p.is_file():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return {}

    def _save_config(self) -> None:
        """G.6 (v0.84): written AND committed through the narrow `_meta` door.

        This file was untracked in every forest this project has produced —
        `init` commits `.gitignore`, `_index.md` and `_meta/schema.md`, and
        this method wrote the file and stopped. So "the binding travels in a
        snapshot" was true of the path and false of the artifact. L.12's door
        (`commit_meta`, `.yaml`/`.md` under `_meta/` only) is what makes it
        true; A.3.1's `.md`-only guard on the ordinary commit path is not
        relaxed.

        Committing the file commits everything in it, which is intended and
        stated: `source_root` and the G.3.2 bucketing rule travel too. Both
        are ADDRESSES, the class of thing `origin` and `payload` already
        are; a credential lives in J.19's registry and never here.
        """
        if self.dry_run:
            return  # a preview that recorded a source root would misdirect
        p = self._config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
        try:
            self.vine.git.commit_meta([p], "gardener(config): source and bindings")
        except Exception:  # noqa: BLE001
            # A forest whose git is unavailable still ingests: the config is
            # on disk and the batch is what the operator asked for. Failing
            # the ingest to version a setting would be the wrong trade.
            pass

    # -- walking ------------------------------------------------------------

    def _ignored(self, path: Path) -> bool:
        if any(part in DEFAULT_IGNORES or part.startswith(".") for part in path.parts):
            return True
        globs = list(DEFAULT_IGNORE_GLOBS) + list(self.config.get("ignore") or [])
        return any(path.match(g) for g in globs)

    def _walk(self, src: Path) -> list[Path]:
        """Every ingestable file under `src`, forests excluded.

        A forest met inside the tree is pruned whole: its passports are
        somebody's curated nodes, not documents to convert, and a source
        that happens to sit above a registry would otherwise hand every
        forest under it to this one — across the tenant boundary, in a
        single call.
        """
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(src):
            here = Path(dirpath)
            rel_dir = here.relative_to(src)
            if here != src and (here / FOREST_MARKER).is_file():
                dirnames[:] = []
                continue
            # Pruning the directory beats filtering its files one by one:
            # os.walk does not descend into what it is not given.
            dirnames[:] = [d for d in dirnames if not self._ignored(rel_dir / d)]
            for name in filenames:
                if not self._ignored(rel_dir / name):
                    out.append(here / name)
        return sorted(out)

    def _resolve_source(self, source: str | Path | None,
                        *, recorded: bool = False) -> Path:
        """The one place a host path becomes an ingest root (G.3).

        Every caller passes through here, so the two ways a walk can escape
        its forest are closed once: an empty source (which `Path("")`
        resolves to the process's working directory — the Station's own
        install tree, or whatever a shell happened to be sitting in), and a
        source that contains the forest, which walks the registry beside it.
        """
        raw = str(source or "").strip()
        if not raw and recorded:
            raw = str(self.config.get("source_root") or "").strip()
        if not raw:
            # Never fall back to the working directory: the caller asked to
            # ingest "the usual place" and this forest has no usual place.
            raise VineError(
                E_SCHEMA, "this forest has no adopted source to sync",
                hint="Adopt a directory first, or pass the source explicitly.")
        src = Path(raw).resolve()
        if not src.is_dir():
            raise VineError(
                E_SCHEMA, f"source is not a directory: {src}",
                hint="Adopt a directory first, or pass the source explicitly.")
        root = self.forest.root.resolve()
        if root == src or root.is_relative_to(src):
            raise VineError(
                E_SCHEMA, f"source contains the forest itself: {src}",
                hint="Ingest reads a source tree into a forest; a source at "
                     "or above the forest root would ingest the forest, and "
                     "every other forest beside it.")
        if src.is_relative_to(root) and not src.is_relative_to(root / "_derived"):
            # `_derived/` is the exception on purpose: the Station's upload
            # staging lives there, and it is explicitly not forest content.
            raise VineError(
                E_SCHEMA, f"source is inside the forest: {src}",
                hint="A forest's own nodes are not a source to re-ingest.")
        return src

    def _staging_root(self) -> Path:
        return self.forest.root.joinpath(*STAGING_DIR)

    def _open_source(self, source: str | Path | None, *,
                     recorded: bool = False):
        """The one place a source becomes something to walk (G.3, G.3.1).

        Returns `(root, remote)`: a directory and `None`, or the staging root
        and the `BucketSource` that fills it. Every refusal a bucket can
        raise — a bucket no configured store serves, a prefix a store does
        not contain — happens HERE, before the first listing call, which is
        the containment rule for a remote source.
        """
        raw = str(source or "").strip()
        if not raw and recorded:
            raw = str(self.config.get("source_root") or "").strip()
        if is_bucket_source(raw):
            staging = self._staging_root()
            remote = open_bucket_source(
                raw, stores=self.stores, staging=staging,
                ignored=lambda rel: self._ignored(Path(rel)))
            staging.mkdir(parents=True, exist_ok=True)
            return staging, remote
        return self._resolve_source(raw or source, recorded=recorded), None

    def _materialise(self, src: Path, rel: str, entry: dict | None) -> Path:
        """The file this step converts: the source's own, or one object."""
        if entry is None or self._remote_source is None:
            return src / rel
        return self._remote_source.fetch(rel)

    def _release(self, f: Path, entry: dict | None) -> None:
        if entry is not None and self._remote_source is not None:
            self._remote_source.release(f)

    # -- G.10.2 the open batch ----------------------------------------------

    def _queue_plant(self, draft: dict, rel: str, report: IngestReport) -> None:
        """Rehearse this document's plant, then defer the commit.

        The step's `action` is decided HERE, from the draft's own C.7.3
        rehearsal, so a draft that would fail is an `error` at its own step
        and not at the flush — which is the only way a batch can be a commit
        without also becoming the place errors are reported.
        """
        try:
            self.vine.plant(draft, dry_run=True, adopted=True)
        except VineError as e:
            report.errors.append(f"{rel}: {e.message}")
            return
        self._batch.append(draft)
        self._batch_ids.add(draft["id"])
        report.queued.append(draft["id"])
        if len(self._batch) >= MAX_BATCH_PLANT:
            self._flush_batch(report)

    def _flush_batch(self, report: IngestReport) -> None:
        """Close the open batch: one commit for the lot, or none of it.

        A batch of ONE plants singly — byte-identical to v0.83, commit
        subject included, so a one-document ingest is untouched by this
        round.
        """
        if not self._batch:
            return
        batch, self._batch = self._batch, []
        ids = [d["id"] for d in batch]
        self._batch_ids.difference_update(ids)
        try:
            if len(batch) == 1:
                self.vine.plant(batch[0], adopted=True)
            else:
                self.vine.plant(batch, adopted=True)
        except VineError as e:
            # C.7.4 is all-or-nothing, so there is no state between: nothing
            # landed, and the report says so rather than leaving the count to
            # be believed.
            for node_id in ids:
                if node_id in report.queued:
                    report.queued.remove(node_id)
            report.errors.append(
                f"plant(batch) of {len(ids)} node(s) refused: {e.message}")
            return
        for node_id in ids:
            if node_id in report.queued:
                report.queued.remove(node_id)
            report.planted.append(node_id)

    def _converter_for(self, path: Path):
        ext = path.suffix.lower()
        for conv in self.converters:
            if ext in conv.extensions:
                return conv
        return None

    def _is_staged(self, f: Path) -> bool:
        """Whether this source sits in the forest's own `_derived/`.

        That tree is disposable by construction, so a path into it is a
        fact about plumbing and never an address: it cannot be an
        `origin` (G.2.7), it cannot back a `reference` body (G.7), and it
        is the one source a caller may declare consumable (J.8).
        """
        try:
            return f.resolve().is_relative_to(
                self.forest.root.resolve() / "_derived")
        except (OSError, ValueError):
            return False

    def _origin_for(self, f: Path, rel: str) -> str | None:
        """G.2.7 (v0.58): where this document came from, as one URI.

        The source file's own address — except for uploads staged under
        the forest's `_derived/`, where the entry's declared `source_url`
        speaks (J.8) and a staging path would be a fact about plumbing.
        """
        url = self.provenance.get(rel)
        if url:
            return url
        if self._remote_source is not None:
            # G.3.1 rule 4: the object's own URI — the address that resolves
            # from any machine holding the store's credentials, which is what
            # a mount path never was. The staged copy is plumbing and its
            # path is never an address.
            return self._remote_source.object_uri(rel)
        if self._is_staged(f):
            return None
        return f.resolve().as_uri()

    def _with_provenance(self, markdown: str, rel: str) -> str:
        """J.8 (v0.48): a converted body whose source has an address ends
        with the same `Source:` line a composed clip carries.

        Applied to markdown conversions only — a dataset's map is not
        prose, and a payload's body is the G.2.3 sample map — and BEFORE
        curation and the content policy, so the Curator reads what a
        reader will and a cached body carries its address too. Idempotent
        by the STAMPED LINE, not by substring: a body citing a deeper
        link on the same site (`…/blog/post-123` under source
        `…/blog`) contains the URL as a prefix, and a substring test
        would silently drop the provenance for exactly the common case.
        Only a body already carrying the exact `Source:` line is left
        alone.
        """
        url = self.provenance.get(rel)
        if not url:
            return markdown
        if re.search(rf"(?m)^Source: {re.escape(url)}[ \t]*$", markdown):
            return markdown
        return markdown.rstrip("\n") + f"\n\n---\n\nSource: {url}\n"

    # -- ids and branches ----------------------------------------------------

    def _branch_id_for(self, rel_dir: Path, dest: str | None) -> str:
        parts = [slugify(p) for p in rel_dir.parts]
        prefix = [] if not dest else [dest]
        return "/".join(prefix + parts + ["_index"]) if (parts or prefix) else "_index"

    def _ensure_branch(self, rel_dir: Path, dest: str | None,
                       report: IngestReport) -> str:
        branch_id = self._branch_id_for(rel_dir, dest)
        if branch_id == "_index" or self.forest.exists(branch_id):
            return branch_id
        parent_id = self._ensure_branch(rel_dir.parent, dest, report) \
            if rel_dir.parts else "_index"
        name = rel_dir.parts[-1] if rel_dir.parts else dest
        title = str(name).replace("_", " ").replace("-", " ")
        if self.dry_run:
            # `branches` becomes "would create" — the id is still returned so
            # the drafts below name the parent the real run would give them.
            report.branches.append(branch_id)
            return branch_id
        self.vine.plant({
            "id": branch_id,
            "type": "branch",
            "parent": parent_id,
            "title": title,
            "summary": f"Documents adopted from source folder '{name}'.",
            "source": "ingest",
            "body": (f"# {title}\n\n> Documents adopted from source folder "
                     f"'{name}'.\n\n## Sub-branches\n\n## Direct bananas\n\n"
                     "## Cross trails\n"),
        })
        report.branches.append(branch_id)
        return branch_id

    # -- rollup (G.4.4) ------------------------------------------------------

    def rollup(self, curator=None, *, only_ingest: bool = True) -> dict:
        """G.4.4: synthesize branch summaries bottom-up (deepest first) from
        the children's entry lines. Writes through C.8 graft, so parent-entry
        propagation and `.md`-only commits are inherited."""
        if self.dry_run:
            return {"rolled": [], "fallbacks": [], "skipped": 0}
        rolled: list[str] = []
        fallbacks: list[str] = []
        skipped = 0
        rows = self.vine.catalog.conn.execute(
            "SELECT id, source, title, summary FROM nodes WHERE kind = 'branch' "
            "ORDER BY LENGTH(id) - LENGTH(REPLACE(id, '/', '')) DESC, id"
        ).fetchall()
        for row in rows:
            branch_id = row["id"]
            if branch_id.startswith("_meta/"):
                continue
            if only_ingest and row["source"] != "ingest":
                skipped += 1
                continue
            # Fresh read: a deeper child's rollup may have just rewritten
            # this branch's entry lines via summary propagation.
            node = self.forest.read(branch_id)
            entries: list[str] = []
            for section in (indexer.SUBBRANCH_SECTION, indexer.BANANAS_SECTION):
                sec = extract_section(node.body, section) or ""
                entries += [l for l in sec.splitlines() if l.startswith("- [[")]
            if not entries:
                skipped += 1  # empty region: the template summary stays
                continue
            new_summary = (curator.branch_summary(row["title"], entries)
                           if curator is not None else None)
            if new_summary is None:
                child_titles = [c["title"]
                                for c in self.vine.catalog.children(branch_id)]
                new_summary = derive_branch_summary(row["title"], child_titles)
                fallbacks.append(branch_id)
            if new_summary == row["summary"]:
                continue
            self.vine.graft(branch_id,
                            {"set_frontmatter": {"summary": new_summary}})
            rolled.append(branch_id)
        return {"rolled": rolled, "fallbacks": fallbacks, "skipped": skipped}

    # -- curation (G.4) -----------------------------------------------------

    def _curate(self, draft: dict, report: IngestReport) -> dict:
        draft.setdefault("tags", [])
        for tag in (self.config.get("curation") or {}).get("default_tags") or []:
            if tag not in draft["tags"]:
                draft["tags"].append(tag)
        if self.curate is False:
            # G.4.7 rule 1: the hooks ARE the curation seam (G.4 rule 3), so
            # skipping them is the whole of "the model is never called". The
            # report says which of the three happened (rule 2) rather than
            # leaving a deliberate choice looking like a model that failed —
            # J.8's own lesson, with a third state.
            report.curation = {"ran": False, "reason": "disabled"}
            return draft
        for hook in self.hooks:
            before = _hook_counts(hook)
            try:
                result = hook(draft)
                if isinstance(result, dict):
                    draft = result
            except Exception as e:  # G.4 r3: a broken hook never aborts ingest
                report.errors.append(f"on_curate hook {getattr(hook, '__name__', hook)!r}: {e}")
            _collect_hook_counts(hook, before, report)
        return draft

    # -- stage 0: archive ----------------------------------------------------

    def _archive_needed(self, ext: str, kind: str, consumed: bool) -> bool:
        """G.7 rule 5 (v0.84): lossiness decides, not the policy alone.

        A conversion is LOSSLESS when the forest holds what the source held:
        a text passthrough, whose body *is* the bytes, and a payload adoption
        (G.2.2), whose payload *is* the source. Everything else is lossy —
        a PDF's tables, a `.docx`'s images, a video's frames — and a lossy
        original MUST be kept whatever `archive:` says when the source will
        not survive the ingest, which is every source the courier consumes
        (J.8.3 removes it the moment the file lands).

        This generalises G.5.1's staging amendment, which stated the rule for
        media and gave a reason that was never about media: a PDF arriving
        through the same door got none of it, and its original existed
        nowhere. ONE predicate, read by the adopt path and the refresh path
        alike — two copies of this test is how the v0.78 rule nearly
        diverged.

        A dataset's original is excluded under `never`: the forest holds its
        rows, `query` reads them, and the node's `payload` is its own `.db`,
        so a second copy would be bytes no passport names. `archive: always`
        still keeps it, which is what that policy is for.
        """
        if kind == "payload":
            return False
        if ext in MarkdownConverter.extensions:
            return False
        if self.config.get("archive", "never") == "always":
            return True
        return consumed and kind != "dataset"

    def _source_is_consumed(self, f: Path) -> bool:
        """Whether this ingest is the last thing that will hold these bytes.

        A staged upload's source is a courier the forest itself deletes
        (J.8.3). A bucket object staged under `_derived/staging/` is the
        opposite case, and the distinction is the whole reason G.3.1 rule 7
        can say "the bucket is the BONE": the staged copy goes, the object
        stays, and copying it into `_assets/` would be the double store
        this round exists to avoid.
        """
        return self._remote_source is None and self._is_staged(f)

    def _archive_store(self):
        """J.19.6: the forest's binding, then the `env` store, then local."""
        binding = str(self.config.get("assets") or "").strip()
        if binding:
            found = resolve_store(name=binding, stores=self.stores)
            if found is not None:
                return found
        return resolve_store(name="env", stores=self.stores)

    def _archive(self, src_file: Path, branch_id: str, *,
                 report: "IngestReport | None" = None,
                 rel: str | None = None) -> tuple[str, str | None, str]:
        """Keep the original: in the bound object store, or under `_assets/`.

        Returns `(payload, payload_type, payload_hash)`. The key is content
        addressed — `<prefix>/<forest id>/<sha256>.<ext>` — so dedup and
        immutability cost nothing and no component is caller-authored: an
        administrator's prefix, the forest root's own directory name, a
        digest and the source's lowercased extension. There is nothing in it
        to traverse with.

        **A failed upload falls back locally and is NAMED.** These bytes are
        about to be deleted by the courier, so losing them to a network error
        is the precise outcome J.19 exists to prevent — and the passport
        records what ACTUALLY happened. The reverse failure, a passport
        naming an object the store does not hold, must never occur, which is
        why the URI is returned only after the PUT returned.
        """
        data = src_file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        ext = src_file.suffix.lower()
        # A.3 (v0.84): an archived original whose extension names no other
        # payload type is `file`. Before it, those bytes were copied and
        # referenced by nothing.
        ptype = PAYLOAD_TYPE_BY_EXT.get(ext) or "file"

        store = self._archive_store()
        if store is not None:
            key = store.key_for(self.forest.root.name, f"{digest}{ext}")
            if self.dry_run:
                return store.uri(key), ptype, digest
            try:
                if head_object(store, key, timeout=STORE_TIMEOUT_S) is None:
                    put_object(store, key, data, timeout=STORE_TIMEOUT_S)
                if report is not None:
                    report.archived_remote += 1
                return store.uri(key), ptype, digest
            except Exception as e:  # noqa: BLE001 - every SDK raises its own
                if report is not None:
                    # The store's NAME and the failure, never a credential:
                    # `StoreCredentials` prints no secret and none is read
                    # here.
                    report.archive_fallbacks.append(
                        f"{rel or src_file.name}: store {store.name!r} "
                        f"refused the upload ({type(e).__name__}) — the "
                        f"original was kept locally instead")

        branch_dir = self.forest.path_for(branch_id).parent
        assets = branch_dir / ASSETS_DIR
        name = f"{digest[:8]}-{slugify(src_file.stem)}{ext}"
        # The digest and the name are computed either way, so a dry run's
        # draft carries the same payload fields a real one would write.
        if not self.dry_run:
            assets.mkdir(parents=True, exist_ok=True)
            (assets / name).write_bytes(data)
        return f"{ASSETS_DIR}/{name}", ptype, digest

    # -- adopt (G.3) ---------------------------------------------------------

    def adopt(self, source: str | Path, dest: str | None = None) -> dict:
        return _drain(self.adopt_iter(source, dest))

    def adopt_iter(self, source: str | Path,
                   dest: str | None = None) -> IngestSteps:
        """One document per step (G.10); `adopt` is exactly "drain this".

        The source root is recorded before the first step, not after the
        last: a run abandoned at any yield — a crash, a cancel (J.9) —
        leaves the stepped files planted and committed, and the recorded
        root is what lets `sync` finish the remainder instead of the
        operator starting over.
        """
        dest = normalize_dest(dest)
        src, remote = self._open_source(source)
        self._remote_source = remote
        entries = ({e["rel"]: e for e in remote.entries} if remote is not None
                   else None)
        rels = (list(entries)
                if entries is not None
                else [f.relative_to(src).as_posix() for f in self._walk(src)])
        if not self.dry_run:
            # G.3.1 rule 8: the recorded root is the URI, written BEFORE the
            # first step, so G.10's abandonment rule and J.9's "recovery is
            # `sync`, not archaeology" work unchanged.
            self.config["source_root"] = (remote.uri if remote is not None
                                          else src.as_posix())
            if dest:
                self.config["dest"] = dest
            if remote is not None and not self.config.get("content"):
                # G.7 rule 7: `cached` is the default for a remote source —
                # the body is a function of source and converter, the source
                # is durable and addressed, and keeping ten thousand
                # converted bodies in git buys versioning of text nobody
                # wrote.
                self.config["content"] = "cached"
            self._plan_bucketing(rels, src, entries)
            self._save_config()
        report = IngestReport()

        def steps():
            for i, rel in enumerate(rels):
                before = _counts(report)
                entry = entries.get(rel) if entries is not None else None
                f = self._materialise(src, rel, entry)
                try:
                    self._ingest_file(src, f, dest, report, entry=entry)
                finally:
                    self._release(f, entry)
                yield _step(rel, i + 1, len(rels), report, before,
                            committed=i + 1 - len(self._batch))
            self._flush_batch(report)
            return report.as_dict()

        return IngestSteps(len(rels), steps(), report)

    # -- G.3.2 auto-bucketing ------------------------------------------------

    def _plan_bucketing(self, rels: list[str], src: Path,
                        entries: dict | None) -> None:
        """Record how a too-wide directory or prefix was grouped (G.3.2).

        Decided ONCE, at adopt, and written into `gardener.yaml` — and the
        RECORDED rule wins on every later `sync`. A file arriving tomorrow
        lands where today's files went even when the set has grown past the
        point where a different rule would now be chosen; otherwise a refresh
        would silently start planting siblings into a second branch, and no
        primitive relocates a node (J.5.7).
        """
        above = bucket_above()
        if above <= 0:
            return
        recorded = dict(self.config.get("bucketing") or {})
        by_dir: dict[str, list[str]] = {}
        for rel in rels:
            path = PurePosixPath(rel)
            by_dir.setdefault(str(path.parent) if path.parent.name or
                              str(path.parent) != "." else "", []).append(rel)
        for folder, members in by_dir.items():
            folder = "" if folder == "." else folder
            if folder in recorded or len(members) <= above:
                continue
            names = [PurePosixPath(r).name for r in members]
            created = {}
            for rel in members:
                name = PurePosixPath(rel).name
                created[name] = self._created_of(src, rel,
                                                 (entries or {}).get(rel))
            rule = choose_bucketing(names, created, above)
            if rule:
                recorded[folder] = {"rule": rule, "above": above}
        if recorded != (self.config.get("bucketing") or {}):
            self.config["bucketing"] = recorded

    def _created_of(self, src: Path, rel: str, entry: dict | None) -> str:
        """The date a passport would carry: the object's `LastModified` for a
        bucket, the file's mtime for a directory — the SAME value, so the
        grouping and C.13's windows agree by construction."""
        try:
            if entry is not None:
                stamp = entry.get("last_modified")
                if stamp is not None and hasattr(stamp, "strftime"):
                    return stamp.strftime("%Y-%m-%d")
                return ""
            return dt.date.fromtimestamp((src / rel).stat().st_mtime).isoformat()
        except (OSError, ValueError, OverflowError):
            return ""

    def _placement(self, rel: Path, src: Path, entry: dict | None) -> Path:
        """Where this document's node lives — `rel`, or `rel` under a group.

        The placement is the only thing auto-bucketing changes: `source_path`
        stays the true relative path, because it is the sync key and a
        grouping is not provenance.
        """
        recorded = self.config.get("bucketing") or {}
        folder = rel.parent.as_posix()
        folder = "" if folder == "." else folder
        rule = (recorded.get(folder) or {}).get("rule")
        if not rule:
            return rel
        created = self._created_of(src, rel.as_posix(), entry)
        group = slugify(_group_key(rule, rel.name, created)) or "other"
        return rel.parent / group / rel.name

    def _ingest_file(self, src: Path, f: Path, dest: str | None,
                     report: IngestReport, *, entry: dict | None = None) -> None:
        rel = f.relative_to(src)
        ext = f.suffix.lower()
        claimants = [c for c in self.converters if ext in c.extensions]
        if not claimants:
            report.unsupported.append(rel.as_posix())
            return
        self._stage(rel.as_posix(), STAGE_CONVERT)
        # G.5.1: a converter that fails falls THROUGH, not out — the next
        # claimant in discovery order gets the file (a describer whose
        # endpoint is down falls back to the stub), and every failure lands
        # in the report's errors, naming who failed on what. Only when the
        # LAST claimant fails does the file take the terminal error path,
        # with the message shape it always had (G.2: a broken converter
        # never crashes adopt).
        conversion = None
        for conv_obj in claimants:
            terminal = conv_obj is claimants[-1]
            try:
                conversion = conv_obj.convert(f)
                break
            except VineError as e:
                if terminal:
                    report.errors.append(f"{rel.as_posix()}: {e.message}")
                    return
                report.errors.append(
                    f"{rel.as_posix()}: {type(conv_obj).__name__} failed, "
                    f"falling back: {e.message}")
            except Exception as e:
                if terminal:
                    report.errors.append(f"{rel.as_posix()}: converter error: {e}")
                    return
                report.errors.append(
                    f"{rel.as_posix()}: {type(conv_obj).__name__} failed, "
                    f"falling back: {e}")

        place = self._placement(rel, src, entry)
        branch_id = self._ensure_branch(place.parent, dest, report)
        node_id = self._node_id(place, dest)
        # A real run collides against nodes that now exist; a dry run has to
        # count the drafts too, or two previewed files that slug the same way
        # would both claim the id and only one of them would be right. As of
        # v0.84 the OPEN BATCH counts the same way: a node queued and not yet
        # committed does not exist on disk, and two documents slugging alike
        # inside one batch would both claim the id — which C.7.4 then refuses
        # for the whole batch, a refusal produced by the batching and by
        # nothing the operator did.
        taken = self.forest.exists(node_id) or node_id in self._batch_ids or (
            self.dry_run and any(d["id"] == node_id for d in report.drafts))
        if taken:
            node_id = f"{node_id}-{hashlib.sha256(rel.as_posix().encode()).hexdigest()[:6]}"

        st = f.stat()
        source_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        origin = self._origin_for(f, rel.as_posix())
        is_text_source = ext in MarkdownConverter.extensions
        # G.5.1: media is typed off the SOURCE, not off what the converter
        # returned — a describer and the stub both hand back markdown, and
        # the passport has to say `media` either way.
        is_media_source = is_media_ext(ext)
        draft: dict = {
            "id": node_id,
            "parent": branch_id,
            "title": conversion.title,
            "source": "ingest",
            "confidence": INGEST_CONFIDENCE,
            "source_path": rel.as_posix(),
            "source_hash": source_hash,
            # G.8 fast-path: sync skips hashing when both still match
            "source_size": st.st_size,
        }
        if entry is None:
            draft["source_mtime"] = round(st.st_mtime, 3)
        else:
            # G.3.1 rule 5: the store's own change signal in place of an
            # mtime no store will promise. An ETag is NOT a content hash —
            # a multipart upload's is a digest of digests — so it decides
            # whether to spend the download and never whether the bytes are
            # the same; `source_hash` still answers that, on the bytes.
            draft["source_etag"] = entry.get("etag") or ""
        # G.2.6 (v0.54): part of the draft build, so adopt derives them and
        # sync recomputes rather than erases. Curation never touches them.
        aliases = derive_aliases(rel, self.config.get("aliases") or {},
                                 title=conversion.title)
        if aliases:
            draft["aliases"] = aliases
        # G.2.7 (v0.58): the one writer who always KNOWS the origin.
        if origin:
            draft["origin"] = origin
        if conversion.kind == "dataset":
            # The map goes in here rather than being left to C.7.1's auto
            # manual, because curation runs BEFORE the plant and G.4.6 reads
            # it. Same text either way — plant keeps a caller-provided
            # manual verbatim — so the body a reader sees is unchanged.
            draft.update({
                "type": "dataset",
                "schema": conversion.schema,
                "rows": conversion.rows,
                "body": f"# {conversion.title}\n\n" + dataset_map(
                    {t: {c: ty.upper() for c, ty in s["columns"].items()}
                     for t, s in (conversion.schema or {}).items()},
                    conversion.rows,
                    {t: len(r) for t, r in (conversion.rows or {}).items()}),
                "summary": self._dataset_summary(conversion),
            })
        elif conversion.kind == "payload":
            # G.2.2: the source IS the payload. The body carries the map
            # here rather than letting C.7.1 generate it — plant is not
            # creating this database and has never read it.
            draft.update({
                "type": "dataset",
                "payload_type": "sqlite",
                "body": f"# {conversion.title}\n\n"
                        + dataset_map(conversion.tables or {}, conversion.samples,
                                      conversion.counts),
                "summary": self._dataset_summary(conversion),
            })
        else:
            # G.5.1 typing rule: text source -> note; an image/audio source
            # -> media; every other converted format -> document.
            draft.update({
                "type": ("note" if is_text_source
                         else "media" if is_media_source else "document"),
                "body": conversion.markdown,
                "summary": derive_summary(conversion.markdown, conversion.title),
            })
        # G.3.1 rule 7 (v0.84): the bucket is the BONE. A source the store
        # keeps durably is REFERENCED, not copied — the object's own URI is
        # the payload, resolved on first use through G.9's hash-validated
        # cache. This is what makes a ten-thousand-document forest hold zero
        # bytes of anybody's original.
        if entry is not None and conversion.kind != "dataset":
            ptype = PAYLOAD_TYPE_BY_EXT.get(ext)
            if conversion.kind == "payload" or ptype:
                draft.update({
                    "payload": self._remote_source.object_uri(rel.as_posix()),
                    "payload_type": ptype or "sqlite",
                    "payload_hash": source_hash,
                })
        # G.2.8 (v0.84): a converter may answer with a TREE, and then this
        # file is a branch and its parts rather than one node. Everything
        # above is shared — the id this rule would have given the single
        # node is the branch's own — and everything below belongs to a leaf.
        if conversion.kind == "tree":
            self._ingest_tree(
                conversion, rel=rel, node_id=node_id, parent_id=branch_id,
                f=f, src=src, entry=entry, st=st, source_hash=source_hash,
                origin=origin, is_text_source=is_text_source,
                is_media_source=is_media_source, report=report)
            return
        # G.7 rule 5 (v0.84): lossiness decides. A durable source is still
        # referenced and not copied; a lossy conversion whose source this
        # ingest consumes keeps its original wherever J.19.6 resolves to.
        if self._archive_needed(ext, conversion.kind,
                                self._source_is_consumed(f)):
            payload, ptype, phash = self._archive(f, branch_id, report=report,
                                                  rel=rel.as_posix())
            # A dataset's payload is its own `.db` (G.2.2 rule 6): under
            # `archive: always` the spreadsheet is kept and NOT referenced,
            # or the archived original would displace the database the node
            # is read through.
            if conversion.kind != "dataset" and ptype:
                draft.update({"payload": payload, "payload_type": ptype,
                              "payload_hash": phash})

        # J.8 (v0.48): the address is stamped after the summary derived —
        # a URL is not scent, and locate's 60 tokens are too few to spend
        # on one — but before curation and the content policy, so the
        # Curator reads what a reader will and a cached body carries its
        # address too.
        if conversion.kind == "markdown":
            draft["body"] = self._with_provenance(draft["body"], rel.as_posix())

        # curation sees the FULL converted text (G.7.4)…
        self._stage(rel.as_posix(), STAGE_CURATE)
        draft = self._curate(draft, report)
        # …and only then the content policy slims the node (G.7)
        if conversion.kind == "markdown":
            draft = self._apply_content_policy(draft, conversion.title,
                                               is_text_source,
                                               staged=self._is_staged(f),
                                               report=report)
        if self.dry_run:
            report.drafts.append(draft)
            return
        self._stage(rel.as_posix(), STAGE_PLANT)
        installed: Path | None = None
        try:
            if conversion.kind == "payload" and entry is None:
                installed = self._install_payload(node_id, f)
                draft["payload"] = installed.name
                draft["payload_hash"] = source_hash
            # G.2.5: the Gardener is trusted infrastructure adopting a
            # source that already exists, not a model declaring a schema —
            # so the C.7.1 count limits do not bind it. Names and types are
            # validated exactly as they are for everyone else.
            #
            # G.10.2 rule 3 (v0.84): a dataset cannot join a batch (C.7.4
            # rule 6 — a payload birth mid-batch has no rollback story), so
            # it closes the open batch, plants by itself, and the next batch
            # starts empty.
            if draft.get("type") == "dataset":
                self._flush_batch(report)
                self.vine.plant(draft, adopted=True)
                report.planted.append(node_id)
            else:
                self._queue_plant(draft, rel.as_posix(), report)
        except VineError as e:
            # C.7's atomicity extends to the copy (G.2.2 rule 5): a payload
            # whose passport was refused is a file nothing references.
            if installed is not None:
                installed.unlink(missing_ok=True)
            report.errors.append(f"{rel.as_posix()}: {e.message}")
        except Exception:
            if installed is not None:
                installed.unlink(missing_ok=True)
            raise

    # -- G.2.8 a document that becomes a branch ------------------------------

    def _provenance_fields(self, rel: Path, source_hash: str, st,
                           origin: str | None, entry: dict | None) -> dict:
        """G.2.8 rule 6: what EVERY node of one document records.

        The same five values on the branch and on every part — they describe
        the one file all of them came from, and the forest is still the sync
        state.
        """
        fields = {
            "source_path": rel.as_posix(),
            "source_hash": source_hash,
            "source_size": st.st_size,
        }
        if entry is None:
            fields["source_mtime"] = round(st.st_mtime, 3)
        else:
            fields["source_etag"] = entry.get("etag") or ""
        if origin:
            fields["origin"] = origin
        return fields

    def _child_type(self, is_text_source: bool, is_media_source: bool) -> str:
        """G.2.8 rule 3: the SOURCE types a part, exactly as it would have
        typed the single node. The kind of the conversion never types a
        node."""
        return ("note" if is_text_source
                else "media" if is_media_source else "document")

    def _branch_body(self, markdown: str, title: str,
                     report: IngestReport) -> str:
        """The document's own front matter ABOVE the A.5 generated sections."""
        text, demoted = demote_index_headings(markdown or f"# {title}")
        report.headings_demoted += demoted
        text = text.rstrip() or f"# {title}"
        return (f"{text}\n\n## {indexer.SUBBRANCH_SECTION}\n\n"
                f"## {indexer.BANANAS_SECTION}\n\n## Cross trails\n")

    def _ingest_tree(self, conversion: Conversion, *, rel: Path, node_id: str,
                     parent_id: str, f: Path, src: Path, entry: dict | None,
                     st, source_hash: str, origin: str | None,
                     is_text_source: bool, is_media_source: bool,
                     report: IngestReport) -> None:
        """Plant one document as a branch and its parts (G.2.8)."""
        problem = validate_tree(conversion)
        if problem:
            # Reported exactly as every other conversion failure is (G.2):
            # the error names the file, the document is NOT planted, and the
            # rest of the batch proceeds.
            report.errors.append(f"{rel.as_posix()}: tree conversion refused "
                                 f"— {problem}")
            return

        branch_id = f"{node_id}/_index"
        provenance = self._provenance_fields(rel, source_hash, st, origin,
                                             entry)
        markdown = self._with_provenance(conversion.markdown or "",
                                         rel.as_posix())
        branch = {
            "id": branch_id,
            "type": "branch",
            "parent": parent_id,
            "title": conversion.title,
            # Rule 8: derived deterministically at ingest and REPLACED by the
            # G.4.4 rollup when curation runs — the branch is
            # `source: ingest`, so rollup's scope covers it with nothing
            # added.
            "summary": derive_summary(markdown, conversion.title),
            "source": "ingest",
            "confidence": INGEST_CONFIDENCE,
            "body": self._branch_body(markdown, conversion.title, report),
            **provenance,
        }
        # Rule 6: derived aliases belong to the DOCUMENT's node alone.
        # Copying a document's code onto 200 chapters would make
        # `locate("BE-291")` answer with 200 results of equal weight.
        aliases = derive_aliases(rel, self.config.get("aliases") or {},
                                 title=conversion.title)
        if aliases:
            branch["aliases"] = aliases
        # Rule 10: the original is archived ONCE and named by the BRANCH.
        ext = f.suffix.lower()
        if entry is not None:
            ptype = PAYLOAD_TYPE_BY_EXT.get(ext)
            if ptype:
                branch.update({
                    "payload": self._remote_source.object_uri(rel.as_posix()),
                    "payload_type": ptype, "payload_hash": source_hash})
        elif self._archive_needed(ext, conversion.kind,
                                  self._source_is_consumed(f)):
            payload, ptype, phash = self._archive(f, parent_id, report=report,
                                                  rel=rel.as_posix())
            if ptype:
                branch.update({"payload": payload, "payload_type": ptype,
                               "payload_hash": phash})

        # Rule 7: the dialect is checked ONCE, before the batch is built — a
        # rel refused inside a batch refuses the whole batch (C.7.4 rule 1),
        # and the document is not what is wrong.
        sequenced = "succeeds" in self.vine.forest.dialect.rels
        if not sequenced:
            report.sequence_skipped.append(branch_id)

        child_type = self._child_type(is_text_source, is_media_source)
        children: list[dict] = []
        previous: str | None = None
        for n, part in enumerate(conversion.children, start=1):
            part_no = f"{n:0{TREE_PART_WIDTH}d}"
            child_id = f"{node_id}/{part_no}-{slugify(str(part['title']))}"
            body = str(part["markdown"])
            draft = {
                "id": child_id,
                "type": child_type,
                "parent": branch_id,
                "title": str(part["title"]),
                "summary": derive_summary(body, str(part["title"])),
                "source": "ingest",
                "confidence": INGEST_CONFIDENCE,
                "body": body,
                "source_part": part_no,
                **provenance,
            }
            # Rule 6: a child derives aliases from its own TITLE only.
            own = derive_aliases(Path(f"{part_no}.md"),
                                 self.config.get("aliases") or {},
                                 title=str(part["title"]))
            if own:
                draft["aliases"] = own
            if sequenced and previous is not None:
                # Rule 7: confidence 1.0 is the order the converter READ out
                # of the file, not a proposal — so it carries no link-level
                # confidence at all and Part H never manages it.
                draft["links"] = [{"rel": "succeeds", "target": previous}]
            # Rule 8: each part is curated on its OWN full text (G.7.4).
            self._stage(rel.as_posix(), STAGE_CURATE)
            draft = self._curate(draft, report)
            draft = self._apply_content_policy(
                draft, str(part["title"]), is_text_source,
                staged=self._is_staged(f), report=report)
            children.append(draft)
            previous = child_id

        if self.dry_run:
            report.drafts.append(branch)
            report.drafts.extend(children)
            return

        self._stage(rel.as_posix(), STAGE_PLANT)
        # Rule 9: the branch is planted BEFORE its children, so every child's
        # parent exists when it is rehearsed and a crash between two commits
        # leaves the planted prefix — nothing points at a node that does not
        # exist except a `succeeds` the next batch will create.
        self._flush_batch(report)
        try:
            self.vine.plant(branch, adopted=True)
        except VineError as e:
            report.errors.append(f"{rel.as_posix()}: {e.message}")
            return
        report.branches.append(branch_id)
        report.planted.append(branch_id)
        for draft in children:
            self._queue_plant(draft, rel.as_posix(), report)

    def _sync_tree(self, conversion: Conversion, branch_id: str, f: Path,
                   new_hash: str, report: IngestReport, rel: str,
                   entry: dict | None, info: dict) -> None:
        """G.2.8 rule 11: reconcile by part, and delete nothing.

        The identity is (`source_path`, `source_part`) — never the title and
        never the id, because a converter that renamed a chapter must not
        renumber the forest.
        """
        problem = validate_tree(conversion)
        if problem:
            report.errors.append(f"{rel}: tree conversion refused — {problem}")
            return
        node_id = branch_id[: -len("/_index")]
        parts = dict(info.get("parts") or {})
        st = f.stat()
        origin = self._origin_for(f, rel)
        provenance = self._provenance_fields(Path(rel), new_hash, st, origin,
                                             entry)
        sequenced = "succeeds" in self.vine.forest.dialect.rels
        if not sequenced:
            report.sequence_skipped.append(branch_id)

        branch = self.forest.read(branch_id)
        is_text_source = f.suffix.lower() in MarkdownConverter.extensions
        child_type = self._child_type(is_text_source,
                                      is_media_ext(f.suffix.lower()))
        order: list[str] = []
        for n, part in enumerate(conversion.children, start=1):
            part_no = f"{n:0{TREE_PART_WIDTH}d}"
            known = parts.pop(part_no, None)
            body = str(part["markdown"])
            if known is not None:
                # A refresh NEVER curates (G.3): the summary, the tags, the
                # links somebody approved stay — and the title stays with
                # them, because a title is curated frontmatter and the id,
                # which carries the old slug, is immutable.
                order.append(known["id"])
                self._refresh_part(known["id"], body, provenance, report)
                continue
            child_id = f"{node_id}/{part_no}-{slugify(str(part['title']))}"
            draft = {
                "id": child_id, "type": child_type, "parent": branch_id,
                "title": str(part["title"]),
                "summary": derive_summary(body, str(part["title"])),
                "source": "ingest", "confidence": INGEST_CONFIDENCE,
                "body": body, "source_part": part_no, **provenance,
            }
            draft = self._curate(draft, report)
            draft = self._apply_content_policy(
                draft, str(part["title"]), is_text_source,
                staged=self._is_staged(f), report=report)
            self._queue_plant(draft, rel, report)
            order.append(child_id)
        # A part the forest has and the new tree does not is reported and NOT
        # deleted — the Gardener never deletes nodes (G.3), and what a
        # tombstone is remains the Ranger's question.
        for leftover in parts.values():
            report.stale.append(leftover["id"])
        self._flush_batch(report)
        if sequenced:
            self._rewrite_sequence(order, report)

        # The branch's own body is rewritten from the new tree's markdown
        # exactly as a leaf's body is from a new conversion; the A.5 sections
        # are the indexer's and are refreshed by the plants, as always.
        markdown = self._with_provenance(conversion.markdown or "", rel)
        fm = dict(branch.frontmatter)
        fm.update(provenance)
        fm["updated"] = dt.date.today().isoformat()
        body = self._branch_body(markdown, str(fm.get("title") or ""), report)
        for section in (indexer.SUBBRANCH_SECTION, indexer.BANANAS_SECTION,
                        "Cross trails"):
            kept = extract_section(self.forest.read(branch_id).body, section)
            if kept:
                content = "\n".join(kept.splitlines()[1:]).strip()
                replaced = replace_section(body, section, content)
                if replaced is not None:
                    body = replaced
        assert branch.path is not None
        branch.path.write_text(serialize_node(fm, body), encoding="utf-8",
                               newline="\n")
        self.vine.git.commit([branch.path], f"gardener(sync): {branch_id}")
        self.vine.catalog.upsert_node(self.forest.read(branch_id))
        report.updated.append(branch_id)

    def _refresh_part(self, node_id: str, body: str, provenance: dict,
                      report: IngestReport) -> None:
        """One part, refreshed in place — id kept, curated scent kept."""
        node = self.forest.read(node_id)
        fm = dict(node.frontmatter)
        fm.update(provenance)
        fm["source_part"] = node.frontmatter.get("source_part")
        fm["updated"] = dt.date.today().isoformat()
        if fm.get("content") == "cached":
            self._write_body_cache(node_id, body)
            new_body = node.body
        else:
            new_body = body
        assert node.path is not None
        if node.path.read_text(encoding="utf-8") == serialize_node(fm, new_body):
            report.unchanged.append(node_id)
            return
        node.path.write_text(serialize_node(fm, new_body), encoding="utf-8",
                             newline="\n")
        self.vine.git.commit([node.path], f"gardener(sync): {node_id}")
        self.vine.catalog.upsert_node(self.forest.read(node_id))
        self.vine.catalog.mark_stale(node_id)
        report.updated.append(node_id)

    def _rewrite_sequence(self, order: list[str], report: IngestReport) -> None:
        """The sequence, recomputed over the parts the source NOW has.

        Through the ONE audited `.md`-only link write the Ranger's
        promote/prune and the human vote already share (H.2.1 rule 1), with
        the Gardener as its author — because two descriptions of what
        rewriting a link means agree only where somebody compared them.
        """
        previous: str | None = None
        for node_id in order:
            if not self.forest.exists(node_id):
                previous = node_id
                continue
            node = self.forest.read(node_id)
            have = [l for l in (node.frontmatter.get("links") or [])
                    if isinstance(l, dict) and l.get("rel") == "succeeds"]
            want = {"rel": "succeeds", "target": previous} if previous else None
            for link in have:
                if want is None or link.get("target") != previous:
                    rewrite_link(self.vine, node_id, link, remove=True,
                                 by="gardener")
            if want is not None and not any(
                    l.get("target") == previous for l in have):
                rewrite_link(self.vine, node_id, want, add=True,
                             by="gardener")
            previous = node_id

    def _install_payload(self, node_id: str, source: Path) -> Path:
        """G.2.2 rule 2: the source database, copied beside its passport
        under the bare `<leaf>.db` name a C.7.1 birth would have used."""
        node_path = self.forest.path_for(node_id)
        db = node_path.parent / f"{node_path.stem}.db"
        if db.exists():
            raise VineError(
                E_SCHEMA, f"payload already exists: {db.name}",
                hint="An adopted database never overwrites a payload.")
        db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, db)
        return db

    @staticmethod
    def _refresh_map(body: str, tables: dict, samples: dict | None,
                     counts: dict | None) -> str:
        """G.2.3 rule 4: rewrite the two generated sections and only those.

        A payload that changed under a sample that did not is a stale claim
        with a commit behind it — and a curator's own headings in the same
        body are not the Gardener's to overwrite, so this replaces section
        by section instead of replacing the body.
        """
        fresh = dataset_map(tables, samples, counts)
        manual = extract_section(fresh, MANUAL_SECTION) or ""
        sample = extract_section(fresh, SAMPLE_SECTION) or ""
        for header, section in ((MANUAL_SECTION, manual), (SAMPLE_SECTION, sample)):
            content = "\n".join(section.splitlines()[1:]).strip()
            updated = replace_section(body, header, content)
            body = updated if updated is not None else append_section(
                body, header, content)
        return body

    def _apply_content_policy(self, draft: dict, title: str,
                              is_text_source: bool,
                              staged: bool = False,
                              report: IngestReport | None = None) -> dict:
        policy = self.config.get("content", "inline")
        if policy == "reference" and not is_text_source:
            policy = "cached"  # converted bodies must live SOMEWHERE local
        if policy == "reference" and self._remote_source is not None:
            # G.7 rule 7 (v0.84): rule 1 resolves a `reference` body from
            # `source_root/source_path` at every `pick`, which for a bucket
            # is a network round trip inside `pick`'s own budget. Degraded,
            # and counted — J.8's lesson that a silent downgrade reads as a
            # feature that does not work.
            policy = "cached"
            if report is not None:
                report.content_degraded += 1
        if policy == "reference" and staged:
            # J.8 (v0.61), the same reasoning one step further: a
            # `reference` body is read back from its source at every
            # `pick`, and a staged upload's source is a courier the forest
            # itself may discard. A body addressed to a courier is a body
            # that vanishes.
            policy = "cached"
        if policy == "cached":
            self._write_body_cache(draft["id"], draft["body"])
            draft["body"] = f"# {title}"
            draft["content"] = "cached"
        elif policy == "reference":
            draft["body"] = f"# {title}"
            draft["content"] = "reference"
        return draft

    def _write_body_cache(self, node_id: str, body: str) -> None:
        if self.dry_run:
            return
        p = self.forest.body_cache_path(node_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")

    def _node_id(self, rel: Path, dest: str | None) -> str:
        parts = [slugify(p) for p in rel.parent.parts]
        prefix = [] if not dest else [dest]
        return "/".join(prefix + parts + [slugify(rel.stem)])

    @staticmethod
    def _dataset_summary(conversion: Conversion) -> str:
        """G.2.3 rule 5: the scent names the tables, not just the first one.

        A twelve-table database summarised as "table X with 6 rows" is a
        scent for the wrong thing — `locate` reads this and nothing else
        about the node.
        """
        if conversion.kind == "payload":
            tables = conversion.tables or {}
            counts = conversion.counts or {}
        else:
            tables = {t: spec["columns"] for t, spec in (conversion.schema or {}).items()}
            counts = {t: len(rows) for t, rows in (conversion.rows or {}).items()}
        named = [f"{t} ({rows_label(counts.get(t, 0))})" for t in list(tables)[:4]]
        more = len(tables) - len(named)
        listing = ", ".join(named) + (f", +{more} more" if more > 0 else "")
        noun = "table" if len(tables) == 1 else f"{len(tables)} tables"
        summary = (f"Tabular data '{conversion.title}': {noun} "
                   f"{listing}. Adopted from source; pending curation.")
        try:
            validate_summary(summary)
        except VineError:
            summary = (f"Tabular data '{conversion.title}' with {len(tables)} "
                       f"table(s). Adopted from source; pending curation.")
        return summary

    # -- sync (G.3) ----------------------------------------------------------

    def _passports(self) -> dict[str, dict]:
        """source_path -> {id, hash, size, mtime}, read from the forest itself
        (the forest IS the sync state — no side bookkeeping to drift)."""
        out: dict[str, dict] = {}
        for nid in self.forest.iter_ids():
            try:
                node = self.forest.read(nid)
            except VineError:
                continue
            fm = node.frontmatter
            if not fm.get("source_path"):
                continue
            rel = str(fm["source_path"])
            facts = {
                "id": nid,
                "hash": str(fm.get("source_hash", "")),
                "size": fm.get("source_size"),
                "mtime": fm.get("source_mtime"),
                # G.3.1 rule 5 (v0.84): the store's own change signal,
                # absent for every directory-adopted node.
                "etag": fm.get("source_etag"),
            }
            entry = out.setdefault(rel, {})
            part = fm.get("source_part")
            if part is None:
                # The document's own node. It WINS the top-level facts
                # whatever order the walk met the nodes in.
                entry.update(facts)
            else:
                # G.2.8 rule 11 (v0.84): a tree makes every node share one
                # `source_path`, so keying on that alone collapsed the whole
                # document to whichever node the walk read last. The parts
                # are keyed by `source_part` — the one field that lets a
                # refresh address one part of one file.
                entry.setdefault("parts", {})[str(part)] = facts
                for key, value in facts.items():
                    entry.setdefault(key, value)
        return out

    # -- J.13.6 re-derivation (v0.61) ---------------------------------------

    # J.13.6 rule 5: the closed list. `aliases` (v0.61) is arithmetic on
    # committed material; `scent` (J.13.6.1, v0.75) is the one member
    # allowed a model call, and it says so here rather than quietly
    # widening rule 1.
    DERIVABLE = ("aliases", "scent")
    # …and the half `recurate()` itself can answer. `scent` is one model
    # call per node, so it is a J.9 job with its own entry point
    # (`recurate_scent_iter`) and never a synchronous wait.
    SYNCHRONOUS = ("aliases",)

    def recurate(self, derive: list[str] | None = None) -> dict:
        """J.13.6: re-derive from the forest's own passports.

        `reindex` repairs what FINDS a node; `sync` repairs what a node
        SAYS by re-reading its source. Between them sits the repair neither
        performs: a derivation rule that improved after the material was
        ingested. Every input to alias derivation — the source path, the
        title — is already in the passport, so this needs no source tree,
        no converter, no model and no network. Yet the only path to it was
        `sync`, which resolves a recorded host root and requires `admin`
        over a directory the Station may no longer be able to read: a
        forest of 1,877 nodes had the v0.59 feature in the code and not in
        the corpus, which is the only place it counts.

        Union semantics are `sync`'s (G.2.6 rule 3): missing derived forms
        are added, hand-written ones are never displaced, the cap never
        evicts, overflow is counted. A node with nothing to add is not
        rewritten and not committed, so a second pass reports no change.

        Only nodes carrying `source_path` are visited: alias derivation is
        the ingest rule (G.2.6), and deriving from a hand-planted node's id
        would be a different rule wearing this one's name.
        """
        wanted = list(derive or ["aliases"])
        unknown = [d for d in wanted if d not in self.DERIVABLE]
        if unknown:
            raise VineError(
                E_SCHEMA,
                f"cannot derive '{unknown[0]}' from passports alone",
                hint=f"`derive` accepts: {', '.join(self.DERIVABLE)}. "
                     "`origin` is the source file's own address, which this "
                     "pass does not have and must not guess (G.2.7 rule 2).")
        deferred = [d for d in wanted if d not in self.SYNCHRONOUS]
        if deferred:
            # Rule 1 is a guarantee about THIS method: passport arithmetic,
            # no model, no network. `scent` is the member that is allowed a
            # model call, so it does not run here — folding it in would
            # make rule 1 a sentence about a method that no longer holds it.
            raise VineError(
                E_SCHEMA,
                f"'{deferred[0]}' is not derived from the passports",
                hint="Re-curating the scent (J.13.6.1) is one model call per "
                     "node, so it is a J.9 job: use `recurate_scent_iter` "
                     "(the Station serves it on the same route, answering "
                     "202 with a job record).")
        report = IngestReport()
        scanned = 0
        for rel, info in sorted(self._passports().items()):
            scanned += 1
            node_id = info["id"]
            merged = self._merge_aliases(node_id, rel, report)
            if merged is None:
                report.unchanged.append(node_id)
                continue
            if self.dry_run:
                report.updated.append(node_id)
                continue
            node = self.forest.read(node_id)
            fm = dict(node.frontmatter)
            fm["aliases"] = merged
            assert node.path is not None
            node.path.write_text(serialize_node(fm, node.body),
                                 encoding="utf-8", newline="\n")
            self.vine.git.commit([node.path], f"recurate(aliases): {node_id}")
            self.vine.catalog.upsert_node(self.forest.read(node_id))
            report.updated.append(node_id)
        out = report.as_dict()
        out["derived"] = wanted
        out["scanned"] = scanned
        out["changed"] = len(report.updated)
        return out

    # -- J.13.6.1 re-curating the scent (v0.75) -----------------------------

    def scent_scope(self, order: str = "created",
                    limit: int | None = None) -> list[str]:
        """The nodes a `derive: ["scent"]` pass would visit, in order.

        Eager and cheap — one indexed catalog read, no body opened — because
        J.13.6.1 rule 5 makes this count the STARTING response's job: it is
        the number of model calls the operator is about to pay for, and a
        cost stated after it is spent is not a cost that was stated.

        Three exclusions, each for its own reason:

        * `_meta/` — the forest's own schema and configuration are not
          material anybody navigates by scent.
        * **branches** — a branch's summary is G.4.4's rollup, computed
          bottom-up from its children's ENTRY LINES and never from a body.
          Curating one from the index render would put a document's
          machinery where a region's answer belongs, and it would fight the
          rollup on the next ingest.
        * **nodes the Gardener did not plant** (`source != "ingest"`). This
          pass REPLACES the summary (rule 3), and a summary somebody typed
          is curation a human wrote — the very thing rule 3 protects tags
          and aliases from. G.4.4 draws the same line for the same reason
          ("the Gardener rewrites what the Gardener planted, nothing else").

        Datasets are IN, and deliberately: G.4.6 curates a dataset from its
        G.2.3 map, the map is the passport's own body, and re-reading it
        costs the same few hundred tokens whether the payload is 5 MB or
        5 GB. Nothing here writes a dataset's body — the two generated
        sections stay the Gardener's (G.4.6 rule 3).

        **The order is chosen, and it is `created` by default (rule 8,
        v0.84).** It used to be id order, which is alphabetical, which is
        nothing — the order a directory listing happens to be in. `created`
        visits OLDEST first: the material that has been carrying the
        thinnest scent for longest is what this pass exists for, and it is
        the order that makes a partial run legible to the person watching
        it. `heat` visits the HOTTEST first, read from the persistent
        pheromone scope in one statement, so a forest of ten thousand
        documents improves what agents are actually reading before it
        improves what nobody has opened.

        Session heat is excluded — it belongs to one live walk, and a
        maintenance pass steered by whoever happens to be navigating right
        now is not a maintenance pass. A node with no heat row sorts LAST,
        ties break on `created`, and both orders are deterministic: two runs
        over an unchanged forest visit the same nodes in the same sequence,
        which is the only thing that makes `limit` usable.
        """
        if order not in ("created", "heat"):
            raise VineError(
                E_SCHEMA, f"unknown scent order: {order}",
                hint="`order` is 'created' (oldest first, the default) or "
                     "'heat' (hottest first).")
        rows = self.vine.catalog.conn.execute(
            "SELECT id, created FROM nodes WHERE kind != 'branch' "
            "AND source = 'ingest' ORDER BY created, id").fetchall()
        scope = [(r[0], r[1] or "") for r in rows
                 if not r[0].startswith("_meta/")]
        if order == "heat":
            heat = self.vine.trails.heat_all()
            scope.sort(key=lambda item: (-heat.get(item[0], 0.0), item[1],
                                         item[0]))
        ids = [node_id for node_id, _created in scope]
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise VineError(
                    E_SCHEMA, f"limit must be a positive integer, got {limit!r}",
                    hint="`limit` bounds how many nodes the pass visits; "
                         "omit it to visit the whole scope.")
            ids = ids[:limit]
        return ids

    def recurate_scent_iter(self, order: str = "created",
                            limit: int | None = None) -> IngestSteps:
        """J.13.6.1: re-curate every in-scope node, one model call per step.

        The shape is an ingest's, because it IS an ingest-shaped run: the
        scope is walked eagerly so `total` is known before the first model
        call, each `next()` is one whole node, and a consumer that stops
        stepping leaves everything already committed committed.

        What it reads is the node's OWN stored body (rule 1) — inline or
        the `_derived/` cache — never a source tree, never a converter and
        never the network beyond the model itself. A `content: reference`
        body lives in the source tree by definition, so it is skipped
        rather than fetched.
        """
        ids = self.scent_scope(order=order, limit=limit)
        # Rule 9: the bill is the BOUNDED number and the report says what is
        # left, so a second run is a decision rather than a guess. The pass
        # keeps no memory of what it curated — running it twice with the
        # same limit and order re-visits the same nodes and pays for them
        # again, which is stated because it is this feature's sharp edge.
        remaining = (max(len(self.scent_scope(order=order)) - len(ids), 0)
                     if limit is not None else 0)
        report = IngestReport()
        stats = {"fallbacks": 0, "skipped": 0}

        def steps():
            for i, node_id in enumerate(ids):
                before = _counts(report)
                self._recurate_scent(node_id, report, stats)
                yield _step(node_id, i + 1, len(ids), report, before)
            return _scent_dict(report, stats, remaining=remaining)

        out = IngestSteps(len(ids), steps(), report)
        # Read by `scent_result` so a CANCELLED run can still be accounted
        # for: the report is live, and these two counters are the half of it
        # the report has no field for.
        out.scent_stats = stats
        return out

    def recurate_scent(self, order: str = "created",
                       limit: int | None = None) -> dict:
        """`recurate_scent_iter`, drained — the library's own entry point."""
        return _drain(self.recurate_scent_iter(order=order, limit=limit))

    def _stored_body(self, node) -> str | None:
        """The text curation gets, from the forest and nowhere else (rule 1).

        G.7's tiers decide where a body lives: inline is the passport's own,
        `cached` is `_derived/bodies/` (still the forest), and `reference`
        is the SOURCE FILE — which this pass may not open, so it yields
        None and the node is skipped rather than quietly re-read.
        """
        mode = node.frontmatter.get("content")
        if mode == "reference":
            return None
        if mode == "cached":
            cached = self.forest.body_cache_path(node.id)
            if not cached.is_file():
                return None
            return cached.read_text(encoding="utf-8") or None
        return node.body or None

    def _curator_fallbacks(self) -> int:
        """G.4's fallback count across the hooks, read as a running total.

        A hook is an arbitrary callable (G.4 rule 3), so this reads only the
        name it declares and reads it as a DELTA per node: one Curator
        serves the whole pass, and its stats never reset.
        """
        total = 0
        for hook in self.hooks:
            stats = getattr(hook, "stats", None)
            if isinstance(stats, dict):
                total += int(stats.get("fallbacks", 0) or 0)
        return total

    def _recurate_scent(self, node_id: str, report: IngestReport,
                        stats: dict) -> None:
        """One node: curate from its own body, then summary REPLACED and
        tags/aliases UNIONED (J.13.6.1 rule 3).

        The union is not the Curator's politeness — it is enforced here, on
        the values that were on disk before the call. Tags and aliases may
        have been corrected by a person or taught by the operator's
        `aliases:` map, and a model must not delete curation a human wrote;
        removing a bad tag stays a human act with a human's authority
        behind it.
        """
        try:
            node = self.forest.read(node_id)
        except VineError as e:
            report.errors.append(f"{node_id}: {e.message}")
            return
        body = self._stored_body(node)
        if body is None:
            # Nothing for a model to read: the node keeps what it has and
            # nothing is billed for it.
            stats["skipped"] += 1
            report.unchanged.append(node_id)
            return
        fm = node.frontmatter
        was = {
            "summary": str(fm.get("summary") or ""),
            "tags": [t for t in (fm.get("tags") or []) if isinstance(t, str)],
            "aliases": [a for a in (fm.get("aliases") or [])
                        if isinstance(a, str)],
        }
        draft = {
            "id": node_id,
            "title": str(fm.get("title") or ""),
            "type": str(fm.get("type") or "note"),
            "summary": was["summary"],
            "tags": list(was["tags"]),
            "aliases": list(was["aliases"]),
            "body": body,
        }
        if fm.get("lang"):
            # A.3.2 rule 4: where the node states a language, the prompt
            # states it. The passport already carries what ingest inferred,
            # so a re-curation must not ask the model to infer it again and
            # answer in a different one.
            draft["lang"] = fm["lang"]
        self._stage(node_id, STAGE_CURATE)
        spent = self._curator_fallbacks()
        draft = self._curate(draft, report)
        if self._curator_fallbacks() > spent:
            # Rule 4: a model that fails, refuses or answers invalidly leaves
            # the node exactly as it was. A re-curation pass must not be able
            # to leave a forest worse than it found it.
            stats["fallbacks"] += 1
            report.unchanged.append(node_id)
            return

        patch: dict = {}
        summary = str(draft.get("summary") or "")
        if summary and summary != was["summary"]:
            patch["summary"] = summary
        tags = list(was["tags"])
        held = set(tags)
        fresh: list[str] = []
        for tag in draft.get("tags") or []:
            if isinstance(tag, str) and tag not in held:
                held.add(tag)
                tags.append(tag)
                fresh.append(tag)
        if fresh:
            try:
                # G.4.2 rule 6: the rule is enforced where writes enter. The
                # node's own tags are grandfathered by their exact spelling
                # (`was`); anything a hook added is new and answers to it.
                for tag in fresh:
                    validate_tag(tag)
            except VineError as e:
                report.errors.append(f"{node_id}: {e.message}")
                return
            patch["tags"] = tags
        aliases = [a for a in (draft.get("aliases") or []) if isinstance(a, str)]
        for alias in was["aliases"]:
            if alias not in aliases:  # union: a hook may add, never displace
                aliases.append(alias)
        if aliases != was["aliases"]:
            patch["aliases"] = aliases[:MAX_ALIASES]

        if not patch:
            report.unchanged.append(node_id)
            return
        if self.dry_run:
            report.updated.append(node_id)
            return
        self._stage(node_id, STAGE_PLANT)
        try:
            self._write_scent(node, patch)
        except VineError as e:
            report.errors.append(f"{node_id}: {e.message}")
            return
        except Exception as e:  # noqa: BLE001 — one node never fails the pass
            report.errors.append(f"{node_id}: {e}")
            return
        report.updated.append(node_id)

    def _write_scent(self, node, patch: dict) -> None:
        """One `.md` commit per changed node, subject `recurate(scent): <id>`.

        A summary is replicated VERBATIM into every index that lists this
        node (A.5), so the passport is not the only file the write touches —
        a passport rewritten alone would leave the parent index answering
        with the old scent, which is exactly the layer navigation reads
        first. Every touched file is restored on failure: the pass may leave
        a node unchanged, never half-changed.
        """
        assert node.path is not None
        fm = dict(node.frontmatter)
        fm.update(patch)
        fm["updated"] = dt.date.today().isoformat()
        validate_frontmatter(fm, self.forest.dialect, strict_summary=False)
        content = serialize_node(fm, node.body)
        touched: list[tuple[Path, str]] = [
            (node.path, node.path.read_text(encoding="utf-8"))]
        paths = [node.path]
        try:
            node.path.write_text(content, encoding="utf-8", newline="\n")
            if "summary" in patch:
                paths += self.vine._propagate_summary(
                    node.id, str(patch["summary"]), touched)
            self.vine.git.commit(paths, f"recurate(scent): {node.id}")
        except Exception:
            for path, original in reversed(touched):
                path.write_text(original, encoding="utf-8", newline="\n")
            raise
        self.vine.catalog.upsert_node(self.forest.read(node.id))
        for path in paths[1:]:
            self.vine.catalog.upsert_node(
                self.forest.read(self.forest.id_for(path)))

    def unrecorded_sources(self, root: str | Path) -> list[tuple[str, int]]:
        """Files under `root` that no live passport records (J.8, v0.61).

        The question an operator cannot otherwise ask: *what is sitting in
        the staging area that is not a document in this forest?* Every file
        whose relative path is some node's `source_path` is accounted for;
        what is left is a batch that failed, a batch that was cancelled, or
        a document whose node was later pruned — and before this it was
        invisible, so it accumulated and, once, came back to life.

        Returns `(relative path, size)`, sorted. Reads, never removes: the
        caller decides, and this engine deletes no source of its own accord
        (G.3).
        """
        base = Path(root)
        if not base.is_dir():
            return []
        base = base.resolve()
        recorded = set(self._passports())
        out: list[tuple[str, int]] = []
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            try:
                rel = f.resolve().relative_to(base).as_posix()
            except ValueError:  # a symlink pointing out of the tree
                continue
            if rel in recorded:
                continue
            try:
                out.append((rel, f.stat().st_size))
            except OSError:
                continue
        return out

    def _contained_rel(self, src: Path, path: str) -> tuple[str, Path]:
        """A source-root-relative name, resolved and proven to stay inside.

        `relative_to` is lexical, so `../../x` survives the join and comes
        back out as a "relative" path — the file would be read, slugified
        into a `node/` branch and planted. Resolving first is what makes
        the containment real: it collapses `..` and follows symlinks.
        """
        f = (src / Path(path)).resolve()
        if Path(path).is_absolute() or not f.is_relative_to(src):
            raise VineError(
                E_SCHEMA, f"sync path leaves the source root: {path}",
                hint="A targeted sync names a path relative to the "
                     "adopted source root.")
        return f.relative_to(src).as_posix(), f

    def sync(self, source: str | Path | None = None,
             path: str | None = None, dest: str | None = None,
             paths: list[str] | None = None, *, consume: bool = False) -> dict:
        """`dest` overrides the adopted root's destination for files sync
        meets for the FIRST time. Files that already have a passport keep
        the branch they were planted in — sync refreshes content, it never
        moves nodes. Without the override a caller who says where a new
        document goes is silently overruled by whatever the last adopt
        recorded."""
        return _drain(self.sync_iter(source=source, path=path, dest=dest,
                                     paths=paths, consume=consume))

    def sync_iter(self, source: str | Path | None = None,
                  path: str | None = None,
                  dest: str | None = None,
                  paths: list[str] | None = None,
                  *, consume: bool = False) -> IngestSteps:
        """One document per step (G.10); `sync` is exactly "drain this".

        Resolution and containment are eager — a bad source or an escaping
        `path` fails here, before any step — while the passport read joins
        the first step: it reads the forest, and construction touches only
        the filesystem.
        """
        src, remote = self._open_source(source, recorded=True)
        self._remote_source = remote
        entries = ({e["rel"]: e for e in remote.entries} if remote is not None
                   else None)
        dest = normalize_dest(dest) or self.config.get("dest")
        report = IngestReport()

        if path is not None and paths is not None:
            raise VineError(
                E_SCHEMA, "path and paths name the subject twice",
                hint="`path` refreshes one file; `paths` refreshes a named "
                     "set. Pass one.")

        # G.8 targeted sync: one file, the event-trigger building block.
        # J.8 (v0.61): `paths` is the same refresh over a NAMED SET — what an
        # upload sends. The staging area is stable per forest so that
        # re-sending a filename means "this document changed", and pointing
        # the refresh at the DIRECTORY made every file every previous batch
        # ever uploaded a candidate on every upload: a file whose node had
        # been pruned no longer had a passport, so it was not a refresh, it
        # was a new document, and it was planted again. A call may only
        # testify about what it walked.
        named = ([path] if path is not None
                 else (list(paths) if paths is not None else None))
        if named is not None:
            resolved = [self._contained_rel(src, one) for one in named]

            def some():
                passports = self._passports()
                for i, (rel, f) in enumerate(resolved):
                    before = _counts(report)
                    entry = entries.get(rel) if entries is not None else None
                    if entry is not None or f.is_file():
                        self._sync_one(src, f, rel, passports, dest, report,
                                       entry=entry)
                    elif rel in passports:
                        report.stale.append(passports[rel]["id"])
                    else:
                        report.unsupported.append(rel)
                    # J.8.3: a courier's bytes are the only copy in
                    # existence, so this route never defers a commit — the
                    # source is deleted below, and deleting it while the
                    # plant sits in an open batch is exactly the loss that
                    # rule exists to prevent.
                    self._flush_batch(report)
                    step = _step(rel, i + 1, len(resolved), report, before,
                                 committed=i + 1)
                    # J.8 (v0.61): bytes the CALLER declared disposable, and
                    # that became a node, are removed once they have. The
                    # node is the record; the courier does not keep a copy,
                    # and a copy left behind is what a later pass reads as a
                    # document nobody sent. `consume` is keyword-only and
                    # host-supplied (G.2.5's construction): the engine never
                    # decides on its own that a source may be deleted, and a
                    # file that FAILED stays, because it is the evidence.
                    if consume and step["action"] in _LANDED and f.is_file():
                        try:
                            f.unlink()
                            report.consumed.append(rel)
                        except OSError:
                            pass
                    yield step
                return report.as_dict()

            return IngestSteps(len(resolved), some(), report)

        rels = (list(entries) if entries is not None
                else [f.relative_to(src).as_posix() for f in self._walk(src)])

        def steps():
            passports = self._passports()
            seen: set[str] = set()
            for i, rel in enumerate(rels):
                seen.add(rel)
                before = _counts(report)
                entry = entries.get(rel) if entries is not None else None
                self._sync_one(src, src / rel, rel, passports, dest, report,
                               entry=entry)
                yield _step(rel, i + 1, len(rels), report, before,
                            committed=i + 1 - len(self._batch))
            self._flush_batch(report)
            for rel, info in passports.items():
                if rel not in seen:
                    report.stale.append(info["id"])
            return report.as_dict()

        return IngestSteps(len(rels), steps(), report)

    def _sync_one(self, src: Path, f: Path, rel: str, passports: dict,
                  dest: str | None, report: IngestReport, *,
                  entry: dict | None = None) -> None:
        if entry is not None:
            self._sync_one_object(src, rel, passports, dest, report, entry)
            return
        if rel not in passports:
            self._ingest_file(src, f, dest, report)
            return
        info = passports[rel]
        st = f.stat()
        # G.8 fast-path (rsync's trick): same size + mtime -> skip hashing
        if (info.get("size") == st.st_size
                and info.get("mtime") == round(st.st_mtime, 3)):
            self._settle_unchanged(info["id"], rel, report, f)
            return
        new_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        if new_hash == info["hash"]:
            self._settle_unchanged(info["id"], rel, report, f)
            return
        self._update_passport(info["id"], f, new_hash, report, rel, info=info)

    def _sync_one_object(self, src: Path, rel: str, passports: dict,
                         dest: str | None, report: IngestReport,
                         entry: dict) -> None:
        """One object, reconciled (G.3.1 rule 5).

        The fast-path is ETag + size and it decides ONE thing: whether to
        spend the download. An object re-uploaded byte-identically changes
        its ETag, is downloaded, hashes equal and is reported `unchanged`
        with no commit — one wasted download, never a false update.
        """
        info = passports.get(rel)
        if info is not None and info.get("size") == entry.get("size") \
                and (info.get("etag") or "") == (entry.get("etag") or "") \
                and info.get("etag"):
            self._settle_unchanged(info["id"], rel, report, None)
            return
        try:
            f = self._materialise(src, rel, entry)
        except Exception as e:  # noqa: BLE001 - every SDK raises its own
            # G.3.1 rule 10: a store that answers an error is an ERROR, never
            # an absence. `stale` means the source is gone, and a 503 that
            # read as a deletion would eventually invite a pruning pass to
            # act on an outage.
            report.errors.append(f"{rel}: the store refused the object "
                                 f"({type(e).__name__})")
            return
        try:
            if info is None:
                self._ingest_file(src, f, dest, report, entry=entry)
                return
            new_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            if new_hash == info["hash"]:
                self._settle_unchanged(info["id"], rel, report, f)
                return
            self._update_passport(info["id"], f, new_hash, report, rel,
                                  entry=entry, info=info)
        finally:
            self._release(f, entry)

    def _settle_unchanged(self, node_id: str, rel: str,
                          report: IngestReport,
                          f: Path | None = None) -> None:
        """G.2.6 rule 3 (v0.56): the fast-path skips the CONVERSION, not the
        alias check — an `aliases:` map added to the config was invisible to
        every already-ingested file, which is exactly where it was aimed.
        The union adds missing derived forms and removes nothing.

        G.2.7 (v0.58): the same `setdefault` for `origin` — a forest
        ingested before the rule gains origins on its next sync without
        re-conversion."""
        merged = self._merge_aliases(node_id, rel, report)
        node = self.forest.read(node_id)
        settle_origin = None
        if not node.frontmatter.get("origin") and (
                f is not None or self._remote_source is not None):
            settle_origin = self._origin_for(f, rel)
        if merged is None and settle_origin is None:
            report.unchanged.append(node_id)
            return
        if self.dry_run:
            report.updated.append(node_id)
            return
        fm = dict(node.frontmatter)
        if merged is not None:
            fm["aliases"] = merged
        if settle_origin is not None:
            fm["origin"] = settle_origin
        assert node.path is not None
        node.path.write_text(serialize_node(fm, node.body),
                             encoding="utf-8", newline="\n")
        what = "aliases" if merged is not None else "origin"
        self.vine.git.commit([node.path],
                             f"gardener(sync): {what} {node_id}")
        self.vine.catalog.upsert_node(self.forest.read(node_id))
        report.updated.append(node_id)

    def _merge_aliases(self, node_id: str, rel: str,
                       report: IngestReport) -> list[str] | None:
        """Union of the node's aliases with the derived forms; None when
        nothing is missing. Existing aliases are never displaced by the cap
        — derived forms that no longer fit are counted, never silent."""
        node = self.forest.read(node_id)
        derived = derive_aliases(Path(rel), self.config.get("aliases") or {},
                                 title=node.frontmatter.get("title"))
        if not derived:
            return None
        have = [str(a) for a in (node.frontmatter.get("aliases") or [])]
        missing = [a for a in derived if a not in have]
        if not missing:
            return None
        merged = have + missing
        if len(merged) > MAX_ALIASES:
            report.aliases_clipped += len(merged) - MAX_ALIASES
            merged = merged[:MAX_ALIASES]
        if merged == have:
            return None
        return merged

    def _update_passport(self, node_id: str, f: Path, new_hash: str,
                         report: IngestReport, rel: str | None = None, *,
                         entry: dict | None = None,
                         info: dict | None = None) -> None:
        """G.3: refresh body + source_hash via the audited write path —
        curated frontmatter (summary, tags, links, confidence) is preserved.

        No `curate` stage here, and that is the contract rather than an
        omission: a refresh keeps the scent somebody already approved.
        """
        ext = f.suffix.lower()
        claimants = [c for c in self.converters if ext in c.extensions]
        if not claimants:
            report.unsupported.append(node_id)
            return
        self._stage(rel or node_id, STAGE_CONVERT)
        # G.5.1: the fallback chain covers refreshes too — a describer whose
        # endpoint is down during a sync falls back to the stub exactly as it
        # does during adopt. A refresh that errored where an adopt would have
        # planted would make the same file's fate depend on which verb found
        # it.
        conversion = None
        for conv_obj in claimants:
            terminal = conv_obj is claimants[-1]
            try:
                conversion = conv_obj.convert(f)
                break
            except VineError as e:
                if terminal:
                    report.errors.append(f"{node_id}: {e.message}")
                    return
                report.errors.append(
                    f"{node_id}: {type(conv_obj).__name__} failed, "
                    f"falling back: {e.message}")
            except Exception as e:
                if terminal:
                    report.errors.append(f"{node_id}: converter error: {e}")
                    return
                report.errors.append(
                    f"{node_id}: {type(conv_obj).__name__} failed, "
                    f"falling back: {e}")

        # J.8 (v0.48): a refresh rebuilds the body from the converter, so
        # the address is stamped again here — the same line the adopt path
        # appended, through the same helper, or a re-uploaded screenshot
        # would lose where it came from on its first refresh.
        if conversion.kind == "markdown" and rel is not None:
            conversion.markdown = self._with_provenance(conversion.markdown, rel)

        if conversion.kind == "tree" and rel is not None:
            # G.2.8 rule 11: this source is a branch and its parts, not one
            # body. Reconciled per part, and the dry run's own preview is the
            # same "it would be refreshed" one line below.
            if self.dry_run:
                report.updated.append(node_id)
                return
            self._sync_tree(conversion, node_id, f, new_hash, report, rel,
                            entry, info or {})
            return

        if self.dry_run:
            # An update refreshes the body and keeps the curated scent (G.3),
            # so there is no passport to review — reporting that it *would*
            # be refreshed is the whole preview.
            report.updated.append(node_id)
            return

        self._stage(rel or node_id, STAGE_PLANT)
        node = self.forest.read(node_id)
        fm = dict(node.frontmatter)
        fm["source_hash"] = new_hash
        st = f.stat()
        fm["source_size"] = st.st_size
        if entry is None:
            fm["source_mtime"] = round(st.st_mtime, 3)
        else:
            fm["source_etag"] = entry.get("etag") or ""
        fm["updated"] = dt.date.today().isoformat()
        if rel is not None:
            # G.2.6 rule 3 (v0.56): a refresh unions derived aliases in,
            # exactly as the fast-path does for untouched files.
            merged = self._merge_aliases(node_id, rel, report)
            if merged is not None:
                fm["aliases"] = merged
        if not fm.get("origin"):
            # G.2.7 rule 2: only when absent — a hand-written origin
            # outranks a derived one and survives every sync.
            derived_origin = self._origin_for(f, rel or node_id)
            if derived_origin:
                fm["origin"] = derived_origin
        body = node.body

        if conversion.kind == "dataset":
            db = self.forest.payload_path(node)
            db.unlink(missing_ok=True)  # rebuild whole (sync is a bulk load)
            conn = sqlite3.connect(db)
            try:
                from monkeyllm.models import TableSchema, dataset_ddl

                schema = {t: TableSchema.model_validate(s)
                          for t, s in conversion.schema.items()}
                for stmt in dataset_ddl(schema):
                    conn.execute(stmt)
                for tname, table_rows in (conversion.rows or {}).items():
                    if table_rows:
                        ph = ", ".join("?" * len(schema[tname].columns))
                        conn.executemany(f"INSERT INTO {tname} VALUES ({ph})",
                                         [tuple(r) for r in table_rows])
                conn.commit()
            finally:
                conn.close()
            fm["payload_hash"] = hashlib.sha256(db.read_bytes()).hexdigest()
            body = self._refresh_map(
                body,
                {t: {c: ty.upper() for c, ty in s["columns"].items()}
                 for t, s in conversion.schema.items()},
                conversion.rows,
                {t: len(r) for t, r in (conversion.rows or {}).items()})
        elif conversion.kind == "payload":
            # G.2.2 rule 5: the source replaces the payload whole.
            db = self.forest.payload_path(node)
            db.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, db)
            fm["payload_hash"] = new_hash
            body = self._refresh_map(body, conversion.tables or {},
                                     conversion.samples, conversion.counts)
        elif fm.get("content") == "cached":
            self._write_body_cache(node_id, conversion.markdown)  # body stays a stub
        elif fm.get("content") == "reference":
            pass  # the body IS the source; hash bookkeeping above is enough
        else:
            body = conversion.markdown

        # G.5.1: a refreshed media file re-archives under the same condition
        # the adopt path used, or the map and the served bytes disagree — a
        # re-uploaded screenshot would keep serving the OLD image from
        # `_assets/` under a payload_hash that still validates, while the
        # new bytes sit only in disposable staging. The digest names the
        # archived copy, so a changed original lands under a new name and
        # the stale one is removed rather than left to accumulate.
        ext = f.suffix.lower()
        if (conversion.kind not in ("payload", "dataset")
                and self._archive_needed(ext, conversion.kind,
                                         self._source_is_consumed(f))):
            old = fm.get("payload")
            payload, ptype, phash = self._archive(f, node_id, report=report,
                                                  rel=rel)
            if ptype:
                fm.update({"payload": payload, "payload_type": ptype,
                           "payload_hash": phash})
                if old and old != payload and str(old).startswith(f"{ASSETS_DIR}/"):
                    stale = self.forest.path_for(node_id).parent / old
                    try:
                        stale.unlink(missing_ok=True)
                    except OSError:
                        pass  # a lingering copy is untidy, not incorrect

        assert node.path is not None
        node.path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")
        self.vine.git.commit([node.path], f"gardener(sync): {node_id}")
        self.vine.catalog.upsert_node(self.forest.read(node_id))
        self.vine.catalog.mark_stale(node_id)
        report.updated.append(node_id)
