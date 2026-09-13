"""Executable baseline helpers for the Gate-G evidence package.

The Gate-G builder remains the authoritative evidence orchestrator.  These
small helpers expose the three named baseline constructions as a stable public
module for reports, notebooks, and handoff consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.frozen_contract import (
    RADIAL_HI_M,
    RADIAL_LO_M,
    RECEPTION_RADIUS_M,
)


@dataclass(frozen=True)
class BaselineFormula:
    """The frozen constants behind the B2 analytic max-min-angle construction."""

    rho_a_m: float = RADIAL_LO_M
    rho_b_m: float = RADIAL_HI_M
    reception_radius_m: float = RECEPTION_RADIUS_M

    @property
    def length_m(self) -> float:
        return self.rho_b_m - self.rho_a_m

    @property
    def x_star_m(self) -> float:
        return self.rho_a_m + self.reception_radius_m**2 / self.length_m

    @property
    def abs_y_star_m(self) -> float:
        ratio = self.reception_radius_m / self.length_m
        return self.reception_radius_m * math.sqrt(1.0 - ratio**2)


def center_ray_max_min_angle(
    station: Point2, bearing_deg: float, *, bounds: Any | None = None
) -> Point2:
    """Construct the B2 analytic center-ray max-min-angle point.

    This is the analytic max-min-angle construction on the center ray.  It
    only carries that interpretation in the canonical untruncated wedge; once
    Omega truncates the first wedge it is a canonical heuristic and no longer
    analytically optimal.  When ``bounds`` is supplied the point is clamped
    componentwise to the Crec-derived search bounds, and that clamping is
    disclosed by the caller's persisted provenance.
    """
    formula = BaselineFormula()
    angle = math.radians(bearing_deg)
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    point = (
        station
        + direction.scaled(formula.x_star_m)
        + perpendicular.scaled(formula.abs_y_star_m)
    )
    return _clamp(point, bounds) if bounds is not None else point


def right_angle_radial(
    station: Point2, bearing_deg: float, radial_interval: tuple[float, float], *, bounds: Any | None = None
) -> Point2:
    """Construct the B1 90-degree midpoint heuristic (one symmetric side).

    Take the midpoint of the feasible radial interval on the first-bearing
    axis as the nominal target and rotate a point of equal distance onto the
    perpendicular.  The Gate-G builder evaluates both symmetric sides and
    reports the better one; this helper exposes the positive-perpendicular
    branch only.
    """
    angle = math.radians(bearing_deg)
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    rho = 0.5 * (radial_interval[0] + radial_interval[1])
    point = station + direction.scaled(rho) + perpendicular.scaled(rho)
    return _clamp(point, bounds) if bounds is not None else point


def _clamp(point: Point2, bounds: Any | None) -> Point2:
    if bounds is None:
        return point
    return Point2(
        min(bounds.x_max, max(bounds.x_min, point.x)),
        min(bounds.y_max, max(bounds.y_min, point.y)),
    )

