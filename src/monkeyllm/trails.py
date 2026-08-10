# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Pheromone trails (_derived/trails.db).

Persistent heat (the long-term whisper) plus session-scoped namespaces
(Phase 1.5 Troop readiness — required by spec Part E.2). Evaporation
(spec H.1) decays the persistent scope with a configurable half-life and
clears stale session leftovers.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from monkeyllm.forest import tune_derived

PERSISTENT_SCOPE = ""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS heat (
    scope TEXT NOT NULL DEFAULT '',
    node_id TEXT NOT NULL,
    heat REAL NOT NULL DEFAULT 0,
    updated REAL NOT NULL,
    PRIMARY KEY (scope, node_id)
);
"""


class Trails:
    def __init__(self, derived_dir: Path):
        derived_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = derived_dir / "trails.db"
        self.conn = sqlite3.connect(self.db_path)
        tune_derived(self.conn)
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def warm(self) -> None:
        """Fault in the heat table without depositing any.

        Read-only on purpose: heat is a memory of where callers actually
        went, and a warm-up that wrote to it would be the server inventing
        traffic that never happened.
        """
        self.conn.execute("SELECT count(*) FROM heat WHERE scope = ''").fetchone()

    def add_heat(self, node_ids: list[str], amount: float = 0.1, scope: str = PERSISTENT_SCOPE) -> None:
        now = time.time()
        for nid in node_ids:
            self.conn.execute(
                """INSERT INTO heat (scope, node_id, heat, updated) VALUES (?,?,?,?)
                   ON CONFLICT(scope, node_id)
                   DO UPDATE SET heat = MIN(heat + ?, 1.0), updated = ?""",
                (scope, nid, min(amount, 1.0), now, amount, now),
            )
        self.conn.commit()

    def get_heat(self, node_id: str, session: str | None = None, beta: float = 0.5) -> float:
        row = self.conn.execute(
            "SELECT heat FROM heat WHERE scope = '' AND node_id = ?", (node_id,)
        ).fetchone()
        heat = row[0] if row else 0.0
        if session:
            row = self.conn.execute(
                "SELECT heat FROM heat WHERE scope = ? AND node_id = ?", (session, node_id)
            ).fetchone()
            if row:
                heat += beta * row[0]
        return round(min(heat, 1.0), 4)

    def heat_map(self, node_ids: list[str], session: str | None = None) -> dict[str, float]:
        return {nid: self.get_heat(nid, session) for nid in node_ids}

    def heat_all(self) -> dict[str, float]:
        """Every warm node in the persistent scope, in one read.

        `heat_map` asks per node, which is right for the handful a primitive
        returns and wrong for a caller holding the whole region (J.11): one
        statement beats two thousand. Persistent scope only — session heat
        belongs to a hunt in flight, never to a map.
        """
        return {
            nid: round(heat, 4)
            for nid, heat in self.conn.execute(
                "SELECT node_id, heat FROM heat WHERE scope = ''")
        }

    def promote_session(self, session: str, node_ids: list[str], amount: float = 0.1) -> None:
        """Convert winning-trail session heat into persistent heat."""
        self.add_heat(node_ids, amount, PERSISTENT_SCOPE)
        self.clear_session(session)

    def clear_session(self, session: str) -> None:
        self.conn.execute("DELETE FROM heat WHERE scope = ?", (session,))
        self.conn.commit()

    # -- spec H.1: evaporation (derived layer only — never commits) --------

    def evaporate(self, half_life_days: float = 30.0, *,
                  now: float | None = None, floor: float = 0.01) -> dict:
        """heat' = heat * 0.5^(dt/half_life); dust rows (< floor) vanish.
        Re-stamps `updated`, so back-to-back runs are no-ops."""
        now = time.time() if now is None else now
        half_life_s = half_life_days * 86400.0
        decayed = removed = 0
        for nid, heat, updated in self.conn.execute(
            "SELECT node_id, heat, updated FROM heat WHERE scope = ''"
        ).fetchall():
            dt_s = now - updated
            if dt_s <= 0:
                continue
            new = heat * (0.5 ** (dt_s / half_life_s))
            if new < floor:
                self.conn.execute(
                    "DELETE FROM heat WHERE scope = '' AND node_id = ?", (nid,))
                removed += 1
            else:
                self.conn.execute(
                    "UPDATE heat SET heat = ?, updated = ? WHERE scope = '' AND node_id = ?",
                    (new, now, nid))
                decayed += 1
        self.conn.commit()
        return {"decayed": decayed, "removed": removed}

    def clear_stale_sessions(self, ttl_hours: float = 24.0, *,
                             now: float | None = None) -> int:
        """Crash leftovers from Troop hunts must not survive (H.1)."""
        now = time.time() if now is None else now
        cur = self.conn.execute(
            "DELETE FROM heat WHERE scope != '' AND updated < ?",
            (now - ttl_hours * 3600.0,))
        self.conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(heat), 0), COALESCE(AVG(heat), 0) "
            "FROM heat WHERE scope = ''").fetchone()
        return {"rows": row[0], "max": round(row[1], 4), "mean": round(row[2], 4)}

    def set_updated(self, node_id: str, when: float,
                    scope: str = PERSISTENT_SCOPE) -> None:
        """Test/maintenance helper: rewind a row's clock (synthetic time)."""
        self.conn.execute(
            "UPDATE heat SET updated = ? WHERE scope = ? AND node_id = ?",
            (when, scope, node_id))
        self.conn.commit()
