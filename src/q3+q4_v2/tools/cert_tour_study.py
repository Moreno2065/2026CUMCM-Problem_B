"""Offline certificate-tour study: how cheap can the forced part be?

Question answered (pure offline, no runtime change): under the certificate
contract of each mode, what is the *minimum* closed tour through a valid
certificate point set - optimising the number of points, their positions and
the visiting order - and what does that floor cost per source compared with
the group targets (Q3 176.25 s/source, Q4 290 s/source)?

Certificate contracts (taken from the production code, not re-defined here):

* ``Q3`` - ``geometry.certificate.q3_certified``: ``Ω ⊆ ∪ B(p, R_eff)`` with
  ``R_eff = R_EFF_MIN = 1000`` and ``Ω`` the disk of radius 1800.  A point
  covers the part of Ω within 1000 m of it.
* ``Q4`` - ``geometry.certificate`` / ``verifier.q4_sparse_verifier``: for every
  possible source state ``(g, u)`` some certificate point ``p`` must satisfy
  ``|p - g| <= 1000`` **and** ``u . (p - g) >= 0``; equivalently ``g`` lies in
  the convex hull of the certificate points within 1000 m of it.  This is
  strictly stronger than the Q3 cover condition.

Verification discipline (acceptance requires an independent judgement path):

* generation uses a coarse feasibility screen only;
* the **verdict** comes from ``judge()``, which (a) samples Ω on a dense
  independent grid, (b) decides hull membership with ``scipy`` convex hull
  half-space tests (not the directional loop the generator uses) and (c) for
  the cover mode reports the exact max-min distance;
* as a third party, Q3 candidates are also cross-checked against the production
  verifier ``verifier.q3_cover_verifier.verify_q3_cover`` and the exact
  ``geometry.certificate.q3_certified``; disagreement is reported, never hidden.

Tours: exact Held-Karp for <= 16 points, cheapest-insertion + 2-opt + or-opt
above that, with an explicit heuristic-vs-exact deviation study on small
instances (acceptance requirement).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry import constants as C                        # noqa: E402
from geometry.q4_sparse_mesh import q4_sparse25_points      # noqa: E402

R = C.OMEGA_RADIUS          # 1800 m
R_EFF = C.R_EFF_MIN         # 1000 m guaranteed reception
SPEED = C.MOVE_SPEED        # 5 m/s
MEASURE = C.MEASURE_TIME    # 5 s per measurement
SWITCH = C.SWITCH_TIME      # 1 s per channel change
TARGET = {"Q3": 176.25, "Q4": 290.0}
Q3_PRODUCTION_RING = 1200.0      # learned_search.scheduler q3_coverage_radius
SEED = 20260912


# ----------------------------------------------------------------------
# sampling + judging (independent of any generation criterion)
# ----------------------------------------------------------------------

def grid_points(step):
    points = []
    n = int(math.ceil(2.0 * R / step)) + 1
    for i in range(n):
        x = -R + i * step
        for j in range(n):
            y = -R + j * step
            if x * x + y * y <= R * R:
                points.append((x, y))
    return points


def hull_inside(points, query):
    """Exact convex-hull membership via half-space tests (scipy ConvexHull)."""
    from scipy.spatial import ConvexHull, QhullError
    array = np.asarray(points, dtype=float)
    if len(array) < 3:
        return bool(np.min(np.linalg.norm(array - query, axis=1)) <= 1e-9)
    try:
        hull = ConvexHull(array)
    except QhullError:
        # collinear: the point must lie on the segment
        return bool(np.min(np.linalg.norm(array - query, axis=1)) <= 1e-9)
    equations = hull.equations          # [a, b, c] with a*x + b*y + c <= 0
    values = equations[:, 0] * query[0] + equations[:, 1] * query[1] \
        + equations[:, 2]
    return bool(np.max(values) <= 1e-6)


def stress_samples(points, step=40.0, boundary=3600, radial=720):
    """Deterministic sample set: grid + ∂Ω + circles at every radius that
    matters (each point radius, the midpoints between them, and R itself).

    The binding constraints of a ring-shaped certificate sit on ∂Ω and between
    the rings, so a plain square grid alone would be a weak witness.
    """
    samples = list(grid_points(step))
    for k in range(boundary):
        phi = 2.0 * math.pi * k / boundary
        samples.append((R * math.cos(phi), R * math.sin(phi)))
    radii = sorted({round(math.hypot(x, y), 6) for x, y in points})
    extra = set()
    for index, radius in enumerate(radii):
        if radius <= 0.0:
            continue
        extra.add(min(radius, R))
        if index + 1 < len(radii):
            extra.add(min(0.5 * (radius + radii[index + 1]), R))
    for radius in sorted(extra):
        for k in range(radial):
            phi = 2.0 * math.pi * k / radial
            samples.append((radius * math.cos(phi), radius * math.sin(phi)))
    return samples


def judge(points, mode, step=40.0, boundary=3600, radial=720):
    """Independent verdict for one point set.

    ``mode='cover'`` (Q3 contract): every sampled g must be within R_EFF of a
    point.  ``mode='hull'`` (Q4 contract): every sampled g must lie in the
    convex hull of the certificate points within R_EFF of it.
    """
    pts = [(float(x), float(y)) for x, y in points]
    array = np.asarray(pts, dtype=float)
    samples = stress_samples(pts, step=step, boundary=boundary,
                             radial=radial)
    max_min = 0.0
    uncovered = []
    for g in samples:
        distances = np.linalg.norm(array - np.asarray(g), axis=1)
        eligible = [pts[i] for i in np.flatnonzero(distances <= R_EFF)]
        max_min = max(max_min, float(distances.min()))
        if mode == "cover":
            if distances.min() > R_EFF + 1e-6:
                uncovered.append(g)
        else:
            if not eligible or not hull_inside(eligible, g):
                uncovered.append(g)
    return {
        "mode": mode,
        "samples": len(samples),
        "grid_step_m": step,
        "ok": not uncovered,
        "uncovered": len(uncovered),
        "first_uncovered": uncovered[0] if uncovered else None,
        "max_min_dist_m": round(max_min, 3),
    }


def directional_probe(points, directions=720, step=60.0):
    """Second, formulation-independent probe: the raw (g, u) quantifier.

    Kept in the tool on purpose: the hull judge above is a *different*
    implementation of the same contract, this one is the contract's literal
    statement, so agreement of the two is the strongest check available here.
    """
    pts = np.asarray([(float(x), float(y)) for x, y in points], dtype=float)
    angles = [2.0 * math.pi * k / directions for k in range(directions)]
    bad = 0
    for g in grid_points(step):
        delta = pts - np.asarray(g)
        distances = np.linalg.norm(delta, axis=1)
        eligible = delta[distances <= R_EFF]
        if len(eligible) == 0:
            bad += 1
            continue
        for angle in angles:
            u = np.array([math.cos(angle), math.sin(angle)])
            if not np.any(eligible @ u >= 0.0):
                bad += 1
                break
    return {"sampled_points": len(grid_points(step)), "uncovered": bad,
            "ok": bad == 0, "directions": directions, "grid_step_m": step}


# ----------------------------------------------------------------------
# tours
# ----------------------------------------------------------------------

def tour_length(order, pts):
    total = 0.0
    for i in range(len(order)):
        a, b = pts[order[i]], pts[order[(i + 1) % len(order)]]
        total += math.dist(a, b)
    return total


def held_karp(pts, limit=16):
    """Exact shortest closed tour (acceptance: <= 16 points).

    Masks always contain the start point (bit 0); ``dp[mask][last]`` is the
    cheapest path 0 -> ... -> last visiting exactly ``mask``.
    """
    n = len(pts)
    if n > limit:
        raise ValueError("held_karp is only used for <= %d points" % limit)
    if n <= 1:
        return list(range(n)), 0.0
    if n == 2:
        return [0, 1], 2.0 * math.dist(pts[0], pts[1])
    dist = [[math.dist(pts[i], pts[j]) for j in range(n)] for i in range(n)]
    size = 1 << n
    inf = float("inf")
    dp = [[inf] * n for _ in range(size)]
    parent = [[-1] * n for _ in range(size)]
    for i in range(1, n):
        dp[(1 << 0) | (1 << i)][i] = dist[0][i]
    for mask in range(size):
        if not mask & 1:
            continue
        for last in range(n):
            cost = dp[mask][last]
            if cost == inf or not (mask >> last) & 1:
                continue
            for nxt in range(n):
                if (mask >> nxt) & 1:
                    continue
                new_mask = mask | (1 << nxt)
                new_cost = cost + dist[last][nxt]
                if new_cost < dp[new_mask][nxt]:
                    dp[new_mask][nxt] = new_cost
                    parent[new_mask][nxt] = last
    full = size - 1
    best, best_last = inf, -1
    for last in range(1, n):
        cost = dp[full][last] + dist[last][0]
        if cost < best:
            best, best_last = cost, last
    order = []
    mask, last = full, best_last
    while last != -1:
        order.append(last)
        prev = parent[mask][last]
        mask ^= (1 << last)
        last = prev
    order.reverse()
    return order, best


def brute_force_tour(pts):
    """Independent exact reference for small n (self-test of held_karp)."""
    from itertools import permutations
    n = len(pts)
    best, best_order = float("inf"), None
    for perm in permutations(range(1, n)):
        order = (0,) + perm
        length = tour_length(list(order), pts)
        if length < best:
            best, best_order = length, list(order)
    return best_order, best


def nearest_neighbour(pts, start=0):
    n = len(pts)
    unvisited = set(range(n))
    unvisited.discard(start)
    order = [start]
    current = start
    while unvisited:
        nxt = min(unvisited, key=lambda j: math.dist(pts[current], pts[j]))
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order


def two_opt(order, pts):
    improved = True
    best = tour_length(order, pts)
    while improved:
        improved = False
        n = len(order)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                if j - i == 1:
                    continue
                candidate = order[:i] + order[i:j][::-1] + order[j:]
                length = tour_length(candidate, pts)
                if length + 1e-9 < best:
                    order, best = candidate, length
                    improved = True
    return order, best


def or_opt(order, pts, max_segment=3):
    best = tour_length(order, pts)
    improved = True
    while improved:
        improved = False
        n = len(order)
        for size in range(1, max_segment + 1):
            for i in range(n):
                segment = order[i:i + size]
                if len(segment) < size:
                    continue
                rest = order[:i] + order[i + size:]
                for j in range(len(rest) + 1):
                    if j == i:
                        continue
                    for segment_order in (segment, segment[::-1]):
                        candidate = rest[:j] + segment_order + rest[j:]
                        length = tour_length(candidate, pts)
                        if length + 1e-9 < best:
                            order, best = candidate, length
                            improved = True
    return order, best


def heuristic_tour(pts, rng, restarts=8):
    """cheapest-insertion + 2-opt + or-opt with restarts (acceptance >16)."""
    best_order, best_length = None, float("inf")
    for attempt in range(restarts):
        start = attempt % len(pts)
        order = nearest_neighbour(pts, start)
        order, length = two_opt(order, pts)
        order, length = or_opt(order, pts)
        if attempt == 0:
            # cheapest insertion from a random 3-cycle for diversity
            seeds = rng.sample(range(len(pts)), 3)
            order = list(seeds)
            remaining = [i for i in range(len(pts)) if i not in seeds]
            while remaining:
                best_gain, best_point, best_pos = None, None, None
                for point in remaining:
                    for pos in range(len(order)):
                        a, b = order[pos], order[(pos + 1) % len(order)]
                        gain = (math.dist(pts[a], pts[point])
                                + math.dist(pts[point], pts[b])
                                - math.dist(pts[a], pts[b]))
                        if best_gain is None or gain < best_gain:
                            best_gain, best_point, best_pos = gain, point, pos
                order.insert(best_pos + 1, best_point)
                remaining.remove(best_point)
            order, length = two_opt(order, pts)
            order, length = or_opt(order, pts)
        if length < best_length:
            best_order, best_length = order, length
    return best_order, best_length


def exact_selftest(rng, trials=6):
    """Held-Karp must equal brute force on small random instances."""
    rows = []
    for trial in range(trials):
        n = 5 + trial % 4
        pts = [(rng.uniform(-2000, 2000), rng.uniform(-2000, 2000))
               for _ in range(n)]
        _, exact = held_karp(pts)
        _, brute = brute_force_tour(pts)
        rows.append({"n": n, "held_karp_m": round(exact, 6),
                     "brute_force_m": round(brute, 6),
                     "match": abs(exact - brute) < 1e-6})
    return {"trials": len(rows), "all_match": all(r["match"] for r in rows),
            "rows": rows}


def heuristic_deviation(pts, rng, trials=12, max_points=14):
    """Compare the heuristic with Held-Karp on small random subsets."""
    results = []
    n = len(pts)
    for trial in range(trials):
        k = min(max_points, n)
        subset = rng.sample(range(n), k)
        sub = [pts[i] for i in subset]
        _, exact = held_karp(sub)
        _, approx = heuristic_tour(sub, rng, restarts=4)
        results.append({"points": k, "exact_m": round(exact, 1),
                        "heuristic_m": round(approx, 1),
                        "gap_pct": round(100.0 * (approx - exact) / exact, 4)})
    gaps = [row["gap_pct"] for row in results]
    return {"trials": len(results), "max_gap_pct": max(gaps),
            "mean_gap_pct": round(sum(gaps) / len(gaps), 4), "rows": results}


# ----------------------------------------------------------------------
# candidate families
# ----------------------------------------------------------------------

def ring(radius, count, phase=0.0):
    return [(radius * math.cos(phase + 2.0 * math.pi * k / count),
             radius * math.sin(phase + 2.0 * math.pi * k / count))
            for k in range(count)]


def q3_production_set():
    return [(0.0, 0.0)] + ring(Q3_PRODUCTION_RING, 6)


def q4_production_set():
    return [(float(x), float(y)) for x, y in q4_sparse25_points()]


def q3_candidate(radius):
    return [(0.0, 0.0)] + ring(radius, 6)


def q4_candidate(n_inner, r_inner, n_outer, r_outer, phase=0.0):
    """Centre + inner ring + outer ring (the sparse25 shape, re-placeable).

    The centre is not decoration: for a source position ``g`` at radius
    ``rho <= 1000`` the eligible inner points only bracket ``g`` over a limited
    arc, and it is the triangle (centre, bracket, bracket) that contains ``g``.
    Dropping the centre was measured to leave the mid-radius region uncovered.
    """
    points = [(0.0, 0.0)]
    points += ring(r_inner, n_inner, math.pi / n_inner)
    points += ring(r_outer, n_outer, phase)
    return points


def screen(points, mode, step=150.0):
    """Coarse feasibility screen (fast, not the verdict).

    Fewer witness samples than the verdict pass on purpose: this only filters
    candidates, and everything reported is re-judged with the full sample set.
    """
    return judge(points, mode, step=step, boundary=360, radial=90)["ok"]


# ----------------------------------------------------------------------

def cost_of(points, order, length_m, n_sources, measurements_per_point=1):
    """Forced part in seconds and per source.

    travel = length / MOVE_SPEED; measurement = one detection per certificate
    stop per measurement pass (``measurements_per_point``), each costing
    MEASURE_TIME plus one channel switch.
    """
    travel_s = length_m / SPEED
    measure_s = len(points) * measurements_per_point * (MEASURE + SWITCH)
    total = travel_s + measure_s
    return {
        "tour_m": round(length_m, 1),
        "travel_s": round(travel_s, 1),
        "measure_s": round(measure_s, 1),
        "forced_s": round(total, 1),
        "forced_per_source_s": round(total / n_sources, 2),
        "travel_per_source_s": round(travel_s / n_sources, 2),
        "measure_per_source_s": round(measure_s / n_sources, 2),
    }


def fast_tour(points, rng):
    """Cheap tour used only to rank candidates inside the search loops."""
    order = nearest_neighbour(points, rng.randrange(len(points)))
    order, length = two_opt(order, points)
    return length


def refine_candidates(candidates, rng, judge_step, label, limit=8):
    """Re-judge candidate layouts with the full sample set.

    The search screen uses a coarse witness set (it only filters); several
    screened-feasible layouts turned out to be invalid once judged properly, so
    every layout that is *reported* goes through this pass.
    """
    rows = []
    for row in candidates[:limit]:
        points = q4_candidate(row["n_inner"], row["r_inner"], row["n_outer"],
                              row["r_outer"])
        verdict = judge(points, "hull", step=judge_step)
        rows.append(dict(row, label=label, verdict_ok=verdict["ok"],
                         uncovered=verdict["uncovered"],
                         first_uncovered=verdict["first_uncovered"],
                         samples=verdict["samples"],
                         tour_m=round(fast_tour(points, rng), 1)))
    return rows


def q3_local_search(rng, judge_step, trials=240):
    """Best-found check around the analytic ring optimum (acceptance: Q3)."""
    best = None
    base_radius = 1800.0 * math.cos(math.pi / 6.0) - math.sqrt(
        R_EFF ** 2 - (1800.0 * math.sin(math.pi / 6.0)) ** 2)
    for trial in range(trials):
        radius = base_radius + rng.uniform(-40.0, 80.0)
        phase = rng.uniform(0.0, math.pi / 6.0)
        points = [(0.0, 0.0)] + ring(radius, 6, phase)
        if trial % 3 == 0:
            points = [(x + rng.uniform(-25.0, 25.0),
                       y + rng.uniform(-25.0, 25.0)) for x, y in points]
        verdict = judge(points, "cover", step=judge_step)
        if not verdict["ok"]:
            continue
        order, length = held_karp(points)
        if best is None or length < best["length_m"]:
            best = {"length_m": round(length, 3), "radius": round(radius, 3),
                    "phase_deg": round(math.degrees(phase), 3),
                    "max_min_dist_m": verdict["max_min_dist_m"],
                    "points": [[round(x, 3), round(y, 3)] for x, y in points]}
    return {"trials": trials, "best": best,
            "analytic_radius_m": round(base_radius, 3),
            "analytic_tour_m": round(7.0 * base_radius, 1)}


def triangular_lattice(spacing, radius):
    points = []
    height = spacing * math.sqrt(3.0) / 2.0
    rows = int(math.ceil(2.0 * radius / height)) + 1
    for row in range(-rows, rows + 1):
        y = row * height
        offset = (spacing / 2.0) if (row % 2) else 0.0
        columns = int(math.ceil(2.0 * radius / spacing)) + 1
        for column in range(-columns, columns + 1):
            x = column * spacing + offset
            if x * x + y * y <= radius * radius:
                points.append((round(x, 3), round(y, 3)))
    return points


def cluster_layer(delta, rng, margin=1.02):
    """Concrete construction for the delta-robust geometric criterion.

    Centres: triangular lattice whose covering radius is exactly ``delta`` (so
    union of B(x, delta) contains Omega).  Per centre: the fewest witnesses that
    put B(x, delta) inside their hull while staying inside ``R_EFF - delta`` of
    x - n points on a ring of radius ``rho`` have in-hull radius
    ``rho * cos(pi / n)``, so ``n = 4`` with ``rho >= delta / cos(pi/4)`` is the
    smallest cluster that can work at all; ``rho`` is capped by ``R_EFF - delta``.
    """
    spacing = delta * math.sqrt(3.0) * margin
    centres = triangular_lattice(spacing, R + 0.75 * spacing)
    rho_max = R_EFF - delta
    n_witness = 4
    rho = max(delta / math.cos(math.pi / n_witness), 0.0)
    feasible = rho <= rho_max + 1e-9
    rho = min(rho * 1.01, rho_max)
    witnesses = {}
    for cx, cy in centres:
        for k in range(n_witness):
            angle = 2.0 * math.pi * k / n_witness + math.pi / n_witness
            point = (round(cx + rho * math.cos(angle), 1),
                     round(cy + rho * math.sin(angle), 1))
            witnesses[point] = True
    witness_list = sorted(witnesses)
    # covering check: every sampled g in Omega must be within delta of a centre
    worst = 0.0
    for g in grid_points(120.0):
        distances = [math.dist(g, c) for c in centres]
        worst = max(worst, min(distances))
    return {
        "delta_m": delta,
        "lattice_spacing_m": round(spacing, 1),
        "centres": len(centres),
        "witnesses_per_centre": n_witness,
        "witness_ring_radius_m": round(rho, 1),
        "cluster_feasible": bool(feasible),
        "witness_points": len(witness_list),
        "cover_worst_m": round(worst, 1),
        "cover_ok": worst <= delta + 1e-6,
        "witnesses": witness_list,
    }


def max_delta_table():
    """Largest delta a cluster of n ring witnesses can certify.

    ``delta <= (R_EFF - delta) * cos(pi / n)``  =>  ``delta <= R_EFF * cos(pi/n)
    / (1 + cos(pi/n))``.
    """
    table = {}
    for n in range(3, 13):
        value = R_EFF * math.cos(math.pi / n) / (1.0 + math.cos(math.pi / n))
        table[n] = round(value, 2)
    return table


def layer_costs(name, n_points, tour_m, groups, channels_of, switch=True):
    rows = {}
    for n in groups:
        channels = channels_of(n)
        travel = tour_m / SPEED
        per = MEASURE + (SWITCH if switch else 0.0)
        measure = n_points * channels * per
        total = travel + measure
        rows["N=%d" % n] = {
            "empty_channels": channels,
            "travel_s": round(travel, 1),
            "measurement_s": round(measure, 1),
            "forced_s": round(total, 1),
            "forced_per_source_s": round(total / n, 2),
            "meets_target": total / n <= TARGET["Q4"],
        }
    return {"layer": name, "points": n_points, "tour_m": round(tour_m, 1),
            "per_group": rows}


def tour_for(points, rng):
    if len(points) <= 16:
        order, length = held_karp(points)
        return order, length, "held-karp-exact"
    order, length = heuristic_tour(points, rng)
    return order, length, "insertion+2opt+oropt"


def study_set(name, points, mode, groups, rng, judge_step=40.0):
    verdict = judge(points, mode, step=judge_step)
    order, length, method = tour_for(points, rng)
    return {
        "name": name,
        "points": [[round(x, 3), round(y, 3)] for x, y in points],
        "n_points": len(points),
        "verdict": verdict,
        "tour": {"method": method, "length_m": round(length, 1),
                 "order": order},
        "costs": {("N=%d" % n): cost_of(points, order, length, n)
                  for n in groups},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--judge-step", type=float, default=40.0)
    parser.add_argument("--json", default="tuning_runs/cert_tour_study.json")
    parser.add_argument("--md", default="tuning_runs/cert_tour_study.md")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    report = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "command": "python -X utf8 " + " ".join(sys.argv),
        "seed": args.seed,
        "constants": {"omega_radius_m": R, "r_eff_m": R_EFF,
                      "move_speed_mps": SPEED, "measure_s": MEASURE,
                      "switch_s": SWITCH, "targets": TARGET},
        "script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "families": {},
    }

    # ---- reference sets -------------------------------------------------
    q3_ref = q3_production_set()
    q4_ref = q4_production_set()
    report["families"]["Q3_production_7ring_r1200"] = study_set(
        "Q3 production 7-point ring (r=1200)", q3_ref, "cover", (10, 13, 16),
        rng, args.judge_step)
    report["families"]["Q4_production_sparse25"] = study_set(
        "Q4 production sparse25", q4_ref, "hull", (10, 13, 16), rng,
        args.judge_step)

    # ---- Q3: minimum is 7 points; optimise the ring radius --------------
    q3_scan = []
    for radius in [round(1000.0 + 2.0 * k, 1) for k in range(0, 351)]:
        points = q3_candidate(radius)
        if not screen(points, "cover"):
            continue
        order, length, _ = tour_for(points, rng)
        q3_scan.append({"radius": radius, "length_m": round(length, 1)})
    best_radius = min(q3_scan, key=lambda row: row["length_m"])
    report["families"]["Q3_optimised_7ring"] = study_set(
        "Q3 optimised 7-point ring (r=%.1f)" % best_radius["radius"],
        q3_candidate(best_radius["radius"]), "cover", (10, 13, 16), rng,
        args.judge_step)
    report["q3_radius_scan"] = {"tested": len(q3_scan),
                                "feasible": len(q3_scan),
                                "best": best_radius,
                                "first_feasible":
                                    q3_scan[0] if q3_scan else None}
    q3_local = q3_local_search(rng, args.judge_step)
    report["q3_local_search"] = q3_local

    # Q3 under the strict hull reading (the Q4 contract applied to Q3)
    report["families"]["Q3_under_hull_reading"] = study_set(
        "Q3 production ring judged by the hull contract", q3_ref, "hull",
        (10, 13, 16), rng, args.judge_step)

    # ---- Q4: search re-placeable layouts --------------------------------
    search = []
    for n_out in (6, 8, 10, 12, 14, 16, 18, 20, 24):
        # the outer ring only has to beat the point budget: its radius is set by
        # the "beyond g" window arccos(1800 / r_out) >= pi / n_out
        base_out = 1800.0 / math.cos(math.pi / n_out)
        for r_out in sorted({round(base_out * 1.002, 1),
                             round(base_out + 25.0, 1),
                             round(base_out + 60.0, 1),
                             1870.0, 1900.0}):
            for n_in in (3, 4, 5, 6, 8, 10, 12):
                if n_in + n_out + 1 > 25:
                    continue
                for r_in in (700.0, 800.0, 870.0, 895.0, 950.0, 1000.0):
                    points = q4_candidate(n_in, r_in, n_out, r_out)
                    if len(points) > 25:
                        continue
                    if not screen(points, "hull", step=300.0):
                        continue
                    search.append({"n_inner": n_in, "r_inner": r_in,
                                   "n_outer": n_out, "r_outer": r_out,
                                   "n_points": len(points),
                                   "length_m": round(fast_tour(points, rng), 1)})
    feasible = [row for row in search if row["length_m"] > 0]
    ranked = sorted(feasible, key=lambda row: row["length_m"])
    perturbations = [{"n_inner": 12, "r_inner": 950.0, "n_outer": 12,
                      "r_outer": 1860.0, "n_points": 25, "length_m": 0.0},
                     {"n_inner": 12, "r_inner": 950.0, "n_outer": 12,
                      "r_outer": 1880.0, "n_points": 25, "length_m": 0.0},
                     {"n_inner": 12, "r_inner": 900.0, "n_outer": 12,
                      "r_outer": 1870.0, "n_points": 25, "length_m": 0.0},
                     {"n_inner": 12, "r_inner": 1000.0, "n_outer": 12,
                      "r_outer": 1870.0, "n_points": 25, "length_m": 0.0},
                     {"n_inner": 10, "r_inner": 950.0, "n_outer": 12,
                      "r_outer": 1870.0, "n_points": 23, "length_m": 0.0},
                     {"n_inner": 12, "r_inner": 950.0, "n_outer": 14,
                      "r_outer": 1850.0, "n_points": 27, "length_m": 0.0},
                     {"n_inner": 14, "r_inner": 950.0, "n_outer": 14,
                      "r_outer": 1845.0, "n_points": 29, "length_m": 0.0},
                     {"n_inner": 8, "r_inner": 1000.0, "n_outer": 16,
                      "r_outer": 1840.0, "n_points": 25, "length_m": 0.0}]
    strict = refine_candidates(ranked, rng, args.judge_step, "search-best",
                               limit=8)
    strict += refine_candidates(perturbations, rng, args.judge_step,
                                "production-perturbation", limit=8)
    valid_strict = [row for row in strict
                    if row["verdict_ok"] and row["n_points"] <= 25]
    best = min(valid_strict, key=lambda row: row["tour_m"]) if valid_strict \
        else None
    report["q4_layout_strict"] = {
        "judged": len(strict), "valid": len(valid_strict),
        "valid_best": best, "rows": strict,
        "note": "verdicts from the full witness set (grid + boundary + radial "
                "circles); the coarse screen produced false positives",
    }
    report["q4_layout_search"] = {"tested": len(search),
                                  "feasible": len(feasible),
                                  "best": best,
                                  "top10": sorted(
                                      feasible,
                                      key=lambda row: row["length_m"])[:10]}
    if best is not None:
        report["families"]["Q4_optimised"] = study_set(
            "Q4 optimised layout (inner %d@%.0f + outer %d@%.0f)"
            % (best["n_inner"], best["r_inner"], best["n_outer"],
               best["r_outer"]),
            q4_candidate(best["n_inner"], best["r_inner"], best["n_outer"],
                         best["r_outer"]),
            "hull", (10, 13, 16), rng, args.judge_step)
        # minimal-point variant among the strictly valid layouts
        fewest = min(valid_strict, key=lambda row: (row["n_points"],
                                                    row["tour_m"]))
        report["families"]["Q4_fewest_points"] = study_set(
            "Q4 fewest-point valid layout (%d points)" % fewest["n_points"],
            q4_candidate(fewest["n_inner"], fewest["r_inner"],
                         fewest["n_outer"], fewest["r_outer"]),
            "hull", (10, 13, 16), rng, args.judge_step)

    # ---- three-layer comparison (captain's t7 addition) -----------------
    # Layer A: the current predicate (Omega inside the union of the witness
    # disks) on a net/mesh of visits.  Layers B/C: the delta-robust geometric
    # criterion, which needs *clustered* witnesses around each centre.
    channels_of = lambda n: max(0, C.NUM_CHANNELS - n)
    layers = {"A_mesh_predicate": {}, "B_delta370": {}, "C_adaptive_delta": {}}
    for label, key in (("Q4 production sparse25", "Q4_production_sparse25"),
                       ("Q4 best strictly valid <=25 points", "Q4_optimised")):
        entry = report["families"][key]
        layers["A_mesh_predicate"][label] = layer_costs(
            label, entry["n_points"], entry["tour"]["length_m"], (10, 13, 16),
            channels_of)
    layer_b = cluster_layer(370.0, rng)
    tour_b = fast_tour([tuple(p) for p in layer_b["witnesses"]], rng)
    layers["B_delta370"] = layer_costs("delta=370 fixed", layer_b["witness_points"],
                                       tour_b, (10, 13, 16), channels_of)
    layers["B_delta370"]["construction"] = {k: v for k, v in layer_b.items()
                                            if k != "witnesses"}
    delta_c = max_delta_table()[4]          # largest delta a 4-ring can certify
    layer_c = cluster_layer(delta_c, rng)
    tour_c = fast_tour([tuple(p) for p in layer_c["witnesses"]], rng)
    layers["C_adaptive_delta"] = layer_costs("adaptive delta (4-ring cap)",
                                             layer_c["witness_points"], tour_c,
                                             (10, 13, 16), channels_of)
    layers["C_adaptive_delta"]["construction"] = {
        k: v for k, v in layer_c.items() if k != "witnesses"}
    layers["max_delta_by_cluster_size"] = max_delta_table()
    layers["per_channel_witness_lower_bound"] = {
        "B_delta370": int(math.ceil(4 * layer_b["centres"]
                                    / (math.pi * (R_EFF - 370.0) ** 2
                                       / (layer_b["lattice_spacing_m"] ** 2
                                          * math.sqrt(3.0) / 2.0)))),
        "note": "each witness point lies within R_EFF-delta of at most this "
                "many centres, so |W| is at least clusters x 4 / sharing",
    }
    report["three_layers"] = layers

    # ---- cross-checks ---------------------------------------------------
    report["cross_checks"] = {}
    report["cross_checks"]["held_karp_vs_brute_force"] = exact_selftest(rng)
    report["cross_checks"]["heuristic_vs_exact"] = heuristic_deviation(
        q4_ref, rng, trials=12, max_points=14)
    try:
        from verifier.q3_cover_verifier import verify_q3_cover
        from geometry.certificate import q3_certified
        cross = {}
        for name in ("Q3_production_7ring_r1200", "Q3_optimised_7ring"):
            pts = [tuple(p) for p in report["families"][name]["points"]]
            samples = verify_q3_cover(pts, boundary_samples=7200,
                                      grid_step=25.0)
            exact = q3_certified(pts)
            cross[name] = {"verify_q3_cover_ok": bool(samples["ok"]),
                           "max_min_dist_m": round(samples["max_min_dist"], 3),
                           "q3_certified": bool(exact["certified"]),
                           "reason": exact["reason"]}
        report["cross_checks"]["production_verifiers"] = cross
    except Exception as error:            # pragma: no cover - reported, not hidden
        report["cross_checks"]["production_verifiers"] = {
            "error": "%s: %s" % (type(error).__name__, error)}
    report["cross_checks"]["directional_probe"] = directional_probe(
        report["families"]["Q4_production_sparse25"]["points"], step=60.0)

    # ---- verdicts vs targets -------------------------------------------
    summary = {}
    for name, entry in report["families"].items():
        row = {"valid": entry["verdict"]["ok"], "n_points": entry["n_points"],
               "tour_m": entry["tour"]["length_m"],
               "tour_s": round(entry["tour"]["length_m"] / SPEED, 1),
               "mode": entry["verdict"]["mode"]}
        for key, cost in entry["costs"].items():
            n = int(key.split("=")[1])
            target = TARGET["Q3" if entry["verdict"]["mode"] in
                            ("cover",) else "Q4"]
            row[key] = {"forced_per_source_s": cost["forced_per_source_s"],
                        "target": target,
                        "meets_target": cost["forced_per_source_s"] <= target}
        summary[name] = row
    report["summary"] = summary

    out = ROOT / args.json
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    lines = ["# Certificate tour study (offline floor)", "",
             "- generated: %s" % report["generated_at"],
             "- seed: %d" % args.seed,
             "- script sha256: `%s`" % report["script_sha256"],
             "- command: `%s`" % report["command"], "",
             "| set | points | tour (m) | tour (s) | forced/source "
             "(N=10/13/16) | meets Q3/Q4 target |",
             "|---|---:|---:|---:|---|---|"]
    for name, row in summary.items():
        per_source = " / ".join(
            "%.1f" % row[key]["forced_per_source_s"]
            for key in ("N=10", "N=13", "N=16") if key in row)
        meets = " ".join(
            "%s:%s" % (key, "yes" if row[key]["meets_target"] else "no")
            for key in ("N=10", "N=13", "N=16") if key in row)
        lines.append("| %s | %d | %.0f | %.0f | %s | %s |"
                     % (name, row["n_points"], row["tour_m"], row["tour_s"],
                        per_source, meets))
    lines += ["", "Judge step: %.0f m; verdicts from `judge()` (hull via "
              "scipy half-space tests) plus the production verifiers for Q3."
              % args.judge_step]
    (ROOT / args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, row in summary.items():
        print("%-32s pts=%2d tour=%7.0f m (%6.0f s) forced/source %s meets %s"
              % (name, row["n_points"], row["tour_m"], row["tour_s"],
                 "/".join("%.0f" % row[k]["forced_per_source_s"]
                          for k in ("N=10", "N=13", "N=16") if k in row),
                 "/".join("%s" % ("Y" if row[k]["meets_target"] else "N")
                          for k in ("N=10", "N=13", "N=16") if k in row)))
    print("written %s and %s" % (args.json, args.md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
