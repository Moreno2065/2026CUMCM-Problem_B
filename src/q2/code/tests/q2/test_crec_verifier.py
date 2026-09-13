"""Independent Crec verification: deep Omega arcs, the 1500 m guard, boundaries."""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.a1 import (
    A1Dimension,
    OUTER_RADIUS_M,
    FirstObservation,
    build_a1,
)
from src.q2.code.geometry.crec import (
    CompatibleRadiusMode,
    CrecWitnessLabel,
    CrecWitnessPiece,
    CrecWitnessRegistry,
    build_crec,
    is_in_crec,
)
from src.q2.code.geometry.primitives import CircularArc, Point2
from src.q2.code.verifier.verify_crec import verify_crec
from src.q2.code.verifier.verify_crec_deep import (
    verify_crec_deep_arc_witnesses,
    verified_in_crec,
)


DEEP_OBSERVATION = FirstObservation(Point2(3000.0, 0.0), 180.0)
DEEP_A1 = build_a1(DEEP_OBSERVATION)
PROBES = (
    Point2(300.0, 300.0),
    Point2(-500.0, 200.0),
    Point2(900.0, 900.0),
    Point2(0.0, 0.0),
)


def test_deep_entry_geometry_actually_produces_radial_depth_arcs() -> None:
    crec = build_crec(DEEP_A1)

    deep = [
        piece
        for piece in crec.witnesses.pieces
        if piece.radius_mode == CompatibleRadiusMode.RADIAL_DEPTH
    ]
    assert deep, "rho>1000 Omega entry must create a radial-depth witness arc"


def test_deep_omega_arc_witnesses_survive_an_independent_dense_scan() -> None:
    crec = build_crec(DEEP_A1)

    for second_station in PROBES:
        report = verify_crec_deep_arc_witnesses(
            crec, second_station, base_samples=2049
        )
        assert report.checked_arc_count >= 1
        assert report.passed, report.failures
        assert report.max_gap_m <= 1e-6


def test_analytic_crec_never_underestimates_the_independent_dense_phi() -> None:
    crec = build_crec(DEEP_A1)

    for second_station in PROBES:
        analytic = is_in_crec(crec, second_station)
        report = verify_crec(
            DEEP_A1,
            second_station,
            analytic_max_violation_m=analytic.max_violation_m,
            analytic_in_crec=analytic.in_crec,
            angle_samples=721,
            radial_samples=129,
        )
        assert report.passed, report.failures


def test_verified_membership_agrees_with_the_fast_path_when_it_should() -> None:
    crec = build_crec(DEEP_A1)

    for second_station in PROBES:
        fast = is_in_crec(crec, second_station)
        verified = verified_in_crec(crec, second_station, base_samples=1025)
        assert verified.in_crec == fast.in_crec
        assert verified.max_violation_m >= fast.max_violation_m - 1e-9


def test_s1_belongs_to_every_supported_crec_region() -> None:
    for station, bearing in (
        (Point2(0.0, 0.0), 0.0),
        (Point2(1700.0, 0.0), 0.0),
        (Point2(2000.0, 0.0), 180.0),
        (Point2(3000.0, 0.0), 180.0),
    ):
        a1 = build_a1(FirstObservation(station, bearing))
        crec = build_crec(a1)
        assert is_in_crec(crec, station).in_crec


def test_rho_1500_is_never_registered_as_a_deep_end_crec_witness() -> None:
    station = Point2(0.0, 0.0)
    forbidden = CrecWitnessPiece(
        CrecWitnessLabel.RHO_1500_AS_DEEP_END_WITNESS,
        CircularArc(station, 1500.0, 0.0, 1.0),
        CompatibleRadiusMode.RADIAL_DEPTH,
        "forbidden",
    )
    with pytest.raises(ValueError, match="rho=1500"):
        CrecWitnessRegistry(
            pieces=(forbidden,),
            first_station=station,
            omega_center=Point2(0.0, 0.0),
            omega_radius_m=1800.0,
        )

    # No supported AREA Crec registry may contain this forbidden witness either.
    for station_xy, bearing in (
        (Point2(0.0, 0.0), 0.0),
        (Point2(1700.0, 0.0), 0.0),
        (Point2(3000.0, 0.0), 180.0),
    ):
        a1 = build_a1(FirstObservation(station_xy, bearing))
        assert a1.dimension == A1Dimension.AREA
        crec = build_crec(a1)
        assert all(
            piece.label != CrecWitnessLabel.RHO_1500_AS_DEEP_END_WITNESS
            for piece in crec.witnesses.pieces
        )
        # 1500 m is still part of A1: radial intervals never exceed it.
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            angle = a1.observation.wedge_limits_rad[0] + fraction * (
                a1.observation.wedge_limits_rad[1] - a1.observation.wedge_limits_rad[0]
            )
            radial = a1.radial_interval(angle)
            if radial is not None:
                assert radial[1] <= OUTER_RADIUS_M + 1e-9


def test_near_boundary_membership_flips_exactly_at_the_violation_zero() -> None:
    crec = build_crec(build_a1(FirstObservation(Point2(0.0, 0.0), 0.0)))

    assert is_in_crec(crec, Point2(0.0, 0.0)).in_crec
    far = Point2(0.0, 2600.0)
    evaluation = is_in_crec(crec, far)
    assert not evaluation.in_crec
    assert evaluation.max_violation_m > 0.0
    assert math.isclose(evaluation.margin_m, -evaluation.max_violation_m, abs_tol=1e-12)
