# -*- coding: utf-8 -*-
"""Q4 三角格点 31 点扫描证书测试（评审第 3 点）。

覆盖：31 点枚举与结构自检、频道级判定正反例、独立验证器
（三角剖分重建 + Ω 边界/内部采样覆盖 + 顶点成员复核）、
500 组对抗 (G, 随机朝向半平面) 数值演示、退化情形（G 在格点/网格边上）、
以及删点/换点反例（验证器非恒真）。
"""

import math
import random

from geometry.constants import (
    OMEGA_RADIUS,
    Q4_LATTICE_SPACING,
    Q4_LATTICE_BOUND,
    Q4_LATTICE_COUNT,
)
from geometry.certificate import (
    q4_lattice_points,
    q4_channel_certified_lattice,
)
from verifier.q4_grid_verifier import verify_q4_lattice_certificate

S = Q4_LATTICE_SPACING      # 950
BOUND = Q4_LATTICE_BOUND    # 2750


# ---------------------------------------------------------------------------
# 构造与枚举
# ---------------------------------------------------------------------------

def test_lattice_count_is_31():
    """评审独立枚举为 31 点；生成器自带断言，这里再显式确认。"""
    pts = q4_lattice_points()
    assert len(pts) == Q4_LATTICE_COUNT == 31


def test_lattice_structure():
    """结构自检：行距 s·√3/2，行点数分布 2/5/6/5/6/5/2，最小间距恰为 s。"""
    pts = q4_lattice_points()
    h = S * math.sqrt(3.0) / 2.0
    rows = {}
    for x, y in pts:
        k = round(y / h)
        assert abs(y - k * h) < 1e-9
        rows.setdefault(k, []).append(x)
    assert sorted(rows) == list(range(-3, 4))
    assert [len(rows[k]) for k in range(-3, 4)] == [2, 5, 6, 5, 6, 5, 2]
    # 奇数行错开 s/2：偶数行含 x=0 的倍数，奇数行含 s/2 的奇数倍
    assert any(abs(x) < 1e-9 for x in rows[0])
    assert any(abs(x - S / 2.0) < 1e-9 for x in rows[1])
    # 全部点在界内
    for p in pts:
        assert math.hypot(*p) <= BOUND + 1e-9
    # 最小两两间距 = s（等边三角格点的最近邻距离）
    dmin = min(
        math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
        for i in range(len(pts)) for j in range(i + 1, len(pts)))
    assert abs(dmin - S) < 1e-9


# ---------------------------------------------------------------------------
# 频道级判定
# ---------------------------------------------------------------------------

def test_channel_certified_full_set():
    assert q4_channel_certified_lattice(q4_lattice_points())


def test_channel_certified_superset():
    """31 点 + 额外 no_signal 点仍应判定通过。"""
    pts = q4_lattice_points() + [(123.4, 567.8), (-2000.0, 100.0)]
    assert q4_channel_certified_lattice(pts)


def test_channel_certified_missing_any_one_fails():
    """缺任意 1 点必须失败（判定非恒真）。"""
    pts = q4_lattice_points()
    for idx in range(len(pts)):
        sub = pts[:idx] + pts[idx + 1:]
        assert not q4_channel_certified_lattice(sub), \
            "dropped index %d still certified" % idx


def test_channel_certified_empty_fails():
    assert not q4_channel_certified_lattice([])


# ---------------------------------------------------------------------------
# 独立验证器：剖分 + 覆盖 + 顶点成员
# ---------------------------------------------------------------------------

def test_verify_lattice_certificate_ok():
    pts = q4_lattice_points()
    res = verify_q4_lattice_certificate(pts)
    assert res["ok"], res
    assert res["n_points"] == 31
    assert res["n_triangles"] > 0
    assert res["vertices_in_set"]
    assert res["uncovered_count"] == 0
    # 覆盖余量：任意 G∈Ω 到其包含三角形最远顶点 ≤ 950 m
    assert res["max_vertex_dist"] <= S + 1e-6


