# -*- coding: utf-8 -*-
"""ACTIVE 模式定位选点（v2.1：默认 max ΔR_MEC/cost，评审第 5 点）。

评价指标（geometry.nbv 的最坏情况扫描）：
- radius（默认）：gain = R_MEC(P) − max_θ̂ R_MEC(P ∩ W(S,θ̂) ∩ B(S,1500))。
  最终清除判据是 R_MEC ≤ 20 m，MEC 半径下降比直径更贴近清除任务。
- diameter（config 可选）：gain = D(P) − max_θ̂ D(...)，v2.0 口径保留。

候选点集（确定性，禁止 Monte Carlo）：
- 可行域 MEC 中心；
- 围绕 MEC 中心的 6 点环（半径 clamp(1.2·R_MEC, 60, 240)：保证对定向源
  也有若干环点落在覆盖半平面内且距源 ≤ R_eff 下界 1000 m）；
- 当前位置 → MEC 中心中点（机会点，省移动）；
- 当前位置本身（零移动成本）；
- 最近一次有效 bearing 观测位置 → MEC 中心线段上的两点（Q4 定向源：
  线段靠近首测点一侧大概率仍在覆盖半平面内）。

成本 = 移动距离/5 + 5 + （换频道 1，若与当前频道不同）。

性能取舍：NBV 扫描评价使用 B(S,1500) 的 16 边外切多边形粗近似
（geometry.nbv 默认 128 边），仅影响候选点打分精度（评价函数不变，
仍是确定性最坏情况扫描），不进入任何状态更新——可行域更新始终走
ChannelState 的 128 边精确路径。radius 模式用 gain ≤ R_MEC(P) 做精确
上界剪枝（diameter 模式用 gain ≤ D(P)）。

直达确认联动：频道可直达确认（approach.eligible）时，候选集收缩为
仅 MEC 中心一点。Q3 任何 ACTIVE 频道均可直达（MEC 收敛链，必有信号）；
Q4 需有效交会（MEC 圆心无信号保证）。
"""

import math

from geometry import constants as C
from geometry.diameter import diameter_value
from geometry.nbv import nbv_score, worst_case_diameter, worst_case_radius
from geometry.wedge import bearing_range
from .q3_ml_ranker import select_q3_candidate

# NBV 评价指标模式："radius"（ΔR_MEC，默认，评审第 5 点）/ "diameter"（ΔD）
NBV_GAIN_MODE = "radius"

# NBV 最坏情况扫描的最大步数（控制策略每步计算量）
MAX_SCAN_STEPS = 16
# 评价用圆盘近似边数（仅打分，不进状态）
EVAL_CIRCLE_SIDES = 16
# 候选点环参数
RING_POINTS = 6
RING_MIN_R = 60.0
RING_MAX_R = 240.0
RING_R_FACTOR = 1.2
# 与历史测点距离小于该值的候选点视为重复（同位置测量结果确定复现）
DUP_POINT_EPS = 1.0


def _adaptive_step(poly, S):
    lo, hi = bearing_range(poly, S)
    span = min(360.0, hi - lo + 2.0 * C.BEARING_ERROR_DEG)
    return max(0.5, span / MAX_SCAN_STEPS)


def _eval_worst(poly, S, step_deg, mode=NBV_GAIN_MODE,
                tol_deg=C.BEARING_ERROR_DEG):
    """最坏情况评价的粗近似版（16 边圆盘）：直径或 MEC 半径。"""
    if mode == "radius":
        return worst_case_radius(poly, S, step_deg, tol_deg,
                                 n_circle=EVAL_CIRCLE_SIDES)[0]
    return worst_case_diameter(poly, S, step_deg, tol_deg,
                               n_circle=EVAL_CIRCLE_SIDES)[0]


def _measured_positions(ch_state):
    return [(obs["position"][0], obs["position"][1])
            for obs in ch_state.observations
            if obs["result"] in ("direction", "no_signal", "near")]


