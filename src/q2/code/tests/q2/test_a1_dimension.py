"""Fail-closed A1 dimension classification and degenerate first observations.

The classifier must never promote a contact/degenerate arrangement to AREA just
because some closure-based midpoint test produced a boundary piece.
"""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.a1 import (
    A1BoundaryLabel,
    A1BoundaryPiece,
    A1Dimension,
    A1DimensionClassificationError,
    FirstObservation,
    _degenerate_dimension,
    _strict_interior_witness,
    build_a1,
)
from src.q2.code.geometry.crec import (
    InvalidFirstObservationGeometry,
    build_crec,
)
from src.q2.code.geometry.primitives import LineSegment, Point2


def test_centered_ordinary_wedge_is_a_positive_area_set() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))

    assert a1.dimension == A1Dimension.AREA
    assert (
        _strict_interior_witness(a1.observation, a1.omega_center, a1.omega_radius_m)
        is not None
    )
    assert {piece.label for piece in a1.boundary.pieces} == {
        A1BoundaryLabel.WEDGE_LOWER,
        A1BoundaryLabel.WEDGE_UPPER,
        A1BoundaryLabel.RHO_INNER,
        A1BoundaryLabel.RHO_OUTER,
    }


@pytest.mark.parametrize("bearing_deg", [0.0, 45.0, 359.5, 0.5])
def test_omega_truncated_and_wrapping_wedges_remain_area(bearing_deg: float) -> None:
    a1 = build_a1(FirstObservation(Point2(1700.0, 0.0), bearing_deg))

    assert a1.dimension == A1Dimension.AREA
    assert A1BoundaryLabel.OMEGA in {piece.label for piece in a1.boundary.pieces}
    radial = a1.radial_interval(math.radians(bearing_deg))
    assert radial is not None and radial[1] > radial[0]
    midpoint = Point2(
        a1.observation.station.x + math.cos(math.radians(bearing_deg)) * sum(radial) / 2.0,
        a1.observation.station.y + math.sin(math.radians(bearing_deg)) * sum(radial) / 2.0,
    )
    assert a1.contains(midpoint)


def test_s1_outside_omega_with_legal_detection_geometry_is_area() -> None:
    a1 = build_a1(FirstObservation(Point2(2000.0, 0.0), 180.0))

    assert a1.dimension == A1Dimension.AREA
    assert A1BoundaryLabel.OMEGA in {piece.label for piece in a1.boundary.pieces}
    radial = a1.radial_interval(math.pi)
    assert radial is not None and radial[1] > radial[0]
    midpoint = Point2(2000.0 - 0.5 * (radial[0] + radial[1]), 0.0)
    assert a1.contains(midpoint)


def test_narrow_wedge_beyond_external_tangent_is_area_and_builds_crec() -> None:
    """A positive-area wedge just beyond an external Omega tangent is not a segment."""
    tangent_deg = 180.0 - math.degrees(math.asin(1800.0 / 2000.0))
    observation = FirstObservation(
        Point2(2000.0, 0.0),
        tangent_deg - 1.0 + 1.0e-4,
    )

    a1 = build_a1(observation)

    assert a1.dimension == A1Dimension.AREA
    assert _strict_interior_witness(
        observation, a1.omega_center, a1.omega_radius_m
    ) is not None
    assert build_crec(a1).witnesses.pieces


def test_tangent_singleton_is_a_point_and_never_area() -> None:
    a1 = build_a1(FirstObservation(Point2(2000.0, 0.0), 114.84193276316712))

    assert a1.dimension == A1Dimension.POINT
    assert a1.dimension != A1Dimension.AREA
    assert (
        _strict_interior_witness(a1.observation, a1.omega_center, a1.omega_radius_m)
        is None
    )
    assert len(a1.boundary.point_pieces) == 1
    assert {piece.label for piece in a1.boundary.pieces} == {
        A1BoundaryLabel.DEGENERATE_POINT
    }


def test_impossible_first_observation_is_empty_and_crec_rejects_it() -> None:
    a1 = build_a1(FirstObservation(Point2(2000.0, 0.0), 0.0))

    assert a1.dimension == A1Dimension.EMPTY
    assert a1.boundary.pieces == ()
    assert (
        _strict_interior_witness(a1.observation, a1.omega_center, a1.omega_radius_m)
        is None
    )
    with pytest.raises(InvalidFirstObservationGeometry):
        build_crec(a1)


def test_degenerate_classifier_fails_closed_instead_of_guessing_area() -> None:
    observation = FirstObservation(Point2(0.0, 0.0), 0.0)
    center = Point2(0.0, 0.0)
    radius = 1800.0

    # A positive-length piece whose own midpoint is a genuine A1 member -> 1D.
    inside = A1BoundaryPiece(
        A1BoundaryLabel.WEDGE_LOWER,
        LineSegment(
            Point2(100.0, -100.0 * math.tan(math.radians(1.0))),
            Point2(200.0, -200.0 * math.tan(math.radians(1.0))),
        ),
    )
    assert (
        _degenerate_dimension(observation, center, radius, [inside], ())
        == A1Dimension.SEGMENT
    )

    # A positive-length piece that is not a certified A1 member must raise
    # rather than be silently reclassified as a positive-area set.
    outside = A1BoundaryPiece(
        A1BoundaryLabel.WEDGE_LOWER,
        LineSegment(Point2(100.0, 100.0), Point2(200.0, 200.0)),
    )
    with pytest.raises(A1DimensionClassificationError):
        _degenerate_dimension(observation, center, radius, [outside], ())

    assert (
        _degenerate_dimension(observation, center, radius, [], (Point2(100.0, 0.0),))
        == A1Dimension.POINT
    )
    assert (
        _degenerate_dimension(observation, center, radius, [], ())
        == A1Dimension.EMPTY
    )
