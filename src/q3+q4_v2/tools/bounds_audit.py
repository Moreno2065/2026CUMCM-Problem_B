# -*- coding: utf-8 -*-
"""Independent audit of tuning_runs/BOUNDS.md (t26) -- own implementation.

Deliberately does NOT import tools/bounds_report.py and does not reuse its
output.  Own MST, own exact open-path solver (Held-Karp for n<=12, with an
MST sandwich above), own certificate validity oracle call.

Parts
  1. Q3 movement term: the predicate only asks Omega subset U B(w, 1000), so the
     witness positions are free -> a provable lower bound must take the MINIMUM
     over all valid coverings.  Searched analytically over ring families and
     improved by hill climbing; validity is decided by the exact
     geometry.certificate.q3_certified, never by a sampled margin.
  2. Q4 movement term: is q4_channel_certified_sparse25 coordinate-fixed?
  3. Six-cell composite bound from the audited movement/service/clear terms.
  4. Per-episode identity  T_total = MST(stops)/5 + detour + measure + switch
     + clear, on >=10 runs to 1e-6.

Read-only.  Run:  python -X utf8 tools/bounds_audit.py
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))
SPEED = 5.0
R_COVER = 1000.0
OMEGA = 1800.0
CLEAR_S = 5.0
MEASURE_S = 5.0

from geometry.certificate import q3_certified  # noqa: E402


# --------------------------------------------------------------- geometry --
def mst_len(pts):
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


def held_karp(pts):
    """Exact open path from index 0, free end."""
    n = len(pts)
    if n <= 1:
        return 0.0
    if n == 2:
        return math.dist(pts[0], pts[1])
    d = [[math.dist(a, b) for b in pts] for a in pts]
    full = 1 << (n - 1)
    INF = float("inf")
    dp = [[INF] * (n - 1) for _ in range(full)]
    for j in range(n - 1):
        dp[1 << j][j] = d[0][j + 1]
    for mask in range(full):
        for j in range(n - 1):
            cur = dp[mask][j]
            if cur == INF or not (mask >> j) & 1:
                continue
            for k in range(n - 1):
                if (mask >> k) & 1:
                    continue
                v = cur + d[j + 1][k + 1]
                if v < dp[mask | (1 << k)][k]:
                    dp[mask | (1 << k)][k] = v
    return min(dp[full - 1])


def nn_2opt_oropt(pts):
    left = set(range(1, len(pts)))
    order = [0]
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda i: math.dist(last, pts[i]))
        order.append(nxt)
        left.discard(nxt)

    def L(o):
        return sum(math.dist(pts[o[i]], pts[o[i + 1]]) for i in range(len(o) - 1))

    improved = True
    while improved:
        improved = False
        n = len(order)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = pts[order[i - 1]], pts[order[i]]
                c = pts[order[j]]
                dd = pts[order[j + 1]] if j + 1 < n else None
                before = math.dist(a, b) + (math.dist(c, dd) if dd else 0.0)
                after = math.dist(a, c) + (math.dist(b, dd) if dd else 0.0)
                if after + 1e-9 < before:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        for i in range(1, n):
            node = order[i]
            rest = order[:i] + order[i + 1:]
            cur = L(order)
            bo, bl = order, cur
            for k in range(1, len(rest)):
                cand = rest[:k] + [node] + rest[k:]
                ln = L(cand)
                if ln + 1e-9 < bl:
                    bl, bo = ln, cand
            if bl + 1e-9 < cur:
                order, improved = bo, True
    return L(order)


def open_path_lb(pts):
    """Lower bound on the optimal open path from pts[0]; exact for n<=12."""
    if len(pts) <= 12:
        v = held_karp(pts)
        return v, v, "held-karp-exact"
    lb = mst_len(pts)
    ub = nn_2opt_oropt(pts)
    return lb, ub, "mst-lb/nn-ub"


# ------------------------------------------------------- Q3 covering search --
def ring(k, r, phase=0.0):
    return [(r * math.cos(phase + 2 * math.pi * i / k),
             r * math.sin(phase + 2 * math.pi * i / k)) for i in range(k)]


def valid(points):
    return bool(q3_certified([(float(p[0]), float(p[1])) for p in points])
                ["certified"])


def min_uniform_radius(k, centre=False, lo=200.0, hi=1800.0, iters=60):
    """Smallest radius at which the symmetric family is certified."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        pts = ([(0.0, 0.0)] if centre else []) + ring(k, mid)
        if valid(pts):
            hi = mid
        else:
            lo = mid
    return hi


