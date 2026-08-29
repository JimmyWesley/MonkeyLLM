# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Telemetry (spec Part D): traces feed the pheromone and the Monkey Bench."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from monkeyllm.trails import Trails

HARVEST_PRIMITIVES = {"pick", "query"}
HOP_PRIMITIVES = {"look", "move"}


class Tracer:
    def __init__(self, derived_dir: Path, trails: Trails, session: str | None = None):
        self.session = session or uuid.uuid4().hex[:12]
        self.trails = trails
        self.traces_dir = derived_dir / "traces"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.traces_dir / f"{self.session}.jsonl"
        self.events: list[dict] = []
        self.closed = False

    def record(
        self,
        primitive: str,
        node_id: str | None,
        tokens_in: int,
        tokens_out: int,
        elapsed_ms: float,
        embed_ms: float | None = None,
        dense_ms: float | None = None,
    ) -> None:
        event = {
            "ts": time.time(),
            "session": self.session,
            "primitive": primitive,
            "id": node_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "elapsed_ms": round(elapsed_ms, 3),
        }
        if embed_ms is not None:
            # The K.2/K.6 query embed ran inside this call (v0.68): its
            # share of `elapsed_ms`, named so the embedder's round trip is
            # never read as the forest's own work.
            event["embed_ms"] = round(embed_ms, 3)
        if dense_ms is not None:
            # The Canopy scan's share (v0.71): local CPU over every node
            # vector, which is the OTHER half of a hybrid entry search and
            # the larger one whenever the query embed is a memo hit. Kept
            # apart from `embed_ms` because one is a provider and one is
            # this process, and an operator tuning the wrong one wastes a
            # week.
            event["dense_ms"] = round(dense_ms, 3)
        self.events.append(event)
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def metrics(self, answer_nodes: list[str] | None = None) -> dict:
        hops = 0
        hops_to_banana = None
        trail_len = None  # spec v0.6: read calls before the 1st answer harvest
        answers = set(answer_nodes or [])
        for i, ev in enumerate(self.events):
            if ev["primitive"] in HOP_PRIMITIVES:
                hops += 1
            elif ev["primitive"] in HARVEST_PRIMITIVES and hops_to_banana is None:
                hops_to_banana = hops
            if (trail_len is None and ev["primitive"] in HARVEST_PRIMITIVES
                    and ev["id"] in answers):
                trail_len = i
        return {
            "hops_to_banana": hops_to_banana,
            "trail_len": trail_len,
            "tokens_to_banana": sum(ev["tokens_out"] for ev in self.events),
            "calls": len(self.events),
            "answer_nodes": answer_nodes or [],
        }

    def close_session(
        self,
        success: bool,
        answer_nodes: list[str],
        trail_of: callable = None,
        shout_threshold: int = 4,
    ) -> dict:
        """Close the hunt (Part D). On success: whisper (heat on winning
        trail) and shout evaluation (spec v0.6: trail_len >= threshold —
        pick chains count, not just look/move)."""
        metrics = self.metrics(answer_nodes)
        suggest_shortcuts = []
        if success and answer_nodes:
            for nid in answer_nodes:
                trail = trail_of(nid) if trail_of else []
                self.trails.add_heat(trail + [nid], amount=0.1)
                if metrics["trail_len"] is not None and metrics["trail_len"] >= shout_threshold:
                    suggest_shortcuts.append(nid)
        outcome = {
            "ts": time.time(),
            "session": self.session,
            "outcome": {"success": success, "answer_nodes": answer_nodes},
            "metrics": metrics,
            "suggest_shortcuts": suggest_shortcuts,
        }
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(outcome, ensure_ascii=False) + "\n")
        self.closed = True
        return outcome
