# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Ranger (spec v0.10, Part H): long-term maintenance.

The compounding loop only works if the pheromone can also forget:
evaporation keeps heat discriminating, pruning keeps proposals from
becoming permanent noise, and the health report tells the operator where
the forest hurts. Trusted infrastructure: evaporation touches only the
derived layer (no commits); link promotion/pruning goes through the
audited `.md`-only commit path.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path
from typing import Callable

import yaml

from monkeyllm import indexer
from monkeyllm.errors import VineError
from monkeyllm.parser import extract_section, replace_section, serialize_node
from monkeyllm.tokens import estimate_tokens
from monkeyllm.vine import Vine

RANGER_CONFIG = "ranger.yaml"  # lives in _meta/ (not a node: non-.md)

DEFAULTS = {
    "half_life_days": 30.0,
    "session_ttl_hours": 24.0,
    "promote_floor": 0.2,
    "promoted_confidence": 0.8,
    "prune_below": 0.5,
    "payload_cache_gb": 5.0,  # H.6
}

NEEDS_SPLIT_ENTRIES = 150   # A.5
NEEDS_SPLIT_TOKENS = 3000   # A.5
FAT_NODE_DEGREE = 50        # A.2
LANDMARKS_SECTION = "Landmarks"  # A.5 / H.7
MAX_LANDMARKS = 20               # A.5: 10-20 highest-degree nodes

_ENTRY_LINE = re.compile(r"^- \[\[", re.MULTILINE)


