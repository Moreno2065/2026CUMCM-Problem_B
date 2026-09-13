#!/usr/bin/env python
"""Independent recomputation of the captain's verification claims (t5 input).

Every claim is recomputed here from scratch; nothing is taken on trust. Checks
that depend on import-time state run in SUBPROCESSES, because the vendored
source used to monkeypatch socket at import time and that hijack is
process-global and permanent.

Run:  python verification/oracle_captain_claims.py
Exit: 0 = every claim reproduced, 1 = at least one mismatch (report as blocker)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
SRC = Path(r"D:\CUMCM2026\src\Q3_Q4_V3")
V4_WS = SRC / "workstreams" / "q4_deep_optimization_v4_20260912"
V3_WS = SRC / "workstreams" / "q4_uniform_optimization_v3_20260912"
BASELINE = HERE / "production_hashes_before.json"
PROD_FILES = ["production.py", "run.py", "runtime.py", "compare.py", "recommended.py"]

ROWS: list[tuple[str, bool, str]] = []


def rec(claim: str, ok: bool, detail: str) -> None:
    ROWS.append((claim, ok, detail))
    print(f"[{'OK  ' if ok else 'DIFF'}] {claim}: {detail}", flush=True)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run_py(code: str, timeout: int = 300) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------- claim 1 + 5
def claim1_lock() -> None:
    v4 = json.loads((V4_WS / "results" / "selection_lock.json").read_text(encoding="utf-8"))
    v3 = json.loads((V3_WS / "results" / "selection_lock.json").read_text(encoding="utf-8"))
    ab = TARGET / "absorbed" / "q4_v4" / "results" / "selection_lock.json"
    if not ab.is_file():
        rec("1 shipped lock", False, f"missing {ab}")
        return
    rec("1 shipped lock == v4 lock (bytes)", sha(ab) == sha(V4_WS / "results" / "selection_lock.json"),
        f"{ab.stat().st_size}B vs v4 {  (V4_WS/'results'/'selection_lock.json').stat().st_size}B")
    rec("1 shipped lock != v3 lock", sha(ab) != sha(V3_WS / "results" / "selection_lock.json"),
        f"v3 lock {  (V3_WS/'results'/'selection_lock.json').stat().st_size}B")
    code = (
        "import json,sys\n"
        f"sys.path.insert(0, {str(TARGET)!r})\n"
        "from absorbed.q4_v4 import locked\n"
        f"L=json.load(open({str(ab)!r},encoding='utf-8'))\n"
        "print(json.dumps({'version':locked.VERSION,'name':locked.SELECTED_NAME,"
        "'n':len(locked.LOCKED_PARAMETERS),'match':locked.LOCKED_PARAMETERS==L['selected_parameters']}))\n"
    )
    rc, out, err = run_py(code)
    if rc != 0:
        rec("1 LOCKED_PARAMETERS replay", False, f"rc={rc} {(err or '').strip()[-160:]}")
        return
    d = json.loads([l for l in out.strip().splitlines() if l.startswith("{")][-1])
    rec("1 LOCKED_PARAMETERS == selected_parameters", bool(d["match"]),
        f"version={d['version']} name={d['name']} n={d['n']}")
    rec("1 n == 36", d["n"] == 36, f"n={d['n']}")
    rec("1 version == v4 lock version", d["version"] == v4.get("version"), f"{d['version']}")
    rec("1 name == v4 selected_name", d["name"] == v4.get("selected_name"), f"{d['name']}")


# -------------------------------------------------------------------- claim 2
def claim2_socket() -> None:
    pre = ("import socket,urllib.request,json\n"
           "ORIG=(socket.socket,socket.create_connection,urllib.request.OpenerDirector.open)\n")
    post = ("print(json.dumps({'socket':socket.socket is ORIG[0],'conn':socket.create_connection is ORIG[1],"
            "'opener':urllib.request.OpenerDirector.open is ORIG[2],"
            "'names':[socket.socket.__name__, urllib.request.OpenerDirector.open.__name__]}))\n")
    cases = {
        "q4 engine first": pre + f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
                           "from absorbed.q4_v4 import strategy_v4, locked\n" + post,
        "q4 engine, numba before": pre + "import numba\n" + f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
                                   "from absorbed.q4_v4 import strategy_v4, locked\n" + post,
        "q3 engine first": pre + f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
                           "from absorbed.q3_v5 import q3_optimizer_v5\n" + post,
        "q3 then q4": pre + f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
                      "from absorbed.q3_v5 import q3_optimizer_v5\n"
                      "from absorbed.q4_v4 import strategy_v4\n" + post,
        "q4 then q3": pre + f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
                      "from absorbed.q4_v4 import strategy_v4\n"
                      "from absorbed.q3_v5 import q3_optimizer_v5\n" + post,
    }
    for label, code in cases.items():
        rc, out, err = run_py(code)
        if rc != 0:
            rec(f"2 socket [{label}]", False, f"rc={rc} {(err or '').strip()[-160:]}")
            continue
        d = json.loads([l for l in out.strip().splitlines() if l.startswith("{")][-1])
        ok = d["socket"] and d["conn"] and d["opener"]
        rec(f"2 socket [{label}]", ok, f"native={d['socket']}/{d['conn']}/{d['opener']} names={d['names']}")


# ------------------------------------------------------------------ claims 3,4
def signature_of(label: str, code: str) -> list[str] | None:
    rc, out, err = run_py(code)
    if rc != 0:
        rec(f"{label} signature", False, f"rc={rc} {(err or '').strip()[-160:]}")
        return None
    for line in out.strip().splitlines():
        if line.startswith("SIG "):
            return line[4:].strip().strip("()").split(", ")
    rec(f"{label} signature", False, "no SIG line produced")
    return None


def claim34_signatures() -> None:
    absorbed_q4 = (
        f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
        "import inspect\nfrom absorbed.q4_v4 import strategy_v4\n"
        "print('SIG '+str(inspect.signature(strategy_v4.solve)))\n"
    )
    source_q4 = (
        "import sys, importlib.util\n"
        f"V2=r'{V3_WS}' if False else r'{V4_WS.parent}/q4_local_optimization_v2_20260912'\n"
        f"V3v=r'{V4_WS.parent}/q4_uniform_optimization_v3_20260912'\n"
        f"V4=r'{V4_WS}'\n"
        "import numba\n"
        "spec=importlib.util.spec_from_file_location('coverage', V2+'/coverage.py')\n"
        "m=importlib.util.module_from_spec(spec); sys.modules['coverage']=m; spec.loader.exec_module(m)\n"
        f"sys.path.insert(0, r'{V4_WS.parent}/q4_local_optimization_20260912')\n"
        "for p in (V2,V3v,V4): sys.path.insert(0,p)\n"
        f"sys.path.insert(0, r'{SRC}/code/src')\n"
        "import inspect, strategy_v4\n"
        "print('SIG '+str(inspect.signature(strategy_v4.solve)))\n"
    )
    a = signature_of("3 absorbed q4 solve", absorbed_q4)
    b = signature_of("3 source q4 solve", source_q4)
    if a and b:
        diff = [x for x in a if x not in b] + [x for x in b if x not in a]
        rec("3 signatures identical", a == b, f"{len(a)} params absorbed / {len(b)} source; diff={diff[:6]}")
        rec("3 param count == 36", len(a) - 1 == 36, f"{len(a)} sig entries incl. client -> {len(a)-1} params")

    absorbed_q3 = (
        f"import sys;sys.path.insert(0,{str(TARGET)!r})\n"
        "import inspect\nfrom absorbed.q3_v5 import q3_optimizer_v5 as m\n"
        "print('SIG '+str(inspect.signature(m.solve_optimized_v5)))\n"
        "print('VER '+str(getattr(m,'VERSION','<none>')))\n"
        "print('NUM '+str(len(getattr(m,'SELECTED_PARAMETERS',{}))))\n"
    )
    rc, out, err = run_py(absorbed_q3)
    if rc != 0:
        rec("4 q3 import", False, f"rc={rc} {(err or '').strip()[-160:]}")
    else:
        rec("4 q3 import", True, "absorbed.q3_v5.q3_optimizer_v5 imported")
        for line in out.strip().splitlines():
            if line.startswith("SIG "):
                rec("4 q3 solve_optimized_v5 signature", True, line[4:])
            if line.startswith("VER "):
                rec("4 q3 VERSION", line[4:].startswith("q3_joint_search_clear_route_v5"), line[4:])
            if line.startswith("NUM "):
                rec("4 q3 SELECTED_PARAMETERS count", line[4:] == "21", f"n={line[4:]}")

    # static: zero bare top-level imports / zero sys.path usage in q3_v5
    external = set(sys.stdlib_module_names) | {"numpy", "scipy", "numba", "llvmlite", "shapely"}
    bare, spath = [], []
    for f in sorted((TARGET / "absorbed" / "q3_v5").rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                top = n.module.split(".")[0]
                if top not in external:
                    bare.append(f"{f.name}:{n.lineno}->{n.module}")
            elif isinstance(n, ast.Import):
                for al in n.names:
                    top = al.name.split(".")[0]
                    if top not in external:
                        bare.append(f"{f.name}:{n.lineno}->{al.name}")
        # sys.path usage must be real code, not a mention inside a comment/docstring
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                node, parts = n, []
                while isinstance(node, ast.Attribute):
                    parts.append(node.attr)
                    node = node.value
                if isinstance(node, ast.Name):
                    parts.append(node.id)
                    chain = ".".join(reversed(parts))
                    if chain.startswith("sys.path"):
                        spath.append(f"{f.name}:{n.lineno}->{chain}")
    rec("4 q3 zero bare top-level imports", not bare, f"non-external bare imports found={bare[:6]}")
    rec("4 q3 zero sys.path usage (AST, not text)", not spath, f"real sys.path accesses found={spath[:6]}")


# -------------------------------------------------------------------- claim 5
def claim5_production() -> None:
    if not BASELINE.is_file():
        rec("5 production baseline", False, "baseline file missing -> UNPROVEN")
        return
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    bad = []
    for name in PROD_FILES:
        ent = base["named_production_files"].get(name, {})
        p = TARGET / name
        if not p.is_file() or sha(p) != ent.get("sha256"):
            bad.append(name)
    rec("5 five named production files match", not bad, f"mismatch={bad} (baseline captured {base.get('captured_at_utc')})")
    changed = []
    for name, ent in base.get("all_toplevel_py", {}).items():
        p = TARGET / name
        if not p.is_file() or sha(p) != ent.get("sha256"):
            changed.append(name)
    for rel, h in base.get("baseline_tree", {}).get("files", {}).items():
        p = TARGET / rel
        if not p.is_file() or sha(p) != h:
            changed.append(rel)
    rec("5 top-level + baseline tree unchanged", not changed, f"changed={changed[:8]} (n={len(changed)})")
    rec("5 ALL_PRODUCTION_UNCHANGED", not bad and not changed,
        f"captured_at_utc={base.get('captured_at_utc')}")


# -------------------------------------------------------------------- claim 6
def claim6_pycache() -> None:
    hits = [p.name for p in (TARGET / "absorbed" / "q4_v4" / "__pycache__").glob("*.nb*")] \
        if (TARGET / "absorbed" / "q4_v4" / "__pycache__").is_dir() else []
    rec("6 numba njit artifacts present (circumstantial)", bool(hits),
        f"{len(hits)} file(s): {hits[:4]}" if hits else "none found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    print(f"=== independent recomputation of captain claims | {TARGET} ===")
    for fn in (claim1_lock, claim2_socket, claim34_signatures, claim5_production, claim6_pycache):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            rec(fn.__name__, False, f"checker raised {exc!r}")
    diffs = [r for r in ROWS if not r[1]]
    print(f"\n--- {len(ROWS) - len(diffs)}/{len(ROWS)} claims reproduced, {len(diffs)} DIFF "
          f"({time.perf_counter() - t0:.1f}s) ---")
    if diffs:
        print("DIFFERENCES (report to captain as blocker-grade):")
        for claim, _ok, detail in diffs:
            print(f"  - {claim}: {detail}")
    if args.json:
        print(json.dumps([{"claim": c, "ok": o, "detail": d} for c, o, d in ROWS], indent=2))
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
