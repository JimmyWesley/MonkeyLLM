# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.16 — what an author is handed, derived from the definitions.

Rule 1 is the whole of this module: **prose is written, schemas are
derived**. The text that teaches lives in `docs/extending/`, where a person
wrote it and anyone reads it without running anything. Everything here is
generated from the definitions themselves — the manifest's own JSON schema,
the seam contracts of L.3, the role kinds of L.6 — because a transcribed
schema is a schema that lies the first time a seam is added, silently, to
exactly the person who has no other source.

The test of this file is therefore not that its output looks right: it is
that adding a seam to the catalogue changes the output with no second edit
(F.203).
"""

from __future__ import annotations

from monkeyllm.extensions.contracts import CONTRACTS, DECLARATIVE
from monkeyllm.extensions.manifest import (ATTRIBUTED_SEAMS, ROLE_KINDS,
                                           SEAMS, ConfigField, Manifest)
from monkeyllm.extensions.sources import (DEFAULT_UPLOAD_MAX_MB,
                                          TIER_SIGNED, TIER_UNVERIFIED,
                                          TIER_VERIFIED)


def _minor(version: str) -> str:
    """`0.81.0` -> `0.81`. The range an author should pin to."""
    parts = str(version).split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(version)


def _next_minor(version: str) -> str:
    """`0.81.0` -> `0.82`, the exclusive upper bound of that pin."""
    parts = str(version).split(".")
    try:
        return f"{parts[0]}.{int(parts[1]) + 1}"
    except (IndexError, ValueError):
        return str(version)


def schema(host_version: str) -> dict:
    """Everything an author's tooling needs, in one derived document.

    `host_version` rides it because it is the number an author copies a
    `station_compat` range out of (L.16 rule 2, which is J.1.2 rule 6's
    rule applied to the thing being copied): material that has aged says
    so, instead of teaching a range that no longer fits.
    """
    return {
        "station": host_version,
        "manifest": Manifest.model_json_schema(),
        "config_field_types": list(
            ConfigField.model_fields["type"].annotation.__args__),
        "role_kinds": list(ROLE_KINDS),
        "tiers": [TIER_VERIFIED, TIER_SIGNED, TIER_UNVERIFIED],
        "upload_max_mb": DEFAULT_UPLOAD_MAX_MB,
        "seams": [
            {
                "seam": name,
                "summary": CONTRACTS[name].summary,
                "signature": (None if name in DECLARATIVE
                              else CONTRACTS[name].signature()),
                "positional": list(CONTRACTS[name].positional),
                "params": [{"name": n, "carries": what}
                           for n, what in CONTRACTS[name].params],
                "returns": CONTRACTS[name].returns,
                "precedence": CONTRACTS[name].precedence,
                "declarative": name in DECLARATIVE,
                # L.3: the two seams that change what the product ANSWERS,
                # and therefore must be nameable in the Part D trace.
                "attributed": name in ATTRIBUTED_SEAMS,
            }
            for name in SEAMS
        ],
    }


def seam_reference(host_version: str) -> str:
    """`references/seams.md` — the seam catalogue as markdown.

    Generated rather than written, so a seam added to the catalogue is a
    seam documented, with nobody remembering to.
    """
    doc = schema(host_version)
    out = [
        "<!-- GENERATED from the seam contracts. Do not edit by hand. -->",
        f"# Seams (MonkeyLLM {host_version})",
        "",
        "An extension **contributes** at a named seam and never patches.",
        "A seam absent from this list is not an extension point, and",
        "reaching one is a defect whether or not it works.",
        "",
        "A handler may accept `**kwargs` and may omit a parameter it does",
        "not use. What it must not do is name a parameter the seam does",
        "not pass: Python binds by name, so a misspelling binds to nothing",
        "and fails at call time. The conformance kit checks this at",
        "install, reading your source without importing it.",
        "",
    ]
    for s in doc["seams"]:
        out.append(f"## `{s['seam']}`")
        out.append("")
        out.append(s["summary"])
        out.append("")
        if s["declarative"]:
            out.append("Declared in the manifest; no handler to write.")
            out.append("")
            out.append(f"*Precedence:* {s['precedence']}")
            out.append("")
            continue
        out.append("```python")
        out.append(s["signature"])
        out.append("```")
        out.append("")
        if s["positional"]:
            out.append(f"Passed by position: `{'`, `'.join(s['positional'])}`")
            out.append("")
        for p in s["params"]:
            out.append(f"- `{p['name']}` — {p['carries']}")
        if s["params"]:
            out.append("")
        out.append(f"**Returns:** {s['returns']}")
        out.append("")
        out.append(f"*Precedence:* {s['precedence']}")
        if s["attributed"]:
            out.append("")
            out.append("*This seam changes what the product answers, so "
                       "every call it touches is named in the Part D "
                       "trace — an operator comparing a bad answer against "
                       "a good one has no other way to learn a third party "
                       "was between them.*")
        out.append("")
    return "\n".join(out)


def manifest_reference(host_version: str) -> str:
    """`references/manifest.md` — the manifest schema, from the model."""
    import json

    doc = schema(host_version)
    return "\n".join([
        "<!-- GENERATED from the manifest model. Do not edit by hand. -->",
        f"# The manifest (MonkeyLLM {host_version})",
        "",
        "`manifest.json` is the whole contract between you and a host.",
        "Unknown keys are **refused, never absorbed**: a typo beside a legal",
        "key used to mean the host silently did less than you asked.",
        "",
        "## Pinning `station_compat`",
        "",
        f"This host is **{host_version}**. The minor is the spec version a",
        "release implements and the patch is every release that cuts no",
        "spec — and while the major is `0`, a patch **may change**",
        "**behaviour**. Pin to the minor you tested against:",
        "",
        "```json",
        f'"station_compat": ">={_minor(host_version)},'
        f'<{_next_minor(host_version)}"',
        "```",
        "",
        "A wider range is legal and means what it says: *I accept whatever",
        "the next minor does to me*. Reasonable for a small surface,",
        "unreasonable for anything that reads a seam closely.",
        "",
        f"- Role kinds: `{'`, `'.join(doc['role_kinds'])}`",
        f"- Config field types: `{'`, `'.join(doc['config_field_types'])}`",
        f"- Trust tiers: `{'`, `'.join(doc['tiers'])}`",
        f"- Uploaded archives are capped at {doc['upload_max_mb']} MB by",
        "  default; dependencies are resolved at install, so this door is",
        "  for your own code.",
        "",
        "## JSON Schema",
        "",
        "```json",
        json.dumps(doc["manifest"], indent=2, sort_keys=True),
        "```",
        "",
    ])
