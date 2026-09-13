"""Full-ledger labels for the *candidate set* question on the production policy.

Question answered: at a real decision point of the **production** policy, what
does it cost to force one action of the extended candidate family instead of
the action production took - and is the label a function of what the policy can
observe at that moment?

Extended candidate family (the family the teacher prefers, sections 20.2 / 21
of ``tuning_runs/ROUND1_MERGED_ROUTING.md``):

  * ``measure`` at the region centre, at the perpendicular baseline point
    (90 deg off the last bearing) and at the NBV point of every ACTIVE channel,
    with the runner's own default scan set (no ``scan_variant`` meta), so a
    candidate costs exactly what the equivalent production stop costs;
  * ``clear`` on every READY channel.

Incumbent: the mission production itself returns (``PRODUCTION``).

Method (same discipline as ``tools/teacher_probe.py``):

1. run production once and record, at every ``Scheduler.decide`` call, the
   online-observable state, the produced mission and the candidate specs;
2. for each sampled decision point, re-run production with its own mission
   forced and assert the whole-episode ledger equals the baseline
   (``selfcheck_error_s``) - a broken replay would show up here;
3. for every candidate, re-run the episode with that candidate forced at the
   sampled step and the untouched production policy afterwards; the recorded
   quantity is the whole ledger ``T_total_virtual``, so
   ``delta = production_total - total(candidate)`` is the realised consequence
   of that single change in seconds (``delta > 0`` = the candidate was cheaper);
4. record whether the override was actually applied (``applied``) and which
   mission was applied, so a candidate that could not be built (channel no
   longer ACTIVE, ...) can never be mistaken for a tie.

Only quantities the online policy may read are stored as features: never the
source count ``n``, the scenario, the ground truth or any hidden position.
``n``/``seed`` are stored as *metadata* for grouping and for the post-hoc
"N=10 vs N=16" diagnostic; ``tools/action_value_signal.py`` excludes them from
the feature set.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import multiprocessing as mp
import shutil
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

import teacher_probe as TP                      # noqa: E402
import production                               # noqa: E402
from state.channel_state import ChannelStatus   # noqa: E402

# Private scratch root.  ``teacher_probe.build_runner`` reads its module-level
# ``OUT_ROOT`` and does ``shutil.rmtree(OUT_ROOT / tag)`` before every replay;
# the tag carries only the case and the step, never the seed, so two concurrent
# drivers sharing that root would delete each other's working directory.  This
# tool therefore rebinds the global to a root of its own and cleans up *that*
# root (``teacher_probe.py`` itself is never modified).  The rebinding is read
# by ``build_runner`` at call time, so it takes effect for every later call.
SCRATCH_ROOT = ROOT / "tuning_runs" / "teach_probe_value"
TP.OUT_ROOT = SCRATCH_ROOT


# ----------------------------------------------------------------------
# observable features
# ----------------------------------------------------------------------

def _mec_stats(channels):
    radii = [float(ch.mec[1]) for ch in channels if ch.mec]
    if not radii:
        return 0.0, 0.0, 0.0
    return statistics.mean(radii), min(radii), max(radii)


def _min_dist(position, channels):
    distances = [math.dist(position, ch.mec[0]) for ch in channels if ch.mec]
    return round(min(distances), 1) if distances else -1.0


def _angle_gap(deg_a, deg_b):
    diff = abs((float(deg_a) - float(deg_b)) % 360.0)
    return round(min(diff, 360.0 - diff), 1)


def state_features(ks, position, current_channel, coverage, step_index, vtime):
    """Online-observable state at one decision (no n / scenario / truth)."""
    active = ks.by_status(ChannelStatus.ACTIVE)
    ready = ks.by_status(ChannelStatus.READY)
    unknown = ks.by_status(ChannelStatus.UNKNOWN)
    cleared = ks.by_status(ChannelStatus.CLEARED)
    certified = ks.by_status(ChannelStatus.CERTIFIED_ABSENT)
    mean_r, min_r, max_r = _mec_stats(active)
    cover_points = coverage.get("_coverage_points") or []
    cover_index = coverage.get("_coverage_index") or 0
    return {
        "step": int(step_index),
        "t_elapsed": round(float(vtime), 1),
        "n_active": len(active),
        "n_ready": len(ready),
        "n_unknown": len(unknown),
        "n_cleared": len(cleared),
        "n_certified": len(certified),
        "n_confirmed": len(active) + len(ready) + len(cleared) + len(certified),
        "cov_index": int(cover_index),
        "cov_remaining": max(0, len(cover_points) - int(cover_index)),
        "d_active": _min_dist(position, active),
        "d_ready": _min_dist(position, ready),
        "mec_mean": round(mean_r, 1),
        "mec_min": round(min_r, 1),
        "mec_max": round(max_r, 1),
        "n_direction_obs": sum(1 for ch in ks.channels.values()
                               for obs in ch.observations
                               if obs["result"] == "direction"),
        "current_channel": int(current_channel or 0),
    }


def action_features(ks, position, current_channel, spec, planner=None):
    """Features of one candidate action (observable at decision time).

    ``planner`` is the runner's ``plan_stop`` (wired to the scheduler as
    ``stop_planner``); when given, the four pre-registered scan-set features are
    computed from the executor's own plan for this candidate, so nothing here
    needs information the online policy cannot compute at decision time.
    """
    channel = ks.channels.get(spec["channel"])
    features = {
        "kind_measure": 1.0 if spec["kind"] == "measure" else 0.0,
        "kind_clear": 1.0 if spec["kind"] == "clear" else 0.0,
        "pt_center": 1.0 if spec["point_name"] == "center" else 0.0,
        "pt_perp": 1.0 if spec["point_name"] == "perp" else 0.0,
        "pt_nbv": 1.0 if spec["point_name"] == "nbv" else 0.0,
        "pt_ready": 1.0 if spec["point_name"] == "ready" else 0.0,
        "is_current": 1.0 if (current_channel is not None
                              and spec["channel"] is not None
                              and int(current_channel) == int(spec["channel"]))
                      else 0.0,
        "d_point": -1.0,
        "d_ratio": -1.0,
        "d_ch_mec": -1.0,
        "ch_mec_radius": -1.0,
        "ch_n_obs": -1.0,
        "ch_n_direction": -1.0,
        "bearing_gap": -1.0,
        "scan_set_size": -1.0,
        "scan_set_cost_s": -1.0,
        "scan_set_active_reach": -1.0,
        "scan_variant_is_default": -1.0,
    }
    if planner is not None:
        _scan_features(ks, spec, planner, features)
    if channel is None:
        return features
    if spec["point"] is not None:
        features["d_point"] = round(math.dist(position, spec["point"]), 1)
    if channel.mec:
        features["d_ch_mec"] = round(math.dist(position, channel.mec[0]), 1)
        features["ch_mec_radius"] = round(float(channel.mec[1]), 1)
        if spec["point"] is not None and float(channel.mec[1]) > 0:
            features["d_ratio"] = round(
                math.dist(position, spec["point"]) / float(channel.mec[1]), 3)
    directions = [obs for obs in channel.observations
                  if obs["result"] == "direction"]
    features["ch_n_obs"] = len(channel.observations)
    features["ch_n_direction"] = len(directions)
    if directions and spec["point"] is not None:
        dx = float(spec["point"][0]) - position[0]
        dy = float(spec["point"][1]) - position[1]
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            heading = math.degrees(math.atan2(dy, dx)) % 360.0
            features["bearing_gap"] = _angle_gap(
                heading, directions[-1]["bearing"])
    return features


# ----------------------------------------------------------------------
# candidate family
# ----------------------------------------------------------------------

VARIANTS = ("primary", "active", "discover", "full")


def _plan_measures(plan):
    """Ordered channel list of a stop plan (measure: ``measures``; clear: the
    success branch, which is itself a channel sequence)."""
    if not plan:
        return []
    if isinstance(plan, list):
        return list(plan)
    value = (plan.get("success") if plan.get("kind") == "clear"
             else plan.get("measures"))
    if isinstance(value, dict):
        value = value.get("measures") or []
    return list(value or [])


def _scan_features(ks, spec, planner, features):
    """The four pre-registered scan-set features, from the executor's plan."""
    mission = TP.build_mission(spec, ks)
    if mission is None:
        return
    measures = _plan_measures(planner(mission))
    count = len(measures)
    features["scan_set_size"] = float(count)
    features["scan_set_cost_s"] = float(6 * count - 1) if count else 0.0
    active_ids = {ch.channel_id for ch in ks.by_status(ChannelStatus.ACTIVE)}
    features["scan_set_active_reach"] = float(
        sum(1 for cid in measures if cid in active_ids))
    default_spec = dict(spec, variant=None)
    default_mission = TP.build_mission(default_spec, ks)
    default_measures = (_plan_measures(planner(default_mission))
                        if default_mission is not None else [])
    features["scan_variant_is_default"] = (
        1.0 if measures == default_measures else 0.0)


