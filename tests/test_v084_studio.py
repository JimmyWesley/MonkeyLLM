# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The v0.84 consoles (spec J.19.9, J.8.6, J.13.4, J.13.6.1, J.20, J.14).

The round gave the Studio four things it did not have: a place to configure
where a converted document's ORIGINAL goes (J.19), a door for the operator
whose corpus is already in a bucket (J.8.6), two long runs that stopped
being held-open requests (J.13.4's canopy build and J.13.6.1's scent pass),
and an inbound trigger whose authority is a signature and not a person
(J.20). Each one is a promise the console can quietly stop keeping: a
credential rendered back into a form, a list of stores hard-coded beside the
one the host answers with, a `fetch` of a payload route that may 302.

Studio has no test runner, so this follows `tests/test_v076_window.py`: the
criteria live in `apps/studio/check-storage.mjs` and
`apps/studio/check-bucket.mjs`, next to the code they describe, and are run
from here so they cannot quietly stop being true.

The boundary is F.137's. The checkers read the source and see the decision
layer — where a list comes from, what a submit puts on the wire, which
answer a number is printed from, whether a byte route is reached by a fetch
or by a navigation. A rendered table, a pointer on a button and a 302 want a
browser and a running Station, and are asserted nowhere here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
LANGS = ("en", "pt", "es")


def _run(checker: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(STUDIO / checker)],
                          capture_output=True, text=True, cwd=STUDIO)


