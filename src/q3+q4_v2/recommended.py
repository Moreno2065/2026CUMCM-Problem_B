"""Run the observation-only production controller for one Q3 or Q4 case.

The command-line source count and scenario are passed to the simulator and
used in the output directory name only.  The scheduler never uses either as
an online hint.  Q3 uses observation-adaptive scanning and a finite fallback;
Q4 uses one fixed learned/search policy with a rolling candidate pool and the
exact finite certificate fallback.  The Q4 pool only changes action order and
may attach a small number of ACTIVE measurements at the same stop; it never
relaxes the completion standard.  Offline scenario labels remain available for
audits without leaking them into the submitted decision policy.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import report_line, run_case
from production import scheduler_kwargs
from learned_search.scheduler import LearnedSearchScheduler
RECOMMENDED = {
    "Q3": LearnedSearchScheduler,
    "Q4": LearnedSearchScheduler,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("Q3", "Q4"), required=True)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--n-sources", type=int, default=10)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "comparison_runs" / "recommended")
    args = parser.parse_args(argv)
    mode = args.mode.upper()
    scenario = args.scenario or ("random" if mode == "Q3" else "mixed")
    # The production configuration lives in production.py so the benchmark
    # entry and the official entry cannot drift apart.
    common = scheduler_kwargs(mode)
    controller = RECOMMENDED[mode]
    out = args.output / f"{mode.lower()}_{args.seed}_{args.n_sources}_{scenario}"
    report = run_case(mode, args.seed, args.n_sources, scenario,
                      controller, out, scheduler_kwargs=common)
    print(report_line(report))
    return 0 if report.get("complete") and report.get("verifier_all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
