"""Deterministic evaluated-result registry and best-known Q2 incumbent."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.q2_point import Q2PointResult


@dataclass(frozen=True)
class EvaluationRecord:
    """One unique production evaluation and its first-seen provenance."""

    result: Q2PointResult
    source: str
    stage: str
    evaluation_id: int


@dataclass(frozen=True)
class BestKnownIncumbent:
    """A valid Q2 result plus the provenance used to promote it."""

    result: Q2PointResult
    source: str
    stage: str
    evaluation_id: int

    @property
    def S2(self) -> Point2:
        return self.result.S2

    @property
    def Q(self) -> float | None:
        return self.result.Q

    @property
    def in_crec(self) -> bool:
        return self.result.in_crec

    @property
    def admissible(self) -> bool:
        return self.result.admissible

    @property
    def all_near(self) -> bool:
        return self.result.all_near

    @property
    def worst_beta(self) -> float | None:
        return self.result.worst_beta

    @property
    def worst_candidate_type(self) -> str:
        return self.result.worst_candidate_type


@dataclass
class EvaluationRegistry:
    """Deduplicate production evaluations without changing their provenance."""

    _by_point: dict[Point2, EvaluationRecord] = field(default_factory=dict)
    _next_evaluation_id: int = 1

    def register(
        self,
        result: Q2PointResult,
        *,
        source: str,
        stage: str,
    ) -> EvaluationRecord:
        existing = self._by_point.get(result.S2)
        if existing is not None:
            return existing
        record = EvaluationRecord(
            result=result,
            source=source,
            stage=stage,
            evaluation_id=self._next_evaluation_id,
        )
        self._by_point[result.S2] = record
        self._next_evaluation_id += 1
        return record

    def register_many(
        self,
        results: Iterable[Q2PointResult],
        *,
        source: str,
        stage: str,
    ) -> tuple[EvaluationRecord, ...]:
        return tuple(
            self.register(result, source=source, stage=stage) for result in results
        )

    def get(self, point: Point2) -> EvaluationRecord | None:
        return self._by_point.get(point)

    @property
    def records(self) -> tuple[EvaluationRecord, ...]:
        return tuple(
            sorted(self._by_point.values(), key=lambda record: record.evaluation_id)
        )

    @property
    def all_results(self) -> tuple[Q2PointResult, ...]:
        return tuple(record.result for record in self.records)


def is_valid_incumbent_result(result: Q2PointResult) -> bool:
    return (
        result.in_crec
        and (result.admissible or result.all_near)
        and result.Q is not None
        and math.isfinite(float(result.Q))
    )


def result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return (
        math.inf if result.Q is None else float(result.Q),
        result.S2.x,
        result.S2.y,
    )


def best_valid_result(
    results: Iterable[Q2PointResult],
) -> Q2PointResult | None:
    valid = [result for result in results if is_valid_incumbent_result(result)]
    return min(valid, key=result_key) if valid else None


def update_incumbent(
    current: BestKnownIncumbent | None,
    candidate: Q2PointResult,
    q_tol: float,
    *,
    source: str = "unknown",
    stage: str = "unknown",
    evaluation_id: int = 0,
) -> BestKnownIncumbent | None:
    """Return the deterministic best known incumbent after one candidate."""
    if q_tol < 0.0 or not math.isfinite(q_tol):
        raise ValueError("q_tol must be finite and nonnegative.")
    if not is_valid_incumbent_result(candidate):
        return current
    if current is None or current.Q is None:
        return BestKnownIncumbent(candidate, source, stage, evaluation_id)
    if candidate.Q < current.Q - q_tol:
        return BestKnownIncumbent(candidate, source, stage, evaluation_id)
    if abs(float(candidate.Q) - float(current.Q)) <= q_tol:
        if result_key(candidate) < result_key(current.result):
            return BestKnownIncumbent(candidate, source, stage, evaluation_id)
    return current
