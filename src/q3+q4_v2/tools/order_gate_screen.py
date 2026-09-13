"""Screen: can a *gate* beat ungated ``prod+order`` on already-consumed seeds?

Read-only analysis of the existing ``ab_order_*.json`` A/B files.  No runs, no
runtime changes, no new seeds.

Motivation
----------
``prod+order`` (Q3-only global stop-order planning, ``order_plan=True``) has
three independent evidence sets.  Under the *ratio* objective it improves all
three Q3 cells on the 800001-800005 holdout, but its mean ``s/源`` regresses at
Q3/13 (+13.2).  Before spending the last virgin seed set (900001-900005) on a
verdict, this screen asks whether a **gate** (activate ``order_plan`` only for
episodes whose baseline plan is "winding") dominates the ungated variant on the
data we have already seen.

Gate quantity
-------------
The gate must be computable online.  The planner already computes both the
planned (reordered) and reference (production-order) plan cost at every replan
(t23's machinery).  The *baseline realised* movement ``T_move`` of the
production run is used here as a **proxy** for the reference plan cost that an
online gate would read at the first decision step.  It is a proxy, not the real
observable: the screen is a hypothesis generator, and any gated variant must be
re-measured by an actual run before adoption.

Usage
-----
    python -X utf8 tools/order_gate_screen.py [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATASETS = [
    ("dev", "tuning_runs/ab_order_dev.json"),
    ("holdout", "tuning_runs/ab_order_holdout.json"),
    ("virgin700", "tuning_runs/ab_order_virgin.json"),
    ("virgin800", "tuning_runs/ab_order_ratio_virgin.json"),
    ("virgin900", "tuning_runs/ab_order_adopt_virgin.json"),
]

THRESHOLDS = [2800.0, 3000.0, 3200.0, 3400.0, 3600.0,
              3800.0, 4000.0, 4200.0, 4400.0, 4600.0]


def load_pairs(path: Path):
    """-> {(mode, n, seed): {"base": row, "ord": row}}"""
    data = json.loads(path.read_text(encoding="utf-8"))
    base = data.get("production", {}).get("rows", [])
    order = data.get("prod+order", {}).get("rows", [])
    pairs = {}
    for row in base:
        key = (row["mode"], int(row["n"]), int(row["seed"]))
        pairs.setdefault(key, {})["base"] = row
    for row in order:
        key = (row["mode"], int(row["n"]), int(row["seed"]))
        pairs.setdefault(key, {})["ord"] = row
    return {k: v for k, v in pairs.items() if "base" in v and "ord" in v}, data


def cell_of(key):
    mode, n, _ = key
    return f"{mode}/{n}"


def screen():
    out = {"datasets": {}, "thresholds": THRESHOLDS}
    for name, rel in DATASETS:
        path = ROOT / rel
        if not path.exists():
            continue
        pairs, raw = load_pairs(path)
        rows = []
        for key, pr in sorted(pairs.items()):
            mode, n, seed = key
            b, o = pr["base"], pr["ord"]
            rows.append({
                "mode": mode, "n": n, "seed": seed,
                "base_tps": b["t_per_source"], "ord_tps": o["t_per_source"],
                "delta": o["t_per_source"] - b["t_per_source"],
                "base_move_s": b.get("T_move", 0.0),
                "ord_move_s": o.get("T_move", 0.0),
                "base_meas_s": b.get("T_measure", 0.0),
                "ord_meas_s": o.get("T_measure", 0.0),
                "base_switch_s": b.get("T_switch", 0.0),
                "ord_switch_s": o.get("T_switch", 0.0),
                "base_clear_s": b.get("T_clear", 0.0),
                "ord_clear_s": o.get("T_clear", 0.0),
                "complete": bool(b["complete"] and o["complete"]),
                "verifier": bool(b["verifier_all_ok"] and o["verifier_all_ok"]),
            })
        cells = {}
        for row in rows:
            cells.setdefault(cell_of((row["mode"], row["n"], row["seed"])),
                             []).append(row)
        ds = {"path": rel, "n_runs": len(rows), "cells": {}}
        for cell, sub in sorted(cells.items()):
            deltas = [r["delta"] for r in sub]
            entry = {
                "runs": len(sub),
                "seeds": sorted(r["seed"] for r in sub),
                "base_mean": statistics.mean(r["base_tps"] for r in sub),
                "ungated_mean_delta": statistics.mean(deltas),
                "ungated_worse": sum(1 for d in deltas if d > 0),
                "ungated_worst": max(deltas),
                "base_move_mean_s": statistics.mean(r["base_move_s"] for r in sub),
                "ledger": {
                    "move": statistics.mean(r["ord_move_s"] - r["base_move_s"]
                                            for r in sub),
                    "meas": statistics.mean(r["ord_meas_s"] - r["base_meas_s"]
                                            for r in sub),
                    "switch": statistics.mean(r["ord_switch_s"] - r["base_switch_s"]
                                              for r in sub),
                    "clear": statistics.mean(r["ord_clear_s"] - r["base_clear_s"]
                                             for r in sub),
                },
                "gated": {},
            }
            for thr in THRESHOLDS:
                picked = [r["delta"] if r["base_move_s"] > thr else 0.0
                          for r in sub]
                entry["gated"][f"{thr:g}"] = {
                    "mean_delta": statistics.mean(picked),
                    "worse": sum(1 for d in picked if d > 0),
                    "activated": sum(1 for r in sub if r["base_move_s"] > thr),
                }
            ds["cells"][cell] = entry
        out["datasets"][name] = ds
    return out


def report(out) -> str:
    lines = []
    for name, ds in out["datasets"].items():
        lines.append(f"== {name} ({ds['path']}, {ds['n_runs']} paired runs) ==")
        for cell, e in ds["cells"].items():
            led = e["ledger"]
            lines.append(
                f"  {cell}: base {e['base_mean']:.2f} | ungated Δ "
                f"{e['ungated_mean_delta']:+.3f} (worse {e['ungated_worse']}/"
                f"{e['runs']}, worst {e['ungated_worst']:+.1f}) | ledger "
                f"move {led['move']:+.1f} meas {led['meas']:+.1f} "
                f"switch {led['switch']:+.1f} clear {led['clear']:+.1f}")
            for thr, g in e["gated"].items():
                lines.append(
                    f"      gate T_move>{thr:>6}: Δ {g['mean_delta']:+8.3f} "
                    f"(worse {g['worse']}/{e['runs']}, "
                    f"aktiv {g['activated']}/{e['runs']})".replace("aktiv", "on"))
    # cross-dataset summary for the ungated and best-threshold variants
    lines.append("== summary (mean Δ per cell across datasets) ==")
    cells = sorted({c for ds in out["datasets"].values() for c in ds["cells"]})
    for cell in cells:
        ung, gate = [], {t: [] for t in out["thresholds"]}
        for ds in out["datasets"].values():
            if cell not in ds["cells"]:
                continue
            e = ds["cells"][cell]
            ung.append(e["ungated_mean_delta"])
            for t, g in e["gated"].items():
                gate[float(t)].append(g["mean_delta"])
        best = min(gate, key=lambda t: statistics.mean(gate[t]))
        lines.append(
            f"  {cell}: ungated {statistics.mean(ung):+.3f} | best gate "
            f"T_move>{best:g} -> {statistics.mean(gate[best]):+.3f} "
            f"(per-dataset " +
            ", ".join(f"{v:+.2f}" for v in gate[best]) + ")")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="tuning_runs/order_gate_screen.json")
    args = ap.parse_args()
    res = screen()
    text = report(res)
    print(text)
    target = ROOT / args.json
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\nwrote {target}")
