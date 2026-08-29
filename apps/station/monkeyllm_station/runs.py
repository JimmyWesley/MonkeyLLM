# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The progress of one answer, while it is still being answered (spec J.10.12).

A hosted `answer` learns everything early and discloses it late: the sweep's
bundle exists at millisecond 19 and leaves at second 10; a walk's third hop
is decided at second 22 and first seen at second 54, beside the second and
the fourth. This is the buffer that lets a caller watch instead of wait.

Three properties shape every method below, and all three are J.10.12's:

* **Emission never blocks the call** (rule 4). `publish` is called from a
  forest lane — a thread in an executor — while the consumer lives on the
  event loop. It appends under a plain lock, wakes the loop through
  `call_soon_threadsafe`, and returns. It never awaits, and a buffer that
  has filled DROPS rather than applies back-pressure: a hunt slowed down by
  somebody watching it is a hunt whose own measurements are now about the
  watching.
* **Nothing outlives its call** (rule 6). Records live here and nowhere
  else, like a J.9 job: a restart forgets records, never work. A stream for
  a finished run yields what it has and closes; a stream for a run that
  never existed closes at once, because a channel that hangs on a typo is
  indistinguishable from one whose call is merely slow.
* **A run is a rendezvous, not a name** (rule 5). The key carries the
  principal and the forest, so one caller's run id can never address
  another's, and the id itself names nothing in any forest.

What may go INTO an event is not this module's rule to keep — J.10.12 rule 2
binds it to what the completed response would have carried to this same
principal, and the caller is where that comparison is possible.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

# A walk is budgeted in hops and a sweep emits one retrieval, so a healthy
# run produces single digits of events. The cap is not a guess at that — it
# is the wall a consumer that stopped reading runs into, so the host's
# memory is bounded by the number of live runs rather than by their length.
MAX_EVENTS = 256

# How long a record may sit unread. Long enough for a walk that is still
# thinking (J.10.5 budgets six hops of provider time), short enough that a
# console left open overnight is not a leak.
TTL_SECONDS = 900

# The gap between heartbeats on an idle stream. A walk can spend half a
# minute inside one model turn, and a proxy that sees nothing for that long
# is entitled to assume the connection died.
HEARTBEAT_SECONDS = 15.0

# How long a channel waits for its call to claim the run.
#
# A watcher must be free to open the channel BEFORE firing the call — that
# is the only order in which nothing can be missed, and it is the order a
# console naturally takes, since awaiting the POST would mean awaiting the
# whole answer. So an unclaimed run is not yet an absent one. Bounded, and
# short: rule 6's point is that a channel must never hang on a typo, and
# three seconds is closing, not hanging.
CLAIM_GRACE_SECONDS = 3.0


@dataclass
class _Run:
    """One call's progress. Mutated from a lane thread, read from the loop."""

    events: list[dict] = field(default_factory=list)
    loop: asyncio.AbstractEventLoop | None = None
    waiter: asyncio.Event | None = None
    done: bool = False
    dropped: int = 0
    started: float = field(default_factory=time.monotonic)
    streaming: bool = False


class RunBoard:
    """Host-memory progress records, keyed by (principal, forest, run).

    The lock is a plain `threading.Lock` and not an asyncio one on purpose:
    the writer is a forest lane and the reader is the loop, which is exactly
    the case an asyncio primitive cannot serve.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str, str], _Run] = {}
        self._lock = threading.Lock()

    # -- the answering side (request coroutine, then a forest lane) ---------

    def claim(self, key: tuple[str, str, str]) -> bool:
        """Reserve a run id for one call. False if it is already live.

        Takes no loop: the loop belongs to whoever watches, and `stream` is
        the one method that certainly runs on it. A call nobody watches
        therefore never touches asyncio at all.
        """
        self._expire()
        with self._lock:
            held = self._runs.get(key)
            if held is not None and not held.done:
                return False
            self._runs[key] = _Run()
            return True

    def publish(self, key: tuple[str, str, str], kind: str, data) -> None:
        """Record one event and wake any consumer. Safe from any thread.

        Never raises: a progress channel that could fail an answer would be
        a spectator with a vote.
        """
        try:
            with self._lock:
                run = self._runs.get(key)
                if run is None or run.done:
                    return
                if len(run.events) >= MAX_EVENTS:
                    run.dropped += 1
                else:
                    run.events.append({"event": kind, "data": data})
                waiter, loop = run.waiter, run.loop
            self._wake(loop, waiter)
        except Exception:  # never the answer's problem
            pass

    def finish(self, key: tuple[str, str, str]) -> None:
        """The call is over. A consumer drains what is left and closes."""
        try:
            with self._lock:
                run = self._runs.get(key)
                if run is None:
                    return
                run.done = True
                waiter, loop = run.waiter, run.loop
            self._wake(loop, waiter)
        except Exception:
            pass

    @staticmethod
    def _wake(loop, waiter) -> None:
        if waiter is None or loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(waiter.set)
        except RuntimeError:  # loop shutting down
            pass

    # -- the watching side (event loop) ------------------------------------

    def live(self, key: tuple[str, str, str]) -> bool:
        with self._lock:
            run = self._runs.get(key)
            return run is not None and not run.done

    async def stream(self, key: tuple[str, str, str]):
        """Yield this run's events as they arrive, then stop.

        A run already finished ends with whatever it has, and one that never
        appears ends too — after `CLAIM_GRACE_SECONDS`, because a watcher is
        entitled to open the channel before firing the call and a race is not
        an absence. Bounded either way (rule 6): this closes, never hangs.

        A second consumer on a live run is refused the same way a second
        claim is: one call, one watcher, so neither can silently starve the
        other.
        """
        deadline = time.monotonic() + CLAIM_GRACE_SECONDS
        while True:
            with self._lock:
                run = self._runs.get(key)
            if run is not None or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
        with self._lock:
            run = self._runs.get(key)
            if run is None:
                return
            if run.streaming:
                return
            run.streaming = True
            if run.waiter is None:
                run.waiter = asyncio.Event()
            # Captured here, where there certainly IS one, so a lane thread
            # has somewhere to hand its events.
            run.loop = asyncio.get_running_loop()
            waiter = run.waiter

        sent = 0
        try:
            while True:
                with self._lock:
                    pending = run.events[sent:]
                    finished = run.done
                    dropped = run.dropped
                sent += len(pending)
                for event in pending:
                    yield event
                if finished:
                    if dropped:
                        # Rule 4: what a slow consumer missed is counted, not
                        # hidden. A gap nobody mentions reads as a hunt that
                        # simply did not do those steps.
                        yield {"event": "dropped", "data": {"count": dropped}}
                    yield {"event": "done", "data": {}}
                    return
                waiter.clear()
                try:
                    await asyncio.wait_for(waiter.wait(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": {}}
        finally:
            with self._lock:
                if key in self._runs:
                    self._runs[key].streaming = False

    # -- housekeeping ------------------------------------------------------

    def _expire(self) -> None:
        cutoff = time.monotonic() - TTL_SECONDS
        with self._lock:
            for key in [k for k, r in self._runs.items()
                        if r.started < cutoff and not r.streaming]:
                del self._runs[key]

    def drop(self, key: tuple[str, str, str]) -> None:
        with self._lock:
            self._runs.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._runs)