def candidate_points(ch_state, position, failed_points=None,
                     opportunistic_reuse=True):
    """生成候选观测点（含去重与黑名单过滤）。

    opportunistic_reuse=False（A2 baseline）：去掉机会式停点候选
    （当前位置、当前→MEC 中点），只保留专门机动候选（MEC 中心、环点、
    bearing 线段点）——定位必须专门机动，不复用既定路线。
    """
    center, radius = ch_state.mec
    ring_r = min(max(RING_R_FACTOR * radius, RING_MIN_R), RING_MAX_R)
    cands = [center]
    for k in range(RING_POINTS):
        ang = 2.0 * math.pi * k / RING_POINTS
        cands.append((center[0] + ring_r * math.cos(ang),
                      center[1] + ring_r * math.sin(ang)))
    if opportunistic_reuse:
        cands.append(((position[0] + center[0]) / 2.0,
                      (position[1] + center[1]) / 2.0))
        cands.append((position[0], position[1]))
    # 最近 bearing 观测位置 → 中心线段上的两点
    dirs = [obs["position"] for obs in ch_state.observations
            if obs["result"] == "direction"]
    if dirs:
        s1 = dirs[-1]
        for t in (0.4, 0.7):
            cands.append((s1[0] + t * (center[0] - s1[0]),
                          s1[1] + t * (center[1] - s1[1])))
    # 过滤：历史测点附近（结果确定复现，无信息）与黑名单
    prev = _measured_positions(ch_state)
    failed = failed_points or set()
    out = []
    for p in cands:
        key = (round(p[0], 3), round(p[1], 3))
        if key in failed:
            continue
        if any(math.hypot(p[0] - q[0], p[1] - q[1]) < DUP_POINT_EPS
               for q in prev):
            continue
        out.append(p)
    return out


def fixed_geometry_point(ch_state, position):
    """A1 baseline（Q2 式固定几何选点）：唯一改变观测点选择规则。

    定义：取可行域 MEC 中心 c；若已有 bearing 观测，沿最近一次 bearing
    方向的垂直方向从 c 偏移 d = min(300, 0.5·R_MEC) 米（取使基线最大的
    一侧——远离最近 bearing 观测点的一侧）；无 bearing 时直接用 c。
    不评估信息量，不自适应——固定规则。
    """
    center, radius = ch_state.mec
    d = min(300.0, 0.5 * radius)
    dirs = [obs for obs in ch_state.observations
            if obs["result"] == "direction"]
    if not dirs or d <= 1e-9:
        return center
    last = dirs[-1]
    theta = math.radians(last["bearing"])     # 观测点 → 源方向
    # 垂直方向两侧候选
    px, py = -math.sin(theta), math.cos(theta)
    c1 = (center[0] + d * px, center[1] + d * py)
    c2 = (center[0] - d * px, center[1] - d * py)
    last = dirs[-1]
    s_pos = last["position"]
    if math.hypot(c1[0] - s_pos[0], c1[1] - s_pos[1]) >= \
            math.hypot(c2[0] - s_pos[0], c2[1] - s_pos[1]):
        return c1
    return c2


