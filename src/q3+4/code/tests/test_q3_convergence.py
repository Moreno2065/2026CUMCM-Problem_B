# -*- coding: utf-8 -*-
"""Q3 确定性 MEC 收敛链的对抗性验证（评审第 2 点，v2.1）。

数学链（被测断言）：
1. 首次 direction 后可行域 ⊆ 半角 1° 楔形 ∩ B(S,1500)，其 MEC 半径
   ≤ R0 = 1500/(2cos1°) ≈ 750.114 m（多边形近似放宽 1/cos(π/128)）。
2. 走到 MEC 圆心 c：dist(c, 真源) ≤ R_MEC ≤ 750.34 < 1000 ≤ R_eff
   ⇒ 下一次测量必然返回 direction 或 near（Q3 全向源，无覆盖角约束）。
3. 在 MEC 圆心再测：R_{k+1} ≤ R_k/(2cos1°)，q ≈ 0.50008。
4. 首次测向后最多再取 ⌈ln(750.114/20)/ln(2cos1°)⌉ = 6 次方向观测，
   必达 R_MEC ≤ 20（READY）。

对抗性设定：测向误差取 ±1° 边界值（恒 +1° / 恒 −1° / 交替）或
[-1°, +1°] 均匀随机；真源任意位置；首测点距真源最远取 1500 m 边界。
合成几何仿真直接驱动 ChannelState.update_direction（与线上同一路径）。

覆盖：1000 组随机场景 + 手造边界场景。
"""

import math
import random

import pytest

from geometry import constants as C
from geometry.wedge import bearing_of
from policy.approach import (
    CONTRACTION_Q,
    FIRST_BEARING_RADIUS_BOUND,
    compute_budget,
)
from state.channel_state import ChannelState, ChannelStatus

# 128 边外切多边形近似把圆盘放宽 1/cos(π/128) ≈ 1+3.0e-4，
# 收缩比断言留 5e-4 容差
POLY_SLACK = 1.0 + 5e-4
MAX_EXTRA_DIRECTION_OBS = 6     # 首次测向后最多再取 6 次方向观测


# 边界误差取 1°−1e-4°：真边界 ±1° 使真源恰落在楔形边界射线上，
# 连续半平面裁剪的浮点容差（1e-9 m 量级）会将其剃出可行域；
# 取任意逼近边界的值，收缩结论不变（wedge 闭区间语义由 in_wedge
# 单测覆盖）。角度域 1e-4° ≪ 容差外的任何几何尺度。
ERR_BOUNDARY = 1.0 - 1e-4

# Python's built-in hash is deliberately process-randomized.  Keep the
# adversarial corpus stable so a passing run means the same 1,000 cases passed.
ADVERSARIAL_SEEDS = {
    "plus": 20260615,
    "minus": 20260616,
    "alternate": 20260617,
    "random": 20260618,
}


def _err_fn(kind, rng=None):
    if kind == "plus":
        return lambda k: ERR_BOUNDARY
    if kind == "minus":
        return lambda k: -ERR_BOUNDARY
    if kind == "alternate":
        return lambda k: ERR_BOUNDARY if k % 2 == 0 else -ERR_BOUNDARY
    if kind == "random":
        return lambda k: rng.uniform(-ERR_BOUNDARY, ERR_BOUNDARY)
    raise ValueError(kind)


def run_mec_chain(G, S0, err_fn, tag=""):
    """从首次 bearing 起走"MEC 圆心再测"链，返回 (n_extra_obs, R_history)。

    每步断言归纳不变式与收缩界；超 6 次方向观测未 READY 则断言失败。
    """
    ch = ChannelState(1, "Q3")
    t = 0.0
    svd = (bearing_of(S0, G) + err_fn(0)) % 360.0
    ch.update_direction(S0, svd, t)
    # A first direction can already shrink the feasible region to the
    # guaranteed-clear radius.  This is a legal, more efficient terminal
    # localization state, not a violation of the MEC contraction contract.
    if ch.status == ChannelStatus.READY:
        assert ch.mec_radius <= C.CLEAR_RADIUS
        return 0, [ch.mec_radius]
    assert ch.status == ChannelStatus.ACTIVE

    # 首测后扇形 MEC 上界（含多边形近似放宽）
    r = ch.mec_radius
    assert r <= FIRST_BEARING_RADIUS_BOUND * POLY_SLACK, \
        "%s: first-bearing R=%.6f > 750.114 bound" % (tag, r)
    R_hist = [r]

    n_extra = 0
    while ch.mec_radius > C.CLEAR_RADIUS:
        center, r_before = ch.mec
        d = math.hypot(center[0] - G[0], center[1] - G[1])
        # 归纳不变式：MEC 圆心覆盖真源（可行域 ⊇ {G} 且凸）
        assert d <= r_before + 1e-6, \
            "%s: invariant dist(center,G)=%.6f > R=%.6f" % (tag, d, r_before)
        # 信号保证：dist ≤ R ≤ 750.34 < 1000 ≤ R_eff ⇒ 下一步必有信号
        assert r_before <= FIRST_BEARING_RADIUS_BOUND * POLY_SLACK + 1e-6
        assert d < C.R_EFF_MIN, "%s: no signal guarantee broken" % tag
        t += 5.0
        svd = (bearing_of(center, G) + err_fn(n_extra + 1)) % 360.0
        ch.update_direction(center, svd, t)
        n_extra += 1
        r_after = ch.mec_radius
        # 收缩界：R_{k+1} ≤ q · R_k（q = 1/(2cos1°)，含多边形容差）
        assert r_after <= r_before * CONTRACTION_Q * POLY_SLACK + 1e-6, \
            "%s: contraction violated %.6f -> %.6f" % (tag, r_before, r_after)
        R_hist.append(r_after)
        assert n_extra <= MAX_EXTRA_DIRECTION_OBS, \
            "%s: %d extra direction obs without READY (R=%.6f)" \
            % (tag, n_extra, r_after)
    assert ch.status == ChannelStatus.READY
    return n_extra, R_hist


