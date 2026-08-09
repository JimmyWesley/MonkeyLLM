"""The Studio ships three complete languages (spec J.5.3, criterion F.20).

"Complete" is a rule, not an intention, so it has to be checkable: these
tests parse `src/i18n.jsx` and fail on the first key missing from any
dictionary. A fallback that silently renders English would make a missing
translation invisible exactly where it matters — in the language the
operator actually reads.

Parsing the source rather than running a JS toolchain keeps this inside the
one suite that must stay green, with no node dependency in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
I18N = STUDIO / "i18n.jsx"

# 'some.key': 'value'  —  the only shape the dictionaries use.
ENTRY = re.compile(r"^\s*'([a-z0-9_.]+)':\s*'(.*)',\s*$")


def _dictionaries() -> dict[str, dict[str, str]]:
    """Split i18n.jsx into its `const <lang> = {...}` blocks."""
    text = I18N.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        start = re.match(r"^const (en|pt|es) = \{$", line)
        if start:
            current = start.group(1)
            out[current] = {}
            continue
        if current and line.startswith("}"):
            current = None
            continue
        if current:
            entry = ENTRY.match(line)
            if entry:
                out[current][entry.group(1)] = entry.group(2)
    return out


@pytest.fixture(scope="module")
def dicts():
    found = _dictionaries()
    assert set(found) == {"en", "pt", "es"}, "three languages are contractual"
    assert len(found["en"]) > 150, "the parser found suspiciously few keys"
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
        if path.name == "i18n.jsx":
            continue
        used |= set(re.findall(r"\bt\('([a-z0-9_.]+)'", path.read_text(encoding="utf-8")))
    undefined = sorted(used - set(dicts["en"]))
    assert not undefined, f"used but never defined: {undefined}"


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
