"""Benchmark the optional candidate-point ProcessPool backend.

Run this module from the repository root.  It compares the frozen serial
reference with workers 2/4/8 for a 21x21 surface, production outer search,
and Gate G-prime adaptive candidate-region refinement.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.batch import Q2PointBatchExecutor
from src.q2.code.solver.candidate_regions import (
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.outer_search import (
    OuterSearchConfig,
    _grid_points,
    derive_search_bounds,
    search_outer,
)
from src.q2.code.solver.q2_point import evaluate_q2_point


S1 = Point2(0.0, 0.0)
THETA1 = 0.0
EPSILON = 1.0
WORKERS = (1, 2, 4, 8)


def _measure(call: Callable[[], Any]) -> tuple[Any, float, int]:
    peak = 1
    stop = threading.Event()

    def monitor() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, 1 + len(__import__("multiprocessing").active_children()))
            stop.wait(0.01)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    started = time.perf_counter()
    value = call()
    elapsed = time.perf_counter() - started
    stop.set()
    thread.join()
    return value, elapsed, peak


def _surface_workload(workers: int, bounds) -> tuple[tuple[Any, ...], int]:
    points = _grid_points(bounds, 21)
    with Q2PointBatchExecutor(S1, THETA1, EPSILON, workers=workers) as batch:
        results = batch.evaluate(points)
    return tuple(results), len(points)


def _outer_workload(workers: int) -> tuple[Any, int]:
    result = search_outer(
        S1,
        THETA1,
        EPSILON,
        config=OuterSearchConfig(
            coarse_resolution=7,
            subdivision_depth=2,
            local_iterations=8,
            parallel_workers=workers,
        ),
    )
    return result, result.evaluated_count


def _adaptive_workload(workers: int, bounds, hero) -> tuple[Any, int]:
    config = CandidateRegionConfig(
        base_resolution=21,
        max_refinement_depth=6,
        target_boundary_resolution_m=5.0,
        near_hero_cell_factor=2.5,
        max_refined_cells_per_level=32,
    )
    with Q2PointBatchExecutor(S1, THETA1, EPSILON, workers=workers) as batch:
        result = build_adaptive_candidate_regions(
            S1,
            THETA1,
            EPSILON,
            bounds,
            hero,
            etas=(0.01, 0.02, 0.05, 0.10),
            config=config,
            batch_evaluator=batch.evaluate,
        )
    return result, len(result.surface)


def _equivalent(kind: str, actual: Any, reference: Any) -> bool:
    if kind == "surface21":
        return actual == reference
    if kind == "outer":
        return (
            actual.recommended == reference.recommended
            and actual.history == reference.history
            and actual.evaluated_count == reference.evaluated_count
        )
    return (
        actual.surface == reference.surface
        and actual.regions == reference.regions
        and actual.cells == reference.cells
    )


def run_benchmark(output: Path) -> dict[str, Any]:
    a1 = build_a1(FirstObservation(S1, THETA1, EPSILON))
    bounds = derive_search_bounds(a1, build_crec(a1))
    hero = evaluate_q2_point(S1, THETA1, Point2(792.3025077759607, -616.4786501226868))
    workloads = {
        "surface21": lambda workers: _surface_workload(workers, bounds),
        "outer": _outer_workload,
        "adaptive": lambda workers: _adaptive_workload(workers, bounds, hero),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "representative_case": {"S1": [0.0, 0.0], "theta1_deg": 0.0, "epsilon_deg": 1.0},
        "workers": list(WORKERS),
        "environment": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        },
        "workloads": {},
    }
    for kind, workload in workloads.items():
        rows: list[dict[str, Any]] = []
        reference = None
        serial_seconds = None
        for workers in WORKERS:
            value, wall_seconds, peak = _measure(lambda w=workers: workload(w))
            result, count = value
            if reference is None:
                reference = result
                serial_seconds = wall_seconds
            rows.append(
                {
                    "workers": workers,
                    "wall_time_s": wall_seconds,
                    "unique_evaluations": count,
                    "evaluations_per_s": count / wall_seconds if wall_seconds else None,
                    "speedup": serial_seconds / wall_seconds if wall_seconds else None,
                    "parallel_efficiency": (
                        serial_seconds / wall_seconds / workers if wall_seconds else None
                    ),
                    "peak_process_count": peak,
                    "equivalent_to_workers_1": _equivalent(kind, result, reference),
                }
            )
        report["workloads"][kind] = rows
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/q2/code/artifacts/q2_batch_benchmark.json"),
    )
    args = parser.parse_args()
    report = run_benchmark(args.output)
    for kind, rows in report["workloads"].items():
        summary = ", ".join(
            f"w{row['workers']}={row['wall_time_s']:.2f}s/{row['speedup']:.2f}x"
            for row in rows
        )
        print(f"{kind}: {summary}")


if __name__ == "__main__":
    main()
