# -*- coding: utf-8 -*-
"""Offline trainer for the Q3 experimental linear ranker.

Training consumes decision-trace JSONL produced by prior deterministic runs.
The trace's existing ``score`` is the teacher preference; no holdout or live
runtime data is read implicitly.  The resulting JSON artifact records the
feature schema and training metadata so it can be reviewed before enabling
``q3_ml_experimental``.
"""

import hashlib
import json
import math
import os

from .q3_ml_ranker import (
    Q3LinearRanker,
    deterministic_q3_choice,
    rank_q3_candidates,
)


def _finite(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be finite" % name) from exc
    if not math.isfinite(value):
        raise ValueError("%s must be finite" % name)
    return value


DEFAULT_LABEL_FIELD = "long_horizon_cost_s"


def _trace_pairs(path, min_gap, label_field=DEFAULT_LABEL_FIELD):
    if not isinstance(label_field, str) or not label_field:
        raise ValueError("label_field must be a non-empty string")
    pairs = []
    with open(os.fspath(path), "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                trace = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON in %s:%d" %
                                 (path, line_no)) from exc
            if not isinstance(trace, dict) or \
                    trace.get("policy_mode") != "active_localization":
                continue
            position = trace.get("position")
            if not isinstance(position, (list, tuple)) or len(position) != 2:
                raise ValueError("active trace must record a two-dimensional "
                                 "decision position in %s:%d"
                                 % (path, line_no))
            position = tuple(_finite(value, "trace.position")
                             for value in position)
            candidates = trace.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError("active trace candidates must be a list in "
                                 "%s:%d" % (path, line_no))
            valid = []
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise ValueError("candidate must be a mapping in %s:%d" %
                                     (path, line_no))
                score = _finite(candidate.get("score"), "candidate.score")
                candidate = dict(candidate)
                candidate["score"] = score
                candidate[label_field] = _finite(
                    candidate.get(label_field),
                    "candidate.%s" % label_field)
                valid.append(candidate)
            if len(valid) < 2:
                continue
            if label_field == "long_horizon_cost_s":
                teacher = min(valid, key=lambda c: (
                    c[label_field], _finite(c.get("cost"),
                                             "candidate.cost"),
                    tuple(c["point"]), str(c.get("channel", ""))))
            else:
                teacher = min(valid, key=lambda c: (
                    -c["score"], _finite(c.get("cost"), "candidate.cost"),
                    tuple(c["point"]), str(c.get("channel", ""))))
            for candidate in valid:
                if candidate is teacher:
                    continue
                gap = (candidate[label_field] - teacher[label_field]
                       if label_field == "long_horizon_cost_s"
                       else teacher["score"] - candidate["score"])
                if gap >= min_gap:
                    pairs.append((teacher, candidate, position))
    return pairs


def calibrate_takeover_gate(model, trace_paths, min_saving_s=0.0):
    """Calibrate the ML margin gate from offline long-horizon labels.

    The margin is used as an uncertainty proxy.  A threshold is accepted only
    when every accepted disagreement on the tuning traces is no worse than
    deterministic ordering by ``min_saving_s``.  This function never reads
    source truth; it consumes only replay labels already attached to traces.
    """
    min_saving_s = _finite(min_saving_s, "min_saving_s")
    if min_saving_s < 0.0:
        raise ValueError("min_saving_s must be >= 0")
    rows = []
    for path in trace_paths:
        with open(os.fspath(path), "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                trace = json.loads(line)
                if not isinstance(trace, dict) or \
                        trace.get("policy_mode") != "active_localization":
                    continue
                candidates = trace.get("candidates")
                if not isinstance(candidates, list) or len(candidates) < 2:
                    continue
                try:
                    if any("long_horizon_cost_s" not in c
                           for c in candidates):
                        continue
                    ranked = rank_q3_candidates(model, candidates,
                                                trace.get("position"))
                    deterministic = deterministic_q3_choice(candidates)
                    if len(ranked) < 2 or deterministic is None:
                        continue
                    ml_top = ranked[0]
                    ml_key = (ml_top.get("channel"),
                              tuple(ml_top.get("point", ())),
                              ml_top.get("kind"))
                    det_key = (deterministic.get("channel"),
                               tuple(deterministic.get("point", ())),
                               deterministic.get("kind"))
                    if ml_key == det_key:
                        continue
                    margin = float(ml_top["ml_score"] -
                                   ranked[1]["ml_score"])
                    by_key = {
                        (c.get("channel"), tuple(c.get("point", ())),
                         c.get("kind")): c for c in candidates}
                    det_label = _finite(
                        by_key[det_key]["long_horizon_cost_s"],
                        "candidate.long_horizon_cost_s")
                    ml_label = _finite(
                        by_key[ml_key]["long_horizon_cost_s"],
                        "candidate.long_horizon_cost_s")
                    rows.append({"margin": margin,
                                 "saving_s": det_label - ml_label})
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("invalid calibration trace %s:%d" %
                                     (path, line_no)) from exc
    thresholds = sorted({0.0} | {row["margin"] for row in rows
                                 if math.isfinite(row["margin"])})
    accepted = []
    for threshold in thresholds:
        subset = [row for row in rows if row["margin"] >= threshold]
        if subset and min(row["saving_s"] for row in subset) >= min_saving_s:
            accepted.append((sum(row["saving_s"] for row in subset) /
                             len(subset), len(subset), threshold, subset))
    if not accepted:
        return {
            "enabled": False,
            "min_ml_margin": 0.05,
            "calibration": {"n_disagreements": len(rows),
                             "accepted_count": 0,
                             "mean_saving_s": 0.0,
                             "worst_saving_s": None},
        }
    mean_saving, count, threshold, subset = max(
        accepted, key=lambda item: (item[0], item[1], item[2]))
    return {
        "enabled": True,
        "min_ml_margin": float(threshold),
        "calibration": {
            "n_disagreements": len(rows),
            "accepted_count": count,
            "mean_saving_s": float(mean_saving),
            "worst_saving_s": float(min(row["saving_s"]
                                        for row in subset)),
            "min_required_saving_s": min_saving_s,
        },
    }


def train_q3_ranker(trace_paths, output_path, epochs=8, learning_rate=0.05,
                    min_gap=0.0, label_field=DEFAULT_LABEL_FIELD,
                    calibration_trace_paths=None, min_saving_s=0.0):
    """Train and persist a Q3 ranker from one or more decision traces."""
    if not trace_paths:
        raise ValueError("trace_paths must not be empty")
    min_gap = _finite(min_gap, "min_gap")
    if min_gap < 0.0:
        raise ValueError("min_gap must be >= 0")
    pairs = []
    for path in trace_paths:
        pairs.extend(_trace_pairs(path, min_gap, label_field=label_field))
    if not pairs:
        raise ValueError("no usable pairwise examples in decision traces")
    model = Q3LinearRanker.fit_pairwise(
        pairs, epochs=epochs, learning_rate=learning_rate)
    model.metadata.update({
        "trace_paths": [os.fspath(p) for p in trace_paths],
        "min_gap": min_gap,
        "label_field": label_field,
    })
    if calibration_trace_paths:
        model.metadata["takeover_gate"] = calibrate_takeover_gate(
            model, calibration_trace_paths, min_saving_s=min_saving_s)
    model.save(output_path)
    with open(output_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return {
        "model_path": os.path.abspath(os.fspath(output_path)),
        "model_sha256": digest,
        "pair_count": len(pairs),
        "model_version": model.to_dict()["model_version"],
    }
