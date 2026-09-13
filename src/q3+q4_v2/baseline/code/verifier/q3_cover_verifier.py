# -*- coding: utf-8 -*-
"""Q3 覆盖证书独立验证器：验证 Ω ⊆ ∪ B(S_i, 1000)。

独立验证路径（不复用 certificate.q3_certified 的内部实现）：
1. ∂Ω 密集角采样：边界上每一点到最近圆心距离 ≤ 1000 + tol；
2. 内部网格采样：网格点步长可调，检查所有 Ω 内网格点；
3. 两两圆交点（Ω 内者）抽查。

采样型验证器的定位是"验收第二意见"：主判定是
geometry.certificate.q3_certified 的精确 arrangement 检查；
本验证器用高密度确定性采样独立复核，发现任何未覆盖点即判定失败。
"""

import math

from geometry.constants import OMEGA_RADIUS, R_EFF_MIN
from geometry.certificate import circle_circle_intersections, COVER_TOL


def _min_dist_to_centers(p, centers):
    if not centers:
        return float("inf")
    return min(math.hypot(p[0] - S[0], p[1] - S[1]) for S in centers)


def verify_q3_cover(no_signal_points, omega_radius=OMEGA_RADIUS,
                    cover_r=R_EFF_MIN, boundary_samples=7200,
                    grid_step=25.0):
    """独立验证 Ω ⊆ ∪ B(S_i, cover_r)。

    返回 dict:
        ok              : bool
        max_min_dist    : 采样点到最近圆心距离的最大值
        worst_point     : 最差采样点
        uncovered_count : 未被覆盖的采样点数量
    """
    centers = [(float(p[0]), float(p[1])) for p in no_signal_points]
    R = float(omega_radius)
    r = float(cover_r)
    max_min = -1.0
    worst = None
    uncovered = 0

    def check(p):
        nonlocal max_min, worst, uncovered
        d = _min_dist_to_centers(p, centers)
        if d > max_min:
            max_min = d
            worst = (p[0], p[1])
        if d > r + COVER_TOL:
            uncovered += 1

    # 1. 边界密集采样
    for k in range(boundary_samples):
        phi = 2.0 * math.pi * k / boundary_samples
        check((R * math.cos(phi), R * math.sin(phi)))

    # 2. 内部网格采样
    n = int(math.ceil(2.0 * R / grid_step)) + 1
    for i in range(n):
        for j in range(n):
            x = -R + i * grid_step
            y = -R + j * grid_step
            if math.hypot(x, y) <= R:
                check((x, y))

    # 3. 两两圆交点抽查（Ω 内者）
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            for p in circle_circle_intersections(centers[i], r,
                                                 centers[j], r):
                if math.hypot(p[0], p[1]) <= R + COVER_TOL:
                    check(p)

    return {"ok": uncovered == 0 and bool(centers),
            "max_min_dist": max_min,
            "worst_point": worst,
            "uncovered_count": uncovered}
