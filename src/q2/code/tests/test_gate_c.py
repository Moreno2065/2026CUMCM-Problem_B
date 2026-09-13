"""Gate C contracts for circular intervals and near-aware angular images."""

from __future__ import annotations

import math
import random
import json
from pathlib import Path

import pytest

try:
    from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
except ModuleNotFoundError:
    CircularIntervalUnion = None

try:
    from src.q2.code.geometry.a1 import FirstObservation, build_a1
    from src.q2.code.geometry.angular_image import build_angular_image
    from src.q2.code.geometry.primitives import Point2
except ModuleNotFoundError:
    build_angular_image = None


def test_circular_interval_empty_full_and_wrapped_normalization() -> None:
    assert CircularIntervalUnion is not None
    empty = CircularIntervalUnion.empty()
    full = CircularIntervalUnion.full()
    wrapped = CircularIntervalUnion.from_degrees(((359.0, 361.0),))

    assert empty.is_empty and not empty.is_full
    assert full.is_full and not full.is_empty
    assert full.contains(math.radians(217.0))
    assert wrapped.component_count == 1
    assert wrapped.contains(math.radians(359.5))
    assert wrapped.contains(0.0)
    assert wrapped.contains(math.radians(0.5))
    assert not wrapped.contains(math.pi)


def test_circular_interval_handles_minus_plus_180_and_touching_merge() -> None:
    assert CircularIntervalUnion is not None
    seam = CircularIntervalUnion.from_degrees(((-181.0, -179.0),))
    touching = CircularIntervalUnion.from_degrees(((10.0, 20.0), (20.0, 30.0)))

    assert seam.contains(math.pi)
    assert seam.contains(-math.pi)
    assert seam.component_count == 1
    assert touching.component_count == 1
    assert touching.contains(math.radians(25.0))


def test_circular_dilation_merges_components_and_can_create_full_circle() -> None:
    assert CircularIntervalUnion is not None
    points = CircularIntervalUnion.from_degrees(((0.0, 0.0), (1.5, 1.5)))
    merged = points.dilated(math.radians(1.0))
    almost_full = CircularIntervalUnion.from_degrees(((10.0, 350.0),))

    assert points.component_count == 2
    assert merged.component_count == 1
    assert merged.contains(math.radians(0.75))
    assert almost_full.dilated(math.radians(10.0)).is_full


def test_circular_interval_does_not_close_a_real_subpicoradian_gap() -> None:
    almost = CircularIntervalUnion.from_intervals(((0.0, math.tau - 5e-13),))
    separate = CircularIntervalUnion.from_intervals(((1.0, 1.0), (1.0 + 5e-13, 1.0 + 5e-13)))

    assert not almost.is_full
    assert separate.component_count == 2


def test_circular_union_rotation_and_distances_are_periodic() -> None:
    assert CircularIntervalUnion is not None
    left = CircularIntervalUnion.from_degrees(((0.0, 5.0), (90.0, 95.0)))
    right = CircularIntervalUnion.from_degrees(((180.0, 185.0),))
    combined = left.union(right)
    rotated = combined.rotated(math.radians(30.0))

    assert combined.component_count == 3
    assert math.isclose(combined.distance_to_angle(math.radians(10.0)), math.radians(5.0))
    assert math.isclose(left.distance_to(right), math.radians(85.0))
    assert rotated.contains(math.radians(32.0))
    assert not rotated.contains(math.radians(2.0))


def _tangent_singleton_a1():
    return build_a1(
        FirstObservation(
            station=Point2(2000.0, 0.0),
            bearing_deg=114.84193276316712,
        )
    )


def test_point_a1_six_metres_from_s2_has_singleton_raw_image() -> None:
    assert build_angular_image is not None
    tangent = Point2(1620.0, 784.6018098373212)
    result = build_angular_image(_tangent_singleton_a1(), Point2(tangent.x + 6.0, tangent.y))

    assert not result.all_near
    assert result.spatial_component_count == 1
    assert len(result.raw_component_intervals) == 1
    assert result.raw_component_intervals[0].component_count == 1
    assert result.merged_closure.contains(math.pi)
    assert not result.merged_closure.contains(math.pi - math.radians(0.01))
    assert result.expanded_closure.contains(math.pi - math.radians(1.0))
    assert result.expanded_closure.contains(math.pi + math.radians(1.0))
    assert not result.full_circle


