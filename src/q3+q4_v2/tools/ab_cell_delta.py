"""Generic per-cell A/B comparison for ``ab_probe``-style JSON files.

Loads ``{arm: {"rows": [...]}}`` and prints, for every cell, the mean s/source of
each arm, the mean delta of every non-baseline arm versus the baseline, the
number of degraded runs, the four-ledger deltas and the complete/verifier flags.

Usage:
  python -X utf8 tools/ab_cell_delta.py tuning_runs/ab_q3trim_dev.json
  python -X utf8 tools/ab_cell_delta.py <json> --base production
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--base", default="production")
    args = ap.parse_args()
    path = Path(args.json)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text(encoding="utf-8"))
    arms = {k: {(r["mode"], int(r["n"]), int(r["seed"])): r
                for r in v.get("rows", [])}
            for k, v in data.items() if isinstance(v, dict) and "rows" in v}
    if args.base not in arms:
        print(f"baseline arm {args.base!r} not in {sorted(arms)}")
        return 1
    base = arms[args.base]
    cells = sorted({f"{m}/{n}" for (m, n, _s) in base},
                   key=lambda c: (c.split("/")[0], int(c.split("/")[1])))
    for arm, rows in arms.items():
        if arm == args.base:
            continue
        print(f"=== {arm} vs {args.base} ({path.name}) ===")
        print(f"{'cell':8}{'runs':>5}{'base':>10}{'arm':>10}{'meanD':>9}"
              f"{'worse':>7}{'maxD':>9}   ledger(move/meas/switch/clear)   flags")
        for cell in cells:
            keys = [k for k in base if f"{k[0]}/{k[1]}" == cell and k in rows]
            if not keys:
                continue
            b = [base[k]["t_per_source"] for k in keys]
            a = [rows[k]["t_per_source"] for k in keys]
            ds = [x - y for x, y in zip(a, b)]
            led = []
            for f in ("T_move", "T_measure", "T_switch", "T_clear"):
                try:
                    led.append(statistics.mean(rows[k][f] - base[k][f] for k in keys))
                except (KeyError, TypeError):
                    led.append(float("nan"))
            green = all(base[k].get("complete") and rows[k].get("complete")
                        and base[k].get("verifier_all_ok")
                        and rows[k].get("verifier_all_ok") for k in keys)
            ident = all(abs(x - y) < 1e-9 for x, y in zip(a, b))
            print(f"{cell:8}{len(keys):>5}{statistics.mean(b):>10.2f}"
                  f"{statistics.mean(a):>10.2f}{statistics.mean(ds):>+9.3f}"
                  f"{sum(1 for d in ds if d > 0):>4}/{len(ds):<2}"
                  f"{max(ds):>+9.2f}   {led[0]:+7.1f}/{led[1]:+6.1f}/"
                  f"{led[2]:+5.1f}/{led[3]:+5.1f}   "
                  f"{'green' if green else 'NOT-GREEN'}"
                  f"{' identical' if ident else ''}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
