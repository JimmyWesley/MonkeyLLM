# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Vine MCP server — the 9 primitives + harvest as MCP tools (spec Part C).

Transport: stdio for dev, streamable-http for the network/Docker.
Errors come back as the spec envelope: {"error": {code, message, hint}}.

Two serving modes (spec C.0):
  single-forest  build_server(forest_root=...)   `forest` param optional
  registry       build_server(root=...)          `forest` param required;
                 every subdirectory of root with an _index.md is servable,
                 opened lazily on first touch (auto-index included)
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.vine import Vine

FOREST_ENV = "MONKEYLLM_FOREST"


class ForestPool:
    """Forest registry: lazily opened Vine per forest (spec C.0)."""

    def __init__(self, *, single: Path | None = None, root: Path | None = None,
                 writable: bool = True):
        if (single is None) == (root is None):
            raise ValueError("ForestPool needs exactly one of single= or root=")
        self.writable = writable
        self.root = Path(root).resolve() if root else None
        self._vines: dict[str, Vine] = {}
        self.default: str | None = None
        if single is not None:
            p = Path(single).resolve()
            self.default = p.name
            self._vines[self.default] = Vine(p, writable=writable)
            self._vines[self.default].warm()

    @property
    def mode(self) -> str:
        return "registry" if self.root else "single"

    def list(self) -> dict:
        if self.root:
            forests = [
                {"id": child.name, "active": child.name in self._vines}
                for child in sorted(self.root.iterdir())
                if child.is_dir() and (child / "_index.md").is_file()
            ]
        else:
            forests = [{"id": fid, "active": True} for fid in self._vines]
        return {"forests": forests, "mode": self.mode}

    def get(self, forest: str | None) -> Vine:
        if forest is None:
            if self.default:
                return self._vines[self.default]
            ids = [f["id"] for f in self.list()["forests"]]
            raise VineError(
                E_SCHEMA,
                "this server hosts multiple forests: pass forest=<id>",
                hint=f"Available forests: {ids}. Use the forests() tool to list them.",
            )
        if forest in self._vines:
            return self._vines[forest]
        if self.root is None:
            raise VineError(
                E_NOT_FOUND,
                f"unknown forest: {forest}",
                hint=f"This server serves a single forest: '{self.default}'.",
            )
        target = (self.root / forest).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise VineError(E_NOT_FOUND, f"forest id escapes the root: {forest}")
        if not (target / "_index.md").is_file():
            raise VineError(
                E_NOT_FOUND,
                f"not a forest (no _index.md): {forest}",
                hint="Use the forests() tool to list servable forests.",
            )
        # first touch: Vine auto-indexes when the catalog is empty
        vine = Vine(target, writable=self.writable)
        # Whoever opened it pays the wake-up, so nobody's *call* does.
        vine.warm()
        self._vines[forest] = vine
        return vine

    def warm_all(self) -> dict:
        """Open and warm every servable forest, best effort.

        Opening is where the cost is — a few milliseconds and a few MB of
        resident memory per forest — and it happens either way; this only
        decides who waits for it. A host that serves a console does it at
        boot so the first visitor is not the one measuring cold SQLite.

        Best effort, always: a forest that will not open (a writer lock left
        behind, a corrupt catalog) is reported and skipped. A server that
        refused to start because one forest out of forty was busy would be
        trading every forest's availability for one forest's warmth.
        """
        opened, skipped = [], {}
        for entry in self.list()["forests"]:
            if entry["id"] in self._vines:
                continue
            try:
                self.get(entry["id"])
                opened.append(entry["id"])
            except Exception as e:                       # noqa: BLE001
                skipped[entry["id"]] = str(e)
        return {"warmed": opened, "skipped": skipped}

    def close(self) -> None:
        for vine in self._vines.values():
            vine.close()
        self._vines.clear()

    def close_one(self, forest: str) -> None:
        """Close a single forest. A host that confines each forest to its
        own thread (spec J.9 isolation) closes each one from that thread,
        which `close()` — all forests, one caller — cannot offer."""
        vine = self._vines.pop(forest, None)
        if vine is not None:
            vine.close()