def family_specs(ks, position, limit_points=3, family="stop"):
    """Candidate family.

    ``stop``: region centre / perpendicular baseline / NBV per ACTIVE channel
    with the runner's default scan set, plus clear per READY channel (the
    first-half corpus).  ``joint``: the same points crossed with the four named
    ``scan_variant`` values - the pre-registered (stop x scan set) cell.
    """
    specs = []
    variants = VARIANTS if family == "joint" else (None,)
    for channel in ks.by_status(ChannelStatus.ACTIVE):
        if channel.mec is None:
            continue
        for name, point in TP.candidate_points(channel, position,
                                               limit_points).items():
            for variant in variants:
                specs.append({"kind": "measure", "channel": channel.channel_id,
                              "point": (float(point[0]), float(point[1])),
                              "point_name": name, "variant": variant})
    for channel in ks.by_status(ChannelStatus.READY):
        specs.append({"kind": "clear", "channel": channel.channel_id,
                      "point": None, "point_name": "ready", "variant": None})
    return specs


def _point_key(point):
    if point is None:
        return None
    return (round(float(point[0]), 3), round(float(point[1]), 3))


def spec_key(spec):
    """Comparable identity of a candidate: clears are identified by channel.

    The scan variant is part of the identity: in the joint family several
    candidates share the same stop point and differ only in their scan set.
    """
    if spec["kind"] == "clear":
        return ("clear", int(spec["channel"]), None, None)
    return ("measure", int(spec["channel"]), _point_key(spec["point"]),
            spec.get("variant"))


