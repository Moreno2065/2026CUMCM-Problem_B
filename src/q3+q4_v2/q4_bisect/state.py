"""Q4 state with a certified update for two midpoint no-signal results.

After a direction result at anchor A, the source lies in the reported
``+/-1 degree`` wedge.  Let ``v`` be the reported direction and let ``D`` be
an upper bound on ``v . (g - A)`` over the current feasible polygon.  The two
points

    A + D/2 v +/- D/2 tan(epsilon) v_perp

bracket every ray in that wedge at axial distance D/2.  If the source were in
the far half, the segment from A (a positive observation) to the source would
cross the segment between the two probes.  Convexity of the directional
reception half-disk then makes at least one probe visible.  Both probes are
within the guaranteed 1000 m reception distance for D <= 1500.46 m.  Hence
two no-signal results certify that the far half contains no source.
"""
from __future__ import annotations

import math

from geometry import constants as C
from geometry.polygon import clip_halfplane
from state.channel_state import ChannelState, ChannelStatus


TERMINAL = (ChannelStatus.CLEARED, ChannelStatus.CERTIFIED_ABSENT)


class Q4BisectChannelState(ChannelState):
    """Conservative Q4 position polygon with certified pair cuts."""

    def __init__(self, channel_id, mode="Q4", **kwargs):
        if mode != "Q4":
            raise ValueError("Q4BisectChannelState supports Q4 only")
        super().__init__(channel_id, mode=mode, **kwargs)
        self.bisect_updates = []

    def apply_midpoint_pair_no_signal(self, anchor, bearing_deg, cutoff_m,
                                      virtual_time=None):
        """Retain ``v . (g-anchor) <= cutoff_m`` after two certified misses.

        The two physical no-signal observations are already present in
        ``observations`` and ``certificate_region``.  This method records only
        the derived constraint so evidence is not counted twice.
        """
        if self.status in TERMINAL:
            return False
        theta = math.radians(float(bearing_deg) % 360.0)
        axis = (math.cos(theta), math.sin(theta))
        cut_point = (float(anchor[0]) + float(cutoff_m) * axis[0],
                     float(anchor[1]) + float(cutoff_m) * axis[1])
        updated = clip_halfplane(self.feasible_region, cut_point, axis,
                                 keep_negative=True)
        if updated is None:
            raise ValueError(
                "midpoint-pair no-signal cut emptied Q4 feasible region "
                "(channel %d)" % self.channel_id)
        before = self.mec_radius
        self.feasible_region = updated
        after = self._update_mec()
        if after <= C.CLEAR_RADIUS:
            self.status = ChannelStatus.READY
            self.clear_position = self.mec[0]
        elif self.status == ChannelStatus.READY:
            self.status = ChannelStatus.ACTIVE
            self.clear_position = None
        self.bisect_updates.append({
            "anchor": (float(anchor[0]), float(anchor[1])),
            "bearing_deg": float(bearing_deg) % 360.0,
            "cutoff_m": float(cutoff_m),
            "mec_before": float(before),
            "mec_after": float(after),
            "virtual_time": (None if virtual_time is None
                             else float(virtual_time)),
        })
        return True

    def to_dict(self):
        result = super().to_dict()
        result["bisect_updates"] = list(self.bisect_updates)
        return result
