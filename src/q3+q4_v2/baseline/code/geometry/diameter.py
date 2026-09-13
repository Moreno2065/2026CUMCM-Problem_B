# -*- coding: utf-8 -*-
"""凸多边形直径：rotating calipers。

输出 (D, (i, j))：直径值与最远顶点对索引。
正确性由 tests 中与 O(n²) 暴力枚举对拍保证。
"""

import math

from .constants import EPS


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def diameter_bruteforce(poly):
    """O(n²) 暴力直径，用于对拍。"""
    best = 0.0
    pair = (0, 0)
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            d = _dist(poly[i], poly[j])
            if d > best:
                best = d
                pair = (i, j)
    return best, pair


def diameter(poly):
    """凸多边形（CCW）直径，rotating calipers，O(n)。

    返回 (D, (i, j))：直径与最远顶点对的索引。
    算法：对每条有向边 (p, p+1)，维护使其有向面积最大的对踵点 q；
    q 随 p 单调推进，所有对踵顶点对均被检查，直径必在其中取得。
    """
    n = len(poly)
    if n == 0:
        return 0.0, (-1, -1)
    if n == 1:
        return 0.0, (0, 0)
    if n == 2:
        return _dist(poly[0], poly[1]), (0, 1)

    best = 0.0
    pair = (0, 1)
    q = 1
    for p in range(n):
        pn = (p + 1) % n
        # q 单调推进：有向面积增大则继续
        guard = 0
        while guard < 2 * n:
            qn = (q + 1) % n
            if _cross(poly[p], poly[pn], poly[qn]) > \
               _cross(poly[p], poly[pn], poly[q]) + EPS:
                q = qn
                guard += 1
            else:
                break
        d1 = _dist(poly[p], poly[q])
        if d1 > best + EPS:
            best = d1
            pair = (p, q)
        d2 = _dist(poly[pn], poly[q])
        if d2 > best + EPS:
            best = d2
            pair = (pn, q)
    return best, pair


def diameter_value(poly):
    """只要直径数值的便捷接口。"""
    return diameter(poly)[0]
