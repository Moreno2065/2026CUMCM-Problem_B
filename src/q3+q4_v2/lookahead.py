"""Short-horizon belief lookahead shared by the rolling policy.

The rolling score used to add a fixed fraction of a hand-written remaining-cost
proxy.  This module instead expands one decision step explicitly:

* enumerate the observable outcomes of the candidate action
  (``direction`` / ``no_signal`` for a measurement, a discovery count for a
  coverage scan, success/failure for a clear),
* update a *shadow* knowledge state with the same update functions the runner
  uses, and
* evaluate the continuation with the same cost model that prices the real
  action sequence.

Only observable quantities enter the probabilities and the shadow updates:
channel status, feasible regions, recorded witnesses and the guarantee radii
from the problem statement.  Nothing here reads source count, scenario or
truth.
"""
from __future__ import annotations

import copy
import math

from geometry import constants as C
from state.channel_state import ChannelStatus


class ShadowKnowledge:
    """A knowledge state with per-channel overrides.

    Only the channels an outcome actually touches are copied, so branching is
    cheap compared with deep-copying all twenty channel states.
    """

    def __init__(self, base, overrides=None, mode=None):
        self._base = base
        self._overrides = dict(overrides or {})
        self.mode = mode or getattr(base, "mode", None)
        self.q4_certificate_layout = getattr(base, "q4_certificate_layout", None)

    def __getitem__(self, channel_id):
        if channel_id in self._overrides:
            return self._overrides[channel_id]
        return self._base[channel_id]

    @property
    def channels(self):
        return {cid: self[cid] for cid in self._base.channels}

    def by_status(self, status):
        return [ch for ch in self.channels.values() if ch.status == status]

    @property
    def cleared(self):
        return self.by_status(ChannelStatus.CLEARED)

    @property
    def certified_absent(self):
        return self.by_status(ChannelStatus.CERTIFIED_ABSENT)

    @property
    def ready(self):
        return self.by_status(ChannelStatus.READY)

    @property
    def active(self):
        return self.by_status(ChannelStatus.ACTIVE)

    @property
    def unknown(self):
        return self.by_status(ChannelStatus.UNKNOWN)

    def branch(self, channel_id, mutate):
        """Return a new shadow where ``mutate`` was applied to one channel."""
        channel = copy.deepcopy(self[channel_id])
        mutate(channel)
        overrides = dict(self._overrides)
        overrides[channel_id] = channel
        return ShadowKnowledge(self._base, overrides, self.mode)


def region_visibility(channel, point, grid, radius):
    """Share of a channel's hiding region visible from ``point``.

    For an omnidirectional source every no-signal witness excludes a disk of
    the guaranteed reception radius, so the hiding region is the grid samples
    not covered by any witness.  Q4 directional sources may additionally hide
    on the blind side, which makes the same region a superset; the caller
    treats it as an optimistic discovery estimate, never as a certificate.
    """
    if not grid:
        return 0.0, 0.0
    px, py = point
    visible = 0
    total = 0
    for sx, sy in grid:
        blocked = False
        for wx, wy in channel.certificate_region:
            dx, dy = sx - wx, sy - wy
            if dx * dx + dy * dy <= radius * radius:
                blocked = True
                break
        if blocked:
            continue
        total += 1
        dx, dy = sx - px, sy - py
        if dx * dx + dy * dy <= radius * radius:
            visible += 1
    if total == 0:
        return 0.0, 0.0
    return visible / float(total), float(total)


def discovery_share(channel, point, grid, radius=None):
    """Share of a channel's remaining hiding region visible from ``point``.

    This is the observable probability that measuring this channel here would
    actually reveal a source: the fraction of the still-possible region that
    falls inside the guaranteed reception disk of the stop.  It uses only the
    channel's own no-signal witnesses, so it is valid for omnidirectional
    sources and optimistic for directional ones.
    """
    share, _ = region_visibility(channel, point, grid,
                                 C.R_EFF_MIN if radius is None else radius)
    return share


def as_shadow(state):
    """Accept either a knowledge state or an existing shadow."""
    if isinstance(state, ShadowKnowledge):
        return state
    return ShadowKnowledge(state)


def measurement_branches(shadow, channel_id, point, grid, facing_prior=1.0):
    """Outcome distribution of one measurement, plus the two shadow states.

    ``direction`` requires the source to sit inside the guaranteed reception
    disk *and* on the visible side; ``no_signal`` is the complement.  The
    bearing used for the direction branch is the maximum-likelihood direction
    from the observation point to the current region estimate, which is the
    only bearing observable-consistent statement available before the reply.
    """
    channel = shadow[channel_id]
    share, _ = region_visibility(channel, point, grid, C.R_EFF_MIN)
    probability = max(0.0, min(1.0, share * facing_prior))
    branches = []
    shadow = as_shadow(shadow)

    def apply_direction(target):
        center = target.mec[0] if target.mec else point
        bearing = math.degrees(math.atan2(center[1] - point[1],
                                          center[0] - point[0])) % 360.0
        try:
            target.update_direction(point, bearing, 0.0)
        except ValueError:
            # An inconsistent branch is not a usable continuation; treat it
            # as carrying no information instead of inventing an update.
            target.update_no_signal(point, 0.0)

    def apply_no_signal(target):
        target.update_no_signal(point, 0.0)

    if probability > 0.0:
        branches.append((probability,
                         shadow.branch(channel_id, apply_direction)))
    if probability < 1.0:
        branches.append((1.0 - probability,
                         shadow.branch(channel_id, apply_no_signal)))
    return branches


def scan_branches(shadow, mission, grid, facing_prior=1.0, max_outcomes=3):
    """Outcome distribution of a coverage scan, summarised by discovery count.

    Each UNKNOWN channel is discovered independently with the probability that
    the stop can see it.  Enumerating every subset is unnecessary for a value
    estimate, so the channels are sorted by probability and truncated to the
    ``max_outcomes`` most likely ones; the remaining mass is charged to the
    aggregate "no further discovery" outcome.
    """
    probabilities = []
    shadow = as_shadow(shadow)
    for channel in shadow.by_status(ChannelStatus.UNKNOWN):
        share, _ = region_visibility(channel, mission.target, grid,
                                     C.R_EFF_MIN)
        probability = max(0.0, min(1.0, share * facing_prior))
        if probability > 0.0:
            probabilities.append((probability, channel.channel_id))
    if not probabilities:
        return [(1.0, shadow)]
    probabilities.sort(reverse=True)
    head = probabilities[:max_outcomes]
    tail = probabilities[max_outcomes:]
    outcomes = []

    def promote(state, channel_id, point):
        def mutate(target):
            center = target.mec[0] if target.mec else point
            bearing = math.degrees(math.atan2(center[1] - point[1],
                                              center[0] - point[0])) % 360.0
            try:
                target.update_direction(point, bearing, 0.0)
            except ValueError:
                pass
        return state.branch(channel_id, mutate)

    # Probability that every truncated channel stays hidden.
    remaining = 1.0
    for probability, _ in tail:
        remaining *= (1.0 - probability)
    # Exact enumeration over the head (two outcomes each).
    for mask in range(1 << len(head)):
        probability = remaining
        state = shadow
        for index, (p, channel_id) in enumerate(head):
            if mask & (1 << index):
                probability *= p
                state = promote(state, channel_id, mission.target)
            else:
                probability *= (1.0 - p)
        if probability > 1e-6:
            outcomes.append((probability, state))
    return outcomes
