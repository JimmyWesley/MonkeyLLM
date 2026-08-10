# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Forest layer: id <-> path mapping, trails, node IO, writer lock,
forest bootstrap (`init_forest`).

Canonical id = path relative to the forest root, forward slashes, no
extension (spec Part B). Files are the database.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Iterator

from monkeyllm.dialect import Dialect
from monkeyllm.errors import E_LOCKED, E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.parser import ParsedNode, parse_node

EXCLUDED_DIRS = {"_derived", "_assets", ".git"}
LOCK_FILE = ".vine.lock"

# spec A.5: master index skeleton (master also carries Landmarks)
_MASTER_BODY = """# {title}

> {summary}

## Sub-branches

## Direct bananas

## Cross trails

## Landmarks
"""

# spec A.1/A.2 default dialect, in the table format Dialect.parse reads
_SCHEMA_BODY = """# Forest dialect

## Node types (type)

| `type` | Description | Harvest verb |
|---|---|---|
| `branch` | Index file (_index.md) of a folder | look |
| `note` | Free-text knowledge | pick |
| `document` | Converted document (PDF/DOCX origin) | pick |
| `dataset` | Tabular data (sibling SQLite) | query |
| `entity` | Person, organization, product, place | pick |
| `concept` | Definition / technical term | pick |
| `event` | Dated fact (meeting, decision, release) | pick |
| `media` | Image/audio/video with description | pick |

## Edge types (rel)

| `rel` | Inverse | Semantics |
|---|---|---|
| `part-of` | `contains` | Logical hierarchy |
| `related-to` | `related-to` | Generic association (symmetric) |
| `mentioned-in` | `mentions` | Entity cited in a document |
| `author` | `author-of` | Authorship |
| `compared-with` | `compared-with` | Technical contrast (symmetric) |
| `derived-from` | `origin-of` | Provenance |
| `same-as` | `same-as` | Soft merge of duplicate entities |
| `discovered-shortcut` | — | The monkey's shout (created by graft) |
| `succeeds` | `precedes` | Temporal order |
"""

# spec A.3.1: binaries never enter the forest git
_GITIGNORE = "_derived/\n.vine.lock\n*.db\n*.sqlite\n_assets/\n"


