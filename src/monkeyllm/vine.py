# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Vine — the navigation protocol (spec Part C).

Ten primitives over a markdown forest:
read: locate, look, move, pick, query, scan, sniff
write: plant, graft, tend (atomic, Git-committed, index-synced)

Every response fits its declared token budget; truncation is always
explicit (`truncated: true`), never silent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import math
import mimetypes
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

from monkeyllm import indexer
from monkeyllm.canopy import CanopyIndex, cosine, rrf_fuse
from monkeyllm.catalog import Catalog
from monkeyllm.dialect import MAX_LINKS_PER_NODE
from monkeyllm.errors import (
    E_ANCHORED,
    E_MOVED,
    E_NOT_FOUND,
    E_QUERY_FORBIDDEN,
    E_QUERY_INVALID,
    E_READONLY,
    E_SCHEMA,
    E_TIMEOUT,
    VineError,
)
from monkeyllm.fetch import PayloadCache, is_remote
from monkeyllm.forest import Forest, WriterLock
from monkeyllm.gitops import GitRepo
from monkeyllm.models import (
    ALIAS_MAX_CHARS,
    MAX_ALIASES,
    MUTABLE_FRONTMATTER_FIELDS,
    NOTES_SECTION,
    GraftPatch,
    Link,
    NodeSpec,
    dataset_ddl,
    dataset_manual,
    validate_dataset_rows,
    validate_dataset_schema,
    validate_frontmatter,
    validate_origin,
    validate_summary,
)
from monkeyllm.parser import (
    ParsedNode,
    append_section,
    extract_outline,
    extract_section,
    parse_node,
    replace_section,
    serialize_node,
)
from monkeyllm.telemetry import Tracer
from monkeyllm.tokens import (
    estimate_payload_tokens,
    estimate_tokens,
    shrink_list_to_budget,
    truncate_text,
)
from monkeyllm.trails import Trails
from monkeyllm.windows import (
    buckets_from_rows,
    in_window,
    nearest_periods,
    normalize_window,
    parse_field,
    window_sql,
)

BUDGET_LOCATE = 800
BUDGET_LOOK = 500
BUDGET_MOVE = 600
BUDGET_SCAN = 800
BUDGET_SNIFF = 800
# C.13.3: the time map, on the same shelf as the other searching reads.
BUDGET_CALENDAR = 800
# C.2.1: the operator's notes ride inside BUDGET_LOOK, with their own
# ceiling — a long note must not starve the digest it travels in.
BUDGET_NOTES = 200
SNIFF_MAX_TERMS = 8
SNIFF_MAX_K = 20
SNIFF_MATCHES_PER_NODE = 3
SNIFF_SNIPPET_CHARS = 100  # ~25 tokens
PICK_MAX_BODY_TOKENS = 4000
# C.4.1 (v0.56): a list of sections is one call with one budget.
MAX_PICK_SECTIONS = 10
# C.14 (v0.56): how many anchors an E_ANCHORED refusal names; the exact
# total always rides beside them as `anchor_count`.
MAX_PRUNE_ANCHORS_SHOWN = 20
# C.7.4 (v0.58): a batch is one plant — everything validated before
# anything is written, the whole batch in one commit.
MAX_BATCH_PLANT = 20
# C.16 (v0.58): the document's past — listing budget and the hard cap.
BUDGET_HISTORY = 800
MAX_HISTORY = 50
# C.4.1: paragraph blocks — the page unit. Each block keeps its trailing
# blank run, so `"".join(blocks) == body` holds by construction and pages
# reassemble byte-identically (F.80).
_BLOCK_BOUNDARY = re.compile(r"\n{2,}")


def _split_blocks(body: str) -> list[str]:
    blocks, start = [], 0
    for m in _BLOCK_BOUNDARY.finditer(body):
        blocks.append(body[start:m.end()])
        start = m.end()
    if start < len(body):
        blocks.append(body[start:])
    return blocks
# C.11 (v0.52): a batch is one call, so it is sized by ONE budget — never
# the per-item budget times the number of items. `look`'s ceiling is above
# a single digest's 500 because a batch exists to replace several calls;
# `pick`'s is the wall a single body already meets, unchanged.
MAX_BATCH_LOOK = 10
MAX_BATCH_PICK = 5
BUDGET_LOOK_BATCH = 2000
BUDGET_PICK_BATCH = PICK_MAX_BODY_TOKENS
# C.6b (v0.52): occurrences enter the score instead of only breaking its
# ties. log2, so the tenth match is worth less than the second, and beta
# sized so ten occurrences outweigh a maximal pheromone bonus.
SNIFF_DENSITY_BETA = 0.15
# C.1.1 (v0.52): what `include` may ask for — a closed set, so a
# misspelling is refused rather than silently ignored.
LOCATE_INCLUDE = {"outline"}
# C.12 rule 7 (v0.54): an enum refuses what it does not accept. A value
# outside these sets used to fall back silently — `direction="all"` read
# as an isolated node, `scope="typo"` as an unfiltered search.
LOCATE_SCOPES = ("all", "branches", "notes")
# C.1 (v0.56): the metaphor stays in the prose. The wire's leaf token is
# "notes"/"note"; the old scope word remains accepted for one minor
# version, and the catalog's internal spelling never crosses the wire.
_SCOPE_ALIASES = {"bananas": "notes"}
_KIND_LEAF = "banana"          # catalog-internal spelling (C.6.1 storage)
MOVE_DIRECTIONS = ("out", "in", "both")


def _wire_kind(kind: str) -> str:
    """C.1/C.6 (v0.56): every emitted `kind` speaks the wire's spelling."""
    return "note" if kind == _KIND_LEAF else kind
# C.6 (v0.54): what `scan`'s `fields` may name — the catalog's
# caller-facing columns plus computed heat. `payload`, `payload_hash` and
# the internal columns are absent on purpose: a payload location is
# J.14's business, not a listing's.
SCAN_FIELDS = frozenset({
    "id", "kind", "type", "title", "summary", "tags", "aliases", "created",
    "updated", "confidence", "source", "entity_kind", "payload_type",
    "parent", "trail", "coverage", "body_tokens", "outline", "heat",
    "origin",
})
NEIGHBOR_SUMMARY_TOKENS = 25
MAX_EDGES_SHOWN = 12
QUERY_DEFAULT_LIMIT = 200
QUERY_TIMEOUT_S = 2.0
# C.6d: the byte ceiling of `view` — the G.5.1 describer's own number,
# because "too big to hand a model?" is one question and gets one answer.
VIEW_MAX_BYTES = 6 * 1024 * 1024
# C.5.1 (v0.47): a row cap is not a token cap — width is unbounded. Below
# PICK_MAX_BODY_TOKENS on purpose: a body is read once, a result enters a
# loop that carries it forward turn after turn.
BUDGET_QUERY = 2000

# Both spellings are listed on purpose: the `PRAGMA` keyword and the
# `pragma_*` table-valued functions are separate syntax and one pattern does
# not cover the other, so neither entry is redundant. The read-only
# connection already refuses everything that *changes* state; these describe
# instead — the schema, and where the payload sits — and J.14 and C.6d are
# deliberate about never returning either.
_FORBIDDEN_SQL = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|VACUUM|REINDEX)\b"
    r"|\b(pragma_\w+)",
    re.IGNORECASE,
)
# tend (C.10) allows INSERT/UPDATE/DELETE but nothing structural or sneaky
_TEND_FORBIDDEN = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|DROP|ALTER|CREATE|VACUUM|REINDEX|BEGIN|COMMIT|TRANSACTION)\b"
    r"|\b(pragma_\w+)",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)

# A table allow-list is decided by SQLite, never by reading the statement
# (spec C.5, J.3: "checked against the parsed statement"). Matching table
# names out of SQL text is a second parser, and two parsers agree only where
# somebody thought to compare them; for SQL that is not a list worth
# maintaining, and being wrong about it is silent. The authorizer is asked
# once per table and column the statement actually touches, so a subquery, a
# CTE, a view and a table-valued function are all the same question, asked by
# the component that resolves them.
_AUTHORIZER_TABLE_ACTIONS = frozenset({
    sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
})


def _table_authorizer(allowed: frozenset[str]):
    """Deny every table the allow-list does not name.

    `SQLITE_READ` matters as much as the write actions, and on the write
    path too: a statement that writes only where it may can still read from
    where it may not, and leave what it read somewhere permitted. Denying
    the write actions alone would police the destination and ignore the
    source.
    """
    def check(action, arg1, arg2, dbname, source):
        if action in _AUTHORIZER_TABLE_ACTIONS:
            name = (arg1 or "").lower()
            # `sqlite_master` and friends describe every table there is, so
            # under a table scope the schema is not readable either — it is
            # the map to what was withheld (and the internal callers that
            # need it run with no authorizer set).
            if name.startswith("sqlite_") or name not in allowed:
                return sqlite3.SQLITE_DENY
        elif action == sqlite3.SQLITE_PRAGMA:
            # `PRAGMA` is already refused as a keyword, but `pragma_table_info`
            # and `pragma_database_list` are table-valued functions that never
            # match it — and the second returns the file's path on disk.
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return check


def _not_authorized(error: Exception) -> bool:
    """Whether SQLite refused this statement because the authorizer said so.

    Two phrasings, both from the same refusal: naming the column it stopped
    at ("access to salaries.amount is prohibited") when it knows one, and
    "not authorized" when the denial lands somewhere without a column to
    name — a scalar subquery, for instance.
    """
    text = str(error).lower()
    return "not authorized" in text or "is prohibited" in text
_HEADER_LINE_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _fit_query_budget(payload: dict) -> dict:
    """Keep whole rows while the response fits BUDGET_QUERY (spec C.5.1).

    `columns` is never dropped: it is the smallest useful part of the
    response and the only one that says how to ask again, so a result whose
    every row was refused still answers *these are the columns your
    statement produces, and none of the rows fit*.

    Sized by summing each row's own cost instead of re-serialising the
    envelope per drop (`shrink_list_to_budget`): a 200-row result of a
    141-column table would otherwise pay 200 serialisations of ~430k
    characters to discover it must keep two.
    """
    rows = payload["rows"]
    if not rows:
        return payload
    spent = estimate_payload_tokens({**payload, "rows": []})
    kept: list = []
    per_row = 0
    for row in rows:
        cost = estimate_payload_tokens(row)
        if not kept:
            per_row = cost
        if spent + cost > BUDGET_QUERY:
            break
        kept.append(row)
        spent += cost
    if len(kept) == len(rows):
        return payload
    payload["rows"] = kept
    payload["row_count"] = len(kept)
    payload["truncated"] = True
    columns = len(payload.get("columns") or [])
    # Say that the missing rows EXIST, first and in those words. A model
    # given "truncated to 5 of 15" reported that only 5 rows matched the
    # filter and offered them as the complete answer: it read a display
    # bound as a count. Truncation is never absence (C.5.1 rule 5), and the
    # sentence that prevents that reading has to come before the advice.
    dropped = len(rows) - len(kept)
    if kept:
        payload["hint"] = (
            f"Showing {len(kept)} of {len(rows)} rows. The other {dropped} "
            f"matched your query and exist: they were dropped by the "
            f"{BUDGET_QUERY}-token response budget, not by your filter — do "
            f"NOT report these {len(kept)} as the complete result. This "
            f"statement returns {columns} column(s); ask again with fewer "
            "columns to fit more rows, or aggregate.")
    else:
        # The hint is the whole payload now, so it carries the arithmetic
        # that makes the next statement obviously different.
        payload["hint"] = (
            f"{len(rows)} row(s) matched your query and exist, but none fit "
            f"the {BUDGET_QUERY}-token response budget: one row of this "
            f"result costs ~{per_row} tokens across {columns} column(s). "
            "Nothing is missing from the data — ask again naming only the "
            "columns you need (the node's Query manual lists them all), or "
            "aggregate.")
    return payload


_FOLD_CACHE: dict[str, str] = {}


def _fold(text: str) -> str:
    """Length-preserving fold: lowercase + strip diacritics by keeping only
    the base character of each NFD decomposition. Positions found in the
    folded text map 1:1 back to the original (spec C.6b matching)."""
    cache = _FOLD_CACHE
    out = []
    for ch in text:
        f = cache.get(ch)
        if f is None:
            f = unicodedata.normalize("NFD", ch)[0].lower()
            cache[ch] = f
        out.append(f)
    return "".join(out)


# G.7: cheap detector for non-inline nodes (frontmatter `content:` marker);
# a body-text false positive only costs one harmless re-read via the parser
_CONTENT_MARKER_RE = re.compile(r"^content: (cached|reference)\s*$", re.MULTILINE)


def _raw_body(text: str) -> str:
    """Body of a node file without parsing the YAML frontmatter (same block
    boundaries as parser.split_frontmatter — sniff only needs the body)."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    nl = text.find("\n", end + 1)
    return text[nl + 1:].lstrip("\n") if nl != -1 else ""


def _sniff_snippet(line: str, pos: int) -> str:
    """Window of the line centered near the first occurrence (~25 tokens)."""
    line = line.rstrip()
    if len(line) <= SNIFF_SNIPPET_CHARS:
        return line.strip()
    start = max(0, pos - SNIFF_SNIPPET_CHARS // 3)
    end = min(len(line), start + SNIFF_SNIPPET_CHARS)
    start = max(0, end - SNIFF_SNIPPET_CHARS)
    out = line[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(line):
        out += "…"
    return out


def _scan_lines(body: str, folded_terms: list[str]) -> list[list[list]]:
    """The memoizable unit of C.6b.1: for each term, every line it occurs
    in, as `[line_no, section, pos, line_text]`.

    Line granularity is not an implementation taste — the scan emits one
    match per line centred on the LEFTMOST term that hit it, so per-term
    results can only be recombined if each carries its own position.

    One pass over the body for all the terms: folding is proportional to
    the corpus, and doing it once per term made a three-term question fold
    the whole forest three times.
    """
    folded_body = _fold(body)
    out: list[list[list]] = [[] for _ in folded_terms]
    present = [t in folded_body for t in folded_terms]
    if not any(present):
        return out
    section: str | None = None
    # `_fold` preserves length, so a position found in the folded line
    # indexes the original line.
    for line_no, (line, folded) in enumerate(
        zip(body.splitlines(), folded_body.splitlines()), start=1
    ):
        h = _HEADER_LINE_RE.match(line)
        if h and len(h.group(1)) in (2, 3):
            section = h.group(2)
        for i, term in enumerate(folded_terms):
            if not present[i]:
                continue
            pos = folded.find(term)
            if pos != -1:
                out[i].append([line_no, section, pos, line])
    return out


def _sniff_lines(body: str, folded_term: str) -> list[list]:
    """One term's line records — the shape a memo row holds."""
    return _scan_lines(body, [folded_term])[0]


def _combine_lines(per_term: list[list[list]]) -> tuple[list[dict], set[int]]:
    """Rebuild `_sniff_body`'s answer from per-term line records.

    Same output, by construction: one match per line, ordered by line
    number, its snippet centred on the smallest position among the terms
    that hit that line — which is what `first_pos` means in the direct
    scan.
    """
    best: dict[int, list] = {}
    terms_hit: set[int] = set()
    for i, lines in enumerate(per_term):
        if lines:
            terms_hit.add(i)
        for line_no, section, pos, line in lines:
            prev = best.get(line_no)
            if prev is None:
                best[line_no] = [section, pos, line]
            elif pos < prev[1]:
                prev[1] = pos
    matches = [
        {"section": section, "line": line_no,
         "snippet": _sniff_snippet(line, pos)}
        for line_no, (section, pos, line) in sorted(best.items())
    ]
    return matches, terms_hit