@pytest.mark.parametrize("separation_m", [5.0, 4.0])
def test_point_a1_at_or_inside_near_disk_has_empty_actual_image(separation_m: float) -> None:
    assert build_angular_image is not None
    tangent = Point2(1620.0, 784.6018098373212)
    result = build_angular_image(
        _tangent_singleton_a1(), Point2(tangent.x + separation_m, tangent.y)
    )

    assert result.all_near
    assert result.spatial_component_count == 0
    assert result.raw_component_intervals == ()
    assert result.merged_closure.is_empty
    assert result.expanded_closure.is_empty
    assert not result.full_circle


def test_point_strictly_beyond_five_metres_is_not_swallowed_by_tolerance() -> None:
    tangent = Point2(1620.0, 784.6018098373212)
    result = build_angular_image(
        _tangent_singleton_a1(), Point2(tangent.x + 5.0000000005, tangent.y)
    )
    assert not result.all_near
    assert not result.merged_closure.is_empty


def test_nondegenerate_image_can_be_full_circle_without_component_cap() -> None:
    assert build_angular_image is not None
    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    result = build_angular_image(a1, Point2(1000.0, 0.0))

    assert not result.all_near
    assert result.spatial_component_count >= 1
    assert result.merged_closure.is_full
    assert result.expanded_closure.is_full
    assert result.full_circle


def test_permanent_three_component_near_clipping_fixture() -> None:
    assert build_angular_image is not None
    a1 = build_a1(
        FirstObservation(
            station=Point2(-1761.0971373778152, -2562.1156141107817),
            bearing_deg=77.4420,
        )
    )
    result = build_angular_image(
        a1, Point2(-1414.5613933607547, -1106.0133123595463)
    )

    assert not result.all_near
    assert result.spatial_component_count == 3
    assert len(result.raw_component_intervals) == 3
    assert not result.merged_closure.is_empty


def test_double_wedge_tangent_is_two_strict_components_with_full_closure() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station2 = Point2(5.0 / math.sin(math.radians(1.0)), 0.0)
    result = build_angular_image(a1, station2)

    assert result.spatial_component_count == 2
    assert len(result.raw_component_intervals) == 2
    assert result.merged_closure.is_full
    assert result.full_circle
    assert {w.source_component_index for w in result.extrema_witnesses} == {0, 1}
    assert {event.source_component_index for event in result.boundary_events} == {0, 1}

    from src.q2.code.verifier.verify_angular import verify_angular_image

    report = verify_angular_image(
        a1, station2, result.merged_closure, result.expanded_closure, result.all_near
    )
    assert report.passed, report.failures


@pytest.mark.parametrize("gap_m", [5e-14, 8e-14, 1e-10])
def test_positive_subnanometre_wedge_channel_remains_connected(gap_m: float) -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station2 = Point2((5.0 + gap_m) / math.sin(math.radians(1.0)), 0.0)
    result = build_angular_image(a1, station2)
    assert result.spatial_component_count == 1


def test_angular_image_rejects_non_a1_boundary_registry() -> None:
    assert build_angular_image is not None
    from dataclasses import replace

    from src.q2.code.geometry.crec import build_crec

    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    wrong_registry = build_crec(a1).witnesses
    corrupted = replace(a1, boundary=wrong_registry)

    with pytest.raises(TypeError, match="A1BoundaryRegistry"):
        build_angular_image(corrupted, Point2(100.0, 0.0))


def test_independent_angular_verifier_uses_boundary_and_radial_paths() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    station2 = Point2(1000.0, 0.0)
    result = build_angular_image(a1, station2)
    report = verify_angular_image(
        a1,
        station2,
        result.merged_closure,
        result.expanded_closure,
        result.all_near,
        boundary_samples_per_piece=101,
        radial_angle_samples=101,
        radial_samples_per_angle=31,
    )

    assert report.passed
    assert report.boundary_points_checked > 0
    assert report.radial_points_checked > 0
    assert report.expanded_error_checks > 0
    assert report.max_missing_angle_rad == 0.0


