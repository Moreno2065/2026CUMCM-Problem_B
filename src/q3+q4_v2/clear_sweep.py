"""Guaranteed clear corridor after one valid bearing."""
from __future__ import annotations

import math

from state.channel_state import ChannelStatus


class ClearSweepMixin:
    """Use a three-ray, 20 m radial clear corridor.

    A positive measurement places the source at distance <=1500 m and true
    bearing within one degree of the reported bearing. At any range d<=1500,
    one of {-1,0,+1} degree rays differs by at most 0.5 degree; a 20 m radial
    grid adds at most 10 m. The worst distance is therefore
    sqrt(10^2 + (1500*sin(.5deg))^2) < 20 m. Clear is orientation-independent,
    so the same argument applies to Q4 directional sources.
    """

    def _init_clear_sweep(self):
        self._clear_sweep_queue = {}

    def _schedule_clear_sweep(self, ch_state, result, position):
        if result != "direction" or ch_state.status != ChannelStatus.ACTIVE:
            return
        cid = ch_state.channel_id
        if cid in self._clear_sweep_queue:
            return
        directions = [obs for obs in ch_state.observations
                      if obs["result"] == "direction"]
        if len(directions) != 1 or position is None:
            return
        bearing = directions[-1]["bearing"]
        points = []
        # Keep the center ray first for typical small bearing error, then the
        # two boundary rays. A bounded radial grid gives the guarantee above.
        for offset in (0.0, -1.0, 1.0):
            theta = math.radians(bearing + offset)
            ux, uy = math.cos(theta), math.sin(theta)
            for i in range(76):
                distance = 20.0 * i
                points.append((position[0] + distance * ux,
                               position[1] + distance * uy))
        self._clear_sweep_queue[cid] = points

    def on_measure_result(self, ch_state, result, r_before, r_after,
                          was_approach, position=None):
        super().on_measure_result(ch_state, result, r_before, r_after,
                                  was_approach, position=position)
        self._schedule_clear_sweep(ch_state, result, position)

    def on_scan_measure_result(self, ch_state, result, position=None):
        self._schedule_clear_sweep(ch_state, result, position)

    def _next_clear_sweep(self, ks):
        for cid in sorted(list(self._clear_sweep_queue)):
            queue = self._clear_sweep_queue.get(cid, [])
            if ks[cid].status == ChannelStatus.CLEARED or not queue:
                self._clear_sweep_queue.pop(cid, None)
                continue
            return cid, queue.pop(0)
        return None

    def on_clear_failure(self, channel_id):
        if channel_id in self._clear_sweep_queue:
            self.anomalies.append("clear corridor miss channel %d" % channel_id)
            return True
        return super().on_clear_failure(channel_id)
