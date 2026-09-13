"""Gate G evidence packaging for the deterministic, non-certified Q2 study."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import time
from typing import Any

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.primitives import BoundaryPoint, CircularArc, LineSegment, Point2
from src.q2.code.solver.outer_search import (
    OuterSearchConfig,
    SearchBounds,
    _local_pattern_refinement,
    derive_search_bounds,
    search_outer,
)
from src.q2.code.geometry.crec import build_crec
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point
from src.q2.code.solver.candidate_regions import (
    AdaptiveCandidateResult,
    CandidateCell,
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.batch import Q2PointBatchExecutor
from src.q2.code.solver.incumbent import (
    BestKnownIncumbent,
    EvaluationRegistry,
    best_valid_result,
    is_valid_incumbent_result,
    result_key as incumbent_result_key,
    update_incumbent,
)


CERTIFIED_GLOBAL_OPTIMUM = False
FIGURE_NAMES = (
    "q2_geometry_overview",
    "q2_crec",
    "q2_angular_image",
    "q2_q_surface",
    "q2_optimum_and_candidate_region",
    "q2_baseline_comparison",
    "q2_worst_case_intersection",
)
ETAS = (0.01, 0.02, 0.05, 0.10)


class HeroClosureDidNotConverge(RuntimeError):
    """Raised when adaptive evidence keeps finding better evaluated points."""


@dataclass(frozen=True)
class GateGConfig:
    outer_config: OuterSearchConfig = OuterSearchConfig()
    surface_resolution: int = 11
    figure_dpi: int = 120
    candidate_region_config: CandidateRegionConfig = CandidateRegionConfig()
    evidence_config_id: str = "q2-final-evidence-v2"
    parallel_workers: int = 1
    hero_promotion_tolerance_m: float = 1e-9
    hero_promotion_min_crec_margin_m: float = 1e-6
    hero_promotion_max_rounds: int = 3
    max_closure_rounds: int | None = None
    closure_seed_points: tuple[Point2, ...] = ()

    def __post_init__(self) -> None:
        if self.surface_resolution < 3:
            raise ValueError("surface_resolution must be at least three.")
        if self.figure_dpi < 50:
            raise ValueError("figure_dpi must be at least 50.")
        if self.parallel_workers < 1:
            raise ValueError("parallel_workers must be at least one.")
        if self.hero_promotion_tolerance_m <= 0.0:
            raise ValueError("hero_promotion_tolerance_m must be positive.")
        if self.hero_promotion_min_crec_margin_m < 0.0:
            raise ValueError("hero_promotion_min_crec_margin_m must be nonnegative.")
        if self.hero_promotion_max_rounds < 1:
            raise ValueError("hero_promotion_max_rounds must be positive.")
        if self.max_closure_rounds is not None and self.max_closure_rounds < 1:
            raise ValueError("max_closure_rounds must be positive when provided.")
        if any(
            not math.isfinite(coordinate)
            for point in self.closure_seed_points
            for coordinate in (point.x, point.y)
        ):
            raise ValueError("closure_seed_points must contain finite coordinates.")

    @property
    def closure_round_limit(self) -> int:
        return self.hero_promotion_max_rounds if self.max_closure_rounds is None else self.max_closure_rounds


@dataclass(frozen=True)
class EvidenceRow:
    method: str
    S2: Point2
    Q: float | None
    crec_feasible: bool
    admissible: bool
    move_distance_m: float
    all_near: bool
    worst_beta_deg: float | None
    runtime_s: float
    verification: str


@dataclass(frozen=True)
class CandidatePoint:
    S2: Point2
    Q: float


@dataclass(frozen=True)
class FigureArtifact:
    name: str
    data_path: Path
    rendered_paths: tuple[Path, Path, Path]


@dataclass(frozen=True)
class GateGEvidence:
    S1: Point2
    theta1_deg: float
    epsilon_deg: float
    bounds: SearchBounds
    rows: tuple[EvidenceRow, ...]
    qhat_star: float
    surface: tuple[Q2PointResult, ...]
    hero_result: Q2PointResult
    candidate_regions: dict[float, tuple[CandidatePoint, ...]]
    evidence_table_path: Path
    candidate_regions_path: Path
    candidate_region_paths: dict[float, Path]
    method_provenance: dict[str, dict[str, Any]]
    method_provenance_path: Path
    figure_artifacts: dict[str, FigureArtifact]
    case_label: str
    claims: str
    certified_global_optimum: bool = CERTIFIED_GLOBAL_OPTIMUM
    candidate_region_cells: dict[float, tuple[CandidateCell, ...]] = field(default_factory=dict)
    candidate_region_thresholds: dict[float, float] = field(default_factory=dict)
    candidate_region_areas_m2: dict[float, float] = field(default_factory=dict)
    refinement_history: tuple[dict[str, object], ...] = ()
    symmetry_check: dict[str, object] = field(default_factory=dict)
    evidence_config_id: str = "q2-final-evidence-v2"
    candidate_region_geojson_paths: dict[float, Path] = field(default_factory=dict)
    figure_data_payload: dict[str, object] = field(default_factory=dict)
    candidate_region_base_resolution: int = 0
    candidate_region_target_resolution_m: float = 0.0
    candidate_region_max_refinement_depth: int = 0
    hero_promotion_history: tuple[dict[str, object], ...] = ()
    all_evaluated_results: tuple[Q2PointResult, ...] = ()
    hero_closure_path: Path | None = None
    hero_closure: dict[str, object] = field(default_factory=dict)


def evaluate_evidence_row(
    method: str,
    S1: Point2,
    theta1_deg: float,
    S2: Point2,
    *,
    runtime_s: float | None = None,
    epsilon_deg: float = 1.0,
    evaluation_registry: EvaluationRegistry | None = None,
) -> EvidenceRow:
    """Evaluate one named method with exactly the frozen Gate E metric."""
    started = time.perf_counter()
    result = evaluate_q2_point(S1, theta1_deg, S2, epsilon_deg)
    elapsed = time.perf_counter() - started if runtime_s is None else runtime_s
    if evaluation_registry is not None:
        evaluation_registry.register(
            result, source="gate_g", stage=f"baseline:{method}"
        )
    return _row_from_result(method, S1, result, elapsed)


def build_gate_g_case(
    S1: Point2,
    theta1_deg: float,
    output_dir: str | Path,
    *,
    config: GateGConfig = GateGConfig(),
    epsilon_deg: float = 1.0,
    render_figures: bool = True,
) -> GateGEvidence:
    """Build one representative, input-specific numerical evidence package."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    a1 = build_a1(FirstObservation(S1, theta1_deg, epsilon_deg))
    bounds = derive_search_bounds(a1, build_crec(a1))

    hero_started = time.perf_counter()
    hero_search = search_outer(S1, theta1_deg, epsilon_deg, config=config.outer_config)
    hero_runtime = time.perf_counter() - hero_started

    registry = EvaluationRegistry()
    for record in hero_search.evaluated_records:
        registry.register(
            record.result,
            source=record.source,
            stage=record.stage,
        )
    hero_record = registry.get(hero_search.recommended.S2)
    if hero_record is None:
        hero_record = registry.register(
            hero_search.recommended,
            source="outer_search",
            stage="recommended",
        )
    hero: BestKnownIncumbent | None = update_incumbent(
        None,
        hero_search.recommended,
        config.hero_promotion_tolerance_m,
        source=hero_record.source,
        stage=hero_record.stage,
        evaluation_id=hero_record.evaluation_id,
    )
    assert hero is not None
    symmetry_expected = _is_x_axis_symmetric_case(S1, theta1_deg)
    promotion_history: list[dict[str, object]] = []
    closure_rounds: list[dict[str, object]] = []
    adaptive: AdaptiveCandidateResult | None = None
    initial_hero = hero
    closure_pass = False
    for promotion_round in range(config.closure_round_limit):
        hero_before = hero
        mirror_seed = (
            Point2(hero.S2.x, -hero.S2.y)
            if symmetry_expected
            else None
        )
        candidate_batch = Q2PointBatchExecutor(
            S1, theta1_deg, epsilon_deg, workers=config.parallel_workers
        )
        try:
            adaptive = build_adaptive_candidate_regions(
                S1,
                theta1_deg,
                epsilon_deg,
                bounds,
                hero.result,
                etas=ETAS,
                config=config.candidate_region_config,
                # Closure discovery is deliberately independent of the
                # mirror-paired production refinement.  This probe must be
                # able to expose an asymmetric, better sampled point; the
                # final candidate regions are rebuilt with mirror pairing
                # after the incumbent closes.
                extra_seeds=config.closure_seed_points,
                batch_evaluator=candidate_batch.evaluate,
                mirror_hero=None,
                evaluation_registry=registry,
            )
        finally:
            candidate_batch.close()
        evidence_best = best_valid_result(adaptive.all_evaluated_results)
        if evidence_best is None:
            raise RuntimeError("The Gate G evidence grid contains no valid point.")
        if (
            hero.Q is None
            or evidence_best.Q is None
            or evidence_best.Q >= hero.Q - config.hero_promotion_tolerance_m
        ):
            closure_rounds.append(
                {
                    "round": promotion_round + 1,
                    "hero_before": _incumbent_payload(hero_before),
                    "best_evidence": _result_payload(evidence_best),
                    "promoted": False,
                    "local_refined": None,
                    "hero_after": _incumbent_payload(hero),
                }
            )
            closure_pass = True
            break
        evidence_record = registry.get(evidence_best.S2)
        if evidence_record is None:
            evidence_record = registry.register(
                evidence_best,
                source="adaptive_evidence",
                stage="candidate_region",
            )
        promoted = update_incumbent(
            hero,
            evidence_best,
            config.hero_promotion_tolerance_m,
            source=evidence_record.source,
            stage=evidence_record.stage,
            evaluation_id=evidence_record.evaluation_id,
        )
        assert promoted is not None
        refined = _refine_surface_seed(
            S1,
            theta1_deg,
            epsilon_deg,
            bounds,
            evidence_best,
            config.parallel_workers,
            registry=registry,
        )
        refined_record = registry.get(refined.S2)
        if refined_record is None:
            refined_record = registry.register(
                refined,
                source="adaptive_evidence",
                stage="local_refinement",
            )
        promoted = update_incumbent(
            promoted,
            refined,
            config.hero_promotion_tolerance_m,
            source=refined_record.source,
            stage=refined_record.stage,
            evaluation_id=refined_record.evaluation_id,
        )
        assert promoted is not None
        hero = promoted
        promotion_payload = {
            "round": promotion_round + 1,
            "previous_S2": [hero_before.S2.x, hero_before.S2.y],
            "previous_Q": hero_before.Q,
            "surface_best_S2": [evidence_best.S2.x, evidence_best.S2.y],
            "surface_best_Q": evidence_best.Q,
            "refined_S2": [refined.S2.x, refined.S2.y],
            "refined_Q": refined.Q,
            "refined_crec_margin_m": refined.crec_margin,
            "promoted_S2": [hero.S2.x, hero.S2.y],
            "promoted_Q": hero.Q,
            "min_crec_margin_m": config.hero_promotion_min_crec_margin_m,
        }
        promotion_history.append(promotion_payload)
        closure_rounds.append(
            {
                "round": promotion_round + 1,
                "hero_before": _incumbent_payload(hero_before),
                "best_evidence": _result_payload(evidence_best),
                "promoted": True,
                "local_refined": _result_payload(refined),
                "hero_after": _incumbent_payload(hero),
            }
        )
    else:
        closure_payload = _hero_closure_payload(
            initial_hero,
            closure_rounds,
            hero,
            registry,
            False,
            config.hero_promotion_min_crec_margin_m,
        )
        closure_path = _write_hero_closure(output, closure_payload)
        raise HeroClosureDidNotConverge(
            f"Hero closure did not converge within {config.closure_round_limit} rounds; "
            f"trajectory saved to {closure_path}."
        )

    # Rebuild the persisted production surface with mirror-paired refinement
    # after closure.  The unpaired probe above is only an independent
    # incumbent-discovery oracle; it is not the published symmetric region.
    mirror_seed = (
        Point2(hero.S2.x, -hero.S2.y)
        if symmetry_expected
        else None
    )
    final_batch = Q2PointBatchExecutor(
        S1, theta1_deg, epsilon_deg, workers=config.parallel_workers
    )
    try:
        adaptive = build_adaptive_candidate_regions(
            S1,
            theta1_deg,
            epsilon_deg,
            bounds,
            hero.result,
            etas=ETAS,
            config=config.candidate_region_config,
            extra_seeds=(() if mirror_seed is None else (mirror_seed,)),
            batch_evaluator=final_batch.evaluate,
            mirror_hero=mirror_seed,
            evaluation_registry=registry,
        )
    finally:
        final_batch.close()
    assert adaptive is not None
    surface = adaptive.surface
    valid_surface = tuple(result for result in surface if _is_valid(result))
    if hero.Q is None:
        raise RuntimeError("Promoted Hero must have a finite Q.")
    hero_result = evaluate_q2_point(S1, theta1_deg, hero.S2, epsilon_deg)
    if hero_result != hero.result:
        raise RuntimeError("Independent Hero re-evaluation disagrees with the production result.")
    hero_runtime = time.perf_counter() - hero_started

    b0 = min(
        valid_surface,
        key=lambda result: (
            result.S2.distance_to(_bounds_center(bounds)),
            result.S2.x,
            result.S2.y,
        ),
    ).S2
    b1 = _center_ray_max_min_angle(a1, bounds)
    method_provenance = {"B1": _b1_provenance(a1, bounds)}
    b2 = _right_angle_heuristic(a1, bounds)
    method_points = (("B0", b0), ("B1", b1), ("B2", b2))
    rows = [
        evaluate_evidence_row(
            name,
            S1,
            theta1_deg,
            point,
            evaluation_registry=registry,
        )
        for name, point in method_points
    ]
    rows.append(_row_from_result("Hero", S1, hero_result, hero_runtime))
    if hero_result.Q is None or not math.isfinite(hero_result.Q):
        raise RuntimeError("Hero must supply a finite numerical Qhat for Gate G.")
    qhat = float(hero_result.Q)

    numerical_samples = surface
    candidate_regions = {
        eta: tuple(CandidatePoint(point, value) for point, value in adaptive.regions[eta])
        for eta in ETAS
    }
    symmetry_check = _evaluate_symmetry_check(
        S1,
        theta1_deg,
        epsilon_deg,
        hero_result,
        symmetry_expected,
        registry=registry,
    )
    best_evaluated = best_valid_result(registry.all_results)
    if best_evaluated is None:
        raise RuntimeError("The production run contains no valid evaluated point.")
    if any(
        result.Q is not None
        and result.Q < hero_result.Q - config.hero_promotion_tolerance_m
        for result in registry.all_results
        if _is_valid(result)
    ):
        raise RuntimeError("The production evaluated set still contains a point better than Hero.")
    closure_payload = _hero_closure_payload(
        initial_hero,
        closure_rounds,
        hero,
        registry,
        closure_pass,
        config.hero_promotion_min_crec_margin_m,
    )
    closure_path = _write_hero_closure(output, closure_payload)

    table_path = output / "q2_evidence_table.json"
    table_path.write_text(
        json.dumps(
            {
                "case_label": "representative illustrative case",
                "certified_global_optimum": False,
                "method_provenance": method_provenance,
                "evidence_config_id": config.evidence_config_id,
                "rows": [_row_payload(row) for row in rows],
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    provenance_path = output / "q2_method_provenance.json"
    provenance_path.write_text(
        json.dumps(method_provenance, indent=2, allow_nan=False), encoding="utf-8"
    )
    regions_path = output / "q2_candidate_good_regions.json"
    regions_path.write_text(
        json.dumps(
                {
                    "kind": "numerical_candidate_good_regions_not_proof",
                    "qhat_star": qhat,
                    # Keep the stable source label for downstream readers.  The
                    # promotion loop itself is persisted separately below, so
                    # provenance remains explicit without breaking the Gate G
                    # compact-schema contract.
                    "qhat_star_source": "Hero numerical search",
                    "evidence_config_id": config.evidence_config_id,
                    "hero_promotion_history": promotion_history,
                    "hero_closure": closure_payload,
                    "approximate_areas_m2": {
                        f"{eta:.2f}": adaptive.approximate_areas_m2[eta] for eta in ETAS
                    },
                    "refinement_history": list(adaptive.refinement_history),
                    "regions": {
                    f"{eta:.2f}": [_candidate_payload(point) for point in points]
                    for eta, points in candidate_regions.items()
                },
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    region_paths: dict[float, Path] = {}
    for eta, points in candidate_regions.items():
        path = output / f"q2_candidate_good_eta_{round(100 * eta):02d}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "numerical_candidate_good_region_not_proof",
                    "eta": eta,
                    "qhat_star": qhat,
                    "threshold": adaptive.thresholds[eta],
                    "approximate_area_m2": adaptive.approximate_areas_m2[eta],
                    "resolution": {
                        "base": adaptive.base_resolution,
                        "max_refinement_depth": adaptive.max_refinement_depth,
                        "target_boundary_resolution_m": adaptive.target_boundary_resolution_m,
                    },
                    "refinement_history": list(adaptive.refinement_history),
                    "hero_promotion_history": promotion_history,
                    "hero_closure": closure_payload,
                    "points": [_candidate_payload(point) for point in points],
                },
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        region_paths[eta] = path

    region_geojson_paths = _write_candidate_geojson(
        output,
        candidate_regions,
        adaptive,
        qhat,
        config.evidence_config_id,
        closure_payload,
    )
    _write_evidence_config(output, S1, theta1_deg, epsilon_deg, config)

    figure_artifacts = _write_figure_data_and_render(
        output,
        S1,
        theta1_deg,
        bounds,
        a1,
        build_crec(a1),
        tuple(rows),
        hero_result,
        numerical_samples,
        candidate_regions,
        adaptive,
        symmetry_check,
        tuple(promotion_history),
        closure_payload,
        config.evidence_config_id,
        config.figure_dpi,
        render_figures,
    )
    figure_data_payload = json.loads(
        (output / f"{FIGURE_NAMES[0]}.json").read_text(encoding="utf-8")
    )["data"]
    return GateGEvidence(
        S1=S1,
        theta1_deg=theta1_deg,
        epsilon_deg=epsilon_deg,
        bounds=bounds,
        rows=tuple(rows),
        qhat_star=qhat,
        surface=numerical_samples,
        hero_result=hero_result,
        candidate_regions=candidate_regions,
        evidence_table_path=table_path,
        candidate_regions_path=regions_path,
        candidate_region_paths=region_paths,
        method_provenance=method_provenance,
        method_provenance_path=provenance_path,
        figure_artifacts=figure_artifacts,
        case_label="representative illustrative case",
        claims="Numerical, illustrative, non-certified results for this input only.",
        candidate_region_cells={eta: adaptive.cells[eta] for eta in ETAS},
        candidate_region_thresholds=adaptive.thresholds,
        candidate_region_areas_m2=adaptive.approximate_areas_m2,
        refinement_history=adaptive.refinement_history,
        symmetry_check=symmetry_check,
        evidence_config_id=config.evidence_config_id,
        candidate_region_geojson_paths=region_geojson_paths,
        figure_data_payload=figure_data_payload,
        candidate_region_base_resolution=adaptive.base_resolution,
        candidate_region_target_resolution_m=adaptive.target_boundary_resolution_m,
        candidate_region_max_refinement_depth=adaptive.max_refinement_depth,
        hero_promotion_history=tuple(promotion_history),
        all_evaluated_results=registry.all_results,
        hero_closure_path=closure_path,
        hero_closure=closure_payload,
    )


def _result_payload(result: Q2PointResult) -> dict[str, object]:
    return {
        "S2": [result.S2.x, result.S2.y],
        "Q": _json_number(result.Q),
        "in_crec": result.in_crec,
        "crec_margin": result.crec_margin,
        "admissible": result.admissible,
        "all_near": result.all_near,
        "worst_beta": result.worst_beta,
        "worst_candidate_type": result.worst_candidate_type,
    }


def _incumbent_payload(incumbent: BestKnownIncumbent) -> dict[str, object]:
    payload = _result_payload(incumbent.result)
    payload.update(
        {
            "source": incumbent.source,
            "stage": incumbent.stage,
            "evaluation_id": incumbent.evaluation_id,
        }
    )
    return payload


def _hero_closure_payload(
    initial_hero: BestKnownIncumbent,
    rounds: list[dict[str, object]],
    final_hero: BestKnownIncumbent,
    registry: EvaluationRegistry,
    closure_pass: bool,
    min_crec_margin_m: float,
) -> dict[str, object]:
    best_evaluated = best_valid_result(registry.all_results)
    if best_evaluated is None or best_evaluated.Q is None or final_hero.Q is None:
        raise RuntimeError("Hero closure requires a finite valid evaluated result.")
    return {
        "initial_hero": _incumbent_payload(initial_hero),
        "rounds": rounds,
        "final_hero": _incumbent_payload(final_hero),
        "best_evaluated_q": float(best_evaluated.Q),
        "hero_minus_best_evaluated": float(final_hero.Q) - float(best_evaluated.Q),
        "evaluated_count": len(registry.records),
        "final_crec_margin_m": float(final_hero.result.crec_margin),
        "crec_margin_status": (
            "marginal_but_independently_verified"
            if final_hero.result.crec_margin < min_crec_margin_m
            else "above_configured_minimum"
        ),
        "crec_margin_minimum_m": min_crec_margin_m,
        "closure_pass": closure_pass,
        "certified_global_optimum": False,
    }


def _write_hero_closure(output: Path, payload: dict[str, object]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "q2_hero_closure.json"
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    return path


def _is_x_axis_symmetric_case(S1: Point2, theta1_deg: float) -> bool:
    return S1 == Point2(0.0, 0.0) and math.isclose(theta1_deg % 360.0, 0.0, abs_tol=1e-12)


def _refine_surface_seed(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    bounds: SearchBounds,
    seed: Q2PointResult,
    workers: int,
    *,
    registry: EvaluationRegistry | None = None,
) -> Q2PointResult:
    cache = {seed.S2: seed}
    history: list[Any] = []
    batch = Q2PointBatchExecutor(S1, theta1_deg, epsilon_deg, workers=workers)
    try:
        return _local_pattern_refinement(
            S1,
            theta1_deg,
            epsilon_deg,
            bounds,
            seed,
            cache,
            history,
            batch,
            5.0,
            14,
            "surface_promotion",
            registry=registry,
            registry_source="adaptive_evidence",
        )
    finally:
        batch.close()


def _evaluate_symmetry_check(
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    hero: Q2PointResult,
    expected: bool,
    *,
    registry: EvaluationRegistry | None = None,
) -> dict[str, object]:
    if not expected:
        return {"expected": False, "status": "not_applicable"}
    mirror = Point2(hero.S2.x, -hero.S2.y)
    result = evaluate_q2_point(S1, theta1_deg, mirror, epsilon_deg)
    if registry is not None:
        registry.register(result, source="gate_g", stage="mirror_check")
    if hero.Q is None or result.Q is None:
        raise RuntimeError("Symmetric representative case must have finite Q values.")
    difference = abs(float(hero.Q) - float(result.Q))
    return {
        "expected": True,
        "S2_plus": [hero.S2.x, hero.S2.y],
        "S2_minus": [mirror.x, mirror.y],
        "Q_plus": float(hero.Q),
        "Q_minus": float(result.Q),
        "abs_Q_difference_m": difference,
        "both_crec_feasible": hero.in_crec and result.in_crec,
        "both_admissible": hero.admissible and result.admissible,
        "tolerance_m": 1e-7,
        "passed": (
            hero.in_crec and result.in_crec and hero.admissible and result.admissible
            and difference <= 1e-7
        ),
    }


def _write_candidate_geojson(
    output: Path,
    regions: dict[float, tuple[CandidatePoint, ...]],
    adaptive: AdaptiveCandidateResult,
    qhat: float,
    config_id: str,
    hero_closure: dict[str, object],
) -> dict[float, Path]:
    paths: dict[float, Path] = {}
    for eta, points in regions.items():
        features: list[dict[str, object]] = []
        for point in points:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [point.S2.x, point.S2.y]},
                    "properties": {"Q_m": point.Q, "eta": eta, "kind": "sample"},
                }
            )
        for cell in adaptive.cells[eta]:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [cell.x_min, cell.y_min],
                            [cell.x_max, cell.y_min],
                            [cell.x_max, cell.y_max],
                            [cell.x_min, cell.y_max],
                            [cell.x_min, cell.y_min],
                        ]],
                    },
                    "properties": {
                        "eta": eta,
                        "kind": "inside_cell",
                        "depth": cell.depth,
                        "approximate_area_m2": cell.area,
                    },
                }
            )
        path = output / f"q2_candidate_region_eta_{round(100 * eta):02d}.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "properties": {
                        "kind": "numerical_candidate_good_region_not_proof",
                        "eta": eta,
                        "qhat_star": qhat,
                        "threshold": adaptive.thresholds[eta],
                        "approximate_area_m2": adaptive.approximate_areas_m2[eta],
                        "evidence_config_id": config_id,
                        "hero_closure": hero_closure,
                        "resolution": {
                            "base": adaptive.base_resolution,
                            "max_refinement_depth": adaptive.max_refinement_depth,
                            "target_boundary_resolution_m": adaptive.target_boundary_resolution_m,
                        },
                    },
                    "features": features,
                },
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        paths[eta] = path
    return paths


