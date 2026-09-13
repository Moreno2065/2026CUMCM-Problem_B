"""Entry-equivalence check: the benchmark entry and the official entry must
run the identical policy on the identical case.

Both entries are executed on the same synthetic case and their full ledger is
compared.  Any drift (a switch present in one path only, a different runner
configuration, a scheduler default silently taking over) shows up as a
different total time, measure count or clear count.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [("q3", 16, "random", 101), ("q4", 16, "mixed", 101),
         ("q4", 10, "mixed", 303)]


def run_benchmark(mode, n, scenario, seed):
    sys.path.insert(0, str(ROOT))
    from runtime import run_case
    from production import scheduler_kwargs
    from learned_search.scheduler import LearnedSearchScheduler
    out = ROOT / "tuning_runs" / "entry_equivalence" / \
        f"{mode}_{n}_{seed}_bench"
    report = run_case(mode.upper(), seed, n, scenario,
                      LearnedSearchScheduler, out,
                      scheduler_kwargs=scheduler_kwargs(mode.upper()))
    return report["metrics"]


def run_official(mode, n, scenario, seed):
    out = ROOT / "runs" / f"_entry_equiv_{mode}_{n}_{seed}"
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "run.py"),
           "--mode", mode, "--sim", "synthetic", "--seed", str(seed),
           "--n-sources", str(n), "--scenario", scenario,
           "--output-dir", str(out)]
    subprocess.run(cmd, cwd=str(ROOT), check=True,
                   stdout=subprocess.DEVNULL)
    metrics_path = out / "metrics.json"
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def main():
    keys = ("T_total_virtual", "total_move_distance_m", "n_measures",
            "n_switches", "n_clear_attempts", "n_clear_success",
            "cleared_count", "certified_absent_count")
    failures = 0
    for mode, n, scenario, seed in CASES:
        bench = run_benchmark(mode, n, scenario, seed)
        official = run_official(mode, n, scenario, seed)
        diffs = {key: (bench.get(key), official.get(key))
                 for key in keys if bench.get(key) != official.get(key)}
        status = "OK" if not diffs else "MISMATCH"
        if diffs:
            failures += 1
        print("%-18s %s" % ("%s/%d/%s" % (mode, n, scenario), status))
        if diffs:
            for key, (a, b) in diffs.items():
                print("    %-24s benchmark=%s official=%s" % (key, a, b))
    print("entry equivalence: %d/%d cases identical" %
          (len(CASES) - failures, len(CASES)))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
