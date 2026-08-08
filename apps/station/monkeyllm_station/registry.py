"""The host registry (spec J.2) — principals, API keys, grants.

Deliberately NOT inside any forest: a forest handed to another operator
must carry no credentials (J.0). One SQLite file, no external database
(J.6).
"""

from __future__ import annotations

import hashlib
import json
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
    allow     TEXT NOT NULL DEFAULT '[""]',   -- JSON list; [""] = whole forest
    deny      TEXT NOT NULL DEFAULT '[]',
    tables    TEXT NOT NULL DEFAULT '{}',     -- JSON {dataset_id: [table, ...]}
    PRIMARY KEY (principal, forest)
);
CREATE TABLE IF NOT EXISTS audit (
    ts        TEXT NOT NULL,
    principal TEXT NOT NULL,
    forest    TEXT NOT NULL,
    primitive TEXT NOT NULL,
    args      TEXT NOT NULL,   -- digest only: never bodies or snippets (J.4)
    result    TEXT NOT NULL,
    size      INTEGER NOT NULL DEFAULT 0,
    commit_sha TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_principal ON audit(principal);

-- Inference providers (J.10): any OpenAI-compatible /v1 — OpenRouter,
-- LiteLLM, vLLM, a local llama.cpp. The key is write-only over the API.
CREATE TABLE IF NOT EXISTS providers (
    name     TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    api_key  TEXT,
    created  TEXT NOT NULL
);
-- Which model serves which ROLE on which forest: a forest ingested by a
-- careful summariser can be answered by a fast reader, and vice versa.
CREATE TABLE IF NOT EXISTS model_bindings (
    forest     TEXT NOT NULL,
    role       TEXT NOT NULL,          -- 'ingest' | 'answer'
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    max_tokens INTEGER NOT NULL DEFAULT 600,
    reasoning  TEXT NOT NULL DEFAULT 'off',
    PRIMARY KEY (forest, role)
);
"""

ROLES = ("ingest", "answer")

# Columns added after the Phase A schema shipped; a Station upgraded in place
# must not lose its principals over a migration.
MIGRATIONS = {
    "grants": {
        "allow": "TEXT NOT NULL DEFAULT '[\"\"]'",
        "deny": "TEXT NOT NULL DEFAULT '[]'",
        "tables": "TEXT NOT NULL DEFAULT '{}'",
    },
}


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
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        for table, columns in MIGRATIONS.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

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

    def grant(
        self,
        principal_id: str,
        forest: str,
        caps: set[str] | frozenset[str],
        allow: list[str] | tuple[str, ...] | None = None,
        deny: list[str] | tuple[str, ...] | None = None,
        tables: dict[str, list[str]] | None = None,
    ) -> None:
        unknown = set(caps) - CAPS
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        # Build the Policy before storing it: an unenforceable grant must fail
        # here, at write time, rather than silently at read time.
        Policy(forest=forest, caps=frozenset(caps),
               allow=tuple(allow) if allow else ("",),
               deny=tuple(deny or ()), tables={k: tuple(v) for k, v in (tables or {}).items()})
        self.add_principal(principal_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO grants (principal, forest, caps, allow, deny, tables) "
            "VALUES (?,?,?,?,?,?)",
            (principal_id, forest, ",".join(sorted(caps)),
             json.dumps(list(allow) if allow else [""]),
             json.dumps(list(deny or [])),
             json.dumps(tables or {})),
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
            "SELECT caps, allow, deny, tables FROM grants WHERE principal = ? AND forest = ?",
            (principal_id, forest),
        ).fetchone()
        if row is None:
            return None
        return Policy(
            forest=forest,
            caps=frozenset(row["caps"].split(",")),
            allow=tuple(json.loads(row["allow"])),
            deny=tuple(json.loads(row["deny"])),
            tables={k: tuple(v) for k, v in json.loads(row["tables"]).items()},
        )

    def forests_for(self, principal_id: str) -> list[str]:
        return [
            r["forest"]
            for r in self.conn.execute(
                "SELECT forest FROM grants WHERE principal = ? ORDER BY forest",
                (principal_id,),
            )
        ]

    # -- audit (J.4) --------------------------------------------------------

    def record(self, *, principal: str, forest: str, primitive: str, args: dict,
               result: str, size: int = 0, commit_sha: str | None = None) -> None:
        """Access log. Arguments are digested, never stored verbatim: the log
        records who read what, not the content they read."""
        digest = {}
        for key, value in (args or {}).items():
            text = str(value)
            digest[key] = text if len(text) <= 80 else f"<{len(text)} chars>"
        self.conn.execute(
            "INSERT INTO audit (ts, principal, forest, primitive, args, result, size, commit_sha) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_now(), principal, forest, primitive,
             json.dumps(digest, ensure_ascii=False), result, size, commit_sha),
        )
        self.conn.commit()

    def audit(self, limit: int = 100, principal: str | None = None) -> list[dict]:
        sql = "SELECT * FROM audit"
        params: list = []
        if principal:
            sql += " WHERE principal = ?"
            params.append(principal)
        sql += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params)]

    # -- introspection ------------------------------------------------------

    def principals(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT p.id, p.kind, p.created, "
            "  (SELECT COUNT(*) FROM api_keys k WHERE k.principal = p.id) AS keys, "
            "  (SELECT COUNT(*) FROM grants g WHERE g.principal = p.id) AS grants "
            "FROM principals p ORDER BY p.id"
        )
        return [dict(r) for r in rows]

    def grants_of(self, principal_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT forest, caps, allow, deny, tables FROM grants WHERE principal = ? "
            "ORDER BY forest", (principal_id,),
        )
        return [
            {"forest": r["forest"], "caps": sorted(r["caps"].split(",")),
             "allow": json.loads(r["allow"]), "deny": json.loads(r["deny"]),
             "tables": json.loads(r["tables"])}
            for r in rows
        ]

    # -- inference providers and per-forest model bindings (J.10) -----------

    def put_provider(self, name: str, endpoint: str, api_key: str | None) -> None:
        """Store a provider. An empty `api_key` keeps the stored one, so the
        console can edit an endpoint without ever holding the secret."""
        if not name or not endpoint:
            raise ValueError("provider needs a name and an endpoint")
        existing = self.conn.execute(
            "SELECT api_key FROM providers WHERE name = ?", (name,)
        ).fetchone()
        key = api_key if api_key else (existing["api_key"] if existing else None)
        self.conn.execute(
            "INSERT OR REPLACE INTO providers (name, endpoint, api_key, created) "
            "VALUES (?,?,?,?)",
            (name, endpoint.rstrip("/"), key, _now()),
        )
        self.conn.commit()

    def delete_provider(self, name: str) -> None:
        self.conn.execute("DELETE FROM providers WHERE name = ?", (name,))
        self.conn.execute("DELETE FROM model_bindings WHERE provider = ?", (name,))
        self.conn.commit()

    def providers(self) -> list[dict]:
        """Never returns secrets — only whether one is set."""
        return [
            {"name": r["name"], "endpoint": r["endpoint"],
             "has_key": bool(r["api_key"]), "created": r["created"]}
            for r in self.conn.execute("SELECT * FROM providers ORDER BY name")
        ]

    def provider_secret(self, name: str) -> dict | None:
        """Server-side only: the one path that reads the key back."""
        row = self.conn.execute(
            "SELECT name, endpoint, api_key FROM providers WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def bind_model(self, forest: str, role: str, provider: str, model: str,
                   max_tokens: int = 600, reasoning: str = "off") -> None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {list(ROLES)}")
        if not self.conn.execute("SELECT 1 FROM providers WHERE name = ?",
                                 (provider,)).fetchone():
            raise ValueError(f"unknown provider: {provider}")
        self.conn.execute(
            "INSERT OR REPLACE INTO model_bindings "
            "(forest, role, provider, model, max_tokens, reasoning) VALUES (?,?,?,?,?,?)",
            (forest, role, provider, model, int(max_tokens),
             "on" if str(reasoning).lower() == "on" else "off"),
        )
        self.conn.commit()

    def unbind_model(self, forest: str, role: str) -> None:
        self.conn.execute("DELETE FROM model_bindings WHERE forest = ? AND role = ?",
                          (forest, role))
        self.conn.commit()

    def bindings(self, forest: str | None = None) -> list[dict]:
        sql = "SELECT * FROM model_bindings"
        params: list = []
        if forest:
            sql += " WHERE forest = ?"
            params.append(forest)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY forest, role", params)]

    def binding(self, forest: str, role: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM model_bindings WHERE forest = ? AND role = ?", (forest, role)
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        secret = self.provider_secret(out["provider"])
        if secret is None:
            return None
        out["endpoint"] = secret["endpoint"]
        out["api_key"] = secret["api_key"]
        return out

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
