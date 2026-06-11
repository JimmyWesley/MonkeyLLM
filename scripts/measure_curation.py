"""T04 measurement: adopt the dump with LLM curation and score the criterion.

Acceptance (T04 / spec G.4.2): 100 mixed documents ingested end-to-end,
>= 95% of LLM summaries accepted by A.4 validation (acceptance = summaries
the model produced that passed validate-and-retry, vs fallbacks), zero
broken links post-ingest (lint errors == 0).

    set MONKEYLLM_LLM_ENDPOINT=http://127.0.0.1:8090/v1
    python scripts/measure_curation.py [--source dump-ingest] [--forest _measure-forest]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm.curator import Curator, make_chat  # noqa: E402
from monkeyllm.forest import Forest, init_forest  # noqa: E402
from monkeyllm.gardener import Gardener  # noqa: E402
from monkeyllm.lint import lint_forest  # noqa: E402
from monkeyllm.models import validate_summary  # noqa: E402
from monkeyllm.vine import Vine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="dump-ingest")
    parser.add_argument("--forest", default="_measure-forest")
    args = parser.parse_args()

    root = Path(args.forest)
    if root.exists():
        shutil.rmtree(root)
    init_forest(root, title="Toucan Robotics knowledge forest")

    chat, model = make_chat()
    print(f"curation model: {model}")
    curator = Curator(chat)

    vine = Vine(root, writable=True)
    t0 = time.perf_counter()
    try:
        gardener = Gardener(vine, hooks=[curator])
        report = gardener.adopt(args.source)
    finally:
        vine.close()
    wall_s = time.perf_counter() - t0

    # re-validate every planted summary against A.4 (belt and suspenders)
    forest = Forest(root)
    a4_fail = []
    for nid in report["planted"]:
        try:
            validate_summary(str(forest.read(nid).frontmatter.get("summary", "")))
        except Exception as e:  # noqa: BLE001
            a4_fail.append(f"{nid}: {e}")

    issues = lint_forest(forest)
    errors = [str(i) for i in issues if i.level == "error"]
    stats = curator.stats
    curated = stats["llm_summaries"] + stats["fallbacks"]
    acceptance = stats["llm_summaries"] / curated if curated else 1.0

    result = {
        "model": model,
        "planted": len(report["planted"]),
        "branches": len(report["branches"]),
        "ingest_errors": report["errors"],
        "curation": stats,
        "llm_acceptance": round(acceptance, 4),
        "criterion_95": acceptance >= 0.95,
        "a4_failures_post_plant": a4_fail,
        "lint_errors": errors,
        "criterion_zero_broken_links": not errors,
        "wall_s": round(wall_s, 1),
        "s_per_doc": round(wall_s / max(1, len(report["planted"])), 2),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if (result["criterion_95"] and not errors) else 1


if __name__ == "__main__":
    sys.exit(main())