# ---------------------------------------------------------------------------
# 预算常数
# ---------------------------------------------------------------------------

def test_budget_from_first_bearing_bound_is_6():
    assert compute_budget(FIRST_BEARING_RADIUS_BOUND) == 6
    assert 750.0 < FIRST_BEARING_RADIUS_BOUND < 750.5
    assert abs(CONTRACTION_Q - 0.50008) < 1e-4


def test_first_direction_may_be_ready():
    """A boundary source and an exterior observation can bypass ACTIVE."""
    n_extra, radii = run_mec_chain(
                                   (-1346.192851695439, 1173.8925266519575),
                                   (-2842.8370193619085, 1228.441464624641),
                                   _err_fn("plus"),
                                   tag="initial_ready")
    assert n_extra == 0
    assert radii[-1] <= C.CLEAR_RADIUS


# ---------------------------------------------------------------------------
# 手造边界场景
# ---------------------------------------------------------------------------

class TestHandcraftedBoundary:
    """源距检测点恰 1500 m（接收半径上界），误差恒取边界值。"""

    G = (900.0, 300.0)

    @pytest.mark.parametrize("err", ["plus", "minus", "alternate"])
    def test_source_at_1500_boundary(self, err):
        G = self.G
        d = C.R_EFF_MAX
        S0 = (G[0] - d, G[1])        # dist(S0, G) = 1500 恰边界
        n_extra, R_hist = run_mec_chain(G, S0, _err_fn(err),
                                        tag="boundary1500/%s" % err)
        assert 1 <= n_extra <= MAX_EXTRA_DIRECTION_OBS
        assert R_hist[-1] <= C.CLEAR_RADIUS

    @pytest.mark.parametrize("err", ["plus", "minus", "alternate"])
    def test_source_on_omega_boundary(self, err):
        rng = random.Random(7)
        G = (C.OMEGA_RADIUS, 0.0)    # 源贴 ∂Ω
        d = rng.uniform(500.0, 1500.0)
        ang = rng.uniform(0, 2 * math.pi)
        S0 = (G[0] + d * math.cos(ang), G[1] + d * math.sin(ang))
        run_mec_chain(G, S0, _err_fn(err), tag="omega_boundary/%s" % err)

    def test_grazing_wedge(self):
        """真源恰好贴楔形边界（误差恒 +1° 使源恒在下边界射线上）。"""
        G = (1000.0, 1000.0)
        S0 = (G[0] - 1500.0 / math.sqrt(2), G[1] - 1500.0 / math.sqrt(2))
        run_mec_chain(G, S0, _err_fn("plus"), tag="grazing")


# ---------------------------------------------------------------------------
# 1000 组随机对抗场景
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("err", ["plus", "minus", "alternate", "random"])
def test_random_adversarial_1000(err):
    rng = random.Random(ADVERSARIAL_SEEDS[err])
    worst_extra = 0
    for trial in range(250):
        # 真源：Ω 内面积均匀
        r = C.OMEGA_RADIUS * math.sqrt(rng.random())
        phi = rng.uniform(0, 2 * math.pi)
        G = (r * math.cos(phi), r * math.sin(phi))
        # 首测点：距真源 [500, 1500]（含最坏 1500 附近）
        d = rng.uniform(500.0, 1500.0)
        ang = rng.uniform(0, 2 * math.pi)
        S0 = (G[0] + d * math.cos(ang), G[1] + d * math.sin(ang))
        n_extra, _ = run_mec_chain(
            G, S0, _err_fn(err, rng), tag="%s#%d" % (err, trial))
        worst_extra = max(worst_extra, n_extra)
    # 对抗边界误差下也不得突破 6 步
    assert worst_extra <= MAX_EXTRA_DIRECTION_OBS
