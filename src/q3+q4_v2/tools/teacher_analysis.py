"""Analyse the expanded teacher sweep: systematic regret, winning families.

Reads ``tuning_runs/teacher_sweep.json`` (produced by ``tools/teacher_sweep.py``)
and answers the questions that decide whether a student model is worth training:

  * is the one-step regret systematic (present in most decisions) or driven by
    a few outliers?
  * which action family wins, and is the winner consistent across seeds for the
    same decision index - i.e. is there a pattern to learn, or is it noise?
  * how often is the production action already optimal?
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def family(state):
    spec = state["best_spec"]
    if spec is None:
        return "no-valid-candidate"
    if not isinstance(spec, dict):
        # tools/teacher_probe.py labels its own (production) action with the
        # bare string "PRODUCTION" when that action wins.
        return "production"
    return "%s/%s" % (spec.get("point_name"), spec.get("variant"))


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                 else "tuning_runs/teacher_sweep.json")
    states = json.loads(path.read_text(encoding="utf-8"))
    if not states:
        print("no states")
        return 1
    # A point where no candidate was valid has ``best_spec=None`` and cannot
    # enter any statistic; list those points explicitly and exclude them.
    unusable = [s for s in states
                if s.get("best_spec") is None or s.get("regret") is None]
    if unusable:
        exclude = {id(s) for s in unusable}
        print("excluded %d/%d point(s) with no valid candidate:" %
              (len(unusable), len(states)))
        for s in sorted(unusable, key=lambda r: (str(r.get("mode")),
                                                 r.get("seed") or 0,
                                                 r.get("index") or 0)):
            print("   %s/%s seed %s idx %s" %
                  (s.get("mode"), s.get("n"), s.get("seed"), s.get("index")))
        states = [s for s in states if id(s) not in exclude]
    if not states:
        print("no usable states")
        return 1
    print("%-4s %-3s %-5s %-6s %8s %8s %8s  %-22s %s" %
          ("mode", "n", "seed", "index", "baseline", "best", "regret",
           "winner", "prod_optimal"))
    for s in sorted(states, key=lambda r: (r["mode"], r["n"], r["seed"],
                                           r["index"])):
        best_cell = ("%8.0f" % s["best_total"] if s.get("best_total")
                     is not None else "     n/a")
        regret_cell = ("%+8.0f" % s["regret"] if s.get("regret") is not None
                       else "     n/a")
        print("%-4s %-3d %-5d %-6d %8.0f %8s %8s  %-22s %s" %
              (s["mode"], s["n"], s["seed"], s["index"], s["baseline"],
               best_cell, regret_cell, family(s), s["best_is_production"]))

    regrets = [s["regret"] for s in states]
    print("\nregret: mean %+.0f  median %+.0f  max %+.0f  positive in %d/%d" %
          (statistics.mean(regrets), statistics.median(regrets), max(regrets),
           sum(1 for r in regrets if r > 1e-9), len(regrets)))
    print("production optimal: %d/%d" %
          (sum(1 for s in states if s["best_is_production"]), len(states)))

    print("\nwinner family counts:")
    for key, count in Counter(family(s) for s in states).most_common():
        print("   %-26s %d" % (key, count))

    # Consistency across seeds for the same (mode, n, index).
    groups = defaultdict(list)
    for s in states:
        groups[(s["mode"], s["n"], s["index"])].append(s)
    print("\nconsistency of the winning family across seeds:")
    consistent = 0
    for key in sorted(groups):
        fams = [family(s) for s in groups[key]]
        counts = Counter(fams)
        top, n_top = counts.most_common(1)[0]
        flag = "consistent" if n_top == len(fams) else "mixed"
        if n_top == len(fams):
            consistent += 1
        print("   %-16s %-24s %s (%d/%d)" %
              ("%s/%d idx %d" % key, top, flag, n_top, len(fams)))
    print("   fully consistent groups: %d/%d" % (consistent, len(groups)))

    print("\nregret by mode:")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        rel = [s["regret"] / s["baseline"] for s in subset]
        print("   %-4s decisions=%2d mean %+6.0f s (%.1f%%) max %+6.0f s "
              "(%.1f%%)" %
              (mode, len(subset),
               statistics.mean(s["regret"] for s in subset),
               100.0 * statistics.mean(rel), max(s["regret"] for s in subset),
               100.0 * max(rel)))
    extended(states, unusable)
    return 0


# --------------------------------------------------------------------------
# Extended diagnostics (added for the multi-seed sweep).  Everything below
# only reads fields already stored by tools/teacher_probe.py /
# tools/teacher_sweep.py; no re-run and no re-scoring happens here.  The
# block above is left byte-identical to its previous version.
# --------------------------------------------------------------------------
def spread(s):
    """Worst minus best *valid* candidate total at one decision."""
    worst, best = s.get("worst_total"), s.get("best_total")
    if worst is None or best is None:
        return 0.0
    return float(worst) - float(best)


def winner_name(s):
    spec = s["best_spec"]
    if spec is None:
        return "no-valid-candidate"
    if not isinstance(spec, dict):
        return "production"
    if spec.get("kind") == "clear":
        return "clear/%s" % spec.get("point_name")
    return "%s/%s" % (spec.get("point_name"), spec.get("variant"))


def point_name(s):
    """Winner's stop family, ignoring the scan set."""
    spec = s["best_spec"]
    if spec is None:
        return "no-valid-candidate"
    if not isinstance(spec, dict):
        return "production"
    return "clear" if spec.get("kind") == "clear" else spec.get("point_name")


