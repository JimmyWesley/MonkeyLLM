#!/usr/bin/env python3
"""Work on the Studio's translation catalogues without hand-editing JSON.

The catalogues are `apps/studio/src/locales/<namespace>/{en,pt,es}.json`, and
the rule is mechanical: **the folder is the key's first dotted segment**. So
`explore.mode_tree` lives in `locales/explore/`, and finding a key never
needs a search.

What still needed a tool is the *writing*. Three languages are contractual
(spec J.5.3): a key added to two of them is a defect, and the suite will say
so — but only after the fact, and only if somebody ran it. Adding a key
should be one command that cannot forget a language, which is what `add` is.

    python scripts/i18n.py map                 what each namespace is for
    python scripts/i18n.py where explore.mode_tree
    python scripts/i18n.py add graph.reset --en "Reset" --pt "Zerar" --es "Reiniciar"
    python scripts/i18n.py rm graph.reset
    python scripts/i18n.py check

Stdlib only, like every other script here: it runs in a checkout with no
environment prepared.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio" / "src"
LOCALES = STUDIO / "locales"
LANGS = ("en", "pt", "es")

KEY_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")
# `t('some.key')` — the literal calls. Template calls (`t(\`nav.${k}\`)`) are
# deliberately not matched: they are real and legitimate, and pretending to
# resolve them is how an "unused key" report starts lying.
LITERAL_USE = re.compile(r"\bt\('([a-z0-9_.]+)'")
TEMPLATE_USE = re.compile(r"\bt\(`([a-z0-9_.]+)\$\{")


def namespaces() -> list[str]:
    return sorted(p.name for p in LOCALES.iterdir() if p.is_dir())


def load(namespace: str, lang: str) -> dict[str, str]:
    path = LOCALES / namespace / f"{lang}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(namespace: str, lang: str, entries: dict[str, str]) -> None:
    path = LOCALES / namespace / f"{lang}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(sorted(entries.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def catalogue(lang: str) -> dict[str, str]:
    """Every namespace merged, the way the console sees it."""
    out: dict[str, str] = {}
    for ns in namespaces():
        out.update(load(ns, lang))
    return out


def used_keys() -> tuple[set[str], set[str]]:
    """(literal keys, template prefixes) across every component."""
    literal: set[str] = set()
    prefixes: set[str] = set()
    for path in STUDIO.rglob("*.jsx"):
        if path.name == "i18n.jsx":
            continue
        text = path.read_text(encoding="utf-8")
        literal |= set(LITERAL_USE.findall(text))
        prefixes |= set(TEMPLATE_USE.findall(text))
    return literal, prefixes


# -- commands ---------------------------------------------------------------


def cmd_map(_args) -> int:
    """Which namespace holds what, and who reads it.

    Derived on demand rather than written down: a hand-maintained map of a
    moving catalogue is a map that lies within a month.
    """
    readers: dict[str, set[str]] = defaultdict(set)
    for path in STUDIO.rglob("*.jsx"):
        if path.name == "i18n.jsx":
            continue
        text = path.read_text(encoding="utf-8")
        for key in LITERAL_USE.findall(text):
            readers[key.split(".", 1)[0]].add(path.relative_to(STUDIO).as_posix())
        for prefix in TEMPLATE_USE.findall(text):
            readers[prefix.rstrip(".")].add(path.relative_to(STUDIO).as_posix())

    width = max(len(ns) for ns in namespaces())
    print(f"{'namespace':<{width}}  keys  read by")
    print("-" * (width + 8 + 40))
    for ns in namespaces():
        files = sorted(readers.get(ns, ()))
        shown = ", ".join(files) if files else "(nothing — see `check`)"
        print(f"{ns:<{width}}  {len(load(ns, 'en')):>4}  {shown}")
    return 0


def cmd_where(args) -> int:
    ns = args.key.split(".", 1)[0]
    found = False
    for lang in LANGS:
        entries = load(ns, lang)
        if args.key in entries:
            found = True
            print(f"{LOCALES.relative_to(REPO)}/{ns}/{lang}.json")
            print(f"  {lang}: {entries[args.key]}")
    if not found:
        print(f"no such key: {args.key}", file=sys.stderr)
        print(f"it would live in {LOCALES.relative_to(REPO)}/{ns}/", file=sys.stderr)
        return 1
    return 0


def cmd_add(args) -> int:
    if not KEY_RE.match(args.key):
        print(f"malformed key: {args.key!r} (want `namespace.some_name`)",
              file=sys.stderr)
        return 2
    values = {"en": args.en, "pt": args.pt, "es": args.es}
    # All three or none. A partial add is exactly the defect this exists to
    # prevent, so it is refused at the door rather than written and reported.
    missing = [lang for lang, v in values.items() if not v]
    if missing:
        print(f"every language is contractual; missing: {', '.join(missing)}",
              file=sys.stderr)
        return 2

    placeholders = {lang: set(re.findall(r"\{(\w+)\}", v)) for lang, v in values.items()}
    if len({frozenset(p) for p in placeholders.values()}) != 1:
        print("placeholders differ between languages: "
              + ", ".join(f"{l}={sorted(p)}" for l, p in placeholders.items()),
              file=sys.stderr)
        return 2

    ns = args.key.split(".", 1)[0]
    is_new = not (LOCALES / ns).is_dir()
    for lang in LANGS:
        entries = load(ns, lang)
        if args.key in entries and not args.force:
            print(f"{args.key} already exists in {ns}/{lang}.json "
                  f"({entries[args.key]!r}); pass --force to replace",
                  file=sys.stderr)
            return 1
        entries[args.key] = values[lang]
        save(ns, lang, entries)

    print(f"{args.key} -> {LOCALES.relative_to(REPO)}/{ns}/{{{','.join(LANGS)}}}.json"
          + ("  (new namespace)" if is_new else ""))
    return 0


def cmd_rm(args) -> int:
    ns = args.key.split(".", 1)[0]
    removed = 0
    for lang in LANGS:
        entries = load(ns, lang)
        if entries.pop(args.key, None) is not None:
            save(ns, lang, entries)
            removed += 1
    if not removed:
        print(f"no such key: {args.key}", file=sys.stderr)
        return 1
    print(f"removed {args.key} from {removed} language(s)")
    # An empty namespace folder is not tidied automatically: deleting
    # directories on somebody's behalf is the kind of help nobody asked for.
    if not load(ns, "en"):
        print(f"note: {ns}/ is now empty")
    return 0


def cmd_check(_args) -> int:
    """Everything the suite proves, plus the one thing it cannot.

    `test_studio_i18n.py` is the gate; this is the same information while you
    are still working, plus a *possibly* unused report the suite deliberately
    does not assert — template calls make certainty impossible, and a test
    that guesses would fail on correct code.
    """
    problems = 0
    cats = {lang: catalogue(lang) for lang in LANGS}
    reference = set(cats["en"])

    for lang in ("pt", "es"):
        missing = sorted(reference - set(cats[lang]))
        extra = sorted(set(cats[lang]) - reference)
        if missing:
            problems += 1
            print(f"{lang}: missing {len(missing)} key(s): {missing[:8]}")
        if extra:
            problems += 1
            print(f"{lang}: has {len(extra)} key(s) English lacks: {extra[:8]}")

    for ns in namespaces():
        files = sorted(p.name for p in (LOCALES / ns).glob("*.json"))
        if files != sorted(f"{lang}.json" for lang in LANGS):
            problems += 1
            print(f"{ns}: language files are {files}")
        for lang in LANGS:
            stray = [k for k in load(ns, lang) if k.split(".", 1)[0] != ns]
            if stray:
                problems += 1
                print(f"{ns}/{lang}.json: keys belonging elsewhere: {stray[:8]}")

    literal, prefixes = used_keys()
    undefined = sorted(literal - reference)
    if undefined:
        problems += 1
        print(f"used in components but never defined: {undefined[:8]}")

    unused = sorted(
        k for k in reference
        if k not in literal and not any(k.startswith(p) for p in prefixes))
    if unused:
        print(f"\npossibly unused ({len(unused)}) — template calls make this a "
              f"hint, not a verdict:\n  {', '.join(unused[:12])}"
              + (" …" if len(unused) > 12 else ""))

    if problems:
        print(f"\n{problems} problem(s)")
        return 1
    print(f"\nok — {len(reference)} keys x {len(LANGS)} languages "
          f"across {len(namespaces())} namespaces")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="i18n", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("map", help="what each namespace holds and who reads it")

    p_where = sub.add_parser("where", help="locate a key and show its three values")
    p_where.add_argument("key")

    p_add = sub.add_parser("add", help="add a key to all three languages at once")
    p_add.add_argument("key")
    for lang in LANGS:
        p_add.add_argument(f"--{lang}", required=True, help=f"{lang} text")
    p_add.add_argument("--force", action="store_true", help="replace if present")

    p_rm = sub.add_parser("rm", help="remove a key from every language")
    p_rm.add_argument("key")

    sub.add_parser("check", help="completeness, placement, and unused hints")

    args = ap.parse_args(argv)
    return {"map": cmd_map, "where": cmd_where, "add": cmd_add,
            "rm": cmd_rm, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
