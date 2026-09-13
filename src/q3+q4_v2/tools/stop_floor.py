"""Per-run floor: MST lower bound on travel + measured service time.

For a run directory:
  * stops = every position at which an action was taken (measure / clear),
  * travel floor = MST over {origin} ∪ stops  (any path visiting all of them is
    at least as long as the MST),
  * service floor = measured T_measure + T_switch + T_clear for that run (these
    costs do not depend on the route),
  * episode floor = travel floor + service floor, and the per-source value.

The floor is compared against a target (default: the goal's 176.25 for Q3 and
290 for Q4).  This is a *lower* bound for the current stop set: a different
policy could choose different stops, so a floor above target only rules out
"reordering the same stops", not every conceivable policy.

Usage:
  python -X utf8 tools/stop_floor.py [--target-n 16] <run_dir> [...]
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEED = 5.0


def load(run_dir: Path):
    stops: list[tuple[float, float]] = []
    svc = {"measure": 0.0, "switch": 0.0, "clear": 0.0}
    move = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = rec.get("dt") or {}
            move += float(dt.get("move") or 0.0)
            svc["measure"] += float(dt.get("measure") or 0.0)
            svc["switch"] += float(dt.get("switch") or 0.0)
            svc["clear"] += float(dt.get("clear") or 0.0)
            ep = rec.get("endpoint")
            if ep not in ("/measure", "/clear"):
                continue
            pos = (rec.get("request") or {}).get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            p = (float(pos["x"]), float(pos["y"]))
            if not stops or math.dist(stops[-1], p) > 1e-9:
                stops.append(p)
    return stops, svc, move


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
    target_n = 16
    args = list(argv[1:])
    if "--target-n" in args:
        i = args.index("--target-n")
        target_n = int(args[i + 1])
        del args[i:i + 2]
    dirs: list[Path] = []
    for raw in args:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / raw
        if any(ch in raw for ch in "*?["):
            dirs.extend(Path(m) for m in sorted(glob.glob(str(p))))
        else:
            dirs.append(p)

    out = []
    print("{:<44}{:>7}{:>9}{:>10}{:>10}{:>10}{:>9}{:>9}".format(
        "run", "stops", "actual_s", "svc_s", "mst_s", "floor_s", "floor/s", "target"))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        stops, svc, move = load(d)
        pts = [(0.0, 0.0)] + stops
        mst_s = mst_len(pts) / SPEED
        svc_s = sum(svc.values())
        floor = mst_s + svc_s
        mode = "Q3" if "Q3" in d.name else "Q4"
        target = 176.25 if mode == "Q3" else 290.0
        n_sources = target_n
        rec = {
            "run": str(d.relative_to(ROOT)),
            "stops": len(stops),
            "actual_move_s": round(move, 1),
            "actual_total_s": round(move + svc_s, 1),
            "service_s": round(svc_s, 1),
            "mst_travel_s": round(mst_s, 1),
            "episode_floor_s": round(floor, 1),
            "floor_per_source_s": round(floor / n_sources, 1),
            "target_per_source_s": target,
            "floor_above_target": bool(floor / n_sources > target),
        }
        out.append(rec)
        print("{run:<44}{stops:>7}{actual_total_s:>9.1f}{service_s:>10.1f}{mst_travel_s:>10.1f}"
              "{episode_floor_s:>10.1f}{floor_per_source_s:>9.1f}{target_per_source_s:>9.2f}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "stop_floor.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
