"""Lower bound on routing slack: optimal-ish open path through a run's stops.

For a given run, collect every position at which the robot took an action
(measure / clear), plus the origin, and compute a nearest-neighbour + 2-opt +
or-opt open path starting at the origin.  Compare it with the movement actually
charged by the engine (sum of ``dt.move``).

Reading:
  * actual / heuristic  close to 1  -> routing is already near-optimal; travel
    can only fall by *visiting fewer/better-placed stops* (structure problem:
    certificate + route fusion).
  * actual / heuristic  large       -> the route order itself has slack; a
    better planner alone could save travel.

CAVEAT (do not oversell): the heuristic ignores precedence constraints (a clear
needs its bearing measurement first, bearing pairs need a baseline, ...), so the
achievable saving is generally *smaller* than the raw gap; and the heuristic is
itself an upper bound on the unconstrained optimum, so the gap is not a proof of
what a constrained planner can reach.  Treat the number as an *estimate of the
headroom*, to be confirmed by an A/B with plan_stop pricing.

Usage:
  python -X utf8 tools/route_lb.py <run_dir> [...]
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEED = 5.0


def stops(run_dir: Path) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("endpoint") not in ("/measure", "/clear"):
                continue
            pos = (rec.get("request") or {}).get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            p = (float(pos["x"]), float(pos["y"]))
            if not pts or math.dist(pts[-1], p) > 1e-9:
                pts.append(p)
    return pts


def actual_move_s(run_dir: Path) -> float:
    total = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += float((rec.get("dt") or {}).get("move") or 0.0)
    return total


def tour_len(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 2:
        return 0.0
    left = set(range(1, len(pts)))
    order = [0]
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda i: math.dist(last, pts[i]))
        order.append(nxt)
        left.discard(nxt)

    def length(o: list[int]) -> float:
        return sum(math.dist(pts[o[i]], pts[o[i + 1]]) for i in range(len(o) - 1))

    improved = True
    while improved:
        improved = False
        n = len(order)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = pts[order[i - 1]], pts[order[i]]
                c, d = pts[order[j]], (pts[order[j + 1]] if j + 1 < n else None)
                before = math.dist(a, b) + (math.dist(c, d) if d else 0.0)
                after = math.dist(a, c) + (math.dist(b, d) if d else 0.0)
                if after + 1e-9 < before:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        for i in range(1, n):  # or-opt: single-node relocation
            node = order[i]
            rest = order[:i] + order[i + 1:]
            best_pos, best_gain = i, 0.0
            cur = length(order)
            for k in range(1, len(rest)):
                cand = rest[:k] + [node] + rest[k:]
                if length(cand) + 1e-9 < cur - best_gain:
                    best_gain = cur - length(cand)
                    best_pos = k
            if best_gain > 1e-9:
                order = rest[:best_pos] + [node] + rest[best_pos:]
                improved = True
    return length(order)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
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
    print("{:<40}{:>7}{:>10}{:>10}{:>9}{:>9}".format("run", "stops", "actual_s", "heur_s", "ratio", "save%"))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        pts = [(0.0, 0.0)] + stops(d)
        act = actual_move_s(d)
        heur = tour_len(pts) / SPEED
        rec = {
            "run": str(d.relative_to(ROOT)),
            "stops": len(pts) - 1,
            "actual_move_s": round(act, 1),
            "heuristic_open_path_s": round(heur, 1),
            "ratio_actual_over_heuristic": round(act / heur, 3) if heur else None,
            "routing_headroom_estimate_pct": round((1 - heur / act) * 100, 1) if act else None,
        }
        out.append(rec)
        print("{run:<40}{stops:>7}{actual_move_s:>10.1f}{heuristic_open_path_s:>10.1f}"
              "{ratio_actual_over_heuristic:>9}{routing_headroom_estimate_pct:>9}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "route_lb.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
