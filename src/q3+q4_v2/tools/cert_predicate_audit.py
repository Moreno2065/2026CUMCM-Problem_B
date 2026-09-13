# -*- coding: utf-8 -*-
"""Independent audit of the two Q4 channel-absence predicates.

Does NOT reuse the generation-side implementations for any verdict.  Every
predicate used below is re-derived here from first principles:

  * detection semantics -- re-derived from the *problem statement* form
    (directional emitter, +-90 deg closed half-plane about the emitter's own
    orientation, range r_eff) and cross-checked once against the frozen
    simulator's ``Source.covers`` (read for validation only, see
    ``validate_against_reference``);
  * ``mesh25`` coordinates -- re-derived from the documented ring geometry
    (centre + 12-gon r=950 at 15+30k deg + 12-gon r=1870 at 30k deg) and
    cross-checked once against the frozen generator;
  * convex hull / point-in-hull -- own monotone-chain implementation;
  * the delta-hull condition -- own implementation in BOTH forms
    (support-function scan and edge-distance), required to agree;
  * Omega coverage -- own sampled check with a rigorous Lipschitz bound.

The two cross-checks are validation only: they never feed a verdict, and their
agreement is reported in the output.

Run:  python -X utf8 tools/cert_predicate_audit.py
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- problem constants (re-derived from the frozen constants module) --------
OMEGA_RADIUS = 1800.0
R_EFF_MIN = 1000.0
Q4_DELTA = 370.0
Q4_GRID_SPACING = 620.0
INNER_RADIUS = 950.0
OUTER_RADIUS = 1870.0
RING_SIZE = 12
MATCH_TOL = 1e-6
COVER_TOL = 1e-6
EPS = 1e-9


# ---------------------------------------------------------------------------
# Independent mesh25 reconstruction
# ---------------------------------------------------------------------------

def mesh25() -> list:
    pts = [(0.0, 0.0)]
    for k in range(RING_SIZE):
        a = math.radians(15.0 + 30.0 * k)
        pts.append((INNER_RADIUS * math.cos(a), INNER_RADIUS * math.sin(a)))
    for k in range(RING_SIZE):
        a = math.radians(30.0 * k)
        pts.append((OUTER_RADIUS * math.cos(a), OUTER_RADIUS * math.sin(a)))
    return pts


# ---------------------------------------------------------------------------
# Own computational geometry
# ---------------------------------------------------------------------------

def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points):
    """Andrew monotone chain; returns CCW hull vertices, collinear dropped."""
    pts = sorted({(float(p[0]), float(p[1])) for p in points})
    if len(pts) <= 1:
        return pts
    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0.0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0.0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def hull_area(hull):
    n = len(hull)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def min_edge_distance(hull, x):
    """Signed distance from x to the nearest hull edge line (CCW hull).

    Positive when x is strictly inside (all edges left of x).
    """
    n = len(hull)
    if n < 3:
        return None
    best = float("inf")
    inside = True
    for i in range(n):
        a = hull[i]
        b = hull[(i + 1) % n]
        # outward normal distance: CCW hull -> interior is left of a->b
        ex, ey = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(ex, ey)
        if ln <= EPS:
            continue
        # positive = left side = interior
        d = (ex * (x[1] - a[1]) - ey * (x[0] - a[0])) / ln
        if d < 0.0:
            inside = False
        if d < best:
            best = d
    return best if inside else -abs(best)


def point_in_convex(all_pts, g):
    """True iff g is in the closed convex hull of ``all_pts``.

    Handles the degenerate cases exactly (0/1/2 points) by separate tests,
    because the surrounding lemma needs ``g in conv(A)`` including boundary.
    """
    pts = [(float(p[0]), float(p[1])) for p in all_pts]
    if not pts:
        return False
    if len(pts) == 1:
        return math.hypot(pts[0][0] - g[0], pts[0][1] - g[1]) <= 1e-9
    if len(pts) == 2:
        (x1, y1), (x2, y2) = pts
        vx, vy = x2 - x1, y2 - y1
        wx, wy = g[0] - x1, g[1] - y1
        ln2 = vx * vx + vy * vy
        if ln2 <= 1e-18:
            return math.hypot(wx, wy) <= 1e-9
        t = (wx * vx + wy * vy) / ln2
        if t < -1e-12 or t > 1 + 1e-12:
            return False
        px, py = x1 + t * vx, y1 + t * vy
        return math.hypot(g[0] - px, g[1] - py) <= 1e-9
    h = convex_hull(pts)
    if len(h) < 3:
        return point_in_convex(h, g)
    n = len(h)
    for i in range(n):
        a = h[i]
        b = h[(i + 1) % n]
        if _cross(a, b, g) < -1e-9:
            return False
    return True


# ---------------------------------------------------------------------------
# Exact soundness criterion (independent of both predicates)
# ---------------------------------------------------------------------------

def witnesses_within(W, g, r_eff):
    return [p for p in W if math.hypot(p[0] - g[0], p[1] - g[1]) <= r_eff]


def escape_at(W, g, r_eff):
    """True iff SOME orientation makes a source at g invisible to all of W.

    A source at g with orientation u is invisible to witness p iff
    ``u.(p-g) < 0`` (strictly behind the closed +-90 deg half-plane) or the
    point is out of range.  Hence invisible-for-all-W is solvable iff there is
    a direction
    strictly separating g from every in-range witness, i.e. iff
    ``g not in conv(W cap B(g, r_eff))``.
    """
    A = witnesses_within(W, g, r_eff)
    return not point_in_convex(A, g)


def soundness_scan(W, r_eff=R_EFF_MIN, rings=180, spokes=1440):
    """Scan Omega for an escaping source position; returns worst margin.

    margin(g) = +dist(g, conv(A(g))) when g is outside (escape) else 0.
    We approximate ``dist(g, conv(A))`` by the maximum over sampled directions
    of the strict-separation slack; a positive slack at any direction is a
    certificate of escape.
    """
    worst = 0.0
    witness = None
    n_dir = 720
    cos_t = [math.cos(2 * math.pi * k / n_dir) for k in range(n_dir)]
    sin_t = [math.sin(2 * math.pi * k / n_dir) for k in range(n_dir)]
    for i in range(rings + 1):
        r = OMEGA_RADIUS * i / rings
        for j in range(spokes):
            a = 2 * math.pi * j / spokes
            g = (r * math.cos(a), r * math.sin(a))
            A = witnesses_within(W, g, r_eff)
            if not A:
                slack = min(math.hypot(p[0] - g[0], p[1] - g[1]) for p in W) \
                    if W else float("inf")
                if slack > worst:
                    worst, witness = slack, (g, "no witness in range")
                continue
            if point_in_convex(A, g):
                continue
            best = 0.0
            for k in range(n_dir):
                m = max(cos_t[k] * p[0] + sin_t[k] * p[1] for p in A)
                s = (cos_t[k] * g[0] + sin_t[k] * g[1]) - m
                if s > best:
                    best = s
            if best > worst:
                worst, witness = best, (g, "separated, |A|=%d" % len(A))
    return worst, witness


# ---------------------------------------------------------------------------
# Predicate A: sparse25 fixed-point membership
# ---------------------------------------------------------------------------

def pred_sparse25(W, tol=MATCH_TOL):
    mesh = mesh25()
    missing = [q for q in mesh
               if not any(math.hypot(q[0] - p[0], q[1] - p[1]) <= tol
                          for p in W)]
    return {"certified": not missing, "missing": missing,
            "matched": len(mesh) - len(missing)}


# ---------------------------------------------------------------------------
# Predicate B: delta-robust convex hull + Omega coverage
# ---------------------------------------------------------------------------

def pred_certify_point(x, W, delta=Q4_DELTA, r_eff_min=R_EFF_MIN,
                       n_dir=720):
    """Own implementation; BOTH forms must agree."""
    r_w = r_eff_min - delta
    A = [(float(p[0]), float(p[1])) for p in W
         if math.hypot(p[0] - x[0], p[1] - x[1]) <= r_w + EPS]
    if len(A) < 3:
        return {"certified": False, "reason": "fewer than 3 witnesses",
                "witness_count": len(A), "min_edge_distance": None,
                "support_margin": None}
    h = convex_hull(A)
    if len(h) < 3 or hull_area(h) <= EPS:
        return {"certified": False, "reason": "degenerate hull",
                "witness_count": len(A), "min_edge_distance": None,
                "support_margin": None}
    dmin = min_edge_distance(h, x)
    margin = float("inf")
    for k in range(n_dir):
        t = 2 * math.pi * k / n_dir
        c, s = math.cos(t), math.sin(t)
        hr = max(c * p[0] + s * p[1] for p in A)
        margin = min(margin, (hr - (c * x[0] + s * x[1])) - delta)
    # support form: x.u + delta <= h_A(u) for all u   --  margin >= 0
    cert_edges = dmin is not None and dmin >= delta - COVER_TOL
    cert_support = margin >= -COVER_TOL
    if cert_edges != cert_support:
        return {"certified": False, "reason": "FORM DISAGREEMENT",
                "witness_count": len(A), "min_edge_distance": dmin,
                "support_margin": margin, "form_conflict": True}
    return {"certified": bool(cert_edges), "reason": "ok" if cert_edges
            else "inscribed radius %.3f < delta" % (dmin or -1e9),
            "witness_count": len(A), "min_edge_distance": dmin,
            "support_margin": margin, "form_conflict": False}


def omega_cover(centers, delta=Q4_DELTA, radius=OMEGA_RADIUS,
                rings=180, spokes=1440):
    """max_{g in Omega} min_i |g-x_i|, with a rigorous Lipschitz upper bound."""
    if not centers:
        return {"covered": False, "sample_max": float("inf"),
                "upper_bound": float("inf")}
    step = 2 * math.pi * radius / spokes
    h = radius / rings
    sample_max = 0.0
    argmax = None
    for i in range(rings + 1):
        r = radius * i / rings
        for j in range(spokes):
            a = 2 * math.pi * j / spokes
            g = (r * math.cos(a), r * math.sin(a))
            d = min(math.hypot(g[0] - c[0], g[1] - c[1]) for c in centers)
            if d > sample_max:
                sample_max, argmax = d, g
    # f(g) = min_i |g-x_i| is 1-Lipschitz; nearest sample is <= max(h, step/2)
    lip = max(h, step / 2.0) * math.sqrt(2.0)
    return {"covered": sample_max <= delta, "sample_max": sample_max,
            "upper_bound": sample_max + lip, "lip_correction": lip,
            "argmax": argmax,
            "covered_certified": (sample_max + lip) <= delta}


# ---------------------------------------------------------------------------
# Validation cross-checks against the frozen reference (never a verdict)
# ---------------------------------------------------------------------------

def validate_against_reference(W_sample, points):
    out = {}
    try:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "baseline" / "code"))
        from geometry.q4_sparse_mesh import (          # noqa: N811
            q4_sparse25_points, q4_channel_certified_sparse25)
        from geometry.certificate import q4_certify_point   # noqa: N811
        ref_mesh = q4_sparse25_points()
        out["mesh_max_abs_diff"] = max(
            math.hypot(a[0] - b[0], a[1] - b[1])
            for a, b in zip(mesh25(), ref_mesh))
        out["mesh_len_equal"] = len(mesh25()) == len(ref_mesh)
        out["sparse25_agree"] = (
            pred_sparse25(W_sample)["certified"]
            == bool(q4_channel_certified_sparse25(W_sample)))
        vals = [(pred_certify_point(x, W_sample)["certified"],
                 bool(q4_certify_point(x, W_sample)["certified"]))
                for x in points]
        out["certify_point_agree"] = sum(1 for a, b in vals if a == b)
        out["certify_point_total"] = len(vals)
        out["certify_point_disagreements"] = [
            i for i, (a, b) in enumerate(vals) if a != b]
    except Exception as exc:                      # pragma: no cover
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


# ---------------------------------------------------------------------------
# Real witness sets
# ---------------------------------------------------------------------------

def load_real_witness_sets(limit=8, per_file=2):
    """Pull per-channel no_signal sets from real Q4 runs (sparse25 basis),
    spread over several run directories."""
    found = []
    for f in sorted((ROOT / "tuning_runs").rglob("certificate.json")):
        par = f.parent.name.upper()
        if not par.startswith("Q4"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        taken = 0
        for ch, rec in d.items():
            if rec.get("absent_basis") != "sparse25":
                continue
            W = [(float(p[0]), float(p[1]))
                 for p in (rec.get("no_signal_points") or [])]
            if len(W) < 25:
                continue
            found.append({
                "file": str(f.relative_to(ROOT)).replace("\\", "/"),
                "channel": ch, "n_witnesses": len(W), "W": W,
                "centers": [(float(c[0]), float(c[1]))
                            for c in (rec.get("certified_centers") or [])],
            })
            taken += 1
            if taken >= per_file or len(found) >= limit:
                break
        if len(found) >= limit:
            return found
    return found


# ---------------------------------------------------------------------------
# Constructions
# ---------------------------------------------------------------------------

def construct_sparse_only():
    """W = mesh25 exactly: sparse25 TRUE, delta-route FALSE."""
    return mesh25()


def construct_hull_only(spacing=Q4_GRID_SPACING, delta=Q4_DELTA,
                        radius=OMEGA_RADIUS, extra_spacing=1):
    """W = equilateral-triangle lattice whose *certified* subset covers Omega.

    Covering radius of the s-triangular lattice is s/sqrt(3) = 357.75 < 370.
    Neighbours sit at exactly ``spacing`` <= r_eff_min - delta = 630, so an
    interior lattice point has its own 6-gon witness hull (inradius 536.9 >=
    370) and is a certified centre.  Boundary lattice points lack neighbours
    and are NOT certified, so the lattice is grown ``extra_spacing`` rows
    beyond Omega + delta to leave a certified interior covering Omega -- which
    mirrors production, where only individually certified cells enter
    ``certified_centers``.  Whether the lattice reproduces the 25 mesh
    coordinates is measured, not assumed.
    """
    s = float(spacing)
    h = s * math.sqrt(3.0) / 2.0
    reach = radius + delta + extra_spacing * spacing
    y0 = -math.ceil(reach / h) * h
    pts = []
    k = int(round(y0 / h))
    y = y0
    while y <= reach + EPS:
        off = 0.0 if (k % 2 == 0) else s / 2.0
        m = int(math.ceil((-reach - off) / s))
        x = off + m * s
        while x <= reach + EPS:
            if math.hypot(x, y) <= reach + EPS:
                pts.append((x, y))
            x += s
        y += h
        k += 1
    return pts


def min_centers_area_bound(delta=Q4_DELTA, radius=OMEGA_RADIUS):
    """Counting bound: |Omega| / (pi delta^2)."""
    return (radius * radius) / (delta * delta)


def point_strictly_inside(all_pts, g, tol=1e-9):
    """True iff g is in the OPEN convex hull (interior) of ``all_pts``."""
    if not point_in_convex(all_pts, g):
        return False
    h = convex_hull(all_pts)
    if len(h) < 3:
        return False
    d = min_edge_distance(h, g)
    return d is not None and d > tol


def construct_tight_triangle(delta=Q4_DELTA):
    """Witnesses forming a SQUARE whose inradius about x=(0,0) is exactly
    ``delta``: vertices at radius delta*sqrt(2) at 45/135/225/315 deg.

    The inradius of a square with circumradius R is R/sqrt(2), so R =
    delta*sqrt(2) = 523.26 <= r_eff_min - delta = 630 -- i.e. the tight case
    is reachable *inside* the witness ball, so the predicate actually accepts
    it while B(x,delta) touches every edge.  (An equilateral triangle cannot
    be tight here: it would need R = 2*delta = 740 > 630, giving 0 witnesses.)
    """
    R = delta * math.sqrt(2.0)
    W = []
    for ang in (45.0, 135.0, 225.0, 315.0):
        a = math.radians(ang)
        W.append((R * math.cos(a), R * math.sin(a)))
    return W


def half_plane_closure_test(delta=Q4_DELTA, r_eff_min=R_EFF_MIN):
    """Does the certificate survive an OPEN (+-90 deg exclusive) half-plane?

    Closed model  : invisible iff g NOT in conv(A(g)).
    Open model    : invisible iff g NOT in int(conv(A(g))).
    So any g on the boundary of conv(A(g)) separates the two.
    """
    W = construct_tight_triangle(delta)
    x = (0.0, 0.0)
    cert = pred_certify_point(x, W, delta=delta, r_eff_min=r_eff_min)
    # midpoint of the edge between the 225 and 315 deg vertices (= bottom edge)
    p1 = W[2]
    p2 = W[3]
    g = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    A = witnesses_within(W, g, r_eff_min)
    return {
        "predicate_certified": cert["certified"],
        "min_edge_distance": cert["min_edge_distance"],
        "witness_count": cert["witness_count"],
        "probe_g": list(g),
        "probe_dist_to_x": math.hypot(g[0] - x[0], g[1] - x[1]),
        "probe_in_range_witnesses": len(A),
        "all_witnesses_in_range_of_g": len(A) == len(W),
        "g_in_closed_hull": point_in_convex(A, g),
        "g_strictly_inside_hull": point_strictly_inside(A, g),
        "escapes_closed_model": not point_in_convex(A, g),
        "escapes_open_model": not point_strictly_inside(A, g),
    }


def delta_mismatch_test(cert_delta=Q4_DELTA, cover_delta=430.0):
    """If the union-cover radius exceeds the per-point certification delta,
    the union cover no longer implies Omega coverage by *certified* balls."""
    W = mesh25()
    return {
        "cert_delta": cert_delta,
        "cover_delta": cover_delta,
        "note": "q4_channel_certified(centers) takes its own delta argument; "
                "passing a larger delta than the one used in q4_certify_point "
                "enlarges the accepted union without enlarging any proven "
                "region -- i.e. the coverage guard and the point guard must "
                "use the same delta for the implication to hold",
        "same_delta_holds": cert_delta == cover_delta,
    }


def main():
    report = {"reference_validation": {}, "mesh_scan": {},
              "constructions": {}, "real_runs": {}, "verdict": {}}

    base_W = mesh25()
    probe_points = mesh25()[:5] + [(640.0, 0.0), (0.0, 640.0)]
    report["reference_validation"] = validate_against_reference(
        base_W, probe_points)

    # --- mesh soundness scan -------------------------------------------
    worst, wit = soundness_scan(mesh25(), R_EFF_MIN)
    report["mesh_scan"] = {
        "r_eff": R_EFF_MIN, "worst_escape_slack": worst,
        "witness": None if wit is None else {"g": list(wit[0]),
                                            "note": wit[1]},
        "sound": worst <= 1e-9,
    }
    # necessary r_eff: max over Omega of distance to nearest mesh point
    best = 0.0
    arg = None
    for i in range(181):
        r = OMEGA_RADIUS * i / 180
        for j in range(1440):
            a = 2 * math.pi * j / 1440
            g = (r * math.cos(a), r * math.sin(a))
            d = min(math.hypot(g[0] - q[0], g[1] - q[1]) for q in mesh25())
            if d > best:
                best, arg = d, g
    report["mesh_scan"]["max_dist_to_mesh_over_Omega"] = best
    report["mesh_scan"]["argmax_g"] = list(arg)
    report["mesh_scan"]["required_r_eff_lower_bound"] = best

    # --- premise failure: r_eff below the required bound ----------------
    fail = {}
    for r_eff in (399.0, 400.0, 500.0, 999.0, 1000.0):
        w, wi = soundness_scan(mesh25(), r_eff, rings=90, spokes=720)
        fail[str(int(r_eff))] = {"worst_escape_slack": w,
                                 "sound": w <= 1e-9}
    report["premise_r_eff_failure"] = fail

    # --- constructions ---------------------------------------------------
    W1 = construct_sparse_only()
    W2 = construct_hull_only()
    p1 = pred_sparse25(W1)
    centers2 = [g for g in W2 if pred_certify_point(g, W2)["certified"]]
    cov2 = omega_cover(centers2)
    p2 = pred_sparse25(W2)
    centers1 = [g for g in W1 if pred_certify_point(g, W1)["certified"]]
    cov1 = omega_cover(centers1)
    report["constructions"] = {
        "W1_mesh_only": {
            "n_witnesses": len(W1),
            "sparse25_certified": p1["certified"],
            "delta_route_certified": bool(centers1) and cov1["covered"],
            "delta_route_certified_rigorous": bool(centers1)
            and cov1["covered_certified"],
            "n_certified_centers": len(centers1),
            "cover_sample_max": cov1["sample_max"],
            "sound_by_scan": soundness_scan(W1, R_EFF_MIN, rings=90,
                                            spokes=720)[0] <= 1e-9,
        },
        "W2_rings_no_mesh": {
            "n_witnesses": len(W2),
            "sparse25_certified": p2["certified"],
            "sparse25_missing": len(p2["missing"]),
            "delta_route_certified": bool(centers2) and cov2["covered"],
            "delta_route_certified_rigorous": bool(centers2)
            and cov2["covered_certified"],
            "n_certified_centers": len(centers2),
            "cover_sample_max": cov2["sample_max"],
            "cover_upper_bound": cov2["upper_bound"],
            "sound_by_scan": soundness_scan(W2, R_EFF_MIN, rings=90,
                                            spokes=720)[0] <= 1e-9,
        },
    }
    report["min_centers"] = {
        "area_counting_lower_bound": min_centers_area_bound(),
        "mesh25_points": len(mesh25()),
        "W2_lattice_points": len(W2),
        "W2_certified_centers": len(centers2),
        "W2_analytic_covering_radius": Q4_GRID_SPACING / math.sqrt(3.0),
        "W2_sampled_cover_max": cov2["sample_max"],
        "W2_analytic_cover_holds": (Q4_GRID_SPACING / math.sqrt(3.0)) < Q4_DELTA,
        "note": "area bound (R/delta)^2 is the packing lower bound on centres "
                "needed to delta-cover Omega; the s-triangular lattice has "
                "analytic covering radius s/sqrt(3)=357.957 < 370 so Omega is "
                "covered rigorously, sampling merely corroborates it",
    }
    report["premise_half_plane_closure"] = half_plane_closure_test()
    report["premise_delta_mismatch"] = delta_mismatch_test()

    # --- real runs --------------------------------------------------------
    real = load_real_witness_sets(limit=6)
    rows = []
    for item in real:
        W = item["W"]
        sp = pred_sparse25(W)
        centers = item["centers"]
        cert_centers = [g for g in W if pred_certify_point(g, W)["certified"]]
        cov = omega_cover(cert_centers) if cert_centers else {
            "covered": False, "sample_max": float("inf")}
        worst, wi = soundness_scan(W, R_EFF_MIN, rings=60, spokes=360)
        rows.append({
            "file": item["file"], "channel": item["channel"],
            "n_witnesses": len(W),
            "sparse25_certified": sp["certified"],
            "sparse25_missing": len(sp["missing"]),
            "reported_absent_basis": "sparse25",
            "certified_centers_accumulated": len(centers),
            "centers_certified_now": len(cert_centers),
            "delta_route_certified": bool(cert_centers) and cov["covered"],
            "cover_sample_max": cov["sample_max"],
            "exact_sound_by_scan": worst <= 1e-9,
            "worst_escape_slack": worst,
        })
    report["real_runs"] = {"count": len(rows), "rows": rows}

    # --- basis census -----------------------------------------------------
    census = {}
    files = [f for f in (ROOT / "tuning_runs").rglob("certificate.json")
             if f.parent.name.upper().startswith("Q4")]
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in d.values():
            b = str(rec.get("absent_basis"))
            census[b] = census.get(b, 0) + 1
    report["basis_census"] = {"files": len(files), "bases": census}

    out_json = ROOT / "tuning_runs" / "cert_predicate_audit.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("\nwrote %s" % out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
