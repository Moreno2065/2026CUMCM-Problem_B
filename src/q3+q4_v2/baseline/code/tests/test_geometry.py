# -*- coding: utf-8 -*-
"""几何模块测试：楔形 wrap/平行/空集、多边形裁剪、MEC 已知答案、
rotating calipers 对拍、MEC vs 直径反例、对抗误差场景。"""

import math
import random

from geometry.constants import EPS, MEC_ACCEPT_EPS
from geometry.polygon import (
    area,
    circumscribed_polygon,
    clip_circle,
    clip_halfplane,
    contains_point,
    convex_hull,
    omega_polygon,
)
from geometry.wedge import bearing_of, bearing_range, in_wedge, wedge_intersect
from geometry.mec import mec
from geometry.diameter import diameter, diameter_bruteforce
from geometry.nbv import nbv_score, worst_case_diameter
from verifier.geometry_verifier import verify_mec_covers


# ---------------------------------------------------------------------------
# 多边形
# ---------------------------------------------------------------------------

def test_circumscribed_polygon_contains_circle():
    """外切多边形必须包含圆盘：边界采样点全部在多边形内。"""
    poly = circumscribed_polygon((0.0, 0.0), 1800.0, 128)
    for k in range(720):
        phi = 2.0 * math.pi * k / 720
        p = (1800.0 * math.cos(phi), 1800.0 * math.sin(phi))
        assert contains_point(poly, p), "boundary point %.3f leaked" % phi
    # 顶点在圆外（外切而非内接）
    for v in poly:
        assert math.hypot(v[0], v[1]) > 1800.0


def test_clip_halfplane_square():
    """正方形 [-1,1]^2 裁掉 x>0 的半平面。"""
    sq = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    out = clip_halfplane(sq, (0.0, 0.0), (1.0, 0.0))  # 保留 x<=0
    assert out is not None
    assert abs(area(out) - 2.0) < 1e-9
    for v in out:
        assert v[0] <= EPS


def test_clip_halfplane_empty():
    """完全裁掉 ⇒ None。"""
    sq = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    out = clip_halfplane(sq, (2.0, 0.0), (1.0, 0.0))  # 保留 x<=2 之外？x<=2 全保留
    assert out is not None
    out2 = clip_halfplane(sq, (-2.0, 0.0), (1.0, 0.0))  # 保留 x<=-2：空
    assert out2 is None


def test_clip_circle_superset():
    """外切近似保证交集是 P ∩ B 的超集：采样圆边界点仍在交集内。"""
    sq = [(-2000.0, -2000.0), (2000.0, -2000.0),
          (2000.0, 2000.0), (-2000.0, 2000.0)]
    out = clip_circle(sq, (100.0, 50.0), 1500.0)
    assert out is not None
    for k in range(360):
        phi = 2.0 * math.pi * k / 360
        p = (100.0 + 1500.0 * math.cos(phi), 50.0 + 1500.0 * math.sin(phi))
        assert contains_point(out, p, eps=1e-6)


# ---------------------------------------------------------------------------
# 楔形
# ---------------------------------------------------------------------------

def test_wedge_wrap_across_zero():
    """bearing 359.5° 相对 0° 检测：楔形跨越 0°/360° 时必须正确处理。"""
    S = (0.0, 0.0)
    # 真源在 359.5° 方向（θ̂=0° 时误差 0.5°，合法）
    src = (1000.0 * math.cos(math.radians(359.5)),
           1000.0 * math.sin(math.radians(359.5)))
    assert in_wedge(S, 0.0, src)
    # 10° 方向的点必须被排除
    p10 = (1000.0 * math.cos(math.radians(10.0)),
           1000.0 * math.sin(math.radians(10.0)))
    assert not in_wedge(S, 0.0, p10)

    omega = omega_polygon()
    out = wedge_intersect(omega, S, 0.0)
    assert out is not None
    assert contains_point(out, src, eps=1e-6)
    assert not contains_point(out, p10)


def test_wedge_wrap_around_360_bearing():
    """θ̂ = 359.9°（θ̂+1° = 360.9° ⇒ 0.9°）的 wrap。"""
    S = (500.0, -300.0)
    src = (S[0] + 800.0 * math.cos(math.radians(0.5)),
           S[1] + 800.0 * math.sin(math.radians(0.5)))
    assert in_wedge(S, 359.9, src)
    out = wedge_intersect(omega_polygon(), S, 359.9)
    assert out is not None
    assert contains_point(out, src, eps=1e-6)


