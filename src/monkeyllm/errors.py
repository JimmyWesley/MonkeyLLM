# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Error envelope per spec Part C: {error: {code, message, hint}}."""

from __future__ import annotations

E_NOT_FOUND = "E_NOT_FOUND"
E_SCHEMA = "E_SCHEMA"
E_FRONTMATTER = "E_FRONTMATTER"
E_READONLY = "E_READONLY"
E_QUERY_FORBIDDEN = "E_QUERY_FORBIDDEN"
E_TIMEOUT = "E_TIMEOUT"
E_LOCKED = "E_LOCKED"


class VineError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.hint:
            err["hint"] = self.hint
        return {"error": err}
