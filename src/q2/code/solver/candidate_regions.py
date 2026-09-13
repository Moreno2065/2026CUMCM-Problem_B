"""Adaptive numerical candidate-region construction for Gate G prime.

This module samples the already frozen ``evaluate_q2_point`` objective.  It
does not alter admissibility or the inner objective and makes no claim of
global certification.

Four separate concepts are maintained and reported, because they are *not*
equivalent (see the candidate-region work order, sections 3 to 5):

``accepted_samples``
    pointwise candidates: individually feasible and below the eta threshold.
    A nonempty sample set never implies that any whole cell was selected.
``sampled_inside_cells``
    cells whose four corners *and* centre all pass.  This is a numerical
    classification only; a finite sample set cannot prove that the cell
    interior stays below the threshold.
``mixed_cells`` / ``unresolved_cells``
    cells that contain a boundary or a known-in-threshold sample but are not
    fully selected, and cells whose boundary could not be characterised.
``display_region`` (``boundary_polygons``)
    the saved numerical polygons used for display and for the area estimate.
    They are not an online-safe action set.

Consequences that are enforced in code:

* if the Hero is feasible and ``Q(Hero) == q_reference`` then the Hero is in
  ``accepted_samples`` for every nonnegative eta, even when
  ``sampled_inside_cell_count == 0``;
* a cell that contains a known-in-threshold sample is never discarded as
  "confirmed empty" just because its corners and centre fail;
* ``area_estimate_m2 == 0`` always carries a diagnostic ``region_status`` and a
  ``stop_reason``; zero area is never recorded as a mathematical empty set;
* the refinement budget is spent on cells that are close to the low-value band
  (known good seeds and Q-threshold crossings first, then near-seed cells, and
  only then far-away Crec validity boundaries), and every deferred cell is
  reported as unresolved instead of silently disappearing.

Refinement priority tiers (lowest index wins, saved per requested cell as the
trigger category in ``refinement_history``)::

    0  known_good_seed      cell holds a Hero/extra/mirror seed sample
    1  Q_threshold          cell has a feasible sample at or below the largest
                            eta threshold, or a threshold lying inside its
                            sampled Q range
    2  other                near-seed neighbourhood or Q-range spread
    3  validity_boundary    only a Crec/admissibility sample disagreement

Within a tier, cells closer to a seed are refined first.  Coarse Crec
boundaries far from the low-value band therefore cannot starve the Q level-set
boundary, and the local boundary clip refuses to claim area for cells coarser
than ``boundary_max_cell_diameter_factor`` times the declared target
resolution.
"""

from __future__ import annotations

import bisect

from dataclasses import dataclass
import math
from typing import Callable

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.incumbent import (
    EvaluationRegistry,
    is_valid_incumbent_result,
)
from src.q2.code.solver.outer_search import SearchBounds
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point
from src.q2.code.solver.region_boundary import (
    BoundaryExtractionConfig,
    CellBoundaryResult,
    extract_mixed_cell_boundary,
    ring_area_m2,
)


CANDIDATE_REGION_KIND = "numerical_candidate_good_region_not_proof"
CLASSIFICATION_SAMPLES = "corners_plus_center"

REGION_STATUS_POSITIVE_AREA = "positive_area_numerical"
REGION_STATUS_UNRESOLVED_THIN = "unresolved_thin_feature"
REGION_STATUS_NO_INSIDE_CELLS = "no_fully_selected_cells"

TRIGGER_KNOWN_GOOD_SEED = "known_good_seed"
TRIGGER_Q_THRESHOLD = "Q_threshold"
TRIGGER_VALIDITY_BOUNDARY = "validity_boundary"
TRIGGER_OTHER = "other"

AREA_METHOD_POLYGONS = "saved_marching_triangle_fragments_plus_inside_cell_rectangles"
AREA_METHOD_NONE = "no_polygonal_area_available"

DISPLAY_REGION_KIND = "numerical_polygons_not_certified"

_MAX_INTERIOR_SPLIT_POINTS = 4

_TRIGGER_TIER = {
    TRIGGER_KNOWN_GOOD_SEED: 0,
    TRIGGER_Q_THRESHOLD: 1,
    TRIGGER_OTHER: 2,
    TRIGGER_VALIDITY_BOUNDARY: 3,
}

_REFINEMENT_STOP_CONVERGED = "converged_no_refinement_requested"
_REFINEMENT_STOP_MAX_DEPTH = "max_refinement_depth_reached"
_REFINEMENT_STOP_CAP = "refinement_cap_deferred_cells_remain"
_REFINEMENT_STOP_NOTHING_EXECUTED = "no_cells_executed"


