"""Recompute the Q3 certificate-composite bound over *optimal* witness covers.

BOUNDS.md (t26) used production's seven-point ring at r=1200 (open path 7 200 m)
as the Q3 travel term.  But the Q3 predicate only requires that Omega be covered
by the union of radius-r_eff disks around the recorded witnesses -- the witness
*positions* are free, so a provable lower bound must minimise the travel over all
valid covers (t7 found centre + 6 @ 1124 m is valid with worst coverage 999.5 m).

Q4 is different: `q4_channel_certified_sparse25` fixes 25 exact coordinates, so
its travel term (17 990.7 m) cannot be optimised.

Usage: python -X utf8 tools/q3_bound_recheck.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import mst_len  # noqa: E402

TARGET = 176.25


def ring(r: float):
    return [(r * math.cos(math.radians(60 * i)), r * math.sin(math.radians(60 * i)))
            for i in range(6)]


def main() -> int:
    print(f"{'r (m)':>8}{'open path m':>13}{'travel s':>10}"
          + "".join(f"{'N=%d' % n:>12}" for n in (10, 13, 16)))
    for r in (1200.0, 1124.0, 1121.6):
        pts = [(0.0, 0.0)] + ring(r)
        length = mst_len(pts)
        row = f"{r:>8.1f}{length:>13.1f}{length / 5:>10.1f}"
        for n in (10, 13, 16):
            absent = 20 - n
            composite = (length / 5 + 7 * absent * 5 + 5 * n) / n
            flag = "EXCL" if composite > TARGET else "ok"
            row += f"{composite:>9.2f}{flag:>3}"
        print(row)
    print("\nQ4 (predicate fixes the 25 coordinates => travel term is not optimisable):")
    q4 = 17990.7
    for n in (10, 13, 16):
        absent = 20 - n
        composite = (q4 / 5 + 25 * absent * 5 + 5 * n) / n
        print(f"  N={n:2d}: {composite:7.2f} s/source "
              f"({'EXCLUDED' if composite > 290.0 else 'not excluded'}) vs target 290")
    print("\nQ3 witness-count sensitivity (k points, k=7 is the proven minimum):")
    for k in (5, 6, 7):
        for n in (10,):
            pass
    for k in (5, 6, 7):
        length = mst_len([(0.0, 0.0)] + ring(1124.0)[:min(k - 1, 6)]) if k >= 1 else 0.0
        print(f"  k={k}: (informational only -- k<7 cannot cover Omega at all)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
