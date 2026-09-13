# -*- coding: utf-8 -*-
"""Verifier-precision worst-case coverage-margin audit for the Q3 ring translate.

Independent of candidate-eng's own margin check (which samples 360 boundary
points).  Method:

  * Omega = B(0,1800) is sampled on a polar grid (RADIAL_RINGS x ANGULAR_SPOKES),
    vectorised with numpy;
  * f(g) = min_i |g - p_i| is 1-Lipschitz, so (sampled max + the largest
    distance from any point of Omega to its nearest sample) is a *rigorous
    upper bound* on max f, hence 1000 - that is a rigorous *lower* bound on the
    cover margin;
  * the sampled argmax is refined with a compass search (step halving) to give a
    tight best estimate of the true worst margin.  A negative refined margin is
    self-certifying (the refined point is an explicit violating witness).

Coverage contract (Q3): Omega must be inside U B(p, 1000) over the channel's
recorded no-signal points.  Cover margin = 1000 - max f.

Read-only: learned_search / baseline / verification and the captain's tools are
never modified.

Run:
  python -X utf8 tools/gate8_margin_audit.py
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMEGA = 1800.0
R_COVER = 1000.0
RUNS = ROOT / "tuning_runs" / "ab_probe"

RADIAL_RINGS = 720          # h = 2.5 m
ANGULAR_SPOKES = 5760       # 2*pi*1800/5760 = 1.96 m at the rim


def lip_bound(rings=RADIAL_RINGS, spokes=ANGULAR_SPOKES, omega=OMEGA):
    """Largest distance from any point of Omega to its nearest grid sample."""
    h = omega / rings
    return math.sqrt((h / 2.0) ** 2 + (math.pi * omega / spokes) ** 2)


def make_grid(rings=RADIAL_RINGS, spokes=ANGULAR_SPOKES):
    r = np.linspace(0.0, OMEGA, rings + 1)
    a = np.arange(spokes) * (2.0 * math.pi / spokes)
    ca, sa = np.cos(a), np.sin(a)
    return r, ca, sa


def grid_max(points, r, ca, sa):
    """Vectorised max over the polar grid of min-distance to ``points``."""
    P = np.asarray(points, dtype=np.float64)          # (m, 2)
    px = P[:, 0][None, :]
    py = P[:, 1][None, :]
    best = -1.0
    arg = None
    for i in range(len(r)):
        gx = (r[i] * ca)[:, None]                     # (spokes,1)
        gy = (r[i] * sa)[:, None]
        d = np.min(np.hypot(gx - px, gy - py), axis=1)   # (spokes,)
        j = int(np.argmax(d))
        if d[j] > best:
            best = float(d[j])
            arg = (float(r[i] * ca[j]), float(r[i] * sa[j]))
    return best, arg


def compass_refine(points, start, step=1.0, floor=1e-3):
    P = np.asarray(points, dtype=np.float64)

    def f(g):
        return float(np.min(np.hypot(P[:, 0] - g[0], P[:, 1] - g[1])))

    g = (float(start[0]), float(start[1]))
    cur = f(g)
    while step > floor:
        improved = False
        for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step),
                       (step, step), (step, -step), (-step, step), (-step, -step)):
            cand = (g[0] + dx, g[1] + dy)
            if math.hypot(cand[0], cand[1]) > OMEGA:
                continue
            v = f(cand)
            if v > cur + 1e-12:
                g, cur, improved = cand, v, True
        if not improved:
            step *= 0.5
    return cur, g


def audit_channel(points, r, ca, sa, lip):
    fs, arg = grid_max(points, r, ca, sa)
    refined, rarg = compass_refine(points, arg)
    return {
        "n_witnesses": len(points),
        "sampled_max_min_dist_m": round(fs, 4),
        "lipschitz_correction_m": round(lip, 4),
        "rigorous_margin_lb_m": round(R_COVER - (fs + lip), 4),
        "refined_max_min_dist_m": round(refined, 4),
        "refined_margin_m": round(R_COVER - refined, 4),
        "refined_argmax": [round(rarg[0], 3), round(rarg[1], 3)],
    }


def exact_max_min_dist(points, boundary_samples=200000):
    """Exact-ish maximum of f(g)=min_i |g-p_i| over the closed disc Omega.

    The maximum is attained either
      (a) at a Voronoi vertex strictly inside Omega (a circumcentre of three
          sites that are exactly the three nearest), or
      (b) on the boundary circle.
    (a) is computed exactly; (b) is scanned densely and refined locally, with a
    1-D Lipschitz remainder of ``2*pi*OMEGA/boundary_samples / 2``.
    """
    P = [(float(p[0]), float(p[1])) for p in points]
    n = len(P)

    def f(g):
        return min(math.hypot(g[0] - p[0], g[1] - p[1]) for p in P)

    best = 0.0
    where = None
    # (a) Voronoi vertices
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                ax, ay = P[i]
                bx, by = P[j]
                cx, cy = P[k]
                d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
                if abs(d) < 1e-12:
                    continue
                ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
                      + (cx * cx + cy * cy) * (ay - by)) / d
                uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
                      + (cx * cx + cy * cy) * (bx - ax)) / d
                if math.hypot(ux, uy) > OMEGA + 1e-9:
                    continue
                ri = math.hypot(ux - ax, uy - ay)
                # must be a genuine nearest-3 vertex
                if min(math.hypot(ux - p[0], uy - p[1]) for p in P) < ri - 1e-7:
                    continue
                if ri > best:
                    best, where = ri, (ux, uy)
    # (b) boundary circle
    for t in range(boundary_samples):
        a = 2.0 * math.pi * t / boundary_samples
        g = (OMEGA * math.cos(a), OMEGA * math.sin(a))
        v = f(g)
        if v > best:
            best, where = v, g
    # local refinement on the circle around the best boundary angle
    if where is not None and abs(math.hypot(*where) - OMEGA) < 1e-6:
        a0 = math.atan2(where[1], where[0])
        lo, hi = a0 - 2.0 * math.pi / boundary_samples, a0 + 2.0 * math.pi / boundary_samples
        for _ in range(60):
            m1 = lo + (hi - lo) / 3.0
            m2 = hi - (hi - lo) / 3.0
            v1 = f((OMEGA * math.cos(m1), OMEGA * math.sin(m1)))
            v2 = f((OMEGA * math.cos(m2), OMEGA * math.sin(m2)))
            if v1 < v2:
                lo = m1
            else:
                hi = m2
        a0 = 0.5 * (lo + hi)
        v = f((OMEGA * math.cos(a0), OMEGA * math.sin(a0)))
        if v > best:
            best, where = v, (OMEGA * math.cos(a0), OMEGA * math.sin(a0))
    return best, where, math.pi * OMEGA / boundary_samples


def main():
    variants = ["prod+q3ring_gate8", "prod+q3ring_safe", "production",
                "prod+q3ring_gated", "prod+q3ring_gate12"]
    r, ca, sa = make_grid()
    lip = lip_bound()
    rep = {"grid": {"radial_rings": RADIAL_RINGS,
                    "angular_spokes": ANGULAR_SPOKES,
                    "lipschitz_correction_m": round(lip, 4),
                    "r_cover_m": R_COVER},
           "variants": {}}
    for v in variants:
        d = RUNS / v
        if not d.is_dir():
            continue
        rows = []
        for case in sorted(d.iterdir()):
            cert = case / "certificate.json"
            if not cert.is_file():
                continue
            try:
                data = json.loads(cert.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for ch, rec in data.items():
                if rec.get("status") == "CLEARED":
                    continue
                pts = [(float(p[0]), float(p[1]))
                       for p in (rec.get("no_signal_points") or [])]
                if len(pts) < 3:
                    continue
                a = audit_channel(pts, r, ca, sa, lip)
                a.update({"case": case.name, "channel": ch,
                          "status": rec.get("status"),
                          "absent_basis": rec.get("absent_basis")})
                rows.append(a)
        if not rows:
            continue
        cert_rows = [x for x in rows if x["absent_basis"] == "certificate"]
        rep["variants"][v] = {
            "n_channels_audited": len(rows),
            "n_certified_by_certificate": len(cert_rows),
            "worst_refined_margin_m": round(min(x["refined_margin_m"]
                                                for x in rows), 4),
            "worst_refined_margin_over_certified_m": round(
                min((x["refined_margin_m"] for x in cert_rows), default=None)
                if cert_rows else None, 4) if cert_rows else None,
            "worst_rigorous_margin_lb_m": round(
                min(x["rigorous_margin_lb_m"] for x in rows), 4),
            "n_refined_below_5m": sum(1 for x in rows
                                      if x["refined_margin_m"] < 5.0),
            "n_violations_refined": sum(1 for x in rows
                                        if x["refined_margin_m"] < 0.0),
            "worst_rows": sorted(rows, key=lambda x: x["refined_margin_m"])[:6],
        }
        print("== %s ==" % v)
        print("  channels=%d certified=%d" % (len(rows), len(cert_rows)))
        print("  worst refined margin = %.3f m ; worst rigorous lb = %.3f m ; "
              "<5m: %d ; violations: %d" % (
                  rep["variants"][v]["worst_refined_margin_m"],
                  rep["variants"][v]["worst_rigorous_margin_lb_m"],
                  rep["variants"][v]["n_refined_below_5m"],
                  rep["variants"][v]["n_violations_refined"]))
        for x in rep["variants"][v]["worst_rows"][:4]:
            print("     %-14s ch=%-3s n=%-3d refined=%.3f m lb=%.3f m basis=%s"
                  % (x["case"], x["channel"], x["n_witnesses"],
                     x["refined_margin_m"], x["rigorous_margin_lb_m"],
                     x["absent_basis"]))
        print(flush=True)

    dest = ROOT / "tuning_runs" / "gate8_margin_audit.json"
    dest.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
