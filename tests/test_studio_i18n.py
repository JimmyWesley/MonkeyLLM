"""The Studio ships three complete languages (spec J.5.3, criterion F.20).

"Complete" is a rule, not an intention, so it has to be checkable: these
tests load the per-namespace catalogues in
`src/locales/<namespace>/{en,pt,es}.json`, merge each language back into one
flat dictionary, and fail on the first key missing from any of them. A
fallback that silently renders English would make a missing translation
invisible exactly where it matters — in the language the operator actually
reads.

The namespace split (one folder per first dotted key segment, one file per
language inside it) exists so a translator working on one console area opens
one folder instead of a 700-key flat file. That only pays off if it stays
checkable, so this suite also asserts the two invariants the split depends
on: every key in a namespace folder actually belongs to that namespace, and
every namespace folder carries all three language files — a namespace that
gained a folder but not all three languages is a missing translation hiding
as a missing file.

The catalogues are plain JSON precisely so this suite (and any translation
tool) can read them without a JS toolchain — no node dependency in CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
LOCALES = STUDIO / "locales"
LANGS = ("en", "pt", "es")

# Keys are flat and dotted; anything else is a typo or a nested object that
# slipped in and would silently vanish from the interface.
KEY = re.compile(r"^[a-z0-9_.]+$")


def _namespaces() -> list[Path]:
    return sorted(p for p in LOCALES.iterdir() if p.is_dir())


def _dictionaries() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    for namespace in _namespaces():
        for lang in LANGS:
            path = namespace / f"{lang}.json"
            if not path.exists():
                continue
            entries = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(entries, dict), f"{path} must be one flat object"
            for key, value in entries.items():
                assert KEY.match(key), f"{namespace.name}/{lang}: malformed key {key!r}"
                assert isinstance(value, str), f"{namespace.name}/{lang}:{key} is not a string"
                assert key not in out[lang], f"{lang}: duplicate key {key!r} (in {namespace.name} too)"
                out[lang][key] = value
    return out


@pytest.fixture(scope="module")
def dicts():
    found = _dictionaries()
    assert set(found) == set(LANGS), "three languages are contractual"
    assert len(found["en"]) > 150, "the catalogue is suspiciously small"
    return found


def test_every_key_exists_in_every_language(dicts):
    reference = set(dicts["en"])
    for lang in ("pt", "es"):
        missing = sorted(reference - set(dicts[lang]))
        assert not missing, f"{lang} is missing {len(missing)} key(s): {missing[:10]}"


def test_no_language_carries_keys_the_others_lack(dicts):
    """A stray key is a rename that only landed in one file."""
    reference = set(dicts["en"])
    for lang in ("pt", "es"):
        extra = sorted(set(dicts[lang]) - reference)
        assert not extra, f"{lang} has keys English does not: {extra}"


def test_no_translation_is_left_empty(dicts):
    for lang, entries in dicts.items():
        blank = sorted(k for k, v in entries.items() if not v.strip())
        assert not blank, f"{lang} has empty strings: {blank}"


def test_placeholders_survive_translation(dicts):
    """`{who} will see {scope}` only works if every language kept the
    placeholders — a dropped one renders as a sentence with a hole in it."""
    for key, english in dicts["en"].items():
        expected = set(re.findall(r"\{(\w+)\}", english))
        for lang in ("pt", "es"):
            got = set(re.findall(r"\{(\w+)\}", dicts[lang][key]))
            assert got == expected, f"{lang}:{key} placeholders {got} != {expected}"


def test_every_used_key_is_defined(dicts):
    """Catches `t('acess.title')` at test time rather than at demo time."""
    used: set[str] = set()
    for path in STUDIO.rglob("*.jsx"):
        used |= set(re.findall(r"\bt\('([a-z0-9_.]+)'", path.read_text(encoding="utf-8")))
    undefined = sorted(used - set(dicts["en"]))
    assert not undefined, f"used but never defined: {undefined}"


def test_every_key_lives_in_its_own_namespace_folder():
    """A key in the wrong file is a key nobody will find.

    The namespace split only pays off if the first dotted segment of a key
    matches the folder it is filed under — otherwise a translator opening
    `explore/` for an `explore.*` key would never see a stray `graph.*` one
    sitting there instead.
    """
    offenders = []
    for namespace in _namespaces():
        prefix = f"{namespace.name}."
        for lang in LANGS:
            path = namespace / f"{lang}.json"
            if not path.exists():
                continue
            entries = json.loads(path.read_text(encoding="utf-8"))
            for key in entries:
                if not key.startswith(prefix):
                    offenders.append(f"{namespace.name}/{lang}.json: {key!r}")
    assert not offenders, f"keys filed under the wrong namespace: {offenders}"


def test_every_namespace_has_exactly_the_three_languages():
    """A namespace folder is either complete or it is a hidden gap.

    A namespace that gained a folder but not all three language files is a
    missing translation disguised as a missing file — `_dictionaries()`
    would skip it silently, so this has to be checked on the directory
    listing itself.
    """
    offenders = {}
    expected = {f"{lang}.json" for lang in LANGS}
    for namespace in _namespaces():
        present = {p.name for p in namespace.iterdir()}
        if present != expected:
            offenders[namespace.name] = sorted(present)
    assert not offenders, f"namespace folders not exactly {sorted(expected)}: {offenders}"


def test_no_dark_only_colour_classes_in_components():
    """A hard-coded palette class is how a light theme regresses (J.5.3).

    Every colour must arrive through a semantic token, so the same markup is
    correct in both themes without a `dark:` variant anywhere.
    """
    offenders = []
    palette = re.compile(
        r"\b(?:bg|text|border|ring|divide|from|to)-"
        r"(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
        r"emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b"
    )
    for path in STUDIO.rglob("*.jsx"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if palette.search(line):
                offenders.append(f"{path.name}:{n}")
    assert not offenders, f"raw palette colours (theme-blind): {offenders}"


def test_api_defines_no_method_twice():
    """A duplicate key in `api.js` replaces the first silently (J.5).

    This is not hypothetical: a maintenance endpoint was added as `health`,
    the Station's own liveness probe was already called `health`, and the
    later definition won — so the sign-in screen asked the wrong endpoint
    whether a password door existed, got a 403, and stopped offering the
    password form. Nothing failed loudly; the door simply disappeared.
    """
    api = (STUDIO / "api.js").read_text(encoding="utf-8")
    body = api[api.index("export const api = {"):]
    names = re.findall(r"^  ([a-zA-Z][a-zA-Z0-9_]*):", body, flags=re.M)
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"api.js defines these more than once: {duplicates}"
    assert len(names) > 15, "the parser found suspiciously few methods"
