"""Neutral closed-set algebra for finite unions of circular intervals."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


TAU = math.tau
# Tolerance is used only to absorb machine-roundoff at a shared endpoint.  It
# must be far below any representable problem-scale angular gap, because this
# type models closed-set topology rather than display precision.
ANGLE_TOL_RAD = 1e-15


@dataclass(frozen=True, order=True)
class ClosedAngularInterval:
    """One canonical closed segment on the cut circle [0, 2*pi]."""

    start_rad: float
    end_rad: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.start_rad) and math.isfinite(self.end_rad)):
            raise ValueError("Angular interval endpoints must be finite.")
        if self.start_rad < -ANGLE_TOL_RAD or self.end_rad > TAU + ANGLE_TOL_RAD:
            raise ValueError("Canonical interval must lie in [0, 2*pi].")
        if self.end_rad < self.start_rad - ANGLE_TOL_RAD:
            raise ValueError("Canonical interval endpoints are reversed.")


@dataclass(frozen=True)
class CircularIntervalUnion:
    """A normalized finite closed union on S1, including EMPTY and FULL."""

    intervals: tuple[ClosedAngularInterval, ...]

    def __post_init__(self) -> None:
        normalized = _merge_canonical(self.intervals)
        if normalized != self.intervals:
            raise ValueError("CircularIntervalUnion must be constructed through a factory.")

    @classmethod
    def empty(cls) -> "CircularIntervalUnion":
        return cls(())

    @classmethod
    def full(cls) -> "CircularIntervalUnion":
        return cls((ClosedAngularInterval(0.0, TAU),))

    @classmethod
    def from_intervals(
        cls, intervals: Iterable[tuple[float, float]]
    ) -> "CircularIntervalUnion":
        canonical: list[ClosedAngularInterval] = []
        for start, end in intervals:
            if not (math.isfinite(start) and math.isfinite(end)):
                raise ValueError("Angular interval endpoints must be finite.")
            if end < start - ANGLE_TOL_RAD:
                raise ValueError("Input intervals must use a nondecreasing unwrapped parameter.")
            span = max(0.0, end - start)
            if span >= TAU:
                return cls.full()
            normalized_start = start % TAU
            normalized_end = normalized_start + span
            if normalized_end <= TAU + ANGLE_TOL_RAD:
                canonical.append(
                    ClosedAngularInterval(normalized_start, min(TAU, normalized_end))
                )
            else:
                canonical.append(ClosedAngularInterval(normalized_start, TAU))
                canonical.append(ClosedAngularInterval(0.0, normalized_end - TAU))
        return cls(_merge_canonical(tuple(canonical)))

    @classmethod
    def from_degrees(
        cls, intervals: Iterable[tuple[float, float]]
    ) -> "CircularIntervalUnion":
        return cls.from_intervals(
            (math.radians(start), math.radians(end)) for start, end in intervals
        )

    @property
    def is_empty(self) -> bool:
        return not self.intervals

    @property
    def is_full(self) -> bool:
        return (
            len(self.intervals) == 1
            and self.intervals[0].start_rad <= ANGLE_TOL_RAD
            and self.intervals[0].end_rad >= TAU - ANGLE_TOL_RAD
        )

    @property
    def component_count(self) -> int:
        if self.is_empty:
            return 0
        if self.is_full:
            return 1
        count = len(self.intervals)
        if (
            count > 1
            and self.intervals[0].start_rad <= ANGLE_TOL_RAD
            and self.intervals[-1].end_rad >= TAU - ANGLE_TOL_RAD
        ):
            count -= 1
        return count

    def contains(self, angle_rad: float, tolerance_rad: float = 1e-12) -> bool:
        if not math.isfinite(angle_rad):
            raise ValueError("Angle must be finite.")
        if self.is_full:
            return True
        angle = angle_rad % TAU
        return any(
            interval.start_rad - tolerance_rad <= angle <= interval.end_rad + tolerance_rad
            or (
                angle <= tolerance_rad
                and interval.end_rad >= TAU - tolerance_rad
            )
            for interval in self.intervals
        )

    def union(self, other: "CircularIntervalUnion") -> "CircularIntervalUnion":
        if self.is_full or other.is_full:
            return self.full()
        return CircularIntervalUnion(_merge_canonical(self.intervals + other.intervals))

    def dilated(self, radius_rad: float) -> "CircularIntervalUnion":
        if not (math.isfinite(radius_rad) and radius_rad >= 0.0):
            raise ValueError("Dilation radius must be finite and nonnegative.")
        if self.is_empty or self.is_full or radius_rad == 0.0:
            return self
        result = self.empty()
        for interval in self.intervals:
            expanded = self.from_intervals(
                ((interval.start_rad - radius_rad, interval.end_rad + radius_rad),)
            )
            result = result.union(expanded)
        return result

    def rotated(self, angle_rad: float) -> "CircularIntervalUnion":
        if not math.isfinite(angle_rad):
            raise ValueError("Rotation angle must be finite.")
        if self.is_empty or self.is_full:
            return self
        result = self.empty()
        for interval in self.intervals:
            result = result.union(
                self.from_intervals(
                    ((interval.start_rad + angle_rad, interval.end_rad + angle_rad),)
                )
            )
        return result

    def distance_to_angle(self, angle_rad: float) -> float:
        if self.is_empty:
            return math.inf
        if self.contains(angle_rad):
            return 0.0
        angle = angle_rad % TAU
        return min(
            _circular_distance(angle, endpoint)
            for interval in self.intervals
            for endpoint in (interval.start_rad, interval.end_rad % TAU)
        )

    def distance_to(self, other: "CircularIntervalUnion") -> float:
        if self.is_empty or other.is_empty:
            return math.inf
        if self.is_full or other.is_full:
            return 0.0
        for interval in self.intervals:
            if other.contains(interval.start_rad) or other.contains(interval.end_rad):
                return 0.0
        for interval in other.intervals:
            if self.contains(interval.start_rad) or self.contains(interval.end_rad):
                return 0.0
        return min(
            _circular_distance(left, right)
            for own in self.intervals
            for foreign in other.intervals
            for left in (own.start_rad, own.end_rad % TAU)
            for right in (foreign.start_rad, foreign.end_rad % TAU)
        )


def _merge_canonical(
    intervals: tuple[ClosedAngularInterval, ...]
) -> tuple[ClosedAngularInterval, ...]:
    if not intervals:
        return ()
    ordered = sorted(intervals)
    merged: list[ClosedAngularInterval] = []
    for interval in ordered:
        start = max(0.0, interval.start_rad)
        end = min(TAU, interval.end_rad)
        if not merged or start > merged[-1].end_rad + ANGLE_TOL_RAD:
            merged.append(ClosedAngularInterval(start, end))
        else:
            merged[-1] = ClosedAngularInterval(
                merged[-1].start_rad, max(merged[-1].end_rad, end)
            )
    if len(merged) == 1 and merged[0].end_rad - merged[0].start_rad >= TAU:
        return (ClosedAngularInterval(0.0, TAU),)
    return tuple(merged)


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % TAU - math.pi)
