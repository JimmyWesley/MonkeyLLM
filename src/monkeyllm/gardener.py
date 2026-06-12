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
import re
import shlex
import sqlite3
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Callable, Protocol

import yaml

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import validate_summary
from monkeyllm.parser import serialize_node
from monkeyllm.tokens import estimate_tokens
from monkeyllm.vine import Vine

GARDENER_CONFIG = "gardener.yaml"  # lives in _meta/ (not a node: non-.md)
DEFAULT_IGNORES = (".git", ".svn", ".hg", "__pycache__", "node_modules",
                   "_derived", "_assets")
DEFAULT_IGNORE_GLOBS = ("~$*", "*.tmp", "*.lock", ".DS_Store", "Thumbs.db")
ASSETS_DIR = "_assets"
SUMMARY_TARGET_TOKENS = 50
INGEST_CONFIDENCE = 0.7  # G.4: unreviewed by an LLM or a human

PAYLOAD_TYPE_BY_EXT = {
    ".pdf": "pdf", ".docx": "docx",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
    ".flac": "audio",
}


# ===========================================================================
# G.2 — the converter contract (public plugin API v1)
# ===========================================================================

@dataclass
class Conversion:
    """What a converter hands back: markdown OR a dataset description."""

    kind: str  # "markdown" | "dataset"
    title: str
    markdown: str = ""
    schema: dict | None = None          # C.7.1 declarative schema
    rows: dict[str, list[list]] | None = None


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
    """INTEGER < REAL < TEXT, judged over the sampled non-empty values."""
    kind = "INTEGER"
    seen = False
    for v in values:
        if v is None or v == "":
            continue
        seen = True
        try:
            int(v)
            continue
        except (TypeError, ValueError):
            pass
        try:
            float(v)
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


def _tabular_conversion(title: str, table: str, header: list[str],
                        records: list[list]) -> Conversion:
    cols = []
    used = set()
    for i, name in enumerate(header):
        col = slugify(str(name) or f"col{i}").replace(".", "_").replace("-", "_")[:48]
        if not re.match(r"^[a-z_]", col):
            col = f"c_{col}"
        while col in used:
            col += "_"
        used.add(col)
        cols.append(col)
    types = {
        col: _infer_column_type([r[i] if i < len(r) else None for r in records])
        for i, col in enumerate(cols)
    }
    rows = [
        [_coerce(r[i] if i < len(r) else None, types[col]) for i, col in enumerate(cols)]
        for r in records
    ]
    schema = {table: {"columns": types}}
    return Conversion(kind="dataset", title=title, schema=schema, rows={table: rows})


def _table_name(path: Path) -> str:
    name = slugify(path.stem).replace(".", "_").replace("-", "_")[:48]
    return name if re.match(r"^[a-z_]", name) else f"t_{name}"


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
    """Built-in when openpyxl is importable: first sheet -> dataset."""

    extensions = {".xlsx"}

    def convert(self, path: Path) -> Conversion:
        from openpyxl import load_workbook  # optional dependency

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        data = [list(row) for row in ws.iter_rows(values_only=True)
                if any(v is not None for v in row)]
        wb.close()
        if len(data) < 2:
            raise VineError(E_SCHEMA, f"xlsx has no data rows: {path.name}")
        header = [str(v) if v is not None else f"col{i}" for i, v in enumerate(data[0])]
        return _tabular_conversion(path.stem.replace("-", " ").replace("_", " "),
                                   _table_name(path), header, data[1:])


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


def builtin_converters() -> list:
    convs: list = [MarkdownConverter(), CsvConverter(), JsonConverter()]
    try:
        import openpyxl  # noqa: F401

        convs.append(XlsxConverter())
    except ImportError:
        pass
    try:
        import docx  # noqa: F401

        convs.append(DocxConverter())
    except ImportError:
        pass
    return convs


def discover_converters(config: dict) -> list:
    """G.2 order: config command hooks > entry points > built-ins."""
    convs: list = [
        CommandConverter(ext, tpl)
        for ext, tpl in (config.get("converters") or {}).items()
    ]
    for ep in entry_points(group="monkeyllm.converters"):
        try:
            loaded = ep.load()
            convs.append(loaded() if isinstance(loaded, type) else loaded)
        except Exception:  # a broken plugin never blocks the pipeline
            continue
    convs.extend(builtin_converters())
    return convs


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

    def as_dict(self) -> dict:
        return {k: list(v) for k, v in self.__dict__.items()}


