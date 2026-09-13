"""Oracle floor: the travel any strategy must pay to visit the true source sites.

Uses ``ground_truth.json`` (offline oracle --- NOT usable by the policy) to answer
the reachability question "even a perfect planner must ...":

  * mandatory stops: every true source must be visited to be cleared
    (clear succeeds within 20 m regardless of facing);
  * travel floor = MST over {origin} ∪ {source positions}  (any path visiting all
    of them is at least the MST length);
  * service floor = the *minimum* service the completion criterion demands:
    5 s per successful clear + at least one measurement per source (5 s) +
    1 s per channel change.  Reported both as "minimal" (2 actions per source)
    and as "measured" (the episode's actual service time) to bracket reality.

Reports per-source values at the episode's own N.  This is an **oracle lower
bound for travel**: it ignores that the policy does not know the source
positions, so it is optimistic by construction.

Usage:
  python -X utf8 tools/oracle_floor.py <run_dir> [...]
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEED = 5.0


def sources(run_dir: Path) -> list[tuple[float, float]]:
    gt = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))
    pts: list[tuple[float, float]] = []

    def walk(node):
        if isinstance(node, dict):
            if "x" in node and "y" in node:
                pts.append((float(node["x"]), float(node["y"])))
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(gt)
    # de-duplicate identical coordinates
    out = []
    for p in pts:
        if not any(math.dist(p, q) < 1e-6 for q in out):
            out.append(p)
    return out


def service_s(run_dir: Path) -> float:
    total = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = rec.get("dt") or {}
            total += float(dt.get("measure") or 0.0) + float(dt.get("switch") or 0.0) + float(dt.get("clear") or 0.0)
    return total


def mst_len(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 2:
        return 0.0
    inside = {0}
    best = [math.dist(pts[0], pts[i]) for i in range(n)]
    total = 0.0
    while len(inside) < n:
        nxt = min((i for i in range(n) if i not in inside), key=lambda i: best[i])
        total += best[nxt]
        inside.add(nxt)
        for i in range(n):
            if i not in inside:
                d = math.dist(pts[nxt], pts[i])
                if d < best[i]:
                    best[i] = d
    return total


def main(argv: list[str]) -> int:
    dirs: list[Path] = []
    for raw in argv[1:]:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / raw
        if any(ch in raw for ch in "*?["):
            dirs.extend(Path(m) for m in sorted(glob.glob(str(p))))
        else:
            dirs.append(p)

    out = []
    print("{:<44}{:>5}{:>10}{:>10}{:>11}{:>11}{:>10}".format(
        "run", "N", "mst_s", "svc_min", "floor_min/s", "svc_act", "floor_act/s"))
    for d in dirs:
        if not (d / "ground_truth.json").exists():
            continue
        src = sources(d)
        if not src:
            continue
        n = len(src)
        mst_s = mst_len([(0.0, 0.0)] + src) / SPEED
        svc_min = 2 * 5.0 * n  # one measure + one clear per source
        svc_act = service_s(d)
        rec = {
            "run": str(d.relative_to(ROOT)),
            "n_sources": n,
            "mst_over_sources_s": round(mst_s, 1),
            "service_minimal_s": svc_min,
            "oracle_floor_minimal_per_source_s": round((mst_s + svc_min) / n, 1),
            "service_actual_s": round(svc_act, 1),
            "oracle_floor_actual_service_per_source_s": round((mst_s + svc_act) / n, 1),
        }
        out.append(rec)
        print("{run:<44}{n_sources:>5}{mst_over_sources_s:>10.1f}{service_minimal_s:>10.1f}"
              "{oracle_floor_minimal_per_source_s:>11.1f}{service_actual_s:>11.1f}"
              "{oracle_floor_actual_service_per_source_s:>10.1f}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "oracle_floor.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
