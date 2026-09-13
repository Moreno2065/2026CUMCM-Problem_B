# -*- coding: utf-8 -*-
"""词典式调度器（v2.1）：FALLBACK_CLEAR > READY > ACTIVE > CERTIFICATE。

每步决策优先级（词典式）：
0. FALLBACK_CLEAR：进入兜底的频道逐个 /clear 其可行域覆盖格点，
   最高优先级，不被其他频道打断，保证有限步内结束（评审第 1 点）。
1. READY：选绕路成本最小者；MEC 触发的 READY 清除点取 Z_c = ∩B(v,20)
   内距当前位置最近的点（geometry.clear_zone.closest_clear_point，
   评审第 5 点），near 触发的 READY 不变（clear_position = near 位置）。
   失败 → 记 clear_failure（不改数学状态），重试上限 1 次后标记人工
   检查（blocked），不再参与调度。
2. ACTIVE：localization NBV（默认 max ΔR_MEC/cost）；可直达确认的频道
   走 approach（MEC 中心再测；Q3 收敛链任何 ACTIVE 均可直达，Q4 需
   有效交会）。ACTIVE 频道无可评候选 ⇒ 已无信息点，直接转兜底。
3. 否则 CERTIFICATE：certificate_policy 选下一证书点（max ΔC/cost）。
4. 任何停点：先测主频道，再批量扫描 UNKNOWN 频道（先测当前频道以省
   1 s 换频）——由 plan_stop_measures 给出顺序。

策略侧状态（不碰数学状态）：clear 重试计数、blocked 集合、
NBV 失败点黑名单、直达确认 tracker、兜底 tracker、异常记录。
"""

import math

from geometry import constants as C
from geometry.clear_zone import closest_clear_point
from state.channel_state import ChannelStatus
from . import localization
from .approach import ApproachTracker
from .certificate_policy import CertificatePolicy
from .fallback import FallbackTracker
from .q3_ml_ranker import Q3LinearRanker

CLEAR_RETRY_LIMIT = 1   # 失败后最多再试 1 次，随后标记人工检查


class Mission:
    """一次调度决策。

    kind ∈ {"clear", "measure", "scan"}
    - clear  : 去 target 对 channel 执行 /clear
      （meta.fallback=True 时为兜底清除点，失败不计 clear_failure）；
    - measure: 去 target 测 channel（主频道），随后机会扫描 UNKNOWN；
    - scan   : 去 target 批量测量 channels（证书模式，全部 UNKNOWN）。
    """

    def __init__(self, kind, target, channel=None, channels=None, meta=None):
        self.kind = kind
        self.target = (float(target[0]), float(target[1]))
        self.channel = channel
        self.channels = list(channels) if channels else []
        self.meta = dict(meta or {})

    def __repr__(self):
        return "Mission(%s, target=%s, channel=%s, meta=%s)" % (
            self.kind, tuple(round(v, 1) for v in self.target),
            self.channel, self.meta)


def plan_stop_measures(primary, unknown_channels, current_channel):
    """停点测量顺序：先当前频道（省 1s 换频），再主频道，再 UNKNOWN 升序。

    同点顺序扫 k 个频道耗时 5k + (k−1)。
    """
    seq = []
    if primary is not None:
        seq.append(primary)
    seq.extend(c for c in sorted(set(unknown_channels)) if c != primary)
    if current_channel in seq:
        seq.remove(current_channel)
        seq.insert(0, current_channel)
    return seq