def test_verify_lattice_rejects_altered_set():
    """把原点格点换成界内另一点：仍 31 点但原点附近出洞，必须失败。"""
    pts = q4_lattice_points()
    assert any(abs(p[0]) < 1e-9 and abs(p[1]) < 1e-9 for p in pts)
    altered = [p for p in pts if abs(p[0]) > 1e-9 or abs(p[1]) > 1e-9]
    altered.append((0.0, 2750.0))  # 界内但形不成单位三角形
    assert len(altered) == 31
    res = verify_q4_lattice_certificate(altered)
    assert not res["ok"]
    assert res["uncovered_count"] > 0


def test_verify_lattice_rejects_30_points():
    pts = q4_lattice_points()[:-1]
    res = verify_q4_lattice_certificate(pts)
    assert not res["ok"]
    assert res["n_points"] == 30


# ---------------------------------------------------------------------------
# 对抗数值演示：500 组随机 (G∈Ω, 随机朝向闭半平面)
# ---------------------------------------------------------------------------

def test_adversarial_goal_and_halfplane_500():
    """每个随机 G∈Ω、每个随机朝向闭半平面，都存在格点距 G ≤950 且落在
    该闭半平面内（含边界，容差 1e-9）。"""
    pts = q4_lattice_points()
    rng = random.Random(2026)
    for _ in range(500):
        r = OMEGA_RADIUS * math.sqrt(rng.uniform(0.0, 1.0))
        phi = rng.uniform(0.0, 2.0 * math.pi)
        G = (r * math.cos(phi), r * math.sin(phi))
        psi = rng.uniform(0.0, 2.0 * math.pi)
        nx, ny = math.cos(psi), math.sin(psi)
        hits = [p for p in pts
                if math.hypot(p[0] - G[0], p[1] - G[1]) <= S + 1e-9
                and (p[0] - G[0]) * nx + (p[1] - G[1]) * ny >= -1e-9]
        assert hits, "G=(%.1f, %.1f) half-plane %.3f: no lattice hit" % (
            G[0], G[1], psi)


def test_adversarial_degenerate_on_lattice_point():
    """G 恰在格点上：自身距离 0，任意闭半平面都含它 ⇒ 必命中（near）。"""
    pts = q4_lattice_points()
    rng = random.Random(3)
    for G in pts:
        for _ in range(4):
            psi = rng.uniform(0.0, 2.0 * math.pi)
            nx, ny = math.cos(psi), math.sin(psi)
            hits = [p for p in pts
                    if math.hypot(p[0] - G[0], p[1] - G[1]) <= S + 1e-9
                    and (p[0] - G[0]) * nx + (p[1] - G[1]) * ny >= -1e-9]
            assert hits


def test_adversarial_degenerate_on_grid_edge():
    """G 在网格边中点：半平面垂直于该边朝外时，由邻接/对侧顶点补足。"""
    pts = q4_lattice_points()
    G = (S / 2.0, 0.0)  # 边 (0,0)-(950,0) 中点
    # 半平面 y >= 0 与 y <= 0 两侧都必须有命中
    for ny in (1.0, -1.0):
        hits = [p for p in pts
                if math.hypot(p[0] - G[0], p[1] - G[1]) <= S + 1e-9
                and (p[1] - G[1]) * ny >= -1e-9]
        assert hits
    # 半平面朝 +x 远离端点：对侧顶点 (950,0) 在边界上（闭半平面含边界）
    hits = [p for p in pts
            if math.hypot(p[0] - G[0], p[1] - G[1]) <= S + 1e-9
            and (p[0] - G[0]) >= -1e-9]
    assert hits


# ---------------------------------------------------------------------------
# 覆盖余量（打印实测值）
# ---------------------------------------------------------------------------

def test_coverage_margin_leq_950(capsys=None):
    """实测：Ω 采样点到其最优包含三角形最远顶点距离的最大值 ≤ 950。"""
    res = verify_q4_lattice_certificate(q4_lattice_points())
    print("\ncoverage max_vertex_dist = %.6f m at %s"
          % (res["max_vertex_dist"], res["worst_point"]))
    assert res["max_vertex_dist"] <= S + 1e-6
