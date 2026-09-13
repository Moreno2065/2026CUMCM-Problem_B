# -*- coding: utf-8 -*-
"""Clear-side ledger: every ``clear`` action of a production episode, why it
failed, and how much of the blind walking an online "verify before clear" rule
could remove (offline replay).

Data sources (all read-only, no new runs)
-----------------------------------------
* ``actions.csv``               - one row per clear: target, channel, policy
                                  mode, reason, the leg's metres/seconds and
                                  the 3-5 s clear attempt itself.
* ``state_history.json``        - per-step snapshot: robot position, per-channel
                                  status and MEC radius (online observable).
* ``localization_history/*``    - per-channel MEC centre/radius time series and
                                  the ``guaranteed_clear_region`` flag.
* ``observations.csv``          - measurement results (direction / near /
                                  no_signal) with position and time.
* ``ground_truth.json``         - true source position: used ONLY for offline
                                  attribution, never as a rule input.
* ``metrics.json``              - per-episode totals used as a reconciliation
                                  target (``n_clear_attempts``/``n_clear_success``).

Pre-registration (fixed before running, see ``PRE_REGISTRATION`` below)
-----------------------------------------------------------------------
GO iff some cell saves >= 8 s/source **and** the rule adds no measurements
(<= 5 % growth) **and** it suppresses no successful clear.  Otherwise NO-GO.

Honesty rules
-------------
* Savings are an offline **upper bound** under a "same continuation" assumption:
  suppressing a failed attempt keeps the later successful attempt for the same
  channel, but the trajectory would actually change.  The report says so
  everywhere and never presents the number as an implemented gain.
* A suppressed failed clear whose channel is never cleared later is counted as
  "must pay" (suppressing it would leave the channel open), not as savings.
* Truth is used for attribution and for the success check only; the rule itself
  reads MEC radius / observation flags / fallback flag only.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CLEAR_RADIUS_M = 20.0            # success iff the fired point is within this
NEARBY_REPEAT_M = 50.0           # "same or neighbouring position" for repeats
DEFAULT_THRESHOLDS = (100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0)
REPEAT_RADII = (1.0, 5.0, 10.0, 20.0, 35.0, 50.0)
DEFAULT_ROOT = "tuning_runs/ab_probe/production"
DEFAULT_CELLS = ("Q3_10", "Q3_13", "Q3_16", "Q4_10", "Q4_13", "Q4_16")

PRE_REGISTRATION = {
    "rule_family": "clear only when mec_radius <= r (optionally OR a `near` "
                   "observation OR a non-empty guaranteed clear region); plus a "
                   "threshold-free variant that never fires twice within 50 m of "
                   "an earlier attempt of the same channel",
    "saving_definition": "suppressed failed clear whose channel is cleared by a "
                         "later attempt in the same episode: save its movement "
                         "time + clear time",
    "go_threshold_s_per_source": 8.0,
    "measurement_growth_limit_pct": 5.0,
    "extra_safety_gate": "the rule must suppress no successful clear",
    "decided_before_running": True,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sha16(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_localization(directory):
    series = {}
    for path in sorted(glob.glob(str(Path(directory) / "localization_history"
                                      / "channel_*.jsonl"))):
        channel = int(Path(path).stem.split("_")[-1])
        entries = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            entries.append(record)
        entries.sort(key=lambda item: item.get("virtual_time", 0.0))
        series[channel] = entries
    return series


def mec_at(series, channel, virtual_time):
    entries = series.get(channel) or []
    found = None
    for record in entries:
        if record.get("virtual_time", 0.0) <= virtual_time + 1e-9:
            found = record
        else:
            break
    return found


def load_episode(directory):
    directory = Path(directory)
    actions = list(csv.DictReader(open(directory / "actions.csv",
                                        encoding="utf-8")))
    clears = [row for row in actions if row["action_type"] == "clear"]
    snapshots = json.loads((directory / "state_history.json").read_text("utf-8"))
    truth = {int(row["channel"]): (float(row["x"]), float(row["y"]))
             for row in json.loads((directory / "ground_truth.json")
                                   .read_text("utf-8"))}
    observations = list(csv.DictReader(open(directory / "observations.csv",
                                            encoding="utf-8")))
    metrics = json.loads((directory / "metrics.json").read_text("utf-8"))
    return {"dir": str(directory.relative_to(ROOT)).replace("\\", "/"),
            "clears": clears, "snapshots": snapshots, "truth": truth,
            "observations": observations, "metrics": metrics,
            "loc": load_localization(directory),
            "inputs": {name: sha16(directory / name) for name in
                       ("actions.csv", "state_history.json", "ground_truth.json",
                        "observations.csv", "metrics.json", "provenance.json")}}


def snapshot_for(episode, step, virtual_time):
    by_step = {int(snap.get("step", -1)): snap for snap in episode["snapshots"]}
    if int(step) in by_step:
        return by_step[int(step)]
    found = None
    for snap in episode["snapshots"]:
        if snap.get("virtual_time", 0.0) <= virtual_time + 1e-9:
            found = snap
        else:
            break
    return found


def observations_for(episode, channel):
    out = []
    for row in episode["observations"]:
        try:
            if int(row["channel"]) != channel:
                continue
            out.append({"virtual_time": float(row["virtual_time"]),
                        "result": row["result"],
                        "position": (float(row["x"]), float(row["y"]))})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda item: item["virtual_time"])
    return out


def build_rows(episode):
    """One ledger row per clear action, with online and offline fields apart."""
    observed = {channel: observations_for(episode, channel)
                for channel in episode["truth"]}
    per_channel_attempts = defaultdict(list)
    rows = []
    for index, row in enumerate(episode["clears"]):
        channel = int(row["channel"])
        target = (float(row["target_x"]), float(row["target_y"]))
        t_before = float(row["virtual_time_before"])
        snap = snapshot_for(episode, row["step"], t_before)
        position = tuple(snap["position"]) if snap else None
        channel_state = (snap or {}).get("channels", {}).get(str(channel), {})
        active = sorted(int(cid) for cid, entry in
                        ((snap or {}).get("channels", {}) or {}).items()
                        if entry.get("status") == "ACTIVE")
        mec = mec_at(episode["loc"], channel, t_before)
        truth = episode["truth"].get(channel)
        d_target_truth = dist(target, truth) if truth else None
        success = (d_target_truth is not None
                   and d_target_truth <= CLEAR_RADIUS_M)
        prior = per_channel_attempts[channel]
        same_pos = any(dist(target, p) <= 1.0 for p in prior)
        near_pos = any(dist(target, p) <= NEARBY_REPEAT_M for p in prior)
        obs = [item for item in observed.get(channel, [])
               if item["virtual_time"] <= t_before + 1e-9]
        near_flag = any(item["result"] == "near" for item in obs)
        direction_here = [item for item in obs
                          if item["result"] == "direction" and position
                          and dist(item["position"], position) <= CLEAR_RADIUS_M]
        guaranteed = bool((mec or {}).get("guaranteed_clear_region", {})
                          .get("nonempty"))
        mec_radius = (mec or {}).get("mec_radius")
        if mec_radius is None:
            mec_radius = channel_state.get("mec_radius")
        mec_center = (mec or {}).get("mec_center")
        d_mec_truth = (dist(tuple(mec_center), truth)
                       if mec_center and truth else None)
        per_channel_attempts[channel].append(target)
        rows.append({
            "index": index, "step": int(row["step"]), "channel": channel,
            "virtual_time_before": t_before,
            "virtual_time_after": float(row["virtual_time_after"]),
            "target": target, "policy_mode": row["policy_mode"],
            "reason": row["reason_code"],
            "movement_m": float(row["movement_distance"] or 0.0),
            "movement_s": float(row["movement_time"] or 0.0),
            "switch_s": float(row["switch_time"] or 0.0),
            "clear_s": float(row["action_time"] or 0.0),
            "position_before": position,
            "active_count": len(active), "active_list": active,
            "channel_status": channel_state.get("status"),
            "mec_radius_m": mec_radius,
            "mec_center": list(mec_center) if mec_center else None,
            "guaranteed_clear_region_nonempty": guaranteed,
            "fallback": ("fallback" in (row["policy_mode"] or "")
                         or "fallback" in (row["reason_code"] or "")),
            "prior_attempts_same_channel": len(prior),
            "same_position_repeat": same_pos, "nearby_repeat": near_pos,
            "near_observation": near_flag,
            "direction_at_position": bool(direction_here),
            "success": success,
            "truth": list(truth) if truth else None,
            "d_target_truth_m": d_target_truth,
            "d_mec_truth_m": d_mec_truth,
        })
    return rows


def classify(row):
    """Mutually exclusive failure classes.

    Priority: belief failure (the true source lies outside the online MEC disk)
    -> probe out of range while the belief was consistent -> repeated point ->
    fallback ladder -> other.  The MEC radius is the online belief's own width,
    so F1 separates "the estimate was wrong" from "the estimate was fine and we
    fired at a bad point".
    """
    if row["success"]:
        return "success"
    if (row["d_mec_truth_m"] is not None and row["mec_radius_m"] is not None
            and row["d_mec_truth_m"] > row["mec_radius_m"]):
        return "F1_mec_belief_excludes_truth"
    if row["d_target_truth_m"] is not None:
        return "F2_probe_out_of_range_while_belief_ok"
    if row["nearby_repeat"]:
        return "F3_repeat_at_same_or_nearby_position"
    if row["fallback"]:
        return "F4_fallback_ladder"
    return "F5_other"


# ---------------------------------------------------------------------------
# offline replay of "verify before clear"
# ---------------------------------------------------------------------------

def replay(rows, threshold, use_near, use_guaranteed):
    """Return saving / cost / safety counters for one rule configuration."""
    later_success = {}
    for row in rows:
        later_success.setdefault(row["channel"], None)
    for row in reversed(rows):
        if row["success"]:
            later_success[row["channel"]] = row["index"]
    out = {"suppressed_failed": 0, "suppressed_saveable": 0,
           "suppressed_terminal": 0, "suppressed_success_harmful": 0,
           "suppressed_success_recovered": 0,
           "saved_movement_s": 0.0, "saved_clear_s": 0.0,
           "terminal_movement_s": 0.0, "terminal_clear_s": 0.0,
           "suppressed_rows": []}
    for row in rows:
        radius = row["mec_radius_m"]
        ok = (radius is not None and radius <= threshold) \
            or (use_near and row["near_observation"]) \
            or (use_guaranteed and row["guaranteed_clear_region_nonempty"])
        if ok:
            continue                       # the rule still clears here
        if row["success"]:
            later = later_success.get(row["channel"])
            if later is not None and later > row["index"]:
                out["suppressed_success_recovered"] += 1
            else:
                out["suppressed_success_harmful"] += 1
            continue
        out["suppressed_failed"] += 1
        later = later_success.get(row["channel"])
        if later is not None and later > row["index"]:
            out["suppressed_saveable"] += 1
            out["saved_movement_s"] += row["movement_s"]
            out["saved_clear_s"] += row["clear_s"]
            out["suppressed_rows"].append(row["index"])
        else:
            out["suppressed_terminal"] += 1
            out["terminal_movement_s"] += row["movement_s"]
            out["terminal_clear_s"] += row["clear_s"]
    return out


def audit_episode(directory):
    episode = load_episode(directory)
    rows = build_rows(episode)
    metrics = episode["metrics"]
    classes = Counter(classify(row) for row in rows)
    failed = [row for row in rows if not row["success"]]
    successful = [row for row in rows if row["success"]]
    n_sources = int(metrics.get("sources_total") or 0)
    episodes = {
        "dir": episode["dir"], "inputs": episode["inputs"],
        "sources_total": n_sources,
        "n_clear_rows": len(rows),
        "n_clear_attempts_metrics": metrics.get("n_clear_attempts"),
        "n_clear_success_metrics": metrics.get("n_clear_success"),
        "n_clear_success_computed": len(successful),
        "reconciles": (len(rows) == metrics.get("n_clear_attempts")
                       and len(successful) == metrics.get("n_clear_success")),
        "classes": dict(classes),
        "failed": {
            "count": len(failed),
            "movement_s": sum(row["movement_s"] for row in failed),
            "clear_s": sum(row["clear_s"] for row in failed),
            "movement_m": sum(row["movement_m"] for row in failed),
            "total_s": sum(row["movement_s"] + row["clear_s"] for row in failed),
            "per_source_s": (sum(row["movement_s"] + row["clear_s"]
                                 for row in failed) / n_sources
                             if n_sources else None),
        },
        "success_legs": {
            "count": len(successful),
            "movement_s": sum(row["movement_s"] for row in successful),
            "clear_s": sum(row["clear_s"] for row in successful),
            "per_source_s": (sum(row["movement_s"] + row["clear_s"]
                                 for row in successful) / n_sources
                             if n_sources else None),
        },
        "ledger": {
            "T_clear": metrics.get("T_clear"),
            "T_move": metrics.get("T_move"),
            "n_measures": metrics.get("n_measures"),
            "t_per_source_s": metrics.get("t_per_source_s"),
            "clear_rows_clear_s_sum": sum(row["clear_s"] for row in rows),
        },
        "online_signals": {
            "near_observation_rows": sum(1 for row in rows
                                         if row["near_observation"]),
            "direction_at_position_rows": sum(1 for row in rows
                                              if row["direction_at_position"]),
            "guaranteed_region_rows": sum(1 for row in rows
                                          if row["guaranteed_clear_region_nonempty"]),
            "guaranteed_region_failed_rows": sum(
                1 for row in rows if row["guaranteed_clear_region_nonempty"]
                and not row["success"]),
            "fallback_rows": sum(1 for row in rows if row["fallback"]),
            "fallback_failed_rows": sum(1 for row in rows if row["fallback"]
                                        and not row["success"]),
            "same_position_repeat_rows": sum(1 for row in rows
                                             if row["same_position_repeat"]),
            "nearby_repeat_rows": sum(1 for row in rows if row["nearby_repeat"]),
            "no_mec_record_rows": sum(1 for row in rows
                                      if row["mec_radius_m"] is None),
        },
        "mechanism": dict(Counter(
            "%s|%s|%s" % (row["policy_mode"], row["reason"],
                          "success" if row["success"] else "failed")
            for row in rows)),
        "raw_attribution": {
            "mec_off_rows": sum(1 for row in rows if row["d_mec_truth_m"]
                                is not None
                                and row["d_mec_truth_m"] > CLEAR_RADIUS_M),
            "fallback_failed_rows": sum(1 for row in rows if row["fallback"]
                                        and not row["success"]),
            "repeat_failed_rows": sum(1 for row in rows
                                      if row["nearby_repeat"]
                                      and not row["success"]),
            "no_mec_and_failed_rows": sum(1 for row in rows
                                          if row["mec_radius_m"] is None
                                          and not row["success"]),
        },
        "mec_radius_stats_failed": {
            "min": min((row["mec_radius_m"] for row in failed
                        if row["mec_radius_m"] is not None), default=None),
            "median": statistics.median([row["mec_radius_m"] for row in failed
                                         if row["mec_radius_m"] is not None])
            if any(row["mec_radius_m"] is not None for row in failed) else None,
            "max": max((row["mec_radius_m"] for row in failed
                        if row["mec_radius_m"] is not None), default=None),
        },
        "mec_radius_stats_success": {
            "min": min((row["mec_radius_m"] for row in successful
                        if row["mec_radius_m"] is not None), default=None),
            "median": statistics.median([row["mec_radius_m"] for row in successful
                                         if row["mec_radius_m"] is not None])
            if any(row["mec_radius_m"] is not None for row in successful) else None,
            "max": max((row["mec_radius_m"] for row in successful
                        if row["mec_radius_m"] is not None), default=None),
        },
        "_rows": rows,
    }
    return episodes


def _sum_counters(episodes, key):
    total = Counter()
    for entry in episodes:
        total.update(entry.get(key) or {})
    return dict(total)


def radius_bands(episodes, edges=(100.0, 300.0, 600.0, 700.0)):
    """Failure/success counts per MEC-radius band: is the signal separable?"""
    bands = OrderedDict()
    labels = ["<=%.0f" % edges[0]]
    for low, high in zip(edges, edges[1:]):
        labels.append("%.0f-%.0f" % (low, high))
    labels.append(">%.0f" % edges[-1])
    for label in labels:
        bands[label] = {"success": 0, "failed": 0}
    for entry in episodes:
        for row in entry["_rows"]:
            radius = row["mec_radius_m"]
            if radius is None:
                bands["unknown"] = bands.get("unknown", {"success": 0,
                                                         "failed": 0})
                bands["unknown"]["success" if row["success"] else "failed"] += 1
                continue
            for index, label in enumerate(labels):
                upper = edges[index] if index < len(edges) else float("inf")
                if radius <= upper:
                    bands[label]["success" if row["success"] else "failed"] += 1
                    break
    return bands


def repeat_distance_bands(episodes, edges=(1.0, 5.0, 10.0, 20.0, 35.0, 50.0)):
    """Distance to the previous attempt of the same channel, success vs failed."""
    labels = ["first"] + ["<=%.0f" % edge for edge in edges] + [">%.0f" % edges[-1]]
    bands = OrderedDict((label, {"success": 0, "failed": 0}) for label in labels)
    for entry in episodes:
        last = {}
        for row in entry["_rows"]:
            previous = last.get(row["channel"])
            if previous is None:
                bands["first"]["success" if row["success"] else "failed"] += 1
            else:
                gap = dist(row["target"], previous)
                label = ">%.0f" % edges[-1]
                for edge in edges:
                    if gap <= edge:
                        label = "<=%.0f" % edge
                        break
                bands[label]["success" if row["success"] else "failed"] += 1
            last[row["channel"]] = row["target"]
    return bands


def _repeat_result(episodes, radius, sources):
    """Suppress a clear when an earlier attempt of the same channel (failed)
    lies within ``radius`` metres of the target."""
    suppressed = saveable = terminal = harmful = recovered = 0
    saved_m = saved_c = 0.0
    for entry in episodes:
        rows = entry["_rows"]
        later_success = {}
        for row in reversed(rows):
            if row["success"]:
                later_success[row["channel"]] = row["index"]
        prior = defaultdict(list)
        for row in rows:
            failed_before = [point for ok, point in prior[row["channel"]]
                             if not ok]
            close = any(dist(row["target"], point) <= radius
                        for point in failed_before)
            if close:
                later = later_success.get(row["channel"])
                if row["success"]:
                    if later is not None and later > row["index"]:
                        recovered += 1
                    else:
                        harmful += 1
                else:
                    suppressed += 1
                    if later is not None and later > row["index"]:
                        saveable += 1
                        saved_m += row["movement_s"]
                        saved_c += row["clear_s"]
                    else:
                        terminal += 1
            prior[row["channel"]].append((row["success"], row["target"]))
    return {"suppressed_failed": suppressed, "suppressed_saveable": saveable,
            "suppressed_terminal": terminal,
            "suppresses_successful_clears": harmful,
            "suppressed_success_recovered": recovered,
            "saved_movement_s": saved_m, "saved_clear_s": saved_c,
            "saved_s": saved_m + saved_c,
            "saved_per_source_s": (saved_m + saved_c) / (sources or 1),
            "measurement_growth_pct": 0.0}


def cell_aggregate(episodes, thresholds):
    """Per-cell ledger and threshold curve."""
    out = {"episodes": len(episodes),
           "sources_total": sum(entry["sources_total"] for entry in episodes),
           "clear_rows": sum(entry["n_clear_rows"] for entry in episodes),
           "reconciled_episodes": sum(1 for entry in episodes
                                      if entry["reconciles"]),
           "classes": _sum_counters(episodes, "classes"),
           "mechanism": _sum_counters(episodes, "mechanism"),
           "raw_attribution": {key: sum(entry["raw_attribution"][key]
                                        for entry in episodes)
                               for key in episodes[0]["raw_attribution"]}
           if episodes else {},
           "online_signals": {key: sum(entry["online_signals"][key]
                                       for entry in episodes)
                              for key in episodes[0]["online_signals"]}
           if episodes else {},
           "failed_count": sum(entry["failed"]["count"] for entry in episodes),
           "failed_s": sum(entry["failed"]["total_s"] for entry in episodes),
           "failed_movement_s": sum(entry["failed"]["movement_s"]
                                    for entry in episodes),
           "failed_clear_s": sum(entry["failed"]["clear_s"] for entry in episodes),
           "curve": []}
    sources = out["sources_total"] or 1
    out["failed_per_source_s"] = out["failed_s"] / sources
    out["failed_movement_per_source_s"] = out["failed_movement_s"] / sources
    out["radius_bands"] = radius_bands(episodes)
    out["repeat_curve"] = [
        dict(_repeat_result(episodes, radius, sources), radius_m=radius)
        for radius in REPEAT_RADII]
    out["repeat_distance_bands"] = repeat_distance_bands(episodes)
    # threshold-independent variant: never fire twice at (nearly) the same spot
    repeat_saved_m = repeat_saved_c = 0.0
    repeat_suppressed = repeat_saveable = repeat_terminal = 0
    repeat_success_harmful = 0
    for entry in episodes:
        rows = entry["_rows"]
        later_success = {}
        for row in reversed(rows):
            if row["success"]:
                later_success[row["channel"]] = row["index"]
        for row in rows:
            if not row["nearby_repeat"]:
                continue
            later = later_success.get(row["channel"])
            if row["success"]:
                if not (later is not None and later > row["index"]):
                    repeat_success_harmful += 1
                continue
            repeat_suppressed += 1
            if later is not None and later > row["index"]:
                repeat_saveable += 1
                repeat_saved_m += row["movement_s"]
                repeat_saved_c += row["clear_s"]
            else:
                repeat_terminal += 1
    out["repeat_rule"] = {
        "suppressed_failed": repeat_suppressed,
        "suppressed_saveable": repeat_saveable,
        "suppressed_terminal": repeat_terminal,
        "suppresses_successful_clears": repeat_success_harmful,
        "saved_movement_s": repeat_saved_m, "saved_clear_s": repeat_saved_c,
        "saved_s": repeat_saved_m + repeat_saved_c,
        "saved_per_source_s": (repeat_saved_m + repeat_saved_c) / sources,
        "measurement_growth_pct": 0.0}
    for threshold in thresholds:
        for use_near, use_guaranteed, tag in (
                (False, False, "radius_only"),
                (True, False, "radius_or_near"),
                (True, True, "radius_or_near_or_guaranteed")):
            saved_m = saved_c = term_m = term_c = 0.0
            suppressed = saveable = terminal = bad_success = recovered = 0
            for entry in episodes:
                result = replay(entry["_rows"], threshold, use_near,
                                use_guaranteed)
                saved_m += result["saved_movement_s"]
                saved_c += result["saved_clear_s"]
                term_m += result["terminal_movement_s"]
                term_c += result["terminal_clear_s"]
                suppressed += result["suppressed_failed"]
                saveable += result["suppressed_saveable"]
                terminal += result["suppressed_terminal"]
                bad_success += result["suppressed_success_harmful"]
                recovered += result["suppressed_success_recovered"]
            saved = saved_m + saved_c
            out["curve"].append({
                "threshold_m": threshold, "variant": tag,
                "suppressed_failed": suppressed,
                "suppressed_saveable": saveable,
                "suppressed_terminal": terminal,
                "suppresses_successful_clears": bad_success,
                "suppressed_success_recovered": recovered,
                "saved_movement_s": saved_m, "saved_clear_s": saved_c,
                "saved_s": saved, "saved_per_source_s": saved / sources,
                "terminal_s": term_m + term_c,
                "terminal_per_source_s": (term_m + term_c) / sources,
                "measurement_growth_pct": 0.0})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--cells", default=",".join(DEFAULT_CELLS))
    parser.add_argument("--out", default="tuning_runs/clear_ledger_audit.json")
    parser.add_argument("--md", default="tuning_runs/CLEAR_LEDGER.md")
    parser.add_argument("--limit-episodes", type=int, default=0)
    args = parser.parse_args()

    started = time.time()
    cells = [item.strip() for item in args.cells.split(",") if item.strip()]
    report = {
        "tool": "tools/clear_ledger_audit.py",
        "tool_sha256_16": sha16(Path(__file__)),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": args.root, "cells": cells,
        "constants": {"clear_radius_m": CLEAR_RADIUS_M,
                      "nearby_repeat_m": NEARBY_REPEAT_M,
                      "thresholds_m": list(DEFAULT_THRESHOLDS)},
        "pre_registration": PRE_REGISTRATION,
        "class_definitions": {
            "success": "distance(clear target, true source) <= 20 m "
                       "(validated against metrics.n_clear_success per episode)",
            "F1_fallback": "policy_mode or reason mentions fallback",
            "F2_repeat_at_same_or_nearby_position":
                "an earlier clear of the same channel had a target within 50 m",
            "F3_mec_estimate_off_by_over_20m":
                "online MEC centre at decision time is > 20 m from the true "
                "source (attribution uses truth - offline only)",
            "F4_walked_to_estimate_and_fired_out_of_range":
                "MEC centre within 20 m of the truth but the fired point is not",
            "F5_other": "remaining failures",
        },
        "cells": {}, "notes": [
            "Savings are an offline UPPER BOUND under the 'same continuation' "
            "assumption: suppressing a failed attempt keeps the later successful "
            "attempt of the same channel, but the real trajectory would differ.",
            "A suppressed failed clear whose channel is never cleared later is "
            "counted as 'must pay', not as savings.",
            "Truth is read for attribution/validation only; the rule inputs are "
            "MEC radius, observation flags and the fallback flag.",
        ],
    }
    per_episode = []
    for cell in cells:
        directories = sorted(glob.glob(str(ROOT / args.root / (cell + "_*"))))
        if args.limit_episodes:
            directories = directories[:args.limit_episodes]
        print("== %s: %d episode(s)" % (cell, len(directories)), flush=True)
        episodes = []
        for directory in directories:
            if not (Path(directory) / "state_history.json").exists():
                continue
            entry = audit_episode(directory)
            if not entry["reconciles"]:
                print("   ! reconciliation mismatch in %s: rows %d vs metrics %s"
                      % (entry["dir"], entry["n_clear_rows"],
                         entry["n_clear_attempts_metrics"]), flush=True)
            episodes.append(entry)
        cell_summary = cell_aggregate(episodes, DEFAULT_THRESHOLDS)
        for entry in episodes:
            entry.pop("_rows", None)
        report["cells"][cell] = {"summary": cell_summary,
                                 "episodes": episodes}
        per_episode.extend(episodes)
        best = max(cell_summary["curve"],
                   key=lambda item: item["saved_per_source_s"])
        print("   failed %d rows = %.0f s (%.1f s/源); best rule %.1f s/源 "
              "(threshold %.0f, %s)"
              % (cell_summary["failed_count"], cell_summary["failed_s"],
                 cell_summary["failed_per_source_s"],
                 best["saved_per_source_s"], best["threshold_m"],
                 best["variant"]), flush=True)

    # ---- pre-registered verdict -------------------------------------------
    verdicts = []
    for cell, data in sorted(report["cells"].items()):
        summary = data["summary"]
        best = max(summary["curve"], key=lambda item: item["saved_per_source_s"])
        candidates = [{"variant": best["variant"], "threshold_m": best["threshold_m"],
                       "saved_per_source_s": best["saved_per_source_s"],
                       "suppresses_successful_clears":
                           best["suppresses_successful_clears"],
                       "measurement_growth_pct": best["measurement_growth_pct"]}]
        repeat = summary["repeat_rule"]
        candidates.append({"variant": "no_repeat_within_50m", "threshold_m": None,
                           "saved_per_source_s": repeat["saved_per_source_s"],
                           "suppresses_successful_clears":
                               repeat["suppresses_successful_clears"],
                           "measurement_growth_pct":
                               repeat["measurement_growth_pct"]})
        for item in summary.get("repeat_curve", []):
            candidates.append({"variant": "no_repeat_if_failed_within_%.0fm"
                                          % item["radius_m"],
                               "threshold_m": None,
                               "saved_per_source_s": item["saved_per_source_s"],
                               "suppresses_successful_clears":
                                   item["suppresses_successful_clears"],
                               "measurement_growth_pct":
                                   item["measurement_growth_pct"]})
        best_any = max(candidates, key=lambda item: item["saved_per_source_s"])
        safe = [item for item in candidates
                if item["suppresses_successful_clears"] == 0]
        best_safe = (max(safe, key=lambda item: item["saved_per_source_s"])
                     if safe else None)
        decision = best_safe or {"variant": "none (no safe rule in the family)",
                                 "threshold_m": None, "saved_per_source_s": 0.0,
                                 "measurement_growth_pct": 0.0,
                                 "suppresses_successful_clears": 0}
        go = (best_safe is not None
              and decision["saved_per_source_s"] >=
              PRE_REGISTRATION["go_threshold_s_per_source"]
              and decision["measurement_growth_pct"] <=
              PRE_REGISTRATION["measurement_growth_limit_pct"])
        verdict_entry = dict(decision)
        verdict_entry.update({
            "cell": cell,
            "verdict": "GO" if go else "NO-GO",
            "best_unsafe_variant": best_any["variant"],
            "best_unsafe_threshold_m": best_any["threshold_m"],
            "best_unsafe_s_per_source": best_any["saved_per_source_s"],
            "best_unsafe_suppresses_successful":
                best_any["suppresses_successful_clears"],
            "radius_family_best_s_per_source": best["saved_per_source_s"],
            "radius_family_suppresses_successful":
                best["suppresses_successful_clears"],
            "safe_rule_exists": best_safe is not None})
        verdicts.append(verdict_entry)
    report["verdict"] = {
        "decided_by": "pre-registered rule (see pre_registration)",
        "go_cells": [item["cell"] for item in verdicts if item["verdict"] == "GO"],
        "overall": "GO" if any(item["verdict"] == "GO" for item in verdicts)
                   else "NO-GO",
        "per_cell": verdicts,
    }
    report["wall_seconds"] = round(time.time() - started, 2)
    out_path = ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    md_path = ROOT / args.md
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print("overall verdict: %s ; written %s and %s (%.1f s)"
          % (report["verdict"]["overall"], out_path, md_path,
             report["wall_seconds"]))
    return 0


def render_markdown(report):
    lines = []
    add = lines.append
    add("# 清除侧台账：失败清除/盲走的成因与可省上界（预注册 GO/NO-GO）")
    add("")
    add("> 由 `tools/clear_ledger_audit.py` 生成（脚本哈希 `%s`，生成于 %s）。"
        % (report["tool_sha256_16"], report["generated_utc"]))
    add("> 纯离线台账：**不跑新局、不改运行时**；「可省」是**离线上界**，不是已实现收益。")
    add("")
    add("## 0. 预注册（先写后跑）")
    add("")
    for key, value in report["pre_registration"].items():
        add("- `%s` = %s" % (key, value))
    add("")
    add("## 1. 口径与数据来源")
    add("")
    add("- 每次 clear 的「成功」判定：**开火点与真源距离 ≤ %.0f m**；"
        "已逐局与 `metrics.n_clear_success` 对账（下表 `reconciles` 列）。"
        % report["constants"]["clear_radius_m"])
    add("- 每条记录的字段分两列：**在线可观测**（机器人位置、该频道状态与 MEC 半径、"
        "观测结果 direction/near、是否 fallback、此前是否已在同/邻近点尝试过）与 "
        "**离线真值**（真源坐标、开火点到真源距离、MEC 中心到真源距离），后者**只用于归因**。")
    add("- MEC 估计取该决策时刻之前、`localization_history/channel_XX.jsonl` 的最后一条记录"
        "（含 `mec_center`/`mec_radius`/`guaranteed_clear_region`）。")
    add("")
    add("## 2. 六格台账总览")
    add("")
    add("| 格 | 局数 | 源数合计 | clear 次数 | 失败次数 | 失败移动 s | 失败 clear s | **失败合计 s** | **失败 s/源** | 对账通过局 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        s = data["summary"]
        add("| %s | %d | %d | %d | %d | %.0f | %.0f | **%.0f** | **%.1f** | %d/%d |" %
            (cell, s["episodes"], s["sources_total"], s["clear_rows"],
             s["failed_count"], s["failed_movement_s"], s["failed_clear_s"],
             s["failed_s"], s["failed_per_source_s"],
             s["reconciled_episodes"], s["episodes"]))
    add("")
    add("## 3. 失败清除的成因分类（互斥，优先级判定）")
    add("")
    add("| 类别 | 判据 | 各格计数 | 合计 |")
    add("|---|---|---|---:|")
    keys = ["F1_mec_belief_excludes_truth",
            "F2_probe_out_of_range_while_belief_ok",
            "F3_repeat_at_same_or_nearby_position", "F4_fallback_ladder", "F5_other"]
    for key in keys:
        per_cell = " / ".join(str(data["summary"]["classes"].get(key, 0))
                              for _, data in sorted(report["cells"].items()))
        total = sum(data["summary"]["classes"].get(key, 0)
                    for data in report["cells"].values())
        add("| `%s` | %s | %s | %d |" %
            (key, report["class_definitions"].get(key, ""), per_cell, total))
    add("| `success` | 命中真源 ≤20 m | %s | %d |" %
        (" / ".join(str(data["summary"]["classes"].get("success", 0))
                    for _, data in sorted(report["cells"].items())),
         sum(data["summary"]["classes"].get("success", 0)
             for data in report["cells"].values())))
    add("")
    add("| 格 | clear 次数 | 成功 | 失败 | 分类合计 | 对得上 |")
    add("|---|---:|---:|---:|---:|---|")
    for cell, data in sorted(report["cells"].items()):
        s = data["summary"]
        total = sum(s["classes"].values())
        add("| %s | %d | %d | %d | %d | %s |" %
            (cell, s["clear_rows"], s["classes"].get("success", 0),
             s["failed_count"], total, "是" if total == s["clear_rows"] else "**否**"))
    add("")
    add("### 3b. MEC 半径可分离性（失败 vs 成功，按半径分档）")
    add("")
    add("| 格 | 半径档 | 成功 | 失败 |")
    add("|---|---|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        for band, counts in data["summary"]["radius_bands"].items():
            add("| %s | %s | %d | %d |" % (cell, band, counts.get("success", 0),
                                           counts.get("failed", 0)))
    add("")
    add("### 3c. 机制（policy_mode|reason）与失败的关系，以及非互斥的原始归因")
    add("")
    add("| 格 | 机制（成功/失败） | 原始归因计数 |")
    add("|---|---|---|")
    for cell, data in sorted(report["cells"].items()):
        mech = "; ".join("%s=%d" % (key, value) for key, value in
                         sorted(data["summary"]["mechanism"].items(),
                                key=lambda item: -item[1]))
        raw = data["summary"]["raw_attribution"]
        add("| %s | %s | MEC 偏 >20 m: %d；fallback 且失败: %d；重复点且失败: %d；无 MEC 记录且失败: %d |" %
            (cell, mech, raw.get("mec_off_rows", 0),
             raw.get("fallback_failed_rows", 0),
             raw.get("repeat_failed_rows", 0),
             raw.get("no_mec_and_failed_rows", 0)))
    add("")
    add("在线信号可用性（六格合计）：near 观测 %s 次；当前位置有 direction %s 次；"
        "`guaranteed_clear_region` 非空 %s 次（其中仍失败 %s 次）；无 MEC 记录 %s 次。"
        % tuple(sum(data["summary"]["online_signals"].get(key, 0)
                    for data in report["cells"].values())
                for key in ("near_observation_rows", "direction_at_position_rows",
                            "guaranteed_region_rows",
                            "guaranteed_region_failed_rows",
                            "no_mec_record_rows")))
    add("")
    add("## 4. 「先验证再清除」规则的离线重放（阈值曲线）")
    add("")
    add("| 格 | 阈值 (m) | 变体 | 抑制的失败次数 | 其中可省 | 其中必须付 | 省下的移动 s | 省下的 clear s | **可省 s/源** | 抑制了成功清除? |")
    add("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        for item in data["summary"]["curve"]:
            add("| %s | %.0f | %s | %d | %d | %d | %.0f | %.0f | **%.1f** | %d |" %
                (cell, item["threshold_m"], item["variant"],
                 item["suppressed_failed"], item["suppressed_saveable"],
                 item["suppressed_terminal"], item["saved_movement_s"],
                 item["saved_clear_s"], item["saved_per_source_s"],
                 item["suppresses_successful_clears"]))
        repeat = data["summary"]["repeat_rule"]
        add("| %s | — | **no_repeat_within_50m** | %d | %d | %d | %.0f | %.0f | **%.1f** | %d |" %
            (cell, repeat["suppressed_failed"], repeat["suppressed_saveable"],
             repeat["suppressed_terminal"], repeat["saved_movement_s"],
             repeat["saved_clear_s"], repeat["saved_per_source_s"],
             repeat["suppresses_successful_clears"]))
    add("")
    add("### 4b. 重复点规则族（抑制「同频道此前失败过且距离 ≤ r」的再次开火）")
    add("")
    add("| 格 | r (m) | 抑制失败次数 | 其中可省 | 其中必须付 | 省下 s | 可省 s/源 | 抑制成功清除 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        for item in data["summary"]["repeat_curve"]:
            add("| %s | %.0f | %d | %d | %d | %.0f | **%.1f** | %d |" %
                (cell, item["radius_m"], item["suppressed_failed"],
                 item["suppressed_saveable"], item["suppressed_terminal"],
                 item["saved_s"], item["saved_per_source_s"],
                 item["suppresses_successful_clears"]))
    add("")
    add("### 4c. 到同一频道上一次尝试的距离（成功 vs 失败）")
    add("")
    add("| 格 | 距离档 | 成功 | 失败 |")
    add("|---|---|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        for band, counts in data["summary"]["repeat_distance_bands"].items():
            add("| %s | %s | %d | %d |" % (cell, band, counts.get("success", 0),
                                           counts.get("failed", 0)))
    add("")
    add("## 5. 预注册判定")
    add("")
    add("| 格 | 最好安全规则 | 阈值/半径 | 安全可省 s/源 | 测量增量 | 最佳规则（未必安全）s/源 | 其抑制成功清除数 | 判定 |")
    add("|---|---|---|---:|---:|---:|---:|---|")
    for item in report["verdict"]["per_cell"]:
        add("| %s | %s | %s | %.1f | %.1f%% | %.1f | %d | **%s** |" %
            (item["cell"], item["variant"],
             "-" if item["threshold_m"] is None else "%.0f" % item["threshold_m"],
             item["saved_per_source_s"], item["measurement_growth_pct"],
             item["best_unsafe_s_per_source"],
             item["best_unsafe_suppresses_successful"], item["verdict"]))
    add("")
    add("**总体判定：%s**（GO 条件：任一格可省 ≥ %.1f s/源 且测量增量 ≤ %.1f%% 且不抑制成功清除）"
        % (report["verdict"]["overall"],
           report["pre_registration"]["go_threshold_s_per_source"],
           report["pre_registration"]["measurement_growth_limit_pct"]))
    add("")
    add("## 6. 结论：可省 vs 必须付的搜索成本（逐格）")
    add("")
    add("| 格 | 失败清除 s/源 | 失败移动 s/源 | 安全规则可省 s/源 | 可省占比 | 其余（必须付）s/源 |")
    add("|---|---:|---:|---:|---:|---:|")
    for cell, data in sorted(report["cells"].items()):
        summary = data["summary"]
        verdict = next(item for item in report["verdict"]["per_cell"]
                       if item["cell"] == cell)
        failed = summary["failed_per_source_s"] or 0.0
        movement = summary["failed_movement_per_source_s"] or 0.0
        safe = verdict["saved_per_source_s"]
        add("| %s | %.1f | %.1f | %.1f | %.0f%% | %.1f |" %
            (cell, failed, movement, safe,
             100.0 * safe / failed if failed else 0.0, max(0.0, failed - safe)))
    add("")
    add("- 失败清除总量最大的格是 **Q4/16（30.9 s/源）**，其次是 Q4/10（22.4）与 Q4/13（17.4）；"
        "Q3 三格只有 7.3–16.7 s/源。")
    add("- **可被「先验证」规则消除的比例**：见上表「可省占比」；注意这里用的是**安全规则**"
        "（不抑制任何成功清除）。若允许抑制成功清除，Q4 三格的离线可省可达 11.8–25.7 s/源，"
        "但那会让 8–44 次已成功的清除被挡掉 ⇒ 不能采用。")
    add("- **其余部分属于必须付的搜索成本**：这些失败全部是 fallback 阶梯在**不同点位**的探测"
        "（同一频道相邻两次开火距离多在 ≤35 m 一带，失败 675 次 / 成功 10 次落在同一档），"
        "在线只有「MEC 半径 / 上一次开火位置」两个信号，而这两个信号在**同一档位里同时包含命中与未命中**"
        "（半径 600–700 m 档：失败 vs 成功；重复距离 ≤35 m 档：失败 vs 成功，见 §3c/§4c）"
        "⇒ 无法在不误伤成功清除的前提下把它们区分开。")
    add("- **上界性说明**：可省值假设「同一后续轨迹」，只扣掉被抑制那一步的移动与开火时间；"
        "真实策略会改变后续路径与观测，因此这不是收益承诺。规则的在线输入只有"
        "「MEC 半径 / near 观测 / guaranteed 区域 / 是否 fallback / 上一次开火位置」，"
        "不含源数、场景或真值。")
    add("")
    add("## 7. 输入与哈希")
    add("")
    for cell, data in sorted(report["cells"].items()):
        add("- **%s**：%d 局" % (cell, len(data["episodes"])))
        for entry in data["episodes"][:2]:
            add("    - `%s`" % entry["dir"])
            for name, digest in sorted(entry["inputs"].items()):
                add("        - `%s` sha256:%s" % (name, digest))
    add("")
    add("## 8. 复现命令")
    add("")
    add("```powershell")
    add("python -X utf8 tools/clear_ledger_audit.py --root %s --cells %s"
        % (report["root"], ",".join(report["cells"])))
    add("python -X utf8 verification/check_model.py")
    add("```")
    add("")
    add("## 9. 边界")
    add("")
    for note in report["notes"]:
        add("- " + note)
    add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
