"""Expand the teacher sample: is the one-step regret systematic, and are the
winning actions generalisable?

Runs ``tools/teacher_probe.py`` over a grid of cases and decision indices and
aggregates:

  * regret per decision (is it always positive, or driven by outliers?);
  * how often the production action was already optimal;
  * which action *families* win (region centre / perpendicular baseline / NBV,
    and which scan set), so a pattern can be looked for before any training;
  * the candidate spread per decision (how much the choice matters at all).

Everything is a full-ledger comparison: each candidate is forced at one
decision and the untouched production policy finishes the episode.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

import teacher_probe   # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", default="Q3:16:101,202,303,404,505:6,12")
    parser.add_argument("--limit-points", type=int, default=3)
    parser.add_argument("--out", default="tuning_runs/teacher_sweep.json")
    parser.add_argument("--from-json", default=None,
                        help="skip probing and re-print the summary of an "
                             "existing sweep artifact (audit/reproduce the "
                             "summary without paying for the probe again)")
    args = parser.parse_args()

    all_states = []
    out = ROOT / args.out

    def flush():
        # Checkpoint after every seed: the full grid is a long single-process
        # run, and an interruption must not lose already-paid-for decisions.
        out.write_text(json.dumps(all_states, ensure_ascii=False, indent=1)
                       + "\n", encoding="utf-8")

    if args.from_json:
        source = ROOT / args.from_json
        all_states = json.loads(source.read_text(encoding="utf-8"))
        print("re-summarising %d states from %s" % (len(all_states), source))
    else:
        for item in args.grid.split(";"):
            mode, n, seeds, indices = item.split(":")
            seeds = [int(s) for s in seeds.split(",")]
            indices = [int(i) for i in indices.split(",")]
            scenario = "random" if mode == "Q3" else "mixed"
            for seed in seeds:
                print("== %s/%s seed %d, indices %s ==" % (mode, n, seed,
                                                           indices), flush=True)
                result = teacher_probe.probe(mode, seed, int(n), scenario,
                                             set(indices), args.limit_points)
                for state in result["states"]:
                    state.update({"mode": mode, "n": int(n), "seed": seed,
                                  "baseline": result["baseline"]})
                    all_states.append(state)
                flush()
                print("  checkpoint: %d states -> %s" % (len(all_states), out),
                      flush=True)

        flush()

    if not all_states:
        print("no states collected")
        return 1
    # A decision point where no candidate was valid carries ``best_spec=None``
    # (and ``best_total/worst_total=None``); every statistic below must skip
    # such points instead of crashing on None.
    scored = [s for s in all_states
              if s.get("best_spec") is not None and s.get("regret") is not None]
    unusable = [s for s in all_states if s not in scored]
    if not scored:
        print("no decision point has a valid candidate; nothing to aggregate")
        return 1
    regrets = [float(s["regret"]) for s in scored]
    # ``spread`` is not part of the current probe entry (it stores best/worst
    # totals instead); fall back to their difference so the summary works with
    # either probe version.
    spreads = []
    spread_missing = 0
    for s in scored:
        value = s.get("spread")
        if value is None and s.get("worst_total") is not None \
                and s.get("best_total") is not None:
            value = s["worst_total"] - s["best_total"]
        if value is None:
            spread_missing += 1
            continue
        spreads.append(float(value))
    prod_best = sum(1 for s in scored if s["best_is_production"])
    failed_total = sum(int(s.get("failed_candidates") or 0)
                       for s in all_states)
    failed_points = sum(1 for s in all_states
                        if (s.get("failed_candidates") or 0))
    print("\n=== summary over %d decision points (%d scored) ===" %
          (len(all_states), len(scored)))
    print("regret: mean %+.0f s, median %+.0f s, max %+.0f s, zero in %d/%d" %
          (statistics.mean(regrets), statistics.median(regrets), max(regrets),
           sum(1 for r in regrets if r <= 1e-9), len(regrets)))
    if spreads:
        print("candidate spread: median %.0f s, max %.0f s%s" %
              (statistics.median(spreads), max(spreads),
               "" if not spread_missing
               else " (%d point(s) missing worst_total)" % spread_missing))
    else:
        print("candidate spread: n/a (no point has best+worst totals)")
    print("production action already optimal: %d/%d" %
          (prod_best, len(scored)))
    print("dropped (incomplete/verifier-failed) candidates: total %d over "
          "%d/%d point(s)" % (failed_total, failed_points, len(all_states)))
    if unusable:
        print("points with no valid candidate (excluded from the stats "
              "above):")
        for s in unusable:
            print("   %s/%s seed %s idx %s" % (s.get("mode"), s.get("n"),
                                               s.get("seed"), s.get("index")))

    def winner_key(s):
        spec = s["best_spec"]
        if spec is None:
            return ("NO_VALID_CANDIDATE", None)
        if not isinstance(spec, dict):
            # Current teacher_probe labels its own action as "PRODUCTION".
            return ("PRODUCTION", None)
        return (spec.get("point_name"), spec.get("variant"))

    winners = Counter(winner_key(s) for s in scored)
    print("winning action families:")
    for key, count in winners.most_common():
        print("   %-28s %d" % (str(key), count))
    rel = [float(s["regret"]) / s["baseline"] for s in scored
           if s.get("baseline")]
    print("relative regret: median %.2f%% max %.2f%%" %
          (100.0 * statistics.median(rel), 100.0 * max(rel)))
    if args.from_json:
        print("re-summarised from %s (nothing written)" % args.from_json)
    else:
        print("written %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
