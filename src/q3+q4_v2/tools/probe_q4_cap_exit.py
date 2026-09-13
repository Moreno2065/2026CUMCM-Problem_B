"""Ceiling of the "exit the certificate mesh once the cardinality cap fires" idea.

At N=16 the runner certifies every remaining channel absent as soon as 16
distinct channels are confirmed (``confirmed = ACTIVE + READY + CLEARED``), so
the certificate tour's *outer* mesh points become pure overhead.  The inner ring
(12 points @950 m, 30 deg apart) already covers Omega within 916 m <= r_eff
(min observed r_eff = 1000.1 m, see tools/probe_r_eff.py), i.e. it guarantees
that every source is seen.

This probe measures, on existing Q4/16 runs, how much movement is spent **after**
the cap fires on certificate stops -- the upper bound of what an early exit
could recover.  It is a ceiling, not a prediction: skipping those stops also
removes the closer vantage points the chase may be using.

Usage: python -X utf8 tools/probe_q4_cap_exit.py [--root tuning_runs/ab_probe/production] [--n 16]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIRMED = {"ACTIVE", "READY", "CLEARED"}


def cap_step(run: Path):
    """First step at which 16 distinct channels are confirmed."""
    hist = run / "channel_state_history.jsonl"
    if not hist.exists():
        return None
    for line in hist.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        chans = rec.get("channels") or {}
        n_conf = sum(1 for c in chans.values()
                     if str(c.get("status")) in CONFIRMED)
        if n_conf >= 16:
            return rec.get("step"), rec.get("virtual_time")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--n", type=int, default=16)
    args = ap.parse_args()

    rows = []
    for d in sorted(glob.glob(str(ROOT / args.root / f"Q4_{args.n}_*"))):
        run = Path(d)
        api = run / "actions.csv"
        if not api.exists():
            continue
        cap = cap_step(run)
        if cap is None:
            rows.append({"run": run.name, "cap_step": None})
            continue
        step0 = cap[0]
        after_move = after_cov_move = 0.0
        cov_after = 0
        with api.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    st = int(float(row.get("step") or 0))
                except ValueError:
                    continue
                if st < step0:
                    continue
                m = float(row.get("movement_time") or 0.0)
                after_move += m
                if (row.get("reason_code") or "") in ("coverage", "certificate"):
                    after_cov_move += m
                    cov_after += 1
        rows.append({"run": run.name, "cap_step": step0, "cap_time": cap[1],
                     "move_after_cap_s": after_move,
                     "coverage_move_after_cap_s": after_cov_move,
                     "coverage_stops_after_cap": cov_after})
    ok = [r for r in rows if r.get("cap_step")]
    print(f"Q4/{args.n} runs scanned: {len(rows)}; cap fired in {len(ok)}")
    if not ok:
        return 0
    for r in ok:
        print(f"  {r['run']:16} cap at step {r['cap_step']:>4} "
              f"(t={r['cap_time']:8.1f} s) | move after {r['move_after_cap_s']:8.1f} s "
              f"| of which coverage {r['coverage_move_after_cap_s']:8.1f} s "
              f"({r['coverage_stops_after_cap']} stops)")
    cm = [r["coverage_move_after_cap_s"] for r in ok]
    am = [r["move_after_cap_s"] for r in ok]
    print(f"\nmean coverage movement AFTER the cap: {statistics.mean(cm):8.1f} s "
          f"= {statistics.mean(cm) / args.n:6.1f} s/source   (ceiling if all of it "
          f"became free)")
    print(f"mean total movement after the cap:    {statistics.mean(am):8.1f} s "
          f"= {statistics.mean(am) / args.n:6.1f} s/source")
    print("\nNOTE: a ceiling, not a prediction -- those stops also provide close "
          "vantage points for the chase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
