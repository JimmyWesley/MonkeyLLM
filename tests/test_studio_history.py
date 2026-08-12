# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The runs Ask kept, and where they are allowed to be (spec J.5.9, F.35).

A run carries the material the model was given — node bodies, read under a
grant. That is what makes the history worth having (an answer without its
material is the markdown download) and it is also what makes where it lives
a governance question rather than a preference: it MUST stay in the browser
that asked, keyed by principal and forest, and go when the credential goes.

Read from the source, like `test_studio_calls` and `test_studio_routes`: the
console is JavaScript, there is no JS harness in this suite, and CI has no
node. So what is checked here is the architecture the rule depends on — no
network, no second store, no address — while the behaviour is F.35.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
HISTORY = STUDIO / "history.js"
ASK = STUDIO / "views" / "Ask.jsx"
API = STUDIO / "api.js"
LANGS = ("en", "pt", "es")

NEW_KEYS = (
    "ask.history_title",
    "ask.history_local",
    "ask.history_bound",
    "ask.history_holding",
    "ask.history_unavailable",
    "ask.history_empty",
    "ask.restored",
    "ask.restored_hint",
    "ask.run_again",
)


def _sources():
    for path in sorted(STUDIO.rglob("*.jsx")) + sorted(STUDIO.rglob("*.js")):
        yield path, path.read_text(encoding="utf-8")


def _function(text: str, signature: str) -> str:
    """One function, from its signature to its matching brace.

    Crude on purpose: these are assertions about which calls appear inside
    one function, and a JS parser to answer that would be a dependency this
    suite does not have. Brace counting is enough for the small, brace-
    balanced functions asserted on here.
    """
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(f"unterminated function: {signature}")


def test_a_run_never_leaves_the_browser():
    """The whole rule in one assertion: the store makes no request. A history
    that needed the Station would be a slower copy of something the Station
    does not have, and would put a grant's worth of node bodies somewhere
    nobody audited."""
    text = HISTORY.read_text(encoding="utf-8")
    assert "fetch(" not in text
    assert "api.js" not in text, "the run store imports the API client"
    assert not re.search(r"\bXMLHttpRequest\b|\bnavigator\.sendBeacon\b", text)


def test_the_panel_reads_the_store_and_not_the_host():
    """Restoring shows a record, so it cannot be a call (J.5.9). The regression
    guarded here is a `restore` that re-asks the question to "refresh" it —
    which spends a model call to destroy the thing being restored."""
    text = ASK.read_text(encoding="utf-8")
    body = _function(text, "async function restore(")
    assert "api." not in body, "restoring a run calls the host"
    assert "loadRun(" in body
    # Parameters as sent, or "ask again" asks a different question.
    for setter in ("setK(", "setHybrid(", "setHops(", "setQuestion("):
        assert setter in body, f"restore does not put back {setter[:-1]}"


def test_runs_are_kept_by_principal_and_by_forest():
    """A browser is shared furniture and a grant is per forest (J.3), so the
    scope is part of the key rather than a filter applied afterwards."""
    text = HISTORY.read_text(encoding="utf-8")
    assert "createIndex('scope', ['principal', 'forest', 'ts'])" in text
    assert "if (!principal || !forest) return null" in text, (
        "a run with no principal would be readable by the next one")


def test_signing_out_discards_them():
    """`clearKey` alone is not enough: the bodies stay on disk, merely
    unlisted. And the drop belongs to signing out and not to any lost
    credential — a Station briefly unreachable must not wipe a history."""
    api = API.read_text(encoding="utf-8")
    assert "export const signOut" in api
    assert "dropEverything()" in _function(api, "export const signOut")
    clear_key = next(line for line in api.splitlines() if "export const clearKey" in line)
    assert "dropEverything" not in clear_key

    shell = (STUDIO / "components" / "Shell.jsx").read_text(encoding="utf-8")
    assert "signOut()" in shell
    assert not re.search(r"clearKey\(\);\s*location\.reload", shell), (
        "a sign-out path that leaves the kept runs behind (J.5.9)")


def test_only_one_store_and_never_the_small_one():
    """`localStorage` holds about five megabytes, synchronously, as strings.
    One answer with its material can be a fifth of that, so keeping runs
    there would serialise half a megabyte on the main thread after every
    question and then start failing at around the tenth."""
    offenders = [
        str(path.relative_to(STUDIO)) for path, text in _sources()
        if path != HISTORY and "indexedDB" in text
    ]
    assert not offenders, f"{offenders} open a second run store"
    assert not re.search(r"localStorage\.\w+\(", HISTORY.read_text(encoding="utf-8"))


def test_the_bound_is_a_number_and_it_is_said_out_loud():
    """Silent eviction is C.6's truncation rule in a different costume: what
    was dropped is said, or a partial history reads as a complete one."""
    text = HISTORY.read_text(encoding="utf-8")
    assert re.search(r"export const MAX_RUNS = \d+", text)
    assert re.search(r"export const MAX_BYTES = ", text)
    ask = ASK.read_text(encoding="utf-8")
    assert "MAX_RUNS" in ask, "the console never states the bound it keeps"
    assert "ask.history_bound" in ask


def test_a_run_has_no_address():
    """J.5.8 made the console's places linkable; a run is not one. An address
    naming a run resolves for its author and is broken for everybody else,
    because the record exists in one browser."""
    router = (STUDIO / "router.js").read_text(encoding="utf-8")
    assert "run" not in re.findall(r"'(\w+)'", router), (
        "the address grammar names a run (J.5.9)")
    ask = ASK.read_text(encoding="utf-8")
    assert "hrefFor" not in _function(ask, "async function restore("), (
        "restoring a run writes an address")


def test_the_history_speaks_three_languages():
    """J.5.3: a missing translation is a defect, not a fallback. The i18n
    suite already proves the catalogues match each other; this proves the
    keys this feature reads are in them at all."""
    for lang in LANGS:
        path = STUDIO / "locales" / "ask" / f"{lang}.json"
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in NEW_KEYS if key not in catalogue]
        assert not missing, f"{path.name} is missing {missing}"


def test_storage_failure_is_not_a_failed_ask():
    """Private browsing, a refused quota, storage off by policy: the answer on
    screen does not depend on any of it, so the keep is fire-and-forget and
    the list reports `ok` rather than raising."""
    ask = ASK.read_text(encoding="utf-8")
    assert re.search(r"saveRun\([^;]*\)\.catch\(", ask, re.S), (
        "a storage error can reach the ask's failure path")
    history = HISTORY.read_text(encoding="utf-8")
    assert "return { ok: false, runs: [], bytes: 0 }" in history


# -- what a failed hop is allowed to say (J.10.5, v0.47) ---------------------


def _path_component() -> str:
    src = ASK.read_text(encoding="utf-8")
    start = src.index("function Path(")
    return src[start:src.index("\nfunction ", start + 1)]


def test_a_failed_hop_shows_the_message_and_not_only_the_code():
    """The code alone rendered a guessed table and a guessed column as the
    same word twice. The engine had already answered both."""
    path = _path_component()
    assert "h.out?.message" in path
    assert "hop_error" in path  # the code is still there beside it


def test_the_hop_message_gets_its_own_line():
    """The hop row truncates its arguments to stay one line; a message
    appended to it would be the part that disappears."""
    path = _path_component()
    message_block = path[path.index("h.out?.message"):]
    assert "basis-full" in message_block[:400]