def _write_evidence_config(
    output: Path,
    S1: Point2,
    theta1_deg: float,
    epsilon_deg: float,
    config: GateGConfig,
) -> None:
    payload = {
        "config_id": config.evidence_config_id,
        "outer_search_config": {
            "coarse_resolution": config.outer_config.coarse_resolution,
            "subdivision_depth": config.outer_config.subdivision_depth,
            "local_iterations": config.outer_config.local_iterations,
            "parallel_workers": config.outer_config.parallel_workers,
        },
        "candidate_region_config": {
            "base_resolution": config.candidate_region_config.base_resolution,
            "max_refinement_depth": config.candidate_region_config.max_refinement_depth,
            "target_boundary_resolution_m": config.candidate_region_config.target_boundary_resolution_m,
            "near_hero_cell_factor": config.candidate_region_config.near_hero_cell_factor,
            "max_refined_cells_per_level": config.candidate_region_config.max_refined_cells_per_level,
        },
        "parallel_workers": config.parallel_workers,
        "hero_promotion": {
            "tolerance_m": config.hero_promotion_tolerance_m,
            "min_crec_margin_m": config.hero_promotion_min_crec_margin_m,
            "max_rounds": config.hero_promotion_max_rounds,
            "max_closure_rounds": config.closure_round_limit,
        },
        "closure_seed_points": [
            [point.x, point.y] for point in config.closure_seed_points
        ],
        "gate_g_surface_config": {
            "legacy_surface_resolution": config.surface_resolution,
            "adaptive_surface": True,
        },
        "figure_dpi": config.figure_dpi,
        "representative_case": {
            "S1": [S1.x, S1.y],
            "theta1_deg": theta1_deg,
            "epsilon_deg": epsilon_deg,
            "case_label": "representative illustrative case",
        },
    }
    (output / "q2_final_evidence_config.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )


def _row_from_result(
    method: str, S1: Point2, result: Q2PointResult, runtime_s: float
) -> EvidenceRow:
    return EvidenceRow(
        method=method,
        S2=result.S2,
        Q=result.Q,
        crec_feasible=result.in_crec,
        admissible=result.admissible,
        move_distance_m=S1.distance_to(result.S2),
        all_near=result.all_near,
        worst_beta_deg=result.worst_beta,
        runtime_s=max(0.0, runtime_s),
        verification="fresh_metric" if _is_valid(result) else "infeasible",
    )


def _center_ray_max_min_angle(a1: Any, bounds: SearchBounds) -> Point2:
    """Return the frozen 5/1500 m center-ray max-min-angle heuristic."""
    provenance = _b1_provenance(a1, bounds)
    return Point2(*provenance["S2"])


def _b1_provenance(a1: Any, bounds: SearchBounds) -> dict[str, Any]:
    rho_a = 5.0
    rho_b = 1500.0
    reception_radius = 1000.0
    length = rho_b - rho_a
    x_star = rho_a + reception_radius**2 / length
    abs_y_star = reception_radius * math.sqrt(
        1.0 - (reception_radius / length) ** 2
    )
    angle = a1.observation.center_angle_rad
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    unclamped = (
        a1.observation.station
        + direction.scaled(x_star)
        + perpendicular.scaled(abs_y_star)
    )
    point = _clamp(unclamped, bounds)
    return {
        "heuristic": "center_ray_max_min_angle",
        "rho_a_m": rho_a,
        "rho_b_m": rho_b,
        "L_m": length,
        "reception_radius_m": reception_radius,
        "x_star_m": x_star,
        "abs_y_star_m": abs_y_star,
        "side": "positive_perpendicular",
        "unclamped_S2": [unclamped.x, unclamped.y],
        "S2": [point.x, point.y],
        "clamp": "componentwise_to_crec_derived_bounds",
    }


def _right_angle_heuristic(a1: Any, bounds: SearchBounds) -> Point2:
    angle = a1.observation.center_angle_rad
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    radial = a1.radial_interval(angle)
    if radial is None:
        return _bounds_center(bounds)
    rho = 0.5 * (radial[0] + radial[1])
    target = a1.observation.station + direction.scaled(rho)
    return _clamp(target + perpendicular.scaled(rho), bounds)


def _grid_points(bounds: SearchBounds, resolution: int) -> tuple[Point2, ...]:
    return tuple(
        Point2(
            bounds.x_min + bounds.width * ix / (resolution - 1),
            bounds.y_min + bounds.height * iy / (resolution - 1),
        )
        for ix in range(resolution)
        for iy in range(resolution)
    )


def _bounds_center(bounds: SearchBounds) -> Point2:
    return Point2(
        0.5 * (bounds.x_min + bounds.x_max),
        0.5 * (bounds.y_min + bounds.y_max),
    )


def _clamp(point: Point2, bounds: SearchBounds) -> Point2:
    return Point2(
        min(bounds.x_max, max(bounds.x_min, point.x)),
        min(bounds.y_max, max(bounds.y_min, point.y)),
    )


def _is_valid(result: Q2PointResult) -> bool:
    return is_valid_incumbent_result(result)


def _result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return incumbent_result_key(result)


def _json_number(value: float | None) -> float | str | None:
    if value is None or math.isfinite(value):
        return value
    return "Infinity" if value > 0.0 else "-Infinity"


def _row_payload(row: EvidenceRow) -> dict[str, Any]:
    return {
        "method": row.method,
        "S2": [row.S2.x, row.S2.y],
        "Q": _json_number(row.Q),
        "Crec_feasible": row.crec_feasible,
        "admissible": row.admissible,
        "move_distance_m": row.move_distance_m,
        "all_near": row.all_near,
        "worst_beta_deg": row.worst_beta_deg,
        "runtime_s": row.runtime_s,
        "verification": row.verification,
    }


def _candidate_payload(point: CandidatePoint) -> dict[str, Any]:
    return {"S2": [point.S2.x, point.S2.y], "Q": point.Q}


def _write_figure_data_and_render(
    output: Path,
    S1: Point2,
    theta1_deg: float,
    bounds: SearchBounds,
    a1: Any,
    crec: Any,
    rows: tuple[EvidenceRow, ...],
    hero: Q2PointResult,
    samples: tuple[Q2PointResult, ...],
    regions: dict[float, tuple[CandidatePoint, ...]],
    adaptive: AdaptiveCandidateResult,
    symmetry_check: dict[str, object],
    hero_promotion_history: tuple[dict[str, object], ...],
    hero_closure: dict[str, object],
    evidence_config_id: str,
    dpi: int,
    render: bool,
) -> dict[str, FigureArtifact]:
    artifacts: dict[str, FigureArtifact] = {}
    common = {
        "S1": [S1.x, S1.y],
        "theta1_deg": theta1_deg,
        "bounds": [bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max],
        "rows": [_row_payload(row) for row in rows],
        "baseline_bar_indices": [
            index for index, row in enumerate(rows) if isinstance(row.Q, (int, float))
        ],
        "baseline_infeasible_indices": [
            index for index, row in enumerate(rows) if not isinstance(row.Q, (int, float))
        ],
        "surface": [
            {
                "S2": [result.S2.x, result.S2.y],
                "Q": _json_number(result.Q),
                "in_crec": result.in_crec,
                "admissible": result.admissible,
            }
            for result in samples
        ],
        "candidate_regions": {
            f"{eta:.2f}": [_candidate_payload(point) for point in points]
            for eta, points in regions.items()
        },
        "expanded_intervals_deg": [
            [math.degrees(interval.start_rad), math.degrees(interval.end_rad)]
            for interval in hero.expanded_theta_intervals.intervals
        ],
        "worst_polygon": [[point.x, point.y] for point in hero.worst_Q1_polygon],
        "geometry": _geometry_payload(a1, crec, hero, symmetry_check),
        "candidate_region_cells": {
            f"{eta:.2f}": [
                {
                    "x_min": cell.x_min,
                    "x_max": cell.x_max,
                    "y_min": cell.y_min,
                    "y_max": cell.y_max,
                    "depth": cell.depth,
                }
                for cell in adaptive.cells[eta]
            ]
            for eta in ETAS
        },
        "candidate_region_thresholds": {
            f"{eta:.2f}": adaptive.thresholds[eta] for eta in ETAS
        },
        "candidate_region_areas_m2": {
            f"{eta:.2f}": adaptive.approximate_areas_m2[eta] for eta in ETAS
        },
        "refinement_history": list(adaptive.refinement_history),
        "hero_promotion_history": list(hero_promotion_history),
        "hero_closure": hero_closure,
        "evidence_config_id": evidence_config_id,
    }
    for name in FIGURE_NAMES:
        data_path = output / f"{name}.json"
        data_path.write_text(
            json.dumps(
                {
                    "figure": name,
                    "metadata": {
                        "equal_axes": True,
                        "units": "m",
                        "baseline_style": "muted",
                        "colormap": "Blues",
                        "case_label": "representative illustrative case",
                        "dpi": dpi,
                        "text_editable": True,
                        "candidate_region_semantics": "numerical sublevel approximation, not proof",
                    },
                    "data": common,
                },
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        paths = tuple(output / f"{name}.{suffix}" for suffix in ("svg", "pdf", "png"))
        artifacts[name] = FigureArtifact(name, data_path, paths)  # type: ignore[arg-type]
    if render:
        render_saved_gate_g_figures(output, dpi=dpi)
    return artifacts


def _geometry_payload(a1: Any, crec: Any, hero: Q2PointResult, symmetry: dict[str, object]) -> dict[str, object]:
    omega = [
        [a1.omega_center.x + a1.omega_radius_m * math.cos(2.0 * math.pi * index / 360.0),
         a1.omega_center.y + a1.omega_radius_m * math.sin(2.0 * math.pi * index / 360.0)]
        for index in range(361)
    ]
    a1_curves = []
    for piece in a1.boundary.pieces:
        a1_curves.append({"label": piece.label.value, "points": _curve_points(piece.curve)})
    crec_curves = []
    for piece in crec.witnesses.pieces:
        crec_curves.append({"label": piece.label.value, "points": _curve_points(piece.curve)})
    return {
        "omega_boundary": omega,
        "a1_fill_polygon": _a1_fill_polygon(a1),
        "a1_boundary": a1_curves,
        "crec_witnesses": crec_curves,
        "hero_S2": [hero.S2.x, hero.S2.y],
        "mirror_S2": symmetry.get("S2_minus"),
        "raw_intervals_deg": [
            [math.degrees(interval.start_rad), math.degrees(interval.end_rad)]
            for interval in hero.raw_theta_intervals.intervals
        ],
        "worst_beta_deg": hero.worst_beta,
        "diameter_witness_pair": (
            [[point.x, point.y] for point in hero.diameter_witness_pair]
            if hero.diameter_witness_pair is not None else []
        ),
        "symmetry": symmetry,
    }


def _a1_fill_polygon(a1: Any) -> list[list[float]]:
    angles = [
        a1.observation.wedge_limits_rad[0]
        + (a1.observation.wedge_limits_rad[1] - a1.observation.wedge_limits_rad[0]) * index / 48.0
        for index in range(49)
    ]
    outer: list[list[float]] = []
    inner: list[list[float]] = []
    for angle in angles:
        radial = a1.radial_interval(angle)
        if radial is None:
            continue
        inner.append([
            a1.observation.station.x + radial[0] * math.cos(angle),
            a1.observation.station.y + radial[0] * math.sin(angle),
        ])
        outer.append([
            a1.observation.station.x + radial[1] * math.cos(angle),
            a1.observation.station.y + radial[1] * math.sin(angle),
        ])
    return outer + list(reversed(inner)) + (outer[:1] if outer else [])


def _curve_points(curve: Any) -> list[list[float]]:
    if isinstance(curve, BoundaryPoint):
        return [[curve.point.x, curve.point.y]]
    if isinstance(curve, LineSegment):
        return [[curve.start.x, curve.start.y], [curve.end.x, curve.end.y]]
    if isinstance(curve, CircularArc):
        count = max(12, int(abs(curve.end_angle_rad - curve.start_angle_rad) * 180.0 / math.pi) + 1)
        return [
            [curve.point_at(index / (count - 1)).x, curve.point_at(index / (count - 1)).y]
            for index in range(count)
        ]
    return []


def render_saved_gate_g_figures(output: str | Path, *, dpi: int = 300) -> None:
    """Render only from persisted JSON sidecars; no solver or optimizer calls."""
    directory = Path(output)
    for name in FIGURE_NAMES:
        sidecar = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        paths = tuple(directory / f"{name}.{suffix}" for suffix in ("svg", "pdf", "png"))
        _render_figure(name, paths, sidecar["data"], dpi)


def _render_figure(
    name: str, paths: tuple[Path, Path, Path], data: dict[str, Any], dpi: int
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["font.size"] = 8
    plt.rcParams["axes.spines.right"] = False
    plt.rcParams["axes.spines.top"] = False
    plt.rcParams["legend.frameon"] = False

    fig, ax = plt.subplots(figsize=(5.4, 4.2), constrained_layout=True)
    rows = data["rows"]
    surface = data["surface"]
    finite = [item for item in surface if isinstance(item["Q"], (int, float))]
    if name == "q2_angular_image":
        intervals = data["expanded_intervals_deg"]
        raw = data.get("geometry", {}).get("raw_intervals_deg", intervals)
        for index, (start, end) in enumerate(raw):
            ax.plot([start, end], [index, index], linewidth=8, color="#B8C7D9", solid_capstyle="butt", label="raw image" if index == 0 else None)
        for index, (start, end) in enumerate(data["expanded_intervals_deg"]):
            ax.plot([start, end], [index, index], linewidth=4, color="#0F4D92", solid_capstyle="butt", label="expanded image" if index == 0 else None)
        theta = data["theta1_deg"] % 360.0
        ax.axvline(theta, color="#272727", linewidth=1.2, label=r"$\hat\theta_1$")
        ax.axvspan(theta - 3.0, theta + 3.0, color="#E9A6A1", alpha=0.35, label="forbidden ±3ε")
        worst = data.get("geometry", {}).get("worst_beta_deg")
        if worst is not None:
            ax.axvline(worst, color="#B64342", linestyle="--", linewidth=1.2, label=r"$\beta^*$")
        ax.set_xlim(0.0, 360.0)
        ax.set_xlabel("bearing [deg]")
        ax.set_ylabel("closed interval component")
        ax.legend(loc="upper right", fontsize=7)
    elif name == "q2_baseline_comparison":
        finite_rows = [(index, row) for index, row in enumerate(rows) if isinstance(row["Q"], (int, float))]
        if finite_rows:
            ax.bar([index for index, _ in finite_rows], [row["Q"] for _, row in finite_rows], color=["#999999" if row["method"] != "Hero" else "#0F4D92" for _, row in finite_rows], width=0.55)
        for index, row in enumerate(rows):
            if not isinstance(row["Q"], (int, float)):
                ax.scatter(index, 0.0, marker="x", s=70, color="#B64342", linewidths=1.8)
                ax.text(index, 0.05, "Infeasible", rotation=90, ha="center", va="bottom", fontsize=7, color="#B64342")
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels([row["method"] for row in rows])
        ax.set_xlabel("method")
        ax.set_ylabel("worst-case diameter Q [m]")
        ax.set_ylim(bottom=-max(1.0, max((row["Q"] for row in rows if isinstance(row["Q"], (int, float))), default=1.0) * 0.05))
    elif name == "q2_worst_case_intersection":
        polygon = data["worst_polygon"]
        if polygon:
            closed = polygon + [polygon[0]]
            ax.fill([p[0] for p in closed], [p[1] for p in closed], color="#99CCEE")
            ax.plot([p[0] for p in closed], [p[1] for p in closed], color="#0F4D92", linewidth=1.2, label="P_Q1")
        _plot_stations(ax, data)
        witness = data.get("geometry", {}).get("diameter_witness_pair", [])
        if witness:
            ax.plot([p[0] for p in witness], [p[1] for p in witness], color="#B64342", linewidth=2.0, marker="o", label="diameter witness")
        ax.legend(loc="best", fontsize=7)
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
    else:
        _plot_main_geometry(ax, name, data, finite, surface)
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
    ax.set_title(name.replace("q2_", "").replace("_", " "))
    if name not in {"q2_angular_image", "q2_baseline_comparison"}:
        ax.set_aspect("equal", adjustable="datalim")
    ax.grid(color="#DDDDDD", linewidth=0.6)
    for path in paths:
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _plot_main_geometry(ax: Any, name: str, data: dict[str, Any], finite: list[dict[str, Any]], surface: list[dict[str, Any]]) -> None:
    geometry = data.get("geometry", {})
    if name == "q2_geometry_overview":
        omega = geometry.get("omega_boundary", [])
        if omega:
            ax.fill([p[0] for p in omega], [p[1] for p in omega], color="#F4F7FA", zorder=0)
            ax.plot([p[0] for p in omega], [p[1] for p in omega], color="#767676", linewidth=1.0, label="Omega")
        a1_fill = geometry.get("a1_fill_polygon", [])
        if len(a1_fill) >= 3:
            ax.fill([p[0] for p in a1_fill], [p[1] for p in a1_fill], color="#F6CFCB", alpha=0.65, label="A1")
        for curve in geometry.get("a1_boundary", []):
            pts = curve["points"]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color="#B64342" if "wedge" in curve["label"] else "#42949E", linewidth=1.3)
        _plot_crec_witnesses(ax, geometry)
        _plot_stations(ax, data)
        ax.legend(loc="best", fontsize=7)
    elif name == "q2_crec":
        inside = [item for item in surface if item["in_crec"]]
        hull = _convex_hull([[item["S2"][0], item["S2"][1]] for item in inside])
        if len(hull) >= 3:
            ax.fill([p[0] for p in hull], [p[1] for p in hull], color="#DDF3DE", alpha=0.45, label="Crec interior")
        for curve in geometry.get("crec_witnesses", []):
            pts = curve["points"]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color="#42949E", linewidth=1.1, alpha=0.85)
        outside = [item for item in surface if not item["in_crec"]]
        if inside:
            ax.scatter([item["S2"][0] for item in inside], [item["S2"][1] for item in inside], color="#AADCA9", s=10, label="Crec interior samples")
        if outside:
            ax.scatter([item["S2"][0] for item in outside], [item["S2"][1] for item in outside], color="#D8D8D8", s=7, label="outside")
        _plot_stations(ax, data)
        ax.legend(loc="best", fontsize=7)
    elif name == "q2_q_surface":
        if len(finite) >= 3:
            try:
                import numpy as np
                from matplotlib.tri import Triangulation
                xs = np.array([item["S2"][0] for item in finite])
                ys = np.array([item["S2"][1] for item in finite])
                qs = np.array([item["Q"] for item in finite])
                ax.tricontourf(Triangulation(xs, ys), qs, levels=14, cmap="Blues", alpha=0.82)
                ax.tricontour(Triangulation(xs, ys), qs, levels=8, colors="#3775BA", linewidths=0.35, alpha=0.6)
            except (ValueError, RuntimeError):
                ax.scatter([item["S2"][0] for item in finite], [item["S2"][1] for item in finite], c=[item["Q"] for item in finite], cmap="Blues", s=10)
        invalid = [item for item in surface if not item["in_crec"] or not item["admissible"]]
        if invalid:
            ax.scatter([item["S2"][0] for item in invalid], [item["S2"][1] for item in invalid], color="#D8D8D8", marker="x", s=7, label="invalid")
        _plot_candidate_cells(ax, data, "0.05", facecolor="none", edgecolor="#B64342", linewidth=0.8)
        _plot_stations(ax, data)
    elif name == "q2_optimum_and_candidate_region":
        _plot_candidate_cells(ax, data, "0.05", facecolor="#AADCA9", edgecolor="#42949E", alpha=0.38, label="5% numerical region")
        for eta, color in (("0.01", "#0F4D92"), ("0.02", "#3775BA"), ("0.10", "#767676")):
            _plot_candidate_cells(ax, data, eta, facecolor="none", edgecolor=color, linewidth=0.8)
        _plot_stations(ax, data)
        ax.legend(loc="best", fontsize=7)
    else:
        if finite:
            ax.scatter([item["S2"][0] for item in finite], [item["S2"][1] for item in finite], color="#BBBBBB", s=8)
        _plot_stations(ax, data)


def _plot_crec_witnesses(ax: Any, geometry: dict[str, Any]) -> None:
    for curve in geometry.get("crec_witnesses", []):
        pts = curve["points"]
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color="#42949E", linewidth=1.0, alpha=0.75, label="Crec witness")


def _plot_candidate_cells(
    ax: Any,
    data: dict[str, Any],
    eta: str,
    *,
    facecolor: str,
    edgecolor: str,
    linewidth: float = 0.7,
    alpha: float = 1.0,
    label: str | None = None,
) -> None:
    cells = data.get("candidate_region_cells", {}).get(eta, [])
    first = True
    for cell in cells:
        xs = [cell["x_min"], cell["x_max"], cell["x_max"], cell["x_min"], cell["x_min"]]
        ys = [cell["y_min"], cell["y_min"], cell["y_max"], cell["y_max"], cell["y_min"]]
        ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha, label=label if first else None)
        first = False


def _convex_hull(points: list[list[float]]) -> list[list[float]]:
    unique = sorted({(float(x), float(y)) for x, y in points})
    if len(unique) <= 1:
        return [[x, y] for x, y in unique]

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return [[x, y] for x, y in lower[:-1] + upper[:-1]]


def _plot_stations(ax: Any, data: dict[str, Any]) -> None:
    s1 = data["S1"]
    ax.scatter([s1[0]], [s1[1]], marker="^", color="#222222", label="S1")
    for row in data["rows"][:-1]:
        ax.scatter(row["S2"][0], row["S2"][1], color="#999999", marker="x")
    hero = data["rows"][-1]
    ax.scatter(hero["S2"][0], hero["S2"][1], color="#4477AA", marker="*", s=100)
    mirror = data.get("geometry", {}).get("mirror_S2")
    if mirror is not None:
        ax.scatter(mirror[0], mirror[1], color="#3775BA", marker="D", s=34, label="symmetric Hero")
