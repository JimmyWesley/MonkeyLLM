# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Error envelope per spec Part C: {error: {code, message, hint}}."""

from __future__ import annotations

E_NOT_FOUND = "E_NOT_FOUND"
E_SCHEMA = "E_SCHEMA"
E_FRONTMATTER = "E_FRONTMATTER"
E_READONLY = "E_READONLY"
E_QUERY_FORBIDDEN = "E_QUERY_FORBIDDEN"
# C.5.2 (v0.47): the guard decides what is forbidden, SQLite decides what
# is invalid. Reporting a mistyped column with the code for "you tried to
# write" makes a typo read as a policy denial — in the response, in the
# console and in the audit.
E_QUERY_INVALID = "E_QUERY_INVALID"
E_TIMEOUT = "E_TIMEOUT"
E_LOCKED = "E_LOCKED"
# C.14 (v0.56): a prune refused by what points at the node (or by a
# branch's children). Not E_SCHEMA — the call was well-formed; the forest's
# current shape is what says no, and the refusal carries that shape.
E_ANCHORED = "E_ANCHORED"
# C.15 (v0.58): the node moved and the waymark knows where. "It is not
# here" would be half the truth; `data.moved_to` is the other half — under
# a policy the host withholds it when the new address is out of the
# reader's scope, and the envelope collapses to the canonical not-found.
E_MOVED = "E_MOVED"
# C.12 (v0.52): the last resort. An unhandled path is a defect in the
# server, and served as a bare 500 with no code it becomes the caller's
# defect too — a model cannot tell it apart from its own bad argument, and
# the two demand opposite reactions.
E_INTERNAL = "E_INTERNAL"


class VineError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None,
                 data: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.hint = hint
        # C.14 (v0.56): structured facts a refusal carries beside its prose
        # (e.g. E_ANCHORED's anchor list). Merged into the envelope; never
        # allowed to shadow code/message/hint.
        self.data = data or {}

    def to_dict(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.hint:
            err["hint"] = self.hint
        for key, value in self.data.items():
            err.setdefault(key, value)
        return {"error": err}
