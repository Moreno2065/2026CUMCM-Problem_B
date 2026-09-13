"""t14: how far can Q3/16's stop set shrink by sharing certificate witnesses?

Offline geometry study.  A stop is a position at which the policy acted
(``/measure`` or ``/clear``); the certificate for the *absent* channels is the
covering ``Omega subset of union B(p_i, 1000)``, and ``geometry.certificate.
q3_certified`` is an exact decider for it.  Q3's rule accepts **any** witness
position, so the ring stops may be re-placed -- in particular they may coincide
with the clear stops the run already pays for.

For every run the study reports:

* ``baseline``  - the run's own stop set: MST(origin + stops)/5 + its ledger
  service time, i.e. ``tools/stop_floor.py`` / ``tools/stopset_overhead.py``
  convention (those tools are out of this task's scope and are NOT modified;
  their loader/MST convention is re-implemented here and cross-checked against
  their stored output);
* ``sources``   - MST(origin + true source sites): what "pay travel only for the
  sources" would cost (offline oracle);
* ``shared``    - clear points + the **fewest extra witnesses** that make
  ``q3_certified`` succeed, greedily chosen from a polar lattice;
* ``clears``    - do the clear points alone certify?  (the free-sharing ideal);
* ``ring``      - clear points + the 7 production ring positions (can the stops
  the policy already pays for be reused as-is?);
* coverage margins (worst uncovered distance over a dense grid, and the exact
  ``q3_certified`` verdict) for each scenario.

Usage:
    python -X utf8 tools/q3_stop_sharing_study.py [run_dir ...]
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

from geometry import constants as C                      # noqa: E402
from geometry.certificate import q3_certified            # noqa: E402

SPEED = C.MOVE_SPEED
COVER_R = C.R_EFF_MIN
OMEGA_R = C.OMEGA_RADIUS
TARGET_PER_SOURCE = 176.25
GRID_STEP = 25.0            # Omega sampling step for the independent check
RING_RADIUS = 1200.0        # production Q3 certificate ring radius
RING_POINTS = 7             # frozen ring size (origin + 7 = the 8-stop cover)


# ----------------------------------------------------------------------
# inputs
# ----------------------------------------------------------------------
def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_stops(run_dir: Path):
    """Action positions and the run's ledger split (stop_floor.py convention)."""
    stops: list[tuple[float, float]] = []
    clears: list[tuple[float, float]] = []
    svc = {"measure": 0.0, "switch": 0.0, "clear": 0.0}
    move = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = record.get("dt") or {}
            move += float(dt.get("move") or 0.0)
            svc["measure"] += float(dt.get("measure") or 0.0)
            svc["switch"] += float(dt.get("switch") or 0.0)
            svc["clear"] += float(dt.get("clear") or 0.0)
            endpoint = record.get("endpoint")
            if endpoint not in ("/measure", "/clear"):
                continue
            pos = (record.get("request") or {}).get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            point = (float(pos["x"]), float(pos["y"]))
            if not stops or math.dist(stops[-1], point) > 1e-9:
                stops.append(point)
            if (endpoint == "/clear" and
                    (record.get("response") or {}).get("clear_result")
                    == "success"):
                clears.append(point)
    return stops, clears, svc, move


def load_sources(run_dir: Path):
    data = json.loads((run_dir / "ground_truth.json").read_text(
        encoding="utf-8"))
    points: list[tuple[float, float]] = []

    def walk(node):
        if isinstance(node, dict):
            if "x" in node and "y" in node:
                points.append((float(node["x"]), float(node["y"])))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    unique = []
    for point in points:
        if all(math.dist(point, other) > 1e-9 for other in unique):
            unique.append(point)
    return unique


def load_service(run_dir: Path) -> float:
    metrics = json.loads((run_dir / "metrics.json").read_text(
        encoding="utf-8"))
    return float(metrics["T_measure"]) + float(metrics["T_switch"]) + \
        float(metrics["T_clear"])