def hillslide(points, rounds=3):
    """Shrink each point radially / tangentially while staying certified."""
    pts = [list(p) for p in points]
    best = open_path_lb([(0.0, 0.0)] + [tuple(p) for p in pts])[0]
    step = 60.0
    while step > 0.5:
        improved = False
        for i in range(len(pts)):
            for dr, dt in ((step, 0), (-step, 0), (0, 0.05), (0, -0.05)):
                trial = [list(p) for p in pts]
                x, y = trial[i]
                r = math.hypot(x, y)
                a = math.atan2(y, x)
                a2 = a + dt
                r2 = max(0.0, r + dr)
                trial[i] = [r2 * math.cos(a2), r2 * math.sin(a2)]
                if not valid(trial):
                    continue
                v = open_path_lb([(0.0, 0.0)] + [tuple(p) for p in trial])[0]
                if v < best - 1e-6:
                    pts, best, improved = trial, v, True
        if not improved:
            step *= 0.5
    return pts, best


def q3_search():
    out = {}
    for k in (5, 6, 7, 8):
        # family: k ring points, no centre
        r_nc = min_uniform_radius(k, centre=False)
        pts_nc = ring(k, r_nc)
        ok_nc = valid(pts_nc)
        entry = {"min_uniform_radius_no_centre": round(r_nc, 2),
                 "certified_no_centre": ok_nc}
        if ok_nc:
            v, _ub, how = open_path_lb([(0.0, 0.0)] + pts_nc)
            entry.update({"open_path_m": round(v, 2), "method": how,
                          "open_path_s": round(v / SPEED, 1)})
            sliding, bestv = hillslide(pts_nc)
            entry["after_hillslide_open_path_m"] = round(bestv, 2)
            entry["after_hillslide_certified"] = valid(sliding)
        # family: centre + k ring points
        r_c = min_uniform_radius(k, centre=True)
        pts_c = [(0.0, 0.0)] + ring(k, r_c)
        ok_c = valid(pts_c)
        entry["min_uniform_radius_with_centre"] = round(r_c, 2)
        entry["certified_with_centre"] = ok_c
        if ok_c:
            v2, _ub2, how2 = open_path_lb([(0.0, 0.0)] + pts_c)
            entry["open_path_with_centre_m"] = round(v2, 2)
            entry["open_path_with_centre_s"] = round(v2 / SPEED, 1)
        out["k=%d" % k] = entry
    return out


# ------------------------------------------------------- Q4 fixed coords ----
def sparse25():
    pts = [(0.0, 0.0)]
    for i in range(12):
        a = math.radians(15.0 + 30.0 * i)
        pts.append((950.0 * math.cos(a), 950.0 * math.sin(a)))
    for i in range(12):
        a = math.radians(30.0 * i)
        pts.append((1870.0 * math.cos(a), 1870.0 * math.sin(a)))
    return pts


def q4_source_check():
    import inspect
    from geometry import q4_sparse_mesh as m
    src = inspect.getsource(m.q4_channel_certified_sparse25)
    return {
        "predicate_source": src.strip().splitlines()[-6:],
        "coordinates_are_module_constants":
            "q4_sparse25_points()" in src,
        "tol": m.MATCH_TOL,
    }


# ------------------------------------------------------------- per-run -----
def load_actions(run_dir):
    rows = []
    p = run_dir / "api_log.jsonl"
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = rec.get("request") or {}
        pos = req.get("position") or {}
        rows.append({
            "ep": rec.get("endpoint"),
            "pos": (float(pos["x"]), float(pos["y"]))
            if "x" in pos and "y" in pos else None,
            "dt": rec.get("dt") or {},
        })
    return rows


