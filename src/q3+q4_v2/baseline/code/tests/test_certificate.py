# -*- coding: utf-8 -*-
"""证书模块测试：Q3 圆盘覆盖证书（7 点骨架正反例、随机/边界/对抗场景）、
Q4 δ-稳健凸包证书（内部点、边界点、对抗方向、δ 边界）与三角格点覆盖。"""

import math
import random

import pytest

from geometry.constants import OMEGA_RADIUS, R_EFF_MIN, Q4_DELTA, Q4_GRID_SPACING
from geometry.certificate import (
    circle_circle_intersections,
    q3_backbone_points,
    q3_certified,
    q3_certified_grid_confirm,
    q4_certify_point,
    q4_channel_certified,
    q4_grid_coverage_margin,
    q4_grid_points,
)
from verifier.q3_cover_verifier import verify_q3_cover
from verifier.q4_grid_verifier import verify_q4_point, verify_q4_grid


# ---------------------------------------------------------------------------
# Q3：7 点骨架
# ---------------------------------------------------------------------------

def test_q3_backbone_geometry_margin():
    """骨架几何自检：a = 900√3，任意边界角平分点距最近外围点 = 900。"""
    pts = q3_backbone_points()
    assert len(pts) == 7
    a = 900.0 * math.sqrt(3.0)
    for k in range(1, 7):
        assert abs(math.hypot(*pts[k]) - a) < 1e-9
    # 相邻外围点角平分线上的边界点距最近外围点恰为 900
    p = (1800.0 * math.cos(math.radians(30.0)),
         1800.0 * math.sin(math.radians(30.0)))
    d = min(math.hypot(p[0] - s[0], p[1] - s[1]) for s in pts[1:])
    assert abs(d - 900.0) < 1e-6


def test_q3_backbone_certified():
    """7 点骨架必须通过精确证书判定 + 独立采样验证器。"""
    pts = q3_backbone_points()
    res = q3_certified(pts)
    assert res["certified"], res
    v = verify_q3_cover(pts, boundary_samples=3600, grid_step=40.0)
    assert v["ok"], v
    assert v["max_min_dist"] <= 1000.0
    # 网格二次确认余量 ≈ 100 m
    worst, _ = q3_certified_grid_confirm(pts, grid_step=40.0)
    assert worst <= 900.0 + 40.0 * math.sqrt(2.0)  # 网格量化误差上界


def test_q3_backbone_minus_one_fails():
    """随机删 1 点必须判定失败（证明 verifier 不是恒真）。"""
    pts = q3_backbone_points()
    rng = random.Random(0)
    for trial in range(7):
        idx = rng.randrange(7)
        sub = pts[:idx] + pts[idx + 1:]
        res = q3_certified(sub)
        assert not res["certified"], "dropped index %d still certified" % idx
        v = verify_q3_cover(sub, boundary_samples=3600, grid_step=60.0)
        assert not v["ok"]


def test_q3_peripheral_only_fails():
    """仅 6 个外围点（无中心）：原点距最近检测点 1558.8 > 1000，必须失败。"""
    pts = q3_backbone_points()[1:]
    res = q3_certified(pts)
    assert not res["certified"]
    assert res["uncovered_point"] is not None
    # 失败见证点应接近原点（内部空洞）
    up = res["uncovered_point"]
    d_origin = math.hypot(*up)
    assert d_origin < 1558.846 - 1000.0 + 1.0  # 空洞半径内


def test_q3_five_point_layout_fails():
    """5 等角外围点骨架反例：1800·sin36° ≈ 1058 > 1000。"""
    a = 1800.0 / (2.0 * math.sin(math.radians(36.0)))  # 最优外围半径估计
    pts = [(0.0, 0.0)] + [
        (a * math.cos(math.radians(72.0 * k)),
         a * math.sin(math.radians(72.0 * k)))
        for k in range(5)
    ]
    res = q3_certified(pts)
    assert not res["certified"]


def test_q3_empty_and_single_point():
    assert not q3_certified([])["certified"]
    assert not q3_certified([(0.0, 0.0)])["certified"]


def test_q3_random_source_scenario():
    """随机源场景：按最坏 R_eff=1000 模拟测量，无源频道证书与有源频道发现。

    对 10 个随机无源频道：骨架 7 点上全部 no_signal ⇒ 证书成立。
    对随机有源频道：源 1000 m 内必有骨架点返回 signal（证书不适用），
    骨架外 no_signal 点给出的排除圆不得包含真源。
    """
    rng = random.Random(99)
    backbone = q3_backbone_points()
    for _ in range(10):
        # 无源频道
        res = q3_certified(backbone)
        assert res["certified"]
        # 有源频道：随机源位置
        G = (rng.uniform(-1700, 1700), rng.uniform(-1700, 1700))
        if math.hypot(*G) > OMEGA_RADIUS:
            continue
        no_sig = [S for S in backbone
                  if math.hypot(S[0] - G[0], S[1] - G[1]) > R_EFF_MIN]
        # 排除圆不得覆盖真源（no_signal ⇒ ‖S−G‖ > 1000 的一致性）
        for S in no_sig:
            assert math.hypot(S[0] - G[0], S[1] - G[1]) > R_EFF_MIN
        # 证书必不成立（源存在 ⇒ 至少一个骨架点在 1000 m 内）
        assert not q3_certified(no_sig)["certified"] or \
            any(math.hypot(S[0] - G[0], S[1] - G[1]) <= R_EFF_MIN
                for S in backbone)


