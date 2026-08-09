# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Token estimation and budget enforcement.

Phase 0 uses a deterministic heuristic (~4 chars/token, tuned for
PT/EN markdown). The contract that matters is: budgets are enforced
and truncation is ALWAYS explicit (`truncated: true`), never silent.
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def estimate_payload_tokens(payload: Any) -> int:
    return estimate_tokens(json.dumps(payload, ensure_ascii=False, default=str))


def truncate_text(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[: max_tokens * CHARS_PER_TOKEN].rstrip() + "…"


def shrink_list_to_budget(payload: dict, list_key: str, budget: int) -> dict:
    """Drop tail items from payload[list_key] until payload fits the budget.

    Sets payload["truncated"] = True when anything was dropped.
    """
    items = payload.get(list_key) or []
    while items and estimate_payload_tokens(payload) > budget:
        items.pop()
        payload["truncated"] = True
    return payload
