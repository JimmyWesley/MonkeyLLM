# Part J (DRAFT) — Station: self-host, governance, and scoped access

> **STATUS: DRAFT — not normative.** This document is written in the spec's
> voice so it can be folded, ideally verbatim, into the first spec version
> released after v0.13 lands. Until then the spec in force remains the
> newest committed `docs/monkeyllm-spec-v*.md`. Contract rule applies: no
> Part J code ships before Part J is normative.

**Motivation.** Forests today are single-operator: whoever owns the
filesystem owns everything. Corporate deployment needs the Supabase shape —
an untouched engine wrapped by a host that adds identity, policy, audit,
and a friendly surface (web UI, REST, MCP) — so that *people* can be given
governed access to forests without ever holding the filesystem.

**Design invariants (inherited, non-negotiable):**

- The engine (`src/monkeyllm`) stays forest-agnostic and policy-free.
  Primitives' semantics/budgets/guards do not change per tenant.
- UIs and bots remain MCP/library **clients** (G.0). The Station is a
  client with privileges, not a plugin.
- Forests are content. Identity, tokens, and policies live in the
  **host registry**, never inside a forest.
- Every write stays a git commit inside the forest (A.3); binaries stay
  out of git (A.3.1).

---

## J.1 The Station (host)

A single self-hostable service that mounts a **forest registry** (a root
directory; every valid forest under it, as `vine serve --root` resolves
today) and exposes three surfaces over one enforcement core:

| Surface | Consumer | Transport |
|---|---|---|
| REST API | apps, scripts, integrations | HTTP/JSON, `/v1/...` |
| MCP | agents, IDEs, bots | streamable HTTP (existing `server.py` machinery) |
| Studio | humans | web UI served by the Station |

All three surfaces call the same `ScopedVine` (J.3). There is no
unscoped path from any surface to a `Vine` instance.

**Packaging:** one container image; `docker compose up` with two volumes
(`/forests`, `/registry`) is a complete deployment. No external database.

## J.2 Identity

- **Principals:** users (humans) and service tokens (machines).
- **Phase 1 authn:** static API keys (hashed in the registry).
- **Phase 2 authn:** OIDC (corporate SSO); JWT claims map to a principal.
- **Roles are per-forest:** `owner`, `gardener` (ingest + writes),
  `ranger` (maintenance), `reader`, plus explicit policy grants (J.3).
  A principal may hold different roles on different forests.

## J.3 Policy and enforcement (the "RLS" of forests)

**Policy object** (registry-stored, deny-by-default):

```yaml
principal: <id>
forest:    <forest-id>
allow:     [branch/prefix/, other/branch/]   # subtree grants
deny:      [branch/prefix/secret/]           # carve-outs, win over allow
caps:      [read, write, query, tend, ingest, admin]
datasets:                                     # optional, per dataset node
  sales/report-q1-2026: {tables: [sales]}
```

**`ScopedVine`** wraps the ten primitives + `harvest` with exactly one
rule per primitive. The unit of scoping is the node id prefix (the branch
path) — the hierarchy is the policy surface:

| Primitive | Enforcement |
|---|---|
| `locate`, `scan` | results filtered to allowed subtrees before budgets/truncation are applied |
| `sniff` | search space restricted to allowed subtrees |
| `look`, `pick` | node id must be inside an allowed subtree, else `E_NOT_FOUND` |
| `move` | edges that cross the scope boundary are omitted (an edge must not leak a forbidden node's existence) |
| `harvest` | inherits all of the above (it is a composite) |
| `query` | requires `query` cap + readable dataset node; optional table allow-list checked against the parsed statement (read-only guard C.9 unchanged) |
| `tend` | requires `tend` cap + writable dataset node (C.10 guards unchanged) |
| `plant`, `graft` | require `write` cap; target path inside an allowed subtree |

Two deliberate consequences, stated normatively: a scoped `locate` MUST
return the same shape (budgets, `truncated`) as an unscoped one — the
caller cannot distinguish "filtered" from "absent"; and `E_NOT_FOUND` for
an out-of-scope node MUST be byte-identical to the genuinely-missing case
(no existence oracle).

## J.4 Audit

- **Writes:** already git commits per forest; the Station annotates the
  commit message with the acting principal (`station(<principal>): ...`),
  same pattern as `ranger(promote|prune)`.
- **Reads:** every scoped call logs `(principal, forest, primitive, args
  digest, result size, timestamp)` to the host registry — the existing
  telemetry/session layer extended with principal identity.
- **Studio** renders both streams as the audit log; git history stays the
  source of truth for writes.

## J.5 Studio (web UI)

Consoles, all speaking REST to the Station: forest browser (tree +
passport + body + links), search console (locate/sniff playground),
dataset console (query manual, read-only SQL runner, `tend` forms),
ingestion console (adopt/sync runs, converter status, curation review
queue for 0.3-confidence edge proposals), trails dashboard (heat,
shortcuts, promote/prune history), governance console (members, roles,
policies, tokens, audit), health (Ranger reports, snapshots).

## J.6 Out of scope for Part J

- Engine changes of any kind (contracts, budgets, ranking).
- Per-node (finer than branch) ACLs — revisit only with a concrete need.
- Multi-writer forests / distributed writes (single-writer lock stands).
- Billing/metering beyond per-token quotas.

## J.7 Acceptance criteria (draft F.18)

1. A fresh `docker compose up` + one API key yields a working Studio,
   REST, and MCP against an example forest registry.
2. A principal scoped to `projects/` cannot obtain the id, title, summary,
   body, edge, or snippet of any node outside `projects/` through ANY
   surface or primitive (leak suite: one test per primitive per surface).
3. Scope filtering precedes budgeting (no truncation oracle).
4. All writes through the Station carry the principal in the commit
   message; the audit log reconstructs any answer's full trail.
5. The engine test suite passes unchanged (zero engine edits).
