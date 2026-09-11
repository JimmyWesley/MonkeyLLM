# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""`vine ext` — Part L from the command line (spec v0.80, L.12).

The whole point of this file: **an operator with no Station installs
extensions.** The mechanism is the engine's, so the engine's own front door
has to expose all of it — install, update, list, config, enable, disable,
remove — or a capability would be reachable only through the AGPL host, and
every extension author would become a client of that host.

What this host cannot serve, it says (L.10). A panel is validated here and
reported `declared (no host surface)`; it is never an error and never
silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from monkeyllm import __version__ as ENGINE_VERSION
from monkeyllm.errors import VineError
from monkeyllm.extensions import forestcfg
from monkeyllm.extensions.installer import (dialect_impact, install, plan,
                                          uninstall, update)
from monkeyllm.extensions.loader import read_manifest
from monkeyllm.extensions.sources import TIER_UNVERIFIED
from monkeyllm.extensions.store import Store

# The version an extension's `station_compat` is judged against. The engine
# is what serves Part L, so the engine's version is the honest number — a
# CLI host has no Station whose version it could quote.
HOST_VERSION = ENGINE_VERSION


def run_ext(args, forest_root: Path | None, parser) -> int:
    store = Store()
    try:
        return _dispatch(args, forest_root, store, parser)
    except VineError as exc:
        print(f"{exc.code}: {exc.message}")
        if exc.hint:
            print(f"  hint: {exc.hint}")
        for key, value in (exc.data or {}).items():
            if key in ("reason", "failed", "roles", "fields", "was", "now"):
                print(f"  {key}: {_render(value)}")
        return 1


