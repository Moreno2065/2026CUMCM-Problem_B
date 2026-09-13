"""Dev smoke test for interval_master (not part of the formal test suite)."""

import math
import time

from src.q2.formal.interval_master import ReceptionWitness, solve_master
from src.q2.formal.scenario_loss import Scenario, box_loss_lower, float_point_loss
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.rigorous_arithmetic import Ivl


def polar(rho, phi_deg):
    p = math.radians(phi_deg)
    return rho * math.cos(p), rho * math.sin(p)


def make_seeds():
    seeds = []
    for phi in (+0.999, -0.999):
        gx, gy = polar(1499.9, phi)
        for e in (-1.0, 0.0, 1.0):
            seeds.append(Scenario(gx, gy, e, label=f"corner{phi:+}/e{e:+}"))
    gx, gy = polar(1499.999, -1.0)
    seeds.append(Scenario(gx, gy, -1.0, label="incumbent_worst"))
    gx, gy = polar(1499.999, +1.0)
    seeds.append(Scenario(gx, gy, +1.0, label="top_corner"))
    gx, gy = polar(1000.0, 0.0)
    seeds.append(Scenario(gx, gy, 0.0, label="mid"))
    return seeds


def main():
    # micro benchmark: single box_loss_lower call on a small box
    scen = make_seeds()[0]
    box = IvlPoint(Ivl.from_bounds(800.0, 801.0), Ivl.from_bounds(-601.0, -600.0))
    t0 = time.time()
    n = 200
    for _ in range(n):
        box_loss_lower(box, scen)
    dt = (time.time() - t0) / n
    lb, br = box_loss_lower(box, scen)
    print(f"box_loss_lower: {dt*1e3:.3f} ms/call  lb={lb.lower_float():.6f} branch={br}")

    seeds = make_seeds()
    # float sanity: M_k at incumbent
    inc = (805.1110506884, -599.7632926544)
    mk = max(float_point_loss(inc[0], inc[1], s) for s in seeds)
    print(f"M_k(incumbent) = {mk:.6f}")

    w0 = [ReceptionWitness(1000.0, 0.0, 1000.0)]
    b0 = (0.0, 2000.0, -1000.0, 1000.0)
    t0 = time.time()
    res = solve_master(
        scenarios=seeds,
        witnesses=w0,
        b0=b0,
        upper_bound=134.066,
        target_tol=0.005,
        max_boxes=200000,
        time_budget_s=120.0,
    )
    print(f"master: L={res.lower_bound:.6f} converged={res.converged} "
          f"boxes={res.boxes_evaluated} live={res.live_boxes} "
          f"cand={res.candidate} cand_Mk={res.candidate_mk:.6f} "
          f"t={res.wall_time_s:.1f}s")
    print(f"L <= Q*(~134.0659)? {res.lower_bound <= 134.066}")


if __name__ == "__main__":
    main()
