# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Webhooks (spec J.16): the outbound half of the host layer.

Everything else in Part J is pull — a principal arrives, is scoped, and
reads. This is the one surface that speaks first: the Station POSTs a
small, signed notification to an address the operator registered, when a
named event happens.

One fact shapes the whole module. **A delivery leaves the Station's
authority behind** (J.16.1). Inside, a read is scoped by J.3, bounded by a
token budget and recorded by J.4; the moment bytes reach a URL, whoever
holds that URL reads them under no scope at all, and a grant revoked
afterwards reaches none of it. So a body carries what an audit row carries
— what happened, to what, by whom, when — and never content. The receiver
that wants more comes back through the API holding its own credential.

Thread shape: `emit` is called from the forest lanes (J.9) and from the
event loop, and must be cheap and non-blocking on both — the primitive has
returned before any socket opens. It enqueues; ONE worker thread owns the
schedule, the retries and the HTTP. The subscription index lives in memory
because `emit` runs on the path of every write, and a registry read per
call to answer "nobody is listening" would tax the hot path for nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import heapq
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("monkeyllm_station.webhooks")

# The deployment scope, spelled as J.4.1's no-forest placeholder so a
# webhook row and a governance audit row agree about what "belongs to no
# forest" looks like.
DEPLOYMENT = "-"

# J.16.3: closed, served, and only events the Station can actually emit. A
# catalogue entry that never fires is worse than an absent one — it is a
# subscription that reads as coverage.
#
# `scope` is a CEILING, not a filter (J.16.2): a forest webhook may not
# subscribe to a deployment event however its list is written.
CATALOGUE: tuple[dict, ...] = (
    # -- content: the forest changed -------------------------------------
    {"event": "node.planted", "scope": "forest", "group": "content"},
    {"event": "node.grafted", "scope": "forest", "group": "content"},
    {"event": "branch.created", "scope": "forest", "group": "content"},
    {"event": "dataset.created", "scope": "forest", "group": "content"},
    {"event": "dataset.changed", "scope": "forest", "group": "content"},
    # -- ingest: a batch moved (J.9 / G.10) ------------------------------
    {"event": "ingest.started", "scope": "forest", "group": "ingest"},
    {"event": "ingest.finished", "scope": "forest", "group": "ingest"},
    {"event": "ingest.failed", "scope": "forest", "group": "ingest"},
    {"event": "ingest.cancelled", "scope": "forest", "group": "ingest"},
    {"event": "ingest.document.failed", "scope": "forest", "group": "ingest"},
    # -- answer: what the forest was asked to do (J.10) ------------------
    {"event": "answer.served", "scope": "forest", "group": "answer"},
    {"event": "answer.failed", "scope": "forest", "group": "answer"},
    # -- access: who was let in, and who was not -------------------------
    {"event": "access.denied", "scope": "forest", "group": "access"},
    {"event": "grant.changed", "scope": "forest", "group": "access"},
    {"event": "model.bound", "scope": "forest", "group": "access"},
    # -- maintenance: the derived layer (Part H / J.13) ------------------
    {"event": "snapshot.created", "scope": "forest", "group": "maintenance"},
    {"event": "canopy.built", "scope": "forest", "group": "maintenance"},
    {"event": "reindex.finished", "scope": "forest", "group": "maintenance"},
    # -- deployment: belongs to no forest, so J.4.1 rule 3 decides -------
    {"event": "auth.login.succeeded", "scope": "deployment", "group": "access"},
    {"event": "auth.login.failed", "scope": "deployment", "group": "access"},
    {"event": "pair.issued", "scope": "deployment", "group": "access"},
    {"event": "key.issued", "scope": "deployment", "group": "access"},
    {"event": "key.revoked", "scope": "deployment", "group": "access"},
    {"event": "provider.changed", "scope": "deployment", "group": "config"},
    {"event": "forest.created", "scope": "deployment", "group": "config"},
)

EVENTS = {entry["event"]: entry for entry in CATALOGUE}
FOREST_EVENTS = frozenset(e for e, v in EVENTS.items() if v["scope"] == "forest")
DEPLOYMENT_EVENTS = frozenset(e for e, v in EVENTS.items() if v["scope"] == "deployment")
GROUPS = ("content", "ingest", "answer", "access", "config", "maintenance")

# Not subscribable (J.16.3): it is what the console's test button sends, so
# "does this address work" is answered without waiting for a real event and
# without a real event's data.
TEST_EVENT = "webhook.test"

# -- delivery discipline (J.16.4) -----------------------------------------

