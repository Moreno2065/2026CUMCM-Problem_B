# -*- coding: utf-8 -*-
"""策略测试：调度优先级、机会扫描顺序、直达确认步数上界。

全部用构造的 KnowledgeState 场景，不依赖模拟器。
"""

import math

import pytest

from geometry import constants as C
from policy.approach import (
    ApproachTracker,
    compute_budget,
    has_valid_intersection,
)
from policy.scheduler import Scheduler, plan_stop_measures
from state.channel_state import ChannelStatus
from state.knowledge_state import KnowledgeState


def _make_ks(mode="Q3"):
    return KnowledgeState(mode)


def _ready_channel(ks, cid, pos):
    ks[cid].update_near(pos, 0.0)
    return ks[cid]


def _active_channel_two_bearings(ks, cid, source):
    """用两次不同位置的精确 bearing 构造 ACTIVE（源位已知仅用于构造）。"""
    from geometry.wedge import bearing_of
    s1, s2 = (0.0, 0.0), (0.0, 500.0)
    ks[cid].update_direction(s1, bearing_of(s1, source), 0.0)
    ks[cid].update_direction(s2, bearing_of(s2, source), 10.0)
    return ks[cid]


# ---------------------------------------------------------------------------
# 调度优先级：READY > ACTIVE > CERTIFICATE
# ---------------------------------------------------------------------------

class TestSchedulingPriority:
    def test_ready_beats_active(self):
        ks = _make_ks()
        _ready_channel(ks, 2, (100.0, 0.0))
        _active_channel_two_bearings(ks, 3, (800.0, 300.0))
        sch = Scheduler("Q3")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "clear" and m.channel == 2
        assert m.target == (100.0, 0.0)

    def test_ready_min_detour(self):
        ks = _make_ks()
        _ready_channel(ks, 2, (1500.0, 0.0))
        _ready_channel(ks, 3, (100.0, 0.0))
        sch = Scheduler("Q3")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.channel == 3          # 绕路成本最小者

    def test_active_beats_certificate(self):
        ks = _make_ks()
        _active_channel_two_bearings(ks, 7, (800.0, 300.0))
        sch = Scheduler("Q3")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "measure" and m.channel == 7

    def test_certificate_when_nothing_else(self):
        ks = _make_ks()
        sch = Scheduler("Q3")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "scan"
        # Q3 首个证书点：原点骨架点（零绕路，20 频道全测）
        assert abs(m.target[0]) < 1e-9 and abs(m.target[1]) < 1e-9
        assert m.meta["kind"] in ("q3_backbone", "current")
        assert len(m.channels) == C.NUM_CHANNELS

    def test_clear_failure_blocks_after_retry(self):
        ks = _make_ks()
        _ready_channel(ks, 2, (100.0, 0.0))
        sch = Scheduler("Q3")
        assert sch.on_clear_failure(2) is True    # 第 1 次：允许重试
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "clear" and m.channel == 2
        assert sch.on_clear_failure(2) is False   # 第 2 次：人工检查
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind != "clear" or m.channel != 2
        assert 2 in sch.blocked
        # 数学状态未被策略改动：仍是 READY
        assert ks[2].status == ChannelStatus.READY


# ---------------------------------------------------------------------------
# 机会扫描顺序：先当前频道（省 1s 换频），再主频道，再 UNKNOWN 升序
# ---------------------------------------------------------------------------

class TestStopPlan:
    def test_current_channel_first(self):
        # 当前频道 3 在 UNKNOWN 集合中 → 最先测
        assert plan_stop_measures(5, [2, 3, 7], 3) == [3, 5, 2, 7]

    def test_current_is_primary(self):
        assert plan_stop_measures(5, [2, 7], 5) == [5, 2, 7]

    def test_current_not_in_set(self):
        # 主频道优先，再 UNKNOWN 升序
        assert plan_stop_measures(5, [2, 7], 1) == [5, 2, 7]

    def test_no_primary(self):
        assert plan_stop_measures(None, [4, 2], 9) == [2, 4]
        assert plan_stop_measures(None, [4, 2], 4) == [4, 2]

    def test_dedup(self):
        assert plan_stop_measures(5, [5, 2], 1) == [5, 2]


# ---------------------------------------------------------------------------
# 直达确认：Q3 MEC 收敛链（v2.1）与 Q4 有效交会门控、步数预算
# ---------------------------------------------------------------------------