def variant_name(s):
    """Winner's scan set, ignoring the stop."""
    spec = s["best_spec"]
    if spec is None:
        return "no-valid-candidate"
    if not isinstance(spec, dict):
        return "production"
    return "clear" if spec.get("kind") == "clear" else spec.get("variant")


def majority(values):
    top, count = Counter(values).most_common(1)[0]
    return top, count, count / len(values)


def same_stop(spec, prod):
    """Stop-level comparison with production's *realised* action.

    This is deliberately not "member of production's candidate set": the probe
    only records the one mission production returned, so the honest comparison
    is realised action vs realised winner.
    """
    if not spec or not prod or not isinstance(spec, dict):
        return False
    if spec.get("kind") != prod.get("kind"):
        return False
    if spec.get("channel") != prod.get("channel"):
        return False
    if spec.get("kind") == "measure":
        point, other = spec.get("point"), prod.get("point")
        if point is None or other is None:
            return False
        if max(abs(point[0] - other[0]), abs(point[1] - other[1])) > 1.0:
            return False
    return True


def extended(states, unusable=()):
    print("\n=== extended diagnostics (reads only stored fields) ===")

    print("(0) coverage of this file:")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        print("   %-4s seeds %s  indices %s  n=%s  decisions=%d" %
              (mode, sorted({s["seed"] for s in subset}),
               sorted({s["index"] for s in subset}),
               sorted({s["n"] for s in subset}), len(subset)))

    def distribution(rows, label):
        reg = sorted((s["regret"] for s in rows), reverse=True)
        total = sum(reg)
        positive = [s for s in rows if s["regret"] > 1e-9]
        rel = [s["regret"] / s["baseline"] for s in rows]
        spreads = [spread(s) for s in rows]
        print("   %-4s n=%2d mean %+6.0f s (%.2f%%) median %+6.0f s max "
              "%+6.0f s | positive %2d/%2d (%.0f%%) | mean w/o top-2 %+6.0f s | "
              "top-2 share of regret mass %.0f%% | spread median %.0f s max "
              "%.0f s" %
              (label, len(rows), statistics.mean(reg),
               100.0 * statistics.mean(rel), statistics.median(reg),
               reg[0] if reg else 0.0, len(positive), len(rows),
               100.0 * len(positive) / max(1, len(rows)),
               statistics.mean(reg[2:]) if len(reg) > 2 else float("nan"),
               100.0 * sum(reg[:2]) / total if total > 0 else 0.0,
               statistics.median(spreads), max(spreads)))
        # Same view with the two largest regret points removed entirely, so
        # "is it only two outliers?" can be read off directly.
        kept = sorted((s["regret"] for s in rows), reverse=True)[2:]
        print("        after dropping the two largest regrets: n=%d mean "
              "%+6.0f s positive %d/%d" %
              (len(kept), statistics.mean(kept) if kept else float("nan"),
               sum(1 for r in kept if r > 1e-9), len(kept)))

    print("\n(1) regret distribution (regret is clamped at 0 by "
          "tools/teacher_probe.py):")
    for mode in sorted({s["mode"] for s in states}):
        distribution([s for s in states if s["mode"] == mode], mode)
    distribution(states, "all")

    print("\n(2) leave-one-seed-out mean regret (is one seed driving it?):")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        means = []
        for seed in sorted({s["seed"] for s in subset}):
            rest = [s["regret"] for s in subset if s["seed"] != seed]
            if not rest:
                continue
            means.append((statistics.mean(rest), seed))
        if not means:
            print("   %-4s single seed: leave-one-seed-out undefined" % mode)
            continue
        lo, lo_seed = min(means)
        hi, hi_seed = max(means)
        print("   %-4s mean %+6.0f s ; drop-one-seed range %+6.0f s (drop "
              "%d) .. %+6.0f s (drop %d)" %
              (mode, statistics.mean(s["regret"] for s in subset), lo, lo_seed,
               hi, hi_seed))

    print("\n(3) candidate spread (worst valid minus best valid candidate):")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        spreads = [spread(s) for s in subset]
        rel = [spread(s) / s["baseline"] for s in subset]
        big = sum(1 for r in rel if r > 0.10)
        print("   %-4s median %.0f s (%.1f%%) max %.0f s (%.1f%%) ; "
              "spread > 10%% of episode: %d/%d" %
              (mode, statistics.median(spreads),
               100.0 * statistics.median(rel), max(spreads),
               100.0 * max(rel), big, len(subset)))

    print("\n(4) replay / ledger audit:")
    errors = [abs(s.get("selfcheck_error_s") or 0.0) for s in states]
    failed = [s.get("failed_candidates") or 0 for s in states]
    # Excluded points still count here: their dropped candidates are evidence.
    all_failed = failed + [s.get("failed_candidates") or 0 for s in unusable]
    print("   max |selfcheck error| = %.6f s ; points with |error| > 1e-6 s: "
          "%d/%d" %
          (max(errors), sum(1 for e in errors if e > 1e-6), len(errors)))
    print("   dropped candidates: total %d ; points with a dropped candidate: "
          "%d/%d" %
          (sum(all_failed), sum(1 for f in all_failed if f), len(all_failed)))

    print("\n(5) winner family counts (point_name/variant):")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        counts = Counter(winner_name(s) for s in subset)
        print("   %-4s %s" %
              (mode, ", ".join("%s=%d" % item for item in counts.most_common())))

    print("\n(6) winner vs production's *realised* action (stop level; NOT "
          "candidate-set membership):")
    for mode in sorted({s["mode"] for s in states}):
        subset = [s for s in states if s["mode"] == mode]
        # ``best_is_production`` is the probe's own assertion that the forced
        # production replay won; that candidate is production's mission by
        # construction, so identity is exact rather than a distance test.
        own = sum(1 for s in subset if s.get("best_is_production"))
        others = [s for s in subset if not s.get("best_is_production")]
        diff = Counter(winner_name(s) for s in others)
        same_stop_n = sum(1 for s in others
                          if same_stop(s["best_spec"], s.get("production")))
        prod_kinds = Counter((s.get("production") or {}).get("kind")
                             for s in subset)
        print("   %-4s production's own action optimal %2d/%2d ; differing "
              "winners: %s ; of those, same stop as production: %d ; "
              "production realised kinds: %s" %
              (mode, own, len(subset),
               ", ".join("%s=%d" % item for item in diff.most_common()) or "-",
               same_stop_n, dict(prod_kinds)))

    print("\n(7) by (mode, n, index) - early/mid/late behaviour:")
    cells = defaultdict(list)
    for s in states:
        cells[(s["mode"], s["n"], s["index"])].append(s["regret"])
    for key in sorted(cells):
        reg = cells[key]
        row = [s for s in states
               if (s["mode"], s["n"], s["index"]) == key]
        cands = [s.get("candidates") or 0 for s in row]
        print("   %-4s n=%-3d idx %-3d mean %+6.0f s positive %d/%d cand "
              "median %3d  %s" %
              (key[0], key[1], key[2], statistics.mean(reg),
               sum(1 for r in reg if r > 1e-9), len(reg),
               statistics.median(cands),
               "[%s]" % " ".join("%+d" % round(r) for r in reg)))

    print("\n(8) winner-family majority share per (mode, n, index) across "
          "seeds:")
    shares = []
    for key in sorted(cells):
        subset = sorted([s for s in states
                         if (s["mode"], s["n"], s["index"]) == key],
                        key=lambda s: s["seed"])
        fams = [winner_name(s) for s in subset]
        top, n_top = Counter(fams).most_common(1)[0]
        shares.append(n_top / len(fams))
        print("   %-4s n=%-3d idx %-3d majority %-18s %d/%d" %
              (key[0], key[1], key[2], top, n_top, len(fams)))
        print("        seeds: %s" %
              "  ".join("%d=%s%s" % (s["seed"], winner_name(s),
                                     "" if s["best_is_production"] else "*")
                        for s in subset))
    print("   (* = winner is not production's own action)")
    print("   mean majority share %.2f over %d groups" %
          (statistics.mean(shares), len(shares)))

    print("\n(9) how coarse must the pattern be to be consistent? (majority "
          "share per group)")
    for key in sorted(cells):
        subset = [s for s in states
                  if (s["mode"], s["n"], s["index"]) == key]
        point, _, p_share = majority([point_name(s) for s in subset])
        variant, _, v_share = majority([variant_name(s) for s in subset])
        family, _, f_share = majority([winner_name(s) for s in subset])
        print("   %-4s n=%-3d idx %-3d stop %-8s %.2f | scan set %-9s %.2f | "
              "family %-16s %.2f" %
              (key[0], key[1], key[2], point, p_share, variant, v_share,
               family, f_share))


if __name__ == "__main__":
    raise SystemExit(main())
