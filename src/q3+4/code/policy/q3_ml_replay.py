# -*- coding: utf-8 -*-
"""Offline long-horizon replay labels for the Q3 experimental ranker.

This module is deliberately outside the online scheduler contract.  It clones
the complete synthetic runner state at a decision boundary, executes one
candidate, then lets the same deterministic policy finish the branch.  No
ground-truth source fields are read while choosing or continuing a branch.
"""

import copy
import json
import math
import os

from .scheduler import Mission


class ReplayBlocked(RuntimeError):
    """Raised when a trustworthy simulator-state replay is unavailable."""


def _finite(value, field):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ReplayBlocked("%s must be finite for replay" % field) from exc
    if not math.isfinite(value):
        raise ReplayBlocked("%s must be finite for replay" % field)
    return value


def _validate_candidate(candidate):
    if not isinstance(candidate, dict):
        raise ReplayBlocked("candidate must be a mapping for replay")
    point = candidate.get("point")
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ReplayBlocked("candidate point must be a pair for replay")
    channel = candidate.get("channel")
    try:
        channel = int(channel)
    except (TypeError, ValueError) as exc:
        raise ReplayBlocked("candidate channel must be an integer") from exc
    if channel <= 0:
        raise ReplayBlocked("candidate channel must be positive")
    return (_finite(point[0], "candidate.point[0]"),
            _finite(point[1], "candidate.point[1]"), channel)


def _clone_runner(runner):
    """Deep-copy and verify the state graph needed by a synthetic replay."""
    simulator = getattr(runner, "simulator", None)
    executor = getattr(runner, "executor", None)
    backend = getattr(executor, "backend", None)
    if simulator is None or backend is None or \
            getattr(backend, "sim", None) is not simulator:
        raise ReplayBlocked(
            "replay requires a runner backed by its synthetic simulator")
    try:
        branch = copy.deepcopy(runner)
    except Exception as exc:  # pragma: no cover - implementation dependent
        raise ReplayBlocked("synthetic runner state cannot be cloned") from exc
    if branch is runner or branch.simulator is simulator \
            or branch.executor is executor \
            or branch.executor.backend is backend \
            or branch.executor.backend.sim is simulator \
            or branch.ks is runner.ks \
            or branch.scheduler is runner.scheduler:
        raise ReplayBlocked("runner clone retained mutable state aliases")
    if branch.executor.position != runner.executor.position \
            or branch.executor.virtual_time != runner.executor.virtual_time:
        raise ReplayBlocked("runner clone changed decision-boundary state")
    branch.scheduler.decision_listener = None
    branch._current_mission = None
    return branch


def replay_candidate_branch(runner, candidate, max_steps=20000):
    """Return a long-horizon cost label for one candidate at a decision point.

    The returned ``delta_virtual_time_s`` is measured from the supplied
    decision boundary until the replay branch completes.  Incomplete or
    ambiguous branches are rejected instead of being converted into labels.
    """
    x, y, channel = _validate_candidate(candidate)
    try:
        max_steps = int(max_steps)
    except (TypeError, ValueError) as exc:
        raise ReplayBlocked("max_steps must be a positive integer") from exc
    if max_steps <= 0:
        raise ReplayBlocked("max_steps must be a positive integer")
    if runner.ks.is_complete():
        raise ReplayBlocked("cannot replay a candidate after completion")

    branch = _clone_runner(runner)
    start_time = float(branch.executor.virtual_time)
    steps = 0
    mission = Mission(
        "measure", (x, y), channel=channel,
        meta={"kind": str(candidate.get("kind", "nbv")),
              "replay": True})
    branch._current_mission = mission
    branch._execute(mission)
    branch._current_mission = None
    steps += 1

    while not branch.ks.is_complete():
        if steps >= max_steps:
            raise ReplayBlocked("replay exceeded max_steps before completion")
        mission = branch.scheduler.decide(
            branch.ks, branch.executor.position,
            branch.executor.current_channel)
        if mission is None:
            raise ReplayBlocked("replay continuation produced no mission")
        branch._current_mission = mission
        branch._execute(mission)
        branch._current_mission = None
        steps += 1

    return {
        "candidate": copy.deepcopy(candidate),
        "delta_virtual_time_s": float(branch.executor.virtual_time)
        - start_time,
        "final_virtual_time_s": float(branch.executor.virtual_time),
        "steps": steps,
        "complete": True,
    }


def replay_candidate_labels(runner, candidates, max_steps=20000):
    """Replay candidates independently and attach offline long-horizon costs."""
    if not isinstance(candidates, (list, tuple)) or not candidates:
        raise ReplayBlocked("candidates must be a non-empty sequence")
    position = runner.executor.position
    decision_position = [_finite(position[0], "decision.position[0]"),
                         _finite(position[1], "decision.position[1]")]
    labels = []
    for candidate in candidates:
        result = replay_candidate_branch(runner, candidate,
                                         max_steps=max_steps)
        labeled = copy.deepcopy(candidate)
        labeled.update({
            "long_horizon_cost_s": result["delta_virtual_time_s"],
            "label_source": "synthetic_branch_replay",
            "decision_position": list(decision_position),
            "replay_steps": result["steps"],
        })
        labels.append(labeled)
    return labels


