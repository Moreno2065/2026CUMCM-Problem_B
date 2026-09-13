"""Decompose a completed Q4 run after its final channel discovery."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _open_path(start, points):
    """Exact open Held-Karp length from start through every point."""
    count = len(points)
    if not count:
        return 0.0
    dp = {(1 << i, i): math.dist(start, points[i]) for i in range(count)}
    for mask in range(1, 1 << count):
        for last in range(count):
            key = (mask, last)
            if key not in dp:
                continue
            value = dp[key]
            for nxt in range(count):
                if mask & (1 << nxt):
                    continue
                new_key = (mask | (1 << nxt), nxt)
                candidate = value + math.dist(points[last], points[nxt])
                if candidate < dp.get(new_key, float("inf")):
                    dp[new_key] = candidate
    full = (1 << count) - 1
    return min(dp[(full, last)] for last in range(count))


def audit(directory):
    directory = Path(directory)
    observations = _rows(directory / "observations.csv")
    trajectory = _rows(directory / "trajectory.csv")
    truth = json.loads((directory / "ground_truth.json").read_text(
        encoding="utf-8"))
    discoveries = [row for row in observations
                   if row["status_before"] == "UNKNOWN" and
                   row["status_after"] == "ACTIVE"]
    final = max(discoveries, key=lambda row: float(row["virtual_time"]))
    final_time = float(final["virtual_time"])
    start = (float(final["x"]), float(final["y"]))
    successes = {}
    for row in trajectory:
        if row["action"] == "clear" and row["result"] == "success":
            successes[int(row["channel"])] = float(row["virtual_time"])
    remaining = [source for source in truth
                 if successes.get(int(source["channel"]), float("inf")) >
                 final_time]
    actual_distance = 0.0
    prior = None
    for row in trajectory:
        time = float(row["virtual_time"])
        point = (float(row["x"]), float(row["y"]))
        if time < final_time:
            continue
        if prior is None:
            prior = start
        if point != prior:
            actual_distance += math.dist(prior, point)
        prior = point
    oracle = _open_path(start, [(float(source["x"]), float(source["y"]))
                                for source in remaining])
    return {
        "directory": str(directory),
        "last_discovery_time_s": final_time,
        "remaining_sources": len(remaining),
        "actual_tail_distance_m": actual_distance,
        "truth_open_path_distance_m": oracle,
        "online_localization_and_route_overhead_m": actual_distance - oracle,
        "ratio": actual_distance / oracle if oracle else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="+")
    args = parser.parse_args()
    print(json.dumps([audit(path) for path in args.directories], indent=2))


if __name__ == "__main__":
    main()