def test_independent_angular_verifier_rejects_vacuous_empty_claim() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    station2 = Point2(1000.0, 0.0)
    empty = CircularIntervalUnion.empty()
    report = verify_angular_image(a1, station2, empty, empty, True)

    assert not report.passed
    assert report.failures


def test_independent_verifier_rejects_full_circle_overclaim() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0))
    station2 = Point2(250.0, 300.0)
    full = CircularIntervalUnion.full()
    report = verify_angular_image(a1, station2, full, full, False)
    assert not report.passed
    assert report.max_endpoint_disagreement_rad > 0.0


def test_independent_verifier_rejects_narrow_filled_gap_overclaim() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station2 = Point2(286.493, 0.0)
    forged = CircularIntervalUnion.from_intervals(
        (
            (0.0, 4.6931781252255345),
            (4.696693250503963, math.tau),
        )
    )
    report = verify_angular_image(
        a1, station2, forged, forged.dilated(math.radians(1.0)), False
    )
    assert not report.passed


def test_independent_verifier_rejects_tiny_artificial_hole() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    station2 = Point2(250.0, 300.0)
    forged = CircularIntervalUnion.from_intervals(
        (
            (4.027423682456046, 4.047823908922441),
            (4.04782490892244, 6.067496329095437),
        )
    )
    report = verify_angular_image(
        a1, station2, forged, forged.dilated(math.radians(1.0)), False
    )
    assert not report.passed


def test_independent_verifier_rejects_nonempty_claim_for_empty_a1() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(FirstObservation(station=Point2(3000.0, 0.0), bearing_deg=0.0))
    full = CircularIntervalUnion.full()
    report = verify_angular_image(a1, Point2(0.0, 0.0), full, full, False)
    assert not report.passed


def test_second_error_expansion_is_frozen_one_degree_not_first_epsilon() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    a1 = build_a1(
        FirstObservation(station=Point2(0.0, 0.0), bearing_deg=0.0, epsilon_deg=2.0)
    )
    station2 = Point2(250.0, 300.0)
    result = build_angular_image(a1, station2)
    report = verify_angular_image(
        a1, station2, result.merged_closure, result.expanded_closure, result.all_near
    )
    assert report.passed, report.failures


def test_verifier_c_has_no_solver_or_crec_import() -> None:
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "verifier" / "verify_angular.py"
    ).read_text(encoding="utf-8")
    assert "geometry.angular_image" not in source
    assert "geometry.crec" not in source


def test_fixed_seed_500_case_analytic_image_contains_both_dense_oracles() -> None:
    from src.q2.code.geometry.a1 import A1Dimension
    from src.q2.code.verifier.verify_angular import verify_angular_image

    rng = random.Random(20260911)
    for index in range(500):
        target_radius = rng.uniform(100.0, 1600.0)
        target_angle = rng.uniform(0.0, math.tau)
        target = Point2(
            target_radius * math.cos(target_angle),
            target_radius * math.sin(target_angle),
        )
        true_bearing = rng.uniform(0.0, math.tau)
        target_range = rng.uniform(20.0, 1450.0)
        station1 = Point2(
            target.x - target_range * math.cos(true_bearing),
            target.y - target_range * math.sin(true_bearing),
        )
        a1 = build_a1(
            FirstObservation(station1, math.degrees(true_bearing) + rng.uniform(-0.8, 0.8))
        )
        assert a1.dimension == A1Dimension.AREA
        if index % 2:
            station2 = Point2(target.x + rng.uniform(-8.0, 8.0), target.y + rng.uniform(-8.0, 8.0))
        else:
            station2 = Point2(
                station1.x + rng.uniform(-1800.0, 1800.0),
                station1.y + rng.uniform(-1800.0, 1800.0),
            )
        result = build_angular_image(a1, station2)
        report = verify_angular_image(
            a1,
            station2,
            result.merged_closure,
            result.expanded_closure,
            result.all_near,
            boundary_samples_per_piece=31,
            radial_angle_samples=31,
            radial_samples_per_angle=11,
        )
        assert report.passed, (index, report.failures)


