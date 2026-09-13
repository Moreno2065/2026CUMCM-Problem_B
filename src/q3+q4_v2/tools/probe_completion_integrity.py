"""Integrity check: does `complete` really mean every source was cleared?

The completion criterion treats `no_signal` at the certificate points as absence
evidence, but a **directional** source returns `no_signal` from behind
(simulator.py: distance <= r_eff AND inside the frontal half-plane).  A source
that is never approached from the front could therefore be certified absent
while still present.

This probe audits every stored run: `complete` + `verifier_all_ok` versus
`metrics.sources_total` and `metrics.cleared_count`.

Usage: python -X utf8 tools/probe_completion_integrity.py [--root tuning_runs/ab_probe]
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    total = 0
    complete = 0
    bad = []
    shortfall = Counter()
    for d in sorted(glob.glob(str(ROOT / args.root / "*" / "*"))):
        run = Path(d)
        rep_f = run / "run_report.json"
        met_f = run / "metrics.json"
        if not (rep_f.exists() and met_f.exists()):
            continue
        try:
            rep = json.loads(rep_f.read_text(encoding="utf-8"))
            met = json.loads(met_f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(met, dict) and "metrics" in met:
            met = met["metrics"]
        total += 1
        if not rep.get("complete"):
            continue
        complete += 1
        src = met.get("sources_total")
        cleared = met.get("cleared_count")
        if src is None or cleared is None:
            continue
        if int(cleared) < int(src):
            bad.append({"run": str(run.relative_to(ROOT)), "sources": src,
                        "cleared": cleared,
                        "verifier": bool(rep.get("verifier_all_ok")),
                        "basis": met.get("status_summary")})
            shortfall[int(src) - int(cleared)] += 1
        if args.limit and len(bad) >= args.limit:
            break

    print(f"runs with run_report+metrics: {total}")
    print(f"runs with complete=True:      {complete}")
    print(f"complete but cleared < sources_total: {len(bad)}")
    if shortfall:
        print("  shortfall distribution:", dict(shortfall))
    for row in bad[:20]:
        print(f"  {row['run']:44} sources={row['sources']} cleared={row['cleared']} "
              f"verifier_ok={row['verifier']}")
        if row["basis"]:
            print(f"      status_summary: {json.dumps(row['basis'], ensure_ascii=False)[:200]}")
    if not bad:
        print("  => every completed run cleared all sources it was given")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
