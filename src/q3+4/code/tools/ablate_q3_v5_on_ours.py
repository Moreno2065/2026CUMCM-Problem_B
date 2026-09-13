#!/usr/bin/env python
"""Fresh Q3-v5 ablation on this repository's simulator (no historical results)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from run_q3_v5_on_ours import CompatibilityClient, SyntheticSimulator
from q3_optimizer_v5 import SELECTED_PARAMETERS, solve


def one(seed: int, params: dict) -> dict:
    sim = SyntheticSimulator("Q3", seed, n_sources=16, scenario="random")
    client = CompatibilityClient(sim)
    started = time.perf_counter()
    error = None
    try:
        client.act("/enter")
        solve(client, **params)
        client.act("/exit")
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        if sim.entered and not sim.exited:
            try:
                client.act("/exit")
            except Exception:
                pass
    cleared = sum(source.cleared for source in sim.sources)
    return {
        "seed": seed,
        "complete": error is None and sim.exited and cleared == len(sim.sources),
        "error": error,
        "seconds_per_source": client.virtual_time if hasattr(client, "virtual_time") else client.virtual / 16.0,
        "total_s": client.virtual,
        "cleared": cleared,
        "measures": sum(row["path"] == "/measure" for row in client.rows),
        "clear_attempts": sum(row["path"] == "/clear" for row in client.rows),
        "wall_clock_s": time.perf_counter() - started,
    }


def summarize(rows: list[dict]) -> dict:
    values = np.asarray([row["total_s"] / 16.0 for row in rows if row["complete"]])
    return {
        "runs": len(rows),
        "complete_runs": len(values),
        "mean_seconds_per_source": None if not len(values) else float(values.mean()),
        "median_seconds_per_source": None if not len(values) else float(np.median(values)),
        "p90_seconds_per_source": None if not len(values) else float(np.quantile(values, .9)),
        "mean_measures": float(np.mean([row["measures"] for row in rows], dtype=float)),
        "mean_clear_attempts": float(np.mean([row["clear_attempts"] for row in rows], dtype=float)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="101,202,303,404,505,606,707,808,909,1001,1102,1203")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "output" / "fresh_q3_v5_ablation_16x12")
    args = parser.parse_args()
    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()]
    base = dict(SELECTED_PARAMETERS)
    configs = {
        "selected": base,
        "no_shared_search": dict(base, share_at_search=False),
        "no_initial_probe": dict(base, probe=0.0),
        "no_trial_clear": dict(base, trial_radius=0.0),
        "legacy_route_order": dict(base, route_mode="v4"),
    }
    reports = {}
    for label, params in configs.items():
        rows = [one(seed, params) for seed in seeds]
        reports[label] = {"parameters": params, "summary": summarize(rows), "rows": rows}
        print(label, json.dumps(reports[label]["summary"], ensure_ascii=False), flush=True)
    output = {"scope": "Fresh ablation on our SyntheticSimulator; no external historical result data.",
              "source_count": 16, "scenario": "random", "seeds": seeds, "configs": reports}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_DIRECTORY=" + str(args.output_dir))
    return 0 if all(data["summary"]["complete_runs"] == len(seeds) for data in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
