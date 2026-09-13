"""Near-disk clipping, 0/360 wrap and the double-wedge tangent-bridge special case."""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.angular_image import (
    NEAR_RADIUS_M,
    TANGENCY_TOL_M,
    _angular_cells,
    _critical_bearings,
    _double_wedge_tangent_bridge,
    build_angular_image,
)
from src.q2.code.geometry.primitives import Point2


def test_point_a1_inside_the_near_disk_is_all_near() -> None:
    a1 = build_a1(FirstObservation(Point2(2000.0, 0.0), 114.84193276316712))
    tangent = a1.boundary.point_pieces[0].curve.point

    image = build_angular_image(a1, tangent)

    assert image.all_near is True
    assert image.merged_closure.is_empty
    assert image.expanded_closure.is_empty
    assert image.extrema_witnesses == ()


def test_near_disk_is_clipped_out_of_the_direction_domain() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station = Point2(400.0, 0.0)

    image = build_angular_image(a1, station)

    assert image.all_near is False
    # A1 membership is measured from S1, so a 5 m shell around the *second*
    # station is still an A1 member ...
    assert a1.contains(Point2(station.x + NEAR_RADIUS_M, 0.0))
    # ... but the near disk is clipped out of the direction domain, recorded as
    # an explicit near-circle boundary event.
    assert "near_circle" in {event.source_label for event in image.boundary_events}

    # Independent dense check: every A1 point strictly outside the 5 m near disk
    # must have its bearing inside the reported closed direction set.
    wedge_lower, wedge_upper = a1.observation.wedge_limits_rad
    checked = 0
    for index in range(41):
        angle = wedge_lower + (wedge_upper - wedge_lower) * index / 40.0
        radial = a1.radial_interval(angle)
        if radial is None:
            continue
        for step in range(1, 41):
            rho = radial[0] + (radial[1] - radial[0]) * step / 40.0
            point = Point2(rho * math.cos(angle), rho * math.sin(angle))
            if point.distance_to(station) <= NEAR_RADIUS_M + 1e-9:
                continue
            if not a1.contains(point):
                continue
            bearing = math.atan2(point.y - station.y, point.x - station.x) % math.tau
            assert image.merged_closure.contains(bearing, tolerance_rad=1e-9), (
                point,
                bearing,
            )
            checked += 1
    assert checked > 100


@pytest.mark.parametrize("bearing_deg", [359.5, 0.5])
def test_bearings_wrapping_through_zero_are_handled(bearing_deg: float) -> None:
    a1 = build_a1(FirstObservation(Point2(1700.0, 0.0), bearing_deg))

    image = build_angular_image(a1, Point2(300.0, 300.0))

    assert image.all_near is False
    assert not image.merged_closure.is_empty
    assert 0.0 <= min(interval.start_rad for interval in image.merged_closure.intervals)
    assert all(
        0.0 <= interval.start_rad <= interval.end_rad <= math.tau
        for interval in image.merged_closure.intervals
    )


def test_double_wedge_tangent_bridge_is_detected_and_keeps_the_raw_objective() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    # A station exactly five metres from both wedge sides: the near circle is
    # tangent to the two wedge-side segments.
    station = Point2(NEAR_RADIUS_M / math.sin(math.radians(1.0)), 0.0)

    bridge = _double_wedge_tangent_bridge(a1, station)
    assert bridge is not None
    assert len(bridge) == 2

    cuts, _ = _critical_bearings(a1, station)
    raw = _angular_cells(a1, station, cuts)
    image = build_angular_image(a1, station)

    # The helper must enrich component/witness metadata only: the frozen
    # objective still uses merged_closure == raw.
    assert image.merged_closure == raw
    assert image.spatial_component_count == 2
    assert "near_circle" in {event.source_label for event in image.boundary_events}
    assert {witness.event_kind for witness in image.extrema_witnesses} == {
        "tangent_bridge_endpoint"
    }


def test_tangent_bridge_is_not_reported_for_an_ordinary_station() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))

    assert _double_wedge_tangent_bridge(a1, Point2(300.0, 300.0)) is None


@pytest.mark.parametrize("gap_m", [5e-14, 8e-14, 1e-10])
def test_sub_nanometre_wedge_channel_is_not_collapsed_to_tangency(gap_m: float) -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station = Point2((NEAR_RADIUS_M + gap_m) / math.sin(math.radians(1.0)), 0.0)

    # The tangency tolerance must stay below the smallest real gap, otherwise a
    # genuine sub-nanometre channel would be misread as two tangent components.
    assert TANGENCY_TOL_M < gap_m
    assert _double_wedge_tangent_bridge(a1, station) is None
    assert build_angular_image(a1, station).spatial_component_count == 1
