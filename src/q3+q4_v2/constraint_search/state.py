"""Conservative, nonconvex Q3 position sets; no simulator access.

Positive disks use the existing OUTER polygons. Excluded disks use INNER
polygons of slightly smaller radius. Thus numerical polygonization retains
possible positions. The convex hull is only a compatibility view; holes and
disconnected components survive all subsequent observation updates.
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

from geometry import constants as C
from geometry.mec import mec
from geometry.polygon import circumscribed_polygon
from geometry.wedge import wedge_intersect
from state.channel_state import ChannelState, ChannelStatus


TERMINAL = (ChannelStatus.CLEARED, ChannelStatus.CERTIFIED_ABSENT)


class ConstrainedChannelState(ChannelState):
    def __init__(self, channel_id, mode="Q3", **kwargs):
        if mode != "Q3":
            raise ValueError("Q3 exclusions must never be applied to Q4")
        super().__init__(channel_id, mode=mode, **kwargs)
        self._domain_polygon = list(self.feasible_region)
        self.position_set = Polygon(self.feasible_region)
        self.excluded_clear_points = []
        self.constraint_stats = {"negative_updates": 0,
                                 "active_negative_shrinks": 0,
                                 "failed_clear_updates": 0}

    def _publish(self):
        hull = self.position_set.convex_hull
        if hull.is_empty:
            if self.status in (ChannelStatus.ACTIVE, ChannelStatus.READY):
                raise ValueError("empty confirmed-source position set")
            # Absence is STILL certified by the existing independent checker.
            self.feasible_region = None
            self.mec = ((0.0, 0.0), 0.0)
            return
        if hull.geom_type == "Polygon":
            self.feasible_region = list(orient(hull, sign=1).exterior.coords)[:-1]
        else:
            # Retain a tiny outer box for legacy polygon routines at degeneracy.
            self.feasible_region = list(orient(hull.buffer(1e-7).envelope,
                                               sign=1).exterior.coords)[:-1]
        self.mec = mec(self.feasible_region)
        if self.status in (ChannelStatus.ACTIVE, ChannelStatus.READY):
            # A failed clear can punch a hole into a previously READY set.
            # Publish both directions of the transition so READY never
            # survives after its guarantee has been invalidated.
            if self.mec_radius <= C.CLEAR_RADIUS:
                self.status = ChannelStatus.READY
                self.clear_position = self.mec[0]
            else:
                self.status = ChannelStatus.ACTIVE
                self.clear_position = None

    def _subtract_disk(self, position, radius):
        # Point.buffer joins points ON this smaller circle: an inscribed disk
        # polygon. Never subtract an outer/tangent disk approximation.
        disk = Point(position).buffer(radius - 1e-6, quad_segs=32)
        self.position_set = self.position_set.difference(disk)
        self._publish()

    def update_direction(self, position, bearing_deg, virtual_time):
        if self.status in TERMINAL:
            return self.status
        # Build the observation wedge on the original domain; legacy clipping
        # rejects extremely small polygons as empty. GEOS then intersects the
        # actual set without that area cutoff. Tiny outward angular slack
        # protects legal observations exactly at the +/-1 degree boundary.
        outer = wedge_intersect(self._domain_polygon, position, bearing_deg,
                                tol_deg=C.BEARING_ERROR_DEG + 1e-7)
        if outer is None:
            raise ValueError("direction inconsistent with constrained hull")
        updated = self.position_set.intersection(Polygon(outer))
        if updated.is_empty:
            raise ValueError("direction inconsistent with nonconvex position set")
        self.position_set = updated
        self._record(position, "direction", virtual_time,
                     bearing=float(bearing_deg) % 360)
        if self.status == ChannelStatus.UNKNOWN:
            self.status = ChannelStatus.ACTIVE
        self._publish()
        return self.status

    def update_no_signal(self, position, virtual_time):
        if self.status in TERMINAL:
            return self.status
        confirmed = self.status in (ChannelStatus.ACTIVE, ChannelStatus.READY)
        before = self.position_set.area
        super().update_no_signal(position, virtual_time)
        self._subtract_disk(position, C.R_EFF_MIN)
        self.constraint_stats["negative_updates"] += 1
        if confirmed and self.position_set.area < before - 1e-6:
            self.constraint_stats["active_negative_shrinks"] += 1
        return self.status

    def update_near(self, position, virtual_time):
        if self.status in TERMINAL:
            return self.status
        outer = Polygon(circumscribed_polygon(position, C.NEAR_THRESHOLD))
        self.position_set = self.position_set.intersection(outer)
        super().update_near(position, virtual_time)
        self._publish()
        self.clear_position = tuple(position)
        return self.status

    def update_failed_clear(self, position, virtual_time):
        if self.status in TERMINAL:
            return self.status
        self.excluded_clear_points.append(tuple(position))
        self._record(position, "failed_clear", virtual_time)
        self._subtract_disk(position, C.CLEAR_RADIUS)
        self.constraint_stats["failed_clear_updates"] += 1
        return self.status

    @property
    def feasible_area(self):
        return self.position_set.area

    def to_dict(self):
        result = super().to_dict()
        result.update(position_set=self.position_set.__geo_interface__,
                      constraint_stats=dict(self.constraint_stats),
                      excluded_clear_points=list(self.excluded_clear_points))
        return result
