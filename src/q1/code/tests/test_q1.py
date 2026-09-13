import math

from q1_geometry import (
    Measurement,
    Point,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNBOUNDED,
    analyze_bounded_vertices,
    solve_q1,
    solve_q1_reference,
)
from q1_verify import deterministic_mec, verify_measurements


def assert_rel(actual, expected, rtol=1e-10, atol=1e-10):
    assert math.isclose(actual, expected, rel_tol=rtol, abs_tol=atol), (actual, expected)


def test_t1_empty_before_unbounded():
    ms = [Measurement(0, 0, 1), Measurement(0, 1, 3)]
    r = solve_q1(ms)
    assert r.status == STATUS_EMPTY
    v = verify_measurements(ms, main=r)
    assert v["lp_status"] == STATUS_EMPTY
    assert v["status_agrees"] is True


def test_t2_two_station_noncoverage_counterexample():
    ms = [
        Measurement(-989.870592, 0.0, 0.955500),
        Measurement(54.647151, -931.757494, 92.372793),
    ]
    r = solve_q1(ms)
    assert r.status == STATUS_OK
    assert r.dimension == 2
    assert r.covered_by_diameter_disk is False
    assert_rel(r.diameter, 48.86413922424335, rtol=2e-11)
    assert_rel(r.rho_viol, 1.01020649778, rtol=2e-10)
    assert_rel(r.max_radial_excess, 0.2493658642, rtol=5e-9, atol=5e-9)

    mec = deterministic_mec(r.vertices)
    assert len(mec.support_indices) == 3
    ratio = 2.0 * mec.radius / r.diameter
    assert_rel(ratio, 1.000051718263, rtol=2e-10)

    v = verify_measurements(ms, main=r)
    assert v["status_agrees"] is True
    assert v["diameter_rel_diff"] < 1e-9


def _rotate_about(p: Point, center: Point, deg: float) -> Point:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    dx, dy = p.x - center.x, p.y - center.y
    return Point(center.x + c * dx - s * dy, center.y + s * dx + c * dy)


def test_t3_equilateral_realizable_counterexample():
    sqrt3 = math.sqrt(3.0)
    G = Point(10.0, 10.0 * sqrt3 / 3.0)
    L = 10.0 * sqrt3 / math.tan(math.radians(2.0)) - 10.0
    s1 = Point(-L, 0.0)
    s2 = _rotate_about(s1, G, 120.0)
    s3 = _rotate_about(s1, G, 240.0)
    ms = [
        Measurement(s1.x, s1.y, 1.0),
        Measurement(s2.x, s2.y, 121.0),
        Measurement(s3.x, s3.y, 241.0),
    ]
    r = solve_q1(ms)
    assert r.status == STATUS_OK
    assert r.dimension == 2
    assert r.covered_by_diameter_disk is False
    assert_rel(r.diameter, 20.0, rtol=1e-12, atol=1e-11)
    mec = deterministic_mec(r.vertices)
    assert_rel(2.0 * mec.radius / r.diameter, 2.0 / sqrt3, rtol=1e-12, atol=1e-12)


def test_t4_point_postprocessing():
    dim, vertices, area, d, pair, covered, center, radius, excess, rho = analyze_bounded_vertices([Point(0, 0)])
    assert dim == 0
    assert vertices == [Point(0, 0)]
    assert d == 0.0
    assert area == 0.0
    assert covered is True
    assert radius == 0.0


def test_t5_segment_postprocessing():
    pts = [Point(0, 0), Point(0.25, 0), Point(1, 0), Point(0.75, 0)]
    dim, vertices, area, d, pair, covered, center, radius, excess, rho = analyze_bounded_vertices(pts)
    assert dim == 1
    assert_rel(d, 1.0)
    assert area == 0.0
    assert covered is True
    assert set(vertices) == {Point(0, 0), Point(1, 0)}