TIMEOUT_SECONDS = 10.0
# Attempt 1 goes out at once; the rest are the backoff. Bounded and it
# stops: a webhook is best-effort notification, never a queue with a
# guarantee — what happened is in the audit table and in git.
BACKOFF_SECONDS = (5.0, 30.0, 120.0, 600.0)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
# Consecutive *deliveries* (not attempts) that exhausted their retries
# before the webhook is suspended. An endpoint answering 500 for a week is
# not a subscription, it is a retry loop nobody is watching.
SUSPEND_AFTER = 10
# Bounded, and it says so: overflow drops the oldest and counts it, because
# a silent drop reads as an integration that works.
QUEUE_MAX = 1000
# Per webhook. One row per ATTEMPT, so a delivery that retried four times
# is four rows sharing one delivery id.
KEEP_DELIVERIES = 100
# The receiver's own text, kept because it is what makes a broken
# integration debuggable — and clipped because a proxy answering with an
# HTML error page would otherwise be stored whole, once per attempt.
RESPONSE_CLIP = 500

# J.16.4: bounded, never overriding the framing or the signed set.
MAX_HEADERS = 5
RESERVED_HEADERS = frozenset({
    "host", "content-length", "content-type", "connection",
    "transfer-encoding", "user-agent",
})
HEADER_PREFIX = "x-monkeyllm-"

