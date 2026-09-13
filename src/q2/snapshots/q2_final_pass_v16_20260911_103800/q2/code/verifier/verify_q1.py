"""Independent Gate D verification through the validated Q1 chain B."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
import sys

from src.q1.code import q1_geometry as _q1_geometry
from src.q2.code.model.q1_adapter import Q1AdapterPoint, Q1AdapterResult

# q1_verify retains a historical top-level import of q1_geometry. Bind that
# name only while loading the validated module, then restore the caller's
# ambient module table. Reload a cached verifier if it was previously built
# against a different module bearing the same top-level name.
_MISSING_MODULE = object()
_ambient_q1_geometry = sys.modules.get("q1_geometry", _MISSING_MODULE)
try:
    sys.modules["q1_geometry"] = _q1_geometry
    _q1_verify = importlib.import_module("src.q1.code.q1_verify")
    if _q1_verify.HalfPlane is not _q1_geometry.HalfPlane:
        _q1_verify = importlib.reload(_q1_verify)
finally:
    if _ambient_q1_geometry is _MISSING_MODULE:
        sys.modules.pop("q1_geometry", None)
    else:
        sys.modules["q1_geometry"] = _ambient_q1_geometry


@dataclass(frozen=True)
class Q1VerificationReport:
    passed: bool
    independent_status: str
    status_agrees: bool
    bounded_agrees: bool
    dimension_agrees: bool
    vertices_agree: bool
    diameter_agrees: bool
    diameter_witness_valid: bool
    degeneracy_agrees: bool
    provenance_agrees: bool
    vertex_hausdorff: float | None
    diameter_abs_diff: float | None
    failures: tuple[str, ...]


def _measurement(point, bearing: float, label: str) -> _q1_geometry.Measurement:
    return _q1_geometry.Measurement(float(point.x), float(point.y), float(bearing), label)


def _affine_dimension(points: list[_q1_geometry.Point]) -> int | None:
    if not points:
        return None
    diameter, pair = _q1_verify.rotating_calipers_diameter(points)
    scale = max(1.0, diameter, *(abs(value) for point in points for value in (point.x, point.y)))
    tolerance = max(5e-8, 5e-12 * scale)
    if diameter <= tolerance:
        return 0
    first, second = pair
    maximum = max(
        abs(
            (second.x - first.x) * (point.y - first.y)
            - (second.y - first.y) * (point.x - first.x)
        )
        / diameter
        for point in points
    )
    return 1 if maximum <= tolerance else 2


def _as_q1_points(points: tuple[Q1AdapterPoint, ...]) -> list[_q1_geometry.Point]:
    return [_q1_geometry.Point(point.x, point.y) for point in points]


def _witness_valid(candidate: Q1AdapterResult, tolerance: float) -> bool:
    if candidate.status != "OK":
        return candidate.diameter_witness_pair is None
    if candidate.diameter is None or candidate.diameter_witness_pair is None:
        return False
    first, second = candidate.diameter_witness_pair
    distance = math.hypot(first.x - second.x, first.y - second.y)
    if abs(distance - candidate.diameter) > tolerance:
        return False
    return first in candidate.ordered_vertices and second in candidate.ordered_vertices


def _points_close(left, right, tolerance: float) -> bool:
    return math.hypot(left.x - right.x, left.y - right.y) <= tolerance


def _ordered_vertices_agree(
    candidate: tuple[Q1AdapterPoint, ...],
    verifier: list[_q1_geometry.Point],
    dimension: int | None,
    tolerance: float,
) -> bool:
    if dimension is None:
        return not candidate and not verifier
    if dimension == 0:
        return len(candidate) == 1 and all(
            _points_close(candidate[0], point, tolerance) for point in verifier
        )
    if len(candidate) != len(verifier):
        return False
    if dimension == 1:
        return all(
            _points_close(left, right, tolerance)
            for left, right in zip(candidate, verifier)
        )
    count = len(candidate)
    return any(
        all(
            _points_close(candidate[index], verifier[(index + offset) % count], tolerance)
            for index in range(count)
        )
        for offset in range(count)
    )


def verify_q1_adapter(
    S1,
    theta1: float,
    S2,
    beta: float,
    epsilon: float,
    candidate: Q1AdapterResult,
) -> Q1VerificationReport:
    """Cross-check an adapter result without executing the adapter evaluator."""
    measurements = (
        _measurement(S1, theta1, "S1"),
        _measurement(S2, beta, "S2"),
    )
    independent = _q1_verify.verify_measurements(
        measurements, main=None, epsilon_deg=float(epsilon)
    )
    status = independent["lp_status"]
    status_agrees = candidate.status == status
    bounded_agrees = candidate.bounded == (status != "UNBOUNDED") and candidate.unbounded == (
        status == "UNBOUNDED"
    )
    failures: list[str] = []
    if not status_agrees:
        failures.append("status differs from independent LP classification")
    if not bounded_agrees:
        failures.append("bounded/unbounded flags disagree with independent LP classification")

    dimension_agrees = candidate.affine_dimension is None
    vertices_agree = not candidate.ordered_vertices
    diameter_agrees = candidate.diameter is None or (
        status == "UNBOUNDED" and math.isinf(candidate.diameter)
    )
    vertex_distance: float | None = None
    diameter_difference: float | None = None
    scale = 1.0

    if status == "OK":
        verifier_vertices = [
            _q1_geometry.Point(row["x"], row["y"])
            for row in independent.get("verifier_vertices", [])
        ]
        verifier_dimension = _affine_dimension(verifier_vertices)
        dimension_agrees = candidate.affine_dimension == verifier_dimension
        candidate_vertices = _as_q1_points(candidate.ordered_vertices)
        vertex_distance = _q1_verify.hausdorff_vertex_distance(
            candidate_vertices, verifier_vertices
        )
        verifier_diameter = float(independent["verifier_diameter"])
        scale = max(1.0, verifier_diameter, candidate.diameter or 0.0)
        geometry_tolerance = max(5e-8, 5e-10 * scale)
        vertices_agree = vertex_distance <= geometry_tolerance and _ordered_vertices_agree(
            candidate.ordered_vertices,
            verifier_vertices,
            verifier_dimension,
            geometry_tolerance,
        )
        diameter_difference = (
            math.inf
            if candidate.diameter is None
            else abs(candidate.diameter - verifier_diameter)
        )
        diameter_agrees = diameter_difference <= geometry_tolerance
        if not dimension_agrees:
            failures.append("affine dimension differs from independent clipped hull")
        if not vertices_agree:
            failures.append("ordered vertex set differs from independent clipped hull")
        if not diameter_agrees:
            failures.append("diameter differs from independent rotating-calipers result")
    elif status == "EMPTY":
        dimension_agrees = candidate.affine_dimension is None
        vertices_agree = not candidate.ordered_vertices
        diameter_agrees = candidate.diameter is None
    elif status == "UNBOUNDED":
        dimension_agrees = candidate.affine_dimension is None
        vertices_agree = not candidate.ordered_vertices
        diameter_agrees = candidate.diameter is not None and math.isinf(candidate.diameter)

    if not dimension_agrees and "affine dimension differs from independent clipped hull" not in failures:
        failures.append("affine dimension is inconsistent with independent status")
    if not vertices_agree and "ordered vertex set differs from independent clipped hull" not in failures:
        failures.append("vertices are inconsistent with independent status")
    if not diameter_agrees and "diameter differs from independent rotating-calipers result" not in failures:
        failures.append("diameter is inconsistent with independent status")

    witness_valid = _witness_valid(candidate, max(5e-8, 5e-10 * scale))
    if not witness_valid:
        failures.append("diameter witness pair is missing or inconsistent")

    expected_degeneracy = {0: "POINT", 1: "SEGMENT", 2: "AREA"}.get(
        candidate.affine_dimension, status
    )
    degeneracy_agrees = candidate.degeneracy == expected_degeneracy
    if not degeneracy_agrees:
        failures.append("degeneracy label disagrees with independently verified dimension")

    expected_bearings = (
        _q1_geometry.canonicalize_deg(float(theta1)),
        _q1_geometry.canonicalize_deg(float(beta)),
    )
    provenance_agrees = (
        candidate.provenance.evaluator == "src.q1.code.q1_geometry.solve_q1"
        and candidate.provenance.measurement_labels == ("S1", "S2")
        and candidate.provenance.normalized_bearings_deg == expected_bearings
        and candidate.provenance.epsilon_deg == float(epsilon)
    )
    if not provenance_agrees:
        failures.append("provenance disagrees with the verified evaluator inputs")

    return Q1VerificationReport(
        passed=not failures,
        independent_status=status,
        status_agrees=status_agrees,
        bounded_agrees=bounded_agrees,
        dimension_agrees=dimension_agrees,
        vertices_agree=vertices_agree,
        diameter_agrees=diameter_agrees,
        diameter_witness_valid=witness_valid,
        degeneracy_agrees=degeneracy_agrees,
        provenance_agrees=provenance_agrees,
        vertex_hausdorff=vertex_distance,
        diameter_abs_diff=diameter_difference,
        failures=tuple(failures),
    )
