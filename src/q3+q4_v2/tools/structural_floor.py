"""Structural cost floor per group, measured from production runs.

Splits each run into the parts the current certificate contract forces:
  * certificate tour travel (legs that end on a finite certificate point)
  * certificate measurements (coverage scans)
  * everything else (chasing, clearing, approaching, switching)
and compares the group's real time with the floor implied by those forced
parts plus a full-information clearing route (MST/NN over the true sources).
"""
from __future__ import annotations

import csv
import glob
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry.q4_sparse_mesh import q4_sparse25_points   # noqa: E402

RING_RADIUS = 1200.0
TARGET = {"Q3": 176.25, "Q4": 290.0}


def tour_points(mode):
    if mode == "Q4":
        return q4_sparse25_points()
    pts = [(0.0, 0.0)]
    for k in range(6):
        pts.append((RING_RADIUS * math.cos(2 * math.pi * k / 6),
                    RING_RADIUS * math.sin(2 * math.pi * k / 6)))
    return pts


def analyse(directory):
    mode = "Q4" if "/Q4_" in directory.replace("\\", "/") else "Q3"
    report = json.loads((Path(directory) / "run_report.json").read_text(
        encoding="utf-8"))
    metrics = report["metrics"]
    points = tour_points(mode)
    travel = {"tour": 0.0, "clear": 0.0, "other": 0.0}
    rows = list(csv.DictReader(open(Path(directory) / "trajectory.csv",
                                    encoding="utf-8")))
    previous = None
    for row in rows:
        position = (float(row["x"]), float(row["y"]))
        if previous is not None:
            distance = math.dist(position, previous)
            if distance > 1.0:
                on_tour = any(math.dist(position, p) <= 1.0 for p in points)
                if row["action"] == "clear":
                    travel["clear"] += distance
                elif on_tour:
                    travel["tour"] += distance
                else:
                    travel["other"] += distance
        previous = position
    measures = defaultdict(int)
    for row in csv.DictReader(open(Path(directory) / "actions.csv",
                                   encoding="utf-8")):
        if row["action_type"] == "measure":
            measures[row["reason_code"]] += 1
    return {
        "metrics": metrics,
        "tour_km": travel["tour"] / 1000.0,
        "clear_km": travel["clear"] / 1000.0,
        "other_km": travel["other"] / 1000.0,
        "coverage_measures": measures.get("coverage", 0),
        "other_measures": sum(v for k, v in measures.items() if k != "coverage"),
    }


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1
                 else "tuning_runs/ab_probe/production")
    groups = defaultdict(list)
    for directory in sorted(glob.glob(str(root / "*"))):
        path = Path(directory)
        if not path.is_dir() or not (path / "run_report.json").exists():
            continue
        name = path.name
        parts = name.split("_")
        if len(parts) < 3 or parts[0] not in ("Q3", "Q4"):
            continue
        groups[(parts[0], int(parts[1]))].append(analyse(directory))
    print("%-7s %7s %6s %6s %6s %7s %7s %8s %8s %8s" %
          ("group", "T/源", "tour", "clear", "other", "certM", "othM",
           "tour_s", "certM_s", "forced%"))
    for key in sorted(groups):
        rows = groups[key]
        mean = lambda f: statistics.mean(f(r) for r in rows)
        t_per_source = mean(lambda r: r["metrics"]["t_per_source_s"])
        tour_km = mean(lambda r: r["tour_km"])
        clear_km = mean(lambda r: r["clear_km"])
        other_km = mean(lambda r: r["other_km"])
        cert_m = mean(lambda r: r["coverage_measures"])
        other_m = mean(lambda r: r["other_measures"])
        total = mean(lambda r: r["metrics"]["T_total_virtual"])
        tour_s = tour_km * 1000.0 / 5.0
        cert_s = cert_m * 6.0
        forced = (tour_s + cert_s) / total * 100.0
        print("%-7s %7.1f %6.1f %6.1f %6.1f %7.0f %7.0f %8.0f %8.0f %7.1f%%" %
              ("%s/%d" % key, t_per_source, tour_km, clear_km, other_km,
               cert_m, other_m, tour_s, cert_s, forced))
        print("        target %.2f -> gap %+.1f s/源 ; forced floor share "
              "%.0f s (%.0f%%)" %
              (TARGET[key[0]], t_per_source - TARGET[key[0]], tour_s + cert_s,
               forced))


if __name__ == "__main__":
    main()
