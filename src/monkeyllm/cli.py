"""Vine CLI: `vine serve`, `vine reindex`, `vine validate`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vine", description="MonkeyLLM Vine (Phase 0)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the MCP server")
    p_serve.add_argument("--forest", default=".", help="forest root (default: cwd)")
    p_serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_serve.add_argument("--readonly", action="store_true")

    p_reindex = sub.add_parser("reindex", help="rebuild _derived/catalog.db from the files")
    p_reindex.add_argument("--forest", default=".")

    p_validate = sub.add_parser("validate", help="lint the forest against the schema")
    p_validate.add_argument("--forest", default=".")
    p_validate.add_argument("--strict", action="store_true", help="warnings also fail")

    args = parser.parse_args(argv)
    forest_root = Path(args.forest).resolve()

    if args.command == "serve":
        from monkeyllm.server import build_server

        server = build_server(forest_root, writable=not args.readonly)
        try:
            server.run(transport="streamable-http" if args.transport == "http" else "stdio")
        finally:
            server._vine.close()
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

    return 2


if __name__ == "__main__":
    sys.exit(main())