def _sniff_body(body: str, folded_terms: list[str]) -> tuple[list[dict], set[int]]:
    """All matching lines of a body, each attributed to its H2/H3 section.
    Returns (matches, indexes of the terms that hit anywhere in the body)."""
    folded_body = _fold(body)
    if not any(t in folded_body for t in folded_terms):
        return [], set()
    matches: list[dict] = []
    terms_hit: set[int] = set()
    section: str | None = None
    # _fold preserves length and never produces line breaks, so the folded
    # lines stay 1:1 with the original lines.
    for line_no, (line, folded) in enumerate(
        zip(body.splitlines(), folded_body.splitlines()), start=1
    ):
        h = _HEADER_LINE_RE.match(line)
        if h and len(h.group(1)) in (2, 3):
            section = h.group(2)
        first_pos: int | None = None
        for i, term in enumerate(folded_terms):
            pos = folded.find(term)
            if pos != -1:
                terms_hit.add(i)
                if first_pos is None or pos < first_pos:
                    first_pos = pos
        if first_pos is None:
            continue
        matches.append(
            {"section": section, "line": line_no, "snippet": _sniff_snippet(line, first_pos)}
        )
    return matches, terms_hit


def _is_index(node_id: str) -> bool:
    """A branch's auto-generated index (C.6b, C.6c.2)."""
    return node_id == "_index" or node_id.endswith("/_index")


def _is_system(node_id: str) -> bool:
    """The dialect's own files (`_meta/`) — served, but not content (C.6
    v0.54): a listing marks them `system: true` instead of leaving two
    tools to disagree about a branch's child count."""
    return node_id == "_meta" or node_id.startswith("_meta/")


def batch_ids(ids, cap: int, primitive: str) -> list[str]:
    """The id list of a C.11 batch, validated once for every surface.

    Duplicates collapse keeping first position: the same node read twice in
    one call is a mistake with no meaning worth preserving.
    """
    if not isinstance(ids, (list, tuple)):
        raise VineError(E_SCHEMA, f"{primitive} expects an id or a list of ids")
    if not ids:
        raise VineError(
            E_SCHEMA,
            f"{primitive} received an empty id list",
            hint="An empty batch is not a request for nothing; send at least one id.",
        )
    if len(ids) > cap:
        raise VineError(
            E_SCHEMA,
            f"{primitive} accepts at most {cap} ids in one call; got {len(ids)}",
            hint="A batch is one call and one budget (spec C.11): split it.",
        )
    out, seen = [], set()
    for i in ids:
        if not isinstance(i, str):
            raise VineError(
                E_SCHEMA,
                f"{primitive}: every id must be a string, got {type(i).__name__}",
            )
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def batch_shape(nodes: list[dict], missing: list[str], budget: int) -> dict:
    """C.11's response: one budget, whole items dropped from the tail, and
    every id the caller sent accounted for in exactly one list."""
    dropped: list[str] = []
    payload = {"nodes": nodes, "missing": missing, "dropped": dropped,
               "truncated": False}
    while nodes and estimate_payload_tokens(payload) > budget:
        gone = nodes.pop()
        dropped.insert(0, gone.get("id"))
        payload["truncated"] = True
    return payload


