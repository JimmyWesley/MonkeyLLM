"""Vine CLI: `vine serve`, `vine reindex`, `vine validate`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vine", description="MonkeyLLM Vine (Phase 0)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the MCP server")
    p_serve.add_argument("--forest", default=None, help="serve a single forest (default: cwd)")
    p_serve.add_argument("--root", default=None,
                         help="registry mode: serve every forest under this directory "
                              "(tools then require forest=<id>)")
    p_serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_serve.add_argument("--readonly", action="store_true")
    p_serve.add_argument("--host", default=None, help="bind address for http (default 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=None, help="port for http (default 8000)")

    p_init = sub.add_parser("init", help="create a new empty forest (A.5 skeleton + dialect + git)")
    p_init.add_argument("--forest", default=".", help="folder to turn into a forest (created if missing)")
    p_init.add_argument("--title", required=True, help="forest title (master index H1)")
    p_init.add_argument("--summary", default=None, help="master summary (<= 60 tokens; sensible default)")

    p_reindex = sub.add_parser("reindex", help="rebuild _derived/catalog.db from the files")
    p_reindex.add_argument("--forest", default=".")

    p_validate = sub.add_parser("validate", help="lint the forest against the schema")
    p_validate.add_argument("--forest", default=".")
    p_validate.add_argument("--strict", action="store_true", help="warnings also fail")

    p_canopy = sub.add_parser("canopy", help="build the optional vector layer (Phase 1)")
    p_canopy.add_argument("action", choices=["build", "status"])
    p_canopy.add_argument("--forest", default=".")

    args = parser.parse_args(argv)
    forest_root = Path(args.forest).resolve() if getattr(args, "forest", None) else None

    if args.command == "serve":
        from monkeyllm.server import build_server

        if args.root and args.forest:
            parser.error("--forest and --root are mutually exclusive")
        server = build_server(
            forest_root=forest_root if not args.root else None,
            root=Path(args.root).resolve() if args.root else None,
            writable=not args.readonly,
            host=args.host,
            port=args.port,
        )
        try:
            server.run(transport="streamable-http" if args.transport == "http" else "stdio")
        finally:
            server._pool.close()
        return 0

    if args.command == "init":
        from monkeyllm.forest import init_forest

        info = init_forest(forest_root, title=args.title, summary=args.summary)
        print(f"forest created at {info['root']} (commit {info['commit'][:8]})")
        print("next: vine validate / vine serve, or plant() your first nodes")
        return 0

    if args.command == "reindex":
        from monkeyllm.catalog import Catalog
        from monkeyllm.forest import Forest

        catalog = Catalog(Forest(forest_root))
        n = catalog.reindex()
        catalog.close()
        print(f"reindexed {n} nodes -> {forest_root / '_derived' / 'catalog.db'}")
        return 0

    if args.command == "validate":
        from monkeyllm.forest import Forest
        from monkeyllm.lint import lint_forest

        issues = lint_forest(Forest(forest_root))
        for issue in issues:
            print(issue)
        errors = sum(1 for i in issues if i.level == "error")
        warnings = len(issues) - errors
        print(f"\n{errors} error(s), {warnings} warning(s)")
        if errors or (args.strict and warnings):
            return 1
        return 0

    if args.command == "canopy":
        from monkeyllm.canopy import CanopyIndex, embedder_from_env
        from monkeyllm.forest import Forest

        derived = Forest(forest_root).derived_dir
        if args.action == "status":
            idx = CanopyIndex.load(derived)
            if idx is None:
                print("canopy: not built (locate is BM25-only)")
            else:
                print(f"canopy: {len(idx)} vectors, model={idx.model}, dim={idx.dim}")
            return 0
        # build
        embedder = embedder_from_env()
        if embedder is None:
            print("error: set MONKEYLLM_EMBED_ENDPOINT to the embedding server "
                  "(e.g. http://localhost:8081/v1) before building the canopy.")
            return 1
        from monkeyllm.vine import Vine

        vine = Vine(forest_root, writable=False, embedder=embedder)
        try:
            info = vine.build_canopy()
        finally:
            vine.close()
        print(f"canopy built: {info['nodes']} vectors, model={info['model']}, dim={info['dim']}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