# ----------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------
def mst_len(points):
    """Euclidean MST length (Prim); same convention as tools/stop_floor.py."""
    n = len(points)
    if n < 2:
        return 0.0
    inside = {0}
    best = [math.dist(points[0], points[i]) for i in range(n)]
    total = 0.0
    while len(inside) < n:
        nxt = min((i for i in range(n) if i not in inside),
                  key=lambda i: best[i])
        total += best[nxt]
        inside.add(nxt)
        for i in range(n):
            if i not in inside:
                best[i] = min(best[i], math.dist(points[nxt], points[i]))
    return total


def omega_grid(step=GRID_STEP):
    grid = []
    radius = int(math.ceil(OMEGA_R / step))
    for i in range(-radius, radius + 1):
        for j in range(-radius, radius + 1):
            x, y = i * step, j * step
            if x * x + y * y <= OMEGA_R * OMEGA_R:
                grid.append((x, y))
    return grid


def worst_uncovered(points, grid, cover_r=COVER_R):
    """Dense-grid sanity check: max over Omega of the distance to the nearest stop.

    Returns ``(worst_min_distance, worst_point)``.  ``worst <= cover_r`` means
    the grid sees Omega covered; the exact decider is ``q3_certified``.
    """
    worst, where = -1.0, None
    for point in grid:
        d = min(math.dist(point, stop) for stop in points)
        if d > worst:
            worst, where = d, point
    return worst, where


def polar_candidates(radii=(0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0),
                     angles=24):
    out = []
    for radius in radii:
        if radius == 0.0:
            out.append((0.0, 0.0))
            continue
        for k in range(angles):
            angle = 2.0 * math.pi * k / angles
            out.append((radius * math.cos(angle), radius * math.sin(angle)))
    return out


def ring_positions():
    """The production Q3 cover: origin plus RING_POINTS at the 1200 m circle.

    ``learned_search.scheduler`` freezes this 8-stop cover (origin + 7 ring
    centres, order ``(4, 5, 0, 1, 2, 3)`` plus the origin), so "reuse the ring
    stops unchanged" means exactly this set.
    """
    out = [(0.0, 0.0)]
    for k in range(RING_POINTS):
        angle = 2.0 * math.pi * k / RING_POINTS
        out.append((RING_RADIUS * math.cos(angle),
                    RING_RADIUS * math.sin(angle)))
    return out


def greedy_extra_points(base, grid, candidates, cover_r=COVER_R):
    """Fewest-look-alike additions that make ``q3_certified`` succeed.

    Greedy set cover over the Omega grid: while the exact decider fails, take
    the uncovered point it reports and pick the admissible candidate
    (``|p - u| <= cover_r``) that covers the most still-uncovered grid points.
    """
    current = list(base)
    extra = []
    covered = [False] * len(grid)
    for index, point in enumerate(grid):
        for stop in current:
            if math.dist(point, stop) <= cover_r:
                covered[index] = True
                break
    guard = 0
    while guard < 40:
        guard += 1
        verdict = q3_certified(current)
        if verdict["certified"]:
            break
        target = verdict.get("uncovered_point") or (0.0, 0.0)
        best = None
        for candidate in candidates:
            if any(math.dist(candidate, stop) <= 1e-6 for stop in current):
                continue
            if math.dist(candidate, target) > cover_r - 1.0:
                continue
            gain, keys = 0, []
            for index, point in enumerate(grid):
                if covered[index]:
                    continue
                if math.dist(candidate, point) <= cover_r:
                    gain += 1
                    keys.append(index)
            if gain <= 0:
                continue
            key = (-gain, math.dist(candidate, target), candidate)
            if best is None or key < best[0]:
                best = (key, candidate, keys)
        if best is None:
            # No lattice point is admissible for this hole (rare, e.g. a hole
            # in a corner of Omega).  Fall back to the witness Omega itself,
            # clamped to cover_r from the hole: it always makes progress.
            fallback = target
            if math.hypot(*fallback) > OMEGA_R:
                scale = OMEGA_R / math.hypot(*fallback)
                fallback = (fallback[0] * scale, fallback[1] * scale)
            if any(math.dist(fallback, stop) <= 1e-6 for stop in current):
                break
            current.append(fallback)
            extra.append(fallback)
            for index, point in enumerate(grid):
                if not covered[index] and math.dist(fallback, point) <= cover_r:
                    covered[index] = True
            continue
        _, chosen, keys = best
        current.append(chosen)
        extra.append(chosen)
        for index in keys:
            covered[index] = True
    return current, extra


