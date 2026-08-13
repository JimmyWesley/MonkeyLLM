# T02 English normalization (PT -> EN)

status: done (2026-07-02) src/ + contract vocabulary DONE via spec v0.5;
normative spec v0.12, roadmap, local-inference translated; remaining PT
demo/bench print strings translated (mcp_demo.py, run_bench.py,
regrade.py). Protected PT test corpus/system prompts/archived spec
versions intentionally left untouched see "Do NOT translate" below.
owner: junior dev (translation pass), review by maintainer

## Goal

Make the public face of the project fully English for the paper and for the
GitHub launch without breaking tests or changing any contract.

## Context

The codebase grew bilingual: identifiers are mostly English, but comments,
docstrings, CLI/print strings and the normative docs are largely Portuguese.
The **test corpus is intentionally Portuguese** and must NOT be translated:
assertions match PT strings, and a PT corpus is also a feature (multilingual
navigation with bge-m3).

## Already done (2026-06-11, spec v0.5)

- **Contract vocabulary is English now** types, rels, `entity_kind`/`source`
  enums, index headings, anti-patterns (see spec v0.5 changelog table). The
  forests were rebuilt from the updated generators; never edit them in place.
- `src/monkeyllm/` is fully English (code, comments, docstrings, templates).
- Tests, `scripts/build_*.py` and demo code updated to the new tokens.

## Translated (PT -> EN) 2026-07-02

- `docs/monkeyllm-spec-v0.12.md` (now normative, superseding the v0.5
  reference below) full prose translation: Part A-F contract prose,
  changelog v0.1->v0.2, C.7.1/graft JSON example content. Section numbering
  (A.3.1, C.6b...) and every contract token kept intact Part G/H/I and
  C.6c onward were already English (written post-v0.5). Earlier archived
  spec versions (v0.1-v0.11) intentionally NOT touched historical record.
- `docs/monkeyllm-roadmap.md`, `docs/local-inference.md` full translation.
  `docs/monkeyllm-arquitetura.md` was already English.
- Remaining PT CLI/print strings in `examples/demo/mcp_demo.py`,
  `bench/run_bench.py`, `bench/regrade.py` translated (mirrored against
  `run_demo.py`'s already-English equivalents where applicable).
- Glossary applied consistently (from the roadmap/paper): shout, whisper,
  trail, branch, banana, forest dialect, shortcut grafting, pheromone/heat.

## Do NOT translate

- Note (2026-07-02): `forests/forest-fixture/` and `forests/bench-forest/`
  are now BOTH English-content corpora (renamed alongside spec v0.5's
  contract vocabulary see commit "vendas -> sales, conceitos ->
  concepts"), and `examples/demo/run_demo.py`'s SYSTEM_PROMPT + protocol
  strings are English to match. The rule below is kept for any future PT
  fixture/corpus, but nothing currently in the tree needs it.
- `tests/test_troop.py`'s scripted-chat fixtures reference stale PT node
  ids (`vendas/devolucoes-q1`, `conceitos/rag`) that no longer exist in the
  regenerated fixture dead since the rename above, harmless because the
  mocked `chat()` never actually resolves them against a real forest walk.
  Left untouched here (test data, out of T02's scope a stale-id cleanup
  is a separate, tiny task if anyone wants it).
- Any genuinely PT test corpus wired to `answer_contains` assertions, and
  any system prompt written specifically to drive one, would still be
  protected by this rule if one is added in the future.

## Acceptance criteria

- [x] No Portuguese left in docs/, CLAUDE.md, comments, docstrings or CLI
      strings, outside the protected PT test-corpus/system-prompt/archived-
      spec paths verified 2026-07-02: full-tree accented-character sweep
      excluding those paths returns only proper nouns (Grassé, Fábio,
      Amazônia) and one direct quote of archived spec prose (now updated to
      match the translated text it quotes, in T03)
- [x] Full test suite green after every batch (`pytest -q` run after the
      spec translation, after the roadmap/local-inference translation, and
      after the code-string batch 276/276 throughout)
- [x] Spec section numbers and budgets unchanged (translation, not
      revision diffed by section header, all A.1-I intact)
- [x] tasks/README.md table updated

## Out of scope

Renaming identifiers, translating the fixture corpus, any behavior change
whatsoever. (The dialect vocabulary change already happened spec v0.5 —
and is NOT part of this task; do not "fix" tokens you think look off.)
