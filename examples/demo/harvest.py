"""CLI wrapper for the harvest tool (spec C.6c) — see monkeyllm.harvest.

Zero-LLM retrieval: one call, ranked bananas + exact snippets back, so the
caller's LLM decides the next steps.

Usage:
    python examples/demo/harvest.py "seed 1045"
    python examples/demo/harvest.py --terms 1045,experiment --k 3 "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from monkeyllm import Vine  # noqa: E402
from monkeyllm.harvest import harvest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", help="free-text question or search phrase")
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"))
    ap.add_argument("--terms", help="comma-separated exact terms (default: derived from the query)")
    ap.add_argument("--k", type=int, default=3, help="max bananas returned (cap 5)")
    args = ap.parse_args()

    vine = Vine(Path(args.forest), writable=False, session="harvest")
    try:
        terms = [t.strip() for t in args.terms.split(",") if t.strip()] if args.terms else None
        out = harvest(vine, args.query, terms=terms, k=args.k)
    finally:
        vine.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