@dataclass(frozen=True)
class CandidateRegionConfig:
    """Extraction budget.  New fields keep defaults for existing callers."""

    base_resolution: int = 21
    max_refinement_depth: int = 6
    target_boundary_resolution_m: float = 5.0
    near_hero_cell_factor: float = 2.5
    max_refined_cells_per_level: int = 32
    q_range_refinement_ratio: float = 0.25
    # Boundary extraction (all optional; defaults preserve old constructions).
    boundary_bisection_steps: int = 8
    boundary_tolerance_m: float = 0.5
    boundary_relative_tolerance: float = 0.08
    boundary_max_subdivision_depth: int = 1
    boundary_probe_budget_per_cell: int = 96
    boundary_max_cells: int = 1024
    boundary_max_probes: int = 8000
    boundary_max_cell_diameter_factor: float = 8.0
    seed_band_ratio: float = 0.25

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
        if self.q_range_refinement_ratio < 0.0 or not math.isfinite(
            self.q_range_refinement_ratio
        ):
            raise ValueError("q_range_refinement_ratio must be finite and nonnegative.")
        if self.boundary_bisection_steps < 1:
            raise ValueError("boundary_bisection_steps must be positive.")
        if self.boundary_tolerance_m <= 0.0 or not math.isfinite(
            self.boundary_tolerance_m
        ):
            raise ValueError("boundary_tolerance_m must be finite and positive.")
        if not 0.0 < self.boundary_relative_tolerance <= 1.0:
            raise ValueError("boundary_relative_tolerance must lie in (0, 1].")
        if self.boundary_max_subdivision_depth < 0:
            raise ValueError("boundary_max_subdivision_depth must be nonnegative.")
        if self.boundary_probe_budget_per_cell < 4:
            raise ValueError("boundary_probe_budget_per_cell must be at least four.")
        if self.boundary_max_cells < 0:
            raise ValueError("boundary_max_cells must be nonnegative.")
        if self.boundary_max_probes < 0:
            raise ValueError("boundary_max_probes must be nonnegative.")
        if self.boundary_max_cell_diameter_factor <= 0.0 or not math.isfinite(
            self.boundary_max_cell_diameter_factor
        ):
            raise ValueError("boundary_max_cell_diameter_factor must be finite and positive.")
        if self.seed_band_ratio < 0.0 or not math.isfinite(self.seed_band_ratio):
            raise ValueError("seed_band_ratio must be finite and nonnegative.")

    def boundary_max_cell_diameter_m(self) -> float:
        """Largest cell a local straight-chord clip may claim area for."""
        return self.boundary_max_cell_diameter_factor * self.target_boundary_resolution_m

    def boundary_config(self) -> BoundaryExtractionConfig:
        return BoundaryExtractionConfig(
            bisection_steps=self.boundary_bisection_steps,
            tolerance_m=self.boundary_tolerance_m,
            relative_tolerance=self.boundary_relative_tolerance,
            max_subdivision_depth=self.boundary_max_subdivision_depth,
            probe_budget_per_cell=self.boundary_probe_budget_per_cell,
        )


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

    @property
    def diameter(self) -> float:
        return math.hypot(self.width, self.height)

    def corners(self) -> tuple[Point2, Point2, Point2, Point2]:
        return (
            Point2(self.x_min, self.y_min),
            Point2(self.x_max, self.y_min),
            Point2(self.x_max, self.y_max),
            Point2(self.x_min, self.y_max),
        )

    def ring(self) -> tuple[Point2, ...]:
        return self.corners()

    def contains(self, point: Point2, tolerance_m: float = 1e-9) -> bool:
        return (
            self.x_min - tolerance_m <= point.x <= self.x_max + tolerance_m
            and self.y_min - tolerance_m <= point.y <= self.y_max + tolerance_m
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
class CandidateRegionDiagnostics:
    """Per-eta extraction diagnostics.

    ``area_estimate_m2 == 0.0`` always comes with a ``region_status`` in
    ``{no_fully_selected_cells, unresolved_thin_feature}`` and a non-empty
    ``stop_reason``; zero area is a numerical statement about the sampling, not
    a proof that the true candidate set is empty.

    ``mixed_cell_count`` counts cells that contain a threshold/validity boundary
    or a known in-threshold sample.  ``unresolved_cell_count`` counts cells whose
    candidate content is *not* characterised: cells deferred by the refinement
    cap plus mixed cells whose boundary clip could not be defended.  The two
    sets can overlap, and neither is a statement about the true set.
    """

    eta: float
    threshold: float
    accepted_sample_count: int
    hero_is_in_accepted_samples: bool
    sampled_inside_cell_count: int
    mixed_cell_count: int
    unresolved_cell_count: int
    area_estimate_m2: float
    area_estimation_method: str
    region_status: str
    stop_reason: str
    kind: str = CANDIDATE_REGION_KIND
    classification_samples: str = CLASSIFICATION_SAMPLES
    requested_refinement_count: int = 0
    executed_refinement_count: int = 0
    deferred_by_cap_count: int = 0
    max_depth_hit_count: int = 0
    refinement_cap_hit_count: int = 0
    trigger_category_counts: tuple[tuple[str, int], ...] = ()
    max_unresolved_boundary_cell_width_m: float = 0.0
    max_unresolved_boundary_cell_height_m: float = 0.0
    max_unresolved_boundary_cell_diameter_m: float = 0.0
    achieved_max_boundary_cell_size_m: float = 0.0
    boundary_stop_reason: str = ""
    boundary_attempted_cell_count: int = 0
    boundary_resolved_cell_count: int = 0
    boundary_unresolved_cell_count: int = 0
    boundary_skipped_cell_count: int = 0
    boundary_probe_count: int = 0
    boundary_polygon_count: int = 0
    boundary_fragment_area_m2: float = 0.0
    inside_cell_area_m2: float = 0.0
    outside_by_samples_cell_count: int = 0
    target_boundary_resolution_m: float = 0.0
    display_region_kind: str = DISPLAY_REGION_KIND
    new_evaluation_count: int = 0
    cache_hit_count: int = 0
    parallel_workers: int = 1
    boundary_batch_call_count: int = 0
    boundary_batch_point_count: int = 0
    boundary_batch_max_size: int = 0


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
    kind: str = CANDIDATE_REGION_KIND
    classification_samples: str = CLASSIFICATION_SAMPLES
    diagnostics: dict[float, CandidateRegionDiagnostics] | None = None
    accepted_samples: dict[float, tuple[tuple[Point2, float], ...]] | None = None
    boundary_polygons: dict[float, tuple[tuple[Point2, ...], ...]] | None = None
    mixed_cells: dict[float, tuple[CandidateCell, ...]] | None = None
    unresolved_cells: dict[float, tuple[CandidateCell, ...]] | None = None


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
    """Build threshold samples, refined cells and boundary polygons per eta."""
    if hero_result.Q is None or not math.isfinite(float(hero_result.Q)):
        raise ValueError("A finite Hero Q is required for candidate regions.")
    if evaluator is not None and batch_evaluator is not None:
        raise ValueError("Provide evaluator or batch_evaluator, not both.")
    eta_values = tuple(float(eta) for eta in etas)
    if not eta_values:
        raise ValueError("At least one eta is required.")
    if any(eta < 0.0 or not math.isfinite(eta) for eta in eta_values):
        raise ValueError("etas must be finite and nonnegative.")

    evaluate = evaluator or (
        lambda point: evaluate_q2_point(S1, theta1_deg, point, epsilon_deg)
    )

    def evaluate_points(points: tuple[Point2, ...]) -> list[Q2PointResult]:
        if batch_evaluator is not None:
            return batch_evaluator(points)
        return [evaluate(point) for point in points]

    cache: dict[Point2, Q2PointResult] = {}
    counters = {"new_evaluations": 0, "cache_hits": 0}
    batch_owner = getattr(batch_evaluator, "__self__", None)
    parallel_workers = int(getattr(batch_owner, "workers", 1))
    boundary_batch_stats = {"calls": 0, "points": 0, "max_size": 0}

    def fill_cache_tagged(points: tuple[tuple[Point2, str], ...]) -> None:
        to_evaluate: list[tuple[Point2, str]] = []
        pending: set[Point2] = set()
        for point, stage in points:
            if point in cache or point in pending:
                counters["cache_hits"] += 1
                continue
            record = (
                None
                if evaluation_registry is None
                else evaluation_registry.get(point)
            )
            if record is None:
                to_evaluate.append((point, stage))
                pending.add(point)
            else:
                cache[point] = record.result
                counters["cache_hits"] += 1
        if to_evaluate:
            evaluated = evaluate_points(tuple(point for point, _ in to_evaluate))
            for (point, stage), result in zip(to_evaluate, evaluated, strict=True):
                if evaluation_registry is not None:
                    evaluation_registry.register(
                        result, source="adaptive_evidence", stage=stage
                    )
                cache[point] = result
            counters["new_evaluations"] += len(to_evaluate)

    def fill_cache(points: tuple[Point2, ...], stage: str) -> None:
        fill_cache_tagged(tuple((point, stage) for point in points))

    mirror_mode = mirror_hero is not None

    def evaluate_one(point: Point2, stage: str) -> Q2PointResult:
        fill_cache_tagged(((point, stage),))
        return cache[point]

    def probe_point(point: Point2) -> Q2PointResult:
        """Production probe used by the boundary clip.

        In the centered mirror case the mirror partner is really evaluated as
        well (never copied) so that the evaluated surface stays mirror-paired.
        """
        result = evaluate_one(point, "boundary_probe")
        if mirror_mode:
            mirror_point = Point2(point.x, -point.y)
            if mirror_point != point:
                evaluate_one(mirror_point, "boundary_probe_mirror")
        return result

    def probe_points(points: tuple[Point2, ...]) -> list[Q2PointResult]:
        """Evaluate independent boundary probes with the existing batch backend."""
        tagged: list[tuple[Point2, str]] = []
        for point in points:
            tagged.append((point, "boundary_probe"))
            if mirror_mode:
                mirror_point = Point2(point.x, -point.y)
                if mirror_point != point:
                    tagged.append((mirror_point, "boundary_probe_mirror"))
        before = counters["new_evaluations"]
        fill_cache_tagged(tuple(tagged))
        evaluated_now = counters["new_evaluations"] - before
        if evaluated_now:
            boundary_batch_stats["calls"] += 1
            boundary_batch_stats["points"] += evaluated_now
            boundary_batch_stats["max_size"] = max(
                boundary_batch_stats["max_size"], evaluated_now
            )
        return [cache[point] for point in points]

    qhat = float(hero_result.Q)
    thresholds = {eta: (1.0 + eta) * qhat for eta in eta_values}
    largest_threshold = max(thresholds.values())

    cache[hero_result.S2] = hero_result
    if evaluation_registry is not None:
        evaluation_registry.register(
            hero_result, source="adaptive_evidence", stage="hero_seed"
        )

    seed_points: list[Point2] = [hero_result.S2]
    extra_seed_points = tuple(dict.fromkeys(extra_seeds))
    if extra_seed_points:
        fill_cache(extra_seed_points, "extra_seed")
        seed_points.extend(extra_seed_points)
    if mirror_hero is not None:
        fill_cache((mirror_hero,), "mirror_seed")
        seed_points.append(mirror_hero)
    seed_points = list(dict.fromkeys(seed_points))

    base_points = _grid_points(bounds, config.base_resolution)
    fill_cache(base_points, "base_grid")
    cells: list[CandidateCell] = list(_base_cells(bounds, config.base_resolution))
    history: list[dict[str, object]] = [
        {
            "stage": "base",
            "resolution": config.base_resolution,
            "depth": 0,
            "point_count": len(cache),
            "cell_count": len(cells),
            "refined_cell_count": 0,
            "requested_refinement_count": 0,
            "executed_refinement_count": 0,
            "deferred_by_cap_count": 0,
            "refinement_cap_hit": False,
            "trigger_counts": {},
            "requested_cells": [],
            "max_cell_width_m": max(cell.width for cell in cells),
            "max_cell_height_m": max(cell.height for cell in cells),
            "max_refined_cells_per_level": config.max_refined_cells_per_level,
            "stop_reason": "",
        }
    ]

    deferred_keys: dict[tuple[float, float, float, float, int], str] = {}
    trigger_totals: dict[str, int] = {name: 0 for name in _TRIGGER_TIER}
    requested_total = 0
    executed_total = 0
    deferred_total = 0
    cap_hit_levels = 0
    refinement_stop_reason = _REFINEMENT_STOP_CONVERGED

    for depth in range(config.max_refinement_depth):
        _fill_cell_samples(cells, fill_cache, cache, f"refinement_samples:{depth}")
        requested: list[tuple[tuple[object, ...], CandidateCell, str]] = []
        for cell in cells:
            if _at_target_resolution(cell, config):
                continue
            trigger = _cell_trigger(cell, cache, thresholds, seed_points, config)
            if trigger is None:
                continue
            requested.append(
                (_cell_priority(cell, cache, seed_points, trigger), cell, trigger)
            )
        requested.sort(key=lambda item: item[0])

        executed, deferred = _select_with_cap(
            requested, cells, config.max_refined_cells_per_level, mirror_hero
        )
        level_triggers: dict[str, int] = {name: 0 for name in _TRIGGER_TIER}
        for _, _, trigger in requested:
            level_triggers[trigger] = level_triggers.get(trigger, 0) + 1
            trigger_totals[trigger] = trigger_totals.get(trigger, 0) + 1
        requested_total += len(requested)
        executed_total += len(executed)
        deferred_total += len(deferred)
        cap_hit = bool(deferred)
        if cap_hit:
            cap_hit_levels += 1
        for _, cell, _ in deferred:
            deferred_keys[_cell_key(cell)] = "refinement_cap"

        history.append(
            {
                "stage": "refinement" if executed else "refinement_stop",
                "depth": depth + 1,
                "requested_refinement_count": len(requested),
                "executed_refinement_count": len(executed),
                "deferred_by_cap_count": len(deferred),
                "refinement_cap_hit": cap_hit,
                "trigger_counts": dict(level_triggers),
                # Kept as plain lists so a JSON round trip compares equal to
                # the in-memory payload (the gate-G verifier re-reads them).
                "requested_cells": [
                    [
                        cell.x_min,
                        cell.y_min,
                        cell.x_max,
                        cell.y_max,
                        trigger,
                        True,
                    ]
                    for _, cell, trigger in executed
                ]
                + [
                    [
                        cell.x_min,
                        cell.y_min,
                        cell.x_max,
                        cell.y_max,
                        trigger,
                        False,
                    ]
                    for _, cell, trigger in deferred
                ],
                "cell_count": len(cells),
                "refined_cell_count": len(executed),
                "point_count": len(cache),
                "max_cell_width_m": (
                    max((cell.width for _, cell, _ in executed), default=0.0)
                ),
                "max_cell_height_m": (
                    max((cell.height for _, cell, _ in executed), default=0.0)
                ),
                "max_refined_cells_per_level": config.max_refined_cells_per_level,
                "stop_reason": "" if executed else _REFINEMENT_STOP_NOTHING_EXECUTED,
            }
        )
        if not executed:
            refinement_stop_reason = (
                _REFINEMENT_STOP_CONVERGED if not requested else _REFINEMENT_STOP_NOTHING_EXECUTED
            )
            break
        cells = _refine(cells, executed)
        _fill_cell_samples(
            [child for _, cell, _ in executed for child in cell.children()],
            fill_cache,
            cache,
            f"refinement:{depth + 1}",
        )
    else:
        refinement_stop_reason = _REFINEMENT_STOP_MAX_DEPTH

    _fill_cell_samples(cells, fill_cache, cache, "classification_samples")

    max_depth_hit_count = 0
    for cell in cells:
        if _at_target_resolution(cell, config):
            continue
        if _cell_trigger(cell, cache, thresholds, seed_points, config) is not None:
            max_depth_hit_count += 1

    if cap_hit_levels:
        refinement_stop_reason = f"{refinement_stop_reason}+{_REFINEMENT_STOP_CAP}"

    boundary_config = config.boundary_config()
    leaf_index = _LeafIndex(cells)
    regions: dict[float, tuple[tuple[Point2, float], ...]] = {}
    accepted_map: dict[float, tuple[tuple[Point2, float], ...]] = {}
    inside_cells_map: dict[float, tuple[CandidateCell, ...]] = {}
    mixed_cells_map: dict[float, tuple[CandidateCell, ...]] = {}
    unresolved_cells_map: dict[float, tuple[CandidateCell, ...]] = {}
    polygons_map: dict[float, tuple[tuple[Point2, ...], ...]] = {}
    areas: dict[float, float] = {}
    diagnostics: dict[float, CandidateRegionDiagnostics] = {}

    interim: dict[float, dict[str, object]] = {}
    for eta, threshold in thresholds.items():
        # Anchor the clip on the samples that are already known to be good; the
        # final accepted set is recomputed from the completed cache below.
        accepted_pre = _accepted_samples(cache, threshold)
        accepted_cells, accepted_by_cell = _locate_accepted(
            {point for point, _ in accepted_pre}, leaf_index
        )

        inside_cells: list[CandidateCell] = []
        mixed_cells: list[CandidateCell] = []
        unresolved_cells: list[CandidateCell] = []
        outside_count = 0
        for cell in cells:
            samples = _cell_sample_results(cell, cache)
            flags = [_is_good(result, threshold) for result in samples]
            if all(flags):
                inside_cells.append(cell)
                continue
            valid = [_is_valid(result) for result in samples]
            values = [float(result.Q) for result in samples if _is_valid(result)]
            straddles = bool(values) and min(values) <= threshold <= max(values)
            contains_accepted = cell in accepted_cells
            band_relevant = bool(values) and min(values) <= largest_threshold
            validity_mixed = len(set(valid)) > 1
            if (
                any(flags)
                or contains_accepted
                or straddles
                or (validity_mixed and band_relevant)
            ):
                mixed_cells.append(cell)
            elif _cell_key(cell) in deferred_keys:
                unresolved_cells.append(cell)
            else:
                outside_count += 1

        (
            ordered,
            boundary_stop,
            attempted_cells,
            resolved_count,
            boundary_unresolved,
            skipped_cells,
            probes_used,
        ) = _extract_boundaries(
            mixed_cells,
            cache,
            threshold,
            boundary_config,
            config,
            probe_point,
            probe_points,
            accepted_cells,
            accepted_by_cell,
            seed_points,
        )
        polygons = [cell.ring() for cell in inside_cells] + list(ordered)
        inside_area = math.fsum(cell.area for cell in inside_cells)
        fragment_area = math.fsum(ring_area_m2(ring) for ring in ordered)
        area = math.fsum(ring_area_m2(ring) for ring in polygons)
        interim[eta] = {
            "threshold": threshold,
            "inside_cells": tuple(inside_cells),
            "mixed_cells": tuple(mixed_cells),
            "deferred_cells": tuple(unresolved_cells),
            "boundary_unresolved": tuple(boundary_unresolved),
            "skipped_cells": tuple(skipped_cells),
            "outside_count": outside_count,
            "polygons": tuple(polygons),
            "area": area,
            "inside_area": inside_area,
            "fragment_area": fragment_area,
            "boundary_stop": boundary_stop,
            "attempted_cells": tuple(attempted_cells),
            "resolved": resolved_count,
            "probes": probes_used,
        }

    for eta, threshold in thresholds.items():
        data = interim[eta]
        # The full cache now contains every boundary probe, so the accepted
        # sample set is complete and matches a fresh recomputation from
        # ``surface``.
        accepted = _accepted_samples(cache, threshold)
        accepted_points = {point for point, _ in accepted}
        if _is_good(hero_result, threshold) and hero_result.S2 not in accepted_points:
            # Defensive: the Hero is seeded into the cache, so this branch is
            # unreachable; it exists so the hard requirement cannot silently
            # regress if the seed plumbing changes.
            accepted = ((hero_result.S2, float(hero_result.Q)),) + accepted
            accepted_points = accepted_points | {hero_result.S2}

        inside_cells = list(data["inside_cells"])
        mixed_cells = list(data["mixed_cells"])
        boundary_unresolved = list(data["boundary_unresolved"])
        skipped_cells = list(data["skipped_cells"])
        attempted_cells = list(data["attempted_cells"])
        unresolved_cells = _dedupe_cells(
            list(data["deferred_cells"]) + boundary_unresolved + skipped_cells
        )
        polygons = list(data["polygons"])
        area = float(data["area"])
        boundary_stop = str(data["boundary_stop"])

        area_method = AREA_METHOD_POLYGONS if polygons else AREA_METHOD_NONE
        if area > 0.0:
            region_status = REGION_STATUS_POSITIVE_AREA
        elif accepted or mixed_cells or unresolved_cells:
            region_status = REGION_STATUS_UNRESOLVED_THIN
        else:
            region_status = REGION_STATUS_NO_INSIDE_CELLS

        boundary_sizes = [cell.diameter for cell in attempted_cells]
        unresolved_boundary_sizes = [
            cell.diameter for cell in boundary_unresolved + skipped_cells
        ]
        regions[eta] = accepted
        accepted_map[eta] = accepted
        inside_cells_map[eta] = tuple(inside_cells)
        mixed_cells_map[eta] = tuple(mixed_cells)
        unresolved_cells_map[eta] = tuple(unresolved_cells)
        polygons_map[eta] = tuple(polygons)
        areas[eta] = area
        diagnostics[eta] = CandidateRegionDiagnostics(
            eta=eta,
            threshold=threshold,
            accepted_sample_count=len(accepted),
            hero_is_in_accepted_samples=hero_result.S2 in accepted_points,
            sampled_inside_cell_count=len(inside_cells),
            mixed_cell_count=len(mixed_cells),
            unresolved_cell_count=len(unresolved_cells),
            area_estimate_m2=area,
            area_estimation_method=area_method,
            region_status=region_status,
            stop_reason=f"{refinement_stop_reason}|boundary:{boundary_stop}",
            requested_refinement_count=requested_total,
            executed_refinement_count=executed_total,
            deferred_by_cap_count=deferred_total,
            max_depth_hit_count=max_depth_hit_count,
            refinement_cap_hit_count=cap_hit_levels,
            trigger_category_counts=tuple(sorted(trigger_totals.items())),
            max_unresolved_boundary_cell_width_m=max(
                (cell.width for cell in boundary_unresolved + skipped_cells), default=0.0
            ),
            max_unresolved_boundary_cell_height_m=max(
                (cell.height for cell in boundary_unresolved + skipped_cells), default=0.0
            ),
            max_unresolved_boundary_cell_diameter_m=max(
                unresolved_boundary_sizes, default=0.0
            ),
            achieved_max_boundary_cell_size_m=max(boundary_sizes, default=0.0),
            boundary_stop_reason=boundary_stop,
            boundary_attempted_cell_count=len(attempted_cells),
            boundary_resolved_cell_count=int(data["resolved"]),
            boundary_unresolved_cell_count=len(boundary_unresolved),
            boundary_skipped_cell_count=len(skipped_cells),
            boundary_probe_count=int(data["probes"]),
            boundary_polygon_count=len(polygons),
            boundary_fragment_area_m2=float(data["fragment_area"]),
            inside_cell_area_m2=float(data["inside_area"]),
            outside_by_samples_cell_count=int(data["outside_count"]),
            target_boundary_resolution_m=config.target_boundary_resolution_m,
            new_evaluation_count=counters["new_evaluations"],
            cache_hit_count=counters["cache_hits"],
            parallel_workers=parallel_workers,
            boundary_batch_call_count=boundary_batch_stats["calls"],
            boundary_batch_point_count=boundary_batch_stats["points"],
            boundary_batch_max_size=boundary_batch_stats["max_size"],
        )

    surfaces = tuple(sorted(cache.values(), key=_result_key))
    if history:
        history[-1].update(
            {
                "parallel_workers": parallel_workers,
                "boundary_batch_call_count": boundary_batch_stats["calls"],
                "boundary_batch_point_count": boundary_batch_stats["points"],
                "boundary_batch_max_size": boundary_batch_stats["max_size"],
            }
        )
    return AdaptiveCandidateResult(
        surface=surfaces,
        all_evaluated_results=surfaces,
        regions=regions,
        cells=inside_cells_map,
        thresholds=thresholds,
        approximate_areas_m2=areas,
        refinement_history=tuple(history),
        base_resolution=config.base_resolution,
        max_refinement_depth=config.max_refinement_depth,
        target_boundary_resolution_m=config.target_boundary_resolution_m,
        diagnostics=diagnostics,
        accepted_samples=accepted_map,
        boundary_polygons=polygons_map,
        mixed_cells=mixed_cells_map,
        unresolved_cells=unresolved_cells_map,
    )


def _extract_boundaries(
    mixed_cells: list[CandidateCell],
    cache: dict[Point2, Q2PointResult],
    threshold: float,
    boundary_config: BoundaryExtractionConfig,
    config: CandidateRegionConfig,
    probe_point: Callable[[Point2], Q2PointResult],
    probe_points: Callable[[tuple[Point2, ...]], list[Q2PointResult]],
    accepted_cells: set[CandidateCell],
    accepted_by_cell: dict[CandidateCell, tuple[Point2, ...]],
    seed_points: list[Point2],
) -> tuple[
    tuple[tuple[Point2, ...], ...],
    str,
    list[CandidateCell],
    int,
    list[CandidateCell],
    list[CandidateCell],
    int,
]:
    """Clip the mixed cells in a defensible order under shared budgets.

    Cells coarser than the declared boundary-reconstruction cap are *not*
    clipped: a straight chord across a cell far larger than the target
    resolution would claim area it cannot defend.  They are returned as skipped
    cells so they stay visible as unresolved instead of silently becoming
    either area or emptiness.
    """
    ordered_cells = sorted(
        mixed_cells,
        key=lambda cell: _boundary_priority(cell, accepted_cells, seed_points),
    )
    cap = config.boundary_max_cell_diameter_m()
    fragments: list[tuple[Point2, ...]] = []
    unresolved: list[CandidateCell] = []
    skipped: list[CandidateCell] = []
    attempted: list[CandidateCell] = []
    probes_used = 0
    resolved_count = 0
    stop_reason = "boundary_complete"
    for index, cell in enumerate(ordered_cells):
        if cell.diameter > cap:
            skipped.append(cell)
            continue
        if len(attempted) >= config.boundary_max_cells:
            stop_reason = "boundary_cell_limit_reached"
            for remaining_cell in ordered_cells[index:]:
                (skipped if remaining_cell.diameter > cap else unresolved).append(
                    remaining_cell
                )
            break
        if probes_used >= config.boundary_max_probes:
            stop_reason = "boundary_probe_budget_exhausted"
            for remaining_cell in ordered_cells[index:]:
                (skipped if remaining_cell.diameter > cap else unresolved).append(
                    remaining_cell
                )
            break
        remaining = config.boundary_max_probes - probes_used
        outcome: CellBoundaryResult = extract_mixed_cell_boundary(
            cell.corners(),
            cell.center,
            cache,
            threshold,
            probe_point,
            probe_many=probe_points,
            config=boundary_config,
            probe_budget=remaining,
            interior_points=_interior_sample_points(cell, accepted_by_cell.get(cell, ())),
        )
        probes_used += outcome.probes
        attempted.append(cell)
        fragments.extend(fragment.ring for fragment in outcome.fragments)
        if outcome.resolved:
            resolved_count += 1
        else:
            unresolved.append(cell)
    if skipped and stop_reason == "boundary_complete":
        stop_reason = "boundary_resolution_cap_skipped_cells"
    return (
        tuple(fragments),
        stop_reason,
        attempted,
        resolved_count,
        unresolved,
        skipped,
        probes_used,
    )


def _locate_accepted(
    points: set[Point2], leaf_index: "_LeafIndex"
) -> tuple[set[CandidateCell], dict[CandidateCell, tuple[Point2, ...]]]:
    """Map accepted samples to the leaf cells that contain them."""
    grouped: dict[CandidateCell, list[Point2]] = {}
    for point in sorted(points, key=lambda item: (item.x, item.y)):
        located = leaf_index.locate(point)
        if located is None:
            continue
        grouped.setdefault(located, []).append(point)
    return (
        set(grouped),
        {cell: tuple(items) for cell, items in grouped.items()},
    )


def _interior_sample_points(
    cell: CandidateCell, points: tuple[Point2, ...]
) -> tuple[Point2, ...]:
    """In-threshold samples that are not already triangulation samples."""
    existing = set(cell.corners()) | {cell.center}
    selected: list[Point2] = []
    for point in points:
        if point in existing:
            continue
        if point not in selected:
            selected.append(point)
        if len(selected) >= _MAX_INTERIOR_SPLIT_POINTS:
            break
    return tuple(selected)


def _dedupe_cells(cells: list[CandidateCell]) -> list[CandidateCell]:
    seen: set[CandidateCell] = set()
    unique: list[CandidateCell] = []
    for cell in cells:
        if cell in seen:
            continue
        seen.add(cell)
        unique.append(cell)
    return unique


def _fill_cell_samples(
    cells: list[CandidateCell],
    fill_cache: Callable[[tuple[Point2, ...], str], None],
    cache: dict[Point2, Q2PointResult],
    stage: str,
) -> None:
    points: list[Point2] = []
    for cell in cells:
        points.extend(cell.corners())
        points.append(cell.center)
    fill_cache(tuple(points), stage)


def _cell_sample_results(
    cell: CandidateCell, cache: dict[Point2, Q2PointResult]
) -> tuple[Q2PointResult, ...]:
    return tuple(cache[corner] for corner in cell.corners()) + (cache[cell.center],)


def _accepted_samples(
    cache: dict[Point2, Q2PointResult], threshold: float
) -> tuple[tuple[Point2, float], ...]:
    samples = [
        (point, float(result.Q))
        for point, result in cache.items()
        if _is_good(result, threshold)
    ]
    samples.sort(key=lambda item: (item[1], item[0].x, item[0].y))
    return tuple(samples)


def _at_target_resolution(cell: CandidateCell, config: CandidateRegionConfig) -> bool:
    return (
        cell.width <= config.target_boundary_resolution_m
        and cell.height <= config.target_boundary_resolution_m
    )


def _cell_trigger(
    cell: CandidateCell,
    cache: dict[Point2, Q2PointResult],
    thresholds: dict[float, float],
    seed_points: list[Point2],
    config: CandidateRegionConfig,
) -> str | None:
    """Classify why a cell deserves refinement (or None when it does not)."""
    if any(cell.contains(point) for point in seed_points):
        return TRIGGER_KNOWN_GOOD_SEED
    samples = _cell_sample_results(cell, cache)
    values = [float(result.Q) for result in samples if _is_valid(result)]
    valid = [_is_valid(result) for result in samples]
    largest_threshold = max(thresholds.values())
    if values and min(values) <= largest_threshold:
        return TRIGGER_Q_THRESHOLD
    if values and any(
        min(values) <= threshold <= max(values) for threshold in thresholds.values()
    ):
        return TRIGGER_Q_THRESHOLD
    if len(set(valid)) > 1:
        return TRIGGER_VALIDITY_BOUNDARY
    if _near_seed(cell, seed_points, config.near_hero_cell_factor):
        return TRIGGER_OTHER
    if values:
        spread = max(values) - min(values)
        if (
            config.q_range_refinement_ratio > 0.0
            and max(values) <= 2.0 * largest_threshold
            and spread > config.q_range_refinement_ratio * max(1.0, abs(max(values)))
        ):
            return TRIGGER_OTHER
    return None


def _cell_priority(
    cell: CandidateCell,
    cache: dict[Point2, Q2PointResult],
    seed_points: list[Point2],
    trigger: str,
) -> tuple[object, ...]:
    """Explicable ordering: trigger tier, then closeness to the known good band.

    Far-away Crec validity boundaries are last so they cannot starve the Q
    level-set boundary that actually defines the candidate band.
    """
    samples = _cell_sample_results(cell, cache)
    values = [float(result.Q) for result in samples if _is_valid(result)]
    spread = (max(values) - min(values)) if values else 0.0
    distance = min(
        (_cell_point_distance(cell, point) for point in seed_points), default=0.0
    )
    return (
        _TRIGGER_TIER.get(trigger, len(_TRIGGER_TIER)),
        distance,
        -spread,
        -cell.area,
    )


def _boundary_priority(
    cell: CandidateCell,
    accepted_cells: set[CandidateCell],
    seed_points: list[Point2],
) -> tuple[float, float]:
    """Cells holding an accepted sample come first, then near-seed cells."""
    distance = min(
        (_cell_point_distance(cell, point) for point in seed_points), default=0.0
    )
    return (0.0 if cell in accepted_cells else 1.0, distance)


def _select_with_cap(
    requested: list[tuple[tuple[object, ...], CandidateCell, str]],
    cells: list[CandidateCell],
    cap: int,
    mirror_hero: Point2 | None,
) -> tuple[
    list[tuple[tuple[object, ...], CandidateCell, str]],
    list[tuple[tuple[object, ...], CandidateCell, str]],
]:
    if mirror_hero is None:
        return requested[:cap], requested[cap:]

    cell_map = {_cell_key(cell): cell for cell in cells}
    seen: set[tuple[float, float, float, float, int]] = set()
    units: list[
        tuple[
            tuple[object, ...],
            tuple[CandidateCell, ...],
            str,
        ]
    ] = []
    for priority, cell, trigger in requested:
        key = _cell_key(cell)
        if key in seen:
            continue
        mirror = cell_map.get(_cell_key(_mirror_cell(cell)))
        unit = (
            (cell,)
            if mirror is None or mirror == cell
            else tuple(dict.fromkeys((cell, mirror)))
        )
        seen.update(_cell_key(item) for item in unit)
        units.append((priority, unit, trigger))

    executed: list[tuple[tuple[object, ...], CandidateCell, str]] = []
    deferred: list[tuple[tuple[object, ...], CandidateCell, str]] = []
    for priority, unit, trigger in units:
        if len(executed) + len(unit) <= cap:
            executed.extend((priority, item, trigger) for item in unit)
        else:
            deferred.extend((priority, item, trigger) for item in unit)
    return executed, deferred


def _refine(
    cells: list[CandidateCell],
    executed: list[tuple[tuple[object, ...], CandidateCell, str]],
) -> list[CandidateCell]:
    selected = {_cell_key(cell) for _, cell, _ in executed}
    refined: list[CandidateCell] = []
    for cell in cells:
        refined.extend(cell.children() if _cell_key(cell) in selected else (cell,))
    return refined


def _near_seed(
    cell: CandidateCell, seed_points: list[Point2], factor: float
) -> bool:
    limit = factor * cell.diameter
    return any(
        _cell_point_distance(cell, point) <= limit for point in seed_points
    )


def _cell_point_distance(cell: CandidateCell, point: Point2) -> float:
    dx = max(cell.x_min - point.x, 0.0, point.x - cell.x_max)
    dy = max(cell.y_min - point.y, 0.0, point.y - cell.y_max)
    return math.hypot(dx, dy)


def _grid_points(bounds: SearchBounds, resolution: int) -> tuple[Point2, ...]:
    return tuple(
        Point2(
            bounds.x_min + bounds.width * ix / (resolution - 1),
            bounds.y_min + bounds.height * iy / (resolution - 1),
        )
        for ix in range(resolution)
        for iy in range(resolution)
    )


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


class _LeafIndex:
    """Locate the leaf cell that contains a point of the root rectangle."""

    def __init__(self, cells: list[CandidateCell]) -> None:
        self._cells = cells
        self._x_breaks = sorted(
            {round(cell.x_min, 9) for cell in cells}
            | {round(cell.x_max, 9) for cell in cells}
        )
        self._y_breaks = sorted(
            {round(cell.y_min, 9) for cell in cells}
            | {round(cell.y_max, 9) for cell in cells}
        )
        self._by_interval: dict[tuple[int, int], CandidateCell] = {}
        for cell in cells:
            self._by_interval[self._interval(cell)] = cell

    def _interval(self, cell: CandidateCell) -> tuple[int, int]:
        return (
            bisect.bisect_left(self._x_breaks, round(cell.x_min, 9)),
            bisect.bisect_left(self._y_breaks, round(cell.y_min, 9)),
        )

    def locate(self, point: Point2) -> CandidateCell | None:
        ix = bisect.bisect_right(self._x_breaks, point.x) - 1
        iy = bisect.bisect_right(self._y_breaks, point.y) - 1
        return self._by_interval.get((ix, iy))


def _is_good(result: Q2PointResult, threshold: float) -> bool:
    return _is_valid(result) and float(result.Q) <= threshold


def _is_valid(result: Q2PointResult) -> bool:
    return is_valid_incumbent_result(result)


def _result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return (
        math.inf if result.Q is None else float(result.Q),
        result.S2.x,
        result.S2.y,
    )
