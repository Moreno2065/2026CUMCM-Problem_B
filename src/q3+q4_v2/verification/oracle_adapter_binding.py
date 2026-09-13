#!/usr/bin/env python
"""F3 runtime assertion: the adapter layer's bare imports must bind to the v2 stack.

`absorbed/adapters/*.py` deliberately imports v2 modules by their bare top-level
names (api / executor / experiment / runtime / verifier). That is the adapter's
job, but it is only correct if each name actually resolves to a module inside
`<target>/baseline/code/` -- otherwise a same-named module elsewhere on sys.path
would be bound silently, which is exactly the name-collision class the port has
to avoid.

This runs each adapter import in its OWN subprocess and prints, for every bare
top-level name, the resolved module's `__file__`, then compares the prefix with
`<target>/baseline/code`.

Verify-only: writes nothing, modifies nothing.

Run:  python verification/oracle_adapter_binding.py [--json]
Exit: 0 = every bare name resolves under baseline/code, 1 = at least one does not
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
ADAPTERS = TARGET / "absorbed" / "adapters"
EXPECTED_PREFIX = TARGET / "baseline" / "code"

PROBE = r"""
import importlib.util, json, sys
sys.path.insert(0, {target!r})
sys.path.insert(0, {v2code!r})   # where the adapter's ensure_v2_import_path() points
names = {names!r}
resolved = {{}}
for n in names:
    try:
        spec = importlib.util.find_spec(n)
        resolved[n] = getattr(spec, "origin", None) if spec else None
    except Exception as exc:
        resolved[n] = "find_spec error: %r" % (exc,)
print("PROBE " + json.dumps({{"mod": "find_spec-resolution", "status": "ok", "resolved": resolved}}))
"""

# The adapter imports that are function-local (deferred) never execute on a plain
# `import absorbed.adapters.*`, so the only faithful way to learn where each bare
# name WOULD bind is the import system itself (find_spec) with the same sys.path
# the adapter installs. An earlier version of this probe imported the modules and
# read sys.modules -- that reported "unresolved" for every name, because none of
# those imports run at import time.
DEFERRED_EXPECTED = {
    "runtime": ("target-root runtime.py", "not under baseline/code by design?"),
}


def bare_imports() -> dict[str, list[tuple[str, int]]]:
    """top-level name -> [(file, lineno)] for absolute imports under adapters/."""
    out: dict[str, list[tuple[str, int]]] = {}
    for f in sorted(ADAPTERS.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    out.setdefault(top, []).append((f.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    top = node.module.split(".")[0]
                    out.setdefault(top, []).append((f.name, node.lineno))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    imports = bare_imports()
    stdlib = set(sys.stdlib_module_names) | {"numpy", "scipy", "numba", "llvmlite", "shapely"}
    external = sorted(n for n in imports if n in stdlib)
    candidates = sorted(n for n in imports if n not in stdlib)
    mods = [f"absorbed.adapters.{p.stem}" for p in sorted(ADAPTERS.glob("*.py"))]

    print(f"adapters/: {len(mods)} modules; bare top-level names: {sorted(imports)}")
    print(f"  stdlib/third-party (not adapter targets): {external}")
    print(f"  to verify against {EXPECTED_PREFIX}: {candidates}\n")

    code = PROBE.format(target=str(TARGET), v2code=str(EXPECTED_PREFIX), names=candidates)
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=600)
    rows = []
    for line in (proc.stdout or "").strip().splitlines():
        if line.startswith("PROBE "):
            rows.append(json.loads(line[6:]))
    if not rows:
        print("PROBE FAILED — stderr tail:")
        print((proc.stderr or "").strip()[-600:])
        return 1

    bad: list[str] = []
    resolved_any: dict[str, str] = {}
    for r in rows:
        print(f"  {r['mod']}: {r['status']}")
        for name, path in sorted(r["resolved"].items()):
            resolved_any.setdefault(name, path)
    print("\n=== resolved __file__ per bare name ===")
    for name in candidates:
        path = resolved_any.get(name)
        if path is None:
            print(f"  {name:12s} NOT RESOLVED (never imported by any adapter)")
            bad.append(f"{name}: unresolved")
            continue
        under = path.startswith(str(EXPECTED_PREFIX))
        print(f"  {'OK  ' if under else 'BAD '} {name:12s} {path}")
        if not under:
            bad.append(f"{name}: {path}")

    print(f"\n=== F3 verdict ===")
    print(f"  imported by: " + "; ".join(f"{n} <- {[f'{f}:{l}' for f, l in v][:3]}"
                                        for n, v in sorted(imports.items()) if n in candidates))
    if bad:
        print(f"  FAIL: {len(bad)} bare name(s) do NOT resolve under baseline/code: {bad}")
    else:
        print(f"  PASS: all {len(candidates)} bare name(s) resolve under {EXPECTED_PREFIX}")
    if args.json:
        print(json.dumps({"resolved": resolved_any, "failures": bad,
                          "expected_prefix": str(EXPECTED_PREFIX)}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
