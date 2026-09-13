# -*- coding: utf-8 -*-
"""直达式定位确认：Q3 确定性 MEC 收敛链（评审第 2 点，v2.1 重构）。

数学依据（写入修订文档 v2.1）：
- 首次 direction 后，可行域 ⊆ 半角 1° 楔形 ∩ B(S, 1500)。该扇形的 MEC
  半径为 R0 = 1500/(2·cos1°) ≈ 750.114 m（扇形三极值点 S、两外角的
  最小覆盖圆）。
- Q3 全向源：走到当前可行域 MEC 圆心 c，dist(c, 真源) ≤ R_MEC ≤
  750.114 < 1000 ≤ R_eff ⇒ 下一次测量**必然**返回 direction 或 near
  （全向源无覆盖角约束）。
- 在 MEC 圆心再测得 direction：新可行域 ⊆ B(c, R_k) ∩ 半角 1° 楔形，
  同上扇形论证得 R_{k+1} ≤ R_k/(2·cos1°)，q = 1/(2cos1°) ≈ 0.50008。
- 归纳：首次测向后最多再取 ⌈ln(750.114/20)/ln(2cos1°)⌉ = 6 次方向观测，
  必达 R_MEC ≤ 20（READY）。near 更早结束。

Q3 确定性流程（替代 v2.0"首次发现后必须先有效交会"的限制）：
    发现（首次 direction/near）
    → 循环【移到当前可行域 MEC 圆心 → 测量】
        direction ⇒ 可行域收缩（沿用 ChannelState.update_direction）
        near      ⇒ READY（clear_position = 当前点）
        no_signal ⇒ Q3 下理论不可能的矛盾工况：记 anomaly、可行域保持不变、
                    连续计数；连续 2 次 → 对该频道走 Q4 同款有限步兜底
                    （FALLBACK_CLEAR，见 policy.fallback）
    → R_MEC ≤ 20 ⇒ READY（ChannelState 自动转移）

Q4 定向频道：MEC 圆心无信号保证（圆心可能在覆盖半平面外），不强制直达；
沿用候选环收缩（localization NBV），并接入 FALLBACK_CLEAR 兜底。
has_valid_intersection 保留供 Q4 门控与外部复核使用。

NBV/机会式观测保留为 ACTIVE 频道的并行优化（跨频道选择与 Q4 主路径），
Q3 直达链本身不依赖它。
"""

import math

from geometry import constants as C

# q = 1/(2 cos 1°) ≈ 0.50008（每步收缩上界）
CONTRACTION_Q = 0.5 / math.cos(math.radians(C.BEARING_ERROR_DEG))

# 首次 direction 后的扇形 MEC 半径上界：R0 = 1500/(2 cos 1°) ≈ 750.114 m
FIRST_BEARING_RADIUS_BOUND = C.R_EFF_MAX * CONTRACTION_Q

# 有效交会的最小基线：两次 bearing 观测位置间距（米）
MIN_BASELINE_M = 1.0

# Q3 直达链 MEC 圆心 no_signal 连续次数上限（理论不可能工况）：
# 超过即转入 FALLBACK_CLEAR
Q3_CENTER_NO_SIGNAL_LIMIT = 2


def compute_budget(R0, clear_radius=C.CLEAR_RADIUS):
    """确认步数预算 ⌈ln(R0/20)/ln(2 cos 1°)⌉（≥1）。

    R0 = 750.114（首测后扇形上界）时预算 = 6。
    """
    if R0 <= clear_radius:
        return 0
    n = math.log(R0 / clear_radius) / math.log(2.0 * math.cos(
        math.radians(C.BEARING_ERROR_DEG)))
    return max(1, int(math.ceil(n - 1e-12)))


def direction_positions(ch_state):
    """该频道全部 direction 观测位置列表。"""
    return [obs["position"] for obs in ch_state.observations
            if obs["result"] == "direction"]


