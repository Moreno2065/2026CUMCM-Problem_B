#!/usr/bin/env python
"""Smoke matrix for the absorbed engines vs the existing routes (t5 item g).

Design constraints taken from the captain's brief:
  * every run happens in its OWN python process -- the vendored source used to
    monkeypatch socket at import time, and that hijack is process-global and
    permanent, so legs must never share an interpreter;
  * inside each process the FIRST thing executed asserts the three socket/urllib
    bindings are still native (a wrapper is injected ahead of the entry point);
  * q3 and q4 always run in separate processes;
  * the comparison table (absorbed vs learned vs geometry at the same seed and
    source count) is the evidence of the absorption's value.

This script fills no numbers in advance: every value in the table is measured at
run time. Use --plan to print the exact command matrix without executing it.

Run:
  python verification/oracle_smoke_matrix.py --plan
  python verification/oracle_smoke_matrix.py --seeds 101,102,103 --n 10,16
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
RUNS = TARGET / "runs" / "_verifier_smoke"

WRAPPER = r"""
import sys, socket, urllib.request, runpy, json
ORIG = (socket.socket, socket.create_connection, urllib.request.OpenerDirector.open)
ok = (socket.socket is ORIG[0] and socket.create_connection is ORIG[1]
      and urllib.request.OpenerDirector.open is ORIG[2])
print("PREFLIGHT_SOCKET_NATIVE=%s" % ok, flush=True)
if not ok:
    raise SystemExit(97)
