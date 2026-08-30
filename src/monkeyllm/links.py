# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The managed links, read and settled by a person (spec H.2.1, v0.75).

H.2 manages exactly one population — links carrying a link-level
`confidence < 1.0` — and until v0.75 it managed them on HEAT alone. Heat is
the right evidence for a link nobody vouched for, and it is the only
evidence there was: a correct `related-to` proposal (G.4.2.1, born at 0.3)
between two nodes nobody has walked stays at 0.3 forever. In a forest that
has just been ingested every node is cold by definition, which is exactly
when the proposals are worth reading and exactly when nothing can act on
them.

This module is the vote. Two functions and one shared write:

* `uncertain_links` lists the managed population with what a decision
  needs — both endpoints' scent and both endpoints' persistent heat, which
  is the answer to *why has this not been promoted already*. No bodies: a
  decision about adjacency is made on the scent, which is what the proposal
  itself was made on.
* `vote` accepts (confidence -> 1.0, permanently out of the managed
  population) or rejects (the link is removed).
* `rewrite_link` is the audited `.md`-only commit path both the Ranger's
  promote/prune and the vote go through (H.2.1 rule 1). It is one function
  on purpose: two descriptions of one write agree only where somebody
  compared them, and the Ranger's version was already the reference.

Two boundaries this module does NOT draw and must not be read as drawing:

* **Capability and scope are the host's** (J.18). `visible` is the policy's
  own predicate, keyword-only and host-supplied — the same construction
  `scan` uses — so it is unreachable from the wire.
* **There is no MCP tool here** (H.2.1 rule 5). The whole point of
  link-level 0.3 is that a model asserted the link and something ELSE has
  to confirm it; an agent-callable accept would let the proposer close its
  own loop and the confidence would stop recording anything.
"""

from __future__ import annotations

import datetime as dt

from monkeyllm.errors import E_READONLY, E_SCHEMA, VineError
from monkeyllm.parser import serialize_node

# H.2's scope rule, as one number. A link AT this value is untouchable, and
# that is exactly why `accept` writes it (H.2.1 rule 2): 0.8 would leave the
# link managed, and a vote that a later configuration change can sweep is
# not a vote.
SETTLED = 1.0

# J.18: grouped by source node, paged in scan's shape. Proposals are born up
# to three at a time on one document (G.4.2.1 rule 4), so the GROUP is what a
# reviewer reads and therefore what a page is counted in.
DEFAULT_GROUPS = 20
MAX_GROUPS = 50

# J.18: fifty independent decisions, never one thought. Bounded because the
# response reports every one of them and each is its own commit.
MAX_VOTES = 50

VOTES = ("accept", "reject")

# The four commit subjects this path can write, in the Ranger's own spelling
# (`ranger(promote): <id> <rel>-><target> 0.8`). One table, because the
# subject is what `history` parses an action off (C.16) and what an operator
# reads in `git log`.
_SUBJECT = {
    ("ranger", False): "ranger(promote)",
    ("ranger", True): "ranger(prune)",
    ("vote", False): "vote(accept)",
    ("vote", True): "vote(reject)",
}


def link_confidence(link) -> float | None:
    """The link's own confidence, or `None` when it declares none.

    `None` is not `1.0`: a structural edge and a link somebody settled at
    1.0 are both outside the managed population, but only one of them is a
    record of a decision (H.2.1 rule 3).
    """
    if not isinstance(link, dict):
        return None
    value = link.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def is_managed(link) -> bool:
    """H.2's scope rule, in one place: link-level `confidence < 1.0`."""
    confidence = link_confidence(link)
    return confidence is not None and confidence < SETTLED


def managed_links(frontmatter: dict) -> list[dict]:
    """Every managed link on one passport, in the file's own order."""
    return [l for l in (frontmatter.get("links") or []) if is_managed(l)]


def find_link(frontmatter: dict, rel: str, target: str) -> dict | None:
    for link in frontmatter.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == rel \
                and link.get("target") == target:
            return link
    return None


def rewrite_link(vine, node_id: str, link: dict, *,
                 confidence: float | None = None, remove: bool = False,
                 by: str = "ranger") -> str:
    """The audited write path: only the `.md` is committed (H.2.1 rule 1).

    Re-reads the node first — a previous action in the same cycle (or the
    previous vote in the same batch) may already have written it — rewrites
    the one link the caller named, commits the passport alone, and refreshes
    the catalog exactly as the Ranger always did.

    `by` picks the commit subject and nothing else. The Ranger's two verbs
    and the vote's two verbs are the same write with a different author, so
    they are the same function: a second copy would be a second definition
    of what promoting a link means.

    Returns the commit sha.
    """
    node = vine.forest.read(node_id)
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
    node.path.write_text(serialize_node(fm, node.body), encoding="utf-8",
                         newline="\n")
    detail = f"{link['rel']}->{link['target']}" + ("" if remove else f" {confidence}")
    sha = vine.git.commit([node.path],
                          f"{_SUBJECT[(by, remove)]}: {node_id} {detail}")
    vine.catalog.upsert_node(vine.forest.read(node_id))
    vine.catalog.mark_stale(node_id)
    return sha


