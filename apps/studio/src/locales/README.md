# Translation catalogues

Three complete languages are contractual (spec J.5.3): English, Portuguese,
Spanish. A key present in two of them is a defect, not a fallback.

## The rule

**The folder is the key's first dotted segment.**

    explore.mode_tree   ->  locales/explore/{en,pt,es}.json
    graph.legend_heat   ->  locales/graph/{en,pt,es}.json

That is the whole rule, and it has no exceptions. Given a key you know the
file without searching; given a file you know every key it may hold. Two
tests in `tests/test_studio_i18n.py` keep it true: one fails if a key is
filed under the wrong folder, the other if a folder is missing a language —
a missing translation hiding as a missing file.

Keys are flat and dotted inside the file. The loader (`../i18n.jsx`) globs
every folder and merges them back into one dictionary per language, so no
`t()` call site knows namespaces exist.

## Working on them

Use the tool rather than editing three files by hand the one mistake worth
engineering against is adding a key to two languages out of three, and `add`
cannot make it.

    python scripts/i18n.py map                    # what each namespace holds, and which views read it
    python scripts/i18n.py where explore.mode_tree
    python scripts/i18n.py add graph.reset --en "Reset" --pt "Zerar" --es "Reiniciar"
    python scripts/i18n.py rm graph.reset
    python scripts/i18n.py check                  # completeness, placement, unused hints

`add` creates the namespace folder when the key needs a new one, refuses a
partial set of languages, and refuses placeholders that differ between them
(`{n} of {max}` must stay `{n}` and `{max}` in all three, or the sentence
renders with a hole in it).

`map` is generated on demand and never written down: a hand-maintained map of
a moving catalogue lies within a month.

## What a namespace is

A namespace groups strings by **subject, not by screen.** They are shared on
purpose `common.*` is read by twelve components, `cap.*` by ten, and
`editor.*` serves both the node editor and the Ingest composer, because those
two are one editing surface with two entry points. Splitting by screen would
duplicate those strings and let the copies drift.

Run `python scripts/i18n.py map` to see the current namespaces, their sizes
and their readers.

## What is not translated

Node ids, titles, summaries, bodies, SQL and model output. Those are forest
content: a console that rewrote them would be lying about what is stored.
