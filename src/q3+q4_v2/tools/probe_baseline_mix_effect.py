"""How much does the mixed-revision baseline move the headline numbers?

``tuning_runs/ab_probe/production`` holds runs produced by five different code
revisions (see ``probe_baseline_revisions.py``), and each seed exists only once,
so a per-cell mean averages runs from different codebases.  This tool quantifies
the effect: per-cell mean over all revisions versus the newest revision only.

Usage: python -X utf8 tools/probe_baseline_mix_effect.py
"""

from __future__ import annotations

import glob
import json
import pathlib
import statistics
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEWEST_PROD = "4377106baa371ae5"
CELLS = ("Q3_10", "Q3_13", "Q3_16", "Q4_10", "Q4_13", "Q4_16")


def main() -> int:
    groups = defaultdict(lambda: defaultdict(list))
    rows = []
    for d in sorted(glob.glob(str(ROOT / "tuning_runs/ab_probe/production/*"))):
        run = pathlib.Path(d)
        cf, rf = run / "policy_config.json", run / "run_report.json"
        if not (cf.exists() and rf.exists()):
            continue
        cfg = json.loads(cf.read_text(encoding="utf-8"))
        met = None
        mf = run / "metrics.json"
        if mf.exists():
            try:
                met = json.loads(mf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                met = None
        if isinstance(met, dict) and "metrics" in met:
            met = met["metrics"]
        if met is None:
            met = (json.loads(rf.read_text(encoding="utf-8")).get("metrics") or {})
        tps = met.get("t_per_source_s")
        if tps is None:
            continue
        sha = cfg.get("code_sha256") or {}
        sch = str(sha.get("learned_search/scheduler.py"))[:16]
        prod = str(sha.get("production.py"))[:16]
        rows.append({"run": run.name, "cell": "_".join(run.name.split("_")[:2]),
                     "scheduler": sch, "prod": prod, "tps": tps})
    print(f"{'cell':8}{'scheduler':18}{'prod':18}{'n':>4}{'mean tps':>11}{'sd':>8}")
    for r in sorted(rows, key=lambda x: (x["cell"], x["prod"], x["scheduler"])):
        pass
    by = defaultdict(list)
    for r in rows:
        by[(r["cell"], r["scheduler"], r["prod"])].append(r["tps"])
    for key in sorted(by):
        v = by[key]
        sd = statistics.pstdev(v) if len(v) > 1 else 0.0
        print(f"{key[0]:8}{key[1]:18}{key[2]:18}{len(v):>4}"
              f"{statistics.mean(v):>11.2f}{sd:>8.2f}")
    print()
    print(f"{'cell':8}{'n_all':>7}{'mean_all':>11}{'n_newest':>10}{'mean_newest':>13}"
          f"{'diff':>9}")
    for cell in CELLS:
        allv = [r["tps"] for r in rows if r["cell"] == cell]
        new = [r["tps"] for r in rows if r["cell"] == cell and r["prod"] == NEWEST_PROD]
        ma = statistics.mean(allv) if allv else float("nan")
        mn = statistics.mean(new) if new else float("nan")
        print(f"{cell:8}{len(allv):>7}{ma:>11.2f}{len(new):>10}{mn:>13.2f}"
              f"{mn - ma:>+9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
