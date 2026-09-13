"""Do the baseline run directories mix code revisions?

Several tasks re-run the *same* ``production`` seed directories with whatever
``scheduler.py`` was current at that moment, so the mean s/source in a report can
silently average different code revisions.  ``policy_config.json`` records
``code_sha256`` for runtime.py / rolling.py / production.py /
learned_search/scheduler.py, so the mix is directly measurable.

Usage: python -X utf8 tools/probe_baseline_revisions.py [--root tuning_runs/ab_probe]
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sig(cfg):
    sha = (cfg or {}).get("code_sha256") or {}
    return (str(sha.get("learned_search/scheduler.py"))[:16],
            str(sha.get("production.py"))[:16],
            str(sha.get("rolling.py"))[:16],
            str(sha.get("runtime.py"))[:16])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe")
    ap.add_argument("--arm", default="", help="restrict to one arm directory")
    args = ap.parse_args()

    per_cell = defaultdict(Counter)
    missing = 0
    total = 0
    pattern = (f"{args.root}/{args.arm}/*" if args.arm else f"{args.root}/*/*")
    for d in sorted(glob.glob(str(ROOT / pattern))):
        run = Path(d)
        cfg_f = run / "policy_config.json"
        if not cfg_f.exists():
            missing += 1
            continue
        total += 1
        try:
            cfg = json.loads(cfg_f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        cell = "_".join(run.name.split("_")[:2])
        per_cell[cell][sig(cfg)] += 1

    print(f"runs with policy_config.json: {total}; without: {missing}")
    for cell in sorted(per_cell):
        counts = per_cell[cell]
        if len(counts) == 1:
            only = next(iter(counts))
            print(f"  {cell:10} {sum(counts.values()):4d} runs, "
                  f"single revision scheduler={only[0]} prod={only[1]}")
        else:
            print(f"  {cell:10} {sum(counts.values()):4d} runs, "
                  f"**{len(counts)} REVISIONS MIXED**")
            for s, c in counts.most_common():
                print(f"      {c:4d}x scheduler={s[0]} prod={s[1]} "
                      f"rolling={s[2]} runtime={s[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
