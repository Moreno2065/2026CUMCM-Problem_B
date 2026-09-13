"""Audit: does the scheduler price the action sequence the runner executes?

Runs real cases and, for every executed mission, compares
``V2GameRunner.plan_stop(mission)`` with the actions that were actually
appended to the ledger by ``_execute``.  Any systematic difference means the
planner is optimising a cost model that does not describe the executor.

Reported per case:
  matched   - planned sequence equals executed sequence
  truncated - execution stopped or skipped terminal channels at the
              cardinality cap, so it is a proper prefix/subsequence
  mismatch  - any other difference (the real failure mode)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from runtime import V2GameRunner, run_case           # noqa: E402
from production import scheduler_kwargs              # noqa: E402
from learned_search.scheduler import LearnedSearchScheduler   # noqa: E402


class AuditingRunner(V2GameRunner):
    LAST = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit = {"matched": 0, "truncated": 0, "mismatch": 0}
        self.mismatch_samples = []
        AuditingRunner.LAST = self

    def _execute(self, mission):
        plan = self.plan_stop(mission)
        start = len(self.actions)
        super()._execute(mission)
        executed = [(row["action_type"], row["channel"])
                    for row in self.actions[start:]]
        if mission.kind == "clear":
            expected_clear = [("clear", mission.channel)]
            for branch in ("success", "failure"):
                planned = expected_clear + [("measure", c)
                                            for c in plan.get(branch, ())]
                if executed == planned:
                    self.audit["matched"] += 1
                    return
            # Try truncation-at-cap and rejected-measure tolerance.
            for branch in ("success", "failure"):
                planned = expected_clear + [("measure", c)
                                            for c in plan.get(branch, ())]
                if (len(executed) < len(planned) and
                        executed == planned[:len(executed)]):
                    self.audit["truncated"] += 1
                    return
            self.audit["mismatch"] += 1
            if len(self.mismatch_samples) < 3:
                self.mismatch_samples.append(
                    (mission.kind, mission.channel, executed,
                     plan.get("success"), plan.get("failure")))
            return
        planned = [("measure", c) for c in plan.get("measures", ())]
        planned_iter = iter(planned)
        is_subsequence = all(
            any(candidate == item for candidate in planned_iter)
            for item in executed)
        if executed == planned:
            self.audit["matched"] += 1
        elif len(executed) < len(planned) and executed == planned[:len(executed)]:
            self.audit["truncated"] += 1
        elif (mission.kind == "scan"
              and self._cardinality_reached()
              and len(executed) < len(planned)
              and is_subsequence):
            # Once the 16th positive is known, runtime skips planned channels
            # that have become terminal.  It may still execute a later ACTIVE
            # entry before the cardinality break, so the legal execution is an
            # order-preserving subsequence rather than necessarily a prefix.
            self.audit["truncated"] += 1
        else:
            self.audit["mismatch"] += 1
            if len(self.mismatch_samples) < 3:
                self.mismatch_samples.append(
                    (mission.kind, mission.channel, executed,
                     plan.get("measures"), None))


def run_case_audited(mode, seed, n, scenario, extra=None):
    """Run one case with the auditing runner in place of the default one.

    ``extra`` enables experimental switches, so the audit covers the
    configuration it claims to (the joint stop/scan-set action is off in the
    production configuration and would otherwise go unchecked).
    """
    import runtime as runtime_module
    original = runtime_module.V2GameRunner
    runtime_module.V2GameRunner = AuditingRunner
    try:
        out = ROOT / "tuning_runs" / "plan_audit" / (
            "%s_%s_%d" % (mode, "extra" if extra else "prod", n))
        cfg = scheduler_kwargs(mode)
        if extra:
            cfg.update(extra)
        report = run_case(mode, seed, n, scenario, LearnedSearchScheduler,
                          out, scheduler_kwargs=cfg)
    finally:
        runtime_module.V2GameRunner = original
    runner = AuditingRunner.LAST
    return (runner.audit if runner is not None else None), report


def main():
    configurations = [
        ("production", None),
        ("joint action + interleave + angle gate",
         {"q3_interleave": True, "joint_action": True,
          "active_scan_angle_gate_deg": 30.0}),
        ("joint action + scan spacing",
         {"q3_interleave": True, "joint_action": True,
          "q3_scan_spacing_m": 800.0, "active_scan_angle_gate_deg": 30.0}),
    ]
    cases = [("Q3", 16, "random"), ("Q3", 10, "random"), ("Q4", 16, "mixed"),
             ("Q4", 10, "mixed")]
    seeds = [101, 303, 505]
    failures = 0
    for label, extra in configurations:
        total = {"matched": 0, "truncated": 0, "mismatch": 0}
        incomplete = 0
        for mode, n, scenario in cases:
            for seed in seeds:
                audit, report = run_case_audited(mode, seed, n, scenario,
                                                 extra)
                if not report.get("complete"):
                    incomplete += 1
                if audit is None:
                    continue
                for key in total:
                    total[key] += audit[key]
        failures += total["mismatch"]
        print("config: %-38s matched=%-4d truncated=%-3d mismatch=%-2d "
              "incomplete=%d" % (label, total["matched"], total["truncated"],
                                 total["mismatch"], incomplete))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