def digest_key(digest):
    if digest is None:
        return None
    if digest.get("kind") == "clear":
        return ("clear", digest.get("channel"), None, None)
    return (digest.get("kind"), digest.get("channel"),
            _point_key(digest.get("point")), digest.get("scan_variant"))


def production_spec(digest):
    if digest is None:
        return {"kind": None, "channel": None, "point": None,
                "point_name": "production", "variant": None}
    return {"kind": digest.get("kind"), "channel": digest.get("channel"),
            "point": (None if digest.get("point") is None
                      else (float(digest["point"][0]), float(digest["point"][1]))),
            "point_name": "production",
            "variant": digest.get("scan_variant")}


def spec_json(spec):
    return {"kind": spec["kind"], "channel": spec["channel"],
            "point": (None if spec["point"] is None
                      else [float(spec["point"][0]), float(spec["point"][1])]),
            "point_name": spec["point_name"], "variant": spec["variant"]}


# ----------------------------------------------------------------------
# replay machinery (mirrors teacher_probe.run_one, plus an applied flag)
# ----------------------------------------------------------------------

def replay(mode, seed, n, scenario, tag, target, spec):
    """Force ``spec`` (or production's own mission) at step ``target``.

    Returns ``(report, applied)`` where ``applied`` is ``"production"``,
    ``"rejected"`` (the candidate could not be built from this state) or the
    digest of the mission that actually replaced the decision.
    """
    runner, scheduler = TP.build_runner(mode, seed, n, scenario, tag)
    original = scheduler.decide
    counter = {"index": 0}
    box = {"applied": None}

    def decide(ks, position, current_channel):
        index = counter["index"]
        counter["index"] += 1
        snapshot = {name: getattr(scheduler, name, None)
                    for name in TP.COVERAGE_FIELDS}
        mission = original(ks, position, current_channel)
        if index == target:
            if spec is TP.PRODUCTION:
                box["applied"] = "production"
                return mission
            replacement = TP.build_mission(spec, ks)
            if replacement is None:
                box["applied"] = "rejected"
                return mission
            if not (mission is not None and mission.kind == "scan"
                    and replacement.kind == "scan"
                    and mission.target == replacement.target):
                for name, value in snapshot.items():
                    setattr(scheduler, name, value)
            box["applied"] = TP.action_digest(replacement)
            return replacement
        return mission

    scheduler.decide = decide
    report = runner.run()
    shutil.rmtree(SCRATCH_ROOT / tag, ignore_errors=True)
    return report, box["applied"]


