"""Minimum tour over the 25-point Q4 sparse mesh: floor for the certificate scan.

Establishes, independently of any policy run:
  * the mesh point set (from the engine's own ``q4_sparse_mesh``);
  * an MST-based lower bound on any closed tour (and ``MST - max_edge`` for an
    open path starting at the origin);
  * a nearest-neighbour + 2-opt + or-opt open path from the origin (upper bound);
  * exact Held-Karp on the two 12-point rings, to cross-check ring sub-tours.

Then converts metres to seconds at 5 m/s and reports the per-source floor at
N = 10 / 13 / 16, i.e. the travel a policy must pay if every mesh point has to be
visited.

Usage:
  python -X utf8 tools/mesh_tour_floor.py [--json out.json]
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.q4_sparse_mesh import q4_sparse25_points  # noqa: E402

SPEED = 5.0


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


def nn_2opt_oropt(pts: list[tuple[float, float]]) -> float:
    left = set(range(1, len(pts)))
    order = [0]
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda i: math.dist(last, pts[i]))
        order.append(nxt)
        left.discard(nxt)

    def length(o):
        return sum(math.dist(pts[o[i]], pts[o[i + 1]]) for i in range(len(o) - 1))

    improved = True
    while improved:
        improved = False
        n = len(order)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = pts[order[i - 1]], pts[order[i]]
                c = pts[order[j]]
                d = pts[order[j + 1]] if j + 1 < n else None
                before = math.dist(a, b) + (math.dist(c, d) if d else 0.0)
                after = math.dist(a, c) + (math.dist(b, d) if d else 0.0)
                if after + 1e-9 < before:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        for i in range(1, n):
            node = order[i]
            rest = order[:i] + order[i + 1:]
            cur = length(order)
            best_len, best_ord = cur, order
            for k in range(1, len(rest)):
                cand = rest[:k] + [node] + rest[k:]
                ln = length(cand)
                if ln + 1e-9 < best_len:
                    best_len, best_ord = ln, cand
            if best_len + 1e-9 < cur:
                order = best_ord
                improved = True
    return length(order)


def held_karp(pts: list[tuple[float, float]]) -> float:
    """Exact open path starting at index 0, free end (bitmask DP)."""
    n = len(pts)
    if n <= 2:
        return math.dist(pts[0], pts[1]) if n == 2 else 0.0
    dist = [[math.dist(a, b) for b in pts] for a in pts]
    full = 1 << (n - 1)
    INF = float("inf")
    dp = [[INF] * (n - 1) for _ in range(full)]
    for j in range(n - 1):
        dp[1 << j][j] = dist[0][j + 1]
    for mask in range(full):
        row = dp[mask]
        for j in range(n - 1):
            cur = row[j]
            if cur == INF or not (mask >> j) & 1:
                continue
            for k in range(n - 1):
                if (mask >> k) & 1:
                    continue
                nmask = mask | (1 << k)
                val = cur + dist[j + 1][k + 1]
                if val < dp[nmask][k]:
                    dp[nmask][k] = val
    return min(dp[full - 1])


def main(argv: list[str]) -> int:
    mesh = [(float(x), float(y)) for x, y in q4_sparse25_points()]
    origin = (0.0, 0.0)
    pts = [origin] + mesh
    mst = mst_len(pts)
    heur = nn_2opt_oropt(pts)

    # The mesh is a centre plus two rings (12 points at r=950, 13 at r=1870).
    # Split by radius, and never fold the origin into a ring: the earlier
    # version sorted by radius and took rings[:12], which put (0,0) inside the
    # inner ring and then passed [origin] + inner to Held-Karp, counting the
    # origin twice (bug found by the t13 audit).
    by_radius = sorted(mesh, key=lambda p: math.hypot(*p))
    inner_ring = [p for p in by_radius if math.hypot(*p) < 1200.0 and math.hypot(*p) > 1e-9]
    outer_ring = [p for p in by_radius if math.hypot(*p) >= 1200.0]
    hk_inner = held_karp([origin] + inner_ring) if len(inner_ring) + 1 <= 16 else None
    hk_outer = held_karp([origin] + outer_ring) if len(outer_ring) + 1 <= 16 else None

    out = {
        "mesh_points": len(mesh),
        "mst_over_origin_plus_mesh_m": round(mst, 1),
        "open_path_heuristic_m": round(heur, 1),
        "optimum_is_exact": bool(abs(heur - mst) < 1e-6),
        "optimum_note": (
            "MST <= OPT <= heuristic; when they coincide the open path is proven optimal"
            if abs(heur - mst) < 1e-6
            else "heuristic strictly above MST; OPT lies in between"
        ),
        "inner_ring_points": len(inner_ring),
        "outer_ring_points": len(outer_ring),
        "held_karp_inner_ring_m": None if hk_inner is None else round(hk_inner, 1),
        "held_karp_outer_ring_m": None if hk_outer is None else round(hk_outer, 1),
        "rings_are_separate_subproblems_note": (
            "the two ring sub-tours are NOT additive and their sum is not a bound "
            "(t13 audit); only mst_over_origin_plus_mesh_m is a valid lower bound"
        ),
        "per_source_floor_s": {
            str(n): round(mst / SPEED / n, 1) for n in (10, 13, 16)
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    dest = ROOT / "tuning_runs" / "mesh_tour_floor.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
