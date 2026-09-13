"""Screen an *online* activation rule for ``order_plan``: cumulative movement.

The t29 premise (activate on the first plan's reference cost) is falsified by
``tools/order_gate_calib_probe.py``: corr(first_ref_s, realised T_move) = +0.07
over 99 traced runs, because the plan is rebuilt 8-18 times per episode and the
first plan only covers 2-3 tasks.

This tool screens the natural observable instead:

    activate ``order_plan`` once the episode's cumulative movement passes X s

which is a *causal* rule (it fires at a well-defined moment of the run).
The activation decision is read from the **production** arm's own action log --
a counterfactual approximation, since the trajectory after activation would
differ; it is a screen, not a verdict.  A real run is required before adoption.

Usage: python -X utf8 tools/order_gate_cummove.py [--grid 1500,2000,2500,...]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from order_gate_screen import DATASETS, load_pairs  # noqa: E402

GRID = [1200.0, 1500.0, 1800.0, 2000.0, 2200.0, 2500.0, 2800.0, 3000.0, 3300.0]


def cumulative_move(run_dir: Path):
    """Return the list of cumulative movement seconds after each action."""
    path = run_dir / "actions.csv"
    if not path.exists():
        return None
    cum, total = [], 0.0
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            total += float(row.get("movement_time") or 0.0)
            cum.append(total)
    return cum


def activates(cum, threshold: float) -> bool:
    return cum is not None and cum and cum[-1] > threshold


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default=",".join(f"{g:g}" for g in GRID))
    ap.add_argument("--json", default="tuning_runs/order_gate_cummove.json")
    args = ap.parse_args()
    grid = [float(x) for x in args.grid.split(",")]

    table = {}
    for name, rel in DATASETS:
        path = ROOT / rel
        if not path.exists():
            continue
        pairs, _ = load_pairs(path)
        for (mode, n, seed), pr in sorted(pairs.items()):
            cell = f"{mode}/{n}"
            prod_dir = (ROOT / "tuning_runs" / "ab_probe" / "production"
                        / f"{mode}_{n}_{seed}")
            cum = cumulative_move(prod_dir)
            delta = pr["ord"]["t_per_source"] - pr["base"]["t_per_source"]
            entry = table.setdefault((name, cell), {"deltas": [], "total_move": []})
            entry["deltas"].append((seed, delta, cum[-1] if cum else None))
            for x in grid:
                entry.setdefault(f"g{x:g}", []).append(
                    delta if activates(cum, x) else 0.0)

    print(f"{'dataset':10}{'cell':8}{'runs':>5}" +
          "".join(f"{x:>9.0f}" for x in grid) + f"{'ungated':>10}{'T_move_avg':>12}")
    summary = {x: {} for x in grid}
    for (name, cell), e in sorted(table.items()):
        row = f"{name:10}{cell:8}{len(e['deltas']):>5}"
        for x in grid:
            m = statistics.mean(e[f"g{x:g}"])
            summary[x].setdefault(cell, []).append(m)
            row += f"{m:>9.2f}"
        row += f"{statistics.mean(d for _s, d, _t in e['deltas']):>10.2f}"
        tm = [t for _s, _d, t in e["deltas"] if t]
        row += f"{statistics.mean(tm) if tm else float('nan'):>12.1f}"
        print(row)

    print("\n== per-cell mean over datasets, and the worst dataset ==")
    best = None
    for x in grid:
        line = f"X={x:>6.0f}  "
        ok = True
        for cell in ("Q3/10", "Q3/13", "Q3/16"):
            vals = summary[x].get(cell, [])
            if not vals:
                continue
            line += (f"{cell}: {statistics.mean(vals):+7.2f} "
                     f"[worst {max(vals):+7.2f}]  ")
            if max(vals) > 0:
                ok = False
        line += "  ALL<=0" if ok else ""
        print(line)
        if ok and (best is None or
                   statistics.mean([statistics.mean(summary[x][c])
                                    for c in ("Q3/10", "Q3/13", "Q3/16")
                                    if summary[x].get(c)]) < best[1]):
            best = (x, statistics.mean([statistics.mean(summary[x][c])
                                        for c in ("Q3/10", "Q3/13", "Q3/16")
                                        if summary[x].get(c)]))
    print(f"\nbest all-non-positive X: {best}")
    out = {"grid": grid,
           "table": {f"{k[0]}|{k[1]}": {kk: vv for kk, vv in v.items()
                                        if kk != "deltas"} |
                     {"deltas": v["deltas"]}
                     for k, v in table.items()},
           "best_all_non_positive": best}
    dest = ROOT / args.json
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
