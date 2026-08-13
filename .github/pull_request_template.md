<!--
Thanks for the pull request. The checklist is short and the first item is the
one that matters most — it is what keeps MonkeyLLM's dual licensing possible.
See CONTRIBUTING.md for why.
-->

## What this changes



## Why



## Checklist

- [ ] I have read [CONTRIBUTING.md](../CONTRIBUTING.md) and I submit this
      contribution under **Apache-2.0**, on every path it touches —
      including `apps/`, which the project distributes under AGPL-3.0-only
      and may also license commercially.
- [ ] Every commit is signed off (`git commit -s`).
- [ ] `python -m pytest -q` passes.
- [ ] If this changes a contract (primitive semantics, budgets, error codes,
      index headings), the spec was versioned first.
- [ ] New source files carry an SPDX header for the tree they live in, and
      `src/monkeyllm/` still imports nothing from `apps/`.
