# -*- coding: utf-8 -*-
"""清除区 Z_c = ∩ B(v, 20) 测试（评审第 5 点）。

覆盖：非空判定（MEC ≤ 20 充要）、reference 在区内返回自身、
区外结果必在边界上、退化情形（单点 / 两点 / R_MEC 恰=20 退化为
MEC 圆心）、随机凸多边形与 0.1 m 网格暴力搜索对拍（差距 ≤0.2 m）。
"""

import math
import random

import numpy as np
import pytest

from geometry.constants import CLEAR_RADIUS, CLEAR_ZONE_EPS
from geometry.clear_zone import clear_zone_nonempty, closest_clear_point
from geometry.mec import mec
from geometry.polygon import convex_hull

R = CLEAR_RADIUS  # 20


def _max_vdist(p, verts):
    return max(math.hypot(p[0] - v[0], p[1] - v[1]) for v in verts)


# ---------------------------------------------------------------------------
# 非空判定
# ---------------------------------------------------------------------------

def test_nonempty_basic():
    # 挤在小范围内的点：MEC ≤ 20 ⇒ Z_c 非空
    assert clear_zone_nonempty([(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)])
    # 跨度 60 m 的两点：MEC = 30 > 20 ⇒ Z_c 为空
    assert not clear_zone_nonempty([(0.0, 0.0), (60.0, 0.0)])
    # 单点：MEC = 0 ⇒ 非空
    assert clear_zone_nonempty([(3.0, 4.0)])
    # 空顶点集
    assert not clear_zone_nonempty([])


def test_nonempty_boundary_r_mec_eq_20():
    """R_MEC 恰 = 20：Z_c 恰含 MEC 圆心一点，判定为非空。"""
    tri = [(R * math.cos(a), R * math.sin(a))
           for a in (0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0)]
    _, r_mec = mec(tri)
    assert abs(r_mec - R) < 1e-9
    assert clear_zone_nonempty(tri)


# ---------------------------------------------------------------------------
# 最近清除点：区内 / 边界 / 退化
# ---------------------------------------------------------------------------

def test_reference_inside_returns_itself():
    verts = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    ref = (5.0, 4.0)  # 距三顶点均 < 20
    assert closest_clear_point(verts, ref) == ref


def test_single_vertex():
    # reference 在盘内：返回自身
    assert closest_clear_point([(3.0, 4.0)], (5.0, 4.0)) == (5.0, 4.0)
    # reference 在盘外：圆边界径向投影
    p = closest_clear_point([(0.0, 0.0)], (50.0, 0.0))
    assert abs(p[0] - R) < 1e-9 and abs(p[1]) < 1e-9
    # 任意方向
    p = closest_clear_point([(0.0, 0.0)], (30.0, 40.0))
    assert abs(math.hypot(*p) - R) < 1e-9
    assert abs(p[0] - 12.0) < 1e-9 and abs(p[1] - 16.0) < 1e-9


def test_two_vertices():
    """两等半径圆盘交：最近点为圆-圆交点。"""
    p = closest_clear_point([(-10.0, 0.0), (10.0, 0.0)], (0.0, 100.0))
    assert abs(p[0]) < 1e-9
    assert abs(p[1] - math.sqrt(R * R - 100.0)) < 1e-9
    assert abs(_max_vdist(p, [(-10.0, 0.0), (10.0, 0.0)]) - R) < 1e-9


def test_r_mec_eq_20_degenerate_singleton():
    """R_MEC = 20：Z_c 退化为 MEC 圆心，任意 reference 都返回它。"""
    tri = [(R * math.cos(a), R * math.sin(a))
           for a in (0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0)]
    for ref in [(50.0, 0.0), (-100.0, -100.0), (0.0, 33.3)]:
        p = closest_clear_point(tri, ref)
        assert math.hypot(*p) < 1e-6, p


def test_empty_zone_raises():
    with pytest.raises(ValueError):
        closest_clear_point([(0.0, 0.0), (60.0, 0.0)], (10.0, 0.0))
    with pytest.raises(ValueError):
        closest_clear_point([], (0.0, 0.0))