SUSPENDED_FAILING = "failing"
SUSPENDED_AUTHORITY = "authority"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over `<timestamp>.<body>` (J.16.4).

    The timestamp is INSIDE the signed string, so a body captured off the
    wire cannot be replayed as a fresh event — a signature over the body
    alone stays valid forever, which is exactly the property an attacker
    needs.
    """
    mac = hmac.new(secret.encode("utf-8"),
                   timestamp.encode("ascii") + b"." + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def scope_of(event: str) -> str | None:
    entry = EVENTS.get(event)
    return entry["scope"] if entry else None


def allowed_events(scope: str) -> frozenset[str]:
    """What a webhook in this scope may subscribe to.

    A ceiling, not a filter (J.16.2). The deployment scope hears every
    forest's events too, because whoever governs the deployment
    administers every forest there is — so narrowing it would hide
    nothing from anybody.
    """
    return (FOREST_EVENTS | DEPLOYMENT_EVENTS if scope == DEPLOYMENT
            else FOREST_EVENTS)


def catalogue(scope: str | None = None) -> list[dict]:
    """The served catalogue (J.16.3), optionally as one scope may see it."""
    allow = allowed_events(scope) if scope else set(EVENTS)
    return [dict(entry) for entry in CATALOGUE if entry["event"] in allow]


class _Task:
    """One attempt waiting to go out. The BODY is fixed at enqueue time and
    never rebuilt (J.16.4): identical bytes on every retry, so the
    signature is stable and a receiver deduplicating by `id` sees one
    event. What changed between attempts travels in the headers."""

    __slots__ = ("webhook", "delivery", "event", "body", "attempt", "due")

    def __init__(self, webhook: str, delivery: str, event: str, body: bytes,
                 attempt: int, due: float):
        self.webhook = webhook
        self.delivery = delivery
        self.event = event
        self.body = body
        self.attempt = attempt
        self.due = due


class Dispatcher:
    """The worker that owns every outbound request.

    `registry` supplies the rows; `authority(owner, scope) -> bool` is the
    host's own reach test, injected rather than reimplemented — it is
    `is_admin` and `governs_deployment`, and a second copy of either would
    agree with the original only where somebody compared them.
    """

    def __init__(self, registry, authority, *, audit=None,
                 client_factory=None):
        self._registry = registry
        self._authority = authority
        self._audit = audit
        self._client_factory = client_factory
        self._client = None

        self._heap: list[tuple[float, int, _Task]] = []
        self._seq = 0
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._running = False
        self.dropped = 0

        # The subscription index: {(scope, event)} for enabled, unsuspended
        # webhooks. `emit` consults this and nothing else, which is what
        # makes "nobody is listening" free on the path of every write.
        self._index: set[tuple[str, str]] = set()
        self._index_lock = threading.Lock()
        self.refresh()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="webhooks",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 — shutdown is not a place to raise
                pass
            self._client = None

    # -- the index ---------------------------------------------------------

    def refresh(self) -> None:
        """Re-read which (scope, event) pairs have a live subscriber.

        Called whenever a webhook is written. Cheap enough to be
        unconditional and rare enough not to matter: webhooks change when
        an operator edits one.
        """
        index: set[tuple[str, str]] = set()
        try:
            for hook in self._registry.webhooks():
                if not hook["enabled"] or hook["suspended"]:
                    continue
                for event in hook["events"]:
                    index.add((hook["scope"], event))
        except Exception:  # noqa: BLE001 — a broken index must not break writes
            log.warning("could not refresh the webhook index", exc_info=True)
            return
        with self._index_lock:
            self._index = index

    def _subscribed(self, forest: str, event: str) -> bool:
        with self._index_lock:
            return ((forest, event) in self._index
                    or (DEPLOYMENT, event) in self._index)

    # -- emission ----------------------------------------------------------

    def emit(self, forest: str, event: str, principal: str,
             data: dict | None = None, metadata: dict | None = None) -> None:
        """Announce that something happened. Never blocks, never raises.

        Runs on forest lanes and on the event loop alike, so it does the
        least it can: one set lookup, and — only when somebody is
        listening — the registry read that resolves which webhooks those
        are. `metadata` is J.16.1's opt-in material (`title`, `summary`),
        merged per webhook: it is what the ACT already knew, never
        something this call goes and reads.
        """
        try:
            if not self._subscribed(forest, event):
                return
            self._enqueue(forest, event, principal, data or {}, metadata or {})
        except Exception:  # noqa: BLE001 — J.16.4: never fail the act
            log.warning("could not emit %s on %s", event, forest, exc_info=True)

    def _enqueue(self, forest: str, event: str, principal: str,
                 data: dict, metadata: dict) -> None:
        node = data.get("node")
        at = now_iso()
        for hook in self._registry.webhooks():
            if not hook["enabled"] or hook["suspended"]:
                continue
            if event not in hook["events"]:
                continue
            if hook["scope"] not in (forest, DEPLOYMENT):
                continue
            # A branch filter narrows the events that name a node and says
            # nothing about the ones that do not — a webhook watching
            # `projects/` still wants to hear that the model binding moved.
            if node and hook["branches"] and not any(
                    str(node).startswith(prefix) for prefix in hook["branches"]):
                continue
            body = self._body(hook, forest, event, principal, at, data, metadata)
            self._schedule(_Task(hook["id"], body["id"], event,
                                 json.dumps(body, default=str,
                                            separators=(",", ":")).encode("utf-8"),
                                 1, time.monotonic()))

    def _body(self, hook: dict, forest: str, event: str, principal: str,
              at: str, data: dict, metadata: dict) -> dict:
        payload = dict(data)
        if hook["include_metadata"]:
            # Only what the act already knew (J.16.1 rule 3). An absent
            # title is absent, never fetched.
            payload.update({k: v for k, v in metadata.items() if v is not None})
        return {
            "id": f"whd-{secrets.token_hex(6)}",
            "event": event,
            "forest": forest,
            "at": at,
            "principal": principal,
            "data": payload,
        }

    def _schedule(self, task: _Task) -> None:
        with self._cond:
            if len(self._heap) >= QUEUE_MAX:
                # Drop the oldest and COUNT it. The count is reported to the
                # console; a queue that quietly forgot would look like an
                # integration that works.
                heapq.heappop(self._heap)
                self.dropped += 1
            self._seq += 1
            heapq.heappush(self._heap, (task.due, self._seq, task))
            self._cond.notify()

    def pending(self) -> int:
        with self._cond:
            return len(self._heap)

    # -- the worker --------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._running:
                    return
                if not self._heap:
                    self._cond.wait(timeout=30.0)
                    continue
                due, _, task = self._heap[0]
                wait = due - time.monotonic()
                if wait > 0:
                    self._cond.wait(timeout=min(wait, 30.0))
                    continue
                heapq.heappop(self._heap)
            try:
                self._attempt(task)
            except Exception:  # noqa: BLE001 — one bad delivery, not the thread
                log.warning("webhook delivery %s failed hard", task.delivery,
                            exc_info=True)

    def _attempt(self, task: _Task) -> None:
        hook = self._registry.webhook(task.webhook)
        if hook is None or not hook["enabled"]:
            return
        # J.16.2: authority is re-read at DELIVERY. A webhook created while
        # its owner governed the deployment must not keep firing after a
        # second forest narrowed that authority — v0.50's rule reaches
        # standing instructions too.
        if not self._authority(hook["owner"], hook["scope"]):
            self._suspend(hook, SUSPENDED_AUTHORITY)
            return
        record = self.send(hook, task.event, task.body, task.delivery,
                           task.attempt)
        if record["ok"]:
            self._registry.set_webhook_state(hook["id"], fail_streak=0,
                                             suspended=None,
                                             last_status=record.get("status"),
                                             last_at=record["ts"])
            return
        if task.attempt < MAX_ATTEMPTS:
            delay = BACKOFF_SECONDS[task.attempt - 1]
            task.attempt += 1
            task.due = time.monotonic() + delay
            self._schedule(task)
            return
        # Retries exhausted: this delivery is lost, and the streak decides
        # whether the webhook itself is.
        streak = int(hook["fail_streak"]) + 1
        self._registry.set_webhook_state(hook["id"], fail_streak=streak,
                                         last_status=record.get("status"),
                                         last_at=record["ts"])
        if streak >= SUSPEND_AFTER:
            self._suspend(hook, SUSPENDED_FAILING)

    def _suspend(self, hook: dict, reason: str) -> None:
        self._registry.set_webhook_state(hook["id"], suspended=reason)
        self.refresh()
        if self._audit:
            self._audit(hook, "suspended", {"reason": reason})

    # -- the request itself ------------------------------------------------

    def _http(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                import httpx

                self._client = httpx.Client(timeout=TIMEOUT_SECONDS,
                                            follow_redirects=False)
        return self._client

    def send(self, hook: dict, event: str, body: bytes, delivery: str,
             attempt: int) -> dict:
        """One HTTP attempt, recorded whatever it does.

        Redirects are NOT followed: a 302 is the destination naming a
        second address the operator never registered and J.16.4 never
        validated, which is the request-forgery hole the URL check exists
        to close.
        """
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MonkeyLLM-Station/webhooks",
            "X-MonkeyLLM-Event": event,
            "X-MonkeyLLM-Delivery": delivery,
            "X-MonkeyLLM-Attempt": str(attempt),
            "X-MonkeyLLM-Forest": hook["scope"],
            "X-MonkeyLLM-Timestamp": timestamp,
            "X-MonkeyLLM-Signature": sign(hook["secret"], timestamp, body),
        }
        # The operator's own headers go on last but cannot take a name the
        # framing or the signature owns — `put_webhook` refuses those, and
        # this is the second lock on the same door.
        for name, value in (hook["headers"] or {}).items():
            if name.lower() in RESERVED_HEADERS:
                continue
            if name.lower().startswith(HEADER_PREFIX):
                continue
            headers[name] = value

        started = time.perf_counter()
        status: int | None = None
        error: str | None = None
        response = ""
        try:
            reply = self._http().post(hook["url"], content=body, headers=headers)
            status = reply.status_code
            response = (reply.text or "")[:RESPONSE_CLIP]
        except Exception as e:  # noqa: BLE001 — every failure is a record
            error = f"{type(e).__name__}: {e}"[:RESPONSE_CLIP]
        ms = round((time.perf_counter() - started) * 1000, 1)
        ok = status is not None and 200 <= status < 300
        record = {
            "webhook": hook["id"], "delivery": delivery, "event": event,
            "attempt": attempt, "ts": now_iso(), "status": status,
            "ms": ms, "error": error, "response": response, "ok": ok,
        }
        try:
            self._registry.record_delivery(
                webhook=hook["id"], delivery=delivery, event=event,
                attempt=attempt, ts=record["ts"], status=status, ms=ms,
                error=error, response=response, body=body.decode("utf-8"))
        except Exception:  # noqa: BLE001 — the log must not fail the delivery
            log.warning("could not record delivery %s", delivery, exc_info=True)
        return record

    # -- the console's two direct actions ----------------------------------

    def test(self, hook: dict) -> dict:
        """`webhook.test`, sent now, on the caller's thread.

        Synchronous on purpose: the operator is waiting, and a test whose
        answer arrived asynchronously would be a test of the queue rather
        than of the address (J.16.5).
        """
        body = json.dumps({
            "id": f"whd-{secrets.token_hex(6)}",
            "event": TEST_EVENT,
            "forest": hook["scope"],
            "at": now_iso(),
            "principal": hook["owner"],
            "data": {"webhook": hook["id"], "label": hook["label"] or ""},
        }, separators=(",", ":")).encode("utf-8")
        record = self.send(hook, TEST_EVENT, body,
                           f"whd-{secrets.token_hex(6)}", 1)
        # A test never suspends and never resumes: it says whether the
        # address answers, which is not the same question as whether the
        # subscription is healthy.
        return record

    def redeliver(self, hook: dict, delivery: dict) -> dict:
        """Re-send a recorded delivery, body unchanged (J.16.4).

        The signature is recomputed because its timestamp is, which is the
        point of the timestamp: a replay by the Station is a new request,
        not a captured one.
        """
        return self.send(hook, delivery["event"],
                         delivery["body"].encode("utf-8"),
                         delivery["delivery"], int(delivery["attempt"]) + 1)
