"""Forest layer: id <-> path mapping, trails, node IO, writer lock.

Canonical id = path relative to the forest root, forward slashes, no
extension (spec Part B). Files are the database.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from monkeyllm.dialect import Dialect
from monkeyllm.errors import E_LOCKED, E_NOT_FOUND, VineError
from monkeyllm.parser import ParsedNode, parse_node

EXCLUDED_DIRS = {"_derived", "_assets", ".git"}
LOCK_FILE = ".vine.lock"


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
