"""Gate B contracts for the frozen robust reception set Crec."""

from __future__ import annotations

import math
import random
import json
import inspect
from pathlib import Path

import pytest

from src.q2.code.geometry.a1 import (
    A1BoundaryLabel,
    A1BoundaryPiece,
    A1BoundaryRegistry,
    A1Dimension,
    A1Region,
    FirstObservation,
    OMEGA_CENTER,
    OMEGA_RADIUS_M,
    build_a1,
)
from src.q2.code.geometry.primitives import CircularArc, Point2

try:
    from src.q2.code.geometry.crec import (
        CrecWitnessLabel,
        CrecWitnessPiece,
        CrecWitnessRegistry,
        CrecRegion,
        CompatibleRadiusMode,
        InvalidFirstObservationGeometry,
        UnsupportedA1Dimension,
        build_crec,
    )
except ModuleNotFoundError:
    CrecWitnessLabel = None
    CrecWitnessPiece = None
    CrecWitnessRegistry = None
    CrecRegion = None
    CompatibleRadiusMode = None
    InvalidFirstObservationGeometry = None
    UnsupportedA1Dimension = None
    build_crec = None

try:
    from src.q2.code.verifier.verify_crec import verify_crec
except ModuleNotFoundError:
    verify_crec = None


TANGENT_STATION = Point2(2000.0, 0.0)
TANGENT_POINT = Point2(1620.0, 784.6018098373212)
TANGENT_BEARING_DEG = 114.84193276316712


def test_point_a1_reduces_crec_to_one_exact_compatible_disk() -> None:
    assert build_crec is not None
    a1 = build_a1(
        FirstObservation(station=TANGENT_STATION, bearing_deg=TANGENT_BEARING_DEG)
    )
    crec = build_crec(a1)

    assert len(crec.witnesses.pieces) == 1
    assert crec.witnesses.pieces[0].label == CrecWitnessLabel.DEGENERATE_POINT

    for offset_m, expected in (
        (0.0, True),
        (999.999, True),
        (1000.0, True),
        (1000.001, False),
    ):
        result = crec.is_in_crec(Point2(TANGENT_POINT.x + offset_m, TANGENT_POINT.y))
        assert result.in_crec is expected
        assert math.isclose(result.max_violation_m, offset_m - 1000.0, abs_tol=2e-7)
        assert math.isclose(result.margin_m, 1000.0 - offset_m, abs_tol=2e-7)
        assert result.active_witness_point.distance_to(TANGENT_POINT) < 1e-7
        assert result.active_witness_type == CrecWitnessLabel.DEGENERATE_POINT
        assert result.active_witness_source == "a1_tangent_singleton"
        assert result.checked_candidate_count == 1
        assert result.a1_dimension == A1Dimension.POINT


def test_empty_a1_is_invalid_instead_of_becoming_the_whole_plane() -> None:
    assert build_crec is not None
    assert InvalidFirstObservationGeometry is not None
    empty = build_a1(FirstObservation(station=Point2(2000.0, 0.0), bearing_deg=0.0))
    assert empty.dimension == A1Dimension.EMPTY
    with pytest.raises(InvalidFirstObservationGeometry):
        build_crec(empty)


def test_unimplemented_one_dimensional_a1_fails_explicitly() -> None:
    assert build_crec is not None
    assert UnsupportedA1Dimension is not None
    observation = FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0)
    segment = A1Region(
        observation=observation,
        omega_center=OMEGA_CENTER,
        omega_radius_m=OMEGA_RADIUS_M,
        boundary=A1BoundaryRegistry((), OMEGA_CENTER, OMEGA_RADIUS_M),
        dimension=A1Dimension.SEGMENT,
    )
    with pytest.raises(UnsupportedA1Dimension):
        build_crec(segment)


def test_crec_registry_is_nominally_isolated_and_rejects_deep_rho_1500() -> None:
    assert CrecWitnessRegistry is not None
    assert CrecWitnessRegistry is not A1BoundaryRegistry

    forbidden = CrecWitnessPiece(
        label=CrecWitnessLabel.RHO_1500_AS_DEEP_END_WITNESS,
        curve=CircularArc(Point2(0.0, 0.0), 1500.0, -0.01, 0.01),
        radius_mode=CompatibleRadiusMode.RADIAL_DEPTH,
        source="adversarial_test",
    )
    with pytest.raises(ValueError, match="rho=1500"):
        CrecWitnessRegistry(
            (forbidden,), Point2(0.0, 0.0), OMEGA_CENTER, OMEGA_RADIUS_M
        )

    with pytest.raises(ValueError, match="rho=1000"):
        A1BoundaryRegistry(
            (
                A1BoundaryPiece(
                    A1BoundaryLabel.OMEGA,
                    CircularArc(OMEGA_CENTER, 1000.0, -0.01, 0.01),
                ),
            )
        )


