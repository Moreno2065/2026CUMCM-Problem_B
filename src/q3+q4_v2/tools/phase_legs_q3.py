"""Where does Q3's detour come from?  Leg decomposition around the certificate ring.

t26's decomposition says the biggest recoverable item in every live Q3 cell is
"detour" = realised movement - MST(realised stops)/5 (Q3/10 167.3, Q3/13 149.8,
Q3/16 122.9 s/source).  This probe asks a structural question the ordering
experiments never answered: *which* legs make up that detour?

Legs are classified by their endpoints:
  ring-ring    both endpoints are certificate-ring positions (origin + 6 @1200)
  ring-other   one endpoint is a ring position (a phase transition)
  other-other  neither (pure chase movement)

A large ring-other share means the policy keeps alternating between the
certificate sweep and the chase, which a phase-structure change could address;
a large other-other share means the detour is inside the chase itself.

Usage: python -X utf8 tools/phase_legs_q3.py [--root tuning_runs/ab_probe/production]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RING_R = 1200.0


def ring_points():
    pts = [(0.0, 0.0)]
    pts += [(RING_R * math.cos(math.radians(60 * i)),
             RING_R * math.sin(math.radians(60 * i))) for i in range(6)]
    return pts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--tol", type=float, default=1.0)
    args = ap.parse_args()
    ring = ring_points()

    rows = []
    for d in sorted(glob.glob(str(ROOT / args.root / "Q3_*_*"))):
        run = Path(d)
        acts = run / "actions.csv"
        if not acts.exists():
            continue
        name = run.name.split("_")
        n = int(name[1])
        prev = None
        tot = rr = ro = oo = 0.0
        changes = 0
        last_kind = None
        with acts.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    x, y = float(row["target_x"]), float(row["target_y"])
                except (TypeError, ValueError, KeyError):
                    continue
                mv = float(row.get("movement_time") or 0.0)
                if mv <= 0.0:
                    continue
                p = (x, y)
                if prev is not None:
                    a = any(math.dist(prev, q) <= args.tol for q in ring)
                    b = any(math.dist(p, q) <= args.tol for q in ring)
                    kind = "rr" if (a and b) else ("oo" if (not a and not b) else "ro")
                    tot += mv
                    if kind == "rr":
                        rr += mv
                    elif kind == "ro":
                        ro += mv
                    else:
                        oo += mv
                    if last_kind is not None and kind != last_kind:
                        changes += 1
                    last_kind = kind
                prev = p
        if tot <= 0:
            continue
        rows.append({"run": run.name, "n": n, "move_s": tot, "rr": rr, "ro": ro,
                     "oo": oo, "changes": changes})

    print(f"{'run':16}{'n':>3}{'move_s':>9}{'ring-ring':>11}{'ring-other':>12}"
          f"{'other-other':>13}{'transitions':>12}")
    for r in sorted(rows, key=lambda x: x["run"]):
        print(f"{r['run']:16}{r['n']:>3}{r['move_s']:>9.1f}"
              f"{r['rr']:>8.1f}({100 * r['rr'] / r['move_s']:>4.1f}%)"
              f"{r['ro']:>8.1f}({100 * r['ro'] / r['move_s']:>4.1f}%)"
              f"{r['oo']:>8.1f}({100 * r['oo'] / r['move_s']:>4.1f}%)"
              f"{r['changes']:>12}")
    print()
    for n in sorted({r["n"] for r in rows}):
        sub = [r for r in rows if r["n"] == n]
        print(f"Q3/{n}: {len(sub)} runs | ring-ring {statistics.mean(r['rr'] for r in sub):7.1f} s"
              f" ({100 * statistics.mean(r['rr'] for r in sub) / statistics.mean(r['move_s'] for r in sub):4.1f}%)"
              f" | ring-other {statistics.mean(r['ro'] for r in sub):7.1f} s"
              f" ({100 * statistics.mean(r['ro'] for r in sub) / statistics.mean(r['move_s'] for r in sub):4.1f}%)"
              f" | other-other {statistics.mean(r['oo'] for r in sub):7.1f} s"
              f" ({100 * statistics.mean(r['oo'] for r in sub) / statistics.mean(r['move_s'] for r in sub):4.1f}%)"
              f" | transitions {statistics.mean(r['changes'] for r in sub):5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