class Scheduler:
    def __init__(self, mode, tau=0.0, nbv_mode="radius", nbv_rule="nbv",
                 opportunistic_reuse=True, cert_select="gain_cost",
                 q4_naive=False, q4_certificate_layout="lattice31",
                 q4_joint_rank=False, cert_route_mode="greedy",
                 q4_residual_sparsify=False, q3_ml_ranker=False,
                 q3_ml_model_path=None):
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        self.mode = mode
        # C 类参数（Addendum B.1）：机会式观测收益阈值。
        # tau=0.0 = 既有隐式行为（任何非负收益候选参与 max gain/cost 竞争）。
        self.tau = float(tau)
        if nbv_mode not in ("radius", "diameter"):
            raise ValueError("nbv_mode must be 'radius' or 'diameter'")
        self.nbv_mode = nbv_mode
        # 消融开关（Addendum C；默认值 = mainline 行为）
        self.nbv_rule = nbv_rule
        self.opportunistic_reuse = bool(opportunistic_reuse)
        self.cert_select = cert_select
        self.q4_naive = bool(q4_naive)
        self.q4_certificate_layout = q4_certificate_layout
        self.q4_joint_rank = bool(q4_joint_rank) and mode == "Q4"
        self.cert_route_mode = (cert_route_mode if mode == "Q4" else
                                "greedy")
        self.q4_residual_sparsify = (bool(q4_residual_sparsify)
                                     and mode == "Q4" and not self.q4_naive)
        if isinstance(q3_ml_ranker, Q3LinearRanker) and mode == "Q3":
            self.q3_ml_ranker = q3_ml_ranker
        elif bool(q3_ml_ranker) and mode == "Q3":
            self.q3_ml_ranker = Q3LinearRanker.load(q3_ml_model_path)
        else:
            self.q3_ml_ranker = None
        # 决策证据 hook（Addendum E.4）：fn(trace_dict)，由 runner 挂接；
        # 策略自身只暴露候选评分，日志逻辑留在 runner。
        self.decision_listener = None
        self.certificate = CertificatePolicy(mode, cert_select=cert_select,
                                             q4_naive=q4_naive,
                                             q4_certificate_layout=
                                             q4_certificate_layout,
                                             q4_joint_rank=q4_joint_rank,
                                             cert_route_mode=cert_route_mode,
                                             q4_residual_sparsify=
                                             q4_residual_sparsify)
        self.approach = ApproachTracker(mode)
        self.fallback = FallbackTracker()
        self.clear_failures = {}        # channel_id -> 失败次数
        self.blocked = set()            # 人工检查标记（不再调度）
        self.failed_points = {}         # channel_id -> set((rx, ry)) NBV 黑名单
        self.anomalies = []             # 异常记录（不中断）

    # ------------------------------------------------------------------
    # 事件回调（由 runner 在执行后调用）
    # ------------------------------------------------------------------

    def on_clear_failure(self, channel_id):
        """clear 失败：记录，不改数学状态。返回是否仍允许重试。"""
        n = self.clear_failures.get(channel_id, 0) + 1
        self.clear_failures[channel_id] = n
        self.anomalies.append("clear_failure channel %d (attempt %d)"
                              % (channel_id, n))
        if n > CLEAR_RETRY_LIMIT:
            self.blocked.add(channel_id)
            self.anomalies.append("channel %d blocked for manual check "
                                  "after %d clear failures" % (channel_id, n))
            return False
        return True

    def on_measure_dead_end(self, channel_id, point, reason):
        """NBV/直达确认在 point 处无信息（Q4 no_signal 或几何矛盾）。"""
        self.failed_points.setdefault(channel_id, set()).add(
            (round(point[0], 3), round(point[1], 3)))
        self.anomalies.append("dead-end measure channel %d at %s: %s"
                              % (channel_id,
                                 tuple(round(v, 1) for v in point), reason))

    def on_measure_result(self, ch_state, result, r_before, r_after,
                          was_approach, position=None):
        """主频道测量后的统一钩子：approach 登记 + 有效收缩跟踪 + 兜底触发。

        result ∈ {"direction", "near", "no_signal"}；几何矛盾的 direction
        由 runner 转调为 result="no_signal"（无进展语义）。
        """
        cid = ch_state.channel_id
        if was_approach:
            anomaly = self.approach.on_confirm(ch_state, result,
                                               r_before, r_after)
            if anomaly:
                self.anomalies.append(anomaly)
        # 有效收缩跟踪：所有 ACTIVE 频道主频道测量（含直达确认测量；
        # READY/CLEARED 转移后 status 已变，自然跳过）
        if ch_state.status == ChannelStatus.ACTIVE \
                and not self.fallback.in_fallback(cid):
            trigger = self.fallback.note_measure(
                ch_state, r_before, r_after, signal=(result != "no_signal"))
            if trigger:
                self.anomalies.append("fallback trigger: " + trigger)
                self._enter_fallback(ch_state, position, trigger)
                return
        # Q3 MEC 圆心连续 no_signal（矛盾工况）达限 → 同款兜底
        if was_approach and result == "no_signal" and self.mode == "Q3":
            n = self.approach.q3_center_no_signal_count(cid)
            trigger = self.fallback.note_q3_center_no_signal(ch_state, n)
            if trigger:
                self.anomalies.append("fallback trigger: " + trigger)
                self._enter_fallback(ch_state, position, trigger)

    def on_approach_result(self, ch_state, result, r_before, r_after,
                           position=None):
        """兼容包装：直达确认测量登记（等价 on_measure_result was_approach=True）。"""
        self.on_measure_result(ch_state, result, r_before, r_after,
                               was_approach=True, position=position)

    # ------------------------------------------------------------------
    # 兜底管理
    # ------------------------------------------------------------------

    def _enter_fallback(self, ch_state, position, trigger):
        if self.fallback.in_fallback(ch_state.channel_id):
            return
        if ch_state.status != ChannelStatus.ACTIVE:
            return
        pos = position if position is not None else (0.0, 0.0)
        rec = self.fallback.enter_fallback(ch_state, pos, trigger)
        self.anomalies.append(
            "FALLBACK_CLEAR channel %d: %d points (estimate %d, "
            "region area %.0f m^2), trigger: %s"
            % (rec["channel"], rec["n_points"], rec["estimated_points"],
               rec["region_area"], rec["trigger"]))

    def on_fallback_clear_result(self, ch_state, success, virtual_time):
        """兜底 /clear 结果登记；序列走完 ⇒ CERTIFIED_ABSENT 保守收尾。"""
        outcome = self.fallback.on_clear_result(ch_state, success)
        if outcome == "exhausted":
            self.anomalies.append(
                "fallback exhausted channel %d: region covered by clear "
                "lattice but source not hit — observations contradict "
                "feasible region; marking CERTIFIED_ABSENT "
                "(basis=fallback_exhausted)" % ch_state.channel_id)
            ch_state.force_certified_absent(virtual_time,
                                            "fallback_exhausted")
        return outcome

    # ------------------------------------------------------------------
    # 决策证据 hook（Addendum E.4）
    # ------------------------------------------------------------------

    def _emit(self, trace):
        if self.decision_listener is not None:
            self.decision_listener(trace)

    @staticmethod
    def _status_lists(ks):
        return {
            "ready": [c.channel_id for c in ks.by_status(ChannelStatus.READY)],
            "active": [c.channel_id
                       for c in ks.by_status(ChannelStatus.ACTIVE)],
            "unknown": [c.channel_id
                        for c in ks.by_status(ChannelStatus.UNKNOWN)],
        }

    def _trace_base(self, ks, policy_mode):
        tr = self._status_lists(ks)
        tr.update({
            "policy_mode": policy_mode,
            "candidates": [],
            "selected": None,
            "tie_break": None,
            "opportunistic_insertions": [],   # 由 runner 执行后回填
            "certificate_gain_estimate": None,
            "fallback_trigger": None,
            "tau": self.tau,
            "nbv_mode": self.nbv_mode,
            "q3_ml_ranker": self.q3_ml_ranker is not None,
        })
        return tr

    def _lookahead_tie_break(self):
        parts = []
        if self.q4_residual_sparsify:
            parts.append("positive exact residual closure gain/cost")
        parts.extend(["max route ratio", "min pair cost"])
        if self.q4_joint_rank:
            parts.append("E2 joint score")
        parts.extend(["existing score/cost", "deterministic identity"])
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # 决策
    # ------------------------------------------------------------------

    def _clear_target(self, ch, position):
        """READY 频道的实际清除点（评审第 5 点）。

        R_MEC ≤ 20（MEC 触发的 READY）：取 Z_c = ∩_{v∈P_c} B(v,20) 内
        距 position 最近的点（Z_c 内任何位置都保证清除，取最近省绕路）。
        near 触发的 READY（R_MEC > 20）：clear_position = near 位置不变。
        """
        if ch.mec_radius <= C.CLEAR_RADIUS + C.CLEAR_ZONE_EPS \
                and ch.feasible_region:
            try:
                return closest_clear_point(ch.feasible_region, position)
            except ValueError:
                return ch.clear_position
        return ch.clear_position

    def decide(self, ks, position, current_channel):
        """返回下一个 Mission；无事可做返回 None。"""
        # 0. FALLBACK_CLEAR > 一切（有限步内结束，不被打断）
        for cid in self.fallback.active_fallbacks():
            ch = ks[cid]
            if ch.status != ChannelStatus.ACTIVE:
                self.fallback.finish(cid)
                continue
            pt = self.fallback.next_point(cid)
            if pt is None:   # 理论上 on_fallback_clear_result 已处理
                continue
            idx, total = self.fallback.index_total(cid)
            tr = self._trace_base(ks, "fallback_clear")
            tr["selected"] = {"kind": "clear", "channel": cid,
                              "point": [pt[0], pt[1]]}
            tr["tie_break"] = "lexicographic priority: FALLBACK_CLEAR first"
            tr["fallback_trigger"] = "fallback sequence %d/%d" % (idx, total)
            self._emit(tr)
            return Mission("clear", pt, channel=cid,
                           meta={"fallback": True,
                                 "fallback_index": idx,
                                 "fallback_total": total})

        # 1. READY > ACTIVE > CERTIFICATE
        ready = [ch for ch in ks.by_status(ChannelStatus.READY)
                 if ch.channel_id not in self.blocked]
        if ready:
            targets = {ch.channel_id: self._clear_target(ch, position)
                       for ch in ready}
            ch = min(ready,
                     key=lambda c: math.hypot(
                         targets[c.channel_id][0] - position[0],
                         targets[c.channel_id][1] - position[1]))
            tgt = targets[ch.channel_id]
            tr = self._trace_base(ks, "ready_clear")
            tr["candidates"] = [{
                "channel": c.channel_id,
                "point": [targets[c.channel_id][0], targets[c.channel_id][1]],
                "gain": None,
                "cost": math.hypot(targets[c.channel_id][0] - position[0],
                                   targets[c.channel_id][1] - position[1]),
                "kind": "clear",
            } for c in ready]
            tr["selected"] = {"kind": "clear", "channel": ch.channel_id,
                              "point": [tgt[0], tgt[1]]}
            tr["tie_break"] = "min detour distance among READY channels"
            self._emit(tr)
            return Mission("clear", tgt, channel=ch.channel_id,
                           meta={"detour": math.hypot(
                               tgt[0] - position[0],
                               tgt[1] - position[1])})

        # 2. ACTIVE：max gain/cost（可直达确认者只评 MEC 中心）
        active = [ch for ch in ks.by_status(ChannelStatus.ACTIVE)
                  if not self.fallback.in_fallback(ch.channel_id)]
        if active:
            nbv_cands = []
            choice = localization.choose_observation(
                ks, active, position, current_channel,
                approach_tracker=self.approach,
                failed_points=self.failed_points,
                mode=self.nbv_mode, tau=self.tau,
                candidate_sink=nbv_cands.extend,
                nbv_rule=self.nbv_rule,
                opportunistic_reuse=self.opportunistic_reuse,
                ml_ranker=self.q3_ml_ranker)
            tr = self._trace_base(ks, "active_localization")
            tr["candidates"] = nbv_cands
            if choice is not None:
                tr["selected"] = {"kind": "measure",
                                  "channel": choice["channel"],
                                  "point": list(choice["point"]),
                                  "gain": choice["gain"],
                                  "cost": choice["cost"],
                                  "score": choice["score"],
                                  "nbv_kind": choice["kind"]}
                if "ml_score" in choice:
                    tr["selected"]["ml_score"] = choice["ml_score"]
                    tr["selected"]["takeover"] = choice.get("takeover", False)
                    tr["selected"]["takeover_reason"] = choice.get(
                        "takeover_reason")
                    if choice.get("ml_margin") is not None:
                        tr["selected"]["ml_margin"] = choice["ml_margin"]
                tr["tie_break"] = "max (gain/cost, -cost)"
                if self.q3_ml_ranker is not None:
                    if choice.get("takeover", False):
                        tr["tie_break"] = (
                            "max learned Q3 rank score over tau-eligible "
                            "candidates; deterministic identity")
                    else:
                        tr["tie_break"] = (
                            "deterministic gain/cost fallback after ML gate: "
                            "%s" % choice.get("takeover_reason", "unknown"))
                self._emit(tr)
                return Mission("measure", choice["point"],
                               channel=choice["channel"],
                               meta={"kind": choice["kind"],
                                     "score": choice["score"],
                                     "gain": choice["gain"],
                                     "cost": choice["cost"],
                                     "mode": choice.get("mode")})
            # τ > 0 时先尝试证书模式补缺口，再转兜底（τ=0 保持旧路径）
            if self.tau > 0.0:
                cert_cands = []
                cert = self.certificate.choose(
                    ks, position, current_channel,
                    candidate_sink=(cert_cands.extend
                                    if (self.q4_joint_rank or
                                        self.cert_route_mode == "lookahead2" or
                                        self.q4_residual_sparsify)
                                    else None))
                if cert is not None:
                    tr["selected"] = None
                    tr["tie_break"] = ("all ACTIVE scores below tau=%g; "
                                       "falling through to certificate"
                                       % self.tau)
                    self._emit(tr)
                    if (self.q4_joint_rank or
                            self.cert_route_mode == "lookahead2" or
                            self.q4_residual_sparsify):
                        cert_trace = self._trace_base(
                            ks, "certificate_tau_fallthrough")
                        cert_trace["candidates"] = cert_cands
                        cert_trace["selected"] = {
                            "kind": "scan", "point": list(cert["point"]),
                            "channels": cert["channels"],
                            "gain": cert["gain"], "cost": cert["cost"],
                        }
                        if self.q4_joint_rank:
                            cert_trace["selected"].update({
                                "joint_state_score":
                                cert["joint_state_score"],
                                "joint_hypothesis_count":
                                cert["joint_hypothesis_count"],
                            })
                        if self.q4_residual_sparsify:
                            cert_trace["selected"].update({
                                "residual_closure_gain":
                                cert["residual_closure_gain"],
                                "residual_target_cell_count":
                                cert["residual_target_cell_count"],
                            })
                        if self.cert_route_mode == "lookahead2":
                            cert_trace["selected"].update({
                                key: cert[key] for key in (
                                    "lookahead_depth",
                                    "lookahead_second_point",
                                    "lookahead_pair_cost",
                                    "lookahead_pair_gain",
                                )
                            })
                        cert_trace["tie_break"] = (
                            self._lookahead_tie_break()
                            if self.cert_route_mode == "lookahead2" else
                            "max (joint_state_score/cost, ΔC/cost, -cost)")
                        cert_trace["certificate_gain_estimate"] = cert["gain"]
                        self._emit(cert_trace)
                    mission_meta = {
                        "kind": cert["kind"], "gain": cert["gain"],
                        "cost": cert["cost"], "tau_fallthrough": True,
                        **({
                            "joint_state_score": cert["joint_state_score"],
                            "joint_hypothesis_count":
                            cert["joint_hypothesis_count"],
                        } if self.q4_joint_rank else {})}
                    if self.q4_residual_sparsify:
                        mission_meta.update({
                            "residual_closure_gain":
                            cert["residual_closure_gain"],
                            "residual_target_cell_count":
                            cert["residual_target_cell_count"],
                        })
                    if self.cert_route_mode == "lookahead2":
                        mission_meta.update({
                            key: cert[key] for key in (
                                "lookahead_depth", "lookahead_second_point",
                                "lookahead_pair_cost", "lookahead_pair_gain",
                            )
                        })
                    return Mission(
                        "scan", cert["point"], channels=cert["channels"],
                        meta=mission_meta)
            # 全部 ACTIVE 无可评候选 ⇒ 该频道已无线索点，直接转兜底，
            # 保证任何 ACTIVE 频道有限步内终止（评审第 1 点调度缺口）
            self.anomalies.append(
                "no NBV candidate for ACTIVE channels %r — forcing "
                "FALLBACK_CLEAR" % [c.channel_id for c in active])
            tr["selected"] = None
            tr["fallback_trigger"] = "no informative observation point left"
            tr["tie_break"] = "no candidate passed tau threshold"
            self._emit(tr)
            for ch in active:
                self._enter_fallback(ch, position,
                                     "no informative observation point left")
            return self.decide(ks, position, current_channel)

        # 3. CERTIFICATE：只补残余缺口
        cert_cands = []
        cert = self.certificate.choose(ks, position, current_channel,
                                       candidate_sink=cert_cands.extend)
        tr = self._trace_base(ks, "certificate")
        tr["candidates"] = cert_cands
        if cert is not None:
            tr["selected"] = {"kind": "scan", "point": list(cert["point"]),
                              "channels": cert["channels"],
                              "gain": cert["gain"], "cost": cert["cost"]}
            if self.q4_joint_rank:
                tr["selected"].update({
                    "joint_state_score": cert["joint_state_score"],
                    "joint_hypothesis_count":
                    cert["joint_hypothesis_count"],
                })
            if self.q4_residual_sparsify:
                tr["selected"].update({
                    "residual_closure_gain": cert["residual_closure_gain"],
                    "residual_target_cell_count":
                    cert["residual_target_cell_count"],
                })
            if self.cert_route_mode == "lookahead2":
                tr["selected"].update({
                    key: cert[key] for key in (
                        "lookahead_depth", "lookahead_second_point",
                        "lookahead_pair_cost", "lookahead_pair_gain",
                    )
                })
                tr["tie_break"] = self._lookahead_tie_break()
            else:
                if self.q4_residual_sparsify:
                    tr["tie_break"] = (
                        "positive exact residual_closure_gain/cost, then "
                        "existing E2/base ordering")
                else:
                    tr["tie_break"] = (
                        "max (joint_state_score/cost, ΔC/cost, -cost)"
                        if self.q4_joint_rank else "max (ΔC/cost, -cost)")
            tr["certificate_gain_estimate"] = cert["gain"]
            self._emit(tr)
            mission_meta = {"kind": cert["kind"], "gain": cert["gain"],
                            "cost": cert["cost"]}
            if self.q4_residual_sparsify:
                mission_meta.update({
                    "residual_closure_gain": cert["residual_closure_gain"],
                    "residual_target_cell_count":
                    cert["residual_target_cell_count"],
                })
            if self.cert_route_mode == "lookahead2":
                mission_meta.update({
                    key: cert[key] for key in (
                        "lookahead_depth", "lookahead_second_point",
                        "lookahead_pair_cost", "lookahead_pair_gain",
                    )
                })
            if (self.q4_joint_rank and
                    self.cert_route_mode == "lookahead2"):
                mission_meta.update({
                    "joint_state_score": cert["joint_state_score"],
                    "joint_hypothesis_count": cert["joint_hypothesis_count"],
                })
            return Mission("scan", cert["point"], channels=cert["channels"],
                           meta=mission_meta)
        tr["tie_break"] = "no residual certificate gap"
        self._emit(tr)
        return None
