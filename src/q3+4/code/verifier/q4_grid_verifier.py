# -*- coding: utf-8 -*-
"""Q4 δ-稳健凸包证书独立验证器。

两个独立验证入口：
1. verify_q4_point(x, no_signal_points, delta, r_eff_min)：
   用"支持函数方向扫描"独立复核 B(x,δ) ⊆ conv(A_δ(x))：
   对足够多的单位方向 u，检查 x·u + δ ≤ max_{p∈A} p·u。
   （certificate.q4_certify_point 用边距精确条件；此处用对偶的
    支持函数扫描作为独立第二意见，另加逐见证点距离复核。）
2. verify_q4_grid(grid_points, radius, delta)：
   验证 ∪B(x_i, δ) 对 Ω 的采样覆盖（边界密集采样 + 内部网格）。
"""

import math

import numpy as np

from geometry.constants import (
    OMEGA_RADIUS,
    R_EFF_MIN,
    Q4_DELTA,
    EPS,
    Q4_LATTICE_SPACING,
    Q4_LATTICE_BOUND,
    Q4_LATTICE_COUNT,
    LATTICE_MATCH_TOL,
)
from geometry.polygon import convex_hull, area, contains_point
from geometry.certificate import COVER_TOL


def verify_q4_point(x, no_signal_points, delta=Q4_DELTA,
                    r_eff_min=R_EFF_MIN, n_directions=1440):
    """独立复核 δ-稳健凸包证书条件。

    返回 dict:
        ok             : bool
        witness_count  : 见证点数（‖p−x‖ ≤ r_eff_min − δ）
        support_margin : min_u (max_p p·u − x·u) − δ（≥0 表示覆盖）
        x_inside_hull  : bool
        hull_2d        : bool
    """
    r_witness = r_eff_min - delta
    xx = (float(x[0]), float(x[1]))
    A = [(float(p[0]), float(p[1])) for p in no_signal_points
         if math.hypot(p[0] - xx[0], p[1] - xx[1]) <= r_witness + EPS]
    if len(A) < 3:
        return {"ok": False, "witness_count": len(A),
                "support_margin": None, "x_inside_hull": False,
                "hull_2d": False}
    hull = convex_hull(A)
    hull_2d = len(hull) >= 3 and area(hull) > EPS
    if not hull_2d:
        return {"ok": False, "witness_count": len(A),
                "support_margin": None, "x_inside_hull": False,
                "hull_2d": False}
    inside = contains_point(hull, xx)
    # 支持函数扫描：margin = min_u (h_A(u) − x·u) − δ
    margin = float("inf")
    for k in range(n_directions):
        phi = 2.0 * math.pi * k / n_directions
        ux, uy = math.cos(phi), math.sin(phi)
        h = max(p[0] * ux + p[1] * uy for p in A)
        margin = min(margin, h - (xx[0] * ux + xx[1] * uy) - delta)
    ok = inside and margin >= -COVER_TOL
    return {"ok": ok, "witness_count": len(A),
            "support_margin": margin, "x_inside_hull": inside,
            "hull_2d": True}


def verify_q4_grid(grid_points, radius=OMEGA_RADIUS, delta=Q4_DELTA,
                   boundary_samples=7200, grid_step=25.0):
    """独立验证 ∪B(x_i, δ) ⊇ Ω（边界密集采样 + 内部网格采样）。

    返回 dict:
        ok              : bool
        max_min_dist    : 采样点到最近格点的最大距离
        worst_point     : 最差采样点
        margin          : δ − max_min_dist（确定性余量估计）
        uncovered_count : 未被覆盖采样点数
    """
    pts = [(float(p[0]), float(p[1])) for p in grid_points]
    R = float(radius)
    max_min = -1.0
    worst = None
    uncovered = 0

    def check(p):
        nonlocal max_min, worst, uncovered
        d = min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in pts) \
            if pts else float("inf")
        if d > max_min:
            max_min = d
            worst = (p[0], p[1])
        if d > delta + COVER_TOL:
            uncovered += 1

    for k in range(boundary_samples):
        phi = 2.0 * math.pi * k / boundary_samples
        check((R * math.cos(phi), R * math.sin(phi)))
    n = int(math.ceil(2.0 * R / grid_step)) + 1
    for i in range(n):
        for j in range(n):
            x = -R + i * grid_step
            y = -R + j * grid_step
            if math.hypot(x, y) <= R:
                check((x, y))
    return {"ok": uncovered == 0 and bool(pts),
            "max_min_dist": max_min,
            "worst_point": worst,
            "margin": delta - max_min,
            "uncovered_count": uncovered}


# ---------------------------------------------------------------------------
# Q4 三角格点 31 点证书独立验证器（评审第 3 点）
# ---------------------------------------------------------------------------

def _unit_triangles_from_points(pts, spacing, tol=1e-6):
    """从点集独立重建等边三角剖分：枚举两两距离均为 spacing 的三元组。

    不使用生成器的行列索引逻辑，也不假设点序；每个单元三角形都是
    边长 spacing 的等边三角形（面积 > 0，非退化）。
    """
    n = len(pts)
    tris = []
    s2 = spacing * spacing
    tol2 = 2.0 * spacing * tol + tol * tol  # |d²−s²| ≤ (s+tol)²−s²
    for i in range(n):
        xi, yi = pts[i]
        for j in range(i + 1, n):
            dx = pts[j][0] - xi
            dy = pts[j][1] - yi
            if abs(dx * dx + dy * dy - s2) > tol2:
                continue
            for k in range(j + 1, n):
                d1 = (pts[k][0] - xi) ** 2 + (pts[k][1] - yi) ** 2
                d2 = (pts[k][0] - pts[j][0]) ** 2 + \
                     (pts[k][1] - pts[j][1]) ** 2
                if abs(d1 - s2) <= tol2 and abs(d2 - s2) <= tol2:
                    tris.append((i, j, k))
    return tris


