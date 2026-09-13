"""Recover a physical adversarial scenario from a certified worst beta (s.18-19).

The scenario loss depends on the scenario only through the measured bearing
beta = arg(G - X_k) + e, so recovering the worst scenario means finding a
strictly legal (G, e) - G in A1 with 5 < |G| <= 1500 and |arg G| <= eps,
e in [-eps, eps] - whose measured bearing matches the certified worst beta
interval.  Every candidate is *verified* by a rigorous point loss enclosure
at X_k; the support gap

    eta = q_hi(X_k) - loss_lower(X_k; s)

is recorded (spec s.19).  A scenario is a valid master cut no matter how
large eta is (any strictly legal scenario is a physical scenario); eta only
measures how well the cut captures the worst case.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.q2.formal.ivl_geometry import (
    EPS,
    BranchCutError,
    IvlPoint,
    arg_enclosure,
    polar_point,
)
from src.q2.formal.polar_bb import PolarExtremum, polar_max, polar_min
from src.q2.formal.rigorous_arithmetic import Ivl
from src.q2.formal.scenario_loss import Scenario, point_loss_enclosure

_EPS_F = math.pi / 180.0


@dataclass
class RecoveredScenario:
    scenario: Scenario | None
    loss_lo: float            # certified lower edge of loss(X_k; s)
    loss_hi: float
    eta: float                # q_hi - loss_lo (spec s.19)
    support_type: str         # "attained" | "closure_only" | "failed"
    closure_only: bool
    beta_measured: float      # float arg(G - X_k) + e [rad]
    detail: str = ""

    @property
    def valid(self) -> bool:
        return self.scenario is not None


_FULL_CIRCLE_LO = -math.pi - 1e-15
_FULL_CIRCLE_HI = math.pi + 1e-15


def _full_circle_extremum() -> PolarExtremum:
    """Safe guidance fallback: the arg image wraps (S2 inside closure(A1)).

    Guidance only - every generated candidate is re-verified by a rigorous
    point loss enclosure, so a full-circle estimate can never produce an
    unsound cut, only extra (filtered) candidates.
    """
    v = Ivl.from_bounds(_FULL_CIRCLE_LO, _FULL_CIRCLE_HI)
    return PolarExtremum(v, math.nan, math.nan, 0, True)


def _true_arg_image(s2: IvlPoint):
    """Rigorous [amin, amax] of arg(G - S2) over closure(A1) with witnesses.

    If S2 lies inside the polar A1 rectangle the image wraps around the
    atan2 branch cut and no single arc exists; fall back to the full circle
    (guidance only).
    """
    s2x, s2y = s2.x.mid_float(), s2.y.mid_float()

    def f(rho: Ivl, phi: Ivl) -> Ivl:
        g = polar_point(rho, phi)
        return arg_enclosure(IvlPoint(g.x - s2.x, g.y - s2.y))

    def ff(rho: float, phi: float) -> float:
        return math.atan2(rho * math.sin(phi) - s2y, rho * math.cos(phi) - s2x)

    try:
        return polar_min(f, ff, 1e-10), polar_max(f, ff, 1e-10)
    except BranchCutError:
        fc = _full_circle_extremum()
        return fc, fc


def _ray_hit_a1(s2x: float, s2y: float, theta: float) -> tuple[float, float] | None:
    """Float construction: a strictly legal G on the ray X_k + t u(theta).

    Returns (gx, gy) or None if the ray misses A1.  Candidate construction
    only - legality is re-verified by the Scenario class and the rigorous
    loss enclosure.
    """
    ux, uy = math.cos(theta), math.sin(theta)
    # candidate t values from intersections with the polar-rectangle boundary
    ts: list[float] = []
    # circles |G| = 5 and |G| = 1500
    for r in (5.0, 1500.0):
        b = s2x * ux + s2y * uy
        c = s2x * s2x + s2y * s2y - r * r
        disc = b * b - c
        if disc > 0:
            sq = math.sqrt(disc)
            ts.extend([-b - sq, -b + sq])
    # wedge sides arg G = +/- eps: cross(s, X + t u) = 0
    for sgn in (+1.0, -1.0):
        sx_, sy_ = math.cos(sgn * _EPS_F), math.sin(sgn * _EPS_F)
        denom = sx_ * uy - sy_ * ux
        if abs(denom) > 1e-300:
            ts.append(-(sx_ * s2y - sy_ * s2x) / denom)
    ts = sorted(t for t in ts if t > 5.0)  # must stay a bearing scenario

    def legal(t: float) -> bool:
        gx, gy = s2x + t * ux, s2y + t * uy
        rho = math.hypot(gx, gy)
        phi = math.degrees(math.atan2(gy, gx))
        return 5.0 + 1e-6 < rho <= 1500.0 - 1e-6 and abs(phi) <= 1.0 - 1e-9

    # feasible t intervals lie between consecutive boundary hits; probe
    points = [5.0 + 1e-3] + ts + [ts[-1] + 1.0 if ts else 3000.0]
    best = None
    for a, b in zip(points, points[1:]):
        mid = 0.5 * (a + b)
        if legal(mid):
            span = b - a
            if best is None or span > best[0]:
                best = (span, mid)
    if best is None:
        # maybe a single boundary hit interval was degenerate; probe around ts
        for t in ts:
            for dt in (1e-3, -1e-3, 1e-1, -1e-1):
                if legal(t + dt):
                    best = (1e-3, t + dt)
                    break
            if best:
                break
    if best is None:
        return None
    t = best[1]
    return s2x + t * ux, s2y + t * uy


def _verify(s2: IvlPoint, scen: Scenario) -> tuple[float, float]:
    enc = point_loss_enclosure(s2, scen)
    if enc.lower is None or enc.upper is None:
        return 0.0, math.inf
    return enc.lower.lower_float(), enc.upper.upper_float()


def recover_worst_physical_scenario(
    s2x: float,
    s2y: float,
    worst_beta_interval: tuple[float, float],
    q_hi: float,
    eta_target: float = 1e-4,
) -> RecoveredScenario:
    """Recover (G, e) with loss(X_k; s) >= q_hi - eta, eta recorded."""
    s2 = IvlPoint(Ivl.from_float(s2x), Ivl.from_float(s2y))
    beta_c = 0.5 * (worst_beta_interval[0] + worst_beta_interval[1])

    amin, amax = _true_arg_image(s2)
    a_lo = amin.value.mid_float()
    a_hi = amax.value.mid_float()

    candidates: list[tuple[float, float, float, str]] = []  # (gx, gy, e, tag)

    def add_ray_candidate(theta: float, e: float, tag: str):
        hit = _ray_hit_a1(s2x, s2y, theta)
        if hit is not None:
            candidates.append((hit[0], hit[1], e, tag))

    # (a) interior attainment: beta_c inside the true image
    if a_lo + 1e-12 <= beta_c <= a_hi - 1e-12:
        add_ray_candidate(beta_c, 0.0, "interior")
    # (b) endpoint attainment with edge error (the typical E1 case)
    for e_frac in (1.0 - 1e-9, -1.0 + 1e-9, 0.5, -0.5, 0.0):
        e = e_frac * _EPS_F
        add_ray_candidate(beta_c - e, e, f"ray_e{e_frac:+.2f}")
    # (c) closure-only: use the rigorous extremizer witness
    for ext, tag in ((amin, "amin_witness"), (amax, "amax_witness")):
        if not math.isfinite(ext.arg_rho):
            continue  # full-circle fallback has no witness to legalize
        gx = ext.arg_rho * math.cos(ext.arg_phi)
        gy = ext.arg_rho * math.sin(ext.arg_phi)
        rho = math.hypot(gx, gy)
        if rho <= 5.0 + 1e-9:
            # legalize: push radially outward, stay on the same ray
            gx *= (5.0 + 1e-6) / rho
            gy *= (5.0 + 1e-6) / rho
        phi = math.degrees(math.atan2(gy, gx))
        if abs(phi) > 1.0 - 1e-9:
            phi = math.copysign(1.0 - 1e-9, phi)
            rho = math.hypot(gx, gy)
            gx, gy = rho * math.cos(math.radians(phi)), rho * math.sin(math.radians(phi))
        e = beta_c - math.atan2(gy - s2y, gx - s2x)
        e = max(-_EPS_F * (1 - 1e-9), min(_EPS_F * (1 - 1e-9), e))
        candidates.append((gx, gy, e, tag))

    best: RecoveredScenario | None = None
    for gx, gy, e, tag in candidates:
        try:
            scen = Scenario(gx, gy, math.degrees(e), label=tag)
        except ValueError:
            continue
        l_lo, l_hi = _verify(s2, scen)
        eta = q_hi - l_lo
        beta_meas = math.atan2(gy - s2y, gx - s2x) + e
        rec = RecoveredScenario(
            scen, l_lo, l_hi, eta,
            "closure_only" if "witness" in tag else "attained",
            "witness" in tag, beta_meas, tag)
        if best is None or rec.eta < best.eta:
            best = rec
        if eta <= eta_target:
            break
    if best is None:
        return RecoveredScenario(None, 0.0, math.inf, math.inf, "failed",
                                 True, math.nan, "no legal candidate")
    return best


def recover_unbounded_scenario(
    s2x: float, s2y: float
) -> RecoveredScenario | None:
    """Find a strictly legal scenario with certified +inf loss at X_k.

    Used when the UB certifier reports UNBOUNDED: the measured-bearing
    superset dips into |beta| <= 2 eps.  Returns None when no legal scenario
    attains an unbounded join (superset overshoot - no cut possible).
    """
    s2 = IvlPoint(Ivl.from_float(s2x), Ivl.from_float(s2y))
    rho2 = math.hypot(s2x, s2y)
    phi2 = math.degrees(math.atan2(s2y, s2x))
    if 5.0 <= rho2 <= 1500.0 and abs(phi2) <= 1.0 + 1e-12:
        # The relative-vector box can contain the origin, so its angle image
        # is not a single interval.  A zero-bearing ray directly supplies a
        # valid unbounded witness when it meets the physical A1 set.
        candidate_thetas = (0.0,)
    else:
        amin, amax = _true_arg_image(s2)
        a_lo, a_hi = amin.value.mid_float(), amax.value.mid_float()
        candidate_thetas = (max(a_lo, min(0.0, a_hi)), a_lo, a_hi)
    for theta in candidate_thetas:
        hit = _ray_hit_a1(s2x, s2y, theta)
        if hit is None:
            continue
        for e in (0.0, 0.5 * _EPS_F, -0.5 * _EPS_F):
            try:
                scen = Scenario(hit[0], hit[1], math.degrees(e),
                                label="unbounded")
            except ValueError:
                continue
            enc = point_loss_enclosure(s2, scen)
            if enc.bounded.name == "FALSE":
                beta_meas = math.atan2(hit[1] - s2y, hit[0] - s2x) + e
                return RecoveredScenario(
                    scen, math.inf, math.inf, 0.0, "attained_unbounded",
                    False, beta_meas, "unbounded join certified")
    return None
