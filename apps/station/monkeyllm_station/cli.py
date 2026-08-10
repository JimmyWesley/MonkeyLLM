# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""`station` CLI: run the host, mint keys, grant access.

    station serve  --root /forests --registry /registry/station.db
    station key    --principal alice --forest forest-fixture --caps read,query
    station grants --principal alice
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from monkeyllm_station.app import build_app, super_admin_from_env
from monkeyllm_station.registry import Registry

DEFAULT_ROOT = os.environ.get("MONKEYLLM_STATION_ROOT", "/forests")
DEFAULT_REGISTRY = os.environ.get("MONKEYLLM_STATION_REGISTRY", "/registry/station.db")

# A platform UI (Dokploy, Coolify, a compose file somebody inherited) has an
# environment table and often no argv field at all, so the opt-in of J.2.5
# has to be reachable from both.
BOOTSTRAP_ENV = "MONKEYLLM_STATION_BOOTSTRAP_KEY"


def wants_bootstrap_key(argv_flag: bool) -> bool:
    return argv_flag or os.environ.get(BOOTSTRAP_ENV, "").strip().lower() in {
        "1", "true", "yes", "on"}


def console_url(host: str, port: int) -> str:
    """What to type into a browser — never what the socket binds to.

    A container binds 0.0.0.0 because it must; printing that back is an
    address nobody can open, and the first instruction a product gives
    should not be one the reader has to correct.
    """
    shown = "localhost" if host in ("0.0.0.0", "::", "") else host
    return f"http://{shown}:{port}"


def first_run_lines(*, url: str, super_admin: str | None,
                    setup_open: bool, key: str | None) -> list[str]:
    """What the terminal says to somebody who cannot sign in yet (J.2.5).

    Nobody meets this product in a browser; they meet it watching a compose
    log scroll, and the console that would explain itself is behind the door
    they are trying to open. Hence three states, one instruction each — and
    silence afterwards, because a restart that reports the deployment's
    authentication state to whatever collects its logs is a disclosure with
    no reader who needed it.
    """
    if key:
        return [
            "first run — minted the bootstrap key you asked for.",
            "",
            f"  console:   {url}",
            "  principal: admin — owner, so it governs every forest, "
            "including the first one it creates",
            f"  API key:   {key}",
            "",
            "store it now: only its digest is kept.",
            "this spent the first-run window — the setup screen is closed.",
        ]
    if super_admin:
        # The password is not echoed: the operator set it, and every log
        # aggregator downstream did not need a copy of it (J.2.5).
        return [
            "first run — this Station takes its administrator from the environment.",
            f"  console: {url}",
            f"  sign in as '{super_admin}', with the password in "
            "MONKEYLLM_STATION_PASSWORD.",
        ]
    if setup_open:
        return [
            "first run — nobody owns this Station yet.",
            f"  open {url} and create the owner account.",
            "  the first person to open it becomes the owner, so do not",
            "  leave a publicly reachable Station sitting on this screen.",
            "  no browser? restart with --bootstrap-key to get an API key",
            f"  instead (or set {BOOTSTRAP_ENV}=1).",
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    # Shared options belong to every subcommand, not to the top-level parser:
    # `station serve --root X` is what a reader expects to work.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=DEFAULT_ROOT, help="forest registry directory")
    common.add_argument("--registry", default=DEFAULT_REGISTRY,
                        help="host registry SQLite file")

    ap = argparse.ArgumentParser(prog="station", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", parents=[common], help="run the Station")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8800)
    p_serve.add_argument("--writable", action="store_true",
                         help="accept writes: plant/graft/tend and ingest "
                              "(off by default; reads always work)")
    p_serve.add_argument("--no-warm", action="store_true",
                         help="do not open every forest at boot (J.6.1). "
                              "Warming costs one open per forest — a few "
                              "milliseconds and a few MB resident each — and "
                              "buys a first call that is not measuring cold "
                              "SQLite. Turn it off for a registry with more "
                              "forests than you want held open at once.")
    p_serve.add_argument("--bootstrap-key", action="store_true",
                         help="on a Station nobody owns yet, mint the first "
                              "API key and print it instead of opening the "
                              "setup screen (J.2.5) — for a deployment with "
                              "no browser. Never mints on a registry that "
                              "already has a way in.")

    p_key = sub.add_parser("key", parents=[common],
                           help="mint an API key and grant a forest")
    p_key.add_argument("--principal", required=True)
    p_key.add_argument("--forest", required=True)
    p_key.add_argument("--caps", default="read",
                       help="comma-separated: read,write,query,tend,ingest,admin")

    p_grants = sub.add_parser("grants", parents=[common],
                              help="list a principal's forests")
    p_grants.add_argument("--principal", required=True)

    args = ap.parse_args(argv)

    if args.command == "key":
        registry = Registry(args.registry)
        caps = {c.strip() for c in args.caps.split(",") if c.strip()}
        key = registry.issue_key(args.principal, label=args.forest)
        registry.grant(args.principal, args.forest, caps)
        print(f"principal: {args.principal}\nforest:    {args.forest}\n"
              f"caps:      {','.join(sorted(caps))}\nAPI key:   {key}")
        print("\nStore it now — the Station keeps only its digest.")
        return 0

    if args.command == "grants":
        registry = Registry(args.registry)
        for forest in registry.forests_for(args.principal):
            print(forest)
        return 0

    import uvicorn

    root = Path(args.root)
    if not root.is_dir():
        print(f"station: forest root does not exist: {root}", file=sys.stderr)
        return 2
    try:
        app = build_app(root=root, registry_path=args.registry,
                        writable=args.writable,
                        # Only ever an override: absent, the environment
                        # decides, so a compose file does not have to add a
                        # command line to change one default.
                        warm=False if args.no_warm else None)
    except ValueError as e:
        # A mistyped ingest root (J.8.2) is a configuration fact, and the
        # operator is standing right here reading the log.
        print(f"station: {e}", file=sys.stderr)
        return 2
    # Starting a server is not an act of administration (J.2.5): the registry
    # is exactly as authoritative after this line as before it, unless the
    # operator asked otherwise on the command line.
    registry = app.state.registry
    key = None
    if wants_bootstrap_key(args.bootstrap_key):
        key = registry.mint_bootstrap_key()
        if key is None:
            print("station: --bootstrap-key: nothing to mint — this registry "
                  "already has a way in. Use `station key`, or the People "
                  "console, from an account that is already inside.",
                  file=sys.stderr)
    for line in first_run_lines(url=console_url(args.host, args.port),
                                super_admin=(super_admin_from_env() or (None,))[0],
                                setup_open=registry.setup_available(), key=key):
        print(f"station: {line}" if line else "station:", flush=True)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
