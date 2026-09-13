"""Q4 tail cost: how much movement goes into clear attempts (esp. failed ones)?

For each run, walk ``api_log.jsonl`` and attribute every action's ``dt.move`` to
the action's kind and, for clears, to its result:

  * move before a successful clear   -> "clear_success_move_s"
  * move before a failed clear       -> "clear_fail_move_s"   (blind search legs)
  * move before a measure            -> "measure_move_s"      (incl. certificate)
  * move before a channel switch     -> "switch_move_s"       (usually 0)

Also reports late-episode share: movement charged after the last successful clear
minus the final approach (i.e. what happens once everything is found).

Usage:
  python -X utf8 tools/q4_tail_cost.py <run_dir_or_glob> [...]
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(run_dir: Path) -> dict:
    buckets = {
        "clear_success_move_s": 0.0,
        "clear_fail_move_s": 0.0,
        "measure_move_s": 0.0,
        "switch_move_s": 0.0,
        "other_move_s": 0.0,
    }
    n_clear_fail = n_clear_success = n_measure = 0
    move_total = 0.0
    first_success_t = None
    move_after_first_success = 0.0
    t_now = 0.0
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = rec.get("dt") or {}
            mv = float(dt.get("move") or 0.0)
            move_total += mv
            t_now = float((rec.get("response") or {}).get("virtual_time_s") or t_now)
            ep = rec.get("endpoint")
            if ep == "/clear":
                res = (rec.get("response") or {}).get("clear_result")
                if res == "success":
                    buckets["clear_success_move_s"] += mv
                    n_clear_success += 1
                    if first_success_t is None:
                        first_success_t = t_now
                else:
                    buckets["clear_fail_move_s"] += mv
                    n_clear_fail += 1
            elif ep == "/measure":
                buckets["measure_move_s"] += mv
                n_measure += 1
            elif ep == "/switch_channel":
                buckets["switch_move_s"] += mv
            else:
                buckets["other_move_s"] += mv
            if first_success_t is not None and t_now > first_success_t:
                move_after_first_success += mv

    return {
        "run": str(run_dir.relative_to(ROOT)),
        "move_total_s": round(move_total, 1),
        "clear_success_move_s": round(buckets["clear_success_move_s"], 1),
        "clear_fail_move_s": round(buckets["clear_fail_move_s"], 1),
        "measure_move_s": round(buckets["measure_move_s"], 1),
        "other_move_s": round(buckets["other_move_s"], 1),
        "n_clear_success": n_clear_success,
        "n_clear_fail": n_clear_fail,
        "n_measure": n_measure,
        # NOTE (t13 audit): this is movement charged after the FIRST successful
        # clear, not after the last one.  The old field name
        # ``move_after_last_success_s`` was wrong and is gone.
        "move_after_first_success_s": round(move_after_first_success, 1),
    }


def main(argv: list[str]) -> int:
    dirs: list[Path] = []
    for raw in argv[1:]:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / raw
        if any(ch in raw for ch in "*?["):
            dirs.extend(Path(m) for m in sorted(glob.glob(str(p))))
        else:
            dirs.append(p)
    out = []
    print("{:<44}{:>9}{:>10}{:>10}{:>9}{:>12}{:>7}{:>6}".format(
        "run", "move_s", "clrOK_s", "clrFAIL_s", "meas_s", "after1stOK", "n_fail", "n_meas"))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        rec = audit(d)
        out.append(rec)
        print("{run:<44}{move_total_s:>9.1f}{clear_success_move_s:>10.1f}{clear_fail_move_s:>10.1f}"
              "{measure_move_s:>9.1f}{move_after_first_success_s:>12.1f}{n_clear_fail:>7}{n_measure:>6}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "q4_tail_cost.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
