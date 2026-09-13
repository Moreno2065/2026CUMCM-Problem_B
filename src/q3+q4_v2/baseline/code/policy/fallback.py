# -*- coding: utf-8 -*-
"""FALLBACK_CLEAR：有限步清除兜底（评审第 1 点，完成性补丁）。

动机：Q4 定向频道在 MEC 圆心/候选点上可能持续 no_signal（源背对检测点），
没有任何量保证必减；ACTIVE > CERTIFICATE 的固定优先级下可能拖住任务。

机制（频道级状态，最高优先级，不被其他频道打断）：
1. 有效收缩跟踪：对 ACTIVE 频道每次主频道测量，R_MEC 相对上次测量
   下降 ≥ SHRINK_MIN_RATIO（10%）计为有效；连续 K=NO_SHRINK_LIMIT（3）
   次测量无有效收缩（含 no_signal、几何矛盾的 direction）→ 进入兜底。
2. 进展预算：ACTIVE 频道主频道测量次数超 PROGRESS_MEASURE_BUDGET
   仍未 READY → 强制转兜底。结合 1，任何 ACTIVE 频道有限步内终止
   （预算内要么 READY，要么触发兜底；兜底点数有限，见下）。
3. 兜底执行：用 disk_lattice_cover（半径 20 m 圆盘三角格点，间距
   20√3 ≈ 34.641 m 无缝覆盖）覆盖该频道当前可行域，贪心最近邻排序后
   逐个 /clear。光学清除不受朝向影响 ⇒ 源在可行域内必被某点清除。
   - 成功 ⇒ CLEARED（ ChannelState.mark_cleared，runner 正常流程）；
   - 序列走完仍未清除 ⇒ 可行域与观测矛盾：记 anomaly，频道标记
     CERTIFIED_ABSENT（basis="fallback_exhausted"，保守收尾，不得静默）。
4. Q3 直达链矛盾工况接入：MEC 圆心连续 2 次 no_signal（理论上不可能）
   → 同款兜底。

点数记录：触发时记录估计值（面积/单盘有效覆盖面积）与实际格点数，
供报告对账（首测后楔形扇区面积约 3.9 万 m² ⇒ 最坏约 38 点）。
"""

import math

from geometry import constants as C
from geometry.fallback_cover import (
    disk_lattice_cover,
    order_greedy,
    cover_point_estimate,
)
from geometry.polygon import area
from .approach import Q3_CENTER_NO_SIGNAL_LIMIT

SHRINK_MIN_RATIO = 0.10      # R_MEC 相对上次测量下降 ≥10% 计有效收缩
NO_SHRINK_LIMIT = 3          # 连续 K 次无有效收缩 → 兜底
PROGRESS_MEASURE_BUDGET = 24  # ACTIVE 频道主频道测量进展预算（次）