def identity_check(run_dir, cert_open_m):
    rows = load_actions(run_dir)
    if not rows:
        return None
    mv = sum(float(r["dt"].get("move") or 0.0) for r in rows)
    ms = sum(float(r["dt"].get("measure") or 0.0) for r in rows)
    sw = sum(float(r["dt"].get("switch") or 0.0) for r in rows)
    cl = sum(float(r["dt"].get("clear") or 0.0) for r in rows)
    stops, seen = [], set()
    for r in rows:
        if r["ep"] in ("/measure", "/clear") and r["pos"]:
            if r["pos"] not in seen:
                seen.add(r["pos"])
                stops.append(r["pos"])
    m = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    t_total = float(m.get("T_total_virtual"))
    mst_s = mst_len([(0.0, 0.0)] + stops) / SPEED
    detour = mv - mst_s
    lhs = mst_s + detour + ms + sw + cl
    residual = mst_s - cert_open_m / SPEED
    return {
        "run": str(run_dir.relative_to(ROOT)),
        "n_stops_distinct": len(stops),
        "T_total": t_total, "T_move": mv, "T_measure": ms,
        "T_switch": sw, "T_clear": cl,
        "mst_stops_s": mst_s, "detour_s": detour,
        "identity_lhs": lhs, "abs_err": abs(lhs - t_total),
        "residual_s": residual,
        "residual_from_definition_s": (mst_s - cert_open_m / SPEED),
    }


def main():
    out = {"q3_covering_search": q3_search(),
           "q4_fixed_coordinates": q4_source_check()}

    # --- composite bounds ---------------------------------------------------
    N = {"10": 10, "13": 13, "16": 16}
    absent = {"Q3": {"10": 10, "13": 7, "16": 4},
              "Q4": {"10": 10, "13": 7, "16": 4}}
    # minimum certified open path per k (from the search)
    best7 = out["q3_covering_search"]["k=7"].get("after_hillslide_open_path_m")
    best7 = min(best7, out["q3_covering_search"]["k=7"]["open_path_m"])
    q4_open = open_path_lb([(0.0, 0.0)] + sparse25())
    out["q4_open_path"] = {"lower_bound_m": round(q4_open[0], 2),
                           "upper_bound_m": round(q4_open[1], 2),
                           "method": q4_open[2]}
    comp = {}
    for k7 in (best7, 6744.0, 7200.0):
        key = "Q3 open path %.1f m" % k7
        comp[key] = {}
        for n in ("10", "13", "16"):
            nn = N[n]
            svc = 7 * absent["Q3"][n] * MEASURE_S
            tot = k7 / SPEED + svc + CLEAR_S * nn
            comp[key]["Q3/%s" % n] = round(tot / nn, 2)
    for n in ("10", "13", "16"):
        nn = N[n]
        svc = 25 * absent["Q4"][n] * MEASURE_S
        tot = q4_open[0] / SPEED + svc + CLEAR_S * nn
        comp.setdefault("Q4 (25 fixed pts)", {})["Q4/%s" % n] = round(tot / nn, 2)
    out["six_cell_composite"] = comp
    out["targets"] = {"Q3": 176.25, "Q4": 290.0}

    # --- identity on >=10 runs ---------------------------------------------
    ids = []
    dirs = sorted((ROOT / "tuning_runs" / "final_recommended_v3").glob("Q*"))
    cert_open = {"Q3": best7 if best7 else 6744.0, "Q4": q4_open[0]}
    for d in dirs:
        if not (d / "api_log.jsonl").is_file():
            continue
        mode = d.name.split("_")[0]
        r = identity_check(d, cert_open[mode])
        if r:
            ids.append(r)
    out["identity_checks"] = ids
    out["identity_max_abs_err"] = max((r["abs_err"] for r in ids), default=None)
    out["identity_n_runs"] = len(ids)

    dest = ROOT / "tuning_runs" / "bounds_audit.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("q3_covering_search", "q4_open_path",
                       "six_cell_composite", "identity_n_runs",
                       "identity_max_abs_err")},
                     ensure_ascii=False, indent=1)[:5000])
    print("\nwrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