def test_a1_registry_cannot_be_substituted_for_crec_registry() -> None:
    assert CrecRegion is not None
    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    with pytest.raises(TypeError, match="CrecWitnessRegistry"):
        CrecRegion(a1=a1, witnesses=a1.boundary)


def test_crec_region_rejects_registry_from_a_different_a1() -> None:
    first_a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    other_a1 = build_a1(FirstObservation(Point2(100.0, 200.0), 90.0))
    other_registry = build_crec(other_a1).witnesses
    with pytest.raises(ValueError, match="metadata"):
        CrecRegion(a1=first_a1, witnesses=other_registry)


def test_neutral_arc_can_be_shared_but_crec_radius_mode_is_an_invariant() -> None:
    station = Point2(0.0, 0.0)
    neutral_arc = CircularArc(station, 5.0, -0.01, 0.01)
    a1_registry = A1BoundaryRegistry(
        (A1BoundaryPiece(A1BoundaryLabel.RHO_INNER, neutral_arc),)
    )
    crec_registry = CrecWitnessRegistry(
        (
            CrecWitnessPiece(
                CrecWitnessLabel.RHO_LO,
                neutral_arc,
                CompatibleRadiusMode.FIXED_1000,
                "shared_neutral_geometry",
            ),
        ),
        station,
        OMEGA_CENTER,
        OMEGA_RADIUS_M,
    )
    assert a1_registry.pieces[0].curve is crec_registry.pieces[0].curve

    wrong_mode = CrecWitnessPiece(
        CrecWitnessLabel.RHO_1000,
        CircularArc(station, 1000.0, -0.01, 0.01),
        CompatibleRadiusMode.RADIAL_DEPTH,
        "adversarial_wrong_mode",
    )
    with pytest.raises(ValueError, match="fixed_1000"):
        CrecWitnessRegistry(
            (wrong_mode,), station, OMEGA_CENTER, OMEGA_RADIUS_M
        )


@pytest.mark.parametrize(
    ("station", "bearing_deg", "expected_labels"),
    [
        (
            Point2(0.0, 0.0),
            0.0,
            {CrecWitnessLabel.RHO_LO, CrecWitnessLabel.RHO_1000},
        ),
        (
            Point2(1700.0, 0.0),
            0.0,
            {
                CrecWitnessLabel.RHO_LO,
                CrecWitnessLabel.OMEGA_TRUNCATED_RHO_HI_BELOW_1000,
            },
        ),
        (
            Point2(2000.0, 0.0),
            180.0,
            {
                CrecWitnessLabel.OMEGA_TRUNCATED_RHO_LO,
                CrecWitnessLabel.RHO_1000,
            },
        ),
        (
            Point2(3000.0, 0.0),
            180.0,
            {CrecWitnessLabel.OMEGA_TRUNCATED_RHO_LO},
        ),
    ],
)
def test_radial_reduction_preserves_all_three_frozen_branches(
    station: Point2,
    bearing_deg: float,
    expected_labels: set,
) -> None:
    assert build_crec is not None
    a1 = build_a1(FirstObservation(station=station, bearing_deg=bearing_deg))
    crec = build_crec(a1)
    assert {piece.label for piece in crec.witnesses.pieces} == expected_labels
    at_first_station = crec.is_in_crec(station)
    assert at_first_station.in_crec is True
    assert at_first_station.max_violation_m <= 2e-7


def test_rho_1000_arc_keeps_its_interior_antipodal_maximum() -> None:
    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    result = build_crec(a1).is_in_crec(Point2(-500.0, 0.0))

    assert math.isclose(result.max_violation_m, 500.0, abs_tol=2e-7)
    assert result.active_witness_type == CrecWitnessLabel.RHO_1000
    assert result.active_witness_source == "radial_transition_rho_1000"
    assert result.active_witness_point.distance_to(Point2(1000.0, 0.0)) < 1e-7


