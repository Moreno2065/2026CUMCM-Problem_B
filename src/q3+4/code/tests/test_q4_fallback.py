# -*- coding: utf-8 -*-
"""Q4 有限步清除兜底（FALLBACK_CLEAR）测试（评审第 1 点，v2.1）。

覆盖：
- disk_lattice_cover：半径 20 m 圆盘三角格点（间距 20√3 ≈ 34.641 m）
  对凸可行域无缝覆盖，点数有限且与面积估计同阶；
- FallbackTracker：R_MEC 下降 ≥10% 计有效收缩，连续 K=3 次无有效收缩
  （含 no_signal）触发兜底；
- 调度集成：FALLBACK_CLEAR 最高优先级（压过 READY）、逐点推进、
  序列走完 → CERTIFIED_ABSENT（basis=fallback_exhausted，记 anomaly，
  不静默）、verify_fallback_cover 独立复核通过；
- 端到端对抗：定向源在收到 2 次 bearing 后永远 no_signal（MEC 圆心方向
  背对的极端抽象），验证兜底触发且有限步内清除成功。
"""

import math

import pytest

from geometry import constants as C
from geometry.fallback_cover import (
    cover_point_estimate,
    disk_lattice_cover,
    order_greedy,
)
from geometry.polygon import area, contains_point
from geometry.wedge import bearing_of, wedge_intersect
from policy.fallback import FallbackTracker, NO_SHRINK_LIMIT
from policy.scheduler import Scheduler
from state.channel_state import ChannelStatus
from state.knowledge_state import KnowledgeState
from verifier.geometry_verifier import verify_fallback_cover


def _sector_polygon():
    """首测后楔形扇区（半角 1°、半径 1500）的多边形。"""
    from geometry.polygon import omega_polygon
    return wedge_intersect(omega_polygon(), (0.0, 0.0), 30.0)


def _active_channel(ks, cid, source=(800.0, 300.0)):
    ks[cid].update_direction((0.0, 0.0), bearing_of((0.0, 0.0), source), 0.0)
    ks[cid].update_direction((0.0, 500.0),
                             bearing_of((0.0, 500.0), source), 10.0)
    return ks[cid]


# ---------------------------------------------------------------------------
# 几何：圆盘格点覆盖
# ---------------------------------------------------------------------------

class TestDiskLatticeCover:
    def test_seamless_cover_of_sector(self):
        poly = _sector_polygon()
        pts = disk_lattice_cover(poly)
        assert pts, "no cover points"
        # 点数有限：首测后扇区面积约 3.9 万 m² ⇒ 最坏 ~38 点（加边界带）
        est = cover_point_estimate(poly)
        assert est <= 45
        assert len(pts) <= est * 2 + 20
        # 无缝性独立复核：顶点 + 5 m 网格采样都在某盘内
        v = verify_fallback_cover(poly, pts, C.CLEAR_RADIUS)
        assert v["ok"], v["uncovered"][:3]
        assert v["n_samples"] > 100

    def test_cover_small_polygon(self):
        poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        pts = disk_lattice_cover(poly)
        assert 1 <= len(pts) <= 9
        assert verify_fallback_cover(poly, pts, C.CLEAR_RADIUS)["ok"]

    def test_empty_polygon(self):
        assert disk_lattice_cover(None) == []
        assert disk_lattice_cover([]) == []

    def test_order_greedy_nearest_first(self):
        poly = _sector_polygon()
        pts = disk_lattice_cover(poly)
        ordered = order_greedy(pts, (0.0, 0.0))
        assert len(ordered) == len(pts)
        first = ordered[0]
        d0 = math.hypot(*first)
        assert d0 == min(math.hypot(*p) for p in pts)


# ---------------------------------------------------------------------------
# 有效收缩跟踪：K=3 触发
# ---------------------------------------------------------------------------

class TestShrinkTracking:
    def test_three_consecutive_no_signal_triggers(self):
        ks = KnowledgeState("Q4")
        ch = _active_channel(ks, 4)
        tr = FallbackTracker()
        r = ch.mec_radius
        trigger = None
        for _ in range(NO_SHRINK_LIMIT):
            trigger = tr.note_measure(ch, r, r, signal=False) or trigger
        assert trigger is not None and "consecutive" in trigger

    def test_small_shrink_below_10pct_counts_as_ineffective(self):
        ks = KnowledgeState("Q4")
        ch = _active_channel(ks, 4)
        tr = FallbackTracker()
        r = ch.mec_radius
        trigger = None
        # 首次信号测量计为有效（发现），其后 5% 收缩 <10% 均为无效
        for i in range(NO_SHRINK_LIMIT + 1):
            r_new = r * 0.95
            trigger = tr.note_measure(ch, r, r_new, signal=True) or trigger
            r = r_new
        assert trigger is not None

    def test_effective_shrink_resets_counter(self):
        ks = KnowledgeState("Q4")
        ch = _active_channel(ks, 4)
        tr = FallbackTracker()
        r = ch.mec_radius
        trigger = None
        for _ in range(3):
            for _ in range(NO_SHRINK_LIMIT - 1):   # 2 次无效
                trigger = tr.note_measure(ch, r, r, signal=False) or trigger
            r_new = r * 0.5                        # 1 次有效（≥10%）复位
            trigger = tr.note_measure(ch, r, r_new, signal=True) or trigger
            r = r_new
        assert trigger is None

    def test_progress_budget_triggers(self):
        ks = KnowledgeState("Q4")
        ch = _active_channel(ks, 4)
        tr = FallbackTracker()
        r = ch.mec_radius
        trigger = None
        # 交替 2 次无效 + 1 次有效（不触发 K=3），但总次数超预算
        for i in range(30):
            if i % 3 == 2:
                r_new = r * 0.89        # 11% ≥ 10%：有效
                trigger = tr.note_measure(ch, r, r_new, True) or trigger
                r = r_new
            else:
                trigger = tr.note_measure(ch, r, r, False) or trigger
            if trigger:
                break
        assert trigger is not None and "budget" in trigger


