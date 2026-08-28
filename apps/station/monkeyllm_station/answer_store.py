# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The answer already given (spec v0.33, J.10.7).

`answer` is the one call in this host that costs real money and real
seconds; everything beneath it is a fraction of a millisecond. The store
keeps the answers this deployment already paid for, named by everything
that shaped the call — so a hit is byte-for-byte the answer that was
bought, and anything that could change the answer changes the key instead
of going stale.

Two digests with two jobs (v0.35). The key — normalised question,
effective terms, `k`, the hops budget, the resolved binding, the caller's
scope — finds the entry; the **reading fingerprint** stored with it
decides whether the model owes a fresh pass: the sweep runs its retrieval
on every ask and serves the stored reply only when the material the model
would read is the material it already answered. The walk cannot be
re-walked without paying the model, so walk entries additionally carry
the forest's HEAD in the key and every commit invalidates them. The scope
is in the key so an entry can never cross scopes: J.10.3's invariant
survives the store by construction, not by a check.

The store lives in the forest's `_derived/` — the disposable layer, out of
git, never a source of truth. A connection is opened per operation, so the
store has no thread affinity of its own; callers still only reach it from
the forest's lane, because that is where `answer` runs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE_DIR = ("_derived", "cache")
STORE_FILE = "answers.db"

# A digest names an entry in logs and audit rows; sixteen hex characters are
# plenty to find it and short enough to read.
DIGEST_CHARS = 16

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key         TEXT PRIMARY KEY,
    question    TEXT NOT NULL,   -- as asked, for the operator reading the store
    response    TEXT NOT NULL,   -- the whole composite response, as served
    trail       TEXT NOT NULL,   -- JSON list of node ids: a WALK hit heats these
    fingerprint TEXT,            -- the reading (v0.35); NULL for walk entries
    priced      INTEGER NOT NULL DEFAULT 0,
    usd         REAL,
    created     TEXT NOT NULL,
    last_served TEXT NOT NULL,
    served      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_entries_lru ON entries(last_served);