def _locale(namespace: str, lang: str) -> dict:
    return json.loads((STUDIO / "src" / "locales" / namespace / f"{lang}.json")
                      .read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_storage_console_meets_its_criteria():
    r = _run("check-storage.mjs")
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run: a
    # checker that exits 0 because it stopped early is a passing test about
    # nothing.
    assert r.stdout.count("PASS") >= 25, r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_bucket_consoles_meet_their_criteria():
    r = _run("check-bucket.mjs")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("PASS") >= 30, r.stdout


def test_the_credential_is_write_only_in_the_console_too():
    """J.19.1, without a toolchain: the Storage tab never reads a secret
    back off an answer, and its form fields are its own state.

    The API answers `has_key` and nothing else, so a console that rendered
    `store.secret_key` would be rendering `undefined` today and a credential
    the day somebody "fixed" the route to return one."""
    src = (STUDIO / "src" / "views" / "storage.jsx").read_text(encoding="utf-8")
    assert "has_key" in src
    for forbidden in ("store.secret_key", "store.access_key",
                      "s.secret_key", "s.access_key", "data.secret_key"):
        assert forbidden not in src, forbidden
    # `null` is "keep what is stored" — the only way an editor that cannot
    # READ a value can leave it alone.
    assert "access_key: form.access_key || null" in src
    assert "secret_key: form.secret_key || null" in src


def test_no_console_fetches_a_payload_that_may_redirect():
    """J.14 (v0.84) + J.5.13. Above the proxy ceiling the payload route
    answers 302 to a presigned URL on a store's own origin, and this page is
    pinned to `connect-src 'self'` — so a credentialed fetch is refused by
    the page's own policy, and the repair is a top-level navigation rather
    than a CSP that is a function of the registry.

    The navigation is to the URL rule 5 hands back, never to the payload
    route itself: a top-level navigation carries no `Authorization` header —
    J.2 authenticates by header and never by cookie — so a bare link there
    answers 401 to everyone who clicks it.

    Asserted across the whole console and not only in the panel that gained
    the link: `api.payload` mints a blob, and the rule is about every caller
    of it."""
    src_dir = STUDIO / "src"
    callers = {p.relative_to(src_dir).as_posix()
               for p in src_dir.rglob("*.jsx")
               if "api.payload(" in p.read_text(encoding="utf-8")}
    # Two callers, and both are bounded to bytes that cannot redirect: the
    # `media:` image a reply cites (J.10.9) and the media node's own picture,
    # which an image is under the 6 MiB ceiling `view` and the describer
    # already agree on; and the download of a payload the digest gave a byte
    # count for, which is exactly what `local` means. A third caller is a
    # decision somebody has to make on purpose, so it fails here by name.
    assert callers == {"views/files.jsx", "design/markdown.jsx"}, callers
    md = (src_dir / "design" / "markdown.jsx").read_text(encoding="utf-8")
    assert "p.type.startsWith('image/')" in md
    files = (src_dir / "views" / "files.jsx").read_text(encoding="utf-8")
    assert "const remote = !local &&" in files
    assert "await api.payloadUrl(forest, d.id)" in files
    assert "window.open(url, '_blank', 'noopener')" in files
    # The route is never the href of anything: that was the first cut of
    # rule 5, and it is a 401 for every reader.
    assert "payloadHref" not in files
    assert "href={api.payload" not in files
    api_js = (src_dir / "api.js").read_text(encoding="utf-8")
    assert "payloadHref" not in api_js
    assert "Accept: 'application/json'" in api_js


def test_every_new_tab_and_console_is_nameable_in_the_address():
    """J.5.8, and v0.41's lesson: a tab whose value is not in `useRouteState`'s
    allow list writes an address the validator rejects, and the console snaps
    back to the default — which reads as the page closing itself."""
    ingest = (STUDIO / "src" / "views" / "Ingest.jsx").read_text(encoding="utf-8")
    allow = ingest[ingest.index("useRouteState('mode'"):]
    allow = allow[:allow.index("]")]
    for tab in ("'upload'", "'adopt'", "'bucket'", "'compose'", "'optimize'",
                "'storage'"):
        assert tab in allow, tab
    shell = (STUDIO / "src" / "components" / "Shell.jsx").read_text(encoding="utf-8")
    app = (STUDIO / "src" / "App.jsx").read_text(encoding="utf-8")
    icons = (STUDIO / "src" / "design" / "icons.jsx").read_text(encoding="utf-8")
    # A console the rail offers, the router cannot render and the icon table
    # does not know is three files disagreeing about one page.
    assert "{ key: 'notify', group: 'build', cap: 'admin' }" in shell
    assert "notify: Notify" in app
    assert "notify: Inbox" in icons


def test_the_new_strings_exist_in_every_language():
    """J.5.3: three languages are contractual. `scripts/i18n.py check` is the
    gate for the catalogue as a whole; this is the round's own keys, so a
    console shipped in English alone fails here with its own name on it."""
    for namespace, keys in (
        ("storage", ("storage.stores", "storage.binding", "storage.binding_next",
                     "storage.unmet", "storage.key_keep", "storage.key_pair",
                     "storage.reach_read_hint")),
        ("ingest", ("ingest.mode_bucket", "ingest.mode_storage",
                    "ingest.bucket_store", "ingest.bucket_curate_now_hint",
                    "ingest.bucket_content_cached", "ingest.bucket_content_inline",
                    "ingest.rescent_order", "ingest.rescent_limit",
                    "ingest.rescent_remaining", "ingest.dense_cancelled")),
        ("notify", ("notify.title", "notify.causes", "notify.sign_headers",
                    "notify.sign_refusal", "notify.secret_once")),
        ("gauntlet", ("gauntlet.job_progress", "gauntlet.build_cancelled")),
        ("files", ("files.original_open", "files.original_remote")),
        ("nav", ("nav.notify", "nav.notify.blurb")),
    ):
        for lang in LANGS:
            catalogue = _locale(namespace, lang)
            for key in keys:
                assert catalogue.get(key), f"{namespace}/{lang}: {key}"


def test_a_placeholder_survives_translation():
    """A key whose placeholder was dropped in one language renders the brace
    to the operator, which is how a translation says "nobody read me"."""
    for lang in LANGS:
        assert "{name}" in _locale("storage", lang)["storage.unmet"]
        assert "{name}" in _locale("storage", lang)["storage.editing"]
        assert "{n}" in _locale("ingest", lang)["ingest.rescent_remaining"]
        assert "{n}" in _locale("notify", lang)["notify.sign_skew"]
        for token in ("{done}", "{total}"):
            assert token in _locale("gauntlet", lang)["gauntlet.job_progress"]
