"""Adaptive three-ray clear corridor experiment.

This module is deliberately separate from the default schedulers so its cost
can be compared honestly. It is safe under the stated ±1° bearing bound but
may be slower than the inherited feasible-region fallback on some cases.
"""
from __future__ import annotations

import math

from state.channel_state import ChannelStatus


class AdaptiveClearMixin:
    """Clear center ray, then boundary rays, using a 20 m radial grid."""

    def _init_adaptive_clear(self):
        self._adaptive_clear_queue = {}

    def _maybe_schedule_clear(self, ch_state, result, position):
        if result != "direction" or ch_state.status != ChannelStatus.ACTIVE:
            return
        cid = ch_state.channel_id
        if cid in self._adaptive_clear_queue or position is None:
            return
        dirs = [obs for obs in ch_state.observations if obs["result"] == "direction"]
        if len(dirs) != 1:
            return
        bearing = dirs[-1]["bearing"]
        points = []
        for offset, reverse in ((0.0, False), (-1.0, True), (1.0, False)):
            theta = math.radians(bearing + offset)
            ux, uy = math.cos(theta), math.sin(theta)
            radii = range(76 - 1, -1, -1) if reverse else range(76)
            points.extend((position[0] + 20.0 * i * ux,
                           position[1] + 20.0 * i * uy) for i in radii)
        self._adaptive_clear_queue[cid] = points

    def on_measure_result(self, ch_state, result, r_before, r_after,
                          was_approach, position=None):
        super().on_measure_result(ch_state, result, r_before, r_after,
                                  was_approach, position=position)
        self._maybe_schedule_clear(ch_state, result, position)

    def on_scan_measure_result(self, ch_state, result, position=None):
        self._maybe_schedule_clear(ch_state, result, position)

    def _next_adaptive_clear(self, ks):
        for cid in sorted(list(self._adaptive_clear_queue)):
            queue = self._adaptive_clear_queue[cid]
            if ks[cid].status == ChannelStatus.CLEARED or not queue:
                self._adaptive_clear_queue.pop(cid, None)
                continue
            return cid, queue.pop(0)
        return None

    def on_clear_failure(self, channel_id):
        if channel_id in self._adaptive_clear_queue:
            self.anomalies.append("adaptive corridor miss channel %d" % channel_id)
            return True
        return super().on_clear_failure(channel_id)
