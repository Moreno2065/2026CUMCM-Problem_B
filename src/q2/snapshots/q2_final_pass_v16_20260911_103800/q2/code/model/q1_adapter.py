"""Pure two-bearing adapter over the validated Q1 geometry evaluator."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from src.q1.code.q1_geometry import Measurement, Point, canonicalize_deg, solve_q1


class PointLike(Protocol):
    x: float
    y: float


@dataclass(frozen=True, order=True)
class Q1AdapterPoint:
    x: float
    y: float


@dataclass(frozen=True)
class Q1AdapterProvenance:
    evaluator: str
    measurement_labels: tuple[str, str]
    normalized_bearings_deg: tuple[float, float]
    epsilon_deg: float


@dataclass(frozen=True)
class Q1AdapterResult:
    status: str
    bounded: bool
    unbounded: bool
    affine_dimension: int | None
    ordered_vertices: tuple[Q1AdapterPoint, ...]
    diameter: float | None
    diameter_witness_pair: tuple[Q1AdapterPoint, Q1AdapterPoint] | None
    degeneracy: str
    provenance: Q1AdapterProvenance


def _coordinates(value: PointLike, label: str) -> tuple[float, float]:
    try:
        x, y = float(value.x), float(value.y)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(f"{label} must expose finite numeric x and y coordinates.") from error
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(f"{label} coordinates must be finite.")
    return x, y


def _point(value: Point) -> Q1AdapterPoint:
    return Q1AdapterPoint(value.x, value.y)


def evaluate_q1(
    S1: PointLike,
    theta1: float,
    S2: PointLike,
    beta: float,
    epsilon: float,
) -> Q1AdapterResult:
    """Evaluate exactly two closed bearing wedges through the frozen Q1 solver."""
    x1, y1 = _coordinates(S1, "S1")
    x2, y2 = _coordinates(S2, "S2")
    theta1_value, beta_value, epsilon_value = (
        float(theta1),
        float(beta),
        float(epsilon),
    )
    if not all(math.isfinite(value) for value in (theta1_value, beta_value, epsilon_value)):
        raise ValueError("Bearings and epsilon must be finite.")

    measurements = (
        Measurement(x1, y1, theta1_value, "S1"),
        Measurement(x2, y2, beta_value, "S2"),
    )
    solved = solve_q1(measurements, epsilon_deg=epsilon_value)
    vertices = tuple(_point(point) for point in solved.vertices)
    pair = (
        None
        if solved.diameter_pair is None
        else (_point(solved.diameter_pair[0]), _point(solved.diameter_pair[1]))
    )
    degeneracy = {0: "POINT", 1: "SEGMENT", 2: "AREA"}.get(
        solved.dimension, solved.status
    )
    provenance = Q1AdapterProvenance(
        evaluator="src.q1.code.q1_geometry.solve_q1",
        measurement_labels=("S1", "S2"),
        normalized_bearings_deg=(
            canonicalize_deg(theta1_value),
            canonicalize_deg(beta_value),
        ),
        epsilon_deg=epsilon_value,
    )
    return Q1AdapterResult(
        status=solved.status,
        bounded=solved.status != "UNBOUNDED",
        unbounded=solved.status == "UNBOUNDED",
        affine_dimension=solved.dimension,
        ordered_vertices=vertices,
        diameter=solved.diameter,
        diameter_witness_pair=pair,
        degeneracy=degeneracy,
        provenance=provenance,
    )