def test_deep_omega_arc_keeps_non_antipodal_interior_stationary_maximum() -> None:
    """The weighted deep objective is not a plain farthest-point-on-Omega problem."""
    station = Point2(3000.0, 0.0)
    a1 = build_a1(FirstObservation(station=station, bearing_deg=180.0))
    result = build_crec(a1).is_in_crec(Point2(4000.0, 0.0))

    assert math.isclose(result.max_violation_m, 1000.0, abs_tol=2e-7)
    assert result.active_witness_type == CrecWitnessLabel.OMEGA_TRUNCATED_RHO_LO
    assert result.active_witness_source == "omega_entry_deep_radial"
    assert result.active_witness_point.distance_to(Point2(1800.0, 0.0)) < 1e-6


def test_compatible_radius_information_is_strictly_less_conservative_than_1000_disk() -> None:
    station = Point2(0.0, 0.0)
    second_station = Point2(100.0, 0.0)
    deep_target = Point2(1200.0, 0.0)
    a1 = build_a1(FirstObservation(station=station, bearing_deg=0.0))
    result = build_crec(a1).is_in_crec(second_station)

    assert 1000.0 < second_station.distance_to(deep_target)
    assert second_station.distance_to(deep_target) < deep_target.distance_to(station)
    assert result.in_crec is True
    assert result.max_violation_m < 0.0


def test_verifier_recovers_internal_rho_1500_omega_tangent_singleton() -> None:
    """POINT A1 recovery must not depend on an angular grid hitting the singleton."""
    assert verify_crec is not None
    station = Point2(3300.0, 0.0)
    a1 = build_a1(FirstObservation(station=station, bearing_deg=180.5))
    assert a1.dimension == A1Dimension.POINT
    assert a1.boundary.point_pieces[0].curve.point.distance_to(Point2(1800.0, 0.0)) < 1e-7

    analytic = build_crec(a1).is_in_crec(station)
    report = verify_crec(
        a1,
        station,
        analytic_max_violation_m=analytic.max_violation_m,
        analytic_in_crec=analytic.in_crec,
        angle_samples=360,
        radial_samples=128,
    )
    assert analytic.in_crec is True
    assert math.isclose(analytic.max_violation_m, 0.0, abs_tol=2e-7)
    assert report.passed, report.failures
    assert report.dense_active_target.distance_to(Point2(1800.0, 0.0)) < 1e-7


@pytest.mark.parametrize(
    ("station", "bearing_deg", "second_station"),
    [
        (Point2(0.0, 0.0), 0.0, Point2(0.0, 0.0)),
        (Point2(1700.0, 0.0), 0.0, Point2(1500.0, 200.0)),
        (Point2(0.0, 0.0), 359.5, Point2(-400.0, 250.0)),
        (Point2(2000.0, 0.0), 180.0, Point2(2000.0, 0.0)),
        (Point2(3000.0, 0.0), 180.0, Point2(4000.0, 0.0)),
    ],
)
def test_independent_dense_verifier_does_not_find_an_analytic_underestimate(
    station: Point2, bearing_deg: float, second_station: Point2
) -> None:
    assert verify_crec is not None
    a1 = build_a1(FirstObservation(station=station, bearing_deg=bearing_deg))
    analytic = build_crec(a1).is_in_crec(second_station)
    report = verify_crec(
        a1,
        second_station,
        analytic_max_violation_m=analytic.max_violation_m,
        analytic_in_crec=analytic.in_crec,
        angle_samples=361,
        radial_samples=129,
    )
    assert report.passed, report.failures
    assert analytic.max_violation_m >= report.dense_radial_max_violation_m - 2e-6


def test_wrap_equivalent_first_bearings_produce_identical_crec_results() -> None:
    station = Point2(0.0, 0.0)
    second = Point2(300.0, -400.0)
    positive = build_crec(build_a1(FirstObservation(station, 359.5))).is_in_crec(second)
    negative = build_crec(build_a1(FirstObservation(station, -0.5))).is_in_crec(second)

    assert positive.in_crec == negative.in_crec
    assert math.isclose(positive.margin_m, negative.margin_m, abs_tol=2e-7)
    assert positive.active_witness_point.distance_to(negative.active_witness_point) < 2e-7


