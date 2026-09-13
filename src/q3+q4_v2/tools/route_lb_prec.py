"""Precedence-aware routing headroom.

`tools/route_lb.py` reorders *all* stops freely, which overstates what a planner
can do: a channel must be measured (bearing / MEC) before it is cleared.  This
tool rebuilds the same point set but keeps a precedence graph

    for every channel c with a clear at index i:  every measure of c at j < i
    must precede i

and then computes a *feasible* open path from the origin:

  1. greedy nearest-available (only nodes whose predecessors are already placed);
  2. single-node relocation (or-opt) passes that accept a move only when the
     resulting sequence is still a valid topological order.

Reported per run: actual movement (sum of dt.move), unconstrained open path
(route_lb-style, as an upper estimate of the optimum), and the feasible path.
The gap between actual and feasible is the routing headroom a constrained
planner can actually chase.

Usage:
  python -X utf8 tools/route_lb_prec.py <run_dir> [...]
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
    kinds: list[str] = []
    channels: list[object] = []
    move_s = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            move_s += float((rec.get("dt") or {}).get("move") or 0.0)
            ep = rec.get("endpoint")
            if ep not in ("/measure", "/clear"):
                continue
            req = rec.get("request") or {}
            pos = req.get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            p = (float(pos["x"]), float(pos["y"]))
            if stops and math.dist(stops[-1], p) <= 1e-9 and kinds[-1] == ep:
                continue
            stops.append(p)
            kinds.append(ep)
            channels.append(req.get("channel"))
    return stops, kinds, channels, move_s


def precedence(kinds: list[str], channels: list[object]) -> list[set[int]]:
    preds: list[set[int]] = [set() for _ in kinds]
    last_measure: dict[object, list[int]] = {}
    for i, (k, c) in enumerate(zip(kinds, channels)):
        if k == "/measure":
            last_measure.setdefault(c, []).append(i)
        elif k == "/clear":
            for j in last_measure.get(c, []):
                if j < i:
                    preds[i].add(j)
    return preds


def feasible(order: list[int], preds: list[set[int]]) -> bool:
    pos = {node: i for i, node in enumerate(order)}
    for v, ps in enumerate(preds):
        for u in ps:
            if pos[u] >= pos[v]:
                return False
    return True


def path_len(pts: list[tuple[float, float]], order: list[int]) -> float:
    return sum(math.dist(pts[order[i]], pts[order[i + 1]]) for i in range(len(order) - 1))


def greedy_feasible(pts: list[tuple[float, float]], preds: list[set[int]]) -> list[int]:
    n = len(pts) - 1  # index 0 is the origin
    placed = {0}
    order = [0]
    satisfied = [set() for _ in range(n + 1)]
    while len(order) < n + 1:
        cur = pts[order[-1]]
        best, best_d = None, math.inf
        for v in range(1, n + 1):
            if v in placed or not preds[v] <= placed:
                continue
            d = math.dist(cur, pts[v])
            if d < best_d:
                best, best_d = v, d
        if best is None:  # precedence cycle / dead end: fall back to nearest unplaced
            for v in range(1, n + 1):
                if v in placed:
                    continue
                d = math.dist(cur, pts[v])
                if d < best_d:
                    best, best_d = v, d
            if best is None:
                break
        order.append(best)
        placed.add(best)
    return order


def or_opt(pts: list[tuple[float, float]], order: list[int], preds: list[set[int]], rounds: int = 4) -> list[int]:
    n = len(order)
    for _ in range(rounds):
        improved = False
        for i in range(1, n):
            node = order[i]
            rest = order[:i] + order[i + 1:]
            base = path_len(pts, order)
            best_order, best_len = order, base
            for k in range(1, len(rest)):
                cand = rest[:k] + [node] + rest[k:]
                ln = path_len(pts, cand)
                if ln + 1e-9 < best_len and feasible(cand, preds):
                    best_order, best_len = cand, ln
            if best_len + 1e-9 < base:
                order = best_order
                improved = True
        if not improved:
            break
    return order


def unconstrained(pts: list[tuple[float, float]]) -> list[int]:
    left = set(range(1, len(pts)))
    order = [0]
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda i: math.dist(last, pts[i]))
        order.append(nxt)
        left.discard(nxt)
    return order


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
    print("{:<40}{:>7}{:>10}{:>11}{:>11}{:>9}{:>9}".format(
        "run", "stops", "actual_s", "free_s", "feasible_s", "free%", "feas%"))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        stops, kinds, channels, move_s = load(d)
        pts = [(0.0, 0.0)] + stops
        raw_preds = precedence(kinds, channels)
        # pts index 0 is the origin; stop i sits at pts index i + 1
        preds: list[set[int]] = [set()]
        for p in raw_preds:
            preds.append({u + 1 for u in p})
        free_order = or_opt(pts, unconstrained(pts), preds=[set() for _ in pts])
        free_s = path_len(pts, free_order) / SPEED
        feas_order = or_opt(pts, greedy_feasible(pts, preds), preds)
        assert feasible(feas_order, preds), f"infeasible order for {d}"
        feas_s = path_len(pts, feas_order) / SPEED
        n_pred_edges = sum(len(p) for p in preds)
        rec = {
            "run": str(d.relative_to(ROOT)),
            "stops": len(stops),
            "precedence_edges": n_pred_edges,
            "actual_move_s": round(move_s, 1),
            "free_path_s": round(free_s, 1),
            "feasible_path_s": round(feas_s, 1),
            "free_headroom_pct": round((1 - free_s / move_s) * 100, 1) if move_s else None,
            "feasible_headroom_pct": round((1 - feas_s / move_s) * 100, 1) if move_s else None,
        }
        out.append(rec)
        print("{run:<40}{stops:>7}{actual_move_s:>10.1f}{free_path_s:>11.1f}{feasible_path_s:>11.1f}"
              "{free_headroom_pct:>9}{feasible_headroom_pct:>9}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "route_lb_prec.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