class TestApproach:
    def test_budget_typical(self):
        # n ≤ ⌈ln(R0/20)/ln(2cos1°)⌉；首测后扇形上界 R0≈750.114 ⇒ 6 步
        assert compute_budget(750.114) == 6
        assert compute_budget(150.0) <= 3
        assert compute_budget(20.0) == 0
        assert compute_budget(100.0) >= 1
        assert compute_budget(160.0) == 4   # 恰超 3 步包络的边界情形

    def test_q3_direct_approach_after_first_bearing(self):
        """v2.1（评审第 2 点）：Q3 首次 direction 后即可直达 MEC 圆心。

        MEC 圆心距真源 ≤ 750.114 < 1000 ≤ R_eff，下一次测量必有信号，
        不再要求"先获得有效交会"。
        """
        ks = _make_ks()
        from geometry.wedge import bearing_of
        ks[4].update_direction((0.0, 0.0), bearing_of((0.0, 0.0),
                                                      (800.0, 300.0)), 0.0)
        tr = ApproachTracker("Q3")
        assert not has_valid_intersection(ks[4])   # 单 bearing 无交会
        assert tr.eligible(ks[4])                  # 但直达链已可用
        sch = Scheduler("Q3")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "measure" and m.meta["kind"] == "approach"
        assert m.target == pytest.approx(ks[4].mec[0])

    def test_q4_requires_valid_intersection(self):
        """Q4 定向源：MEC 圆心无信号保证，仍需有效交会才可直达。"""
        ks = _make_ks("Q4")
        from geometry.wedge import bearing_of
        ks[4].update_direction((0.0, 0.0), bearing_of((0.0, 0.0),
                                                      (800.0, 300.0)), 0.0)
        tr = ApproachTracker("Q4")
        assert not tr.eligible(ks[4])
        ch = ks[4]
        ch.update_direction((0.0, 500.0), bearing_of((0.0, 500.0),
                                                     (800.0, 300.0)), 10.0)
        assert tr.eligible(ch)
        assert tr.confirm_point(ch) == ch.mec[0]

    def test_approach_after_valid_intersection(self):
        ks = _make_ks()
        ch = _active_channel_two_bearings(ks, 4, (800.0, 300.0))
        tr = ApproachTracker("Q3")
        assert has_valid_intersection(ch)
        assert tr.eligible(ch)
        assert tr.confirm_point(ch) == ch.mec[0]
        sch = Scheduler("Q3")
        m = sch.decide(ks, (500.0, 500.0), 1)
        assert m.kind == "measure" and m.channel == 4
        assert m.meta["kind"] == "approach"
        assert m.target == pytest.approx(ch.mec[0])

    def test_q3_center_no_signal_counted_not_cooled(self):
        """Q3 MEC 圆心 no_signal：矛盾工况，计数且保持可行域，不冷却。"""
        ks = _make_ks()
        ch = _active_channel_two_bearings(ks, 4, (800.0, 300.0))
        tr = ApproachTracker("Q3")
        r0 = ch.mec_radius
        anomaly = tr.on_confirm(ch, "no_signal", r0, r0)
        assert anomaly is not None and "contradiction" in anomaly
        assert tr.q3_center_no_signal_count(4) == 1
        assert tr.eligible(ch)      # 不冷却：直达链仍可继续（下次必收信号）
        # 有效信号复位计数
        tr.on_confirm(ch, "direction", r0, r0 * 0.4)
        assert tr.q3_center_no_signal_count(4) == 0

    def test_q4_no_signal_cooldown(self):
        ks = _make_ks("Q4")
        ch = _active_channel_two_bearings(ks, 4, (800.0, 300.0))
        tr = ApproachTracker("Q4")
        r0 = ch.mec_radius
        anomaly = tr.on_confirm(ch, "no_signal", r0, r0)
        assert anomaly is not None
        assert not tr.eligible(ch)      # 冷却：需新 bearing 才解除
        from geometry.wedge import bearing_of
        ch.update_direction((500.0, 0.0), bearing_of((500.0, 0.0),
                                                     (800.0, 300.0)), 20.0)
        assert tr.eligible(ch)

    def test_over_budget_recorded_not_failed(self):
        ks = _make_ks()
        ch = _active_channel_two_bearings(ks, 4, (800.0, 300.0))
        tr = ApproachTracker("Q3")
        # 模拟收缩：每次按 q 缩半径登记
        r = 160.0
        budget = compute_budget(r)
        anomalies = []
        for _ in range(budget + 2):
            a = tr.on_confirm(ch, "direction", r, r * 0.4)
            r *= 0.4
            if a:
                anomalies.append(a)
        assert tr.steps(4) == budget + 2
        assert len(anomalies) == 1      # 超预算只记录一次，不判失败
        assert "over budget" in anomalies[0]


# ---------------------------------------------------------------------------
# Q3/Q4 证书点选择
# ---------------------------------------------------------------------------

class TestCertificatePolicy:
    def test_q3_residual_backbone(self):
        ks = _make_ks()
        sch = Scheduler("Q3")
        # 在原点测过全部频道（no_signal）后，原点骨架点不再补访
        for cid in range(1, C.NUM_CHANNELS + 1):
            ks[cid].update_no_signal((0.0, 0.0), 0.0)
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m is not None and m.kind == "scan"
        assert math.hypot(*m.target) > 100.0   # 去往外围骨架点

    def test_q4_grid_scan(self):
        ks = _make_ks("Q4")
        sch = Scheduler("Q4")
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "scan"
        assert m.meta["kind"] in ("q4_lattice", "current")
        assert len(m.channels) == C.NUM_CHANNELS