-- The store's economy, kept next to the entries it describes. Clearing the
-- entries keeps the tallies: what was saved so far is history, not cache.
CREATE TABLE IF NOT EXISTS tallies (
    name  TEXT PRIMARY KEY,
    value REAL NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize(question: str) -> str:
    """Normalised for nothing but writing: NFC, trimmed, inner whitespace
    collapsed, case-folded. Two spellings of the same sentence are one key;
    two sentences are two."""
    folded = unicodedata.normalize("NFC", str(question or "")).casefold().strip()
    return " ".join(folded.split())


def build_key(*, question: str, terms, k: int, hops, hybrid: bool,
              binding: dict, policy, head: str | None = None,
              reply_tokens: int | None = None,
              window: dict | None = None,
              include_superseded: bool = False) -> str:
    """The closed list of J.10.7 — and nothing off it.

    Every component here can change the answer; nothing else may enter,
    because every extra component is a hit rate halved for no correctness
    bought. The binding contributes what answers (provider, model, budget,
    reasoning) and never its credentials; the policy contributes the scope
    exactly as enforced (J.3), so an entry is shared across principals whose
    scope is identical and unreachable across scopes. `head` is the walk's
    pin (v0.35): a sweep passes None, because its freshness is decided by
    the reading fingerprint rather than by the forest's clock.
    `reply_tokens` (J.10.8) enters only when the caller set one — the
    material keeps its old shape otherwise, so an upgrade invalidates
    nothing. `window` (C.13.1) enters on the same terms and MUST: it
    changes which nodes the retrieval could reach at all, so the same
    question bounded to June and to July are two questions.
    `include_superseded` (C.6c.4 rule 4) enters on those same terms and for
    that same reason: the flag decides whether a replaced document is in the
    material at all, so the history view and the current view are two
    questions — and off, which is the default, keys exactly as before.
    """
    material = json.dumps({
        "question": normalize(question),
        # The engine folds terms before matching (C.6b), so two spellings of
        # a term are one retrieval — and must be one key.
        "terms": [normalize(t) for t in (terms or [])],
        "k": int(k),
        "hops": hops,
        "hybrid": bool(hybrid),
        "binding": {
            "provider": binding.get("provider"),
            "model": binding.get("model"),
            "max_tokens": binding.get("max_tokens"),
            "reasoning": binding.get("reasoning"),
        },
        "scope": {
            "allow": sorted(policy.allow),
            "deny": sorted(policy.deny),
            "tables": {d: sorted(t) for d, t in sorted((policy.tables or {}).items())},
        },
        "head": head,
        **({"reply_tokens": int(reply_tokens)} if reply_tokens else {}),
        **({"window": {"since": window.get("since"),
                       "until": window.get("until"),
                       "date_field": window.get("date_field")}}
           if window else {}),
        **({"include_superseded": True} if include_superseded else {}),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def reading_fingerprint(bundle: dict) -> str:
    """The second digest of J.10.7 (v0.35): the reading, never the ranking.

    Hashes what the model would actually read — the set of results keyed
    by id, each contributing type, title, summary, matches and body
    content, plus the truncation flag — and excludes everything volatile:
    not score, not heat, not the serving order. Pheromone drifts on every
    use and reorders near-ties (Part D); the order is the ranking's affair,
    not the body's, and a store invalidated by its own hits would never
    hold an entry. A result that enters or leaves the set is a change of
    reading; a set that merely reshuffled is not.

    `notes` is in the list (v0.48) because it is in the bundle (C.2.1 rule
    6): the teaching is handed to the model, so a teaching edited is a
    reading changed — without it, an operator writing notes could not
    invalidate an answer built before them. The dates and the
    supersession annotations join for the same reason (C.6c.3, v0.57).
    """
    material = sorted(
        [[r.get("id"), r.get("type"), r.get("title"), r.get("summary"),
          r.get("matches"), r.get("content"), r.get("notes"),
          # C.6c.3 (v0.57): the material's stated time and order are handed
          # to the model, so material re-dated or re-ordered is material
          # re-read — a stored answer built before a succession was
          # declared must not be served after it.
          r.get("created"), r.get("updated"),
          r.get("supersedes"), r.get("superseded_by")]
         for r in (bundle.get("results") or [])],
        key=lambda item: str(item[0]))
    payload = json.dumps(
        {"results": material, "truncated": bool(bundle.get("truncated"))},
        sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def storable(result: dict) -> bool:
    """Nothing empty and nothing broken enters the store (J.10.7).

    An errored or refused call, a truncated response, a turn that produced a
    commit, an answer with no evidence or no text — none of them are worth a
    key. The empty answer is the least useful response this product can
    give, and the store must never make it the fastest.
    """
    if not isinstance(result, dict) or "error" in result:
        return False
    if result.get("cached") or result.get("truncated") or result.get("commit"):
        return False
    if not (result.get("answer") or "").strip():
        return False
    return bool(result.get("evidence"))


class AnswerStore:
    """One forest's store, in that forest's own disposable layer."""

    def __init__(self, forest_root: Path):
        self.path = Path(forest_root).joinpath(*STORE_DIR) / STORE_FILE

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        # The store is the disposable layer: a file from before the reading
        # fingerprint (v0.35) is not migrated, it is bought again. Dropping
        # it costs money, never truth — and never a wrong answer, which a
        # column full of NULLs served as fingerprints could be.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
        if "fingerprint" not in cols:
            conn.execute("DROP TABLE entries")
            conn.executescript(SCHEMA)
        return conn

    def _bump(self, conn: sqlite3.Connection, name: str, amount: float = 1.0) -> None:
        conn.execute(
            "INSERT INTO tallies (name, value) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
            (name, amount))

    # -- the read path ------------------------------------------------------

    def get(self, key: str, ttl_hours: float | None = None) -> dict | None:
        """The entry this key names, or None. Counting is the caller's:
        whether an absent row or a stale reading is the miss depends on
        which check failed (J.10.7 v0.35), and only the caller knows.

        A TTL is hygiene, never correctness (the reading check and the
        walk's HEAD already invalidate): an entry past it is deleted on
        sight rather than served.
        """
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM entries WHERE key = ?",
                               (key,)).fetchone()
            if row is not None and ttl_hours:
                born = datetime.fromisoformat(row["created"])
                if _now() - born > timedelta(hours=float(ttl_hours)):
                    conn.execute("DELETE FROM entries WHERE key = ?", (key,))
                    conn.commit()
                    row = None
            return dict(row) if row is not None else None

    def count_miss(self) -> None:
        """One consulted lookup that did not serve — absent entry or a
        reading that changed under it."""
        with closing(self._connect()) as conn:
            self._bump(conn, "misses")
            conn.commit()

    def touch(self, key: str, *, priced: bool, usd: float | None) -> None:
        """A hit happened: the entry was served. The saving is counted only
        when the original run was priced — an unpriced saving is unpriced,
        never $0.00 (J.10.4's rule in mirror)."""
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE entries SET served = served + 1, last_served = ? "
                "WHERE key = ?", (_now().isoformat(), key))
            self._bump(conn, "hits")
            if priced and usd:
                self._bump(conn, "priced_hits")
                self._bump(conn, "avoided_usd", float(usd))
            conn.commit()

    # -- the write path -----------------------------------------------------

    def put(self, key: str, *, question: str, response: str, trail: list,
            priced: bool, usd: float | None, bound: int,
            fingerprint: str | None = None) -> None:
        """Store (or replace — `cache: false` and a changed reading both
        refresh) and hold the bound: the store is finite and evicts
        oldest-served-first, out loud via `stats()` rather than by silently
        growing."""
        now = _now().isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entries "
                "(key, question, response, trail, fingerprint, priced, usd, "
                " created, last_served, served) VALUES (?,?,?,?,?,?,?,?,?,0)",
                (key, question, response, json.dumps(trail), fingerprint,
                 int(bool(priced)), usd, now, now))
            if bound and bound > 0:
                conn.execute(
                    "DELETE FROM entries WHERE key NOT IN "
                    "(SELECT key FROM entries "
                    " ORDER BY last_served DESC, created DESC LIMIT ?)",
                    (int(bound),))
            conn.commit()

    # -- the operator's view ------------------------------------------------

    def clear(self) -> int:
        """Empty the entries; keep the tallies. What was saved so far is
        history, not cache — deleting the store costs money, never truth."""
        with closing(self._connect()) as conn:
            gone = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            conn.execute("DELETE FROM entries")
            conn.commit()
            return int(gone)

    def stats(self) -> dict:
        with closing(self._connect()) as conn:
            held = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            tallies = {r["name"]: r["value"]
                       for r in conn.execute("SELECT * FROM tallies")}
        out = {"held": int(held),
               "hits": int(tallies.get("hits", 0)),
               "misses": int(tallies.get("misses", 0))}
        # Money appears only when priced runs were actually avoided: silence
        # is never rendered as $0.00.
        if tallies.get("priced_hits"):
            out["avoided_usd"] = round(tallies.get("avoided_usd", 0.0), 6)
        return out
