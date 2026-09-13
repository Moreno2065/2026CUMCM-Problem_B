"""Float incumbent improvement on the Crec boundary (heuristic, non-certificate).

Scans the active reception circle (G* = (5, +1deg) corner, R = 1000) around
the known optimum direction, then polishes with a margin-penalty NM.
Output: src/q2/artifacts/formal/incumbent_float_reconciled.json
"""

import json
import math

import numpy as np
from scipy.optimize import minimize

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec, is_in_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.q2_point import evaluate_q2_point

S1 = Point2(0.0, 0.0)
A1 = build_a1(FirstObservation(S1, 0.0, 1.0))
CREC = build_crec(A1)
GS = (4.999238475781956, 0.08726203218641757)


def q_marg(x, y):
    r = evaluate_q2_point(S1, 0.0, Point2(x, y))
    ev = is_in_crec(CREC, Point2(x, y))
    ok = r.in_crec and r.admissible and not r.all_near and r.Q is not None
    return (r.Q if ok else 1e7), ev.margin_m


def main():
    t0 = math.atan2(-606.4105445247 - GS[1], 800.0831401130 - GS[0])
    best = (1e9, None, None)
    for t in np.linspace(t0 - 0.25, t0 + 0.25, 2001):
        x = GS[0] + 1000.0 * math.cos(t)
        y = GS[1] + 1000.0 * math.sin(t)
        q, m = q_marg(x, y)
        if m > -1e-7 and q < best[0]:
            best = (q, x, y)
    print(f"circle scan: S2=({best[1]:.8f},{best[2]:.8f}) Q={best[0]:.8f}", flush=True)

    def pen(v, m0=2e-4):
        q, m = q_marg(v[0], v[1])
        return q + (0.0 if m >= m0 else 3e5 * (m0 - m) ** 2 + 1e4 * (m0 - m))

    starts = [(best[1], best[2]), (800.0831401130, -606.4105445247),
              (802.6128928494, -603.0812536809)]
    champion = best
    for s in starts:
        res = minimize(pen, s, method="Nelder-Mead",
                       options=dict(xatol=1e-12, fatol=1e-14, maxfev=1500))
        q, m = q_marg(res.x[0], res.x[1])
        print(f"start {s}: -> ({res.x[0]:.10f},{res.x[1]:.10f}) "
              f"Q={q:.10f} margin={m:.3e}", flush=True)
        if m > 0 and q < champion[0]:
            champion = (q, float(res.x[0]), float(res.x[1]))
    q, x, y = champion
    r = evaluate_q2_point(S1, 0.0, Point2(x, y))
    print(f"CHAMPION: S2=({x:.10f},{y:.10f}) Q={q:.10f} "
          f"worst_beta={r.worst_beta} type={r.worst_candidate_type}", flush=True)
    json.dump({"S2": [x, y], "Q": q, "worst_beta_deg": r.worst_beta,
               "type": r.worst_candidate_type},
              open("src/q2/artifacts/formal/incumbent_float_reconciled.json", "w"),
              indent=1)


if __name__ == "__main__":
    main()
