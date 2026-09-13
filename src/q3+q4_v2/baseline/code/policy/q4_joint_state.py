# -*- coding: utf-8 -*-
"""Pure Q4 sampled-hypothesis scoring used only for candidate ranking.

The ensemble is intentionally fixed and independent of simulator ground truth.
Filtering consumes only accepted observations already present on ChannelState and
the channel's current conservative feasible region.  Cached values are keyed by
an immutable snapshot, so this module never adds state to ChannelState.
"""

from functools import lru_cache
import math

from geometry import constants as C
from geometry.certificate import q4_grid_points
from geometry.polygon import contains_point
from state.channel_state import ChannelStatus


_RADII = (1000.0, 1250.0, 1500.0)
_ORIENTATIONS = tuple(float(value) for value in range(0, 360, 30))
_SOURCE_POINTS = tuple(
    (float(point[0]), float(point[1]))
    for point in q4_grid_points()
    if math.hypot(point[0], point[1]) <= C.OMEGA_RADIUS + C.EPS
)
_HYPOTHESES = tuple(
    (point[0], point[1], radius, kind, orientation)
    for point in _SOURCE_POINTS
    for radius in _RADII
    for kind, orientation in (
        (("omni", None),)
        + tuple(("directional", value) for value in _ORIENTATIONS)
    )
)


def _zero_result():
    return {
        "score": 0.0,
        "signal_count": 0,
        "no_signal_count": 0,
        "hypothesis_count": 0,
    }


def _point(value):
    if not isinstance(value, (list, tuple)):
        return None
    try:
        if len(value) != 2:
            return None
        point = (float(value[0]), float(value[1]))
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(coordinate) for coordinate in point):
        return None
    return point


def _predicts_signal(hypothesis, stop):
    gx, gy, radius, kind, orientation = hypothesis
    dx, dy = stop[0] - gx, stop[1] - gy
    distance = math.hypot(dx, dy)
    if distance > radius + C.EPS:
        return False
    if kind == "omni" or distance <= C.EPS:
        return True
    angle = math.degrees(math.atan2(dy, dx))
    difference = abs((angle - orientation + 180.0) % 360.0 - 180.0)
    return difference <= 90.0 + C.EPS_ANGLE


def _immutable_state_signature(channel):
    try:
        raw_region = channel.feasible_region
        raw_observations = channel.observations
        if not isinstance(raw_region, (list, tuple)) \
                or len(raw_region) < 3 \
                or not isinstance(raw_observations, list):
            return None
        region_points = tuple(_point(vertex) for vertex in raw_region)
        if any(vertex is None for vertex in region_points):
            return None
        region = tuple(region_points)
        observations = []
        terminal_observation = False
        for observation in raw_observations:
            if not isinstance(observation, dict):
                return None
            if observation.get("accepted", True) is False:
                continue
            if "result" not in observation or "position" not in observation:
                return None
            result = observation["result"]
            if result not in ("direction", "no_signal", "near", "cleared",
                              "fallback_exhausted"):
                return None
            position = _point(observation["position"])
            if position is None:
                return None
            if result == "direction":
                try:
                    bearing = float(observation["bearing"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    return None
                if not math.isfinite(bearing):
                    return None
            if result in ("direction", "no_signal"):
                observations.append((result, position[0], position[1]))
            elif result in ("near", "cleared"):
                terminal_observation = True
        return region, tuple(observations), terminal_observation
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


@lru_cache(maxsize=4096)
def _survivors_cached(region, observations):
    has_direction = any(result == "direction"
                        for result, _, _ in observations)
    surviving = []
    for hypothesis in _HYPOTHESES:
        source = (hypothesis[0], hypothesis[1])
        if has_direction and not contains_point(region, source):
            continue
        consistent = True
        for result, x, y in observations:
            predicted = _predicts_signal(hypothesis, (x, y))
            if (result == "direction" and not predicted) or \
                    (result == "no_signal" and predicted):
                consistent = False
                break
        if consistent:
            surviving.append(hypothesis)
    return tuple(surviving)


def rank_q4_candidate(ch_state, point):
    """Return a deterministic balanced-split score without mutating state."""
    candidate = _point(point)
    if candidate is None or getattr(ch_state, "mode", None) != "Q4":
        return _zero_result()
    status = getattr(ch_state, "status", None)
    if status == ChannelStatus.CLEARED:
        return _zero_result()
    signature = _immutable_state_signature(ch_state)
    if signature is None or signature[2]:
        return _zero_result()
    surviving = _survivors_cached(signature[0], signature[1])
    hypothesis_count = len(surviving)
    if hypothesis_count == 0:
        return _zero_result()
    signal_count = sum(_predicts_signal(hypothesis, candidate)
                       for hypothesis in surviving)
    no_signal_count = hypothesis_count - signal_count
    probability = signal_count / hypothesis_count
    score = 4.0 * probability * (1.0 - probability)
    return {
        "score": score,
        "signal_count": signal_count,
        "no_signal_count": no_signal_count,
        "hypothesis_count": hypothesis_count,
    }
