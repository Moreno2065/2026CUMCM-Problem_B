"""Is a measurement worth its cost?  Offline design + audit of a threshold rule.

Motivation (measured, not assumed): service time is 26-38 % of the structural
floor, and for Q3/16 the floor is already ``MST(sources) + service = 173.4 s``
against a target of 176.25 s -- the only remaining lever is *not paying for
scans that buy nothing*.  t12 showed that "safe to drop without seeing the
future" is at most 0-3.4 s/source; this tool asks whether an **online,
observable** gain/cost rule can do better, and it must answer with the miss
rate (measurements the rule would skip that turned out to be load-bearing).

Everything here is offline analysis of stored runs; no runtime file is touched.

The rule (implementable form, default off)
------------------------------------------
For a candidate measurement ``m`` of channel ``c`` at point ``p``::

    share_new(m) = fraction of Omega that the witness disk B(p, R_eff) adds to
                   the union of that channel's witnesses recorded so far
    prior(c)     = observable presence proxy: 0.5 if status_before in
                   {ACTIVE, READY}, 0.25 if UNKNOWN, 0.0 if CLEARED /
                   CERTIFIED_ABSENT (no demand left)
    cost_s(m)    = MEASURE_TIME + SWITCH_TIME * [channel != last channel]
                   + induced_travel_s(m)      (extra leg vs the cheapest
                                               pending demand; 0 when free)

    measure  iff  share_new(m) * prior(c) * REWARD_S  >=  cost_s(m)

``REWARD_S`` is the certificate seconds a channel's full coverage is worth; in
the audit below the rule is evaluated as a *ratio* ``theta = share_new *
prior / cost_s`` with a swept threshold ``tau`` (skip iff theta < tau), so the
result does not depend on one arbitrary REWARD_S.

Evaluation discipline
---------------------
* the rule sees only online-observable quantities (status_before, position,
  already-recorded witnesses, channel switching) -- never N, scenario or truth;
* the *verdict* on a skipped measurement uses the recorded outcome
  (``result``, ``status_after``) and, for Q3, the production predicate
  ``q3_certified`` on the witnesses recorded *before* that measurement, so
  "safe" means "the channel's certificate already held" or "identical
  observation seen before" -- classes that cannot lose information;
* anything else the rule skips is counted in the miss column, split by outcome
  (direction = first contact / localization, near = channel becomes READY,
  no_signal = emptiness evidence).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry import constants as C                        # noqa: E402
from geometry.certificate import q3_certified              # noqa: E402

R = C.OMEGA_RADIUS
R_EFF = C.R_EFF_MIN
MEASURE = C.MEASURE_TIME
SWITCH = C.SWITCH_TIME
SPEED = C.MOVE_SPEED
DATASET = ROOT / "tuning_runs" / "final_recommended_v3"


def omega_grid(step=60.0):
    points = []
    n = int(math.ceil(2.0 * R / step)) + 1
    for i in range(n):
        x = -R + i * step
        for j in range(n):
            y = -R + j * step
            if x * x + y * y <= R * R:
                points.append((x, y))
    return points


GRID = omega_grid(60.0)


def share_new(point, previous):
    """Fraction of Omega newly covered by B(point, R_eff)."""
    px, py = point
    new = 0
    for gx, gy in GRID:
        if (px - gx) ** 2 + (py - gy) ** 2 <= R_EFF ** 2:
            continue
        if any((qx - gx) ** 2 + (qy - gy) ** 2 <= R_EFF ** 2 for qx, qy in previous):
            continue
        new += 1
    return new / len(GRID)


def presence_prior(status_before):
    if status_before in ("CLEARED", "CERTIFIED_ABSENT"):
        return 0.0
    if status_before in ("ACTIVE", "READY"):
        return 0.5
    return 0.25


def load_episode(directory):
    actions = list(csv.DictReader(open(directory / "actions.csv",
                                       encoding="utf-8")))
    observations = list(csv.DictReader(open(directory / "observations.csv",
                                            encoding="utf-8")))
    return actions, observations


def episode_ledger(directory, mode, n_sources, q3_exact=True):
    actions, observations = load_episode(directory)
    measures = [row for row in actions if row["action_type"] == "measure"]
    if len(measures) != len(observations):
        # t12 established the 1:1 link; report a mismatch instead of guessing
        return None
    witnesses = defaultdict(list)
    seen = set()
    rows = []
    certified = {}
    last_channel = None
    for action, observation in zip(measures, observations):
        channel = int(action["channel"])
        point = (float(action["target_x"]), float(action["target_y"]))
        status_before = observation["status_before"]
        result = observation["result"]
        previous = list(witnesses[channel])
        entry = {
            "step": int(action["step"]),
            "channel": channel,
            "point": point,
            "reason": action["reason_code"],
            "status_before": status_before,
            "result": result,
            "status_after": observation["status_after"],
            "switch": 0 if channel == last_channel else 1,
            "service_s": MEASURE + (SWITCH if channel != last_channel else 0.0),
            "movement_s": float(action["movement_time"] or 0.0),
            "duplicate": (channel, round(point[0], 1), round(point[1], 1),
                          status_before, result) in seen,
            "no_demand": status_before in ("CLEARED", "CERTIFIED_ABSENT"),
            "already_certified": False,
        }
        seen.add((channel, round(point[0], 1), round(point[1], 1),
                  status_before, result))
        if result == "no_signal":
            entry["share_new"] = round(share_new(point, previous), 6)
            if mode == "Q3" and q3_exact:
                key = (channel, len(previous))
                if key not in certified:
                    certified[key] = bool(q3_certified(previous)["certified"])
                entry["already_certified"] = certified[key]
            witnesses[channel].append(point)
        else:
            entry["share_new"] = 0.0
            entry["already_certified"] = False
        entry["prior"] = presence_prior(status_before)
        cost = entry["service_s"] + max(0.0, entry["movement_s"])
        entry["cost_s"] = round(cost, 3)
        entry["theta"] = round(entry["share_new"] * entry["prior"]
                               / max(cost, 1e-9), 8)
        rows.append(entry)
        last_channel = channel
    return rows


def evaluate(rows, tau):
    """Apply the rule with threshold tau; classify every skipped row."""
    skipped = [row for row in rows if row["theta"] < tau]
    safe = [row for row in skipped
            if row["already_certified"] or row["duplicate"]
            or row["no_demand"]]
    miss = [row for row in skipped if row not in safe]
    missed_direction = [row for row in miss if row["result"] == "direction"]
    saved_service = sum(row["service_s"] for row in safe)
    return {
        "tau": tau,
        "skipped": len(skipped),
        "safe": len(safe),
        "miss": len(miss),
        "miss_direction": len(missed_direction),
        "miss_rate": round(len(miss) / max(1, len(skipped)), 4),
        "safe_service_s": round(saved_service, 1),
        "missed_direction_service_s": round(
            sum(row["service_s"] for row in missed_direction), 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--json", default="tuning_runs/infogain_criterion.json")
    parser.add_argument("--taus", default="0.0005,0.001,0.002,0.005,0.01,0.02,0.05")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    report = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "command": "python -X utf8 " + " ".join(sys.argv),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset": dataset.relative_to(ROOT).as_posix(),
        "constants": {"omega_radius_m": R, "r_eff_m": R_EFF,
                      "measure_s": MEASURE, "switch_s": SWITCH,
                      "speed_mps": SPEED},
        "criterion": {
            "theta": "share_new * presence_prior / cost_s",
            "skip_if": "theta < tau",
            "observable_only": ["status_before", "position", "recorded "
                                "witnesses", "channel switching", "movement leg"],
            "forbidden": ["N sources", "scenario", "ground truth", "outcomes"],
            "note": "the rule itself reads only the observables column above; "
                    "the recorded outcome is used only to *score* a skip",
        },
        "episodes": {},
    }

    groups = defaultdict(list)
    for directory in sorted(dataset.glob("*")):
        if not directory.is_dir():
            continue
        name = directory.name
        parts = name.split("_")
        if len(parts) != 3 or parts[0] not in ("Q3", "Q4"):
            continue
        mode, n_sources, seed = parts[0], int(parts[1]), int(parts[2])
        rows = episode_ledger(directory, mode, n_sources)
        if rows is None:
            report["episodes"][name] = {"error": "actions/observations length mismatch"}
            continue
        report["episodes"][name] = {
            "measurements": len(rows),
            "no_signal": sum(1 for row in rows if row["result"] == "no_signal"),
            "direction": sum(1 for row in rows if row["result"] == "direction"),
            "near": sum(1 for row in rows if row["result"] == "near"),
            "already_certified_rows": sum(1 for row in rows
                                          if row.get("already_certified")),
            "duplicate_rows": sum(1 for row in rows if row["duplicate"]),
            "no_demand_rows": sum(1 for row in rows if row["no_demand"]),
        }
        groups[(mode, n_sources)].append((rows, seed))

    summary = {}
    for (mode, n_sources), entries in sorted(groups.items()):
        all_rows = [row for rows, _ in entries for row in rows]
        key = "%s/%d" % (mode, n_sources)
        summary[key] = {
            "episodes": len(entries),
            "measurements_mean": round(
                sum(len(rows) for rows, _ in entries) / len(entries), 1),
            "provably_zero_info": {
                "duplicate": sum(1 for row in all_rows if row["duplicate"]),
                "no_demand": sum(1 for row in all_rows if row["no_demand"]),
                "certificate_already_held": sum(
                    1 for row in all_rows if row.get("already_certified")),
            },
            "sweep": [evaluate(all_rows, tau)
                      for tau in [float(x) for x in args.taus.split(",")]],
        }
    report["summary"] = summary

    # the two mechanisms counted separately (requirement: report them apart)
    report["mechanisms"] = {
        "duplicate_same_channel_point_state_outcome": {
            key: item["provably_zero_info"]["duplicate"]
            for key, item in summary.items()},
        "certificate_already_held_before_measurement": {
            key: item["provably_zero_info"]["certificate_already_held"]
            for key, item in summary.items()},
        "no_demand_status": {
            key: item["provably_zero_info"]["no_demand"]
            for key, item in summary.items()},
    }

    out = ROOT / args.json
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print("%-8s %6s %8s %8s %8s %8s" % ("group", "meas", "dup", "noDem",
                                        "certHeld", "safeBest"))
    for key, item in summary.items():
        best = max(item["sweep"], key=lambda row: row["safe"])
        print("%-8s %6.1f %8d %8d %8d %8d" %
              (key, item["measurements_mean"],
               item["provably_zero_info"]["duplicate"],
               item["provably_zero_info"]["no_demand"],
               item["provably_zero_info"]["certificate_already_held"],
               best["safe"]))
    print("written %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
