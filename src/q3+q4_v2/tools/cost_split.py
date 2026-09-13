"""Split an episode's virtual time into move / measure / switch / clear.

Reads ``api_log.jsonl`` + ``metrics.json`` from one or more run directories and
prints, per run: T_total, the four cost buckets (seconds), the number of measure
and clear calls, and the movement share.  Read-only measurement tool.

Usage:
  python -X utf8 tools/cost_split.py <run_dir_or_glob> [...]
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(run_dir: Path) -> dict:
    mv = ms = sw = cl = 0.0
    n_measure = n_clear = n_switch = 0
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
            mv += float(dt.get("move") or 0.0)
            ms += float(dt.get("measure") or 0.0)
            sw += float(dt.get("switch") or 0.0)
            cl += float(dt.get("clear") or 0.0)
            ep = rec.get("endpoint")
            if ep == "/measure":
                n_measure += 1
            elif ep == "/clear":
                n_clear += 1
            elif ep == "/switch_channel":
                n_switch += 1
    t_total = None
    metrics = run_dir / "metrics.json"
    if metrics.exists():
        try:
            t_total = json.loads(metrics.read_text(encoding="utf-8")).get("T_total_s")
        except json.JSONDecodeError:
            t_total = None
    total = t_total if t_total else (mv + ms + sw + cl)
    return {
        "run": str(run_dir.relative_to(ROOT)),
        "T_total_s": None if t_total is None else round(float(t_total), 1),
        "move_s": round(mv, 1),
        "measure_s": round(ms, 1),
        "switch_s": round(sw, 1),
        "clear_s": round(cl, 1),
        "n_measure": n_measure,
        "n_clear": n_clear,
        "n_switch_endpoint": n_switch,
        "move_share_pct": round(mv / total * 100.0, 1) if total else None,
        "measure_share_pct": round(ms / total * 100.0, 1) if total else None,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
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
    header = ("run", "T_total", "move", "measure", "switch", "clear", "n_meas", "n_clear", "move%")
    print("{:<34}{:>9}{:>9}{:>9}{:>8}{:>8}{:>7}{:>7}{:>7}".format(*header))
    for d in dirs:
        if not (d / "api_log.jsonl").exists():
            continue
        rec = audit(d)
        out.append(rec)
        t = rec["T_total_s"] if rec["T_total_s"] is not None else -1.0
        share = rec["move_share_pct"] if rec["move_share_pct"] is not None else -1.0
        print(
            "{run:<34}{t:>9.1f}{move_s:>9.1f}{measure_s:>9.1f}{switch_s:>8.1f}{clear_s:>8.1f}"
            "{n_measure:>7}{n_clear:>7}{share:>7.1f}".format(t=t, share=share, **rec)
        )
    if out:
        dest = ROOT / "tuning_runs" / "cost_split.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
