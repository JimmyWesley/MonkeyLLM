# T05 — Publication readiness (GitHub + paper)

status: todo
depends-on: T01 (results), T02 (English)

## Goal

Ship MonkeyLLM as a public repository people can understand, run and extend —
and assemble the paper's result set.

## Steps

1. Top-level `README.md` (English): thesis, architecture sketch, quickstart
   (pip/venv, `serve_llm.py`, demo run), the metrics story
   (hops/tokens-to-banana, banana precision), link to spec.
2. License decision + file (owner decides; Apache-2.0 is the ecosystem norm).
3. CI: `pytest -q` on push (GitHub Actions, Windows + Linux matrix; tests are
   already self-contained — fixtures build their own forests).
4. Repo hygiene: `pyproject.toml` metadata, `pip install monkeyllm` extras,
   secrets scan, strip local-only paths from docs.
5. Paper result set: Phase 1 bench table (monkey x topk x iter), sniff A/B
   (buried-facts set: 2/4 -> 4/4, -40% tokens), convergence curve (Phase 2).
6. Glossary table EN (shout, whisper, troop, banana...) — presented once,
   used freely after (roadmap Phase 4 guidance).

## Acceptance criteria

- [ ] Fresh clone + README quickstart reaches a passing demo run
- [ ] CI green on a clean runner
- [ ] No Portuguese in any public-facing text (T02 done)
- [ ] Results table reproducible from committed scripts

## Out of scope

monkeyllm.com product packaging (Docker Compose, R2 mirror) — separate task
when Phase 2 lands.