def record_case(mode, seed, n, scenario, tag, family="stop"):
    """Run production once, recording the observable state at every decision."""
    runner, scheduler = TP.build_runner(mode, seed, n, scenario, tag)
    original = scheduler.decide
    counter = {"index": 0}
    records = []

    def decide(ks, position, current_channel):
        index = counter["index"]
        counter["index"] += 1
        coverage = {name: getattr(scheduler, name, None)
                    for name in TP.COVERAGE_FIELDS}
        vtime = float(getattr(runner.executor, "virtual_time", 0.0) or 0.0)
        mission = original(ks, position, current_channel)
        digest = TP.action_digest(mission)
        records.append({
            "index": index,
            "state": state_features(ks, position, current_channel, coverage,
                                    index, vtime),
            "production": digest,
            "production_features": action_features(
                ks, position, current_channel, production_spec(digest),
                planner=runner.plan_stop),
            "specs": [{"spec": spec_json(sp),
                       "features": action_features(ks, position,
                                                   current_channel, sp,
                                                   planner=runner.plan_stop)}
                      for sp in family_specs(ks, position, family=family)],
        })
        return mission

    scheduler.decide = decide
    report = runner.run()
    shutil.rmtree(SCRATCH_ROOT / tag, ignore_errors=True)
    return report, records


def sample_indices(records, k):
    """Evenly spaced decision indices that have at least one candidate."""
    usable = [rec["index"] for rec in records if rec["specs"]]
    if not usable:
        return []
    if len(usable) <= k:
        return usable
    stride = len(usable) / float(k)
    picked = [usable[min(len(usable) - 1, int(i * stride))] for i in range(k)]
    return sorted(set(picked))


def label_case(mode, seed, n, k_steps, worker, limit_points=3,
               family="stop"):
    scenario = "random" if mode == "Q3" else "mixed"
    tag = "w%02d_%s_%d_%d" % (worker, mode, n, seed)
    started = time.time()
    base_report, records = record_case(mode, seed, n, scenario,
                                       tag + "_base", family=family)
    baseline = TP.total_time(base_report)
    base_ok = bool(base_report.get("complete")) and bool(
        base_report.get("verifier_all_ok"))
    indices = sample_indices(records, k_steps)
    by_index = {rec["index"]: rec for rec in records}
    rows = []
    decisions = []
    for index in indices:
        rec = by_index[index]
        digest = rec["production"]
        check_report, _ = replay(mode, seed, n, scenario,
                                 "%s_chk%d" % (tag, index), index, TP.PRODUCTION)
        prod_total = TP.total_time(check_report)
        selfcheck = prod_total - baseline

        specs = []
        seen = set()
        # Production's own action is the incumbent (delta = 0 by construction).
        # A candidate identical to it would be a duplicate run; only skip when
        # production's mission carries no scan-variant of its own.
        if digest is not None and digest.get("scan_variant") is None:
            seen.add(digest_key(digest))
        for entry in rec["specs"]:
            raw = entry["spec"]
            spec = {"kind": raw["kind"], "channel": raw["channel"],
                    "point": (None if raw["point"] is None
                              else (float(raw["point"][0]),
                                    float(raw["point"][1]))),
                    "point_name": raw["point_name"],
                    "variant": raw.get("variant")}
            if spec_key(spec) in seen:
                continue
            seen.add(spec_key(spec))
            specs.append((spec, entry["features"]))
        bare_specs = [item[0] for item in specs]

        row_base = {
            "mode": mode, "n": int(n), "seed": int(seed), "index": int(index),
            "baseline": round(baseline, 3),
            "production_total": round(prod_total, 3),
            "selfcheck_error_s": round(selfcheck, 6),
            "state": rec["state"],
        }
        rows.append(dict(row_base, **{
            "action": production_spec(digest),
            "action_features": rec["production_features"],
            "is_production": True,
            "applied": "production",
            "delta": 0.0,
            "total": round(prod_total, 3),
            "complete": bool(check_report.get("complete")),
            "verifier_ok": bool(check_report.get("verifier_all_ok")),
        }))

        candidates = 0
        rejected = 0
        for spec, candidate_features in specs:
            report, applied = replay(mode, seed, n, scenario,
                                     "%s_c%d_%d" % (tag, index, candidates),
                                     index, spec)
            total = TP.total_time(report)
            rows.append(dict(row_base, **{
                "action": spec_json(spec),
                "action_features": candidate_features,
                "is_production": False,
                "applied": ("candidate" if applied != "rejected"
                            else "rejected"),
                "delta": round(prod_total - total, 3),
                "total": round(total, 3),
                "complete": bool(report.get("complete")),
                "verifier_ok": bool(report.get("verifier_all_ok")),
            }))
            candidates += 1
            if applied == "rejected":
                rejected += 1
        decisions.append(dict(row_base, **{
            "candidates": len(bare_specs),
            "rejected": rejected,
            "production_action": digest,
            "base_complete": base_ok,
        }))
        print("   %s/%d seed %d step %3d: cand=%3d rej=%d selfcheck=%+.3f s"
              % (mode, n, seed, index, candidates, rejected, selfcheck),
              flush=True)
    return {
        "mode": mode, "n": int(n), "seed": int(seed), "baseline": baseline,
        "base_complete": base_ok, "decisions": len(indices),
        "wall_seconds": round(time.time() - started, 1), "rows": rows,
        "decision_rows": decisions,
    }


