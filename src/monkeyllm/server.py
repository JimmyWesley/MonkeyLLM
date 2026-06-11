"""Vine MCP server — the 9 primitives as MCP tools.

Transport: stdio for dev, streamable-http for Docker (spec Part C).
Errors come back as the spec envelope: {"error": {code, message, hint}}.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from monkeyllm.errors import VineError
from monkeyllm.vine import Vine

FOREST_ENV = "MONKEYLLM_FOREST"


def build_server(forest_root: str | Path | None = None, writable: bool = True) -> FastMCP:
    root = Path(forest_root or os.environ.get(FOREST_ENV, "."))
    vine = Vine(root, writable=writable)
    mcp = FastMCP(
        "vine",
        instructions=(
            "MonkeyLLM forest navigation. Start with look('_index') for the map, "
            "or locate(query) to be dropped near the target; sniff(terms) greps "
            "bodies for exact terms (codes, names, numbers) the summaries miss. "
            "Use look(id) for a cheap digest, move(id) for neighbors, pick(id) "
            "only when the summary says it is the banana, query(id, sql) for "
            "datasets. plant/graft to write."
        ),
    )

    def guarded(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except VineError as e:
            return e.to_dict()

    @mcp.tool()
    def locate(query: str, k: int = 5, scope: str = "all", type_filter: str | None = None) -> dict:
        """Find entry points (the helicopter). scope: all|branches|bananas."""
        return guarded(vine.locate, query, k=k, scope=scope, type_filter=type_filter)

    @mcp.tool()
    def sniff(
        terms: str | list[str],
        scope: str | None = None,
        k: int = 5,
        type_filter: str | None = None,
    ) -> dict:
        """Literal grep over node bodies (the tracker): exact terms -> node + section + snippet."""
        return guarded(vine.sniff, terms, scope=scope, k=k, type_filter=type_filter)

    @mcp.tool()
    def look(id: str, fields: list[str] | None = None) -> dict:
        """Digest of a node (<=500 tokens): summary, outline/children, edges, stats."""
        return guarded(vine.look, id, fields=fields)

    @mcp.tool()
    def move(id: str, rel: str | None = None, direction: str = "out") -> dict:
        """Neighbors of a node. rel='children' lists a branch's physical children."""
        return guarded(vine.move, id, rel=rel, direction=direction)

    @mcp.tool()
    def pick(id: str, section: str | None = None) -> dict:
        """Harvest the body (or one section) of a node."""
        return guarded(vine.pick, id, section=section)

    @mcp.tool()
    def query(id: str, sql: str) -> dict:
        """Read-only SELECT over a dataset node's SQLite payload (LIMIT 200 enforced)."""
        return guarded(vine.query, id, sql)

    @mcp.tool()
    def scan(
        parent_id: str,
        filter: dict | None = None,
        fields: list[str] | None = None,
        recursive: bool = False,
        limit: int = 50,
    ) -> dict:
        """Metadata query over a branch's children via the Catalog (no file opens)."""
        return guarded(vine.scan, parent_id, filter=filter, fields=fields, recursive=recursive, limit=limit)

    @mcp.tool()
    def plant(node: dict) -> dict:
        """Create a node: frontmatter + body + parent (atomic: file+index+git commit)."""
        return guarded(vine.plant, node)

    @mcp.tool()
    def graft(id: str, patch: dict) -> dict:
        """Edit a node: set_frontmatter / add_links / remove_links / append_section / replace_section."""
        return guarded(vine.graft, id, patch)

    @mcp.tool()
    def close_session(success: bool, answer_nodes: list[str]) -> dict:
        """Close the hunt: reinforces heat on the winning trail and returns metrics."""
        return guarded(vine.close_session, success, answer_nodes)

    mcp._vine = vine  # for tests / lifecycle
    return mcp
