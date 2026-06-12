"""T04 convergence curve: recurring questions over a LEARNING forest.

The paper's signature chart: run the same multi-hop question set N times
with `--learn` on (shouts grafted, heat accumulating, NO trail cleaning
between passes — the accumulation IS the experiment) and watch the
navigation cost fall. Acceptance (T04): mean hops-to-banana drops >= 25%;
trail_len (spec v0.6, the metric that actually sees pick chains) is
reported alongside.

    set MONKEYLLM_LLM_ENDPOINT=http://127.0.0.1:8090/v1
    python scripts/convergence.py [--passes 5] [--rebuild]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "bench" / "_artifacts" / "convergence"
PY = sys.executable


def run(args: list[str], ok_codes: tuple[int, ...] = (0,)) -> None:
    r = subprocess.run([PY, *args], cwd=REPO)
    if r.returncode not in ok_codes:
        sys.exit(f"step failed: {' '.join(args)}")


def mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def point_from(report_path: Path, i: int) -> dict:
    results = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "pass": i,
        "correct": sum(1 for r in results if r.get("correct_text")),
        "n": len(results),
        "hops": mean([r["metrics"].get("hops_to_banana") for r in results]),
        "trail_len": mean([r["metrics"].get("trail_len") for r in results]),
        "tokens": mean([r["metrics"].get("tokens_to_banana") for r in results]),
        "wall_s": mean([r.get("wall_s") for r in results]),
        "shortcuts_grafted": sum(
            1 for r in results for s in r.get("shortcuts", []) if "error" not in s),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--passes", type=int, default=5)
    ap.add_argument("--forest", default="bench-forest")
    ap.add_argument("--questions", default=str(REPO / "bench" / "questions-v3.json"))
    ap.add_argument("--rebuild", action="store_true",
                    help="regenerate the forest first (clean slate: no grafts, no heat)")
    ap.add_argument("--start", type=int, default=1,
                    help="resume from this pass (earlier pass-*.json files are reloaded)")
    args = ap.parse_args()

    if args.rebuild:
        print("== rebuilding the forest (clean slate) ==")
        run(["scripts/build_bench_forest.py", "--out", args.forest])
        if os.environ.get("MONKEYLLM_EMBED_ENDPOINT"):
            print("== building canopy (hybrid locate, v3 parity) ==")
            run(["-m", "monkeyllm.cli", "canopy", "build", "--forest", args.forest])

    ART.mkdir(parents=True, exist_ok=True)
    curve = []
    for i in range(1, args.start):  # resume: reload prior passes
        prior = ART / f"pass-{i:02d}.json"
        if prior.is_file():
            curve.append(point_from(prior, i))
    for i in range(args.start, args.passes + 1):
        out = ART / f"pass-{i:02d}.json"
        print(f"== pass {i}/{args.passes} ==")
        # run_demo exits 1 when not all answers are correct — that is data,
        # not a failure (the report file is still written)
        run(["demo/run_demo.py", "--forest", args.forest,
             "--questions", args.questions, "--learn", "--out", str(out)],
            ok_codes=(0, 1))
        point = point_from(out, i)
        curve.append(point)
        print(f"   correct {point['correct']}/{point['n']}  hops {point['hops']}  "
              f"trail_len {point['trail_len']}  tokens {point['tokens']}  "
              f"shortcuts +{point['shortcuts_grafted']}")

    def drop(key: str) -> float | None:
        first, best = curve[0][key], min(p[key] for p in curve[1:] if p[key] is not None)
        if not first:
            return None
        return round(100 * (first - best) / first, 1)

    summary = {
        "curve": curve,
        "drop_pct": {k: drop(k) for k in ("hops", "trail_len", "tokens")},
        "criterion_hops_25": (drop("hops") or 0) >= 25,
        "criterion_trail_len_25": (drop("trail_len") or 0) >= 25,
    }
    (ART / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n== convergence ==")
    print(f"{'pass':>4} {'correct':>8} {'hops':>6} {'trail':>6} {'tokens':>7} {'+cuts':>6}")
    for p in curve:
        print(f"{p['pass']:>4} {p['correct']:>5}/{p['n']:<2} {p['hops'] or '-':>6} "
              f"{p['trail_len'] or '-':>6} {p['tokens'] or '-':>7} {p['shortcuts_grafted']:>6}")
    print(f"drops vs pass 1: {summary['drop_pct']}")
    print(f"saved -> {ART / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
