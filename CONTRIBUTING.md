# Contributing to MonkeyLLM

Thank you for wanting to help. Two things are asked of every pull request —
an **inbound licence** and a **sign-off** — and this file explains both,
because one of them is unusual enough to deserve a paragraph rather than a
checkbox.

## The inbound licence

> Unless you explicitly state otherwise, any Contribution you intentionally
> submit for inclusion in MonkeyLLM is licensed under the **Apache License,
> Version 2.0**, with no additional terms or conditions. This applies to
> **every path in the repository, including `apps/`**, which the project
> distributes under AGPL-3.0-only.
>
> You grant the project the right to distribute your Contribution under
> AGPL-3.0-only as part of `apps/`, and under separate commercial terms.

That last sentence is the whole point, so it is stated plainly instead of
buried: **your contribution may end up in a commercially licensed build.**

### Why it has to work this way

MonkeyLLM is dual-licensed (see [LICENSING.md](LICENSING.md)): Apache-2.0
for the engine, AGPL-3.0-only for the host under `apps/`. Dual licensing is
only possible while a single copyright holder can speak for the whole work.

A contribution accepted under AGPL alone would leave behind a second
copyright holder who never agreed to any of that — and from that commit on,
the AGPL parts could not be offered under commercial terms without their
permission or the removal of their code. Ten contributors over two years
makes that impossible in practice. The commercial option would disappear in
silence, one merged pull request at a time, and nobody would notice until
somebody asked to buy a licence.

Apache-2.0 inbound solves it cleanly. Apache-2.0 is one-way compatible with
the AGPL, so a permissively licensed contribution may travel into the AGPL
tree; the reverse may not. You keep your copyright — this is a licence
grant, not an assignment.

## The sign-off

Every commit carries a `Signed-off-by` line:

```
git commit -s -m "your message"
```

The line certifies provenance under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/) —
that the work is yours to submit, and that you understand it is public and
recorded:

```
By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the
    right to submit it under the open source license indicated in the file; or
(b) The contribution is based upon previous work that, to the best of my
    knowledge, is covered under an appropriate open source license and I have
    the right under that license to submit that work with modifications,
    whether created in whole or in part by me, under the same open source
    license (unless I am permitted to submit under a different license), as
    indicated in the file; or
(c) The contribution was provided directly to me by some other person who
    certified (a), (b) or (c) and I have not modified it.
(d) I understand and agree that this project and the contribution are public
    and that a record of the contribution (including all personal information
    I submit with it, including my sign-off) is maintained indefinitely and
    may be redistributed consistent with this project or the open source
    license(s) involved.
```

The DCO certifies **where the code came from**. The inbound licence above
decides **what the project may do with it**. They are different statements
and both are required; a sign-off alone would not make the dual licensing
possible.

A CI check enforces the sign-off. If you forget it:

```
git commit --amend -s        # last commit
git rebase --signoff main    # a whole branch
git push --force-with-lease
```

## Versions, and what a tag means

Three numbers, and until `1.0.0` only the first two carry a promise.

| Position | Meaning |
|---|---|
| **major** | `0` until this project says otherwise. It is not `1` yet, and that is a statement: see below. |
| **minor** | the spec version this release implements. `0.81.x` implements `docs/monkeyllm-spec-v0.81.md`. A contract change therefore always moves this number, because a contract change always cuts a spec first. |
| **patch** | every release that cuts no spec — a fix, a console, a document, a measurement. |

**While the major is `0`, a patch may break you.** That is the honest reading
of a `0.x` version and it is stated here rather than left to be discovered:
this project reserves the right to change behaviour in a patch release, and
the version number alone is not a compatibility promise. What *is* promised
is that the spec is the truth — if behaviour changed, a spec version says
so, and if it changed without one, that is a defect worth reporting.

The one place this rule has teeth is an extension's `station_compat`
(spec L.1). Because a patch may break, an extension SHOULD pin to the minor
it was written and tested against:

```json
"station_compat": ">=0.81,<0.82"
```

A wider range such as `>=0.81,<1.0` is allowed and means what it says — *I
accept whatever the next minor does to me*. It is the right choice for an
extension with a tiny surface and the wrong one for anything that reads a
seam closely.

### Releasing

The tag is the only thing anybody types, and it must equal `version` in
`pyproject.toml` — the release workflow's first job refuses the pair when
they disagree, in ten seconds, before the suite has run. PyPI never lets a
published version mean anything else and never lets it be replaced, so the
sequence is:

1. bump `version` in `pyproject.toml`, in a commit whose subject is
   `Release <version>`;
2. merge to `main`;
3. `git tag v<version> && git push origin v<version>`;
4. approve the `pypi` environment when the run asks — every check has
   already run by then, and that approval is the irreversible step.

Do not skip a number. A gap in the PyPI index reads as a release that was
published and withdrawn, which is a different and more alarming thing than
a version that never existed.

## Before you open a pull request

- **The spec is the truth.** `docs/monkeyllm-spec-v0.49.md` is normative. A
  change to any contract — primitive semantics, budgets, error codes, index
  headings — needs a new spec version *before* the code.
- **The suite stays green.** `python -m pytest -q`.
- **English is the project's native language** — code, comments, tests,
  docs, CLI output. Contract tokens are English and are not translated.
- **The licence boundary is legal, not stylistic.** `src/monkeyllm/` must
  never import from `apps/`. Every new source file carries an SPDX header
  naming the licence of the tree it lives in.
- **Forests are generated, never edited.** Change the generator under
  `forests/scripts/` and rebuild.
- **Binaries never enter the forest git** — gitops versions `.md` only.

## Where contributions are easiest to accept

Everything outside `apps/` is already Apache-2.0 in both directions, so a
patch to the engine, the spec, the benchmark, the docs or the examples is
the least ceremonious thing you can send.

Patches to `apps/station/`, `apps/studio/` and `apps/clipper/` are welcome
too and follow the same rules — the inbound licence is simply doing more
work there, which is why it is written out above rather than assumed.

## Reporting instead of patching

A bug report is always welcome and carries none of this. If you would rather
describe a problem than write the fix, open an issue: a described bug is not
a contribution, and it is often the faster path for both of us.
