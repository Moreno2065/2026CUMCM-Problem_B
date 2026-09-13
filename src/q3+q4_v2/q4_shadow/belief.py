"""Small deterministic posterior used only to rank risky Q4 actions.

The hard ChannelState polygon and the finite absence/clear certificates remain
authoritative.  This module samples positions inside that polygon, receive
radii in [1000, 1500] m, and antenna orientations.  It conditions those
hypotheses on every recorded positive and no-signal observation.  The result
is a planning posterior, never a completion predicate.
"""
from __future__ import annotations

import math

from geometry import constants as C
from geometry.polygon import contains_point
from state.channel_state import ChannelStatus


def _point_key(point):
    return (round(float(point[0]), 5), round(float(point[1]), 5))


def _visible(source, point, radius, directional, orientation):
    dx = float(point[0]) - source[0]
    dy = float(point[1]) - source[1]
    distance = math.hypot(dx, dy)
    if distance > radius + C.EPS:
        return False
    if not directional or distance <= C.EPS:
        return True
    angle = math.degrees(math.atan2(dy, dx))
    difference = abs((angle - orientation + 180.0) % 360.0 - 180.0)
    return difference <= 90.0 + C.EPS_ANGLE


def _observations(channel):
    return tuple(
        (observation.get("result"),
         (float(observation["position"][0]),
          float(observation["position"][1])))
        for observation in channel.observations
        if observation.get("result") in ("direction", "no_signal")
        and observation.get("position") is not None
    )


def _consistent(source, radius, directional, orientation, observations):
    for result, point in observations:
        predicted = _visible(source, point, radius, directional, orientation)
        if (result == "direction" and not predicted) or \
                (result == "no_signal" and predicted):
            return False
    return True