# ---------------------------------------------------------------------------
# 调度集成：优先级、推进、走完收尾
# ---------------------------------------------------------------------------

class TestSchedulerFallback:
    def _enter(self):
        ks = KnowledgeState("Q4")
        ch = _active_channel(ks, 4)
        ks[5].update_near((100.0, 0.0), 0.0)     # READY 频道作对照
        sch = Scheduler("Q4")
        r = ch.mec_radius
        for _ in range(NO_SHRINK_LIMIT):
            sch.on_measure_result(ch, "no_signal", r, r,
                                  was_approach=False, position=(0.0, 0.0))
        assert sch.fallback.in_fallback(4)
        return ks, sch, ch

    def test_fallback_beats_ready(self):
        ks, sch, ch = self._enter()
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "clear" and m.channel == 4
        assert m.meta["fallback"] is True
        assert m.meta["fallback_total"] >= 1

    def test_sequence_walk_and_exhaustion(self):
        ks, sch, ch = self._enter()
        n = 0
        vt = 20.0
        while sch.fallback.in_fallback(4):
            m = sch.decide(ks, (0.0, 0.0), 1)
            assert m.meta["fallback"] and m.channel == 4
            out = sch.on_fallback_clear_result(ch, False, vt)
            vt += 3.0
            n += 1
            assert n <= m.meta["fallback_total"] + 1   # 有限步
        assert out == "exhausted"
        # 保守收尾：CERTIFIED_ABSENT + anomaly，不静默
        assert ch.status == ChannelStatus.CERTIFIED_ABSENT
        assert ch.absent_basis == "fallback_exhausted"
        assert any("fallback exhausted channel 4" in a for a in sch.anomalies)
        # 复核快照：可行域被清除格点无缝覆盖
        rec = [r for r in sch.fallback.records if r["channel"] == 4][0]
        assert rec["n_points"] == n
        assert verify_fallback_cover(rec["region"], rec["points"],
                                     C.CLEAR_RADIUS)["ok"]
        # 兜底结束后调度恢复：READY 频道 5 的清除
        m = sch.decide(ks, (0.0, 0.0), 1)
        assert m.kind == "clear" and m.channel == 5

    def test_success_mid_sequence(self):
        ks, sch, ch = self._enter()
        m = sch.decide(ks, (0.0, 0.0), 1)
        ch.mark_cleared(30.0)
        out = sch.on_fallback_clear_result(ch, True, 30.0)
        assert out == "cleared"
        assert not sch.fallback.in_fallback(4)
        rec = [r for r in sch.fallback.records if r["channel"] == 4][0]
        assert rec["result"] == "cleared" and rec["used"] == 1


# ---------------------------------------------------------------------------
# 端到端对抗：2 次 bearing 后永远 no_signal 的定向源
# ---------------------------------------------------------------------------

class _StonewallSimulatorMixin:
    """目标频道：前 2 次在接收半径内的测量给 direction（误差 +0.5°，
    在 ±1° 界内），此后永远 no_signal（模拟 MEC 圆心方向背对的
    极端定向源）。其余频道语义不变。"""

    def _measure_result(self, position, channel):
        src = self._live_source(channel)
        if src is None:
            return {"measure_result": "no_signal"}
        d = math.hypot(position[0] - src.x, position[1] - src.y)
        if self._dir_budget.get(channel, 0) > 0 and d <= src.r_eff:
            self._dir_budget[channel] -= 1
            svd = (bearing_of(position, src.pos) + 0.5) % 360.0
            return {"measure_result": "direction",
                    "svd_deg": round(svd, 2)}
        return {"measure_result": "no_signal"}


def test_q4_fallback_end_to_end(tmp_path):
    from executor.action_executor import ActionExecutor
    from experiment.runner import GameRunner
    from experiment.simulator import SimulatorBackend, SyntheticSimulator

    class StonewallSim(_StonewallSimulatorMixin, SyntheticSimulator):
        pass

    sim = StonewallSim("Q4", 777, n_sources=1, scenario="random")
    assert len(sim.sources) == 1
    sim.sources[0].directional = True
    sim.sources[0].r_eff = C.R_EFF_MAX     # 保证两处 bearing 在 1500 内可达
    sim._dir_budget = {sim.sources[0].channel: 2}

    ex = ActionExecutor(SimulatorBackend(sim))
    out = tmp_path / "q4_fallback_e2e"
    runner = GameRunner("Q4", ex, str(out), simulator=sim)
    report = runner.run()

    assert report["complete"], report["failure"]
    assert report["verifier_all_ok"]
    assert sim.sources[0].cleared
    m = report["metrics"]
    # 兜底触发并有限步内清除成功；点数有限并记录
    recs = [r for r in m["fallback_records"]
            if r["channel"] == sim.sources[0].channel]
    assert recs, "fallback never triggered"
    rec = recs[0]
    assert rec["result"] == "cleared"
    assert 1 <= rec["used"] <= rec["n_points"] <= 80
    assert rec["estimated_points"] >= 1
    assert any("FALLBACK_CLEAR channel %d" % sim.sources[0].channel in a
               for a in m["anomalies"])
    # 指标口径字段存在
    assert m["t_per_source_s"] is not None
    assert abs(m["T_ledger_sum"] - m["T_total_virtual"]) <= 1e-3
