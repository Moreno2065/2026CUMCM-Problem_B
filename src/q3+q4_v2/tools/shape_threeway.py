"""Three-way check of the revision-matched shape arms (Q3 early fallback).

`probe/salvage_shape_sweep.py` compares each arm to `production`, whose runs may
come from other revisions.  The arms `prod+shape5_g10`, `prod+shape5_g13` and
`prod+shape8_g13` all sit on the SAME revision (scheduler 64f8b712c605d674 /
production d48def6a7b4fb0c2), so they can be compared directly on the seeds they
share -- which is the only question that matters: is the shipped 5/g10 the best
point of that grid?

Usage: python -X utf8 tools/shape_threeway.py
"""

from __future__ import annotations

import glob
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARMS = ["prod+shape5_g10", "prod+shape5_g13", "prod+shape8_g13"]


def load(arm):
    out = {}
    for d in sorted(glob.glob(str(ROOT / "tuning_runs/ab_probe" / arm / "*"))):
        run = pathlib.Path(d)
        mf = run / "metrics.json"
        if not mf.exists():
            continue
        met = json.loads(mf.read_text(encoding="utf-8"))
        if isinstance(met, dict) and "metrics" in met:
            met = met["metrics"]
        tps = met.get("t_per_source_s")
        if tps is None:
            continue
        mode, n, seed = run.name.split("_")
        out[(mode, int(n), int(seed))] = tps
    return out


def main() -> int:
    data = {a: load(a) for a in ARMS}
    common = set.intersection(*[set(v) for v in data.values()])
    print(f"arms: {ARMS}")
    print(f"shared runs across all three: {len(common)}")
    cells = sorted({(k[0], k[1]) for k in common})
    print(f"{'cell':8}{'runs':>5}" + "".join(f"{a.replace('prod+',''):>16}" for a in ARMS))
    for cell in cells:
        keys = [k for k in common if (k[0], k[1]) == cell]
        row = f"{cell[0] + '/' + str(cell[1]):8}{len(keys):>5}"
        best = None
        means = {}
        for a in ARMS:
            m = statistics.mean(data[a][k] for k in keys)
            means[a] = m
            if best is None or m < best[1]:
                best = (a, m)
        for a in ARMS:
            row += f"{means[a]:>16.2f}"
        row += f"   best={best[0].replace('prod+', '')}"
        print(row)
    print("\nper-run detail (shared runs only):")
    for cell in cells:
        keys = sorted(k for k in common if (k[0], k[1]) == cell)
        for k in keys:
            vals = "  ".join(f"{a.replace('prod+shape',''):>10}="
                             f"{data[a][k]:7.2f}" for a in ARMS)
            print(f"  {cell[0]}/{cell[1]} seed {k[2]:>5}  {vals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