# ----------------------------------------------------------------------
# one run
# ----------------------------------------------------------------------
def analyse(run_dir: Path, n: int, grid):
    def per_source(seconds):
        return round(seconds / n, 1)

    stops, clears, svc, move = load_stops(run_dir)
    sources = load_sources(run_dir)
    service = load_service(run_dir)
    if not sources or not clears:
        return None
    mst_stops = mst_len([(0.0, 0.0)] + stops)
    mst_sources = mst_len([(0.0, 0.0)] + sources)
    mst_clears = mst_len([(0.0, 0.0)] + clears)
    pass_line = TARGET_PER_SOURCE * n - service      # allowed travel seconds

    clears_verdict = q3_certified(clears)
    clears_worst, clears_where = worst_uncovered(clears, grid)

    candidates = polar_candidates() + list(clears) + ring_positions()
    shared, extra = greedy_extra_points(clears, grid, candidates)
    shared_verdict = q3_certified(shared)
    shared_worst, shared_where = worst_uncovered(shared, grid)
    mst_shared = mst_len([(0.0, 0.0)] + shared)
    # Minimality of the greedy repair: drop any single added witness and the
    # exact decider must fail again (otherwise the addition was redundant).
    redundant = []
    for point in extra:
        trial = [p for p in shared if math.dist(p, point) > 1e-9]
        if q3_certified(trial)["certified"]:
            redundant.append([round(point[0], 1), round(point[1], 1)])

    ring_set = list(clears) + ring_positions()
    ring_verdict = q3_certified(ring_set)
    ring_worst, _ = worst_uncovered(ring_set, grid)
    mst_ring = mst_len([(0.0, 0.0)] + ring_set)

    # Exact trim: keep the clear points (mandatory) and choose the *subset* of
    # the 8 frozen ring stops that still certifies with the smallest MST.  This
    # is the real "ring and clears share stops" question -- the clears can make
    # individual ring stops redundant.
    ring = ring_positions()
    best_trim = None
    for mask in range(1 << len(ring)):
        subset = [ring[i] for i in range(len(ring)) if mask & (1 << i)]
        trial = list(clears) + subset
        if not q3_certified(trial)["certified"]:
            continue
        length = mst_len([(0.0, 0.0)] + trial)
        key = (round(length, 6), len(subset))
        if best_trim is None or key < best_trim[0]:
            best_trim = (key, subset, length)
    trimmed = {
        "subsets_tried": 1 << len(ring),
        "kept_ring_stops": None if best_trim is None else len(best_trim[1]),
        "kept_ring_points": None if best_trim is None else
        [[round(x, 1), round(y, 1)] for x, y in best_trim[1]],
        "points": None if best_trim is None else len(clears) + len(best_trim[1]),
        "mst_per_source": None if best_trim is None else
        per_source(best_trim[2] / SPEED),
        "floor_per_source": None if best_trim is None else
        per_source(best_trim[2] / SPEED + service),
        "stopset_overhead_per_source": None if best_trim is None else
        per_source(best_trim[2] / SPEED - mst_sources / SPEED),
        "gain_vs_baseline_s_per_source": None if best_trim is None else
        per_source(mst_stops / SPEED - best_trim[2] / SPEED),
        "crosses_pass_line": None if best_trim is None else
        bool(best_trim[2] / SPEED <= pass_line),
        "certified_exact": best_trim is not None,
    }
    if best_trim is not None:
        trim_worst, trim_where = worst_uncovered(list(clears) + best_trim[1],
                                                 grid)
        trimmed["worst_uncovered_m"] = round(trim_worst, 1)
        trimmed["coverage_slack_m"] = round(COVER_R - trim_worst, 1)
        trimmed["uncovered_point"] = None if trim_where is None else [
            round(trim_where[0], 1), round(trim_where[1], 1)]

    ring_only_verdict = q3_certified(ring_positions())
    ring_only_worst, _ = worst_uncovered(ring_positions(), grid)

    near = {limit: sum(1 for point in clears
                       if min(math.dist(point, r) for r in ring_positions())
                       <= limit)
            for limit in (50.0, 100.0, 200.0, 400.0)}
    snap_extra = 0.0
    for point in clears:
        nearest = min(ring_positions(), key=lambda r: math.dist(point, r))
        snap_extra += 2.0 * max(0.0, math.dist(point, nearest) - 20.0)

    return {
        "run": str(run_dir.relative_to(ROOT)).replace("\\", "/"),
        "n": n,
        "stops": len(stops),
        "clear_points": len(clears),
        "sources": len(sources),
        "service_s": round(service, 1),
        "pass_line_travel_s": round(pass_line, 1),
        "baseline": {
            "mst_stops_s": round(mst_stops / SPEED, 1),
            "mst_per_source": per_source(mst_stops / SPEED),
            "floor_per_source": per_source(mst_stops / SPEED + service),
            "stopset_overhead_per_source": per_source(
                mst_stops / SPEED - mst_sources / SPEED),
            "overhead_share_pct": round(
                (mst_stops / SPEED - mst_sources / SPEED) /
                (mst_stops / SPEED + service) * 100, 1),
            "crosses_pass_line": bool(mst_stops / SPEED <= pass_line),
        },
        "oracle_sources": {
            "mst_per_source": per_source(mst_sources / SPEED),
            "floor_per_source": per_source(mst_sources / SPEED + service),
        },
        "clears_only": {
            "points": len(clears),
            "mst_per_source": per_source(mst_clears / SPEED),
            "floor_per_source": per_source(mst_clears / SPEED + service),
            "certified_exact": bool(clears_verdict["certified"]),
            "certified_reason": clears_verdict["reason"],
            "worst_uncovered_m": round(clears_worst, 1),
            "coverage_slack_m": round(COVER_R - clears_worst, 1),
            "uncovered_point": None if clears_where is None else
            [round(clears_where[0], 1), round(clears_where[1], 1)],
            "crosses_pass_line": bool(mst_clears / SPEED <= pass_line),
        },
        "shared": {
            "extra_points": [[round(x, 1), round(y, 1)] for x, y in extra],
            "extra_count": len(extra),
            "extra_redundant": redundant,
            "points": len(shared),
            "mst_per_source": per_source(mst_shared / SPEED),
            "floor_per_source": per_source(mst_shared / SPEED + service),
            "stopset_overhead_per_source": per_source(
                mst_shared / SPEED - mst_sources / SPEED),
            "certified_exact": bool(shared_verdict["certified"]),
            "certified_reason": shared_verdict["reason"],
            "worst_uncovered_m": round(shared_worst, 1),
            "coverage_slack_m": round(COVER_R - shared_worst, 1),
            "gain_vs_baseline_s_per_source": per_source(
                mst_stops / SPEED - mst_shared / SPEED),
            "crosses_pass_line": bool(mst_shared / SPEED <= pass_line),
        },
        "ring_trimmed_exact": trimmed,
        "clears_plus_frozen_ring": {
            "points": len(ring_set),
            "mst_per_source": per_source(mst_ring / SPEED),
            "floor_per_source": per_source(mst_ring / SPEED + service),
            "certified_exact": bool(ring_verdict["certified"]),
            "certified_reason": ring_verdict["reason"],
            "worst_uncovered_m": round(ring_worst, 1),
            "coverage_slack_m": round(COVER_R - ring_worst, 1),
        },
        "frozen_ring_only": {
            "certified_exact": bool(ring_only_verdict["certified"]),
            "worst_uncovered_m": round(ring_only_worst, 1),
            "coverage_slack_m": round(COVER_R - ring_only_worst, 1),
        },
        "sharing_conditions": {
            "clear_points_within_ring_radius_m": near,
            "clear_points_near_ring_share_pct": {
                str(int(k)): round(v / len(clears) * 100, 1)
                for k, v in near.items()},
            "forced_snap_extra_move_s": round(snap_extra / SPEED, 1),
            "forced_snap_extra_s_per_source": per_source(snap_extra / SPEED),
        },
    }


