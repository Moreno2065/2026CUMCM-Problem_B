# -*- coding: utf-8 -*-
"""CERTIFICATE 模式：max ΔC/cost，只补残余缺口。

Q3：7 点骨架 + no_signal 累积。骨架点 b 对频道 c 仍需补访，当且仅当：
  1. 频道 c 未在 b 处测量过（同点测量结果确定复现，重测无信息）；
  2. B(b,1000) 未被 c 的既有 no_signal 圆盘并集完全覆盖（精确
     arrangement 检查，复用 geometry.certificate 内部机制）。
ΔC 代理 = 在该点尚未测量的 UNKNOWN 频道数（每频道各贡献一个新排除圆盘）。

Q4（v2.1，评审第 3 点）：兜底扫描点集改为 31 点三角格点
（q4_lattice_points，边长 s=950 m，保留距原点 ≤ 2750 m 的格点）。
  - 频道证书完成判定（ChannelState.refresh_certificate）：
    31 点全部 no_signal（q4_channel_certified_lattice）
    **或** 既有 δ-稳健凸包证书覆盖 Ω（机会式早证，保留；
    判定用 620 m 网格细胞的 certified_centers 累积）。
  - 格点访问顺序按 ΔC/cost（就近缺口优先，由 choose 的成本评估给出；
    31 点中 2 点在 2750 m 环上，移动成本高，调度照常按成本评估）。
  - 若所有格点对所有 UNKNOWN 频道都已测量而证书仍未闭合（即只可能
    是 δ-凸包证书的边界细胞缺外向见证），进入补充阶段：对未认证细胞 x
    生成 6 个 620 m 环上的补充见证点（conv 内切圆半径
    620·cos30° ≈ 537 ≥ δ=370，必可闭合证书）。

当前位置恒为候选（零移动成本的机会式停点扫描）。
"""

import math

from geometry import constants as C
from geometry.certificate import (
    q3_backbone_points,
    q4_grid_points,
    q4_lattice_points,
    _boundary_arcs,
    _arcs_cover_circle,
    _find_interior_hole,
)
from geometry.q4_sparse_mesh import q4_sparse25_points
from state.channel_state import ChannelStatus
from .certificate_sparsify import q4_residual_closure_score
from .q4_joint_state import rank_q4_candidate
from .route_lookahead import choose_lookahead2

MEASURED_EPS = 1.0          # 同点判定（米）
Q4_WITNESS_RADIUS = C.R_EFF_MIN - C.Q4_DELTA   # 630 m
Q4_RING_POINTS = 6
Q4_RING_RADIUS = C.Q4_GRID_SPACING             # 620 m


def disk_fully_covered(b, r, centers):
    """精确判定 B(b,r) ⊆ ∪B(S_i,r)（等半径圆盘，arrangement 检查）。

    边界弧精确并集 + 内部空洞探针（与 q3_certified 同一套机制，
    把圆心平移到以 b 为原点、以 r 为外半径）。
    """
    shifted = [(s[0] - b[0], s[1] - b[1]) for s in centers]
    intervals, full = _boundary_arcs(shifted, r, r)
    if not full and not _arcs_cover_circle(intervals):
        return False
    return _find_interior_hole(shifted, r, r) is None


def _measured_at(ch_state, p, eps=MEASURED_EPS):
    return any(math.hypot(obs["position"][0] - p[0],
                          obs["position"][1] - p[1]) < eps
               for obs in ch_state.observations
               if obs["result"] in ("direction", "no_signal", "near"))


