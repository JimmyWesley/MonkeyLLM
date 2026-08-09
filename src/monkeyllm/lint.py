# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""`vine validate` — lint the forest against the schema (roadmap deliverable 3)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from monkeyllm.errors import VineError
from monkeyllm.forest import Forest
from monkeyllm.models import validate_frontmatter, validate_summary
from monkeyllm.parser import WIKILINK_RE


@dataclass
class Issue:
    node_id: str
    level: str  # 'error' | 'warning'
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.node_id}: {self.message}"


def lint_forest(forest: Forest) -> list[Issue]:
    issues: list[Issue] = []
    all_ids: set[str] = set(forest.iter_ids())

    for node_id in sorted(all_ids):
        try:
            node = forest.read(node_id)
        except VineError as e:
            issues.append(Issue(node_id, "error", e.message))
            continue

        if node_id.startswith("_meta/"):
            continue

        fm = dict(node.frontmatter)
        if node.is_branch:
            fm.setdefault("title", node.title_from_body or node_id)
            fm.setdefault("summary", node.quote_from_body or "")
            fm.setdefault("created", fm.get("updated"))
        try:
            validate_frontmatter(fm, forest.dialect, strict_summary=False)
        except VineError as e:
            issues.append(Issue(node_id, "error", f"{e.code}: {e.message}"))
            continue

        if fm.get("id") != node_id:
            issues.append(
                Issue(node_id, "error", f"frontmatter id '{fm.get('id')}' != canonical id")
            )
        try:
            validate_summary(str(fm.get("summary", "")))
        except VineError as e:
            issues.append(Issue(node_id, "warning", f"summary: {e.message}"))

        for link in fm.get("links") or []:
            target = link.get("target") if isinstance(link, dict) else None
            if target and target not in all_ids:
                issues.append(Issue(node_id, "error", f"broken link target: {target}"))
        for wl in node.wikilinks():
            if wl not in all_ids:
                issues.append(Issue(node_id, "warning", f"broken wikilink: [[{wl}]]"))

        if node.frontmatter.get("payload"):
            from monkeyllm.fetch import is_remote

            if is_remote(node.frontmatter["payload"]):
                continue  # G.9: validated by hash at fetch time, not by lint
            payload = forest.payload_path(node)
            if not payload.is_file():
                issues.append(
                    Issue(node_id, "error", f"payload missing: {node.frontmatter['payload']}")
                )
            elif node.frontmatter.get("payload_hash"):
                # spec A.3/C.10: drift detection — the hash is the audit anchor
                actual = hashlib.sha256(payload.read_bytes()).hexdigest()
                if actual != node.frontmatter["payload_hash"]:
                    issues.append(
                        Issue(node_id, "warning",
                              f"payload drift: sha256 mismatch for {node.frontmatter['payload']} "
                              "(edited outside tend?)")
                    )
    return issues
