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
    last_used_at TEXT,
    -- J.2.6: the capability mask a paired key carries. JSON list, or NULL
    -- for an unmasked key. A mask is a filter over live authority, never a
    -- copy of it: the grants are read at the moment of use and intersected,
    -- so revoking a grant narrows every masked key immediately.
    caps         TEXT
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
    commit_sha TEXT,
    -- J.4.2 (v0.73). All nullable, all read as ABSENT rather than as zero:
    -- a row written by an older Station makes no claim about its cost, its
    -- refusal or its clock, and `0.0 ms` / `$0.00` are both claims.
    ms         REAL,      -- the engine's own span (the Part D slice)
    model_ms   REAL,      -- the provider round trip, when one ran
    error_code TEXT,      -- the envelope's code (C.12) — never its message
    usd        REAL,      -- what the provider's catalogue prices this at
    tokens     INTEGER,   -- prompt + completion, the provider's own count
    calls      INTEGER,   -- provider round trips inside this one call
    priced     INTEGER    -- 1 when a catalogue answered; 0 = tokens, no price
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_principal ON audit(principal);
-- The audit console filters by forest and reads its totals per forest
-- (J.4.3), and the scope rule turns every one of those into a forest
-- predicate — so this is the index the whole route rides on.
CREATE INDEX IF NOT EXISTS idx_audit_forest ON audit(forest, ts);

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
    max_tokens INTEGER NOT NULL DEFAULT 1500,
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
-- Webhooks (J.16): the outbound half. `scope` is a forest id, or '-' for
-- the deployment — the same no-forest placeholder a governance audit row
-- carries, so the two agree about what "belongs to no forest" looks like.
-- `owner` is the principal whose authority the webhook rides on: it is
-- re-read at every delivery, never only at creation (J.16.2), which is what
-- keeps a standing instruction from outliving the grant behind it.
CREATE TABLE IF NOT EXISTS webhooks (
    id               TEXT PRIMARY KEY,
    scope            TEXT NOT NULL,
    owner            TEXT NOT NULL,
    label            TEXT,
    url              TEXT NOT NULL,
    -- Shown once, at creation, and never read back over the API (J.16.4).
    secret           TEXT NOT NULL,
    events           TEXT NOT NULL,                 -- JSON list
    branches         TEXT NOT NULL DEFAULT '[]',    -- JSON list; [] = every node
    -- Write-only over the API, like a provider's key: the wire gets names.
    headers          TEXT NOT NULL DEFAULT '{}',    -- JSON map
    -- J.16.1's one opt-in: `title` and `summary` on events that name a
    -- node. Never a body, in any mode.
    include_metadata INTEGER NOT NULL DEFAULT 0,
    enabled          INTEGER NOT NULL DEFAULT 1,
    -- NULL, 'failing' or 'authority'. Suspended rather than deleted: the
    -- same fact delivered as silence reads as an integration that works.
    suspended        TEXT,
    fail_streak      INTEGER NOT NULL DEFAULT 0,
    created          TEXT NOT NULL,
    last_status      INTEGER,
    last_at          TEXT
);
-- One row per ATTEMPT, so a delivery that retried four times is four rows
-- sharing one `delivery` id and one body. `body` is kept because that is
-- what makes redelivery a re-send rather than a reconstruction (J.16.4).
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    webhook  TEXT NOT NULL,
    delivery TEXT NOT NULL,
    event    TEXT NOT NULL,
    attempt  INTEGER NOT NULL,
    ts       TEXT NOT NULL,
    status   INTEGER,
    ms       REAL,
    error    TEXT,
    response TEXT,
    body     TEXT NOT NULL
);
-- Just the webhook: SQLite will not index `rowid`, and it does not need
-- to — the rows come back newest-first by rowid, which is the order they
-- were inserted in.
CREATE INDEX IF NOT EXISTS idx_deliveries_hook
    ON webhook_deliveries(webhook);
