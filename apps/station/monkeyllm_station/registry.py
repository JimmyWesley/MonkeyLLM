# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

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
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monkeyllm_station.policy import CAPS, Policy

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS principals (
    id      TEXT PRIMARY KEY,
    kind    TEXT NOT NULL DEFAULT 'service',   -- 'user' | 'service'
    created TEXT NOT NULL,
    -- J.2.1: unlike an API key, a password is guessable, so it is stored as
    -- a salted memory-hard hash rather than a plain digest. NULL means this
    -- principal simply has no password door — never a blank one.
    pw_salt TEXT,
    pw_hash TEXT,
    -- J.2.4: the owner bit. `admin` on every forest present AND future,
    -- including on none — which is the only shape that can create the first
    -- forest on an empty registry. A property of the principal, never a sum
    -- of grants, because a grant can be revoked one forest at a time and
    -- would leave a half-owner behind.
    owner INTEGER NOT NULL DEFAULT 0,
    -- Optional contact for the owner (J.2.4). Local only: nothing here is
    -- ever transmitted, so setup completes on an air-gapped host.
    email TEXT
);
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash     TEXT PRIMARY KEY,
    principal    TEXT NOT NULL REFERENCES principals(id),
    label        TEXT,
    created      TEXT NOT NULL,
    -- J.2.2: a credential that cannot be listed, expired or revoked is not
    -- governed. `prefix` is the non-secret head, so a token can be
    -- recognised in a list without being disclosed.
    prefix       TEXT,
    kind         TEXT NOT NULL DEFAULT 'api',   -- 'api' | 'session'
    expires_at   TEXT,
    revoked_at   TEXT,
    last_used_at TEXT
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
-- `origin` says who declared it: 'console' rows are typed in and keep their
-- key here; 'env' rows are declared by the deployment (J.10.1) and their
-- key is NEVER stored — it is read back from the environment at call time.
CREATE TABLE IF NOT EXISTS providers (
    name     TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    api_key  TEXT,
    created  TEXT NOT NULL,
    origin   TEXT NOT NULL DEFAULT 'console'
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
-- Per-forest switches that are not bindings. Today only the Gauntlet's
-- on/off (Part K); a table rather than a column because the next one will
-- not be about models either.
CREATE TABLE IF NOT EXISTS forest_settings (
    forest TEXT NOT NULL,
    key    TEXT NOT NULL,
    value  TEXT NOT NULL,
    PRIMARY KEY (forest, key)
);
"""

# Indexes over columns that MIGRATIONS may still be about to add. Running
# these inside SCHEMA_SQL would fail on an in-place upgrade, because
# `CREATE TABLE IF NOT EXISTS` is a no-op there and the column does not
# exist yet — so they run after the migration instead.
POST_MIGRATION_SQL = """
-- J.2.4: exactly one owner, enforced by the database rather than by the
-- code path that happens to create them. Two concurrent setup calls cannot
-- both win, whatever the application layer does.
CREATE UNIQUE INDEX IF NOT EXISTS idx_single_owner
    ON principals(owner) WHERE owner = 1;
"""

# `embed` is not a chat model: it builds the Canopy and points the
# Gauntlet (Part K). Absent, navigation is unchanged.
ROLES = ("ingest", "answer", "embed")

# Columns added after the Phase A schema shipped; a Station upgraded in place
# must not lose its principals over a migration.
MIGRATIONS = {
    "grants": {
        "allow": "TEXT NOT NULL DEFAULT '[\"\"]'",
        "deny": "TEXT NOT NULL DEFAULT '[]'",
        "tables": "TEXT NOT NULL DEFAULT '{}'",
    },
    "principals": {"pw_salt": "TEXT", "pw_hash": "TEXT",
                   "owner": "INTEGER NOT NULL DEFAULT 0", "email": "TEXT"},
    "api_keys": {
        "prefix": "TEXT",
        "kind": "TEXT NOT NULL DEFAULT 'api'",
        "expires_at": "TEXT",
        "revoked_at": "TEXT",
        "last_used_at": "TEXT",
    },
    "providers": {"origin": "TEXT NOT NULL DEFAULT 'console'"},
}

# A login is good for a working day. Long enough not to nag, short enough
# that a browser left open in a meeting room is not a permanent credential.
SESSION_HOURS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _in_hours(hours: float) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(hours=hours)).isoformat(timespec="seconds")


def hash_key(key: str) -> str:
    """API keys are 256-bit random tokens, so a plain digest is enough — the
    slow-KDF argument applies to guessable secrets, not to these."""
    return hashlib.sha256(key.encode()).hexdigest()


def hash_password(password: str, salt: str) -> str:
    """scrypt from the standard library: memory-hard, no new dependency.

    A password is guessable, which is exactly the case `hash_key`'s plain
    digest does not cover — a stolen registry with sha256 password digests
    is a wordlist away from every account.
    """
    return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                          n=2 ** 14, r=8, p=1, dklen=32).hex()


class Registry:
    """The host's own storage: principals, keys, grants, bindings, audit.

    **One connection per thread.** The Station touches this file from two
    threads by design — the event loop authenticates every request, and the
    forest worker writes the audit record once a call has run — and a single
    `sqlite3.Connection` shared between them shares its *transaction state*
    too. One thread's `commit()` then lands inside the other's open
    transaction, and the loser raises "cannot commit - no transaction is
    active" mid-request: a 500 for the caller and a silently dropped audit
    row. It is intermittent, which is why a mostly-sequential test suite
    never saw it.

    A lock around every method would work and would be wrong to maintain:
    thirty-odd methods touch the connection, and the thirty-first added later
    reintroduces the bug quietly. Giving each thread its own connection makes
    the isolation structural — no method can forget it — and lets SQLite
    arbitrate between them, which is what it is for.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._opened: list[sqlite3.Connection] = []
        self._opened_lock = threading.Lock()
        self.conn.executescript(SCHEMA_SQL)
        self._migrate()
        self.conn.executescript(POST_MIGRATION_SQL)
        self.conn.commit()
        # Keys of environment-declared providers (J.10.1). In memory, for the
        # life of the process, and never written: the registry file is a
        # backup target and the environment is not.
        self._env_secrets: dict[str, str] = {}

    def _migrate(self) -> None:
        for table, columns in MIGRATIONS.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    @property
    def conn(self) -> sqlite3.Connection:
        """This thread's connection, opened the first time it asks."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # `check_same_thread=False` is not what makes this safe — one
            # connection per thread is. It is here only so `close()` can shut
            # down connections belonging to threads that have already gone.
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # WAL lets the reader on the event loop and the writer on the
            # forest thread proceed at once; without it they serialise on the
            # whole file and a read can fail while a write is in flight.
            conn.execute("PRAGMA journal_mode=WAL")
            # Two writers still take turns. Waiting a moment is the right
            # answer; failing the request is not.
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
            with self._opened_lock:
                self._opened.append(conn)
        return conn

    def close(self) -> None:
        with self._opened_lock:
            for conn in self._opened:
                try:
                    conn.close()
                except sqlite3.Error:
                    # Shutdown is not the place to raise about a connection
                    # that is already gone.
                    pass
            self._opened.clear()
        self._local = threading.local()

    # -- principals and keys ------------------------------------------------

    def add_principal(self, principal_id: str, kind: str = "service") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO principals (id, kind, created) VALUES (?,?,?)",
            (principal_id, kind, _now()),
        )
        self.conn.commit()

    def issue_key(self, principal_id: str, label: str | None = None, *,
                  expires_in_days: float | None = None,
                  kind: str = "api") -> str:
        """Mint an API key. The plaintext is returned ONCE and never stored."""
        self.add_principal(principal_id)
        key = f"mk_{secrets.token_urlsafe(32)}"
        expires = (_in_hours(expires_in_days * 24)
                   if expires_in_days else None)
        self.conn.execute(
            "INSERT INTO api_keys (key_hash, principal, label, created, prefix, "
            "kind, expires_at) VALUES (?,?,?,?,?,?,?)",
            (hash_key(key), principal_id, label, _now(), key[:9], kind, expires),
        )
        self.conn.commit()
        return key

    def authenticate(self, key: str | None) -> str | None:
        """API key -> principal id, or None.

        Lookup is by digest, so a stolen registry file yields no usable keys.
        Revoked and expired keys fail here rather than at some later gate:
        this is the single place every surface passes through, and a
        lifecycle enforced anywhere else is a lifecycle with a bypass.
        """
        if not key:
            return None
        row = self.conn.execute(
            "SELECT principal, revoked_at, expires_at FROM api_keys "
            "WHERE key_hash = ?", (hash_key(key),)
        ).fetchone()
        if row is None or row["revoked_at"]:
            return None
        if row["expires_at"] and row["expires_at"] <= _now():
            return None
        # Last use is what makes an unused token safe to remove. Written on
        # every call, so it is second-resolution and best-effort, not an
        # audit record — the audit log is next door and keeps the detail.
        self.conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (_now(), hash_key(key)))
        self.conn.commit()
        return row["principal"]

    def keys_of(self, principals: list[str] | None = None) -> list[dict]:
        """Token metadata — never the secret, which exists only in the reply
        to the call that minted it. Sessions are excluded: they are the
        by-product of a login, not a credential anyone manages (J.2.2)."""
        sql = ("SELECT key_hash, principal, label, created, prefix, expires_at, "
               "revoked_at, last_used_at FROM api_keys WHERE kind = 'api'")
        args: tuple = ()
        if principals is not None:
            if not principals:
                return []
            sql += f" AND principal IN ({','.join('?' * len(principals))})"
            args = tuple(principals)
        rows = self.conn.execute(sql + " ORDER BY created DESC", args)
        now = _now()
        out = []
        for r in rows:
            item = dict(r)
            # The digest is the handle for revocation. It is not a secret —
            # it is what a stolen registry already contains — but the key it
            # came from cannot be derived from it.
            item["id"] = item.pop("key_hash")
            item["status"] = ("revoked" if r["revoked_at"]
                              else "expired" if r["expires_at"] and r["expires_at"] <= now
                              else "active")
            out.append(item)
        return out

    def owner_of_key(self, key_id: str) -> str | None:
        """Whose token is this? Separate from `revoke_key` so a caller can
        authorize before acting rather than after."""
        row = self.conn.execute(
            "SELECT principal FROM api_keys WHERE key_hash = ?", (key_id,)).fetchone()
        return row["principal"] if row else None

    def revoke_key(self, key_id: str) -> str | None:
        """Revoke by digest. Returns the principal it belonged to, or None."""
        owner = self.owner_of_key(key_id)
        if owner is None:
            return None
        self.conn.execute("UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
                          (_now(), key_id))
        self.conn.commit()
        return owner

    # -- passwords (J.2.1) ---------------------------------------------------

    def set_password(self, principal_id: str, password: str | None) -> None:
        """Set or clear a principal's password. Clearing removes the door
        entirely rather than leaving a blank one behind."""
        self.add_principal(principal_id, kind="user")
        if not password:
            self.conn.execute(
                "UPDATE principals SET pw_salt = NULL, pw_hash = NULL WHERE id = ?",
                (principal_id,))
        else:
            salt = secrets.token_bytes(16).hex()
            self.conn.execute(
                "UPDATE principals SET pw_salt = ?, pw_hash = ? WHERE id = ?",
                (salt, hash_password(password, salt), principal_id))
        self.conn.commit()

    def has_any_password(self) -> bool:
        """Whether the password door is worth offering at all."""
        return bool(self.conn.execute(
            "SELECT 1 FROM principals WHERE pw_hash IS NOT NULL LIMIT 1").fetchone())

    # -- the owner and first-run setup (J.2.4) -------------------------------

    def is_owner(self, principal_id: str) -> bool:
        row = self.conn.execute("SELECT owner FROM principals WHERE id = ?",
                                (principal_id,)).fetchone()
        return bool(row and row["owner"])

    def owner_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM principals WHERE owner = 1").fetchone()
        return row["id"] if row else None

    def _has_any_credential(self) -> bool:
        """Any way in that already exists: a password, or a key an operator
        holds. Sessions do not count — they are the by-product of a login
        (J.2.1), so a stale one must not be able to keep setup closed."""
        return bool(self.conn.execute(
            "SELECT 1 FROM principals WHERE pw_hash IS NOT NULL "
            "UNION ALL "
            "SELECT 1 FROM api_keys WHERE kind != 'session' LIMIT 1").fetchone())

    def setup_available(self) -> bool:
        """J.2.4: setup exists only while the registry holds no credential.

        The owner check is separate and deliberate: clearing every credential
        must NOT reopen setup once an owner exists, or removing a password
        would hand the deployment to whoever asked next.
        """
        return self.owner_id() is None and not self._has_any_credential()

    def create_owner(self, principal_id: str, password: str,
                     email: str | None = None) -> bool:
        """Create the one owner. Returns False if setup was already closed.

        The check and the write are one `BEGIN IMMEDIATE` transaction, so two
        concurrent first calls produce one owner and one refusal rather than
        two owners. `idx_single_owner` then makes that structural: even a
        caller that bypassed this method could not create a second one.
        """
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not self.setup_available():
                conn.rollback()
                return False
            salt = secrets.token_bytes(16).hex()
            conn.execute(
                "INSERT INTO principals (id, kind, created, pw_salt, pw_hash, "
                "owner, email) VALUES (?,?,?,?,?,1,?)",
                (principal_id, "user", _now(), salt,
                 hash_password(password, salt), (email or "").strip() or None))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Lost the race, or the id already exists. Both are "somebody got
            # here first", and both are the same answer to the caller.
            conn.rollback()
            return False
        except Exception:
            conn.rollback()
            raise

    def has_password(self, principal_id: str) -> bool:
        row = self.conn.execute("SELECT pw_hash FROM principals WHERE id = ?",
                                (principal_id,)).fetchone()
        return bool(row and row["pw_hash"])

    def verify_password(self, principal_id: str, password: str) -> bool:
        row = self.conn.execute(
            "SELECT pw_salt, pw_hash FROM principals WHERE id = ?",
            (principal_id,)).fetchone()
        if not row or not row["pw_hash"] or not password:
            return False
        return secrets.compare_digest(
            hash_password(password, row["pw_salt"]), row["pw_hash"])

    def open_session(self, principal_id: str, hours: float = SESSION_HOURS) -> dict:
        key = self.issue_key(principal_id, label="session", kind="session")
        self.conn.execute(
            "UPDATE api_keys SET expires_at = ? WHERE key_hash = ?",
            (_in_hours(hours), hash_key(key)))
        self.conn.commit()
        return {"key": key, "principal": principal_id,
                "expires_at": _in_hours(hours)}

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
        """Deny-by-default (J.3): no grant means no access.

        The owner (J.2.4) is the one exception, and it is resolved *here*
        rather than at the call sites, because "every forest present and
        future" is a statement about policy resolution and there is no grant
        row to read. Every consumer — primitives, scoping, the console
        projections — inherits it, so none of them can forget it.
        """
        if self.is_owner(principal_id):
            return Policy(forest=forest, caps=frozenset(CAPS),
                          allow=("",), deny=(), tables={})
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
            "SELECT p.id, p.kind, p.created, p.pw_hash IS NOT NULL AS has_password, "
            "  (SELECT COUNT(*) FROM api_keys k WHERE k.principal = p.id "
            "     AND k.kind = 'api' AND k.revoked_at IS NULL) AS keys, "
            "  (SELECT COUNT(*) FROM grants g WHERE g.principal = p.id) AS grants "
            "FROM principals p ORDER BY p.id"
        )
        return [{**dict(r), "has_password": bool(r["has_password"])} for r in rows]

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

    # -- per-forest settings -------------------------------------------------

    def setting(self, forest: str, key: str, default=None):
        row = self.conn.execute(
            "SELECT value FROM forest_settings WHERE forest = ? AND key = ?",
            (forest, key)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set_setting(self, forest: str, key: str, value) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO forest_settings (forest, key, value) VALUES (?,?,?)",
            (forest, key, json.dumps(value)))
        self.conn.commit()

    # -- inference providers and per-forest model bindings (J.10) -----------

    def adopt_env_providers(self, declared: list[dict]) -> None:
        """Publish the deployment's own providers (J.10.1).

        A Station whose endpoint and key already live in the environment
        should not ask an operator to paste that key into a form — they would
        be copying a secret from the place that governs it into a place that
        does not. So the row is published here with `api_key` NULL; the key
        stays in this process's memory and is overlaid on read. Rotating it
        means editing the environment and restarting, which is the same
        lifecycle the variable already had.

        A provider that WAS declared and no longer is becomes an ordinary
        console row rather than disappearing: dropping it would silently take
        its bindings with it, and a binding that vanished because a variable
        was renamed is the kind of failure nobody traces back.
        """
        names = set()
        for entry in declared:
            name, endpoint = entry.get("name"), entry.get("endpoint")
            if not name or not endpoint:
                continue
            names.add(name)
            # Upsert, not REPLACE: a declaration that lands on a name somebody
            # already typed takes the name over, but must not destroy the key
            # stored under it. The environment's key wins while it is declared
            # (see `provider_secret`), and withdrawing the variables leaves a
            # console provider that still works.
            self.conn.execute(
                "INSERT INTO providers (name, endpoint, api_key, created, origin) "
                "VALUES (?,?,NULL,?,'env') "
                "ON CONFLICT(name) DO UPDATE SET endpoint = excluded.endpoint, "
                "origin = 'env'",
                (name, endpoint.rstrip("/"), _now()),
            )
            if entry.get("api_key"):
                self._env_secrets[name] = entry["api_key"]
            else:
                self._env_secrets.pop(name, None)
        stale = [r["name"] for r in
                 self.conn.execute("SELECT name FROM providers WHERE origin = 'env'")
                 if r["name"] not in names]
        for name in stale:
            self.conn.execute(
                "UPDATE providers SET origin = 'console' WHERE name = ?", (name,))
            self._env_secrets.pop(name, None)
        self.conn.commit()

    def _origin(self, name: str) -> str | None:
        row = self.conn.execute(
            "SELECT origin FROM providers WHERE name = ?", (name,)).fetchone()
        return row["origin"] if row else None

    def put_provider(self, name: str, endpoint: str, api_key: str | None) -> None:
        """Store a provider. An empty `api_key` keeps the stored one, so the
        console can edit an endpoint without ever holding the secret."""
        if not name or not endpoint:
            raise ValueError("provider needs a name and an endpoint")
        if self._origin(name) == "env":
            raise ValueError(f"'{name}' is declared by the environment; "
                             "edit the variables and restart the Station")
        existing = self.conn.execute(
            "SELECT api_key FROM providers WHERE name = ?", (name,)
        ).fetchone()
        key = api_key if api_key else (existing["api_key"] if existing else None)
        self.conn.execute(
            "INSERT OR REPLACE INTO providers (name, endpoint, api_key, created, origin) "
            "VALUES (?,?,?,?,'console')",
            (name, endpoint.rstrip("/"), key, _now()),
        )
        self.conn.commit()

    def delete_provider(self, name: str) -> None:
        if self._origin(name) == "env":
            raise ValueError(f"'{name}' is declared by the environment; "
                             "unset the variables and restart the Station")
        self.conn.execute("DELETE FROM providers WHERE name = ?", (name,))
        self.conn.execute("DELETE FROM model_bindings WHERE provider = ?", (name,))
        self.conn.commit()

    def providers(self) -> list[dict]:
        """Never returns secrets — only whether one is set."""
        return [
            {"name": r["name"], "endpoint": r["endpoint"],
             "has_key": bool(r["api_key"] or self._env_secrets.get(r["name"])),
             "origin": r["origin"], "created": r["created"]}
            for r in self.conn.execute("SELECT * FROM providers ORDER BY name")
        ]

    def provider_secret(self, name: str) -> dict | None:
        """Server-side only: the one path that reads the key back."""
        row = self.conn.execute(
            "SELECT name, endpoint, api_key, origin FROM providers WHERE name = ?",
            (name,)
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        if out["origin"] == "env":
            out["api_key"] = self._env_secrets.get(name)
        return out

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

    def mint_bootstrap_key(self, principal_id: str = "admin") -> str | None:
        """J.2.5: the first key, minted only when an operator asks for it.

        Returns the plaintext key, or None when there was no window to spend.
        A registry that already holds a credential — or an owner — has a way
        in already, and MUST NOT grow a second full-authority one by being
        restarted with a flag; that is what `station key` and the People
        console are for, and both require somebody who is already inside.

        The principal takes the **owner bit**, for J.2.4's reason: authority
        that has to create the first forest cannot be derived from a forest.
        Until v0.28 this minted a key granted per forest, which on a fresh
        volume summed to no authority at all — the v0.25 deadlock, still
        open in the one door nobody had walked through.

        Check and write are one `BEGIN IMMEDIATE`, as in `create_owner`:
        this spends the very same one-shot window the setup route does, so
        it is held to the same atomicity.
        """
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not self.setup_available():
                conn.rollback()
                return None
            key = f"mk_{secrets.token_urlsafe(32)}"
            conn.execute(
                "INSERT OR IGNORE INTO principals (id, kind, created) "
                "VALUES (?,?,?)", (principal_id, "user", _now()))
            conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                         (principal_id,))
            conn.execute(
                "INSERT INTO api_keys (key_hash, principal, label, created, "
                "prefix, kind) VALUES (?,?,?,?,?,?)",
                (hash_key(key), principal_id, "bootstrap", _now(),
                 key[:9], "api"))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return key

    def ensure_super_admin(self, principal_id: str, forests: list[str]) -> None:
        """The environment account (J.2.1): break-glass, **no stored
        credential**, and the owner bit when the seat is free.

        Its password is checked against the environment at login, so nothing
        here is secret — this only makes sure the identity exists and can
        govern. Taking the owner bit is what lets it reach a registry with no
        forest at all; before v0.25 it was granted per forest, and on an empty
        volume that summed to no authority whatsoever (J.2.4).

        If somebody else already owns the deployment, the bit is not stolen:
        the account falls back to explicit grants, so break-glass still opens
        every existing forest without demoting the real owner.
        """
        self.add_principal(principal_id, kind="user")
        owner = self.owner_id()
        if owner is None or owner == principal_id:
            self.conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                              (principal_id,))
            self.conn.commit()
            return
        for forest in forests:
            self.grant(principal_id, forest, set(CAPS))
