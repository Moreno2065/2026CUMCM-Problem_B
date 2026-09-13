"""Within-state signal test: are the observable features informative at all?

Across-state learning is confused by state-level variance (the same features
appear in different states with very different totals).  The cleaner question
is whether, *inside a single decision point*, any observable feature ranks the
candidates - that is what a model would need, and it is not limited by the
number of decision points.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = sys.argv[1:] or sorted(glob.glob(
        str(ROOT / "tuning_runs" / "teacher_v3_*.json")))
    rows = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for state in data["states"]:
            entries = [r for r in state.get("rows", []) if r.get("features")]
            if len(entries) < 10:
                continue
            rows.append((" %s seed%d idx%d" % (data["mode"], data["seed"],
                                              state["index"]), entries))
    if not rows:
        print("no states found")
        return 1
    keys = sorted(rows[0][1][0]["features"])
    print("states: %d, candidates per state: %s" %
          (len(rows), [len(e) for _, e in rows]))
    print()
    print("%-22s %s" % ("feature", "spearman rho per state (cost vs feature)"))
    summary = {}
    for key in keys:
        rhos = []
        for _, entries in rows:
            values = np.array([e["features"][key] for e in entries])
            if values.std() < 1e-9:
                rhos.append(0.0)
                continue
            cost = np.array([e["total"] for e in entries])
            rho = spearmanr(values, cost).statistic
            rhos.append(0.0 if np.isnan(rho) else float(rho))
        strong = sum(1 for r in rhos if abs(r) >= 0.3)
        consistent = max(sum(1 for r in rhos if r >= 0.3),
                         sum(1 for r in rhos if r <= -0.3))
        summary[key] = (strong, consistent)
        print("%-22s %s  |>=0.3| in %d/%d, same sign %d" %
              (key, " ".join("%+.2f" % r for r in rhos), strong, len(rhos),
               consistent))
    print()
    print("features whose |rho|>=0.3 in at least half the states with a "
          "consistent sign:")
    half = len(rows) / 2.0
    found = [k for k, (strong, consistent) in summary.items()
             if strong >= half and consistent >= half]
    print("   ", found if found else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
