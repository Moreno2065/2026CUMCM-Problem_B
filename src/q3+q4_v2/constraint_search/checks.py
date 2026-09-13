"""Geometry safety checks independent of the action policy."""
import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline" / "code")]

from shapely.geometry import Point, Polygon
from constraint_search.state import ConstrainedChannelState
from geometry.wedge import bearing_of
from state.channel_state import ChannelStatus


class GeometryChecks(unittest.TestCase):
    def test_holes_survive_positive_observation(self):
        ch = ConstrainedChannelState(1)
        ch.update_no_signal((0, 0), 1)
        self.assertFalse(ch.position_set.covers(Point(0, 0)))
        ch.update_direction((1200, 0), 180, 2)
        self.assertFalse(ch.position_set.covers(Point(0, 0)))
        self.assertTrue(ch.position_set.covers(Point(-1100, 0)) is False)
        self.assertTrue(ch.position_set.covers(Point(1100, 0)))

    def test_disconnected_set_is_retained(self):
        ch = ConstrainedChannelState(1)
        ch.position_set = Polygon([(-1500, -20), (1500, -20),
                                   (1500, 20), (-1500, 20)])
        ch._publish()
        ch.update_no_signal((0, 0), 1)
        self.assertEqual(ch.position_set.geom_type, "MultiPolygon")
        self.assertFalse(ch.position_set.covers(Point(0, 0)))
        self.assertGreater(len(ch.position_set.geoms), 1)

    def test_legal_extreme_bearings_never_remove_truth(self):
        rng = random.Random(918220)
        for _ in range(60):
            g = (rng.uniform(-700, 700), rng.uniform(-700, 700))
            ch = ConstrainedChannelState(1)
            for j in range(10):
                angle = rng.uniform(0, 2 * math.pi)
                distance = rng.choice((400, 900, 1000.00001, 1400))
                p = (g[0] + distance * math.cos(angle),
                     g[1] + distance * math.sin(angle))
                if distance > 1000:
                    ch.update_no_signal(p, j)
                else:
                    theta = bearing_of(p, g) + rng.choice((-1., 0., 1.))
                    ch.update_direction(p, theta, j)
                self.assertLessEqual(ch.position_set.distance(Point(g)), 1e-6)

    def test_failed_clear_and_boundary_are_conservative(self):
        ch = ConstrainedChannelState(1)
        ch.update_failed_clear((0, 0), 3)
        self.assertFalse(ch.position_set.covers(Point(0, 0)))
        self.assertTrue(ch.position_set.covers(Point(20, 0)))
        self.assertEqual(ch.status, ChannelStatus.UNKNOWN)

    def test_failed_clear_demotes_invalid_ready_state(self):
        ch = ConstrainedChannelState(1)
        # Defensive state-recovery check: a contradictory external READY
        # marker must not survive once the failed-clear exclusion is applied.
        ch.status = ChannelStatus.READY
        ch.clear_position = (0.0, 0.0)
        ch.update_failed_clear((0, 0), 2)
        self.assertEqual(ch.status, ChannelStatus.ACTIVE)
        self.assertGreater(ch.mec_radius, 20.0)

    def test_compact_ring_is_exact_certificate(self):
        from compact_ring.scheduler import CompactRingScheduler
        from geometry.certificate import q3_certified
        policy = CompactRingScheduler(segment_budget=0)
        self.assertEqual(len(policy._coverage_points), 8)
        self.assertNotIn((0.0, 0.0), policy._coverage_points)
        self.assertTrue(q3_certified(policy._coverage_points)["certified"])
        route = (math.dist((0.0, 0.0), policy._coverage_points[0])
                 + sum(math.dist(a, b) for a, b in zip(
                     policy._coverage_points, policy._coverage_points[1:])))
        self.assertAlmostEqual(route, 5976.113969924581)

    def test_compact_acif_preserves_exact_certificate(self):
        from compact_ring.scheduler import CompactRingScheduler
        from geometry.certificate import q3_certified
        from state.channel_state import ChannelStatus

        class Channel:
            def __init__(self, channel_id, status, center=None):
                self.channel_id = channel_id
                self.status = status
                self.mec = (center, 50.0) if center is not None else None
                self.mec_radius = 50.0 if center is not None else float("inf")

        class Knowledge:
            def __init__(self):
                self.channels = {
                    1: Channel(1, ChannelStatus.ACTIVE, (1500.0, 200.0)),
                    2: Channel(2, ChannelStatus.UNKNOWN),
                }
            def by_status(self, status):
                return [channel for channel in self.channels.values()
                        if channel.status == status]

        policy = CompactRingScheduler(segment_budget=0,
                                      compact_acif_translate_m=250.0)
        state = Knowledge()
        policy._coverage_index = 2
        policy._coverage_remaining = set(range(2, 8))
        policy._adapt_certificate_field(state, (0.0, 0.0))
        visited = [policy._coverage_points[index] for index in range(2)]
        pending = [policy._coverage_points[index] for index in
                   sorted(policy._coverage_remaining)]
        self.assertTrue(q3_certified(visited + pending)["certified"])

    def test_compact_acif_route_gate_reduces_projected_route(self):
        from compact_ring.scheduler import CompactRingScheduler
        from state.channel_state import ChannelStatus

        class Channel:
            def __init__(self, channel_id, status, center=None):
                self.channel_id = channel_id
                self.status = status
                self.mec = (center, 50.0) if center is not None else None
                self.mec_radius = 50.0 if center is not None else float("inf")

        class Knowledge:
            def __init__(self):
                self.channels = {
                    1: Channel(1, ChannelStatus.ACTIVE, (1500.0, 200.0)),
                    2: Channel(2, ChannelStatus.UNKNOWN),
                }
            def by_status(self, status):
                return [channel for channel in self.channels.values()
                        if channel.status == status]

        policy = CompactRingScheduler(
            segment_budget=0, compact_acif_translate_m=250.0,
            compact_acif_route_aware=True,
            compact_acif_min_route_gain_m=0.0)
        state = Knowledge()
        policy._coverage_index = 2
        policy._coverage_remaining = set(range(2, 8))
        indices = tuple(sorted(policy._coverage_remaining))
        before = [policy._coverage_points[index] for index in indices]
        targets = policy._acif_targets(state, (0.0, 0.0))
        old_cost = policy._acif_route_proxy(
            (0.0, 0.0), indices, before, targets)
        policy._adapt_certificate_field(state, (0.0, 0.0))
        after = [policy._coverage_points[index] for index in indices]
        new_cost = policy._acif_route_proxy(
            (0.0, 0.0), indices, after, targets)
        self.assertLessEqual(new_cost, old_cost + 1e-9)

    def test_exact_open_path_order(self):
        from compact_ring.scheduler import CompactRingScheduler
        items = [(1, (5.0, 0.0)), (2, (1.0, 0.0)), (3, (3.0, 0.0))]
        ordered = CompactRingScheduler._exact_open_order(items, (0.0, 0.0))
        self.assertEqual([cid for cid, _ in ordered], [2, 3, 1])

    def test_strip_cover_is_finite_and_verified(self):
        from compact_ring.scheduler import CompactRingScheduler
        from verifier.geometry_verifier import verify_fallback_cover
        poly = [(0.0, -5.0), (100.0, -5.0),
                (100.0, 5.0), (0.0, 5.0)]
        covers = CompactRingScheduler._strip_covers(poly)
        points = min(covers, key=len)
        self.assertEqual(len(points), 3)
        self.assertTrue(verify_fallback_cover(poly, points, 20.0)["ok"])

    def test_q4_rejected(self):
        with self.assertRaises(ValueError):
            ConstrainedChannelState(1, mode="Q4")

    def test_search_snapshot_does_not_follow_bound_callbacks(self):
        from constraint_search.macro import ConstraintMacroScheduler, snapshot
        class ForbiddenCopy:
            def __deepcopy__(self, memo):
                raise AssertionError("copied a live runner callback")
        policy = ConstraintMacroScheduler()
        policy.stop_planner = ForbiddenCopy()
        policy.decision_listener = ForbiddenCopy()
        copied = snapshot(policy)
        self.assertNotIn('stop_planner', copied)
        self.assertNotIn('decision_listener', copied)


if __name__ == "__main__":
    unittest.main()
