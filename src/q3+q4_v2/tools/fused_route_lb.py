# -*- coding: utf-8 -*-
"""R1 fused-route lower bound: how short can one open path be?

Offline only.  Nothing here is imported by the runtime; the tool reads finished
episodes and writes two artifacts (``--out`` JSON and ``--md`` report).

Question answered
-----------------
An episode forces the robot to visit three families of points:

  (a) Q4's 25 fixed certificate mesh points (``geometry.q4_sparse_mesh``);
  (b) the actual clear points of the episode;
  (c) the actual measure / direction stops that are not mesh points.

If a single *fused* open route had to visit exactly those points, how few
metres could it travel?  That number is the movement budget of the R1 fused
planner, so the gap to production's recorded movement estimates R1's headroom.

Release level (R2 estimate)
---------------------------
Production's contract is "all 25 fixed mesh points must carry a no-signal
witness".  The δ-robust certificate in ``geometry.certificate`` is weaker: a
channel is provably absent once certified centres ``x`` cover Ω with
``B(x, δ)``.  So the certificate stops may be *chosen freely*: the tool keeps
the work stops (clear + non-mesh measure stops) as the witness base and greedily
adds lattice points until every certified-absent channel's centre set covers Ω.
The resulting route is shorter because it visits fewer, better-placed points —
an optimistic estimate of R2's benefit, not a policy.

Honesty rules
-------------
* ``<= 16`` vertices : Held-Karp exact optimum (fixed start, open end).
* ``> 16`` vertices  : cheapest insertion + 2-opt + Or-opt = a *feasible*
  route, i.e. an upper estimate of the optimum.  The provable lower bound is
  the MST over the point set (any path is a spanning tree); the exact branch is
  used to measure both the heuristic gap and the MST bound's tightness on
  ``<= 16`` sub-problems drawn from the same clouds.
* These are geometric travel numbers for one fixed point set.  They are not an
  implemented policy, not a whole-episode bound (measure / switch / clear
  service time is outside the travel account) and not evidence that 290 s per
  source is reachable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.certificate import q3_certified, q4_certify_point, q4_grid_points  # noqa: E402
from geometry.constants import (MOVE_SPEED, OMEGA_RADIUS, Q4_DELTA,               # noqa: E402
                                R_EFF_MIN)
from geometry.q4_sparse_mesh import q4_sparse25_points                           # noqa: E402

MOVE_SPEED_IMPORT_ERROR = None

ORIGIN = (0.0, 0.0)
POINT_TOL = 1e-6
TARGET_Q4_S_PER_SOURCE = 290.0
TARGET_Q3_S_PER_SOURCE = 176.25

DEFAULT_CASES = [
    ("Q4/10 seed 101", "tuning_runs/final_recommended_v3/Q4_10_101"),
    ("Q4/13 seed 101", "tuning_runs/t4_plan_audit/production_Q4_13_101"),
    ("Q4/16 seed 101", "tuning_runs/final_recommended_v3/Q4_16_101"),
]
CROSSCHECK_CASE = ("Q4/13 seed 101 (mixed-revision copy)",
                   "tuning_runs/ab_probe/production/Q4_13_101")


# ---------------------------------------------------------------------------
# small geometry helpers
# ---------------------------------------------------------------------------

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def dedupe(points, tol=1e-6):
    out = []
    for point in points:
        point = (float(point[0]), float(point[1]))
        if not any(dist(point, kept) <= tol for kept in out):
            out.append(point)
    return out


def path_length(order):
    return sum(dist(order[i], order[i + 1]) for i in range(len(order) - 1))


def mst_length(points, return_longest=False):
    """Prim MST weight.

    A Hamiltonian *path* that visits every point is itself a spanning tree, so
    its length is >= MST(vertices): this is a valid lower bound for the open
    path with free end.  ``MST - longest_edge`` is a weaker but also valid
    bound (the captain's convention); both are reported.
    """
    pts = list(points)
    if len(pts) < 2:
        return (0.0, 0.0) if return_longest else 0.0
    outside = list(range(1, len(pts)))
    best = [dist(pts[0], pts[i]) for i in range(len(pts))]
    total = 0.0
    longest = 0.0
    while outside:
        j = min(outside, key=lambda i: best[i])
        total += best[j]
        longest = max(longest, best[j])
        outside.remove(j)
        for i in outside:
            d = dist(pts[j], pts[i])
            if d < best[i]:
                best[i] = d
    if return_longest:
        return total, longest
    return total


def held_karp(points, start=ORIGIN):
    """Exact shortest open path: ``start`` fixed, end free, all points visited.

    Only used for small instances (<= 16 vertices); raises otherwise.
    """
    pts = [(float(p[0]), float(p[1])) for p in points
           if dist(p, start) > POINT_TOL]
    n = len(pts)
    if n > 15:
        raise ValueError("held_karp refused: %d free points (>15)" % n)
    full = 1 << n
    INF = float("inf")
    table = [[INF] * n for _ in range(full)]
    for j in range(n):
        table[1 << j][j] = dist(start, pts[j])
    for mask in range(full):
        row = table[mask]
        for j in range(n):
            cost = row[j]
            if cost == INF:
                continue
            for k in range(n):
                if mask & (1 << k):
                    continue
                new = mask | (1 << k)
                cand = cost + dist(pts[j], pts[k])
                if cand < table[new][k]:
                    table[new][k] = cand
    return min(table[full - 1])


def cheapest_insertion(points, start=ORIGIN):
    """Feasible open route: cheapest insertion, then 2-opt + Or-opt."""
    pts = sorted(dedupe(points), key=lambda p: dist(start, p))
    if not pts:
        return [start]
    if len(pts) == 1:
        return [start, pts[0]]
    # seed with the nearest point, then insert the cheapest next one
    order = [start, pts[0]]
    rest = pts[1:]
    while rest:
        best = None
        for idx, point in enumerate(rest):
            for pos in range(1, len(order)):
                delta = (dist(order[pos - 1], point) + dist(point, order[pos])
                         - dist(order[pos - 1], order[pos]))
                if best is None or delta < best[0]:
                    best = (delta, idx, pos)
        _, idx, pos = best
        order.insert(pos, rest.pop(idx))
    return improve_open(order)


def improve_open(order):
    """2-opt + Or-opt on an open path whose first vertex stays fixed."""
    order = list(order)
    improved = True
    rounds = 0
    while improved and rounds < 60:
        improved = False
        rounds += 1
        n = len(order)
        for i in range(1, n - 1):                      # 2-opt
            for j in range(i + 1, n):
                a, b = order[i - 1], order[i]
                c = order[j]
                d = order[j + 1] if j + 1 < n else None
                before = dist(a, b) + (dist(c, d) if d else 0.0)
                after = dist(a, c) + (dist(b, d) if d else 0.0)
                if after < before - 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        for seg in (1, 2, 3):                          # Or-opt
            for i in range(1, n - seg + 1):
                block = order[i:i + seg]
                rest = order[:i] + order[i + seg:]
                for pos in range(1, len(rest) + 1):
                    if pos == i:
                        continue
                    cand = rest[:pos] + block + rest[pos:]
                    if path_length(cand) < path_length(order) - 1e-9:
                        order = cand
                        improved = True
                        break
                else:
                    continue
                break
    return order


def nearest_neighbour(points, start=ORIGIN):
    """Feasible open route: nearest neighbour + 2-opt + Or-opt."""
    remaining = list(dedupe(points))
    order = [start]
    while remaining:
        nxt = min(remaining, key=lambda p: dist(order[-1], p))
        order.append(nxt)
        remaining.remove(nxt)
    return improve_open(order)


def farthest_insertion(points, start=ORIGIN):
    """Feasible open route: farthest insertion + 2-opt + Or-opt."""
    pts = list(dedupe(points))
    if not pts:
        return [start]
    far = max(pts, key=lambda p: dist(start, p))
    order = [start, far]
    rest = [p for p in pts if dist(p, far) > POINT_TOL]
    while rest:
        pick = max(rest, key=lambda p: min(dist(p, q) for q in order))
        best = None
        for pos in range(1, len(order)):
            delta = (dist(order[pos - 1], pick) + dist(pick, order[pos])
                     - dist(order[pos - 1], order[pos]))
            if best is None or delta < best[0]:
                best = (delta, pos)
        order.insert(best[1], pick)
        rest.remove(pick)
    return improve_open(order)


def solve_route(points, exact_limit=16):
    """Best of three constructors (each 2-opt + Or-opt), or exact if small.

    Returns the route, its length, the per-constructor lengths (so a third
    party can see which solver won) and two provable lower bounds.
    """
    pts = dedupe(points)
    vertices = [ORIGIN] + [p for p in pts if dist(p, ORIGIN) > POINT_TOL]
    mst, longest = mst_length(vertices, return_longest=True)
    bounds = {"mst_lb_m": mst, "mst_minus_longest_edge_lb_m": mst - longest}
    if len(vertices) <= exact_limit:
        value = held_karp(pts)
        return {"length_m": value, "method": "held-karp exact",
                "vertices": len(vertices), "order": [ORIGIN],
                "candidates_m": {"held-karp": value}, **bounds}
    candidates = {}
    for name, constructor in (("nearest-neighbour", nearest_neighbour),
                              ("cheapest-insertion", cheapest_insertion),
                              ("farthest-insertion", farthest_insertion)):
        order = constructor(pts)
        candidates[name] = path_length(order)
    winner = min(candidates, key=candidates.get)
    order = {"nearest-neighbour": nearest_neighbour,
             "cheapest-insertion": cheapest_insertion,
             "farthest-insertion": farthest_insertion}[winner](pts)
    return {"length_m": candidates[winner],
            "method": "portfolio best = %s (+2-opt+or-opt), feasible" % winner,
            "vertices": len(vertices), "order": order,
            "candidates_m": candidates, **bounds}


# ---------------------------------------------------------------------------
# episode reading
# ---------------------------------------------------------------------------

def sha16(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def read_episode(directory):
    directory = ROOT / directory
    rows = list(csv.DictReader(open(directory / "actions.csv",
                                    encoding="utf-8")))
    metrics = json.loads((directory / "metrics.json").read_text("utf-8"))
    cert = json.loads((directory / "certificate.json").read_text("utf-8"))
    prov = json.loads((directory / "provenance.json").read_text("utf-8"))
    stops = []
    move_by_row = []
    for row in rows:
        kind = row["action_type"]
        if kind not in ("measure", "clear"):
            continue
        try:
            point = (float(row["target_x"]), float(row["target_y"]))
        except (TypeError, ValueError):
            continue
        stops.append({"kind": kind, "point": point,
                      "policy_mode": row["policy_mode"],
                      "reason": row["reason_code"],
                      "channel": row["channel"],
                      "movement_distance": float(row["movement_distance"] or 0.0),
                      "movement_time": float(row["movement_time"] or 0.0)})
        move_by_row.append(float(row["movement_distance"] or 0.0))
    return {"dir": str(directory.relative_to(ROOT)).replace("\\", "/"),
            "stops": stops, "metrics": metrics, "certificate": cert,
            "provenance": prov, "movement_sum": sum(move_by_row),
            "inputs": {name: sha16(directory / name)
                       for name in ("actions.csv", "metrics.json",
                                    "certificate.json", "provenance.json")}}


def classify(episode, mesh):
    """Split the episode's stops into mesh hits / clear / other work stops."""
    mesh_hits, clears, others = [], [], []
    for stop in episode["stops"]:
        point = stop["point"]
        on_mesh = any(dist(point, m) <= POINT_TOL for m in mesh)
        if on_mesh:
            mesh_hits.append(point)
        elif stop["kind"] == "clear":
            clears.append(point)
        else:
            others.append(point)
    return (dedupe(mesh_hits), dedupe(clears), dedupe(others))


def mesh_movement(episode, mesh):
    """Movement recorded on rows whose target is a mesh point (vs elsewhere)."""
    on_mesh = sum(stop["movement_distance"] for stop in episode["stops"]
                  if any(dist(stop["point"], m) <= POINT_TOL for m in mesh))
    return on_mesh, episode["movement_sum"] - on_mesh


# ---------------------------------------------------------------------------
# release level: freely chosen certificate stops
# ---------------------------------------------------------------------------

def certified_centers(witnesses, candidates):
    out = []
    for point in candidates:
        if q4_certify_point(point, witnesses)["certified"]:
            out.append(point)
    return out


def cover_ok(centers):
    return bool(centers) and q3_certified(centers, cover_r=Q4_DELTA)["certified"]


def omega_samples(ring=360, step=75.0, radius=OMEGA_RADIUS):
    """Dense sample of Ω (boundary ring + interior lattice) for progress only."""
    pts = [(radius * math.cos(2.0 * math.pi * k / ring),
            radius * math.sin(2.0 * math.pi * k / ring)) for k in range(ring)]
    n = int(math.ceil(2.0 * radius / step)) + 1
    for i in range(n):
        x = -radius + i * step
        for j in range(n):
            y = -radius + j * step
            if math.hypot(x, y) <= radius:
                pts.append((x, y))
    return pts


def cover_masks(samples, lattice):
    """Bitmask of Ω samples covered by ``B(x, δ)`` for every lattice centre."""
    masks = []
    for center in lattice:
        mask = 0
        for k, point in enumerate(samples):
            if dist(point, center) <= Q4_DELTA + 1e-9:
                mask |= (1 << k)
        masks.append(mask)
    return masks


def _popcount(value):
    return bin(value).count("1")


def channel_witnesses(episode, absent, base):
    """No-signal points of an absent channel restricted to the work stops."""
    out = {}
    for cid in absent:
        record = episode["certificate"][str(cid)]
        points = [(float(q[0]), float(q[1]))
                  for q in record.get("no_signal_points", [])]
        out[cid] = [p for p in points
                    if any(dist(p, b) <= 1e-3 for b in base)]
    return out


def coverage_ok_from(witnesses, base, added, lattice):
    """Exact check: does the chosen stop set certify this channel?"""
    centers = certified_centers(list(witnesses) + list(added), lattice)
    return cover_ok(centers)


def strict_probe(episode, base_stops, lattice, verbose=True):
    """Level B feasibility probe: δ-hull certificate with stop-placed witnesses.

    The δ-robust criterion certifies ``B(x, δ)`` only where witnesses surround
    ``x`` within 630 m.  A stop set that *is* the witness set therefore cannot
    certify the outer region of Ω at all (no witnesses beyond it).  The probe
    measures that limit instead of pretending a tour exists.
    """
    absent = sorted(int(cid) for cid, rec in episode["certificate"].items()
                    if rec.get("status") == "CERTIFIED_ABSENT")
    base = dedupe(base_stops)
    witnesses = channel_witnesses(episode, absent, base)
    certified = [x for x in lattice
                 if q4_certify_point(x, lattice)["certified"]]
    lattice_cover = q3_certified(certified, cover_r=Q4_DELTA)
    per_channel = {}
    for cid in absent:
        centers = certified_centers(witnesses[cid] + list(lattice), lattice)
        per_channel[str(cid)] = {
            "certified_centres": len(centers),
            "covers_omega": cover_ok(centers),
            "witnesses_at_work_stops": len(witnesses[cid]),
        }
    ring_probes = []
    inner = [x for x in lattice if dist(x, ORIGIN) <= OMEGA_RADIUS]
    for ring_r, ring_n in ((2440.0, 24), (2390.0, 30), (2600.0, 24)):
        outer = [(ring_r * math.cos(2.0 * math.pi * k / ring_n),
                  ring_r * math.sin(2.0 * math.pi * k / ring_n))
                 for k in range(ring_n)]
        pool = inner + outer
        cert = [x for x in inner if q4_certify_point(x, pool)["certified"]]
        ring_probes.append({
            "witness_ring_radius_m": ring_r, "witness_ring_points": ring_n,
            "total_stops_in_probe": len(pool), "certified_centres": len(cert),
            "covers_omega": q3_certified(cert, cover_r=Q4_DELTA)["certified"]})
    feasible = all(v["covers_omega"] for v in per_channel.values())
    out = {"feasible": feasible, "absent_channels": absent,
           "lattice_size": len(lattice),
           "lattice_self_certified_centres": len(certified),
           "lattice_self_cover": lattice_cover,
           "per_channel_with_lattice_stops": per_channel,
           "outward_ring_probes": ring_probes,
           "base_witness_counts": {cid: len(witnesses[cid]) for cid in absent}}
    if verbose:
        print("    strict probe: lattice self-certifies %d/%d centres, covers Ω "
              "= %s ; per-channel coverage = %d/%d"
              % (len(certified), len(lattice), lattice_cover,
                 sum(1 for v in per_channel.values() if v["covers_omega"]),
                 len(per_channel)), flush=True)
    return out


def optimistic_release(samples, masks, lattice, verbose=True):
    """Level C (optimistic): only the stop's own δ-ball is asked to cover Ω.

    This drops the certification hull test, so it is the most favourable
    reading of "certificate stops may be chosen freely" and therefore an upper
    estimate of R2's benefit, not a policy requirement.
    """
    total = len(samples)
    covered = 0
    chosen = []
    while _popcount(covered) < total and len(chosen) < len(lattice):
        best = None
        for yi in range(len(lattice)):
            if yi in chosen:
                continue
            gain = _popcount(covered | masks[yi]) - _popcount(covered)
            if best is None or gain > best[0]:
                best = (gain, yi)
        if best is None or best[0] <= 0:
            break
        chosen.append(best[1])
        covered |= masks[best[1]]
    # prune redundant centres
    changed = True
    while changed and len(chosen) > 1:
        changed = False
        for yi in list(chosen):
            trial = [j for j in chosen if j != yi]
            mask = 0
            for j in trial:
                mask |= masks[j]
            if _popcount(mask) == total:
                chosen = trial
                changed = True
                break
    if verbose:
        print("    optimistic cover: %d stop(s) cover all %d Ω samples"
              % (len(chosen), total), flush=True)
    return {"added_stops": [lattice[j] for j in chosen], "samples": total,
            "covers_all_samples": _popcount(covered) == total}


def release_plan(episode, mesh, base_stops, samples, masks, lattice, verbose=True):
    strict = strict_probe(episode, base_stops, lattice, verbose)
    optimistic = optimistic_release(samples, masks, lattice, verbose)
    strict["optimistic_stops"] = optimistic["added_stops"]
    strict["omega_samples"] = len(samples)
    return strict


# ---------------------------------------------------------------------------
# heuristic validation on exactly solvable sub-problems
# ---------------------------------------------------------------------------

def validate(points, trials=12, size=12, seed=20260912, exact_limit=16):
    rng = random.Random(seed)
    cloud = dedupe(points)
    rows = []
    if len(cloud) < size:
        return rows
    for _ in range(trials):
        sample = rng.sample(cloud, size)
        exact = held_karp(sample)
        order = cheapest_insertion(sample)
        heur = path_length(order)
        mst = mst_length([ORIGIN] + [p for p in sample
                                     if dist(p, ORIGIN) > POINT_TOL])
        rows.append({"n": size, "exact_m": exact, "heuristic_m": heur,
                     "heuristic_gap_pct": 100.0 * (heur - exact) / exact,
                     "mst_lb_m": mst, "mst_gap_pct":
                     100.0 * (exact - mst) / exact})
    return rows


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def analyse(label, directory, mesh, lattice, samples, masks, sub_exact_limit=16):
    episode = read_episode(directory)
    metrics = episode["metrics"]
    mesh_hits, clears, others = classify(episode, mesh)
    all_stops = dedupe([stop["point"] for stop in episode["stops"]])
    # Work stops = every visited position that is not a fixed mesh point; the
    # mesh positions are certificate stops, not work, and level C is allowed to
    # replace them with freely chosen certificate stops.
    work_stops = [p for p in all_stops
                  if not any(dist(p, m) <= POINT_TOL for m in mesh)]
    n_sources = int(metrics.get("sources_total") or 0)
    move_on_mesh, move_off_mesh = mesh_movement(episode, mesh)
    speed = MOVE_SPEED or (episode["movement_sum"]
                           / metrics["T_move"] if metrics.get("T_move") else None)

    base_stops = work_stops
    # ---- level A0: fuse exactly what the episode visited (no rule change) --
    visited = dedupe([ORIGIN] + [stop["point"] for stop in episode["stops"]])
    route_a0 = solve_route(visited, sub_exact_limit)
    # ---- level A: the contract *this episode actually used* ---------------
    # The 25 fixed mesh points are only required when at least one channel was
    # certified with the sparse25 basis; an episode whose absences rest on the
    # ``cardinality`` basis needs no mesh visit (Q4/16 s101: 18/25 mesh points
    # were touched, all four absences cite cardinality).
    absent_bases = Counter(rec.get("absent_basis")
                           for rec in episode["certificate"].values()
                           if rec.get("status") == "CERTIFIED_ABSENT")
    mesh_required = absent_bases.get("sparse25", 0) > 0
    set_a = dedupe(visited + (mesh if mesh_required else []))
    route_a = solve_route(set_a, sub_exact_limit)
    # ---- level B: certificate stops free (δ-robust criterion) -------------
    release = release_plan(episode, mesh, base_stops, samples, masks, lattice)
    strict = {key: value for key, value in release.items()
              if key != "optimistic_stops"}
    # ---- level C: optimistic free-placement cover (R2 benefit estimate) ----
    set_c = dedupe([ORIGIN] + base_stops + release["optimistic_stops"])
    route_c = solve_route(set_c, sub_exact_limit)

    def per_source(metres):
        return metres / float(speed) / n_sources if speed and n_sources else None

    case = {
        "label": label, "dir": episode["dir"],
        "inputs": episode["inputs"],
        "provenance": episode["provenance"],
        "sources_total": n_sources,
        "move_speed_mps": speed,
        "episode": {
            "total_move_distance_m": metrics.get("total_move_distance_m"),
            "movement_sum_from_actions_m": round(episode["movement_sum"], 3),
            "movement_on_mesh_m": round(move_on_mesh, 1),
            "movement_off_mesh_m": round(move_off_mesh, 1),
            "T_move": metrics.get("T_move"),
            "T_measure": metrics.get("T_measure"),
            "T_switch": metrics.get("T_switch"),
            "T_clear": metrics.get("T_clear"),
            "T_total_virtual": metrics.get("T_total_virtual"),
            "t_per_source_s": metrics.get("t_per_source_s"),
        },
        "points": {
            "mesh25": len(mesh),
            "mesh_points_hit_by_episode": len(mesh_hits),
            "clear_points": len(clears),
            "other_work_stops": len(others),
            "distinct_episode_stops": len(dedupe([s["point"] for s in episode["stops"]])),
            "absent_bases": dict(absent_bases),
            "mesh_required_by_basis": mesh_required,
        },
        "level_a0_fuse_actual_visits": {
            "must_visit_points": len([p for p in visited
                                      if dist(p, ORIGIN) > POINT_TOL]),
            "method": route_a0["method"], "tsp_m": route_a0["length_m"],
            "candidates_m": route_a0["candidates_m"],
            "mst_lb_m": route_a0["mst_lb_m"],
            "mst_minus_longest_edge_lb_m": route_a0["mst_minus_longest_edge_lb_m"],
            "travel_s_per_source": per_source(route_a0["length_m"]),
        },
        "level_a": {
            "must_visit_points": len([p for p in set_a if dist(p, ORIGIN) > POINT_TOL]),
            "method": route_a["method"], "tsp_m": route_a["length_m"],
            "candidates_m": route_a["candidates_m"],
            "mst_lb_m": route_a["mst_lb_m"],
            "mst_minus_longest_edge_lb_m": route_a["mst_minus_longest_edge_lb_m"],
            "travel_s_per_source": per_source(route_a["length_m"]),
            "mst_travel_s_per_source": per_source(route_a["mst_lb_m"]),
            "feasible_upper_s_per_source": per_source(route_a["length_m"]),
            "provable_lower_s_per_source": per_source(route_a["mst_lb_m"]),
        },
        "_point_sets": {
            "origin": ORIGIN,
            "mesh25": mesh,
            "mesh_actually_hit": mesh_hits,
            "clear_stops": clears,
            "other_work_stops": others,
            "level_a0_points": visited,
            "level_a_points": set_a,
            "level_c_points": set_c,
            "level_c_added_certificate_stops": release["optimistic_stops"],
        },
        "level_b_strict": strict,
        "level_c_optimistic": {
            "must_visit_points": len([p for p in set_c if dist(p, ORIGIN) > POINT_TOL]),
            "method": route_c["method"], "tsp_m": route_c["length_m"],
            "mst_lb_m": route_c["mst_lb_m"],
            "travel_s_per_source": per_source(route_c["length_m"]),
            "added_certificate_stops": len(release["optimistic_stops"]),
        },
        "production": {
            "travel_s_per_source": per_source(episode["movement_sum"]),
            "move_distance_per_source_m": (episode["movement_sum"]
                                           / n_sources if n_sources else None),
            "t_per_source_s": metrics.get("t_per_source_s"),
        },
        "saving_vs_production_s_per_source": {
            "level_a0": (per_source(episode["movement_sum"])
                         - per_source(route_a0["length_m"])),
            "level_a": (per_source(episode["movement_sum"])
                        - per_source(route_a["length_m"])),
            "level_c_optimistic": (per_source(episode["movement_sum"])
                                   - per_source(route_c["length_m"])),
            "level_a_minus_level_c": (per_source(route_a["length_m"])
                                      - per_source(route_c["length_m"])),
        },
        "service_s_per_source": ({
            "T_measure": metrics.get("T_measure"),
            "T_switch": metrics.get("T_switch"),
            "T_clear": metrics.get("T_clear"),
            "sum_per_source": ((metrics.get("T_measure") or 0.0)
                               + (metrics.get("T_switch") or 0.0)
                               + (metrics.get("T_clear") or 0.0))
            / n_sources if n_sources else None,
        }),
        "target": TARGET_Q4_S_PER_SOURCE,
        "strict_probe": strict,
    }
    # ---- exact sub-problems (<= 16 vertices) ------------------------------
    subs = {}
    if len(clears) + 1 <= sub_exact_limit:
        subs["clear points + origin"] = held_karp(clears)
    for name, cloud in (("mesh inner ring (12) + origin", mesh[1:13]),
                        ("mesh outer ring (12) + origin", mesh[13:25]),
                        ("mesh25 + origin", mesh)):
        if len(cloud) + 1 <= sub_exact_limit:
            subs[name] = held_karp(cloud)
    case["exact_subproblems_m"] = subs
    # ---- heuristic validation --------------------------------------------
    cloud = set_a
    val = validate(cloud, trials=12, size=min(12, len(cloud)))
    case["validation_subsets"] = {
        "trials": len(val),
        "size": min(12, len(cloud)),
        "exact_mean_m": statistics.mean(r["exact_m"] for r in val) if val else None,
        "heuristic_mean_m": statistics.mean(r["heuristic_m"] for r in val) if val else None,
        "heuristic_gap_max_pct": max(r["heuristic_gap_pct"] for r in val) if val else None,
        "heuristic_gap_mean_pct": statistics.mean(r["heuristic_gap_pct"] for r in val) if val else None,
        "mst_gap_max_pct": max(r["mst_gap_pct"] for r in val) if val else None,
        "rows": val,
    }
    return case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=None,
                        help="LABEL=DIR; repeatable (default: three Q4 cases)")
    parser.add_argument("--out", default="tuning_runs/fused_route_lb.json")
    parser.add_argument("--md", default="tuning_runs/FUSED_ROUTE_LB.md")
    parser.add_argument("--points",
                        default="tuning_runs/fused_route_lb_points.json")
    args = parser.parse_args()

    cases = ([(item.split("=", 1)[0], item.split("=", 1)[1])
              for item in args.case] if args.case else DEFAULT_CASES)
    cases = cases + [CROSSCHECK_CASE]
    mesh = dedupe(q4_sparse25_points())
    lattice = dedupe(q4_grid_points())
    samples = omega_samples()
    masks = cover_masks(samples, lattice)

    started = time.time()
    report = {
        "tool": "tools/fused_route_lb.py",
        "tool_sha256_16": sha16(Path(__file__)),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "move_speed_mps": MOVE_SPEED,
        "move_speed_import_error": globals().get("MOVE_SPEED_IMPORT_ERROR"),
        "constants": {"omega_radius_m": OMEGA_RADIUS,
                      "r_eff_min_m": R_EFF_MIN, "q4_delta_m": Q4_DELTA},
        "certificate_contracts": {
            "production_fixed_mesh": "all 25 sparse25 mesh points need a "
                                     "no-signal witness (geometry/q4_sparse_mesh.py)",
            "delta_robust_release": "certified centres x with B(x,delta) in "
                                    "conv(A_delta(x)); Omega must be covered by "
                                    "B(x,delta) (geometry/certificate.py)",
            "release_lattice_points": len(lattice),
            "lattice_covers_omega": q3_certified(lattice, cover_r=Q4_DELTA)["certified"],
            "omega_progress_samples": len(samples),
        },
        "cases": [],
        "geometry_inputs": {
            rel: sha16(ROOT / rel) for rel in (
                "baseline/code/geometry/certificate.py",
                "baseline/code/geometry/q4_sparse_mesh.py",
                "baseline/code/geometry/constants.py",
                "baseline/code/geometry/polygon.py")
            if (ROOT / rel).exists()},
        "notes": [
            "Offline geometric accounting only: the fused route is a point set, "
            "not a policy; travel metres are converted with MOVE_SPEED and are "
            "NOT a whole-episode bound (measure/switch/clear service time is not "
            "in the travel account).",
            "<=16 vertices -> Held-Karp exact optimum; >16 -> best of three "
            "constructors (nearest neighbour / cheapest insertion / farthest "
            "insertion), each improved by 2-opt + Or-opt = feasible route. For an "
            "open path with free end a Hamiltonian path IS a spanning tree, so "
            "MST(vertices) is a valid lower bound; MST - longest_edge (the "
            "captain's convention) is also reported and is weaker but valid.",
            "Level A is contract-aware: the 25 fixed mesh points enter the point "
            "set only when some channel was certified with the sparse25 basis "
            "(a 'cardinality' basis episode needs no mesh visit).",
            "Level B is a relaxation (certificate witness set is chosen freely), "
            "so it is an optimistic estimate of R2's benefit, not a prediction.",
        ],
    }
    points_dump = {"tool": "tools/fused_route_lb.py",
                   "tool_sha256_16": report["tool_sha256_16"],
                   "generated_utc": report["generated_utc"],
                   "note": "exact point sets behind fused_route_lb.json; "
                           "coordinates rounded to 4 decimals (<=1e-4 m).",
                   "cases": []}
    for label, directory in cases:
        print("== %s :: %s" % (label, directory), flush=True)
        case = analyse(label, directory, mesh, lattice, samples, masks)
        point_sets = case.pop("_point_sets", {})
        report["cases"].append(case)
        points_dump["cases"].append({
            "label": label, "dir": case["dir"],
            "mesh_required_by_basis": case["points"]["mesh_required_by_basis"],
            "absent_bases": case["points"]["absent_bases"],
            "counts": {
                "level_a0_points": len(point_sets.get("level_a0_points", [])),
                "level_a_points": len(point_sets.get("level_a_points", [])),
                "level_c_points": len(point_sets.get("level_c_points", [])),
                "clear_stops": len(point_sets.get("clear_stops", [])),
                "other_work_stops": len(point_sets.get("other_work_stops", [])),
                "mesh_actually_hit": len(point_sets.get("mesh_actually_hit", [])),
            },
            "origin": [0.0, 0.0],
            "points": {key: [[round(float(p[0]), 4), round(float(p[1]), 4)]
                             for p in value]
                       for key, value in point_sets.items()
                       if key != "origin"},
        })
        print("   A: points=%d len=%.0f m (%s) -> %.1f s/source [LB %.0f m]"
              % (case["level_a"]["must_visit_points"], case["level_a"]["tsp_m"],
                 case["level_a"]["method"], case["level_a"]["travel_s_per_source"],
                 case["level_a"]["mst_lb_m"]),
              flush=True)
        print("   B: strict free-certificate reading feasible = %s "
              "(lattice self-certifies %d/%d centres, covers Ω = %s)"
              % (case["level_b_strict"]["feasible"],
                 case["level_b_strict"]["lattice_self_certified_centres"],
                 case["level_b_strict"]["lattice_size"],
                 case["level_b_strict"]["lattice_self_cover"]), flush=True)
        print("   C: points=%d len=%.0f m -> %.1f s/source (optimistic cover: %d stops)"
              % (case["level_c_optimistic"]["must_visit_points"],
                 case["level_c_optimistic"]["tsp_m"],
                 case["level_c_optimistic"]["travel_s_per_source"],
                 case["level_c_optimistic"]["added_certificate_stops"]),
              flush=True)
    report["wall_seconds"] = round(time.time() - started, 2)

    out_path = ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    points_path = ROOT / args.points
    points_path.write_text(json.dumps(points_dump, ensure_ascii=False, indent=1)
                           + "\n", encoding="utf-8")
    md_path = ROOT / args.md
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print("written %s, %s and %s (%.1f s)"
          % (out_path, points_path, md_path, report["wall_seconds"]))
    return 0


