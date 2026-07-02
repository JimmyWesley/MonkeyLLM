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

    p_adopt = sub.add_parser("adopt", help="Gardener: mirror a source tree into the forest (spec G.3)")
    p_adopt.add_argument("source", help="directory full of documents to adopt")
    p_adopt.add_argument("--forest", default=".")
    p_adopt.add_argument("--dest", default=None, help="root the mirror under this existing branch")
    p_adopt.add_argument("--curate", action="store_true",
                         help="LLM curation (G.4.2): A.4 summaries + tags + edge "
                              "proposals via MONKEYLLM_LLM_ENDPOINT")

    p_sync = sub.add_parser("sync", help="Gardener: hash-diff the adopted source and refresh passports")
    p_sync.add_argument("source", nargs="?", default=None,
                        help="source directory (default: the adopted root in _meta/gardener.yaml)")
    p_sync.add_argument("--forest", default=".")
    p_sync.add_argument("--curate", action="store_true",
                        help="LLM curation for newly adopted files (G.4.2, "
                             "incl. edge proposals)")
    p_sync.add_argument("--path", default=None,
                        help="targeted sync (G.8): reconcile only this source-relative path")

    p_ranger = sub.add_parser("ranger", help="Ranger: evaporate heat, tend links, report health (spec H)")
    p_ranger.add_argument("--forest", default=".")
    p_ranger.add_argument("--every", type=int, default=None,
                          help="service mode: repeat every N seconds until interrupted")

    p_snap = sub.add_parser("snapshot", help="package/restore the forest as a git bundle (spec Part I)")
    p_snap.add_argument("action", choices=["create", "restore"])
    p_snap.add_argument("file", nargs="?", default=None,
                        help="bundle file (restore: required; create: optional output)")
    p_snap.add_argument("--forest", default=".")
    p_snap.add_argument("--with-payloads", action="store_true",
                        help="create: also zip the dataset payloads as a sidecar")
    p_snap.add_argument("--payloads", default=None,
                        help="restore: payload sidecar zip to extract")
    p_snap.add_argument("--to", default=None,
                        help="create: upload the bundle to this URI (file:// or s3://)")

    p_prefetch = sub.add_parser("prefetch", help="warm remote payloads under a branch (spec G.9.5)")
    p_prefetch.add_argument("scope", nargs="?", default="_index")
    p_prefetch.add_argument("--forest", default=".")

    args = parser.parse_args(argv)
    forest_root = Path(args.forest).resolve() if getattr(args, "forest", None) else None

    # Every subcommand but `init` and `snapshot restore` operates on an
    # EXISTING forest. Without this check, the ubiquitous `--forest`
    # default of "." makes it dangerously easy to run a forest command
    # from an arbitrary directory (e.g. the project's own outer repo) and
    # have it silently treated as a forest, writing `_derived/`/`.vine.lock`
    # there. A real forest always carries `_meta/schema.md` (spec A.5),
    # written by `init` — its absence means "not a forest", not "empty one".
    _needs_existing_forest = args.command not in ("init",) and not (
        args.command == "snapshot" and args.action == "restore"
    ) and not (args.command == "serve" and args.root)
    if _needs_existing_forest:
        _check_root = forest_root if forest_root is not None else Path(".").resolve()
        if not (_check_root / "_meta" / "schema.md").is_file():
            parser.error(
                f"{_check_root} is not a forest (no _meta/schema.md) — "
                f"run 'vine init --forest {_check_root} --title \"...\"' first, "
                "or pass --forest to point at an existing one"
            )

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

    if args.command in ("adopt", "sync"):
        from monkeyllm.gardener import Gardener, discover_hooks
        from monkeyllm.vine import Vine

        vine = Vine(forest_root, writable=True)
        try:
            curator = None
            if args.curate:
                import yaml

                from monkeyllm.curator import Curator, make_candidates, make_chat

                chat, model = make_chat()
                print(f"curation model: {model}")
                directives = ""
                cfg_path = forest_root / "_meta" / "gardener.yaml"
                if cfg_path.is_file():
                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    directives = (cfg.get("curation") or {}).get("directives") or ""
                curator = Curator(chat, directives=directives,
                                  candidates=make_candidates(vine))
            hooks = discover_hooks() + ([curator] if curator else [])
            gardener = Gardener(vine, hooks=hooks)
            if args.command == "adopt":
                report = gardener.adopt(args.source, dest=args.dest)
            else:
                report = gardener.sync(args.source, path=args.path)
        finally:
            vine.close()
        for key in ("planted", "branches", "updated", "unchanged", "stale",
                    "unsupported", "errors"):
            if report.get(key):
                print(f"{key} ({len(report[key])}):")
                for item in report[key]:
                    print(f"  {item}")
        if curator:
            print(f"curation: {curator.stats}")
        if not any(report.values()):
            print("nothing to do")
        return 1 if report.get("errors") else 0

    if args.command == "snapshot":
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        if args.action == "create":
            info = create_snapshot(forest_root, out=Path(args.file) if args.file else None,
                                   with_payloads=args.with_payloads)
            print(f"bundle: {info['bundle']} ({info['bytes']:,} bytes)")
            if info.get("payload_sidecar"):
                print(f"payload sidecar: {info['payload_sidecar']} ({info['payloads']} file(s))")
            if args.to:
                from monkeyllm.fetch import upload

                upload(Path(info["bundle"]), args.to)
                print(f"uploaded to {args.to}")
        else:
            if not args.file:
                parser.error("snapshot restore needs the bundle file")
            info = restore_snapshot(Path(args.file), forest_root,
                                    payload_sidecar=Path(args.payloads) if args.payloads else None)
            print(f"restored {info['nodes']} nodes -> {info['forest']}"
                  + (f" (+{info['restored_payloads']} payload(s))" if info["restored_payloads"] else ""))
        return 0

    if args.command == "prefetch":
        from monkeyllm.vine import Vine

        vine = Vine(forest_root, writable=False)
        try:
            report = vine.prefetch(args.scope)
        finally:
            vine.close()
        print(f"fetched {len(report['fetched'])}, already local {report['already_local']}")
        for item in report["fetched"]:
            print(f"  {item}")
        for err in report["errors"]:
            print(f"  ERROR {err}")
        return 1 if report["errors"] else 0

    if args.command == "ranger":
        import json as _json
        import time as _time

        from monkeyllm.ranger import Ranger
        from monkeyllm.vine import Vine

        vine = Vine(forest_root, writable=True)
        try:
            ranger = Ranger(vine)
            while True:
                report = ranger.run()
                print(_json.dumps(report, ensure_ascii=False, indent=2))
                if args.every is None:
                    break
                _time.sleep(args.every)
        except KeyboardInterrupt:
            pass
        finally:
            vine.close()
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
