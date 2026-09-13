"""Run the learned-policy + search strategy without pytest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
from runtime import report_line, run_case
from learned_search.scheduler import LearnedSearchScheduler


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("q3", "q4"), default="q3")
    p.add_argument("--seed", type=int, default=101)
    p.add_argument("--n-sources", type=int, default=10)
    p.add_argument("--scenario", default="random")
    p.add_argument("--model", default=None)
    p.add_argument("--output-dir", default=None)
    args = p.parse_args(argv)
    out = Path(args.output_dir or HERE / "runs" /
               f"{args.mode}_{args.seed}_{args.n_sources}_{args.scenario}")
    mode = args.mode.lower()
    scheduler_kwargs = {
        "nbv_mode": "radius",
        "opportunistic_reuse": True,
        "cert_route_mode": "lookahead2",
        "q4_joint_rank": True,
        "q4_residual_sparsify": True,
        "q4_certificate_layout": "sparse25",
        "channel_scan_mode": "selective_clear" if mode == "q3" else "state_aware",
        "active_scan_margin_m": 0.0 if mode == "q3" else 0.0,
        "q3_observation_adaptive": mode == "q3",
        "q3_dynamic_order": mode == "q3",
        "q3_adaptive_radius": False,
        "q3_ring_order": (4, 5, 0, 1, 2, 3) if mode == "q3" else None,
        "q3_risky_clear_radius": 40.0 if mode == "q3" else 0.0,
        "model_path": args.model,
    }
    report = run_case(args.mode, args.seed, args.n_sources, args.scenario,
                      LearnedSearchScheduler, out,
                      scheduler_kwargs=scheduler_kwargs)
    print(json.dumps(report_line(report), ensure_ascii=False, indent=2))
    return 0 if report.get("complete") and report.get("verifier_all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
