"""KPI baseline for the new goal: how close is each cell to its lower bound?

Goal metric (pre-registered here):

    ratio(cell) = mean over runs of  (actual_s_per_source) / (floor_s_per_source)

where, for each run,
    actual_s_per_source = T_total / N,
    floor_s_per_source  = (MST(origin ∪ action stops) / MOVE_SPEED + service_s) / N,
    service_s           = T_measure + T_switch + T_clear  (the run's own ledger).

A ratio of 1.0 means the episode is as short as its own stop set allows; the
closer to 1, the better.  Reported per cell (mean / min / max) across the
production runs found in the given directories.

Usage:
  python -X utf8 tools/ratio_table.py --cells Q3:10=tuning_runs/ab_probe/production/Q3_10_* ...
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import load, mst_len  # noqa: E402

SPEED = 5.0
DEFAULT_CELLS = [
    ("Q3/10", "Q3", 10, "tuning_runs/ab_probe/production/Q3_10_*"),
    ("Q3/13", "Q3", 13, "tuning_runs/ab_probe/production/Q3_13_*"),
    ("Q3/16", "Q3", 16, "tuning_runs/ab_probe/production/Q3_16_*"),
    ("Q4/10", "Q4", 10, "tuning_runs/ab_probe/production/Q4_10_*"),
    ("Q4/13", "Q4", 13, "tuning_runs/ab_probe/production/Q4_13_*"),
    ("Q4/16", "Q4", 16, "tuning_runs/ab_probe/production/Q4_16_*"),
]


def cell_stats(pattern: str, n: int) -> dict:
    rows = []
    for d in sorted(Path(p) for p in glob.glob(str(ROOT / pattern))):
        if not (d / "api_log.jsonl").exists():
            continue
        stops, svc, move = load(d)
        svc_s = sum(svc.values())
        mst_s = mst_len([(0.0, 0.0)] + stops) / SPEED
        actual = move + svc_s
        floor = mst_s + svc_s
        # oracle denominator: MST over the TRUE source sites + the same service term.
        # It does not move when a variant changes its stop set, so it separates a real
        # improvement from a denominator effect.
        mst_src = None
        try:
            from oracle_floor import sources  # local import: optional dependency
            src = sources(d)
            if src:
                mst_src = mst_len([(0.0, 0.0)] + src) / SPEED
        except Exception:
            mst_src = None
        rows.append(
            {
                "run": d.name,
                "n": n,
                "actual_s": round(actual, 1),
                "floor_s": round(floor, 1),
                "actual_per_source": round(actual / n, 2),
                "floor_per_source": round(floor / n, 2),
                "ratio": round(actual / floor, 4) if floor else None,
                "ratio_move_only": round(move / mst_s, 4) if mst_s else None,
                "oracle_floor_s": None if mst_src is None else round(mst_src + svc_s, 1),
                "ratio_oracle": None if mst_src is None else round(actual / (mst_src + svc_s), 4),
            }
        )
    if not rows:
        return {"runs": 0}
    ratios = [r["ratio"] for r in rows if r["ratio"]]
    oratios = [r["ratio_oracle"] for r in rows if r.get("ratio_oracle")]
    return {
        "runs": len(rows),
        "ratio_mean": round(sum(ratios) / len(ratios), 4),
        "ratio_min": min(ratios),
        "ratio_max": max(ratios),
        "ratio_oracle_mean": round(sum(oratios) / len(oratios), 4) if oratios else None,
        "actual_per_source_mean": round(sum(r["actual_per_source"] for r in rows) / len(rows), 2),
        "floor_per_source_mean": round(sum(r["floor_per_source"] for r in rows) / len(rows), 2),
        "ratio_move_only_mean": round(
            sum(r["ratio_move_only"] for r in rows if r["ratio_move_only"]) / len(rows), 4
        ),
        "detail": rows,
    }


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    root = "tuning_runs/ab_probe/production"
    if "--root" in args:
        i = args.index("--root")
        root = args[i + 1].rstrip("/\\")
    cells = [
        (name, mode, n, f"{root}/Q{('3' if mode == 'Q3' else '4')}_{n}_*")
        for name, mode, n, _pat in DEFAULT_CELLS
    ]
    out = {}
    print(f"root = {root}")
    print("{:<8}{:>6}{:>12}{:>12}{:>10}{:>10}{:>11}".format(
        "cell", "runs", "actual/s", "floor/s", "ratio", "move-only", "ratio(oracle)"))
    for name, _mode, n, pattern in cells:
        st = cell_stats(pattern, n)
        out[name] = st
        if st.get("runs"):
            print("{:<8}{:>6}{:>12.2f}{:>12.2f}{:>10.4f}{:>10.4f}{:>11}".format(
                name, st["runs"], st["actual_per_source_mean"], st["floor_per_source_mean"],
                st["ratio_mean"], st["ratio_move_only_mean"],
                "-" if st.get("ratio_oracle_mean") is None else f"{st['ratio_oracle_mean']:.4f}"))
    tag = root.replace("/", "_").replace("\\", "_")
    dest = ROOT / "tuning_runs" / f"ratio_table_{tag}.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
