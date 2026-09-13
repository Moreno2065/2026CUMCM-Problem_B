"""Offline choice probe with self-validation.

Question answered: at a real decision point, is there a *joint* action
``(next stop, channel set, order)`` whose execution - followed by the untouched
production policy - finishes the whole task cheaper than what production did?

Correct replay requires three properties, all asserted by this tool:

1. **Side effects preserved.** ``Scheduler.decide`` mutates internal state
   (coverage index, pending coverage, probe bookkeeping).  The probe therefore
   always calls the original ``decide`` and only replaces the *returned*
   mission, so the continuation sees the same bookkeeping as production.
2. **Coverage bookkeeping restored on override.** If the overridden action is
   not the coverage stop production chose, the coverage cursor is rolled back,
   because that stop was not actually visited.
3. **Production replay is exact.** For every sampled point the tool re-runs
   with production's own mission forced and asserts the total time matches the
   baseline exactly; the per-point error is stored in the results.

Conclusion discipline: a positive regret means *a better action existed in the
candidate set on this map*.  It does NOT show that online-observable
information suffices to pick it, and it does not predict a faster policy.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from executor.action_executor import ActionExecutor            # noqa: E402
from experiment.config import MainlineConfig                   # noqa: E402
from experiment.simulator import SimulatorBackend, SyntheticSimulator  # noqa: E402
from policy import localization                                # noqa: E402
from policy.scheduler import Mission                           # noqa: E402
from state.channel_state import ChannelStatus                  # noqa: E402
import production                                              # noqa: E402
from runtime import V2GameRunner                               # noqa: E402
from learned_search.scheduler import LearnedSearchScheduler    # noqa: E402

VARIANTS = ("primary", "active", "discover", "full")
PRODUCTION = "PRODUCTION"
OUT_ROOT = ROOT / "tuning_runs" / "teach_probe"

COVERAGE_FIELDS = ("_coverage_index", "_coverage_pending_point",
                   "_coverage_pending_active", "_rolling_coverage",
                   "_rolling_coverage_age")


def build_runner(mode, seed, n, scenario, tag):
    simulator = SyntheticSimulator(mode, int(seed), n_sources=n,
                                   scenario=scenario)
    executor = ActionExecutor(SimulatorBackend(simulator, robot_id="TEACH"))
    scheduler_cfg, runner_cfg = production.split_config(mode)
    out_dir = OUT_ROOT / tag
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = V2GameRunner(mode, executor, str(out_dir), simulator=simulator,
                          config=MainlineConfig(**runner_cfg))
    scheduler = LearnedSearchScheduler(mode, **scheduler_cfg)
    runner.attach_scheduler(scheduler)
    return runner, scheduler


def total_time(report):
    return float(report["metrics"]["T_total_virtual"])


def action_digest(mission):
    if mission is None:
        return None
    return {
        "kind": mission.kind,
        "channel": mission.channel,
        "point": [round(mission.target[0], 3), round(mission.target[1], 3)],
        "channels": list(mission.channels or ()),
        "meta_kind": mission.meta.get("kind"),
        "scan_variant": mission.meta.get("scan_variant"),
    }


def candidate_points(channel, position, limit=3):
    out = {"center": channel.mec[0]}
    directions = [obs for obs in channel.observations
                  if obs["result"] == "direction"]
    if directions and len(out) < limit:
        last = directions[-1]
        theta = math.radians(last["bearing"])
        offset = min(900.0, max(200.0, 2.0 * float(channel.mec[1])))
        angle = theta + math.pi / 2.0
        out["perp"] = (last["position"][0] + offset * math.cos(angle),
                       last["position"][1] + offset * math.sin(angle))
    for point in localization.candidate_points(
            channel, position, opportunistic_reuse=True):
        if len(out) >= limit:
            break
        if math.dist(point, position) >= 1.0:
            out.setdefault("nbv", point)
    return out


def enumerate_candidates(ks, position, limit_points=3):
    out = []
    for channel in ks.by_status(ChannelStatus.ACTIVE):
        for name, point in candidate_points(channel, position,
                                            limit_points).items():
            for variant in VARIANTS:
                out.append({"kind": "measure", "channel": channel.channel_id,
                            "point": (float(point[0]), float(point[1])),
                            "point_name": name, "variant": variant})
    for channel in ks.by_status(ChannelStatus.READY):
        out.append({"kind": "clear", "channel": channel.channel_id,
                    "point": None, "point_name": "ready", "variant": None})
    return out


def build_mission(spec, ks):
    if spec["kind"] == "measure":
        channel = ks[spec["channel"]] if spec["channel"] in ks.channels else None
        if channel is None or channel.status != ChannelStatus.ACTIVE:
            return None
        return Mission("measure", spec["point"], channel=spec["channel"],
                       meta={"kind": "teacher_probe",
                             "scan_variant": spec["variant"]})
    if spec["kind"] == "clear":
        channel = ks[spec["channel"]] if spec["channel"] in ks.channels else None
        if channel is None or channel.status != ChannelStatus.READY:
            return None
        return Mission("clear", channel.clear_position or channel.mec[0],
                       channel=spec["channel"], meta={"kind": "teacher_probe"})
    if spec["kind"] == "scan":
        return Mission("scan", spec["point"],
                       channels=[c.channel_id for c in ks.unknown],
                       meta={"kind": "teacher_probe",
                             "scan_variant": spec["variant"]})
    return None


def run_one(mode, seed, n, scenario, tag, target=None, forced=PRODUCTION,
            collect=None):
    """Run one case; at ``target`` return ``forced`` instead of the decision.

    ``decide`` is ALWAYS called first, so every internal bookkeeping effect
    happens exactly as in production.  Only the returned mission is replaced,
    and the coverage cursor is rolled back when the replacement is not the
    coverage stop that production picked.
    """
    runner, scheduler = build_runner(mode, seed, n, scenario, tag)
    original = scheduler.decide
    counter = {"index": 0}

    def decide(ks, position, current_channel):
        index = counter["index"]
        counter["index"] += 1
        snapshot = {name: getattr(scheduler, name, None)
                    for name in COVERAGE_FIELDS}
        mission = original(ks, position, current_channel)
        if index == target:
            if collect is not None:
                collect(index, ks, position, current_channel, mission)
            if forced is not PRODUCTION and forced is not None:
                replacement = build_mission(forced, ks)
                if replacement is not None:
                    # The chosen coverage stop was not visited, so its cursor
                    # must not stay advanced.
                    if not (mission is not None and mission.kind == "scan"
                            and replacement.kind == "scan"
                            and mission.target == replacement.target):
                        for name, value in snapshot.items():
                            setattr(scheduler, name, value)
                    return replacement
        return mission

    scheduler.decide = decide
    report = runner.run()
    return report


def candidate_features(spec, snapshot_before, production_spec):
    """Observable features of one joint candidate (no hidden information)."""
    is_prod = spec is PRODUCTION
    kind = production_spec.get("kind") if is_prod else spec["kind"]
    meta_kind = "production" if is_prod else spec.get("point_name")
    variant = None if is_prod else spec.get("variant")
    channel = production_spec.get("channel") if is_prod else spec.get("channel")
    return {
        "is_production": 1.0 if is_prod else 0.0,
        "kind_measure": 1.0 if kind == "measure" else 0.0,
        "kind_clear": 1.0 if kind == "clear" else 0.0,
        "kind_scan": 1.0 if kind == "scan" else 0.0,
        "point_center": 1.0 if meta_kind == "center" else 0.0,
        "point_perp": 1.0 if meta_kind == "perp" else 0.0,
        "point_nbv": 1.0 if meta_kind == "nbv" else 0.0,
        "variant_primary": 1.0 if variant == "primary" else 0.0,
        "variant_active": 1.0 if variant == "active" else 0.0,
        "variant_discover": 1.0 if variant == "discover" else 0.0,
        "variant_full": 1.0 if variant == "full" else 0.0,
        "n_active": float(len(snapshot_before.get("active") or ())),
        "n_ready": float(len(snapshot_before.get("ready") or ())),
        "n_unknown": float(snapshot_before.get("unknown") or 0),
        "channel": float(channel or 0),
    }


def probe(mode, seed, n, scenario, indices, limit_points=3, verbose=True):
    baseline_report = run_one(mode, seed, n, scenario, "baseline")
    baseline = total_time(baseline_report)
    baseline_actions = baseline_report["metrics"].get("n_measures")
    results = {"mode": mode, "seed": seed, "n": n, "baseline": baseline,
               "baseline_measures": baseline_actions, "states": []}
    for index in sorted(indices):
        # 1. Self-check: production's own mission must reproduce the baseline.
        check_report = run_one(mode, seed, n, scenario, f"selfcheck_{index}",
                               target=index, forced=PRODUCTION)
        selfcheck = total_time(check_report) - baseline
        # 2. Collect the observable state and the candidate list at this
        #    decision (one extra run; the simulator is deterministic so the
        #    state is identical to the self-check run).
        box = {}

        def collect(i, ks, position, current_channel, mission):
            box["production"] = action_digest(mission)
            box["snapshot"] = {
                "position": [round(position[0], 1), round(position[1], 1)],
                "active": [c.channel_id
                           for c in ks.by_status(ChannelStatus.ACTIVE)],
                "ready": [c.channel_id
                          for c in ks.by_status(ChannelStatus.READY)],
                "unknown": len(ks.by_status(ChannelStatus.UNKNOWN)),
                "current_channel": current_channel,
            }
            box["specs"] = enumerate_candidates(ks, position, limit_points)

        run_one(mode, seed, n, scenario, f"collect_{index}", target=index,
                forced=PRODUCTION, collect=collect)
        if "specs" not in box:
            continue
        specs = [PRODUCTION] + box["specs"]
        rows = []
        started = time.time()
        for spec in specs:
            tag = "cand_%d_%s" % (index, len(rows))
            report = run_one(mode, seed, n, scenario, tag, target=index,
                             forced=(PRODUCTION if spec is PRODUCTION else spec))
            rows.append({
                "spec": (spec if spec is PRODUCTION else
                         {k: (list(v) if isinstance(v, tuple) else v)
                          for k, v in spec.items()}),
                "total": total_time(report),
                "complete": bool(report.get("complete")),
                "verifier_ok": bool(report.get("verifier_all_ok")),
                "measures": report["metrics"].get("n_measures"),
                "features": candidate_features(spec, box.get("snapshot") or {},
                                               box.get("production") or {}),
            })
        elapsed = time.time() - started
        valid = [row for row in rows if row["complete"] and row["verifier_ok"]]
        failed = len(rows) - len(valid)
        valid.sort(key=lambda row: row["total"])
        best = valid[0] if valid else None
        production_row = next((row for row in rows
                               if row["spec"] is PRODUCTION), None)
        entry = {
            "index": index,
            "snapshot": box.get("snapshot"),
            "production": box.get("production"),
            "production_replay_total": (production_row or {}).get("total"),
            "selfcheck_error_s": selfcheck,
            "candidates": len(rows),
            "failed_candidates": failed,
            "best_total": best["total"] if best else None,
            "best_spec": best["spec"] if best else None,
            "best_is_production": bool(best and best["spec"] is PRODUCTION),
            "regret": (max(0.0, baseline - best["total"]) if best else 0.0),
            "worst_total": valid[-1]["total"] if valid else None,
            "wall_seconds": round(elapsed, 2),
            "rows": [{"total": row["total"], "spec": row["spec"],
                      "features": row["features"]} for row in valid],
        }
        results["states"].append(entry)
        if verbose:
            print("  state %3d: selfcheck=%+.0f s  cand=%3d fail=%d "
                  "best=%.0f regret=%+.0f prod_best=%s (%.1fs)" %
                  (index, selfcheck, len(rows), failed,
                   best["total"] if best else -1, entry["regret"],
                   entry["best_is_production"], elapsed), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="Q3")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--n", type=int, default=16)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--indices", type=int, nargs="+", default=[6, 10])
    parser.add_argument("--limit-points", type=int, default=3)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    mode = args.mode.upper()
    scenario = args.scenario or ("random" if mode == "Q3" else "mixed")
    result = probe(mode, args.seed, args.n, scenario, set(args.indices),
                   args.limit_points)
    errors = [round(s["selfcheck_error_s"], 3) for s in result["states"]]
    print("baseline %.0f s ; selfcheck errors %s ; regrets %s" %
          (result["baseline"], errors,
           [round(s["regret"]) for s in result["states"]]))
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                             encoding="utf-8")


if __name__ == "__main__":
    main()
