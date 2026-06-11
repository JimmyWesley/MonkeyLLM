# T02 — English normalization (PT -> EN)

status: todo
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

## Translate (PT -> EN)

- `docs/monkeyllm-spec-v0.2.md` — the normative spec (highest priority; the
  paper cites it). Keep section numbering (A.3.1, C.6b...) intact.
- `docs/monkeyllm-arquitetura.md`, `docs/monkeyllm-roadmap.md`,
  `docs/local-inference.md`.
- `CLAUDE.md` (agent guide).
- All code comments and docstrings under `src/monkeyllm/`, `demo/`, `bench/`,
  `scripts/`, `tests/`.
- CLI and print/log strings (e.g. `vine validate` output, bench runner prints,
  `scripts/junit_to_html.py` UI strings).
- Error `hint` strings in `src/monkeyllm/` (messages are already mostly EN —
  unify).
- Glossary to apply consistently (from the roadmap/paper): shout (grito),
  whisper (sussurro), trail (trilha), branch (galho), banana, forest dialect
  (dialeto), shortcut grafting, pheromone/heat.

## Do NOT translate

- `forest-fixture/` content and `scripts/build_fixture.py` corpus literals —
  PT test data wired to `answer_contains` assertions.
- `demo/questions*.json`, `bench/questions-v*.json` — same reason.
- The demo/bench **system prompts** stay PT for now (they drive a PT corpus
  with PT questions); add an English variant only as a separate, tested change.
- Node type/rel vocabulary of the forest dialect (`galho`, `parte-de`...) —
  it is *data schema*, changing it is a spec/contract change (out of scope).

## Acceptance criteria

- [ ] No Portuguese left in docs/, CLAUDE.md, comments, docstrings or CLI
      strings (spot-check: `grep -rn "ç\|ão\|õe" src/ docs/ bench/ scripts/ tests/`)
- [ ] Full test suite green after every batch (`pytest -q` — do not batch more
      than one module between runs)
- [ ] Spec section numbers and budgets unchanged (translation, not revision)
- [ ] tasks/README.md table updated

## Out of scope

Renaming identifiers, translating the fixture corpus, changing the forest
dialect vocabulary, any behavior change whatsoever.
