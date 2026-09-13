"""How much does the planner's cost actually differ from the legacy estimate?

Records, for every mission the scheduler prices, the planned measurement
sequence length and the two cost estimates.  A large share of stops planning a
single measurement means the corrected model cannot change any decision.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from runtime import V2GameRunner, run_case           # noqa: E402
from production import scheduler_kwargs              # noqa: E402
from learned_search.scheduler import LearnedSearchScheduler   # noqa: E402


class CostAuditRunner(V2GameRunner):
    stats = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats = {"lengths": Counter(), "legacy": 0.0, "plan": 0.0,
                      "by_kind": defaultdict(lambda: [0, 0.0, 0.0])}
        CostAuditRunner.stats = self.stats

    def plan_stop(self, mission):
        plan = super().plan_stop(mission)
        if mission.kind == "clear":
            lengths = [len(plan.get("success", ())), len(plan.get("failure", ()))]
            key = "clear:%d/%d" % (lengths[0], lengths[1])
            self.stats["lengths"][key] += 1
        else:
            k = len(plan.get("measures", ()))
            self.stats["lengths"]["%s:%d" % (mission.kind, k)] += 1
        return plan


def main():
    cases = [("Q3", 16, "random", 101), ("Q4", 16, "mixed", 101),
             ("Q4", 10, "mixed", 303)]
    for mode, n, scenario, seed in cases:
        import runtime as runtime_module
        original = runtime_module.V2GameRunner
        runtime_module.V2GameRunner = CostAuditRunner
        try:
            out = ROOT / "tuning_runs" / "cost_audit" / f"{mode}_{n}_{seed}"
            run_case(mode, seed, n, scenario, LearnedSearchScheduler, out,
                     scheduler_kwargs=scheduler_kwargs(mode))
        finally:
            runtime_module.V2GameRunner = original
        stats = CostAuditRunner.stats
        print("== %s/%d seed %d ==" % (mode, n, seed))
        for key, count in sorted(stats["lengths"].items()):
            print("   %-12s %5d calls" % (key, count))


if __name__ == "__main__":
    main()
