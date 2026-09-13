# -*- coding: utf-8 -*-
"""MEC 判据独立验证器。

verify_mec_covers(polygon, center, radius, eps)：所有顶点距 center ≤ R + ε。
这是 MEC 模块的独立验收路径（narrative 第 12 节：
所有关键结论具有独立验证路径）。
"""

import math

from geometry.constants import MEC_ACCEPT_EPS, EPS
from geometry.polygon import contains_point


def verify_mec_covers(polygon, center, radius, eps=MEC_ACCEPT_EPS):
    """验证多边形所有顶点都被 B(center, radius) 覆盖（容差 eps）。

    返回 dict:
        ok        : bool
        max_dist  : 顶点到 center 的最大距离
        violations: 超限顶点列表 [(index, point, dist), ...]
    """
    if polygon is None or len(polygon) == 0:
        return {"ok": False, "max_dist": None,
                "violations": [("empty", None, None)]}
    cx, cy = float(center[0]), float(center[1])
    max_d = -1.0
    violations = []
    for i, p in enumerate(polygon):
        d = math.hypot(p[0] - cx, p[1] - cy)
        if d > max_d:
            max_d = d
        if d > radius + eps:
            violations.append((i, p, d))
    return {"ok": not violations, "max_dist": max_d,
            "violations": violations}


def verify_fallback_cover(region, points, radius, grid_step=5.0):
    """FALLBACK_CLEAR 收尾的独立复核（采样第二意见）。

    验证 conv(region) ⊆ ∪ B(p_i, radius)：
      1. 全部顶点距某清除点 ≤ radius + 1e-6；
      2. region 包围盒内 grid_step 网格采样：落在 region 内的采样点
         距某清除点 ≤ radius + 1e-6。
    精确性由 disk_lattice_cover 的三角格点构造保证（覆盖半径恰为
    radius，采样仅作独立复核）。

    返回 dict: {"ok", "n_points", "n_samples", "uncovered"}
    """
    if not points:
        return {"ok": False, "n_points": 0, "n_samples": 0,
                "uncovered": [("no_points", None)]}
    tol = 1e-6
    uncovered = []

    def covered(p):
        return any(math.hypot(p[0] - q[0], p[1] - q[1]) <= radius + tol
                   for q in points)

    for i, v in enumerate(region):
        if not covered(v):
            uncovered.append(("vertex", i, v))
    xs = [v[0] for v in region]
    ys = [v[1] for v in region]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    n_samples = 0
    nx = max(1, int(math.ceil((x1 - x0) / grid_step)))
    ny = max(1, int(math.ceil((y1 - y0) / grid_step)))
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = (x0 + i * grid_step, y0 + j * grid_step)
            if not contains_point(region, p, eps=-EPS):
                continue
            n_samples += 1
            if not covered(p):
                uncovered.append(("sample", None, p))
    return {"ok": not uncovered, "n_points": len(points),
            "n_samples": n_samples, "uncovered": uncovered[:10]}