def _sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _rel(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def provenance_snapshot(args, cases, seeds, rows, decision_rows, outputs):
    """Timestamped, hash-bearing config snapshot for the labels just written.

    The tree is not under version control, so a stored label file is only
    reproducible if it carries: the exact command, the time, the policy
    configuration actually used (production.split_config per mode), the code
    hashes of every file that can change a decision or an execution, and the
    hash of the label files themselves.
    """
    modes = sorted({mode for mode, _ in cases})
    policy = {}
    for mode in modes:
        scheduler_cfg, runner_cfg = production.split_config(mode)
        policy[mode] = production.policy_snapshot(mode, scheduler_cfg,
                                                  runner_cfg)
    selfcheck = [abs(row["selfcheck_error_s"]) for row in decision_rows]
    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "command": "python -X utf8 " + " ".join(sys.argv),
        "working_directory": str(Path.cwd()),
        "tool": {"path": "tools/action_value_labels.py",
                 "sha256": _sha256_file(ROOT / "tools"
                                        / "action_value_labels.py")},
        "reused_candidate_tool": {
            "path": "tools/teacher_probe.py",
            "sha256": _sha256_file(ROOT / "tools" / "teacher_probe.py"),
            "note": "build_runner / run_one / action_digest / build_mission / "
                    "candidate_points are imported, not copied",
        },
        "problem": {
            "cases": ["%s:%d" % (mode, n) for mode, n in cases],
            "seeds": list(seeds),
            "steps_per_episode": int(args.steps_per_episode),
            "limit_points": int(args.limit_points),
            "workers": int(args.workers),
            "candidate_family": "measure at region centre / perpendicular "
                                "baseline / NBV of every ACTIVE channel + "
                                "clear on every READY channel; incumbent = "
                                "production's own mission at that decision; "
                                "scan sets = "
                                + ("{primary,active,discover,full}"
                                   if args.family == "joint" else
                                   "runner default (no scan_variant)"),
        },
        "outputs": outputs,
        "counts": {
            "label_rows": len(rows),
            "candidate_rows": sum(1 for row in rows
                                  if not row["is_production"]),
            "decision_rows": len(decision_rows),
            "rejected_candidates": sum(int(row.get("rejected") or 0)
                                       for row in decision_rows),
            "selfcheck_exact": sum(1 for value in selfcheck if value < 1e-9),
            "selfcheck_max_abs_s": max(selfcheck) if selfcheck else 0.0,
            "incomplete_or_unverified": sum(
                1 for row in rows
                if not (row.get("complete") and row.get("verifier_ok"))),
        },
        "policy": policy,
        "feature_policy": {
            "observable_only": True,
            "excluded": ["source count n", "seed", "scenario", "ground truth",
                         "hidden source positions"],
            "note": "n/seed are stored as row metadata for grouping and for "
                    "the diagnostic only; tools/action_value_signal.py never "
                    "puts them in the feature vector",
        },
    }


