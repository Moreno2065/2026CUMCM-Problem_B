"""Is Q3's chase internally wasteful, or just geometrically spread out?

tools/phase_legs_q3.py showed 58-69% of Q3 movement happens inside the chase
(other-other legs), and t26's decomposition puts the "detour" at 123-167 s/source.
Those two facts together do not yet say whether a *chase* mechanism could help:
a near-straight approach to every source would already be near-optimal.

For every source this probe measures, from its **first detection** (a `direction`
reading) to its **successful clear**:

    path_len    = movement actually driven in between (actions.csv)
    straight    = straight-line distance between those two positions
    ratio       = path_len / straight

ratio ~ 1 means the chase drives almost straight at the source (no lever);
ratio >> 1 means the approach zigzags or overshoots (a lever exists).

Usage: python -X utf8 tools/probe_chase_efficiency.py [--root ...] [--mode Q3]
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


def load_actions(run: Path):
    rows = []
    with (run / "actions.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append({
                    "step": int(float(r["step"] or 0)),
                    "t": float(r["virtual_time_after"] or 0.0),
                    "x": float(r["target_x"] or 0.0),
                    "y": float(r["target_y"] or 0.0),
                    "type": r["action_type"],
                    "ch": r.get("channel") or "",
                    "dist": float(r.get("movement_distance") or 0.0),
                })
            except (TypeError, ValueError):
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--mode", default="Q3")
    args = ap.parse_args()

    per_cell = {}
    per_final = {}
    seg_rows = {}
    for d in sorted(glob.glob(str(ROOT / args.root / f"{args.mode}_*_*"))):
        run = Path(d)
        if not (run / "actions.csv").exists():
            continue
        name = run.name.split("_")
        n = int(name[1])
        acts = load_actions(run)
        if not acts:
            continue
        # direction readings per channel (first and last) -- the *last* one is
        # the operative fix for the final approach; the first one only says when
        # the source became known at all.
        dirs = {}
        with (run / "observations.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["result"] != "direction":
                    continue
                ch = int(r["channel"])
                dirs.setdefault(ch, []).append(
                    {"step": int(float(r["step"] or 0)),
                     "x": float(r["x"]), "y": float(r["y"])})
        first_dir = {ch: v[0] for ch, v in dirs.items()}
        last_dir = {ch: v[-1] for ch, v in dirs.items()}
        # step at which each channel becomes CLEARED
        cleared_step = {}
        hist = run / "channel_state_history.jsonl"
        if hist.exists():
            for line in hist.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for ch, st in (rec.get("channels") or {}).items():
                    if str(st.get("status")) == "CLEARED" and int(ch) not in cleared_step:
                        cleared_step[int(ch)] = rec.get("step")
        ratios = []
        final = []
        for ch, det in first_dir.items():
            step_c = cleared_step.get(ch)
            if step_c is None:
                continue
            clear_act = next((a for a in acts
                              if a["step"] == step_c and a["type"] == "clear"
                              and str(a["ch"]) == str(ch)), None)
            if clear_act is None:
                continue
            path_len = sum(a["dist"] for a in acts
                           if det["step"] < a["step"] <= step_c)
            straight = math.dist((det["x"], det["y"]),
                                 (clear_act["x"], clear_act["y"]))
            if straight < 1.0:
                continue
            ratios.append({"ch": ch, "path": path_len, "straight": straight,
                           "ratio": path_len / straight})
            last = last_dir.get(ch)
            if last is None or last["step"] >= step_c:
                continue
            p_final = sum(a["dist"] for a in acts
                          if last["step"] < a["step"] <= step_c)
            s_final = math.dist((last["x"], last["y"]),
                                (clear_act["x"], clear_act["y"]))
            if s_final >= 1.0:
                final.append({"ch": ch, "path": p_final, "straight": s_final,
                              "ratio": p_final / s_final})
        if ratios:
            per_cell.setdefault(n, []).extend(ratios)
        if final:
            per_final.setdefault(n, []).extend(final)
        # contiguous approach segment: walk back from the successful clear while
        # the actions belong to the same channel -- this isolates the movement the
        # policy itself attributes to reaching that source, with no interleaving.
        truth = {}
        gt = run / "ground_truth.json"
        if gt.exists():
            for s in json.loads(gt.read_text(encoding="utf-8")):
                truth[int(s["channel"])] = (float(s["x"]), float(s["y"]))
        for i, a in enumerate(acts):
            if a["type"] != "clear" or str(a["ch"]) == "":
                continue
            ch = int(a["ch"])
            if cleared_step.get(ch) != a["step"] or ch not in truth:
                continue
            j = i
            seg = 0.0
            while j >= 0 and str(acts[j]["ch"]) == str(ch):
                seg += acts[j]["dist"]
                j -= 1
            start = acts[j + 1]
            sx, sy = start["x"], start["y"]
            gx, gy = truth[ch]
            straight = math.dist((sx, sy), (gx, gy))
            if straight >= 1.0:
                seg_rows.setdefault(n, []).append(
                    {"ch": ch, "seg": seg, "straight": straight,
                     "ratio": seg / straight,
                     "end_dist": math.dist((a["x"], a["y"]), (gx, gy))})

    for n in sorted(per_cell):
        sub = per_cell[n]
        rs = sorted(r["ratio"] for r in sub)
        print(f"{args.mode}/{n}: {len(sub)} cleared sources with a direction "
              f"first-detection")
        print(f"   ratio path/straight: mean {statistics.mean(rs):5.2f}  "
              f"median {statistics.median(rs):5.2f}  p10 {rs[len(rs) // 10]:5.2f}  "
              f"p90 {rs[9 * len(rs) // 10]:5.2f}  max {rs[-1]:5.2f}")
        near = sum(1 for x in rs if x <= 1.25)
        print(f"   straight-ish (<=1.25): {near}/{len(rs)}  "
              f"| >2.0: {sum(1 for x in rs if x > 2.0)}/{len(rs)}")
        print(f"   mean path {statistics.mean(r['path'] for r in sub):7.1f} m "
              f"vs mean straight "
              f"{statistics.mean(r['straight'] for r in sub):7.1f} m")
    print()
    for n in sorted(per_final):
        sub = per_final[n]
        rs = sorted(r["ratio"] for r in sub)
        print(f"{args.mode}/{n} FINAL APPROACH (last direction -> clear): "
              f"{len(sub)} sources")
        print(f"   ratio path/straight: mean {statistics.mean(rs):5.2f}  "
              f"median {statistics.median(rs):5.2f}  p10 {rs[len(rs) // 10]:5.2f}  "
              f"p90 {rs[9 * len(rs) // 10]:5.2f}  max {rs[-1]:5.2f}")
        print(f"   straight-ish (<=1.25): {sum(1 for x in rs if x <= 1.25)}/{len(rs)}"
              f"  | >2.0: {sum(1 for x in rs if x > 2.0)}/{len(rs)}")
        print(f"   mean path {statistics.mean(r['path'] for r in sub):7.1f} m "
              f"vs mean straight "
              f"{statistics.mean(r['straight'] for r in sub):7.1f} m")
    print()
    for n in sorted(seg_rows):
        sub = seg_rows[n]
        rs = sorted(r["ratio"] for r in sub)
        excess = statistics.mean(r["seg"] - r["straight"] for r in sub)
        print(f"{args.mode}/{n} CONTIGUOUS APPROACH SEGMENT: {len(sub)} sources")
        print("   CAVEAT: the segment starts at the first same-channel action, "
              "which is often already beside the source, so the ratio below is "
              "not a driving-efficiency measure -- use the FINAL APPROACH block.")
        print(f"   ratio seg/straight: mean {statistics.mean(rs):5.2f}  "
              f"median {statistics.median(rs):5.2f}  "
              f"p90 {rs[9 * len(rs) // 10]:5.2f}  max {rs[-1]:5.2f}")
        print(f"   straight-ish (<=1.25): {sum(1 for x in rs if x <= 1.25)}/{len(rs)}"
              f"  | >2.0: {sum(1 for x in rs if x > 2.0)}/{len(rs)}")
        print(f"   mean segment {statistics.mean(r['seg'] for r in sub):7.1f} m vs "
              f"mean straight {statistics.mean(r['straight'] for r in sub):7.1f} m"
              f" | excess {excess:6.1f} m = {excess / n:5.1f} s/source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
