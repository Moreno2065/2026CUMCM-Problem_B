"""Gate D contracts for the pure two-bearing Q1 adapter."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from src.q2.code.geometry.primitives import Point2

try:
    from src.q2.code.model.q1_adapter import evaluate_q1
    from src.q2.code.verifier.verify_q1 import verify_q1_adapter
except ModuleNotFoundError:
    evaluate_q1 = None
    verify_q1_adapter = None


def _evaluate(
    station1: tuple[float, float],
    theta1: float,
    station2: tuple[float, float],
    beta: float,
    epsilon: float = 1.0,
):
    assert evaluate_q1 is not None
    return evaluate_q1(Point2(*station1), theta1, Point2(*station2), beta, epsilon)


@pytest.mark.parametrize(
    ("case_id", "station1", "theta1", "station2", "beta", "status", "dimension", "vertices"),
    [
        ("quadrilateral", (-500.0, 0.0), 0.0, (-250.0, -250.0 * math.sqrt(3.0)), 60.0, "OK", 2, 4),
        ("triangle", (0.0, 0.0), 1.0, (1.0, 0.0), 180.0, "OK", 2, 3),
        ("segment", (0.0, 0.0), 1.0, (1.0, 0.0), 181.0, "OK", 1, 2),
        ("point", (0.0, 0.0), 1.0, (0.0, 0.0), 181.0, "OK", 0, 1),
        ("empty", (0.0, 0.0), 1.0, (0.0, 1.0), 3.0, "EMPTY", None, 0),
        ("unbounded", (0.0, 0.0), 37.0, (10.0, 0.0), 37.5, "UNBOUNDED", None, 0),
        (
            "near_parallel",
            (-500.0, 0.0),
            0.0,
            (-500.0 * math.cos(math.radians(2.01)), -500.0 * math.sin(math.radians(2.01))),
            2.01,
            "OK",
            2,
            4,
        ),
    ],
)
def test_adapter_classifies_frozen_two_bearing_fixtures(
    case_id, station1, theta1, station2, beta, status, dimension, vertices
) -> None:
    result = _evaluate(station1, theta1, station2, beta)

    assert result.status == status, case_id
    assert result.affine_dimension == dimension, case_id
    assert len(result.ordered_vertices) == vertices, case_id
    assert result.bounded is (status != "UNBOUNDED"), case_id
    assert result.unbounded is (status == "UNBOUNDED"), case_id
    assert result.degeneracy == ({2: "AREA", 1: "SEGMENT", 0: "POINT"}.get(dimension, status))
    assert result.provenance.evaluator == "src.q1.code.q1_geometry.solve_q1"


def test_adapter_reports_diameter_and_witness_pair() -> None:
    result = _evaluate((0.0, 0.0), 1.0, (1.0, 0.0), 180.0)

    assert result.status == "OK"
    assert result.diameter == pytest.approx(1.0)
    assert result.diameter_witness_pair is not None
    first, second = result.diameter_witness_pair
    assert math.hypot(first.x - second.x, first.y - second.y) == pytest.approx(result.diameter)
    assert first in result.ordered_vertices
    assert second in result.ordered_vertices


def test_wraparound_is_exactly_equivalent_at_adapter_boundary() -> None:
    station2 = (-250.0, -250.0 * math.sqrt(3.0))
    wrapped = _evaluate((-500.0, 0.0), 359.5, station2, 60.5)
    negative = _evaluate((-500.0, 0.0), -0.5, station2, 60.5)

    assert wrapped.status == negative.status == "OK"
    assert wrapped.affine_dimension == negative.affine_dimension
    assert wrapped.ordered_vertices == negative.ordered_vertices
    assert wrapped.diameter == negative.diameter


def test_both_station_apices_are_included_in_closed_quadrilateral() -> None:
    result = _evaluate((0.0, 0.0), 0.0, (1.0, 0.0), 180.0)

    assert result.status == "OK"
    assert result.affine_dimension == 2
    coordinates = {(point.x, point.y) for point in result.ordered_vertices}
    assert (0.0, 0.0) in coordinates
    assert (1.0, 0.0) in coordinates


@pytest.mark.parametrize(
    ("station1", "theta1", "station2", "beta"),
    [
        ((-500.0, 0.0), 0.0, (-250.0, -250.0 * math.sqrt(3.0)), 60.0),
        ((0.0, 0.0), 1.0, (1.0, 0.0), 180.0),
        ((0.0, 0.0), 1.0, (1.0, 0.0), 181.0),
        ((0.0, 0.0), 1.0, (0.0, 0.0), 181.0),
        ((0.0, 0.0), 1.0, (0.0, 1.0), 3.0),
        ((0.0, 0.0), 37.0, (10.0, 0.0), 37.5),
        (
            (-500.0, 0.0),
            0.0,
            (-500.0 * math.cos(math.radians(2.01)), -500.0 * math.sin(math.radians(2.01))),
            2.01,
        ),
    ],
)
def test_independent_q1_verifier_agrees_with_adapter(station1, theta1, station2, beta) -> None:
    assert verify_q1_adapter is not None
    result = _evaluate(station1, theta1, station2, beta)
    report = verify_q1_adapter(
        Point2(*station1), theta1, Point2(*station2), beta, 1.0, result
    )

    assert report.passed, report.failures
    assert report.status_agrees
    assert report.dimension_agrees
    assert report.diameter_agrees
    assert report.vertices_agree


def test_adapter_public_signature_and_source_are_physically_isolated() -> None:
    assert evaluate_q1 is not None
    assert list(inspect.signature(evaluate_q1).parameters) == [
        "S1",
        "theta1",
        "S2",
        "beta",
        "epsilon",
    ]
    source = (Path(__file__).parents[1] / "model" / "q1_adapter.py").read_text(encoding="utf-8").lower()
    for forbidden in ("geometry.a1", "geometry.crec", "omega", "near_radius", "1000.0", "1500.0"):
        assert forbidden not in source


def test_verifier_uses_independent_q1_chain_without_calling_adapter() -> None:
    source = (Path(__file__).parents[1] / "verifier" / "verify_q1.py").read_text(encoding="utf-8")

    assert "q1_verify" in source
    assert "evaluate_q1(" not in source


def test_verifier_rejects_reversed_area_vertex_order() -> None:
    assert verify_q1_adapter is not None
    result = _evaluate((-500.0, 0.0), 0.0, (-250.0, -250.0 * math.sqrt(3.0)), 60.0)
    corrupted = replace(result, ordered_vertices=tuple(reversed(result.ordered_vertices)))

    report = verify_q1_adapter(
        Point2(-500.0, 0.0),
        0.0,
        Point2(-250.0, -250.0 * math.sqrt(3.0)),
        60.0,
        1.0,
        corrupted,
    )

    assert not report.passed
    assert not report.vertices_agree


def test_verifier_rejects_forged_degeneracy_and_provenance() -> None:
    assert verify_q1_adapter is not None
    result = _evaluate((0.0, 0.0), 1.0, (1.0, 0.0), 180.0)
    forged_provenance = replace(result.provenance, evaluator="forged")
    corrupted = replace(result, degeneracy="POINT", provenance=forged_provenance)

    report = verify_q1_adapter(
        Point2(0.0, 0.0), 1.0, Point2(1.0, 0.0), 180.0, 1.0, corrupted
    )

    assert not report.passed
    assert not report.degeneracy_agrees
    assert not report.provenance_agrees


def test_verifier_import_isolated_from_ambient_q1_geometry_module() -> None:
    script = textwrap.dedent(
        """
        import sys
        import types

        poison = types.ModuleType("q1_geometry")
        sys.modules["q1_geometry"] = poison

        from src.q2.code.geometry.primitives import Point2
        from src.q2.code.model.q1_adapter import evaluate_q1
        from src.q2.code.verifier.verify_q1 import verify_q1_adapter

        station1 = Point2(0.0, 0.0)
        station2 = Point2(1.0, 0.0)
        candidate = evaluate_q1(station1, 1.0, station2, 180.0, 1.0)
        report = verify_q1_adapter(
            station1, 1.0, station2, 180.0, 1.0, candidate
        )
        assert report.passed, report.failures
        assert sys.modules["q1_geometry"] is poison
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[4],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