def test_result_on_boundary_when_reference_outside():
    """Z_c 非空但 reference 在区外：结果必在 ∂Z_c 上（某约束活跃）。"""
    rng = random.Random(5)
    for _ in range(20):
        c = (rng.uniform(-30, 30), rng.uniform(-30, 30))
        verts = [(c[0] + rng.uniform(-15, 15), c[1] + rng.uniform(-15, 15))
                 for _ in range(rng.randint(3, 7))]
        ref = (c[0] + rng.uniform(30, 100), c[1] + rng.uniform(-100, 100))
        if _max_vdist(ref, verts) <= R:
            continue  # 恰好在区内，跳过
        p = closest_clear_point(verts, ref)
        assert _max_vdist(p, verts) <= R + 1e-6
        assert _max_vdist(p, verts) >= R - 1e-3  # 活跃约束 ⇒ 在边界上


# ---------------------------------------------------------------------------
# 与 0.1 m 网格暴力搜索对拍
# ---------------------------------------------------------------------------

def _brute_force_closest(verts, ref, step=0.1):
    """在覆盖 Z_c 的包围盒上做 step 网格暴力搜索最近可行点。"""
    V = np.asarray(verts, dtype=float)
    lo = V.min(axis=0) - R - step
    hi = V.max(axis=0) + R + step
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0], step),
                         np.arange(lo[1], hi[1], step))
    G = np.stack([gx.ravel(), gy.ravel()], axis=1)
    feas = np.all(
        np.hypot(G[:, 0:1] - V[:, 0], G[:, 1:2] - V[:, 1]) <= R, axis=1)
    if not feas.any():
        return None
    d = np.hypot(G[:, 0] - ref[0], G[:, 1] - ref[1])
    d[~feas] = np.inf
    idx = int(np.argmin(d))
    return float(d[idx]), (float(G[idx, 0]), float(G[idx, 1]))


def test_random_polygons_vs_brute_force_grid():
    """随机凸多边形 + 随机 reference：与 0.1 m 网格暴力解差距 ≤ 0.2 m。"""
    rng = random.Random(2026)
    compared = 0
    for _ in range(30):
        c = (rng.uniform(-40, 40), rng.uniform(-40, 40))
        raw = [(c[0] + rng.uniform(-17, 17), c[1] + rng.uniform(-17, 17))
               for _ in range(rng.randint(3, 8))]
        verts = convex_hull(raw)
        if len(verts) < 3:
            continue
        if not clear_zone_nonempty(verts):
            continue
        ref = (c[0] + rng.uniform(-120, 120), c[1] + rng.uniform(-120, 120))
        brute = _brute_force_closest(verts, ref)
        assert brute is not None
        grid_d, _ = brute
        p = closest_clear_point(verts, ref)
        # 可行性
        assert _max_vdist(p, verts) <= R + CLEAR_ZONE_EPS
        d_ours = math.hypot(p[0] - ref[0], p[1] - ref[1])
        # 网格量化误差 ~step/√2 ≈ 0.071 m；判据 0.2 m
        assert d_ours <= grid_d + 0.2, \
            "ours=%.4f brute=%.4f" % (d_ours, grid_d)
        compared += 1
    assert compared >= 15


def test_kkt_style_local_optimality():
    """KKT 思想复核：结果点附近任意可行小扰动不得更优（局部最优性）。

    对结果 x* 做 ±0.05 m 细粒度局部搜索：所有仍可行的邻点距
    reference 不更近（容差 1e-6）。
    """
    rng = random.Random(11)
    for _ in range(15):
        c = (rng.uniform(-30, 30), rng.uniform(-30, 30))
        verts = [(c[0] + rng.uniform(-15, 15), c[1] + rng.uniform(-15, 15))
                 for _ in range(rng.randint(3, 7))]
        if not clear_zone_nonempty(verts):
            continue
        ref = (c[0] + rng.uniform(25, 90), c[1] + rng.uniform(-90, 90))
        if _max_vdist(ref, verts) <= R:
            continue
        p = closest_clear_point(verts, ref)
        d_star = math.hypot(p[0] - ref[0], p[1] - ref[1])
        for k in range(16):
            ang = 2.0 * math.pi * k / 16
            q = (p[0] + 0.05 * math.cos(ang), p[1] + 0.05 * math.sin(ang))
            if _max_vdist(q, verts) <= R:
                assert math.hypot(q[0] - ref[0], q[1] - ref[1]) \
                    >= d_star - 1e-6