def build_server(
    forest_root: str | Path | None = None,
    writable: bool = True,
    root: str | Path | None = None,
) -> MCPServer:
    # host/port are transport options in mcp 2.x: they go to run(), not here.
    #
    # mcp 2.x runs sync tools on arbitrary worker threads (anyio.to_thread;
    # 1.x ran them inline on the event loop), and a SQLite connection belongs
    # to the thread that opened it — a guarantee the engine keeps. So every
    # forest touch — open, call, close — is confined to one dedicated thread,
    # the same discipline the Station host applies (spec Part J).
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vine")

    def in_vine_thread(fn):
        return worker.submit(fn).result()

    if root is not None:
        pool = in_vine_thread(lambda: ForestPool(root=Path(root), writable=writable))
    else:
        single = Path(forest_root or os.environ.get(FOREST_ENV, "."))
        pool = in_vine_thread(lambda: ForestPool(single=single, writable=writable))

    mcp = MCPServer(
        "vine",
        instructions=(
            "MonkeyLLM forest navigation. Two ways in: harvest(query) for "
            "one-shot retrieval (ranked evidence + snippets, you reason over "
            "it), or navigate yourself — look('_index') for the map, "
            "locate(query) to be dropped near the target, sniff(terms) to grep "
            "bodies for exact terms the summaries miss, look(id) for a cheap "
            "digest, move(id) for neighbors, pick(id) only when the summary "
            "says it is the banana, query(id, sql) for datasets. "
            "plant/graft to write nodes (plant with schema= births a new "
            "dataset); tend(id, sql) to write dataset rows. "
            "When this server hosts multiple forests, call forests() and pass "
            "forest=<id> on every tool."
        ),
    )

    def guarded(method: str, forest: str | None, /, *args, **kwargs):
        try:
            return in_vine_thread(
                lambda: getattr(pool.get(forest), method)(*args, **kwargs)
            )
        except VineError as e:
            return e.to_dict()

    @mcp.tool()
    def forests() -> dict:
        """List the forests this server can navigate (spec C.0)."""
        return in_vine_thread(pool.list)

    @mcp.tool()
    def harvest(query: str, terms: list[str] | None = None, k: int = 3,
                forest: str | None = None) -> dict:
        """One-shot retrieval (zero LLM server-side): ranked bananas with body or
        matched sections + exact snippets. Use it when you want evidence in a
        single call and will reason over it yourself; use the primitives below
        when you want to navigate step by step."""
        from monkeyllm.harvest import harvest as _harvest

        try:
            return in_vine_thread(
                lambda: _harvest(pool.get(forest), query, terms=terms, k=k)
            )
        except VineError as e:
            return e.to_dict()

    @mcp.tool()
    def locate(query: str, k: int = 5, scope: str = "all",
               type_filter: str | None = None, forest: str | None = None) -> dict:
        """Find entry points (the helicopter). scope: all|branches|bananas."""
        return guarded("locate", forest, query, k=k, scope=scope, type_filter=type_filter)

    @mcp.tool()
    def sniff(terms: str | list[str], scope: str | None = None, k: int = 5,
              type_filter: str | None = None, forest: str | None = None) -> dict:
        """Literal grep over node bodies (the tracker): exact terms -> node + section + snippet."""
        return guarded("sniff", forest, terms, scope=scope, k=k, type_filter=type_filter)

    @mcp.tool()
    def look(id: str, fields: list[str] | None = None, forest: str | None = None) -> dict:
        """Digest of a node (<=500 tokens): summary, outline/children, edges, stats."""
        return guarded("look", forest, id, fields=fields)

    @mcp.tool()
    def move(id: str, rel: str | None = None, direction: str = "out",
             forest: str | None = None) -> dict:
        """Neighbors of a node. rel='children' lists a branch's physical children."""
        return guarded("move", forest, id, rel=rel, direction=direction)

    @mcp.tool()
    def pick(id: str, section: str | None = None, forest: str | None = None) -> dict:
        """Harvest the body (or one section) of a node."""
        return guarded("pick", forest, id, section=section)

    @mcp.tool()
    def query(id: str, sql: str, forest: str | None = None) -> dict:
        """Read-only SELECT over a dataset node's SQLite payload (LIMIT 200 enforced)."""
        return guarded("query", forest, id, sql)

    @mcp.tool()
    def tend(id: str, sql: str, forest: str | None = None) -> dict:
        """Write to a dataset node's SQLite payload (spec C.10): one INSERT/UPDATE/
        DELETE statement, WHERE required on UPDATE/DELETE; refreshes payload_hash
        and commits the .md audit reference (the binary never enters git)."""
        return guarded("tend", forest, id, sql)

    @mcp.tool()
    def scan(parent_id: str, filter: dict | None = None, fields: list[str] | None = None,
             recursive: bool = False, limit: int = 50, forest: str | None = None) -> dict:
        """Metadata query over a branch's children via the Catalog (no file opens)."""
        return guarded("scan", forest, parent_id, filter=filter, fields=fields,
                       recursive=recursive, limit=limit)

    @mcp.tool()
    def plant(node: dict, forest: str | None = None) -> dict:
        """Create a node: frontmatter + body + parent (atomic: file+index+git commit).
        For type:dataset, pass schema={table: {columns: {name: TEXT|INTEGER|REAL|BLOB},
        primary_key?: [...]}} and Vine births the SQLite payload + query manual
        (spec C.7.1); rows then enter via tend()."""
        return guarded("plant", forest, node)

    @mcp.tool()
    def graft(id: str, patch: dict, forest: str | None = None) -> dict:
        """Edit a node: set_frontmatter / add_links / remove_links / append_section / replace_section."""
        return guarded("graft", forest, id, patch)

    @mcp.tool()
    def close_session(success: bool, answer_nodes: list[str],
                      forest: str | None = None) -> dict:
        """Close the hunt: reinforces heat on the winning trail and returns metrics."""
        return guarded("close_session", forest, success, answer_nodes)

    def close() -> None:
        """Close every Vine on the thread that opened them, then the thread."""
        in_vine_thread(pool.close)
        worker.shutdown(wait=True)

    mcp._pool = pool  # for tests
    mcp._close = close  # lifecycle: the one way to shut the server's forests
    return mcp
