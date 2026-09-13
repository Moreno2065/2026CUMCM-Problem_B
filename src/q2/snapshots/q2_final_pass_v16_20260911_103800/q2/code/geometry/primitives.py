"""Neutral two-dimensional primitives for the frozen Q2 geometry.

This module intentionally knows nothing about A1, reception witnesses, or Q1.
It provides only metric/vector operations that may be shared by distinct Q2
registries without sharing their physical-boundary semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, order=True)
class Point2:
    """A finite point/vector in metres."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError("Point2 coordinates must be finite.")

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def distance_to(self, other: "Point2") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def __add__(self, other: "Point2") -> "Point2":
        return Point2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point2") -> "Point2":
        return Point2(self.x - other.x, self.y - other.y)

    def scaled(self, scalar: float) -> "Point2":
        if not math.isfinite(scalar):
            raise ValueError("Scale must be finite.")
        return Point2(self.x * scalar, self.y * scalar)

    def dot(self, other: "Point2") -> float:
        return self.x * other.x + self.y * other.y

    def angle_rad(self) -> float:
        if self.x == 0.0 and self.y == 0.0:
            raise ValueError("The zero vector has no bearing angle.")
        return math.atan2(self.y, self.x)


@dataclass(frozen=True)
class LineSegment:
    """A non-degenerate closed Euclidean line segment."""

    start: Point2
    end: Point2

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise ValueError("LineSegment must be non-degenerate.")

    def point_at(self, fraction: float) -> Point2:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("Segment fraction must be in [0, 1].")
        return self.start + (self.end - self.start).scaled(fraction)

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass(frozen=True)
class CircularArc:
    """A closed counter-clockwise arc with an explicitly unwrapped parameter."""

    center: Point2
    radius: float
    start_angle_rad: float
    end_angle_rad: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.radius) and self.radius > 0.0):
            raise ValueError("CircularArc radius must be finite and positive.")
        if not (math.isfinite(self.start_angle_rad) and math.isfinite(self.end_angle_rad)):
            raise ValueError("CircularArc parameters must be finite.")
        if self.end_angle_rad <= self.start_angle_rad:
            raise ValueError("CircularArc must have positive counter-clockwise span.")
        if self.end_angle_rad - self.start_angle_rad > math.tau + 1e-12:
            raise ValueError("CircularArc span cannot exceed one full turn.")

    @property
    def angle_span_rad(self) -> float:
        return self.end_angle_rad - self.start_angle_rad

    def point_at(self, fraction: float) -> Point2:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("Arc fraction must be in [0, 1].")
        angle = self.start_angle_rad + fraction * self.angle_span_rad
        return self.center + Point2(math.cos(angle), math.sin(angle)).scaled(self.radius)

    @property
    def endpoints(self) -> tuple[Point2, Point2]:
        return self.point_at(0.0), self.point_at(1.0)


@dataclass(frozen=True)
class BoundaryPoint:
    """A closed zero-dimensional geometry primitive.

    It deliberately carries no A1-specific semantics so later modules can use
    it for tangent and clipping degeneracies without inventing a zero-length
    segment or zero-span arc.
    """

    point: Point2

    def point_at(self, fraction: float) -> Point2:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("Point fraction must be in [0, 1].")
        return self.point
