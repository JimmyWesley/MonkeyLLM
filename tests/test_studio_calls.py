# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The console's primitive calls match the primitives' signatures (J.5).

The Studio is a REST client: `POST /v1/forests/{f}/{primitive}` with a JSON
body, and the body IS the call's keyword arguments (`getattr(scoped, name)
(**payload)`). So a console that sends the right *content* under the wrong
*shape* fails at the dispatcher with a Python TypeError shown to an
operator — which is how branch creation shipped: `plant` takes one `node`
object and the dialog sent the passport's fields flat.

Nothing in the Python suite could see it. Those tests exercise the wire
contract directly and were correct; the console is JavaScript and there is
no JS harness here. Reading the source is what is left, and it is the same
trick `test_studio_i18n` already uses for the same reason: the catalogues
and the call sites are both plain text, and CI has no node.

Only literal call sites are reachable. `Playground` passes the primitive in
a variable by design (it exists to send arbitrary calls), so it is invisible
here and that is correct — it is the one console whose job is to be wrong on
purpose.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

# `api.call(forest, 'plant', {` and the prop-passed `call(forest, 'plant', {`
CALL = re.compile(r"\bcall\(\s*[A-Za-z_$][\w$.]*\s*,\s*'([a-z_]+)'\s*,\s*\{")


def _object_keys(text: str, start: int) -> tuple[list[str], bool]:
    """Top-level keys of the object literal whose `{` is at `start`.

    Returns (keys, has_spread). A hand-rolled scanner beats a regex here for
    one reason: nested objects and template strings are common in these
    payloads, and a regex that matched braces would read their keys as if
    they were the call's arguments.
    """
    depth = 0
    i = start
    keys: list[str] = []
    spread = False
    expect_key = False
    while i < len(text):
        c = text[i]
        if c in "\"'`":  # skip strings whole; escapes cannot end them
            quote = c
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        if c in "{[(":
            depth += 1
            expect_key = depth == 1 and c == "{"
            i += 1
            continue
        if c in "}])":
            depth -= 1
            if depth == 0:
                break
            i += 1
            continue
        if depth == 1 and c == ",":
            expect_key = True
            i += 1
            continue
        if depth == 1 and text.startswith("...", i):
            spread = True
            expect_key = False
            i += 3
            continue
        if depth == 1 and expect_key and (c.isalpha() or c == "_"):
            m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
            keys.append(m.group(0))
            expect_key = False
            i += m.end()
            continue
        i += 1
    return keys, spread


def _sites() -> list[tuple[Path, str, list[str], bool]]:
    out = []
    for path in sorted(STUDIO.rglob("*.jsx")) + sorted(STUDIO.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for m in CALL.finditer(text):
            keys, spread = _object_keys(text, m.end() - 1)
            out.append((path, m.group(1), keys, spread))
    return out


def _signature(primitive: str):
    from monkeyllm_station.policy import ScopedVine

    fn = getattr(ScopedVine, primitive, None)
    return None if fn is None else inspect.signature(fn)


def test_the_write_primitives_are_actually_covered():
    """A refactor that renamed `call`, or a scanner that quietly matched
    nothing, would otherwise make this suite pass by checking zero sites."""
    checked = {p for _, p, _, _ in _sites() if _signature(p) is not None}
    assert {"plant", "graft", "tend"} <= checked, (
        f"the console's write calls are not being checked; found {checked}")


def test_every_console_call_names_arguments_the_primitive_has():
    offenders = []
    for path, primitive, keys, _ in _sites():
        sig = _signature(primitive)
        if sig is None:
            # A composite (`answer`) or a host action (`ingest`) — dispatched
            # from a payload dict, not from a signature, so there is nothing
            # here to compare against. J.10/J.8 own those contracts.
            continue
        allowed = {p for p in sig.parameters if p != "self"}
        extra = [k for k in keys if k not in allowed]
        if extra:
            offenders.append(
                f"{path.relative_to(STUDIO)}: {primitive}({', '.join(keys)}) "
                f"— {extra} is not a parameter; it takes {sorted(allowed)}")
    assert not offenders, "\n".join(offenders)


def test_every_console_call_supplies_the_required_arguments():
    offenders = []
    for path, primitive, keys, spread in _sites():
        sig = _signature(primitive)
        if sig is None or spread:
            continue  # a spread may carry them; nothing to conclude statically
        required = [
            p.name for p in sig.parameters.values()
            if p.name != "self" and p.default is inspect.Parameter.empty
            and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        ]
        missing = [r for r in required if r not in keys]
        if missing:
            offenders.append(
                f"{path.relative_to(STUDIO)}: {primitive} is missing {missing}")
    assert not offenders, "\n".join(offenders)