# -- the listing (J.18) ------------------------------------------------------


def _scent(catalog, node_id: str, heat: dict) -> dict | None:
    """What a decision about adjacency is made on. `None` when the node has
    no catalog row at all — a link into a hole is reported the way an
    out-of-scope endpoint is, because from the reviewer's side those are the
    same fact and J.3 requires them to look it."""
    row = catalog.get(node_id)
    if row is None:
        return None
    return {
        "id": node_id,
        "type": row["type"],
        "title": row["title"],
        "summary": row["summary"],
        "heat": heat.get(node_id, 0.0),
    }


def uncertain_links(vine, *, after: str | None = None,
                    limit: int = DEFAULT_GROUPS, visible=None) -> dict:
    """The managed links, grouped by source node and paged by cursor.

    The candidate SOURCES come from the catalog's `edges` table, which
    indexes link-level confidence for exactly this reason — walking every
    passport is the Ranger's job once a cycle, not a console's on every
    page. The links themselves are then read off the passports of the
    page's own sources, so the `confidence` and the `note` served are the
    FILE's and not an index's: the files are the truth (A.3), and this
    listing is what a person is about to act on.

    `visible` is the host policy's predicate (J.18 / H.2.1 rule 6),
    keyword-only and host-supplied, unreachable from the wire (`scan`'s
    construction). A link with EITHER endpoint out of scope is absent —
    accepting publishes the target's id into a node other principals may
    read, so the scope test is the one G.4.2.1 already applies to
    candidates.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise VineError(E_SCHEMA, "limit must be an integer") from None
    limit = min(max(1, limit), MAX_GROUPS)
    if after is not None and not isinstance(after, str):
        raise VineError(E_SCHEMA, "after must be a string")

    seen: dict[str, list[tuple[str, str]]] = {}
    for row in vine.catalog.uncertain_edges():
        src, dst = row["src"], row["dst"]
        if src.startswith("_meta/"):
            continue
        if visible is not None and not (visible(src) and visible(dst)):
            continue
        seen.setdefault(src, []).append((row["rel"], dst))

    ids = sorted(seen)
    if after:
        ids = [i for i in ids if i > after]
    page = ids[:limit]
    more = len(ids) > limit

    # One heat statement for the whole page (C.6b.1's rule): the endpoints
    # of twenty groups are a few dozen ids, and asking per node is a round
    # trip each.
    wanted: list[str] = []
    for src in page:
        wanted.append(src)
        wanted.extend(dst for _, dst in seen[src])
    # PERSISTENT heat, with no session scope mixed in (J.18): the number
    # that answers "why has this not been promoted already" is the one
    # H.2 reads, and a hunt's transient warmth is not it.
    heat = vine.trails.heat_map(sorted(set(wanted)))

    groups = []
    for src in page:
        try:
            node = vine.forest.read(src)
        except VineError:
            # The passport went away since the catalog last saw it. Absent
            # rather than reported: a group whose source cannot be read is a
            # group nobody can vote on.
            continue
        source = _scent(vine.catalog, src, heat)
        if source is None:
            continue
        items = []
        for rel, dst in seen[src]:
            link = find_link(node.frontmatter, rel, dst)
            # The file decides. A catalog row for a link the passport no
            # longer carries (or no longer carries as a proposal) is stale,
            # and offering a vote on it would offer a vote that answers
            # `missing`.
            if link is None or not is_managed(link):
                continue
            target = _scent(vine.catalog, dst, heat)
            if target is None:
                continue
            item = {
                "target": target,
                "rel": rel,
                "confidence": link_confidence(link),
            }
            note = link.get("note")
            # G.4.2.1 rule 3: a proposal MAY carry one. Absent stays absent
            # — an empty string reads as a note somebody wrote and left
            # blank.
            if isinstance(note, str) and note.strip():
                item["note"] = note
            items.append(item)
        if not items:
            continue
        groups.append({"source": source, "links": items})

    payload = {
        "groups": groups,
        # The principal's own counts, never the forest's: a global total
        # here would be a size oracle for a region nobody granted (J.3).
        "total": len(seen),
        "returned": len(groups),
        "links": sum(len(g["links"]) for g in groups),
        "truncated": more,
    }
    if more and page:
        # The last SOURCE id offered is what the next call's `after` takes.
        payload["next"] = page[-1]
    return payload


# -- the vote (H.2.1 rules 1-3) ---------------------------------------------


def _record(item: dict, outcome: str, **extra) -> dict:
    """One vote's outcome. `missing` carries nothing beyond the echo, which
    is what makes an out-of-scope endpoint byte-identical to a link that
    does not exist (H.2.1 rule 6)."""
    out = {"id": item["id"], "rel": item["rel"], "target": item["target"],
           "vote": item["vote"], "outcome": outcome}
    out.update(extra)
    return out


def _shape(raw) -> dict | None:
    """One vote as sent, or `None` when it is not one."""
    if not isinstance(raw, dict):
        return None
    fields = {k: raw.get(k) for k in ("id", "rel", "target", "vote")}
    if not all(isinstance(v, str) and v for v in fields.values()):
        return None
    return fields


def vote(vine, votes, *, visible=None) -> list[dict]:
    """Settle managed links. One `.md` commit per vote, never a batch.

    C.7.4's plant batch is atomic because a branch and its children are ONE
    thought that is incoherent half-written. Fifty votes are fifty
    independent decisions, and failing all of them because one target had
    since been pruned would throw away work a person actually did — so this
    returns one record per vote sent and never raises for an individual
    one.

    The outcomes, and why each is the outcome it is:

    * `accepted` / `rejected` — a managed link was settled.
    * `unchanged` — the vote's own outcome already holds. In practice this
      is `accept` on a link already at 1.0: a reviewer double-clicking, or
      a batch retried after a dropped connection, must not read as an
      error (J.18), and the link is in exactly the state the vote asks for.
    * `missing` — the link, or an endpoint, is gone OR out of scope. One
      outcome for both, byte-identically (J.3).
    * `refused` — the link is outside the managed population and the vote
      would change it: a structural edge, a link with no confidence field,
      or a `reject` aimed at a link somebody already settled at 1.0. Rule 2
      makes 1.0 permanent, so `reject` cannot walk it back; a vote is not a
      general link editor.
    """
    if not vine.writable:
        raise VineError(
            E_READONLY, "this forest is open read-only",
            hint="A vote is a commit inside the forest (H.2.1 rule 1).")
    if not isinstance(votes, list) or not votes:
        raise VineError(E_SCHEMA, "votes must be a non-empty list")
    if len(votes) > MAX_VOTES:
        raise VineError(
            E_SCHEMA, f"{len(votes)} votes (max {MAX_VOTES})",
            hint="A review batch is bounded: every vote is its own commit "
                 "and its own audit row (J.18).")

    out: list[dict] = []
    for raw in votes:
        item = _shape(raw)
        if item is None or item["vote"] not in VOTES:
            echo = raw if isinstance(raw, dict) else {}
            out.append({
                "id": echo.get("id") if isinstance(echo.get("id"), str) else None,
                "rel": echo.get("rel") if isinstance(echo.get("rel"), str) else None,
                "target": (echo.get("target")
                           if isinstance(echo.get("target"), str) else None),
                "vote": echo.get("vote") if isinstance(echo.get("vote"), str) else None,
                "outcome": "refused",
                "code": E_SCHEMA,
                "message": "each vote is {id, rel, target, vote} with "
                           f"vote in {list(VOTES)}",
            })
            continue
        out.append(_one(vine, item, visible))
    return out


def _one(vine, item: dict, visible) -> dict:
    node_id, rel, target = item["id"], item["rel"], item["target"]
    # Scope first, and it decides before anything is read: both endpoints
    # must be visible (H.2.1 rule 6), and a refusal that named the reason
    # would be the periscope the rule exists to close.
    if visible is not None and not (visible(node_id) and visible(target)):
        return _record(item, "missing")
    try:
        node = vine.forest.read(node_id)
    except VineError:
        return _record(item, "missing")
    link = find_link(node.frontmatter, rel, target)
    if link is None:
        return _record(item, "missing")
    if vine.catalog.get(target) is None:
        # The far end is not in the forest. Same fact as an absent link
        # from the reviewer's side, and the listing hides it for the same
        # reason.
        return _record(item, "missing")

    confidence = link_confidence(link)
    if confidence is None:
        return _record(
            item, "refused", code=E_READONLY,
            message=f"'{rel}' -> {target} carries no confidence, so it is "
                    "not a proposal",
        )
    if confidence >= SETTLED:
        if item["vote"] == "accept":
            return _record(item, "unchanged", confidence=SETTLED)
        return _record(
            item, "refused", code=E_READONLY,
            message="this link is settled at 1.0 and is no longer managed",
        )

    if item["vote"] == "accept":
        sha = rewrite_link(vine, node_id, link, confidence=SETTLED, by="vote")
        return _record(item, "accepted", confidence=SETTLED, commit=sha)
    sha = rewrite_link(vine, node_id, link, remove=True, by="vote")
    return _record(item, "rejected", commit=sha)


__all__ = [
    "DEFAULT_GROUPS", "MAX_GROUPS", "MAX_VOTES", "SETTLED", "VOTES",
    "find_link", "is_managed", "link_confidence", "managed_links",
    "rewrite_link", "uncertain_links", "vote",
]