def choose_observation(ks, active_channels, position, current_channel,
                       approach_tracker=None, failed_points=None,
                       mode=NBV_GAIN_MODE, tau=0.0, candidate_sink=None,
                       nbv_rule="nbv", opportunistic_reuse=True,
                       ml_ranker=None):
    """在 ACTIVE 频道中选 {"channel","point","score",...}，最大化 gain/cost。

    gain 口径由 mode 决定（默认 ΔR_MEC）。可直达确认的频道只评 MEC 中心
    （直达式确认，用精确 nbv_score）；其余频道评全部候选点（粗近似评价 +
    上界剪枝）。无可评候选返回 None（调度层据此转 FALLBACK_CLEAR）。

    tau（Addendum B.1 C 类参数）：候选得分 score = gain/cost < tau 时不予
    接受。默认 0.0 = 既有隐式行为（任何非负收益候选都参与竞争）。
    nbv_rule="fixed_geometry"（A1 baseline）：每频道候选收缩为
    fixed_geometry_point 单点（Q2 式固定几何选点），频道间仍按同一
    gain/cost 机制比较——唯一改变是观测点选择规则。
    candidate_sink：可选回调 fn(list_of_dict)，接收全部已评候选的
    {channel, point, gain, cost, score, kind}（decision_trace 证据用，
    不影响决策）。
    ml_ranker：Q3 实验支线的可选离线排序器。启用时只改变已评候选的
    选择顺序；候选生成、tau 门槛、几何状态更新和证书判定均不变。
    """
    best = None  # (pick_key, channel_id, point, info, approach_only)
    evaluated = [] if candidate_sink is not None else None
    ml_candidates = []
    for ch in active_channels:
        if ch.feasible_region is None:
            continue
        # 精确上界剪枝：radius 模式 gain ≤ R_MEC(P)，diameter 模式 gain ≤ D(P)
        bound = ch.mec_radius if mode == "radius" \
            else diameter_value(ch.feasible_region)
        approach_only = approach_tracker is not None \
            and approach_tracker.eligible(ch)
        if nbv_rule == "fixed_geometry":
            # A1 baseline：观测点选择规则整体替换为固定几何规则
            # （含直达确认点——点选择是被消融的唯一模块；完成性由兜底保证）
            p = fixed_geometry_point(ch, position)
            prev = _measured_positions(ch)
            failed = (failed_points or {}).get(ch.channel_id) or set()
            dup = any(math.hypot(p[0] - q[0], p[1] - q[1]) < DUP_POINT_EPS
                      for q in prev)
            blacklisted = (round(p[0], 3), round(p[1], 3)) in failed
            cands = [] if (dup or blacklisted) else [p]
            approach_only = False
        elif approach_only:
            cands = [approach_tracker.confirm_point(ch)]
        else:
            cands = candidate_points(
                ch, position,
                failed_points=(failed_points or {}).get(ch.channel_id),
                opportunistic_reuse=opportunistic_reuse)
        for S in cands:
            move = math.hypot(S[0] - position[0], S[1] - position[1])
            cost = move / C.MOVE_SPEED + C.MEASURE_TIME
            if ch.channel_id != current_channel:
                cost += C.SWITCH_TIME
            if ml_ranker is None and best is not None \
                    and bound / cost <= best[0][0]:
                continue
            if approach_only:
                info = nbv_score(ch.feasible_region, S, cost=cost,
                                 step_deg=_adaptive_step(
                                     ch.feasible_region, S),
                                 mode=mode)
            else:
                worst = _eval_worst(ch.feasible_region, S,
                                    _adaptive_step(ch.feasible_region, S),
                                    mode=mode)
                gain = bound - worst
                info = {"gain": gain, "cost": cost,
                        "score": gain / max(cost, 1e-9),
                        "worst_diameter": worst if mode == "diameter" else None,
                        "worst_radius": worst if mode == "radius" else None,
                        "worst_bearing": None, "mode": mode}
            if evaluated is not None:
                evaluated.append({
                    "channel": ch.channel_id,
                    "point": [float(S[0]), float(S[1])],
                    "gain": float(info["gain"]), "cost": float(info["cost"]),
                    "score": float(info["score"]),
                    "kind": "approach" if approach_only else "nbv",
                })
            if info["score"] < tau:
                continue                       # C 类参数 τ：机会式观测收益阈值
            if ml_ranker is not None:
                ml_candidates.append({
                    "channel": ch.channel_id,
                    "point": [float(S[0]), float(S[1])],
                    "gain": float(info["gain"]),
                    "cost": float(info["cost"]),
                    "score": float(info["score"]),
                    "kind": "approach" if approach_only else "nbv",
                    "mode": mode,
                })
                continue
            pick = (info["score"], -cost)
            if best is None or pick > best[0]:
                best = (pick, ch.channel_id, S, info, approach_only)
    if candidate_sink is not None:
        candidate_sink(evaluated)
    if ml_ranker is not None:
        choice = select_q3_candidate(ml_ranker, ml_candidates, position)
        if not choice:
            return None
        return {
            "channel": choice["channel"],
            "point": (float(choice["point"][0]),
                      float(choice["point"][1])),
            "score": choice["score"],
            "gain": choice["gain"],
            "cost": choice["cost"],
            "kind": choice["kind"],
            "mode": choice.get("mode", mode),
            "ml_score": choice.get("ml_score"),
            "takeover": choice.get("takeover", False),
            "takeover_reason": choice.get("takeover_reason"),
            "ml_margin": choice.get("ml_margin"),
        }
    if best is None:
        return None
    _, cid, S, info, approach_only = best
    return {
        "channel": cid,
        "point": (float(S[0]), float(S[1])),
        "score": info["score"],
        "gain": info["gain"],
        "cost": info["cost"],
        "kind": "approach" if approach_only else "nbv",
        "mode": mode,
    }
