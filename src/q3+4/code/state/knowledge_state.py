# -*- coding: utf-8 -*-
"""KnowledgeState：全部 20 个频道的知识状态 K_t 管理。

全局完成判定（严格停止条件）：
- 全部频道 CLEARED ∨ CERTIFIED_ABSENT ⇒ 完成；
- CLEARED 数达到 MAX_SOURCES = 16 ⇒ 立即完成（零风险早停，
  因为源总数 ≤ 16，其余频道必无源）。
"""

from geometry import constants as C
from state.channel_state import ChannelState, ChannelStatus


class KnowledgeState:
    """20 频道的集合知识状态聚合。"""

    def __init__(self, mode="Q3", q4_certificate_layout="lattice31"):
        self.mode = mode
        self.q4_certificate_layout = q4_certificate_layout
        self.channels = {
            cid: ChannelState(cid, mode=mode,
                              q4_certificate_layout=q4_certificate_layout)
            for cid in range(1, C.NUM_CHANNELS + 1)
        }

    def __getitem__(self, channel_id):
        return self.channels[channel_id]

    # ------------------------------------------------------------------
    # 状态分组
    # ------------------------------------------------------------------

    def by_status(self, status):
        return [ch for ch in self.channels.values() if ch.status == status]

    @property
    def cleared(self):
        return self.by_status(ChannelStatus.CLEARED)

    @property
    def certified_absent(self):
        return self.by_status(ChannelStatus.CERTIFIED_ABSENT)

    @property
    def ready(self):
        return self.by_status(ChannelStatus.READY)

    @property
    def active(self):
        return self.by_status(ChannelStatus.ACTIVE)

    @property
    def unknown(self):
        return self.by_status(ChannelStatus.UNKNOWN)

    # ------------------------------------------------------------------
    # 全局完成判定
    # ------------------------------------------------------------------

    def is_complete(self):
        """严格停止条件或 16 源早停。"""
        if len(self.cleared) >= C.MAX_SOURCES:
            return True
        return all(ch.status in (ChannelStatus.CLEARED,
                                 ChannelStatus.CERTIFIED_ABSENT)
                   for ch in self.channels.values())

    def summary(self):
        counts = {s.value: 0 for s in ChannelStatus}
        for ch in self.channels.values():
            counts[ch.status.value] += 1
        counts["complete"] = self.is_complete()
        return counts

    def refresh_all_certificates(self):
        """对所有未终结频道刷新证书状态（Q3 圆盘覆盖）。"""
        for ch in self.channels.values():
            ch.refresh_certificate()
