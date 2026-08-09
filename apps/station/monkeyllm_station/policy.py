# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Policy and ScopedVine — the single enforcement seam (spec J.3).

Every Station surface reaches a forest through `ScopedVine` and nothing
else, so an unscoped `Vine` handle is unreachable by construction (J.1).

The scoped read methods keep the engine's signatures deliberately: the
composite `harvest` (C.6c) takes a vine-shaped object, so handing it a
`ScopedVine` makes the composite inherit scoping instead of needing its own
copy of the rules.

Two invariants shape every method here (J.3):

* **No existence oracle.** Out-of-scope reads raise the engine's own
  `E_NOT_FOUND`, byte-identical to a genuinely missing node — including
  through `move`, whose edges would otherwise disclose a hidden neighbour.
* **No truncation oracle.** Filtering happens before the caller-visible
  cut, and every derived count (`coverage`, `stats.degree`,
  `scanned_nodes`) is recomputed from what survived, because a count taken
  over the whole forest is itself a disclosure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

# Host-level code: the node is visible, the action is not permitted. Never
# used for out-of-scope nodes — an authorization error there would be an
# existence oracle.
E_FORBIDDEN = "E_FORBIDDEN"

CAPS = frozenset({"read", "write", "query", "tend", "ingest", "admin"})
WHOLE_FOREST = ("",)

# Candidates pulled per requested result before scope filtering. The engine
# ranks and cuts in one step, so the host asks for headroom and filters on
# the way out: with enough of it a scoped caller still receives a full `k`,
# which is what keeps the filtering invisible. When the headroom is not
# enough the caller loses recall — never a hint that something was hidden.
OVERFETCH = 8
MAX_OVERFETCH = 200

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_SQL_TABLES = re.compile(r"\b(?:from|join)\s+[\"'`\[]?([A-Za-z_][\w$]*)", re.IGNORECASE)


def _normalize(prefixes) -> tuple[str, ...]:
    """Prefixes compare with a trailing slash so that a grant on `projects/`
    cannot accidentally swallow `projects-secret/`."""
    out: list[str] = []
    for raw in prefixes or ():
        p = str(raw).strip().lstrip("/")
        out.append("" if p == "" else (p if p.endswith("/") else p + "/"))
    if "" in out:
        return WHOLE_FOREST
    return tuple(sorted(set(out)))


@dataclass(frozen=True)
class Policy:
    """What one principal may do on one forest."""

    forest: str
    caps: frozenset[str] = field(default_factory=lambda: frozenset({"read"}))
    allow: tuple[str, ...] = WHOLE_FOREST
    deny: tuple[str, ...] = ()
    tables: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.caps) - CAPS
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        object.__setattr__(self, "caps", frozenset(self.caps))
        object.__setattr__(self, "allow", _normalize(self.allow) or WHOLE_FOREST)
        object.__setattr__(self, "deny", _normalize(self.deny))

    @property
    def unrestricted(self) -> bool:
        return self.allow == WHOLE_FOREST and not self.deny

    def in_scope(self, node_id: str | None) -> bool:
        if not node_id:
            return False
        if any(node_id.startswith(d) for d in self.deny):
            return False
        if self.allow == WHOLE_FOREST:
            return True
        return any(node_id.startswith(a) for a in self.allow)

    def grants(self, cap: str) -> bool:
        return "admin" in self.caps or cap in self.caps

    def roots(self) -> list[str]:
        """Where a scoped principal starts. There is no implicit grant on the
        ancestors of a granted subtree: the master `_index` names every branch
        in the forest, so handing it out would defeat the grant. A principal's
        world is the subtrees they were given."""
        if self.allow == WHOLE_FOREST:
            return ["_index"]
        return [a + "_index" for a in self.allow]

    def tables_for(self, dataset_id: str) -> tuple[str, ...] | None:
        allowed = self.tables.get(dataset_id)
        return tuple(allowed) if allowed else None

    @classmethod
    def full(cls, forest: str) -> Policy:
        return cls(forest=forest, caps=frozenset(CAPS))


