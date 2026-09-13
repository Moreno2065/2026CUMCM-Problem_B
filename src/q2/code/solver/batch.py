"""Optional candidate-point multiprocessing for the frozen Q2 evaluator.

The single-point evaluator remains authoritative.  This module only batches
independent ``S2`` evaluations and preserves input order; it does not alter
the Q2 geometry, admissibility, or inner-maximization semantics.
"""

from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass
import multiprocessing
from typing import Iterable

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point


_WORKER_CONTEXT: tuple[Point2, float, float] | None = None


def _initialize_worker(
    s1_x: float,
    s1_y: float,
    theta1: float,
    epsilon: float,
) -> None:
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = (Point2(s1_x, s1_y), theta1, epsilon)


def _evaluate_worker(point: tuple[float, float]) -> Q2PointResult:
    if _WORKER_CONTEXT is None:
        raise RuntimeError("Q2 batch worker was not initialized.")
    s1, theta1, epsilon = _WORKER_CONTEXT
    return evaluate_q2_point(s1, theta1, Point2(point[0], point[1]), epsilon)


@dataclass
class Q2PointBatchExecutor:
    """Reusable batch executor for one immutable first-observation context."""

    S1: Point2
    theta1: float
    epsilon: float = 1.0
    workers: int = 1

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be at least one.")
        self._executor: Executor | None = None
        if self.workers > 1:
            self._executor = ProcessPoolExecutor(
                max_workers=self.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_worker,
                initargs=(self.S1.x, self.S1.y, self.theta1, self.epsilon),
            )

    def evaluate(self, points: Iterable[Point2]) -> list[Q2PointResult]:
        point_list = list(points)
        if not point_list:
            return []
        if self._executor is None:
            return [
                evaluate_q2_point(self.S1, self.theta1, point, self.epsilon)
                for point in point_list
            ]
        payloads = [(point.x, point.y) for point in point_list]
        return list(self._executor.map(_evaluate_worker, payloads))

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def __enter__(self) -> "Q2PointBatchExecutor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def evaluate_q2_points_batch(
    S1: Point2,
    theta1: float,
    points: Iterable[Point2],
    epsilon: float = 1.0,
    *,
    workers: int = 1,
) -> list[Q2PointResult]:
    """Evaluate independent candidate stations in deterministic input order.

    ``workers=1`` deliberately executes the existing serial evaluator directly
    and is the reference path.  For ``workers>1`` one spawn-safe process pool
    is created for this batch and shut down before returning.
    """
    if workers < 1:
        raise ValueError("workers must be at least one.")
    point_list = list(points)
    if not point_list:
        return []
    with Q2PointBatchExecutor(S1, theta1, epsilon, workers) as batch:
        return batch.evaluate(point_list)
