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

from monkeyllm_station.app import build_app
from monkeyllm_station.registry import Registry

DEFAULT_ROOT = os.environ.get("MONKEYLLM_STATION_ROOT", "/forests")
DEFAULT_REGISTRY = os.environ.get("MONKEYLLM_STATION_REGISTRY", "/registry/station.db")


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
                         help="open forests writable (Phase A still serves reads only)")

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
    app = build_app(root=root, registry_path=args.registry, writable=args.writable)
    forests = [f["id"] for f in app.state.pool.list()["forests"]]
    key = app.state.registry.bootstrap_admin(forests)
    if key:
        print(f"station: bootstrapped principal 'admin' with full caps on "
              f"{len(forests)} forest(s)\nstation: API key: {key}\n"
              f"station: store it now — only its digest is kept.")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
