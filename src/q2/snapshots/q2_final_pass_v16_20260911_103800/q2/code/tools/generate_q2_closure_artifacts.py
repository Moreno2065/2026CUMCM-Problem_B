"""Regenerate the representative Q2 Gate G package after Hero closure."""

from __future__ import annotations

import json
from pathlib import Path

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import CandidateRegionConfig
from src.q2.code.solver.gate_g import GateGConfig, build_gate_g_case
from src.q2.code.solver.outer_search import OuterSearchConfig
from src.q2.code.verifier.verify_gate_g import verify_gate_g


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "artifacts" / "gate_g_representative"
    config = GateGConfig(
        outer_config=OuterSearchConfig(
            coarse_resolution=7,
            subdivision_depth=2,
            local_iterations=8,
            parallel_workers=8,
        ),
        surface_resolution=21,
        figure_dpi=300,
        candidate_region_config=CandidateRegionConfig(
            base_resolution=21,
            max_refinement_depth=6,
            target_boundary_resolution_m=5.0,
            near_hero_cell_factor=2.5,
            max_refined_cells_per_level=32,
        ),
        evidence_config_id="q2-final-evidence-v5-hero-closure",
        parallel_workers=8,
        hero_promotion_tolerance_m=1e-9,
        hero_promotion_min_crec_margin_m=1e-6,
        hero_promotion_max_rounds=3,
        max_closure_rounds=3,
        closure_seed_points=(
            Point2(800.0736125053295, -606.4160929019891),
        ),
    )
    evidence = build_gate_g_case(
        Point2(0.0, 0.0),
        0.0,
        output,
        config=config,
        render_figures=True,
    )
    verification = verify_gate_g(evidence)
    if not verification.passed:
        raise RuntimeError(
            "Generated Gate G closure artifacts failed independent verification: "
            + "; ".join(verification.failures)
        )
    print(
        json.dumps(
            {
                "output": str(output),
                "hero": [evidence.hero_result.S2.x, evidence.hero_result.S2.y],
                "Q": evidence.hero_result.Q,
                "closure": evidence.hero_closure,
                "evaluated_count": len(evidence.all_evaluated_results),
                "independent_verification": {
                    "passed": verification.passed,
                    "hero_closure_passed": verification.hero_closure_passed,
                    "independent_hero_passed": verification.independent_hero_passed,
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
