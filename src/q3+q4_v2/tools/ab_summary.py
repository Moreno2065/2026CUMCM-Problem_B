"""Summarise an ab_probe result JSON: per-variant group means (s/source and move s).

Handles the two shapes seen in this repo:
  * ``{variant: {"rows": [ {mode, n, seed, t_per_source, T_move, complete, verifier_all_ok}, ...]}}``
  * ``{"rows": [...], "groups": {variant: {group: {...}}}}``
  * a bare list of row dicts.

Usage:
  python -X utf8 tools/ab_summary.py <ab_json> [...] [--move]
Read-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rows_by_variant(data) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if isinstance(data, dict) and "rows" in data and isinstance(data["rows"], list):
        out["_rows"] = data["rows"]
    elif isinstance(data, list):
        out["_rows"] = data
    elif isinstance(data, dict):
        for variant, payload in data.items():
            if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                out[variant] = payload["rows"]
            elif isinstance(payload, list):
                out[variant] = payload
    return out


def summarise(path: Path, show_move: bool) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    per_variant = _rows_by_variant(data)
    if "_rows" in per_variant:  # rows carry their own variant label
        rows = per_variant.pop("_rows")
        for r in rows:
            per_variant.setdefault(r.get("variant", "?"), []).append(r)

    agg: dict[str, dict[str, dict]] = {}
    for variant, rows in per_variant.items():
        for r in rows:
            key = f"{r.get('mode')}/{r.get('n')}"
            cell = agg.setdefault(variant, {}).setdefault(key, {"t": [], "mv": [], "ok": True, "n": 0})
            v = r.get("t_per_source") or r.get("T_per_source_s") or r.get("average_time_per_source_s")
            if v is not None:
                cell["t"].append(float(v))
            mv = r.get("T_move")
            if mv is not None:
                cell["mv"].append(float(mv))
            cell["ok"] = cell["ok"] and bool(r.get("complete")) and bool(r.get("verifier_all_ok"))
            cell["n"] += 1

    variants = sorted(agg)
    keys = sorted({k for v in variants for k in agg[v]})
    base = "production" if "production" in agg else (variants[0] if variants else None)
    print(f"== {path.relative_to(ROOT)}  variants={variants}")
    print("group".ljust(9) + "".join(v.ljust(20) for v in variants))
    for key in keys:
        line = key.ljust(9)
        b = agg.get(base, {}).get(key)
        b_t = sum(b["t"]) / len(b["t"]) if b and b["t"] else None
        b_mv = sum(b["mv"]) / len(b["mv"]) if b and b["mv"] else None
        for v in variants:
            g = agg[v].get(key)
            if not g or not g["t"]:
                line += "-".ljust(20)
                continue
            t = sum(g["t"]) / len(g["t"])
            cell = f"{t:.2f}"
            if b_t is not None and v != base:
                cell += f" ({t - b_t:+.2f})"
            if show_move and g["mv"]:
                mv = sum(g["mv"]) / len(g["mv"])
                cell += f" mv{mv:.0f}"
                if b_mv is not None and v != base:
                    cell += f"({mv - b_mv:+.0f})"
            if not g["ok"]:
                cell += " !"
            line += cell.ljust(20)
        print(line)
    print()


def main(argv: list[str]) -> int:
    show_move = "--move" in argv
    files = [a for a in argv[1:] if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    for raw in files:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / raw
        summarise(p, show_move)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
