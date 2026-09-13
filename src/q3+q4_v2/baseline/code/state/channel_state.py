# -*- coding: utf-8 -*-
"""频道状态 ChannelState：单个频道的可行域、证书区域与状态机。

状态机：UNKNOWN → ACTIVE → READY → CLEARED
        UNKNOWN/ACTIVE → CERTIFIED_ABSENT（覆盖证书成立后；
        或 FALLBACK_CLEAR 序列走完后保守收尾，basis="fallback_exhausted"）

观测更新（narrative 第 4 节）：
- direction : P_c ← P_c ∩ W(S, θ̂, ±1°) ∩ B(S, 1500)
- no_signal : 记录检测点；Q3 下 B(S,1000) 为排除圆（覆盖判定在证书模块）
- near      : 进入 READY，clear_position = 当前位置
清除判据（narrative 第 5 节）：R_MEC(P_c) ≤ 20 ⇒ READY，clear_position = MEC 圆心
（调度层实际清除点改用 Z_c 最近点，见 scheduler._clear_target，评审第 5 点）
"""

from enum import Enum

from geometry import constants as C
from geometry.mec import mec
from geometry.polygon import omega_polygon, area
from geometry.wedge import wedge_intersect
from geometry.certificate import (
    q3_certified,
    q4_channel_certified,
    q4_channel_certified_lattice,
)
from geometry.q4_sparse_mesh import q4_channel_certified_sparse25


