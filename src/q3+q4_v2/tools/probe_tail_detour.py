"""Ceiling of "tail-only ordering": reorder the chase *after* the certificate closes.

The ordering family (``order_plan``) failed because it interleaves the
certificate sweep with the chase and inflates measurements (t23: the net gate
saw 0.0 s per blocked step; t28: Q3/13 +61.9 s/source).  But
``tools/phase_legs_q3.py`` shows the ring is walked as one clean sweep and
58-69% of Q3 movement happens afterwards, inside the chase.

A *causally* activated variant would be: keep production order until the
certificate closes, then order the remaining chase stops globally:

    activate order_plan only once the last ring anchor has been visited

No prediction is needed (the trigger is an observed event) and the certificate
phase cannot be perturbed (it is already over).  This probe measures the
**ceiling**: how much of the post-ring movement is detour, i.e. how much a
perfect reordering of the remaining stops could recover.

Usage: python -X utf8 tools/probe_tail_detour.py [--root tuning_runs/ab_probe/production]
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import mst_len  # noqa: E402

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
        n = int(run.name.split("_")[1])
        recs = []
        with acts.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                tx, ty = (r.get("target_x") or "").strip(), (r.get("target_y") or "").strip()
                if not tx or not ty:
                    continue  # rows without a position must NOT be coerced to (0,0)
                try:
                    recs.append({
                        "step": int(float(r["step"] or 0)),
                        "t": float(r["virtual_time_after"] or 0.0),
                        "x": float(tx),
                        "y": float(ty),
                        "type": r["action_type"],
                        "dist": float(r.get("movement_distance") or 0.0),
                    })
                except (TypeError, ValueError):
                    continue
        if not recs:
            continue
        ring_steps = [r["step"] for r in recs
                      if math.hypot(r["x"], r["y"]) > 1.0
                      and any(math.dist((r["x"], r["y"]), q) <= args.tol
                              for q in ring)]
        if not ring_steps:
            continue
        last_ring = max(ring_steps)
        ring_t = next(r["t"] for r in recs if r["step"] == last_ring)
        tail_move = sum(r["dist"] for r in recs if r["step"] > last_ring)
        tail_stops, seen = [], set()
        for r in recs:
            if r["step"] <= last_ring:
                continue
            key = (round(r["x"], 3), round(r["y"], 3))
            if key not in seen:
                seen.add(key)
                tail_stops.append((r["x"], r["y"]))
        pos = next(((r["x"], r["y"]) for r in recs if r["step"] == last_ring),
                   (0.0, 0.0))
        mst = mst_len([pos] + tail_stops) if tail_stops else 0.0
        total_move = sum(r["dist"] for r in recs)
        rows.append({
            "run": run.name, "n": n,
            "last_ring_t": next(r["t"] for r in recs if r["step"] == last_ring),
            "total_move_s": total_move / 5.0,
            "tail_move_s": tail_move / 5.0,
            "tail_mst_s": mst / 5.0,
            "tail_detour_s": (tail_move - mst) / 5.0,
            "tail_stops": len(tail_stops),
        })

    print(f"{'run':16}{'n':>3}{'ring done t':>12}{'tail move s':>12}"
          f"{'tail MST s':>11}{'tail detour s':>14}{'detour/source':>14}{'stops':>7}")
    for r in sorted(rows, key=lambda x: x["run"]):
        print(f"{r['run']:16}{r['n']:>3}{r['last_ring_t']:>12.0f}"
              f"{r['tail_move_s']:>12.1f}{r['tail_mst_s']:>11.1f}"
              f"{r['tail_detour_s']:>14.1f}{r['tail_detour_s'] / r['n']:>14.1f}"
              f"{r['tail_stops']:>7}")
    print()
    for n in sorted({r["n"] for r in rows}):
        sub = [r for r in rows if r["n"] == n]
        tm = statistics.mean(r["tail_move_s"] for r in sub)
        td = statistics.mean(r["tail_detour_s"] for r in sub)
        print(f"Q3/{n}: {len(sub)} runs | ring done at "
              f"{statistics.mean(r['last_ring_t'] for r in sub):6.0f} s | "
              f"tail move {tm:7.1f} s ({100 * tm / statistics.mean(r['total_move_s'] for r in sub):4.1f}% "
              f"of total) | tail detour {td:7.1f} s = **{td / n:5.1f} s/source** ceiling")
    # ---------------------------------------------------------------- attainable
    # The ceiling above includes *discovery*: sources first seen during the tail
    # cannot be ordered before they are known.  A reorderer can only touch stops
    # whose task is already known, so measure the ceiling from the moment the
    # LAST source becomes known (everything after that is pure "go clear what you
    # already found").
    print()
    print("== attainable ceiling: movement after the LAST source is detected ==")
    att = {}
    for d in sorted(glob.glob(str(ROOT / args.root / "Q3_*_*"))):
        run = Path(d)
        obs = run / "observations.csv"
        acts = run / "actions.csv"
        if not (obs.exists() and acts.exists()):
            continue
        n = int(run.name.split("_")[1])
        first = {}
        with obs.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["result"] != "direction":
                    continue
                ch = int(r["channel"])
                if ch not in first:
                    first[ch] = float(r["virtual_time"])
        if not first:
            continue
        t_full = max(first.values())
        recs = []
        with acts.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                tx, ty = (r.get("target_x") or "").strip(), (r.get("target_y") or "").strip()
                if not tx or not ty:
                    continue
                try:
                    recs.append({"step": int(float(r["step"] or 0)),
                                 "t": float(r["virtual_time_after"] or 0.0),
                                 "x": float(tx), "y": float(ty),
                                 "dist": float(r.get("movement_distance") or 0.0)})
                except (TypeError, ValueError):
                    continue
        if not recs:
            continue
        before = [r for r in recs if r["t"] <= t_full]
        after = [r for r in recs if r["t"] > t_full]
        pos = (before[-1]["x"], before[-1]["y"]) if before else (0.0, 0.0)
        move = sum(r["dist"] for r in after)
        stops, seen = [], set()
        for r in after:
            k = (round(r["x"], 3), round(r["y"], 3))
            if k not in seen:
                seen.add(k)
                stops.append((r["x"], r["y"]))
        mst = mst_len([pos] + stops) if stops else 0.0
        att.setdefault(n, []).append((move - mst) / 5.0 / n)
    for n in sorted(att):
        v = att[n]
        print(f"Q3/{n}: {len(v)} runs | attainable tail ceiling "
              f"mean **{statistics.mean(v):5.1f}** s/source  "
              f"(median {statistics.median(v):5.1f}, max {max(v):5.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