class Gardener:
    def __init__(self, vine: Vine, converters: list | None = None,
                 hooks: list[Callable] | None = None):
        self.vine = vine
        self.forest = vine.forest
        self.config = self._load_config()
        self.converters = (converters if converters is not None
                           else discover_converters(self.config))
        self.hooks = hooks if hooks is not None else discover_hooks()

    # -- config (G.6) -------------------------------------------------------

    def _config_path(self) -> Path:
        return self.forest.root / "_meta" / GARDENER_CONFIG

    def _load_config(self) -> dict:
        p = self._config_path()
        if p.is_file():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return {}

    def _save_config(self) -> None:
        p = self._config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")

    # -- walking ------------------------------------------------------------

    def _ignored(self, path: Path) -> bool:
        if any(part in DEFAULT_IGNORES or part.startswith(".") for part in path.parts):
            return True
        globs = list(DEFAULT_IGNORE_GLOBS) + list(self.config.get("ignore") or [])
        return any(path.match(g) for g in globs)

    def _walk(self, src: Path) -> list[Path]:
        return sorted(
            p for p in src.rglob("*")
            if p.is_file() and not self._ignored(p.relative_to(src))
        )

    def _converter_for(self, path: Path):
        ext = path.suffix.lower()
        for conv in self.converters:
            if ext in conv.extensions:
                return conv
        return None

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

    # -- curation (G.4) -----------------------------------------------------

    def _curate(self, draft: dict, report: IngestReport) -> dict:
        draft.setdefault("tags", [])
        for tag in (self.config.get("curation") or {}).get("default_tags") or []:
            if tag not in draft["tags"]:
                draft["tags"].append(tag)
        for hook in self.hooks:
            try:
                result = hook(draft)
                if isinstance(result, dict):
                    draft = result
            except Exception as e:  # G.4.3: a broken hook never aborts ingest
                report.errors.append(f"on_curate hook {getattr(hook, '__name__', hook)!r}: {e}")
        return draft

    # -- stage 0: archive ----------------------------------------------------

    def _archive(self, src_file: Path, branch_id: str) -> tuple[str, str | None, str]:
        """Copy the original under the branch's _assets/ (gitignored).
        Returns (payload, payload_type | None, payload_hash)."""
        branch_dir = self.forest.path_for(branch_id).parent
        assets = branch_dir / ASSETS_DIR
        assets.mkdir(parents=True, exist_ok=True)
        data = src_file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        name = f"{digest[:8]}-{slugify(src_file.stem)}{src_file.suffix.lower()}"
        (assets / name).write_bytes(data)
        ptype = PAYLOAD_TYPE_BY_EXT.get(src_file.suffix.lower())
        return f"{ASSETS_DIR}/{name}", ptype, digest

    # -- adopt (G.3) ---------------------------------------------------------

    def adopt(self, source: str | Path, dest: str | None = None) -> dict:
        src = Path(source).resolve()
        if not src.is_dir():
            raise VineError(E_SCHEMA, f"source is not a directory: {src}")
        report = IngestReport()
        for f in self._walk(src):
            self._ingest_file(src, f, dest, report)
        self.config["source_root"] = src.as_posix()
        if dest:
            self.config["dest"] = dest
        self._save_config()
        return report.as_dict()

    def _ingest_file(self, src: Path, f: Path, dest: str | None,
                     report: IngestReport) -> None:
        rel = f.relative_to(src)
        conv_obj = self._converter_for(f)
        if conv_obj is None:
            report.unsupported.append(rel.as_posix())
            return
        try:
            conversion = conv_obj.convert(f)
        except VineError as e:
            report.errors.append(f"{rel.as_posix()}: {e.message}")
            return
        except Exception as e:  # G.2: a broken converter never crashes adopt
            report.errors.append(f"{rel.as_posix()}: converter error: {e}")
            return

        branch_id = self._ensure_branch(rel.parent, dest, report)
        node_id = self._node_id(rel, dest)
        if self.forest.exists(node_id):
            node_id = f"{node_id}-{hashlib.sha256(rel.as_posix().encode()).hexdigest()[:6]}"

        st = f.stat()
        source_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        is_text_source = f.suffix.lower() in MarkdownConverter.extensions
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
            "source_mtime": round(st.st_mtime, 3),
        }
        if conversion.kind == "dataset":
            draft.update({
                "type": "dataset",
                "schema": conversion.schema,
                "rows": conversion.rows,
                "summary": self._dataset_summary(conversion),
            })
        else:
            draft.update({
                "type": "note" if is_text_source else "document",
                "body": conversion.markdown,
                "summary": derive_summary(conversion.markdown, conversion.title),
            })
        # G.7 archive policy: durable sources are referenced, not copied
        if not is_text_source and self.config.get("archive", "never") == "always":
            payload, ptype, phash = self._archive(f, branch_id)
            # dataset payload is its own .db; unknown payload types are
            # archived but not referenced (the A.3 enum stays honest)
            if conversion.kind != "dataset" and ptype:
                draft.update({"payload": payload, "payload_type": ptype,
                              "payload_hash": phash})

        # curation sees the FULL converted text (G.7.4)…
        draft = self._curate(draft, report)
        # …and only then the content policy slims the node (G.7)
        if conversion.kind != "dataset":
            draft = self._apply_content_policy(draft, conversion.title,
                                               is_text_source)
        try:
            self.vine.plant(draft)
            report.planted.append(node_id)
        except VineError as e:
            report.errors.append(f"{rel.as_posix()}: {e.message}")

    def _apply_content_policy(self, draft: dict, title: str,
                              is_text_source: bool) -> dict:
        policy = self.config.get("content", "inline")
        if policy == "reference" and not is_text_source:
            policy = "cached"  # converted bodies must live SOMEWHERE local
        if policy == "cached":
            self._write_body_cache(draft["id"], draft["body"])
            draft["body"] = f"# {title}"
            draft["content"] = "cached"
        elif policy == "reference":
            draft["body"] = f"# {title}"
            draft["content"] = "reference"
        return draft

    def _write_body_cache(self, node_id: str, body: str) -> None:
        p = self.forest.body_cache_path(node_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")

    def _node_id(self, rel: Path, dest: str | None) -> str:
        parts = [slugify(p) for p in rel.parent.parts]
        prefix = [] if not dest else [dest]
        return "/".join(prefix + parts + [slugify(rel.stem)])

    @staticmethod
    def _dataset_summary(conversion: Conversion) -> str:
        table, spec = next(iter(conversion.schema.items()))
        n = len((conversion.rows or {}).get(table) or [])
        cols = ", ".join(list(spec["columns"])[:6])
        return (f"Tabular data '{conversion.title}': table {table} with "
                f"{n} rows ({cols}). Adopted from source; pending curation.")

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
            if fm.get("source_path"):
                out[str(fm["source_path"])] = {
                    "id": nid,
                    "hash": str(fm.get("source_hash", "")),
                    "size": fm.get("source_size"),
                    "mtime": fm.get("source_mtime"),
                }
        return out

    def sync(self, source: str | Path | None = None,
             path: str | None = None) -> dict:
        src = Path(source or self.config.get("source_root", "")).resolve()
        if not src.is_dir():
            raise VineError(
                E_SCHEMA,
                f"sync source is not a directory: {src}",
                hint="Run adopt first, or pass the source directory explicitly.",
            )
        dest = self.config.get("dest")
        report = IngestReport()
        passports = self._passports()

        if path:  # G.8 targeted sync: one file, the event-trigger building block
            rel = Path(path).as_posix()
            f = src / rel
            if f.is_file():
                self._sync_one(src, f, rel, passports, dest, report)
            elif rel in passports:
                report.stale.append(passports[rel]["id"])
            else:
                report.unsupported.append(rel)
            return report.as_dict()

        seen: set[str] = set()
        for f in self._walk(src):
            rel = f.relative_to(src).as_posix()
            seen.add(rel)
            self._sync_one(src, f, rel, passports, dest, report)
        for rel, info in passports.items():
            if rel not in seen:
                report.stale.append(info["id"])
        return report.as_dict()

    def _sync_one(self, src: Path, f: Path, rel: str, passports: dict,
                  dest: str | None, report: IngestReport) -> None:
        if rel not in passports:
            self._ingest_file(src, f, dest, report)
            return
        info = passports[rel]
        st = f.stat()
        # G.8 fast-path (rsync's trick): same size + mtime -> skip hashing
        if (info.get("size") == st.st_size
                and info.get("mtime") == round(st.st_mtime, 3)):
            report.unchanged.append(info["id"])
            return
        new_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        if new_hash == info["hash"]:
            report.unchanged.append(info["id"])
            return
        self._update_passport(info["id"], f, new_hash, report)

    def _update_passport(self, node_id: str, f: Path, new_hash: str,
                         report: IngestReport) -> None:
        """G.3: refresh body + source_hash via the audited write path —
        curated frontmatter (summary, tags, links, confidence) is preserved."""
        conv_obj = self._converter_for(f)
        if conv_obj is None:
            report.unsupported.append(node_id)
            return
        try:
            conversion = conv_obj.convert(f)
        except VineError as e:
            report.errors.append(f"{node_id}: {e.message}")
            return
        except Exception as e:
            report.errors.append(f"{node_id}: converter error: {e}")
            return

        node = self.forest.read(node_id)
        fm = dict(node.frontmatter)
        fm["source_hash"] = new_hash
        st = f.stat()
        fm["source_size"] = st.st_size
        fm["source_mtime"] = round(st.st_mtime, 3)
        fm["updated"] = dt.date.today().isoformat()
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
        elif fm.get("content") == "cached":
            self._write_body_cache(node_id, conversion.markdown)  # body stays a stub
        elif fm.get("content") == "reference":
            pass  # the body IS the source; hash bookkeeping above is enough
        else:
            body = conversion.markdown

        assert node.path is not None
        node.path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")
        self.vine.git.commit([node.path], f"gardener(sync): {node_id}")
        self.vine.catalog.upsert_node(self.forest.read(node_id))
        self.vine.catalog.mark_stale(node_id)
        report.updated.append(node_id)
