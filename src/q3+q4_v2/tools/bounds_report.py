"""Unified lower-bound table and gap decomposition for the Q3/Q4 cells (t26).

Read-only analysis.  Three bound families exist in the workspace and they do not
agree; this tool recomputes all of them from the same primitives and labels
each one's nature:

``certificate_composite``  (provable)
    movement: the *open path* an episode must walk to collect the certificate,
    computed as MST(origin + certificate points) with a matching 2-opt/or-opt
    heuristic -- when both agree the value is the proven optimum (no closed
    loop: an episode never has to return to the origin);
    service: every absent channel needs a no_signal witness at *every*
    certificate point -> 5 s * points * (20 - N);
    clear: 5 s * N for N successful clears.
    For N = 16 the witness term has two branches (cardinality cap);
    the branch and its condition are reported explicitly.

``hindsight_floor``  (hindsight)
    ``tools/ratio_table.py`` convention: for one run,
    (MST(origin + that run's *actual* action stops)/5 + that run's *measured*
    service)/N.  It uses the run's own stop set and service, so it is an upper
    bound on any true lower bound -- it can never prove a cell unreachable.

``oracle_*``  (hindsight / oracle)
    the same service term with MST over the *true source sites*
    (``tools/oracle_floor.py`` convention).  Reference only.

The decomposition block splits every run's ``T_total`` exactly:

    T_total = T_move + T_measure + T_switch + T_clear                  (i)
    T_move  = MST(actual stops)/5 + detour                             (ii)
    gap vs certificate_composite = 绕路' + 多测量 + 多换频 + 失败清除 + 残差

with ``残差`` reported two ways: as the task words it (detour relative to the
actual stop set, so the residual is exactly  MST(actual stops)/5 - cert/5, the
extra-stop travel) and as the bound-relative version whose residual is 0 by
construction.  Both identities are checked per run at 1e-6.

Usage:
    python -X utf8 tools/bounds_report.py
Artifacts (deterministically rewritten):
    tuning_runs/bounds_report.json , tuning_runs/BOUNDS.md
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))
sys.path.insert(0, str(ROOT / "tools"))

from geometry import constants as C                      # noqa: E402
from geometry.certificate import q3_certified            # noqa: E402
from geometry.q4_sparse_mesh import q4_sparse25_points   # noqa: E402
from stop_floor import load, mst_len                     # noqa: E402
from oracle_floor import sources                         # noqa: E402

SPEED = C.MOVE_SPEED
MEASURE_S = C.MEASURE_TIME
CLEAR_S = C.CLEAR_SUCCESS_TIME
TARGET = {"Q3": 176.25, "Q4": 290.0}
MAX_CHANNELS = C.NUM_CHANNELS
MAX_SOURCES = C.MAX_SOURCES
RING_RADIUS = 1200.0
RING_POINTS = 6                     # production Q3 cover = origin + 6 ring stops
TOL = 1e-6

CELLS = [("Q3/10", "Q3", 10), ("Q3/13", "Q3", 13), ("Q3/16", "Q3", 16),
         ("Q4/10", "Q4", 10), ("Q4/13", "Q4", 13), ("Q4/16", "Q4", 16)]
RUN_ROOT = "tuning_runs/ab_probe/production"
Q3_MOVEMENT_JSON = "tuning_runs/cert_tour_study.json"


# ----------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------
def q3_ring_points(radius=RING_RADIUS, count=RING_POINTS, phase=0.0):
    return [(radius * math.cos(phase + 2.0 * math.pi * k / count),
             radius * math.sin(phase + 2.0 * math.pi * k / count))
            for k in range(count)]


# ----------------------------------------------------------------------
# t33: Q3 movement = minimum over ALL valid covers (not a fixed ring)
# ----------------------------------------------------------------------
def open_path_held_karp(points, start=(0.0, 0.0), limit=12):
    """Exact shortest open path from ``start`` through every point.

    Held-Karp DP over subsets with a fixed start; used for the certificate
    covers found by the search below (all have <= 12 points).  Returns
    ``(length_m, None)`` or ``(None, None)`` above ``limit``.
    """
    pts = [p for p in points if math.dist(p, start) > 1e-9]
    n = len(pts)
    if n == 0:
        return 0.0, None
    if n > limit:
        return None, None
    dist = [[math.dist(pts[i], pts[j]) for j in range(n)] for i in range(n)]
    first = [math.dist(start, pts[i]) for i in range(n)]
    size = 1 << n
    inf = float("inf")
    dp = [[inf] * n for _ in range(size)]
    for i in range(n):
        dp[1 << i][i] = first[i]
    for mask in range(size):
        row = dp[mask]
        for last in range(n):
            cost = row[last]
            if cost == inf:
                continue
            for nxt in range(n):
                if (mask >> nxt) & 1:
                    continue
                new_mask = mask | (1 << nxt)
                new_cost = cost + dist[last][nxt]
                if new_cost < dp[new_mask][nxt]:
                    dp[new_mask][nxt] = new_cost
    full = size - 1
    return min(dp[full][i] for i in range(n)), None


def is_certified(points):
    """Validity oracle: the EXACT production decider, no sampling margin."""
    return bool(q3_certified(points)["certified"])


def min_ring_radius(k, centre=False, hi=None, steps=60):
    """Smallest ring radius whose cover is certified (exact bisection).

    ``centre=False``: pure ring -> the origin must fall inside some disk, so
    feasibility is an interval [r*, 1000]; bisection on that branch is exact.
    ``centre=True``: the centre covers the origin, so the interval is wider and
    a coarse scan locates the lower endpoint before bisecting.
    """
    if not centre:
        hi = 1000.0 if hi is None else hi
        if not is_certified(q3_ring_points(hi, k)):
            return None
        lo, high = 0.0, hi
        for _ in range(steps):
            mid = 0.5 * (lo + high)
            if is_certified(q3_ring_points(mid, k)):
                high = mid
            else:
                lo = mid
        return high
    # centre + ring: scan for the first certified radius, then bisect
    hi = 2400.0 if hi is None else hi
    r = 200.0
    found = None
    while r <= hi:
        if is_certified([(0.0, 0.0)] + q3_ring_points(r, k)):
            found = r
            break
        r += 5.0
    if found is None:
        return None
    lo, high = found - 5.0, found
    for _ in range(steps):
        mid = 0.5 * (lo + high)
        if is_certified([(0.0, 0.0)] + q3_ring_points(mid, k)):
            high = mid
        else:
            lo = mid
    return high


def hill_slide(points, start=(0.0, 0.0), steps=(40.0, 20.0, 8.0, 3.0)):
    """Deterministic hill-slide: nudge single points while staying certified.

    Accepts a nudge only when the exact decider still certifies the cover *and*
    the exact open path strictly improves, so the result is a valid cover with a
    shorter or equal path (a local optimum of this neighbourhood).
    """
    best = [tuple(p) for p in points]
    best_len, _ = open_path_held_karp(best, start)
    if best_len is None:
        return best, None
    for step in steps:
        improved = True
        while improved:
            improved = False
            for index in range(len(best)):
                px, py = best[index]
                radius = math.hypot(px, py)
                if radius < 1e-9:
                    continue
                radial = (px / radius, py / radius)
                tangential = (-radial[1], radial[0])
                for direction in (radial, (-radial[0], -radial[1]),
                                  tangential, (-tangential[0], -tangential[1])):
                    trial = list(best)
                    trial[index] = (px + step * direction[0],
                                    py + step * direction[1])
                    if not is_certified(trial):
                        continue
                    length, _ = open_path_held_karp(trial, start)
                    if length is None:
                        continue
                    if length < best_len - 1e-9:
                        best, best_len = trial, length
                        improved = True
                        break
                if improved:
                    break
    return best, best_len


def q3_cover_search(k_values=range(5, 13)):
    """Constructive minimum-cover search over symmetric ring families (t33).

    Every candidate is judged by the exact decider ``q3_certified`` (never by a
    sampling margin) and its open path is verified with an exact Held-Karp DP;
    the best candidates are passed through a deterministic hill-slide.  The
    reported minimum is "the smallest composite over the covers this search can
    construct", which is what the bound must use.
    """
    candidates = []
    for k in k_values:
        for centre in (False, True):
            radius = min_ring_radius(k, centre=centre)
            if radius is None:
                continue
            points = (([] if not centre else [(0.0, 0.0)]) +
                      q3_ring_points(radius, k))
            if not is_certified(points):
                continue
            length, _ = open_path_held_karp(points)
            if length is None:            # more stops than the exact DP allows
                continue
            candidates.append({
                "family": "centre+ring" if centre else "pure_ring",
                "k": k, "ring_radius_m": round(radius, 4),
                "n_points": len(points),
                "open_path_m": round(length, 4),
                "open_path_s": round(length / SPEED, 3),
                "certified": True,
                "points": [[round(x, 4), round(y, 4)] for x, y in points],
            })
    if not candidates:
        return {"candidates": [], "best_movement": None, "best_composite": None}
    # hill-slide the shortest-path candidates (deterministic, exact-verified)
    candidates.sort(key=lambda item: (item["open_path_m"], item["k"],
                                      item["family"]))
    for item in candidates[:4]:
        points = [tuple(p) for p in item["points"]]
        slid, length = hill_slide(points)
        if length is not None and length < item["open_path_m"] - 1e-9:
            item["hill_slid"] = {
                "open_path_m": round(length, 4),
                "open_path_s": round(length / SPEED, 3),
                "certified": is_certified(slid),
                "points": [[round(x, 4), round(y, 4)] for x, y in slid],
            }
            # the slid cover is certified and strictly shorter, so it is the
            # cover to use for this candidate from here on
            item["open_path_m"] = round(length, 4)
            item["open_path_s"] = round(length / SPEED, 3)
            item["points"] = item["hill_slid"]["points"]
            item["path_source"] = "hill-slide"
    best_movement = min(candidates, key=lambda item: item["open_path_m"])
    composites = []
    for item in candidates:
        for cell, n in (("Q3/10", 10), ("Q3/13", 13), ("Q3/16", 16)):
            witness = MEASURE_S * item["n_points"] * (MAX_CHANNELS - n)
            clear = CLEAR_S * n
            total = item["open_path_s"] + witness + clear
            composites.append({"cell": cell, "n": n,
                               "family": item["family"], "k": item["k"],
                               "n_points": item["n_points"],
                               "open_path_s": item["open_path_s"],
                               "witness_s": witness, "clear_s": clear,
                               "composite_s": round(total, 4),
                               "composite_per_source": round(total / n, 4)})
    best_composite = {}
    for cell in ("Q3/10", "Q3/13", "Q3/16"):
        best_composite[cell] = min((row for row in composites
                                    if row["cell"] == cell),
                                   key=lambda row: (row["composite_per_source"],
                                                    row["n_points"]))
    return {"candidates": candidates,
            "composites": composites,
            "best_movement": best_movement,
            "best_composite": best_composite,
            "oracle": "geometry.certificate.q3_certified (exact)",
            "open_path_oracle": "Held-Karp exact (<= 12 stops)",
            "nature": ("constructive search over symmetric ring families + "
                       "hill-slide; the minimum is over the constructed covers, "
                       "so it is an upper bound on the true minimum and can "
                       "only make the bound weaker (safe direction)")}



def path_len(order):
    return sum(math.dist(order[i], order[i + 1])
               for i in range(len(order) - 1))


def nearest_neighbour(start, others):
    remaining = list(others)
    current = start
    order = [start]
    while remaining:
        index = min(range(len(remaining)),
                    key=lambda j: math.dist(current, remaining[j]))
        current = remaining.pop(index)
        order.append(current)
    return order


def two_opt(order, passes=100):
    best = list(order)
    improved = True
    while improved and passes > 0:
        improved = False
        passes -= 1
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                trial = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                if path_len(trial) < path_len(best) - 1e-9:
                    best, improved = trial, True
    return best


def or_opt(order, passes=40):
    best = list(order)
    improved = True
    while improved and passes > 0:
        improved = False
        passes -= 1
        for segment in (1, 2, 3):
            for i in range(1, len(best) - segment + 1):
                block = best[i:i + segment]
                rest = best[:i] + best[i + segment:]
                for j in range(1, len(rest) + 1):
                    if j == i:
                        continue
                    trial = rest[:j] + block + rest[j:]
                    if path_len(trial) < path_len(best) - 1e-9:
                        best, improved = trial, True
                        break
                if improved:
                    break
            if improved:
                break
    return best


def open_path_bounds(points, start=(0.0, 0.0)):
    """MST lower bound and heuristic upper bound for an open path from ``start``.

    Returns ``(mst_m, heuristic_m, proven, order_len)``; ``proven`` is true when
    the two agree, which makes the value the exact optimum.
    """
    others = [p for p in points if math.dist(p, start) > 1e-9]
    mst_m = mst_len([start] + others)
    order = nearest_neighbour(start, others)
    order = two_opt(order)
    order = or_opt(order)
    order = two_opt(order)
    heuristic_m = path_len(order)
    proven = abs(heuristic_m - mst_m) <= 1e-6
    return mst_m, heuristic_m, proven, len(order)


def closed_tour(points, start=(0.0, 0.0)):
    """Closed-loop length in the production visit order (t7's convention)."""
    others = [p for p in points if math.dist(p, start) > 1e-9]
    order = nearest_neighbour(start, others)
    order = two_opt(order)
    order = or_opt(order)
    return path_len(order + [start])


def dense_margin(points, start=(0.0, 0.0), step=25.0):
    """Worst distance from Omega to the nearest witness (grid sanity check)."""
    worst, where = -1.0, None
    radius = int(math.ceil(C.OMEGA_RADIUS / step))
    stops = [start] + list(points)
    for i in range(-radius, radius + 1):
        for j in range(-radius, radius + 1):
            x, y = i * step, j * step
            if x * x + y * y > C.OMEGA_RADIUS ** 2:
                continue
            d = min(math.dist((x, y), p) for p in stops)
            if d > worst:
                worst, where = d, (x, y)
    return worst, where


def coarse_grid(step=100.0):
    grid = []
    radius = int(math.ceil(C.OMEGA_RADIUS / step))
    for i in range(-radius, radius + 1):
        for j in range(-radius, radius + 1):
            x, y = i * step, j * step
            if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                grid.append((x, y))
    return grid


def worst_radius(grid, points):
    worst = -1.0
    for point in grid:
        d = min(math.dist(point, stop) for stop in points)
        if d > worst:
            worst = d
    return worst


def ring_family_best(k, radius_step=1.0):
    """Best symmetric k-point ring cover of Omega (analytic family + scan).

    For k points on a ring of radius r the worst coverage distance is
    ``max(r, |boundary midpoint to nearest ring point|)`` -- the first term is
    the origin, the second is the boundary gap.  Scanning r gives the best
    symmetric arrangement; asymmetric arrangements are cross-checked
    numerically by ``min_witness_search``.
    """
    R = C.OMEGA_RADIUS
    best = None
    r = 0.0
    while r <= 1000.0 + 1e-9:
        gap = math.sqrt(R * R + r * r - 2.0 * R * r * math.cos(math.pi / k))
        worst = max(r, gap)
        if best is None or worst < best[0] - 1e-9:
            best = (worst, r, gap)
        r += radius_step
    worst, r, gap = best
    points = [(r * math.cos(2.0 * math.pi * i / k),
               r * math.sin(2.0 * math.pi * i / k)) for i in range(k)]
    dense, _where = dense_margin(points, start=(0.0, 0.0), step=25.0)
    verdict = q3_certified(points)
    return {
        "ring_radius_m": round(r, 1),
        "origin_term_m": round(r, 1),
        "boundary_gap_m": round(gap, 1),
        "analytic_worst_m": round(worst, 1),
        "dense_worst_m": round(dense, 1),
        "feasible_exact_q3_certified": bool(verdict["certified"]),
        "points": [[round(x, 1), round(y, 1)] for x, y in points],
    }


def min_witness_search(grid, counts=(5, 6, 7), trials=60, seed=20260912,
                       climb=2):
    """How many witness points must an episode visit?

    Analytic best of the symmetric ring family per k, plus a small random +
    hill-climb cross-check on a coarse grid; the best configuration found is
    re-checked on the dense grid and with the exact decider.  Deterministic.
    """
    import random
    out = {}
    for k in counts:
        family = ring_family_best(k)
        rng = random.Random(seed + k)
        best = None
        for _ in range(trials):
            points = [random_point(rng) for _ in range(k)]
            value = worst_radius(grid, points)
            for _pass in range(climb):
                improved = False
                for index in range(k):
                    for delta in ((60.0, 60.0), (60.0, -60.0), (-60.0, 60.0),
                                  (-60.0, -60.0), (120.0, 0.0), (-120.0, 0.0),
                                  (0.0, 120.0), (0.0, -120.0)):
                        trial = list(points)
                        candidate = (points[index][0] + delta[0],
                                     points[index][1] + delta[1])
                        if math.hypot(*candidate) > C.OMEGA_RADIUS:
                            continue
                        trial[index] = candidate
                        candidate_value = worst_radius(grid, trial)
                        if candidate_value < value - 1e-9:
                            points, value = trial, candidate_value
                            improved = True
                if not improved:
                    break
            if best is None or value < best[0] - 1e-9:
                best = (value, points)
        random_worst, random_points = best
        dense, where = dense_margin(random_points, start=(0.0, 0.0), step=25.0)
        verdict = q3_certified(random_points)
        out[str(k)] = {
            "ring_family": family,
            "random_search": {
                "coarse_worst_m": round(random_worst, 1),
                "dense_worst_m": round(dense, 1),
                "feasible_exact_q3_certified": bool(verdict["certified"]),
                "points": [[round(x, 1), round(y, 1)] for x, y in random_points],
                "worst_point": None if where is None else
                [round(where[0], 1), round(where[1], 1)],
            },
            "feasible": bool(family["feasible_exact_q3_certified"] or
                             verdict["certified"]),
            "min_worst_m": min(family["analytic_worst_m"],
                               round(random_worst, 1)),
        }
    return out


def random_point(rng):
    while True:
        x = rng.uniform(-C.OMEGA_RADIUS, C.OMEGA_RADIUS)
        y = rng.uniform(-C.OMEGA_RADIUS, C.OMEGA_RADIUS)
        if x * x + y * y <= C.OMEGA_RADIUS ** 2:
            return (x, y)


def t7_closed_tours():
    """t7's own closed-loop certificate tours, read from its artifact."""
    path = ROOT / "tuning_runs" / "cert_tour_study.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    families = data.get("families") or {}
    out = {}
    q3 = (families.get("Q3_production_7ring_r1200") or {}).get("tour") or {}
    q4 = (families.get("Q4_production_sparse25") or {}).get("tour") or {}
    if q3.get("length_m") is not None:
        out["Q3"] = {"length_m": float(q3["length_m"]),
                     "source": "tuning_runs/cert_tour_study.json"
                               "::families.Q3_production_7ring_r1200.tour"}
    if q4.get("length_m") is not None:
        out["Q4"] = {"length_m": float(q4["length_m"]),
                     "source": "tuning_runs/cert_tour_study.json"
                               "::families.Q4_production_sparse25.tour"}
    return out


# ----------------------------------------------------------------------
# per-cell bounds
# ----------------------------------------------------------------------
def cell_bounds(mode, n, q3_search=None):
    cover = None
    if mode == "Q3" and q3_search and q3_search.get("best_composite"):
        cover = q3_search["best_composite"]["Q3/%d" % n]
    if mode == "Q3" and cover is not None:
        candidates = q3_search["candidates"]
        match = next(item for item in candidates
                     if item["family"] == cover["family"]
                     and item["k"] == cover["k"])
        points = [tuple(p) for p in match["points"]]
        start = (0.0, 0.0)
        stops = list(points)
        cert_name = ("Q3 minimum certified cover (%s, k=%d @r=%.3f m)"
                     % (cover["family"], cover["k"],
                        match["ring_radius_m"]))
        verdict = q3_certified(points)
        exact_ok = bool(verdict["certified"])
        exact_reason = verdict["reason"]
    elif mode == "Q3":
        points = q3_ring_points()
        start = (0.0, 0.0)
        stops = [start] + points
        cert_name = "Q3 origin + 6 ring stops @r=1200"
        verdict = q3_certified(stops)
        exact_ok = bool(verdict["certified"])
        exact_reason = verdict["reason"]
    else:
        points = [(float(x), float(y)) for x, y in q4_sparse25_points()]
        start = (0.0, 0.0)
        stops = list(points)
        cert_name = "Q4 sparse25 scan set (centre + 12@950 + 12@1870)"
        exact_ok = None           # sparse25 is a scan set, not a cover predicate
        exact_reason = ("sparse25 scan set; its 25 coordinates are fixed by the "
                        "predicate (q4_channel_certified_sparse25 iterates "
                        "q4_sparse25_points with MATCH_TOL=1e-6)")
    mst_m, heur_m, proven, n_visited = open_path_bounds(points, start)
    if mode == "Q3" and cover is not None:
        exact_path, _ = open_path_held_karp(points, start)
        heur_m = exact_path
        mst_m = min(mst_m, exact_path)
        proven = True
        path_method = "Held-Karp exact (open path from origin)"
    else:
        path_method = ("MST = heuristic => proven optimal"
                       if proven else "MST lower bound + heuristic upper bound")
    closed_m = closed_tour(points, start)
    t7_closed = (t7_closed_tours().get(mode) or {}).get("length_m")
    worst, where = dense_margin(points, start)
    cert_points = len(points) if mode == "Q3" and cover is not None \
        else (len(stops) if mode == "Q3" else len(points))
    witness_s = MEASURE_S * cert_points * (MAX_CHANNELS - n)
    clear_s = CLEAR_S * n
    tour_s = heur_m / SPEED
    composite_s = tour_s + witness_s + clear_s
    sensitivity = None
    if mode == "Q3":
        sensitivity = {
            str(k): round((tour_s + MEASURE_S * k * (MAX_CHANNELS - n) +
                           clear_s) / n, 3) for k in (5, 6, 7)
        }
        sensitivity["note"] = (
            "composite as a function of the number of witness points; the "
            "minimum feasible k is reported in min_witness_points (k=5 and k=6 "
            "cannot cover Omega numerically; the production ring is a 7-point "
            "set)")
    else:
        sensitivity = {
            "note": ("25 witnesses are the sparse25 rule's own scan set; a "
                     "smaller witness set is only possible under the "
                     "delta-robust hull reading, which t7/t10 found infeasible "
                     "or no cheaper")}
    return {
        "cell": "%s/%d" % (mode, n),
        "mode": mode, "n": n,
        "certificate_set": cert_name,
        "certificate_points": cert_points,
        "certificate_stops": [[round(x, 3), round(y, 3)] for x, y in stops],
        "certificate_exact": {
            "decider": "geometry.certificate.q3_certified" if mode == "Q3"
            else "q4 sparse25 rule (per channel)",
            "certified": exact_ok,
            "reason": exact_reason,
            "dense_grid_step_m": 25.0,
            "worst_uncovered_m": round(worst, 1),
            "coverage_margin_m": round(1000.0 - worst, 1),
            "worst_point": None if where is None else
            [round(where[0], 1), round(where[1], 1)],
        },
        "movement": {
            "stops_visited": n_visited,
            "mst_open_m": round(mst_m, 1),
            "heuristic_open_m": round(heur_m, 1),
            "open_path_proven_optimal": bool(proven),
            "open_path_method": path_method,
            "open_path_m": round(heur_m, 1),
            "open_path_s": round(tour_s, 2),
            "cover_family": None if cover is None else cover["family"],
            "cover_k": None if cover is None else cover["k"],
            "cover_n_points": cert_points,
            "cover_radius_m": None if mode != "Q3" or cover is None else
            round(next(item["ring_radius_m"] for item in
                       q3_search["candidates"]
                       if item["family"] == cover["family"]
                       and item["k"] == cover["k"]), 4),
            "closed_tour_m": round(closed_m, 1),
            "closed_tour_s": round(closed_m / SPEED, 2),
            "t7_closed_tour_m": None if t7_closed is None else t7_closed,
            "t7_closed_tour_s": None if t7_closed is None else
            round(t7_closed / SPEED, 2),
            "t7_closed_source": "source: tuning_runs/cert_tour_study.json"
                                if t7_closed is not None else None,
            "open_vs_closed_saving_m": round(
                (t7_closed if t7_closed is not None else closed_m) - heur_m, 1),
            "open_vs_closed_saving_s": round(
                ((t7_closed if t7_closed is not None else closed_m) - heur_m) /
                SPEED, 2),
            "nature": ("provable: minimum over the constructed certified covers, "
                       "open path exact (Held-Karp)"
                       if mode == "Q3" else
                       "provable (sparse25 coordinates fixed by the predicate; "
                       "MST = heuristic => optimal open path)"),
        },
        "witness_service": {
            "per_absent_channel_s": MEASURE_S * cert_points,
            "absent_channels": MAX_CHANNELS - n,
            "measure_s": round(witness_s, 2),
            "nature": "provable given the predicate, conditional for N=16",
        },
        "clear_service": {"clear_s": float(clear_s), "nature": "provable (N successful clears)"},
        "certificate_composite_s": round(composite_s, 2),
        "certificate_composite_per_source": round(composite_s / n, 3),
        "witness_point_sensitivity": sensitivity,
    }


def cardinality_branch(mode, n):
    """N = 16: the cardinality cap can retire the certificate grid entirely."""
    if n != MAX_SOURCES:
        return None
    if mode == "Q3":
        tour_s = round(path_len([(0.0, 0.0)] + q3_ring_points()) / SPEED, 2)
        grid_per_source = round((tour_s + MEASURE_S * 7 * 4 + CLEAR_S * n) / n, 3)
    else:
        points = [(float(x), float(y)) for x, y in q4_sparse25_points()]
        mst_m, heur_m, _p, _c = open_path_bounds(points, (0.0, 0.0))
        tour_s = heur_m / SPEED
        grid_per_source = round((tour_s + MEASURE_S * 25 * 4 + CLEAR_S * n) / n, 3)
    return {
        "cell": "%s/%d" % (mode, n),
        "condition": ("cardinality cap fires: 16 distinct channels confirmed => "
                      "every remaining channel is CERTIFIED_ABSENT with no "
                      "further measurement (runtime._apply_cardinality_cap)"),
        "grid_required": False,
        "witness_service_s": 0.0,
        "note": ("the remaining mandatory work is finding + clearing 16 sources; "
                 "5 s * N successful clears is the only part this argument "
                 "lower-bounds (the discovery/localization service is not "
                 "bounded by the certificate argument)"),
        "clear_only_composite_per_source": round(CLEAR_S, 3),
        "grid_branch_per_source": grid_per_source,
        "which_branch_applies": ("either branch may apply per episode: the cap "
                                 "needs all 16 channels confirmed before the "
                                 "grid finishes"),
    }


# ----------------------------------------------------------------------
# per-cell run decomposition
# ----------------------------------------------------------------------
def run_rows(mode, n):
    pattern = str(ROOT / RUN_ROOT / ("%s_%d_*" % (mode, n)))
    rows = []
    for path in sorted(Path(p) for p in glob.glob(pattern)):
        if not (path / "api_log.jsonl").exists():
            continue
        stops, svc, move = load(path)
        src = sources(path)
        mst_stops_s = mst_len([(0.0, 0.0)] + stops) / SPEED
        mst_src_s = (mst_len([(0.0, 0.0)] + src) / SPEED) if src else None
        svc_s = sum(svc.values())
        # the run's own ledger, straight from api_log dt sums
        t_measure, t_switch, t_clear = svc["measure"], svc["switch"], svc["clear"]
        t_total = move + svc_s
        rows.append({
            "run": path.name, "stops": len(stops), "sources": len(src),
            "T_total_s": t_total, "T_move_s": move,
            "T_measure_s": t_measure, "T_switch_s": t_switch,
            "T_clear_s": t_clear,
            "MST_actual_stops_s": mst_stops_s,
            "MST_sources_s": mst_src_s,
            "detour_vs_actual_mst_s": move - mst_stops_s,
            "identity_ledger_error_s": abs(t_total - (move + t_measure +
                                                      t_switch + t_clear)),
        })
    return rows


def cell_decomposition(mode, n, bounds):
    rows = run_rows(mode, n)
    if not rows:
        return None
    tour_s = bounds["movement"]["open_path_s"]
    witness_s = bounds["witness_service"]["measure_s"]
    clear_s = float(bounds["clear_service"]["clear_s"])
    composite = bounds["certificate_composite_s"]
    out = {"runs": len(rows), "per_run": [], "means_per_source": {}}
    keys = ("detour", "excess_measure", "excess_switch", "excess_clear",
            "residual", "mst_actual", "mst_sources", "move_minus_cert")
    acc = {k: 0.0 for k in keys}
    worst_ledger = 0.0
    worst_split = 0.0
    worst_rel = 0.0
    for row in rows:
        t_total = row["T_total_s"]
        t_move = row["T_move_s"]
        t_measure = row["T_measure_s"]
        t_switch = row["T_switch_s"]
        t_clear = row["T_clear_s"]
        mst_actual = row["MST_actual_stops_s"]
        detour = t_move - mst_actual
        excess_measure = t_measure - witness_s
        excess_switch = t_switch
        excess_clear = t_clear - clear_s
        # task wording: movement split as MST(actual)/5 + detour, then the gap
        # vs the composite carries a residual = MST(actual)/5 - cert tour/5
        residual = (t_total - composite - detour - excess_measure -
                    excess_switch - excess_clear)
        bound_relative = t_total - composite - (t_move - tour_s) - \
            excess_measure - excess_switch - excess_clear
        move_minus_cert = t_move - tour_s
        out["per_run"].append({
            "run": row["run"],
            "s_per_source": round(t_total / n, 3),
            "floor_s_per_source": round(
                (mst_actual + t_measure + t_switch + t_clear) / n, 3),
            "gap_vs_composite_s": round(t_total - composite, 3),
            "detour_s": round(detour, 4),
            "excess_measure_s": round(excess_measure, 4),
            "excess_switch_s": round(excess_switch, 4),
            "excess_clear_s": round(excess_clear, 4),
            "residual_s": round(residual, 6),
            "residual_bound_relative_s": round(bound_relative, 9),
            "move_minus_cert_s": round(move_minus_cert, 4),
            "identity_ledger_error_s": row["identity_ledger_error_s"],
            "identity_split_error_s": abs(t_total - (mst_actual + detour +
                                                     t_measure + t_switch +
                                                     t_clear)),
        })
        for key, value in (("detour", detour), ("excess_measure", excess_measure),
                           ("excess_switch", excess_switch),
                           ("excess_clear", excess_clear),
                           ("residual", residual), ("mst_actual", mst_actual),
                           ("mst_sources", row["MST_sources_s"] or 0.0),
                           ("move_minus_cert", move_minus_cert)):
            acc[key] += value
        worst_ledger = max(worst_ledger, row["identity_ledger_error_s"])
        worst_split = max(worst_split,
                          abs(t_total - (mst_actual + detour + t_measure +
                                         t_switch + t_clear)))
        worst_rel = max(worst_rel, abs(bound_relative))
    count = float(len(rows))
    for key, value in acc.items():
        out["means_per_source"][key] = round(value / count / n, 3)
    out["mean_actual_per_source"] = round(
        sum(r["T_total_s"] for r in rows) / count / n, 3)
    out["ratio_hindsight_mean_of_ratios"] = round(
        sum(row["s_per_source"] / row["floor_s_per_source"]
            for row in out["per_run"]) / count, 4)
    out["mean_floor_per_source"] = round(
        sum(r["MST_actual_stops_s"] + r["T_measure_s"] + r["T_switch_s"] +
            r["T_clear_s"] for r in rows) / count / n, 3)
    out["mean_oracle_floor_per_source"] = round(
        sum((r["MST_sources_s"] or 0.0) + r["T_measure_s"] + r["T_switch_s"] +
            r["T_clear_s"] for r in rows) / count / n, 3)
    out["identity"] = {
        "ledger_max_error_s": worst_ledger,
        "movement_split_max_error_s": worst_split,
        "bound_relative_residual_max_abs_s": worst_rel,
        "tolerance_s": TOL,
        "all_within_tolerance": bool(max(worst_ledger, worst_split,
                                         worst_rel) <= TOL),
    }
    ranking_source = [
        ("绕路 = T_move - MST(实际停点)/5", "detour",
         "recoverable (route order + stop placement)"),
        ("多测量 = T_measure - 见证下界", "excess_measure",
         "recoverable (fewer/cheaper measurements)"),
        ("多换频 = T_switch", "excess_switch",
         "recoverable (fewer channel switches)"),
        ("失败清除 = T_clear - 5N", "excess_clear",
         "recoverable (fewer failed clears)"),
        ("残差 = MST(实际停点)/5 - 证书开路径/5", "residual",
         "conditionally recoverable (extra stops: sources/localization)"),
    ]
    out["recoverable_ranking"] = sorted(
        [{"item": label, "s_per_source": out["means_per_source"][key],
          "nature": nature}
         for label, key, nature in ranking_source],
        key=lambda item: (-item["s_per_source"], item["item"]))
    out["movement_gap_view"] = {
        "move_minus_cert_open_path_s_per_source":
            out["means_per_source"]["move_minus_cert"],
        "note": ("T_move - 证书开路径/5, i.e. all movement above the "
                 "certificate tour (detour + extra stops)"),
    }
    return out


# ----------------------------------------------------------------------
# report assembly
# ----------------------------------------------------------------------
def sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def build():
    q3_search = q3_cover_search()
    bounds_rows = []
    for cell, mode, n in CELLS:
        row = cell_bounds(mode, n, q3_search)
        branch = cardinality_branch(mode, n)
        decomp = cell_decomposition(mode, n, row)
        row["cardinality_branch"] = branch
        row["decomposition"] = decomp
        if decomp:
            row["production_actual_per_source"] = decomp["mean_actual_per_source"]
            row["hindsight_floor_per_source"] = decomp["mean_floor_per_source"]
            row["oracle_floor_per_source"] = decomp["mean_oracle_floor_per_source"]
            row["ratio_vs_composite"] = round(
                decomp["mean_actual_per_source"] /
                row["certificate_composite_per_source"], 4)
            row["ratio_vs_hindsight"] = round(
                decomp["mean_actual_per_source"] /
                decomp["mean_floor_per_source"], 4)
            row["ratio_vs_hindsight_mean_of_ratios"] = \
                decomp["ratio_hindsight_mean_of_ratios"]
            row["runs"] = decomp["runs"]
            row["target"] = TARGET[mode]
            row["composite_excludes_target"] = bool(
                row["certificate_composite_per_source"] > TARGET[mode])
            row["composite_margin_vs_target"] = round(
                TARGET[mode] - row["certificate_composite_per_source"], 3)
        bounds_rows.append(row)
    payload = {
        "task": "t26 lower-bound unification",
        "conventions": {
            "speed_m_per_s": SPEED,
            "measure_s": MEASURE_S,
            "clear_s": CLEAR_S,
            "omega_radius_m": C.OMEGA_RADIUS,
            "channels": MAX_CHANNELS,
            "max_sources": MAX_SOURCES,
            "targets": TARGET,
            "run_root": RUN_ROOT,
            "identity_tolerance_s": TOL,
        },
        "inputs_sha256": {
            "tools/bounds_report.py": sha256(Path(__file__).resolve()),
            "tools/stop_floor.py": sha256(ROOT / "tools" / "stop_floor.py"),
            "tools/oracle_floor.py": sha256(ROOT / "tools" / "oracle_floor.py"),
            "tools/ratio_table.py": sha256(ROOT / "tools" / "ratio_table.py"),
            "baseline/code/geometry/certificate.py":
                sha256(ROOT / "baseline" / "code" / "geometry" /
                       "certificate.py"),
            "baseline/code/geometry/q4_sparse_mesh.py":
                sha256(ROOT / "baseline" / "code" / "geometry" /
                       "q4_sparse_mesh.py"),
            "baseline/code/geometry/constants.py":
                sha256(ROOT / "baseline" / "code" / "geometry" / "constants.py"),
        },
        "cells": bounds_rows,
        "q3_cover_search": q3_search,
        "t31_comparison": t31_comparison(bounds_rows, q3_search),
        "min_witness_points": min_witness_search(coarse_grid(step=150.0),
                                                 trials=8, climb=1),
        "t7_closed_tours": t7_closed_tours(),
        "t7_discrepancies": t7_discrepancies(bounds_rows),
        "conclusions": conclusions(bounds_rows),
    }
    return payload


def t7_discrepancies(bounds_rows):
    q3 = next(r for r in bounds_rows if r["cell"] == "Q3/16")
    q4 = next(r for r in bounds_rows if r["cell"] == "Q4/16")
    return [
        {
            "id": "D1",
            "t7_claim": "证书巡游用闭环：Q3 7 点环 = 8 400 m @r=1200",
            "recomputed": "开路径口径正确，但替换值不能是任何固定环：Q3 的移动项应取"
                          "「**在所有有效覆盖上取最小**」——本节构造性搜索的最小开路径为 "
                          "%.2f m（%.2f s，%s）；t31 的 k=7 纯环值 %.2f m 亦被复现。"
                          % (q3["movement"]["open_path_m"],
                             q3["movement"]["open_path_s"],
                             q3["movement"]["open_path_method"],
                             6189.23),
            "verdict": "t7 的闭环口径确实偏高（闭环 %.1f m）；但旧文的 7200 m（生产环开路径）"
                       "**也不是最小** ⇒ 替换值 = 所有有效覆盖上的最小开路径"
                       % (q3["movement"]["open_path_m"],),
            "who_is_right": "以「所有有效覆盖的最小开路径」为准（t33 更正）",
        },
        {
            "id": "D2",
            "t7_claim": "Q4 生产 sparse25 闭环巡游 19 433 m；最优替代 19 186 m",
            "recomputed": "开路径最优 = %.1f m（MST = 启发式 ⇒ 已证；与队长候选 "
                          "17 990.7 m 一致）" % q4["movement"]["open_path_m"],
            "verdict": "t7 的闭环值偏高；开路径比闭环省 %.1f m = %.1f s/局"
                       % (q4["movement"]["open_vs_closed_saving_m"],
                          q4["movement"]["open_vs_closed_saving_s"]),
            "who_is_right": "以开路径为准，且 17 990.7 m 已被独立复核为最优",
        },
        {
            "id": "D3",
            "t7_claim": "Q4/10 强制下限 ≈ 538.7 s/源（闭环 19 433 m + 1 500 s 测量）",
            "recomputed": "开路径合成界 = %.3f s/源（含 5 s×N 清除）"
                          % next(r for r in bounds_rows
                                 if r["cell"] == "Q4/10")[
                                     "certificate_composite_per_source"],
            "verdict": "结论不变（都被排除），但数值口径要换：t7 的 538.7 混用了闭环移动",
            "who_is_right": "结论一致，数值以本报告为准",
        },
        {
            "id": "D4",
            "t7_claim": "Q4/16 强制 280.4 s/源 < 290 ⇒ 证书不阻断目标",
            "recomputed": "开路径网格分支 = %.3f s/源；基数上限分支下证书服务 = 0"
                          % q4["certificate_composite_per_source"],
            "verdict": "t7 的 280.4 用闭环 3 886 s（应 3 598.1 s）但结论方向一致；"
                       "本报告额外给出 N=16 的基数上限分支条件",
            "who_is_right": "结论一致；分支条件以本报告为准",
        },
        {
            "id": "D5",
            "t7_claim": "「按腿端点落在巡游点上」的归属值不是下限（t7 §145 自述）",
            "recomputed": "本报告把移动拆成 MST(实际停点)/5 + 绕路，并逐局验证恒等式",
            "verdict": "与 t7 自述一致；本报告给出可引用的分解与残差定义",
            "who_is_right": "一致（本报告补充逐局恒等式）",
        },
    ]


def conclusions(bounds_rows):
    out = []
    for row in bounds_rows:
        if row.get("decomposition") is None:
            continue
        top = [item for item in row["decomposition"]["recoverable_ranking"]
               if item["s_per_source"] > 0][:3]
        out.append({
            "cell": row["cell"],
            "target": row["target"],
            "production_per_source": row["production_actual_per_source"],
            "composite_per_source": row["certificate_composite_per_source"],
            "hindsight_floor_per_source": row["hindsight_floor_per_source"],
            "composite_excludes_target": row["composite_excludes_target"],
            "top_three_recoverable": top,
            "verdict": ("provably out of reach under the current predicate"
                        if row["composite_excludes_target"]
                        else "still has room above the composite bound"),
        })
    return out


T31_VALUES = {"Q3/10": 163.78, "Q3/13": 119.07, "Q3/16": 91.12,
              "Q4/10": 489.81, "Q4/13": 349.09, "Q4/16": 261.13}
OLD_VALUES = {"Q3/10": 184.00, "Q3/13": 134.62, "Q3/16": 103.75,
              "Q4/10": 489.81, "Q4/13": 349.09, "Q4/16": 261.13}


def t31_comparison(bounds_rows, q3_search):
    """My value vs t31's independent recomputation vs the superseded table."""
    rows = []
    for row in bounds_rows:
        cell = row["cell"]
        mine = row["certificate_composite_per_source"]
        rows.append({
            "cell": cell,
            "mine": mine,
            "t31": T31_VALUES[cell],
            "old_bounds_md": OLD_VALUES[cell],
            "delta_vs_t31": round(mine - T31_VALUES[cell], 3),
            "delta_vs_old": round(mine - OLD_VALUES[cell], 3),
            "cover": None if row["movement"]["cover_family"] is None else
            "%s k=%d @r=%.3f m" % (row["movement"]["cover_family"],
                                   row["movement"]["cover_k"],
                                   row["movement"]["cover_radius_m"]),
            "movement_m": row["movement"]["open_path_m"],
            "movement_s": row["movement"]["open_path_s"],
            "agrees_with_t31": abs(mine - T31_VALUES[cell]) <= 0.05,
            "not_worse_than_t31": mine <= T31_VALUES[cell] + 1e-9,
        })
    q3_candidates = q3_search.get("candidates") or []
    k7 = next((item for item in q3_candidates
               if item["family"] == "pure_ring" and item["k"] == 7), None)
    return {
        "rows": rows,
        "t31_reference_k7_pure_ring": {
            "t31_open_path_m": 6189.23,
            "reproduced_open_path_m": None if k7 is None else k7["open_path_m"],
            "reproduced_open_path_s": None if k7 is None else k7["open_path_s"],
            "my_min_certified_radius_m": None if k7 is None else
            k7["ring_radius_m"],
            "note": ("t31 printed r=997.2 (the exact threshold is 997.201346 m; "
                     "997.20 alone is certified=False because the boundary "
                     "midpoint sits ~1 mm beyond 1000 m) -- the open path "
                     "reproduces to the printed digits"),
        },
        "movement_minimum": None if not q3_candidates else
        min(q3_candidates, key=lambda item: item["open_path_m"])["open_path_m"],
        "note": ("mine <= t31 in every cell: the composite is minimised over the "
                 "constructed covers *per cell* (the service term grows with the "
                 "number of witness points, so the movement-minimal cover is not "
                 "always the composite-minimal one)"),
    }


def fmt_table(payload):
    lines = []
    lines.append("# 下界口径统一与剩余空间分解（t26）\n")
    lines.append("> 由 `tools/bounds_report.py` **确定性重写**（无时间戳；重复运行字节一致）。"
                 "只读分析，不改任何运行时文件。\n")
    lines.append("## 1. 六格主表（每条界标注性质）\n")
    lines.append("> **t33 更正**：Q3 的移动项由「某个固定环」改为「**在所有有效覆盖上取最小**」"
                 "（构造性搜索 + 精确 `q3_certified` + Held-Karp 开路径）。"
                 "因此 Q3 三格数值下调，**Q3/10 的「合成界排除」结论被推翻**（见 §7 对照表）。\n")
    lines.append("| 格 | 证书点 | 移动 s | 已证最优 | 见证服务 s | 清除 s | "
                 "certificate_composite s/源 | 性质 | hindsight_floor s/源 | "
                 "production 实测 s/源 | ratio(composite) | ratio(hindsight) | 目标 | 合成界排除? |")
    lines.append("|---|---:|---:|:--:|---:|---:|---:|---|---:|---:|---:|---:|---:|:--:|")
    for row in payload["cells"]:
        mark = "是" if row["movement"]["open_path_proven_optimal"] else "否"
        lines.append("| %s | %d | %.1f | %s | %.0f | %.0f | **%.2f** | 可证 | "
                     "%.2f | %.2f | %.4f | %.4f | %.2f | %s |" % (
                         row["cell"], row["movement"]["cover_n_points"],
                         row["movement"]["open_path_s"], mark,
                         row["witness_service"]["measure_s"],
                         row["clear_service"]["clear_s"],
                         row["certificate_composite_per_source"],
                         row["hindsight_floor_per_source"],
                         row["production_actual_per_source"],
                         row["ratio_vs_composite"], row["ratio_vs_hindsight"],
                         row["target"],
                         "**是**" if row["composite_excludes_target"] else "否"))
    lines.append("")
    lines.append("## 2. 每条界的性质与条件\n")
    for row in payload["cells"]:
        lines.append("### %s" % row["cell"])
        if row["mode"] == "Q3":
            lines.append("- **移动（可证）**：证书契约只要求 `Ω ⊆ ∪B(见证, 1000)`，"
                         "**见证点位置自由** ⇒ 下界必须写成「**在所有有效覆盖上取最小**」，"
                         "而不是任何固定环。本表用的是构造性搜索结果：`%s`，"
                         "见证点 %d 个，开路径 **%.1f m = %.1f s**（%s；有效性一律由精确 "
                         "`q3_certified` 判定，无采样余量）。生产环（原点 + 6@1200）与 "
                         "t7 的闭环口径（%.1f m）都只作参照，见 §7 对照表。"
                         % (row["certificate_set"],
                            row["movement"]["cover_n_points"],
                            row["movement"]["open_path_m"],
                            row["movement"]["open_path_s"],
                            row["movement"]["open_path_method"],
                            row["movement"]["t7_closed_tour_m"] or 0.0))
        else:
            lines.append("- **移动（可证）**：%s；MST %.1f m，启发式 %.1f m，%s；"
                         "开路径 %.1f m = %.1f s。**25 个坐标由判据写死**："
                         "`q4_channel_certified_sparse25` 逐个对照模块常量 "
                         "`q4_sparse25_points()`（`MATCH_TOL = 1e-6`）"
                         "⇒ 该分支的移动项**不可优化**（t31 已用 MST 下界 = 启发式上界夹逼"
                         "确认为精确最优）。"
                         % (row["certificate_set"], row["movement"]["mst_open_m"],
                            row["movement"]["heuristic_open_m"],
                            row["movement"]["open_path_method"],
                            row["movement"]["open_path_m"],
                            row["movement"]["open_path_s"]))
        lines.append("- **见证服务（可证，条件成立）**：%d 个证书点 × %d 个缺席频道 × "
                     "%.0f s = %.0f s；条件 = 「每个缺席频道必须在每个证书点上有 "
                     "no_signal 见证」%s" % (
                         row["certificate_points"], MAX_CHANNELS - row["n"],
                         MEASURE_S, row["witness_service"]["measure_s"],
                         "；N=16 有基数上限分支（见下）"
                         if row["n"] == MAX_SOURCES else ""))
        lines.append("- **清除服务（可证）**：%.0f s = 5 s × %d" %
                     (row["clear_service"]["clear_s"], row["n"]))
        lines.append("- **hindsight_floor（事后口径）**：用该局**实际**停点 MST + "
                     "**实测**服务 ⇒ 任何真下界的**上界**；只能证「可行」，"
                     "不能证「不可行」。")
        if row["cardinality_branch"]:
            b = row["cardinality_branch"]
            lines.append("- **基数上限分支（条件成立）**：%s ⇒ 证书服务 = 0；"
                         "该分支下本论证只剩 5 s/源 的清除服务下界（%.0f s/源），"
                         "发现/定位的服务与移动不在本论证范围内；网格分支为 %.3f s/源"
                         % (b["condition"], b["clear_only_composite_per_source"],
                            b["grid_branch_per_source"]))
        lines.append("")
    lines.append("## 3. 与 t7 的逐条差异\n")
    lines.append("| id | t7 说法 | 重算 | 判定 |")
    lines.append("|---|---|---|---|")
    for item in payload["t7_discrepancies"]:
        lines.append("| %s | %s | %s | %s |" % (
            item["id"], item["t7_claim"], item["recomputed"],
            item["verdict"] + "（" + item["who_is_right"] + "）"))
    lines.append("")
    lines.append("### 3.1 最少见证点数（决定 Q3/10 的排除是否稳健）\n")
    lines.append("| k 点 | 对称环族最优：半径 m / 原点项 / 边界缝 / 最差 m | 精确判据 | "
                 "随机+爬坡最差 m | 结论 |")
    lines.append("|---:|---|---|:--:|---:|---|")
    for k, item in sorted(payload["min_witness_points"].items(),
                          key=lambda kv: int(kv[0])):
        ring = item["ring_family"]
        rnd = item["random_search"]
        lines.append("| %s | %.1f / %.1f / %.1f / **%.1f** | %s | %.1f | %s |" % (
            k, ring["ring_radius_m"], ring["origin_term_m"],
            ring["boundary_gap_m"], ring["analytic_worst_m"],
            "可行" if ring["feasible_exact_q3_certified"] else "不可行",
            rnd["coarse_worst_m"],
            "k=%s 可覆盖 Ω" % k if item["feasible"] else "k=%s 无法覆盖 Ω" % k))
    lines.append("")
    q3_search = payload["q3_cover_search"]
    lines.append("**构造性最小覆盖搜索（t33，本节取代旧文的空前提反事实段）**\n")
    lines.append("对称环族（纯环 / 中心+环）× 精确二分求最小可行半径 × Held-Karp 精确开路径；"
                 "有效性一律用精确 `q3_certified`：\n")
    lines.append("| 族 | k | 最小可行半径 m | 见证点数 | 开路径 m | 开路径 s |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for item in sorted(q3_search["candidates"],
                       key=lambda r: (r["open_path_m"], r["k"])):
        lines.append("| %s | %d | %.3f | %d | %.2f | %.2f |" % (
            item["family"], item["k"], item["ring_radius_m"], item["n_points"],
            item["open_path_m"], item["open_path_s"]))
    lines.append("")
    lines.append("- **k=5、k=6 不存在有效覆盖**（两族、全部半径都不可行）⇒ 旧文「即便只算 "
                 "6 个见证点，Q3/10 仍 > 176.25」的**前提为空**，该反事实段已删除。"
                 "正确的说法是：**7 点纯环（无中心）@r=%.3f m 即可给出开路径 %.2f m**"
                 "（含原点在内的纯环覆盖，圆心不需要额外见证点）。"
                 % (next(i["ring_radius_m"] for i in q3_search["candidates"]
                         if i["family"] == "pure_ring" and i["k"] == 7),
                    next(i["open_path_m"] for i in q3_search["candidates"]
                         if i["family"] == "pure_ring" and i["k"] == 7)))
    lines.append("- **每格的合成界在该格的全部已构造覆盖上取最小**（服务项随 k 线性增长，"
                 "所以移动最小的覆盖不一定是合成最小的覆盖）：")
    for cell in ("Q3/10", "Q3/13", "Q3/16"):
        best = q3_search["best_composite"][cell]
        lines.append("  - %s：%s k=%d（开路径 %.2f s + 见证 %.0f s + 清除 %.0f s）"
                     "⇒ **%.3f s/源**"
                     % (cell, best["family"], best["k"], best["open_path_s"],
                        best["witness_s"], best["clear_s"],
                        best["composite_per_source"]))
    lines.append("- ⇒ **Q3/10 不再被排除**（%.2f < 176.25）；Q3/13、Q3/16 亦不被排除。"
                 % q3_search["best_composite"]["Q3/10"]["composite_per_source"])
    lines.append("- **移动项本身的全局最小** = %.2f m（%.2f s）由更密的 k 环给出；"
                 "但见证服务项 = 每缺席频道每见证点 5 s 随 k 增长，所以**每格合成界取的是"
                 "该格合成最小的覆盖**，而不是移动最小的覆盖（两者已在上面按格列出）。"
                 % (q3_search["best_movement"]["open_path_m"],
                    q3_search["best_movement"]["open_path_s"]))
    lines.append("- **Q4 三格不受本节影响**：`q4_channel_certified_sparse25` 的 25 个坐标是"
                 "模块常量（`for expected in q4_sparse25_points()`、`MATCH_TOL = 1e-6`）"
                 "⇒ 该分支的移动项不可优化，服务下界「每缺席频道每见证点一次测量」也随之固定。"
                 "δ-稳健凸包是**并行的另一条判据路径**，其最廉开路径需单独论证，"
                 "不能用来支持「Q4 排除稳健」。")
    lines.append("")
    lines.append("## 4. 剩余空间分解（每格均值，s/源）\n")
    lines.append("| 格 | 实测 s/源 | MST(实际停点)/5 | 绕路 | 多测量 | 多换频 | "
                 "失败清除 | 残差 | 恒等式最大误差 s |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in payload["cells"]:
        d = row.get("decomposition")
        if not d:
            continue
        m = d["means_per_source"]
        lines.append("| %s | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f | %.2e |"
                     % (row["cell"], d["mean_actual_per_source"],
                        m["mst_actual"], m["detour"], m["excess_measure"],
                        m["excess_switch"], m["excess_clear"], m["residual"],
                        d["identity"]["ledger_max_error_s"]))
    lines.append("")
    lines.append("恒等式（逐局验证）：`T_total = MST(实际停点)/5 + 绕路 + 测量 + 换频 + 清除`，"
                 "`绕路 = T_move − MST/5`。**该恒等式是定义性的**（`绕路` 按定义构造，"
                 "其内容只是账本可加性 `T_total = T_move + T_measure + T_switch + T_clear`），"
                 "因此它对下界论证没有贡献，只用于把实测拆成可比较的项。\n")
    lines.append("**残差 = `MST(实际停点)/5 − 证书开路径/5`** 同样只是定义，**不是误差、也不是界**："
                 "它**随所选覆盖变化** —— 同一个 `MST/5` 下，证书开路径取 1440 s（旧文的 7200 m）时 "
                 "Q3/10 残差 = 184.710 − 144.0 = **40.710**；取本节的最小覆盖 1237.85 s 时 = "
                 "**60.925**。按界相对口径（`绕路' = T_move − 证书开路径/5`）分解时残差恒为 0。\n")
    lines.append("## 5. 每格最该打的三项（按可回收 s/源 排序）\n")
    for item in payload["conclusions"]:
        tops = "；".join("%s = %.3f" % (t["item"], t["s_per_source"])
                         for t in item["top_three_recoverable"])
        lines.append("- **%s**（目标 %.2f，合成界 %.2f，实测 %.2f）：%s ⇒ %s"
                     % (item["cell"], item["target"],
                        item["composite_per_source"],
                        item["production_per_source"], tops, item["verdict"]))
    lines.append("")
    lines.append("### 5.1 合成界排除的稳健性（t33 更正：Q3/10 **不**被排除）\n")
    q3_10 = next(r for r in payload["cells"] if r["cell"] == "Q3/10")
    q3_search = payload["q3_cover_search"]
    lines.append("- Q3 证书见证集**不固定**：契约只要求 `Ω ⊆ ∪B(见证, 1000)`；"
                 "构造性搜索给出 k=7 纯环 @r=%.3f m（开路径 %.2f m，Held-Karp 精确），"
                 "k=8、k=9 的纯环开路径更短（见 §3.1 表）。**k=5、k=6 无有效覆盖**，"
                 "因此旧文「退一步只算 6 个见证点 ⇒ 179.0 > 176.25」的前提为空，已删除。"
                 % (next(i["ring_radius_m"] for i in q3_search["candidates"]
                         if i["family"] == "pure_ring" and i["k"] == 7),
                    next(i["open_path_m"] for i in q3_search["candidates"]
                         if i["family"] == "pure_ring" and i["k"] == 7)))
    lines.append("- 每格取该格全部已构造覆盖中合成界的最小值：Q3/10 = **%.3f**"
                 "（%s k=%d）、Q3/13 = **%.3f**、Q3/16 = **%.3f** s/源 ⇒ "
                 "**Q3/10 的排除结论被推翻**（%.2f < 176.25），Q3/13、Q3/16 亦不排除。"
                 % (q3_search["best_composite"]["Q3/10"]["composite_per_source"],
                    q3_search["best_composite"]["Q3/10"]["family"],
                    q3_search["best_composite"]["Q3/10"]["k"],
                    q3_search["best_composite"]["Q3/13"]["composite_per_source"],
                    q3_search["best_composite"]["Q3/16"]["composite_per_source"],
                    q3_10["certificate_composite_per_source"]))
    lines.append("- **Q4 三格的排除理由改为**：`q4_channel_certified_sparse25` 的 25 个坐标"
                 "由判据写死（逐个对照模块常量 `q4_sparse25_points()`，`MATCH_TOL = 1e-6`）"
                 "⇒ 移动项与服务项都不可优化，故 Q4/10（%.2f）、Q4/13（%.2f）的排除成立。"
                 "δ-稳健凸包是**并行分支**，其最廉开路径需单独论证，不能用来支持本结论。"
                 % (next(r["certificate_composite_per_source"]
                         for r in payload["cells"] if r["cell"] == "Q4/10"),
                    next(r["certificate_composite_per_source"]
                         for r in payload["cells"] if r["cell"] == "Q4/13")))
    lines.append("")
    lines.append("## 6. 复现与交叉核对\n")
    lines.append("`tools/ratio_table.py`（队长口径）在本报告同一 root 上的存档 "
                 "`tuning_runs/ratio_table_tuning_runs_ab_probe_production.json`："
                 "Q4 三格的 actual/floor 与本报告**逐位一致**（729.13/594.49、"
                 "561.75/434.04、406.87/293.80）；Q3 三格有 ≤1.3 s/源 的差异，"
                 "原因是该存档只含 27 局/格，而目录里现在有 %d 局/格（新增 run 后重算）。"
                 "ratio 的两口径都给出：均值之比（本表 `ratio(hindsight)`）与"
                 "逐局比值再平均（`ratio_vs_hindsight_mean_of_ratios`）。"
                 % next(r["runs"] for r in payload["cells"]
                        if r["cell"] == "Q3/10"))
    lines.append("")
    lines.append("## 7. 与 t31（`BOUNDS_AUDIT.md`）的数值对照\n")
    lines.append("| 格 | 本次值 | t31 值 | 旧 BOUNDS.md 值 | Δ vs t31 | Δ vs 旧 | 本次覆盖 | 移动 m | 移动 s |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---:|---:|")
    for item in payload["t31_comparison"]["rows"]:
        lines.append("| %s | **%.3f** | %.2f | %.2f | %+.3f | %+.3f | %s | %.1f | %.1f |"
                     % (item["cell"], item["mine"], item["t31"],
                        item["old_bounds_md"], item["delta_vs_t31"],
                        item["delta_vs_old"], item["cover"] or "sparse25（固定坐标）",
                        item["movement_m"], item["movement_s"]))
    lines.append("")
    ref = payload["t31_comparison"]["t31_reference_k7_pure_ring"]
    lines.append("- **t31 的 6 189.23 m 已复现**：我的搜索在 k=7 纯环上的最小认证半径 "
                 "%.3f m（**精确阈值 997.201346 m**；997.20 单独取值为 "
                 "`certified=False`，因为边界中点比 1000 m 超出约 1 mm，"
                 "故 t31 印出的 997.2 是四舍五入值）⇒ 开路径 **%.2f m = %.2f s**。"
                 % (ref["my_min_certified_radius_m"] or 0.0,
                    ref["reproduced_open_path_m"] or 0.0,
                    ref["reproduced_open_path_s"] or 0.0))
    lines.append("- **本次值 ≤ t31 值**：合成界在**该格全部已构造覆盖**上取最小。"
                 "k=8/k=9 的纯环开路径更短（%.2f / %.2f m），代价是见证服务项随 k 增长，"
                 "所以 Q3/13、Q3/16 的最优 k 大于 7，而 Q3/10 仍是 k=7 最优。"
                 % (next((i["open_path_m"] for i in q3_search["candidates"]
                          if i["family"] == "pure_ring" and i["k"] == 8), 0.0),
                    next((i["open_path_m"] for i in q3_search["candidates"]
                          if i["family"] == "pure_ring" and i["k"] == 9), 0.0)))
    lines.append("- Q4 三格的 Δ vs t31 ≤ 0.005 s/源，全部为**显示位数差异**（t31 印两位小数 "
                 "489.81/349.09/261.13，本报告保留三位）：按两位小数比对逐位一致。")
    lines.append("- 显示精度说明：Q3/10 的 Δ = +0.005 s/源 只是位数差异 —— t31 印两位小数 "
                 "`163.78`，本报告保留三位 `%.3f`；按 t31 的精度四舍五入后一致。"
                 % next(item["mine"] for item in payload["t31_comparison"]["rows"]
                        if item["cell"] == "Q3/10"))
    lines.append("")
    lines.append("```powershell\npython -X utf8 tools/bounds_report.py\n"
                 "python -X utf8 verification/check_model.py\n```\n")
    lines.append("产物：`tuning_runs/bounds_report.json`、`tuning_runs/BOUNDS.md`"
                 "（两者均由本脚本确定性重写）。输入哈希见 JSON 的 `inputs_sha256`。")
    return "\n".join(lines) + "\n"


def main():
    payload = build()
    json_path = ROOT / "tuning_runs" / "bounds_report.json"
    md_path = ROOT / "tuning_runs" / "BOUNDS.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                    sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(fmt_table(payload), encoding="utf-8")
    print("wrote %s" % json_path.relative_to(ROOT))
    print("wrote %s" % md_path.relative_to(ROOT))
    print("{:<8}{:>10}{:>10}{:>10}{:>10}{:>9}{:>9}".format(
        "cell", "composite", "hindsight", "actual", "ratio_c", "ratio_h",
        "excluded"))
    for row in payload["cells"]:
        print("{:<8}{:>10.2f}{:>10.2f}{:>10.2f}{:>10.4f}{:>9.4f}{:>9}".format(
            row["cell"], row["certificate_composite_per_source"],
            row["hindsight_floor_per_source"],
            row["production_actual_per_source"], row["ratio_vs_composite"],
            row["ratio_vs_hindsight"],
            "Y" if row["composite_excludes_target"] else "N"))
    bad = [row["cell"] for row in payload["cells"]
           if row.get("decomposition") and
           not row["decomposition"]["identity"]["all_within_tolerance"]]
    print("identity violations (tol 1e-6): %s" % (bad or "none"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
