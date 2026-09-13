"""Independent metric and artifact-integrity verifier for Gate G evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from src.q2.code.geometry.a1 import A1BoundaryLabel, FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec, is_in_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point
from .verify_angular import verify_angular_image
from .verify_crec import verify_crec
from .verify_inner import verify_inner
from .verify_q1 import verify_q1_adapter


EXPECTED_METHODS = ("B0", "B1", "B2", "Hero")
EXPECTED_ETAS = (0.01, 0.02, 0.05, 0.10)
EXPECTED_FIGURES = (
    "q2_geometry_overview", "q2_crec", "q2_angular_image", "q2_q_surface",
    "q2_optimum_and_candidate_region", "q2_baseline_comparison",
    "q2_worst_case_intersection",
)
MISSING = object()

# Stable method identities.  These literals are deliberately re-declared here
# instead of imported so the verifier does not trust the builder's lookup; a
# swapped label, constructor, side rule, clamp rule or fingerprint must fail.
METHOD_ID_B0 = "bounds_center_seed"
METHOD_ID_B1 = "right_angle_midpoint"
METHOD_ID_B2 = "center_ray_max_min_angle"
METHOD_ID_HERO = "robust_minimax"

FORMULA_B0 = "argmin_over_valid_surface_samples_of_distance_to_search_bounds_center"
INPUTS_B0 = ("valid_surface_samples", "search_bounds_center")
SIDE_B0 = "none"
CLAMP_B0 = "none_selected_point_is_an_already_evaluated_sample"

FORMULA_B1 = "centre_ray_radial_midpoint_plus_perpendicular_offset_at_equal_radius"
INPUTS_B1 = ("rho_lo_m", "rho_hi_m", "center_angle_rad", "station")
SIDE_B1 = "min_Q_over_symmetric_sides"
CLAMP_B1 = "componentwise_to_crec_derived_bounds"

FORMULA_B2 = "analytic_max_min_angle_closure_on_the_center_ray"
INPUTS_B2 = ("rho_a_m", "rho_b_m", "reception_radius_m", "center_angle_rad", "station")
SIDE_B2 = "positive_perpendicular"
CLAMP_B2 = "componentwise_to_crec_derived_bounds"

FORMULA_HERO = (
    "adaptive_multiscale_surface_search_minimising_robust_Q_with_crec_margin_promotion"
)
INPUTS_HERO = (
    "S1",
    "theta1_deg",
    "epsilon_deg",
    "outer_search_config",
    "candidate_region_config",
    "closure_seed_points",
)
CLAMP_HERO = "candidates_kept_inside_search_bounds_and_crec_by_the_inner_search"

REGION_KIND = "numerical_candidate_good_region_not_proof"
CLASSIFICATION_SAMPLES = "corners_plus_center"
REGION_STATUS_POSITIVE = "positive_area_numerical"
REGION_STATUS_UNRESOLVED = "unresolved_thin_feature"
REGION_STATUS_NO_INSIDE = "no_fully_selected_cells"
ALLOWED_ZERO_AREA_STATUSES = (REGION_STATUS_UNRESOLVED, REGION_STATUS_NO_INSIDE)
AREA_METHOD_POLYGONS = (
    "saved_marching_triangle_fragments_plus_inside_cell_rectangles"
)
AREA_METHOD_NONE = "no_polygonal_area_available"
AGGREGATE_PREVIEW = 16

ACCEPTED_SAMPLES_NOTE = (
    "accepted_samples is the full pointwise-accepted list for this eta; "
    "representative_accepted_samples in the aggregate JSON is a truncated "
    "display of the best entries, not the complete set."
)
BOUNDARY_POLYGON_NOTE = (
    "boundary_fragment geometry is the saved masked clip from the candidate "
    "region extractor: each fragment is one ring, fragments are never merged, "
    "so holes, separate branches and degenerate pieces stay separate.  The "
    "geometry is numerical and is not a set-inclusion certificate."
)


class EvidencePackage(Protocol):
    S1: Point2
    theta1_deg: float
    epsilon_deg: float
    bounds: Any
    rows: tuple
    qhat_star: float
    surface: tuple[Q2PointResult, ...]
    hero_result: Q2PointResult
    candidate_regions: dict
    evidence_table_path: Path
    candidate_regions_path: Path
    candidate_region_paths: dict
    method_provenance: dict
    method_provenance_path: Path
    figure_artifacts: dict
    case_label: str
    certified_global_optimum: bool
    evidence_config_id: str
    figure_data_payload: dict
    candidate_region_cells: dict
    candidate_region_thresholds: dict
    candidate_region_areas_m2: dict
    refinement_history: tuple
    candidate_region_base_resolution: int
    candidate_region_target_resolution_m: float
    candidate_region_max_refinement_depth: int
    hero_promotion_history: tuple
    all_evaluated_results: tuple[Q2PointResult, ...]
    hero_closure_path: Path
    hero_closure: dict
    candidate_region_diagnostics: dict
    candidate_region_accepted_samples: dict
    candidate_region_boundary_polygons: dict


@dataclass(frozen=True)
class GateGVerificationReport:
    passed: bool
    recomputed_rows: int
    checked_candidate_points: int
    checked_figure_files: int
    failures: tuple[str, ...]
    hero_closure_passed: bool = False
    independent_hero_passed: bool = False


def verify_gate_g(evidence: EvidencePackage) -> GateGVerificationReport:
    """Freshly recompute numerical claims and compare every persisted payload."""
    failures: list[str] = []
    if evidence.certified_global_optimum is not False:
        failures.append("Gate G must not claim a global certificate")
    if tuple(row.method for row in evidence.rows) != EXPECTED_METHODS:
        failures.append("headline method schema differs from B0/B1/B2/Hero")

    fresh_rows: list[Q2PointResult] = []
    for row in evidence.rows:
        fresh = evaluate_q2_point(
            evidence.S1, evidence.theta1_deg, row.S2, evidence.epsilon_deg
        )
        fresh_rows.append(fresh)
        if not _row_matches_fresh(row, evidence.S1, fresh):
            failures.append(f"headline row {row.method} disagrees with fresh Q2 evaluation")

    fresh_hero = fresh_rows[-1] if fresh_rows else None
    if (
        fresh_hero is None
        or fresh_hero.Q is None
        or evidence.qhat_star != fresh_hero.Q
        or evidence.hero_result != fresh_hero
    ):
        failures.append("Qhat or stored Hero provenance disagrees with fresh Hero Q")

    hero_closure_passed = _verify_closure_artifact(evidence, fresh_hero, failures)
    independent_hero_passed = _verify_independent_hero(
        evidence, fresh_hero, failures
    )

    expected_regions = _expected_regions(evidence)
    if set(evidence.candidate_regions) != set(EXPECTED_ETAS):
        failures.append("candidate-region eta schema is incomplete")
    elif any(
        tuple((point.S2, point.Q) for point in evidence.candidate_regions[eta])
        != expected_regions[eta]
        for eta in EXPECTED_ETAS
    ):
        failures.append("in-memory candidate regions are empty, incomplete, or threshold-expanded")

    checked_candidates = 0
    fresh_candidates: dict[Point2, Q2PointResult] = {}
    for eta in EXPECTED_ETAS:
        for point in evidence.candidate_regions.get(eta, ()):
            checked_candidates += 1
            if point.S2 not in fresh_candidates:
                fresh_candidates[point.S2] = evaluate_q2_point(
                    evidence.S1, evidence.theta1_deg, point.S2, evidence.epsilon_deg
                )
            fresh = fresh_candidates[point.S2]
            if (
                not _is_valid(fresh)
                or fresh.Q != point.Q
                or float(fresh.Q) > (1.0 + eta) * evidence.qhat_star
            ):
                failures.append(f"candidate point fails fresh eta={eta:.2f} check")

    expected_table = {
        "case_label": evidence.case_label,
        "certified_global_optimum": False,
        "method_provenance": evidence.method_provenance,
        "evidence_config_id": evidence.evidence_config_id,
        "rows": [_row_payload(row) for row in evidence.rows],
    }
    if _read_json(evidence.evidence_table_path) != expected_table:
        failures.append("evidence table payload disagrees with in-memory/fresh rows")

    expected_provenance = _expected_method_provenance(evidence, failures)
    if evidence.method_provenance != expected_provenance:
        failures.append(
            "method identity provenance disagrees with the frozen constructors"
        )
    if _read_json(evidence.method_provenance_path) != expected_provenance:
        failures.append("persisted method identity provenance disagrees with evidence")
    alias_row = {row.method: row for row in evidence.rows}
    for provenance in expected_provenance.values():
        row = alias_row.get(provenance["paper_alias"])
        if row is not None and row.S2 != Point2(*provenance["S2"]):
            failures.append(
                f"{provenance['paper_alias']} row does not use its declared constructor point"
            )
    if len({item["method_id"] for item in expected_provenance.values()}) != len(
        EXPECTED_METHODS
    ):
        failures.append("method identities are not unique under method_id")
    if (
        expected_provenance[METHOD_ID_B1]["formula_or_constructor"]
        == expected_provenance[METHOD_ID_B2]["formula_or_constructor"]
    ):
        failures.append("B1 and B2 share a constructor; labels alone cannot identify them")
    if (
        expected_provenance[METHOD_ID_B1]["source_fingerprint"]
        == expected_provenance[METHOD_ID_B2]["source_fingerprint"]
    ):
        failures.append("B1 and B2 share a source fingerprint")

    scalars_by_eta: dict[float, dict[str, Any]] = {}
    for eta in EXPECTED_ETAS:
        scalars = _expected_region_scalars(evidence, eta, failures)
        if scalars is not None:
            scalars_by_eta[eta] = scalars
    expected_combined = _expected_aggregate_payload(evidence, scalars_by_eta)
    if _read_json(evidence.candidate_regions_path) != expected_combined:
        failures.append("aggregate candidate-region payload disagrees with evidence")

    if set(evidence.candidate_region_paths) != set(EXPECTED_ETAS):
        failures.append("separate candidate-region files are incomplete")
    else:
        for eta in EXPECTED_ETAS:
            scalars = scalars_by_eta.get(eta)
            if scalars is None:
                continue
            expected_eta = _expected_eta_payload(evidence, eta, scalars)
            if _read_json(evidence.candidate_region_paths[eta]) != expected_eta:
                failures.append(f"separate eta={eta:.2f} payload disagrees with evidence")

    if set(evidence.candidate_region_geojson_paths) != set(EXPECTED_ETAS):
        failures.append("candidate-region GeoJSON files are incomplete")
    else:
        for eta in EXPECTED_ETAS:
            scalars = scalars_by_eta.get(eta)
            if scalars is None:
                continue
            expected_geo = _expected_candidate_geojson(evidence, eta, scalars)
            if _read_json(evidence.candidate_region_geojson_paths[eta]) != expected_geo:
                failures.append(
                    f"candidate-region GeoJSON at eta={eta:.2f} disagrees with the "
                    f"saved masked boundary fragments or samples"
                )

    expected_figure_data = _figure_data_payload(evidence)
    checked_files = 0
    if set(evidence.figure_artifacts) != set(EXPECTED_FIGURES):
        failures.append("figure-name schema is incomplete")
    else:
        for name in EXPECTED_FIGURES:
            artifact = evidence.figure_artifacts[name]
            expected_sidecar = {
                "figure": name,
                "metadata": {
                    "equal_axes": True, "units": "m", "baseline_style": "muted",
                    "colormap": "Blues", "case_label": evidence.case_label,
                    "dpi": _figure_dpi(artifact.data_path),
                    "text_editable": True,
                    "candidate_region_semantics": "numerical sublevel approximation, not proof",
                },
                "data": expected_figure_data,
            }
            if _read_json(artifact.data_path) != expected_sidecar:
                failures.append(f"figure sidecar for {name} disagrees with evidence")
            if tuple(path.suffix for path in artifact.rendered_paths) != (".svg", ".pdf", ".png"):
                failures.append(f"rendered format schema for {name} is invalid")
            for path in artifact.rendered_paths:
                checked_files += 1
                if not _valid_rendered_file(path):
                    failures.append(f"missing or invalid rendered figure: {path.name}")

    return GateGVerificationReport(
        passed=not failures,
        recomputed_rows=len(fresh_rows),
        checked_candidate_points=checked_candidates,
        checked_figure_files=checked_files,
        failures=tuple(failures),
        hero_closure_passed=hero_closure_passed,
        independent_hero_passed=independent_hero_passed,
    )


def _verify_closure_artifact(
    evidence: EvidencePackage,
    fresh_hero: Q2PointResult | None,
    failures: list[str],
) -> bool:
    path = getattr(evidence, "hero_closure_path", None)
    expected_payload = getattr(evidence, "hero_closure", {})
    if path is None:
        failures.append("Hero closure artifact is missing")
        return False
    payload = _read_json(path)
    if payload is MISSING or payload != expected_payload:
        failures.append("Hero closure artifact disagrees with in-memory provenance")
        return False
    if payload.get("closure_pass") is not True:
        failures.append("Hero closure artifact does not report PASS")
        return False
    if fresh_hero is None or fresh_hero.Q is None:
        failures.append("Hero closure cannot be checked without a finite fresh Hero")
        return False
    all_results = getattr(evidence, "all_evaluated_results", evidence.surface)
    valid = [result for result in all_results if _is_valid(result)]
    best = min(valid, key=_result_key) if valid else None
    if best is None or best.Q is None:
        failures.append("Hero closure has no valid evaluated result")
        return False
    tolerance = 1e-9
    if float(payload.get("best_evaluated_q", math.inf)) != float(best.Q):
        failures.append("Hero closure best evaluated Q disagrees with the registry")
    if fresh_hero.Q > best.Q + tolerance:
        failures.append("Hero is dominated by a valid evaluated production result")
    if abs(
        float(payload.get("hero_minus_best_evaluated", math.inf))
        - (float(fresh_hero.Q) - float(best.Q))
    ) > tolerance:
        failures.append("Hero closure Q difference is inconsistent with evaluated results")
    final_hero = payload.get("final_hero", {})
    if final_hero.get("S2") != [fresh_hero.S2.x, fresh_hero.S2.y]:
        failures.append("Hero closure final coordinates disagree with fresh Hero")
    return not any(
        message in failures
        for message in (
            "Hero closure artifact is missing",
            "Hero closure artifact disagrees with in-memory provenance",
            "Hero closure artifact does not report PASS",
            "Hero closure cannot be checked without a finite fresh Hero",
            "Hero closure has no valid evaluated result",
            "Hero is dominated by a valid evaluated production result",
            "Hero closure best evaluated Q disagrees with the registry",
            "Hero closure Q difference is inconsistent with evaluated results",
            "Hero closure final coordinates disagree with fresh Hero",
        )
    )


def _verify_independent_hero(
    evidence: EvidencePackage,
    hero: Q2PointResult | None,
    failures: list[str],
) -> bool:
    if hero is None:
        failures.append("Independent Hero verification has no Hero result")
        return False
    try:
        a1 = build_a1(
            FirstObservation(evidence.S1, evidence.theta1_deg, evidence.epsilon_deg)
        )
        crec = build_crec(a1)
        crec_eval = is_in_crec(crec, hero.S2)
        crec_report = verify_crec(
            a1,
            hero.S2,
            analytic_max_violation_m=-hero.crec_margin,
            analytic_in_crec=hero.in_crec,
            angle_samples=361,
            radial_samples=129,
        )
        if (
            not crec_report.passed
            or crec_eval.in_crec != hero.in_crec
            or not math.isclose(crec_eval.margin_m, hero.crec_margin, abs_tol=2e-6)
        ):
            failures.append("Independent Crec verification failed for Hero")
            return False

        angular_report = verify_angular_image(
            a1,
            hero.S2,
            hero.raw_theta_intervals,
            hero.expanded_theta_intervals,
            hero.all_near,
            boundary_samples_per_piece=31,
            radial_angle_samples=61,
            radial_samples_per_angle=15,
        )
        if not angular_report.passed:
            failures.append("Independent angular verification failed for Hero")
            return False

        if _is_valid(hero) and not hero.all_near:
            if hero.Q is None or hero.worst_beta is None:
                failures.append("Independent inner verification lacks Hero witnesses")
                return False
            inner_candidate = SimpleNamespace(
                Q=hero.Q,
                worst_beta_deg=hero.worst_beta,
            )
            inner_report = verify_inner(
                evidence.S1,
                evidence.theta1_deg,
                hero.S2,
                hero.expanded_theta_intervals,
                inner_candidate,
                evidence.epsilon_deg,
                samples_per_component=257,
            )
            q1_candidate = evaluate_q1(
                evidence.S1,
                evidence.theta1_deg,
                hero.S2,
                hero.worst_beta,
                evidence.epsilon_deg,
            )
            q1_report = verify_q1_adapter(
                evidence.S1,
                evidence.theta1_deg,
                hero.S2,
                hero.worst_beta,
                evidence.epsilon_deg,
                q1_candidate,
            )
            if not inner_report.passed or not q1_report.passed:
                failures.append("Independent Q1/inner verification failed for Hero")
                return False
        return True
    except (ArithmeticError, RuntimeError, ValueError, TypeError) as error:
        failures.append(f"Independent Hero verification raised {type(error).__name__}: {error}")
        return False


def _row_matches_fresh(row: Any, S1: Point2, fresh: Q2PointResult) -> bool:
    return (
        row.S2 == fresh.S2 and row.Q == fresh.Q
        and row.crec_feasible == fresh.in_crec
        and row.admissible == fresh.admissible
        and row.move_distance_m == S1.distance_to(fresh.S2)
        and row.all_near == fresh.all_near
        and row.worst_beta_deg == fresh.worst_beta
        and math.isfinite(row.runtime_s) and row.runtime_s >= 0.0
        and row.verification == ("fresh_metric" if _is_valid(fresh) else "infeasible")
    )


def _expected_regions(evidence: EvidencePackage) -> dict[float, tuple[tuple[Point2, float], ...]]:
    samples = {result.S2: result for result in evidence.surface}
    samples[evidence.hero_result.S2] = evidence.hero_result
    ordered = sorted(samples.values(), key=_result_key)
    return {
        eta: tuple(
            (result.S2, float(result.Q))
            for result in ordered
            if _is_valid(result) and float(result.Q) <= (1.0 + eta) * evidence.qhat_star
        )
        for eta in EXPECTED_ETAS
    }


def _metric_valid(result: Q2PointResult) -> bool:
    """The production incumbent-validity predicate, re-implemented locally."""
    return (
        result.in_crec
        and (result.admissible or result.all_near)
        and result.Q is not None
        and math.isfinite(float(result.Q))
    )


def _region_good(result: Q2PointResult, threshold: float) -> bool:
    return _metric_valid(result) and float(result.Q) <= threshold


def _ring_area(ring: tuple) -> float:
    """Absolute shoelace area of one saved ring (same arithmetic order)."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for index in range(len(ring)):
        current = ring[index]
        following = ring[(index + 1) % len(ring)]
        total += current.x * following.y - following.x * current.y
    return abs(total) / 2.0


