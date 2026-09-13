"""Gate A contracts: neutral primitives and first-observation feasible set."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random

import pytest

try:
    from src.q2.code.geometry.primitives import Point2
except ModuleNotFoundError:
    Point2 = None

try:
    from src.q2.code.geometry.a1 import (
        A1BoundaryLabel,
        A1BoundaryPiece,
        A1BoundaryRegistry,
        FirstObservation,
        build_a1,
    )
except ModuleNotFoundError:
    A1BoundaryLabel = None
    A1BoundaryPiece = None
    A1BoundaryRegistry = None
    FirstObservation = None
    build_a1 = None

try:
    from src.q2.code.geometry.primitives import CircularArc
except ModuleNotFoundError:
    CircularArc = None

try:
    from src.q2.code.geometry.primitives import BoundaryPoint
except ImportError:
    BoundaryPoint = None

try:
    from src.q2.code.geometry.a1 import A1Dimension
except ImportError:
    A1Dimension = None

try:
    from src.q2.code.verifier.verify_a1 import verify_a1_boundary
except ModuleNotFoundError:
    verify_a1_boundary = None


def test_point2_has_euclidean_norm_and_distance() -> None:
    """The neutral primitive must preserve ordinary metric geometry exactly."""
    assert Point2 is not None
    p = Point2(3.0, 4.0)
    assert math.isclose(p.norm(), 5.0, abs_tol=1e-14)
    assert math.isclose(p.distance_to(Point2(0.0, 0.0)), 5.0, abs_tol=1e-14)


def test_a1_for_central_east_observation_keeps_only_physical_boundaries() -> None:
    """A1 uses the first wedge and 5--1500 m range, not a 1000 m surrogate."""
    assert build_a1 is not None
    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))

    assert a1.contains(Point2(100.0, 0.0))
    assert not a1.contains(Point2(5.0, 0.0))
    assert not a1.contains(Point2(1500.1, 0.0))
    assert not a1.contains(Point2(100.0, 4.0))

    labels = {piece.label for piece in a1.boundary.pieces}
    assert labels == {
        A1BoundaryLabel.WEDGE_LOWER,
        A1BoundaryLabel.WEDGE_UPPER,
        A1BoundaryLabel.RHO_INNER,
        A1BoundaryLabel.RHO_OUTER,
    }


def test_a1_clipping_and_registry_isolation_pass_independent_boundary_verifier() -> None:
    """The target circle may replace rho=1500, but rho=1000 is never an A1 boundary."""
    assert verify_a1_boundary is not None

    clipped = build_a1(
        FirstObservation(station=Point2(1700.0, 0.0), bearing_deg=0.0)
    )
    labels = {piece.label for piece in clipped.boundary.pieces}
    assert A1BoundaryLabel.OMEGA in labels
    assert A1BoundaryLabel.RHO_OUTER not in labels
    assert verify_a1_boundary(clipped, samples_per_piece=11).passed

    with pytest.raises(ValueError, match="rho=1500"):
        A1BoundaryRegistry(
            (
                A1BoundaryPiece(
                    A1BoundaryLabel.RHO_OUTER,
                    CircularArc(Point2(0.0, 0.0), 1000.0, 0.0, 0.5),
                ),
            )
        )

    with pytest.raises(ValueError, match="rho=1000"):
        A1BoundaryRegistry(
            (
                A1BoundaryPiece(
                    A1BoundaryLabel.OMEGA,
                    CircularArc(Point2(0.0, 0.0), 1000.0, 0.0, 0.5),
                ),
            )
        )

    with pytest.raises(ValueError, match="Omega"):
        A1BoundaryRegistry(
            (
                A1BoundaryPiece(
                    A1BoundaryLabel.OMEGA,
                    CircularArc(Point2(123.0, 456.0), 1700.0, 0.0, 0.5),
                ),
            )
        )


@pytest.mark.parametrize(
    ("station", "bearing_deg"),
    [
        (Point2(0.0, 0.0), 359.5),
        (Point2(1700.0, 0.0), 359.5),
        (Point2(2000.0, 0.0), 180.0),
    ],
)
def test_a1_boundary_samples_remain_physically_feasible_in_edge_configurations(
    station: Point2, bearing_deg: float
) -> None:
    """Unwrap and target-disk entry/exit may change active pieces, never their constraints."""
    a1 = build_a1(FirstObservation(station=station, bearing_deg=bearing_deg))
    report = verify_a1_boundary(a1, samples_per_piece=13)
    assert report.checked_points > 0
    assert report.passed, report.failures

    radial = a1.radial_interval(math.radians(bearing_deg))
    assert radial is not None
    assert radial[1] > radial[0]
    midpoint = Point2(
        station.x + math.cos(math.radians(bearing_deg)) * sum(radial) / 2.0,
        station.y + math.sin(math.radians(bearing_deg)) * sum(radial) / 2.0,
    )
    assert a1.contains(midpoint)


def test_tangent_singleton_a1_is_registered_and_cannot_vacuously_pass() -> None:
    """A wedge-side tangent to Omega is a valid zero-dimensional A1, not EMPTY."""
    assert A1Dimension is not None
    assert BoundaryPoint is not None

    station = Point2(2000.0, 0.0)
    tangent = Point2(1620.0, 784.6018098373212)
    a1 = build_a1(
        FirstObservation(station=station, bearing_deg=114.84193276316712)
    )

    assert a1.contains(tangent)
    assert a1.closure_contains(tangent)
    assert a1.dimension == A1Dimension.POINT
    assert len(a1.boundary.point_pieces) == 1
    point_piece = a1.boundary.point_pieces[0]
    assert isinstance(point_piece.curve, BoundaryPoint)
    assert point_piece.curve.point.distance_to(tangent) < 1e-7

    report = verify_a1_boundary(a1, samples_per_piece=11)
    assert report.checked_points >= 1
    assert report.completeness_checked is True
    assert report.passed, report.failures


def test_empty_a1_cannot_receive_a_vacuous_boundary_verifier_pass() -> None:
    """An empty registry is never evidence that a nonempty physical A1 was covered."""
    a1 = build_a1(FirstObservation(station=Point2(2000.0, 0.0), bearing_deg=0.0))

    assert a1.dimension == A1Dimension.EMPTY
    assert a1.boundary.pieces == ()
    report = verify_a1_boundary(a1)
    assert report.checked_points == 0
    assert report.completeness_checked is False
    assert report.passed is False
    assert "independent emptiness proof" in report.failures[0]


def test_gate_a_persistent_fixtures_replay_through_completeness_oracle() -> None:
    """Every published Gate A fixture remains both sound and boundary-complete."""
    fixture_path = Path(__file__).parents[1] / "artifacts" / "q2_gate_a_fixtures.json"
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(fixture_payload["cases"]) >= 5

    for case in fixture_payload["cases"]:
        station = Point2(case["station"]["x"], case["station"]["y"])
        a1 = build_a1(FirstObservation(station=station, bearing_deg=case["bearing_deg"]))
        assert {piece.label.value for piece in a1.boundary.pieces} == set(
            case["expected_active_labels"]
        ), case["id"]
        if "expected_dimension" in case:
            assert a1.dimension.value == case["expected_dimension"], case["id"]
        if "expected_point" in case:
            assert len(a1.boundary.point_pieces) == 1, case["id"]
            expected = Point2(case["expected_point"]["x"], case["expected_point"]["y"])
            actual = a1.boundary.point_pieces[0].curve.point
            assert actual.distance_to(expected) < 1e-7, case["id"]
        report = verify_a1_boundary(a1, samples_per_piece=101)
        assert report.completeness_checked is True, case["id"]
        assert report.passed, (case["id"], report.failures)


def test_independent_completeness_oracle_covers_500_fixed_seed_nondegenerate_cases() -> None:
    """A separate ray oracle must cover real boundaries beyond the hand-picked fixtures."""
    rng = random.Random(20260911)
    for _ in range(500):
        target_radius = rng.uniform(100.0, 1600.0)
        target_angle = rng.uniform(0.0, math.tau)
        target = Point2(
            target_radius * math.cos(target_angle),
            target_radius * math.sin(target_angle),
        )
        true_bearing = rng.uniform(0.0, math.tau)
        range_m = rng.uniform(20.0, 1450.0)
        station = Point2(
            target.x - range_m * math.cos(true_bearing),
            target.y - range_m * math.sin(true_bearing),
        )
        bearing_deg = math.degrees(true_bearing) + rng.uniform(-0.8, 0.8)
        a1 = build_a1(FirstObservation(station=station, bearing_deg=bearing_deg))

        assert a1.dimension == A1Dimension.AREA
        report = verify_a1_boundary(a1, samples_per_piece=101)
        assert report.completeness_checked is True
        assert report.passed, report.failures