def test_crec_is_covariant_under_a_common_rigid_motion() -> None:
    station = Point2(2000.0, 0.0)
    second = Point2(850.0, 430.0)
    bearing = 180.0
    base_a1 = build_a1(FirstObservation(station, bearing))
    base = build_crec(base_a1).is_in_crec(second)

    rotation_deg = 37.0
    translation = Point2(321.0, -654.0)

    def transform(point: Point2) -> Point2:
        angle = math.radians(rotation_deg)
        return Point2(
            math.cos(angle) * point.x - math.sin(angle) * point.y + translation.x,
            math.sin(angle) * point.x + math.cos(angle) * point.y + translation.y,
        )

    transformed_a1 = build_a1(
        FirstObservation(transform(station), bearing + rotation_deg),
        omega_center=transform(OMEGA_CENTER),
        omega_radius_m=OMEGA_RADIUS_M,
    )
    transformed = build_crec(transformed_a1).is_in_crec(transform(second))

    assert transformed.in_crec == base.in_crec
    assert math.isclose(transformed.margin_m, base.margin_m, abs_tol=2e-6)
    assert transformed.active_witness_point.distance_to(transform(base.active_witness_point)) < 2e-6


def test_fixed_seed_random_analytic_phi_dominates_independent_dense_phi() -> None:
    assert verify_crec is not None
    rng = random.Random(20260911)
    for _ in range(500):
        target_radius = rng.uniform(100.0, 1600.0)
        target_angle = rng.uniform(0.0, math.tau)
        target = Point2(
            target_radius * math.cos(target_angle),
            target_radius * math.sin(target_angle),
        )
        true_bearing = rng.uniform(0.0, math.tau)
        target_range = rng.uniform(20.0, 1450.0)
        station = Point2(
            target.x - target_range * math.cos(true_bearing),
            target.y - target_range * math.sin(true_bearing),
        )
        bearing_deg = math.degrees(true_bearing) + rng.uniform(-0.8, 0.8)
        second = Point2(
            station.x + rng.uniform(-1800.0, 1800.0),
            station.y + rng.uniform(-1800.0, 1800.0),
        )
        a1 = build_a1(FirstObservation(station, bearing_deg))
        assert a1.dimension == A1Dimension.AREA
        crec = build_crec(a1)
        at_first_station = crec.is_in_crec(station)
        assert at_first_station.in_crec is True
        assert at_first_station.max_violation_m <= 2e-7
        analytic = crec.is_in_crec(second)
        report = verify_crec(
            a1,
            second,
            analytic_max_violation_m=analytic.max_violation_m,
            analytic_in_crec=analytic.in_crec,
            angle_samples=81,
            radial_samples=49,
        )
        assert report.passed, report.failures


def test_verifier_b_has_no_solver_or_witness_registry_dependency() -> None:
    assert verify_crec is not None
    source = inspect.getsource(inspect.getmodule(verify_crec))
    assert "from ..geometry.crec" not in source
    assert "is_in_crec(" not in source
    assert ".witnesses" not in source


def test_gate_b_persistent_fixtures_replay_through_both_oracles() -> None:
    assert verify_crec is not None
    fixture_path = Path(__file__).parents[1] / "artifacts" / "q2_gate_b_fixtures.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) >= 7

    for case in payload["cases"]:
        station = Point2(case["station"]["x"], case["station"]["y"])
        second = Point2(case["second_station"]["x"], case["second_station"]["y"])
        a1 = build_a1(FirstObservation(station, case["bearing_deg"]))
        analytic = build_crec(a1).is_in_crec(second)
        assert analytic.in_crec is case["expected_in_crec"], case["id"]
        assert math.isclose(
            analytic.max_violation_m,
            case["expected_max_violation_m"],
            abs_tol=2e-6,
        ), case["id"]
        assert analytic.active_witness_type.value == case["expected_witness_type"], case["id"]

        report = verify_crec(
            a1,
            second,
            analytic_max_violation_m=analytic.max_violation_m,
            analytic_in_crec=analytic.in_crec,
            angle_samples=181,
            radial_samples=97,
        )
        assert report.passed, (case["id"], report.failures)

        for check in case.get("tangent_offset_checks", []):
            probe = Point2(TANGENT_POINT.x + check["offset_m"], TANGENT_POINT.y)
            assert build_crec(a1).is_in_crec(probe).in_crec is check["expected_in_crec"]
