"""Generate the independent Q2 verification artifacts for the repair package.

Runs the frozen evaluator on a representative centered instance and writes:

    q2_verification/inner_verifier_report.json
    q2_verification/near_parallel_endpoint_verifier.json
    q2_verification/crec_witness_verifier.json
    q2_verification/candidate_region_resolution_stability.json
    q2_verification/symmetry_report.json

Every number is computed here; nothing is hand-written.

Section 6 requires one frozen target set for the whole evidence run: the Hero,
the search box, ``q_reference`` and the thresholds are resolved once and then
shared by the inner probes, the symmetry report and every resolution level.  The
Hero candidates below are *seeds*: each is freshly evaluated through the frozen
evaluator and the best valid one becomes the reference, so the choice is a
computed result rather than a pinned old coordinate.

The inner rows keep two separate promotion vocabularies on purpose.  The
independent verifier promotes when its finite scan exceeds the main value by
more than ``max(1e-6, 1e-8 * max(1, |q_main|))``; the production facade
``maximize_inner_verified`` promotes above
``InnerVerificationConfig.promotion_tolerance_m = 1e-4``.  Unifying them would
change Q and every downstream artifact, so this round only reports both.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import math
from pathlib import Path
import time

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.angular_image import build_angular_image
from src.q2.code.geometry.crec import build_crec, CompatibleRadiusMode, is_in_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import (
    AdaptiveCandidateResult,
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.gate_g import _center_ray_max_min_angle, _right_angle_heuristic
from src.q2.code.solver.inner_max import (
    InnerVerificationConfig,
    maximize_inner,
    maximize_inner_verified,
)
from src.q2.code.solver.outer_search import OuterSearchConfig, search_outer
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_candidate_resolution import (
    DECLARED_PHASE_FRACTIONS,
    DECLARED_RESOLUTION_CRITERIA,
    ExtractionLevelSpec,
    candidate_region_resolution_stability,
    evaluator_source_fingerprint,
)
from src.q2.code.verifier.verify_crec import verify_crec
from src.q2.code.verifier.verify_crec_deep import (
    verify_crec_deep_arc_witnesses,
)
from src.q2.code.verifier.verify_inner import (
    PARALLEL_EVENT_FRACTION_OF_EPSILON,
    _event_interval_distance,
    _independent_scan_samples,
    _parallel_events,
    default_endpoint_densification_distance_rad,
    verify_inner_max_independent,
)
from src.q2.code.verifier.verify_symmetry import build_symmetry_report


S1 = Point2(0.0, 0.0)
THETA1_DEG = 0.0
EPSILON_DEG = 1.0
ETA_PRIMARY = 0.05

# One shared outer search resolves the Hero and the search box for every report.
REFERENCE_OUTER = OuterSearchConfig(
    coarse_resolution=7, subdivision_depth=2, local_iterations=8
)
# Declared Hero seeds.  Each is evaluated through the frozen evaluator; the best
# valid one becomes q_reference.  They are seeds, not pinned answers.
REFERENCE_HERO_CANDIDATES = (
    ("round1_receipt_hero", Point2(800.1012338639696, -606.388471543349)),
    ("gate_g_closure_seed", Point2(800.0736125053295, -606.4160929019891)),
)

HERO_REGION = CandidateRegionConfig(
    base_resolution=21,
    max_refinement_depth=6,
    target_boundary_resolution_m=5.0,
    max_refined_cells_per_level=32,
    # Declared boundary budget for this auxiliary region build: it only supplies
    # probe points and the symmetry cross-check, so the boundary clip is kept
    # bounded instead of spending the full default budget.
    boundary_max_cells=128,
    boundary_max_probes=1200,
    boundary_probe_budget_per_cell=64,
)

# Declared spatial-extraction budgets for the section-6 comparison.  Only these
# fields may differ between the three levels; everything else is frozen above.
# The boundary budgets are declared here, before the run, and the same values are
# written into candidate_region_resolution_stability.json.
RESOLUTION_LEVELS = (
    ExtractionLevelSpec(
        "coarse",
        CandidateRegionConfig(
            base_resolution=21,
            max_refinement_depth=3,
            target_boundary_resolution_m=40.0,
            max_refined_cells_per_level=48,
            boundary_max_cells=128,
            boundary_max_probes=2000,
            boundary_probe_budget_per_cell=48,
            boundary_max_cell_diameter_factor=2.0,
        ),
    ),
    ExtractionLevelSpec(
        "medium",
        CandidateRegionConfig(
            base_resolution=41,
            max_refinement_depth=3,
            target_boundary_resolution_m=25.0,
            max_refined_cells_per_level=192,
            boundary_max_cells=512,
            boundary_max_probes=8000,
            boundary_probe_budget_per_cell=96,
            boundary_max_cell_diameter_factor=2.0,
        ),
    ),
    ExtractionLevelSpec(
        "fine",
        CandidateRegionConfig(
            base_resolution=41,
            max_refinement_depth=3,
            target_boundary_resolution_m=15.0,
            max_refined_cells_per_level=192,
            boundary_max_cells=512,
            boundary_max_probes=8000,
            boundary_probe_budget_per_cell=96,
            boundary_max_cell_diameter_factor=2.0,
        ),
    ),
)
# The declared phase sweep probes the final numerical display resolution, not a
# deliberately coarse reconnaissance grid.  It is declared before this run.
PHASE_PROBE_LEVEL = "fine"
STABILITY_WORKERS = 8

NEAR_PARALLEL_GATE_PROBES = (
    ("near_parallel_gate_y120", Point2(600.0, 120.0)),
    ("near_parallel_gate_y90", Point2(600.0, 90.0)),
    ("near_parallel_gate_y78", Point2(600.0, 78.0)),
    ("near_parallel_gate_y76", Point2(600.0, 76.0)),
    ("near_parallel_gate_y73_334", Point2(600.0, 73.334)),
)
NEAR_PARALLEL_FAR_POINT = Point2(750.0, 500.0)

PROMOTION_TOLERANCE_NOTE = (
    "two promotion tolerances coexist and are reported side by side instead of "
    "being unified in this round: the independent verifier promotes when "
    "abs_gap > max(1e-6, 1e-8 * max(1, |q_main|)) inside "
    "verify_inner_max_independent, while the production facade "
    "maximize_inner_verified promotes when the scan exceeds the raw candidate "
    "maximum by more than InnerVerificationConfig.promotion_tolerance_m. "
    "Changing either threshold would change Q and every downstream artifact, so "
    "the difference is registered as an open calibration item."
)
FINITE_SCAN_NOTE = (
    "a finite scan over beta, even with a zero or negative gap, is a sampling "
    "lower bound for the inner supremum. It is not a certified upper bound and "
    "not a global-optimality proof; the independent ingredient is the search path "
    "over beta, not the shared Q1 polygon algorithm."
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "q2_verification"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    a1 = build_a1(FirstObservation(S1, THETA1_DEG, EPSILON_DEG))
    crec = build_crec(a1)

    # One outer search for the whole run: same Hero, same bounds everywhere.
    search = search_outer(S1, THETA1_DEG, EPSILON_DEG, config=REFERENCE_OUTER)

    stability = candidate_region_resolution_stability(
        S1,
        THETA1_DEG,
        EPSILON_DEG,
        RESOLUTION_LEVELS,
        eta=ETA_PRIMARY,
        hero_result=search.recommended,
        bounds=search.bounds,
        hero_source="shared_search_outer_reference",
        reference_candidates=REFERENCE_HERO_CANDIDATES,
        mirror_symmetric=True,
        phase_fractions=DECLARED_PHASE_FRACTIONS,
        phase_probe_level=PHASE_PROBE_LEVEL,
        workers=STABILITY_WORKERS,
    )
    (output / "candidate_region_resolution_stability.json").write_text(
        json.dumps(_to_jsonable(stability), indent=2, allow_nan=False),
        encoding="utf-8",
    )

    hero = evaluate_q2_point(
        S1, THETA1_DEG, Point2(*stability.frozen.hero_S2), EPSILON_DEG
    )
    if hero.Q is None or abs(float(hero.Q) - stability.frozen.q_reference_m) > 1e-9:
        raise RuntimeError(
            "the frozen reference Hero is not reproducible through the frozen evaluator"
        )

    adaptive = build_adaptive_candidate_regions(
        S1,
        THETA1_DEG,
        EPSILON_DEG,
        search.bounds,
        hero,
        etas=(ETA_PRIMARY,),
        config=HERO_REGION,
        # The representative centred case is mirror-symmetric, so the auxiliary
        # region build is mirror-paired exactly like the Gate-G production
        # builder; otherwise the symmetry report would flag the asymmetric
        # refinement as a broken symmetry.
        extra_seeds=(Point2(hero.S2.x, -hero.S2.y),),
        mirror_hero=Point2(hero.S2.x, -hero.S2.y),
    )

    probes = _probe_points(hero, adaptive, search.bounds)

    inner_report = _inner_report(hero, probes)
    (output / "inner_verifier_report.json").write_text(
        json.dumps(inner_report, indent=2, allow_nan=False), encoding="utf-8"
    )

    near_parallel = _near_parallel_report(a1, probes)
    (output / "near_parallel_endpoint_verifier.json").write_text(
        json.dumps(near_parallel, indent=2, allow_nan=False), encoding="utf-8"
    )

    crec_report = _crec_report(a1, crec, probes)
    (output / "crec_witness_verifier.json").write_text(
        json.dumps(crec_report, indent=2, allow_nan=False), encoding="utf-8"
    )

    symmetry = build_symmetry_report(
        S1, THETA1_DEG, hero, epsilon_deg=EPSILON_DEG, adaptive=adaptive, eta=ETA_PRIMARY
    )
    (output / "symmetry_report.json").write_text(
        json.dumps(_to_jsonable(symmetry), indent=2, allow_nan=False),
        encoding="utf-8",
    )

    paths = [
        output / "inner_verifier_report.json",
        output / "near_parallel_endpoint_verifier.json",
        output / "crec_witness_verifier.json",
        output / "candidate_region_resolution_stability.json",
        output / "symmetry_report.json",
    ]
    print(
        json.dumps(
            {
                "output_directory": str(output),
                "artifacts": [str(path) for path in paths],
                "reference_hero_S2": [hero.S2.x, hero.S2.y],
                "q_reference_m": stability.frozen.q_reference_m,
                "reference_source": stability.frozen.q_reference_source,
                "reference_selection": list(stability.frozen.reference_selection_rows),
                "reference_update_history": list(stability.frozen.reference_update_history),
                "evaluator_fingerprint": stability.frozen.evaluator_fingerprint,
                "evaluator_fingerprint_files": stability.frozen.evaluator_fingerprint_file_count,
                "shared_hero": stability.frozen.shared_hero,
                "shared_bounds": stability.frozen.shared_bounds,
                "thresholds_by_eta": stability.frozen.thresholds_by_eta,
                "levels": [
                    {
                        "name": level.name,
                        "q_reference_m": level.q_reference_m,
                        "threshold": level.threshold,
                        "area_m2": level.area_estimate_m2,
                        "component_count": level.component_count,
                        "boundary_sample_count": level.boundary_sample_count,
                        "boundary_distance_m": level.boundary_bidirectional_distance_m,
                        "achieved_max_boundary_cell_size_m": level.achieved_max_boundary_cell_size_m,
                        "stop_reason": level.stop_reason,
                        "new_evaluation_count": level.new_evaluation_count,
                        "cache_hit_count": level.cache_hit_count,
                        "runtime_s": level.runtime_s,
                    }
                    for level in stability.levels
                ],
                "grid_phase_perturbation": {
                    "level": stability.grid_phase_perturbation.level_name,
                    "max_area_relative_deviation": stability.grid_phase_perturbation.max_area_relative_deviation,
                    "component_counts": list(stability.grid_phase_perturbation.component_counts),
                },
                "cache_consistency": {
                    "checked_count": stability.cache_consistency.checked_count,
                    "max_abs_difference_m": stability.cache_consistency.max_abs_difference_m,
                    "passed": stability.cache_consistency.passed,
                },
                "stability_converged": stability.converged,
                "stability_unconverged_reasons": list(stability.unconverged_reasons),
                "declared_criteria": asdict(DECLARED_RESOLUTION_CRITERIA),
                "inner_probes": inner_report["summary"]["probe_count"],
                "inner_max_abs_gap_m": inner_report["summary"]["max_abs_gap_m"],
                "near_parallel_rows": near_parallel["summary"]["row_count"],
                "near_parallel_densified_rows": near_parallel["summary"]["densified_row_count"],
                "crec_max_gap_m": crec_report["summary"]["max_deep_arc_gap_m"],
                "symmetry_passed": symmetry.passed,
                "evaluator_fingerprint_at_start": stability.frozen.evaluator_fingerprint,
                "evaluator_fingerprint_at_end": evaluator_source_fingerprint()[0],
                "evaluator_fingerprint_changed_during_run": (
                    evaluator_source_fingerprint()[0]
                    != stability.frozen.evaluator_fingerprint
                ),
                "wall_time_s": time.perf_counter() - started,
            },
            indent=2,
        )
    )


def _probe_points(
    hero, adaptive: AdaptiveCandidateResult, bounds
) -> tuple[tuple[str, Point2], ...]:
    points: list[tuple[str, Point2]] = [
        ("hero", hero.S2),
        ("hero_mirror", Point2(hero.S2.x, -hero.S2.y)),
    ]
    radar = build_a1(FirstObservation(S1, THETA1_DEG, EPSILON_DEG))
    # The gate-G heuristic returns (point, provenance, result) in the current
    # revision; index the point so a further field does not break this tool.
    b1 = _right_angle_heuristic(
        S1, THETA1_DEG, EPSILON_DEG, radar, bounds, None
    )[0]
    points.append(("baseline_B1_90deg_midpoint", b1))
    points.append(("baseline_B2_max_min_angle", _center_ray_max_min_angle(radar, bounds)))
    points.append(("S1_origin", Point2(0.0, 0.0)))
    points.append(("outside_crec_far", Point2(0.0, 2600.0)))
    points.append(("far_from_every_parallel_event", NEAR_PARALLEL_FAR_POINT))
    # Approaching the 3*epsilon gate on the centre-ray second station: these
    # probes exercise the explicit near-parallel densification bands.
    points.extend(NEAR_PARALLEL_GATE_PROBES)

    surface = [result for result in adaptive.surface if result.Q is not None]
    if surface:
        lowest = min(surface, key=lambda item: float(item.Q))
        highest = max(surface, key=lambda item: float(item.Q))
        points.append(("surface_min_Q", lowest.S2))
        points.append(("surface_max_Q", highest.S2))
    for index, result in enumerate(
        sorted(
            (item for item in surface if item.in_crec and item.admissible),
            key=lambda item: float(item.Q),
        )[:3]
    ):
        points.append((f"surface_low_Q_{index}", result.S2))
    return tuple(points)


def _inner_report(hero, probes) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    max_gap = 0.0
    failures: list[str] = []
    for name, point in probes:
        result = evaluate_q2_point(S1, THETA1_DEG, point, EPSILON_DEG)
        if result.all_near or not result.admissible or result.Q is None:
            rows.append({"name": name, "status": "skipped", "reason": result.worst_candidate_type})
            continue
        allowed = result.expanded_theta_intervals
        if allowed.is_empty:
            rows.append({"name": name, "status": "skipped", "reason": "empty_bearing_set"})
            continue
        main = maximize_inner(
            S1, THETA1_DEG, point, allowed, EPSILON_DEG
        )
        production = maximize_inner_verified(
            S1, THETA1_DEG, point, allowed, EPSILON_DEG
        )
        verification = verify_inner_max_independent(
            S1,
            THETA1_DEG,
            point,
            allowed,
            EPSILON_DEG,
            q_main=production.Q,
            beta_main_deg=production.worst_beta_deg,
        )
        gap = (
            math.nan
            if verification.q_verify is None or production.Q is None
            else verification.q_verify - production.Q
        )
        if math.isfinite(gap):
            max_gap = max(max_gap, gap)
        if verification.failures:
            failures.extend(f"{name}: {failure}" for failure in verification.failures)
        verifier_tolerance = max(
            1e-6,
            1e-8 * max(1.0, abs(0.0 if production.Q is None else production.Q)),
        )
        rows.append(
            {
                "name": name,
                "status": "checked",
                "S2": [point.x, point.y],
                "q_candidate_raw_m": main.Q,
                "beta_main_deg": main.worst_beta_deg,
                "candidate_type": main.candidate_type,
                "all_matching_event_types": list(main.all_matching_event_types),
                "matching_tolerance_m": main.matching_tolerance_m,
                "q_production_returned_m": production.Q,
                "q_main_raw_m": verification.q_main_raw,
                "q_verify_m": verification.q_verify,
                "beta_verify_deg": verification.beta_verify_deg,
                "q_returned_m": verification.q_returned,
                "gap_before_promotion_m": verification.gap_before_promotion,
                "abs_gap_m": verification.abs_gap,
                "relative_gap": verification.relative_gap,
                "promoted": verification.promoted,
                "verifier_promoted": verification.promoted,
                "production_promoted": production.promoted,
                "production_gap_before_promotion_m": production.gap_before_promotion,
                "verifier_promotion_tolerance_m": verifier_tolerance,
                "production_promotion_tolerance_m": InnerVerificationConfig().promotion_tolerance_m,
                "sampling_levels": dict(verification.sampling_levels),
                "convergence_diagnostic": verification.convergence_diagnostic,
                "endpoint_densification_distance_rad": verification.endpoint_densification_distance_rad,
                "nearest_event_distance_rad": verification.nearest_event_distance_rad,
                "sample_count": verification.sample_count,
                "refinement_rounds": verification.refinement_rounds,
                "near_parallel_bands": verification.near_parallel_bands,
                "converged": verification.converged,
                "failures": list(verification.failures),
            }
        )
    return {
        "case": {"S1": [S1.x, S1.y], "theta1_deg": THETA1_DEG, "epsilon_deg": EPSILON_DEG},
        "hero_Q_m": hero.Q,
        "promotion_tolerance_note": PROMOTION_TOLERANCE_NOTE,
        "interpretation_note": FINITE_SCAN_NOTE,
        "rows": rows,
        "summary": {
            "probe_count": len(rows),
            "checked_count": sum(row["status"] == "checked" for row in rows),
            "max_abs_gap_m": max_gap,
            "failures": failures,
            "passed": not failures,
        },
    }


def _near_parallel_report(a1, probes) -> dict[str, object]:
    threshold = default_endpoint_densification_distance_rad(EPSILON_DEG)
    rows: list[dict[str, object]] = []
    for name, point in probes:
        result = evaluate_q2_point(S1, THETA1_DEG, point, EPSILON_DEG)
        row: dict[str, object] = {
            "name": name,
            "S2": [point.x, point.y],
            "in_crec": result.in_crec,
            "admissible": result.admissible,
            "all_near": result.all_near,
            "status": result.worst_candidate_type,
            "endpoint_densification_distance_rad": threshold,
        }
        allowed = result.expanded_theta_intervals
        if allowed.is_empty:
            row.update(
                {
                    "allowed_interval_count": 0,
                    "nearest_event_distance_rad": None,
                    "nearest_event_deg": None,
                    "nearest_event_inside_allowed_interval": None,
                    "bands": 0,
                    "base_samples": 0,
                    "densification_samples": 0,
                    "bands_triggered": False,
                    "events": [],
                    "note": "empty expanded bearing set: no interval to densify",
                    "promoted": None,
                }
            )
            rows.append(row)
            continue
        samples, bands, base_count, densified, nearest = _independent_scan_samples(
            allowed, THETA1_DEG, EPSILON_DEG, 65, 5, threshold
        )
        angular_events = build_angular_image(a1, point).boundary_events
        events: list[dict[str, object]] = []
        for family, angles in (
            ("E3_parallel_boundary", _parallel_events(THETA1_DEG, EPSILON_DEG)),
            ("A1_angular_image_boundary", tuple(event.angle_rad for event in angular_events)),
        ):
            for index, event in enumerate(angles):
                best_distance: float | None = None
                inside = False
                for interval in allowed.intervals:
                    distance, inside_value = _event_interval_distance(
                        event, interval.start_rad, interval.end_rad
                    )
                    if best_distance is None or distance < best_distance:
                        best_distance = distance
                        inside = inside_value is not None
                entry: dict[str, object] = {
                    "family": family,
                    "event_deg": math.degrees(event) % 360.0,
                    "event_rad": event % math.tau,
                    "circular_distance_to_allowed_set_rad": best_distance,
                    "inside_allowed_interval": inside,
                    "densified": bool(
                        family == "E3_parallel_boundary"
                        and best_distance is not None
                        and best_distance < threshold
                    ),
                }
                if family == "A1_angular_image_boundary":
                    entry["source_label"] = angular_events[index].source_label
                events.append(entry)
        nearest_row = min(
            (
                event
                for event in events
                if event["circular_distance_to_allowed_set_rad"] is not None
            ),
            key=lambda item: item["circular_distance_to_allowed_set_rad"],
            default=None,
        )
        e3_rows = [event for event in events if event["family"] == "E3_parallel_boundary"]
        e3_nearest = min(
            (
                event
                for event in e3_rows
                if event["circular_distance_to_allowed_set_rad"] is not None
            ),
            key=lambda item: item["circular_distance_to_allowed_set_rad"],
            default=None,
        )
        row.update(
            {
                "allowed_interval_count": len(allowed.intervals),
                # The gate reads only the E3 parallel-boundary family, so the
                # headline nearest-event fields describe that family.
                "nearest_event_distance_rad": nearest,
                "nearest_event_deg": None if e3_nearest is None else e3_nearest["event_deg"],
                "in_interval": (
                    None if e3_nearest is None else e3_nearest["inside_allowed_interval"]
                ),
                "nearest_event_inside_allowed_interval": (
                    None if e3_nearest is None else e3_nearest["inside_allowed_interval"]
                ),
                "nearest_any_event_distance_rad": (
                    None if nearest_row is None else nearest_row["circular_distance_to_allowed_set_rad"]
                ),
                "nearest_any_event_deg": (
                    None if nearest_row is None else nearest_row["event_deg"]
                ),
                "nearest_any_event_family": (
                    None if nearest_row is None else nearest_row["family"]
                ),
                "nearest_any_event_in_interval": (
                    None if nearest_row is None else nearest_row["inside_allowed_interval"]
                ),
                "bands": bands,
                "base_samples": base_count,
                "densification_samples": densified,
                "sample_count_total": len(samples),
                "bands_triggered": bands > 0,
                "events": events,
                "note": (
                    "the gate is the circular distance between an event and the closed "
                    "allowed interval, not exact event membership: an endpoint can sit "
                    "arbitrarily close to an event that lies outside the interval"
                ),
            }
        )
        if not result.all_near and result.admissible:
            production = maximize_inner_verified(
                S1, THETA1_DEG, point, allowed, EPSILON_DEG
            )
            verification = verify_inner_max_independent(
                S1,
                THETA1_DEG,
                point,
                allowed,
                EPSILON_DEG,
                q_main=production.Q,
                beta_main_deg=production.worst_beta_deg,
            )
            row.update(
                {
                    "q_main_raw_m": verification.q_main_raw,
                    "q_verify_m": verification.q_verify,
                    "gap_before_promotion_m": verification.gap_before_promotion,
                    "q_returned_m": verification.q_returned,
                    "promoted": verification.promoted,
                    "verifier_promoted": verification.promoted,
                    "production_promoted": production.promoted,
                    "production_promotion_tolerance_m": InnerVerificationConfig().promotion_tolerance_m,
                    "verifier_promotion_tolerance_m": max(
                        1e-6,
                        1e-8
                        * max(1.0, abs(0.0 if production.Q is None else production.Q)),
                    ),
                    "sampling_levels": dict(verification.sampling_levels),
                    "convergence_diagnostic": verification.convergence_diagnostic,
                }
            )
        else:
            row.update(
                {
                    "q_main_raw_m": None,
                    "q_verify_m": None,
                    "gap_before_promotion_m": None,
                    "q_returned_m": None,
                    "promoted": None,
                    "verifier_promoted": None,
                    "production_promoted": None,
                    "reason": (
                        "not admissible or all-near: the inner maximisation is not defined "
                        "for this station, so no promotion vocabulary applies"
                    ),
                }
            )
        rows.append(row)
    admissible_rows = [row for row in rows if row["admissible"]]
    e3_admissible_events = [
        event
        for row in admissible_rows
        for event in row["events"]
        if event["family"] == "E3_parallel_boundary"
    ]
    non_admissible_with_inside_events = [
        row["name"]
        for row in rows
        if not row["admissible"]
        and any(
            event["family"] == "E3_parallel_boundary"
            and event["inside_allowed_interval"]
            for event in row["events"]
        )
    ]
    results = {
        "epsilon_deg": EPSILON_DEG,
        "threshold_rad": threshold,
        "threshold_fraction_of_epsilon": PARALLEL_EVENT_FRACTION_OF_EPSILON,
        "threshold_formula": "max(PARALLEL_EVENT_FRACTION_OF_EPSILON * radians(epsilon), 1e-12)",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "admissible_row_count": len(admissible_rows),
            "densified_row_count": sum(bool(row["bands_triggered"]) for row in rows),
            "exact_same_side_parallel_events_excluded_from_every_admissible_row": not any(
                event["inside_allowed_interval"] for event in e3_admissible_events
            ),
            "non_admissible_rows_where_an_e3_event_is_inside": non_admissible_with_inside_events,
            "endpoint_proximity_to_outside_event_triggers_densification": any(
                row["bands_triggered"] and row["in_interval"] is False for row in rows
            ),
        },
        "promotion_tolerance_note": PROMOTION_TOLERANCE_NOTE,
        "interpretation_note": (
            "Two distinct statements must not be conflated. (1) The 3*epsilon "
            "admissibility gate excludes the exact same-side parallel events "
            "beta = theta1 +- 2*epsilon from the expanded bearing set: those events "
            "are never inside an allowed interval. (2) That gate gives no uniform "
            "positive numerical margin: an allowed interval endpoint can still sit "
            "arbitrarily close to an event that is strictly outside the interval, so "
            "the densification condition is the event-to-interval circular distance "
            "and not exact event membership. The reverse-parallel events "
            "theta1 + pi and theta1 + pi +- 2*epsilon are also listed; no 180-degree "
            "hard exclusion is assumed."
        ),
    }
    return results


CREC_CASES = (
    ("centered", Point2(0.0, 0.0), 0.0),
    ("deep_entry_s1_outside_omega", Point2(3000.0, 0.0), 180.0),
)


def _crec_probe_points(station1: Point2, theta1_deg: float) -> tuple[Point2, ...]:
    """Candidate second stations used for both Crec oracles."""
    return (
        Point2(300.0, 300.0),
        Point2(-500.0, 200.0),
        Point2(900.0, 900.0),
        Point2(0.0, 0.0),
        Point2(-1400.0, 100.0),
        Point2(600.0, 76.0),
    )


def _crec_report(a1, crec, probes) -> dict[str, object]:
    """Independent Crec cross-checks over the centered and deep-entry cases.

    The centered case contains no RADIAL_DEPTH Omega arc, so the deep-entry
    configuration (first station outside Omega, rho>1000 Omega entry) is added
    explicitly: it is the only family that exercises the analytic deep-arc
    stationary solve that has to be cross-checked.
    """
    del a1, crec, probes
    rows: list[dict[str, object]] = []
    deep_rows: list[dict[str, object]] = []
    max_gap = 0.0
    failures: list[str] = []
    for case_name, station1, theta1_deg in CREC_CASES:
        case_a1 = build_a1(FirstObservation(station1, theta1_deg, EPSILON_DEG))
        case_crec = build_crec(case_a1)
        for point in _crec_probe_points(station1, theta1_deg):
            name = f"{case_name}@{point.x:.3f},{point.y:.3f}"
            analytic = is_in_crec(case_crec, point)
            dense = verify_crec(
                case_a1,
                point,
                analytic_max_violation_m=analytic.max_violation_m,
                analytic_in_crec=analytic.in_crec,
                angle_samples=1441,
                radial_samples=257,
            )
            deep = verify_crec_deep_arc_witnesses(
                case_crec, point, base_samples=4097
            )
            rows.append(
                {
                    "case": case_name,
                    "name": name,
                    "S1": [station1.x, station1.y],
                    "S2": [point.x, point.y],
                    "analytic_max_violation_m": analytic.max_violation_m,
                    "analytic_in_crec": analytic.in_crec,
                    "dense_max_violation_m": dense.dense_radial_max_violation_m,
                    "representative_max_violation_m": dense.representative_max_violation_m,
                    "analytic_minus_dense_m": dense.analytic_minus_dense_m,
                    "dense_passed": dense.passed,
                    "deep_arc_count": deep.checked_arc_count,
                    "deep_arc_max_gap_m": deep.max_gap_m,
                    "deep_arc_passed": deep.passed,
                }
            )
            if not dense.passed:
                failures.extend(f"{name}: {failure}" for failure in dense.failures)
            if not deep.passed:
                failures.extend(f"{name}: {failure}" for failure in deep.failures)
            max_gap = max(max_gap, deep.max_gap_m)
            for deep_row in deep.rows:
                deep_rows.append(
                    {
                        "case": case_name,
                        "probe": name,
                        "S2": [point.x, point.y],
                        **asdict(deep_row),
                    }
                )
    return {
        "cases": [
            {
                "name": case_name,
                "S1": [station1.x, station1.y],
                "theta1_deg": theta1_deg,
                "epsilon_deg": EPSILON_DEG,
                "deep_arc_witness_count": len(
                    [
                        piece
                        for piece in build_crec(
                            build_a1(FirstObservation(station1, theta1_deg, EPSILON_DEG))
                        ).witnesses.pieces
                        if piece.radius_mode
                        == CompatibleRadiusMode.RADIAL_DEPTH
                    ]
                ),
            }
            for case_name, station1, theta1_deg in CREC_CASES
        ],
        "deep_arc_witnesses": deep_rows,
        "rows": rows,
        "summary": {
            "probe_count": len(rows),
            "deep_arc_total": len(deep_rows),
            "max_deep_arc_gap_m": max_gap,
            "failures": failures,
            "passed": not failures,
        },
    }


def _to_jsonable(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            key: _to_jsonable(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    main()
