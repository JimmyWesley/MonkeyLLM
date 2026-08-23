# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Ingest jobs (spec J.9): the host's memory of running batches.

A job is process state, never forest content — progress is not curated
material, the same boundary that keeps model runs in the browser (J.5.9).
Reading a job therefore touches no forest: no lane, no trace event, no
pheromone. A restart forgets these records; it cannot forget the work,
because the work is commits, and the recovery is `sync` (G.10 records the
source root before the first step).

Thread shape: a job is mutated by the driver (event loop) and by step
notes arriving from the forest lane, and read by any request thread. One
lock per board keeps every snapshot consistent; nothing here ever blocks
on forest work, which is what keeps watching free.
"""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone

# Job records kept per forest. Bounded and honest about it (J.9): the list
# answers `truncated: true` when the bound cut, the C.6 rule applied to a
# store instead of a response.
KEEP = 20


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class IngestJob:
    """One accepted batch: identity, progress, and — once finished — the
    unabridged result. `states`: running → done | error | cancelled."""

    def __init__(self, forest: str, mode: str, total: int, principal: str):
        self.id = f"ing-{secrets.token_hex(4)}"
        self.forest = forest
        # J.9 (v0.61): `mode` is the caller's own word and stays it. It used
        # to be rewritten to "sync" mid-call by the upload flip — a mode
        # that mirrors a host directory, which the caller never asked for.
        # The flip is gone (J.8), so there is one mode and it is this one.
        self.mode = mode
        self.principal = principal
        self.state = "running"
        self.done = 0
        self.total = total
        self.current: str | None = None
        # G.10.1: the phase of `current`. A batch of one document is
        # one step, so `done` alone stands at 0 until it is 1 — which
        # an operator cannot tell from a hang.
        self.stage: str | None = None
        self.errors = 0
        self.started = _now()
        self.finished: str | None = None
        self.report: dict | None = None
        self.error: dict | None = None
        self.cancel_requested = False
        # The driver task, so `wait: true` has something to await. Not part
        # of any snapshot.
        self.task = None

    def snapshot(self) -> dict:
        out = {
            "id": self.id, "forest": self.forest, "mode": self.mode,
            "state": self.state, "done": self.done, "total": self.total,
            "current": self.current, "stage": self.stage,
            "errors": self.errors,
            "started": self.started,
        }
        if self.finished:
            out["finished"] = self.finished
        if self.report is not None:
            out["report"] = self.report
        if self.error is not None:
            out["error"] = self.error
        return out


class JobBoard:
    """All jobs the Station remembers, per forest, under one lock."""

    def __init__(self, keep: int = KEEP):
        self._keep = keep
        self._jobs: dict[str, list[IngestJob]] = {}
        self._lock = threading.Lock()

    def claim(self, forest: str, mode: str, total: int,
              principal: str) -> IngestJob | None:
        """One batch per forest at a time (J.9): atomically start a job,
        or return None when one is already running — the caller answers
        E_LOCKED naming it (`running()` says which)."""
        with self._lock:
            jobs = self._jobs.setdefault(forest, [])
            if any(j.state == "running" for j in jobs):
                return None
            job = IngestJob(forest, mode, total, principal)
            jobs.insert(0, job)
            # Evict oldest finished records past the bound; the running job
            # is never a record to evict.
            done = [j for j in jobs if j.state != "running"]
            for old in done[self._keep:]:
                jobs.remove(old)
            return job

    def abandon(self, job: IngestJob) -> None:
        """A claim whose batch was refused after all (staging failed, the
        source escaped the roots): the caller got an error, not a job, and
        no record should say otherwise."""
        with self._lock:
            jobs = self._jobs.get(job.forest, [])
            if job in jobs:
                jobs.remove(job)

    def running(self, forest: str) -> IngestJob | None:
        with self._lock:
            return next((j for j in self._jobs.get(forest, [])
                         if j.state == "running"), None)

    def get(self, forest: str, job_id: str) -> IngestJob | None:
        with self._lock:
            return next((j for j in self._jobs.get(forest, [])
                         if j.id == job_id), None)

    def list(self, forest: str, limit: int = KEEP) -> tuple[list[dict], bool]:
        with self._lock:
            jobs = self._jobs.get(forest, [])
            return [j.snapshot() for j in jobs[:limit]], len(jobs) > limit

    def note_step(self, job: IngestJob, step: dict) -> None:
        """A G.10 step landed: advance the counters the console shows."""
        with self._lock:
            job.done = int(step.get("index") or job.done + 1)
            job.current = step.get("file")
            # The document is finished; its phase is not a thing any more.
            job.stage = None
            if step.get("action") == "error":
                job.errors += 1

    def note_stage(self, job: IngestJob, file: str, stage: str) -> None:
        """G.10.1: the Gardener named the phase it is in, mid-step.

        Called from the forest lane, never from the event loop, so it takes
        the board's lock like every other mutation. It reports; it never
        pauses the work, and a job already finished ignores it.
        """
        with self._lock:
            if job.state == "running":
                job.current = file
                job.stage = stage

    def finish(self, job: IngestJob, state: str, report: dict | None = None,
               error: dict | None = None) -> None:
        with self._lock:
            job.state = state
            job.finished = _now()
            job.current = None
            job.stage = None
            job.report = report
            job.error = error

    def cancel(self, job: IngestJob) -> None:
        """Ask; the driver answers at the next step boundary (J.9). On a
        job already finished this is a no-op, not an error — the intent
        (\"make it not run\") is already true."""
        with self._lock:
            if job.state == "running":
                job.cancel_requested = True
