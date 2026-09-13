"""Captain cross-check of the t28 pre-registered adoption verdict.

`tools/ratio_table.py --root <arm>` aggregates **every** run under that root, so
it cannot answer the t28 question: the virgin verdict is about the five seeds
900001-900005 only.  This tool recomputes the two ratio columns **per run** for
exactly those seeds, on both arms, and evaluates the pre-registered criteria
verbatim.

Criteria (from the t28 contract, written before the A/B was run):

  C1  own-denominator ratio improves in every Q3 cell
  C2  oracle-denominator ratio improves in every Q3 cell
  C3  both arms 5/5 complete AND verifier_all_ok
  C4  Q4 cells bit-for-bit identical between arms (order_plan is Q3-only)
  G   guardrail: mean s/源 regression <= +15 in every Q3 cell

Usage:  python -X utf8 tools/order_adopt_check.py [--seeds 900001,...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import load, mst_len  # noqa: E402

SPEED = 5.0
ARMS = ("production", "prod+order")
CELLS = [("Q3/10", "Q3", 10), ("Q3/13", "Q3", 13), ("Q3/16", "Q3", 16),
         ("Q4/10", "Q4", 10), ("Q4/13", "Q4", 13), ("Q4/16", "Q4", 16)]
GUARDRAIL = 15.0


def measure(run_dir: Path, n: int):
    if not (run_dir / "api_log.jsonl").exists():
        return None
    stops, svc, move = load(run_dir)
    svc_s = sum(svc.values())
    actual = move + svc_s
    floor = mst_len([(0.0, 0.0)] + stops) / SPEED + svc_s
    oratio = None
    try:
        from oracle_floor import sources  # local import: optional
        src = sources(run_dir)
        if src:
            oratio = actual / (mst_len([(0.0, 0.0)] + src) / SPEED + svc_s)
    except Exception:
        oratio = None
    rep = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    return {
        "actual": actual, "floor": floor, "ratio": actual / floor if floor else None,
        "ratio_oracle": oratio, "tps": actual / n,
        "T_move": rep.get("T_move"), "T_total": rep.get("T_total"),
        "complete": bool(rep.get("complete")),
        "verifier": bool(rep.get("verifier_all_ok")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="900001,900002,900003,900004,900005")
    ap.add_argument("--json", default="tuning_runs/order_adopt_check.json")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    data = {}
    for arm in ARMS:
        for cell, mode, n in CELLS:
            for seed in seeds:
                d = ROOT / "tuning_runs" / "ab_probe" / arm / f"{mode}_{n}_{seed}"
                m = measure(d, n)
                if m:
                    data.setdefault((cell, arm), []).append((seed, m))

    out = {"seeds": seeds, "arms": {}, "criteria": {}}
    print(f"{'cell':7}{'arm':12}{'runs':>5}{'actual/s':>10}{'floor/s':>9}"
          f"{'ratio':>8}{'oracle':>8}{'allgreen':>10}")
    for cell, _m, _n in CELLS:
        for arm in ARMS:
            rows = data.get((cell, arm), [])
            if not rows:
                print(f"{cell:7}{arm:12}{'--':>5}  (no runs)")
                continue
            mets = [m for _s, m in rows]
            rm = [m["ratio"] for m in mets if m["ratio"]]
            ro = [m["ratio_oracle"] for m in mets if m["ratio_oracle"]]
            entry = {
                "runs": len(mets),
                "actual_per_source": sum(m["tps"] for m in mets) / len(mets),
                "floor_per_source": sum(m["floor"] / _n for m in mets) / len(mets),
                "ratio_mean": sum(rm) / len(rm) if rm else None,
                "ratio_oracle_mean": sum(ro) / len(ro) if ro else None,
                "all_green": all(m["complete"] and m["verifier"] for m in mets),
                "per_seed_tps": {s: m["tps"] for s, m in sorted(rows)},
            }
            out["arms"].setdefault(cell, {})[arm] = entry
            print(f"{cell:7}{arm:12}{len(mets):>5}{entry['actual_per_source']:>10.2f}"
                  f"{entry['floor_per_source']:>9.2f}"
                  f"{entry['ratio_mean']:>8.4f}"
                  f"{(entry['ratio_oracle_mean'] or float('nan')):>8.4f}"
                  f"{str(entry['all_green']):>10}")

    print()
    for cell, _m, _n in CELLS:
        arms = out["arms"].get(cell, {})
        if len(arms) < 2:
            continue
        b, o = arms["production"], arms["prod+order"]
        d_own = o["ratio_mean"] - b["ratio_mean"]
        d_or = ((o["ratio_oracle_mean"] - b["ratio_oracle_mean"])
                if o["ratio_oracle_mean"] and b["ratio_oracle_mean"] else None)
        d_tps = o["actual_per_source"] - b["actual_per_source"]
        worse = sum(1 for s in o["per_seed_tps"]
                    if o["per_seed_tps"][s] > b["per_seed_tps"][s])
        ident = all(abs(o["per_seed_tps"][s] - b["per_seed_tps"][s]) < 1e-9
                    for s in o["per_seed_tps"])
        out["criteria"][cell] = {
            "delta_ratio_own": d_own, "delta_ratio_oracle": d_or,
            "delta_tps": d_tps, "worse_seeds": worse, "identical": ident,
            "green": b["all_green"] and o["all_green"],
        }
        print(f"{cell}: Δratio(own) {d_own:+.4f}  Δratio(oracle) "
              f"{('n/a' if d_or is None else f'{d_or:+.4f}')}  Δ s/源 {d_tps:+.3f}  "
              f"worse {worse}/{len(o['per_seed_tps'])}  bitwise-same {ident}  "
              f"all-green {b['all_green'] and o['all_green']}")

    q3 = [out["criteria"][c] for c in ("Q3/10", "Q3/13", "Q3/16") if c in out["criteria"]]
    c1 = all(x["delta_ratio_own"] > 0 for x in q3)
    c2 = all(x["delta_ratio_oracle"] is not None and x["delta_ratio_oracle"] > 0
             for x in q3)
    c3 = all(x["green"] for x in out["criteria"].values())
    c4 = all(x["identical"] for c, x in out["criteria"].items() if c.startswith("Q4"))
    g = all(x["delta_tps"] <= GUARDRAIL for x in q3)
    verdict = "PASS" if (c1 and c2 and c3 and c4 and g) else "FAIL"
    out["verdict"] = {"C1_own_ratio": c1, "C2_oracle_ratio": c2,
                      "C3_all_green": c3, "C4_q4_identical": c4,
                      "G_guardrail": g, "verdict": verdict}
    print(f"\nC1 own-ratio all Q3 >0: {c1}\nC2 oracle-ratio all Q3 >0: {c2}\n"
          f"C3 both arms 5/5 green: {c3}\nC4 Q4 bitwise identical: {c4}\n"
          f"G  mean s/源 regression <= +{GUARDRAIL:g}: {g}\n=> {verdict}")
    dest = ROOT / args.json
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
