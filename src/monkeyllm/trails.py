"""Pheromone trails (_derived/trails.db).

Persistent heat (the long-term whisper) plus session-scoped namespaces
(Phase 1.5 Troop readiness — required by spec Part E.2). Evaporation is
the Ranger's job (out of Phase 0 scope); the schema already carries
timestamps for it.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

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
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

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

    def promote_session(self, session: str, node_ids: list[str], amount: float = 0.1) -> None:
        """Convert winning-trail session heat into persistent heat."""
        self.add_heat(node_ids, amount, PERSISTENT_SCOPE)
        self.clear_session(session)

    def clear_session(self, session: str) -> None:
        self.conn.execute("DELETE FROM heat WHERE scope = ?", (session,))
        self.conn.commit()