-- J.17 (v0.56): a share is a key with one room — one node, read-only,
-- expiring, revocable. The token is stored HASHED exactly as API keys are;
-- the URL is the secret, shown once at creation and returned by nothing.
CREATE TABLE IF NOT EXISTS shares (
    id         TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    forest     TEXT NOT NULL,
    node       TEXT NOT NULL,
    issuer     TEXT NOT NULL,
    created    TEXT NOT NULL,
    expires    TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_shares_forest ON shares(forest);
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

# `vision` is the G.5.1 describer: it reads images at adopt/sync so `sniff`
# can find them; absent, the engine's stub still plants `media` nodes.
# `embed` is not a chat model: it builds the Canopy and points the
# Gauntlet (Part K). Absent, navigation is unchanged.
ROLES = ("ingest", "answer", "vision", "embed")

# One-time DATA repairs, applied in order and stamped in `PRAGMA
# user_version`. A repair that ran on every open would fight the operator:
# somebody who deliberately chooses the old value after the upgrade must keep
# it, and only a version stamp can tell that apart from a value nobody ever
# considered. Append a statement and the stamp follows; never edit one that
# has shipped, because a Station that already ran it will not run it again.
DATA_REPAIRS = (
    # v1 — J.10.8, measured. Every role shipped bound at `max_tokens` 600, and
    # for `answer` that is below the reply it has to carry: the final action of
    # a walk is a JSON object holding the answer text AND `answer_nodes`, so
    # the budget pays for the citation apparatus and not only for prose. On the
    # 18-question suite two answers were lost to it, both AFTER the model had
    # run the correct query and reached the correct node — and both scored as
    # WRONG ANSWERS rather than as truncation, which is what made the cause
    # invisible for so long. Only bindings still sitting on the shipped default
    # are moved; a deliberate 600 is byte-identical to it, which is exactly why
    # this runs once and never again.
    "UPDATE model_bindings SET max_tokens = 1500 "
    "WHERE role = 'answer' AND max_tokens = 600",
)

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
        "caps": "TEXT",
    },
    "providers": {"origin": "TEXT NOT NULL DEFAULT 'console'"},
    # J.4.2 (v0.73): the bill, the refusal and the clock. Nullable by
    # design — see the table above.
    "audit": {"ms": "REAL", "model_ms": "REAL", "error_code": "TEXT",
              "usd": "REAL", "tokens": "INTEGER", "calls": "INTEGER",
              "priced": "INTEGER"},
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
        self._repair()
        self.conn.commit()
        # Keys of environment-declared providers (J.10.1). In memory, for the
        # life of the process, and never written: the registry file is a
        # backup target and the environment is not.
        self._env_secrets: dict[str, str] = {}

    def _repair(self) -> None:
        """Apply the DATA_REPAIRS this database has not seen (see the tuple).

        A fresh registry runs them against empty tables — no-ops — and is
        stamped current, so a new Station never carries a repair forward.
        """
        done = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for statement in DATA_REPAIRS[done:]:
            self.conn.execute(statement)
        if done < len(DATA_REPAIRS):
            # PRAGMA takes no parameters; the value is our own constant.
            self.conn.execute(f"PRAGMA user_version = {len(DATA_REPAIRS)}")

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
                  kind: str = "api",
                  caps: set[str] | frozenset[str] | None = None) -> str:
        """Mint an API key. The plaintext is returned ONCE and never stored.

        `caps` is the J.2.6 capability mask: stored sorted so two masks that
        mean the same thing read the same in the table. None means unmasked
        — today's keys, byte-for-byte.
        """
        self.add_principal(principal_id)
        key = f"mk_{secrets.token_urlsafe(32)}"
        expires = (_in_hours(expires_in_days * 24)
                   if expires_in_days else None)
        self.conn.execute(
            "INSERT INTO api_keys (key_hash, principal, label, created, prefix, "
            "kind, expires_at, caps) VALUES (?,?,?,?,?,?,?,?)",
            (hash_key(key), principal_id, label, _now(), key[:9], kind, expires,
             json.dumps(sorted(caps)) if caps is not None else None),
        )
        self.conn.commit()
        return key

    def resolve_key(self, key: str | None) -> dict | None:
        """API key -> {"principal": id, "caps": frozenset | None}, or None.

        Lookup is by digest, so a stolen registry file yields no usable keys.
        Revoked and expired keys fail here rather than at some later gate:
        this is the single place every surface passes through, and a
        lifecycle enforced anywhere else is a lifecycle with a bypass —
        which is also why `authenticate` is a wrapper over this rather than
        a second copy of the checks.

        `caps` is the J.2.6 mask exactly as stored: None for an unmasked
        key, a frozenset for a paired one. The intersection with the live
        grants happens at the moment of use, never here — this method knows
        the credential, not the authority.
        """
        if not key:
            return None
        row = self.conn.execute(
            "SELECT principal, revoked_at, expires_at, caps FROM api_keys "
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
        return {"principal": row["principal"],
                "caps": frozenset(json.loads(row["caps"])) if row["caps"]
                else None}

    def authenticate(self, key: str | None) -> str | None:
        """API key -> principal id, or None. A thin wrapper over
        `resolve_key`, so the lifecycle stays enforced in one place."""
        resolved = self.resolve_key(key)
        return resolved["principal"] if resolved else None

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
               result: str, size: int = 0, commit_sha: str | None = None,
               ms: float | None = None, model_ms: float | None = None,
               error_code: str | None = None, cost: dict | None = None) -> None:
        """Access log. Arguments are digested, never stored verbatim: the log
        records who read what, not the content they read.

        `ms`, `model_ms`, `error_code` and `cost` are J.4.2 (v0.73). Every
        one of them is optional and stored as NULL when the caller does not
        have it, because "this Station did not measure it" and "it measured
        zero" are different statements and only one of them is usually true:
        a `look` calls no provider, and recording `$0.00` for it would put a
        price on the row that nobody quoted.

        `cost` is the shape J.10.2 already builds and the response already
        carries — never recomputed here, because an audit write must not be
        able to fail the act it describes.
        """
        digest = {}
        for key, value in (args or {}).items():
            text = str(value)
            digest[key] = text if len(text) <= 80 else f"<{len(text)} chars>"
        cost = cost or {}
        tokens = None
        if cost.get("prompt_tokens") is not None \
                or cost.get("completion_tokens") is not None:
            tokens = int(cost.get("prompt_tokens") or 0) \
                + int(cost.get("completion_tokens") or 0)
        self.conn.execute(
            "INSERT INTO audit (ts, principal, forest, primitive, args, result, "
            "  size, commit_sha, ms, model_ms, error_code, usd, tokens, calls, priced) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), principal, forest, primitive,
             json.dumps(digest, ensure_ascii=False), result, size, commit_sha,
             None if ms is None else round(float(ms), 3),
             None if model_ms is None else round(float(model_ms), 3),
             error_code or None,
             cost.get("usd"), tokens, cost.get("calls"),
             None if not cost else int(bool(cost.get("priced")))),
        )
        self.conn.commit()

    # The result values that ARE a refusal (J.4.3). Stated positively: a
    # primitive's envelope lands as 'error', a governance guard's as
    # 'refused', and the other values this table holds ('ok', 'cache', and
    # the outcomes of admin repairs like 'kept') are not refusals and must
    # not be counted as ones. `error_code` catches anything newer.
    REFUSED = ("error", "refused")

    def _audit_where(self, *, forests=None, principal=None, forest=None,
                     primitive=None, result=None, errors=False,
                     since=None, before=None) -> tuple[str, list]:
        """The J.4.3 filter, built once and read three ways.

        `forests` is the scope (J.3.2), and it is a different kind of
        argument from the rest: the others are what the caller asked for and
        this one is what they are allowed to ask about. `None` means no
        restriction; an EMPTY collection means this principal governs
        nothing, and it must match nothing rather than everything — the
        difference between "no filter" and "a filter that excludes all" is
        one `if` away from handing a stranger the whole log.

        `before` is already exclusive: the route expands an inclusive
        `until` to the day after it, exactly as C.13 does, so the comparison
        here stays a bare range over the indexed column.
        """
        where: list[str] = []
        params: list = []
        if forests is not None:
            names = sorted(set(forests))
            if not names:
                return " WHERE 1 = 0", []
            where.append(f"forest IN ({','.join('?' * len(names))})")
            params.extend(names)
        for column, value in (("principal", principal), ("forest", forest),
                              ("primitive", primitive), ("result", result)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        if errors:
            marks = ",".join("?" * len(self.REFUSED))
            where.append(f"(result IN ({marks}) OR error_code IS NOT NULL)")
            params.extend(self.REFUSED)
        if since:
            where.append("ts >= ?")
            params.append(since)
        if before:
            where.append("ts < ?")
            params.append(before)
        return (" WHERE " + " AND ".join(where)) if where else "", params

    def audit(self, limit: int = 100, **filters) -> list[dict]:
        """A page of the filtered log, newest first."""
        where, params = self._audit_where(**filters)
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM audit{where} ORDER BY ts DESC, rowid DESC LIMIT ?",
            [*params, limit])]

    def audit_totals(self, **filters) -> dict:
        """What the WHOLE filtered set adds up to (J.4.3).

        Computed here rather than over the returned page, which is the whole
        point: a count of the rows on screen is a fact about the page size.

        Spend and saving are separate sums over the same column, split by
        `result`: a store hit's `usd` is the cost that was NOT paid (J.4.2),
        and adding the two together would bill a deployment for the calls it
        avoided.
        """
        where, params = self._audit_where(**filters)
        marks = ",".join("?" * len(self.REFUSED))
        row = self.conn.execute(
            "SELECT COUNT(*) AS calls,"
            f" SUM(result IN ({marks}) OR error_code IS NOT NULL) AS errors,"
            " SUM(result = 'cache') AS cached,"
            " SUM(CASE WHEN result = 'cache' THEN 0 ELSE COALESCE(usd, 0) END) AS usd,"
            " SUM(CASE WHEN result = 'cache' THEN COALESCE(usd, 0) ELSE 0 END) AS usd_saved,"
            " SUM(CASE WHEN result = 'cache' THEN 0 ELSE COALESCE(tokens, 0) END) AS tokens,"
            # A row whose provider published no catalogue: it has tokens
            # and no price, and J.5.16 rule 4 needs to say so rather than
            # render it free. NULL `priced` is a row that called no
            # provider at all and SUM skips it, which is the wanted answer.
            " SUM(priced = 0) AS unpriced,"
            " COUNT(DISTINCT principal) AS people,"
            " MIN(ts) AS first, MAX(ts) AS last"
            f" FROM audit{where}", [*self.REFUSED, *params]).fetchone()
        out = {k: row[k] for k in row.keys()}
        for key in ("calls", "errors", "cached", "tokens", "unpriced",
                    "people"):
            out[key] = int(out[key] or 0)
        for key in ("usd", "usd_saved"):
            out[key] = round(float(out[key] or 0.0), 6)
        return out

    def audit_facets(self, *, forests=None, since=None, before=None,
                     cap: int = 200) -> dict:
        """The values the filters can actually take, over this caller's set.

        Narrowed by the scope and the window and by nothing else: choosing a
        primitive must not empty the list of primitives. A filter offering a
        value that returns nothing teaches an operator that the log is empty
        when it is the filter that is (J.4.3).
        """
        where, params = self._audit_where(forests=forests, since=since,
                                          before=before)
        out: dict[str, list[str]] = {}
        for key, column in (("principals", "principal"), ("forests", "forest"),
                            ("primitives", "primitive"),
                            ("codes", "error_code")):
            rows = self.conn.execute(
                f"SELECT DISTINCT {column} AS v FROM audit{where}"
                f" ORDER BY v LIMIT {int(cap)}", params)
            out[key] = [r["v"] for r in rows if r["v"]]
        return out

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
        """Store a provider. An empty `api_key` keeps the stored one *for the
        same endpoint*, so the console can edit other fields without ever
        holding the secret. A changed endpoint is a changed destination: the
        stored credential belongs to the address it was stored against, so it
        does not follow the endpoint — the key has to be supplied again."""
        if not name or not endpoint:
            raise ValueError("provider needs a name and an endpoint")
        if self._origin(name) == "env":
            raise ValueError(f"'{name}' is declared by the environment; "
                             "edit the variables and restart the Station")
        endpoint = endpoint.rstrip("/")
        existing = self.conn.execute(
            "SELECT endpoint, api_key FROM providers WHERE name = ?", (name,)
        ).fetchone()
        if existing and existing["endpoint"] != endpoint and not api_key:
            raise ValueError(
                "changing a provider's endpoint requires supplying its key "
                "again: a credential belongs to the address it was stored against")
        key = api_key if api_key else (existing["api_key"] if existing else None)
        self.conn.execute(
            "INSERT OR REPLACE INTO providers (name, endpoint, api_key, created, origin) "
            "VALUES (?,?,?,?,'console')",
            (name, endpoint, key, _now()),
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
                   max_tokens: int = 1500, reasoning: str = "off") -> None:
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

    # -- webhooks (J.16) ----------------------------------------------------

    def _webhook(self, row) -> dict:
        """One row, with its JSON columns decoded.

        The secret and the header VALUES are in here: this is the host's own
        storage and the dispatcher needs both. Stripping them for the wire is
        the API layer's job, in one place, so there is exactly one shaper to
        get right (J.16.4).
        """
        out = dict(row)
        out["events"] = json.loads(out["events"] or "[]")
        out["branches"] = json.loads(out["branches"] or "[]")
        out["headers"] = json.loads(out["headers"] or "{}")
        out["include_metadata"] = bool(out["include_metadata"])
        out["enabled"] = bool(out["enabled"])
        return out

    def webhooks(self, scopes: list[str] | None = None) -> list[dict]:
        sql = "SELECT * FROM webhooks"
        params: list = []
        if scopes is not None:
            if not scopes:
                return []
            sql += f" WHERE scope IN ({','.join('?' * len(scopes))})"
            params.extend(scopes)
        return [self._webhook(r) for r in
                self.conn.execute(sql + " ORDER BY created DESC", params)]

    def webhook(self, webhook_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM webhooks WHERE id = ?",
                                (webhook_id,)).fetchone()
        return self._webhook(row) if row else None

    def put_webhook(self, *, webhook_id: str | None, scope: str, owner: str,
                    url: str, events: list[str], label: str | None = None,
                    branches: list[str] | None = None,
                    headers: dict | None = None,
                    include_metadata: bool = False, enabled: bool = True,
                    secret: str | None = None) -> dict:
        """Create or replace one webhook.

        `secret` is written only when supplied — absent on an edit means
        "keep the one you have", which is what makes a shown-once secret
        survive every later change to the subscription (J.16.4). Editing
        also clears `suspended` and the streak: an operator who changed the
        address has answered the reason it was suspended for.
        """
        existing = self.webhook(webhook_id) if webhook_id else None
        if webhook_id and existing is None:
            raise ValueError(f"unknown webhook: {webhook_id}")
        wid = webhook_id or f"wh-{secrets.token_hex(5)}"
        if existing is None:
            self.conn.execute(
                "INSERT INTO webhooks (id, scope, owner, label, url, secret, "
                "events, branches, headers, include_metadata, enabled, created) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (wid, scope, owner, label, url, secret or "",
                 json.dumps(sorted(set(events))), json.dumps(branches or []),
                 json.dumps(headers or {}), int(bool(include_metadata)),
                 int(bool(enabled)), _now()))
        else:
            self.conn.execute(
                "UPDATE webhooks SET scope = ?, owner = ?, label = ?, url = ?, "
                "events = ?, branches = ?, headers = ?, include_metadata = ?, "
                "enabled = ?, suspended = NULL, fail_streak = 0"
                + (", secret = ?" if secret else "") + " WHERE id = ?",
                (scope, owner, label, url, json.dumps(sorted(set(events))),
                 json.dumps(branches or []), json.dumps(headers or {}),
                 int(bool(include_metadata)), int(bool(enabled)))
                + ((secret,) if secret else ()) + (wid,))
        self.conn.commit()
        return self.webhook(wid)

    def delete_webhook(self, webhook_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        self.conn.execute("DELETE FROM webhook_deliveries WHERE webhook = ?",
                          (webhook_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def set_webhook_state(self, webhook_id: str, **fields) -> None:
        """The dispatcher's write-back: streak, suspension, last outcome.

        Deliberately narrow. Everything an operator edits goes through
        `put_webhook`; this is the worker thread reporting what the world
        did, and it must not be able to change a subscription.
        """
        allowed = ("fail_streak", "suspended", "last_status", "last_at",
                   "enabled")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        assignments = ", ".join(f"{k} = ?" for k in sets)
        self.conn.execute(f"UPDATE webhooks SET {assignments} WHERE id = ?",
                          (*sets.values(), webhook_id))
        self.conn.commit()

    def record_delivery(self, *, webhook: str, delivery: str, event: str,
                        attempt: int, ts: str, status: int | None,
                        ms: float | None, error: str | None,
                        response: str | None, body: str,
                        keep: int = 100) -> None:
        """One attempt, kept. Bounded per webhook, the C.6 rule applied to a
        store: the oldest rows go rather than the file growing forever."""
        self.conn.execute(
            "INSERT INTO webhook_deliveries (webhook, delivery, event, attempt, "
            "ts, status, ms, error, response, body) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (webhook, delivery, event, int(attempt), ts, status, ms, error,
             response, body))
        self.conn.execute(
            "DELETE FROM webhook_deliveries WHERE webhook = ? AND rowid NOT IN "
            "(SELECT rowid FROM webhook_deliveries WHERE webhook = ? "
            " ORDER BY rowid DESC LIMIT ?)", (webhook, webhook, int(keep)))
        self.conn.commit()

    def deliveries(self, webhook: str, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM webhook_deliveries WHERE webhook = ? "
            "ORDER BY rowid DESC LIMIT ?", (webhook, int(limit)))]

    def delivery(self, webhook: str, delivery: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM webhook_deliveries WHERE webhook = ? AND delivery = ? "
            "ORDER BY rowid DESC LIMIT 1", (webhook, delivery)).fetchone()
        return dict(row) if row else None

    # -- shares (J.17) ------------------------------------------------------

    SHARE_DEFAULT_DAYS = 7
    SHARE_MAX_DAYS = 90

    def create_share(self, *, forest: str, node: str, issuer: str,
                     days: int | None = None) -> dict:
        """Mint a share: one node, read-only, expiring. The token is
        returned ONCE and stored hashed, exactly as API keys are (J.17
        rule 2); no later call can recover it."""
        days = self.SHARE_DEFAULT_DAYS if days is None else int(days)
        if not 1 <= days <= self.SHARE_MAX_DAYS:
            raise ValueError(f"days must be 1..{self.SHARE_MAX_DAYS}")
        token = secrets.token_hex(16)          # 128 bits — rule 2
        share_id = f"sh_{secrets.token_hex(6)}"
        expires = _in_hours(days * 24)
        self.conn.execute(
            "INSERT INTO shares (id, token_hash, forest, node, issuer, "
            "created, expires) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (share_id, hash_key(token), forest, node, issuer, _now(), expires))
        self.conn.commit()
        return {"id": share_id, "token": token, "expires": expires}

    def resolve_share(self, token: str | None) -> dict | None:
        """The LIVE share behind a token, or None. Revoked, expired and
        never-existed resolve identically (J.17 rule 3) — the caller adds
        the issuer-authority re-check, which this table cannot know."""
        if not token:
            return None
        row = self.conn.execute(
            "SELECT * FROM shares WHERE token_hash = ?",
            (hash_key(token),)).fetchone()
        if row is None or row["revoked_at"] or row["expires"] <= _now():
            return None
        return dict(row)

    def shares_of(self, forest: str, issuer: str | None = None) -> list[dict]:
        """Active shares of a forest — never the token, no endpoint returns
        it after creation (J.17 rule 5)."""
        sql = ("SELECT id, forest, node, issuer, created, expires FROM shares "
               "WHERE forest = ? AND revoked_at IS NULL AND expires > ?")
        params: list = [forest, _now()]
        if issuer is not None:
            sql += " AND issuer = ?"
            params.append(issuer)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY created DESC",
                                                   params)]

    def revoke_share(self, share_id: str, forest: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, node, issuer FROM shares WHERE id = ? AND forest = ? "
            "AND revoked_at IS NULL", (share_id, forest)).fetchone()
        if row is None:
            return None
        self.conn.execute("UPDATE shares SET revoked_at = ? WHERE id = ?",
                          (_now(), share_id))
        self.conn.commit()
        return dict(row)

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