def test_wedge_nearly_parallel_boundaries():
    """两条边界射线夹角仅 2°（近平行）：楔形必须仍是窄条而非退化。"""
    S = (-1000.0, 0.0)
    theta = 0.0
    omega = omega_polygon()
    out = wedge_intersect(omega, S, theta)
    assert out is not None
    # 楔形宽度：距 S 为 d 处横向半宽 ≈ d·tan(1°)
    # 交集中的点必须满足方位角在 ±1° 内
    for v in out:
        if math.hypot(v[0] - S[0], v[1] - S[1]) > 1.0:
            b = bearing_of(S, v)
            err = min(abs(b - theta), 360.0 - abs(b - theta))
            assert err <= 1.0 + 1e-6


def test_wedge_empty_intersection():
    """楔形指向 Ω 之外 ⇒ 空交集 ⇒ None。"""
    # S 在 Ω 边界上，楔形指向外侧
    S = (1800.0, 0.0)
    out = wedge_intersect(omega_polygon(), S, 0.0)  # 正东，指向 Ω 外
    # 仅 S 本身在楔形内（Ω 的外切多边形略大于 Ω，可能有微小残片），
    # 面积必须接近零或直接为 None
    if out is not None:
        assert area(out) < 1.0  # 外切近似残留 < 1 m²


def test_wedge_source_always_feasible_adversarial():
    """对抗误差场景：示向度取满 ±1° 误差，真源必须始终在可行域内。"""
    rng = random.Random(42)
    for _ in range(30):
        # 随机检测点与随机源（都在 Ω 内，且源距 S ≤ 1500）
        while True:
            S = (rng.uniform(-1700, 1700), rng.uniform(-1700, 1700))
            G = (rng.uniform(-1700, 1700), rng.uniform(-1700, 1700))
            d = math.hypot(G[0] - S[0], G[1] - S[1])
            if math.hypot(*G) <= 1800.0 and 10.0 < d <= 1500.0:
                break
        true_bearing = bearing_of(S, G)
        # 对抗：误差取满边界 ±1° 的随机端
        err = rng.choice([-1.0, 1.0, rng.uniform(-1.0, 1.0)])
        theta_hat = true_bearing + err
        out = wedge_intersect(omega_polygon(), S, theta_hat)
        assert out is not None, "feasible region emptied under legal error"
        assert contains_point(out, G, eps=1e-6), \
            "true source excluded under adversarial error"


def test_wedge_intersection_shrinks_region():
    """两次交会后真源仍在，且可行域面积严格下降。"""
    G = (300.0, 400.0)
    P = omega_polygon()
    for S, err in [((-800.0, -600.0), 0.7), ((900.0, -200.0), -0.9),
                   ((100.0, 1100.0), 1.0)]:
        th = bearing_of(S, G) + err
        P = wedge_intersect(P, S, th)
        assert P is not None
        assert contains_point(P, G, eps=1e-6)
    assert area(P) < area(omega_polygon()) * 0.01


# ---------------------------------------------------------------------------
# MEC
# ---------------------------------------------------------------------------

def test_mec_equilateral_triangle():
    """等边三角形边长 a：R_MEC = a/√3。"""
    a = 100.0
    tri = [(0.0, 0.0), (a, 0.0),
           (a / 2.0, a * math.sqrt(3.0) / 2.0)]
    center, radius = mec(tri)
    assert abs(radius - a / math.sqrt(3.0)) < 1e-6
    res = verify_mec_covers(tri, center, radius)
    assert res["ok"]


def test_mec_square():
    """正方形边长 a：R_MEC = a√2/2。"""
    a = 50.0
    sq = [(0.0, 0.0), (a, 0.0), (a, a), (0.0, a)]
    center, radius = mec(sq)
    assert abs(radius - a * math.sqrt(2.0) / 2.0) < 1e-6
    assert abs(center[0] - a / 2.0) < 1e-6
    assert abs(center[1] - a / 2.0) < 1e-6
    assert verify_mec_covers(sq, center, radius)["ok"]


def test_mec_obtuse_triangle():
    """钝角三角形：MEC = 最长边直径圆。"""
    tri = [(0.0, 0.0), (10.0, 0.0), (1.0, 1.0)]
    center, radius = mec(tri)
    assert abs(radius - 5.0) < 1e-6
    assert abs(center[0] - 5.0) < 1e-6 and abs(center[1]) < 1e-6


def test_mec_random_polygons_verified():
    """随机凸多边形：MEC 必须覆盖所有顶点，且半径 ≥ 直径/2。"""
    rng = random.Random(7)
    for _ in range(20):
        pts = [(rng.uniform(-1000, 1000), rng.uniform(-1000, 1000))
               for _ in range(12)]
        hull = convex_hull(pts)
        if len(hull) < 3:
            continue
        center, radius = mec(hull)
        res = verify_mec_covers(hull, center, radius,
                                eps=MEC_ACCEPT_EPS)
        assert res["ok"], res["violations"]
        D, _ = diameter_bruteforce(hull)
        assert radius >= D / 2.0 - 1e-6