class FallbackTracker:
    """ACTIVE 频道有效收缩跟踪 + FALLBACK_CLEAR 序列管理（策略侧）。"""

    def __init__(self):
        # channel_id -> {"last_r", "no_shrink", "n_measures"}
        self._progress = {}
        # channel_id -> {"points", "index", "estimate", "region_area",
        #                "trigger", "used"}
        self._fallback = {}
        self.records = []      # 已结束的兜底记录（触发/结果/点数）

    # ------------------------------------------------------------------
    # 进展跟踪
    # ------------------------------------------------------------------

    def _pg(self, channel_id):
        return self._progress.setdefault(channel_id, {
            "last_r": None, "no_shrink": 0, "n_measures": 0})

    def in_fallback(self, channel_id):
        return channel_id in self._fallback

    def note_measure(self, ch_state, r_before, r_after, signal):
        """登记一次 ACTIVE 频道主频道测量，返回触发的 anomaly str 或 None。

        signal: bool，本次测量是否返回 direction/near（no_signal 或
        几何矛盾为 False）。READY/CLEARED/CERTIFIED_ABSENT 频道不再跟踪。
        """
        if ch_state.status.value != "ACTIVE":
            return None
        cid = ch_state.channel_id
        if cid in self._fallback:
            return None
        pg = self._pg(cid)
        pg["n_measures"] += 1
        effective = False
        if signal and pg["last_r"] is not None and pg["last_r"] > 0:
            effective = r_after <= pg["last_r"] * (1.0 - SHRINK_MIN_RATIO) \
                + 1e-9
        elif signal and pg["last_r"] is None:
            effective = True      # 首次测量（发现）计为有效
        pg["no_shrink"] = 0 if effective else pg["no_shrink"] + 1
        pg["last_r"] = r_after
        if pg["no_shrink"] >= NO_SHRINK_LIMIT:
            return ("channel %d: %d consecutive measures without effective "
                    "shrink (>=10%% R_MEC drop)" % (cid, pg["no_shrink"]))
        if pg["n_measures"] > PROGRESS_MEASURE_BUDGET:
            return ("channel %d: ACTIVE progress budget exceeded "
                    "(%d measures without READY)"
                    % (cid, pg["n_measures"]))
        return None

    def note_q3_center_no_signal(self, ch_state, consecutive):
        """Q3 MEC 圆心连续 no_signal（矛盾工况）计数，达限返回触发原因。"""
        if consecutive >= Q3_CENTER_NO_SIGNAL_LIMIT:
            return ("channel %d: Q3 MEC-center no_signal x%d "
                    "(theoretically impossible)"
                    % (ch_state.channel_id, consecutive))
        return None

    # ------------------------------------------------------------------
    # 兜底序列
    # ------------------------------------------------------------------

    def enter_fallback(self, ch_state, position, trigger):
        """为频道生成兜底清除点序列。返回记录 dict（含估计/实际点数）。"""
        cid = ch_state.channel_id
        poly = ch_state.feasible_region
        points = order_greedy(disk_lattice_cover(poly), position)
        rec = {
            "channel": cid,
            "trigger": trigger,
            "region_area": area(poly) if poly else 0.0,
            "estimated_points": cover_point_estimate(poly),
            "n_points": len(points),
            "used": 0,
            "result": None,          # "cleared" / "exhausted"
            # 复核快照（exhausted 时 verify_fallback_cover 用）
            "region": [tuple(v) for v in poly] if poly else None,
            "points": [tuple(p) for p in points],
        }
        self._fallback[cid] = {
            "points": points, "index": 0, "record": rec,
        }
        return rec

    def next_point(self, channel_id):
        """当前兜底点；序列走完返回 None。"""
        st = self._fallback.get(channel_id)
        if st is None or st["index"] >= len(st["points"]):
            return None
        return st["points"][st["index"]]

    def on_clear_result(self, ch_state, success):
        """登记兜底 /clear 结果。

        成功：结束兜底（CLEARED 由 runner 流程完成）。
        失败：推进到下一点；序列走完返回 "exhausted"。
        返回 None（继续）/ "cleared" / "exhausted"。
        """
        cid = ch_state.channel_id
        st = self._fallback.get(cid)
        if st is None:
            return None
        st["record"]["used"] += 1
        used = st["record"]["used"]
        if success:
            st["record"]["result"] = "cleared"
            self.records.append(st["record"])
            del self._fallback[cid]
            self._progress.pop(cid, None)
            return "cleared"
        st["index"] += 1
        if st["index"] >= len(st["points"]):
            st["record"]["result"] = "exhausted"
            self.records.append(st["record"])
            del self._fallback[cid]
            return "exhausted"
        return None

    def finish(self, channel_id):
        """频道因其他原因终结（如 near READY/CLEARED）时清理跟踪状态。"""
        st = self._fallback.pop(channel_id, None)
        if st is not None and st["record"]["result"] is None:
            st["record"]["result"] = "resolved_externally"
            self.records.append(st["record"])
        self._progress.pop(channel_id, None)

    def active_fallbacks(self):
        return list(self._fallback.keys())

    def index_total(self, channel_id):
        """当前兜底进度 (index, total)；不在兜底返回 None。"""
        st = self._fallback.get(channel_id)
        if st is None:
            return None
        return (st["index"], len(st["points"]))

    def progress(self, channel_id):
        return dict(self._pg(channel_id))
