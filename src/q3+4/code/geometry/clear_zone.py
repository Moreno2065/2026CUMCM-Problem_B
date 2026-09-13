# -*- coding: utf-8 -*-
"""清除区 Z_c（评审第 5 点）：Z_c = ∩_{g∈P_c} B(g, 20) = ∩_{顶点 v} B(v, 20)。

圆盘是凸集，因此 P = conv(顶点) ⊆ B(x, 20) ⟺ 全部顶点 ∈ B(x, 20)，
交集只需对顶点取。Z_c 非空 ⟺ R_MEC ≤ 20（MEC 圆心即见证点）。

清除点不必固定为 MEC 圆心：Z_c 内任何位置都能保证清除，
closest_clear_point 在 Z_c 内找距 reference 最近的点（凸集上的投影）。

精确性说明（最近点投影的闭式候选 + Dykstra 兜底）：
  reference 在 Z_c 外时，最优点 x* 必在 ∂Z_c 上。KKT 条件给出活跃约束
  子集：二维中非退化情形为 1 个或 2 个活跃圆盘——
    * 1 个活跃圆盘 B(v, r)：x* 是 reference 在该圆边界上的径向投影
      v + r·(reference − v)/‖reference − v‖；
    * 2 个活跃圆盘：x* 是两圆边界交点。
  因此枚举 {各圆径向投影} ∪ {所有圆-圆交点}，取可行且距 reference
  最近者即为精确解。候选为空（数值退化）时退到 Dykstra 交替投影，
  它收敛到凸集交上的精确投影点。
"""

import math

from .constants import EPS, CLEAR_RADIUS, CLEAR_ZONE_EPS
from .certificate import circle_circle_intersections
from .mec import mec


def clear_zone_nonempty(vertices, radius=CLEAR_RADIUS):
    """判定 Z_c = ∩ B(v, radius) 非空 ⟺ R_MEC(顶点) ≤ radius。"""
    if vertices is None or len(vertices) == 0:
        return False
    _, r = mec(vertices)
    return r <= radius + CLEAR_ZONE_EPS


def _feasible(p, verts, radius, tol):
    return all(math.hypot(p[0] - v[0], p[1] - v[1]) <= radius + tol
               for v in verts)


def _project_disk(p, c, radius):
    """点 p 到闭圆盘 B(c, radius) 的投影。"""
    dx = p[0] - c[0]
    dy = p[1] - c[1]
    d = math.hypot(dx, dy)
    if d <= radius:
        return p
    return (c[0] + radius * dx / d, c[1] + radius * dy / d)


def _dykstra_projection(verts, radius, reference, max_iter=20000,
                        tol=1e-13):
    """Dykstra 交替投影：收敛到 reference 在 ∩B(v, radius) 上的精确投影。"""
    x = (reference[0], reference[1])
    shifts = [(0.0, 0.0)] * len(verts)
    for _ in range(max_iter):
        x_old = x
        for i, c in enumerate(verts):
            px, py = shifts[i]
            y = _project_disk((x[0] + px, x[1] + py), c, radius)
            shifts[i] = (x[0] + px - y[0], x[1] + py - y[1])
            x = y
        if math.hypot(x[0] - x_old[0], x[1] - x_old[1]) <= tol:
            break
    return x


def closest_clear_point(vertices, reference, radius=CLEAR_RADIUS):
    """在 Z_c 内找距 reference 最近的点（凸集 ∩圆盘 上的最近点投影）。

    参数：
        vertices  : 可行域凸多边形顶点（或任意点集）list[(x, y)]
        reference : 参考点（如当前位置或下一路线点）
        radius    : 清除半径（默认 20 m）

    返回 (x*, y*)；reference ∈ Z_c 时原样返回 reference。
    Z_c 为空（R_MEC > radius）或顶点为空时抛 ValueError。

    退化情形：单点（Z_c = 圆盘）、两点（等半径两圆交）、
    R_MEC 恰 = radius（Z_c 退化为 MEC 圆心一点）均正确。
    """
    if vertices is None or len(vertices) == 0:
        raise ValueError("empty vertex set")
    verts = list(dict.fromkeys(
        (float(v[0]), float(v[1])) for v in vertices))
    ref = (float(reference[0]), float(reference[1]))
    center, r_mec = mec(verts)
    if r_mec > radius + CLEAR_ZONE_EPS:
        raise ValueError("clear zone is empty: R_MEC=%.6f > %.6f"
                         % (r_mec, radius))

    # reference 已在 Z_c 内：最近点即自身
    if _feasible(ref, verts, radius, EPS):
        return ref

    # 闭式候选：径向投影 + 圆-圆交点 + MEC 圆心（退化兜底）
    candidates = [center]
    for v in verts:
        d = math.hypot(ref[0] - v[0], ref[1] - v[1])
        if d > EPS:
            candidates.append((v[0] + radius * (ref[0] - v[0]) / d,
                               v[1] + radius * (ref[1] - v[1]) / d))
    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            candidates.extend(
                circle_circle_intersections(verts[i], radius,
                                            verts[j], radius))

    best = None
    best_d = float("inf")
    for p in candidates:
        if not _feasible(p, verts, radius, CLEAR_ZONE_EPS):
            continue
        d = math.hypot(p[0] - ref[0], p[1] - ref[1])
        if d < best_d:
            best_d = d
            best = p

    if best is None:
        # 数值退化兜底：Dykstra 投影（从 reference 出发直接求交投影）
        best = _dykstra_projection(verts, radius, ref)

    # 数值清洁：若结果微幅违反某约束（≤ CLEAR_ZONE_EPS），向该圆盘
    # 投影回边界，保证返回值在 1e-9 量级上可行。
    for _ in range(3):
        fixed = best
        for v in verts:
            d = math.hypot(best[0] - v[0], best[1] - v[1])
            if d > radius + EPS:
                best = _project_disk(best, v, radius)
        if best == fixed:
            break
    return best
