#!/usr/bin/env python
"""Run the Q3 v5 implementation from Q3_Q4_V3 against this repository's simulator.

This is a compatibility experiment only.  The solver receives only protocol
responses through ``CompatibilityClient``; source locations are inspected only
after the run to report whether every source was cleared.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve()
OUR_CODE = HERE.parents[1]
REPO = HERE.parents[4]
EXTERNAL_SRC = REPO / "src" / "Q3_Q4_V3" / "code" / "src"

# Both projects expose a top-level module named ``geometry``.  Import our
# simulator first, then temporarily give the external solver its own module
# while its imports are resolved.  Solver functions retain their imported
# geometry functions, after which our package is restored for the simulator.
sys.path.insert(0, str(OUR_CODE))
from experiment.simulator import SimulatorBackend, SyntheticSimulator  # noqa: E402

_our_geometry = {
    name: module for name, module in list(sys.modules.items())
    if name == "geometry" or name.startswith("geometry.")
}
for _name in _our_geometry:
    sys.modules.pop(_name, None)
sys.path.insert(0, str(EXTERNAL_SRC))
from q3_optimizer_v5 import solve_optimized_v5  # noqa: E402
for _name in [name for name in list(sys.modules)
              if name == "geometry" or name.startswith("geometry.")]:
    sys.modules.pop(_name, None)
sys.modules.update(_our_geometry)


class CompatibilityClient:
    """Expose the tiny ``act`` interface expected by the external Q3 solver."""

    def __init__(self, simulator: SyntheticSimulator) -> None:
        self._backend = SimulatorBackend(simulator, robot_id="XCOMPAT")
        self._simulator = simulator
        self.position = [0.0, 0.0]
        self.channel = 1
        self.virtual = 0.0
        self.rows: list[dict] = []

    def act(self, path: str, position=None, channel=None) -> dict:
        point = None if position is None else [float(position[0]), float(position[1])]
        if path == "/enter":
            response = self._backend.enter()
        elif path == "/exit":
            response = self._backend.exit()
        elif path == "/measure":
            if point is None or channel is None:
                raise ValueError("/measure requires position and channel")
            response = self._backend.measure(tuple(point), int(channel))
            self.channel = int(channel)
        elif path == "/clear":
            if point is None or channel is None:
                raise ValueError("/clear requires position and channel")
            response = self._backend.clear(tuple(point), int(channel))
        else:
            raise ValueError("unsupported endpoint: %s" % path)

        self.position = [float(self._backend.position[0]), float(self._backend.position[1])]
        self.virtual = float(self._backend.virtual_time)
        result = dict(response)
        self.rows.append({
            "path": path,
            "position": point,
            "channel": None if channel is None else int(channel),
            "response": result.copy(),
        })
        return result


def one(seed: int, n_sources: int, scenario: str, error_field_type: str) -> dict:
    simulator = SyntheticSimulator("Q3", seed, n_sources=n_sources,
                                   scenario=scenario,
                                   error_field_type=error_field_type)
    client = CompatibilityClient(simulator)
    started = time.perf_counter()
    error = None
    result = None
    try:
        client.act("/enter")
        result = solve_optimized_v5(client)
        client.act("/exit")
    except Exception as exc:  # Preserve failed cases for robustness reporting.
        error = "%s: %s" % (type(exc).__name__, exc)
        if simulator.entered and not simulator.exited:
            try:
                client.act("/exit")
            except Exception:
                pass
    clears = [r for r in client.rows if r["path"] == "/clear"]
    measures = [r for r in client.rows if r["path"] == "/measure"]
    previous = [0.0, 0.0]
    move_distance = 0.0
    for row in client.rows:
        if row["position"] is not None:
            move_distance += math.dist(previous, row["position"])
            previous = row["position"]
    previous_measure_channel = None
    switches = 0
    for row in measures:
        if previous_measure_channel is not None and row["channel"] != previous_measure_channel:
            switches += 1
        previous_measure_channel = row["channel"]
    clear_successes = sum(
        r["response"].get("clear_result") == "success" for r in clears
    )
    clear_failures = len(clears) - clear_successes
    cleared = sum(1 for source in simulator.sources if source.cleared)
    complete = error is None and cleared == len(simulator.sources) and simulator.exited
    return {
        "seed": seed,
        "source_count": len(simulator.sources),
        "scenario": scenario,
        "error_field_type": error_field_type,
        "complete": complete,
        "error": error,
        "total_s": client.virtual,
        "seconds_per_source": client.virtual / len(simulator.sources),
        "cleared": cleared,
        "measures": len(measures),
        "clear_attempts": len(clears),
        "clear_successes": clear_successes,
        "move_distance_m": move_distance,
        "time_move_s": move_distance / 5.0,
        "time_measure_s": 5.0 * len(measures),
        "switches": switches,
        "time_switch_s": float(switches),
        "time_clear_s": 5.0 * clear_successes + 3.0 * clear_failures,
        "actions": len(client.rows),
        "wall_clock_s": time.perf_counter() - started,
        "solver_result_keys": [] if result is None else sorted(result),
    }


def summarize(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["complete"]]
    values = sorted(row["seconds_per_source"] for row in valid)
    def percentile(q: float):
        if not values:
            return None
        index = (len(values) - 1) * q
        lo, hi = int(index), min(int(index) + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return {
        "runs": len(rows),
        "complete_runs": len(valid),
        "failure_runs": len(rows) - len(valid),
        "mean_seconds_per_source": None if not values else sum(values) / len(values),
        "median_seconds_per_source": percentile(0.5),
        "p90_seconds_per_source": percentile(0.9),
        "min_seconds_per_source": None if not values else values[0],
        "max_seconds_per_source": None if not values else values[-1],
        "under_200_runs": sum(value < 200.0 for value in values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="101,202,303,404,505,606,707,808,909,1001,1102,1203")
    parser.add_argument("--n-sources", type=int, default=16)
    parser.add_argument("--scenario", default="random")
    parser.add_argument("--error-field-type",
                        choices=("random_fixed", "boundary", "structured"),
                        default="random_fixed")
    parser.add_argument("--output-dir", type=Path,
                        default=OUR_CODE / "output" / "fresh_q3_v5_on_ours")
    args = parser.parse_args()
    seeds = [int(token.strip()) for token in args.seeds.split(",") if token.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, seed in enumerate(seeds, 1):
        row = one(seed, args.n_sources, args.scenario, args.error_field_type)
        rows.append(row)
        print("%d/%d seed=%s complete=%s s/source=%.3f%s" % (
            index, len(seeds), seed, row["complete"], row["seconds_per_source"],
            "" if row["error"] is None else " error=" + row["error"]), flush=True)
    report = {
        "scope": "Fresh cross-implementation experiment: external Q3 v5 solver on this repository's SyntheticSimulator.",
        "solver_path": str(EXTERNAL_SRC / "q3_optimizer_v5.py"),
        "simulator_path": str(OUR_CODE / "experiment" / "simulator.py"),
        "n_sources": args.n_sources,
        "scenario": args.scenario,
        "error_field_type": args.error_field_type,
        "seeds": seeds,
        "summary": summarize(rows),
        "rows": rows,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "rows.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = [key for key in rows[0] if key != "solver_result_keys"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fields})
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("RESULT_DIRECTORY=" + str(args.output_dir))
    return 0 if report["summary"]["failure_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