def verify_q4_lattice_certificate(points, spacing=Q4_LATTICE_SPACING,
                                  bound=Q4_LATTICE_BOUND,
                                  omega_radius=OMEGA_RADIUS,
                                  boundary_arc_step=1.0,
                                  interior_grid_step=10.0):
    """独立复核 31 点三角格点扫描证书（不复用生成器内部逻辑）。

    步骤：
      a. 由点集枚举两两距离均为 s 的三元组，重建单位三角剖分；
      b. 精确（采样意义上）验证 Ω 被覆盖：∂Ω 按 ≤ boundary_arc_step
         弧长采样 + 内部按 ≤ interior_grid_step 网格采样，每个采样点
         必须落在某个三顶点距它均 ≤ s 的剖分三角形内；
      c. 每个剖分三角形的三顶点都在给定点集内（按构造成立，显式复核）；
      d. 点集规模与界复核：恰好 Q4_LATTICE_COUNT 个点且均在 B(0,bound) 内。

    返回 dict:
        ok               : bool（全部检查通过）
        n_points         : 输入点数
        n_triangles      : 重建的单位三角形数
        max_vertex_dist  : 所有采样点"其最优包含三角形的最远顶点距离"最大值
        worst_point      : 达到该最大值的采样点
        uncovered_count  : 未被任何顶点距离 ≤ s 的三角形覆盖的采样点数
        vertices_in_set  : bool（c 项复核结果）
    """
    pts = [(float(p[0]), float(p[1])) for p in points]
    R = float(omega_radius)
    s = float(spacing)

    # d. 点集规模与界
    n_ok = len(pts) == Q4_LATTICE_COUNT
    in_bound = all(math.hypot(x, y) <= bound + LATTICE_MATCH_TOL
                   for x, y in pts)
    # 唯一性（无重复点）
    uniq = len(set((round(x, 6), round(y, 6)) for x, y in pts)) == len(pts)

    # a. 重建单位三角剖分
    tris = _unit_triangles_from_points(pts, s)

    # c. 三顶点都在给定点集内（按索引构造必然成立，显式复核坐标成员性）
    key = set((round(x, 6), round(y, 6)) for x, y in pts)
    vertices_in_set = all(
        (round(pts[i][0], 6), round(pts[i][1], 6)) in key and
        (round(pts[j][0], 6), round(pts[j][1], 6)) in key and
        (round(pts[k][0], 6), round(pts[k][1], 6)) in key
        for i, j, k in tris)

    # b. 采样：∂Ω ≤1m 弧长 + 内部 ≤10m 网格
    n_b = max(1, int(math.ceil(2.0 * math.pi * R / boundary_arc_step)))
    boundary = np.stack(
        [R * np.cos(2.0 * math.pi * np.arange(n_b) / n_b),
         R * np.sin(2.0 * math.pi * np.arange(n_b) / n_b)], axis=1)
    g = np.arange(-R, R + 0.5 * interior_grid_step, interior_grid_step)
    gx, gy = np.meshgrid(g, g)
    grid = np.stack([gx.ravel(), gy.ravel()], axis=1)
    grid = grid[np.hypot(grid[:, 0], grid[:, 1]) <= R]
    samples = np.vstack([boundary, grid])

    P = np.asarray(pts, dtype=float)
    best = np.full(len(samples), np.inf)
    bary_tol = 1e-9
    for i, j, k in tris:
        a, b_, c = P[i], P[j], P[k]
        v0 = c - a
        v1 = b_ - a
        v2 = samples - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        u = (v2[:, 0] * v1[1] - v1[0] * v2[:, 1]) / den
        v = (v0[0] * v2[:, 1] - v2[:, 0] * v0[1]) / den
        inside = (u >= -bary_tol) & (v >= -bary_tol) & \
                 (u + v <= 1.0 + bary_tol)
        if not inside.any():
            continue
        da = np.hypot(v2[:, 0], v2[:, 1])
        db = np.hypot(samples[:, 0] - b_[0], samples[:, 1] - b_[1])
        dc = np.hypot(samples[:, 0] - c[0], samples[:, 1] - c[1])
        dmax = np.maximum(da, np.maximum(db, dc))
        best = np.minimum(best, np.where(inside, dmax, np.inf))

    finite = np.isfinite(best)
    uncovered = int(np.count_nonzero(~finite)) + int(
        np.count_nonzero(finite & (best > s + COVER_TOL)))
    idx = int(np.argmax(np.where(np.isfinite(best), best, -np.inf)))
    max_vertex_dist = float(best[idx])
    ok = (n_ok and in_bound and uniq and vertices_in_set and tris
          and uncovered == 0 and max_vertex_dist <= s + COVER_TOL)
    return {"ok": bool(ok),
            "n_points": len(pts),
            "n_triangles": len(tris),
            "max_vertex_dist": max_vertex_dist,
            "worst_point": (float(samples[idx, 0]), float(samples[idx, 1])),
            "uncovered_count": uncovered,
            "vertices_in_set": bool(vertices_in_set)}
