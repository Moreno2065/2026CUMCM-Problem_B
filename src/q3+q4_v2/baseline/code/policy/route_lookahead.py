# -*- coding: utf-8 -*-
"""Deterministic two-stop routing for Q4 certificate candidates."""

import json
import math
from numbers import Real

from geometry import constants as C


def _finite_number(value):
    return (isinstance(value, Real) and not isinstance(value, bool) and
            math.isfinite(float(value)))


def _normalize_candidate(candidate):
    """Build a private validated ranking record, or fail closed with None."""
    if not isinstance(candidate, dict):
        return None
    try:
        canonical_json = json.dumps(
            candidate, sort_keys=True, separators=(",", ":"),
            allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return None
    point = candidate.get("point")
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    if not all(_finite_number(value) for value in point):
        return None
    point = (float(point[0]), float(point[1]))

    raw_channels = candidate.get("channels")
    if not isinstance(raw_channels, (list, tuple)) or not raw_channels:
        return None
    if any(not isinstance(channel, int) or isinstance(channel, bool) or
           not 1 <= channel <= C.NUM_CHANNELS for channel in raw_channels):
        return None
    channels = tuple(sorted(set(raw_channels)))

    gain = candidate.get("gain")
    if not _finite_number(gain) or float(gain) < 0.0:
        return None
    gain = float(gain)
    if "cost" in candidate and (
            not _finite_number(candidate["cost"]) or
            float(candidate["cost"]) < 0.0):
        return None

    optional = {}
    for field in ("score", "joint_state_score", "residual_closure_gain",
                  "residual_target_cell_count"):
        if field in candidate:
            if not _finite_number(candidate[field]):
                return None
            optional[field] = float(candidate[field])

    kind = candidate.get("kind", "")
    if not isinstance(kind, str):
        return None
    identity = (
        channels, kind, gain,
        "score" in optional, optional.get("score", 0.0),
        "joint_state_score" in optional,
        optional.get("joint_state_score", 0.0),
        canonical_json,
    )
    return {
        "original": candidate,
        "point": point,
        "channels": channels,
        "gain": gain,
        "score": optional.get("score", 0.0),
        "joint_state_score": optional.get("joint_state_score", 0.0),
        "has_joint": "joint_state_score" in optional,
        "identity": identity,
    }


def _stop_cost(origin, destination, channels, incoming_channel):
    """Return ``(cost, outgoing_channel)`` for one scheduled scan stop."""
    sequence = sorted(set(channels))
    if incoming_channel in sequence:
        sequence.remove(incoming_channel)
        sequence.insert(0, incoming_channel)

    movement = math.hypot(destination[0] - origin[0],
                          destination[1] - origin[1]) / C.MOVE_SPEED
    measure = C.MEASURE_TIME * len(sequence)
    transitions = max(0, len(sequence) - 1)
    if sequence and sequence[0] != incoming_channel:
        transitions += 1
    cost = movement + measure + C.SWITCH_TIME * transitions
    outgoing = sequence[-1] if sequence else incoming_channel
    return cost, outgoing


def _annotated(candidate, depth, second_point, pair_cost, pair_gain):
    choice = dict(candidate)
    choice.update({
        "lookahead_depth": depth,
        "lookahead_second_point": (list(second_point)
                                    if second_point is not None else None),
        "lookahead_pair_cost": float(pair_cost),
        "lookahead_pair_gain": float(pair_gain),
    })
    return choice


def choose_lookahead2(candidates, position, current_channel):
    """Choose the first stop of the best ordered, distinct-point pair.

    Pair ordering is maximum total-gain/total-cost, lower total cost, then,
    when E2 fields are present, the first stop's existing E2 joint-score/cost,
    existing score and cost, followed by lexicographic first/second point.
    This leaves E3's route objective primary while retaining E2 as the first
    control criterion on an exact route tie.

    With fewer than two distinct points, the existing greedy ordering is used
    and the returned candidate is annotated as a depth-one decision.
    """
    records = []
    for candidate in candidates:
        record = _normalize_candidate(candidate)
        if record is not None:
            records.append(record)
    if not records:
        return None

    stop_data = []
    for record in records:
        cost, outgoing = _stop_cost(
            position, record["point"], record["channels"],
            current_channel)
        stop_data.append((record, cost, outgoing))

    distinct_points = {record["point"] for record in records}
    joint_enabled = any(record["has_joint"] for record in records)
    if len(distinct_points) < 2:
        def greedy_key(item):
            record, cost, _ = item
            joint_ratio = record["joint_state_score"] / max(cost, C.EPS)
            return (
                -joint_ratio if joint_enabled else 0.0,
                -record["score"],
                cost,
                record["point"],
                record["identity"],
            )

        record, cost, _ = min(stop_data, key=greedy_key)
        return _annotated(record["original"], 1, None, cost, record["gain"])

    pairs = []
    for first, first_cost, outgoing in stop_data:
        for second in records:
            if first["point"] == second["point"]:
                continue
            second_cost, _ = _stop_cost(
                first["point"], second["point"], second["channels"], outgoing)
            total_cost = first_cost + second_cost
            total_gain = first["gain"] + second["gain"]
            ratio = total_gain / max(total_cost, C.EPS)
            joint_ratio = first["joint_state_score"] / max(first_cost, C.EPS)
            ranking = (-ratio, total_cost)
            if joint_enabled:
                ranking += (-joint_ratio,
                            -first["score"], first_cost,
                            first["point"], second["point"])
            else:
                ranking += (first["point"], second["point"],
                            -first["score"], first_cost)
            ranking += (first["identity"], second["identity"])
            pairs.append((
                ranking,
                first, second, total_cost, total_gain,
            ))

    _, first, second, total_cost, total_gain = min(pairs, key=lambda x: x[0])
    return _annotated(first["original"], 2, second["point"], total_cost,
                      total_gain)