def _sample_positions(channel, limit=36):
    """Deterministic interior support for the current convex polygon."""
    polygon = list(channel.feasible_region or ())
    if len(polygon) < 3:
        return []
    centroid = (sum(point[0] for point in polygon) / len(polygon),
                sum(point[1] for point in polygon) / len(polygon))
    candidates = [centroid, channel.mec[0]]
    for index, point in enumerate(polygon):
        nxt = polygon[(index + 1) % len(polygon)]
        candidates.extend((
            point,
            ((point[0] + nxt[0]) * 0.5, (point[1] + nxt[1]) * 0.5),
            ((point[0] + centroid[0]) * 0.5,
             (point[1] + centroid[1]) * 0.5),
        ))
    unique = []
    seen = set()
    for point in candidates:
        key = _point_key(point)
        if key in seen or not contains_point(polygon, point, eps=1e-6):
            continue
        seen.add(key)
        unique.append((float(point[0]), float(point[1])))
    if len(unique) <= limit:
        return unique
    # Evenly retain boundary and interior support; never depend on randomness.
    return [unique[(i * len(unique)) // limit] for i in range(limit)]


class ShadowPosterior:
    """Weighted Q4 hypotheses plus an empirical-Bayes antenna-type prior."""

    def __init__(self, prior_directional=0.60, prior_strength=8.0,
                 quantile_z=1.645, orientation_step_deg=10.0,
                 position_limit=36):
        self.prior_directional = min(0.99, max(0.01,
                                                float(prior_directional)))
        self.prior_strength = max(0.1, float(prior_strength))
        self.quantile_z = max(0.0, float(quantile_z))
        step = max(5.0, min(30.0, float(orientation_step_deg)))
        self.orientations = tuple(
            float(index) for index in range(0, 360, int(round(step))))
        self.position_limit = max(8, int(position_limit))
        self.radii = (C.R_EFF_MIN,
                      0.5 * (C.R_EFF_MIN + C.R_EFF_MAX),
                      C.R_EFF_MAX)
        self._type_cache = {}
        self._particle_cache = {}

    @staticmethod
    def _signature(channel):
        region = tuple(_point_key(point)
                       for point in (channel.feasible_region or ()))
        observations = tuple((kind, *_point_key(point))
                             for kind, point in _observations(channel))
        return channel.channel_id, region, observations

    def type_likelihood(self, channel):
        """Return P(data|omni), P(data|directional) under fixed supports."""
        signature = self._signature(channel)
        if signature in self._type_cache:
            return self._type_cache[signature]
        points = _sample_positions(channel, self.position_limit)
        observations = _observations(channel)
        if not points:
            return (1.0, 1.0)
        omni_mass = 0.0
        directional_mass = 0.0
        total = float(len(points) * len(self.radii))
        for source in points:
            for radius in self.radii:
                if _consistent(source, radius, False, 0.0, observations):
                    omni_mass += 1.0
                directional_mass += sum(
                    _consistent(source, radius, True, orientation,
                                observations)
                    for orientation in self.orientations
                ) / float(len(self.orientations))
        result = (omni_mass / total, directional_mass / total)
        self._type_cache[signature] = result
        return result

    def directional_fraction(self, knowledge):
        """Mean and conservative upper quantile of the directional share.

        The beta prior is the explicit exogenous evidence.  Each already
        discovered channel contributes its soft posterior type probability.
        A normal approximation to the beta quantile is sufficient here because
        the value only gates/ranks actions; it cannot certify completion.
        """
        alpha = self.prior_directional * self.prior_strength
        beta = (1.0 - self.prior_directional) * self.prior_strength
        prior = self.prior_directional
        used = 0
        for channel in knowledge.channels.values():
            if channel.status in (ChannelStatus.UNKNOWN,
                                  ChannelStatus.CERTIFIED_ABSENT):
                continue
            if not any(obs.get("result") == "direction"
                       for obs in channel.observations):
                continue
            omni_like, directional_like = self.type_likelihood(channel)
            denominator = ((1.0 - prior) * omni_like
                           + prior * directional_like)
            probability = (prior * directional_like / denominator
                           if denominator > 1e-15 else prior)
            alpha += probability
            beta += 1.0 - probability
            used += 1
        mean = alpha / (alpha + beta)
        variance = (alpha * beta /
                    ((alpha + beta) ** 2 * (alpha + beta + 1.0)))
        upper = min(0.995, max(mean,
                               mean + self.quantile_z * math.sqrt(variance)))
        return {"mean": mean, "upper": upper, "alpha": alpha,
                "beta": beta, "channels": used}

    def particles(self, channel, directional_prior):
        signature = self._signature(channel)
        key = (signature, round(float(directional_prior), 5))
        if key in self._particle_cache:
            return self._particle_cache[key]
        points = _sample_positions(channel, self.position_limit)
        observations = _observations(channel)
        if not points:
            return ()
        q = min(0.995, max(0.005, float(directional_prior)))
        particles = []
        base = 1.0 / float(len(points) * len(self.radii))
        for source in points:
            for radius in self.radii:
                if _consistent(source, radius, False, 0.0, observations):
                    particles.append((source, radius, False, 0.0,
                                      base * (1.0 - q)))
                directional_weight = base * q / len(self.orientations)
                for orientation in self.orientations:
                    if _consistent(source, radius, True, orientation,
                                   observations):
                        particles.append((source, radius, True, orientation,
                                          directional_weight))
        mass = sum(particle[4] for particle in particles)
        if mass <= 1e-15:
            result = ()
        else:
            result = tuple((*particle[:4], particle[4] / mass)
                           for particle in particles)
        self._particle_cache[key] = result
        return result

    def position_likelihood(self, channel, point, directional_prior=None):
        """Unnormalised P(observations | source at ``point``).

        This marginalises receive radius, antenna type and orientation.  It is
        useful for ordering an already-valid clear cover: the cover remains
        complete even when this deliberately coarse planning prior is wrong.
        """
        observations = _observations(channel)
        q = self.prior_directional if directional_prior is None else min(
            0.995, max(0.005, float(directional_prior)))
        omni = 0.0
        directional = 0.0
        for radius in self.radii:
            if _consistent(point, radius, False, 0.0, observations):
                omni += 1.0
            directional += sum(
                _consistent(point, radius, True, orientation, observations)
                for orientation in self.orientations)
        omni /= float(len(self.radii))
        directional /= float(len(self.radii) * len(self.orientations))
        return (1.0 - q) * omni + q * directional

    def candidate_stats(self, channel, point, directional_prior):
        particles = self.particles(channel, directional_prior)
        if not particles:
            return {"p_signal": 0.5, "p_no_signal": 0.5,
                    "p_directional": directional_prior,
                    "balanced_split": 1.0, "ess": 0.0,
                    "hypotheses": 0}
        p_signal = 0.0
        p_directional = 0.0
        square_mass = 0.0
        for source, radius, directional, orientation, weight in particles:
            square_mass += weight * weight
            if directional:
                p_directional += weight
            if _visible(source, point, radius, directional, orientation):
                p_signal += weight
        p_signal = min(1.0, max(0.0, p_signal))
        return {
            "p_signal": p_signal,
            "p_no_signal": 1.0 - p_signal,
            "p_directional": p_directional,
            "balanced_split": 4.0 * p_signal * (1.0 - p_signal),
            "ess": 1.0 / max(square_mass, 1e-15),
            "hypotheses": len(particles),
        }
