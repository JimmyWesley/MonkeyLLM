"""Re-grade a saved bench report against the (possibly fixed) questions file,
without re-running the models. Grading bugs/gabarito fixes shouldn't cost a
GPU pass: the raw answers and harvested nodes are all in the report.

    python bench/regrade.py [--report path] [--questions path]
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def regrade(report: dict, questions: list[dict]) -> dict:
    by_id = {q["id"]: q for q in questions}
    summaries = []
    for arm, results in report["results"].items():
        for r in results:
            q = by_id[r["id"]]
            harvested = {a.split("#")[0] for a in r["answer_nodes"]}
            expected = set(q["expected_nodes"])
            r["correct_text"] = r["answer"] is not None and all(
                s.lower() in str(r["answer"]).lower() for s in q["answer_contains"]
            )
            r["banana_precision"] = round(
                (len(harvested & expected) / len(harvested)) if harvested else 0.0, 2
            )
        toks = [r["metrics"]["tokens_to_banana"] for r in results]
        summaries.append({
            "arm": arm,
            "correct": sum(1 for r in results if r["correct_text"]),
            "n": len(results),
            "precision_mean": round(sum(r["banana_precision"] for r in results) / len(results), 2),
            "tokens_median": int(statistics.median(toks)),
            "tokens_mean": int(sum(toks) / len(toks)),
            "wall_s_median": round(statistics.median(r.get("wall_s", 0.0) for r in results), 1),
        })
    report["summaries"] = summaries
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", default=str(REPO / "bench" / "_artifacts" / "report-forest-fixture.json"))
    ap.add_argument("--questions", default=str(REPO / "bench" / "questions-v1.json"))
    args = ap.parse_args()

    path = Path(args.report)
    report = json.loads(path.read_text(encoding="utf-8"))
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    report = regrade(report, questions)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    head = f"{'braço':<8} {'corretas':>9} {'precision':>10} {'tokens (med)':>13} {'wall s (med)':>13}"
    print(head)
    print("-" * len(head))
    for s in report["summaries"]:
        print(f"{s['arm']:<8} {s['correct']}/{s['n']:<7} {s['precision_mean']:>10} "
              f"{s['tokens_median']:>13} {s['wall_s_median']:>13}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
