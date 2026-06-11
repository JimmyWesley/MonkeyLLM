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

## Sub-galhos

## Bananas diretas

## Trilhas cruzadas

## Landmarks
"""

# spec A.1/A.2 default dialect, in the table format Dialect.parse reads
_SCHEMA_BODY = """# Dialeto da floresta

## Tipos de nó (type)

| `type` | Descrição | Verbo de colheita |
|---|---|---|
| `galho` | Arquivo de índice (_index.md) de uma pasta | look |
| `nota` | Conhecimento em texto livre | pick |
| `documento` | Documento convertido (origem PDF/DOCX) | pick |
| `dataset` | Dados tabulares (SQLite irmão) | query |
| `entidade` | Pessoa, organização, produto, lugar | pick |
| `conceito` | Definição/termo técnico | pick |
| `evento` | Fato datado (reunião, decisão, release) | pick |
| `midia` | Imagem/áudio/vídeo com descrição | pick |

## Tipos de aresta (rel)

| `rel` | Inversa | Semântica |
|---|---|---|
| `parte-de` | `contem` | Hierarquia lógica |
| `relacionado-com` | `relacionado-com` | Associação genérica (simétrica) |
| `mencionado-em` | `menciona` | Entidade citada em documento |
| `autor` | `autor-de` | Autoria |
| `comparado-com` | `comparado-com` | Contraste técnico (simétrica) |
| `derivado-de` | `origem-de` | Proveniência |
| `same-as` | `same-as` | Soft merge de entidades duplicadas |
| `atalho-descoberto` | — | Grito do macaco (criado por graft) |
| `sucede` | `precede` | Ordem temporal |
"""

# spec A.3.1: binaries never enter the forest git
_GITIGNORE = "_derived/\n.vine.lock\n*.db\n*.sqlite\n_assets/\n"


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
        f"Galho-mestre da floresta {title}. Recém-criada: ainda sem sub-galhos; "
        f"plante nós com plant() e organize as regiões."
    )
    master_fm = {
        "id": "_index", "type": "galho", "title": title, "summary": summary,
        "coverage": "0 bananas, 0 sub-galhos", "created": today, "updated": today,
    }
    schema_fm = {
        "id": "_meta/schema", "type": "nota", "title": "Dialeto da floresta",
        "summary": "Tipos de nó e de aresta válidos nesta floresta. Novos tipos "
                   "entram aqui antes do primeiro uso; o Vine rejeita o que não "
                   "estiver declarado.",
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
