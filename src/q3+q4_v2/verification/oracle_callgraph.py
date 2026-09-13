#!/usr/bin/env python
"""Name-level call-graph reachability from the SOTA entry point.

Answers the question the captain requires an *evidence-based* answer to:
"a closure file the port dropped -- is it really zero-call on solve()'s path?"

Method (static, AST only -- never imports the source package):
  1. Build the canonical module index of the source tree, pinning candidates with
     the v4 selection_lock.json `source_sha256` table where possible.
  2. Resolve the entry function (strategy_v4.solve / q3_optimizer_v5.solve_optimized_v5).
  3. Walk reachable definitions name by name:
       - names referenced inside a reachable def that resolve to a module-level def
         or to an import binding are followed;
       - `from X import *` is expanded to X's public names (transitively);
       - a reachable class pulls in its methods.
     Reachability over-approximates on purpose: a false "reachable" is safe, an
     under-approximation would wrongly justify deleting needed code.
  4. For every name reachable on solve()'s path, verify an AST-identical definition
     exists under absorbed/ (imports/docstrings stripped).

Run:  python verification/oracle_callgraph.py [--src-root P] [--absorbed P] [--json]
Exit: 0 = every reachable name has an absorbed twin
      1 = a reachable name is missing from absorbed (blocker-grade finding)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
DEFAULT_SRC = Path(r"D:\CUMCM2026\src\Q3_Q4_V3")
Q4_WS = "q4_deep_optimization_v4_20260912"


# ------------------------------------------------------------------ AST utils
class _Strip(ast.NodeTransformer):
    def visit_Import(self, node):  # noqa: N802
        return None

    def visit_ImportFrom(self, node):  # noqa: N802
        return None

    @staticmethod
    def _drop_doc(node):
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:]
        return node

    def visit_Module(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_doc(node)

    def visit_FunctionDef(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_doc(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_doc(node)


def fp(_node: ast.AST) -> str:
    tree = _Strip().visit(_node)
    ast.fix_missing_locations(tree)
    return hashlib.sha256(ast.dump(tree, annotate_fields=False).encode("utf-8")).hexdigest()


class ModuleInfo:
    def __init__(self, path: Path):
        self.path = path
        self.src = path.read_text(encoding="utf-8", errors="replace")
        self.tree = ast.parse(self.src)
        self.defs: dict[str, ast.AST] = {}
        self.imports: dict[str, tuple[str, str]] = {}
        self.wildcards: list[str] = []
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[node.name] = node
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.defs.setdefault(t.id, node)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.imports[a.asname or a.name.split(".")[0]] = ("", a.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("."):
                    continue
                for a in node.names:
                    if a.name == "*":
                        self.wildcards.append(mod.split(".")[0])
                    else:
                        self.imports[a.asname or a.name] = (mod.split(".")[0], a.name)

    def refs(self, node: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

    def methods(self, cls: ast.ClassDef) -> list[ast.AST]:
        return [b for b in cls.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def def_fingerprints(self) -> dict[str, str]:
        out = {}
        for name, node in self.defs.items():
            try:
                out[name] = fp(node)
            except Exception:
                pass
        return out


# --------------------------------------------------------------- module index
def build_index(root: Path) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        idx.setdefault(p.parent.name if p.name == "__init__.py" else p.stem, []).append(p)
    return idx


def pin_map(root: Path) -> dict[str, Path]:
    lock = root / "workstreams" / Q4_WS / "results" / "selection_lock.json"
    if not lock.is_file():
        return {}
    data = json.loads(lock.read_text(encoding="utf-8"))
    ws = root / "workstreams" / Q4_WS
    out = {}
    for rel, h in data.get("source_sha256", {}).items():
        out[h.lower()] = (ws / rel).resolve()
    return out


def canonical(index: dict[str, list[Path]], top: str, pinned: set[Path]) -> Path | None:
    cands = index.get(top, [])
    if not cands:
        return None
    hit = [c for c in (x.resolve() for x in cands) if c in pinned]
    if len(hit) == 1:
        return hit[0]
    fresh = [c for c in cands if "snapshots" not in c.parts]
    if len(fresh) == 1:
        return fresh[0].resolve()
    if len(cands) == 1:
        return cands[0].resolve()
    return None


# ------------------------------------------------------------------- analysis
class Walker:
    def __init__(self, root: Path, absorbed: Path):
        self.root = root
        self.index = build_index(root)
        self.pinned = set(pin_map(root).values())
        self.cache: dict[Path, ModuleInfo] = {}
        self.absorbed = absorbed
        self.abs_fps: set[str] = set()
        for f in absorbed.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            try:
                self.abs_fps.update(ModuleInfo(f).def_fingerprints().values())
            except SyntaxError:
                continue
        self.wild_cache: dict[Path, dict[str, str]] = {}
        self.wild_def_cache: dict[tuple, dict[str, tuple[Path, ast.AST]]] = {}
        self.reachable: dict[Path, set[str]] = {}
        self.missing: list[str] = []
        self.unresolved: set[str] = set()

    def mod(self, path: Path) -> ModuleInfo:
        if path not in self.cache:
            self.cache[path] = ModuleInfo(path)
        return self.cache[path]

    def public(self, path: Path, seen=None) -> dict[str, str]:
        """name -> fingerprint for names a `from <module> import *` would expose."""
        if path in self.wild_cache:
            return self.wild_cache[path]
        seen = seen or set()
        if path in seen:
            return {}
        seen.add(path)
        m = self.mod(path)
        out = m.def_fingerprints()
        for top in m.wildcards:
            tgt = canonical(self.index, top, self.pinned)
            if tgt:
                out.update(self.public(tgt, seen))
        self.wild_cache[path] = out
        return out

    def public_defs(self, path: Path, seen=None) -> dict[str, tuple[Path, ast.AST]]:
        """name -> (defining module, node) for `from <module> import *`.

        Follows nested wildcard chains, so `bridge_v4`'s `from bridge import *`
        (which in turn does `from base import *`) resolves to the module that
        actually defines the name. Without this, re-exported names look unused
        and their modules would be wrongly reported as zero-call.
        """
        key = ("pd", path)
        cached = self.wild_def_cache.get(key)
        if cached is not None:
            return cached
        seen = seen or set()
        if path in seen:
            return {}
        seen = seen | {path}
        m = self.mod(path)
        out: dict[str, tuple[Path, ast.AST]] = {n: (path, node) for n, node in m.defs.items()}
        # a module also re-exports whatever it imported by name (this is how
        # v2/base.py exposes the geometry names, and how v3/bridge.py and
        # v4/bridge_v4.py forward them onward)
        for local, (mod, orig) in m.imports.items():
            if not mod or local in out:
                continue
            tgt = canonical(self.index, mod, self.pinned)
            if not tgt:
                continue
            got = self.public_defs(tgt, seen).get(orig)
            if got:
                out[local] = got
        for top in m.wildcards:
            tgt = canonical(self.index, top, self.pinned)
            if tgt:
                out.update(self.public_defs(tgt, seen))
        self.wild_def_cache[key] = out
        return out

    def resolve_through(self, path: Path, name: str) -> tuple[Path, ast.AST] | None:
        """Resolve `name` as seen from `path`, following wildcard re-exports."""
        m = self.mod(path)
        if name in m.defs:
            return path, m.defs[name]
        for top in m.wildcards:
            tgt = canonical(self.index, top, self.pinned)
            if not tgt:
                continue
            got = self.public_defs(tgt).get(name)
            if got:
                return got
        return None

    def visit(self, path: Path, name: str, node: ast.AST) -> None:
        bucket = self.reachable.setdefault(path, set())
        if name in bucket:
            return
        bucket.add(name)
        m = self.mod(path)
        if not self.covered(path, name):
            self.missing.append(f"{path.relative_to(self.root).as_posix()}::{name}")
        if isinstance(node, ast.ClassDef):
            for meth in m.methods(node):
                self.walk_names(path, meth)
            return
        self.walk_names(path, node)

    def covered(self, path: Path, name: str) -> bool:
        try:
            node = self.mod(path).defs[name]
        except KeyError:
            return True
        try:
            return fp(node) in self.abs_fps
        except Exception:
            return True

    def walk_names(self, path: Path, node: ast.AST) -> None:
        m = self.mod(path)
        for ref in sorted(m.refs(node)):
            if ref in m.defs:
                self.visit(path, ref, m.defs[ref])
                continue
            if ref in m.imports:
                mod, orig = m.imports[ref]
                if not mod:
                    continue  # `import x` binding -> external module object
                tgt = canonical(self.index, mod, self.pinned)
                if tgt is None:
                    self.unresolved.add(f"{mod}.{orig}")
                    continue
                tm = self.mod(tgt)
                if orig in tm.defs:
                    self.visit(tgt, orig, tm.defs[orig])
                    continue
                # re-exported through a wildcard chain inside the target module
                got = self.resolve_through(tgt, orig)
                if got:
                    self.visit(got[0], orig, got[1])
                else:
                    self.unresolved.add(f"{mod}.{orig}")
                continue
            # wildcard-provided by this module itself
            got = self.resolve_through(path, ref)
            if got:
                self.visit(got[0], ref, got[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", default=str(DEFAULT_SRC))
    ap.add_argument("--absorbed", default=str(TARGET / "absorbed"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.src_root)
    absorbed = Path(args.absorbed)
    w = Walker(root, absorbed)

    ent = [
        ("Q4", root / "workstreams" / Q4_WS / "strategy_v4.py", "solve"),
        ("Q3", root / "code" / "src" / "q3_optimizer_v5.py", "solve_optimized_v5"),
    ]
    for label, path, fname in ent:
        if not path.is_file():
            print(f"FATAL: entry not found {path}")
            return 2
        m = w.mod(path)
        if fname not in m.defs:
            print(f"FATAL: {fname} not defined in {path}")
            return 2
        w.visit(path, fname, m.defs[fname])
        print(f"[{label}] entry {path.name}::{fname} expanded", flush=True)

    # every file in the Q4 lock table, classified
    lock = root / "workstreams" / Q4_WS / "results" / "selection_lock.json"
    locked_files = sorted(pin_map(root).values())

    live = [(p, sorted(n for n in names if n)) for p, names in sorted(w.reachable.items())]
    print("\n=== REACHABLE from solve() (file -> names on the path) ===")
    for p, names in live:
        tag = "" if p in locked_files else "  (not in lock table)"
        print(f"  {p.relative_to(root).as_posix()}{tag}")
        print(f"      {', '.join(names[:14])}{' ...' if len(names) > 14 else ''}")

    reach_set = {p for p, _ in live}
    print("\n=== lock-table files NOT reachable (candidates for deletion) ===")
    zero = [p for p in locked_files if p not in reach_set]
    for p in zero:
        print(f"  {p.relative_to(root).as_posix()}")
    print(f"  -> {len(zero)} of {len(locked_files)} lock-table files are zero-call on solve()'s path")

    print("\n=== reachable definitions WITHOUT an AST-identical twin in absorbed/ ===")
    if w.missing:
        for m in w.missing:
            print(f"  MISSING {m}")
    else:
        print("  (none)")

    print(f"\nSUMMARY reachable_files={len(live)} zero_call={len(zero)} "
          f"missing_defs={len(w.missing)} unresolved_imports={len(w.unresolved)}")
    if w.unresolved:
        print("unresolved import targets (external/ambiguous):", sorted(w.unresolved)[:12])

    if args.json:
        print(json.dumps({
            "reachable": {p.relative_to(root).as_posix(): sorted(n) for p, n in live},
            "zero_call": [p.relative_to(root).as_posix() for p in zero],
            "missing_defs": w.missing,
        }, indent=2))

    return 1 if w.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