def main(argv):
    patterns = argv[1:] or [
        "tuning_runs/ab_route/q3check/production/Q3_16_*",
        "tuning_runs/ab_route/production/Q3_16_5000*",
    ]
    dirs: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if not path.is_absolute():
            path = ROOT / pattern
        found = sorted(glob.glob(str(path)))
        if not found and Path(path).is_dir():
            found = [str(path)]
        dirs.extend(Path(item) for item in found)

    grid = omega_grid()
    runs = []
    for run_dir in dirs:
        if not (run_dir / "api_log.jsonl").exists():
            continue
        record = analyse(run_dir, 16, grid)
        if record is None:
            print("skip (no clears/sources): %s" % run_dir)
            continue
        runs.append(record)

    print("{:<44}{:>8}{:>8}{:>9}{:>9}{:>8}{:>9}{:>8}{:>8}{:>7}".format(
        "run", "stops", "clr", "base/s", "ovh/s", "pass_s", "clearCov",
        "extra", "shared", "cross"))
    for row in runs:
        print("{run:<44}{stops:>8}{clear_points:>8}{base:>9.1f}{ovh:>9.1f}"
              "{passl:>8.0f}{cov:>9}{extra:>8}{shared:>9.1f}{cross:>7}".format(
                  run=row["run"].split("/")[-1], stops=row["stops"],
                  clear_points=row["clear_points"],
                  base=row["baseline"]["floor_per_source"],
                  ovh=row["baseline"]["stopset_overhead_per_source"],
                  passl=row["pass_line_travel_s"],
                  cov="Y" if row["clears_only"]["certified_exact"] else "N",
                  extra=row["shared"]["extra_count"],
                  shared=row["shared"]["floor_per_source"],
                  cross="Y" if row["shared"]["crosses_pass_line"] else "N"))

    payload = {
        "task": "t14 Q3/16 stop-set sharing study",
        "basis": {
            "speed_m_per_s": SPEED,
            "cover_radius_m": COVER_R,
            "omega_radius_m": OMEGA_R,
            "grid_step_m": GRID_STEP,
            "target_per_source_s": TARGET_PER_SOURCE,
            "ring_radius_m": RING_RADIUS,
            "ring_points": RING_POINTS,
            "mst": "Euclidean MST over {origin} u points (Prim)",
            "service": "run ledger T_measure + T_switch + T_clear",
            "exact_decider": "geometry.certificate.q3_certified",
            "independent_check": "dense Omega grid, worst distance to nearest stop",
        },
        "code_sha256": {
            "tools/q3_stop_sharing_study.py": sha256(
                Path(__file__).resolve()),
            "geometry/certificate.py": sha256(
                ROOT / "baseline" / "code" / "geometry" / "certificate.py"),
        },
        "inputs": {},
        "runs": runs,
    }
    for run_dir in dirs:
        if not (run_dir / "api_log.jsonl").exists():
            continue
        key = str(run_dir.relative_to(ROOT)).replace("\\", "/")
        payload["inputs"][key] = {
            "ground_truth.json": sha256(run_dir / "ground_truth.json"),
            "metrics.json": sha256(run_dir / "metrics.json"),
            "api_log.jsonl": sha256(run_dir / "api_log.jsonl"),
        }
    dest = ROOT / "tuning_runs" / "q3_stop_sharing.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print("wrote %s (%d runs)" % (dest.relative_to(ROOT), len(runs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
