"""The host registry (spec J.2) — principals, API keys, grants.

Deliberately NOT inside any forest: a forest handed to another operator
must carry no credentials (J.0). One SQLite file, no external database
(J.6).
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from monkeyllm_station.policy import CAPS, Policy

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS principals (
    id      TEXT PRIMARY KEY,
    kind    TEXT NOT NULL DEFAULT 'service',   -- 'user' | 'service'
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash  TEXT PRIMARY KEY,
    principal TEXT NOT NULL REFERENCES principals(id),
    label     TEXT,
    created   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
    principal TEXT NOT NULL REFERENCES principals(id),
    forest    TEXT NOT NULL,
    caps      TEXT NOT NULL,
    PRIMARY KEY (principal, forest)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_key(key: str) -> str:
    """API keys are 256-bit random tokens, so a plain digest is enough — the
    slow-KDF argument applies to guessable secrets, not to these."""
    return hashlib.sha256(key.encode()).hexdigest()


class Registry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- principals and keys ------------------------------------------------

    def add_principal(self, principal_id: str, kind: str = "service") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO principals (id, kind, created) VALUES (?,?,?)",
            (principal_id, kind, _now()),
        )
        self.conn.commit()

    def issue_key(self, principal_id: str, label: str | None = None) -> str:
        """Mint an API key. The plaintext is returned ONCE and never stored."""
        self.add_principal(principal_id)
        key = f"mk_{secrets.token_urlsafe(32)}"
        self.conn.execute(
            "INSERT INTO api_keys (key_hash, principal, label, created) VALUES (?,?,?,?)",
            (hash_key(key), principal_id, label, _now()),
        )
        self.conn.commit()
        return key

    def authenticate(self, key: str | None) -> str | None:
        """API key -> principal id, or None. Lookup is by digest, so a stolen
        registry file yields no usable keys."""
        if not key:
            return None
        row = self.conn.execute(
            "SELECT principal FROM api_keys WHERE key_hash = ?", (hash_key(key),)
        ).fetchone()
        return row["principal"] if row else None

    # -- grants -------------------------------------------------------------

    def grant(self, principal_id: str, forest: str, caps: set[str] | frozenset[str]) -> None:
        unknown = set(caps) - CAPS
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        self.add_principal(principal_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO grants (principal, forest, caps) VALUES (?,?,?)",
            (principal_id, forest, ",".join(sorted(caps))),
        )
        self.conn.commit()

    def revoke(self, principal_id: str, forest: str) -> None:
        self.conn.execute(
            "DELETE FROM grants WHERE principal = ? AND forest = ?",
            (principal_id, forest),
        )
        self.conn.commit()

    def policy_for(self, principal_id: str, forest: str) -> Policy | None:
        """Deny-by-default (J.3): no grant means no access."""
        row = self.conn.execute(
            "SELECT caps FROM grants WHERE principal = ? AND forest = ?",
            (principal_id, forest),
        ).fetchone()
        if row is None:
            return None
        return Policy(forest=forest, caps=frozenset(row["caps"].split(",")))

    def forests_for(self, principal_id: str) -> list[str]:
        return [
            r["forest"]
            for r in self.conn.execute(
                "SELECT forest FROM grants WHERE principal = ? ORDER BY forest",
                (principal_id,),
            )
        ]

    # -- bootstrap ----------------------------------------------------------

    def bootstrap_admin(self, forests: list[str], principal_id: str = "admin") -> str | None:
        """First-run convenience: if no key exists, mint one with full caps on
        every forest in the registry. Returns the plaintext key, or None when
        the registry is already populated."""
        if self.conn.execute("SELECT 1 FROM api_keys LIMIT 1").fetchone():
            return None
        key = self.issue_key(principal_id, label="bootstrap")
        for forest in forests:
            self.grant(principal_id, forest, set(CAPS))
        return key