def _method_source_fingerprint(descriptor: dict[str, Any]) -> str:
    canonical = json.dumps(
        descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _method_identity(
    method_id: str,
    paper_alias: str,
    formula_or_constructor: str,
    inputs: tuple[str, ...],
    side_selection: str,
    clamp_or_projection_policy: str,
) -> dict[str, Any]:
    descriptor = {
        "method_id": method_id,
        "formula_or_constructor": formula_or_constructor,
        "inputs": list(inputs),
        "side_selection": side_selection,
        "clamp_or_projection_policy": clamp_or_projection_policy,
    }
    payload: dict[str, Any] = dict(descriptor)
    payload["paper_alias"] = paper_alias
    payload["source_fingerprint"] = _method_source_fingerprint(descriptor)
    return payload


def _attach_fresh_metrics(
    provenance: dict[str, Any], result: Q2PointResult
) -> dict[str, Any]:
    provenance["S2"] = [result.S2.x, result.S2.y]
    provenance["fresh_Q"] = _json_number(result.Q)
    provenance["validity"] = bool(_metric_valid(result))
    provenance["margin"] = _json_number(result.crec_margin)
    return provenance


def _expected_method_provenance(
    evidence: EvidencePackage, failures: list[str]
) -> dict[str, dict[str, Any]]:
    """Reconstruct every headline method identity from its own constructor."""
    provenance: dict[str, dict[str, Any]] = {}
    try:
        provenance[METHOD_ID_B0] = _expected_b0_provenance(evidence)
        provenance[METHOD_ID_B1] = _expected_b1_provenance(evidence)
        provenance[METHOD_ID_B2] = _expected_b2_provenance(evidence)
        hero = evaluate_q2_point(
            evidence.S1,
            evidence.theta1_deg,
            evidence.hero_result.S2,
            evidence.epsilon_deg,
        )
        provenance[METHOD_ID_HERO] = _expected_hero_provenance(evidence, hero)
    except (ArithmeticError, ValueError, TypeError) as error:
        failures.append(
            f"method identity reconstruction failed: {type(error).__name__}: {error}"
        )
    return provenance


def _expected_b0_provenance(evidence: EvidencePackage) -> dict[str, Any]:
    center = _bounds_center(evidence.bounds)
    valid = [result for result in evidence.surface if _metric_valid(result)]
    if not valid:
        raise ValueError("surface has no valid sample for the B0 constructor")
    chosen = min(
        valid,
        key=lambda result: (
            result.S2.distance_to(center),
            result.S2.x,
            result.S2.y,
        ),
    )
    fresh = evaluate_q2_point(
        evidence.S1, evidence.theta1_deg, chosen.S2, evidence.epsilon_deg
    )
    provenance = _method_identity(
        METHOD_ID_B0, "B0", FORMULA_B0, INPUTS_B0, SIDE_B0, CLAMP_B0
    )
    provenance["selection_rule"] = (
        "min_distance_to_bounds_center_then_lexicographic_x_then_y"
    )
    provenance["bounds_center_m"] = [center.x, center.y]
    return _attach_fresh_metrics(provenance, fresh)


def _expected_hero_provenance(
    evidence: EvidencePackage, fresh: Q2PointResult
) -> dict[str, Any]:
    symmetry = _is_x_axis_symmetric_case(evidence.S1, evidence.theta1_deg)
    provenance = _method_identity(
        METHOD_ID_HERO,
        "Hero",
        FORMULA_HERO,
        INPUTS_HERO,
        (
            "mirror_paired_symmetric_sides"
            if symmetry
            else "unrestricted_over_search_bounds"
        ),
        CLAMP_HERO,
    )
    provenance["worst_beta_deg"] = fresh.worst_beta
    provenance["all_near"] = fresh.all_near
    provenance["certified_global_optimum"] = False
    return _attach_fresh_metrics(provenance, fresh)


def _is_x_axis_symmetric_case(S1: Point2, theta1_deg: float) -> bool:
    return S1 == Point2(0.0, 0.0) and math.isclose(
        theta1_deg % 360.0, 0.0, abs_tol=1e-12
    )


def _expected_region_scalars(
    evidence: EvidencePackage, eta: float, failures: list[str]
) -> dict[str, Any] | None:
    """Independently recompute the persisted per-eta scalar block."""
    threshold = (1.0 + eta) * evidence.qhat_star
    stored_threshold = float(evidence.candidate_region_thresholds[eta])
    if stored_threshold != threshold:
        failures.append(
            f"eta={eta:.2f} threshold is not (1+eta)*qhat_star"
        )
    accepted_count = sum(
        1 for result in evidence.surface if _region_good(result, threshold)
    )
    hero_good = _region_good(evidence.hero_result, threshold)
    cells = evidence.candidate_region_cells[eta]
    saved_polygons = tuple(
        getattr(evidence, "candidate_region_boundary_polygons", {}).get(eta, ())
    )
    # ``boundary_polygons`` is the ordered saved list (inside-cell rings first,
    # clipped fragments after); it is already the exact area source.
    area = math.fsum(_ring_area(ring) for ring in saved_polygons)
    fragment_count = max(0, len(saved_polygons) - len(cells))
    stored_area = float(evidence.candidate_region_areas_m2[eta])
    if stored_area != area:
        failures.append(
            f"eta={eta:.2f} area estimate is not the saved masked geometry area"
        )
    if len(evidence.candidate_regions[eta]) != accepted_count:
        failures.append(
            f"eta={eta:.2f} in-memory candidate samples disagree with the fresh accepted count"
        )
    if hero_good and accepted_count == 0:
        failures.append(
            f"eta={eta:.2f} cleared accepted_samples although Hero is inside threshold"
        )

    diagnostics = getattr(evidence, "candidate_region_diagnostics", {}).get(eta)
    if diagnostics is None:
        failures.append(f"eta={eta:.2f} extraction diagnostics are missing")
        return None
    if diagnostics.accepted_sample_count != accepted_count:
        failures.append(
            f"eta={eta:.2f} accepted_sample_count disagrees with the fresh pointwise count"
        )
    if bool(diagnostics.hero_is_in_accepted_samples) != hero_good:
        failures.append(
            f"eta={eta:.2f} hero_is_in_accepted_samples disagrees with fresh recomputation"
        )
    if float(diagnostics.area_estimate_m2) != area:
        failures.append(
            f"eta={eta:.2f} diagnostics area disagrees with the saved geometry"
        )
    if float(diagnostics.threshold) != threshold:
        failures.append(f"eta={eta:.2f} diagnostics threshold disagrees with qhat_star")
    area_method = AREA_METHOD_POLYGONS if saved_polygons else AREA_METHOD_NONE
    if area > 0.0:
        status = REGION_STATUS_POSITIVE
    elif accepted_count or diagnostics.mixed_cell_count or diagnostics.unresolved_cell_count:
        status = REGION_STATUS_UNRESOLVED
    else:
        status = REGION_STATUS_NO_INSIDE
    if diagnostics.region_status != status:
        failures.append(
            f"eta={eta:.2f} region_status disagrees with the numerical area and counts"
        )
    if area == 0.0 and status not in ALLOWED_ZERO_AREA_STATUSES:
        failures.append(f"eta={eta:.2f} zero area is reported as a proved empty set")
    if area == 0.0 and not str(diagnostics.stop_reason).strip():
        failures.append(
            f"eta={eta:.2f} zero area has no stop_reason to explain it"
        )
    if diagnostics.area_estimation_method != area_method:
        failures.append(
            f"eta={eta:.2f} area_estimation_method disagrees with the saved geometry"
        )
    return {
        "kind": REGION_KIND,
        "classification_samples": CLASSIFICATION_SAMPLES,
        "eta": eta,
        "threshold": threshold,
        "accepted_sample_count": accepted_count,
        "hero_is_in_accepted_samples": hero_good,
        "sampled_inside_cell_count": diagnostics.sampled_inside_cell_count,
        "mixed_cell_count": diagnostics.mixed_cell_count,
        "unresolved_cell_count": diagnostics.unresolved_cell_count,
        "area_estimate_m2": area,
        "area_estimation_method": area_method,
        "region_status": status,
        "stop_reason": diagnostics.stop_reason,
        "achieved_max_boundary_cell_size_m": (
            diagnostics.achieved_max_boundary_cell_size_m
        ),
        "target_boundary_resolution_m": diagnostics.target_boundary_resolution_m,
        "boundary_fragment_count": fragment_count,
        "saved_polygon_count": len(saved_polygons),
        "requested_refinement_count": diagnostics.requested_refinement_count,
        "executed_refinement_count": diagnostics.executed_refinement_count,
        "deferred_by_cap_count": diagnostics.deferred_by_cap_count,
        "refinement_cap_hit": diagnostics.refinement_cap_hit_count > 0,
        "trigger_counts": {
            name: count for name, count in diagnostics.trigger_category_counts
        },
        "display_region_kind": diagnostics.display_region_kind,
    }


def _accepted_sample_payload(samples: tuple) -> list[list[Any]]:
    return [[[point.x, point.y], value] for point, value in samples]


def _expected_eta_payload(
    evidence: EvidencePackage, eta: float, scalars: dict[str, Any]
) -> dict[str, Any]:
    accepted = tuple(
        getattr(evidence, "candidate_region_accepted_samples", {}).get(eta, ())
    )
    payload: dict[str, Any] = {
        "kind": scalars["kind"],
        "classification_samples": scalars["classification_samples"],
        "eta": eta,
        "qhat_star": evidence.qhat_star,
        "threshold": scalars["threshold"],
        "approximate_area_m2": scalars["area_estimate_m2"],
        "resolution": {
            "base": evidence.candidate_region_base_resolution,
            "max_refinement_depth": evidence.candidate_region_max_refinement_depth,
            "target_boundary_resolution_m": evidence.candidate_region_target_resolution_m,
        },
        "diagnostics": scalars,
        "display_region": {
            "kind": scalars["display_region_kind"],
            "area_estimate_m2": scalars["area_estimate_m2"],
            "boundary_polygon_count": scalars["saved_polygon_count"],
        },
        "accepted_samples": _accepted_sample_payload(accepted),
        "accepted_samples_total": len(accepted),
        "accepted_samples_note": ACCEPTED_SAMPLES_NOTE,
        "boundary_polygon_note": BOUNDARY_POLYGON_NOTE,
        "refinement_history": list(evidence.refinement_history),
        "hero_promotion_history": list(
            getattr(evidence, "hero_promotion_history", ())
        ),
        "hero_closure": evidence.hero_closure,
        "points": [
            _candidate_payload(point) for point in evidence.candidate_regions[eta]
        ],
    }
    payload.update(scalars)
    return payload


def _expected_aggregate_payload(
    evidence: EvidencePackage, scalars_by_eta: dict[float, dict[str, Any]]
) -> dict[str, Any]:
    accepted = getattr(evidence, "candidate_region_accepted_samples", {})
    return {
        "kind": "numerical_candidate_good_regions_not_proof",
        "classification_samples": CLASSIFICATION_SAMPLES,
        "region_kind": REGION_KIND,
        "qhat_star": evidence.qhat_star,
        "qhat_star_source": "Hero numerical search",
        "evidence_config_id": evidence.evidence_config_id,
        "hero_promotion_history": list(
            getattr(evidence, "hero_promotion_history", ())
        ),
        "hero_closure": evidence.hero_closure,
        "approximate_areas_m2": {
            f"{eta:.2f}": evidence.candidate_region_areas_m2[eta]
            for eta in EXPECTED_ETAS
        },
        "area_estimate_m2": {
            f"{eta:.2f}": scalars_by_eta[eta]["area_estimate_m2"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "area_estimation_method": {
            f"{eta:.2f}": scalars_by_eta[eta]["area_estimation_method"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "region_status": {
            f"{eta:.2f}": scalars_by_eta[eta]["region_status"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "stop_reason": {
            f"{eta:.2f}": scalars_by_eta[eta]["stop_reason"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "accepted_sample_count": {
            f"{eta:.2f}": scalars_by_eta[eta]["accepted_sample_count"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "hero_is_in_accepted_samples": {
            f"{eta:.2f}": scalars_by_eta[eta]["hero_is_in_accepted_samples"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "sampled_inside_cell_count": {
            f"{eta:.2f}": scalars_by_eta[eta]["sampled_inside_cell_count"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "mixed_cell_count": {
            f"{eta:.2f}": scalars_by_eta[eta]["mixed_cell_count"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "unresolved_cell_count": {
            f"{eta:.2f}": scalars_by_eta[eta]["unresolved_cell_count"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "achieved_max_boundary_cell_size_m": {
            f"{eta:.2f}": scalars_by_eta[eta]["achieved_max_boundary_cell_size_m"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "boundary_fragment_count": {
            f"{eta:.2f}": scalars_by_eta[eta]["boundary_fragment_count"]
            for eta in EXPECTED_ETAS
            if eta in scalars_by_eta
        },
        "diagnostics": {
            f"{eta:.2f}": scalars_by_eta[eta] for eta in EXPECTED_ETAS
        },
        "representative_accepted_samples": {
            f"{eta:.2f}": _accepted_sample_payload(
                tuple(accepted.get(eta, ()))[:AGGREGATE_PREVIEW]
            )
            for eta in EXPECTED_ETAS
        },
        "representative_accepted_sample_limit": AGGREGATE_PREVIEW,
        "representative_accepted_samples_truncated": {
            f"{eta:.2f}": len(tuple(accepted.get(eta, ()))) > AGGREGATE_PREVIEW
            for eta in EXPECTED_ETAS
        },
        "accepted_samples_note": ACCEPTED_SAMPLES_NOTE,
        "boundary_polygon_note": BOUNDARY_POLYGON_NOTE,
        "accepted_samples_full_paths": {
            f"{eta:.2f}": f"q2_candidate_good_eta_{round(100 * eta):02d}.json"
            for eta in EXPECTED_ETAS
        },
        "refinement_history": list(evidence.refinement_history),
        "regions": {
            f"{eta:.2f}": [
                _candidate_payload(point) for point in evidence.candidate_regions[eta]
            ]
            for eta in EXPECTED_ETAS
        },
    }


def _closed_ring(ring: tuple) -> list[list[float]]:
    coordinates = [[point.x, point.y] for point in ring]
    if coordinates and coordinates[0] != coordinates[-1]:
        coordinates.append(list(coordinates[0]))
    return coordinates


def _expected_candidate_geojson(
    evidence: EvidencePackage, eta: float, scalars: dict[str, Any]
) -> dict[str, Any]:
    saved_polygons = tuple(
        getattr(evidence, "candidate_region_boundary_polygons", {}).get(eta, ())
    )
    cells = evidence.candidate_region_cells[eta]
    fragments = saved_polygons[len(cells):]
    features: list[dict[str, Any]] = []
    for point in evidence.candidate_regions[eta]:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [point.S2.x, point.S2.y],
                },
                "properties": {"Q_m": point.Q, "eta": eta, "kind": "sample"},
            }
        )
    for cell in cells:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_closed_ring(cell.ring())],
                },
                "properties": {
                    "eta": eta,
                    "kind": "inside_cell",
                    "depth": cell.depth,
                    "approximate_area_m2": cell.area,
                },
            }
        )
    for index, ring in enumerate(fragments):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_closed_ring(ring)],
                },
                "properties": {
                    "eta": eta,
                    "kind": "boundary_fragment",
                    "fragment_index": index,
                    "ring_vertex_count": len(ring),
                    "area_m2": _ring_area(ring),
                },
            }
        )
    properties: dict[str, Any] = {
        "kind": REGION_KIND,
        "eta": eta,
        "qhat_star": evidence.qhat_star,
        "approximate_area_m2": scalars["area_estimate_m2"],
        "evidence_config_id": evidence.evidence_config_id,
        "hero_closure": evidence.hero_closure,
        "resolution": {
            "base": evidence.candidate_region_base_resolution,
            "max_refinement_depth": evidence.candidate_region_max_refinement_depth,
            "target_boundary_resolution_m": evidence.candidate_region_target_resolution_m,
        },
        "display_region_kind": scalars["display_region_kind"],
        "classification_samples": CLASSIFICATION_SAMPLES,
        "boundary_polygon_note": BOUNDARY_POLYGON_NOTE,
    }
    properties.update(scalars)
    return {
        "type": "FeatureCollection",
        "properties": properties,
        "features": features,
    }


def _figure_data_payload(evidence: EvidencePackage) -> dict[str, Any]:
    base = {
        "S1": [evidence.S1.x, evidence.S1.y],
        "theta1_deg": evidence.theta1_deg,
        "bounds": [evidence.bounds.x_min, evidence.bounds.x_max,
                   evidence.bounds.y_min, evidence.bounds.y_max],
        "rows": [_row_payload(row) for row in evidence.rows],
        "surface": [
            {"S2": [result.S2.x, result.S2.y], "Q": _json_number(result.Q),
             "in_crec": result.in_crec, "admissible": result.admissible}
            for result in evidence.surface
        ],
        "candidate_regions": {
            f"{eta:.2f}": [_candidate_payload(point) for point in evidence.candidate_regions[eta]]
            for eta in EXPECTED_ETAS
        },
        "expanded_intervals_deg": [
            [math.degrees(interval.start_rad), math.degrees(interval.end_rad)]
            for interval in evidence.hero_result.expanded_theta_intervals.intervals
        ],
        "worst_polygon": [[point.x, point.y] for point in evidence.hero_result.worst_Q1_polygon],
    }
    stored = getattr(evidence, "figure_data_payload", {})
    return stored if stored else base


def _figure_dpi(path: Path) -> int:
    payload = _read_json(path)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    return int(metadata.get("dpi", 300))


def _expected_b2_provenance(evidence: EvidencePackage) -> dict[str, Any]:
    rho_a = 5.0
    rho_b = 1500.0
    reception_radius = 1000.0
    length = rho_b - rho_a
    x_star = rho_a + reception_radius**2 / length
    abs_y_star = reception_radius * math.sqrt(1.0 - (reception_radius / length) ** 2)
    angle = math.radians(evidence.theta1_deg % 360.0)
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    unclamped = (
        evidence.S1
        + direction.scaled(x_star)
        + perpendicular.scaled(abs_y_star)
    )
    point = _clamp_to_bounds(unclamped, evidence.bounds)
    a1 = build_a1(
        FirstObservation(evidence.S1, evidence.theta1_deg, evidence.epsilon_deg)
    )
    radial = a1.radial_interval(angle)
    omega_truncated = (
        radial is None
        or any(piece.label == A1BoundaryLabel.OMEGA for piece in a1.boundary.pieces)
        or not (
            math.isclose(radial[0], 5.0, abs_tol=1e-9)
            and math.isclose(radial[1], 1500.0, abs_tol=1e-9)
        )
    )
    fresh = evaluate_q2_point(
        evidence.S1, evidence.theta1_deg, point, evidence.epsilon_deg
    )
    return _attach_fresh_metrics(
        _method_identity(
            METHOD_ID_B2, "B2", FORMULA_B2, INPUTS_B2, SIDE_B2, CLAMP_B2
        )
        | {
            "heuristic": "center_ray_max_min_angle",
            "status": (
                "canonical_heuristic_omega_truncated"
                if omega_truncated
                else "analytic_untruncated"
            ),
            "analytic_optimality_claimed": not omega_truncated,
            "omega_truncated": omega_truncated,
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
            "clamped": unclamped != point,
        },
        fresh,
    )


def _expected_b1_provenance(evidence: EvidencePackage) -> dict[str, Any]:
    """Independently recompute the two-sided 90-degree midpoint selection."""
    angle = math.radians(evidence.theta1_deg % 360.0)
    direction = Point2(math.cos(angle), math.sin(angle))
    perpendicular = Point2(-direction.y, direction.x)
    a1 = build_a1(
        FirstObservation(evidence.S1, evidence.theta1_deg, evidence.epsilon_deg)
    )
    radial = a1.radial_interval(angle)
    if radial is None:
        fallback = _bounds_center(evidence.bounds)
        fresh = evaluate_q2_point(
            evidence.S1, evidence.theta1_deg, fallback, evidence.epsilon_deg
        )
        return _attach_fresh_metrics(
            _method_identity(
                METHOD_ID_B1, "B1", FORMULA_B1, INPUTS_B1, SIDE_B1, CLAMP_B1
            )
            | {
                "heuristic": "right_angle_radial_midpoint",
                "status": "bounds_center_fallback",
                "rho_m": 0.0,
                "rho_lo_m": 0.0,
                "rho_hi_m": 0.0,
                "nominal_target_m": [fallback.x, fallback.y],
                "selection_rule": "min_Q_over_symmetric_sides",
                "chosen_side": "bounds_center_fallback",
                "evaluated_sides": [],
                "unclamped_S2": [fallback.x, fallback.y],
                "S2": [fallback.x, fallback.y],
                "clamp": "componentwise_to_crec_derived_bounds",
                "clamped": False,
            },
            fresh,
        )
    rho = 0.5 * (radial[0] + radial[1])
    target = evidence.S1 + direction.scaled(rho)
    evaluated = []
    for side, sign in (("positive_perpendicular", 1.0), ("negative_perpendicular", -1.0)):
        raw = target + perpendicular.scaled(sign * rho)
        clamped = _clamp_to_bounds(raw, evidence.bounds)
        result = evaluate_q2_point(
            evidence.S1, evidence.theta1_deg, clamped, evidence.epsilon_deg
        )
        evaluated.append((side, raw, clamped, result))
    feasible = [item for item in evaluated if _baseline_valid(item[3])]
    chosen = (
        min(feasible, key=lambda item: _baseline_result_key(item[3]))
        if feasible
        else evaluated[0]
    )
    chosen_side, chosen_raw, chosen_point, chosen_result = chosen
    return _attach_fresh_metrics(
        _method_identity(
            METHOD_ID_B1, "B1", FORMULA_B1, INPUTS_B1, SIDE_B1, CLAMP_B1
        )
        | {
            "heuristic": "right_angle_radial_midpoint",
            "status": "ok",
            "rho_m": rho,
            "rho_lo_m": radial[0],
            "rho_hi_m": radial[1],
            "nominal_target_m": [target.x, target.y],
            "selection_rule": "min_Q_over_symmetric_sides",
            "chosen_side": chosen_side,
            "evaluated_sides": [
                {
                    "side": side,
                    "unclamped_S2": [raw.x, raw.y],
                    "clamped_S2": [point.x, point.y],
                    "Q": _json_number(result.Q),
                    "Crec_feasible": result.in_crec,
                    "admissible": result.admissible,
                }
                for side, raw, point, result in evaluated
            ],
            "unclamped_S2": [chosen_raw.x, chosen_raw.y],
            "S2": [chosen_point.x, chosen_point.y],
            "clamp": "componentwise_to_crec_derived_bounds",
            "clamped": chosen_raw != chosen_point,
        },
        chosen_result,
    )


def _clamp_to_bounds(point: Point2, bounds: Any) -> Point2:
    return Point2(
        min(bounds.x_max, max(bounds.x_min, point.x)),
        min(bounds.y_max, max(bounds.y_min, point.y)),
    )


def _bounds_center(bounds: Any) -> Point2:
    return Point2(
        0.5 * (bounds.x_min + bounds.x_max),
        0.5 * (bounds.y_min + bounds.y_max),
    )


def _baseline_valid(result: Q2PointResult) -> bool:
    return (
        result.in_crec
        and (result.admissible or result.all_near)
        and result.Q is not None
        and math.isfinite(float(result.Q))
    )


def _baseline_result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return (float(result.Q), result.S2.x, result.S2.y)


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        "method": row.method, "S2": [row.S2.x, row.S2.y], "Q": _json_number(row.Q),
        "Crec_feasible": row.crec_feasible, "admissible": row.admissible,
        "move_distance_m": row.move_distance_m, "all_near": row.all_near,
        "worst_beta_deg": row.worst_beta_deg, "runtime_s": row.runtime_s,
        "verification": row.verification,
    }


def _candidate_payload(point: Any) -> dict[str, Any]:
    return {"S2": [point.S2.x, point.S2.y], "Q": point.Q}


def _json_number(value: float | None) -> float | str | None:
    if value is None or math.isfinite(value):
        return value
    return "Infinity" if value > 0.0 else "-Infinity"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MISSING


def _is_valid(result: Q2PointResult) -> bool:
    return result.in_crec and result.admissible and result.Q is not None


def _result_key(result: Q2PointResult) -> tuple[float, float, float]:
    return (math.inf if result.Q is None else float(result.Q), result.S2.x, result.S2.y)


def _valid_rendered_file(path: Path) -> bool:
    try:
        content = path.read_bytes()
    except OSError:
        return False
    if len(content) <= 100:
        return False
    if path.suffix == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if path.suffix == ".pdf":
        return content.startswith(b"%PDF")
    if path.suffix == ".svg":
        return b"<svg" in content[:1000]
    return False
