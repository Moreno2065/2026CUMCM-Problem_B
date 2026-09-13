"""Sample hypothetical worlds from observations, never from the live backend.

The first experiment starts only once UNKNOWN is empty. Position proposals
are area-uniform in the convex feasible polygon, rejected against exact
bearing/range/near observations and failed clear disks. Q4 also samples the
unknown antenna type, orientation, and receive radius. This is an explicit
planning prior, not a calibrated posterior or a completion certificate.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from geometry import constants as C
from state.channel_state import ChannelStatus


def angle(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360.0


def angle_error(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def point_key(point):
    return (round(float(point[0]), 6), round(float(point[1]), 6))


def _triangles(poly):
    origin = poly[0]
    items, total = [], 0.0
    for a, b in zip(poly[1:-1], poly[2:]):
        weight = abs((a[0] - origin[0]) * (b[1] - origin[1]) -
                     (a[1] - origin[1]) * (b[0] - origin[0]))
        if weight > 1e-12:
            total += weight
            items.append((total, origin, a, b))
    return items, total


def _sample_point(triangles, total, rng, poly):
    if total <= 0.0:
        # Degenerate line/point regions are still valid proposal supports.
        a, b = poly[0], poly[-1]
        u = rng.random()
        return (a[0] * (1 - u) + b[0] * u,
                a[1] * (1 - u) + b[1] * u)
    target = rng.random() * total
    for cumulative, a, b, c in triangles:
        if cumulative >= target:
            u, v = math.sqrt(rng.random()), rng.random()
            return ((1-u)*a[0] + u*(1-v)*b[0] + u*v*c[0],
                    (1-u)*a[1] + u*(1-v)*b[1] + u*v*c[1])
    raise AssertionError("invalid triangle proposal")


@dataclass(frozen=True)
class Hypothesis:
    position: tuple
    receive_radius: float
    directional: bool
    orientation: float

    def covers(self, point):
        return (not self.directional or
                math.dist(point, self.position) <= 1e-9 or
                angle_error(angle(self.position, point), self.orientation)
                <= 90.0 + 1e-9)


def sample_source(channel, mode, failed_clears, rng, max_attempts=1600):
    poly = channel.feasible_region
    if not poly:
        return None
    triangles, total = _triangles(poly)
    positive = [o for o in channel.observations
                if o['result'] in ('direction', 'near')]
    negative = [o for o in channel.observations if o['result'] == 'no_signal']
    if not positive:
        return None
    for _ in range(max_attempts):
        p = _sample_point(triangles, total, rng, poly)
        if math.hypot(*p) > C.OMEGA_RADIUS + 1e-8:
            continue
        if any(math.dist(p, q) <= C.CLEAR_RADIUS for q in failed_clears):
            continue
        distances = [math.dist(p, o['position']) for o in positive]
        if any((o['result'] == 'near' and d > C.NEAR_THRESHOLD) or
               (o['result'] == 'direction' and
                (d <= C.NEAR_THRESHOLD or d > C.R_EFF_MAX or
                 angle_error(angle(o['position'], p), o['bearing']) >
                 C.BEARING_ERROR_DEG + 1e-7))
               for o, d in zip(positive, distances)):
            continue
        directional = mode == 'Q4' and rng.random() < 0.5
        # Condition orientation on one positive witness before rejecting the
        # remaining witnesses; every accepted direction still fits history.
        orientation = ((angle(p, positive[-1]['position']) +
                        rng.uniform(-90.0, 90.0)) % 360.0
                       if directional else 0.0)
        trial = Hypothesis(p, C.R_EFF_MAX, directional, orientation)
        if any(not trial.covers(o['position']) for o in positive):
            continue
        lower = max([C.R_EFF_MIN] + distances)
        upper = C.R_EFF_MAX
        for o in negative:
            if trial.covers(o['position']):
                upper = min(upper, math.dist(p, o['position']) - 1e-7)
        if upper < lower:
            continue
        return Hypothesis(p, rng.uniform(lower, upper), directional, orientation)
    return None


def sample_worlds(ks, failed_clears, count, seed):
    """All-or-nothing sampling: a missing hypothesis cancels this search."""
    if ks.unknown:
        return []
    worlds = []
    for index in range(count):
        rng = random.Random(f'belief-rollout|{seed}|{index}')
        world = {}
        for ch in ks.active + ks.ready:
            h = sample_source(ch, ks.mode,
                              failed_clears.get(ch.channel_id, ()), rng)
            if h is None:
                return []
            world[ch.channel_id] = h
        worlds.append(world)
    return worlds


class HypotheticalBackend:
    """In-memory protocol-equivalent action costs for a supplied hypothesis.

    Its only inputs are sampled hypotheses, observable history and robot
    state. Repeated historical measurements return the observed reply;
    unobserved positions use an independent bounded, deterministic error.
    """
    def __init__(self, world, ks, position, current_channel, seed):
        self.world = dict(world)
        self.position = tuple(position)
        self.current_channel = current_channel
        self.virtual_time = 0.0
        self.max_virtual_duration_s = 360000.0
        self.seed = str(seed)
        self.history = {}
        for ch in ks.active + ks.ready:
            for obs in ch.observations:
                if obs['result'] in ('direction', 'near', 'no_signal'):
                    self.history[(ch.channel_id, point_key(obs['position']))] = {
                        'measure_result': obs['result'],
                        **({'svd_deg': obs['bearing']}
                           if obs['result'] == 'direction' else {}),
                    }

    def real_time_exceeded(self):
        return False

    def _move(self, point):
        self.virtual_time += math.dist(self.position, point) / C.MOVE_SPEED
        self.position = tuple(point)

    def measure(self, point, channel):
        self._move(point)
        self.virtual_time += C.MEASURE_TIME
        if self.current_channel is not None and channel != self.current_channel:
            self.virtual_time += C.SWITCH_TIME
        self.current_channel = channel
        h = self.world.get(channel)
        key = (channel, point_key(point))
        if h is None:
            result = {'measure_result': 'no_signal'}
        elif key in self.history:
            result = self.history[key]
        else:
            d = math.dist(point, h.position)
            if not h.covers(point) or d > h.receive_radius:
                result = {'measure_result': 'no_signal'}
            elif d <= C.NEAR_THRESHOLD:
                result = {'measure_result': 'near'}
            else:
                digest = hashlib.sha256(
                    repr((self.seed, channel, point_key(point))).encode()).digest()
                error = (int.from_bytes(digest[:8], 'big') / 2**64 * 2-1)*0.99
                result = {'measure_result': 'direction', 'svd_deg':
                          round((angle(point, h.position) + error) % 360, 2) % 360}
            self.history[key] = result
        return {'accepted': True, 'virtual_time_s': self.virtual_time, **result}

    def clear(self, point, channel):
        self._move(point)
        h = self.world.get(channel)
        success = h is not None and math.dist(point, h.position) <= C.CLEAR_RADIUS
        self.virtual_time += C.CLEAR_SUCCESS_TIME if success else C.CLEAR_FAIL_TIME
        if success:
            del self.world[channel]
        return {'accepted': True, 'virtual_time_s': self.virtual_time,
                'clear_result': 'success' if success else 'no_target_in_range'}
