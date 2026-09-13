"""Deterministic, explicitly non-certified Gate F spatial search."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.a1 import A1Region, FirstObservation, build_a1
from src.q2.code.geometry.crec import CompatibleRadiusMode, CrecRegion, build_crec
from src.q2.code.geometry.primitives import BoundaryPoint, CircularArc, Point2
from src.q2.code.solver.batch import Q2PointBatchExecutor
from src.q2.code.solver.incumbent import (
    EvaluationRecord,
    EvaluationRegistry,
    BestKnownIncumbent,
    is_valid_incumbent_result,
    result_key,
    update_incumbent,
)
from src.q2.code.solver.q2_point import Q2PointResult


CERTIFIED_GLOBAL_OPTIMUM = False


@dataclass(frozen=True)
class SearchBounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    derivation: str

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    def contains(self, point: Point2, tolerance_m: float = 1e-9) -> bool:
        return (
            self.x_min - tolerance_m <= point.x <= self.x_max + tolerance_m
            and self.y_min - tolerance_m <= point.y <= self.y_max + tolerance_m
        )


@dataclass(frozen=True)
class OuterSearchConfig:
    coarse_resolution: int = 7
    subdivision_depth: int = 2
    local_iterations: int = 8
    parallel_workers: int = 1

    def __post_init__(self) -> None:
        if self.coarse_resolution < 3:
            raise ValueError("coarse_resolution must be at least three.")
        if self.subdivision_depth < 0:
            raise ValueError("subdivision_depth must be nonnegative.")
        if self.local_iterations < 1:
            raise ValueError("local_iterations must be positive.")
        if self.parallel_workers < 1:
            raise ValueError("parallel_workers must be at least one.")


@dataclass(frozen=True)
class SearchSeed:
    layout: str
    point: Point2
    in_crec: bool
    admissible: bool
    Q: float | None


@dataclass(frozen=True)
class SearchRecord:
    stage: str
    point: Point2
    Q: float | None
    incumbent: bool


@dataclass(frozen=True)
class OuterSearchResult:
    recommended: Q2PointResult
    bounds: SearchBounds
    config: OuterSearchConfig
    seeds: tuple[SearchSeed, ...]
    history: tuple[SearchRecord, ...]
    evaluated_count: int
    valid_count: int
    no_known_better_neighbor: bool
    method: str
    evaluated_records: tuple[EvaluationRecord, ...]
    certified_global_optimum: bool = CERTIFIED_GLOBAL_OPTIMUM


def derive_search_bounds(a1: A1Region, crec: CrecRegion) -> SearchBounds:
    """Return a safe axis-aligned superset of Crec for outer searching.

    Each piece of ``crec.witnesses`` is a *necessary* constraint: every
    admissible point must lie in the closed disk it defines.  Intersecting the
    axis-aligned bounding boxes of a subset of those mandatory disks therefore
    yields ``B_search`` with ``B_search ⊇ C_rec``.  The result may be loose (it
    is a superset, not the exact Crec box), but it never removes a genuine Crec
    point.  Membership is still decided exclusively by the exact ``is_in_crec``
    evaluator at every actual candidate, so this bound only narrows the search
    window and never replaces the Crec predicate.
    """
    if crec.a1 is not a1:
        raise ValueError("Crec and A1 objects must describe the same observation.")
    boxes: list[tuple[float, float, float, float]] = []
    for piece in crec.witnesses.pieces:
        curve = piece.curve
        if isinstance(curve, BoundaryPoint):
            points = (curve.point,)
        elif isinstance(curve, CircularArc):
            points = (curve.point_at(0.0), curve.point_at(0.5), curve.point_at(1.0))
        else:
            continue
        for target in points:
            radius = (
                1000.0
                if piece.radius_mode == CompatibleRadiusMode.FIXED_1000
                else target.distance_to(a1.observation.station)
            )
            boxes.append(
                (
                    target.x - radius,
                    target.x + radius,
                    target.y - radius,
                    target.y + radius,
                )
            )
    if not boxes:
        raise ValueError("A nonempty Crec must provide a witness-derived search bound.")
    bounds = SearchBounds(
        x_min=max(box[0] for box in boxes),
        x_max=min(box[1] for box in boxes),
        y_min=max(box[2] for box in boxes),
        y_max=min(box[3] for box in boxes),
        derivation="safe_superset_from_subset_of_mandatory_crec_disk_boxes",
    )
    if bounds.x_min > bounds.x_max or bounds.y_min > bounds.y_max:
        raise RuntimeError("Crec witness boxes unexpectedly have empty intersection.")
    if not bounds.contains(a1.observation.station, tolerance_m=1e-6):
        raise RuntimeError(
            "Search bounds must contain S1 because S1 is always in C_rec."
        )
    return bounds


def search_outer(
    S1: Point2,
    theta1: float,
    epsilon: float = 1.0,
    *,
    config: OuterSearchConfig = OuterSearchConfig(),
) -> OuterSearchResult:
    """Search C_adm with the serial evaluator or optional point batching."""
    with Q2PointBatchExecutor(
        S1, theta1, epsilon, workers=config.parallel_workers
    ) as batch:
        return _search_outer_impl(S1, theta1, epsilon, config, batch)


def _search_outer_impl(
    S1: Point2,
    theta1: float,
    epsilon: float,
    config: OuterSearchConfig,
    batch: Q2PointBatchExecutor,
) -> OuterSearchResult:
    """Search C_adm reproducibly without making an optimality certificate."""
    a1 = build_a1(FirstObservation(S1, theta1, epsilon))
    crec = build_crec(a1)
    bounds = derive_search_bounds(a1, crec)
    cache: dict[Point2, Q2PointResult] = {}
    registry = EvaluationRegistry()
    history: list[SearchRecord] = []
    incumbent: BestKnownIncumbent | None = None

    def evaluate_many(points: tuple[Point2, ...], stage: str) -> list[Q2PointResult]:
        nonlocal incumbent
        pending = tuple(
            dict.fromkeys(point for point in points if point not in cache)
        )
        if pending:
            cache.update(zip(pending, batch.evaluate(pending), strict=True))
            registry.register_many(
                (cache[point] for point in pending),
                source="outer_search",
                stage=stage,
            )
        results: list[Q2PointResult] = []
        for point in points:
            result = cache[point]
            record = registry.get(result.S2)
            assert record is not None
            previous = incumbent
            incumbent = update_incumbent(
                incumbent,
                result,
                1e-9,
                source=record.source,
                stage=record.stage,
                evaluation_id=record.evaluation_id,
            )
            accepted = incumbent is not previous
            history.append(SearchRecord(stage, point, result.Q, accepted))
            results.append(result)
        return results

    seed_specs = _initial_seed_specs(a1, bounds)
    seed_results: list[SearchSeed] = []
    seed_points = tuple(point for _, point in seed_specs)
    seed_evaluations = evaluate_many(seed_points, "seed")
    for (layout, point), result in zip(seed_specs, seed_evaluations, strict=True):
        seed_results.append(
            SearchSeed(layout, point, result.in_crec, result.admissible, result.Q)
        )

    coarse_valid: list[Q2PointResult] = []
    coarse_points = _grid_points(bounds, config.coarse_resolution)
    for result in evaluate_many(coarse_points, "coarse_grid"):
        if _is_valid(result):
            coarse_valid.append(result)
    if not coarse_valid and incumbent is None:
        raise RuntimeError("No admissible second station was found in the derived bounds.")
    assert incumbent is not None
    if coarse_valid:
        coarse_best = min(coarse_valid, key=_result_key)
        seed_results.append(
            SearchSeed(
                "coarse_grid_best",
                coarse_best.S2,
                coarse_best.in_crec,
                coarse_best.admissible,
                coarse_best.Q,
            )
        )

    frontier = sorted(coarse_valid, key=_result_key)[:4] or [incumbent.result]
    coarse_step_x = bounds.width / (config.coarse_resolution - 1)
    coarse_step_y = bounds.height / (config.coarse_resolution - 1)
    for depth in range(1, config.subdivision_depth + 1):
        step_x = coarse_step_x / (2**depth)
        step_y = coarse_step_y / (2**depth)
        refined: list[Q2PointResult] = []
        subdivision_points: list[Point2] = []
        for base in frontier:
            for dx in (-step_x, 0.0, step_x):
                for dy in (-step_y, 0.0, step_y):
                    point = Point2(base.S2.x + dx, base.S2.y + dy)
                    if not bounds.contains(point):
                        continue
                    subdivision_points.append(point)
        for result in evaluate_many(
            tuple(subdivision_points), f"subdivision:{depth}"
        ):
            if _is_valid(result):
                refined.append(result)
        frontier = sorted(refined, key=_result_key)[:4] or [incumbent.result]

    refined_incumbent = _local_pattern_refinement(
        S1,
        theta1,
        epsilon,
        bounds,
        incumbent.result,
        cache,
        history,
        batch,
        max(coarse_step_x, coarse_step_y) / (2 ** (config.subdivision_depth + 1)),
        config.local_iterations,
        "local",
        registry=registry,
    )
    record = registry.register(
        refined_incumbent, source="outer_search", stage="local_refinement"
    )
    incumbent = update_incumbent(
        incumbent,
        refined_incumbent,
        1e-9,
        source=record.source,
        stage=record.stage,
        evaluation_id=record.evaluation_id,
    )
    assert incumbent is not None
    refined_incumbent = _local_pattern_refinement(
        S1,
        theta1,
        epsilon,
        bounds,
        incumbent.result,
        cache,
        history,
        batch,
        5.0,
        14,
        "validation",
        registry=registry,
    )
    record = registry.register(
        refined_incumbent, source="outer_search", stage="validation_refinement"
    )
    incumbent = update_incumbent(
        incumbent,
        refined_incumbent,
        1e-9,
        source=record.source,
        stage=record.stage,
        evaluation_id=record.evaluation_id,
    )
    assert incumbent is not None
    final_step = 5.0 / (2**13)
    no_better = False
    for _ in range(3):
        # Freeze the centre first: every probe direction must be generated from
        # the same final candidate, otherwise "no better neighbour" would be a
        # statement about a centre that silently moved mid-scan.
        center = incumbent.result
        neighbor_points: list[Point2] = []
        for direction in _directions():
            point = Point2(
                center.S2.x + direction.x * final_step,
                center.S2.y + direction.y * final_step,
            )
            if bounds.contains(point):
                neighbor_points.append(point)
        neighbors = evaluate_many(tuple(neighbor_points), "final_neighbor_check")
        better = [result for result in neighbors if _better(result, center)]
        if not better:
            no_better = True
            break
        seed = min(better, key=_result_key)
        record = registry.register(
            seed, source="outer_search", stage="final_neighbor_seed"
        )
        incumbent = update_incumbent(
            incumbent,
            seed,
            1e-9,
            source=record.source,
            stage=record.stage,
            evaluation_id=record.evaluation_id,
        )
        assert incumbent is not None
        refined_incumbent = _local_pattern_refinement(
            S1,
            theta1,
            epsilon,
            bounds,
            incumbent,
            cache,
            history,
            batch,
            final_step * 8.0,
            6,
            "final_recheck",
            registry=registry,
        )
        record = registry.register(
            refined_incumbent, source="outer_search", stage="final_recheck"
        )
        incumbent = update_incumbent(
            incumbent,
            refined_incumbent,
            1e-9,
            source=record.source,
            stage=record.stage,
            evaluation_id=record.evaluation_id,
        )
        assert incumbent is not None

    return OuterSearchResult(
        recommended=incumbent.result,
        bounds=bounds,
        config=config,
        seeds=tuple(seed_results),
        history=tuple(history),
        evaluated_count=len(cache),
        valid_count=sum(_is_valid(result) for result in cache.values()),
        no_known_better_neighbor=no_better,
        method="deterministic adaptive subdivision with local pattern refinement",
        evaluated_records=registry.records,
    )


def _initial_seed_specs(a1: A1Region, bounds: SearchBounds) -> tuple[tuple[str, Point2], ...]:
    station = a1.observation.station
    angle = a1.observation.center_angle_rad
    radial = a1.radial_interval(angle)
    rho = 500.0 if radial is None else 0.5 * (radial[0] + radial[1])
    target = station + Point2(math.cos(angle), math.sin(angle)).scaled(rho)
    perpendicular = Point2(-math.sin(angle), math.cos(angle))
    offset = min(600.0, 0.25 * max(bounds.width, bounds.height))
    analytic = target + perpendicular.scaled(offset)
    symmetric = target - perpendicular.scaled(offset)
    center = Point2(0.5 * (bounds.x_min + bounds.x_max), 0.5 * (bounds.y_min + bounds.y_max))
    boundary = (
        Point2(bounds.x_min, bounds.y_min),
        Point2(bounds.x_min, bounds.y_max),
        Point2(bounds.x_max, bounds.y_min),
        Point2(bounds.x_max, bounds.y_max),
        Point2(center.x, bounds.y_min),
        Point2(center.x, bounds.y_max),
        Point2(bounds.x_min, center.y),
        Point2(bounds.x_max, center.y),
    )
    specs = [("analytic_baseline", analytic), ("symmetry_related", symmetric), ("interior", center)]
    specs.extend(("boundary", point) for point in boundary)
    return tuple((label, _clamp(point, bounds)) for label, point in specs)


def _grid_points(bounds: SearchBounds, resolution: int) -> tuple[Point2, ...]:
    return tuple(
        Point2(
            bounds.x_min + bounds.width * ix / (resolution - 1),
            bounds.y_min + bounds.height * iy / (resolution - 1),
        )
        for ix in range(resolution)
        for iy in range(resolution)
    )


def _local_pattern_refinement(
    S1,
    theta1,
    epsilon,
    bounds,
    incumbent,
    cache,
    history,
    batch,
    initial_step,
    iterations,
    stage_prefix,
    *,
    registry: EvaluationRegistry | None = None,
    registry_source: str = "outer_search",
):
    step = initial_step
    for level in range(iterations):
        for move in range(32):
            neighbours: list[Q2PointResult] = []
            neighbour_points: list[Point2] = []
            for direction in _directions():
                point = Point2(
                    incumbent.S2.x + direction.x * step,
                    incumbent.S2.y + direction.y * step,
                )
                if not bounds.contains(point):
                    continue
                neighbour_points.append(point)
            pending_points = tuple(
                dict.fromkeys(point for point in neighbour_points if point not in cache)
            )
            pending: list[Point2] = []
            for point in pending_points:
                record = None if registry is None else registry.get(point)
                if record is None:
                    pending.append(point)
                else:
                    cache[point] = record.result
            if pending:
                cache.update(zip(pending, batch.evaluate(tuple(pending)), strict=True))
                if registry is not None:
                    registry.register_many(
                        (cache[point] for point in pending),
                        source=registry_source,
                        stage=f"{stage_prefix}:{level}:{move}",
                    )
            neighbours.extend(cache[point] for point in neighbour_points)
            better = [result for result in neighbours if _better(result, incumbent)]
            selected = min(better, key=_result_key) if better else None
            for result in neighbours:
                history.append(
                    SearchRecord(
                        f"{stage_prefix}:{level}:{move}",
                        result.S2,
                        result.Q,
                        result is selected,
                    )
                )
            if selected is not None:
                incumbent = selected
        step *= 0.5
    return incumbent


def _directions() -> tuple[Point2, ...]:
    return tuple(
        Point2(math.cos(index * math.pi / 8.0), math.sin(index * math.pi / 8.0))
        for index in range(16)
    )


def _clamp(point: Point2, bounds: SearchBounds) -> Point2:
    return Point2(
        min(bounds.x_max, max(bounds.x_min, point.x)),
        min(bounds.y_max, max(bounds.y_min, point.y)),
    )


def _is_valid(result: Q2PointResult) -> bool:
    return is_valid_incumbent_result(result)


def _result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return result_key(result)


def _better(candidate: Q2PointResult, incumbent: Q2PointResult | None) -> bool:
    return _is_valid(candidate) and (
        incumbent is None or _result_key(candidate) < _result_key(incumbent)
    )