def _traced(fn):
    # Only primitives whose first argument IS a node id may report one.
    # `locate("payroll")` passes a query string positionally, and recording
    # that as `id` filed a search term where every reader expects a node —
    # harmless to Part D's metrics (a query never matches an answer node),
    # but a lie to anything that displays a trace.
    takes_id = list(inspect.signature(fn).parameters)[1:2] == ["id"]

    def wrapper(self: "Vine", *args, **kwargs):
        t0 = time.perf_counter()
        result = fn(self, *args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        node_id = kwargs.get("id") or (args[0] if takes_id and args else None)
        self.tracer.record(
            fn.__name__,
            node_id if isinstance(node_id, str) else None,
            tokens_in=estimate_tokens(json.dumps([str(a) for a in args]) + json.dumps(kwargs, default=str)),
            tokens_out=estimate_payload_tokens(result),
            elapsed_ms=elapsed,
        )
        return result

    return wrapper


class Vine:
    def __init__(
        self,
        root: str | Path,
        writable: bool = True,
        session: str | None = None,
        alpha: float = 0.3,
        embedder=None,
        beta: float = 1.0,
        hybrid_locate: bool = False,
    ):
        self.forest = Forest(root)
        self.catalog = Catalog(self.forest)
        self.trails = Trails(self.forest.derived_dir)
        self.payload_cache = PayloadCache(self.forest.derived_dir)
        self.tracer = Tracer(self.forest.derived_dir, self.trails, session)
        self.alpha = alpha
        self.beta = beta
        self.writable = writable
        self.git = GitRepo(self.forest.root)
        self._write_mutex = threading.Lock()
        self._lock: WriterLock | None = None
        if writable:
            self._lock = WriterLock(self.forest.root)
            self._lock.acquire()
        if self.catalog.count() == 0:
            self.catalog.reindex()
        # Canopy (optional vector layer, Phase 1). BM25-only unless BOTH a
        # built index and a query embedder are present (locate contract is
        # unchanged otherwise — architecture doc §3).
        self.embedder = embedder
        self.canopy = CanopyIndex.load(self.forest.derived_dir)
        # The Gauntlet's goal (Part K): the vector of the most recent hunt.
        # `locate` embeds the query anyway when the dense layer is on, so
        # carrying it costs one embedding per hunt instead of one per hop.
        # Entry search stays lexical unless explicitly asked otherwise.
        # Measurement (Part K changelog) showed fusing a dense ranker into
        # an already-correct BM25 *degrades* it — so the dense layer being
        # available must not imply using it here.
        # Public and writable for the same reason `embedder` is (J.0): a host
        # offering the per-call switch K.3 requires must be able to flip it
        # without forking the pool. Off is the default and stays the default.
        self.hybrid_locate = hybrid_locate
        self._goal: list[float] | None = None
        self._goal_text: str | None = None

    @property
    def commit_trailers(self) -> list[str]:
        """J.4 (v0.57): lines the next commit appends after a blank line —
        a public, host-writable seam in the J.0 pattern (`embedder`,
        `hybrid_locate`). The host sets it around each scoped write to
        stamp the acting principal in the commit itself, retiring the
        amend; the engine appends what it is handed and never reads it."""
        return self.git.trailers

    @commit_trailers.setter
    def commit_trailers(self, value: list[str] | None) -> None:
        self.git.trailers = list(value or [])

    @property
    def dense_ready(self) -> bool:
        """Whether a usable vector layer exists. NOT whether to use it: the
        two consumers — entry search and the Gauntlet — decide separately,
        because measurement says one is helped by it and the other harmed."""
        return (
            self.embedder is not None
            and self.canopy is not None
            and len(self.canopy) > 0
            # K.4: comparing a query embedded by one model against vectors
            # produced by another compares two unrelated spaces. That does
            # not rank badly, it ranks meaninglessly — and it fails silently,
            # because a dot product always returns a number. A mismatched
            # index is therefore treated as no index at all.
            and self.canopy.model == self.embedder.model
        )

    @property
    def hybrid(self) -> bool:
        """RRF fusion in `locate`. Off unless asked for, on purpose."""
        return self.hybrid_locate and self.dense_ready

    @property
    def canopy_status(self) -> dict:
        """Why the dense layer is or is not active (K.4), for validation and
        for any surface that shows index health."""
        index_model = self.canopy.model if self.canopy is not None else None
        query_model = self.embedder.model if self.embedder is not None else None
        if self.embedder is None:
            state = "no-embedder"
        elif self.canopy is None or len(self.canopy) == 0:
            state = "no-index"
        elif index_model != query_model:
            state = "model-mismatch"
        else:
            state = "active"
        return {"state": state, "active": state == "active",
                "index_model": index_model, "query_model": query_model,
                "vectors": len(self.canopy) if self.canopy is not None else 0,
                # K.4 (v0.42): what a refresh would cost, before it runs. A
                # layer quietly behind is indistinguishable from a current
                # one, and since v0.42 no read pays this debt down by
                # surprise — somebody has to choose to.
                "stale": len(self.catalog.stale_ids())}

    # -- the Gauntlet (Part K) ---------------------------------------------

    def _goal_for(self, toward: str | None, enabled: bool | None):
        """The goal vector for this call, or None to leave the order alone.

        Returns None whenever ANY precondition fails (K.1), because the
        contract is that an absent Gauntlet is not a degraded mode — it is
        v0.20 behaviour, byte for byte. Every caller therefore only has to
        check for None.
        """
        if enabled is False or not self.dense_ready:
            return None
        if toward:
            # An explicit goal costs its own embedding — once per distinct
            # text, since v0.42 (K.6). That is the price of testability, and
            # it is why it is not the default path.
            return self.embed_query(toward), toward
        if self._goal_text is None:
            return None
        if self._goal is None:
            # Paid once, on the first hop of the hunt — not in `locate`, and
            # never at all for a hunt that only ever reads the entry list.
            # Nothing is re-embedded here but the goal itself (K.2, v0.42).
            self._goal = self.embed_query(self._goal_text)
        return self._goal, self._goal_text

    def _rank_frontier(self, items, goal, id_of=lambda x: x["id"],
                       signal_of=lambda x: 0.0):
        """Order a frontier by proximity to the goal, in place.

        Proximity decides and the existing signal — heat, degree — breaks
        near-ties: rounding the cosine to three places makes "as close as
        each other" mean something, so a node the colony has found useful
        before still wins between equals. Heat stays a memory of past hunts
        (Part H depends on that); it simply stops being the only voice.
        """
        vectors = {i: v for i, v in zip(self.canopy.ids, self.canopy.vectors)}
        def key(item):
            vec = vectors.get(id_of(item))
            prox = cosine(goal, vec) if vec is not None else -1.0
            return (-round(prox, 3), -signal_of(item))
        items.sort(key=key)

    def build_canopy(self, embedder=None) -> dict:
        """Embed every node's summary and persist the vector index. Offline
        (Gardener territory): generous compute, runs out of the read path."""
        emb = embedder or self.embedder
        if emb is None:
            raise VineError(E_SCHEMA, "build_canopy needs an embedder")
        rows = self.catalog.conn.execute(
            "SELECT id, title, summary FROM nodes ORDER BY id"
        ).fetchall()
        pairs = [(r["id"], f"{r['title']}. {r['summary']}") for r in rows]
        idx = CanopyIndex.build(pairs, emb)
        idx.save(self.forest.derived_dir)
        self.canopy = idx
        self.catalog.clear_stale(self.catalog.stale_ids())
        return {"nodes": len(idx), "model": idx.model, "dim": idx.dim}

    def embed_query(self, text: str) -> list[float]:
        """Embed ONE caller-supplied text, through the K.6 memo.

        `embed(model, text)` is pure, so the round trip is owed once per
        distinct question rather than once per asking. Node vectors do not
        come through here: the Canopy index is their home, and a second
        copy would be a second answer to "what is this node's vector".
        """
        key = " ".join(str(text).split())
        model = self.embedder.model
        cached = self.catalog.embed_memo(model, key)
        if cached is not None:
            self.catalog.embed_memo_touch(model, key)
            return cached
        vec = self.embedder.embed([text])[0]
        self.catalog.embed_memo_store(model, key, vec)
        return vec

    def refresh_canopy(self) -> dict:
        """Embed the nodes marked stale by plant/graft/ingest (J.13.4).

        Maintenance, never a read: this used to run inside `locate`, which
        meant the question that happened to arrive after an ingest paid for
        every document of it — unbounded work inside the primitive with the
        tightest budget in the spec (F.6). It is triggered now, and what it
        will cost is reported before it runs (K.4's `stale`).
        """
        if self.embedder is None:
            raise VineError(E_SCHEMA, "refreshing the dense layer needs an embedder",
                            hint="Bind an embedding model, then refresh.")
        if not self.dense_ready:
            raise VineError(
                E_SCHEMA, "the dense layer is not usable, so a partial "
                          "re-embed would leave it in two spaces at once",
                hint="Build the index first (K.4): a model change requires a "
                     "full build, never a refresh.")
        stale = self.catalog.stale_ids()
        self._refresh_canopy()
        return {"refreshed": len(stale), **self.canopy_status}

    def _refresh_canopy(self) -> None:
        """The re-embed itself. Called by `refresh_canopy` and by nothing in
        a read path — see K.2 as amended in v0.42."""
        stale = self.catalog.stale_ids()
        if not stale:
            return
        rows = [self.catalog.get(i) for i in stale]
        pairs = [(r["id"], f"{r['title']}. {r['summary']}") for r in rows if r is not None]
        if pairs:
            vecs = self.embedder.embed([t for _, t in pairs])
            for (node_id, _), vec in zip(pairs, vecs):
                self.canopy.upsert(node_id, vec)
            self.canopy.save(self.forest.derived_dir)
        self.catalog.clear_stale(stale)

    # -- lifecycle ---------------------------------------------------------

    def warm(self) -> None:
        """Pay the first call's start-up cost before there is a first call.

        Opening a forest is not free and neither is the first query through
        it — measured on a fresh process, `locate` costs several times what
        it costs from the second call on, all of it SQLite waking up. That
        is a fact about the process, not about the forest, and a caller who
        happens to be first should not be shown it as the cost of the call.

        Storage only, and never a primitive: a warm-up that went through
        `locate` would append a trace event and deposit heat, so the server
        would be forging the pheromone the Ranger later reads as evidence of
        where people went (Part D, Part H). Bodies are not touched either —
        that is the whole corpus off disk, which is a different trade.
        """
        self.catalog.warm()
        self.trails.warm()

    def close(self) -> None:
        if self._lock:
            self._lock.release()
            self._lock = None
        self.catalog.close()
        self.trails.close()

    def __enter__(self) -> "Vine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def reindex(self) -> int:
        return self.catalog.reindex()

    def close_session(self, success: bool, answer_nodes: list[str]) -> dict:
        return self.tracer.close_session(success, answer_nodes, trail_of=self.forest.trail)

    # -- helpers -----------------------------------------------------------

    def _heat(self, node_id: str) -> float:
        return self.trails.get_heat(node_id, self.tracer.session)

    def _summary_of(self, node_id: str) -> str:
        row = self.catalog.get(node_id)
        return row["summary"] if row else ""

    def _row_or_raise(self, node_id: str) -> sqlite3.Row:
        row = self.catalog.get(node_id)
        if row is None:
            if self.forest.exists(node_id):
                self.catalog.upsert_node(self.forest.read(node_id))
                return self.catalog.get(node_id)
            moved = self.catalog.moved_to(node_id)
            if moved:
                # C.15 rule 4: "it is not here" is half the truth when the
                # other half is known. The host withholds `moved_to` when
                # the destination is out of the reader's scope (J.3).
                raise VineError(
                    E_MOVED,
                    f"node moved: {node_id}",
                    hint=f"It now lives at '{moved}'; update your reference.",
                    data={"moved_to": moved},
                )
            raise VineError(
                E_NOT_FOUND,
                f"node not found: {node_id}",
                hint="Use locate() to find entry points.",
            )
        return row

    # =======================================================================
    # C.1 locate — the helicopter
    # =======================================================================

    @_traced
    def locate(
        self,
        query: str,
        k: int = 5,
        scope: str = "all",
        type_filter: str | None = None,
        include: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        date_field: str | None = None,
    ) -> dict:
        if include is not None:
            unknown = [i for i in include if i not in LOCATE_INCLUDE]
            if not isinstance(include, list) or unknown:
                raise VineError(
                    E_SCHEMA,
                    f"include accepts {sorted(LOCATE_INCLUDE)}; got {unknown or include!r}",
                    hint="include=['outline'] adds each result's section headers.",
                )
        scope = _SCOPE_ALIASES.get(scope, scope)
        if scope not in LOCATE_SCOPES:
            # C.12 rule 7 (v0.54): treated as "all", a typo returns a result
            # the caller believes was filtered.
            raise VineError(
                E_SCHEMA,
                f"scope expects one of {sorted(LOCATE_SCOPES)}, got {scope!r}",
                hint="'branches' lands in regions, 'notes' on leaves, "
                     "'all' searches both.",
            )
        # C.13.1: the window is decided here, where the candidates are
        # chosen — a filter applied to the ranked top-k returns fewer than
        # k while the forest still holds matches, and the caller reads a
        # scarcity the implementation invented.
        window = normalize_window(since, until, date_field)
        win_where, win_params = window_sql(window)
        cand = max(k * 5, 25)
        rows = self.catalog.fts_search(query, limit=cand, where=win_where,
                                       params=win_params)
        by_id = {r["id"]: r for r in rows}

        # base strength per id, in [0, 1]. BM25-only by default (Phase 0);
        # RRF(vector, BM25) when the canopy layer is active (Phase 1).
        # The hunt's goal is REMEMBERED here and embedded later, on the first
        # hop that actually needs it (K.2). Embedding it now would put a
        # network round trip inside `locate`, whose budget is 100 ms p95 —
        # and would charge it to every hunt that never leaves the entry list.
        self._goal, self._goal_text = None, query
        if self.hybrid:
            # The query, and nothing else (K.2 as amended in v0.42). Node
            # vectors are refreshed by J.13.4, not by whoever asked next.
            qvec = self.embed_query(query)
            self._goal = qvec
            vec_hits = self.canopy.search(qvec, k=cand)
            for vid, _cos in vec_hits:
                if vid not in by_id:
                    extra = self.catalog.get(vid)
                    # The dense half meets the same window as the lexical
                    # one: a filter that holds for only one of two fused
                    # rankings is not a filter (C.13.1 rule 2).
                    if extra is not None and (
                            window is None
                            or in_window(extra[window["date_field"]], window)):
                        by_id[vid] = extra
            bm25_ids = [r["id"] for r in rows]
            vec_ids = [vid for vid, _ in vec_hits]
            fused = rrf_fuse(bm25_ids, vec_ids)
            top = max(fused.values()) if fused else 1.0
            strength_of = {i: (s / top if top else 0.0) for i, s in fused.items()}
        else:
            best = min((r["rank"] for r in rows), default=0.0)  # bm25: lower=better (<=0)
            strength_of = {
                r["id"]: ((r["rank"] / best) if best < 0 else 1.0) for r in rows
            }

        candidates = list(by_id.values())
        if scope == "branches":
            candidates = [r for r in candidates if r["kind"] == "branch"]
        elif scope == "notes":
            candidates = [r for r in candidates if r["kind"] == _KIND_LEAF]
        if type_filter:
            candidates = [r for r in candidates if r["type"] == type_filter]

        wants_outline = bool(include) and "outline" in include
        results = []
        for r in candidates:
            strength = strength_of.get(r["id"], 0.0)
            heat = self._heat(r["id"])
            score = strength * (1 + self.alpha * heat)
            item = {
                "id": r["id"],
                "kind": _wire_kind(r["kind"]),
                "type": r["type"],
                "title": r["title"],
                "summary": r["summary"],
                "trail": json.loads(r["trail"]),
                "score": round(score, 4),
                "heat": heat,
                # C.1.1 (v0.52): the size of what the caller is about to
                # open, at the one moment it changes the decision. The
                # catalog row is already in hand, so it costs nothing.
                "body_tokens": r["body_tokens"],
            }
            if r["kind"] == "branch" and r["coverage"]:
                # C.1 (v0.54): machine fields carry numbers; the prose
                # rendering stays in the index bodies.
                item["coverage"] = (indexer.parse_coverage(r["coverage"])
                                    or r["coverage"])
            if wants_outline:
                # Same row again: the hop whose only purpose was learning
                # which section to pick (C.1.1 rule 2).
                item["outline"] = json.loads(r["outline"])
            results.append(item)
        results.sort(key=lambda x: x["score"], reverse=True)
        payload = {"results": results[:k], "truncated": len(results) > k}
        payload = shrink_list_to_budget(payload, "results", BUDGET_LOCATE)
        if window:
            payload["window"] = window
            undated = self.undated_count(window["date_field"])
            if undated:
                payload["undated_excluded"] = undated
        if not payload["results"]:
            # C.1.1 rule 3 / C.13.2: an empty entry list is indistinguishable
            # from a forest that knows nothing — and, under a window, from a
            # window that holds nothing. Three situations, three repairs, so
            # the response says which one it is. Computed HERE and nowhere
            # else: a caller holding results was already told what it needed.
            payload.update(self.empty_context(window, "No curated scent "
                                              "matched"))
        return payload

    def _scope_where(self, scope: str | None) -> tuple[list[str], list]:
        """A scope as a predicate: one node, one subtree, or the forest.

        Shared by `sniff` (C.6b) and `calendar` (C.13.3) so that "scope" is
        one idea with one resolution — a second reading of the same word
        would agree only where somebody compared them.
        """
        where: list[str] = []
        params: list = []
        if not scope:
            return where, params
        scope = scope.strip().strip("/")
        row = self.catalog.get(scope)
        if row is not None and row["kind"] == "banana":
            where.append("{n}id = ?")
            params.append(scope)
            return where, params
        scope_id = (scope if scope == "_index" or scope.endswith("/_index")
                    else f"{scope}/_index")
        self._row_or_raise(scope_id)
        if scope_id != "_index":
            prefix = scope_id[: -len("_index")]  # "<branch>/_index" -> "<branch>/"
            # substr, not LIKE: '_' is a single-character wildcard there and
            # node ids are full of them ('_index'), so LIKE would silently
            # widen the scope the caller asked to narrow.
            where.append("substr({n}id, 1, ?) = ?")
            params.extend([len(prefix), prefix])
        return where, params

    def undated_count(self, field: str, *,
                      policy_where: tuple[list[str], list] | None = None) -> int:
        """Nodes a window can never match (C.13.1 rule 5). Reported only
        when there are any: a forest with complete passports should not pay
        a line of response for a zero.

        `policy_where` is the host's scope predicate (J.3) — every number a
        scoped caller reads must be about the nodes it may see, and this one
        is no exception: a global count of undated nodes describes a region
        nobody granted.
        """
        where, params = policy_where or ([], [])
        return self.catalog.count_nodes(
            where + [f"({{n}}{field} IS NULL OR {{n}}{field} = '')"], list(params))

    def empty_context(self, window: dict | None, what: str, *,
                      policy_where: tuple[list[str], list] | None = None) -> dict:
        """What an empty read owes its caller (C.1.1 rule 3, C.13.2).

        Without a window: how large the space was, and the search this
        primitive does not perform. With one: whether the WINDOW was the
        reason — which is a different mistake from a question that matched
        nothing, and needs a different repair — plus where the material
        actually sits, so the next call is a correction and not a guess.

        Every count and every period here passes through `policy_where`
        (J.3). A hint is prose, but "this forest holds 82 nodes from January
        to August" is a measurement, and a scoped caller must not read one
        about a region it was never granted — which is exactly the oracle
        C.1.1 refused for `searched`.
        """
        pol_where, pol_params = policy_where or ([], [])
        out: dict = {"searched": self.catalog.count_nodes(pol_where,
                                                          list(pol_params))}
        if not window:
            out["hint"] = (
                f"{what}. locate() searches titles, summaries and tags only "
                "— sniff(terms) searches the bodies, where an exact term may "
                "be waiting.")
            return out
        where, params = window_sql(window)
        matched = self.catalog.count_nodes(pol_where + where,
                                           list(pol_params) + params)
        out["matched_window"] = matched
        span = nearest_periods(
            self.catalog.date_buckets(window["date_field"], "month",
                                      pol_where, list(pol_params)), window)
        edges = span["range"]
        nearest = ", ".join(f"{b['period']} ({b['nodes']})"
                            for b in span["nearest"]) or "none"
        if matched:
            out["hint"] = (
                f"{what}, though {matched} node(s) fall in that window — the "
                "window is not the reason. Try sniff(terms) for exact text in "
                "bodies, or ask a wider question.")
        else:
            out["hint"] = (
                f"No node has a {window['date_field']} date inside that "
                f"window, so the question was never tested against anything. "
                f"This forest holds {edges['nodes']} dated node(s) from "
                f"{edges['first']} to {edges['last']}; nearest periods with "
                f"material: {nearest}. Widen the window, drop it, or call "
                "calendar() to see where the material sits.")
        return out

    # =======================================================================
    # C.2 look — the central operation (<= 500 tokens)
    # =======================================================================

    @_traced
    def look(self, id, fields: list[str] | None = None,
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
        if isinstance(id, (list, tuple)):
            ids = batch_ids(id, MAX_BATCH_LOOK, "look")
            nodes, missing = [], []
            for nid in ids:
                try:
                    nodes.append(self._look(nid, fields=fields, gauntlet=gauntlet,
                                            toward=toward))
                except VineError as e:
                    if e.code == E_NOT_FOUND and not self.forest.exists(nid):
                        missing.append(nid)
                        continue
                    raise
            return batch_shape(nodes, missing, BUDGET_LOOK_BATCH)
        return self._look(id, fields=fields, gauntlet=gauntlet, toward=toward)

    def _look(self, id: str, fields: list[str] | None = None,
              gauntlet: bool | None = None, toward: str | None = None) -> dict:
        row = self._row_or_raise(id)
        node = self.forest.read(id)
        digest: dict = {
            "id": id,
            "type": row["type"],
            "title": row["title"],
            "summary": row["summary"],
            "tags": json.loads(row["tags"]),
            "confidence": row["confidence"],
            # C.2 (v0.56): the passport says who and when. Both were in
            # every passport and the catalog since their birth; the digest
            # just never said them, so provenance read as absent.
            "created": row["created"],
            "updated": row["updated"],
            "source": row["source"],
        }
        aliases = json.loads(row["aliases"]) if row["aliases"] else []
        if aliases:
            digest["aliases"] = aliases
        if "origin" in row.keys() and row["origin"]:
            # A.3 (v0.57): provenance toward the world outside the forest.
            digest["origin"] = row["origin"]

        edges_out = []
        for e in self.catalog.edges_out(id):
            edges_out.append(
                {
                    "rel": e["rel"],
                    "target": e["dst"],
                    "target_summary": truncate_text(
                        self._summary_of(e["dst"]), NEIGHBOR_SUMMARY_TOKENS
                    ),
                    "_heat": self._heat(e["dst"]),
                }
            )
        edges_out.sort(key=lambda e: e["_heat"], reverse=True)
        edges_in = []
        for e in self.catalog.edges_in(id):
            shown_rel = self.forest.dialect.inverse(e["rel"]) or e["rel"]
            edges_in.append({"rel": shown_rel, "source": e["src"], "_heat": self._heat(e["src"])})
        edges_in.sort(key=lambda e: e["_heat"], reverse=True)
        degree = len(edges_out) + len(edges_in)
        _defer_heat_pop = edges_out + edges_in
        # Part K: condition the frontier BEFORE the cap, which is the whole
        # point — reordering after the cut cannot recover what the cut hid.
        #
        # But not when the caller asked for fields that contain no frontier:
        # the `fields` filter below would drop the order anyway, and the goal
        # is embedded lazily, so ranking a discarded list meant a network
        # round trip for nothing. `harvest` does exactly that — one
        # `look(id, fields=["summary"])` per result — and it was charging
        # every harvest and every answer ~150 ms of embedding for output no
        # caller ever sees.
        wants_frontier = not fields or bool(
            {"edges_out", "edges_in", "frontier"} & set(fields))
        goal = self._goal_for(toward, gauntlet) if wants_frontier else None
        if goal is not None:
            self._rank_frontier(edges_out, goal[0],
                                id_of=lambda e: e["target"],
                                signal_of=lambda e: e["_heat"])
            self._rank_frontier(edges_in, goal[0],
                                id_of=lambda e: e["source"],
                                signal_of=lambda e: e["_heat"])
            digest["frontier"] = {"ranked": True, "toward": goal[1]}
        for e in _defer_heat_pop:
            e.pop("_heat", None)
        digest["edges_out"] = edges_out[:MAX_EDGES_SHOWN]
        digest["edges_in"] = edges_in[:MAX_EDGES_SHOWN]

        if row["kind"] == "branch":
            children = [
                {"id": c["id"], "summary": truncate_text(c["summary"], NEIGHBOR_SUMMARY_TOKENS)}
                for c in self.catalog.children(id)
            ]
            digest["children"] = children
            cross = extract_section(node.body, "Cross trails")
            if cross:
                digest["cross_trails"] = [
                    ln.lstrip("- ").strip() for ln in cross.splitlines()[1:] if ln.strip().startswith("-")
                ]
            if row["coverage"]:
                # C.2 (v0.54): same rule as locate — counts, not prose.
                digest["coverage"] = (indexer.parse_coverage(row["coverage"])
                                      or row["coverage"])
        else:
            digest["outline"] = json.loads(row["outline"])

        if row["type"] == "dataset" and row["payload_type"] == "sqlite":
            # Each of these opens the payload, so a caller that named its
            # fields does not pay for the ones it did not ask for — the
            # sweep asks for exactly one of them, per result (C.6c).
            wanted = set(fields) if fields else None
            if wanted is None or "query_manual" in wanted:
                digest["query_manual"] = self._dataset_manual(node)
            if wanted is None or "sample_rows" in wanted:
                digest["sample_rows"] = self._dataset_sample(node)
            # C.2.1: what a person taught about this data. It rides in the
            # digest because the path an agent takes to a dataset is `look`
            # then `query` — a note reachable only through `pick` is a note
            # it will not read.
            if wanted is None or "notes" in wanted:
                notes, clipped = self._dataset_notes(node)
                if notes:
                    digest["notes"] = notes
                    if clipped:
                        digest["truncated"] = True

        digest["stats"] = {
            "body_tokens": row["body_tokens"],
            "degree": degree,
            "heat": self._heat(id),
        }

        if fields:
            keep = set(fields) | {"id"}
            digest = {k: v for k, v in digest.items() if k in keep}

        # C.2 (v0.57): the budget clips in declared order — the outline
        # first (big, and re-derivable through pick's first page), edges
        # after it, a dataset's sample rows only as the last resort (its
        # digest exists to feed `query`) — and every field the budget
        # touched is NAMED. The old shrink took the edges while a 28-item
        # outline stayed: `edges_out: []` beside `stats.degree: 2`, and the
        # caller concluded the node was isolated.
        clipped: list[str] = []
        was_truncated = digest.get("truncated")
        if estimate_payload_tokens(digest) > BUDGET_LOOK:
            # C.6.2's pattern: the meta fields sit INSIDE the budget at
            # their largest possible size while the lists are cut, and only
            # their values are fixed up afterwards — the 500 stays a
            # ceiling.
            digest["truncated"] = True
            digest["truncated_fields"] = ["outline", "children",
                                          "edges_in", "edges_out",
                                          "sample_rows"]
        for key in ("outline", "children", "edges_in", "edges_out"):
            if key in digest and estimate_payload_tokens(digest) > BUDGET_LOOK:
                before = len(digest[key])
                shrink_list_to_budget(digest, key, BUDGET_LOOK)
                if len(digest[key]) < before:
                    clipped.append(key)
        if estimate_payload_tokens(digest) > BUDGET_LOOK:
            if digest.pop("sample_rows", None) is not None:
                clipped.append("sample_rows")
        if clipped:
            digest["truncated"] = True
            digest["truncated_fields"] = clipped
        else:
            digest.pop("truncated_fields", None)
            if not was_truncated and estimate_payload_tokens(digest) <= BUDGET_LOOK:
                digest.pop("truncated", None)
        return digest

    def _dataset_db(self, node: ParsedNode, *, for_write: bool = False) -> Path:
        payload = node.frontmatter.get("payload")
        if is_remote(payload):
            if for_write:
                raise VineError(
                    E_QUERY_FORBIDDEN,
                    f"remote payload is read-only: {payload}",
                    hint="Datasets are local-first (spec G.9.4): bring the .db "
                         "local to tend it — editing a cached copy would fork it.",
                )
            # G.9: download-on-first-use, hash-validated, LRU-touched (H.6)
            return self.payload_cache.get(
                str(payload), node.frontmatter.get("payload_hash"))
        db = self.forest.payload_path(node)
        if not db.is_file():
            raise VineError(E_NOT_FOUND, f"payload missing: {db.name}")
        return db

    def prefetch(self, scope: str = "_index") -> dict:
        """G.9.5 — the parachute warms the camp: after locate drops the monkey
        on a region, pull every remote payload under it in one sweep so the
        following sniff/query hops run at local speed."""
        scope = scope.strip().strip("/")
        if scope in ("", "_index"):
            prefix = ""
        elif scope.endswith("/_index"):
            prefix = scope[: -len("_index")]
        else:
            prefix = scope + "/"
        fetched, local, errors = [], 0, []
        for row in self.catalog.conn.execute(
            "SELECT id, payload, payload_hash FROM nodes WHERE payload IS NOT NULL"
        ).fetchall():
            if prefix and not row["id"].startswith(prefix):
                continue
            if not is_remote(row["payload"]):
                local += 1
                continue
            try:
                self.payload_cache.get(row["payload"], row["payload_hash"])
                fetched.append(row["id"])
            except VineError as e:
                errors.append(f"{row['id']}: {e.message}")
        return {"scope": scope or "_index", "fetched": fetched,
                "already_local": local, "errors": errors}

    def _dataset_manual(self, node: ParsedNode) -> dict:
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            tables = {}
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ):
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({name})")]
                tables[name] = cols
        finally:
            conn.close()
        manual_section = extract_section(node.body, "Query manual") or ""
        example_queries = re.findall(r"`(SELECT[^`]+)`", manual_section, re.IGNORECASE)[:3]
        return {"tables": tables, "example_queries": example_queries}

    @staticmethod
    def _name_hint(conn, error: str, allowed: frozenset[str] | None = None) -> str | None:
        """What exists, for a query that named something that does not.

        Only for the two errors where a list is the answer — anything else
        gets no hint rather than an irrelevant one. Best effort by
        construction: this runs while an exception is already being raised,
        so a failure here must not replace the error the caller needs.

        `allowed` narrows it to what the caller may read. The hint runs after
        the statement failed and therefore after the authorizer was cleared,
        so without this it would answer "no such table" by naming every table
        in the file — handing a scoped principal the list of what is being
        kept from them, for the price of one misspelling.
        """
        text = error.lower()

        def permitted(names: list[str]) -> list[str]:
            if allowed is None:
                return names
            return [n for n in names if str(n).lower() in allowed]

        try:
            if text.startswith("no such table"):
                names = permitted([r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")])
                return f"Tables in this dataset: {', '.join(names)}." if names else None
            if text.startswith("no such column"):
                names = permitted([r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")])
                columns: list[str] = []
                for name in names[:4]:
                    quoted = '"' + str(name).replace('"', '""') + '"'
                    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({quoted})")]
                    columns.append(f"{name}({', '.join(cols[:25])})")
                return f"Columns: {'; '.join(columns)}." if columns else None
        except sqlite3.Error:
            return None
        return None

    def _dataset_notes(self, node: ParsedNode) -> tuple[str, bool]:
        """C.2.1: the operator's `## Notes`, clipped to its own budget.

        Clipped here rather than left to the digest's overall check so the
        cut is stated instead of the whole section vanishing, and so a long
        note cannot starve the rest of the digest. Header line dropped —
        the key already names it.
        """
        section = extract_section(node.body, NOTES_SECTION)
        if not section:
            return "", False
        text = "\n".join(section.splitlines()[1:]).strip()
        if not text:
            return "", False
        clipped = truncate_text(text, BUDGET_NOTES)
        return clipped, clipped != text

    def _dataset_sample(self, node: ParsedNode, n: int = 3) -> dict:
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            if not row:
                return {"columns": [], "rows": []}
            cur = conn.execute(f"SELECT * FROM {row[0]} LIMIT {n}")
            return {
                "columns": [d[0] for d in cur.description],
                "rows": [list(r) for r in cur.fetchall()],
            }
        finally:
            conn.close()

    # =======================================================================
    # C.3 move — structural navigation (<= 600 tokens)
    # =======================================================================

    @_traced
    def move(self, id: str, rel: str | None = None, direction: str = "out",
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
        if direction not in MOVE_DIRECTIONS:
            # C.3 (v0.54): matched against nothing, an unknown direction
            # returned an empty neighbour list — byte-identical to an
            # isolated node, on nodes with degree > 0.
            raise VineError(
                E_SCHEMA,
                f"direction expects one of {sorted(MOVE_DIRECTIONS)}, "
                f"got {direction!r}",
                hint="Every direction at once is 'both' here; 'all' is "
                     "locate's scope word, not a direction.",
            )
        self._row_or_raise(id)
        neighbors: list[dict] = []

        if rel == "children":
            for c in self.catalog.children(id):
                neighbors.append(
                    {
                        "id": c["id"],
                        "rel": "children",
                        "direction": "out",
                        "type": c["type"],
                        "summary": c["summary"],
                        "heat": self._heat(c["id"]),
                    }
                )
        else:
            if direction in ("out", "both"):
                for e in self.catalog.edges_out(id):
                    if rel and e["rel"] != rel:
                        continue
                    neighbors.append(
                        {
                            "id": e["dst"],
                            "rel": e["rel"],
                            "direction": "out",
                            "type": (self.catalog.get(e["dst"]) or {"type": "?"})["type"],
                            "summary": self._summary_of(e["dst"]),
                            "heat": self._heat(e["dst"]),
                        }
                    )
            if direction in ("in", "both"):
                for e in self.catalog.edges_in(id):
                    shown = self.forest.dialect.inverse(e["rel"]) or e["rel"]
                    if rel and rel not in (e["rel"], shown):
                        continue
                    neighbors.append(
                        {
                            "id": e["src"],
                            "rel": shown,
                            "direction": "in",
                            "type": (self.catalog.get(e["src"]) or {"type": "?"})["type"],
                            "summary": self._summary_of(e["src"]),
                            "heat": self._heat(e["src"]),
                        }
                    )

        neighbors.sort(key=lambda n: n["heat"], reverse=True)
        goal = self._goal_for(toward, gauntlet)
        if goal is not None:
            self._rank_frontier(neighbors, goal[0],
                                signal_of=lambda n: n.get("heat", 0.0))
        payload = {"neighbors": neighbors, "truncated": False}
        if goal is not None:
            payload["frontier"] = {"ranked": True, "toward": goal[1]}
        return shrink_list_to_budget(payload, "neighbors", BUDGET_MOVE)

    # =======================================================================
    # C.4 pick — harvest the banana
    # =======================================================================

    def _resolved_body(self, node: ParsedNode) -> str:
        """G.7 lazy FLESH resolution: cached -> _derived/bodies, reference ->
        the source file itself. Inline nodes return their own body."""
        mode = node.frontmatter.get("content")
        if mode == "cached":
            f = self.forest.body_cache_path(node.id)
            if not f.is_file():
                raise VineError(
                    E_NOT_FOUND,
                    f"cached body missing for {node.id}",
                    hint="Re-run `vine sync` with the sources reachable to rebuild "
                         "_derived/bodies. The map (locate/look/scan) keeps working.",
                )
            return f.read_text(encoding="utf-8")
        if mode == "reference":
            root = self.forest.gardener_source_root()
            sp = node.frontmatter.get("source_path")
            f = (root / str(sp)) if root and sp else None
            if f is not None and not f.resolve().is_relative_to(root.resolve()):
                # G.7: a reference body lives UNDER the adopted source root.
                # `source_path` is ordinary frontmatter (models.py allows
                # extras), so a planted `../../` would otherwise turn a read
                # primitive into arbitrary host reads with the Vine's
                # authority — reported as if the node owned the file.
                raise VineError(
                    E_NOT_FOUND,
                    f"reference body unreachable for {node.id}",
                    hint="source_path leaves the adopted source root. The map "
                         "(locate/look/scan) keeps working.",
                )
            if f is None or not f.is_file():
                raise VineError(
                    E_NOT_FOUND,
                    f"reference body unreachable for {node.id}",
                    hint=f"source file: {f}. The map (locate/look/scan) keeps working.",
                )
            return f.read_text(encoding="utf-8", errors="replace")
        return node.body

    @_traced
    def pick(self, id, section=None, after: str | None = None) -> dict:
        if isinstance(id, (list, tuple)):
            if after is not None:
                raise VineError(
                    E_SCHEMA,
                    "after pages one document; pass a single id",
                    hint="A cursor resumes one body (C.4.1); a batch of ids "
                         "has no single body to resume.",
                )
            ids = batch_ids(id, MAX_BATCH_PICK, "pick")
            nodes, missing = [], []
            for nid in ids:
                try:
                    nodes.append(self._pick(nid, section=section))
                except VineError as e:
                    # A missing SECTION is not a missing node: it names an
                    # id the caller can see and a header it cannot, and
                    # burying that in `missing` would report the node absent.
                    if e.code == E_NOT_FOUND and not self.forest.exists(nid):
                        missing.append(nid)
                        continue
                    raise
            return batch_shape(nodes, missing, BUDGET_PICK_BATCH)
        return self._pick(id, section=section, after=after)

    def _pick(self, id: str, section=None, after: str | None = None) -> dict:
        node = self.forest.read(id)
        body, outline = node.body, node.outline
        if node.frontmatter.get("content") in ("cached", "reference"):
            body = self._resolved_body(node)
            _, _, outline = extract_outline(body)
        body_tokens = estimate_tokens(body)
        if section is not None and after is not None:
            # C.4.1 rule 5: two addressing schemes in one call.
            raise VineError(
                E_SCHEMA,
                "after and section cannot be combined",
                hint="after pages the whole body; section addresses pieces "
                     "of it by name. Pass one.",
            )
        if isinstance(section, (list, tuple)):
            return self._pick_sections(id, node.title, body, outline,
                                       list(section))
        if section:
            content = extract_section(body, section)
            if content is None:
                raise VineError(
                    E_NOT_FOUND,
                    f"section '{section}' not found in {id}",
                    hint=f"Available sections: {outline}",
                )
            return {
                "id": id,
                "title": node.title,
                "section": section,
                "body": content,
                "body_tokens": estimate_tokens(content),
                "truncated": False,
            }
        if after is not None or body_tokens > PICK_MAX_BODY_TOKENS:
            return self._pick_page(id, node.title, body, body_tokens,
                                   outline, after)
        return {
            "id": id,
            "title": node.title,
            "body": body,
            "body_tokens": body_tokens,
            "truncated": False,
        }

    def _pick_sections(self, id: str, title: str, body: str,
                       outline: list, names: list) -> dict:
        """C.4.1 rule 4: a list of sections is one call with one budget."""
        if not names:
            raise VineError(E_SCHEMA, "section list must not be empty",
                            hint="Name at least one header, or drop the "
                                 "parameter to read the body.")
        if len(names) > MAX_PICK_SECTIONS:
            raise VineError(
                E_SCHEMA,
                f"pick accepts at most {MAX_PICK_SECTIONS} sections, "
                f"got {len(names)}",
            )
        found, missing = [], []
        for name in names:
            content = extract_section(body, str(name))
            if content is None:
                missing.append(str(name))
                continue
            # C.4.1 (v0.57): the header line that actually matched — the
            # match is by prefix, so the section served is not always the
            # string asked, and a list identified only by order is a list
            # the caller re-derives.
            header = content.splitlines()[0].lstrip("#").strip()
            found.append({"section": str(name), "header": header,
                          "body": content,
                          "body_tokens": estimate_tokens(content)})
        # Whole sections drop from the tail, in request order, and are
        # named — C.11's rule at section grain.
        kept, dropped, used = [], [], 0
        for item in found:
            if not dropped and used + item["body_tokens"] <= PICK_MAX_BODY_TOKENS:
                kept.append(item)
                used += item["body_tokens"]
            else:
                dropped.append(item["section"])
        result = {"id": id, "title": title, "sections": kept,
                  "missing": missing, "dropped": dropped,
                  "truncated": bool(dropped)}
        if missing:
            result["hint"] = f"Available sections: {outline}"
        return result

    def _pick_page(self, id: str, title: str, body: str, body_tokens: int,
                   outline: list, after: str | None) -> dict:
        """C.4.1: the body of one large node is the same problem as one
        large forest — pages, a cursor, totals. Every page is a byte-exact
        substring; pages concatenated in cursor order reproduce the body
        byte-identically (F.80)."""
        blocks = _split_blocks(body)
        total = len(blocks)
        if after in (None, ""):
            start = 0
        else:
            m = re.fullmatch(r"b(\d+)", after)
            if m is None:
                raise VineError(
                    E_SCHEMA,
                    f"unknown cursor {after!r}",
                    hint='Pass the `next` value from the previous page, or '
                         '"" for the first.',
                )
            start = int(m.group(1)) + 1
        result: dict = {"id": id, "title": title, "total": total}
        if start >= total:
            # A cursor past the end states the truth rather than guessing
            # what moved: nothing lies after it.
            result.update({"body": "", "body_tokens": 0, "returned": 0,
                           "truncated": False})
            return result
        end, used = start, 0
        while end < total:
            cost = estimate_tokens(blocks[end])
            if end > start and used + cost > PICK_MAX_BODY_TOKENS:
                break
            used += cost
            end += 1
            if used > PICK_MAX_BODY_TOKENS:
                break
        page = "".join(blocks[start:end])
        cut = False
        if estimate_tokens(page) > PICK_MAX_BODY_TOKENS:
            # C.4.1 rule 3: one block wider than the whole budget arrives
            # alone, hard-cut and flagged — and the cursor still advances,
            # so progress is guaranteed along with the flag.
            page = truncate_text(page, PICK_MAX_BODY_TOKENS)
            cut = True
        result.update({
            "body": page,
            "body_tokens": estimate_tokens(page),
            "returned": end - start,
            "truncated": cut or end < total,
        })
        if cut:
            result["cut"] = True
        if end < total:
            result["next"] = f"b{end - 1}"
        if after is None:
            # The first page a caller did not ask to page: say why it is
            # partial and how to continue (the old dead-end said only
            # `section=`).
            result["outline"] = outline
            result["hint"] = (
                f"Body is {body_tokens} tokens (> {PICK_MAX_BODY_TOKENS}); "
                "this is the first page. Pass after=<next> for the rest, "
                "or section=<header> for one section."
            )
        return result

    def export(self, id: str) -> str:
        """J.14.1 (v0.56): the document as text/markdown for people and
        pipelines. No token budget — none is on this path; budgets protect
        a model's context window and this never enters one.

        `content: inline` returns the passport file VERBATIM (byte-identical
        to what was planted, F.84); `cached`/`reference` return the
        frontmatter plus the resolved body (G.7 — an unreachable body is
        E_NOT_FOUND with the map intact).
        """
        self._row_or_raise(id)
        node = self.forest.read(id)
        assert node.path is not None
        if node.frontmatter.get("content") in ("cached", "reference"):
            body = self._resolved_body(node)
            return serialize_node(dict(node.frontmatter), body)
        return node.path.read_text(encoding="utf-8")

    # =======================================================================
    # C.6d view — the image payload, resolved for a multimodal client
    # =======================================================================

    @_traced
    def view(self, id: str) -> dict:
        """Resolve a media node's image payload (spec C.6d).

        Returns the file's location and identity, never the bytes: the
        transport (an MCP image content block, J.14's model-facing twin)
        reads the file itself. Resolution mirrors J.14 exactly — and the
        refusals are deliberate: a node without a payload answers the SAME
        envelope as a missing node, a remote URI is refused rather than
        fetched inside a read, and anything that is not an image stays with
        the surfaces that already serve it (`query` for datasets, the J.14
        byte route for people).
        """
        self._row_or_raise(id)
        node = self.forest.read(id)
        not_found = VineError(
            E_NOT_FOUND,
            f"node not found: {id}",
            hint="Use locate() to find entry points.",
        )
        payload = node.frontmatter.get("payload")
        if not payload:
            raise not_found
        if is_remote(payload):
            scheme = str(payload).split("://", 1)[0]
            raise VineError(
                E_SCHEMA,
                f"remote payload scheme '{scheme}' is not served",
                hint="view() serves local bytes only; warm the region with "
                     "prefetch first (G.9).",
            )
        root_dir = Path(self.forest.root).resolve()
        assert node.path is not None
        target = (node.path.parent / str(payload)).resolve()
        if not target.is_relative_to(root_dir):
            raise VineError(E_SCHEMA, "payload escapes the forest")
        if not target.is_file():
            # The map said bytes exist and the disk disagrees: same absent
            # payload as no field at all (J.14 / F.49 discipline).
            raise not_found
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if not media_type.startswith("image/"):
            raise VineError(
                E_SCHEMA,
                f"payload is not an image ({media_type})",
                hint="view() serves image payloads; a dataset is read with "
                     "query(), and raw bytes of any kind are the host's "
                     "payload route (J.14).",
            )
        size = target.stat().st_size
        if size > VIEW_MAX_BYTES:
            raise VineError(
                E_SCHEMA,
                f"image payload is {size} bytes, over the "
                f"{VIEW_MAX_BYTES}-byte view limit",
                hint="The host's payload route (J.14) serves bytes of any "
                     "size to people.",
            )
        return {
            "id": id,
            "path": str(target),
            "media_type": media_type,
            "size": size,
            "payload_hash": str(node.frontmatter.get("payload_hash") or ""),
        }

    # =======================================================================
    # C.5 query — read-only SQL over dataset payloads
    # =======================================================================

    @_traced
    def query(self, id: str, sql: str, *, tables: tuple[str, ...] | None = None) -> dict:
        """Read-only SQL over a dataset (C.5).

        `tables` is the host's table allow-list (J.3) and is keyword-only and
        unreachable from the wire — `ScopedVine.query(self, id, sql)` forwards
        the two arguments an agent supplies, and adds this one from the grant.
        A narrowing an agent could pass is a narrowing an agent could omit.
        """
        row = self._row_or_raise(id)
        if row["type"] != "dataset" or row["payload_type"] != "sqlite":
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"node {id} is not a sqlite dataset (type={row['type']})",
                hint="query() only works on type:dataset nodes with payload_type:sqlite.",
            )
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise VineError(E_QUERY_FORBIDDEN, "only a single SQL statement is allowed")
        first = sql.split(None, 1)[0].upper() if sql else ""
        if first not in ("SELECT", "WITH"):
            raise VineError(E_QUERY_FORBIDDEN, "statement must start with SELECT or WITH")
        m = _FORBIDDEN_SQL.search(sql)
        if m:
            raise VineError(E_QUERY_FORBIDDEN, f"forbidden keyword: {m.group(0).upper()}")

        limited_injected = False
        if not _LIMIT_RE.search(sql):
            sql = f"{sql} LIMIT {QUERY_DEFAULT_LIMIT}"
            limited_injected = True

        node = self.forest.read(id)
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        allowed = (frozenset(t.lower() for t in tables)
                   if tables is not None else None)
        t0 = time.perf_counter()
        try:
            if allowed is not None:
                conn.set_authorizer(_table_authorizer(allowed))
            try:
                cur = conn.execute(sql)
                rows = cur.fetchall()
                columns = [d[0] for d in cur.description] if cur.description else []
            finally:
                # Only the caller's statement is judged. What follows — the
                # name hint below — is the engine reading its own schema, and
                # it filters itself.
                conn.set_authorizer(None)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise VineError(E_TIMEOUT, f"query exceeded {QUERY_TIMEOUT_S}s") from e
            # C.5 (v0.46): a name that is not there is the most common way
            # for generated SQL to fail, and "no such table: x" alone sends
            # the caller off to spend a `look` finding out what IS there.
            # The answer costs one read of sqlite_master on a path that has
            # already failed, so it is free where it matters.
            raise VineError(E_QUERY_INVALID, f"SQL error: {e}",
                            hint=self._name_hint(conn, str(e), allowed)) from e
        except sqlite3.DatabaseError as e:
            if allowed is None or not _not_authorized(e):
                raise VineError(E_QUERY_INVALID, f"SQL error: {e}") from e
            # C.5.2: the allow-list is policy, so this is the guard's 403 and
            # not SQLite's 400 — even though SQLite is what noticed. The
            # message never repeats the name it stopped at: that would answer
            # "does this table exist?" for every table the caller may not read.
            raise VineError(
                E_QUERY_FORBIDDEN,
                "this statement reads a table outside this principal's allow-list",
                hint=f"Readable here: {sorted(allowed)}.") from e
        finally:
            conn.close()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        payload = {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "limited": limited_injected and len(rows) == QUERY_DEFAULT_LIMIT,
            "elapsed_ms": round(elapsed_ms, 2),
        }
        return _fit_query_budget(payload)

    # =======================================================================
    # C.6 scan — metadata queries via the Catalog (<= 800 tokens)
    # =======================================================================

    @_traced
    def scan(
        self,
        parent_id: str,
        filter: dict | None = None,
        fields: list[str] | None = None,
        recursive: bool = False,
        limit: int = 50,
        after: str | None = None,
        gauntlet: bool | None = None,
        toward: str | None = None,
        since: str | None = None,
        until: str | None = None,
        date_field: str | None = None,
        *,
        visible=None,
    ) -> dict:
        # `visible` is the host policy's predicate (J.3), applied where the
        # candidates are chosen so `total`, the cursor and the page are all
        # the principal's own — a count over nodes they may not see is a
        # size oracle, and a cursor over them skips what a post-hoc trim
        # drops. Keyword-only and absent from the signature table: it is
        # the host's to pass, unreachable from the wire (same construction
        # as G.2.5's `adopted`).
        self._row_or_raise(parent_id)
        window = normalize_window(since, until, date_field)
        filter = filter or {}
        # C.6 (v0.54): the cost of opening a node is known wherever a node
        # is offered — body_tokens joins the default projection.
        fields = fields or ["id", "type", "summary", "body_tokens"]
        unknown = [f for f in fields if f not in SCAN_FIELDS]
        if unknown:
            # C.12 rule 7: silently omitted from every item, an unknown
            # field reads exactly like "empty on every node".
            raise VineError(
                E_SCHEMA,
                f"fields accepts {sorted(SCAN_FIELDS)}; got {unknown[0]!r}",
            )
        if after is not None and (toward or gauntlet):
            raise VineError(
                E_SCHEMA,
                "after cannot be combined with gauntlet/toward",
                hint="An enumeration has one order (id); a ranked page "
                     "cannot be resumed. Drop the cursor to rank.",
            )
        limit = min(max(1, limit), 50)

        rows = self.catalog.children(parent_id, recursive=recursive)
        out = []
        for r in rows:
            if visible is not None and not visible(r["id"]):
                continue
            if not self._match_filter(r, filter):
                continue
            if window and not in_window(r[window["date_field"]], window):
                continue
            item = {"id": r["id"]}
            for f in fields:
                if f == "id":
                    continue
                if f in ("tags", "aliases", "trail", "outline"):
                    item[f] = json.loads(r[f])
                elif f == "kind":
                    # C.6 (v0.56): the wire's spelling, never the catalog's.
                    item[f] = _wire_kind(r["kind"])
                elif f == "heat":
                    item[f] = self._heat(r["id"])
                elif f == "coverage":
                    cov = indexer.parse_coverage(r["coverage"])
                    if cov or r["coverage"]:
                        item[f] = cov or r["coverage"]
                elif f in r.keys():
                    item[f] = r[f]
            if _is_system(r["id"]):
                # C.6 (v0.54): `_meta/schema` is a child of no branch, so
                # it shows up here and in no `look` — the marker is the
                # explanation for the differing counts.
                item["system"] = True
            item["_heat"] = self._heat(r["id"])
            out.append(item)
        # C.6.2 (v0.54): `total` is what the requested scope holds, counted
        # before any cut — the size of what was NOT received.
        total = len(out)
        goal = None
        if after is not None:
            # The cursor selects id order: stable, resumable, and complete
            # over a stable forest. `after: ""` starts at the beginning.
            out.sort(key=lambda x: x["id"])
            out = [x for x in out if x["id"] > after]
        else:
            out.sort(key=lambda x: x["_heat"], reverse=True)
            # Part K: 60 children cut to 14 by the budget, ordered by heat,
            # is the forager seeing a quarter of the frontier chosen by
            # something that has nothing to do with the question. Rank
            # first, then cut.
            goal = self._goal_for(toward, gauntlet)
            if goal is not None:
                self._rank_frontier(out, goal[0],
                                    signal_of=lambda x: x["_heat"])
        for item in out:
            item.pop("_heat", None)
        payload = {"nodes": out[:limit], "truncated": len(out) > limit}
        if goal is not None:
            payload["frontier"] = {"ranked": True, "toward": goal[1]}
        if window:
            payload["window"] = window
        # C.6.2: the meta fields sit inside the budget, so they are present
        # (at their largest possible size) while the list is cut, and only
        # their values are fixed up afterwards — the 800 stays a ceiling.
        payload["total"] = total
        payload["returned"] = len(payload["nodes"])
        if after is not None and out:
            payload["next"] = max((x["id"] for x in out), key=len)
        payload = shrink_list_to_budget(payload, "nodes", BUDGET_SCAN)
        payload["returned"] = len(payload["nodes"])
        if (after is not None and payload["nodes"]
                and payload["returned"] < len(out)):
            # The last id returned is exactly what the next call's `after`
            # takes; the final page carries no `next`.
            payload["next"] = payload["nodes"][-1]["id"]
        else:
            payload.pop("next", None)
        return payload

    @staticmethod
    def _match_filter(row: sqlite3.Row, flt: dict) -> bool:
        for key, want in flt.items():
            if key == "tags_any":
                tags = set(json.loads(row["tags"]))
                if not tags & set(want):
                    return False
            elif key == "updated_after":
                if not row["updated"] or row["updated"] < str(want):
                    return False
            elif key == "updated_before":
                if not row["updated"] or row["updated"] > str(want):
                    return False
            elif key == "created_after":
                if not row["created"] or row["created"] < str(want):
                    return False
            elif key == "min_confidence":
                if row["confidence"] < float(want):
                    return False
            elif key == "kind":
                # C.6 (v0.56): the filter MUST match what the field emits —
                # a filter that only matched the storage spelling would make
                # {"kind": "note"} silently empty.
                if _wire_kind(row["kind"]) != want:
                    return False
            elif key in row.keys():
                if row[key] != want:
                    return False
            else:
                raise VineError(E_SCHEMA, f"unknown scan filter: {key}")
        return True

    # =======================================================================
    # C.6b sniff — the tracker (literal search over bodies)
    # =======================================================================

    @_traced
    def sniff(
        self,
        terms: str | list[str],
        scope: str | None = None,
        k: int = 5,
        type_filter: str | None = None,
        since: str | None = None,
        until: str | None = None,
        date_field: str | None = None,
    ) -> dict:
        if isinstance(terms, str):
            terms = [terms]
        if not isinstance(terms, list) or not terms or len(terms) > SNIFF_MAX_TERMS:
            raise VineError(
                E_SCHEMA,
                f"terms must be 1..{SNIFF_MAX_TERMS} literal strings",
                hint="Pass exact terms (codes, names, numbers); regex is not supported.",
            )
        folded_terms = []
        for t in terms:
            ft = _fold(str(t)).strip()
            if len(ft) < 2:
                raise VineError(
                    E_SCHEMA,
                    f"term too short after normalization: {t!r}",
                    hint="Literal terms need >= 2 characters; regex is not supported.",
                )
            folded_terms.append(ft)

        # scope: branch -> physical subtree; banana -> that single node
        # (grep-within-the-node, the natural follow-up to locate/look).
        if scope is not None and not isinstance(scope, str):
            raise VineError(
                E_SCHEMA,
                "scope must be a single node or branch id (string)",
                hint="Pass scope as one string: a branch id or a node id, not a list.",
            )
        k = min(max(1, k), SNIFF_MAX_K)
        # The scope is a WHERE, never a Python skip. Fetching every row to
        # discard all but one made a single-node sniff cost the whole
        # forest — and the sweep (C.6c) issues one per term per result.
        where, params = self._scope_where(scope)
        if type_filter:
            where.append("{n}type = ?")
            params.append(type_filter)
        # C.13.1: the cheapest filter in the system, and the one that pays
        # most here — a windowed sniff opens the files of those days and no
        # others, instead of every body in the forest.
        window = normalize_window(since, until, date_field)
        win_where, win_params = window_sql(window)
        where.extend(win_where)
        params.extend(win_params)
        clauses = [c.format(n="") for c in where]
        rows = self.catalog.conn.execute(
            "SELECT * FROM nodes"
            + (" WHERE " + " AND ".join(clauses) if clauses else "")
            + " ORDER BY id", params).fetchall()
        # C.6b.1: what the scan already knows, per term, still valid by hash.
        memo = [self.catalog.sniff_memo(t, where, params) for t in folded_terms]
        learned: list[tuple[str, str, str, str]] = []
        scanned = 0
        hits = []
        for r in rows:
            nid = r["id"]
            body_hash = r["body_hash"]
            remembered = [m.get(nid) for m in memo]
            if body_hash and all(lines is not None for lines in remembered):
                # Not one file opened for this node: the terms were all
                # scanned against this exact body before.
                scanned += 1
                matches, terms_hit = _combine_lines(
                    [json.loads(lines) for lines in remembered])
            else:
                try:
                    text = self.forest.path_for(nid).read_text(encoding="utf-8")
                except (VineError, OSError):
                    continue  # validate() reports broken nodes; sniff skips them
                body = _raw_body(text)
                if _CONTENT_MARKER_RE.search(text):
                    # G.7: non-inline node — grep the resolved FLESH instead
                    # of the stub; an unreachable body degrades to "no match".
                    # Its hash is empty by construction, so it is never
                    # memoized: the `.md` this hash covers is not this text.
                    try:
                        body = self._resolved_body(self.forest.read(nid))
                    except VineError:
                        continue
                scanned += 1
                if body_hash:
                    per_term = _scan_lines(body, folded_terms)
                    learned.extend(
                        (t, nid, body_hash, json.dumps(per_term[i]))
                        for i, t in enumerate(folded_terms)
                        if remembered[i] is None)
                    matches, terms_hit = _combine_lines(per_term)
                else:
                    matches, terms_hit = _sniff_body(body, folded_terms)
            if not matches:
                continue
            strength = len(terms_hit) / len(folded_terms)
            heat = self._heat(nid)
            # C.6b (v0.52): occurrences are part of the score. `strength` is
            # frequently constant across literal hits, which left `heat` —
            # the traversal that came before — as the only thing separating
            # a note holding ten occurrences from an index holding one.
            density = 1 + SNIFF_DENSITY_BETA * math.log2(len(matches))
            hit = {
                "id": nid,
                "type": r["type"],
                "title": r["title"],
                "trail": json.loads(r["trail"]),
                "score": round(strength * density * (1 + self.alpha * heat), 4),
                "heat": heat,
                # C.6b (v0.54): the row is already in hand, and the caller
                # is choosing what to open (C.1.1's rule).
                "body_tokens": r["body_tokens"],
                "match_count": len(matches),
                "truncated_matches": len(matches) > SNIFF_MATCHES_PER_NODE,
                "matches": matches[:SNIFF_MATCHES_PER_NODE],
            }
            if _is_index(nid):
                # C.6b (v0.54): the sort below is deliberate and invisible
                # on the wire — a client re-sorting by score would silently
                # undo it. The marker says so; the score keeps telling the
                # truth.
                hit["demoted"] = True
            hits.append(hit)
        # After the answer is decided, never before it: what the scan learned
        # is latency for the next caller, and it must not be able to change
        # this one's result.
        self.catalog.sniff_memo_store(learned)
        # C.6b (v0.52): a pointer never outranks what it points at. An index
        # carries the summary of every child, so it matches nearly any term
        # and gathers heat by being the way through; a term found inside it
        # is evidence about a child. Demoted in the ORDER, never in the
        # `score` — a number adjusted to force a position is a number that
        # lies, and the order is what this contract publishes.
        hits.sort(key=lambda h: (not _is_index(h["id"]), h["score"],
                                 h["match_count"]), reverse=True)
        payload = {
            "results": hits[:k],
            "scanned_nodes": scanned,
            "truncated": len(hits) > k,
        }
        payload = shrink_list_to_budget(payload, "results", BUDGET_SNIFF)
        if window:
            payload["window"] = window
            undated = self.undated_count(window["date_field"])
            if undated:
                payload["undated_excluded"] = undated
            if not payload["results"]:
                payload.update(self.empty_context(window, "No body matched"))
        return payload

    # =======================================================================
    # C.13 calendar — where the material sits in time (<= 800 tokens)
    # =======================================================================

    @_traced
    def calendar(self, scope: str | None = None, date_field: str | None = None,
                 granularity: str = "month", since: str | None = None,
                 until: str | None = None, limit: int = 24, *,
                 policy_where: tuple[list[str], list] | None = None) -> dict:
        """The map that makes a window a choice instead of a guess (C.13.3).

        Answered from the catalog alone: which periods hold anything, how
        much, and the two dates of each — which are exactly the strings the
        windowed reads take, so there is no arithmetic between finding a
        period and searching it.
        """
        field = parse_field(date_field)
        window = normalize_window(since, until, field)
        where, params = self._scope_where(scope)
        win_where, win_params = window_sql(window)
        # J.3: under a policy every count covers only nodes in scope — a
        # global count here would be a finer size oracle than `locate` could
        # ever be, describing the shape of a region nobody granted, period by
        # period. The predicate is the policy's own prefixes as SQL, so the
        # filtering happens inside the GROUP BY rather than after it; it is
        # keyword-only and supplied by the host, unreachable from the wire
        # (G.2.5's construction).
        pol_where, pol_params = policy_where or ([], [])
        rows = self.catalog.date_buckets(
            field, granularity,
            where + win_where + pol_where,
            params + win_params + pol_params)
        payload = buckets_from_rows(rows, granularity, limit)
        undated_where = [f"({{n}}{field} IS NULL OR {{n}}{field} = '')"]
        payload = {"date_field": field, "granularity": granularity, **payload,
                   "undated": self.catalog.count_nodes(
                       where + undated_where + pol_where, params + pol_params)}
        if scope:
            payload["scope"] = scope
        if window:
            payload["window"] = window
        return shrink_list_to_budget(payload, "buckets", BUDGET_CALENDAR)

    # =======================================================================
    # C.10 tend — dataset writes (spec v0.7, Phase 2: the living bank)
    # =======================================================================

    @_traced
    def tend(self, id: str, sql: str, *, tables: tuple[str, ...] | None = None) -> dict:
        """The one dataset write path (C.10).

        `tables` is the host's allow-list, on the same terms as `query`:
        keyword-only, supplied by `ScopedVine` from the grant, never by the
        caller. It governs what the statement reads as well as what it
        writes, because a scope that holds for only one of those can be
        worked around through the other.
        """
        self._require_writable()
        with self._write_mutex:
            return self._tend(id, sql, tables=tables)

    def _tend(self, id: str, sql: str, *,
              tables: tuple[str, ...] | None = None) -> dict:
        row = self._row_or_raise(id)
        if row["type"] != "dataset" or row["payload_type"] != "sqlite":
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"node {id} is not a sqlite dataset (type={row['type']})",
                hint="tend() only works on type:dataset nodes with payload_type:sqlite.",
            )
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise VineError(E_QUERY_FORBIDDEN, "only a single SQL statement is allowed")
        first = sql.split(None, 1)[0].upper() if sql else ""
        if first not in ("INSERT", "UPDATE", "DELETE"):
            raise VineError(
                E_QUERY_FORBIDDEN,
                "tend accepts INSERT, UPDATE or DELETE only",
                hint="Reads go through query(); schema changes are the Gardener's job.",
            )
        m = _TEND_FORBIDDEN.search(sql)
        if m:
            raise VineError(E_QUERY_FORBIDDEN, f"forbidden keyword: {m.group(0).upper()}")
        if first in ("UPDATE", "DELETE") and not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"{first} without WHERE is not allowed (mass-wipe guard)",
                hint="Target rows explicitly; full rewrites are the Gardener's job.",
            )

        node = self.forest.read(id)
        db = self._dataset_db(node, for_write=True)
        conn = sqlite3.connect(db)
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        allowed = (frozenset(t.lower() for t in tables)
                   if tables is not None else None)
        t0 = time.perf_counter()
        try:
            if allowed is not None:
                conn.set_authorizer(_table_authorizer(allowed))
            try:
                cur = conn.execute(sql)
                conn.commit()
                rows_affected = cur.rowcount
            finally:
                conn.set_authorizer(None)
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "interrupted" in str(e).lower():
                raise VineError(E_TIMEOUT, f"tend exceeded {QUERY_TIMEOUT_S}s") from e
            # C.5.2 (v0.47): the guard above said what is forbidden; from
            # here on it is SQLite saying what is invalid, on a dataset this
            # principal is allowed to write.
            raise VineError(E_QUERY_INVALID, f"SQL error: {e}",
                            hint=self._name_hint(conn, str(e), allowed)) from e
        except sqlite3.Error as e:
            conn.rollback()
            if allowed is None or not _not_authorized(e):
                raise VineError(E_QUERY_INVALID, f"SQL error: {e}") from e
            raise VineError(
                E_QUERY_FORBIDDEN,
                "this statement touches a table outside this principal's allow-list",
                hint=f"Writable here: {sorted(allowed)}.") from e
        finally:
            conn.close()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # audit trail (spec C.10): the .md records what/when via payload_hash;
        # the binary itself never enters git (A.3.1)
        new_hash = hashlib.sha256(db.read_bytes()).hexdigest()
        fm = dict(node.frontmatter)
        fm["payload_hash"] = new_hash
        fm["updated"] = dt.date.today().isoformat()
        content = serialize_node(fm, node.body)
        assert node.path is not None
        original = node.path.read_text(encoding="utf-8")
        try:
            node.path.write_text(content, encoding="utf-8", newline="\n")
            commit = self.git.commit(
                [node.path], f"tend({id}): {first} {rows_affected} row(s)"
            )
        except Exception:
            # payload already committed: restore the .md and surface the error;
            # the hash drift is exactly what `vine validate` warns about
            node.path.write_text(original, encoding="utf-8", newline="\n")
            raise
        self.catalog.upsert_node(self.forest.read(id))
        return {
            "id": id,
            "rows_affected": rows_affected,
            "payload_hash": new_hash,
            "commit": commit,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    # =======================================================================
    # C.7 plant — atomic create (file + index + git)
    # =======================================================================

    @_traced
    def plant(self, node: dict | NodeSpec, *, if_absent: bool = False,
              dry_run: bool = False, adopted: bool = False) -> dict:
        """`adopted` (G.2.5, v0.45) says the schema was READ off a source the
        operator already owns, not declared by a model: the C.7.1 count
        limits are guards against hallucinated DDL and do not apply to it.
        Names and types are validated exactly as always.

        Keyword-only, and deliberately unreachable from the wire — the host
        dispatches `getattr(scoped, "plant")(**payload)` and
        `ScopedVine.plant` forwards `node` and `if_absent` and nothing else,
        so an extra key in a request body is a TypeError, never a relaxed
        guard.

        `if_absent` (C.7.2, v0.52) IS caller-facing, and is keyword-only for
        a different reason: a second positional argument here used to be a
        TypeError, and that is the property the G.2.5 suite checks. Keeping
        it keyword-only keeps `plant(node, True)` refused, which is what
        stops a positional call from ever landing on `adopted`.

        `dry_run` (C.7.3, v0.57) rehearses the write: every validation the
        real plant runs, in the real order, on the same code path — then
        returns before the first byte is written. Nothing is created,
        committed or indexed; the failure is the exact envelope the real
        call would raise.

        `node` MAY be a list (C.7.4, v0.58): everything validated before
        anything is written — in order, so a branch and its children may
        share one batch — and the whole batch lands in ONE commit or none
        of it lands.
        """
        self._require_writable()
        if isinstance(node, (list, tuple)):
            with self._write_mutex:
                return self._plant_batch(list(node), if_absent=bool(if_absent),
                                         dry_run=bool(dry_run))
        spec = node if isinstance(node, NodeSpec) else NodeSpec.model_validate(node)
        with self._write_mutex:
            return self._plant(spec, adopted=adopted, if_absent=bool(if_absent),
                               dry_run=bool(dry_run))

    def _prepare_dataset_spec(self, spec: NodeSpec, *, adopted: bool = False) -> None:
        """C.7.1: the schema is data, never DDL — validate it whole and
        default the payload fields before the frontmatter is built."""
        if spec.type != "dataset":
            raise VineError(
                E_SCHEMA,
                f"schema is only valid on type:dataset nodes (got type={spec.type})",
            )
        assert spec.table_schema is not None
        validate_dataset_schema(spec.table_schema, limits=not adopted)
        if spec.rows:
            validate_dataset_rows(spec.table_schema, spec.rows)
        if spec.payload is None:
            spec.payload = spec.id.rsplit("/", 1)[-1] + ".db"
        if "/" in spec.payload or "\\" in spec.payload or not spec.payload.endswith(".db"):
            raise VineError(
                E_SCHEMA,
                f"payload must be a bare filename ending in .db: {spec.payload}",
            )
        spec.payload_type = spec.payload_type or "sqlite"
        if spec.payload_type != "sqlite":
            raise VineError(E_SCHEMA, "schema requires payload_type: sqlite")

    def _plant(self, spec: NodeSpec, *, adopted: bool = False,
               if_absent: bool = False, dry_run: bool = False,
               pending: dict[str, str] | None = None) -> dict:
        # `pending` (C.7.4): the batch's own earlier nodes, so a branch and
        # its children rehearse in one list. Keyword-only, engine-internal.
        if spec.rows and spec.table_schema is None:
            raise VineError(E_SCHEMA, "rows require a schema (C.7.1 rule 7)")
        if spec.table_schema is not None:
            self._prepare_dataset_spec(spec, adopted=adopted)
        fm = spec.frontmatter_dict()
        validate_frontmatter(fm, self.forest.dialect)
        if self.forest.exists(spec.id) or (pending and spec.id in pending):
            if if_absent:
                # C.7.2 (v0.52): "make sure this exists". Nothing is written,
                # nothing is committed, and the submitted content is not
                # compared to what is there — changing it is graft's job.
                out = {"id": spec.id, "created": False,
                       "trail": self.forest.trail(spec.id)}
                if dry_run:
                    out["dry_run"] = True
                return out
            raise VineError(E_SCHEMA, f"id already exists: {spec.id}", hint="ids are immutable and unique.")
        parent_row = self.catalog.get(spec.parent)
        parent_pending = bool(pending
                              and pending.get(spec.parent) == "branch")
        if not parent_pending and (parent_row is None
                                   or parent_row["kind"] != "branch"):
            raise VineError(E_NOT_FOUND, f"parent branch not found: {spec.parent}")
        expected_parent = self.forest.parent_index_id(spec.id)
        if spec.parent != expected_parent:
            raise VineError(
                E_SCHEMA,
                f"id '{spec.id}' does not live under parent '{spec.parent}' "
                f"(expected parent: {expected_parent})",
            )
        if dry_run and spec.table_schema is not None:
            # The one refusal left between here and the first write: rehearse
            # it read-only, in the real path's own order.
            assert spec.payload is not None
            if (self.forest.path_for(spec.id).parent / spec.payload).exists():
                raise VineError(
                    E_SCHEMA,
                    f"payload already exists: {spec.payload}",
                    hint="A newborn dataset never overwrites an existing payload.",
                )
        if dry_run:
            # C.7.3 (v0.57): every validation ran; nothing was written, so
            # `created` is absent — nothing was.
            return {"id": spec.id, "valid": True, "dry_run": True}

        # C.7.1 payload birth: create the SQLite BEFORE the .md so the hash
        # lands in the frontmatter; the binary itself never enters git (A.3.1)
        payload_db: Path | None = None
        if spec.table_schema is not None:
            assert spec.payload is not None
            payload_db = self.forest.path_for(spec.id).parent / spec.payload
            if payload_db.exists():
                raise VineError(
                    E_SCHEMA,
                    f"payload already exists: {spec.payload}",
                    hint="A newborn dataset never overwrites an existing payload.",
                )
            try:
                payload_db.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(payload_db)
                try:
                    for stmt in dataset_ddl(spec.table_schema):
                        conn.execute(stmt)
                    # C.7.1 rule 7: initial rows go in parameterized — values
                    # are data, never SQL text
                    for tname, table_rows in (spec.rows or {}).items():
                        if table_rows:
                            ph = ", ".join("?" * len(spec.table_schema[tname].columns))
                            conn.executemany(
                                f"INSERT INTO {tname} VALUES ({ph})",
                                [tuple(r) for r in table_rows],
                            )
                    conn.commit()
                finally:
                    conn.close()
                fm["payload_hash"] = hashlib.sha256(payload_db.read_bytes()).hexdigest()
            except sqlite3.Error as e:
                payload_db.unlink(missing_ok=True)
                raise VineError(E_SCHEMA, f"dataset birth failed: {e}") from e
            except Exception:
                payload_db.unlink(missing_ok=True)
                raise

        body = spec.body.strip() or f"# {spec.title}"
        if not body.lstrip().startswith("#"):
            body = f"# {spec.title}\n\n{body}"
        if spec.table_schema is not None and extract_section(body, "Query manual") is None:
            # C.7.1 rule 4 (v0.44): the manual is followed by G.2.3's sample
            # map when the node is born with rows — the body is the only
            # place a value inside the payload is visible to `sniff`.
            body = f"{body.rstrip()}\n\n{dataset_manual(spec.table_schema, spec.rows)}"
        content = serialize_node(fm, body)

        parent_node = self.forest.read(spec.parent)
        new_parent_body = indexer.add_entry(
            parent_node, spec.id, spec.summary, is_branch=(spec.type == "branch")
        )
        new_parent_content = indexer.render_index(parent_node, new_parent_body)

        written: list[tuple[Path, str | None]] = []
        try:
            node_path = self.forest.path_for(spec.id)
            written.append((node_path, None))
            self.forest.write(spec.id, content)
            assert parent_node.path is not None
            written.append((parent_node.path, parent_node.path.read_text(encoding="utf-8")))
            parent_node.path.write_text(new_parent_content, encoding="utf-8", newline="\n")
            commit = self.git.commit(
                [node_path, parent_node.path],
                f"plant({spec.id}): {spec.title} [source={spec.source}]",
            )
        except Exception:
            for path, original in reversed(written):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(original, encoding="utf-8", newline="\n")
            if payload_db is not None:
                payload_db.unlink(missing_ok=True)
            raise

        self.catalog.upsert_node(self.forest.read(spec.id))
        self.catalog.upsert_node(self.forest.read(spec.parent))
        self.catalog.mark_stale(spec.id)
        return {"id": spec.id, "created": True, "commit": commit,
                "trail": self.forest.trail(spec.id)}

    def _plant_batch(self, nodes: list, *, if_absent: bool,
                     dry_run: bool) -> dict:
        """C.7.4: a batch is one plant — everything validated before
        anything is written, the whole batch in ONE commit or none of it.
        """
        if not nodes:
            raise VineError(E_SCHEMA, "plant batch must not be empty",
                            hint="Pass one node, or a list of up to "
                                 f"{MAX_BATCH_PLANT}.")
        if len(nodes) > MAX_BATCH_PLANT:
            raise VineError(
                E_SCHEMA,
                f"plant accepts at most {MAX_BATCH_PLANT} nodes per batch, "
                f"got {len(nodes)}")
        specs: list[NodeSpec] = []
        for entry in nodes:
            spec = (entry if isinstance(entry, NodeSpec)
                    else NodeSpec.model_validate(entry))
            if spec.table_schema is not None or spec.rows:
                # C.7.4 rule 6: a payload birth mid-batch has no rollback
                # story yet; refusing is honest where restoring is not.
                raise VineError(
                    E_SCHEMA,
                    f"'{spec.id}': datasets are planted one at a time",
                    hint="A batch is .md-only; plant the dataset in its "
                         "own call (C.7.1).")
            specs.append(spec)
        seen: set[str] = set()
        for spec in specs:
            if spec.id in seen:
                raise VineError(
                    E_SCHEMA, f"duplicate id in batch: {spec.id}",
                    hint="Two nodes cannot claim one address, even "
                         "transiently.")
            seen.add(spec.id)

        # Rehearsal pass: C.7.3's own code path, per node, in order —
        # earlier batch nodes count as existing for later ones.
        pending: dict[str, str] = {}
        existing: list[str] = []
        would_create: list[NodeSpec] = []
        for spec in specs:
            try:
                verdict = self._plant(spec, if_absent=if_absent,
                                      dry_run=True, pending=pending)
            except VineError as e:
                raise VineError(e.code, f"{spec.id}: {e.message}",
                                hint=e.hint, data=e.data) from e
            if verdict.get("created") is False:
                existing.append(spec.id)
                continue
            pending[spec.id] = ("branch" if spec.type == "branch"
                                else "leaf")
            would_create.append(spec)
        if dry_run:
            out = {"valid": True, "count": len(would_create),
                   "dry_run": True}
            if existing:
                out["existing"] = existing
            return out
        if not would_create:
            # C.7.2's answer at batch grain: everything already existed,
            # nothing written, nothing committed.
            return {"created": [], "count": 0, "existing": existing}

        # Write pass: every file and every parent-index refresh, then ONE
        # commit. Any failure restores everything — all-or-nothing is the
        # whole point (C.7.4 rule 1).
        written: list[tuple[Path, str | None]] = []
        paths: list[Path] = []
        created: list[str] = []
        try:
            for spec in would_create:
                fm = spec.frontmatter_dict()
                body = spec.body.strip() or f"# {spec.title}"
                if not body.lstrip().startswith("#"):
                    body = f"# {spec.title}\n\n{body}"
                node_path = self.forest.path_for(spec.id)
                written.append((node_path, None))
                self.forest.write(spec.id, serialize_node(fm, body))
                paths.append(node_path)
                parent_node = self.forest.read(spec.parent)
                assert parent_node.path is not None
                new_body = indexer.add_entry(
                    parent_node, spec.id, spec.summary,
                    is_branch=(spec.type == "branch"))
                if parent_node.path not in paths:
                    written.append((parent_node.path,
                                    parent_node.path.read_text(
                                        encoding="utf-8")))
                    paths.append(parent_node.path)
                parent_node.path.write_text(
                    indexer.render_index(parent_node, new_body),
                    encoding="utf-8", newline="\n")
                created.append(spec.id)
            commit = self.git.commit(
                paths, f"plant(batch): {len(created)} nodes")
        except Exception:
            for path, original in reversed(written):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(original, encoding="utf-8", newline="\n")
            raise

        for spec in would_create:
            self.catalog.upsert_node(self.forest.read(spec.id))
            self.catalog.mark_stale(spec.id)
        for parent in dict.fromkeys(s.parent for s in would_create):
            if self.forest.exists(parent):
                self.catalog.upsert_node(self.forest.read(parent))
        out = {"created": created, "commit": commit, "count": len(created)}
        if existing:
            out["existing"] = existing
        return out

    # =======================================================================
    # C.8 graft — atomic edit with reinforce-before-create
    # =======================================================================

    @_traced
    def graft(self, id: str, patch: dict | GraftPatch) -> dict:
        self._require_writable()
        if isinstance(patch, GraftPatch):
            p = patch
        else:
            # C.8 (v0.56): an unknown patch key is refused before anything
            # is written — beside a legal operation it used to be silently
            # dropped, and the call answered 200 while doing less than it
            # was asked. Checked here for the message; the model's
            # extra="forbid" is the backstop for every other constructor.
            unknown = [k for k in patch
                       if k not in GraftPatch.model_fields] \
                if isinstance(patch, dict) else []
            if unknown:
                raise VineError(
                    E_SCHEMA,
                    f"unknown patch key {unknown[0]!r}",
                    hint="A patch accepts: "
                         f"{sorted(GraftPatch.model_fields)}.",
                )
            p = GraftPatch.model_validate(patch)
        with self._write_mutex:
            return self._graft(id, p)

    def _graft(self, id: str, patch: GraftPatch) -> dict:
        node = self.forest.read(id)
        if patch.is_empty():
            raise VineError(E_SCHEMA, "empty graft patch")

        # C.8 v0.43: one patch states one truth about the body — a whole-body
        # replace alongside section surgery is refused, never resolved by
        # precedence. And an index's body is the indexer's render: a
        # hand-written one would stop parsing as a map.
        if patch.replace_body is not None:
            if patch.replace_section or patch.append_section:
                raise VineError(
                    E_SCHEMA,
                    "replace_body cannot be combined with section operations",
                    hint="Send the whole body, or section patches — not both.",
                )
            if id == "_index" or id.endswith("/_index"):
                raise VineError(
                    E_SCHEMA,
                    f"'{id}' is an index: its body is the indexer's render",
                    hint="Indexes accept section operations only.",
                )

        for field in patch.set_frontmatter:
            if field not in MUTABLE_FRONTMATTER_FIELDS:
                raise VineError(
                    E_READONLY,
                    f"frontmatter field '{field}' is immutable",
                    hint=f"Mutable fields: {sorted(MUTABLE_FRONTMATTER_FIELDS)}",
                )
        if "summary" in patch.set_frontmatter:
            validate_summary(str(patch.set_frontmatter["summary"]))
        if "aliases" in patch.set_frontmatter:
            aliases = patch.set_frontmatter["aliases"]
            if (not isinstance(aliases, list) or len(aliases) > MAX_ALIASES
                    or any(not isinstance(a, str) or not a.strip()
                           or len(a) > ALIAS_MAX_CHARS for a in aliases)):
                raise VineError(
                    E_SCHEMA,
                    f"aliases must be a list of at most {MAX_ALIASES} "
                    f"non-empty strings of at most {ALIAS_MAX_CHARS} chars",
                    hint="Aliases are curated names locate indexes beside "
                         "the title (C.8, G.2.6).",
                )
        if "origin" in patch.set_frontmatter:
            # A.3 (v0.57): one bounded URI, never prose; `None` clears it.
            if patch.set_frontmatter["origin"] is not None:
                validate_origin(patch.set_frontmatter["origin"])

        fm = dict(node.frontmatter)
        body = node.body
        file_changed = False
        fortified: list[dict] = []

        if patch.set_frontmatter:
            fm.update(patch.set_frontmatter)
            if fm.get("origin") is None:
                # `origin: null` is a clearing, not a value (A.3, v0.57).
                fm.pop("origin", None)
            file_changed = True

        links = [Link.model_validate(l) for l in (fm.get("links") or [])]
        existing = {l.key() for l in links}

        for link in patch.add_links:
            if link.rel not in self.forest.dialect.rels:
                raise VineError(E_SCHEMA, f"unknown rel '{link.rel}'")
            if link.key() in existing:
                # Reinforce-before-create: duplicate link -> fortification
                # (heat goes up; no new edge, no commit for this op).
                self.trails.add_heat([id, link.target], amount=0.1)
                fortified.append({"rel": link.rel, "target": link.target})
                continue
            extra = link.model_dump()
            if link.rel == "discovered-shortcut":
                extra.setdefault("confidence", 0.5)
                extra.setdefault("discovered_by", "agent")
            links.append(Link.model_validate(extra))
            existing.add(link.key())
            file_changed = True

        if patch.remove_links:
            removals = {l.key() for l in patch.remove_links}
            kept = [l for l in links if l.key() not in removals]
            if len(kept) != len(links):
                links = kept
                file_changed = True

        if len(links) > MAX_LINKS_PER_NODE:
            raise VineError(E_SCHEMA, f"node would have {len(links)} links (max {MAX_LINKS_PER_NODE})")
        fm["links"] = [l.model_dump(exclude_none=True) for l in links]
        if not fm["links"]:
            fm.pop("links")

        if patch.replace_body is not None:
            body = patch.replace_body
            file_changed = True
        if patch.replace_section:
            new_body = replace_section(body, patch.replace_section.header, patch.replace_section.body)
            if new_body is None:
                raise VineError(
                    E_NOT_FOUND,
                    f"section '{patch.replace_section.header}' not found in {id}",
                    hint="Use append_section to add a new section.",
                )
            body = new_body
            file_changed = True
        if patch.append_section:
            body = append_section(body, patch.append_section.header, patch.append_section.body)
            file_changed = True

        # C.8 (v0.54): a body edit that leaves the summary behind ages the
        # exact layer navigation trusts. Compared text-to-text, so a
        # replace_body that wrote the same words signals nothing.
        summary_stale = (body != node.body
                         and "summary" not in patch.set_frontmatter)

        if not file_changed:
            return {"id": id, "commit": None, "fortified": fortified, "trail": self.forest.trail(id)}

        fm["updated"] = dt.date.today().isoformat()
        validate_frontmatter(fm, self.forest.dialect, strict_summary=False)
        content = serialize_node(fm, body)
        if patch.replace_body is not None:
            # The write validates before it commits (v0.43): whatever the
            # next read would refuse is refused now, while the file on disk
            # is still the old one.
            parse_node(id, content)

        touched: list[tuple[Path, str]] = []
        assert node.path is not None
        touched.append((node.path, node.path.read_text(encoding="utf-8")))
        paths = [node.path]
        try:
            node.path.write_text(content, encoding="utf-8", newline="\n")
            if "summary" in patch.set_frontmatter:
                paths += self._propagate_summary(id, str(patch.set_frontmatter["summary"]), touched)
            commit = self.git.commit(paths, f"graft({id}): {patch.summary_line()}")
        except Exception:
            for path, original in reversed(touched):
                path.write_text(original, encoding="utf-8", newline="\n")
            raise

        self.catalog.upsert_node(self.forest.read(id))
        self.catalog.mark_stale(id)
        for path in paths[1:]:
            idx_id = self.forest.id_for(path)
            self.catalog.upsert_node(self.forest.read(idx_id))
        result = {"id": id, "commit": commit, "fortified": fortified,
                  "trail": self.forest.trail(id)}
        if summary_stale:
            # Absent, never false: a signal, not a judgement of whether the
            # summary still fits — only a reader of both can make that one.
            result["summary_stale"] = True
        return result

    def _propagate_summary(
        self, child_id: str, new_summary: str, touched: list[tuple[Path, str]]
    ) -> list[Path]:
        """Summary changes propagate VERBATIM to every index replicating it."""
        changed_paths: list[Path] = []
        # Sub-branch entries carry a coverage suffix that the rewrite must
        # preserve (A.5, spec v0.13).
        child_row = self.catalog.get(child_id)
        coverage = None
        if child_row is not None and child_row["kind"] == "branch":
            coverage = child_row["coverage"] or None
        for row in self.catalog.conn.execute("SELECT id FROM nodes WHERE kind = 'branch'"):
            idx_id = row[0]
            idx_node = self.forest.read(idx_id)
            new_body, changed = indexer.sync_summary(
                idx_node.body, child_id, new_summary, coverage)
            if changed:
                assert idx_node.path is not None
                touched.append((idx_node.path, idx_node.path.read_text(encoding="utf-8")))
                idx_node.path.write_text(
                    indexer.render_index(idx_node, new_body), encoding="utf-8", newline="\n"
                )
                changed_paths.append(idx_node.path)
        return changed_paths

    # =======================================================================
    # C.14 prune — the write you can take back (v0.56)
    # =======================================================================

    @_traced
    def prune(self, id: str, force: bool = False, *, visible=None) -> dict:
        """Remove one node: passport through git (history keeps it), parent
        index entry and coverage refreshed, catalog row gone, local payload
        moved to `_derived/graveyard/`. `visible` is the host policy's
        predicate (J.3), keyword-only and unreachable from the wire — same
        construction as `scan`'s.
        """
        self._require_writable()
        with self._write_mutex:
            return self._prune(id, bool(force), visible)

    def _prune(self, id: str, force: bool, visible) -> dict:
        row = self._row_or_raise(id)
        if id == "_index":
            raise VineError(
                E_SCHEMA,
                "the forest root cannot be pruned",
                hint="The root index has no parent to account for it.",
            )
        if _is_system(id):
            raise VineError(
                E_SCHEMA,
                f"'{id}' is a system node",
                hint="`_meta/` is the dialect, not content; edit it as an "
                     "operator, never through prune.",
            )
        node = self.forest.read(id)

        # C.14 rule 4: a branch with children is never prunable — recursive
        # deletion is a loop the CALLER writes, one audited decision at a
        # time, not a flag that can erase a subtree in one call.
        if row["kind"] == "branch":
            children = self.catalog.children(id)
            if children:
                raise VineError(
                    E_ANCHORED,
                    f"branch has {len(children)} children; prune them first",
                    hint="No recursive deletion exists (C.14). Remove the "
                         "children, then the branch.",
                )

        # C.14 rule 3: what points at the node refuses the removal.
        anchors = [{"source": e["src"], "rel": e["rel"]}
                   for e in self.catalog.edges_in(id)]
        hidden = 0
        if visible is not None:
            shown = [a for a in anchors if visible(a["source"])]
            hidden = len(anchors) - len(shown)
        else:
            shown = anchors
        if anchors and not force:
            # The list is what the caller needs to decide. Out-of-scope
            # anchors are a count, never names (J.3).
            data = {"anchors": shown[:MAX_PRUNE_ANCHORS_SHOWN],
                    "anchor_count": len(anchors)}
            if hidden:
                data["out_of_scope"] = hidden
            raise VineError(
                E_ANCHORED,
                f"{len(anchors)} node(s) point at {id}",
                hint="Pass force=true to remove the node and strip these "
                     "backlinks in the same commit.",
                data=data,
            )
        if anchors and force and hidden:
            # A write the caller cannot see is a write it cannot have
            # authorized: force edits every pointing node, so every pointing
            # node must be the caller's to edit.
            raise VineError(
                E_ANCHORED,
                f"{hidden} anchor(s) lie outside your scope",
                hint="force strips backlinks from every pointing node; ask "
                     "a principal whose scope covers them.",
            )

        assert node.path is not None
        node_path = node.path
        parent_idx_id = self.forest.parent_index_id(id)
        idx_node = self.forest.read(parent_idx_id)
        assert idx_node.path is not None

        touched: list[tuple[Path, str]] = []
        removed_original = node_path.read_text(encoding="utf-8")
        paths: list[Path] = [node_path]
        backlinks_removed = 0
        payload_moved = None
        moved_pair = None
        try:
            # Backlinks first (force path): the same commit that removes the
            # node leaves nothing pointing at the hole.
            for src in dict.fromkeys(a["source"] for a in anchors):
                src_node = self.forest.read(src)
                fm = dict(src_node.frontmatter)
                links = [Link.model_validate(l) for l in (fm.get("links") or [])]
                kept = [l for l in links if l.target != id]
                if len(kept) == len(links):
                    continue
                backlinks_removed += len(links) - len(kept)
                fm["links"] = [l.model_dump(exclude_none=True) for l in kept]
                if not fm["links"]:
                    fm.pop("links")
                fm["updated"] = dt.date.today().isoformat()
                assert src_node.path is not None
                touched.append((src_node.path,
                                src_node.path.read_text(encoding="utf-8")))
                src_node.path.write_text(
                    serialize_node(fm, src_node.body),
                    encoding="utf-8", newline="\n")
                paths.append(src_node.path)

            # Parent index: the reverse of planting, with the same indexer.
            new_body = indexer.remove_entry_from_body(idx_node.body, id)
            if new_body != idx_node.body:
                touched.append((idx_node.path,
                                idx_node.path.read_text(encoding="utf-8")))
                idx_node.path.write_text(
                    indexer.render_index(idx_node, new_body),
                    encoding="utf-8", newline="\n")
                paths.append(idx_node.path)

            # C.14 rule 2: a local payload moves to the graveyard — binaries
            # are not in git, so unlink would be the one irreversible byte
            # of a primitive that promises to be reversible.
            payload = node.frontmatter.get("payload")
            if payload and not is_remote(payload):
                src_file = self.forest.payload_path(node)
                if src_file.is_file():
                    grave = (Path(self.forest.root) / "_derived" / "graveyard"
                             / id)
                    grave.mkdir(parents=True, exist_ok=True)
                    dest = grave / src_file.name
                    shutil.move(str(src_file), str(dest))
                    moved_pair = (src_file, dest)
                    payload_moved = str(
                        dest.relative_to(Path(self.forest.root)))

            node_path.unlink()
            commit = self.git.commit(paths, f"prune({id})")
        except Exception:
            for path, original in reversed(touched):
                path.write_text(original, encoding="utf-8", newline="\n")
            if not node_path.exists():
                node_path.write_text(removed_original,
                                     encoding="utf-8", newline="\n")
            if moved_pair is not None and moved_pair[1].exists():
                shutil.move(str(moved_pair[1]), str(moved_pair[0]))
            raise

        if row["kind"] == "branch":
            # An empty branch directory after its _index left: remove it,
            # best effort — stray non-forest files keep it, harmlessly.
            try:
                node_path.parent.rmdir()
            except OSError:
                pass
        self.catalog.delete_node(id)
        self.catalog.upsert_node(self.forest.read(parent_idx_id))
        for path in paths:
            if path in (node_path, idx_node.path):
                continue
            src_id = self.forest.id_for(path)
            self.catalog.upsert_node(self.forest.read(src_id))
        return {"id": id, "pruned": True,
                "backlinks_removed": backlinks_removed,
                "payload_moved": payload_moved, "commit": commit}

    # =======================================================================
    # C.15 transplant — the move that leaves a waymark (v0.58)
    # =======================================================================

    @_traced
    def transplant(self, id: str, new_id: str, *, visible=None) -> dict:
        """Move one leaf node to a new address in one commit: passport
        rewritten under `new_id`, every backlink following, both parent
        indexes refreshed, the old id left as a waymark (`moved_from` +
        alias). `visible` is the host policy's predicate, keyword-only and
        unreachable from the wire — `prune`'s construction."""
        self._require_writable()
        with self._write_mutex:
            return self._transplant(id, new_id, visible)

    def _transplant(self, id: str, new_id: str, visible) -> dict:
        row = self._row_or_raise(id)
        new_id = (new_id or "").strip().strip("/")
        if not new_id:
            raise VineError(E_SCHEMA, "new_id must not be empty")
        if new_id == id:
            raise VineError(E_SCHEMA, "new_id equals the current id",
                            hint="A move that goes nowhere is not a move.")
        if row["kind"] == "branch" or id == "_index":
            raise VineError(
                E_SCHEMA,
                f"'{id}' is a branch: branches do not transplant",
                hint="Move the leaves, one audited decision at a time "
                     "(C.15 rule 1).")
        if _is_system(id) or _is_system(new_id):
            raise VineError(
                E_SCHEMA, "'_meta/' is the dialect, not content",
                hint="System nodes neither move nor receive moves.")
        if new_id.endswith("/_index"):
            raise VineError(
                E_SCHEMA, f"'{new_id}' is an index address",
                hint="A leaf cannot become a branch's index by moving.")
        if self.forest.exists(new_id):
            raise VineError(E_SCHEMA, f"id already exists: {new_id}",
                            hint="ids are immutable and unique.")
        new_parent = self.forest.parent_index_id(new_id)
        parent_row = self.catalog.get(new_parent)
        if parent_row is None or parent_row["kind"] != "branch":
            raise VineError(E_NOT_FOUND,
                            f"parent branch not found: {new_parent}")

        # C.15 rule 2: every backlink follows, or the call refuses — an
        # anchor outside the caller's scope is C.14 rule 6's refusal.
        anchors = [e["src"] for e in self.catalog.edges_in(id)]
        if visible is not None:
            hidden = [a for a in anchors if not visible(a)]
            if hidden:
                raise VineError(
                    E_ANCHORED,
                    f"{len(hidden)} pointing node(s) lie outside your scope",
                    hint="A move rewrites every pointing node, so every "
                         "pointing node must be the caller's to edit.")

        node = self.forest.read(id)
        assert node.path is not None
        old_path = node.path
        fm = dict(node.frontmatter)
        fm["id"] = new_id
        fm["updated"] = dt.date.today().isoformat()
        moved_from = [m for m in (fm.get("moved_from") or [])
                      if isinstance(m, str)]
        if id not in moved_from:
            moved_from.append(id)
        fm["moved_from"] = moved_from
        aliases = [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
        alias_clipped = False
        if id not in aliases:
            if len(aliases) < MAX_ALIASES:
                aliases.append(id)
            else:
                alias_clipped = True
        if aliases:
            fm["aliases"] = aliases

        old_parent = self.forest.parent_index_id(id)
        touched: list[tuple[Path, str]] = []
        paths: list[Path] = []
        removed_original = old_path.read_text(encoding="utf-8")
        moved_pair = None
        backlinks = 0
        try:
            new_path = self.forest.path_for(new_id)
            paths.append(new_path)
            self.forest.write(new_id, serialize_node(fm, node.body))
            old_path.unlink()
            paths.append(old_path)

            for src in dict.fromkeys(anchors):
                src_node = self.forest.read(src)
                sfm = dict(src_node.frontmatter)
                links = [Link.model_validate(l)
                         for l in (sfm.get("links") or [])]
                changed = False
                for link in links:
                    if link.target == id:
                        link.target = new_id
                        changed = True
                        backlinks += 1
                if not changed:
                    continue
                sfm["links"] = [l.model_dump(exclude_none=True)
                                for l in links]
                sfm["updated"] = dt.date.today().isoformat()
                assert src_node.path is not None
                touched.append((src_node.path,
                                src_node.path.read_text(encoding="utf-8")))
                src_node.path.write_text(
                    serialize_node(sfm, src_node.body),
                    encoding="utf-8", newline="\n")
                paths.append(src_node.path)

            for idx_id, mutate in ((old_parent, "remove"),
                                   (new_parent, "add")):
                idx = self.forest.read(idx_id)
                assert idx.path is not None
                if mutate == "remove":
                    body = indexer.remove_entry_from_body(idx.body, id)
                    if body == idx.body:
                        continue
                else:
                    body = indexer.add_entry(idx, new_id, fm["summary"],
                                             is_branch=False)
                if idx.path not in paths:
                    touched.append((idx.path,
                                    idx.path.read_text(encoding="utf-8")))
                    paths.append(idx.path)
                idx.path.write_text(indexer.render_index(idx, body),
                                    encoding="utf-8", newline="\n")

            payload = node.frontmatter.get("payload")
            if payload and not is_remote(payload):
                src_file = old_path.parent / payload
                if src_file.is_file():
                    dest = new_path.parent / payload
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_file), str(dest))
                    moved_pair = (src_file, dest)

            commit = self.git.commit(paths, f"transplant({id} -> {new_id})")
        except Exception:
            for path, original in reversed(touched):
                path.write_text(original, encoding="utf-8", newline="\n")
            self.forest.path_for(new_id).unlink(missing_ok=True)
            if not old_path.exists():
                old_path.write_text(removed_original,
                                    encoding="utf-8", newline="\n")
            if moved_pair is not None and moved_pair[1].exists():
                shutil.move(str(moved_pair[1]), str(moved_pair[0]))
            raise

        self.catalog.delete_node(id)
        self.catalog.upsert_node(self.forest.read(new_id))
        for idx_id in dict.fromkeys((old_parent, new_parent)):
            if self.forest.exists(idx_id):
                self.catalog.upsert_node(self.forest.read(idx_id))
        for src in dict.fromkeys(anchors):
            if self.forest.exists(src):
                self.catalog.upsert_node(self.forest.read(src))
        # C.15 rule 5: heat follows the node, best effort — the pheromone
        # was earned by the content, which did not change.
        try:
            self.trails.rekey(id, new_id)
        except Exception:                                    # noqa: BLE001
            pass
        out = {"id": new_id, "moved_from": id,
               "backlinks_rewritten": backlinks, "commit": commit,
               "trail": self.forest.trail(new_id)}
        if alias_clipped:
            out["alias_clipped"] = True
        return out

    # =======================================================================
    # C.16 history — the document's past (v0.58)
    # =======================================================================

    @_traced
    def history(self, id: str, limit: int = 20) -> dict:
        """The node's commits, newest first, through renames — what
        happened, when (with time of day), and by whom when the commit
        carries the attribution trailer."""
        self._row_or_raise(id)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise VineError(E_SCHEMA, "limit must be an integer") from None
        limit = min(max(1, limit), MAX_HISTORY)
        rel = (self.forest.path_for(id).resolve()
               .relative_to(self.forest.root.resolve())).as_posix()
        # One extra row answers "is there more past than this page".
        entries = self.git.file_history(rel, limit=limit + 1)
        more = len(entries) > limit
        entries = entries[:limit]
        for entry in entries:
            subject = entry.get("message") or ""
            # The commit subject's own convention: `plant(id): …`,
            # `gardener(sync): …` — the prefix before the parenthesis.
            head = subject.split("(", 1)[0].strip()
            entry["action"] = head if head and " " not in head else subject
        payload = {"id": id, "entries": entries,
                   "returned": len(entries), "truncated": more}
        payload = shrink_list_to_budget(payload, "entries", BUDGET_HISTORY)
        payload["returned"] = len(payload["entries"])
        if payload["entries"]:
            payload["oldest"] = payload["entries"][-1]["commit"]
        return payload

    def _require_writable(self) -> None:
        if not self.writable:
            raise VineError(E_READONLY, "this Vine is read-only", hint="Start without --readonly to write.")
