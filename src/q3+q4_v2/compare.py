"""Equal-budget paired comparison for the three v2 strategies.

Usage example:
    python compare.py --seed 101 --n-sources 10 --q4-scenario mixed

This is a benchmark runner, not pytest and not a regression/smoke suite. Every
strategy receives the same synthetic case seed, source count and scenario.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from runtime import report_line, run_case
from geometry_joint.scheduler import GeometryJointScheduler
from probabilistic_search.scheduler import BeliefProbeScheduler
from learned_search.scheduler import LearnedSearchScheduler


STRATEGIES = {
    "geometry_joint": GeometryJointScheduler,
    "belief_probe_search": BeliefProbeScheduler,
    "learned_search": LearnedSearchScheduler,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--n-sources", type=int, default=10)
    parser.add_argument("--q3-scenario", default="random")
    parser.add_argument("--q4-scenario", default="mixed")
    parser.add_argument("--output", type=Path, default=ROOT / "comparison_runs")
    args = parser.parse_args(argv)
    rows = []
    common = {"nbv_mode": "radius", "opportunistic_reuse": True,
              "cert_route_mode": "lookahead2", "q4_joint_rank": True,
              "q4_residual_sparsify": True,
              "q4_certificate_layout": "sparse25"}
    for mode, scenario in (("Q3", args.q3_scenario), ("Q4", args.q4_scenario)):
        for name, cls in STRATEGIES.items():
            out = args.output / f"{mode.lower()}_{name}_{args.seed}_{args.n_sources}_{scenario}"
            route_cfg = dict(common)
            # Each route owns its policy parameters, but all three still use
            # this identical case, executor, virtual budget and verifier.
            # The learned route uses the same production gates as
            # recommended.py; geometry and belief keep their independent
            # route defaults for a transparent paired comparison.
            if name == "learned_search" and mode == "Q3":
                route_cfg.update({
                    "channel_scan_mode": "selective_clear",
                    "active_scan_margin_m": (
                        175.0 if args.n_sources <= 10 else
                        (150.0 if scenario == "dense" else 60.0)),
                    "q3_dynamic_order": args.n_sources >= 16,
                    # Keep the formal incumbent in paired comparisons.  The
                    # adaptive-radius candidate remains an offline ablation.
                    "q3_adaptive_radius": False,
                    "q3_ring_order": (
                        ((0, 1, 5, 4, 3, 2) if scenario == "dense" else
                         (4, 5, 0, 1, 2, 3))
                        if args.n_sources >= 16 else None),
                    "q3_risky_clear_radius": (
                        75.0 if args.n_sources <= 10 else
                        (30.0 if scenario == "dense" else 40.0)),
                })
            elif name == "learned_search" and mode == "Q4":
                route_cfg["channel_scan_mode"] = "state_aware"
                if args.n_sources >= 16 and scenario == "mixed":
                    route_cfg.update({
                        "q4_active_repeat_limit_high": 2,
                        "q4_warm_start_m": 75.0,
                        "q4_forward_distances": (200.0, 400.0),
                        "q4_point_order": (
                            0, 1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2,
                            14, 13, 24, 23, 22, 21, 20, 19, 18, 17, 16,
                            15),
                        "model_path": str(ROOT / "learned_search" /
                                           "model_q4_mixed16.json"),
                    })
            report = run_case(mode, args.seed, args.n_sources, scenario, cls, out,
                              scheduler_kwargs=route_cfg)
            row = {"mode": mode, "scenario": scenario, "strategy": name,
                   "seed": args.seed, "source_count": args.n_sources,
                   **report_line(report)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    summary = {"format": "q3q4-v2-equal-budget-comparison-v1",
               "generated_at": datetime.now(timezone.utc).isoformat(),
               "same_case": {"seed": args.seed, "source_count": args.n_sources,
                             "q3_scenario": args.q3_scenario,
                             "q4_scenario": args.q4_scenario},
               "strategies": list(STRATEGIES), "rows": rows,
               "all_complete": all(row["complete"] and row["verifier_all_ok"]
                                    for row in rows),
               "scope": "paired local synthetic benchmark; not official simulator"}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"summary_{args.seed}_{args.n_sources}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(path), "all_complete": summary["all_complete"]}, ensure_ascii=False))
    return 0 if summary["all_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
