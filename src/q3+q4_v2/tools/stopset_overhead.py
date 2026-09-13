"""Where does each cell's distance to its lower bound live: travel or service?

For every run:
  * stops      = the positions at which the policy took an action,
  * sources    = the true source sites (offline oracle, ground_truth.json),
  * MST(origin ∪ stops)   and MST(origin ∪ sources)  -> stop-set travel overhead,
  * service    = T_measure + T_switch + T_clear (the run's own ledger),
  * floor      = MST(stops)/5 + service,   oracle_floor = MST(sources)/5 + service.

Reported per source.  The split tells you what a "closer to the bound" strategy
must attack: a large stop-set overhead means fewer/better stops, a large service
term means fewer measurements (or cheaper channel handling).

Usage:
  python -X utf8 tools/stopset_overhead.py <run_dir> [...]
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import load, mst_len  # noqa: E402
from oracle_floor import sources  # noqa: E402

SPEED = 5.0


def analyse(run_dir: Path, n: int) -> dict | None:
    if not (run_dir / "api_log.jsonl").exists():
        return None
    stops, svc, move = load(run_dir)
    src = sources(run_dir)
    if not src:
        return None
    mst_s = mst_len([(0.0, 0.0)] + stops) / SPEED
    mst_src = mst_len([(0.0, 0.0)] + src) / SPEED
    service = sum(svc.values())
    return {
        "run": str(run_dir.relative_to(ROOT)),
        "n": n,
        "stops": len(stops),
        "sources": len(src),
        "mst_stops_per_source": round(mst_s / n, 1),
        "mst_sources_per_source": round(mst_src / n, 1),
        "stopset_overhead_per_source": round((mst_s - mst_src) / n, 1),
        "service_per_source": round(service / n, 1),
        "floor_per_source": round((mst_s + service) / n, 1),
        "oracle_floor_per_source": round((mst_src + service) / n, 1),
        "overhead_share_pct": round((mst_s - mst_src) / (mst_s + service) * 100, 1),
    }


def main(argv: list[str]) -> int:
    targets: list[tuple[Path, int]] = []
    for raw in argv[1:]:
        if "=" in raw and raw.split("=")[0].isdigit():
            n_str, pattern = raw.split("=", 1)
            n = int(n_str)
        else:
            pattern, n = raw, 16
        p = Path(pattern)
        if not p.is_absolute():
            p = ROOT / pattern
        for m in sorted(glob.glob(str(p))):
            targets.append((Path(m), n))

    out = []
    print("{:<42}{:>5}{:>7}{:>11}{:>11}{:>11}{:>11}{:>10}{:>8}".format(
        "run", "N", "stops", "mst_stops", "mst_src", "overhead", "service", "floor", "ovh%"))
    for d, n in targets:
        rec = analyse(d, n)
        if not rec:
            continue
        out.append(rec)
        print("{run:<42}{n:>5}{stops:>7}{mst_stops_per_source:>11.1f}{mst_sources_per_source:>11.1f}"
              "{stopset_overhead_per_source:>11.1f}{service_per_source:>11.1f}"
              "{floor_per_source:>11.1f}{overhead_share_pct:>8.1f}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "stopset_overhead.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