def has_valid_intersection(ch_state, min_baseline=MIN_BASELINE_M):
    """是否存在有效交会：≥2 次不同位置的 bearing 且可行域非空有界。

    Q4 门控保留使用；Q3 直达链自 v2.1 起不再需要（单 bearing 后
    MEC 圆心必有信号）。
    """
    pos = direction_positions(ch_state)
    if len(pos) < 2 or ch_state.feasible_region is None:
        return False
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            if math.hypot(pos[i][0] - pos[j][0],
                          pos[i][1] - pos[j][1]) >= min_baseline:
                return True
    return False


class ApproachTracker:
    """每个 ACTIVE 频道的直达确认状态（纯策略侧，不碰数学状态）。"""

    def __init__(self, mode):
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        self.mode = mode
        self._state = {}  # channel_id -> dict

    def _st(self, channel_id):
        return self._state.setdefault(channel_id, {
            "steps": 0,            # 已执行的 MEC 中心确认次数
            "R0": None,            # 进入直达确认时的初始半径
            "budget": None,        # 预算步数
            "cooldown_obs": 0,     # Q4 冷却：direction 观测数须超过该值才解除
            "center_no_signal": 0,  # Q3 MEC 圆心连续 no_signal 计数
            "history": [],         # [(R_before, R_after, ratio)]
            "over_budget_recorded": False,
        })

    def eligible(self, ch_state):
        """是否可执行直达确认（MEC 中心再测）。

        Q3：任何 ACTIVE 频道均可（首次 bearing 后 MEC 圆心距真源
            ≤ 750.114 < 1000 ≤ R_eff，必收信号）。
        Q4：需有效交会且不在冷却中（MEC 圆心无信号保证）。
        """
        if ch_state.status.value != "ACTIVE":
            return False
        if self.mode == "Q3":
            return True
        if not has_valid_intersection(ch_state):
            return False
        st = self._st(ch_state.channel_id)
        n_dir = len(direction_positions(ch_state))
        return n_dir > st["cooldown_obs"]

    def confirm_point(self, ch_state):
        """直达确认点 = 当前可行域 MEC 中心。"""
        return ch_state.mec[0]

    def q3_center_no_signal_count(self, channel_id):
        return self._st(channel_id)["center_no_signal"]

    def on_confirm(self, ch_state, result, r_before, r_after):
        """登记一次 MEC 中心确认的结果，返回需要记录的异常 str 或 None。

        result ∈ {"direction", "near", "no_signal"}。
        near 的 READY 转移由 ChannelState.update_near 完成，不在此处理。
        """
        st = self._st(ch_state.channel_id)
        anomaly = None
        if result == "no_signal":
            # 中心确认无信号：Q3 下与 dist(c, 源) ≤ R_MEC < R_eff 矛盾
            # （理论不可能工况）；Q4 下为合法（定向源覆盖半平面不含中心）。
            if self.mode == "Q3":
                st["center_no_signal"] += 1
                anomaly = ("approach no_signal at MEC center, channel %d "
                           "(Q3 contradiction, consecutive=%d, region kept)"
                           % (ch_state.channel_id, st["center_no_signal"]))
            else:
                # Q4：冷却至获得新 bearing
                st["cooldown_obs"] = len(direction_positions(ch_state))
                anomaly = ("approach no_signal at MEC center, channel %d "
                           "(degraded to NBV)" % ch_state.channel_id)
            return anomaly
        # 有效信号：复位 Q3 连续 no_signal 计数
        st["center_no_signal"] = 0
        if result == "direction":
            st["steps"] += 1
            if st["R0"] is None:
                st["R0"] = r_before
                st["budget"] = compute_budget(r_before)
            ratio = (r_after / r_before) if r_before > 0 else 0.0
            st["history"].append((r_before, r_after, ratio))
            if st["steps"] > st["budget"] and not st["over_budget_recorded"]:
                st["over_budget_recorded"] = True
                anomaly = ("approach over budget: channel %d steps=%d "
                           "budget=%d (continuing)"
                           % (ch_state.channel_id, st["steps"], st["budget"]))
        return anomaly

    def history(self, channel_id):
        return list(self._st(channel_id)["history"])

    def steps(self, channel_id):
        return self._st(channel_id)["steps"]

    def budget(self, channel_id):
        return self._st(channel_id)["budget"]
