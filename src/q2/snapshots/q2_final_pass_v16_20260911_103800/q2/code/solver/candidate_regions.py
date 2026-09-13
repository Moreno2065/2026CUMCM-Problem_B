"""Adaptive numerical candidate-region construction for Gate G prime.

This module samples the already frozen ``evaluate_q2_point`` objective.  It
does not alter admissibility or the inner objective and makes no claim of
global certification.  Cells are refined only near threshold crossings,
validity changes, Crec/admissibility boundaries, or the numerical Hero.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.incumbent import EvaluationRegistry
from src.q2.code.solver.outer_search import SearchBounds
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point


@dataclass(frozen=True)
class CandidateRegionConfig:
    base_resolution: int = 21
    max_refinement_depth: int = 6
    target_boundary_resolution_m: float = 5.0
    near_hero_cell_factor: float = 2.5
    max_refined_cells_per_level: int = 32

    def __post_init__(self) -> None:
        if self.base_resolution < 3:
            raise ValueError("base_resolution must be at least three.")
        if self.max_refinement_depth < 0:
            raise ValueError("max_refinement_depth must be nonnegative.")
        if self.target_boundary_resolution_m <= 0.0:
            raise ValueError("target_boundary_resolution_m must be positive.")
        if self.near_hero_cell_factor <= 0.0:
            raise ValueError("near_hero_cell_factor must be positive.")
        if self.max_refined_cells_per_level < 1:
            raise ValueError("max_refined_cells_per_level must be positive.")


@dataclass(frozen=True)
class CandidateCell:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    depth: int

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Point2:
        return Point2(0.5 * (self.x_min + self.x_max), 0.5 * (self.y_min + self.y_max))

    def corners(self) -> tuple[Point2, Point2, Point2, Point2]:
        return (
            Point2(self.x_min, self.y_min),
            Point2(self.x_max, self.y_min),
            Point2(self.x_max, self.y_max),
            Point2(self.x_min, self.y_max),
        )

    def children(self) -> tuple["CandidateCell", ...]:
        x_mid = 0.5 * (self.x_min + self.x_max)
        y_mid = 0.5 * (self.y_min + self.y_max)
        depth = self.depth + 1
        return (
            CandidateCell(self.x_min, x_mid, self.y_min, y_mid, depth),
            CandidateCell(x_mid, self.x_max, self.y_min, y_mid, depth),
            CandidateCell(x_mid, self.x_max, y_mid, self.y_max, depth),
            CandidateCell(self.x_min, x_mid, y_mid, self.y_max, depth),
        )


@dataclass(frozen=True)
class AdaptiveCandidateResult:
    surface: tuple[Q2PointResult, ...]
    all_evaluated_results: tuple[Q2PointResult, ...]
    regions: dict[float, tuple[tuple[Point2, float], ...]]
    cells: dict[float, tuple[CandidateCell, ...]]
    thresholds: dict[float, float]
    approximate_areas_m2: dict[float, float]
    refinement_history: tuple[dict[str, object], ...]
    base_resolution: int
    max_refinement_depth: int
    target_boundary_resolution_m: float


def build_adaptive_candidate_regions(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    bounds: SearchBounds,
    hero_result: Q2PointResult,
    *,
    etas: tuple[float, ...],
    config: CandidateRegionConfig,
    extra_seeds: tuple[Point2, ...] = (),
    evaluator: Callable[[Point2], Q2PointResult] | None = None,
    batch_evaluator: Callable[[tuple[Point2, ...]], list[Q2PointResult]] | None = None,
    mirror_hero: Point2 | None = None,
    evaluation_registry: EvaluationRegistry | None = None,
) -> AdaptiveCandidateResult:
    """Build threshold samples and a leaf-cell approximation for each eta."""
    if hero_result.Q is None or not math.isfinite(float(hero_result.Q)):
        raise ValueError("A finite Hero Q is required for candidate regions.")
    if evaluator is not None and batch_evaluator is not None:
        raise ValueError("Provide evaluator or batch_evaluator, not both.")
    evaluate = evaluator or (
        lambda point: evaluate_q2_point(S1, theta1_deg, point, epsilon_deg)
    )
    def evaluate_points(points: tuple[Point2, ...]) -> list[Q2PointResult]:
        if batch_evaluator is not None:
            return batch_evaluator(points)
        return [evaluate(point) for point in points]

    def fill_cache(points: tuple[Point2, ...], stage: str) -> None:
        pending = tuple(dict.fromkeys(point for point in points if point not in cache))
        if not pending:
            return
        to_evaluate: list[Point2] = []
        for point in pending:
            record = (
                None
                if evaluation_registry is None
                else evaluation_registry.get(point)
            )
            if record is None:
                to_evaluate.append(point)
            else:
                cache[point] = record.result
        if to_evaluate:
            evaluated = evaluate_points(tuple(to_evaluate))
            for point, result in zip(to_evaluate, evaluated, strict=True):
                if evaluation_registry is not None:
                    evaluation_registry.register(
                        result, source="adaptive_evidence", stage=stage
                    )
                cache[point] = result

    qhat = float(hero_result.Q)
    thresholds = {eta: (1.0 + eta) * qhat for eta in etas}
    cache: dict[Point2, Q2PointResult] = {hero_result.S2: hero_result}
    if evaluation_registry is not None:
        evaluation_registry.register(
            hero_result, source="adaptive_evidence", stage="hero_seed"
        )
    fill_cache(extra_seeds, "extra_seed")

    base_points = _grid_points(bounds, config.base_resolution)
    fill_cache(base_points, "base_grid")
    cells = list(_base_cells(bounds, config.base_resolution))
    history: list[dict[str, object]] = [
        {
            "stage": "base",
            "resolution": config.base_resolution,
            "point_count": len(cache),
            "cell_count": len(cells),
        }
    ]

    for depth in range(config.max_refinement_depth):
        corner_points = tuple(
            corner for cell in cells for corner in cell.corners()
        )
        fill_cache(corner_points, "refinement_boundary")
        selected: list[CandidateCell] = []
        for cell in cells:
            results = tuple(cache[point] for point in cell.corners())
            if _needs_refinement(
                cell, results, hero_result, thresholds, config, mirror_hero
            ):
                selected.append(cell)
        selected = _limit_refinement_cells(
            selected,
            cells,
            cache,
            hero_result,
            thresholds,
            config.max_refined_cells_per_level,
            mirror_hero,
        )
        if not selected:
            break
        next_cells: list[CandidateCell] = []
        selected_ids = {id(cell) for cell in selected}
        for cell in cells:
            next_cells.extend(cell.children() if id(cell) in selected_ids else (cell,))
        cells = next_cells
        refinement_points = tuple(
            point
            for cell in selected
            for child in cell.children()
            for point in (*child.corners(), child.center)
        )
        fill_cache(refinement_points, f"refinement:{depth + 1}")
        history.append(
            {
                "stage": "refinement",
                "depth": depth + 1,
                "refined_cell_count": len(selected),
                "cell_count": len(cells),
                "point_count": len(cache),
                "max_cell_width_m": max(cell.width for cell in selected),
                "max_cell_height_m": max(cell.height for cell in selected),
                "max_refined_cells_per_level": config.max_refined_cells_per_level,
            }
        )

    surfaces = tuple(sorted(cache.values(), key=_result_key))
    region_cells: dict[float, tuple[CandidateCell, ...]] = {}
    region_points: dict[float, tuple[tuple[Point2, float], ...]] = {}
    areas: dict[float, float] = {}
    for eta, threshold in thresholds.items():
        points = tuple(
            (result.S2, float(result.Q))
            for result in surfaces
            if _is_valid(result) and float(result.Q) <= threshold
        )
        selected_cells = tuple(
            cell
            for cell in cells
            if _cell_inside_threshold(cell, cache, threshold)
        )
        region_points[eta] = points
        region_cells[eta] = selected_cells
        areas[eta] = sum(cell.area for cell in selected_cells)

    return AdaptiveCandidateResult(
        surface=surfaces,
        all_evaluated_results=surfaces,
        regions=region_points,
        cells=region_cells,
        thresholds=thresholds,
        approximate_areas_m2=areas,
        refinement_history=tuple(history),
        base_resolution=config.base_resolution,
        max_refinement_depth=config.max_refinement_depth,
        target_boundary_resolution_m=config.target_boundary_resolution_m,
    )


def _grid_points(bounds: SearchBounds, resolution: int) -> tuple[Point2, ...]:
    return tuple(
        Point2(
            bounds.x_min + bounds.width * ix / (resolution - 1),
            bounds.y_min + bounds.height * iy / (resolution - 1),
        )
        for ix in range(resolution)
        for iy in range(resolution)
    )


def _cached(
    cache: dict[Point2, Q2PointResult],
    point: Point2,
    evaluate: Callable[[Point2], Q2PointResult],
) -> Q2PointResult:
    if point not in cache:
        cache[point] = evaluate(point)
    return cache[point]


def _base_cells(bounds: SearchBounds, resolution: int) -> tuple[CandidateCell, ...]:
    cells: list[CandidateCell] = []
    for ix in range(resolution - 1):
        for iy in range(resolution - 1):
            x0 = bounds.x_min + bounds.width * ix / (resolution - 1)
            x1 = bounds.x_min + bounds.width * (ix + 1) / (resolution - 1)
            y0 = bounds.y_min + bounds.height * iy / (resolution - 1)
            y1 = bounds.y_min + bounds.height * (iy + 1) / (resolution - 1)
            cells.append(CandidateCell(x0, x1, y0, y1, 0))
    return tuple(cells)


def _needs_refinement(
    cell: CandidateCell,
    results: tuple[Q2PointResult, ...],
    hero: Q2PointResult,
    thresholds: dict[float, float],
    config: CandidateRegionConfig,
    mirror_hero: Point2 | None = None,
) -> bool:
    if cell.width <= config.target_boundary_resolution_m and cell.height <= config.target_boundary_resolution_m:
        return False
    valid = [_is_valid(result) for result in results]
    if any(value != valid[0] for value in valid[1:]):
        return True
    q_values = [float(result.Q) for result in results if _is_valid(result)]
    if q_values and any(min(q_values) <= threshold <= max(q_values) for threshold in thresholds.values()):
        return True
    diagonal = math.hypot(cell.width, cell.height)
    if _cell_distance_to_heroes(cell, hero.S2, mirror_hero) <= config.near_hero_cell_factor * diagonal:
        return True
    return False


def _refinement_priority(
    cell: CandidateCell,
    cache: dict[Point2, Q2PointResult],
    hero: Q2PointResult,
    thresholds: dict[float, float],
    mirror_hero: Point2 | None = None,
) -> tuple[float, float, float]:
    results = [cache[corner] for corner in cell.corners()]
    valid = [_is_valid(result) for result in results]
    validity_priority = 1000.0 if any(value != valid[0] for value in valid[1:]) else 0.0
    values = [float(result.Q) for result in results if _is_valid(result)]
    crossing = sum(
        1.0 for threshold in thresholds.values()
        if values and min(values) <= threshold <= max(values)
    )
    distance = _cell_distance_to_heroes(cell, hero.S2, mirror_hero)
    return (validity_priority + 100.0 * crossing, -distance, cell.area)


def _limit_refinement_cells(
    requested: list[CandidateCell],
    cells: list[CandidateCell],
    cache: dict[Point2, Q2PointResult],
    hero: Q2PointResult,
    thresholds: dict[float, float],
    cap: int,
    mirror_hero: Point2 | None,
) -> list[CandidateCell]:
    if mirror_hero is None:
        requested.sort(
            key=lambda cell: _refinement_priority(cell, cache, hero, thresholds),
            reverse=True,
        )
        return requested[:cap]

    cell_map = {_cell_key(cell): cell for cell in cells}
    pairs: list[tuple[tuple[float, float, float], tuple[CandidateCell, ...]]] = []
    seen: set[tuple[float, float, float, float, int]] = set()
    for cell in requested:
        key = _cell_key(cell)
        if key in seen:
            continue
        mirror = cell_map.get(_cell_key(_mirror_cell(cell)))
        pair = (cell,) if mirror is None or mirror == cell else (cell, mirror)
        seen.update(_cell_key(item) for item in pair)
        priority = max(
            _refinement_priority(item, cache, hero, thresholds, mirror_hero)
            for item in pair
        )
        pairs.append((priority, pair))
    pairs.sort(key=lambda item: item[0], reverse=True)
    selected: list[CandidateCell] = []
    for _, pair in pairs:
        if len(selected) + len(pair) > cap:
            continue
        selected.extend(pair)
    return selected


def _cell_distance_to_heroes(
    cell: CandidateCell,
    hero: Point2,
    mirror_hero: Point2 | None,
) -> float:
    centers = (hero,) if mirror_hero is None else (hero, mirror_hero)
    return min(corner.distance_to(center) for corner in cell.corners() for center in centers)


def _mirror_cell(cell: CandidateCell) -> CandidateCell:
    return CandidateCell(cell.x_min, cell.x_max, -cell.y_max, -cell.y_min, cell.depth)


def _cell_key(cell: CandidateCell) -> tuple[float, float, float, float, int]:
    return (
        round(cell.x_min, 10),
        round(cell.x_max, 10),
        round(cell.y_min, 10),
        round(cell.y_max, 10),
        cell.depth,
    )


def _cell_inside_threshold(
    cell: CandidateCell,
    cache: dict[Point2, Q2PointResult],
    threshold: float,
) -> bool:
    values = [cache[corner] for corner in cell.corners()]
    return all(
        _is_valid(result) and float(result.Q) <= threshold + 1e-9
        for result in values
    )


def _is_valid(result: Q2PointResult) -> bool:
    return result.in_crec and result.admissible and result.Q is not None and math.isfinite(float(result.Q))


def _result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return (math.inf if result.Q is None else float(result.Q), result.S2.x, result.S2.y)
