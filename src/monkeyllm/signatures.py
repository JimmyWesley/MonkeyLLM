# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The signature table (spec C.12, v0.52) — one declaration of what every
primitive accepts, read by every surface that takes arguments off a wire.

Why it exists at all: a malformed argument used to reach the primitive and
raise whatever Python raised there. Measured against a served Station, seven
malformed calls produced five different behaviours — three bare `500`s, one
`TypeError` leaking through the envelope's `message`, one `null` coerced to
the string `"None"` and looked up, and one integer accepted as a search term
and answered with an empty result set, which reads exactly like "nothing in
this forest matches".

The table is in the ENGINE, not in the host, for the same reason the MCP
tool list is not the contract: `vine serve` is a wire boundary too, and two
descriptions of one contract agree only where somebody compared them. The
comparison is mechanical (see `tests/test_signatures.py`).

Types are named rather than expressed as Python types so that a message can
say what was expected in the caller's language: `"string"`, not
`<class 'str'>`.
"""

from __future__ import annotations

from monkeyllm.errors import E_SCHEMA, VineError

# Type names, and what satisfies them.
_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    # J.10.10 (v0.59): a score threshold. An int is a number; a bool is not
    # — the C.12 rule that a value is never coerced applies here too.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    # J.10.5: `hops: true` means "the budget you would have picked", a
    # number sets it — one parameter, two spellings, both meant.
    "boolean|integer": lambda v: isinstance(v, bool) or isinstance(v, int),
    "object": lambda v: isinstance(v, dict),
    "string[]": lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
    "object[]": lambda v: isinstance(v, list) and all(isinstance(i, dict) for i in v),
    # C.11: one id, or a batch of them. The element check lives here so a
    # list of integers is refused with the parameter's name attached.
    "string|string[]": lambda v: isinstance(v, str) or (
        isinstance(v, list) and all(isinstance(i, str) for i in v)
    ),
    # C.7.4: one node, or a batch of them.
    "object|object[]": lambda v: isinstance(v, dict) or (
        isinstance(v, list) and all(isinstance(i, dict) for i in v)
    ),
}


def _param(type_name: str, *, required: bool = False) -> dict:
    return {"type": type_name, "required": required}


# Every parameter a surface may hand a primitive. Keyword-only guards
# (`adopted`, `tables`) are deliberately absent: they are unreachable from
# the wire by construction (G.2.5, C.5.3) and listing them here would be the
# first step towards making them reachable.
SIGNATURES: dict[str, dict[str, dict]] = {
    "locate": {
        "query": _param("string", required=True),
        "k": _param("integer"),
        "scope": _param("string"),
        "type_filter": _param("string"),
        "include": _param("string[]"),
        # C.13.1: the window. Optional everywhere, and absent means the
        # call behaves exactly as it did before v0.52.
        "since": _param("string"),
        "until": _param("string"),
        "date_field": _param("string"),
        # A.3.2 rule 5 (v0.75): the document's language as a filter, never
        # a boost. Absent, the call behaves exactly as it did before.
        "lang": _param("string"),
        # K.3: the entry-search switch, read and removed by the host before
        # the primitive is called. Declared so it is not an unknown key.
        "hybrid": _param("boolean"),
    },
    "look": {
        "id": _param("string|string[]", required=True),
        "fields": _param("string[]"),
        "gauntlet": _param("boolean"),
        "toward": _param("string"),
    },
    "move": {
        "id": _param("string", required=True),
        "rel": _param("string"),
        "direction": _param("string"),
        "gauntlet": _param("boolean"),
        "toward": _param("string"),
    },
    "pick": {
        "id": _param("string|string[]", required=True),
        # C.4.1 (v0.56): a list of sections is one call with one budget.
        "section": _param("string|string[]"),
        # C.4.1: the page cursor — scan's idiom on one body. "" starts at
        # the beginning; the response's `next` is what the next call takes.
        "after": _param("string"),
    },
    "view": {
        "id": _param("string", required=True),
    },
    "scan": {
        "parent_id": _param("string", required=True),
        "filter": _param("object"),
        "fields": _param("string[]"),
        "recursive": _param("boolean"),
        "limit": _param("integer"),
        # C.6.2 (v0.54): the enumeration cursor. "" starts at the
        # beginning; the response's `next` is what the next call takes.
        "after": _param("string"),
        "gauntlet": _param("boolean"),
        "toward": _param("string"),
        "since": _param("string"),
        "until": _param("string"),
        "date_field": _param("string"),
    },
    "sniff": {
        "terms": _param("string|string[]", required=True),
        "scope": _param("string"),
        "k": _param("integer"),
        "type_filter": _param("string"),
        "since": _param("string"),
        "until": _param("string"),
        "date_field": _param("string"),
        # A.3.2 rule 5 (v0.75): the document's language as a filter, never
        # a boost. Absent, the call behaves exactly as it did before.
        "lang": _param("string"),
    },
    "calendar": {
        "scope": _param("string"),
        "date_field": _param("string"),
        "granularity": _param("string"),
        "since": _param("string"),
        "until": _param("string"),
        "limit": _param("integer"),
    },
    "coverage": {
        # C.17 (v0.59): what the forest holds, from the catalog alone.
        "scope": _param("string"),
        "date_field": _param("string"),
    },
    "query": {
        "id": _param("string", required=True),
        "sql": _param("string", required=True),
    },
    "plant": {
        # C.7.4 (v0.58): one node, or a batch of up to 20 — everything
        # validated before anything is written, one commit for the lot.
        "node": _param("object|object[]", required=True),
        "if_absent": _param("boolean"),
        "dry_run": _param("boolean"),
    },
    "graft": {
        "id": _param("string", required=True),
        "patch": _param("object", required=True),
    },
    "tend": {
        "id": _param("string", required=True),
        "sql": _param("string", required=True),
    },
    # C.14 (v0.56): the write you can take back. `visible` (the host
    # policy's predicate) is keyword-only in the engine and deliberately
    # absent here — same construction as `adopted`.
    "prune": {
        "id": _param("string", required=True),
        "force": _param("boolean"),
    },
    # C.15 (v0.58): the move that leaves a waymark.
    "transplant": {
        "id": _param("string", required=True),
        "new_id": _param("string", required=True),
    },
    # C.16 (v0.58): the document's past.
    "history": {
        "id": _param("string", required=True),
        "limit": _param("integer"),
    },
    # Composites (C.6c, J.10.5): not primitives, same wire, same rule.
    "harvest": {
        "query": _param("string", required=True),
        "terms": _param("string[]"),
        "k": _param("integer"),
        "since": _param("string"),
        "until": _param("string"),
        "date_field": _param("string"),
        # A.3.2 rule 5 (v0.75): the document's language as a filter, never
        # a boost. Absent, the call behaves exactly as it did before.
        "lang": _param("string"),
        # C.6c.4 (v0.58): the history view — restores what a live
        # `supersedes` edge excludes by default.
        "include_superseded": _param("boolean"),
    },
    "answer": {
        # `query` is the older spelling of `question` and still accepted, so
        # neither is required on its own — the composite refuses an empty
        # question with its own message.
        "question": _param("string"),
        "query": _param("string"),
        # J.10.3 (v0.67): the caller's own literal terms for the sweep's
        # `sniff` leg — the same shapes `harvest` takes, on the same rules.
        # Absent, the sweep derives them from the question as it always has;
        # sent beside `hops` it is E_SCHEMA, because a walk authors its own
        # retrieval and a parameter silently dropped is a lie about what ran.
        "terms": _param("string[]"),
        "k": _param("integer"),
        "cache": _param("boolean"),
        "reply_tokens": _param("integer"),
        "min_evidence": _param("integer"),
        # J.10.10 (v0.59): the floor that counts evidence, not items.
        "min_score": _param("number"),
        "include_superseded": _param("boolean"),
        "hops": _param("boolean|integer"),
        "since": _param("string"),
        "until": _param("string"),
        "date_field": _param("string"),
    },
    # J.8's REST surface additionally carries the ingest console's own keys
    # (`stage`, `draft`, `title`, `text`, `source`), which are validated
    # there; this entry describes the agent-facing tool.
    "ingest": {
        "mode": _param("string"),
        "files": _param("object[]"),
        "path": _param("string"),
        "dest": _param("string"),
        "wait": _param("boolean"),
    },
}


_NAMES = {str: "string", bool: "boolean", int: "integer", float: "number",
          list: "list", dict: "object", type(None): "null"}


def _type_name(value) -> str:
    """What arrived, said the way the table says it — and for a list, what
    was inside: "list of integer" is the sentence that fixes the call, while
    "list" sends the caller looking at the wrong thing."""
    if isinstance(value, list):
        inner = sorted({_NAMES.get(type(v), type(v).__name__) for v in value})
        return f"list of {'/'.join(inner)}" if inner else "empty list"
    return _NAMES.get(type(value), type(value).__name__)


def validate_args(primitive: str, args: dict) -> dict:
    """Check `args` against the declaration and return them, cleaned.

    Cleaned means one thing only: a `null` for an optional parameter is
    removed, so the primitive's own default applies (C.12 rule 3). Nothing
    is coerced — a string that looks like a number stays wrong, because the
    caller that sent it has a bug worth being told about.
    """
    table = SIGNATURES.get(primitive)
    if table is None:
        return dict(args)
    if not isinstance(args, dict):
        raise VineError(E_SCHEMA, f"{primitive}: arguments must be a JSON object")

    unknown = [k for k in args if k not in table]
    if unknown:
        raise VineError(
            E_SCHEMA,
            f"{primitive}: unknown parameter {unknown[0]!r}",
            hint=f"{primitive} accepts: {sorted(table)}.",
        )

    out = {}
    for name, spec in table.items():
        if name not in args:
            if spec["required"]:
                raise VineError(
                    E_SCHEMA,
                    f"{primitive}: missing required parameter {name!r} "
                    f"({spec['type']})",
                    hint=f"{primitive} accepts: {sorted(table)}.",
                )
            continue
        value = args[name]
        if value is None:
            # C.12 rule 3: `null` is not a value. Required means it was not
            # given; optional means the primitive's own default applies.
            if spec["required"]:
                raise VineError(
                    E_SCHEMA,
                    f"{primitive}: parameter {name!r} is required and was null "
                    f"({spec['type']} expected)",
                    hint="A null argument is a missing argument, never a value.",
                )
            continue
        if not _CHECKS[spec["type"]](value):
            raise VineError(
                E_SCHEMA,
                f"{primitive}: parameter {name!r} expects {spec['type']}, "
                f"got {_type_name(value)}",
                hint=f"{primitive} accepts: {sorted(table)}.",
            )
        out[name] = value
    return out