def test_rigid_motion_and_wrap_covariance_of_angular_image() -> None:
    station1 = Point2(2000.0, 0.0)
    station2 = Point2(900.0, 300.0)
    bearing = 180.0
    base = build_angular_image(build_a1(FirstObservation(station1, bearing)), station2)
    rotation = math.radians(37.0)
    translation = Point2(321.0, -654.0)

    def transform(point: Point2) -> Point2:
        return Point2(
            math.cos(rotation) * point.x - math.sin(rotation) * point.y + translation.x,
            math.sin(rotation) * point.x + math.cos(rotation) * point.y + translation.y,
        )

    moved_a1 = build_a1(
        FirstObservation(transform(station1), bearing + 37.0),
        omega_center=transform(Point2(0.0, 0.0)),
    )
    moved = build_angular_image(moved_a1, transform(station2))
    expected = base.merged_closure.rotated(rotation)
    for index in range(1440):
        angle = math.tau * index / 1440
        assert moved.merged_closure.contains(angle) == expected.contains(angle)

    positive = build_angular_image(
        build_a1(FirstObservation(Point2(0.0, 0.0), 359.5)), Point2(-500.0, 0.0)
    )
    negative = build_angular_image(
        build_a1(FirstObservation(Point2(0.0, 0.0), -0.5)), Point2(-500.0, 0.0)
    )
    assert positive.merged_closure == negative.merged_closure


def test_clipped_components_expose_near_arc_and_endpoint_provenance() -> None:
    from src.q2.code.geometry.a1 import A1BoundaryLabel

    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    result = build_angular_image(a1, Point2(200.0, 0.0))
    assert len(result.raw_component_intervals) == result.spatial_component_count == 2
    assert any(event.source_label == "near_circle" for event in result.boundary_events)
    assert all(witness.source_component_index >= 0 for witness in result.extrema_witnesses)
    assert all(witness.source_piece_index >= 0 for witness in result.extrema_witnesses)
    assert not any(
        piece.label != A1BoundaryLabel.RHO_OUTER
        and getattr(piece.curve, "radius", None) == 1500.0
        for piece in a1.boundary.pieces
    )
    assert not any(getattr(piece.curve, "radius", None) == 1000.0 for piece in a1.boundary.pieces)


def test_rho_1500_arc_tangent_is_retained_as_an_extremum() -> None:
    a1 = build_a1(
        FirstObservation(
            Point2(2076.7525102614745, -2296.7203770041724),
            116.04544676998955,
        )
    )
    result = build_angular_image(a1, Point2(-1884.2883700881307, -2565.6633451029884))
    assert any(
        witness.source_label == "a1_rho_1500" and witness.event_kind == "tangent"
        for witness in result.extrema_witnesses
    )


def test_gate_c_persistent_fixtures_replay_through_both_oracles() -> None:
    from src.q2.code.verifier.verify_angular import verify_angular_image

    fixture_path = Path(__file__).parents[1] / "artifacts" / "q2_gate_c_fixtures.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 10

    for case in payload["cases"]:
        station = Point2(case["station"]["x"], case["station"]["y"])
        station2 = Point2(case["second_station"]["x"], case["second_station"]["y"])
        a1 = build_a1(FirstObservation(station, case["bearing_deg"]))
        result = build_angular_image(a1, station2)
        assert result.all_near is case["expected_all_near"], case["id"]
        assert result.spatial_component_count == case["expected_spatial_components"], case["id"]
        assert result.merged_closure.component_count == case["expected_angular_components"], case["id"]
        assert result.full_circle is case["expected_full_circle"], case["id"]
        assert result.expanded_closure.component_count == case["expected_expanded_components"], case["id"]

        report = verify_angular_image(
            a1,
            station2,
            result.merged_closure,
            result.expanded_closure,
            result.all_near,
            boundary_samples_per_piece=101,
            radial_angle_samples=101,
            radial_samples_per_angle=31,
        )
        assert report.passed, (case["id"], report.failures)
