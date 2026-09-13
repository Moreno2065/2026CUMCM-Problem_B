# -*- coding: utf-8 -*-
"""Pure helpers for Q4 residual certificate closure and sparsification."""

import math
from numbers import Real

from geometry import constants as C
from geometry.certificate import (
    q4_certify_point,
    q4_channel_certified,
    q4_grid_points,
)
from state.channel_state import ChannelStatus


def _finite_point(point):
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    if any(not isinstance(value, Real) or isinstance(value, bool) or
           not math.isfinite(float(value)) for value in point):
        return None
    return (float(point[0]), float(point[1]))


def _unchanged_result(centers, raw_count, *, accepted, reason,
                      initial_certified=False):
    return {
        "centers": centers,
        "retained_centers": centers,
        "raw_count": raw_count,
        "retained_count": raw_count,
        "pruned_count": 0,
        "initial_certified": bool(initial_certified),
        "final_certified": bool(initial_certified) if accepted else False,
        "accepted": bool(accepted),
        "reason": reason,
    }


def prune_certified_centers(centers):
    """Greedily remove redundant Q4 cover centers without mutating input.

    Inputs must be a finite, duplicate-free sequence of two-dimensional
    points.  Invalid inputs fail closed and are returned unchanged.  An input
    that is not already an exact Q4 channel cover is also returned unchanged.
    Removal order is lexicographic by coordinate, independent of container
    iteration details, while retained points preserve their original order.
    """
    if not isinstance(centers, (list, tuple)):
        return _unchanged_result(centers, 0, accepted=False,
                                 reason="centers must be a sequence")
    original = list(centers)
    normalized = []
    for point in original:
        value = _finite_point(point)
        if value is None:
            return _unchanged_result(original, len(original), accepted=False,
                                     reason="malformed or non-finite point")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        return _unchanged_result(original, len(original), accepted=False,
                                 reason="duplicate center")
    try:
        initial = bool(q4_channel_certified(normalized)["certified"])
    except (ArithmeticError, TypeError, ValueError, IndexError, KeyError):
        return _unchanged_result(original, len(original), accepted=False,
                                 reason="exact cover check failed")
    if not initial:
        return _unchanged_result(original, len(original), accepted=True,
                                 reason="initial set is not certified")

    retained = list(normalized)
    for point in sorted(normalized):
        trial = list(retained)
        trial.remove(point)
        if q4_channel_certified(trial)["certified"]:
            retained = trial

    final = bool(q4_channel_certified(retained)["certified"])
    if not final:
        return _unchanged_result(original, len(original), accepted=False,
                                 reason="post-prune exact cover check failed",
                                 initial_certified=True)
    return {
        "centers": retained,
        "retained_centers": retained,
        "raw_count": len(original),
        "retained_count": len(retained),
        "pruned_count": len(original) - len(retained),
        "initial_certified": True,
        "final_certified": True,
        "accepted": True,
        "reason": "exact cover retained",
    }


def q4_residual_closure_score(ch_state, point, grid_points=None):
    """Return the exact number of currently open Q4 cells closed by point.

    The scorer reads an UNKNOWN Q4 channel snapshot only.  It neither records
    the candidate observation nor updates certified centers/status.
    """
    empty = {"residual_closure_gain": 0,
             "residual_target_cell_count": 0}
    if getattr(ch_state, "mode", None) != "Q4" or \
            getattr(ch_state, "status", None) != ChannelStatus.UNKNOWN:
        return empty
    candidate = _finite_point(point)
    if candidate is None:
        return empty
    raw_region = getattr(ch_state, "certificate_region", None)
    if not isinstance(raw_region, (list, tuple)):
        return empty
    region = []
    for witness in raw_region:
        value = _finite_point(witness)
        if value is None:
            return empty
        region.append(value)
    cells = q4_grid_points() if grid_points is None else grid_points
    normalized_cells = []
    if not isinstance(cells, (list, tuple)):
        return empty
    for cell in cells:
        value = _finite_point(cell)
        if value is None:
            return empty
        normalized_cells.append(value)

    target_count = 0
    closure_gain = 0
    augmented = region + [candidate]
    try:
        for cell in normalized_cells:
            # Outside A_delta(cell), the new witness cannot change the result.
            if math.hypot(cell[0] - candidate[0],
                          cell[1] - candidate[1]) > \
                    C.R_EFF_MIN - C.Q4_DELTA + C.EPS:
                continue
            if q4_certify_point(cell, region)["certified"]:
                continue
            target_count += 1
            if q4_certify_point(cell, augmented)["certified"]:
                closure_gain += 1
    except (ArithmeticError, TypeError, ValueError, IndexError, KeyError):
        return empty
    return {
        "residual_closure_gain": closure_gain,
        "residual_target_cell_count": target_count,
    }


def q4_residual_closure_gain(ch_state, point, grid_points=None):
    """Numeric convenience wrapper around :func:`q4_residual_closure_score`."""
    return q4_residual_closure_score(
        ch_state, point, grid_points=grid_points)["residual_closure_gain"]