def tune_derived(conn) -> None:
    """Journal settings for a database in `_derived/`.

    Every read primitive deposits pheromone (Part D/E.2), so every read is
    also a commit — and in the default rollback mode that is a journal
    created, fsynced and deleted, per call. WAL makes it an append, and
    `synchronous=NORMAL` stops fsyncing each one.

    The durability that buys is durability this data does not need: the
    files are the source of truth and `_derived/` is disposable by
    definition. A crash costs the last few heat deposits, which evaporate on
    a schedule anyway (H.1), and at worst a `reindex`, which is the
    documented repair. Corruption is not on the table — WAL is
    crash-safe; what is lost is the tail.

    Best effort: a filesystem that cannot do WAL (a network mount, no shared
    memory) keeps the mode it had and keeps working. Failing to open a
    forest because it could not be made faster would be the wrong trade.
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:                                    # noqa: BLE001
        pass


def init_forest(root: str | os.PathLike, title: str, summary: str | None = None) -> dict:
    """Bootstrap an empty, valid forest: A.5 master index, default dialect,
    A.3.1 .gitignore, embedded git repo with the initial commit.

    The folder becomes immediately servable (`vine serve`) and plantable.
    """
    from monkeyllm.gitops import GitRepo
    from monkeyllm.parser import serialize_node

    root = Path(root).resolve()
    if (root / "_index.md").exists():
        raise VineError(E_SCHEMA, f"already a forest: {root}",
                        hint="Refusing to overwrite an existing _index.md.")
    root.mkdir(parents=True, exist_ok=True)
    (root / "_meta").mkdir(exist_ok=True)

    today = _dt.date.today().isoformat()
    summary = summary or (
        f"Master branch of the {title} forest. Freshly created: no sub-branches "
        f"yet; plant() nodes and organize the regions."
    )
    master_fm = {
        "id": "_index", "type": "branch", "title": title, "summary": summary,
        "coverage": "0 bananas, 0 sub-branches", "created": today, "updated": today,
    }
    schema_fm = {
        "id": "_meta/schema", "type": "note", "title": "Forest dialect",
        "summary": "Node and edge types valid in this forest. New types are "
                   "declared here before first use; the Vine rejects anything "
                   "not declared.",
        "created": today, "updated": today,
    }
    (root / "_index.md").write_text(
        serialize_node(master_fm, _MASTER_BODY.format(title=title, summary=summary)),
        encoding="utf-8", newline="\n")
    (root / "_meta" / "schema.md").write_text(
        serialize_node(schema_fm, _SCHEMA_BODY), encoding="utf-8", newline="\n")
    (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8", newline="\n")

    repo = GitRepo(root)
    if not repo.is_repo:
        repo.init()
    repo._run("add", "--", ".gitignore", "_index.md", "_meta/schema.md")
    repo._run("commit", "--quiet", "-m", f"init: forest '{title}' (empty A.5 skeleton)")

    return {"root": str(root), "title": title, "commit": repo.head()}


class Forest:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise VineError(E_NOT_FOUND, f"forest root not found: {self.root}")
        self.dialect = Dialect.load(self.root)
        self.derived_dir = self.root / "_derived"

    # -- id/path ---------------------------------------------------------

    def path_for(self, node_id: str) -> Path:
        node_id = node_id.strip().strip("/")
        p = (self.root / f"{node_id}.md").resolve()
        if self.root not in p.parents and p != self.root:
            raise VineError(E_NOT_FOUND, f"id escapes forest: {node_id}")
        return p

    def id_for(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root)
        return rel.as_posix()[: -len(".md")]

    def exists(self, node_id: str) -> bool:
        try:
            return self.path_for(node_id).is_file()
        except VineError:
            return False

    def trail(self, node_id: str) -> list[str]:
        """Index ids from the root down to (excluding) the node itself."""
        trail = ["_index"]
        parts = node_id.split("/")
        for i in range(1, len(parts)):
            prefix = "/".join(parts[:i])
            if prefix == "_meta" or prefix.startswith("_"):
                continue
            trail.append(f"{prefix}/_index")
        if node_id == "_index":
            return []
        if node_id.endswith("/_index") and trail and trail[-1] == node_id:
            trail.pop()
        return trail

    def parent_index_id(self, node_id: str) -> str:
        if "/" in node_id:
            folder = node_id.rsplit("/", 1)[0]
            if node_id.endswith("/_index"):
                grand = folder.rsplit("/", 1)[0] if "/" in folder else None
                return f"{grand}/_index" if grand else "_index"
            return f"{folder}/_index"
        return "_index"

    # -- IO ----------------------------------------------------------------

    def read(self, node_id: str) -> ParsedNode:
        path = self.path_for(node_id)
        if not path.is_file():
            raise VineError(
                E_NOT_FOUND,
                f"node not found: {node_id}",
                hint="Use locate() to find entry points; ids are canonical paths.",
            )
        return parse_node(node_id, path.read_text(encoding="utf-8"), path)

    def write(self, node_id: str, content: str) -> Path:
        path = self.path_for(node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def iter_ids(self) -> Iterator[str]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for name in sorted(filenames):
                if name.endswith(".md"):
                    yield self.id_for(Path(dirpath) / name)

    def payload_path(self, node: ParsedNode) -> Path:
        payload = node.frontmatter.get("payload")
        if not payload:
            raise VineError(E_NOT_FOUND, f"node {node.id} has no payload")
        assert node.path is not None
        return node.path.parent / payload

    def body_cache_path(self, node_id: str) -> Path:
        """G.7 `content: cached` — the FLESH lives in _derived, out of git."""
        return self.derived_dir / "bodies" / f"{node_id}.md"

    def gardener_source_root(self) -> Path | None:
        """The adopted source root (G.6 config) — backs `content: reference`."""
        if not hasattr(self, "_gardener_root"):
            import yaml

            cfg = self.root / "_meta" / "gardener.yaml"
            root = None
            if cfg.is_file():
                data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                if data.get("source_root"):
                    root = Path(str(data["source_root"]))
            self._gardener_root: Path | None = root
        return self._gardener_root


class WriterLock:
    """One writer per forest (spec C.9). `.vine.lock` at the root."""

    def __init__(self, root: Path):
        self.path = Path(root) / LOCK_FILE
        self._fd: int | None = None

    def acquire(self) -> None:
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode())
        except FileExistsError:
            raise VineError(
                E_LOCKED,
                f"forest already has a writer (lock: {self.path})",
                hint="Only one writing Vine per forest. Remove a stale .vine.lock manually.",
            ) from None

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "WriterLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
