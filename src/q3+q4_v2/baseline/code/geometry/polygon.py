# -*- coding: utf-8 -*-
"""凸多边形基础：外切圆盘近似、半平面裁剪（Sutherland–Hodgman）、面积、点包含。

约定：
- 多边形用顶点 list[(x, y)] 表示，逆时针（CCW）顺序，不重复首尾点。
- 圆盘一律用**外切**正多边形近似：近似多边形包含真实圆盘，
  因此交集结果是真实可行域的超集（对清除保证保守安全）。
- 空交集一律返回 None（而不是空 list），调用方需显式处理。
"""

import math

import numpy as np

from .constants import EPS, EPS_AREA, DISK_POLYGON_SIDES


def circumscribed_polygon(center, radius, n=DISK_POLYGON_SIDES, phase=0.0):
    """返回圆盘 B(center, radius) 的外切正 n 边形顶点（CCW）。

    顶点位于半径 radius/cos(π/n) 处，边中点恰好与圆相切，
    因此多边形严格包含圆盘。
    """
    if radius <= 0:
        raise ValueError("radius must be positive")
    rv = radius / math.cos(math.pi / n)
    cx, cy = float(center[0]), float(center[1])
    return [
        (cx + rv * math.cos(phase + 2.0 * math.pi * k / n),
         cy + rv * math.sin(phase + 2.0 * math.pi * k / n))
        for k in range(n)
    ]


def omega_polygon(n=DISK_POLYGON_SIDES):
    """目标区域 Ω = B(0, 1800) 的外切正多边形（初始可行域）。"""
    from .constants import OMEGA_RADIUS
    return circumscribed_polygon((0.0, 0.0), OMEGA_RADIUS, n)


def _cross(o, a, b):
    """(a-o) x (b-o) 的 z 分量。"""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def area(poly):
    """多边形有向面积（CCW 为正）的绝对值。"""
    if poly is None or len(poly) < 3:
        return 0.0
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def clip_halfplane(poly, point, normal, keep_negative=True):
    """Sutherland–Hodgman 半平面裁剪（要求输入为凸多边形，CCW）。

    保留半平面：normal·(x - point) <= 0 （keep_negative=True，默认），
    或 normal·(x - point) >= 0 （keep_negative=False）。

    返回新的凸多边形顶点 list（CCW）；交集为空返回 None。
    边界上的点被保留（闭半平面），保证 ±1° 楔形边界包含在可行域内。
    """
    if poly is None or len(poly) == 0:
        return None
    nx, ny = float(normal[0]), float(normal[1])
    px, py = float(point[0]), float(point[1])
    sign = 1.0 if keep_negative else -1.0

    def value(v):
        return sign * (nx * (v[0] - px) + ny * (v[1] - py))

    out = []
    n = len(poly)
    for i in range(n):
        cur = poly[i]
        nxt = poly[(i + 1) % n]
        vc, vn = value(cur), value(nxt)
        cur_in = vc <= EPS
        nxt_in = vn <= EPS
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:
            # 边与半平面边界相交，求线性插值交点
            t = vc / (vc - vn)
            out.append((cur[0] + t * (nxt[0] - cur[0]),
                        cur[1] + t * (nxt[1] - cur[1])))
    # 去除相邻重复点
    cleaned = []
    for v in out:
        if not cleaned or (abs(v[0] - cleaned[-1][0]) > EPS or
                           abs(v[1] - cleaned[-1][1]) > EPS):
            cleaned.append(v)
    if len(cleaned) >= 2:
        a, b = cleaned[0], cleaned[-1]
        if abs(a[0] - b[0]) <= EPS and abs(a[1] - b[1]) <= EPS:
            cleaned.pop()
    if len(cleaned) < 3 or area(cleaned) <= EPS_AREA:
        return None
    return cleaned


def clip_circle(poly, center, radius, n=DISK_POLYGON_SIDES):
    """凸多边形与圆盘 B(center, radius) 的交集（圆盘用外切 n 边形近似）。

    由于外切多边形 ⊇ 圆盘，结果是 P ∩ B 的保守超集。
    交集为空返回 None。
    """
    if poly is None:
        return None
    disk_poly = circumscribed_polygon(center, radius, n)
    out = poly
    m = len(disk_poly)
    for i in range(m):
        a = disk_poly[i]
        b = disk_poly[(i + 1) % m]
        # 边 a->b 的内法向（指向圆心一侧，多边形为 CCW 时内侧在左边）
        ex, ey = b[0] - a[0], b[1] - a[1]
        normal = (-ey, ex)  # 左法向 = 内侧
        # 保留 normal·(x - a) >= 0 的一侧
        out = clip_halfplane(out, a, normal, keep_negative=False)
        if out is None:
            return None
    return out


def contains_point(poly, p, eps=EPS):
    """点 p 是否在凸多边形（CCW，闭区域）内。"""
    if poly is None or len(poly) < 3:
        return False
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        if _cross(a, b, p) < -eps:
            return False
    return True


def vertices_array(poly):
    """转为 numpy (n,2) 数组，便于向量化计算。"""
    return np.asarray(poly, dtype=float)


def convex_hull(points):
    """Andrew monotone chain 凸包，返回 CCW 顶点 list（不含重复首尾点）。

    共线中间点被剔除。点数 < 3 或共线时返回去重后的点（面积可能为 0），
    调用方负责检查是否为二维凸包。
    """
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 2:
        return pts

    def build(seq):
        hull = []
        for p in seq:
            while len(hull) >= 2 and _cross(hull[-2], hull[-1], p) <= EPS:
                hull.pop()
            hull.append(p)
        return hull

    lower = build(pts)
    upper = build(list(reversed(pts)))
    return lower[:-1] + upper[:-1]


def edge_distance(poly, p):
    """点 p 到凸多边形各边（直线）距离的最小值；p 在多边形外时返回负值。

    用于 Q4 证书：B(x,δ) ⊆ conv(A) ⟺ x 在 conv 内且每条边到 x 的距离 ≥ δ。
    """
    if poly is None or len(poly) < 3:
        return float("-inf")
    if not contains_point(poly, p):
        return -1.0
    best = float("inf")
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length = math.hypot(ex, ey)
        if length <= EPS:
            continue
        # CCW 多边形内侧在边 a->b 左边，距离 = cross(e, p-a)/|e|
        d = (ex * (p[1] - a[1]) - ey * (p[0] - a[0])) / length
        best = min(best, d)
    return best
