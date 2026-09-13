# -*- coding: utf-8 -*-
"""一局运行器：驱动 policy loop，保存全部交付物（Addendum E 证据契约）。

交付物（output_dir 下）：
    config.yaml / provenance.json / actions.csv / observations.csv /
    trajectory.csv / channel_state_history.jsonl / decision_trace.jsonl /
    localization_history/ / certificate_history/ / metrics.json /
    verifier_report.json / figure_data/ / state_history.json（兼容保留）/
    certificate.json / api_log.jsonl / run_report.json /
    ground_truth.json（合成模式）

循环：
    enter → while not complete: decide → execute → apply → snapshot → exit
停止条件（KnowledgeState）：全部 CLEARED∨CERTIFIED_ABSENT，或
CLEARED 数 = 16（题设上限早停）。通信异常不破坏 K_t：只有
accepted=true 的响应才更新状态（executor/session 已保证）。
"""

import csv
import json
import math
import os
import time

from geometry import constants as C
from geometry.certificate import (
    q3_certified,
    q4_certify_point,
    q4_channel_certified,
    q4_channel_certified_lattice,
    q4_grid_points,
    q4_lattice_points,
)
from geometry.clear_zone import clear_zone_nonempty
from geometry.diameter import diameter_value
from geometry.q4_sparse_mesh import q4_sparse25_points
from policy.certificate_sparsify import prune_certified_centers
from policy.certificate_policy import disk_fully_covered
from policy.scheduler import Scheduler, plan_stop_measures
from state.channel_state import ChannelStatus
from state.knowledge_state import KnowledgeState
from verifier.geometry_verifier import verify_fallback_cover, verify_mec_covers
from verifier.q3_cover_verifier import verify_q3_cover
from verifier.q4_grid_verifier import (
    verify_q4_lattice_certificate,
    verify_q4_point,
    verify_q4_grid,
)
from verifier.q4_sparse_verifier import (
    verify_q4_sparse25_channel,
    verify_q4_sparse25_mesh,
)
from .config import (
    MODEL_VERSION,
    SPEC_VERSION,
    MainlineConfig,
    config_sha256,
    dump_config_yaml,
    git_commit,
)
from .metrics import compute_metrics

MAX_STEPS = 20000
# 运行版独立复核的采样密度（精确判定在 certificate 模块，此处为第二意见）
VERIFY_BOUNDARY_SAMPLES = 1440
VERIFY_GRID_STEP = 90.0
VERIFY_Q4_DIRECTIONS = 360
# state_history 证书覆盖率估计的粗网格步长
COVERAGE_EST_STEP = 450.0

ACTIONS_FIELDS = ["step", "virtual_time_before", "virtual_time_after",
                  "action_type", "target_x", "target_y", "channel",
                  "policy_mode", "reason_code", "movement_distance",
                  "movement_time", "switch_time", "action_time"]
OBS_FIELDS = ["step", "virtual_time", "x", "y", "channel", "result",
              "bearing_deg", "status_before", "status_after", "svd_deg"]


