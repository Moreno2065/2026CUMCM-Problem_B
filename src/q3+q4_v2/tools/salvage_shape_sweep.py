"""Salvage the unanalyzed `prod+shape*` sweep (Q3 early-fallback ablation).

`tuning_runs/ab_probe/prod+shape3/5/8/_quiet/_g13/_g10/_g13` were run at
17:03-17:07 (12 seeds each) but only `prod+shape5_g10` was ever summarized -- and
that arm is what the production default now ships.  The other arms answer the
obvious follow-up: **is 5/g10 actually the best point of the grid?**

The runs come from one code revision window, but each arm covers a possibly
different seed set, so arms are compared **on the intersection of their seeds**
only, and the revision signature is reported for each arm.

Usage: python -X utf8 tools/salvage_shape_sweep.py [--base production]
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import statistics
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_arm(arm: str):
    runs = {}
    for d in sorted(glob.glob(str(ROOT / "tuning_runs/ab_probe" / arm / "*"))):
        run = pathlib.Path(d)
        cf, mf = run / "policy_config.json", run / "metrics.json"
        if not (cf.exists() and mf.exists()):
            continue
        cfg = json.loads(cf.read_text(encoding="utf-8"))
        met = json.loads(mf.read_text(encoding="utf-8"))
        if isinstance(met, dict) and "metrics" in met:
            met = met["metrics"]
        tps = met.get("t_per_source_s")
        if tps is None:
            continue
        mode, n, seed = run.name.split("_")
        sha = cfg.get("code_sha256") or {}
        runs[(mode, int(n), int(seed))] = {
            "tps": tps, "scheduler": str(sha.get("learned_search/scheduler.py"))[:16],
            "prod": str(sha.get("production.py"))[:16],
        }
    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="production")
    args = ap.parse_args()

    arms = sorted(p.name for p in (ROOT / "tuning_runs/ab_probe").iterdir()
                  if p.is_dir() and p.name.startswith("prod+shape"))
    data = {"production": load_arm("production")}
    for a in arms:
        data[a] = load_arm(a)
    base = data["production"]
    print("arms found:", ", ".join(arms))
    for a in arms:
        sigs = {(v["scheduler"], v["prod"]) for v in data[a].values()}
        seeds = sorted({k[2] for k in data[a]})
        print(f"  {a:22} n={len(data[a]):3d} seeds={len(seeds)} "
              f"revisions={len(sigs)} {sorted(sigs)[:2]}")
    print()
    cells = sorted({(k[0], k[1]) for r in data.values() for k in r})
    print(f"{'arm':22}" + "".join(f"{f'{m}/{n}':>22}" for m, n in cells))
    for a in ["production", *arms]:
        row = f"{a:22}"
        for cell in cells:
            sub = {k: v for k, v in data[a].items() if (k[0], k[1]) == cell}
            common = [k for k in sub if k in base]
            if not common:
                row += f"{'-':>22}"
                continue
            bm = statistics.mean(base[k]["tps"] for k in common)
            am = statistics.mean(sub[k]["tps"] for k in common)
            worse = sum(1 for k in common if sub[k]["tps"] > base[k]["tps"])
            row += f"{am:>10.2f}({am - bm:+6.2f},{worse}/{len(common)})"
        print(row)
    print("\n(format: arm mean s/source on the seeds shared with the baseline "
          "(delta vs baseline, degraded runs/shared runs))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
