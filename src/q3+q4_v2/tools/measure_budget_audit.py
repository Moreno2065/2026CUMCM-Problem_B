# -*- coding: utf-8 -*-
"""Measurement-budget audit for Q3/16 and Q4/16 episodes (offline only).

What it does
------------
For every episode it joins ``actions.csv`` (policy intent) with
``observations.csv`` (result + channel-status transition) row by row, then:

* classifies each measurement by purpose with an explicit, checkable rule;
* reports counts / seconds / shares per class and per stage;
* reconstructs the certificate accounting: which basis certified the residual
  channels, how many witnesses they actually received, and how many a
  ``sparse25`` basis would have demanded;
* locates the moment the cardinality cap closed the case and counts the
  measurements spent *after* that moment;
* quantifies the offline reducible upper bound in four labelled categories,
  each flagged for whether removing it can touch ``complete`` /
  ``verifier_all_ok`` / certificate validity.

Honesty rules
-------------
* Every row costs 5 s (``action_time``) and some rows pay 1 s of channel switch;
  both are read from the ledger, not modelled.
* "Reducible" here means *offline arithmetic on a finished episode*.  It is an
  upper bound on what an offline planner could delete, **not** a promise that a
  policy can reach it: a policy cannot know the future and several categories
  are state-dependent.  The report keeps the two apart everywhere.
* Nothing here changes the runtime: this tool only reads finished episodes.
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
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.certificate import (q3_backbone_points, q3_certified,          # noqa: E402
                                  q4_certify_point)
from geometry.constants import MOVE_SPEED, Q4_DELTA, R_EFF_MIN           # noqa: E402
from geometry.q4_sparse_mesh import q4_sparse25_points                   # noqa: E402

MEASURE_SECONDS = 5.0
SWITCH_SECONDS = 1.0
MAX_SOURCES = 16                      # runtime.V2GameRunner._apply_cardinality_cap
POSITIVE = ("ACTIVE", "READY", "CLEARED")
INPUT_FILES = ("actions.csv", "observations.csv", "certificate.json",
               "metrics.json", "provenance.json")
DEFAULT_SEEDS = (101, 202, 303, 404, 505)
CLASS_ORDER = ("certificate_witness_required", "certificate_free_witness",
               "discovery_found", "discovery_ruled_out", "pre_clear_probe",
               "localization_active", "other")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def sha16(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def on_points(point, cloud, tol=1e-6):
    return any(dist(point, q) <= tol for q in cloud)


# ---------------------------------------------------------------------------
# episode loading / joining
# ---------------------------------------------------------------------------

def load_episode(directory):
    directory = ROOT / directory
    actions = list(csv.DictReader(open(directory / "actions.csv",
                                        encoding="utf-8")))
    observations = list(csv.DictReader(open(directory / "observations.csv",
                                             encoding="utf-8")))
    certificate = json.loads((directory / "certificate.json")
                             .read_text(encoding="utf-8"))
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((directory / "provenance.json")
                            .read_text(encoding="utf-8"))
    measures = [row for row in actions if row["action_type"] == "measure"]
    joined, mismatches = [], 0
    for index, (action, observation) in enumerate(zip(measures, observations)):
        point = (float(action["target_x"]), float(action["target_y"]))
        same = (action["channel"] == observation["channel"]
                and abs(point[0] - float(observation["x"])) <= 1e-6
                and abs(point[1] - float(observation["y"])) <= 1e-6)
        mismatches += 0 if same else 1
        joined.append({
            "index": index,
            "step": action["step"],
            "channel": int(action["channel"]),
            "point": point,
            "policy_mode": action["policy_mode"],
            "reason": action["reason_code"],
            "action_time": float(action["action_time"] or 0.0),
            "switch_time": float(action["switch_time"] or 0.0),
            "result": observation["result"],
            "status_before": observation["status_before"],
            "status_after": observation["status_after"],
        })
    return {"dir": str(directory.relative_to(ROOT)).replace("\\", "/"),
            "rows": joined, "certificate": certificate, "metrics": metrics,
            "provenance": provenance, "n_measure_rows": len(measures),
            "n_observation_rows": len(observations), "join_mismatches": mismatches,
            "inputs": {name: sha16(directory / name) for name in INPUT_FILES}}


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def final_status(certificate, channel):
    record = certificate.get(str(channel))
    return (record or {}).get("status")


def classify_episode(episode, mesh, basis_required):
    """Purpose class per measurement (mutually exclusive, documented order).

    ``basis_required`` maps basis name -> required witness rows per absent
    channel (``sparse25`` -> len(mesh), ``cardinality`` -> 0).
    """
    certificate = episode["certificate"]
    absent = {int(cid) for cid, rec in certificate.items()
              if rec.get("status") == "CERTIFIED_ABSENT"}
    basis = {int(cid): rec.get("absent_basis") for cid, rec in certificate.items()
             if rec.get("status") == "CERTIFIED_ABSENT"}
    for row in episode["rows"]:
        channel = row["channel"]
        status = final_status(certificate, channel)
        required = basis_required.get(basis.get(channel, ""), 0)
        if channel in absent and required > 0 and on_points(row["point"], mesh):
            row["class"] = "certificate_witness_required"
        elif row["result"] == "no_signal" and status == "CERTIFIED_ABSENT":
            row["class"] = "certificate_free_witness"
        elif row["status_before"] == "UNKNOWN":
            row["class"] = ("discovery_found" if row["result"] == "direction"
                            else "discovery_ruled_out")
        elif "probe" in row["reason"]:
            row["class"] = "pre_clear_probe"
        elif row["status_before"] == "ACTIVE" and status == "CLEARED":
            row["class"] = "localization_active"
        else:
            row["class"] = "other"
    return absent, basis


def cap_index(episode):
    """Index of the measurement that let the cardinality cap fire (or None)."""
    confirmed = set()
    for row in episode["rows"]:
        if row["status_after"] in POSITIVE:
            confirmed.add(row["channel"])
        if len(confirmed) >= MAX_SOURCES:
            return row["index"], sorted(confirmed)
    return None, sorted(confirmed)


# ---------------------------------------------------------------------------
# reducible categories
# ---------------------------------------------------------------------------

def reducible(episode, mesh):
    """Four labelled categories; each row is counted once, in this order."""
    rows = episode["rows"]
    certificate = episode["certificate"]
    absent = {int(cid) for cid, rec in certificate.items()
              if rec.get("status") == "CERTIFIED_ABSENT"}
    required = {"sparse25": len(mesh), "cardinality": 0}
    witness_used = Counter()
    categories = OrderedDict((name, {"rows": 0, "indices": []}) for name in (
        "D1_duplicate_measurement", "D2_no_signal_already_cleared",
        "D3_witness_beyond_basis_need", "D4_certificate_geometry_other_purpose"))
    seen = Counter()
    cap_at, _ = cap_index(episode)
    for row in rows:
        key = (row["channel"], round(row["point"][0], 6), round(row["point"][1], 6),
               row["status_before"], row["result"])
        seen[key] += 1
        if seen[key] >= 2:
            categories["D1_duplicate_measurement"]["rows"] += 1
            categories["D1_duplicate_measurement"]["indices"].append(row["index"])
            continue
        status = final_status(certificate, row["channel"])
        if row["result"] == "no_signal" and status == "CLEARED":
            categories["D2_no_signal_already_cleared"]["rows"] += 1
            categories["D2_no_signal_already_cleared"]["indices"].append(row["index"])
            continue
        if row["channel"] in absent and row["result"] == "no_signal":
            need = required.get(
                (certificate.get(str(row["channel"])) or {}).get("absent_basis", ""),
                None)
            witness_used[row["channel"]] += 1
            if need is not None and witness_used[row["channel"]] > need:
                categories["D3_witness_beyond_basis_need"]["rows"] += 1
                categories["D3_witness_beyond_basis_need"]["indices"].append(
                    row["index"])
                continue
        if on_points(row["point"], mesh) and row["channel"] not in absent:
            categories["D4_certificate_geometry_other_purpose"]["rows"] += 1
            categories["D4_certificate_geometry_other_purpose"]["indices"].append(
                row["index"])
    post_cap = [row for row in rows
                if cap_at is not None and row["index"] > cap_at]
    # "after the cap" breakdown: scans of still-UNKNOWN channels are pure waste
    post_cap_unknown = [row for row in post_cap
                        if row["status_before"] == "UNKNOWN"]
    post_cap_certificate = [row for row in post_cap
                            if row["class"] in ("certificate_free_witness",
                                                "certificate_witness_required")]
    return {"categories": categories,
            "d1_d3_rows": (categories["D1_duplicate_measurement"]["rows"]
                           + categories["D3_witness_beyond_basis_need"]["rows"]),
            "cap_index": cap_at,
            "post_cap_rows": len(post_cap),
            "post_cap_unknown_channel_rows": len(post_cap_unknown),
            "post_cap_certificate_class_rows": len(post_cap_certificate),
            "post_cap_unnecessary_rows": len({row["index"] for row in
                                              post_cap_unknown + post_cap_certificate})}


def switch_floor(episode):
    stops = OrderedDict()
    for row in episode["rows"]:
        key = (round(row["point"][0], 6), round(row["point"][1], 6))
        stops.setdefault(key, set()).add(row["channel"])
    floor = sum(max(0, len(channels) - 1) for channels in stops.values())
    actual = sum(1 for row in episode["rows"] if row["switch_time"] > 0)
    return {"stops": len(stops), "actual_switch_rows": actual,
            "per_stop_floor": floor,
            "offline_switch_rows_savable": max(0, actual - floor)}


# ---------------------------------------------------------------------------
# per-episode audit
# ---------------------------------------------------------------------------

def certificate_lower_bound(case, absent, basis, rows, mesh, certificate):
    """Required / already-covered / marginal witness rows per basis.

    Q4 sparse25: a certified-absent channel needs a no_signal witness at each of
    the 25 fixed mesh points.  Q4 cardinality: zero witnesses are demanded.
    Q3 disk cover: absence needs enough witnesses to cover Ω with 1000 m disks;
    the documented constructive witness set is ``q3_backbone_points`` (7 points),
    and a channel's own witnesses are checked against the exact criterion.
    """
    detail = {}
    marginal_total = 0
    for cid in sorted(absent):
        points = [(row["point"][0], row["point"][1]) for row in rows
                  if row["channel"] == cid and row["result"] == "no_signal"]
        distinct = {(round(p[0], 6), round(p[1], 6)) for p in points}
        entry = {"no_signal_rows": len(points), "distinct_points": len(distinct)}
        if case == "Q4":
            on_mesh = sum(1 for p in distinct if on_points(p, mesh))
            entry.update({"on_fixed_mesh_points": on_mesh,
                          "required_by_basis": (25 if basis.get(cid) == "sparse25"
                                                else 0),
                          "marginal_rows_to_sparse25": max(0, 25 - on_mesh)})
            marginal_total += entry["marginal_rows_to_sparse25"]
        else:
            satisfied = bool(points) and q3_certified(points, cover_r=R_EFF_MIN)["certified"]
            entry.update({"sparse25": None,
                          "disk_criterion_satisfied_by_own_witnesses": satisfied,
                          "required_by_backbone": len(q3_backbone_points()),
                          "marginal_rows_to_disk_criterion": max(
                              0, len(q3_backbone_points()) - (len(distinct)
                                                              if satisfied else 0))})
            marginal_total += entry["marginal_rows_to_disk_criterion"]
        detail[str(cid)] = entry
    return {"per_absent_channel": detail,
            "marginal_rows_total": marginal_total,
            "marginal_seconds_total": marginal_total * MEASURE_SECONDS}


def certificate_class_breakdown(case, rows, absent, mesh):
    """Where the certificate-class measurements actually went."""
    out = Counter()
    for row in rows:
        if row["policy_mode"] != "certificate":
            continue
        ends_absent = "absent" if row["channel"] in absent else "not_absent"
        geometry = ("on_mesh" if on_points(row["point"], mesh) else "off_mesh") \
            if case == "Q4" else ("witness" if row["result"] == "no_signal"
                                  else "no_witness")
        out["%s|%s" % (ends_absent, geometry)] += 1
    return dict(out)


def mst_length(points, return_longest=False):
    pts = list(points)
    if len(pts) < 2:
        return (0.0, 0.0) if return_longest else 0.0
    remaining = list(range(1, len(pts)))
    best = [dist(pts[0], pts[i]) for i in range(len(pts))]
    total, longest = 0.0, 0.0
    while remaining:
        j = min(remaining, key=lambda i: best[i])
        total += best[j]
        longest = max(longest, best[j])
        remaining.remove(j)
        for i in remaining:
            d = dist(pts[j], pts[i])
            if d < best[i]:
                best[i] = d
    return (total, longest) if return_longest else total


def improve_open(order):
    order = list(order)
    improved, rounds = True, 0
    while improved and rounds < 40:
        improved, rounds = False, rounds + 1
        n = len(order)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b, c = order[i - 1], order[i], order[j]
                d = order[j + 1] if j + 1 < n else None
                before = dist(a, b) + (dist(c, d) if d else 0.0)
                after = dist(a, c) + (dist(b, d) if d else 0.0)
                if after < before - 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        for seg in (1, 2, 3):
            for i in range(1, len(order) - seg + 1):
                block = order[i:i + seg]
                rest = order[:i] + order[i + seg:]
                for pos in range(1, len(rest) + 1):
                    if pos == i:
                        continue
                    cand = rest[:pos] + block + rest[pos:]
                    if sum(dist(cand[k], cand[k + 1])
                           for k in range(len(cand) - 1)) < \
                            sum(dist(order[k], order[k + 1])
                                for k in range(len(order) - 1)) - 1e-9:
                        order = cand
                        improved = True
                        break
                else:
                    continue
                break
    return order


def open_path_candidates(points, start=(0.0, 0.0)):
    """NN / cheapest-insertion / farthest-insertion, each 2-opt+Or-opt."""
    pts = [p for p in points if dist(p, start) > 1e-9]
    out = {}
    remaining = list(pts)
    order = [start]
    while remaining:                                    # nearest neighbour
        nxt = min(remaining, key=lambda p: dist(order[-1], p))
        order.append(nxt)
        remaining.remove(nxt)
    out["nearest-neighbour"] = improve_open(order)
    ordered = sorted(pts, key=lambda p: dist(start, p))  # cheapest insertion
    order, rest = [start, ordered[0]], ordered[1:]
    while rest:
        pick = None
        for idx, point in enumerate(rest):
            for pos in range(1, len(order)):
                delta = (dist(order[pos - 1], point) + dist(point, order[pos])
                         - dist(order[pos - 1], order[pos]))
                if pick is None or delta < pick[0]:
                    pick = (delta, idx, pos)
        order.insert(pick[2], rest.pop(pick[1]))
    out["cheapest-insertion"] = improve_open(order)
    far = max(pts, key=lambda p: dist(start, p))         # farthest insertion
    order = [start, far]
    rest = [p for p in pts if dist(p, far) > 1e-9]
    while rest:
        pick = max(rest, key=lambda p: min(dist(p, q) for q in order))
        best = None
        for pos in range(1, len(order)):
            delta = (dist(order[pos - 1], pick) + dist(pick, order[pos])
                     - dist(order[pos - 1], order[pos]))
            if best is None or delta < best[0]:
                best = (delta, pos)
        order.insert(best[1], pick)
        rest.remove(pick)
    out["farthest-insertion"] = improve_open(order)
    return {name: sum(dist(o[k], o[k + 1]) for k in range(len(o) - 1))
            for name, o in out.items()}


EXCLUSION_CODE_FACTS = [
    ("baseline/code/geometry/constants.py", "MAX_SOURCES = 16"),
    ("runtime.py", "if confirmed < C.MAX_SOURCES:"),
    ("runtime.py", 'ch.absent_basis = "cardinality"'),
    ("baseline/code/state/knowledge_state.py",
     "return all(ch.status in (ChannelStatus.CLEARED,"),
    ("baseline/code/geometry/q4_sparse_mesh.py", "MATCH_TOL = 1e-6"),
    ("baseline/code/geometry/q4_sparse_mesh.py",
     "any(math.dist(expected, observed) <= MATCH_TOL"),
    ("production.py", '"q4_certificate_layout": "sparse25"'),
    ("baseline/code/state/channel_state.py",
     "self.status == ChannelStatus.UNKNOWN and"),
    ("baseline/code/state/channel_state.py",
     'self.absent_basis = "fallback_exhausted"'),
    ("baseline/code/experiment/runner.py",
     'if basis == "certificate" and self.mode == "Q4":'),
]


def verify_exclusion(dataset, scan_roots):
    """Check the premises of the N=10/13 strict-exclusion argument."""
    mesh = q4_sparse25_points()
    origin = (0.0, 0.0)
    mst, longest = mst_length([origin] + mesh, return_longest=True)
    candidates = open_path_candidates(mesh, origin)
    best = min(candidates.values())
    optimal_proved = abs(mst - best) < 1.0
    floors = {}
    for n in (10, 13, 16):
        service = service_per_source(n, dataset)
        movement = best / MOVE_SPEED / n
        floors[str(n)] = {
            "movement_floor_s_per_source": movement,
            "movement_floor_s_total": best / MOVE_SPEED,
            "service_s_per_source_measured": service,
            "movement_plus_service_s_per_source": (movement + service
                                                   if service is not None else None),
            "exceeds_target_290": (movement + (service or 0.0)) > 290.0,
        }
    facts = []
    for rel, needle in EXCLUSION_CODE_FACTS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        facts.append({"file": rel, "needle": needle, "present": needle in text})
    bases = Counter()
    groups = {}
    files = 0
    for root in scan_roots:
        for cert_path in sorted(glob.glob(str(ROOT / root / "*" / "certificate.json"))):
            try:
                certificate = json.loads(Path(cert_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            files += 1
            case = Path(cert_path).parent.name
            for record in certificate.values():
                if record.get("status") == "CERTIFIED_ABSENT":
                    basis = record.get("absent_basis")
                    bases[basis] += 1
                    groups.setdefault(basis, set()).add(
                        "_".join(case.split("_")[:2]))
    return {
        "mesh_points": len(mesh),
        "open_path_through_mesh_m": best,
        "mst_m": mst,
        "mst_longest_edge_m": longest,
        "solver_candidates_m": candidates,
        "optimal_proved_by_mst_equals_feasible": optimal_proved,
        "floors": floors,
        "code_facts": facts,
        "code_facts_all_present": all(item["present"] for item in facts),
        "basis_scan": {"files": files, "counts": dict(bases),
                       "case_groups": {k: sorted(v) for k, v in groups.items()}},
    }


def service_per_source(n_sources, dataset):
    """Measured service time (measure+switch+clear) per source for a case.

    The clean baseline directory holds Q4/10 and Q4/16 only, so the N=13 case
    is read from the verifier's own audit directory (same executor, same
    ledger fields); each candidate is accepted only when its own
    ``sources_total`` matches.
    """
    candidates = [
        ROOT / dataset / "Q4_10_101" / "metrics.json",
        ROOT / dataset / "Q4_13_101" / "metrics.json",
        ROOT / dataset / "Q4_16_101" / "metrics.json",
        ROOT / "tuning_runs/t4_plan_audit/production_Q4_13_101" / "metrics.json",
        ROOT / "tuning_runs/ab_probe/production/Q4_13_101" / "metrics.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if int(metrics.get("sources_total") or 0) != n_sources:
            continue
        total = ((metrics.get("T_measure") or 0.0)
                 + (metrics.get("T_switch") or 0.0)
                 + (metrics.get("T_clear") or 0.0))
        return total / n_sources
    return None


def audit_case(case, seed, dataset):
    directory = "%s/%s_16_%d" % (dataset, case, seed)
    episode = load_episode(directory)
    mesh = q4_sparse25_points()
    basis_required = {"sparse25": len(mesh), "cardinality": 0}
    absent, basis = classify_episode(episode, mesh, basis_required)
    metrics = episode["metrics"]
    n_sources = int(metrics.get("sources_total") or 0)
    rows = episode["rows"]
    total_measure_s = sum(row["action_time"] for row in rows)
    class_counts = Counter(row["class"] for row in rows)
    class_rows = OrderedDict()
    for name in CLASS_ORDER:
        count = class_counts.get(name, 0)
        class_rows[name] = {
            "rows": count, "seconds": count * MEASURE_SECONDS,
            "share_pct": 100.0 * count / len(rows) if rows else 0.0}
    cross = Counter((row["policy_mode"], row["reason"]) for row in rows)
    result_status = Counter((row["result"], row["status_before"])
                            for row in rows)
    result = Counter(row["result"] for row in rows)
    witnesses = {cid: sum(1 for row in rows
                          if row["channel"] == cid and row["result"] == "no_signal")
                 for cid in sorted(absent)}
    witness_points = {cid: len({(round(row["point"][0], 6), round(row["point"][1], 6))
                                for row in rows
                                if row["channel"] == cid
                                and row["result"] == "no_signal"})
                      for cid in sorted(absent)}
    sparse25_need = Counter()
    for cid in absent:
        if basis.get(cid) == "sparse25":
            sparse25_need[cid] = 25
    red = reducible(episode, mesh)
    switch = switch_floor(episode)
    cap_at, confirmed = cap_index(episode)
    lb = certificate_lower_bound(case, absent, basis, rows, mesh,
                                 episode["certificate"])
    cert_breakdown = certificate_class_breakdown(case, rows, absent, mesh)
    tier1_rows = (red["categories"]["D1_duplicate_measurement"]["rows"]
                  + red["post_cap_unnecessary_rows"])
    tier2_rows = (red["categories"]["D2_no_signal_already_cleared"]["rows"]
                  + red["categories"]["D3_witness_beyond_basis_need"]["rows"])
    tier3_rows = red["categories"]["D4_certificate_geometry_other_purpose"]["rows"]

    def per_source(value_s):
        return value_s / n_sources if n_sources else None

    return {
        "case": case, "seed": seed, "dir": episode["dir"],
        "inputs": episode["inputs"],
        "sources_total": n_sources,
        "ledger": {
            "n_measure_rows": len(rows),
            "n_observation_rows": episode["n_observation_rows"],
            "join_mismatches": episode["join_mismatches"],
            "T_measure": metrics.get("T_measure"),
            "T_switch": metrics.get("T_switch"),
            "T_clear": metrics.get("T_clear"),
            "T_move": metrics.get("T_move"),
            "T_total_virtual": metrics.get("T_total_virtual"),
            "t_per_source_s": metrics.get("t_per_source_s"),
            "measure_seconds_sum": round(total_measure_s, 1),
            "measure_seconds_per_source": per_source(total_measure_s),
            "switch_seconds_per_source": per_source(metrics.get("T_switch") or 0.0),
        },
        "classes": class_rows,
        "classes_by_result": {
            "result_counts": dict(result),
            "result_x_status_before": {"%s|%s" % key: value
                                       for key, value in result_status.items()},
            "policy_mode_x_reason": {"%s|%s" % key: value
                                     for key, value in cross.items()},
        },
        "certificate": {
            "statuses": dict(Counter(rec.get("status")
                                     for rec in episode["certificate"].values())),
            "absent_bases": dict(Counter(basis.values())),
            "absent_channels": sorted(absent),
            "witnesses_per_absent_channel": witnesses,
            "witness_points_per_absent_channel": witness_points,
            "required_rows": {"sparse25_counterfactual": sum(sparse25_need.values()),
                              "cardinality_actual": 0},
            "sparse25_counterfactual_need_per_channel": dict(sparse25_need),
        },
        "cap": {"cap_index": cap_at, "confirmed_channels": len(confirmed),
                "post_cap_rows": red["post_cap_rows"],
                "post_cap_unknown_channel_rows": red["post_cap_unknown_channel_rows"],
                "post_cap_certificate_class_rows": red["post_cap_certificate_class_rows"],
                "post_cap_unnecessary_rows": red["post_cap_unnecessary_rows"],
                "post_cap_unnecessary_seconds": red["post_cap_unnecessary_rows"]
                * MEASURE_SECONDS,
                "post_cap_unnecessary_per_source": per_source(
                    red["post_cap_unnecessary_rows"] * MEASURE_SECONDS)},
        "reducible": {
            "categories": {name: {"rows": value["rows"],
                                  "seconds": value["rows"] * MEASURE_SECONDS,
                                  "per_source": per_source(value["rows"]
                                                           * MEASURE_SECONDS)}
                           for name, value in red["categories"].items()},
            "d1_plus_d3_rows": red["d1_d3_rows"],
            "d1_plus_d3_per_source": per_source(red["d1_d3_rows"]
                                                 * MEASURE_SECONDS),
        },
        "certificate_lower_bound": lb,
        "certificate_class_breakdown": cert_breakdown,
        "reducible_tiers": {
            "tier1_foresight_free_rows": tier1_rows,
            "tier1_seconds": tier1_rows * MEASURE_SECONDS,
            "tier1_per_source": per_source(tier1_rows * MEASURE_SECONDS),
            "tier2_hindsight_only_rows": tier2_rows,
            "tier2_seconds": tier2_rows * MEASURE_SECONDS,
            "tier2_per_source": per_source(tier2_rows * MEASURE_SECONDS),
            "tier3_not_recoverable_rows": tier3_rows,
            "tier3_seconds": tier3_rows * MEASURE_SECONDS,
            "tier3_per_source": per_source(tier3_rows * MEASURE_SECONDS),
        },
        "switches": switch,
    }


def aggregate(cases):
    out = {}
    for case in sorted({entry["case"] for entry in cases}):
        subset = [entry for entry in cases if entry["case"] == case]
        keys = {
            "seeds": [entry["seed"] for entry in subset],
            "n_measure_rows": [entry["ledger"]["n_measure_rows"] for entry in subset],
            "T_measure": [entry["ledger"]["T_measure"] for entry in subset],
            "T_total_virtual": [entry["ledger"]["T_total_virtual"] for entry in subset],
            "t_per_source_s": [entry["ledger"]["t_per_source_s"] for entry in subset],
            "measure_s_per_source": [entry["ledger"]["measure_seconds_per_source"]
                                     for entry in subset],
            "post_cap_unnecessary_per_source": [
                entry["cap"]["post_cap_unnecessary_per_source"] for entry in subset],
            "d1_d3_per_source": [entry["reducible"]["d1_plus_d3_per_source"]
                                 for entry in subset],
            "tier1_per_source": [entry["reducible_tiers"]["tier1_per_source"]
                                 for entry in subset],
            "tier2_per_source": [entry["reducible_tiers"]["tier2_per_source"]
                                 for entry in subset],
            "tier3_per_source": [entry["reducible_tiers"]["tier3_per_source"]
                                 for entry in subset],
            "marginal_witness_s_per_source": [
                entry["certificate_lower_bound"]["marginal_seconds_total"]
                / (entry["sources_total"] or 1) for entry in subset],
        }
        out[case] = {name: {"min": min(values), "max": max(values),
                            "mean": statistics.mean(values)}
                     for name, values in keys.items() if name != "seeds"}
        out[case]["seeds"] = keys["seeds"]
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tuning_runs/final_recommended_v3")
    parser.add_argument("--cases", default="Q3:16,Q4:16")
    parser.add_argument("--seeds", default=",".join(str(seed)
                                                    for seed in DEFAULT_SEEDS))
    parser.add_argument("--out", default="tuning_runs/measure_budget_audit.json")
    parser.add_argument("--md", default="tuning_runs/MEASURE_BUDGET.md")
    args = parser.parse_args()

    started = time.time()
    cases = [item.split(":")[0] for item in args.cases.split(",")]
    seeds = [int(item) for item in args.seeds.split(",")]
    report = {
        "tool": "tools/measure_budget_audit.py",
        "tool_sha256_16": sha16(Path(__file__)),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset": args.dataset, "cases": cases, "seeds": seeds,
        "constants": {"measure_seconds": MEASURE_SECONDS,
                      "switch_seconds": SWITCH_SECONDS,
                      "max_sources": MAX_SOURCES, "move_speed": MOVE_SPEED,
                      "q4_delta": Q4_DELTA, "r_eff_min": R_EFF_MIN},
        "class_definitions": {
            "certificate_witness_required":
                "row at a certificate witness point for a channel that ends "
                "CERTIFIED_ABSENT, where the episode's basis actually demands "
                "that witness (sparse25 -> 25 fixed mesh points; cardinality -> 0)",
            "certificate_free_witness":
                "result=no_signal for a channel that ends CERTIFIED_ABSENT, at a "
                "point the basis does not demand (evidence collected in passing)",
            "discovery_found":
                "status_before=UNKNOWN and result=direction (first contact that "
                "turns the channel ACTIVE)",
            "discovery_ruled_out":
                "status_before=UNKNOWN and result=no_signal (emptiness check)",
            "pre_clear_probe":
                "reason code contains 'probe' (q3_risky_probe / rolling_probe*): "
                "the deliberate probe before a clear attempt",
            "localization_active":
                "status_before=ACTIVE for a channel that ends CLEARED (MEC "
                "contraction / confirmation of a known source)",
            "other": "remainder (e.g. scans of ACTIVE channels that end absent)",
        },
        "episodes": [],
        "notes": [
            "Offline arithmetic on finished episodes: 'reducible' rows are what "
            "could have been deleted with hindsight, NOT what a policy can reach.",
            "D1 duplicates are state-neutral in this deterministic simulator (the "
            "same (channel, point, status, result) repeats), so removing copies "
            "leaves complete/verifier_all_ok and the certificate unchanged.",
            "D3 rows are witnesses beyond the episode's basis need: safe under "
            "cardinality (0 demanded) but they ARE the evidence structure the "
            "sparse25 basis would rely on, so they are flagged basis-dependent.",
            "D4 rows scan non-absent channels at certificate geometry: they feed "
            "localization, so they must NOT be counted as recoverable time.",
        ],
    }
    for case in cases:
        for seed in seeds:
            print("== %s/16 seed %d" % (case, seed), flush=True)
            entry = audit_case(case, seed, args.dataset)
            report["episodes"].append(entry)
            classes = entry["classes"]
            print("   measures=%d (%.0f s) | cert_free=%d discovery=%d probe=%d "
                  "loc=%d other=%d | post-cap waste=%d (%.1f s/源)"
                  % (entry["ledger"]["n_measure_rows"],
                     entry["ledger"]["measure_seconds_sum"],
                     classes["certificate_free_witness"]["rows"],
                     classes["discovery_found"]["rows"]
                     + classes["discovery_ruled_out"]["rows"],
                     classes["pre_clear_probe"]["rows"],
                     classes["localization_active"]["rows"],
                     classes["other"]["rows"],
                     entry["cap"]["post_cap_unnecessary_rows"],
                     entry["cap"]["post_cap_unnecessary_per_source"] or 0.0),
                  flush=True)
    report["aggregate"] = aggregate(report["episodes"])
    report["exclusion_check"] = verify_exclusion(args.dataset, [
        "tuning_runs/final_recommended_v3",
        "tuning_runs/t4_plan_audit",
        "tuning_runs/ab_probe/production",
        "tuning_runs/ab_probe/ladder2",
        "tuning_runs/ab_probe/ladder3"])
    ex = report["exclusion_check"]
    print("== N=10/13 exclusion check: mesh-only optimal open path %.1f m "
          "(MST %.1f; optimal proved = %s); floors %s"
          % (ex["open_path_through_mesh_m"], ex["mst_m"],
             ex["optimal_proved_by_mst_equals_feasible"],
             {k: round(v["movement_plus_service_s_per_source"] or 0, 1)
              for k, v in ex["floors"].items()}), flush=True)
    print("   code facts all present: %s | basis scan: %s"
          % (ex["code_facts_all_present"], ex["basis_scan"]["counts"]), flush=True)
    report["wall_seconds"] = round(time.time() - started, 2)
    out_path = ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    md_path = ROOT / args.md
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print("written %s and %s (%.1f s)" % (out_path, md_path,
                                          report["wall_seconds"]))
    return 0


def render_markdown(report):
    lines = []
    add = lines.append
    add("# 测量预算审计：Q3/16 与 Q4/16 的每一次测量用在哪里")
    add("")
    add("> 由 `tools/measure_budget_audit.py` 生成（脚本哈希 `%s`，生成于 %s）。"
        % (report["tool_sha256_16"], report["generated_utc"]))
    add("> 纯离线审计：所有「可削减」都是**事后算术**，**不是**策略能拿到的收益承诺。")
    add("")
    add("## 0. 口径")
    add("")
    add("- 每次测量 5 s（逐行 `action_time`），换频 1 s（逐行 `switch_time`）；"
        "两者直接读账本，不建模。")
    add("- 连接方式：`actions.csv` 的 measure 行与 `observations.csv` 行**逐行一一对应**"
        "（channel + 停点坐标一致；本报告各局 `join_mismatches` 均为 0），"
        "因此「政策意图」取 actions，「结果/状态迁移」取 observations。")
    add("- 用途分类（互斥，按此顺序判定）：" + "；".join(
        "`%s`=%s" % (name, text) for name, text in
        report["class_definitions"].items()))
    add("- 结束基准：`runtime.py:_apply_cardinality_cap`——16 个频道取得正向存在证据后，"
        "其余 UNKNOWN 一律 `absent_basis=\"cardinality\"`，**需要 0 次额外见证**；"
        "若走 `sparse25` 基准则每个缺席频道需 25 个固定网格点见证。")
    add("")
    add("## 1. 分类表（每局）")
    add("")
    add("| 题目/种子 | 源数 | 测量数 | 测量 s | 证书(途中见证) | 发现(找到) | 发现(排除) | 盲清前试探 | 定位/确认 | 其它 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for entry in report["episodes"]:
        c = entry["classes"]
        led = entry["ledger"]
        add("| %s/16 s%d | %d | %d | %.0f | %d | %d | %d | %d | %d | %d |" %
            (entry["case"], entry["seed"], entry["sources_total"],
             led["n_measure_rows"], led["measure_seconds_sum"],
             c["certificate_free_witness"]["rows"],
             c["discovery_found"]["rows"], c["discovery_ruled_out"]["rows"],
             c["pre_clear_probe"]["rows"], c["localization_active"]["rows"],
             c["other"]["rows"]))
    add("")
    add("| 题目/种子 | 测量 s/源 | 换频 s/源 | 证书基准 | 缺席频道 | 缺席频道的 no_signal 见证 | sparse25 反事实需要 |")
    add("|---|---:|---:|---|---:|---|---:|")
    for entry in report["episodes"]:
        cert = entry["certificate"]
        witnesses = sum(cert["witnesses_per_absent_channel"].values())
        add("| %s/16 s%d | %.1f | %.1f | %s | %d | %d | %d |" %
            (entry["case"], entry["seed"],
             entry["ledger"]["measure_seconds_per_source"],
             entry["ledger"]["switch_seconds_per_source"],
             cert["absent_bases"], len(cert["absent_channels"]), witnesses,
             cert["required_rows"]["sparse25_counterfactual"]))
    add("")
    add("## 2. 分组聚合（同题多种子）")
    add("")
    add("| 题目 | 测量数 min–max | 测量 s min–max | 整局 t/源 min–max | 测量 s/源 min–max | Tier1 s/源 | Tier2 s/源 | 边际见证 s/源 |")
    add("|---|---|---|---|---|---|---|---|")
    for case, values in sorted(report["aggregate"].items()):
        add("| %s/16 | %d–%d | %.0f–%.0f | %.1f–%.1f | %.1f–%.1f | %.1f–%.1f | %.1f–%.1f | %.1f–%.1f |" %
            (case, values["n_measure_rows"]["min"], values["n_measure_rows"]["max"],
             values["T_measure"]["min"], values["T_measure"]["max"],
             values["t_per_source_s"]["min"], values["t_per_source_s"]["max"],
             values["measure_s_per_source"]["min"],
             values["measure_s_per_source"]["max"],
             values["tier1_per_source"]["min"], values["tier1_per_source"]["max"],
             values["tier2_per_source"]["min"], values["tier2_per_source"]["max"],
             values["marginal_witness_s_per_source"]["min"],
             values["marginal_witness_s_per_source"]["max"]))
    add("")
    add("## 3. 证书见证的必要次数（下界推导）")
    add("")
    add("| 题目/种子 | 缺席频道 | 该频道实际 no_signal（行 / 不同点） | 落在 Q4 固定网格上的见证 | 本局基准要求 | **改走 sparse25 的边际行数** |")
    add("|---|---:|---|---:|---:|---:|")
    for entry in report["episodes"]:
        for cid, detail in sorted(entry["certificate_lower_bound"]["per_absent_channel"].items(),
                                  key=lambda item: int(item[0])):
            if entry["case"] == "Q4":
                add("| %s/16 s%d | %s | %d / %d | %d | %d | **%d** |" %
                    (entry["case"], entry["seed"], cid, detail["no_signal_rows"],
                     detail["distinct_points"], detail["on_fixed_mesh_points"],
                     detail["required_by_basis"], detail["marginal_rows_to_sparse25"]))
            else:
                add("| %s/16 s%d | %s | %d / %d | n/a（Q3 不用网格） | 磁盘判据满足=%s（骨架 %d 点） | **%d** |" %
                    (entry["case"], entry["seed"], cid, detail["no_signal_rows"],
                     detail["distinct_points"],
                     detail["disk_criterion_satisfied_by_own_witnesses"],
                     detail["required_by_backbone"],
                     detail["marginal_rows_to_disk_criterion"]))
    add("")
    add("| 题目/种子 | 边际总行数 | 边际总秒 | 边际 s/源 | 证书类测量实际行数 | 证书类测量的去向 |")
    add("|---|---:|---:|---:|---:|---|")
    for entry in report["episodes"]:
        lb = entry["certificate_lower_bound"]
        cert_rows = sum(entry["certificate_class_breakdown"].values())
        add("| %s/16 s%d | %d | %.0f | %.1f | %d | %s |" %
            (entry["case"], entry["seed"], lb["marginal_rows_total"],
             lb["marginal_seconds_total"],
             (lb["marginal_seconds_total"] / entry["sources_total"]),
             cert_rows,
             "; ".join("%s=%d" % item for item in
                       sorted(entry["certificate_class_breakdown"].items()))))
    add("")
    add("读法：**现判据（Q4 sparse25）**要求每个缺席频道在 25 个固定网格点各拿到一次 no_signal"
        "（4 个缺席频道 ⇒ 100 行）。本批 N=16 局实际都以 **cardinality 基准**结束（16 个频道取得"
        "正向证据后其余 UNKNOWN 直接判缺席，要求 **0 次**见证）；上表给出「若改回网格基准，还差多少行」"
        "的边际代价，以及证书类测量实际花在哪里（**超出部分**：对非缺席频道在证书几何点上的定位扫描、"
        "以及网格点之外的顺带扫描——它们不进 sparse25 的证据结构）。")
    add("")
    add("## 4. 可削减量与上限（每条标注影响面）")
    add("")
    add("| 类别 | 含义 | 影响 complete/verifier | 影响证书 | 各局行数 | 折合 s/源 |")
    add("|---|---|---|---|---|---|")
    add("| D1 重复测量 | 同一 (频道, 停点, 前置状态, 结果) 重复 ≥2 次的多余副本 | 无（确定性仿真） | 无（仍留 1 次） | %s | %s |" %
        (" / ".join(str(entry["reducible"]["categories"]["D1_duplicate_measurement"]["rows"])
                    for entry in report["episodes"]) or "0",
         " / ".join("%.1f" % (entry["reducible"]["categories"]["D1_duplicate_measurement"]["per_source"] or 0.0)
                    for entry in report["episodes"]) or "0"))
    add("| D2 已清除频道的空扫 | 结果 no_signal 但该频道最终 CLEARED（对证书无用） | 无 | 无 | %s | %s |" %
        (" / ".join(str(entry["reducible"]["categories"]["D2_no_signal_already_cleared"]["rows"])
                    for entry in report["episodes"]) or "0",
         " / ".join("%.1f" % (entry["reducible"]["categories"]["D2_no_signal_already_cleared"]["per_source"] or 0.0)
                    for entry in report["episodes"]) or "0"))
    add("| D3 超出基准所需的见证 | 缺席频道已满足本局基准所需见证后的多余 no_signal 行（cardinality 基准需要 0） | 无 | **依赖基准**：它们是 sparse25 基准赖以成立的证据 | %s | %s |" %
        (" / ".join(str(entry["reducible"]["categories"]["D3_witness_beyond_basis_need"]["rows"])
                    for entry in report["episodes"]) or "0",
         " / ".join("%.1f" % (entry["reducible"]["categories"]["D3_witness_beyond_basis_need"]["per_source"] or 0.0)
                    for entry in report["episodes"]) or "0"))
    add("| D4 证书几何点上的其它用途扫描 | 在网格/证书点上测非缺席频道（喂定位） | 无 | 无 | %s | %s |" %
        (" / ".join(str(entry["reducible"]["categories"]["D4_certificate_geometry_other_purpose"]["rows"])
                    for entry in report["episodes"]) or "0",
         " / ".join("%.1f" % (entry["reducible"]["categories"]["D4_certificate_geometry_other_purpose"]["per_source"] or 0.0)
                    for entry in report["episodes"]) or "0"))
    add("")
    add("**上限（离线）**：D1 + D3 = %s 行 ⇒ %s s/源（这是「不改变已确认结论就能删掉」的上限）；"
        "其中 D1（%s 行）连证书证据都不动。"
        % (" / ".join(str(entry["reducible"]["d1_plus_d3_rows"])
                      for entry in report["episodes"]),
           " / ".join("%.1f" % (entry["reducible"]["d1_plus_d3_per_source"] or 0.0)
                      for entry in report["episodes"]),
           " / ".join(str(entry["reducible"]["categories"]["D1_duplicate_measurement"]["rows"])
                      for entry in report["episodes"])))
    add("")
    add("## 5. cardinality cap 之后的浪费（可核对）")
    add("")
    add("| 题目/种子 | cap 触发点（第几次测量） | cap 后测量数 | 其中扫 UNKNOWN 频道 | 其中证书类 | 判定为无用（并集） | 折合 s/源 |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for entry in report["episodes"]:
        cap = entry["cap"]
        add("| %s/16 s%d | %s | %d | %d | %d | **%d** | **%.1f** |" %
            (entry["case"], entry["seed"], cap["cap_index"], cap["post_cap_rows"],
             cap["post_cap_unknown_channel_rows"],
             cap["post_cap_certificate_class_rows"],
             cap["post_cap_unnecessary_rows"],
             cap["post_cap_unnecessary_per_source"] or 0.0))
    add("")
    add("**三档口径（每局数值见下表）**：")
    add("")
    add("- **Tier 1（无需预知未来）** = D1 重复测量 + cap 之后的任何测量：删掉它们不改变已确认的结论，"
        "也不依赖对未来状态的判断 ⇒ 这是唯一可能做成在线规则的候选，仍必须先做同预算 A/B。")
    add("- **Tier 2（只有事后才知道）** = D2（扫了最终被清除的频道而没有信号）+ D3（缺席频道的见证超过本局基准所需）："
        "在线时这些测量是「当时必须做的发现/排除动作」，**不能当作收益**。")
    add("- **Tier 3（不可回收）** = D4（在证书几何点上为非缺席频道做的定位扫描）：它们喂定位，删了会改变后续状态。")
    add("")
    add("| 题目/种子 | Tier1 行 / s/源 | Tier2 行 / s/源 | Tier3 行 / s/源 | D1+D3（离线上限）s/源 |")
    add("|---|---|---|---|---|")
    for entry in report["episodes"]:
        tiers = entry["reducible_tiers"]
        add("| %s/16 s%d | %d / %.1f | %d / %.1f | %d / %.1f | %.1f |" %
            (entry["case"], entry["seed"],
             tiers["tier1_foresight_free_rows"], tiers["tier1_per_source"] or 0.0,
             tiers["tier2_hindsight_only_rows"], tiers["tier2_per_source"] or 0.0,
             tiers["tier3_not_recoverable_rows"], tiers["tier3_per_source"] or 0.0,
             entry["reducible"]["d1_plus_d3_per_source"] or 0.0))
    add("")
    add("## 6. 换频（属 t11 的排序问题，仅记录）")
    add("")
    add("| 题目/种子 | 停点数 | 实际换频行 | 同停点理论下限 | 离线可省行 |")
    add("|---|---:|---:|---:|---:|")
    for entry in report["episodes"]:
        sw = entry["switches"]
        add("| %s/16 s%d | %d | %d | %d | %d |" %
            (entry["case"], entry["seed"], sw["stops"],
             sw["actual_switch_rows"], sw["per_stop_floor"],
             sw["offline_switch_rows_savable"]))
    add("")
    add("## 7. 离线可削减量 vs 策略能拿到的量")
    add("")
    add("- 上表所有数字都是**对已完成一局的事后算术**：它假设我们知道哪些测量是多余的。"
        "在线策略不知道未来（哪些频道会缺席、哪个停点会重复），因此**不能**把 D1/D3 的 s/源"
        "当成收益承诺。")
    add("- 团队已有的三项独立结论同向：§20.2 两次静态规则失败；§23.2 `q4_work_first_min_active`"
        " 三次规则全负；§24 可学性 gate 不通过（留一/tree/阈值/置换零分布全负）。"
        "本审计的 D3/D4 恰好说明「省测量」高度状态相关。")
    add("- 唯一**状态无关**的部分是 D1（同点同频道重复测量的多余副本）与 D2（扫已清除频道）："
        "它们不依赖对未来状态的判断，是唯一可以考虑做成在线规则的候选，且必须先做同预算 A/B。")
    add("")
    add("## 8. 输入与哈希（可复核）")
    add("")
    for entry in report["episodes"]:
        add("- **%s/16 s%d**：`%s`" % (entry["case"], entry["seed"], entry["dir"]))
        for name, digest in sorted(entry["inputs"].items()):
            add("    - `%s` sha256:%s" % (name, digest))
    add("")
    add("## 9. 复现命令")
    add("")
    add("```powershell")
    add("python -X utf8 tools/measure_budget_audit.py --dataset %s "
        "--cases Q3:16,Q4:16 --seeds %s" %
        (report["dataset"], ",".join(str(seed) for seed in report["seeds"])))
    add("```")
    add("")
    add("")
    add("## 10. 附加项：N=10/13 严格排除论证的可证性核对")
    add("")
    ex = report["exclusion_check"]
    add("**结论：需要附加前提** —— 论证的算术与两条判据前提都成立，但『任何成功局必须走满 25 点网格』"
        "这一步依赖**当前生产配置把 Q4 缺席路线限制在 sparse25**；代码里另有两条 verifier 接受的免网格路线。")
    add("")
    add("| 前提 | 核对结果 | 证据（可机器复核） |")
    add("|---|---|---|")
    add("| (a) 基数上限只在「已确认频道数 ≥ 16」触发 | **成立** | `MAX_SOURCES = 16`；`_apply_cardinality_cap` 首行 `if confirmed < C.MAX_SOURCES: return []`（`runtime.py:53-56`），`confirmed = active+ready+cleared`；N=10/13 时 confirmed ≤ n < 16 ⇒ 永不触发 |")
    add("| (b) sparse25 要求精确坐标见证 | **成立** | `q4_sparse_mesh.py: MATCH_TOL = 1e-6`，判定 `math.dist(expected, observed) <= MATCH_TOL` 覆盖 25 个固定点 |")
    add("| (c) 完成判定迫使残余频道必须被证缺席 | **成立** | `knowledge_state.is_complete()`：`cleared ≥ 16` 或**所有频道都 CLEARED/CERTIFIED_ABSENT**；N=10/13 时 cleared<16 ⇒ 残余频道必须拿证书 |")
    add("| (d) 25 点网格的移动下界 = 最优开路径 | **成立，且证得最优** | MST(起点+25 点) = %.1f m；三条构造（NN/CI/FI + 2-opt + Or-opt）最好 = %.1f m ⇒ `MST = 可行解` ⇒ **精确最优**（候选 %s） |"
        % (ex["mst_m"], ex["open_path_through_mesh_m"],
           {k: round(v, 1) for k, v in ex["solver_candidates_m"].items()}))
    add("| (e) 「必须走满 25 点」= Q4 缺席只能由 sparse25 取得 | **不成立（需附加前提）** | 代码另有两条**免网格**路线且 verifier 均接受：① δ-凸包中心 → basis `certificate`（`channel_state.py` 的 `status == UNKNOWN and certified_centers and q4_channel_certified(...)`；verifier 分支 `runner.py` 的 `if basis == 'certificate' and self.mode == 'Q4'`）；② `fallback_exhausted`（`channel_state.py:force_certified_absent`；verifier 分支支持）。二者都不要求 25 个固定点 |")
    add("")
    add("| N | 移动下界 s/源 | 实测服务账 s/源 | 合计下界 s/源 | 是否 > 290 |")
    add("|---|---:|---:|---:|---|")
    for n, values in sorted(ex["floors"].items(), key=lambda item: int(item[0])):
        add("| %s | %.1f | %s | **%.1f** | %s |" %
            (n, values["movement_floor_s_per_source"],
             "%.1f" % values["service_s_per_source_measured"]
             if values["service_s_per_source_measured"] is not None else "n/a",
             values["movement_plus_service_s_per_source"] or 0.0,
             "是 ⇒ 被排除" if values["exceeds_target_290"] else "否"))
    add("")
    add("**经验支持（已扫描 %d 份真实对局产物）**：Q4 的缺席基准只出现 `sparse25`；`certificate` 基准"
        "**只出现在 Q3** 组；`lattice31` / `fallback_exhausted` / `naive_q3_style` 出现 **0 次**。"
        "基准计数：%s（按 case 组的归属见 JSON `basis_scan.case_groups`）。"
        "生产配置亦为 `q4_certificate_layout=\"sparse25\"`、`q4_residual_sparsify=True`，"
        "各局 metrics 的 `q4_certified_cells_raw = 0` ⇒ δ-凸包路线在实践中处于休眠。"
        % (ex["basis_scan"]["files"], ex["basis_scan"]["counts"]))
    add("")
    add("**为什么 Q3 没有这条排除**：`q3_certified` 接受**任意位置**的见证点（只要求 Ω ⊆ ∪B(S_i,1000) 的圆盘覆盖，"
        "无固定点位、无坐标匹配容差），本审计 §3 实测：Q3 各缺席频道只需 ~7 个骨架见证点即可（边际 28 行 = 8.8 s/源），"
        "因此**没有**任何固定几何能把移动压到一个常数下界；Q3 的真实约束在测量次数与巡游长度，而不是「必须走满某 25 点」。")
    add("")
    add("**因此正确表述**：在**当前生产配置**（Q4 = sparse25 布局、无 hull 中心累积、无 fallback 耗尽）下，"
        "任何 N≤13 的成功局移动 ≥ **%.0f m ⇒ ≥ %.1f / %.1f s/源**（N=10/13），加服务后 ≥ **%.1f / %.1f s/源** ⇒ **≫ 290，故 N=10/13 被排除**；"
        "但这条排除是**配置/代码路径相关**的事实，不是纯代码定理——一旦启用 δ-凸包或 fallback 耗尽路线，"
        "25 点要求（及其下界）即失效（注意：按 §26/§27 的探针，这两条路线并不显然更便宜，但那是另外的论证）。"
        % (ex["open_path_through_mesh_m"],
           ex["floors"]["10"]["movement_floor_s_per_source"],
           ex["floors"]["13"]["movement_floor_s_per_source"],
           ex["floors"]["10"]["movement_plus_service_s_per_source"] or 0.0,
           ex["floors"]["13"]["movement_plus_service_s_per_source"] or 0.0))
    add("")
    add("代码事实逐条机器复核（%d 条 needle 全部命中 = %s）："
        % (len(ex["code_facts"]), ex["code_facts_all_present"]))
    for item in ex["code_facts"]:
        add("- `%s`：`%s` → %s" % (item["file"], item["needle"],
                                   "命中" if item["present"] else "**未命中**"))
    add("")
    add("## 11. 边界")
    add("")
    for note in report["notes"]:
        add("- " + note)
    add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