class ChannelStatus(Enum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    READY = "READY"
    CLEARED = "CLEARED"
    CERTIFIED_ABSENT = "CERTIFIED_ABSENT"


class ChannelState:
    """单个频道的集合知识状态 K_c(t) = (P_c, C_c, σ_c)。"""

    def __init__(self, channel_id, mode="Q3",
                 q4_certificate_layout="lattice31"):
        if not (1 <= channel_id <= C.NUM_CHANNELS):
            raise ValueError("channel_id must be in 1..%d" % C.NUM_CHANNELS)
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        if q4_certificate_layout not in ("lattice31", "sparse25"):
            raise ValueError("q4_certificate_layout must be 'lattice31' or "
                             "'sparse25'")
        self.channel_id = int(channel_id)
        self.mode = mode
        self.q4_certificate_layout = q4_certificate_layout
        # 可行域：Ω 的外切正多边形（真实可行域的保守超集）
        self.feasible_region = omega_polygon()
        # 证书区域：no_signal 检测点列表（Q3 排除圆心 / Q4 见证点）
        self.certificate_region = []
        # Q4: 已通过 δ-稳健凸包证书的格点中心列表
        self.certified_centers = []
        # E4: 累计登记数与最终保留数分离；剪枝不回退原始工作量。
        self.q4_certified_centers_raw_count = 0
        self.status = ChannelStatus.UNKNOWN
        self.observations = []
        self.mec = None           # (center, radius)
        self.clear_position = None
        # CERTIFIED_ABSENT 依据："certificate"（覆盖证书）/
        # "fallback_exhausted"（兜底序列走完，观测矛盾保守收尾）
        self.absent_basis = None
        self._update_mec()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _update_mec(self):
        center, radius = mec(self.feasible_region)
        self.mec = (center, radius)
        return radius

    def _record(self, position, result, virtual_time, bearing=None):
        self.observations.append({
            "position": (float(position[0]), float(position[1])),
            "channel": self.channel_id,
            "result": result,
            "bearing": bearing,
            "virtual_time": float(virtual_time),
        })

    # ------------------------------------------------------------------
    # 观测更新
    # ------------------------------------------------------------------

    def update_direction(self, position, bearing_deg, virtual_time):
        """direction 观测：P_c ← P_c ∩ W(S,θ̂) ∩ B(S,1500)。

        交集为空时抛 ValueError（观测与既有可行域矛盾，属异常工况，
        调用方必须显式处理，禁止静默吞掉）。
        更新后若 R_MEC ≤ 20 m 自动进入 READY 并设 clear_position 为 MEC 圆心。
        """
        if self.status in (ChannelStatus.CLEARED,
                           ChannelStatus.CERTIFIED_ABSENT):
            return self.status
        new_region = wedge_intersect(self.feasible_region, position,
                                     bearing_deg)
        if new_region is None:
            raise ValueError(
                "direction observation inconsistent with feasible region "
                "(channel %d @ %s, bearing %.3f)" %
                (self.channel_id, position, bearing_deg))
        self.feasible_region = new_region
        self._record(position, "direction", virtual_time,
                     bearing=float(bearing_deg) % 360.0)
        if self.status == ChannelStatus.UNKNOWN:
            self.status = ChannelStatus.ACTIVE
        r = self._update_mec()
        if r <= C.CLEAR_RADIUS and self.status != ChannelStatus.READY:
            self.status = ChannelStatus.READY
            self.clear_position = self.mec[0]
        return self.status

    def update_no_signal(self, position, virtual_time):
        """no_signal 观测：记录排除证据点。

        Q3：B(S,1000) 加入排除区域（覆盖判定由证书模块/refresh_certificate
        完成）。Q4：作为见证点积累，供 δ-稳健凸包证书使用。
        """
        if self.status in (ChannelStatus.CLEARED,
                           ChannelStatus.CERTIFIED_ABSENT):
            return self.status
        p = (float(position[0]), float(position[1]))
        self.certificate_region.append(p)
        self._record(p, "no_signal", virtual_time)
        return self.status

    def update_near(self, position, virtual_time):
        """near 观测：源距当前位置 ≤ 5 m，直接进入 READY。"""
        if self.status in (ChannelStatus.CLEARED,
                           ChannelStatus.CERTIFIED_ABSENT):
            return self.status
        p = (float(position[0]), float(position[1]))
        self._record(p, "near", virtual_time)
        self.status = ChannelStatus.READY
        self.clear_position = p
        return self.status

    def mark_cleared(self, virtual_time):
        """清除成功：进入 CLEARED（终态）。"""
        self._record(self.clear_position if self.clear_position else (0.0, 0.0),
                     "cleared", virtual_time)
        self.status = ChannelStatus.CLEARED
        return self.status

    # ------------------------------------------------------------------
    # 证书
    # ------------------------------------------------------------------

    def refresh_certificate(self):
        """根据累计 no_signal 证据刷新证书状态。

        Q3：Ω ⊆ ∪B(S_i,1000) ⇒ CERTIFIED_ABSENT。
        Q4（v2.1，评审第 3 点）：满足任一即 CERTIFIED_ABSENT——
          (a) 31 点三角格点全部 no_signal（q4_channel_certified_lattice，
              充分扫描证书，与朝向/R_eff 无关）；
          (b) Ω ⊆ ∪_{certified x_i} B(x_i,δ)（δ-稳健凸包机会式早证，
              逐格点证书由 policy 层调用 q4_certify_point 后经
              add_q4_certified_center 累积，此处只做频道级覆盖判定）。
        """
        if self.status in (ChannelStatus.CLEARED,
                           ChannelStatus.CERTIFIED_ABSENT):
            return self.status
        # 已获得 direction 的频道（ACTIVE/READY）说明源存在，不做缺席证书
        if self.status in (ChannelStatus.ACTIVE, ChannelStatus.READY):
            return self.status
        if self.mode == "Q3":
            res = q3_certified(self.certificate_region)
            if res["certified"]:
                self.status = ChannelStatus.CERTIFIED_ABSENT
                self.absent_basis = "certificate"
        else:
            if self.q4_certificate_layout == "sparse25":
                if q4_channel_certified_sparse25(self.certificate_region):
                    self.status = ChannelStatus.CERTIFIED_ABSENT
                    self.absent_basis = "sparse25"
            elif q4_channel_certified_lattice(self.certificate_region):
                self.status = ChannelStatus.CERTIFIED_ABSENT
                self.absent_basis = "lattice31"
            if self.status == ChannelStatus.UNKNOWN and \
                    self.certified_centers and q4_channel_certified(
                        self.certified_centers)["certified"]:
                self.status = ChannelStatus.CERTIFIED_ABSENT
                self.absent_basis = "certificate"
        return self.status

    def force_certified_absent(self, virtual_time, reason):
        """FALLBACK_CLEAR 序列走完仍未清除 ⇒ 观测矛盾，保守收尾。

        记 anomaly 由调度层完成；此处显式转移状态并记录依据，
        不得静默（observations 中留 result="fallback_exhausted" 痕迹）。
        """
        if self.status in (ChannelStatus.CLEARED,
                           ChannelStatus.CERTIFIED_ABSENT):
            return self.status
        self._record((0.0, 0.0), "fallback_exhausted", virtual_time)
        self.status = ChannelStatus.CERTIFIED_ABSENT
        self.absent_basis = "fallback_exhausted"
        return self.status

    def add_q4_certified_center(self, x):
        """Q4：登记一个通过 δ-稳健凸包证书的格点中心。"""
        self.certified_centers.append((float(x[0]), float(x[1])))
        self.q4_certified_centers_raw_count += 1

    def retain_q4_certified_centers(self, centers):
        """E4：以已独立确认的精确覆盖子集替换当前保留中心。"""
        self.certified_centers = [(float(x[0]), float(x[1]))
                                  for x in centers]

    # ------------------------------------------------------------------
    # 便捷查询
    # ------------------------------------------------------------------

    @property
    def feasible_area(self):
        return area(self.feasible_region)

    @property
    def mec_radius(self):
        return self.mec[1] if self.mec else float("inf")

    @property
    def clearable(self):
        """是否满足 MEC 清除判据（或已 near）。"""
        return self.status == ChannelStatus.READY

    def to_dict(self):
        return {
            "channel_id": self.channel_id,
            "mode": self.mode,
            "q4_certificate_layout": self.q4_certificate_layout,
            "status": self.status.value,
            "feasible_region": self.feasible_region,
            "certificate_region": list(self.certificate_region),
            "certified_centers": list(self.certified_centers),
            "q4_certified_centers_raw_count":
                self.q4_certified_centers_raw_count,
            "q4_certified_centers_retained_count":
                len(self.certified_centers),
            "mec": {"center": self.mec[0], "radius": self.mec[1]}
            if self.mec else None,
            "clear_position": self.clear_position,
            "absent_basis": self.absent_basis,
            "observations": list(self.observations),
        }
