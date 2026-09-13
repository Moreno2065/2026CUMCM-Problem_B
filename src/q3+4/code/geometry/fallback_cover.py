# -*- coding: utf-8 -*-
"""有限步清除兜底的可行域圆盘覆盖（评审第 1 点，FALLBACK_CLEAR）。

数学依据：
- 光学清除不受辐射朝向影响（题设）：clear 在距源 ≤ CLEAR_RADIUS=20 m
  处必成功，与该源是否定向、朝向如何无关。
- 可行域 P_c 是有界凸多边形（Ω 外切多边形经半平面/圆盘裁剪），面积有限，
  因此用半径 20 m 圆盘无缝覆盖 P_c 所需的圆盘数必为有限。
- 覆盖构造：三角格点圆盘覆盖。格点最近邻间距 a = √3·r 时，
  格点覆盖半径（平面任意点到最近格点的最大距离）恰为 a/√3 = r
  （三角格点 Voronoi 细胞为边长 a/√3 的正六边形，外接圆半径 a/√3）。
  取 r = CLEAR_RADIUS = 20 m，a = 20√3 ≈ 34.641 m，行距 h = a·√3/2 = 30 m。
- 因此：逐个在格点 /clear，若源在 P_c 内（观测一致性保证），必在有限步内
  命中；序列走完仍未命中 ⇒ 可行域与观测矛盾（异常工况，记 anomaly 并
  保守收尾）。

点数估计：N ≈ area(P_c) / (单格点有效覆盖面积)，单格点有效面积
= (√3/2)·a² = (√3/2)·1200 ≈ 1039.2 m²。首测后楔形扇区（半径 1500、
半角 1°）面积约 1500²·(2° in rad)/2 ≈ 3.93 万 m² ⇒ 最坏约 38 点。
"""

import math

from .constants import EPS, CLEAR_RADIUS
from .polygon import contains_point

# 三角格点参数（冻结）：间距 = √3·r，行距 = 3r/2
LATTICE_SPACING_FACTOR = math.sqrt(3.0)   # a = factor · r


def _point_polygon_distance(poly, p):
    """点 p 到凸多边形 poly 的距离（内部为 0）。"""
    if contains_point(poly, p, eps=-EPS):
        return 0.0
    best = float("inf")
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        abx, aby = b[0] - a[0], b[1] - a[1]
        apx, apy = p[0] - a[0], p[1] - a[1]
        L2 = abx * abx + aby * aby
        t = 0.0 if L2 <= EPS else max(0.0, min(1.0, (apx * abx + apy * aby) / L2))
        dx = apx - t * abx
        dy = apy - t * aby
        d = math.hypot(dx, dy)
        if d < best:
            best = d
    return best


def disk_lattice_cover(poly, radius=CLEAR_RADIUS):
    """生成覆盖凸多边形 poly 的半径 radius 圆盘格点序列（有限，确定性）。

    返回 list[(x, y)]：三角格点中所有圆盘与 poly 相交的格点
    （dist(格点, poly) ≤ radius）。对这些点逐个 /clear，poly 内任意
    目标必在某点的清除半径内。

    空多边形 / None 返回空 list。
    """
    if poly is None or len(poly) == 0:
        return []
    a = LATTICE_SPACING_FACTOR * radius          # 最近邻间距 20√3 ≈ 34.641
    h = a * math.sqrt(3.0) / 2.0                 # 行距 = 1.5·r = 30
    xs = [v[0] for v in poly]
    ys = [v[1] for v in poly]
    x0, x1 = min(xs) - radius, max(xs) + radius
    y0, y1 = min(ys) - radius, max(ys) + radius
    # 对齐：行锚定到 y0（确定性，与全局坐标无关）
    pts = []
    k0 = 0
    y = y0
    while y <= y1 + EPS:
        offset = (k0 % 2) * a / 2.0
        x = x0 + offset
        while x <= x1 + EPS:
            if _point_polygon_distance(poly, (x, y)) <= radius + EPS:
                pts.append((x, y))
            x += a
        y += h
        k0 += 1
    return pts


def order_greedy(points, start):
    """把覆盖点按贪心最近邻排序（从 start 出发），减少兜底巡回绕路。

    点数 ≤ 数十，O(n²) 足够。返回新 list，不改原序列。
    """
    remaining = list(points)
    out = []
    cur = (float(start[0]), float(start[1]))
    while remaining:
        i = min(range(len(remaining)),
                key=lambda i: math.hypot(remaining[i][0] - cur[0],
                                         remaining[i][1] - cur[1]))
        cur = remaining.pop(i)
        out.append(cur)
    return out


def cover_point_estimate(poly, radius=CLEAR_RADIUS):
    """兜底点数估计：area(P_c) / 单格点有效覆盖面积（记录用，非上界证明）。"""
    from .polygon import area
    if poly is None:
        return 0
    a = LATTICE_SPACING_FACTOR * radius
    cell = math.sqrt(3.0) / 2.0 * a * a          # ≈ 1039.2 m²（r=20）
    return int(math.ceil(area(poly) / cell))
