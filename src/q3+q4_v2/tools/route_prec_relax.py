"""Relaxed precedence model: how much does "re-pairing" buy over strict ordering?

`tools/route_lb_prec.py` (frozen for the t13 audit) keeps a *strict* precedence
model: every measure of channel c that precedes its clear must stay before it.
That forbids re-pairing --- a planner may instead re-take a bearing pair close to
the clear site, so only the *last couple* of measures really have to precede the
clear.

This tool computes three open paths over the same stop set:

  * ``strict``  : all earlier measures of c precede the clear of c;
  * ``loose``   : only the two measures of c nearest (geometrically) to the clear
                  precede it --- the clear may "re-pair";
  * ``free``    : no precedence at all (upper estimate of the optimum).

All three start at the origin and are built with greedy nearest-available plus
single-node relocation passes that keep the sequence a valid topological order.

Usage:
  python -X utf8 tools/route_prec_relax.py <run_dir> [...]
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
    stops, kinds, channels, move = [], [], [], 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            move += float((rec.get("dt") or {}).get("move") or 0.0)
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
    return stops, kinds, channels, move


def build_preds(stops, kinds, channels, model: str) -> list[set[int]]:
    """Return preds over pts indices (0 = origin, stop i -> i+1)."""
    preds: list[set[int]] = [set() for _ in range(len(stops) + 1)]
    history: dict[object, list[int]] = {}
    for i, (k, c) in enumerate(zip(kinds, channels)):
        if k == "/measure":
            history.setdefault(c, []).append(i)
        elif k == "/clear":
            prev = history.get(c, [])
            if model == "strict":
                chosen = list(prev)
            elif model == "loose":
                chosen = sorted(prev, key=lambda j: math.dist(stops[j], stops[i]))[:2]
            else:
                chosen = []
            preds[i + 1] = {j + 1 for j in chosen}
    return preds


def path_len(pts, order) -> float:
    return sum(math.dist(pts[order[i]], pts[order[i + 1]]) for i in range(len(order) - 1))


def feasible(order, preds) -> bool:
    pos = {n: i for i, n in enumerate(order)}
    return all(pos[u] < pos[v] for v, ps in enumerate(preds) for u in ps)


def greedy(pts, preds) -> list[int]:
    n = len(pts) - 1
    placed, order = {0}, [0]
    while len(order) < n + 1:
        cur = pts[order[-1]]
        cands = [v for v in range(1, n + 1) if v not in placed and preds[v] <= placed]
        if not cands:
            cands = [v for v in range(1, n + 1) if v not in placed]
            if not cands:
                break
        order.append(min(cands, key=lambda v: math.dist(cur, pts[v])))
        placed.add(order[-1])
    return order


def or_opt(pts, order, preds, rounds=3) -> list[int]:
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
                order, improved = best_order, True
        if not improved:
            break
    return order


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
    print("{:<40}{:>7}{:>10}{:>10}{:>10}{:>10}{:>9}{:>9}".format(
        "run", "stops", "actual_s", "strict_s", "loose_s", "free_s", "loose%", "free%"))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        stops, kinds, channels, move = load(d)
        pts = [(0.0, 0.0)] + stops
        res = {}
        for model in ("strict", "loose"):
            preds = build_preds(stops, kinds, channels, model)
            order = or_opt(pts, greedy(pts, preds), preds)
            assert feasible(order, preds)
            res[model] = path_len(pts, order) / SPEED
        preds_none: list[set[int]] = [set() for _ in pts]
        res["free"] = path_len(pts, or_opt(pts, greedy(pts, preds_none), preds_none)) / SPEED
        rec = {
            "run": str(d.relative_to(ROOT)),
            "stops": len(stops),
            "actual_move_s": round(move, 1),
            "strict_s": round(res["strict"], 1),
            "loose_s": round(res["loose"], 1),
            "free_s": round(res["free"], 1),
            "strict_headroom_pct": round((1 - res["strict"] / move) * 100, 1) if move else None,
            "loose_headroom_pct": round((1 - res["loose"] / move) * 100, 1) if move else None,
            "free_headroom_pct": round((1 - res["free"] / move) * 100, 1) if move else None,
        }
        out.append(rec)
        print("{run:<40}{stops:>7}{actual_move_s:>10.1f}{strict_s:>10.1f}{loose_s:>10.1f}"
              "{free_s:>10.1f}{loose_headroom_pct:>9}{free_headroom_pct:>9}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "route_prec_relax.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