class CertificatePolicy:
    """证书补访策略。mode ∈ {"Q3", "Q4"}。

    cert_select="nearest"（A4 baseline）：证书残差选点改为最近未访点
    （min 移动成本，确定性 tie-break），唯一改变选点规则。
    q4_naive=True（C.5 对照）：Q4 频道用 Q3 式 7 点骨架 + 1000 m 圆盘
    证书语义（明知不健全，仅用于证明 Q4 证书层必要性）。
    """

    def __init__(self, mode, cert_select="gain_cost", q4_naive=False,
                 q4_certificate_layout="lattice31", q4_joint_rank=False,
                 cert_route_mode="greedy", q4_residual_sparsify=False):
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        if cert_select not in ("gain_cost", "nearest"):
            raise ValueError("cert_select must be 'gain_cost' or 'nearest'")
        if q4_certificate_layout not in ("lattice31", "sparse25"):
            raise ValueError("q4_certificate_layout must be 'lattice31' or "
                             "'sparse25'")
        if cert_route_mode not in ("greedy", "lookahead2"):
            raise ValueError("cert_route_mode must be 'greedy' or "
                             "'lookahead2'")
        self.mode = mode
        self.cert_select = cert_select
        self.q4_naive = bool(q4_naive) and mode == "Q4"
        self.q4_certificate_layout = q4_certificate_layout
        self.q4_joint_rank = bool(q4_joint_rank) and mode == "Q4"
        self.cert_route_mode = (cert_route_mode if mode == "Q4" else
                                "greedy")
        self.q4_residual_sparsify = (bool(q4_residual_sparsify)
                                     and mode == "Q4" and not self.q4_naive)
        use_q3_style = mode == "Q3" or self.q4_naive
        self.backbone = q3_backbone_points() if use_q3_style else None
        # Q4：620 m 网格（δ-稳健凸包机会式早证的细胞中心，保留）
        self.grid = q4_grid_points() if mode == "Q4" else None
        # Q4：31 点三角格点（兜底扫描点集，评审第 3 点）
        if use_q3_style:
            self.lattice = None
        elif q4_certificate_layout == "sparse25":
            self.lattice = q4_sparse25_points()
        else:
            self.lattice = q4_lattice_points()
        # (channel_id, backbone_index) -> True 的永久缓存（覆盖关系单调）
        self._covered_cache = {}

    # ------------------------------------------------------------------
    # Q3
    # ------------------------------------------------------------------

    def _q3_point_useful(self, ch_state, b_index):
        b = self.backbone[b_index]
        if _measured_at(ch_state, b):
            return False
        key = (ch_state.channel_id, b_index)
        if self._covered_cache.get(key):
            return False
        if disk_fully_covered(b, C.R_EFF_MIN, ch_state.certificate_region):
            self._covered_cache[key] = True
            return False
        return True

    # ------------------------------------------------------------------
    # Q4
    # ------------------------------------------------------------------

    def _q4_uncertified_cells(self, ch_state):
        certified = set(ch_state.certified_centers)
        return [x for x in self.grid if x not in certified]

    def _q4_supplementary_points(self, unknown_channels,
                                 min_existing_witnesses=0):
        """为未认证细胞生成环上补充见证点：{point: [channel_id, ...]}"""
        serve = {}
        for ch in unknown_channels:
            for x in self._q4_uncertified_cells(ch):
                witness_count = sum(
                    math.hypot(p[0] - x[0], p[1] - x[1]) <=
                    Q4_WITNESS_RADIUS + C.EPS
                    for p in ch.certificate_region)
                if witness_count < min_existing_witnesses:
                    continue
                for k in range(Q4_RING_POINTS):
                    ang = 2.0 * math.pi * k / Q4_RING_POINTS
                    p = (x[0] + Q4_RING_RADIUS * math.cos(ang),
                         x[1] + Q4_RING_RADIUS * math.sin(ang))
                    if _measured_at(ch, p):
                        continue
                    key = (round(p[0], 3), round(p[1], 3))
                    serve.setdefault(key, set()).add(ch.channel_id)
        return serve

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------

    def choose(self, ks, position, current_channel, candidate_sink=None):
        """选下一个证书点，返回 dict 或 None（无残余缺口）。

        返回 {"point", "channels", "gain", "cost", "kind"}，
        channels 为在该点应测量的 UNKNOWN 频道列表。
        candidate_sink：可选回调 fn(list_of_dict)，接收全部已评证书候选的
        {point, channels, gain, cost, score, kind}（decision_trace 用）。
        """
        unknown = ks.by_status(ChannelStatus.UNKNOWN)
        if not unknown:
            return None
        cands = {}  # key -> {"point", "channels", "kind"}

        if self.mode == "Q3" or self.q4_naive:
            # Q3 主路径 / Q4 naive 对照（C.5）：7 点骨架 + 1000 m 圆盘语义
            for i, b in enumerate(self.backbone):
                chans = [ch.channel_id for ch in unknown
                         if self._q3_point_useful(ch, i)]
                if chans:
                    cands[("b", i)] = {"point": b, "channels": sorted(chans),
                                       "kind": "q3_backbone"}
        else:
            # Q4 固定证书点扫描（就近缺口优先由下方 ΔC/cost 评估给出）
            certificate_kind = ("q4_sparse25"
                                if self.q4_certificate_layout == "sparse25"
                                else "q4_lattice")
            for p in self.lattice:
                chans = [ch.channel_id for ch in unknown
                         if not _measured_at(ch, p)]
                if chans:
                    cands[("g", p)] = {"point": p, "channels": sorted(chans),
                                       "kind": certificate_kind}
            if not cands and self.q4_certificate_layout == "lattice31":
                # 原有兜底阶段必须完整保留。
                for key, chids in self._q4_supplementary_points(
                        unknown).items():
                    cands[("s", key)] = {"point": key,
                                         "channels": sorted(chids),
                                         "kind": "q4_supplementary"}
            if self.q4_residual_sparsify:
                # E4 提前暴露接近闭合的环见证，但不替换固定布局兜底。
                for key, chids in self._q4_supplementary_points(
                        unknown, min_existing_witnesses=2).items():
                    candidate_key = ("s", key)
                    if candidate_key not in cands:
                        cands[candidate_key] = {
                            "point": key, "channels": sorted(chids),
                            "kind": "q4_supplementary",
                            "e4_early_only": True,
                        }

        # 当前位置机会扫描（零移动）
        cur = (round(position[0], 3), round(position[1], 3))
        chans_here = [ch.channel_id for ch in unknown
                      if not _measured_at(ch, position)]
        if chans_here:
            cands[("c", cur)] = {"point": (float(position[0]),
                                           float(position[1])),
                                 "channels": sorted(chans_here),
                                 "kind": "current"}

        best = None
        safe_best = None
        safe_evaluated = []
        any_positive_closure = False
        evaluated = ([] if candidate_sink is not None or
                     self.cert_route_mode == "lookahead2" or
                     self.q4_residual_sparsify else None)
        for cand in cands.values():
            k = len(cand["channels"])
            move = math.hypot(cand["point"][0] - position[0],
                              cand["point"][1] - position[1])
            cost = move / C.MOVE_SPEED + C.MEASURE_TIME * k \
                + C.SWITCH_TIME * max(0, k - 1)
            if current_channel not in cand["channels"]:
                cost += C.SWITCH_TIME
            gain = float(k)
            score = gain / max(cost, 1e-9)
            joint_state_score = 0.0
            joint_hypothesis_count = 0
            if self.q4_joint_rank:
                for channel_id in cand["channels"]:
                    joint = rank_q4_candidate(ks[channel_id], cand["point"])
                    joint_state_score += joint["score"]
                    joint_hypothesis_count += joint["hypothesis_count"]
            residual_closure_gain = 0
            residual_target_cell_count = 0
            if self.q4_residual_sparsify:
                for channel_id in cand["channels"]:
                    closure = q4_residual_closure_score(
                        ks[channel_id], cand["point"], self.grid)
                    residual_closure_gain += closure[
                        "residual_closure_gain"]
                    residual_target_cell_count += closure[
                        "residual_target_cell_count"]
            if evaluated is not None:
                entry = {
                    "point": [float(cand["point"][0]), float(cand["point"][1])],
                    "channels": list(cand["channels"]),
                    "gain": gain, "cost": float(cost), "score": float(score),
                    "kind": cand["kind"],
                }
                if self.q4_joint_rank:
                    entry["joint_state_score"] = float(joint_state_score)
                    entry["joint_hypothesis_count"] = joint_hypothesis_count
                if self.q4_residual_sparsify:
                    entry["residual_closure_gain"] = float(
                        residual_closure_gain)
                    entry["residual_target_cell_count"] = int(
                        residual_target_cell_count)
                evaluated.append(entry)
            if self.q4_joint_rank:
                point_key = (-float(cand["point"][0]),
                             -float(cand["point"][1]))
                pick = (joint_state_score / max(cost, 1e-9), score, -cost,
                        point_key)
            elif self.cert_select == "nearest":
                # A4 baseline：最近未访证书点（min 移动，确定性 tie-break）
                pick = (-move, -cost)
            else:
                pick = (score, -cost)
            base_pick = pick
            best_value = (base_pick, cand, cost, gain, joint_state_score,
                          joint_hypothesis_count, residual_closure_gain,
                          residual_target_cell_count)
            if not cand.get("e4_early_only"):
                if safe_best is None or base_pick > safe_best[0]:
                    safe_best = best_value
                if evaluated is not None:
                    safe_evaluated.append(evaluated[-1])
            if self.q4_residual_sparsify and residual_closure_gain > 0:
                any_positive_closure = True
                pick = (1, residual_closure_gain / max(cost, 1e-9)) + pick
            elif self.q4_residual_sparsify:
                pick = (0, 0.0) + pick
            if best is None or pick > best[0]:
                best = (pick, cand, cost, gain, joint_state_score,
                        joint_hypothesis_count, residual_closure_gain,
                        residual_target_cell_count)
        if candidate_sink is not None:
            candidate_sink(evaluated)
        if best is None:
            return None
        if self.q4_residual_sparsify and not any_positive_closure:
            best = safe_best
            if best is None:
                return None
        if self.cert_route_mode == "lookahead2":
            route_candidates = evaluated
            if self.q4_residual_sparsify:
                positive = [entry for entry in evaluated
                            if entry["residual_closure_gain"] > 0]
                if positive:
                    best_ratio = max(
                        entry["residual_closure_gain"] /
                        max(entry["cost"], 1e-9) for entry in positive)
                    route_candidates = [
                        entry for entry in positive
                        if math.isclose(
                            entry["residual_closure_gain"] /
                            max(entry["cost"], 1e-9), best_ratio,
                            rel_tol=0.0, abs_tol=1e-15)
                    ]
                else:
                    route_candidates = safe_evaluated
            return choose_lookahead2(route_candidates, position,
                                     current_channel)
        (_, cand, cost, gain, joint_state_score, joint_hypothesis_count,
         residual_closure_gain, residual_target_cell_count) = best
        choice = {"point": cand["point"], "channels": cand["channels"],
                  "gain": gain, "cost": cost, "kind": cand["kind"]}
        if self.q4_joint_rank:
            choice["joint_state_score"] = float(joint_state_score)
            choice["joint_hypothesis_count"] = joint_hypothesis_count
        if self.q4_residual_sparsify:
            choice["residual_closure_gain"] = float(residual_closure_gain)
            choice["residual_target_cell_count"] = int(
                residual_target_cell_count)
        return choice