class Ranger:
    def __init__(self, vine: Vine, *, now: Callable[[], float] = time.time):
        self.vine = vine
        self.forest = vine.forest
        self.now = now
        self.config = dict(DEFAULTS)
        cfg = self.forest.root / "_meta" / RANGER_CONFIG
        if cfg.is_file():
            self.config.update(yaml.safe_load(cfg.read_text(encoding="utf-8")) or {})

    # -- H.1 evaporation ----------------------------------------------------

    def evaporate(self) -> dict:
        report = self.vine.trails.evaporate(
            float(self.config["half_life_days"]), now=self.now())
        report["stale_sessions_cleared"] = self.vine.trails.clear_stale_sessions(
            float(self.config["session_ttl_hours"]), now=self.now())
        return report

    # -- H.2 promotion and pruning -------------------------------------------

    def _managed_links(self, fm: dict) -> list[dict]:
        """Only links born as proposals (link-level confidence < 1.0)."""
        out = []
        for link in fm.get("links") or []:
            if isinstance(link, dict) and isinstance(link.get("confidence"), (int, float)) \
                    and link["confidence"] < 1.0:
                out.append(link)
        return out

    def tend_links(self) -> dict:
        promoted: list[str] = []
        pruned: list[str] = []
        floor = float(self.config["promote_floor"])
        promo = float(self.config["promoted_confidence"])
        prune_below = float(self.config["prune_below"])

        for node_id in list(self.forest.iter_ids()):
            if node_id.startswith("_meta/"):
                continue
            try:
                node = self.forest.read(node_id)
            except VineError:
                continue
            for link in self._managed_links(node.frontmatter):
                heat_src = self.vine.trails.get_heat(node_id)
                heat_tgt = self.vine.trails.get_heat(link["target"])
                if heat_src >= floor and heat_tgt >= floor and link["confidence"] < promo:
                    self._rewrite_link(node_id, link, confidence=promo)
                    promoted.append(f"{node_id} {link['rel']}->{link['target']}")
                elif link["confidence"] <= prune_below and heat_src == 0 and heat_tgt == 0:
                    self._rewrite_link(node_id, link, remove=True)
                    pruned.append(f"{node_id} {link['rel']}->{link['target']}")
        return {"promoted": promoted, "pruned": pruned}

    def _rewrite_link(self, node_id: str, link: dict, *, confidence: float | None = None,
                      remove: bool = False) -> None:
        """Audited write path (like tend/gardener): only the `.md` is committed."""
        node = self.forest.read(node_id)  # re-read: previous action may have written
        fm = dict(node.frontmatter)
        links = list(fm.get("links") or [])
        key = (link["rel"], link["target"])
        kept = []
        for l in links:
            if isinstance(l, dict) and (l.get("rel"), l.get("target")) == key:
                if remove:
                    continue
                l = dict(l)
                l["confidence"] = confidence
            kept.append(l)
        if kept:
            fm["links"] = kept
        else:
            fm.pop("links", None)
        fm["updated"] = dt.date.today().isoformat()
        assert node.path is not None
        node.path.write_text(serialize_node(fm, node.body), encoding="utf-8", newline="\n")
        action = "prune" if remove else "promote"
        detail = f"{link['rel']}->{link['target']}" + ("" if remove else f" {confidence}")
        self.vine.git.commit([node.path], f"ranger({action}): {node_id} {detail}")
        self.vine.catalog.upsert_node(self.forest.read(node_id))
        self.vine.catalog.mark_stale(node_id)

    # -- H.7 landmarks refresh (v0.13) ----------------------------------------

    def tend_landmarks(self) -> dict:
        """Keep the master `_index.md`'s `## Landmarks` section fresh (A.5):
        top-degree non-branch nodes, idempotent, audited `.md`-only commit."""
        rows = self.vine.catalog.top_degrees(MAX_LANDMARKS)
        desired = [indexer.entry_line(r["id"], r["summary"]) for r in rows]

        master = self.forest.read("_index")
        body = indexer.ensure_section(master.body, LANDMARKS_SECTION)
        current_sec = extract_section(body, LANDMARKS_SECTION) or ""
        current = [l for l in current_sec.splitlines() if l.startswith("- [[")]
        if current == desired:
            return {"landmarks": len(desired), "changed": False}

        new_body = replace_section(body, LANDMARKS_SECTION, "\n".join(desired))
        assert new_body is not None  # ensure_section guarantees the heading
        fm = dict(master.frontmatter)
        fm["updated"] = dt.date.today().isoformat()
        assert master.path is not None
        master.path.write_text(serialize_node(fm, new_body),
                               encoding="utf-8", newline="\n")
        self.vine.git.commit([master.path], "ranger(landmarks): refresh")
        self.vine.catalog.upsert_node(self.forest.read("_index"))
        return {"landmarks": len(desired), "changed": True}

    # -- H.3 health report (read-only) ----------------------------------------

    def health(self) -> dict:
        from monkeyllm.gardener import MEDIA_STUB_SENTINEL
        from monkeyllm.lint import lint_forest

        needs_split: list[str] = []
        fat_nodes: list[str] = []
        stale_passports: list[str] = []
        needs_description: list[str] = []
        buckets: dict[str, int] = {}

        source_root = self._gardener_source_root()
        for node_id in self.forest.iter_ids():
            if node_id.startswith("_meta/"):
                continue
            try:
                node = self.forest.read(node_id)
            except VineError:
                continue
            if node.is_branch:
                entries = len(_ENTRY_LINE.findall(node.body))
                if entries > NEEDS_SPLIT_ENTRIES or estimate_tokens(node.body) > NEEDS_SPLIT_TOKENS:
                    needs_split.append(node_id)
            if self.vine.catalog.degree(node_id) > FAT_NODE_DEGREE:
                fat_nodes.append(node_id)
            for link in self._managed_links(node.frontmatter):
                bucket = f"{link['confidence']:.1f}"
                buckets[bucket] = buckets.get(bucket, 0) + 1
            sp = node.frontmatter.get("source_path")
            if sp and source_root and not (source_root / str(sp)).exists():
                stale_passports.append(node_id)
            # H.3 (v0.54): media still wearing the G.5.1 stub — findable by
            # filename and nothing else, and every one of them a BM25
            # near-duplicate of the others. The repair is a vision binding
            # plus a re-describe, and a repair nobody is told about is not
            # one.
            if (node.frontmatter.get("type") == "media"
                    and MEDIA_STUB_SENTINEL in node.body):
                needs_description.append(node_id)

        issues = lint_forest(self.forest)
        return {
            "needs_split": needs_split,
            "fat_nodes": fat_nodes,
            "lint": {
                "errors": sum(1 for i in issues if i.level == "error"),
                "warnings": sum(1 for i in issues if i.level == "warning"),
            },
            "stale_passports": stale_passports,
            "needs_description": needs_description,
            "uncertain_links": buckets,
            "heat": self.vine.trails.stats(),
        }

    def _gardener_source_root(self) -> Path | None:
        cfg = self.forest.root / "_meta" / "gardener.yaml"
        if not cfg.is_file():
            return None
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        root = data.get("source_root")
        return Path(root) if root else None

    # -- H.4 one full cycle ----------------------------------------------------

    def run(self) -> dict:
        report = {"evaporation": self.evaporate()}
        # H.6: evaporation for bytes — cold cached payloads leave the disk
        report["payload_cache"] = self.vine.payload_cache.evict(
            float(self.config["payload_cache_gb"]))
        report["links"] = self.tend_links()
        report["landmarks"] = self.tend_landmarks()
        report["health"] = self.health()
        return report
