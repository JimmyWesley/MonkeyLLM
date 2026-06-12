# T02 — English normalization (PT -> EN)

status: in progress (src/ + contract vocabulary DONE via spec v0.5; docs remain)
owner: junior dev (translation pass), review by maintainer

## Goal

Make the public face of the project fully English — for the paper and for the
GitHub launch — without breaking tests or changing any contract.

## Context

The codebase grew bilingual: identifiers are mostly English, but comments,
docstrings, CLI/print strings and the normative docs are largely Portuguese.
The **test corpus is intentionally Portuguese** and must NOT be translated:
assertions match PT strings, and a PT corpus is also a feature (multilingual
navigation with bge-m3).

## Already done (2026-06-11, spec v0.5)

- **Contract vocabulary is English now** — types, rels, `entity_kind`/`source`
  enums, index headings, anti-patterns (see spec v0.5 changelog table). The
  forests were rebuilt from the updated generators; never edit them in place.
- `src/monkeyllm/` is fully English (code, comments, docstrings, templates).
- Tests, `scripts/build_*.py` and demo code updated to the new tokens.

## Translate (PT -> EN) — remaining

- `docs/monkeyllm-spec-v0.5.md` PT prose sections — the normative spec
  (highest priority; the paper cites it). Keep section numbering (A.3.1,
  C.6b...) and the v0.5 contract tokens intact. Earlier spec versions are
  archived: do not touch.
- `docs/monkeyllm-arquitetura.md`, `docs/monkeyllm-roadmap.md`,
  `docs/local-inference.md`.
- Remaining PT comments/strings under `examples/demo/`, `bench/`, `scripts/`, `tests/`
  (e.g. demo runner prints like "GRITO: atalho ...").
- Glossary to apply consistently (from the roadmap/paper): shout (grito),
  whisper (sussurro), trail (trilha), branch (galho), banana, forest dialect
  (dialeto), shortcut grafting, pheromone/heat.

## Do NOT translate

- `forests/forest-fixture/` content and `forests/scripts/build_fixture.py` corpus literals —
  PT test data wired to `answer_contains` assertions.
- `examples/demo/questions*.json`, `bench/questions-v*.json` — same reason.
- The demo/bench **system prompts** stay PT for now (they drive a PT corpus
  with PT questions); add an English variant only as a separate, tested change.
- The PT corpus **tags** (`["conceito"]`, `["evento"]`...) — they are free
  content vocabulary searched by locate over PT questions, not contract.

## Acceptance criteria

- [ ] No Portuguese left in docs/, CLAUDE.md, comments, docstrings or CLI
      strings (spot-check: `grep -rn "ç\|ão\|õe" src/ docs/ bench/ scripts/ tests/`)
- [ ] Full test suite green after every batch (`pytest -q` — do not batch more
      than one module between runs)
- [ ] Spec section numbers and budgets unchanged (translation, not revision)
- [ ] tasks/README.md table updated

## Out of scope

Renaming identifiers, translating the fixture corpus, any behavior change
whatsoever. (The dialect vocabulary change already happened — spec v0.5 —
and is NOT part of this task; do not "fix" tokens you think look off.)
