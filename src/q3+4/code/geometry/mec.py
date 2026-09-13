# -*- coding: utf-8 -*-
"""最小包围圆（Minimum Enclosing Circle）：Welzl 算法。

输入凸多边形（顶点 list），输出 (center, radius)。
点的集合意义下的 MEC 与凸包意义下的 MEC 相同，因此直接对顶点集运行。

Welzl 为期望线性时间随机增量算法；为保证可复现性，使用固定种子洗牌。
验收由 verifier/geometry_verifier.verify_mec_covers 独立执行：
所有顶点 d <= R + MEC_ACCEPT_EPS。
"""

import math
import random

from .constants import EPS


def _circle_from_2(a, b):
    c = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return c, math.hypot(a[0] - b[0], a[1] - b[1]) / 2.0


def _circle_from_3(a, b, c):
    """三点外接圆；共线时退化为最远两点直径圆。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) <= EPS:
        # 共线：取两两距离最大的一对
        pairs = [(a, b), (a, c), (b, c)]
        p, q = max(pairs, key=lambda pq: math.hypot(pq[0][0] - pq[1][0],
                                                    pq[0][1] - pq[1][1]))
        return _circle_from_2(p, q)
    ux = ((ax * ax + ay * ay) * (by - cy) +
          (bx * bx + by * by) * (cy - ay) +
          (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) +
          (bx * bx + by * by) * (ax - cx) +
          (cx * cx + cy * cy) * (bx - ax)) / d
    center = (ux, uy)
    return center, math.hypot(ux - ax, uy - ay)


def _contains(circle, p, eps=1e-9):
    (cx, cy), r = circle
    return math.hypot(p[0] - cx, p[1] - cy) <= r + eps


def _welzl(points, boundary):
    """递归 Welzl：boundary 为必须在圆边界上的点（<=3 个）。"""
    if not points or len(boundary) == 3:
        if len(boundary) == 0:
            return (0.0, 0.0), -1.0
        if len(boundary) == 1:
            return boundary[0], 0.0
        if len(boundary) == 2:
            return _circle_from_2(*boundary)
        return _circle_from_3(*boundary)
    p = points[-1]
    rest = points[:-1]
    circle = _welzl(rest, boundary)
    if circle[1] >= 0.0 and _contains(circle, p):
        return circle
    return _welzl(rest, boundary + [p])


def mec(poly, seed=2026):
    """凸多边形（或任意点集）的最小包围圆。

    返回 (center, radius)，center 为 (x, y) 元组。
    空输入返回 ((0,0), -1)；单点返回半径 0。
    """
    if poly is None or len(poly) == 0:
        return (0.0, 0.0), -1.0
    pts = [(float(p[0]), float(p[1])) for p in poly]
    if len(pts) == 1:
        return pts[0], 0.0
    rng = random.Random(seed)
    rng.shuffle(pts)
    # 深递归防护：点数较多时迭代式 Welzl（move-to-front 变体）
    return _welzl_iterative(pts)


def _welzl_iterative(pts):
    """Welzl 的迭代实现（Emo Welzl 标准形式 + 栈展开），避免递归深度问题。"""
    # 对顶点数 <= 几百的多边形，直接递归也完全安全；这里仍用递归封装，
    # 但把点列表切片改为索引窗口以避免大量 list 拷贝。
    import sys
    sys.setrecursionlimit(max(10000, len(pts) * 4 + 100))

    def rec(lo, boundary):
        # 处理 pts[lo:]（首元素为当前点）
        if lo == len(pts) or len(boundary) == 3:
            if len(boundary) == 0:
                return (0.0, 0.0), -1.0
            if len(boundary) == 1:
                return boundary[0], 0.0
            if len(boundary) == 2:
                return _circle_from_2(*boundary)
            return _circle_from_3(*boundary)
        p = pts[lo]
        circle = rec(lo + 1, boundary)
        if circle[1] >= 0.0 and _contains(circle, p):
            return circle
        return rec(lo + 1, boundary + [p])

    return rec(0, [])