def test_mec_vs_diameter_counterexample():
    """直径判据不充分：等边三角形 D=a=40 ≤ 40，但 R_MEC = a/√3 ≈ 23.09 > 20。

    演示 spec 要求的反例：D ≤ 40 不蕴含存在半径 20 的覆盖圆，
    因此清除判据必须用 MEC 而非直径。
    """
    a = 40.0
    tri = [(0.0, 0.0), (a, 0.0),
           (a / 2.0, a * math.sqrt(3.0) / 2.0)]
    D, _ = diameter(tri)
    center, radius = mec(tri)
    assert abs(D - a) < 1e-9            # 直径判据"满足"
    assert D <= 40.0 + EPS
    assert radius > 20.0                # 但 MEC 判据不满足
    assert abs(radius - a / math.sqrt(3.0)) < 1e-9
    assert radius > a / 2.0             # R_MEC > D/2


# ---------------------------------------------------------------------------
# 直径：rotating calipers 对拍
# ---------------------------------------------------------------------------

def test_diameter_matches_bruteforce():
    """rotating calipers 与 O(n²) 暴力枚举对拍。"""
    rng = random.Random(1234)
    for _ in range(50):
        m = rng.randint(3, 20)
        pts = [(rng.uniform(-500, 500), rng.uniform(-500, 500))
               for _ in range(m)]
        hull = convex_hull(pts)
        if len(hull) < 2:
            continue
        d_fast, _ = diameter(hull)
        d_slow, _ = diameter_bruteforce(hull)
        assert abs(d_fast - d_slow) < 1e-6, \
            "calipers %.9f != brute %.9f" % (d_fast, d_slow)


def test_diameter_known_shapes():
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    d, _ = diameter(sq)
    assert abs(d - 10.0 * math.sqrt(2.0)) < 1e-9
    seg = [(0.0, 0.0), (7.0, 0.0)]
    d, _ = diameter(seg)
    assert abs(d - 7.0) < 1e-12


# ---------------------------------------------------------------------------
# NBV
# ---------------------------------------------------------------------------

def test_nbv_bisecting_point_beats_degenerate():
    """从侧向观测一个长条可行域，其最坏情况直径应显著小于原直径。"""
    # 沿 x 轴的长条可行域
    strip = [(-500.0, -10.0), (500.0, -10.0),
             (500.0, 10.0), (-500.0, 10.0)]
    d0 = math.hypot(1000.0, 20.0)
    S_side = (0.0, 300.0)  # 侧向观测点：bearing 约为 -90°±...
    res = nbv_score(strip, S_side, current_pos=(0.0, 0.0))
    assert res["gain"] > 0.0
    assert res["worst_diameter"] < 0.2 * d0  # 侧向 1° 楔形把长条切成 ~10m 宽
    assert res["cost"] > 0.0
    assert abs(res["score"] - res["gain"] / res["cost"]) < 1e-12
    assert set(("gain", "cost", "score")).issubset(res.keys())


def test_nbv_deterministic_scan_matches_worst_case():
    """worst_case_diameter 的确定性扫描 ≥ 任意单个假设 bearing 的结果。"""
    strip = [(-500.0, -10.0), (500.0, -10.0),
             (500.0, 10.0), (-500.0, 10.0)]
    S = (0.0, 300.0)
    worst_d, worst_b = worst_case_diameter(strip, S)
    assert worst_d >= 0.0 and worst_b is not None
    # 扫描覆盖若干随机 bearing，其直径不超过 worst_d
    rng = random.Random(5)
    from geometry.wedge import wedge_intersect as wi
    from geometry.diameter import diameter_value
    for _ in range(10):
        th = rng.uniform(200.0, 340.0)
        out = wi(strip, S, th)
        d = diameter_value(out) if out else 0.0
        assert d <= worst_d + 1e-6


def test_bearing_range_outside_point():
    """外部点看多边形：方位角范围被正确收紧。"""
    sq = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
    lo, hi = bearing_range(sq, (1000.0, 0.0))
    assert hi - lo < 5.0  # 远处看小正方形，角范围很小
    mid = (lo + hi) / 2.0 % 360.0
    assert abs(mid - 180.0) < 1.0  # 方向朝西（180°）
    # 内部点 ⇒ 全圆
    lo2, hi2 = bearing_range(sq, (0.0, 0.0))
    assert hi2 - lo2 >= 360.0
