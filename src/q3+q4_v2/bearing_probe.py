"""Shared observable bearing-probe behavior used by all three v2 policies."""
from __future__ import annotations

import math

from state.channel_state import ChannelStatus


class BearingProbeMixin:
    """Schedule three legal follow-up measurements after the first bearing.

    The mixin does not inspect simulator sources. It only uses the returned
    bearing and the current observable channel state. Subclasses decide when
    to call ``_next_bearing_probe``; their inherited fallback remains intact.
    """

    def _init_bearing_probe(self):
        self._bearing_probe_queue = {}

    def on_measure_result(self, ch_state, result, r_before, r_after,
                          was_approach, position=None):
        super().on_measure_result(ch_state, result, r_before, r_after,
                                  was_approach, position=position)
        self._record_first_bearing(ch_state, result, position)

    def on_scan_measure_result(self, ch_state, result, position=None):
        """Observe an opportunistic scan without invoking base scheduler hooks."""
        self._record_first_bearing(ch_state, result, position)

    def _record_first_bearing(self, ch_state, result, position):
        # Q3 omni sources are cheap to localize from the base geometry search;
        # the forward/side probes are reserved for Q4's visibility ambiguity.
        if getattr(self, "mode", None) == "Q3":
            return
        if result != "direction" or ch_state.status != ChannelStatus.ACTIVE:
            return
        cid = ch_state.channel_id
        n_direction = sum(obs["result"] == "direction"
                          for obs in ch_state.observations)
        if cid in self._bearing_probe_queue or n_direction != 1 or position is None:
            return
        theta = math.radians(ch_state.observations[-1]["bearing"])
        ux, uy = math.cos(theta), math.sin(theta)
        nx, ny = -uy, ux
        sx, sy = position
        forward = (sx + 600.0 * ux, sy + 600.0 * uy)
        self._bearing_probe_queue[cid] = [
            forward,
            (forward[0] + 300.0 * nx, forward[1] + 300.0 * ny),
            (forward[0] - 300.0 * nx, forward[1] - 300.0 * ny),
        ]

    def _next_bearing_probe(self, ks):
        for cid in sorted(list(self._bearing_probe_queue)):
            queue = self._bearing_probe_queue.get(cid, [])
            if ks[cid].status != ChannelStatus.ACTIVE or not queue:
                self._bearing_probe_queue.pop(cid, None)
                continue
            point = queue.pop(0)
            if not queue:
                self._bearing_probe_queue.pop(cid, None)
            return cid, point
        return None
