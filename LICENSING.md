# Licensing

MonkeyLLM ships under **two** licenses, split along the line the
architecture already draws: the engine is a contract meant to spread, and
the host is a product meant to be operated.

| Path | License | Why |
|---|---|---|
| `src/monkeyllm/` the engine, the 10 primitives, `harvest` | **Apache-2.0** | The MCP contract is the asset. Embed it, ship it, build on it; the explicit patent grant is what lets a company do that without a legal review. |
| `docs/`, `tests/`, `bench/`, `troop/`, `scripts/`, `examples/`, `forests/scripts/`, `paper/`, `deploy/` | **Apache-2.0** | The spec, the benchmark and the deployment glue are only useful if everyone can copy them. |
| `apps/station/` the Station (REST, MCP surface, governance) | **AGPL-3.0-only** | Self-hosting stays completely free. Offering it as a managed service means opening your service stack. |
| `apps/studio/` the Studio web console | **AGPL-3.0-only** | Same reason: it is the operated product, not the contract. |
| `apps/clipper/` the browser extension | **AGPL-3.0-only** | A client of the Station, distributed by it (spec J.15) — the same product, on the other side of the wire. |

The root [`LICENSE`](LICENSE) is Apache-2.0 and covers everything **except**
`apps/`. Each package under `apps/` carries its own `LICENSE`.

Every source file states its own license in an SPDX header, so a file that
travels away from this repository keeps its terms:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley
```

## The direction of the dependency is load-bearing

Apache-2.0 is one-way compatible with AGPL-3.0: an AGPL work may include
Apache-2.0 code, never the reverse. So the host may depend on the engine —
and the engine **must never import from `apps/`**.

That is already true architecturally: spec Part J specifies the Station as a
*privileged client* of the engine, not an extension ("the engine gains
nothing, loses nothing"). The license split now makes the same boundary a
legal one, which means a violation is no longer only a design smell.

## If you host a modified Station

AGPL-3.0 section 13 applies to network use: if you modify the Station or the
Studio and let other people interact with it over a network, you must offer
those users the Corresponding Source of your modified version. Running an
**unmodified** copy for yourself or your organisation triggers nothing.

## Commercial licensing

The copyright is held by a single author, so the AGPL is not the only way to
get this software. If AGPL-3.0 does not fit you want to embed the Station
in a closed product, or offer it as a managed service without opening your
stack a commercial license is available. Contact the copyright holder.

## Contributing

Contributions come in under **Apache-2.0 on every path** — including
`apps/`, which this project distributes under AGPL-3.0-only. That inbound
licence is what keeps the dual licensing above possible: Apache-2.0 travels
one way into an AGPL tree, so a permissively licensed contribution can be
distributed under the AGPL *and* under commercial terms, while a
contribution accepted under AGPL alone could be distributed under neither
without its author's separate permission. It would leave a copyright holder
who never agreed to relicense, and the commercial option would quietly
disappear — one merged pull request at a time.

Every commit is also signed off (`git commit -s`) under the **Developer
Certificate of Origin**, and CI enforces it. The two do different jobs and
both are required: the DCO certifies where the code came from, the inbound
licence decides what the project may do with it. A sign-off alone would not
make the dual licensing possible.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the exact wording of both.