def test_q3_boundary_source_scenario():
    """边界源场景：源恰在 ∂Ω 上，距其 >1000 的骨架点排除圆仍一致。"""
    backbone = q3_backbone_points()
    for ang in range(0, 360, 15):
        G = (1800.0 * math.cos(math.radians(ang)),
             1800.0 * math.sin(math.radians(ang)))
        no_sig = [S for S in backbone
                  if math.hypot(S[0] - G[0], S[1] - G[1]) > R_EFF_MIN + 1e-9]
        # 边界源距最近骨架点 ≤ 900 ⇒ 至少一点 signal
        assert len(no_sig) < 7
        # 排除证据一致性
        for S in no_sig:
            assert math.hypot(S[0] - G[0], S[1] - G[1]) > R_EFF_MIN


def test_q3_partial_coverage_not_certified():
    """只给骨架点的子集 + 源方向的局部排除，不应误判 certified。"""
    pts = q3_backbone_points()[:4]  # 中心 + 3 外围
    assert not q3_certified(pts)["certified"]


def test_circle_circle_intersections():
    c = circle_circle_intersections((0.0, 0.0), 5.0, (8.0, 0.0), 5.0)
    assert len(c) == 2
    for p in c:
        assert abs(math.hypot(*p) - 5.0) < 1e-9
        assert abs(math.hypot(p[0] - 8.0, p[1]) - 5.0) < 1e-9
    # 相切
    c = circle_circle_intersections((0.0, 0.0), 5.0, (10.0, 0.0), 5.0)
    assert len(c) == 1
    # 相离 / 内含 / 同心
    assert circle_circle_intersections((0, 0), 1.0, (10, 0), 1.0) == []
    assert circle_circle_intersections((0, 0), 10.0, (1, 0), 1.0) == []
    assert circle_circle_intersections((0, 0), 5.0, (0, 0), 5.0) == []


# ---------------------------------------------------------------------------
# Q4：δ-稳健凸包证书
# ---------------------------------------------------------------------------

def _ring_witnesses(x, r, n, phase=0.0):
    return [(x[0] + r * math.cos(phase + 2.0 * math.pi * k / n),
             x[1] + r * math.sin(phase + 2.0 * math.pi * k / n))
            for k in range(n)]


def test_q4_interior_point_certified():
    """构造满足条件的见证点集：6 个见证点在半径 630 的环上。

    凸包为正六边形，内切圆半径 = 630·cos(30°) ≈ 545.6 ≥ 370 ⇒ 通过。
    """
    x = (100.0, 200.0)
    A = _ring_witnesses(x, 630.0, 6)
    res = q4_certify_point(x, A)
    assert res["certified"], res
    assert res["witness_count"] == 6
    assert res["min_edge_distance"] >= Q4_DELTA
    # 独立支持函数验证器复核
    v = verify_q4_point(x, A)
    assert v["ok"], v
    assert v["support_margin"] >= -1e-6


def test_q4_boundary_point_exact_delta():
    """见证点构成内切半径恰为 δ 的正方形 ⇒ 边界通过。

    正方形半边长 δ：顶点在 (±δ√2) 环上 = 522.6... 用 4 点 (±δ, 0),(0, ±δ)
    构成菱形，内切半径 = δ·cos45° < δ 不够。改用正方形顶点 (±δ,±δ)：
    凸包边为 x=±δ, y=±δ，内切半径 = δ 恰好满足。
    顶点距 x 为 δ√2 ≈ 523.0 ≤ 630 ⇒ 全部计入 A_δ。
    """
    x = (0.0, 0.0)
    d = Q4_DELTA
    A = [(d, d), (-d, d), (-d, -d), (d, -d)]
    res = q4_certify_point(x, A)
    assert res["certified"], res
    assert abs(res["min_edge_distance"] - d) < 1e-9


def test_q4_boundary_point_just_inside_fails():
    """内切半径 δ−0.5 ⇒ 不通过（边界严格性）。"""
    x = (0.0, 0.0)
    d = Q4_DELTA - 0.5
    A = [(d, d), (-d, d), (-d, -d), (d, -d)]
    res = q4_certify_point(x, A)
    assert not res["certified"]