def replay_candidate_pairs(runner, candidates, min_saving_s=0.0,
                           max_steps=20000):
    """Return lower-cost-over-higher-cost pairs from replay labels."""
    try:
        min_saving_s = float(min_saving_s)
    except (TypeError, ValueError) as exc:
        raise ReplayBlocked("min_saving_s must be finite") from exc
    if not math.isfinite(min_saving_s) or min_saving_s < 0.0:
        raise ReplayBlocked("min_saving_s must be >= 0")
    labels = replay_candidate_labels(runner, candidates, max_steps=max_steps)
    labels.sort(key=lambda item: (
        item["long_horizon_cost_s"], int(item["channel"]),
        tuple(item["point"])))
    position = tuple(labels[0]["decision_position"])
    pairs = []
    for index, preferred in enumerate(labels):
        for rejected in labels[index + 1:]:
            saving = (rejected["long_horizon_cost_s"]
                      - preferred["long_horizon_cost_s"])
            if saving >= min_saving_s:
                pairs.append((preferred, rejected, position))
    return pairs


def collect_replay_labeled_traces(case, config=None, max_steps=20000,
                                  branch_max_steps=20000):
    """Run one deterministic Q3 baseline and label its active decisions."""
    from executor.action_executor import ActionExecutor
    from experiment.config import MainlineConfig
    from experiment.runner import GameRunner
    from experiment.simulator import SimulatorBackend, SyntheticSimulator

    if not isinstance(case, dict) or case.get("question") != "q3":
        raise ReplayBlocked("replay label collection requires a Q3 case")
    if config is None:
        config = MainlineConfig()
    if bool(getattr(config, "q3_ml_ranker", False)):
        raise ReplayBlocked("replay labels require the deterministic baseline")
    try:
        max_steps = int(max_steps)
        branch_max_steps = int(branch_max_steps)
    except (TypeError, ValueError) as exc:
        raise ReplayBlocked("replay step limits must be positive integers") \
            from exc
    if max_steps <= 0 or branch_max_steps <= 0:
        raise ReplayBlocked("replay step limits must be positive integers")

    simulator = SyntheticSimulator.from_case(case)
    executor = ActionExecutor(SimulatorBackend(simulator))
    runner = GameRunner("Q3", executor, ".", simulator=simulator,
                        case=case, config=config, max_steps=max_steps,
                        policy_variant="q3_ml_replay_label")
    entered = False
    try:
        executor.enter()
        entered = True
        for _ in range(max_steps):
            if runner.ks.is_complete():
                break
            mission = runner.scheduler.decide(
                runner.ks, runner.executor.position,
                runner.executor.current_channel)
            if mission is None:
                raise ReplayBlocked("baseline label collection produced no mission")
            trace = runner.decision_trace[-1]
            if trace.get("policy_mode") == "active_localization" \
                    and trace.get("candidates"):
                labels = replay_candidate_labels(
                    runner, trace["candidates"], max_steps=branch_max_steps)
                trace["candidates"] = labels
                trace["label_source"] = "synthetic_branch_replay"
            runner._current_mission = mission
            runner._execute(mission)
            runner._current_mission = None
            runner._step += 1
        else:
            raise ReplayBlocked("baseline label collection exceeded max_steps")
        if not runner.ks.is_complete():
            raise ReplayBlocked("baseline label collection did not complete")
        traces = copy.deepcopy(runner.decision_trace)
        return {
            "case_id": case["case_id"],
            "traces": traces,
            "decision_count": len(traces),
            "labeled_decision_count": sum(
                1 for trace in traces
                if trace.get("label_source") == "synthetic_branch_replay"),
        }
    finally:
        if entered:
            executor.exit()


def write_replay_labeled_trace(collection, output_path):
    """Persist a collected labeled trace as JSONL for offline training."""
    if not isinstance(collection, dict) or \
            not isinstance(collection.get("traces"), list):
        raise ReplayBlocked("collection must contain a trace list")
    path = os.fspath(output_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for trace in collection["traces"]:
            if not isinstance(trace, dict):
                raise ReplayBlocked("trace entries must be mappings")
            f.write(json.dumps(trace, ensure_ascii=False,
                               allow_nan=False, separators=(",", ":")))
            f.write("\n")
    return {
        "trace_path": os.path.abspath(path),
        "case_id": collection.get("case_id"),
        "decision_count": collection.get("decision_count",
                                          len(collection["traces"])),
        "labeled_decision_count": collection.get("labeled_decision_count"),
    }


def collect_replay_labeled_trace_file(case, output_path, config=None,
                                      max_steps=20000,
                                      branch_max_steps=20000):
    """Collect one case and write its replay labels to a JSONL artifact."""
    collection = collect_replay_labeled_traces(
        case, config=config, max_steps=max_steps,
        branch_max_steps=branch_max_steps)
    return write_replay_labeled_trace(collection, output_path)