class GameRunner:
    def __init__(self, mode, executor, output_dir, simulator=None,
                 max_steps=MAX_STEPS, config=None, case=None,
                 config_path=None, policy_variant="mainline"):
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        self.mode = mode
        self.executor = executor
        self.output_dir = output_dir
        self.simulator = simulator
        self.max_steps = max_steps
        self.config = config or MainlineConfig()
        if self.config.max_steps is not None and max_steps == MAX_STEPS:
            self.max_steps = self.config.max_steps
        self.case = case                    # 冻结案例 dict（可为 None）
        self.config_path = config_path
        self.policy_variant = policy_variant
        self.start_time = None
        self.ks = KnowledgeState(
            mode, q4_certificate_layout=self.config.q4_certificate_layout)
        self.scheduler = Scheduler(
            mode, tau=self.config.tau, nbv_mode=self.config.nbv_mode,
            nbv_rule=self.config.nbv_rule,
            opportunistic_reuse=self.config.opportunistic_reuse,
            cert_select=self.config.cert_select,
            q4_naive=self.config.q4_naive,
            q4_certificate_layout=self.config.q4_certificate_layout,
            q4_joint_rank=self.config.q4_joint_rank,
            cert_route_mode=self.config.cert_route_mode,
            q4_residual_sparsify=self.config.q4_residual_sparsify,
            q3_ml_ranker=self.config.q3_ml_ranker,
            q3_ml_model_path=self.config.q3_ml_model_path)

        self.scheduler.decision_listener = self._record_decision
        # 记录
        self.trajectory = []       # dict 行
        self.observations = []     # dict 行
        self.state_history = []    # 快照
        self.mec_radius_history = []
        self.cert_growth = []
        self.actions = []          # actions.csv 行（Addendum E.2）
        self.decision_trace = []   # decision_trace.jsonl（Addendum E.4）
        self.loc_history = {}      # cid -> [entry]（Addendum E.5）
        self.cert_history = {}     # cid -> [entry]（Addendum E.6）
        self._step = 0
        self._current_mission = None
        self._ready_snapshots = {}  # cid -> {"region","center","radius","basis"}
        self._cert_sets = {}        # cid -> set(certified centers)（Q4 快查）
        self._coverage_est_cache = {}
        self._coverage_grid = self._make_coverage_grid()

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(self):
        t0 = time.time()
        import datetime
        self.start_time = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        self.executor.enter()
        self._traj("enter", None, None)
        vt0 = self.executor.virtual_time
        self._action("enter", None, None, vt0, vt0, 0.0, 0.0, 0.0, 0.0)
        failure = None
        steps = 0
        while not self.ks.is_complete():
            if steps >= self.max_steps:
                failure = "max_steps_exceeded"
                break
            if self.executor.real_time_exceeded():
                failure = "real_time_exceeded"
                break
            if self.executor.virtual_time > self.executor.max_virtual_duration_s:
                failure = "virtual_time_exceeded"
                break
            mission = self.scheduler.decide(self.ks, self.executor.position,
                                            self.executor.current_channel)
            if mission is None:
                failure = "no_mission"
                break
            self._current_mission = mission
            self._execute(mission)
            self._current_mission = None
            steps += 1
            self._step = steps
            self._snapshot(steps)
        try:
            self.executor.exit()
            self._traj("exit", None, None)
            vt1 = self.executor.virtual_time
            self._action("exit", None, None, vt1, vt1, 0.0, 0.0, 0.0, 0.0)
        except Exception as e:  # exit 失败不掩盖已完成状态
            failure = failure or ("exit_failed: %s" % e)
        wall = time.time() - t0
        report = self._finalize(wall, failure, steps)
        return report

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    def _scan_set(self, at_position, scan_mode=None):
        """停点伴随扫描集合（A3 消融的唯一改变点）。

        state_aware（默认）：只扫 UNKNOWN 频道，且跳过在该点已测过的
        （结果确定复现，无信息）。
        sweep_all（A3 baseline）：机械扫描全部未结频道（非 CLEARED /
        CERTIFIED_ABSENT），不做状态过滤也不做同点去重。

        useful_sweep（Q3 Candidate v2）：保留 UNKNOWN/ACTIVE 频道的顺带
        bearing 收益，但跳过 READY、终态以及同点已测频道。

        selective_sweep / selective_clear（实验）：Q3 仅保留能带来新排除
        覆盖的 UNKNOWN；
        ACTIVE 仅在当前停点与其 MEC 外包络（信号半径 + MEC 半径）
        相交时顺带测量。Q4 保留 UNKNOWN，因其证书语义不同。
        """
        scan_mode = scan_mode or self.config.channel_scan_mode
        # selective_clear uses the same information-safe filter for every
        # opportunistic sweep. A Q3 UNKNOWN stop whose full signal disk is
        # already covered cannot produce a new bearing or certificate gain.
        if scan_mode == "selective_clear":
            scan_mode = "selective_sweep"
        if scan_mode == "sweep_all":
            return [c.channel_id for c in self.ks.channels.values()
                    if c.status not in (ChannelStatus.CLEARED,
                                        ChannelStatus.CERTIFIED_ABSENT)]
        if scan_mode == "useful_sweep":
            unknown = [c for c in self.ks.channels.values()
                       if c.status == ChannelStatus.UNKNOWN
                       and not self._measured_near(c, at_position)]
            active = [c for c in self.ks.channels.values()
                      if c.status == ChannelStatus.ACTIVE
                      and not self._measured_near(c, at_position)]
            return [c.channel_id for c in active + unknown]
        if scan_mode == "selective_sweep":
            selected = []
            for c in self.ks.channels.values():
                if c.status == ChannelStatus.UNKNOWN:
                    useful = (self.mode != "Q3" or not disk_fully_covered(
                        at_position, C.R_EFF_MIN, c.certificate_region))
                elif c.status == ChannelStatus.ACTIVE:
                    center, radius = c.mec
                    useful = (math.hypot(center[0] - at_position[0],
                                         center[1] - at_position[1])
                              <= (C.R_EFF_MIN + radius
                                  + self.config.active_scan_margin_m
                                  + 1e-9))
                else:
                    useful = False
                if useful and not self._measured_near(c, at_position):
                    selected.append(c.channel_id)
            return selected
        return [c.channel_id for c in self.ks.unknown
                if not self._measured_near(self.ks[c.channel_id],
                                           at_position)]

    def _clear_scan_mode(self, clear_succeeded):
        """Choose the post-clear opportunistic scan policy.

        On success, make the selective mode explicit. On failure, leave the
        configured mode unchanged; ``selective_clear`` itself still applies
        only information-safe filters, so it cannot suppress a useful bearing.
        """
        if (clear_succeeded
                and self.config.channel_scan_mode == "selective_clear"):
            return "selective_sweep"
        return None

    def _execute(self, mission):
        if mission.kind == "clear":
            self._execute_clear(mission)
        else:
            primary = mission.channel if mission.kind == "measure" else None
            if mission.kind == "scan":
                # 证书任务的频道集合已经由 CertificatePolicy 按证书缺口
                # 选定；不能再次套用 selective 机会扫描过滤，否则可能
                # 把唯一的证书补缺测量过滤掉并形成空任务循环。
                unknowns = [c for c in mission.channels
                            if self.ks[c].status == ChannelStatus.UNKNOWN
                            and not self._measured_near(
                                self.ks[c], mission.target)]
            else:
                unknowns = self._scan_set(mission.target)
            seq = plan_stop_measures(primary, unknowns,
                                     self.executor.current_channel)
            if mission.kind == "measure":
                # scan 任务的频道即证书主任务，不算机会式插入
                self._note_opportunistic([c for c in seq if c != primary])
            for cid in seq:
                outcome = self.executor.move_and_measure(
                    mission.target[0], mission.target[1], cid)
                if not outcome.accepted:
                    self.scheduler.anomalies.append(
                        "measure rejected (accepted=false) channel %d"
                        % cid)
                    continue
                is_primary = (mission.kind == "measure"
                              and cid == mission.channel)
                self._action("measure", cid, outcome.position,
                             outcome.vtime_before, outcome.vtime_after,
                             outcome.dt_move * C.MOVE_SPEED,
                             outcome.dt_move, outcome.dt_switch,
                             outcome.dt_measure,
                             reason_suffix=None if (is_primary or
                                                    mission.kind == "scan")
                             else "opportunistic")
                self._apply_measure(
                    outcome, primary=is_primary,
                    was_approach=(is_primary and mission.meta.get("kind")
                                  == "approach"))

    def _execute_clear(self, mission):
        cid = mission.channel
        outcome = self.executor.clear_at(mission.target[0],
                                         mission.target[1], cid)
        self._traj("clear", cid, outcome.clear_result)
        self._action("clear", cid, outcome.position,
                     outcome.vtime_before, outcome.vtime_after,
                     outcome.dt_move * C.MOVE_SPEED, outcome.dt_move,
                     0.0, outcome.dt_clear)
        if not outcome.accepted:
            self.scheduler.anomalies.append(
                "clear rejected (accepted=false) channel %d" % cid)
            return
        ch = self.ks[cid]
        is_fallback = bool(mission.meta.get("fallback"))
        if outcome.success:
            ch.mark_cleared(outcome.vtime_after)
            if is_fallback:
                self.scheduler.on_fallback_clear_result(
                    ch, True, outcome.vtime_after)
        else:
            if is_fallback:
                # 兜底格点未命中属预期（多数点无目标），不计 clear_failure
                self.scheduler.on_fallback_clear_result(
                    ch, False, outcome.vtime_after)
            else:
                self.scheduler.on_clear_failure(cid)
        # 清除停点后的机会式 UNKNOWN 扫描（A3 baseline 为机械全扫）
        pos = self.executor.position
        clear_scan_mode = self._clear_scan_mode(bool(outcome.success))
        seq = plan_stop_measures(None, self._scan_set(pos, clear_scan_mode),
                                 self.executor.current_channel)
        self._note_opportunistic(seq)
        for uid in seq:
            outcome = self.executor.move_and_measure(pos[0], pos[1], uid)
            if outcome.accepted:
                self._action("measure", uid, outcome.position,
                             outcome.vtime_before, outcome.vtime_after,
                             outcome.dt_move * C.MOVE_SPEED,
                             outcome.dt_move, outcome.dt_switch,
                             outcome.dt_measure,
                             reason_suffix="opportunistic")
                self._apply_measure(outcome, primary=False,
                                    was_approach=False)

    # ------------------------------------------------------------------
    # 观测应用（只有 accepted=true 才会到这里）
    # ------------------------------------------------------------------

    def _apply_measure(self, outcome, primary, was_approach):
        ch = self.ks[outcome.channel]
        pos = outcome.position
        vt = outcome.vtime_after
        self._traj("measure", outcome.channel, outcome.result)
        status_before = ch.status
        r_before = ch.mec_radius
        hook_result = outcome.result
        if outcome.result == "direction":
            try:
                ch.update_direction(pos, outcome.svd_deg, vt)
            except ValueError as e:
                self.scheduler.anomalies.append(
                    "direction inconsistency: %s" % e)
                self.scheduler.on_measure_dead_end(
                    outcome.channel, pos, "inconsistent direction")
                # 几何矛盾 = 无进展：按 no_signal 语义计入兜底跟踪
                hook_result = "no_signal"
                self.observations.append(self._obs_row(
                    outcome, status_before, ch.status))
                if primary:
                    self.scheduler.on_measure_result(
                        ch, hook_result, r_before, ch.mec_radius,
                        was_approach, position=self.executor.position)
                return
        elif outcome.result == "near":
            ch.update_near(pos, vt)
        else:  # no_signal
            ch.update_no_signal(pos, vt)
            self._refresh_certificates(ch, pos)
            self._record_certificate(ch, pos)
            if was_approach:
                self.scheduler.on_measure_dead_end(
                    outcome.channel, pos, "no_signal at approach confirm")
        self.observations.append(self._obs_row(outcome, status_before,
                                               ch.status))
        if ch.status in (ChannelStatus.ACTIVE, ChannelStatus.READY) \
                and outcome.result in ("direction", "near"):
            self._record_localization(ch)
        if primary:
            self.scheduler.on_measure_result(
                ch, hook_result, r_before, ch.mec_radius, was_approach,
                position=self.executor.position)
        # READY 快照（清除时刻 MEC 验证用）；basis 取触发 READY 的观测类型：
        # near 触发的清除依据是 ≤5 m  proximity，与 MEC 无关
        if status_before != ChannelStatus.READY \
                and ch.status == ChannelStatus.READY:
            basis = "near" if outcome.result == "near" else "mec"
            self._ready_snapshots[ch.channel_id] = {
                "region": [tuple(v) for v in ch.feasible_region]
                if ch.feasible_region else None,
                "center": ch.mec[0], "radius": ch.mec[1],
                "basis": basis,
            }

    def _obs_row(self, outcome, status_before, status_after):
        pos = outcome.position
        return {
            "step": self._step + 1,
            "virtual_time": outcome.vtime_after,
            "x": pos[0], "y": pos[1],
            "channel": outcome.channel, "result": outcome.result,
            "bearing_deg": outcome.svd_deg
            if outcome.svd_deg is not None else "",
            "status_before": status_before.value,
            "status_after": status_after.value,
            "svd_deg": outcome.svd_deg
            if outcome.svd_deg is not None else "",
        }

    def _refresh_certificates(self, ch, pos):
        """增量证书刷新（仅 no_signal 频道）。

        q4_naive（C.5 对照）：Q4 频道误用 Q3 式 1000 m 圆盘证书——
        明知不健全（定向源 no_signal 并不蕴含源在 B(S,1000) 外），
        假证书由 suite 层的 ground-truth 后置检查发现（不计为成功）。
        """
        if ch.status in (ChannelStatus.CLEARED,
                         ChannelStatus.CERTIFIED_ABSENT):
            return
        if self.mode == "Q3":
            ch.refresh_certificate()
            return
        if self.config.q4_naive:
            if ch.status == ChannelStatus.UNKNOWN:
                res = q3_certified(ch.certificate_region)
                if res["certified"]:
                    ch.status = ChannelStatus.CERTIFIED_ABSENT
                    ch.absent_basis = "naive_q3_style"
            return
        if (self.config.q4_certificate_layout == "sparse25" and
                not self.config.q4_residual_sparsify):
            ch.refresh_certificate()
            return
        # Q4：只重查见证池发生变化的细胞（距新见证点 ≤ 630 m）
        grid = self.scheduler.certificate.grid
        cert_set = self._cert_sets.setdefault(ch.channel_id, set())
        for x in grid:
            if x in cert_set:
                continue
            if math.hypot(x[0] - pos[0], x[1] - pos[1]) \
                    <= C.R_EFF_MIN - C.Q4_DELTA + 1e-9:
                res = q4_certify_point(x, ch.certificate_region)
                if res["certified"]:
                    ch.add_q4_certified_center(x)
                    cert_set.add(x)
        exact_cover = bool(ch.certified_centers) and q4_channel_certified(
            ch.certified_centers)["certified"]
        retained_exact_cover = False
        if self.config.q4_residual_sparsify and exact_cover:
            sparsified = prune_certified_centers(ch.certified_centers)
            if sparsified["accepted"] and sparsified["final_certified"]:
                ch.retain_q4_certified_centers(sparsified["centers"])
                cert_set.clear()
                cert_set.update(ch.certified_centers)
                retained_exact_cover = q4_channel_certified(
                    ch.certified_centers)["certified"]
        if (self.config.q4_residual_sparsify and
                self.config.q4_certificate_layout == "lattice31" and
                retained_exact_cover):
            ch.status = ChannelStatus.CERTIFIED_ABSENT
            ch.absent_basis = "certificate"
        # v2.1：每次 no_signal 后都刷新（31 点格点证书
        # q4_channel_certified_lattice 不依赖凸包细胞，可能独立闭合）
        # E4's lattice run continues past the coarse 31-point sufficient
        # certificate until the exact delta-cover closes and can be pruned.
        # The lattice remains the deterministic candidate fallback throughout.
        lattice_complete = q4_channel_certified_lattice(
            ch.certificate_region)
        if not (self.config.q4_residual_sparsify and
                self.config.q4_certificate_layout == "lattice31" and
                lattice_complete and not exact_cover):
            ch.refresh_certificate()

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def _traj(self, action, channel, result):
        pos = self.executor.position
        self.trajectory.append({
            "virtual_time": self.executor.virtual_time,
            "x": pos[0], "y": pos[1], "action": action,
            "channel": channel if channel is not None else "",
            "result": result or "",
        })

    # ------------------------------------------------------------------
    # Addendum E 证据记录
    # ------------------------------------------------------------------

    def _record_decision(self, trace):
        """Scheduler 决策 hook：记录决策前位置、步号与时刻。"""
        position = self.executor.position
        entry = {"step": self._step + 1,
                 "virtual_time": self.executor.virtual_time,
                 "position": [float(position[0]), float(position[1])]}
        entry.update(trace)
        self.decision_trace.append(entry)

    def _mission_mode_reason(self):
        m = self._current_mission
        if m is None:
            return ("lifecycle", "enter_exit")
        mode = {"clear": "ready_clear", "measure": "active_localization",
                "scan": "certificate"}.get(m.kind, m.kind)
        if m.meta.get("fallback"):
            mode = "fallback_clear"
        reason = m.meta.get("kind") or ("fallback" if m.meta.get("fallback")
                                        else m.kind)
        return (mode, reason)

    def _action(self, action_type, channel, target, vt_before, vt_after,
                move_dist, move_time, switch_time, action_time,
                reason_suffix=None):
        mode, reason = self._mission_mode_reason()
        if reason_suffix:
            reason = "%s:%s" % (reason, reason_suffix)
        self.actions.append({
            "step": self._step + 1,
            "virtual_time_before": round(vt_before, 6),
            "virtual_time_after": round(vt_after, 6),
            "action_type": action_type,
            "target_x": target[0] if target else "",
            "target_y": target[1] if target else "",
            "channel": channel if channel is not None else "",
            "policy_mode": mode,
            "reason_code": reason,
            "movement_distance": round(move_dist, 6),
            "movement_time": round(move_time, 6),
            "switch_time": round(switch_time, 6),
            "action_time": round(action_time, 6),
        })

    def _note_opportunistic(self, channel_ids):
        """回填最近一次决策的机会式插入频道列表（Addendum E.4）。"""
        if self.decision_trace and channel_ids:
            cur = self.decision_trace[-1].setdefault(
                "opportunistic_insertions", [])
            cur.extend(int(c) for c in channel_ids)

    def _record_localization(self, ch):
        """Addendum E.5：ACTIVE/READY 频道每次定位更新的完整几何快照。"""
        region = ch.feasible_region
        entry = {
            "virtual_time": self.executor.virtual_time,
            "observation_count": len(ch.observations),
            "status": ch.status.value,
            "vertices": [list(v) for v in region] if region else None,
            "area": ch.feasible_area if region else None,
            "diameter": diameter_value(region) if region else None,
            "mec_center": list(ch.mec[0]) if ch.mec else None,
            "mec_radius": ch.mec[1] if ch.mec else None,
            # 保证清除区 Z_c = ∩_{v∈P} B(v,20)：由 vertices + 20 m 半径
            # 即可精确重画；此处给出非空判定与实际清除点见证。
            "guaranteed_clear_region": {
                "definition": "Z_c = intersection of B(v,20) over vertices",
                "nonempty": clear_zone_nonempty(region) if region else False,
                "clear_point": (list(ch.clear_position)
                                if ch.clear_position else None),
            },
        }
        self.loc_history.setdefault(ch.channel_id, []).append(entry)

    def _record_certificate(self, ch, source_stop):
        """Addendum E.6：证书进展（Q3/Q4 coverage 定义不同，字段统一）。

        Q3 coverage_ratio：粗网格被 ∪B(S_i,1000) 覆盖的比例；
        Q4 coverage_ratio：粗网格被 ∪_{x∈certified} B(x,δ) 覆盖的比例。
        certificate_measure：证据强度计数 = no_signal 证据点数 +
        已证细胞数。new_gain = 距上一条目的 coverage 增量。
        """
        cov = self._coverage_est(ch)
        hist = self.cert_history.setdefault(ch.channel_id, [])
        prev = hist[-1]["coverage_ratio"] if hist else 0.0
        hist.append({
            "virtual_time": self.executor.virtual_time,
            "certificate_measure": len(ch.certificate_region)
            + len(ch.certified_centers),
            "n_no_signal": len(ch.certificate_region),
            "n_certified_cells": len(ch.certified_centers),
            "n_certified_cells_raw":
                ch.q4_certified_centers_raw_count,
            "coverage_ratio": cov,
            "coverage_definition": self._coverage_definition(),
            "new_gain": cov - prev,
            "certificate_source_stop": [float(source_stop[0]),
                                        float(source_stop[1])],
        })

    def _coverage_definition(self):
        if self.mode == "Q3":
            return "q3_disk_coverage"
        if self.config.q4_naive:
            return "q3_disk_coverage_naive"
        if self.config.q4_certificate_layout == "sparse25":
            return "sparse25_witness_completion"
        return "q4_delta_center_coverage"

    @staticmethod
    def _measured_near(ch_state, p, eps=1.0):
        return any(math.hypot(o["position"][0] - p[0],
                              o["position"][1] - p[1]) < eps
                   for o in ch_state.observations
                   if o["result"] in ("direction", "no_signal", "near"))

    @staticmethod
    def _make_coverage_grid():
        pts = []
        R = C.OMEGA_RADIUS
        n = int(math.ceil(2.0 * R / COVERAGE_EST_STEP)) + 1
        for i in range(n):
            for j in range(n):
                x = -R + i * COVERAGE_EST_STEP
                y = -R + j * COVERAGE_EST_STEP
                if math.hypot(x, y) <= R:
                    pts.append((x, y))
        return pts

    def _coverage_est(self, ch):
        """证书覆盖率估计（粗网格；仅 UNKNOWN 频道需要）。"""
        ev = (len(ch.certificate_region), len(ch.certified_centers))
        cached = self._coverage_est_cache.get(ch.channel_id)
        if cached and cached[0] == ev:
            return cached[1]
        if self.mode == "Q4" and not self.config.q4_naive \
                and self.config.q4_certificate_layout == "sparse25":
            matched = verify_q4_sparse25_channel(
                ch.certificate_region)["matched_count"]
            est = matched / 25.0
            self._coverage_est_cache[ch.channel_id] = (ev, est)
            return est
        if self.mode == "Q3" or self.config.q4_naive:
            centers = ch.certificate_region
            r = C.R_EFF_MIN
        else:
            centers = ch.certified_centers
            r = C.Q4_DELTA
        if not centers:
            est = 0.0
        else:
            covered = sum(
                1 for p in self._coverage_grid
                if any(math.hypot(p[0] - s[0], p[1] - s[1]) <= r
                       for s in centers))
            est = covered / float(len(self._coverage_grid))
        self._coverage_est_cache[ch.channel_id] = (ev, est)
        return est

    def _serialized_certificate_result(self, ch):
        """Return a basis-specific certificate result with a stable ``ok``."""
        basis = ch.absent_basis
        if basis == "fallback_exhausted":
            rec = next(
                (record for record in self.scheduler.fallback.records
                 if record["channel"] == ch.channel_id
                 and record["result"] == "exhausted"), None)
            if rec is None or rec["region"] is None:
                return {"ok": False, "basis": basis,
                        "reason": "missing fallback record"}
            result = verify_fallback_cover(rec["region"], rec["points"],
                                           C.CLEAR_RADIUS)
            result["basis"] = basis
            result["ok"] = bool(result["ok"])
            return result
        if basis == "sparse25":
            result = verify_q4_sparse25_channel(ch.certificate_region)
            result["basis"] = basis
            result["certified"] = bool(result["ok"])
            if self._has_e4_retained_exact_cover(ch):
                exact = verify_q3_cover(
                    ch.certified_centers, cover_r=C.Q4_DELTA,
                    boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                    grid_step=VERIFY_GRID_STEP)
                exact["certified"] = q4_channel_certified(
                    ch.certified_centers)["certified"]
                exact["ok"] = bool(exact["ok"] and exact["certified"])
                result["retained_exact_cover"] = exact
                result["ok"] = bool(result["ok"] and exact["ok"])
            return result
        if basis == "lattice31":
            ok = q4_channel_certified_lattice(ch.certificate_region)
            return {"ok": bool(ok), "certified": bool(ok),
                    "basis": basis,
                    "n_no_signal": len(ch.certificate_region)}
        if basis == "naive_q3_style":
            result = verify_q3_cover(
                ch.certificate_region,
                boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                grid_step=VERIFY_GRID_STEP)
            result["basis"] = basis
            result["certified"] = q3_certified(
                ch.certificate_region)["certified"]
            result["ok"] = bool(result["ok"])
            return result
        if basis == "certificate" and self.mode == "Q3":
            result = verify_q3_cover(
                ch.certificate_region,
                boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                grid_step=VERIFY_GRID_STEP)
            result["basis"] = basis
            result["certified"] = q3_certified(
                ch.certificate_region)["certified"]
            result["ok"] = bool(result["ok"])
            return result
        if basis == "certificate" and self.mode == "Q4":
            result = verify_q3_cover(
                ch.certified_centers, cover_r=C.Q4_DELTA,
                boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                grid_step=VERIFY_GRID_STEP)
            result["basis"] = basis
            result["certified"] = q4_channel_certified(
                ch.certified_centers)["certified"]
            result["ok"] = bool(result["ok"])
            return result
        return {"ok": False, "basis": basis,
                "reason": "unsupported absent_basis"}

    def _has_e4_retained_exact_cover(self, ch):
        """Whether E4 left a complete exact cover requiring a second audit."""
        return (self.config.q4_residual_sparsify and
                bool(ch.certified_centers) and
                q4_channel_certified(ch.certified_centers)["certified"])

    def _snapshot(self, step):
        vt = self.executor.virtual_time
        chans = {}
        for ch in self.ks.channels.values():
            entry = {
                "status": ch.status.value,
                "mec_radius": ch.mec_radius,
                "n_no_signal": len(ch.certificate_region),
                "n_certified_cells": len(ch.certified_centers),
                "n_certified_cells_raw":
                    ch.q4_certified_centers_raw_count,
            }
            if ch.status == ChannelStatus.UNKNOWN and \
                    (ch.certificate_region or ch.certified_centers):
                entry["certificate_coverage_est"] = self._coverage_est(ch)
            chans[str(ch.channel_id)] = entry
            if ch.status in (ChannelStatus.ACTIVE, ChannelStatus.READY):
                self.mec_radius_history.append({
                    "step": step, "virtual_time": vt,
                    "channel": ch.channel_id, "r_mec": ch.mec_radius})
            if ch.certificate_region or ch.certified_centers:
                self.cert_growth.append({
                    "step": step, "virtual_time": vt,
                    "channel": ch.channel_id,
                    "n_no_signal": len(ch.certificate_region),
                    "n_certified_cells": len(ch.certified_centers),
                    "n_certified_cells_raw":
                        ch.q4_certified_centers_raw_count,
                })
        self.state_history.append({
            "step": step, "virtual_time": vt,
            "position": list(self.executor.position),
            "channels": chans,
        })

    # ------------------------------------------------------------------
    # 收尾：指标 + 独立复核 + 落盘
    # ------------------------------------------------------------------

    def _finalize(self, wall, failure, steps):
        n_sources = len(self.simulator.sources) if self.simulator else None
        metrics = compute_metrics(self.executor, self.ks, wall,
                                  n_sources=n_sources,
                                  anomalies=self.scheduler.anomalies,
                                  fallback_records=
                                  self.scheduler.fallback.records,
                                  config=self.config,
                                  decision_trace=self.decision_trace)
        verifier_report = self._verify()
        metrics["verifier_all_ok"] = bool(verifier_report["all_ok"])
        report = {
            "mode": self.mode,
            "complete": self.ks.is_complete(),
            "failure": failure,
            "steps": steps,
            "metrics": metrics,
            "verifier_all_ok": verifier_report["all_ok"],
            "output_dir": os.path.abspath(self.output_dir),
        }
        self._save(metrics, verifier_report, report)
        return report

    def _verify(self):
        rep = {"mec_checks": [], "q3_cover": [], "q4_point_checks_sample": [],
               "q4_channel_cover": [], "q4_lattice_channel": [],
               "q4_sparse_channel": [],
               "fallback_cover": [],
               "q4_grid_static": None, "q4_lattice_static": None,
               "q4_sparse_static": None,
               "all_ok": True}
        # 1. 清除时刻 MEC 验证
        for ch in self.ks.cleared:
            snap = self._ready_snapshots.get(ch.channel_id)
            if snap is None or snap["basis"] == "near":
                rep["mec_checks"].append({"channel": ch.channel_id,
                                          "basis": "near", "ok": True})
                continue
            v = verify_mec_covers(snap["region"], snap["center"],
                                  snap["radius"])
            ok = v["ok"] and snap["radius"] <= C.CLEAR_RADIUS + 1e-9
            rep["mec_checks"].append({
                "channel": ch.channel_id, "basis": "mec", "ok": ok,
                "radius": snap["radius"], "max_dist": v["max_dist"]})
            rep["all_ok"] &= ok
        # 2. 证书频道独立复核
        for ch in self.ks.certified_absent:
            if self.mode == "Q3":
                v = verify_q3_cover(
                    ch.certificate_region,
                    boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                    grid_step=VERIFY_GRID_STEP)
                rep["q3_cover"].append({"channel": ch.channel_id,
                                        "ok": v["ok"],
                                        "max_min_dist": v["max_min_dist"]})
                rep["all_ok"] &= v["ok"]
            else:
                basis = ch.absent_basis or "certificate"
                if basis == "naive_q3_style":
                    # C.5 对照：复核其 Q3 式圆盘覆盖"声明"的几何一致性
                    # （声明本身对定向源不健全；真伪由 suite 层 ground-truth
                    # 后置检查判定，见 suite._case_entry）
                    v = verify_q3_cover(
                        ch.certificate_region,
                        boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                        grid_step=VERIFY_GRID_STEP)
                    rep["q3_cover"].append({
                        "channel": ch.channel_id, "ok": v["ok"],
                        "basis": "naive_q3_style",
                        "max_min_dist": v["max_min_dist"]})
                    rep["all_ok"] &= v["ok"]
                    continue
                if basis == "fallback_exhausted":
                    # 兜底序列走完：独立复核 可行域 ⊆ ∪B(清除点, 20)
                    rec = next(
                        (r for r in self.scheduler.fallback.records
                         if r["channel"] == ch.channel_id
                         and r["result"] == "exhausted"), None)
                    if rec is None or rec["region"] is None:
                        rep["fallback_cover"].append(
                            {"channel": ch.channel_id, "ok": False,
                             "reason": "missing fallback record"})
                        rep["all_ok"] = False
                    else:
                        v = verify_fallback_cover(rec["region"],
                                                  rec["points"],
                                                  C.CLEAR_RADIUS)
                        rep["fallback_cover"].append(
                            {"channel": ch.channel_id, "ok": v["ok"],
                             "n_points": v["n_points"]})
                        rep["all_ok"] &= v["ok"]
                    continue
                if basis == "lattice31":
                    # 31 点格点证书：频道级判定独立复核
                    ok = q4_channel_certified_lattice(ch.certificate_region)
                    rep["q4_lattice_channel"].append(
                        {"channel": ch.channel_id, "ok": ok,
                         "basis": "lattice31"})
                    rep["all_ok"] &= ok
                    continue
                if basis == "sparse25":
                    v = verify_q4_sparse25_channel(ch.certificate_region)
                    entry = dict(v)
                    entry.update({"channel": ch.channel_id,
                                  "basis": "sparse25"})
                    rep["q4_sparse_channel"].append(entry)
                    rep["all_ok"] &= v["ok"]
                    if not self._has_e4_retained_exact_cover(ch):
                        continue
                v = verify_q3_cover(
                    ch.certified_centers, cover_r=C.Q4_DELTA,
                    boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                    grid_step=VERIFY_GRID_STEP)
                rep["q4_channel_cover"].append({"channel": ch.channel_id,
                                                "ok": v["ok"]})
                rep["all_ok"] &= v["ok"]
                # 每个已证细胞的逐点复核（支持函数扫描）
                for x in ch.certified_centers:
                    pv = verify_q4_point(x, ch.certificate_region,
                                         n_directions=VERIFY_Q4_DIRECTIONS)
                    rep["q4_point_checks_sample"].append(
                        {"channel": ch.channel_id, "cell": list(x),
                         "ok": pv["ok"]})
                    rep["all_ok"] &= pv["ok"]
        if self.mode == "Q4":
            g = verify_q4_grid(q4_grid_points(),
                               boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                               grid_step=VERIFY_GRID_STEP)
            rep["q4_grid_static"] = g
            rep["all_ok"] &= g["ok"]
            lat = verify_q4_lattice_certificate(q4_lattice_points())
            rep["q4_lattice_static"] = {"ok": lat["ok"],
                                        "n_points": lat["n_points"],
                                        "max_vertex_dist":
                                            lat["max_vertex_dist"]}
            rep["all_ok"] &= lat["ok"]
            sparse = verify_q4_sparse25_mesh(q4_sparse25_points())
            rep["q4_sparse_static"] = sparse
            rep["all_ok"] &= sparse["ok"]
        rep["all_ok"] = bool(rep["all_ok"])
        return rep

    # ------------------------------------------------------------------
    # 落盘
    # ------------------------------------------------------------------

    def _save(self, metrics, verifier_report, report):
        out = self.output_dir
        os.makedirs(out, exist_ok=True)
        os.makedirs(os.path.join(out, "figure_data"), exist_ok=True)

        def wcsv(name, rows, fields):
            with open(os.path.join(out, name), "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for r in rows:
                    w.writerow(r)

        def wjson(name, obj):
            with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)

        def wjsonl(name, rows):
            with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # Addendum E.1/E：配置快照与 provenance
        dump_config_yaml(self.config, os.path.join(out, "config.yaml"))
        wjson("provenance.json", {
            "model_version": MODEL_VERSION,
            "spec_version": SPEC_VERSION,
            "git_commit": git_commit(
                cwd=os.path.dirname(os.path.abspath(__file__))),
            "case_id": self.case["case_id"] if self.case else None,
            "case_seed": (self.case["case_seed"] if self.case
                          else getattr(self.simulator, "seed", None)),
            "policy_variant": self.policy_variant,
            "frozen_config_hash": config_sha256(self.config_path),
            "error_field_type": getattr(self.simulator, "error_field_type",
                                        None),
            "error_field_version": getattr(self.simulator,
                                           "error_field_version", None),
            "start_time": self.start_time,
        })

        wcsv("trajectory.csv", self.trajectory,
             ["virtual_time", "x", "y", "action", "channel", "result"])
        wcsv("actions.csv", self.actions, ACTIONS_FIELDS)
        wcsv("observations.csv", self.observations, OBS_FIELDS)
        wjson("state_history.json", self.state_history)
        # Addendum E：channel_state_history.jsonl（与 state_history 并行）
        wjsonl("channel_state_history.jsonl", self.state_history)
        wjsonl("decision_trace.jsonl", self.decision_trace)

        # Addendum E.5：每 ACTIVE 频道定位收缩史（足以重画收缩图）
        loc_dir = os.path.join(out, "localization_history")
        os.makedirs(loc_dir, exist_ok=True)
        for cid, entries in self.loc_history.items():
            wjsonl(os.path.join("localization_history",
                                "channel_%02d.jsonl" % cid), entries)

        # Addendum E.6：每频道证书进展史
        cert_dir = os.path.join(out, "certificate_history")
        os.makedirs(cert_dir, exist_ok=True)
        for cid, entries in self.cert_history.items():
            wjsonl(os.path.join("certificate_history",
                                "channel_%02d.jsonl" % cid), entries)

        # 每频道最终证书
        cert = {}
        for ch in self.ks.channels.values():
            entry = {
                "status": ch.status.value,
                "absent_basis": ch.absent_basis,
                "no_signal_points": ch.certificate_region,
                "certified_centers": ch.certified_centers,
                "q4_certified_centers_raw_count":
                    ch.q4_certified_centers_raw_count,
                "q4_certified_centers_retained_count":
                    len(ch.certified_centers),
                "n_observations": len(ch.observations),
            }
            if ch.status == ChannelStatus.CERTIFIED_ABSENT:
                entry["certificate_result"] = \
                    self._serialized_certificate_result(ch)
            cert[str(ch.channel_id)] = entry
        wjson("certificate.json", cert)

        wjson("metrics.json", metrics)
        wjson("verifier_report.json", verifier_report)
        wjson("run_report.json", report)

        with open(os.path.join(out, "api_log.jsonl"), "w",
                  encoding="utf-8") as f:
            for entry in self.executor.api_log:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        wcsv(os.path.join("figure_data", "mec_radius.csv"),
             self.mec_radius_history,
             ["step", "virtual_time", "channel", "r_mec"])
        wcsv(os.path.join("figure_data", "certificate_growth.csv"),
             self.cert_growth,
             ["step", "virtual_time", "channel", "n_no_signal",
              "n_certified_cells", "n_certified_cells_raw"])
        wcsv(os.path.join("figure_data", "trajectory.csv"), self.trajectory,
             ["virtual_time", "x", "y", "action", "channel", "result"])

        if self.simulator is not None:
            wjson("ground_truth.json", self.simulator.ground_truth())
