"""Section-6 resolution study: three extraction budgets, one frozen target set.

The numerical candidate good region is a sampled sublevel approximation, not a
certified set.  The only available credibility evidence is convergence: rebuild
the region at coarse/medium/fine *extraction budgets* on the *same frozen
objective* and report how the area, the connected-component count and the saved
boundary geometry move between budgets.

Section 6 of the round-2 work order requires that the three budgets compare the
*same target set*.  Everything that defines the target set is therefore frozen
once per report and recorded in :class:`FrozenTargetSet`:

``first observation``
    ``S1``, ``theta1_deg``, ``epsilon_deg`` and the frozen geometry / reception /
    near-distance constants.
``Q1 + Q2 evaluator source fingerprint``
    SHA-256 over the ``.py`` sources of ``src/q2/code`` and ``src/q1/code``.
``inner verifier budget and tolerances``
    :class:`InnerVerificationConfig` plus the near-parallel densification gate.
``q_reference`` and ``threshold_by_eta``
    ``T_eta = (1 + eta) * q_reference``.
``search box and ROI``
    the frozen :class:`SearchBounds`.

Only the *declared* spatial extraction budget (``base_resolution``,
``max_refinement_depth``, ``target_boundary_resolution_m``, the boundary budget
and the per-level refinement cap) may differ between levels.

Two modes exist:

* shared mode -- ``hero_result`` and ``bounds`` are supplied (or discovered once
  from a single ``search_outer`` call).  All levels share that Hero, that ROI and
  one :class:`EvaluationRegistry`, so a per-point evaluation is never repeated;
  this is the mode section 6 requires.
* legacy mode -- neither is supplied.  Each level still runs its own
  ``search_outer`` (the pre-round-2 behaviour).  That means the levels do *not*
  share a Hero, so the report carries an explicit warning and cannot be marked
  converged.

Nothing here certifies a global optimum, a true level set, or a positive area.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import time
from pathlib import Path

from src.q2.code.geometry.a1 import (
    INNER_RADIUS_M,
    OMEGA_RADIUS_M,
    OUTER_RADIUS_M,
)
from src.q2.code.geometry.angular_image import NEAR_RADIUS_M
from src.q2.code.geometry.crec import MIN_RECEPTION_RADIUS_M
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.batch import Q2PointBatchExecutor
from src.q2.code.solver.candidate_regions import (
    CandidateCell,
    CandidateRegionConfig,
    CandidateRegionDiagnostics,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.incumbent import (
    EvaluationRegistry,
    is_valid_incumbent_result,
)
from src.q2.code.solver.inner_max import InnerVerificationConfig
from src.q2.code.solver.outer_search import (
    OuterSearchConfig,
    SearchBounds,
    search_outer,
)
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point
from src.q2.code.solver.region_boundary import ring_area_m2
from src.q2.code.verifier.verify_inner import (
    default_endpoint_densification_distance_rad,
)


STABILITY_SCHEMA = "q2_candidate_region_resolution_stability_v2_section6"
COMPONENT_METHOD = "positive_area_or_edge_adjacency_of_saved_numerical_display_polygons"
BOUNDARY_DISTANCE_METHOD = (
    "sampled_bidirectional_hausdorff_of_saved_boundary_polygon_rings"
)
EVALUATOR_FINGERPRINT_ROOTS = (
    "src/q2/code/geometry",
    "src/q2/code/model",
    "src/q2/code/solver",
    "src/q2/code/verifier",
    "src/q1/code",
)
EVALUATOR_FINGERPRINT_SUFFIX = ".py"
EVALUATOR_FINGERPRINT_SKIP_PARTS = ("__pycache__", ".pytest_cache", "artifacts", "q2_verification")

_LEGACY_WARNING = (
    "LEGACY MODE: every level ran its own search_outer, so the coarse/medium/fine "
    "levels do NOT share one Hero; the three budgets do not compare the same "
    "target set and section 6 is NOT satisfied"
)
_IGNORED_OUTER_CONFIG_WARNING = (
    "per-level outer_config was supplied together with a shared Hero and was "
    "therefore not used; section 6 forbids a per-level Hero search"
)


@dataclass(frozen=True)
class ResolutionConvergenceCriteria:
    """Acceptance thresholds declared *before* the production run.

    Every field is written into the report before any result is known, and the
    convergence verdict is computed from these values only.  They are the
    pre-declared budget/accuracy gate; they are never relaxed after the fact.
    """

    max_area_relative_delta_between_levels: float = 0.25
    require_positive_area_at_every_level: bool = True
    require_identical_component_count: bool = True
    max_boundary_bidirectional_distance_over_target: float = 1.0
    max_phase_area_relative_deviation: float = 0.25
    reference_update_tolerance_m: float = 1e-6
    max_reference_update_rounds: int = 2
    cache_consistency_probe_count: int = 3
    cache_consistency_tolerance_m: float = 1e-9

    def __post_init__(self) -> None:
        if not 0.0 < self.max_area_relative_delta_between_levels:
            raise ValueError("max_area_relative_delta_between_levels must be positive.")
        if not 0.0 < self.max_boundary_bidirectional_distance_over_target:
            raise ValueError(
                "max_boundary_bidirectional_distance_over_target must be positive."
            )
        if not 0.0 < self.max_phase_area_relative_deviation:
            raise ValueError("max_phase_area_relative_deviation must be positive.")
        if self.reference_update_tolerance_m < 0.0:
            raise ValueError("reference_update_tolerance_m must be nonnegative.")
        if self.max_reference_update_rounds < 0:
            raise ValueError("max_reference_update_rounds must be nonnegative.")
        if self.cache_consistency_probe_count < 0:
            raise ValueError("cache_consistency_probe_count must be nonnegative.")
        if self.cache_consistency_tolerance_m < 0.0:
            raise ValueError("cache_consistency_tolerance_m must be nonnegative.")


DECLARED_RESOLUTION_CRITERIA = ResolutionConvergenceCriteria()
DECLARED_PHASE_FRACTIONS = (0.25, 0.5)
PRODUCTION_ETAS = (0.01, 0.02, 0.05, 0.10)


@dataclass(frozen=True)
class ExtractionLevelSpec:
    """One declared spatial extraction budget.

    ``outer_config`` is only honoured in legacy mode.  When a shared Hero is
    supplied it is recorded as supplied-but-ignored instead of silently dropped.
    """

    name: str
    candidate_region_config: CandidateRegionConfig
    outer_config: OuterSearchConfig | None = None


@dataclass(frozen=True)
class FrozenTargetSet:
    """Everything section 6 requires the three levels to share."""

    schema: str
    S1: tuple[float, float]
    theta1_deg: float
    epsilon_deg: float
    etas: tuple[float, ...]
    primary_eta: float
    q_reference_m: float
    q_reference_source: str
    hero_S2: tuple[float, float]
    thresholds_by_eta: tuple[tuple[float, float], ...]
    thresholds_at_production_etas: tuple[tuple[float, float], ...]
    bounds: tuple[float, float, float, float]
    bounds_derivation: str
    shared_hero: bool
    shared_bounds: bool
    evaluator_fingerprint: str
    evaluator_fingerprint_file_count: int
    evaluator_fingerprint_roots: tuple[tuple[str, str], ...]
    inner_verification_budget: tuple[tuple[str, float], ...]
    endpoint_densification_distance_rad: float
    geometry_constants: tuple[tuple[str, float], ...]
    reference_update_rounds: int
    reference_update_history: tuple[dict[str, object], ...]
    reference_selection_rows: tuple[dict[str, object], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionLevel:
    """Section-6 field list for one (level, eta) pair.

    The raw upstream diagnostics are kept verbatim in ``region_diagnostics``;
    the derived fields make the section-6 checklist machine-readable.
    """

    name: str
    eta: float
    level_index: int
    candidate_region_config: CandidateRegionConfig
    outer_config: OuterSearchConfig | None
    outer_config_used: bool
    hero_S2: tuple[float, float]
    q_reference_m: float
    threshold: float
    thresholds_by_eta: tuple[tuple[float, float], ...]
    valid_sample_count: int
    threshold_inside_sample_count: int
    accepted_sample_count: int
    hero_is_in_accepted_samples: bool
    sampled_inside_cell_count: int
    mixed_cell_count: int
    unresolved_cell_count: int
    outside_by_samples_cell_count: int
    area_estimate_m2: float
    area_estimation_method: str
    area_role: str
    achieved_max_boundary_cell_size_m: float
    target_boundary_resolution_m: float
    boundary_polygon_count: int
    area_bearing_ring_count: int
    component_count: int
    component_method: str
    component_gate_comparable: bool
    area_abs_delta_vs_previous_m2: float | None
    area_relative_delta_vs_previous: float | None
    area_relative_delta_reference_level: str | None
    boundary_sample_count: int
    boundary_bidirectional_distance_m: float | None
    boundary_distance_reference_level: str | None
    boundary_distance_method: str
    new_evaluation_count: int
    cache_hit_count: int
    runtime_s: float
    stop_reason: str
    refinement_stop_reason: str
    boundary_stop_reason: str
    region_status: str
    region_diagnostics: CandidateRegionDiagnostics


@dataclass(frozen=True)
class GridPhaseSample:
    """One lattice-phase offset of the declared phase-probe level."""

    phase_fraction: float
    lattice_shift_m: tuple[float, float]
    q_reference_m: float
    threshold: float
    area_estimate_m2: float
    raw_area_estimate_m2: float
    component_count: int
    accepted_sample_count: int
    sampled_inside_cell_count: int
    mixed_cell_count: int
    area_relative_delta_vs_zero_phase: float | None
    component_delta_vs_zero_phase: int
    stop_reason: str
    runtime_s: float


@dataclass(frozen=True)
class GridPhasePerturbation:
    """Shift the sampling-lattice origin, never the Hero or the target geometry.

    Only the origin of the base sampling lattice is translated by a declared
    fraction of one base cell.  The physical input, ``q_reference``, the
    thresholds and the ROI box are unchanged; the shifted-lattice regions are
    cropped back to the frozen ROI before any area or component count is taken.
    """

    applied: bool
    level_name: str | None
    eta: float
    phase_fractions: tuple[float, ...]
    base_cell_size_m: tuple[float, float] | None
    roi: tuple[float, float, float, float] | None
    samples: tuple[GridPhaseSample, ...]
    max_area_relative_deviation: float | None
    component_counts: tuple[int, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class CacheConsistencyCheck:
    """Re-evaluate a declared sample of cached points and compare the Q values."""

    checked_count: int
    tolerance_m: float
    max_abs_difference_m: float | None
    passed: bool
    rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ResolutionStabilityReport:
    schema: str
    eta: float
    etas: tuple[float, ...]
    frozen: FrozenTargetSet
    levels: tuple[ResolutionLevel, ...]
    reference_level: str
    q_reference_relative_spread: float
    area_relative_spread: float | None
    max_boundary_bidirectional_distance_m: float | None
    component_counts: tuple[int, ...]
    criteria: ResolutionConvergenceCriteria
    grid_phase_perturbation: GridPhasePerturbation
    cache_consistency: CacheConsistencyCheck
    converged: bool
    unconverged_reasons: tuple[str, ...]
    observations: tuple[str, ...]
    certified: bool = False


def candidate_region_resolution_stability(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    levels: tuple[ExtractionLevelSpec, ...],
    *,
    eta: float = 0.05,
    etas: tuple[float, ...] | None = None,
    hero_result: Q2PointResult | None = None,
    bounds: SearchBounds | None = None,
    hero_source: str = "provided_hero_result",
    reference_candidates: tuple[tuple[str, Point2], ...] = (),
    outer_config: OuterSearchConfig | None = None,
    mirror_symmetric: bool = False,
    criteria: ResolutionConvergenceCriteria = DECLARED_RESOLUTION_CRITERIA,
    phase_fractions: tuple[float, ...] = DECLARED_PHASE_FRACTIONS,
    phase_probe_level: str | None = None,
    boundary_sample_limit: int = 400,
    workers: int = 1,
) -> ResolutionStabilityReport:
    """Rebuild the eta-region at several extraction budgets on one target set.

    ``hero_result`` and ``bounds`` freeze the target set.  When they are omitted
    the function falls back to the pre-round-2 behaviour (one ``search_outer``
    per level) and reports that section 6 is not satisfied.
    """
    if len(levels) < 2:
        raise ValueError("At least two resolution levels are required.")
    specs = tuple(_normalise_level(level) for level in levels)
    names = [spec.name for spec in specs]
    if len(set(names)) != len(names):
        raise ValueError("Resolution level names must be unique.")
    eta_values = (float(eta),) if etas is None else tuple(float(value) for value in etas)
    if not eta_values:
        raise ValueError("At least one eta is required.")
    for value in eta_values:
        if not 0.0 < value < 1.0:
            raise ValueError("every eta must lie in (0, 1).")
    if float(eta) not in eta_values:
        raise ValueError("eta must be one of the declared etas.")
    if boundary_sample_limit < 2:
        raise ValueError("boundary_sample_limit must be at least two.")
    if workers < 1:
        raise ValueError("workers must be at least one.")
    if phase_probe_level is not None and phase_probe_level not in names:
        raise ValueError("phase_probe_level must name one of the declared levels.")

    notes: list[str] = []
    legacy = hero_result is None or bounds is None

    with Q2PointBatchExecutor(S1, theta1_deg, epsilon_deg, workers=workers) as batch:
        registry = EvaluationRegistry()
        if legacy:
            notes.append(_LEGACY_WARNING)
        else:
            if hero_result.Q is None or not math.isfinite(float(hero_result.Q)):
                raise ValueError("The supplied Hero must have a finite Q.")
            if not bounds.contains(hero_result.S2, tolerance_m=1e-6):
                raise ValueError("The supplied Hero must lie inside the supplied bounds.")
            if any(spec.outer_config is not None for spec in specs):
                notes.append(_IGNORED_OUTER_CONFIG_WARNING)

        fingerprint, fingerprint_count, fingerprint_roots = evaluator_source_fingerprint()
        frozen_base = {
            "schema": STABILITY_SCHEMA,
            "S1": (S1.x, S1.y),
            "theta1_deg": float(theta1_deg),
            "epsilon_deg": float(epsilon_deg),
            "etas": eta_values,
            "primary_eta": float(eta),
            "bounds": (bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max)
            if bounds is not None
            else (math.nan, math.nan, math.nan, math.nan),
            "bounds_derivation": bounds.derivation if bounds is not None else "per_level_search_outer",
            "shared_bounds": bounds is not None,
            "shared_hero": not legacy,
            "evaluator_fingerprint": fingerprint,
            "evaluator_fingerprint_file_count": fingerprint_count,
            "evaluator_fingerprint_roots": fingerprint_roots,
            "inner_verification_budget": _inner_budget(),
            "endpoint_densification_distance_rad": default_endpoint_densification_distance_rad(
                epsilon_deg
            ),
            "geometry_constants": _geometry_constants(),
        }

        sample_index: dict[tuple[int, float], tuple[Point2, ...]] = {}
        if legacy:
            reference, reference_source, reference_history = None, "per_level_search_outer", ()
            selection_rows: tuple[dict[str, object], ...] = ()
            level_rows = _run_levels_legacy(
                S1, theta1_deg, epsilon_deg, specs, eta_values, registry, batch,
                outer_config, mirror_symmetric, sample_index,
            )
        else:
            (
                reference,
                reference_source,
                reference_history,
                level_rows,
                selection_rows,
            ) = _run_levels_shared(
                S1, theta1_deg, epsilon_deg, specs, eta_values, registry, batch,
                hero_result, bounds, hero_source, reference_candidates,
                mirror_symmetric, criteria, sample_index,
            )
        level_rows = _link_levels(level_rows, sample_index, boundary_sample_limit)
        frozen = FrozenTargetSet(
            q_reference_m=math.nan if reference is None else float(reference.Q),
            q_reference_source=reference_source,
            hero_S2=(math.nan, math.nan) if reference is None else (reference.S2.x, reference.S2.y),
            thresholds_by_eta=_thresholds(reference, eta_values),
            thresholds_at_production_etas=_thresholds(reference, PRODUCTION_ETAS),
            reference_update_rounds=len(reference_history),
            reference_update_history=reference_history,
            reference_selection_rows=selection_rows,
            notes=tuple(notes),
            **frozen_base,
        )

        phase = _grid_phase_perturbation(
            S1,
            theta1_deg,
            epsilon_deg,
            specs,
            eta_values,
            registry,
            batch,
            reference,
            bounds,
            mirror_symmetric,
            phase_fractions,
            phase_probe_level,
            level_rows,
        )
        cache_check = _cache_consistency(
            S1, theta1_deg, epsilon_deg, registry, level_rows, criteria
        )

    levels_report = tuple(level_rows)
    converged, reasons = _convergence_verdict(
        levels_report, frozen, phase, cache_check, criteria
    )
    qhats = [level.q_reference_m for level in levels_report]
    finite_qhats = [value for value in qhats if math.isfinite(value)]
    qhat_spread = (
        (max(finite_qhats) - min(finite_qhats)) / max(1e-12, abs(min(finite_qhats)))
        if finite_qhats
        else None
    )
    areas = [level.area_estimate_m2 for level in levels_report]
    area_spread = (
        (max(areas) - min(areas)) / max(1e-12, abs(max(areas))) if areas else None
    )
    distances = [
        level.boundary_bidirectional_distance_m
        for level in levels_report
        if level.boundary_bidirectional_distance_m is not None
    ]
    component_counts = tuple(level.component_count for level in levels_report)
    observations = (
        f"schema {STABILITY_SCHEMA}",
        f"shared Hero across levels: {frozen.shared_hero}",
        f"shared bounds/ROI across levels: {frozen.shared_bounds}",
        f"evaluator source fingerprint: {frozen.evaluator_fingerprint} "
        f"over {frozen.evaluator_fingerprint_file_count} files",
        f"q_reference relative spread over levels: {qhat_spread}",
        "area relative spread over level/eta rows: " + str(area_spread),
        "saved-display-polygon component counts across level/eta rows: "
        + ", ".join(map(str, component_counts)),
        "component-count gate comparable across level/eta rows: "
        + ", ".join(
            str(level.component_gate_comparable) for level in levels_report
        ),
        f"declared convergence criteria: {criteria}",
        BOUNDARY_DISTANCE_METHOD,
        "the saved boundary polygons are numerical display geometry, not a "
        "certified set containment",
        "a finite sample set is a lower estimate of the true level set; it is "
        "never a global-optimality certificate",
    ) + tuple(reasons)
    return ResolutionStabilityReport(
        schema=STABILITY_SCHEMA,
        eta=float(eta),
        etas=eta_values,
        frozen=frozen,
        levels=levels_report,
        reference_level=specs[-1].name,
        q_reference_relative_spread=qhat_spread,
        area_relative_spread=area_spread,
        max_boundary_bidirectional_distance_m=max(distances, default=None),
        component_counts=component_counts,
        criteria=criteria,
        grid_phase_perturbation=phase,
        cache_consistency=cache_check,
        converged=converged,
        unconverged_reasons=reasons,
        observations=observations,
    )


_PRODUCTION_ETAS = (0.01, 0.02, 0.05, 0.10)


def _normalise_level(level: object) -> ExtractionLevelSpec:
    if isinstance(level, ExtractionLevelSpec):
        return level
    if isinstance(level, tuple) and len(level) == 3:
        name, outer_config, region_config = level
        raise ValueError(
            "Per-level outer configurations are no longer accepted: section 6 "
            "forbids a per-level Hero search. Pass ExtractionLevelSpec("
            f"{name!r}, {region_config!r}, outer_config={outer_config!r}) and run it "
            "in legacy mode by omitting hero_result/bounds, or drop outer_config "
            "and supply one shared Hero."
        )
    raise TypeError("levels must contain ExtractionLevelSpec entries.")


def _thresholds(
    reference: Q2PointResult | None, etas: tuple[float, ...]
) -> tuple[tuple[float, float], ...]:
    if reference is None or reference.Q is None:
        return tuple((value, math.nan) for value in etas)
    return tuple((value, (1.0 + value) * float(reference.Q)) for value in etas)


def _inner_budget() -> tuple[tuple[str, float], ...]:
    config = InnerVerificationConfig()
    return (
        ("inner_verification.base_samples_per_interval", float(config.base_samples_per_interval)),
        ("inner_verification.peak_seeds", float(config.peak_seeds)),
        ("inner_verification.refinement_iterations", float(config.refinement_iterations)),
        ("inner_verification.near_parallel_bands", float(config.near_parallel_bands)),
        ("inner_verification.promotion_tolerance_m", float(config.promotion_tolerance_m)),
    )


def _geometry_constants() -> tuple[tuple[str, float], ...]:
    return (
        ("geometry.inner_radius_m", float(INNER_RADIUS_M)),
        ("geometry.outer_radius_m", float(OUTER_RADIUS_M)),
        ("geometry.omega_radius_m", float(OMEGA_RADIUS_M)),
        ("geometry.min_reception_radius_m", float(MIN_RECEPTION_RADIUS_M)),
        ("geometry.near_radius_m", float(NEAR_RADIUS_M)),
    )


# ---------------------------------------------------------------------------
# shared / legacy level execution
# ---------------------------------------------------------------------------


def _run_levels_shared(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    specs: tuple[ExtractionLevelSpec, ...],
    eta_values: tuple[float, ...],
    registry: EvaluationRegistry,
    batch: Q2PointBatchExecutor,
    hero_result: Q2PointResult,
    bounds: SearchBounds,
    hero_source: str,
    reference_candidates: tuple[tuple[str, Point2], ...],
    mirror_symmetric: bool,
    criteria: ResolutionConvergenceCriteria,
    sample_index: dict[tuple[int, float], tuple[Point2, ...]],
):
    reference = hero_result
    reference_source = hero_source
    history: list[dict[str, object]] = []

    reference, selection = _select_reference(
        S1, theta1_deg, epsilon_deg, reference, reference_source,
        reference_candidates, registry, batch,
    )
    reference_source = str(selection["selected_source"])
    selection_rows = tuple(selection["rows"])

    levels_report: list[ResolutionLevel] = []
    for round_index in range(criteria.max_reference_update_rounds + 1):
        levels_report = []
        for level_index, spec in enumerate(specs):
            started = time.perf_counter()
            adaptive = build_adaptive_candidate_regions(
                S1,
                theta1_deg,
                epsilon_deg,
                bounds,
                reference,
                etas=eta_values,
                config=spec.candidate_region_config,
                mirror_hero=Point2(reference.S2.x, -reference.S2.y) if mirror_symmetric else None,
                batch_evaluator=batch.evaluate,
                evaluation_registry=registry,
            )
            runtime = time.perf_counter() - started
            for eta_value in eta_values:
                row, samples = _level_row(
                    spec,
                    level_index,
                    eta_value,
                    reference,
                    bounds,
                    adaptive,
                    runtime,
                    outer_config_used=False,
                )
                levels_report.append(row)
                sample_index[(level_index, eta_value)] = samples
        better = _best_better_point(
            S1, theta1_deg, epsilon_deg, registry, reference, criteria
        )
        if better is None or round_index >= criteria.max_reference_update_rounds:
            if better is not None:
                history.append(
                    {
                        "round": round_index,
                        "status": "reference_update_budget_exhausted",
                        "better_q_m": float(better.Q),
                        "better_S2": [better.S2.x, better.S2.y],
                    }
                )
            break
        history.append(
            {
                "round": round_index,
                "status": "reference_updated",
                "previous_q_reference_m": float(reference.Q),
                "previous_hero_S2": [reference.S2.x, reference.S2.y],
                "promoted_q_m": float(better.Q),
                "promoted_S2": [better.S2.x, better.S2.y],
                "reason": "a shared-registry surface point was strictly better and "
                "was revalidated by the same evaluator before the reference moved",
            }
        )
        reference, reference_source = better, f"surface_update_round_{round_index + 1}"
    return reference, reference_source, tuple(history), levels_report, selection_rows


def _run_levels_legacy(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    specs: tuple[ExtractionLevelSpec, ...],
    eta_values: tuple[float, ...],
    registry: EvaluationRegistry,
    batch: Q2PointBatchExecutor,
    outer_config: OuterSearchConfig | None,
    mirror_symmetric: bool,
    sample_index: dict[tuple[int, float], tuple[Point2, ...]],
):
    rows: list[ResolutionLevel] = []
    for level_index, spec in enumerate(specs):
        config = spec.outer_config or outer_config
        if config is None:
            raise ValueError(
                "Legacy mode (no shared Hero) needs an outer_config per level or one "
                "shared outer_config."
            )
        search = search_outer(S1, theta1_deg, epsilon_deg, config=config)
        hero = search.recommended
        if hero.Q is None or not math.isfinite(float(hero.Q)):
            raise ValueError(f"Resolution level {spec.name!r} produced a non-finite Hero Q.")
        started = time.perf_counter()
        adaptive = build_adaptive_candidate_regions(
            S1,
            theta1_deg,
            epsilon_deg,
            search.bounds,
            hero,
            etas=eta_values,
            config=spec.candidate_region_config,
            mirror_hero=Point2(hero.S2.x, -hero.S2.y) if mirror_symmetric else None,
            batch_evaluator=batch.evaluate,
            evaluation_registry=registry,
        )
        runtime = time.perf_counter() - started
        for eta_value in eta_values:
            row, samples = _level_row(
                spec,
                level_index,
                eta_value,
                hero,
                search.bounds,
                adaptive,
                runtime,
                outer_config_used=True,
            )
            rows.append(row)
            sample_index[(level_index, eta_value)] = samples
    return rows


def _select_reference(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    hero_result: Q2PointResult,
    hero_source: str,
    reference_candidates: tuple[tuple[str, Point2], ...],
    registry: EvaluationRegistry,
    batch: Q2PointBatchExecutor,
) -> tuple[Q2PointResult, dict[str, object]]:
    """Pick the q_reference from declared seed points, each freshly evaluated.

    Section 6: a potentially better Hero is recorded and validated *before* the
    reference moves; the same point is registered so the levels reuse it.
    """
    rows: list[dict[str, object]] = []
    best = _register_point(S1, theta1_deg, epsilon_deg, hero_result, registry, batch, "reference_hero")
    rows.append(
        {
            "source": hero_source,
            "S2": [hero_result.S2.x, hero_result.S2.y],
            "Q_m": None if hero_result.Q is None else float(hero_result.Q),
            "valid": is_valid_incumbent_result(hero_result),
            "selected": True,
        }
    )
    for name, point in reference_candidates:
        result = _register_point(
            S1, theta1_deg, epsilon_deg,
            evaluate_q2_point(S1, theta1_deg, point, epsilon_deg),
            registry, batch, "reference_candidate",
        )
        valid = is_valid_incumbent_result(result)
        selected = False
        if valid and (best.Q is None or float(result.Q) < float(best.Q)):
            best, selected = result, True
        rows.append(
            {
                "source": name,
                "S2": [result.S2.x, result.S2.y],
                "Q_m": None if result.Q is None else float(result.Q),
                "valid": valid,
                "selected": selected,
            }
        )
    # Every "selected" flag must describe the final choice.
    for row in rows:
        row["selected"] = (row["S2"] == [best.S2.x, best.S2.y]) and bool(row["valid"])
    return best, {
        "selected_source": next(
            (str(row["source"]) for row in rows if row["selected"]), hero_source
        ),
        "rows": rows,
    }


def _register_point(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    result: Q2PointResult,
    registry: EvaluationRegistry,
    batch: Q2PointBatchExecutor,
    stage: str,
) -> Q2PointResult:
    existing = registry.get(result.S2)
    if existing is not None:
        return existing.result
    registry.register(result, source="resolution_stability", stage=stage)
    return result


def _best_better_point(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    registry: EvaluationRegistry,
    reference: Q2PointResult,
    criteria: ResolutionConvergenceCriteria,
) -> Q2PointResult | None:
    if reference.Q is None:
        return None
    best: Q2PointResult | None = None
    for record in registry.records:
        result = record.result
        if not is_valid_incumbent_result(result) or result.Q is None:
            continue
        if float(result.Q) < float(reference.Q) - criteria.reference_update_tolerance_m:
            if best is None or float(result.Q) < float(best.Q):
                best = result
    if best is None:
        return None
    # Re-validate the promoted point through a direct evaluator call: the
    # registry value alone would silently mix a stale Q with a new reference.
    fresh = evaluate_q2_point(S1, theta1_deg, best.S2, epsilon_deg)
    if not is_valid_incumbent_result(fresh) or fresh.Q is None:
        return None
    if abs(float(fresh.Q) - float(best.Q)) > criteria.cache_consistency_tolerance_m:
        raise RuntimeError(
            "registry Q disagrees with a direct re-evaluation of the promotion "
            f"candidate: {best.Q!r} vs {fresh.Q!r}"
        )
    return fresh


def _level_row(
    spec: ExtractionLevelSpec,
    level_index: int,
    eta_value: float,
    reference: Q2PointResult,
    bounds: SearchBounds,
    adaptive,
    runtime: float,
    *,
    outer_config_used: bool,
) -> tuple[ResolutionLevel, tuple[Point2, ...]]:
    diagnostics = adaptive.diagnostics[eta_value]
    valid_sample_count = sum(
        1 for result in adaptive.surface if is_valid_incumbent_result(result)
    )
    stop_reason = diagnostics.stop_reason
    if "|boundary:" in stop_reason:
        refinement_stop_reason, boundary_stop_reason = stop_reason.split("|boundary:", 1)
    else:
        refinement_stop_reason, boundary_stop_reason = stop_reason, ""
    rings = adaptive.boundary_polygons[eta_value]
    samples = _boundary_samples(rings)
    return ResolutionLevel(
        name=spec.name,
        eta=eta_value,
        level_index=level_index,
        candidate_region_config=spec.candidate_region_config,
        outer_config=spec.outer_config,
        outer_config_used=outer_config_used,
        hero_S2=(reference.S2.x, reference.S2.y),
        q_reference_m=float(reference.Q),
        threshold=float(adaptive.thresholds[eta_value]),
        thresholds_by_eta=tuple(
            sorted((key, float(value)) for key, value in adaptive.thresholds.items())
        ),
        valid_sample_count=valid_sample_count,
        threshold_inside_sample_count=diagnostics.accepted_sample_count,
        accepted_sample_count=diagnostics.accepted_sample_count,
        hero_is_in_accepted_samples=diagnostics.hero_is_in_accepted_samples,
        sampled_inside_cell_count=diagnostics.sampled_inside_cell_count,
        mixed_cell_count=diagnostics.mixed_cell_count,
        unresolved_cell_count=diagnostics.unresolved_cell_count,
        outside_by_samples_cell_count=diagnostics.outside_by_samples_cell_count,
        area_estimate_m2=float(adaptive.approximate_areas_m2[eta_value]),
        area_estimation_method=diagnostics.area_estimation_method,
        area_role="numerical_display_area_not_a_certified_safe_action_set",
        achieved_max_boundary_cell_size_m=diagnostics.achieved_max_boundary_cell_size_m,
        target_boundary_resolution_m=diagnostics.target_boundary_resolution_m,
        boundary_polygon_count=diagnostics.boundary_polygon_count,
        area_bearing_ring_count=len(rings),
        component_count=_display_component_count(rings),
        component_method=COMPONENT_METHOD,
        component_gate_comparable=True,
        area_abs_delta_vs_previous_m2=None,
        area_relative_delta_vs_previous=None,
        area_relative_delta_reference_level=None,
        boundary_sample_count=len(_boundary_samples(rings)),
        boundary_bidirectional_distance_m=None,
        boundary_distance_reference_level=None,
        boundary_distance_method=BOUNDARY_DISTANCE_METHOD,
        new_evaluation_count=diagnostics.new_evaluation_count,
        cache_hit_count=diagnostics.cache_hit_count,
        runtime_s=runtime,
        stop_reason=stop_reason,
        refinement_stop_reason=refinement_stop_reason,
        boundary_stop_reason=boundary_stop_reason,
        region_status=diagnostics.region_status,
        region_diagnostics=diagnostics,
    ), samples


def _link_levels(
    rows: list[ResolutionLevel],
    sample_index: dict[tuple[int, float], tuple[Point2, ...]],
    boundary_sample_limit: int,
) -> list[ResolutionLevel]:
    """Fill the cross-level area deltas and boundary distances.

    Rows are compared inside one eta across consecutive declared levels.  An
    empty boundary sample set yields ``None`` for the distance, never ``0.0``:
    zero would claim that the two boundaries coincide.
    """
    linked: list[ResolutionLevel] = []
    by_eta: dict[float, list[ResolutionLevel]] = {}
    for row in rows:
        by_eta.setdefault(row.eta, []).append(row)
    previous_by_eta: dict[float, ResolutionLevel] = {}
    for eta_value, group in by_eta.items():
        for row in sorted(group, key=lambda item: item.level_index):
            previous = previous_by_eta.get(eta_value)
            if previous is None:
                linked.append(row)
                previous_by_eta[eta_value] = row
                continue
            left = sample_index.get((previous.level_index, eta_value), ())
            right = sample_index.get((row.level_index, eta_value), ())
            distance = boundary_bidirectional_distance_m(
                left, right, subsample_limit=boundary_sample_limit
            )
            linked.append(
                replace(
                    row,
                    area_abs_delta_vs_previous_m2=abs(
                        row.area_estimate_m2 - previous.area_estimate_m2
                    ),
                    area_relative_delta_vs_previous=_relative_delta(
                        row.area_estimate_m2, previous.area_estimate_m2
                    ),
                    area_relative_delta_reference_level=previous.name,
                    boundary_bidirectional_distance_m=distance,
                    boundary_distance_reference_level=(
                        previous.name if distance is not None else None
                    ),
                )
            )
            previous_by_eta[eta_value] = row
    return linked


# ---------------------------------------------------------------------------
# grid-phase perturbation
# ---------------------------------------------------------------------------


def _grid_phase_perturbation(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    specs: tuple[ExtractionLevelSpec, ...],
    eta_values: tuple[float, ...],
    registry: EvaluationRegistry,
    batch: Q2PointBatchExecutor,
    reference: Q2PointResult | None,
    roi: SearchBounds | None,
    mirror_symmetric: bool,
    phase_fractions: tuple[float, ...],
    phase_probe_level: str | None,
    level_rows: list[ResolutionLevel],
) -> GridPhasePerturbation:
    if reference is None or roi is None or not phase_fractions:
        return GridPhasePerturbation(
            applied=False,
            level_name=None,
            eta=eta_values[0],
            phase_fractions=tuple(phase_fractions),
            base_cell_size_m=None,
            roi=None,
            samples=(),
            max_area_relative_deviation=None,
            component_counts=(),
            notes=(
                "grid-phase perturbation requires one shared Hero and one shared ROI; "
                "it was not applied in this mode",
            ),
        )
    spec = specs[-1]
    if phase_probe_level is not None:
        spec = next(item for item in specs if item.name == phase_probe_level)
    resolution = spec.candidate_region_config.base_resolution
    cell_x = roi.width / (resolution - 1)
    cell_y = roi.height / (resolution - 1)
    samples: list[GridPhaseSample] = []
    zero_area_by_eta: dict[float, float] = {}
    zero_components_by_eta: dict[float, int] = {}
    probe_rows = {
        row.eta: row
        for row in level_rows
        if row.name == spec.name and row.outer_config_used is False
    }
    for phase in (0.0,) + tuple(phase_fractions):
        if phase == 0.0 and probe_rows:
            # The frozen ROI *is* this level's bounds in shared mode, so the
            # already-computed row is the zero-phase reference; re-running it
            # would spend budget without adding information.
            for eta_value in eta_values:
                row = probe_rows.get(eta_value)
                if row is None:
                    continue
                zero_area_by_eta[eta_value] = row.area_estimate_m2
                zero_components_by_eta[eta_value] = row.component_count
                samples.append(
                    GridPhaseSample(
                        phase_fraction=0.0,
                        lattice_shift_m=(0.0, 0.0),
                        q_reference_m=row.q_reference_m,
                        threshold=row.threshold,
                        area_estimate_m2=row.area_estimate_m2,
                        raw_area_estimate_m2=row.area_estimate_m2,
                        component_count=row.component_count,
                        accepted_sample_count=row.accepted_sample_count,
                        sampled_inside_cell_count=row.sampled_inside_cell_count,
                        mixed_cell_count=row.mixed_cell_count,
                        area_relative_delta_vs_zero_phase=0.0,
                        component_delta_vs_zero_phase=0,
                        stop_reason=row.stop_reason,
                        runtime_s=row.runtime_s,
                    )
                )
            continue
        shifted = SearchBounds(
            x_min=roi.x_min + phase * cell_x,
            x_max=roi.x_max + phase * cell_x,
            y_min=roi.y_min + phase * cell_y,
            y_max=roi.y_max + phase * cell_y,
            derivation=(
                "grid_phase_perturbation: the ROI box is translated by a declared "
                "fraction of one base cell so the sampling-lattice origin moves; the "
                "saved geometry is cropped back to the frozen ROI"
            ),
        )
        started = time.perf_counter()
        adaptive = build_adaptive_candidate_regions(
            S1,
            theta1_deg,
            epsilon_deg,
            shifted,
            reference,
            etas=eta_values,
            config=spec.candidate_region_config,
            mirror_hero=Point2(reference.S2.x, -reference.S2.y) if mirror_symmetric else None,
            batch_evaluator=batch.evaluate,
            evaluation_registry=registry,
        )
        runtime = time.perf_counter() - started
        for eta_value in eta_values:
            cropped_area, cropped_cells, cropped_rings = _crop_to_roi(
                adaptive, eta_value, roi
            )
            components = _display_component_count(cropped_rings)
            diagnostics = adaptive.diagnostics[eta_value]
            base_area = zero_area_by_eta.get(eta_value)
            base_components = zero_components_by_eta.get(eta_value)
            samples.append(
                GridPhaseSample(
                    phase_fraction=phase,
                    lattice_shift_m=(phase * cell_x, phase * cell_y),
                    q_reference_m=float(reference.Q),
                    threshold=float(adaptive.thresholds[eta_value]),
                    area_estimate_m2=cropped_area,
                    raw_area_estimate_m2=float(adaptive.approximate_areas_m2[eta_value]),
                    component_count=components,
                    accepted_sample_count=diagnostics.accepted_sample_count,
                    sampled_inside_cell_count=len(cropped_cells),
                    mixed_cell_count=diagnostics.mixed_cell_count,
                    area_relative_delta_vs_zero_phase=(
                        None
                        if base_area is None
                        else _relative_delta(cropped_area, base_area)
                    ),
                    component_delta_vs_zero_phase=(
                        0 if base_components is None else components - base_components
                    ),
                    stop_reason=diagnostics.stop_reason,
                    runtime_s=runtime,
                )
            )
    nonzero = [
        sample.area_relative_delta_vs_zero_phase
        for sample in samples
        if sample.phase_fraction != 0.0
        and sample.area_relative_delta_vs_zero_phase is not None
    ]
    return GridPhasePerturbation(
        applied=True,
        level_name=spec.name,
        eta=eta_values[0],
        phase_fractions=tuple(phase_fractions),
        base_cell_size_m=(cell_x, cell_y),
        roi=(roi.x_min, roi.x_max, roi.y_min, roi.y_max),
        samples=tuple(samples),
        max_area_relative_deviation=max(nonzero, default=None),
        component_counts=tuple(sample.component_count for sample in samples),
        notes=(
            "only the sampling-lattice origin moves; the Hero, the physical input, "
            "q_reference, the thresholds and the frozen ROI box are unchanged",
            "shifted-lattice regions are cropped back to the frozen ROI before any "
            "area or component count is taken",
            "cropping discards the sliver of the ROI that the shifted lattice no "
            "longer covers and keeps shifted cells whose corners fall outside the ROI, "
            "so a phase difference is an upper estimate of the phase sensitivity",
        ),
    )


def _crop_to_roi(
    adaptive, eta: float, roi: SearchBounds
) -> tuple[float, tuple[CandidateCell, ...], tuple[tuple[Point2, ...], ...]]:
    """Crop one saved numerical display without counting its full cells twice.

    ``boundary_polygons`` already contains a rectangle ring for every selected
    inside cell plus the clipped mixed-cell fragments.  The cells returned here
    are only for the legacy inside-cell adjacency diagnostic; they must not be
    added to the polygonal display area a second time.
    """
    cropped: list[CandidateCell] = []
    for cell in adaptive.cells[eta]:
        piece = _intersect_cell(cell, roi)
        if piece is not None:
            cropped.append(piece)
    rings = tuple(
        clipped
        for ring in adaptive.boundary_polygons[eta]
        if len(clipped := _clip_ring_to_rect(ring, roi)) >= 3
    )
    area = math.fsum(ring_area_m2(ring) for ring in rings)
    return area, tuple(cropped), rings


def _intersect_cell(cell: CandidateCell, roi: SearchBounds) -> CandidateCell | None:
    x_min = max(cell.x_min, roi.x_min)
    x_max = min(cell.x_max, roi.x_max)
    y_min = max(cell.y_min, roi.y_min)
    y_max = min(cell.y_max, roi.y_max)
    if x_max - x_min <= 1e-12 or y_max - y_min <= 1e-12:
        return None
    return CandidateCell(x_min, x_max, y_min, y_max, cell.depth)


def _clip_ring_to_rect(
    ring: tuple[Point2, ...], roi: SearchBounds
) -> tuple[Point2, ...]:
    """Sutherland-Hodgman clip of a ring against the axis-aligned ROI box."""
    points = list(ring)
    planes = (
        (lambda point: point.x >= roi.x_min, lambda a, b: _cut_x(a, b, roi.x_min)),
        (lambda point: point.x <= roi.x_max, lambda a, b: _cut_x(a, b, roi.x_max)),
        (lambda point: point.y >= roi.y_min, lambda a, b: _cut_y(a, b, roi.y_min)),
        (lambda point: point.y <= roi.y_max, lambda a, b: _cut_y(a, b, roi.y_max)),
    )
    for inside, cut in planes:
        if not points:
            return ()
        clipped: list[Point2] = []
        previous = points[-1]
        previous_inside = inside(previous)
        for current in points:
            current_inside = inside(current)
            if current_inside:
                if not previous_inside:
                    clipped.append(cut(previous, current))
                clipped.append(current)
            elif previous_inside:
                clipped.append(cut(previous, current))
            previous, previous_inside = current, current_inside
        points = clipped
    return tuple(points)


def _cut_x(a: Point2, b: Point2, x: float) -> Point2:
    if b.x == a.x:
        return Point2(x, a.y)
    ratio = (x - a.x) / (b.x - a.x)
    return Point2(x, a.y + ratio * (b.y - a.y))


def _cut_y(a: Point2, b: Point2, y: float) -> Point2:
    if b.y == a.y:
        return Point2(a.x, y)
    ratio = (y - a.y) / (b.y - a.y)
    return Point2(a.x + ratio * (b.x - a.x), y)


# ---------------------------------------------------------------------------
# cache consistency and convergence verdict
# ---------------------------------------------------------------------------


def _cache_consistency(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    registry: EvaluationRegistry,
    level_rows: list[ResolutionLevel],
    criteria: ResolutionConvergenceCriteria,
) -> CacheConsistencyCheck:
    if criteria.cache_consistency_probe_count == 0:
        return CacheConsistencyCheck(
            checked_count=0,
            tolerance_m=criteria.cache_consistency_tolerance_m,
            max_abs_difference_m=None,
            passed=True,
            rows=(),
        )
    candidates: list[Point2] = []
    for record in registry.records:
        if record.result.Q is not None and math.isfinite(float(record.result.Q)):
            candidates.append(record.result.S2)
        if len(candidates) >= criteria.cache_consistency_probe_count:
            break
    rows: list[dict[str, object]] = []
    max_difference: float | None = None
    passed = True
    for point in candidates:
        record = registry.get(point)
        cached = None if record is None else record.result.Q
        fresh_result = evaluate_q2_point(S1, theta1_deg, point, epsilon_deg)
        fresh = fresh_result.Q
        difference = (
            None
            if cached is None or fresh is None
            else abs(float(cached) - float(fresh))
        )
        if difference is not None:
            max_difference = difference if max_difference is None else max(max_difference, difference)
            if difference > criteria.cache_consistency_tolerance_m:
                passed = False
        rows.append(
            {
                "S2": [point.x, point.y],
                "cached_Q_m": None if cached is None else float(cached),
                "fresh_Q_m": None if fresh is None else float(fresh),
                "abs_difference_m": difference,
            }
        )
    return CacheConsistencyCheck(
        checked_count=len(candidates),
        tolerance_m=criteria.cache_consistency_tolerance_m,
        max_abs_difference_m=max_difference,
        passed=passed,
        rows=tuple(rows),
    )


def _convergence_verdict(
    levels: tuple[ResolutionLevel, ...],
    frozen: FrozenTargetSet,
    phase: GridPhasePerturbation,
    cache_check: CacheConsistencyCheck,
    criteria: ResolutionConvergenceCriteria,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not frozen.shared_hero:
        reasons.append(_LEGACY_WARNING)
    if not frozen.shared_bounds:
        reasons.append(
            "the levels did not share one ROI box, so the areas are not comparable"
        )
    if not frozen.evaluator_fingerprint or frozen.evaluator_fingerprint == "unavailable":
        reasons.append("the Q1/Q2 evaluator source fingerprint could not be computed")
    by_eta: dict[float, list[ResolutionLevel]] = {}
    for level in levels:
        by_eta.setdefault(level.eta, []).append(level)
    for eta_value, rows in sorted(by_eta.items()):
        for row in rows:
            if (
                criteria.require_positive_area_at_every_level
                and row.area_estimate_m2 <= 0.0
            ):
                reasons.append(
                    f"eta={eta_value}: level {row.name!r} reports area "
                    f"{row.area_estimate_m2} m^2 with status {row.region_status!r} and "
                    f"stop reason {row.stop_reason!r}; a 0 -> positive -> 0 area band or "
                    "a budget-starved empty area is not a stable extraction"
                )
        pairs = sorted(rows, key=lambda item: item.level_index)
        for previous, current in zip(pairs, pairs[1:]):
            if previous.area_estimate_m2 > 0.0 and current.area_estimate_m2 > 0.0:
                relative = _relative_delta(
                    current.area_estimate_m2, previous.area_estimate_m2
                )
                if (
                    relative is None
                    or relative > criteria.max_area_relative_delta_between_levels
                ):
                    reasons.append(
                        f"eta={eta_value}: area changes by {relative} between "
                        f"{previous.name!r} and {current.name!r}, above the declared "
                        f"{criteria.max_area_relative_delta_between_levels}"
                    )
            if criteria.require_identical_component_count:
                if not (
                    previous.component_gate_comparable
                    and current.component_gate_comparable
                ):
                    reasons.append(
                        f"eta={eta_value}: component-count gate is not comparable "
                        f"between {previous.name!r} and {current.name!r}; at least "
                        "one numerical display area includes boundary fragments or "
                        "unresolved cells that are excluded from the inside-cell "
                        "adjacency count"
                    )
                elif previous.component_count != current.component_count:
                    reasons.append(
                        f"eta={eta_value}: component count differs between "
                        f"{previous.name!r} ({previous.component_count}) and "
                        f"{current.name!r} ({current.component_count})"
                    )
            distance = current.boundary_bidirectional_distance_m
            target = max(
                previous.target_boundary_resolution_m,
                current.target_boundary_resolution_m,
            )
            if previous.boundary_sample_count == 0 or current.boundary_sample_count == 0:
                if previous.boundary_sample_count != current.boundary_sample_count:
                    reasons.append(
                        f"eta={eta_value}: one side of the boundary comparison between "
                        f"{previous.name!r} and {current.name!r} has no saved boundary "
                        "samples, so no distance can be reported"
                    )
                continue
            if distance is None or distance > (
                criteria.max_boundary_bidirectional_distance_over_target * target
            ):
                reasons.append(
                    f"eta={eta_value}: boundary bidirectional distance {distance} m "
                    f"between {previous.name!r} and {current.name!r} exceeds the declared "
                    f"{criteria.max_boundary_bidirectional_distance_over_target} x "
                    f"{target} m"
                )
    if phase.applied:
        deviation = phase.max_area_relative_deviation
        if deviation is None or deviation > criteria.max_phase_area_relative_deviation:
            reasons.append(
                f"grid-phase perturbation of level {phase.level_name!r} changes the area "
                f"by {deviation}, above the declared "
                f"{criteria.max_phase_area_relative_deviation}"
            )
    else:
        reasons.append("the grid-phase perturbation check was not applied")
    if not cache_check.passed:
        reasons.append(
            "a cached evaluation disagreed with a direct re-evaluation beyond "
            f"{cache_check.tolerance_m} m"
        )
    return (not reasons), tuple(reasons)


# ---------------------------------------------------------------------------
# geometry helpers (kept for the region-convergence regression tests)
# ---------------------------------------------------------------------------


def evaluator_source_fingerprint(
    repo_root: Path | None = None,
) -> tuple[str, int, tuple[tuple[str, str], ...]]:
    """SHA-256 over the Q1/Q2 evaluator sources, grouped by root."""
    root = repo_root if repo_root is not None else _default_repo_root()
    if root is None:
        return ("unavailable", 0, ())
    digest = hashlib.sha256()
    per_root: list[tuple[str, str]] = []
    count = 0
    for relative in EVALUATOR_FINGERPRINT_ROOTS:
        base = root / relative
        if not base.is_dir():
            continue
        root_digest = hashlib.sha256()
        entries: list[tuple[str, str]] = []
        for path in sorted(base.rglob(f"*{EVALUATOR_FINGERPRINT_SUFFIX}")):
            parts = set(path.relative_to(root).parts)
            if parts & set(EVALUATOR_FINGERPRINT_SKIP_PARTS):
                continue
            payload = path.read_bytes()
            file_digest = hashlib.sha256(payload).hexdigest()
            entries.append((path.relative_to(root).as_posix(), file_digest))
            root_digest.update(f"{file_digest}  {path.relative_to(root).as_posix()}\n".encode("utf-8"))
            digest.update(f"{file_digest}  {path.relative_to(root).as_posix()}\n".encode("utf-8"))
            count += 1
        per_root.append((relative, root_digest.hexdigest()))
    if count == 0:
        return ("unavailable", 0, tuple(per_root))
    return (digest.hexdigest(), count, tuple(per_root))


def _default_repo_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[4]
    if (candidate / "src" / "q2" / "code").is_dir() and (
        candidate / "src" / "q1" / "code"
    ).is_dir():
        return candidate
    return None


def _boundary_samples(
    polygons: tuple[tuple[Point2, ...], ...],
) -> tuple[Point2, ...]:
    """Sorted unique vertices of the saved numerical boundary polygons."""
    seen: dict[tuple[float, float], Point2] = {}
    for ring in polygons:
        for point in ring:
            seen[(round(point.x, 6), round(point.y, 6))] = point
    return tuple(seen[key] for key in sorted(seen))


def _subsample(points: tuple[Point2, ...], limit: int) -> tuple[Point2, ...]:
    if len(points) <= limit:
        return points
    stride = len(points) / limit
    return tuple(points[int(index * stride)] for index in range(limit))


def _sampled_hausdorff(left: tuple[Point2, ...], right: tuple[Point2, ...]) -> float:
    if not left or not right:
        return math.inf
    return max(min(point.distance_to(other) for other in right) for point in left)


def boundary_bidirectional_distance_m(
    left: tuple[Point2, ...],
    right: tuple[Point2, ...],
    *,
    subsample_limit: int = 400,
) -> float | None:
    """Sampled bidirectional distance; ``None`` when either side is empty.

    An empty boundary set must never be reported as a zero distance: zero would
    claim the two boundaries coincide.
    """
    if not left or not right:
        return None
    left_sample = _subsample(tuple(sorted(left, key=lambda p: (p.x, p.y))), subsample_limit)
    right_sample = _subsample(tuple(sorted(right, key=lambda p: (p.x, p.y))), subsample_limit)
    return max(
        _sampled_hausdorff(left_sample, right_sample),
        _sampled_hausdorff(right_sample, left_sample),
    )


def _component_count(cells: tuple[CandidateCell, ...]) -> int:
    """Edge-adjacency components of the selected leaf cells."""
    if not cells:
        return 0
    index = {cell: position for position, cell in enumerate(cells)}
    by_x_min: dict[float, list[CandidateCell]] = {}
    by_y_min: dict[float, list[CandidateCell]] = {}
    for cell in cells:
        by_x_min.setdefault(round(cell.x_min, 9), []).append(cell)
        by_y_min.setdefault(round(cell.y_min, 9), []).append(cell)

    parent = list(range(len(cells)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(first: int, second: int) -> None:
        root_first, root_second = find(first), find(second)
        if root_first != root_second:
            parent[root_second] = root_first

    for cell in cells:
        position = index[cell]
        for neighbour in by_x_min.get(round(cell.x_max, 9), ()):
            if min(cell.y_max, neighbour.y_max) - max(cell.y_min, neighbour.y_min) > 1e-9:
                union(position, index[neighbour])
        for neighbour in by_y_min.get(round(cell.y_max, 9), ()):
            if min(cell.x_max, neighbour.x_max) - max(cell.x_min, neighbour.x_min) > 1e-9:
                union(position, index[neighbour])
    return len({find(position) for position in range(len(cells))})


def _display_component_count(rings: tuple[tuple[Point2, ...], ...]) -> int:
    """Count numerical-display components without joining at a lone corner.

    The candidate-area estimate is the union of the saved polygon rings, not
    merely the complete inside cells.  Two rings are connected when their
    filled interiors overlap or they share a boundary segment of positive
    length.  A single-point touch deliberately remains split, matching the
    existing edge-adjacency convention for rectangular cells.
    """
    if not rings:
        return 0
    parent = list(range(len(rings)))
    bounds = tuple(_ring_bounds(ring) for ring in rings)

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(first: int, second: int) -> None:
        root_first = find(first)
        root_second = find(second)
        if root_first != root_second:
            parent[root_second] = root_first

    for first, ring in enumerate(rings):
        for second in range(first + 1, len(rings)):
            if not _bounds_overlap(bounds[first], bounds[second]):
                continue
            if _display_polygons_join(ring, rings[second]):
                union(first, second)
    return len({find(position) for position in range(len(rings))})


def _ring_bounds(ring: tuple[Point2, ...]) -> tuple[float, float, float, float]:
    return (
        min(point.x for point in ring),
        max(point.x for point in ring),
        min(point.y for point in ring),
        max(point.y for point in ring),
    )


def _bounds_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    tolerance: float = 1e-9,
) -> bool:
    return not (
        first[1] < second[0] - tolerance
        or second[1] < first[0] - tolerance
        or first[3] < second[2] - tolerance
        or second[3] < first[2] - tolerance
    )


def _display_polygons_join(
    first: tuple[Point2, ...], second: tuple[Point2, ...]
) -> bool:
    if any(_strictly_inside_polygon(point, second) for point in first):
        return True
    if any(_strictly_inside_polygon(point, first) for point in second):
        return True
    first_edges = _ring_edges(first)
    second_edges = _ring_edges(second)
    return any(
        _segments_properly_cross(left_start, left_end, right_start, right_end)
        or _collinear_overlap_has_positive_length(
            left_start, left_end, right_start, right_end
        )
        for left_start, left_end in first_edges
        for right_start, right_end in second_edges
    )


def _ring_edges(ring: tuple[Point2, ...]) -> tuple[tuple[Point2, Point2], ...]:
    if len(ring) < 2:
        return ()
    return tuple(zip(ring, ring[1:] + ring[:1], strict=True))


def _strictly_inside_polygon(point: Point2, ring: tuple[Point2, ...]) -> bool:
    """Strict ray-cast containment; boundary-only contact does not connect."""
    inside = False
    for start, end in _ring_edges(ring):
        if _point_on_segment(point, start, end):
            return False
        if (start.y > point.y) == (end.y > point.y):
            continue
        crossing_x = start.x + (point.y - start.y) * (end.x - start.x) / (end.y - start.y)
        if crossing_x > point.x:
            inside = not inside
    return inside


def _point_on_segment(point: Point2, start: Point2, end: Point2) -> bool:
    tolerance = 1e-9
    return (
        abs(_cross(start, end, point)) <= tolerance
        and min(start.x, end.x) - tolerance <= point.x <= max(start.x, end.x) + tolerance
        and min(start.y, end.y) - tolerance <= point.y <= max(start.y, end.y) + tolerance
    )


def _segments_properly_cross(
    first_start: Point2,
    first_end: Point2,
    second_start: Point2,
    second_end: Point2,
) -> bool:
    tolerance = 1e-9
    first_a = _cross(first_start, first_end, second_start)
    first_b = _cross(first_start, first_end, second_end)
    second_a = _cross(second_start, second_end, first_start)
    second_b = _cross(second_start, second_end, first_end)
    return (
        (first_a > tolerance and first_b < -tolerance)
        or (first_a < -tolerance and first_b > tolerance)
    ) and (
        (second_a > tolerance and second_b < -tolerance)
        or (second_a < -tolerance and second_b > tolerance)
    )


def _collinear_overlap_has_positive_length(
    first_start: Point2,
    first_end: Point2,
    second_start: Point2,
    second_end: Point2,
) -> bool:
    tolerance = 1e-9
    if (
        abs(_cross(first_start, first_end, second_start)) > tolerance
        or abs(_cross(first_start, first_end, second_end)) > tolerance
    ):
        return False
    dx = abs(first_end.x - first_start.x)
    dy = abs(first_end.y - first_start.y)
    if dx >= dy:
        overlap = min(max(first_start.x, first_end.x), max(second_start.x, second_end.x)) - max(
            min(first_start.x, first_end.x), min(second_start.x, second_end.x)
        )
    else:
        overlap = min(max(first_start.y, first_end.y), max(second_start.y, second_end.y)) - max(
            min(first_start.y, first_end.y), min(second_start.y, second_end.y)
        )
    return overlap > tolerance


def _cross(origin: Point2, first: Point2, second: Point2) -> float:
    return (first.x - origin.x) * (second.y - origin.y) - (
        first.y - origin.y
    ) * (second.x - origin.x)


def _component_gate_is_comparable(
    *,
    area_bearing_ring_count: int,
    unresolved_cell_count: int,
) -> bool:
    """Whether inside-cell adjacency represents the saved display geometry.

    Boundary rings add positive display area but are deliberately excluded from
    :func:`_component_count`; unresolved cells make that omission unknown as
    well.  In either situation, comparing raw inside-cell component counts
    would mistake a bookkeeping artifact for a topology observation.
    """
    return area_bearing_ring_count == 0 and unresolved_cell_count == 0


def _relative_delta(current: float, previous: float) -> float | None:
    if previous == 0.0:
        return 0.0 if current == 0.0 else math.inf
    return abs(current - previous) / abs(previous)