def _render(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _dispatch(args, forest_root, store: Store, parser) -> int:
    action = args.action

    if action == "install":
        result = install(args.source, HOST_VERSION, store=store,
                         acknowledge_unverified=args.yes,
                         verify=not args.no_verify,
                         build_env=not args.no_deps)
        return _report_install(result, store)

    if action == "update":
        result = update(args.id, HOST_VERSION, store=store,
                        acknowledge_unverified=args.yes)
        return _report_install(result, store)

    if action == "list":
        return _list(store)

    if action == "show":
        return _show(args.id, store)

    if action == "outdated":
        return _outdated(store)

    if action == "quarantine":
        entries = store.list_quarantine()
        if not entries:
            print("nothing in quarantine")
            return 0
        for entry in entries:
            fields = ", ".join(entry["fields"]) or "(no settings)"
            print(f"{entry['id']:<20} expires in {entry['expires_in_days']:>5} "
                  f"days   {fields}")
        return 0

    if action == "remove":
        impact = dialect_impact(args.id, store)
        # L.8: what will START BEING REFUSED is named before confirmation.
        if impact["losing"] and not args.yes:
            print(f"removing {args.id!r} un-declares: "
                  f"{', '.join(impact['losing'])}")
            print("a write using one of those will be refused by A.2 "
                  "afterwards. Re-run with --yes to accept.")
            return 1
        result = uninstall(args.id, store=store)
        print(f"removed {result['id']}")
        if result["config_quarantined"]:
            print("  its config is in quarantine; reinstalling recovers it")
        print("  restart the host to release the loaded module")
        return 0

    if action == "config":
        return _config(args, store)

    if action in ("enable", "disable"):
        return _enablement(args, forest_root, store, parser)

    parser.error(f"unknown ext action: {action}")
    return 2


# ---------------------------------------------------------------------------

def _report_install(result: dict, store: Store) -> int:
    print(f"installed {result['id']} {result['version']}  "
          f"[{result['tier']}]")
    if result.get("tracking"):
        # L.2 rule 2: the ref travels with the id, everywhere.
        print(f"  tracking {result['tracking']} at "
              f"{(result.get('revision') or '')[:12]}")
    elif result.get("revision"):
        print(f"  revision {result['revision'][:12]}")
    print(f"  licence  {result['license']}")
    if result.get("environment"):
        print(f"  environment {result['environment']}")
    if result.get("config_recovered"):
        print(f"  recovered config: {', '.join(result['config_recovered'])}")
    # L.10: validated here, unserved here, and said rather than dropped.
    manifest = read_manifest(store.tree(result["id"]))
    if manifest.contributes.panel:
        print("  panel: declared (no host surface)")
    if manifest.models.registers:
        for role in manifest.models.registers:
            print(f"  registers role {role.role} ({role.kind}) — bind it with "
                  f"MONKEYLLM_ROLE_{role.role.upper()}_*")
    print("  restart the host, then enable it on a forest:")
    print(f"    vine ext enable {result['id']} --forest <path>")
    return 0


def _list(store: Store) -> int:
    """F.193: a listing is an OFFLINE call. Being behind costs a fetch and
    therefore belongs to `outdated`, not here."""
    records = store.list()
    if not records:
        print("no extensions installed")
        return 0
    for r in records:
        ref = f" @{r.tracking}" if r.tracking else ""
        rev = f" {r.revision[:8]}" if r.revision else ""
        print(f"{r.id:<20} {r.version:<10} {r.tier:<11}{ref}{rev}")
        if r.reason and r.tier == TIER_UNVERIFIED:
            print(f"  {r.reason}")
    return 0


def _show(ext_id: str, store: Store) -> int:
    record = store.require(ext_id)
    manifest = read_manifest(store.tree(ext_id))
    print(json.dumps({
        "install": record.to_dict(),
        "contributes": {
            seam: [getattr(s, "name", None) or s.handler
                   for s in getattr(manifest.contributes, seam)]
            for seam in ("converters", "curation", "events", "jobs", "tools",
                         "routes", "ranking", "prompt")
            if getattr(manifest.contributes, seam)
        },
        "panel": manifest.contributes.panel,
        "config": {k: {"type": v.type, "required": v.required,
                       "secret": v.secret,
                       "value": ("(set)" if v.secret and
                                 store.read_config(ext_id).get(k) else
                                 store.read_config(ext_id).get(k, v.default))}
                   for k, v in manifest.config.items()},
    }, indent=2, sort_keys=True, default=str))
    return 0


def _outdated(store: Store) -> int:
    from monkeyllm.extensions.sources import _git, _parse_git
    tracked = [r for r in store.list() if r.tracking and r.kind in
               ("git", "index")]
    if not tracked:
        print("nothing is tracking a moving ref")
        return 0
    for record in tracked:
        try:
            _, _, url, _ = _parse_git(record.source)
            head = _git("ls-remote", url, record.tracking).split("\t")[0]
        except Exception as exc:
            print(f"{record.id:<20} could not be checked: {exc}")
            continue
        state = "up to date" if head == record.revision else \
            f"behind: {head[:8]} is now {record.tracking}"
        print(f"{record.id:<20} {state}")
    return 0


def _config(args, store: Store) -> int:
    manifest = read_manifest(store.tree(args.id))
    values = store.read_config(args.id)
    if not args.set:
        for key, field in sorted(manifest.config.items()):
            # L.7 rule 4: a secret is never printed back, only its presence.
            shown = "(set)" if field.secret and values.get(key) else \
                values.get(key, field.default)
            flag = " *secret" if field.secret else \
                (" *required" if field.required else "")
            print(f"{key:<24} {shown}{flag}")
        return 0
    for pair in args.set:
        key, sep, raw = pair.partition("=")
        if not sep:
            print(f"E_SCHEMA: --set expects KEY=VALUE, got {pair!r}")
            return 1
        field = manifest.config.get(key)
        if field is None:
            # L.10: every required setting is reachable here, so an unknown
            # key is a typo and naming the vocabulary is the whole answer.
            print(f"E_SCHEMA: {args.id} has no setting {key!r}")
            print(f"  it declares: {', '.join(sorted(manifest.config)) or '(none)'}")
            return 1
        values[key] = _coerce(raw, field.type)
    store.write_config(args.id, values)
    touched = sorted(pair.split("=", 1)[0] for pair in args.set)
    print(f"{args.id}: {', '.join(touched)} set")
    return 0


def _coerce(raw: str, kind: str):
    if kind == "integer":
        return int(raw)
    if kind == "number":
        return float(raw)
    if kind == "boolean":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return raw


def _enablement(args, forest_root, store: Store, parser) -> int:
    root = Path(forest_root or args.forest).resolve()
    if args.action == "disable":
        forestcfg.disable(root, args.id)
        print(f"{args.id} disabled on {root.name}")
        print("  restart the host; the module stays resident until then")
        return 0

    record = store.require(args.id)
    manifest = read_manifest(store.tree(args.id))
    forestcfg.enable(root, args.id, version=record.version)
    print(f"{args.id} enabled on {root.name}")
    if manifest.contributes.tools:
        print("  its tools are published on this forest to keys that reach it")
    return 0