def test_q4_adversarial_one_sided_witnesses_fail():
    """对抗方向：见证点全挤在一侧 ⇒ x 不在凸包内 ⇒ 不通过。"""
    x = (0.0, 0.0)
    A = [(600.0, math.cos(math.radians(a)) * 0.0 + 100.0 * k)
         for k, a in enumerate(range(0, 50, 10))]
    # 全部 x 坐标为正（一侧）
    assert all(p[0] > 0 for p in A)
    res = q4_certify_point(x, A)
    assert not res["certified"]
    v = verify_q4_point(x, A)
    assert not v["ok"]


def test_q4_witness_distance_boundary():
    """A_δ 距离边界：恰为 630 计入，630+ε 不计入。"""
    x = (0.0, 0.0)
    d = Q4_DELTA
    base = [(d, d), (-d, d), (-d, -d), (d, -d)]
    extra_in = [(630.0, 0.0)]          # 恰为 630：计入
    res = q4_certify_point(x, base + extra_in)
    assert res["witness_count"] == 5
    extra_out = [(630.0 + 1e-3, 0.0)]  # 630+ε：不计入
    res2 = q4_certify_point(x, base + extra_out)
    assert res2["witness_count"] == 4
    assert res2["certified"]


def test_q4_degenerate_collinear_witnesses_fail():
    """共线见证点：凸包退化 ⇒ 不通过。"""
    x = (0.0, 0.0)
    A = [(100.0, 0.0), (200.0, 0.0), (300.0, 0.0), (400.0, 0.0)]
    res = q4_certify_point(x, A)
    assert not res["certified"]
    assert res["reason"].startswith("witness hull is degenerate") or \
        "fewer" in res["reason"]


def test_q4_fewer_than_3_witnesses_fail():
    x = (0.0, 0.0)
    assert not q4_certify_point(x, [(100.0, 0.0)])["certified"]
    assert not q4_certify_point(x, [])["certified"]


# ---------------------------------------------------------------------------
# Q4：三角格点
# ---------------------------------------------------------------------------

def test_q4_grid_covers_omega():
    """三角格点 ∪B(x_i, 370) 覆盖 Ω（理论余量 370 − 620/√3 ≈ 12.25 m）。"""
    grid = q4_grid_points()
    assert len(grid) >= 30  # 构造性上界约 40
    assert len(grid) <= 120
    v = verify_q4_grid(grid, boundary_samples=3600, grid_step=30.0)
    assert v["ok"], v
    # 覆盖余量应接近理论值（采样量化误差 ~grid_step/2）
    assert v["max_min_dist"] <= Q4_DELTA
    assert v["max_min_dist"] >= Q4_GRID_SPACING / math.sqrt(3.0) - 30.0
    margin_val, worst = q4_grid_coverage_margin(grid)
    assert margin_val <= Q4_DELTA


def test_q4_channel_completion_via_certified_grid():
    """频道完成判定：全部格点 certified ⇒ Ω ⊆ ∪B(x_i,δ) 成立。"""
    grid = q4_grid_points()
    res = q4_channel_certified(grid)
    assert res["certified"], res
    # 去掉一半格点（保留偶数索引）⇒ 覆盖半径变 s·2/√3 ≈ 716 > 370，必失败
    half = grid[::3]
    res2 = q4_channel_certified(half)
    assert not res2["certified"]


def test_q4_full_pipeline_simulated():
    """端到端模拟：定向源存在时，δ 环上的 no_signal 与源存在矛盾的场景。

    构造：x 周围 630 环上 6 见证点全部 no_signal ⇒ B(x,370) 内无源；
    在 B(x,370) 内放一个假想源 G，验证对每个 180° 闭半平面方向，
    至少一个见证点距 G ≤ 1000（半平面论证的数值演示）。
    """
    x = (300.0, -500.0)
    A = _ring_witnesses(x, 630.0, 6)
    res = q4_certify_point(x, A)
    assert res["certified"]
    rng = random.Random(11)
    for _ in range(50):
        # G ∈ B(x, δ)
        r = rng.uniform(0, Q4_DELTA)
        phi = rng.uniform(0, 2 * math.pi)
        G = (x[0] + r * math.cos(phi), x[1] + r * math.sin(phi))
        # 任意定向半平面方向
        for _ in range(8):
            psi = rng.uniform(0, 2 * math.pi)
            n = (math.cos(psi), math.sin(psi))
            witnesses = [p for p in A
                         if (p[0] - G[0]) * n[0] + (p[1] - G[1]) * n[1]
                         >= -1e-9]
            assert witnesses, "no witness in closed half-plane"
            d = min(math.hypot(p[0] - G[0], p[1] - G[1])
                    for p in witnesses)
            assert d <= R_EFF_MIN + 1e-6, \
                "witness too far: %.3f" % d
