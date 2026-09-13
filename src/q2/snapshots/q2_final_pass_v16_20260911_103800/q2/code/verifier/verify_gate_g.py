"""Independent metric and artifact-integrity verifier for Gate G evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from src.q2.code.geometry.a1 import FirstObservation, build_a1
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

    expected_b1 = {"B1": _expected_b1_provenance(evidence)}
    if evidence.method_provenance != expected_b1:
        failures.append("B1 formula provenance disagrees with the frozen heuristic")
    if _read_json(evidence.method_provenance_path) != expected_b1:
        failures.append("persisted B1 formula provenance disagrees with evidence")
    if len(evidence.rows) > 1 and evidence.rows[1].S2 != Point2(*expected_b1["B1"]["S2"]):
        failures.append("B1 row does not use the frozen heuristic point")

    expected_combined = {
        "kind": "numerical_candidate_good_regions_not_proof",
        "qhat_star": evidence.qhat_star,
        "qhat_star_source": "Hero numerical search",
        "evidence_config_id": evidence.evidence_config_id,
        "hero_promotion_history": list(getattr(evidence, "hero_promotion_history", ())),
        "hero_closure": evidence.hero_closure,
        "approximate_areas_m2": {
            f"{eta:.2f}": evidence.candidate_region_areas_m2[eta]
            for eta in EXPECTED_ETAS
        },
        "refinement_history": list(evidence.refinement_history),
        "regions": {
            f"{eta:.2f}": [_candidate_payload(point) for point in evidence.candidate_regions[eta]]
            for eta in EXPECTED_ETAS
        },
    }
    if _read_json(evidence.candidate_regions_path) != expected_combined:
        failures.append("aggregate candidate-region payload disagrees with evidence")

    if set(evidence.candidate_region_paths) != set(EXPECTED_ETAS):
        failures.append("separate candidate-region files are incomplete")
    else:
        for eta in EXPECTED_ETAS:
            expected_eta = {
                "kind": "numerical_candidate_good_region_not_proof",
                "eta": eta,
                "qhat_star": evidence.qhat_star,
                "threshold": evidence.candidate_region_thresholds[eta],
                "approximate_area_m2": evidence.candidate_region_areas_m2[eta],
                "resolution": {
                    "base": getattr(evidence, "candidate_region_base_resolution", None)
                    or _resolution_from_cells(evidence.candidate_region_cells[eta]),
                    "max_refinement_depth": evidence.candidate_region_max_refinement_depth,
                    "target_boundary_resolution_m": getattr(
                        evidence, "candidate_region_target_resolution_m", None
                    ) or 5.0,
                },
                "refinement_history": list(evidence.refinement_history),
                "hero_promotion_history": list(getattr(evidence, "hero_promotion_history", ())),
                "hero_closure": evidence.hero_closure,
                "points": [_candidate_payload(point) for point in evidence.candidate_regions[eta]],
            }
            if _read_json(evidence.candidate_region_paths[eta]) != expected_eta:
                failures.append(f"separate eta={eta:.2f} payload disagrees with evidence")

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


def _resolution_from_cells(cells: tuple) -> int:
    return 0 if not cells else 0


def _figure_dpi(path: Path) -> int:
    payload = _read_json(path)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    return int(metadata.get("dpi", 300))


def _expected_b1_provenance(evidence: EvidencePackage) -> dict[str, Any]:
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
    point = Point2(
        min(evidence.bounds.x_max, max(evidence.bounds.x_min, unclamped.x)),
        min(evidence.bounds.y_max, max(evidence.bounds.y_min, unclamped.y)),
    )
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