def run_task(task):
    """Picklable single-argument wrapper for ``Pool.imap_unordered``."""
    return label_case(*task)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="Q3:10,Q3:13,Q3:16")
    parser.add_argument("--seeds", default="101,202,303,404,505")
    parser.add_argument("--steps-per-episode", type=int, default=6)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--limit-points", type=int, default=3)
    parser.add_argument("--family", default="stop", choices=("stop", "joint"),
                        help="stop = points with the runner default scan set "
                             "(first half); joint = points x the four named "
                             "scan_variant values (pre-registered 2nd half)")
    parser.add_argument("--baseline-only", action="store_true",
                        help="record the baseline run only (timing / step "
                             "count check, no candidate replays)")
    parser.add_argument("--out", default="tuning_runs/action_value_labels.jsonl")
    parser.add_argument("--decisions-out",
                        default="tuning_runs/action_value_decisions.jsonl")
    parser.add_argument("--provenance", default=None,
                        help="timestamped config/hash snapshot for the labels "
                             "written by this run (default: <out>_provenance"
                             ".json)")
    args = parser.parse_args()

    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    cases = []
    for item in args.cases.split(","):
        mode, n = item.split(":")
        cases.append((mode.upper(), int(n)))
    seeds = [int(s) for s in args.seeds.split(",")]

    if args.baseline_only:
        for mode, n in cases:
            for seed in seeds:
                scenario = "random" if mode == "Q3" else "mixed"
                started = time.time()
                report, records = record_case(mode, seed, n, scenario,
                                              "dry_%s_%d_%d" % (mode, n, seed))
                print("%s/%d seed %d: %d decisions, T=%.0f s, complete=%s, "
                      "verifier=%s, %.2f s wall, sample=%s"
                      % (mode, n, seed, len(records),
                         TP.total_time(report), report.get("complete"),
                         report.get("verifier_all_ok"),
                         time.time() - started,
                         [rec["index"] for rec in records][:8]), flush=True)
        return 0

    tasks = [(mode, seed, n, args.steps_per_episode, i, args.limit_points,
              args.family)
             for i, (mode, n, seed) in enumerate(
                 [(m, nn, sd) for m, nn in cases for sd in seeds])]
    results = []
    if args.workers <= 1:
        for task in tasks:
            results.append(label_case(*task))
    else:
        with mp.Pool(processes=args.workers) as pool:
            for result in pool.imap_unordered(run_task, tasks):
                results.append(result)
                print("== finished %s/%d seed %d: %d decisions in %.1f s =="
                      % (result["mode"], result["n"], result["seed"],
                         result["decisions"], result["wall_seconds"]),
                      flush=True)

    rows = []
    decision_rows = []
    for result in sorted(results, key=lambda r: (r["mode"], r["n"], r["seed"])):
        rows.extend(result["rows"])
        decision_rows.extend(result["decision_rows"])
    out = ROOT / args.out
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    decisions_out = ROOT / args.decisions_out
    with decisions_out.open("w", encoding="utf-8") as handle:
        for row in decision_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("\nwrote %d label rows (%d decisions) -> %s"
          % (len(rows), len(decision_rows), out))
    print("wrote decision rows -> %s" % decisions_out)
    errors = [abs(row["selfcheck_error_s"]) for row in decision_rows]
    if errors:
        print("self-check error: max %.3e s, %d/%d exact"
              % (max(errors), sum(1 for e in errors if e < 1e-6), len(errors)))

    provenance = (Path(args.provenance) if args.provenance
                  else ROOT / (Path(args.out).stem + "_provenance.json"))
    if not provenance.is_absolute():
        provenance = ROOT / provenance
    snapshot = provenance_snapshot(
        args, cases, seeds, rows, decision_rows,
        {"labels": {"path": _rel(out), "sha256": _sha256_file(out),
                    "rows": len(rows)},
         "decisions": {"path": _rel(decisions_out),
                       "sha256": _sha256_file(decisions_out),
                       "rows": len(decision_rows)}})
    provenance.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print("wrote provenance snapshot -> %s (%s)"
          % (_rel(provenance), snapshot["generated_at"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