entry = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(entry, run_name="__main__")
"""

# leg name -> (entry file, extra args builder)
def leg_command(leg: str, mode: str, seed: int, n_sources: int, outdir: Path):
    if leg == "recommended":
        # production "recommended" route: uppercase --mode, --output (not --output-dir)
        entry = TARGET / "recommended.py"
        extra = ["--mode", mode.upper(), "--seed", str(seed),
                 "--n-sources", str(n_sources), "--output", str(outdir)]
        return [sys.executable, "-X", "utf8", "-c", WRAPPER, str(entry)] + extra
    # scenario must match the frozen baseline: recommended.py:40 uses random for Q3
    # and mixed for Q4, so the absorbed leg has to use the same world per mode.
    scenario = "random" if mode.lower() == "q3" else "mixed"
    common = ["--sim", "http-synthetic", "--scenario", scenario,
              "--seed", str(seed), "--n-sources", str(n_sources),
              "--output-dir", str(outdir)]
    if leg == "absorbed":
        entry = TARGET / "absorbed" / "run_absorbed.py"
        engine = "q3-v5" if mode == "q3" else "q4-v4"
        extra = ["--mode", mode, "--engine", engine]
    elif leg in ("learned", "geometry"):
        entry = TARGET / "run.py"
        extra = ["--mode", mode, "--policy", leg]
    else:
        raise ValueError(f"unknown leg {leg}")
    return [sys.executable, "-X", "utf8", "-c", WRAPPER, str(entry)] + extra + common


def parse_stdout_json(out: str) -> dict:
    """The runners print a one-line JSON summary; prefer the last such line."""
    for line in reversed((out or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return {}


def parse_artifacts(outdir: Path, wall: float) -> dict:
    """Read run_report.json / metrics.json; tolerate unknown key spellings."""
    res = {"complete": None, "verifier_all_ok": None, "cleared": None,
           "certified_absent": None, "t_per_source_s": None,
           "wall_clock_s": round(wall, 3), "artifacts": []}
    def _find(names):
        hits = [outdir / n for n in names if (outdir / n).is_file()]
        if not hits:
            hits = [p for p in sorted(outdir.rglob("*"))
                    if p.is_file() and p.name in names and "__pycache__" not in p.parts]
        return hits

    report = None
    rp = _find(("run_report.json", "report.json"))
    if rp:
        res["artifacts"].append(str(rp[-1].relative_to(outdir)))
        try:
            report = json.loads(rp[-1].read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            res["parse_error"] = f"{rp[-1].name}: {exc!r}"
    metrics = None
    mp = _find(("metrics.json",))
    if mp:
        res["artifacts"].append(str(mp[-1].relative_to(outdir)))
        try:
            metrics = json.loads(mp[-1].read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            res["parse_error"] = f"metrics.json: {exc!r}"

    src = report or {}
    mets = (metrics if metrics is not None else src.get("metrics", {})) or {}
    for key in ("complete", "verifier_all_ok", "all_verified", "verified_all_ok"):
        if key in src:
            res["verifier_all_ok" if key != "complete" else "complete"] = src[key]
    if res["complete"] is None and "complete" in mets:
        res["complete"] = mets["complete"]
    for key in ("cleared_count", "cleared", "sources_cleared"):
        if key in mets:
            res["cleared"] = mets[key]
            break
    for key in ("certified_absent_count", "certified_absent"):
        if key in mets:
            res["certified_absent"] = mets[key]
            break
    for key in ("t_per_source_s", "average_time_per_source_s"):
        if key in mets and mets[key] is not None:
            res["t_per_source_s"] = mets[key]
            break
    if not res["artifacts"]:
        res["parse_error"] = "no run_report.json / metrics.json found"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="101,102,103")
    ap.add_argument("--n", default="10,16")
    ap.add_argument("--modes", default="q3,q4")
    ap.add_argument("--legs", default="absorbed,learned,geometry")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--plan", action="store_true", help="print commands only")
    ap.add_argument("--out", default=str(HERE / "smoke_matrix_summary.json"))
    args = ap.parse_args()

    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    counts = [int(x) for x in args.n.split(",") if x.strip()]
    modes = [x.strip() for x in args.modes.split(",") if x.strip()]
    legs = [x.strip() for x in args.legs.split(",") if x.strip()]

    plan = []
    for mode in modes:
        for n_sources in counts:
            for seed in seeds:
                for leg in legs:
                    outdir = RUNS / f"{mode}_{leg}_s{seed}_n{n_sources}"
                    plan.append((mode, leg, seed, n_sources, outdir))

    if args.plan:
        print(f"{len(plan)} runs planned (each in its own process):\n")
        for mode, leg, seed, n_sources, outdir in plan:
            cmd = leg_command(leg, mode, seed, n_sources, outdir)
            shown = ["<py>", "-X", "utf8", "-c", "<socket-preflight-wrapper>"] + cmd[5:]
            print("  " + " ".join(shown))
        print("\nno process started (--plan)")
        return 0

    rows = []
    for mode, leg, seed, n_sources, outdir in plan:
        outdir.mkdir(parents=True, exist_ok=True)
        cmd = leg_command(leg, mode, seed, n_sources, outdir)
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, cwd=str(TARGET), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=args.timeout)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            rc, out, err = -9, "", f"timeout after {args.timeout}s"
        wall = time.perf_counter() - t0
        preflight = any("PREFLIGHT_SOCKET_NATIVE=True" in line for line in (out or "").splitlines())
        shown = ["<py>", "-X", "utf8", "-c", "<socket-preflight-wrapper>"] + cmd[5:]
        row = {"mode": mode, "leg": leg, "seed": seed, "n_sources": n_sources,
               "exit_code": rc, "socket_native_at_start": preflight,
               "command": " ".join(shown)}
        row.update(parse_artifacts(outdir, wall))
        sj = parse_stdout_json(out)
        row["stdout_json"] = sj
        aliases = {"complete": ("complete",), "verifier_all_ok": ("verifier_all_ok",),
                   "cleared": ("cleared", "cleared_count"),
                   "certified_absent": ("certified_absent", "certified_absent_count"),
                   "t_per_source_s": ("T_per_source_s", "t_per_source_s")}
        for field, keys in aliases.items():
            if row.get(field) is None:
                for k in keys:
                    if sj.get(k) is not None:
                        row[field] = sj[k]
                        break
        if rc != 0:
            row["stderr_tail"] = " | ".join((err or "").strip().splitlines()[-3:])
        rows.append(row)
        print(f"[{mode}/{leg}] seed={seed} n={n_sources} rc={rc} "
              f"socket_native={preflight} complete={row.get('complete')} "
              f"verifier_all_ok={row.get('verifier_all_ok')} "
              f"T/s={row.get('t_per_source_s')} wall={row['wall_clock_s']}s", flush=True)

    summary = {"captured_at_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(),
        "plan_size": len(plan), "rows": rows}
    Path(args.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== comparison table: T_per_source_s (absorbed vs existing routes) ===")
    print(f"{'mode':5s} {'seed':6s} {'n':4s} " + " ".join(f"{leg:>12s}" for leg in legs))
    seen = {}
    for r in rows:
        seen.setdefault((r["mode"], r["seed"], r["n_sources"]), {})[r["leg"]] = r
    for key in sorted(seen):
        mode, seed, n_sources = key
        cells = []
        for leg in legs:
            v = seen[key].get(leg, {}).get("t_per_source_s")
            cells.append(f"{v:12.3f}" if isinstance(v, (int, float)) else f"{'n/a':>12s}")
        print(f"{mode:5s} {seed:<6d} {n_sources:<4d} " + " ".join(cells))
    bad = [r for r in rows if not r.get("complete") or not r.get("verifier_all_ok")
           or not r.get("socket_native_at_start")]
    print(f"\n{len(rows)} runs; {len(bad)} failing a MUST assertion "
          f"(complete / verifier_all_ok / socket-native-at-start)")
    print(f"summary written to {args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