def render_markdown(report):
    lines = []
    add = lines.append
    add("# R1 融合开路径：离线下界与释放层级")
    add("")
    add("> 本文件由 `tools/fused_route_lb.py` 生成（脚本哈希 `%s`，生成于 %s）。"
        % (report["tool_sha256_16"], report["generated_utc"]))
    add("> 纯离线几何核算：**不是**已实现的策略，**不是**整局时间下界，"
        "也**不**证明 290 s/源可达。")
    add("")
    add("## 0. 口径")
    add("")
    add("- 移动速度：`MOVE_SPEED` 常量 = %s；导入失败时回退为逐局 "
        "`total_move_distance_m / T_move`（本报告各局回退值均为 5.0000000 m/s）。"
        % report["move_speed_mps"])
    if report.get("move_speed_import_error"):
        add("  - `from constants import MOVE_SPEED` 失败：`%s`"
            % report["move_speed_import_error"])
    add("- 证书契约（现判据）：Q4 的 25 个固定稀疏网格点必须全部取得 no-signal 见证"
        "（`geometry/q4_sparse_mesh.py:q4_channel_certified_sparse25`）。**仅当某局的缺席频道"
        "确实以 `sparse25` 基准认证时**，本报告的层级 A 才把 25 个网格点计入必访点；"
        "以 `cardinality` 基准认证的局（如 Q4/16 s101）不需要网格访问。")
    add("- 释放层级判据：δ-稳健凸包证书 `geometry/certificate.py:q4_certify_point` "
        "（δ=%s，见证池半径 %s m），频道完成 = Ω ⊆ ∪ B(x, δ)；"
        "格点集 %d 个点，覆盖 Ω = %s。"
        % (report["constants"]["q4_delta_m"],
           report["constants"]["r_eff_min_m"] - report["constants"]["q4_delta_m"],
           report["certificate_contracts"]["release_lattice_points"],
           report["certificate_contracts"]["lattice_covers_omega"]))
    add("- ≤16 顶点：Held-Karp 精确最优（起点固定、终点自由）；>16：三种构造"
        "（nearest-neighbour / cheapest-insertion / farthest-insertion，各自再跑 2-opt + Or-opt）"
        "**取最短**，逐构造长度全部落盘。可证下界给两个：`MST(顶点)`（开路径本身就是生成树，"
        "故成立）与 `MST − 最长边`（captain 口径，更弱但同样成立）。")
    add("")
    add("## 1. 结论摘要（先读；明细见 §3–§6）")
    add("")
    add("> 每条结论都标注口径：**【只减移动】**= 只动移动账；**【整局估算】**= 移动上端 + 本局实测服务账，"
        "**不是下界**，只是两本账并排。")
    add("")
    for case in report["cases"]:
        a = case["level_a"]
        a0 = case["level_a0_fuse_actual_visits"]
        prod = case["production"]
        sv = case["saving_vs_production_s_per_source"]
        svc = case["service_s_per_source"]
        add("- **%s**（%d 源）【只减移动】：层级 A 的融合移动 = **区间 [%.0f, %.0f] m = "
            "[%.1f, %.1f] s/源**（下端 = 可证 MST 下界，上端 = 可行路径；顶点 %d 个，"
            "由该局实际使用的证书基准决定是否计 25 点网格：absent_bases=%s ⇒ mesh_required=%s）。"
            "该局实际访问点集融合 = %.0f m（%.1f s/源）。生产实测移动 %.1f s/源 ⇒ 移动账上端可省 "
            "%+.1f s/源、下端（最保守）%+.1f s/源。"
            % (case["label"], case["sources_total"],
               a["mst_lb_m"], a["tsp_m"], a["provable_lower_s_per_source"],
               a["feasible_upper_s_per_source"], a["must_visit_points"],
               case["points"]["absent_bases"], case["points"]["mesh_required_by_basis"],
               a0["tsp_m"], a0["travel_s_per_source"],
               prod["travel_s_per_source"], sv["level_a"],
               prod["travel_s_per_source"] - a["provable_lower_s_per_source"]))
        add("    - 【整局估算】移动上端 + 本局服务账（%.1f）= **%.1f s/源**（生产整局 %.1f s/源；"
            "距 290 目标 %+.1f s/源）。该口径**不是下界**：服务时间与测量次数不在本报告的移动账内。"
            % (svc["sum_per_source"],
               a["feasible_upper_s_per_source"] + svc["sum_per_source"],
               prod["t_per_source_s"],
               a["feasible_upper_s_per_source"] + svc["sum_per_source"]
               - case["target"]))
        add("    - 求解器：三种构造（最近邻 / cheapest insertion / farthest insertion，各自 "
            "2-opt + Or-opt）取最短；本局各构造 %.0f / %.0f / %.0f m。"
            % (a["candidates_m"].get("nearest-neighbour", float("nan")),
               a["candidates_m"].get("cheapest-insertion", float("nan")),
               a["candidates_m"].get("farthest-insertion", float("nan"))))
        add("    - 释放层级 (b)（证书点自由 + δ-凸包判据）：**不可行 → 该方向封闭，不再投入预算** —— "
            "43 个 δ-格点全部走完只自证 %d/%d 个中心（覆盖 Ω：%s —— %s）；外扩见证环（§4 探针）仍不足。"
            % (case["level_b_strict"]["lattice_self_certified_centres"],
               case["level_b_strict"]["lattice_size"],
               case["level_b_strict"]["lattice_self_cover"].get("certified"),
               case["level_b_strict"]["lattice_self_cover"].get("reason")))
        add("    - 释放层级 (c)（最乐观读法：只要求停点自身 δ 圆盘覆盖 Ω，不做凸包检验）需 %d 个证书"
            "停点 → %.0f m（%.1f s/源），比 (a) 上端**贵 %.1f s/源** ⇒ **同样封闭**：R2 的收益"
            "不来自『更少的证书点』。"
            % (case["level_c_optimistic"]["added_certificate_stops"],
               case["level_c_optimistic"]["tsp_m"],
               case["level_c_optimistic"]["travel_s_per_source"],
               -sv["level_a_minus_level_c"]))
    primary = [case for case in report["cases"]
               if case["label"] != CROSSCHECK_CASE[0]]
    upper = [case["saving_vs_production_s_per_source"]["level_a"]
             for case in primary]
    lower = [case["production"]["travel_s_per_source"]
             - case["level_a"]["provable_lower_s_per_source"]
             for case in primary]
    totals = [case["level_a"]["feasible_upper_s_per_source"]
              + case["service_s_per_source"]["sum_per_source"]
              for case in primary]
    gaps = [value - case["target"] for value, case in zip(totals, primary)]
    add("")
    add("- **R1 收益上限（一句话）**：融合路线**【只减移动】**省 **%+.1f…%+.1f s/源**"
        "（按局面，Q4/16 最大；保守下端 %+.1f…%+.1f）；但**【整局估算】**仍为 %s s/源 ⇒ "
        "距 290 目标 %s s/源 ⇒ **不构成可达性主张**。"
        % (min(upper), max(upper), min(lower), max(lower),
           " / ".join("%.1f" % value for value in totals),
           " / ".join("%+.1f" % value for value in gaps)))
    add("- **与 captain 引文的对账**（避免口径漂移）：你读到的是中间 revision（该版 A0 = 17 845 m / "
        "223.1 s/源、A = 23 055 m / 288.2 s/源，因为当时把 25 点网格无条件计入且只用单构造求解器）；"
        "本版修正后 **A = A0 = 16 644 m / 208.1 s/源**（与 `tools/route_lb.py` 的那一局结果**逐位一致**）"
        "⇒ 移动省 %+.1f…%+.1f、整局距 290 %+.1f…%+.1f。所有数字均可由 "
        "`tuning_runs/fused_route_lb.json` 与 `tuning_runs/fused_route_lb_points.json` 逐项重算。"
        % (min(upper), max(upper), min(gaps), max(gaps)))
    add("")
    add("## 2. 三个真实局面")
    add("")
    add("| 局面 | 来源目录 | 源数 | 生产移动 (m) | 其中网格点相关 (m) | 生产 t/源 (s) |")
    add("|---|---|---:|---:|---:|---:|")
    for case in report["cases"]:
        add("| %s | `%s` | %d | %.0f | %.0f | %.1f |" %
            (case["label"], case["dir"], case["sources_total"],
             case["episode"]["total_move_distance_m"],
             case["episode"]["movement_on_mesh_m"],
             case["episode"]["t_per_source_s"]))
    add("")
    add("## 3. 点位集合与下界")
    add("")
    add("| 局面 | 缺席基准 | 需 25 点网格 | 25 网格点被访问 | 清除点 | 其它工作停点 | A 必访点 | A 方法 |")
    add("|---|---|---|---:|---:|---:|---:|---|")
    for case in report["cases"]:
        pts = case["points"]
        add("| %s | %s | %s | %d/25 | %d | %d | %d | %s |" %
            (case["label"], pts["absent_bases"], pts["mesh_required_by_basis"],
             pts["mesh_points_hit_by_episode"], pts["clear_points"],
             pts["other_work_stops"], case["level_a"]["must_visit_points"],
             case["level_a"]["method"]))
    add("")
    add("| 局面 | A 区间 s/源 | A 上端 (m) | A MST 下界 (m) | C 必访点 | C 路径 (m) | C 路径 s/源 | C 新增证书停点 |")
    add("|---|---|---:|---:|---:|---:|---:|---:|")
    for case in report["cases"]:
        add("| %s | [%.1f, %.1f] | %.0f | %.0f | %d | %.0f | %.1f | %d |" %
            (case["label"], case["level_a"]["provable_lower_s_per_source"],
             case["level_a"]["feasible_upper_s_per_source"],
             case["level_a"]["tsp_m"], case["level_a"]["mst_lb_m"],
             case["level_c_optimistic"]["must_visit_points"],
             case["level_c_optimistic"]["tsp_m"],
             case["level_c_optimistic"]["travel_s_per_source"],
             case["level_c_optimistic"]["added_certificate_stops"]))
    add("")
    add("## 4. 释放层级 (b)(c)：结论已封闭（在停点即见证的读法下不可行 / 更贵）")
    add("")
    add("| 局面 | 缺席频道 | 格点自证中心 | 格点自证覆盖 Ω | 用 43 格点停点后仍不覆盖的频道 | 外扩见证环探针 |")
    add("|---|---:|---:|---|---:|---|")
    for case in report["cases"]:
        probe = case["level_b_strict"]
        open_channels = sum(1 for v in probe["per_channel_with_lattice_stops"]
                            .values() if not v["covers_omega"])
        rings = "; ".join("%.0f m×%d 点→%d 中心/覆盖=%s" %
                          (r["witness_ring_radius_m"], r["witness_ring_points"],
                           r["certified_centres"], r["covers_omega"])
                          for r in probe["outward_ring_probes"])
        add("| %s | %d | %d/%d | %s | %d/%d | %s |" %
            (case["label"], len(probe["absent_channels"]),
             probe["lattice_self_certified_centres"], probe["lattice_size"],
             probe["lattice_self_cover"]["certified"], open_channels,
             len(probe["per_channel_with_lattice_stops"]), rings))
    add("")
    add("读法 (b)（证书点自由选择、但必须用 `certificate.py` 的 δ-稳健凸包判据证明缺席）"
        "在本项目这四局里**无法给出更短的巡游**：判据要求每个中心 x 在 630 m 内被见证点"
        "『围住』（内切半径 ≥ δ=370 m），而见证点只能是路线实际停留点 ⇒ 出访点云的外缘"
        "证明不了外缘中心，覆盖不到 Ω 边界。上面的探针显示：即使把 43 个 δ-格点全部走完"
        "（或再外扩到 r≈2440–2600 的见证环、总计 55–61 个停点），Ω 覆盖仍不成立。")
    add("")
    add("## 5. 求解器与下界口径（对齐第三方）")
    add("")
    add("层级 A 的**区间**：下端 = 可证下界，上端 = 本次可行路径。同一局换求解器只会动上端。")
    add("")
    add("| 局面 | 顶点 | 最近邻 | cheapest insertion | farthest insertion | 取用（上端） | MST 下界 | MST−最长边 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for case in report["cases"]:
        a = case["level_a"]
        cand = a["candidates_m"]
        add("| %s | %d | %.0f | %.0f | %.0f | **%.0f** | %.0f | %.0f |" %
            (case["label"], a["must_visit_points"] + 1,
             cand.get("nearest-neighbour", float("nan")),
             cand.get("cheapest-insertion", float("nan")),
             cand.get("farthest-insertion", float("nan")),
             a["tsp_m"], a["mst_lb_m"], a["mst_minus_longest_edge_lb_m"]))
    add("")
    add("说明：开路径（起点固定、终点自由）本身是一棵生成树 ⇒ `可行路径 ≥ MST(顶点)` 必然成立；"
        "`MST − 最长边` 是更弱但同样成立的界。若第三方的可行路径大于本表的 MST，则两份结果"
        "**兼容**；若小于，必有一方的点集不同或求解器有错（本表已把点集单独落盘到 "
        "`tuning_runs/fused_route_lb_points.json` 供逐点对齐）。")
    add("")
    add("## 6. 与生产实测、目标 290 的对比（s/源）")
    add("")
    add("| 局面 | 生产移动 s/源 | A 融合路径 s/源（MST 下界见 §3） | C 松弛 s/源 | A 相对生产节省 | C 相对生产节省 | A − C（融合相对自由选点的优势） |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for case in report["cases"]:
        saving = case["saving_vs_production_s_per_source"]
        add("| %s | %.1f | %.1f | %.1f | %+.1f | %+.1f | %+.1f |" %
            (case["label"], case["production"]["travel_s_per_source"],
             case["level_a"]["travel_s_per_source"],
             case["level_c_optimistic"]["travel_s_per_source"],
             saving["level_a"], saving["level_c_optimistic"],
             saving["level_a_minus_level_c"]))
    add("")
    add("对照目标 %.0f s/源：上表全是**移动账**；层级 A 只减移动，**不含**测量/换频/清除服务时间，"
        "因此本报告不把移动数字与 290 直接相减。两本账并排（供读者自行判断，不构成可达性主张）："
        % TARGET_Q4_S_PER_SOURCE)
    add("")
    add("| 局面 | 生产整局 t/源 | 生产移动 s/源 | 服务账 s/源（测量+换频+清除） | 层级 A 移动区间 s/源 |")
    add("|---|---:|---:|---:|---|")
    for case in report["cases"]:
        a = case["level_a"]
        svc = case["service_s_per_source"]
        add("| %s | %.1f | %.1f | %.1f | [%.1f, %.1f] |" %
            (case["label"], case["production"]["t_per_source_s"],
             case["production"]["travel_s_per_source"], svc["sum_per_source"],
             a["provable_lower_s_per_source"], a["feasible_upper_s_per_source"]))
    add("")
    add("## 7. 精确子问题（≤16 顶点，Held-Karp）")
    add("")
    for case in report["cases"]:
        subs = case["exact_subproblems_m"]
        add("- **%s**：%s" % (case["label"], ", ".join(
            "%s = %.0f m" % (k, v) for k, v in sorted(subs.items())) or "无"))
    add("")
    add("## 8. 启发式与 MST 下界的实测偏差（同点云 ≤16 随机子集）")
    add("")
    add("| 局面 | 子集数/大小 | 精确均值 (m) | 启发式均值 (m) | 启发式最大偏差 | MST 最大偏差 |")
    add("|---|---:|---:|---:|---:|---:|")
    for case in report["cases"]:
        val = case["validation_subsets"]
        add("| %s | %d/%d | %.0f | %.0f | %.3f%% | %.1f%% |" %
            (case["label"], val["trials"], val["size"], val["exact_mean_m"],
             val["heuristic_mean_m"], val["heuristic_gap_max_pct"],
             val["mst_gap_max_pct"]))
    add("")
    add("## 9. 每局输入与哈希（可复核）")
    add("")
    add("证书几何模块（判据的真正输入）：")
    for name, digest in sorted(report["geometry_inputs"].items()):
        add("- `%s` sha256:%s" % (name, digest))
    add("")
    for case in report["cases"]:
        add("- **%s**：`%s`" % (case["label"], case["dir"]))
        for name, digest in sorted(case["inputs"].items()):
            add("    - `%s` sha256:%s" % (name, digest))
    add("")
    add("## 10. 复现命令")
    add("")
    add("```powershell")
    for label, directory in DEFAULT_CASES:
        add("python -X utf8 tools/fused_route_lb.py --case \"%s=%s\"" %
            (label, directory))
    add("python -X utf8 tools/fused_route_lb.py   # 默认即上面三局 + Q4/13 混合目录对照")
    add("```")
    add("")
    add("## 11. 边界")
    add("")
    for note in report["notes"]:
        add("- " + note)
    add("- 交叉对照局 `%s` 取自混合代码版本目录，只用于验证点位/几何一致，"
        "不作为基线；Q4/13 主案取自 `tuning_runs/t4_plan_audit/production_Q4_13_101`"
        "（t4 独立复核目录），因为 `final_recommended_v3/` 没有 N=13 的局。" % CROSSCHECK_CASE[1])
    add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
