#!/usr/bin/env python
"""Independent second Q3 differential (mock spec supplied by q3-porter).

Motivation: the t6 harness (`verification/differential_check.py`) is not written by
me, so a second, independently implemented mock that reproduces the same engines
strengthens the equivalence claim -- and q3-porter's spec came with concrete
expected numbers (actions=110 / virtual=550.0 / cleared=12) I can test against.

Deliberate differences from q3-porter's own run (per their advice):
  * each engine runs in its OWN process (their run was same-process);
  * for the error-path stub I compare only (error type, actions, virtual) --
    the exception text embeds the engine's own file path and therefore cannot be
    equal across the source tree and the absorbed copy.

The mock is a differential instrument only; it says nothing about Q3 business
correctness vs the official problem (same caveat as MANIFEST §7b).

Run:  python verification/oracle_q3_mock_diff.py
Exit: 0 = both engines identical on every compared field, 1 = divergence
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
SRC = Path(r"D:\CUMCM2026\src\Q3_Q4_V3")

MOCK = r'''
import math
import numpy as np

class MockClient:
    """Deterministic world: 12 sources on a 600 m ring, channels 13..20 empty."""
    def __init__(self):
        self.S = {c: np.array([600.0 * math.cos(math.radians(30 * (c - 1))),
                               600.0 * math.sin(math.radians(30 * (c - 1)))])
                  for c in range(1, 13)}
        self.position = np.array([0.0, 0.0])
        self.virtual = 0.0
        self.rows = []
        self.channel = None

    def act(self, path, position=None, channel=None):
        if path == "/measure":
            self.rows.append({"path": "/measure", "pos": np.asarray(position).tolist(), "ch": channel})
            self.virtual += 5.0
            self.position = np.asarray(position, dtype=float)
            self.channel = channel
            if channel not in self.S:
                return {"measure_result": "no_signal", "svd_deg": None}
            d = float(np.linalg.norm(self.position - self.S[channel]))
            if d <= 5.0:
                return {"measure_result": "near", "svd_deg": None}
            if d <= 1000.0:
                dx, dy = self.S[channel] - self.position
                return {"measure_result": "direction",
                        "svd_deg": math.degrees(math.atan2(dy, dx)) % 360}
            return {"measure_result": "no_signal", "svd_deg": None}
        if path == "/clear":
            self.rows.append({"path": "/clear", "pos": np.asarray(position).tolist(), "ch": channel})
            self.virtual += 5.0
            self.channel = channel
            if channel in self.S and float(np.linalg.norm(np.asarray(position) - self.S[channel])) <= 20.0:
                return {"clear_result": "success"}
            return {"clear_result": "no_target_in_range"}
        raise RuntimeError("unexpected " + str(path))


class BlindStub:
    """STUB-A: never reports signal, never clears -> exercises the engine's own
    counting-contract check instead of the happy path."""
    def __init__(self):
        self.position = np.array([0.0, 0.0]); self.virtual = 0.0; self.rows = []; self.channel = None
    def act(self, path, position=None, channel=None):
        if path not in ("/measure", "/clear"):
            raise RuntimeError("unexpected " + str(path))
        self.rows.append({"path": path, "pos": np.asarray(position).tolist(), "ch": channel})
        self.virtual += 5.0
        self.position = np.asarray(position, dtype=float); self.channel = channel
        return ({"measure_result": "no_signal", "svd_deg": None} if path == "/measure"
                else {"clear_result": "no_target_in_range"})
'''

DRIVER = MOCK + r'''
import json, sys
{imports}
import {modname} as eng
out = dict()
for name, cls in (("mock", MockClient), ("blind", BlindStub)):
    cl = cls()
    try:
        r = eng.solve_optimized_v5(cl)
        payload = {"outcome": "ok",
                   "actions": len(cl.rows), "virtual": round(float(cl.virtual), 9),
                   "cleared_count": r.get("cleared_count"),
                   "cleared_channels": r.get("cleared_channels"),
                   "result_json": json.dumps(r, sort_keys=True, default=str)}
    except Exception as exc:
        payload = {"outcome": type(exc).__name__,
                   "actions": len(cl.rows), "virtual": round(float(cl.virtual), 9)}
    out[name] = payload
print("DIGEST " + json.dumps(out))
'''


def run(side: str, timeout: int = 900):
    if side == "source":
        imports = (f"sys.path.insert(0, r'{SRC / 'code'}')\n"
                   f"sys.path.insert(0, r'{SRC / 'code' / 'src'}')")
        modname = "q3_optimizer_v5"
    else:
        imports = f"sys.path.insert(0, r'{TARGET}')"
        modname = "absorbed.q3_v5.q3_optimizer_v5"
    code = DRIVER.replace("{imports}", imports).replace("{modname}", modname)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0:
        return None, (p.stderr or "").strip().splitlines()[-4:]
    for line in reversed((p.stdout or "").strip().splitlines()):
        if line.startswith("DIGEST "):
            return json.loads(line[7:]), None
    return None, ["no DIGEST line"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    src, err_s = run("source")
    por, err_p = run("absorbed")
    if src is None:
        print("SOURCE SIDE FAILED:", err_s); return 1
    if por is None:
        print("ABSORBED SIDE FAILED:", err_p); return 1
    print("q3-porter's reported reference: mock outcome=ok actions=110 virtual=550.0 cleared=12")
    bad = 0
    for case in ("mock", "blind"):
        s, a = src[case], por[case]
        print(f"\n--- case {case} ---")
        print(f"  source   : {json.dumps({k: v for k, v in s.items() if k != 'result_json'}, ensure_ascii=False)}")
        print(f"  absorbed : {json.dumps({k: v for k, v in a.items() if k != 'result_json'}, ensure_ascii=False)}")
        checks = {"outcome": s.get("outcome") == a.get("outcome"),
                  "actions": s.get("actions") == a.get("actions"),
                  "virtual": s.get("virtual") == a.get("virtual")}
        if case == "mock":
            checks["result_json_equal"] = s.get("result_json") == a.get("result_json")
            checks["cleared_count"] = s.get("cleared_count") == a.get("cleared_count")
            checks["cleared_channels"] = s.get("cleared_channels") == a.get("cleared_channels")
            dk = []
            if not checks["result_json_equal"]:
                ds, da = json.loads(s["result_json"]), json.loads(a["result_json"])
                dk = sorted({k for k in set(ds) | set(da) if ds.get(k) != da.get(k)})
            checks["differing_top_level_keys"] = dk
            print(f"  matches q3-porter reference: actions==110 {s.get('actions') == 110}, "
                  f"virtual==550.0 {s.get('virtual') == 550.0}, cleared==12 {s.get('cleared_count') == 12}")
        else:
            # error text embeds each engine's own path -> compare type + counters only
            checks["error_type_only (path differs by design)"] = True
        ok = all(v is True or (isinstance(v, list) and not v) for v in checks.values())
        print(f"  checks: {json.dumps({k: v for k, v in checks.items()}, ensure_ascii=False)}")
        print(f"  verdict: {'PASS' if ok else 'DIFF'}")
        bad += 0 if ok else 1
    print(f"\n{'ALL IDENTICAL' if not bad else 'DIVERGENCE'}: {bad} failing case(s)")
    if args.json:
        print(json.dumps({"source": src, "absorbed": por}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