def test_t6_angle_wrap_metamorphic_equivalence():
    y2 = -250.0 * math.sqrt(3.0)
    a = [Measurement(-500, 0, 359.5), Measurement(-250, y2, 60.5)]
    b = [Measurement(-500, 0, -0.5), Measurement(-250, y2, 60.5)]
    ra, rb = solve_q1(a), solve_q1(b)
    assert (ra.status, ra.dimension, ra.covered_by_diameter_disk) == (
        rb.status,
        rb.dimension,
        rb.covered_by_diameter_disk,
    )
    assert_rel(ra.diameter, rb.diameter, rtol=1e-12, atol=1e-10)
    assert len(ra.vertices) == len(rb.vertices)
    for p, q in zip(ra.vertices, rb.vertices):
        assert_rel(p.x, q.x, rtol=1e-12, atol=1e-9)
        assert_rel(p.y, q.y, rtol=1e-12, atol=1e-9)


def test_t7_healthy_fixture_small_perturbation():
    y2 = -250.0 * math.sqrt(3.0)
    base = [Measurement(-500, 0, 0), Measurement(-250, y2, 60)]
    pert = [Measurement(-500, 0, 0), Measurement(-250, y2, 60.000000001)]
    r0, r1 = solve_q1(base), solve_q1(pert)
    assert r0.status == r1.status == STATUS_OK
    assert r0.dimension == r1.dimension == 2
    assert r0.covered_by_diameter_disk == r1.covered_by_diameter_disk
    assert_rel(r0.diameter, 34.9420682302265066, rtol=2e-11)
    assert abs(r1.diameter - r0.diameter) / r0.diameter < 1e-8


def test_t8_near_unbounded_but_finite():
    gamma = 2.01
    a = math.radians(gamma)
    ms = [
        Measurement(-500.0, 0.0, 0.0),
        Measurement(-500.0 * math.cos(a), -500.0 * math.sin(a), gamma),
    ]
    r = solve_q1(ms)
    assert r.status == STATUS_OK
    assert r.dimension == 2
    assert math.isfinite(r.diameter)
    assert_rel(r.diameter, 100244.33804648454, rtol=3e-10, atol=1e-6)
    assert r.diameter > 100000.0  # explicitly forbid silent clipping by an arbitrary box

    v = verify_measurements(ms, main=r)
    assert v["status_agrees"] is True
    assert v["diameter_rel_diff"] < 1e-9


def test_single_measurement_is_unbounded():
    r = solve_q1([Measurement(0, 0, 37.0)])
    assert r.status == STATUS_UNBOUNDED
    assert math.isinf(r.diameter)
    assert r.escape_direction_deg is not None


def test_cli_serialization_semantics_for_unbounded():
    r = solve_q1([Measurement(0, 0, 10)])
    payload = r.as_dict()
    assert payload["status"] == STATUS_UNBOUNDED
    assert payload["diameter"] is None
    assert payload["diameter_is_infinite"] is True


def test_default_numba_matches_reference_on_hard_fixtures():
    fixtures = [
        [
            Measurement(-989.870592, 0.0, 0.955500),
            Measurement(54.647151, -931.757494, 92.372793),
        ],
    ]
    gamma = 2.01
    a = math.radians(gamma)
    fixtures.append([
        Measurement(-500.0, 0.0, 0.0),
        Measurement(-500.0 * math.cos(a), -500.0 * math.sin(a), gamma),
    ])

    for ms in fixtures:
        fast = solve_q1(ms)  # default backend must be Numba when available
        ref = solve_q1_reference(ms)
        assert (fast.status, fast.dimension, fast.covered_by_diameter_disk) == (
            ref.status, ref.dimension, ref.covered_by_diameter_disk
        )
        if fast.diameter is not None and math.isfinite(fast.diameter):
            assert_rel(fast.diameter, ref.diameter, rtol=1e-11, atol=1e-8)
        assert len(fast.vertices) == len(ref.vertices)
        for p, q in zip(fast.vertices, ref.vertices):
            assert_rel(p.x, q.x, rtol=1e-11, atol=1e-8)
            assert_rel(p.y, q.y, rtol=1e-11, atol=1e-8)
