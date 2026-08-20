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
from dataclasses import dataclass, field, replace

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.signatures import validate_args
from monkeyllm.vine import (
    BUDGET_LOOK_BATCH,
    BUDGET_PICK_BATCH,
    MAX_BATCH_LOOK,
    MAX_BATCH_PICK,
    batch_ids,
    batch_shape,
)

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

    def masked(self, mask: frozenset[str] | None) -> "Policy":
        """This policy as one credential may exercise it (J.2.6).

        Effective authority is grants ∩ mask, computed at the moment of
        use: the mask is a filter over live authority, never a copy of it,
        so a grant revoked after pairing is gone from the intersection
        immediately. None means unmasked — today's behaviour, byte-for-byte
        — and an empty intersection is a working key that can do nothing:
        the refusals come from the existing capability checks, not from a
        new error path here. Scope (`allow`/`deny`/`tables`) is untouched —
        a mask narrows capabilities, never widens or reshapes a subtree.
        """
        if mask is None:
            return self
        return replace(self, caps=self.caps & frozenset(mask))

    def sql_scope(self, alias: str = "{n}") -> tuple[list[str], list]:
        """This policy's subtrees as a predicate over the catalog (C.13.3).

        `in_scope` decides one id at a time, which is right for filtering a
        handful of results and wrong for counting: an aggregate that has to
        call Python per row cannot be a GROUP BY. The prefixes are the same
        prefixes, spelled for SQLite — and `test_windows.py` compares the
        two over every node in the fixture, because a second reading of one
        rule agrees only where somebody checked.

        `substr(id, 1, n) = ?`, never LIKE: `_` is a single-character
        wildcard there and node ids are full of them (`_index`).
        """
        where: list[str] = []
        params: list = []
        if self.allow != WHOLE_FOREST:
            ors = []
            for prefix in self.allow:
                ors.append(f"substr({alias}id, 1, ?) = ?")
                params.extend([len(prefix), prefix])
            where.append("(" + " OR ".join(ors) + ")")
        for prefix in self.deny:
            where.append(f"substr({alias}id, 1, ?) != ?")
            params.extend([len(prefix), prefix])
        return where, params

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
    "scan": "read", "sniff": "read", "harvest": "read", "view": "read",
    "calendar": "read",
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
               type_filter: str | None = None,
               include: list[str] | None = None,
               since: str | None = None, until: str | None = None,
               date_field: str | None = None) -> dict:
        win = {"since": since, "until": until, "date_field": date_field}
        if self.policy.unrestricted:
            return self._vine.locate(query, k=k, scope=scope,
                                     type_filter=type_filter, include=include,
                                     **win)
        raw = self._vine.locate(query, k=self._fetch(k), scope=scope,
                                type_filter=type_filter, include=include,
                                **win)
        out = self._trim(raw, "results", k)
        if "window" in raw:
            out["window"] = raw["window"]
            out.pop("undated_excluded", None)
            excluded = self._vine.undated_count(
                raw["window"]["date_field"], policy_where=self.policy.sql_scope())
            if excluded:
                out["undated_excluded"] = excluded
        if not out["results"]:
            # C.1.1 / C.13.2 (v0.52): every number an empty read carries is
            # bounded by what this principal may see — the counts they could
            # reach by walking, never the forest's, which would make an empty
            # search a size oracle for the region they were not granted. The
            # engine composes the sentence; the predicate decides the facts
            # in it, so there is one wording and no scoped copy of it.
            out.update(self._empty_context(raw))
        else:
            for key in ("searched", "hint", "matched_window"):
                out.pop(key, None)
        return out

    def _empty_context(self, raw: dict) -> dict:
        return self._vine.empty_context(
            raw.get("window"), "No curated scent matched",
            policy_where=self.policy.sql_scope())

    def sniff(self, terms, scope: str | None = None, k: int = 5,
              type_filter: str | None = None, since: str | None = None,
              until: str | None = None, date_field: str | None = None) -> dict:
        if scope is not None:
            self._gate(scope)
        win = {"since": since, "until": until, "date_field": date_field}
        if self.policy.unrestricted:
            return self._vine.sniff(terms, scope=scope, k=k,
                                    type_filter=type_filter, **win)
        raw = self._vine.sniff(terms, scope=scope, k=self._fetch(k),
                               type_filter=type_filter, **win)
        out = self._trim(raw, "results", k)
        # The engine counts every body it opened, most of which a scoped
        # principal may not know exists — that number is a forest-size oracle,
        # so it is replaced by what the caller can actually see.
        out["scanned_nodes"] = len(out["results"])
        out.pop("undated_excluded", None)
        if "window" in raw:
            out["window"] = raw["window"]
            excluded = self._vine.undated_count(
                raw["window"]["date_field"], policy_where=self.policy.sql_scope())
            if excluded:
                out["undated_excluded"] = excluded
            if not out["results"]:
                out.update(self._vine.empty_context(
                    raw["window"], "No body matched",
                    policy_where=self.policy.sql_scope()))
        return out

    def scan(self, parent_id: str, filter: dict | None = None,
             fields: list[str] | None = None, recursive: bool = False,
             limit: int = 50, after: str | None = None,
             gauntlet: bool | None = None,
             toward: str | None = None, since: str | None = None,
             until: str | None = None, date_field: str | None = None) -> dict:
        self._gate(parent_id)
        # Part K is ordering, not access: it changes which in-scope nodes come
        # first, never which nodes are in scope.
        win = {"since": since, "until": until, "date_field": date_field}
        if self.policy.unrestricted:
            return self._vine.scan(parent_id, filter=filter, fields=fields,
                                   recursive=recursive, limit=limit,
                                   after=after, gauntlet=gauntlet,
                                   toward=toward, **win)
        # C.6.2 (v0.54): the policy rides INTO the engine, where candidates
        # are chosen — so `total` counts what this principal may see (never
        # the forest, which is a size oracle), and the cursor walks their
        # nodes without skipping what a post-hoc trim would have dropped.
        raw = self._vine.scan(parent_id, filter=filter, fields=fields,
                              recursive=recursive, limit=limit, after=after,
                              gauntlet=gauntlet, toward=toward,
                              visible=self.policy.in_scope, **win)
        raw["nodes"] = [self._scrub(it) for it in raw["nodes"]]
        return raw

    def look(self, id, fields: list[str] | None = None,
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
        if isinstance(id, (list, tuple)):
            # C.11: the batch is assembled from the SCOPED single read, so
            # every digest is gated and scrubbed exactly as it would be on
            # its own — and an id this principal may not see joins the
            # absent ones in `missing`, byte-identically (J.3).
            return self._batch(id, MAX_BATCH_LOOK, BUDGET_LOOK_BATCH, "look",
                               lambda nid: self.look(nid, fields=fields,
                                                     gauntlet=gauntlet,
                                                     toward=toward))
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
                # C.2 (v0.54): counts, not prose — recomputed from what
                # survived the scope, same as every derived number (J.11).
                digest["coverage"] = {"notes": bananas, "branches": branches}
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

    def pick(self, id, section: str | None = None) -> dict:
        if isinstance(id, (list, tuple)):
            return self._batch(id, MAX_BATCH_PICK, BUDGET_PICK_BATCH, "pick",
                               lambda nid: self.pick(nid, section=section))
        self._gate(id)
        return self._vine.pick(id, section=section)

    def _batch(self, ids, cap: int, budget: int, primitive: str, read_one) -> dict:
        """C.11 under a policy: same shape, same budget, same accounting."""
        wanted = batch_ids(ids, cap, primitive)
        nodes, missing = [], []
        for nid in wanted:
            try:
                nodes.append(read_one(nid))
            except VineError as e:
                if e.code == E_NOT_FOUND and not self._exists(nid):
                    missing.append(nid)
                    continue
                raise
        return batch_shape(nodes, missing, budget)

    def _exists(self, node_id: str) -> bool:
        """Out of scope counts as absent here, exactly as `_gate` reports it:
        a batch MUST NOT become the surface that tells the two apart."""
        return self._visible(node_id) and self._vine.forest.exists(node_id)

    def view(self, id: str) -> dict:
        # C.6d resolves like J.14: out-of-scope, absent and payload-less all
        # answer the one `_gate`/engine envelope, byte-identical.
        self._gate(id)
        return self._vine.view(id)

    def harvest(self, query: str, terms: list[str] | None = None, k: int = 3,
                since: str | None = None, until: str | None = None,
                date_field: str | None = None) -> dict:
        from monkeyllm.harvest import harvest as _harvest

        # `self`, not `self._vine`: the composite runs on the scoped surface.
        return _harvest(self, query, terms=terms, k=k, since=since,
                        until=until, date_field=date_field)

    def calendar(self, scope: str | None = None, date_field: str | None = None,
                 granularity: str = "month", since: str | None = None,
                 until: str | None = None, limit: int = 24) -> dict:
        if scope is not None:
            self._gate(scope)
        if self.policy.unrestricted:
            return self._vine.calendar(scope=scope, date_field=date_field,
                                       granularity=granularity, since=since,
                                       until=until, limit=limit)
        # J.3: the predicate is the whole difference — every bucket counts
        # only nodes this principal may see, so the map never describes the
        # shape of a region they were not granted. It travels as SQL so the
        # filtering happens inside the GROUP BY, not after it.
        return self._vine.calendar(scope=scope, date_field=date_field,
                                   granularity=granularity, since=since,
                                   until=until, limit=limit,
                                   policy_where=self.policy.sql_scope())

    def query(self, id: str, sql: str) -> dict:
        self._gate(id)
        allowed = self.policy.tables_for(id)
        if allowed is not None:
            # A cheap pre-read, kept for the message it can give: it names the
            # offending table, which the engine's refusal cannot. It is NOT
            # the control — matching names out of SQL text disagrees with
            # SQLite wherever the syntax is unusual, and the statements that
            # slip past it are exactly the ones somebody chose deliberately.
            # The control is the allow-list handed to the engine below, where
            # SQLite itself decides what the statement touches.
            referenced = {t.lower() for t in _SQL_TABLES.findall(sql or "")}
            forbidden = referenced - {t.lower() for t in allowed}
            if forbidden:
                raise VineError(
                    E_FORBIDDEN,
                    f"table not permitted: {sorted(forbidden)[0]}",
                    hint=f"This principal may read: {sorted(allowed)}.",
                )
        return self._vine.query(id, sql, tables=allowed)

    # -- write surface ------------------------------------------------------

    def plant(self, node, if_absent: bool = False) -> dict:
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
        # C.7.2 (v0.52): a caller-facing option, unlike `adopted` — which
        # stays keyword-only and unreachable from the wire (G.2.5).
        return self._vine.plant(node, if_absent=bool(if_absent))

    def graft(self, id: str, patch) -> dict:
        self._gate(id)
        return self._vine.graft(id, patch)

    def tend(self, id: str, sql: str) -> dict:
        self._gate(id)
        # The same allow-list as `query`, and it has to be: writing is a way
        # of reading, so a scope applied to only one of them is a scope that
        # can be worked around. The engine holds that line for both.
        return self._vine.tend(id, sql, tables=self.policy.tables_for(id))

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
            # C.12: argument shape is decided by the one declaration both
            # surfaces read, before anything reaches the primitive. The
            # TypeError below stays as a belt: a signature that drifts from
            # the table is a defect, and it must not become a bare 500.
            return getattr(self, primitive)(**validate_args(primitive, kwargs))
        except VineError as e:
            return e.to_dict()
        except TypeError as e:  # bad/missing arguments from an API client
            return VineError(E_SCHEMA, str(e)).to_dict()