REQUIRED_CAP = {
    "locate": "read", "look": "read", "move": "read", "pick": "read",
    "scan": "read", "sniff": "read", "harvest": "read",
    "query": "query", "tend": "tend", "plant": "write", "graft": "write",
}


class ScopedVine:
    """A Vine seen through one principal's policy."""

    def __init__(self, vine, policy: Policy):
        self._vine = vine
        self.policy = policy

    # -- scope helpers ------------------------------------------------------

    def _visible(self, node_id: str | None) -> bool:
        return self.policy.in_scope(node_id)

    def _gate(self, node_id: str) -> None:
        """Out-of-scope is reported exactly as absent (J.3). The message and
        hint mirror the engine's `_row_or_raise` verbatim; if that text ever
        drifts, the leak suite fails and says so."""
        if not self._visible(node_id):
            raise VineError(
                E_NOT_FOUND,
                f"node not found: {node_id}",
                hint="Use locate() to find entry points.",
            )

    def _fetch(self, k: int) -> int:
        return min(max(int(k), 1) * OVERFETCH, MAX_OVERFETCH)

    def _scrub(self, item: dict) -> dict:
        """Result rows carry a `trail` of ancestor ids, which for a scoped
        principal runs up through branches they were never granted. The trail
        is navigational sugar, so it is filtered like everything else rather
        than special-cased into visibility."""
        if isinstance(item.get("trail"), list):
            item = dict(item)
            item["trail"] = [t for t in item["trail"] if self._visible(t)]
        return item

    def _trim(self, payload: dict, key: str, k: int) -> dict:
        items = [
            self._scrub(it) for it in payload.get(key, []) if self._visible(it.get("id"))
        ]
        out = dict(payload)
        out[key] = items[:k]
        out["truncated"] = len(items) > k
        return out

    # -- read surface (engine-compatible signatures) ------------------------

    def locate(self, query: str, k: int = 5, scope: str = "all",
               type_filter: str | None = None) -> dict:
        if self.policy.unrestricted:
            return self._vine.locate(query, k=k, scope=scope, type_filter=type_filter)
        raw = self._vine.locate(query, k=self._fetch(k), scope=scope, type_filter=type_filter)
        return self._trim(raw, "results", k)

    def sniff(self, terms, scope: str | None = None, k: int = 5,
              type_filter: str | None = None) -> dict:
        if scope is not None:
            self._gate(scope)
        if self.policy.unrestricted:
            return self._vine.sniff(terms, scope=scope, k=k, type_filter=type_filter)
        raw = self._vine.sniff(terms, scope=scope, k=self._fetch(k), type_filter=type_filter)
        out = self._trim(raw, "results", k)
        # The engine counts every body it opened, most of which a scoped
        # principal may not know exists — that number is a forest-size oracle,
        # so it is replaced by what the caller can actually see.
        out["scanned_nodes"] = len(out["results"])
        return out

    def scan(self, parent_id: str, filter: dict | None = None,
             fields: list[str] | None = None, recursive: bool = False,
             limit: int = 50, gauntlet: bool | None = None,
             toward: str | None = None) -> dict:
        self._gate(parent_id)
        # Part K is ordering, not access: it changes which in-scope nodes come
        # first, never which nodes are in scope. So it is forwarded as-is and
        # the filtering below is unchanged.
        if self.policy.unrestricted:
            return self._vine.scan(parent_id, filter=filter, fields=fields,
                                   recursive=recursive, limit=limit,
                                   gauntlet=gauntlet, toward=toward)
        raw = self._vine.scan(parent_id, filter=filter, fields=fields,
                              recursive=recursive, limit=self._fetch(limit),
                              gauntlet=gauntlet, toward=toward)
        return self._trim(raw, "nodes", limit)

    def look(self, id: str, fields: list[str] | None = None,
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
        self._gate(id)
        digest = self._vine.look(id, fields=fields, gauntlet=gauntlet, toward=toward)
        if self.policy.unrestricted:
            return digest

        for key, id_key in (("edges_out", "target"), ("edges_in", "source")):
            if key in digest:
                digest[key] = [e for e in digest[key] if self._visible(e.get(id_key))]
        if "children" in digest:
            digest["children"] = [c for c in digest["children"] if self._visible(c.get("id"))]
            # coverage counts the branch's real children, hidden ones included.
            branches = sum(1 for c in digest["children"] if c["id"].endswith("/_index"))
            bananas = len(digest["children"]) - branches
            if "coverage" in digest:
                digest["coverage"] = f"{bananas} bananas, {branches} sub-branches."
        if "cross_trails" in digest:
            digest["cross_trails"] = [
                t for t in digest["cross_trails"] if self._trail_visible(t)
            ]
        if "stats" in digest and isinstance(digest["stats"], dict):
            # degree counted the hidden edges too.
            digest["stats"] = dict(digest["stats"])
            digest["stats"]["degree"] = len(digest.get("edges_out", [])) + len(
                digest.get("edges_in", [])
            )
        return digest

    def _trail_visible(self, entry: str) -> bool:
        targets = _WIKILINK.findall(entry or "")
        return all(self._visible(t.strip()) for t in targets)

    def move(self, id: str, rel: str | None = None, direction: str = "out",
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
        self._gate(id)
        payload = self._vine.move(id, rel=rel, direction=direction,
                                  gauntlet=gauntlet, toward=toward)
        if self.policy.unrestricted:
            return payload
        payload = dict(payload)
        payload["neighbors"] = [
            n for n in payload.get("neighbors", []) if self._visible(n.get("id"))
        ]
        return payload

    def pick(self, id: str, section: str | None = None) -> dict:
        self._gate(id)
        return self._vine.pick(id, section=section)

    def harvest(self, query: str, terms: list[str] | None = None, k: int = 3) -> dict:
        from monkeyllm.harvest import harvest as _harvest

        # `self`, not `self._vine`: the composite runs on the scoped surface.
        return _harvest(self, query, terms=terms, k=k)

    def query(self, id: str, sql: str) -> dict:
        self._gate(id)
        allowed = self.policy.tables_for(id)
        if allowed is not None:
            referenced = {t.lower() for t in _SQL_TABLES.findall(sql or "")}
            forbidden = referenced - {t.lower() for t in allowed}
            if forbidden:
                raise VineError(
                    E_FORBIDDEN,
                    f"table not permitted: {sorted(forbidden)[0]}",
                    hint=f"This principal may read: {sorted(allowed)}.",
                )
        return self._vine.query(id, sql)

    # -- write surface ------------------------------------------------------

    def plant(self, node) -> dict:
        node_id = node.get("id") if isinstance(node, dict) else getattr(node, "id", None)
        if not node_id:
            raise VineError(E_SCHEMA, "plant requires an 'id'")
        if not self._visible(node_id):
            # A write outside the grant is refused as forbidden, not as
            # not-found: the caller supplied the id, so nothing is disclosed.
            raise VineError(
                E_FORBIDDEN,
                f"'{node_id}' is outside this principal's grant",
                hint=f"Writable subtrees: {list(self.policy.allow)}.",
            )
        return self._vine.plant(node)

    def graft(self, id: str, patch) -> dict:
        self._gate(id)
        return self._vine.graft(id, patch)

    def tend(self, id: str, sql: str) -> dict:
        self._gate(id)
        return self._vine.tend(id, sql)

    # -- dispatcher used by the surfaces ------------------------------------

    def call(self, primitive: str, /, **kwargs) -> dict:
        """Invoke a primitive under the policy. Returns the primitive's dict
        or the spec error envelope — never raises for expected failures."""
        cap = REQUIRED_CAP.get(primitive)
        if cap is None:
            return VineError(E_SCHEMA, f"unknown primitive: {primitive}").to_dict()
        if not self.policy.grants(cap):
            return VineError(
                E_FORBIDDEN,
                f"'{primitive}' requires the '{cap}' capability",
                hint=f"This principal holds: {sorted(self.policy.caps)}.",
            ).to_dict()
        try:
            return getattr(self, primitive)(**kwargs)
        except VineError as e:
            return e.to_dict()
        except TypeError as e:  # bad/missing arguments from an API client
            return VineError(E_SCHEMA, str(e)).to_dict()
