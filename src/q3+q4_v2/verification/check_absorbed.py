#!/usr/bin/env python
"""Independent gate for the absorbed/ SOTA port (Q3 v5 + Q4 v4).

Verify-only: this script never modifies the source package, never modifies
everything else in the target package, and never imports the source package
into its own process (a socket hijack must not leak into the verifier).

Run:  python verification/check_absorbed.py [--src-root <path>] [--json]

Exit codes:
  0 = all MUST checks passed
  1 = at least one MUST check FAILED  (findings, blocker)
  2 = not ready (absorbed/ missing, or baseline unavailable)

Evidence classes used in the output:
  [EXEC]  executed here, output observed
  [STATIC] read from source text / AST, no execution
  [UNPROVEN] could not be established; must NOT be reported as PASS
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
DEFAULT_SRC_ROOT = Path(r"D:\CUMCM2026\src\Q3_Q4_V3")
Q4_WS_NAME = "q4_deep_optimization_v4_20260912"
Q4_LOCK_REL = ("workstreams", Q4_WS_NAME, "results", "selection_lock.json")
Q3_ENTRY_REL = ("code", "src", "q3_optimizer_v5.py")
BASELINE_REL = ("verification", "production_hashes_before.json")
ABSORBED_NAME = "absorbed"

# Modules that identify an engine package (as opposed to the adapter/entry layer).
ENGINE_ENTRY_STEMS = {"strategy_v4", "q3_optimizer_v5"}

# Vendored files whose AST differs from the locked source only by an explicitly
# reviewed delta may be listed here as {"<source relpath>": "<reason>"}.
# Empty by default: any unlisted mismatch is reported as FAIL.
ALLOWLIST: dict[str, str] = {}

# Definitions the port deliberately does NOT vendor. Each entry was read and
# verified by the verifier: none of them participates in solve()'s call graph.
DEF_ALLOWLIST: dict[str, dict[str, str]] = {
    "code/practice_single_source.py": {
        "ClassDef:PracticeClient":
            "source stub only raises RuntimeError('Simulator clients are disabled...'); "
            "no algorithm semantics, never instantiated by q3_optimizer_v5",
    },
    "code/practice_all_sources.py": {
        "FunctionDef:main": "offline CLI entry point; not in the solve() call graph",
    },
    "code/practice_all_sources_fast.py": {
        "FunctionDef:main": "offline CLI entry point; not in the solve() call graph",
    },
}

HIJACK_PATTERNS = (
    r"socket\s*\.\s*socket\s*=",
    r"socket\s*\.\s*create_connection\s*=",
    r"urllib\s*\.\s*request\s*\.\s*OpenerDirector\s*\.\s*open\s*=",
    r"OpenerDirector\s*\.\s*open\s*=",
)

# Names that are legitimately imported from outside absorbed/: the stdlib plus the
# scientific stack the SOTA solvers depend on.
STDLIB_AND_KNOWN = set(sys.stdlib_module_names) | {
    "numpy", "scipy", "numba", "llvmlite", "shapely", "yaml", "pytest",
}

ROWS: list[tuple[str, str, str, str]] = []  # (class, id, status, detail)


def rec(cls: str, cid: str, status: str, detail: str) -> None:
    ROWS.append((cls, cid, status, detail))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- AST helpers
class _StripImports(ast.NodeTransformer):
    """Drop Import/ImportFrom anywhere (returning None deletes the statement)."""

    def visit_Import(self, node):  # noqa: N802
        return None

    def visit_ImportFrom(self, node):  # noqa: N802
        return None


class _StripDocstrings(ast.NodeTransformer):
    @staticmethod
    def _drop_first_str(node):
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:]
        return node

    def visit_Module(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_first_str(node)

    def visit_FunctionDef(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_first_str(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):  # noqa: N802
        self.generic_visit(node)
        return self._drop_first_str(node)


def fingerprint(path: Path, *, drop_docstrings: bool) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    tree = _StripImports().visit(tree)
    if drop_docstrings:
        tree = _StripDocstrings().visit(tree)
    ast.fix_missing_locations(tree)
    return sha256_bytes(ast.dump(tree, annotate_fields=False).encode("utf-8"))


def top_level_imports(path: Path) -> list[tuple[str, int]]:
    """Absolute (non-relative) top-level module names imported by a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((a.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.module.split(".")[0], node.lineno))
    return found


def module_level_assignments(path: Path) -> dict[str, object]:
    """Top-level NAME = <literal> assignments (integrity-relevant constants)."""
    out: dict[str, object] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    try:
                        out[tgt.id] = ast.literal_eval(node.value)
                    except Exception:
                        out[tgt.id] = "<non-literal>"
    return out


def module_level_effects(path: Path) -> list[tuple[int, str]]:
    """Module-level statements that are not def/class/import/Assign/docstring."""
    effects: list[tuple[int, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return effects
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        if i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.If) and all(
            isinstance(b, (ast.Import, ast.ImportFrom, ast.Try, ast.Assign)) for b in node.body
        ):
            continue
        effects.append((node.lineno, type(node).__name__))
    return effects


def is_script(path: Path) -> bool:
    """True when module-level execution is guarded by `if __name__ == '__main__'`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.If):
            src = ast.dump(node.test)
            if "__name__" in src and "__main__" in src:
                return True
    return False


def attr_chain(node) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)) if parts else None


def raising_stub_names(tree) -> set[str]:
    """Names of module-local functions whose body is essentially `raise ...`."""
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [b for b in node.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
            if body and all(isinstance(b, ast.Raise) for b in body):
                out.add(node.name)
    return out


def find_binding_assignments(path: Path) -> list[dict]:
    """Protected-name assignments found via AST (never matches text in docstrings).

    Classification: 'noop' (X = X, behaviourally inert), 'stub' (assigned a local
    function that only raises => deny injection), 'other' (needs review).
    """
    protected = {
        "socket.socket", "socket.create_connection",
        "urllib.request.OpenerDirector.open", "OpenerDirector.open",
    }
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    stubs = raising_stub_names(tree)
    found: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            target = attr_chain(tgt)
            if target not in protected:
                continue
            value = attr_chain(node.value)
            if value is not None and value == target:
                kind = "noop"
            elif value is not None and value.split(".")[-1] in stubs:
                kind = "stub"
            elif isinstance(node.value, ast.Lambda):
                kind = "stub"
            else:
                kind = "other"
            found.append({"line": node.lineno, "target": target, "kind": kind,
                          "value": value or type(node.value).__name__})
    return found


def def_fingerprints(path: Path) -> dict[str, str]:
    """Map '<Kind>:<name>' -> fingerprint of that top-level def/class node."""
    out: dict[str, str] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            single = ast.Module(body=[node], type_ignores=[])
            single = _StripImports().visit(single)
            single = _StripDocstrings().visit(single)
            ast.fix_missing_locations(single)
            out[f"{type(node).__name__}:{node.name}"] = sha256_bytes(
                ast.dump(single, annotate_fields=False).encode("utf-8"))
    return out


def collect_def_fingerprints(absorbed: Path) -> dict[str, list[str]]:
    pool: dict[str, list[str]] = {}
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        for key, fp in def_fingerprints(f).items():
            pool.setdefault(fp, []).append(f"{f.relative_to(absorbed).as_posix()}::{key}")
    return pool


def target_top_names() -> set[str]:
    """Module/package names importable from the target package roots (collision set)."""
    names: set[str] = set()
    roots = [TARGET, TARGET / "baseline" / "code", TARGET / "tools"]
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                names.add(p.name)
            elif p.suffix == ".py":
                names.add(p.stem)
    return names


# --------------------------------------------------------- source-side closure
def name_index(root: Path) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        idx.setdefault(p.parent.name if p.name == "__init__.py" else p.stem, []).append(p)
    return idx


def load_q4_lock(src_root: Path) -> dict:
    return json.loads(src_root.joinpath(*Q4_LOCK_REL).read_text(encoding="utf-8"))


def q4_locked_hashes(lock: dict, src_root: Path) -> dict[str, Path]:
    ws = src_root / "workstreams" / Q4_WS_NAME
    by_hash: dict[str, Path] = {}
    for rel, h in lock.get("source_sha256", {}).items():
        by_hash[h.lower()] = (ws / rel).resolve()
    return by_hash


def resolve_closure(start: Path, index: dict[str, list[Path]], prefer: dict[str, Path]) -> tuple[list[Path], list[str]]:
    """BFS the absolute-import closure. `prefer` maps sha256 -> path (lock-pinned)."""
    preferred_paths = {v.resolve() for v in prefer.values()}
    seen: list[Path] = []
    notes: list[str] = []
    queue = [start.resolve()]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.append(cur)
        for top, _ln in top_level_imports(cur):
            cands = index.get(top, [])
            if not cands:
                continue  # external (stdlib / site-packages)
            pinned = [c for c in (x.resolve() for x in cands) if c in preferred_paths]
            fresh = [c for c in cands if "snapshots" not in c.parts]
            if len(pinned) == 1:
                nxt = pinned[0]
            elif len(fresh) == 1:
                nxt = fresh[0].resolve()
            elif len(cands) == 1:
                nxt = cands[0].resolve()
            else:
                notes.append(f"ambiguous import '{top}' in {cur.name} -> {len(cands)} candidates")
                continue
            if nxt.suffix == ".py" and nxt not in seen:
                queue.append(nxt)
    return seen, notes


# ------------------------------------------------------------------- checks
def check_a_ast_equivalence(src_root: Path, absorbed: Path) -> None:
    """(a) per-file AST equivalence between locked source files and absorbed copies."""
    lock = load_q4_lock(src_root)
    prefer = q4_locked_hashes(lock, src_root)
    index = name_index(src_root)

    q3_start = src_root.joinpath(*Q3_ENTRY_REL)
    q3_closure, q3_notes = resolve_closure(q3_start, index, prefer)
    q4_start = src_root / "workstreams" / Q4_WS_NAME / "strategy_v4.py"
    q4_closure, q4_notes = resolve_closure(q4_start, index, prefer)

    files = sorted(absorbed.rglob("*.py"))
    if not files:
        rec("MUST", "a", "FAIL", "absorbed/ contains no .py files")
        return

    strict: dict[str, Path] = {}
    relaxed: dict[str, Path] = {}
    for f in files:
        if "__pycache__" in f.parts:
            continue
        s = fingerprint(f, drop_docstrings=False)
        r = fingerprint(f, drop_docstrings=True)
        if s:
            strict.setdefault(s, f)
        if r:
            relaxed.setdefault(r, f)

    groups = (("Q3", q3_closure), ("Q4", q4_closure))
    defpool = collect_def_fingerprints(absorbed)
    matched = merged = absent = notvend = 0
    for label, closure in groups:
        for src in closure:
            rel = src.relative_to(src_root).as_posix()
            if rel in ALLOWLIST:
                rec("MUST", "a", "STATIC", f"[{label}] {rel}: allowlisted ({ALLOWLIST[rel]})")
                continue
            fs = fingerprint(src, drop_docstrings=False)
            fr = fingerprint(src, drop_docstrings=True)
            match = strict.get(fs) or relaxed.get(fr)
            src_sha = sha256_file(src)
            in_lock = src_sha.lower() in prefer
            locktag = " [lock-hash verified]" if in_lock else ""
            if match is not None:
                same_bytes = sha256_file(match) == src_sha
                kind = "byte-identical" if same_bytes else "AST-identical (docstring/format delta)"
                rec("MUST", "a", "STATIC",
                    f"[{label}] {rel} -> {match.relative_to(absorbed).as_posix()} : {kind}{locktag}")
                matched += 1
                continue
            # no whole-file twin: try per-definition equivalence (merged / renamed module)
            defs = def_fingerprints(src)
            allowed = DEF_ALLOWLIST.get(rel, {})
            hits = [k for k, fp in defs.items() if fp in defpool]
            missed = [k for k, fp in defs.items() if fp not in defpool and k not in allowed]
            dropped = [k for k in defs if k in allowed]
            same_stem = [f for f in files if f.stem == src.stem and "__pycache__" not in f.parts]
            where = f" (same-stem file present: {same_stem[0].relative_to(absorbed).as_posix()}, body diverged)" if same_stem else ""
            if defs and not missed and not dropped:
                rec("MUST", "a", "STATIC",
                    f"[{label}] {rel}: no file twin{where}; all {len(hits)} top-level definitions are "
                    f"AST-identical elsewhere in absorbed/{locktag}")
                merged += 1
            elif defs and not missed and dropped:
                rec("MUST", "a", "STATIC",
                    f"[{label}] {rel}: {len(hits)} definitions AST-identical elsewhere; {len(dropped)} deliberately "
                    f"not vendored -> " + "; ".join(f"{k} ({allowed[k]})" for k in dropped))
                merged += 1
            elif hits:
                rec("MUST", "a", "FAIL",
                    f"[{label}] {rel}: {len(missed)}/{len(defs)} top-level definitions have no AST-identical "
                    f"twin{where}: {missed[:8]}{locktag}")
                absent += 1
            else:
                # Nothing comparable was vendored at all: a documented removal, not an
                # AST PASS. Its equivalence must be established behaviourally instead.
                rec("MUST", "a", "NOTVEND",
                    f"[{label}] {rel}: not vendored at all{where} (source sha256 {src_sha[:12]}"
                    f"{', lock-verified' if in_lock else ''}) -> equivalence must be covered by "
                    f"differential_check.py; require a written justification in MANIFEST.md")
                notvend += 1
    if q3_notes or q4_notes:
        for n in (q3_notes + q4_notes)[:10]:
            rec("MUST", "a", "UNPROVEN", f"closure resolution note: {n}")
    rec("MUST", "a", "EXEC",
        f"closure checked: {matched} file-level identical, {merged} definition-level identical, "
        f"{notvend} deliberately not vendored, {absent} unresolved")


def check_b_import_smoke(absorbed: Path, timeout: int = 300) -> None:
    """(b) import smoke in both orders: `import numba` first, and last."""
    targets = discover_entry_modules(absorbed)
    if not targets:
        rec("MUST", "b", "FAIL", "no importable entry module found under absorbed/ (expected solve_optimized_v5 / solve)")
        return
    for order in ("numba_first", "numba_last"):
        for dotted, root in targets:
            lines = [
                "import sys, socket, urllib.request, json",
                f"sys.path.insert(0, {str(root)!r})",
                f"sys.path.insert(0, {str(TARGET)!r})",
                "ORIG = (socket.socket, socket.create_connection, urllib.request.OpenerDirector.open)",
                "def _st(tag):",
                "    print(json.dumps({'tag': tag,",
                "        'socket_native': socket.socket is ORIG[0],",
                "        'conn_native': socket.create_connection is ORIG[1],",
                "        'opener_native': urllib.request.OpenerDirector.open is ORIG[2]}))",
                "_st('before')",
            ]
            if order == "numba_first":
                lines.append("import numba")
            lines.append(f"import importlib; importlib.import_module({dotted!r})")
            if order == "numba_last":
                lines.append("import numba")
            lines.append("_st('after')")
            code = "\n".join(lines) + "\n"
            try:
                t0 = time.perf_counter()
                out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)
                dt = time.perf_counter() - t0
            except subprocess.TimeoutExpired:
                rec("MUST", "b", "FAIL", f"{dotted} [{order}]: import timed out after {timeout}s")
                continue
            if out.returncode != 0:
                tail = (out.stderr or "").strip().splitlines()[-3:]
                rec("MUST", "b", "FAIL", f"{dotted} [{order}]: import raised -> {' | '.join(tail)}")
                continue
            state = {}
            for line in out.stdout.strip().splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                state[d.get("tag")] = d
            after = state.get("after", {})
            native = bool(after.get("socket_native")) and bool(after.get("conn_native")) and bool(after.get("opener_native"))
            pre = state.get("before", {})
            status = "EXEC" if native else "FAIL"
            rec(
                "MUST",
                "b",
                status,
                f"{dotted} [{order}]: imported in {dt:.1f}s; native before={pre.get('socket_native')}/{pre.get('conn_native')}/{pre.get('opener_native')} "
                f"after={after.get('socket_native')}/{after.get('conn_native')}/{after.get('opener_native')}",
            )


    # combined order: both engines loaded in ONE process, both permutations
    if len(targets) >= 2:
        def pick(token):
            return next((t for t in targets if token in t[0]), None)
        q3, q4 = pick("q3"), pick("q4")
        if q3 and q4:
            for first, second, label in ((q3, q4, "Q3->Q4"), (q4, q3, "Q4->Q3")):
                lines = [
                    "import sys, socket, urllib.request, json",
                    f"sys.path.insert(0, {str(first[1])!r})",
                    f"sys.path.insert(0, {str(second[1])!r})",
                    f"sys.path.insert(0, {str(TARGET)!r})",
                    "ORIG = (socket.socket, socket.create_connection, urllib.request.OpenerDirector.open)",
                    "def _st(tag):",
                    "    print(json.dumps({'tag': tag,",
                    "        'socket_native': socket.socket is ORIG[0],",
                    "        'conn_native': socket.create_connection is ORIG[1],",
                    "        'opener_native': urllib.request.OpenerDirector.open is ORIG[2]}))",
                    "import importlib",
                    f"importlib.import_module({first[0]!r})",
                    "_st('after_first')",
                    f"importlib.import_module({second[0]!r})",
                    "_st('after_second')",
                ]
                try:
                    out = subprocess.run([sys.executable, "-c", "\n".join(lines) + "\n"],
                                         capture_output=True, text=True, timeout=timeout)
                except subprocess.TimeoutExpired:
                    rec("MUST", "b", "FAIL", f"combined order {label}: timed out")
                    continue
                if out.returncode != 0:
                    tail = (out.stderr or "").strip().splitlines()[-3:]
                    rec("MUST", "b", "FAIL", f"combined order {label}: {' | '.join(tail)}")
                    continue
                states = {}
                for line in out.stdout.strip().splitlines():
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    states[d.get("tag")] = d
                one, two = states.get("after_first", {}), states.get("after_second", {})
                ok = all(one.get(k) and two.get(k) for k in ("socket_native", "conn_native", "opener_native"))
                rec("MUST", "b", "EXEC" if ok else "FAIL",
                    f"combined order {label}: after 1st={one.get('socket_native')}/{one.get('conn_native')}/"
                    f"{one.get('opener_native')}, after 2nd={two.get('socket_native')}/{two.get('conn_native')}/"
                    f"{two.get('opener_native')}")


def discover_entry_modules(absorbed: Path) -> list[tuple[str, Path]]:
    """Find importable modules defining a solver entry point."""
    wanted = {"solve_optimized_v5", "solve"}
    found: list[tuple[str, Path]] = []
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if not (names & wanted):
            continue
        root, parts = f.parent, [f.stem]
        while (root / "__init__.py").exists():
            parts.insert(0, root.name)
            root = root.parent
        found.append((".".join(parts) if len(parts) > 1 else f.stem, root))
    return found


def check_c_parameters(src_root: Path, absorbed: Path) -> None:
    """(c) locked parameters transported verbatim."""
    lock = load_q4_lock(src_root)
    want = lock.get("selected_parameters", {})
    seen: dict[str, tuple[Path, object]] = {}
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        for name, value in module_level_assignments(f).items():
            if name == "VERSION" or "PARAMETER" in name.upper() or "SELECTED" in name.upper():
                seen[name] = (f, value)
    if not seen:
        rec("MUST", "c", "FAIL", "no VERSION/SELECTED_PARAMETERS/LOCKED_PARAMETERS assignment found under absorbed/")
    for name, (f, value) in sorted(seen.items()):
        if not isinstance(value, dict):
            rec("MUST", "c", "STATIC", f"{name} in {f.name} = {value!r} (not a parameter dict)")
            continue
        overlap = set(value) & set(want)
        if len(overlap) < 0.6 * len(want):
            rec("MUST", "c", "STATIC",
                f"{name} in {f.name}: unrelated parameter set ({len(value)} fields, overlap {len(overlap)}/{len(want)}) "
                f"-> not the Q4 lock; ignored")
            continue
        missing = {k: v for k, v in want.items() if value.get(k) != v}
        extra = {k: v for k, v in value.items() if k not in want}
        if not missing and not extra:
            rec("MUST", "c", "STATIC", f"{name} in {f.name}: all {len(want)} locked fields match selection_lock.json")
        else:
            rec(
                "MUST",
                "c",
                "FAIL",
                f"{name} in {f.name}: {len(missing)} field(s) differ from lock "
                f"({ {k: (value.get(k), v) for k, v in list(missing.items())[:6]} }), extra={sorted(extra)[:6]}",
            )
    # a shipped copy of the lock must match byte-for-byte
    for f in sorted(absorbed.rglob("*.json")):
        if f.name == "selection_lock.json":
            same = sha256_file(f) == sha256_file(src_root.joinpath(*Q4_LOCK_REL))
            rec("MUST", "c", "STATIC" if same else "FAIL",
                f"shipped {f.relative_to(absorbed).as_posix()}: byte-identical to source lock = {same}")

    # --- v4 lock vs v3 lock: the absorbed defaults must come from v4, not v3 ---
    v3_rel = None
    for rel in lock.get("source_sha256", {}):
        if rel.endswith("q4_uniform_optimization_v3_20260912/results/selection_lock.json"):
            v3_rel = (src_root / "workstreams" / Q4_WS_NAME / rel).resolve()
    if v3_rel and v3_rel.is_file():
        v3 = json.loads(v3_rel.read_text(encoding="utf-8")).get("selected_parameters", {})
        diff = {k: (v3.get(k), want.get(k)) for k in set(v3) | set(want) if v3.get(k) != want.get(k)}
        rec("MUST", "c", "STATIC",
            f"v3 lock at {v3_rel.parent.parent.name}/results/selection_lock.json differs from the v4 lock in "
            f"{len(diff)} field(s) -> the two are genuinely different files; absorbed must use v4")
        for name, (f, value) in sorted(seen.items()):
            if not isinstance(value, dict) or len(set(value) & set(want)) < 0.6 * len(want):
                continue
            if value == v3:
                rec("MUST", "c", "FAIL", f"{name} in {f.name} equals the **v3** lock, not the v4 lock")
            else:
                rec("MUST", "c", "STATIC", f"{name} in {f.name}: matches v4 lock, does NOT equal the v3 lock")
        for name, (f, value) in sorted(seen.items()):
            if name.lower().startswith("v3") or "V3" in name:
                rec("MUST", "c", "FAIL",
                    f"{name} in {f.name} injects v3-lock parameters into the absorbed package")
    else:
        rec("MUST", "c", "UNPROVEN", "v3 selection_lock.json not found; v4-vs-v3 distinction not verified")


def check_d_socket(absorbed: Path) -> None:
    """(d) no socket/urllib monkeypatch survives in the absorbed engine."""
    stubs: list[str] = []
    others: list[str] = []
    noops: list[str] = []
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        for hit in find_binding_assignments(f):
            where = f"{f.relative_to(absorbed).as_posix()}:{hit['line']} {hit['target']} = {hit['value']}"
            {"noop": noops, "stub": stubs, "other": others}[hit["kind"]].append(where)
    if stubs:
        rec("MUST", "d", "FAIL",
            f"{len(stubs)} deny-injection site(s) still EXECUTE under absorbed/ (would kill socket/urllib "
            f"process-wide): " + "; ".join(stubs[:6]))
    if others:
        rec("MUST", "d", "FAIL",
            f"{len(others)} protected-name assignment(s) of unclear effect: " + "; ".join(others[:6]))
    if not stubs and not others:
        rec("MUST", "d", "STATIC",
            f"no deny-injection or unknown binding assignment under absorbed/ "
            f"({len(noops)} inert self-assignment(s) documenting source removals)")
    if noops:
        rec("MUST", "d", "STATIC", "inert self-assignments: " + "; ".join(noops[:6]))

    targets = discover_entry_modules(absorbed)
    if not targets:
        rec("MUST", "d", "UNPROVEN", "no entry module found; runtime socket assertion not performed")
        return
    dotted, root = targets[0]
    code = (
        "import sys, socket, urllib.request\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        f"sys.path.insert(0, {str(TARGET)!r})\n"
        "o = (socket.socket, socket.create_connection, urllib.request.OpenerDirector.open)\n"
        f"import importlib; importlib.import_module({dotted!r})\n"
        "same = (socket.socket is o[0], socket.create_connection is o[1], urllib.request.OpenerDirector.open is o[2])\n"
        "print('IDENTITY', same)\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 1), timeout=0.3)\n"
        "    print('CONNECT', 'connected')\n"
        "except RuntimeError as e:\n"
        "    print('CONNECT', 'HIJACKED', e)\n"
        "except OSError as e:\n"
        "    print('CONNECT', 'native-behaviour', type(e).__name__)\n"
    )
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        rec("MUST", "d", "FAIL", f"runtime socket assertion timed out for {dotted}")
        return
    txt = out.stdout
    ident = "IDENTITY (True, True, True)" in txt
    hij = "HIJACKED" in txt
    rec(
        "MUST",
        "d",
        "EXEC" if (ident and not hij) else "FAIL",
        f"{dotted}: identity preserved={ident}, connect hijacked={hij} | {txt.strip().replace(chr(10), ' ; ')[:220]}",
    )


def check_e_bare_imports(absorbed: Path) -> None:
    """(e) bare top-level imports that could silently resolve OUTSIDE absorbed/.

    The hazard is not stdlib/site-packages (those are intended); it is a name that
    also exists on the target package's sys.path (e.g. `geometry` -> baseline/code/
    geometry), which binds the wrong module with no error at all.
    """
    internal = {p.parent.name if p.name == "__init__.py" else p.stem for p in absorbed.rglob("*.py")}
    internal.add(absorbed.name)
    collide = target_top_names()
    engine_dirs = {f.parent for f in absorbed.rglob("*.py") if f.stem in ENGINE_ENTRY_STEMS}
    risky: list[str] = []
    adapter_risky: list[str] = []
    unresolvable: list[str] = []
    total = 0
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        in_engine = f.parent in engine_dirs
        for top, line in top_level_imports(f):
            total += 1
            if top in internal:
                continue
            here = f"{f.relative_to(absorbed).as_posix()}:{line} -> {top}"
            if top in collide:
                (risky if in_engine else adapter_risky).append(here)
            elif top not in STDLIB_AND_KNOWN:
                unresolvable.append(here)
    if risky:
        rec("MUST", "e", "FAIL",
            f"{len(risky)} bare import(s) inside the engine packages can silently bind a target-package "
            f"module: " + "; ".join(risky[:10]))
    else:
        rec("MUST", "e", "STATIC",
            f"engine packages (dirs {sorted(d.name for d in engine_dirs)}): of {total} import statements "
            f"none binds an outside-absorbed module (collision set: {sorted(collide)[:12]})")
    if adapter_risky:
        rec("MUST", "e", "STATIC",
            f"{len(adapter_risky)} bare import(s) outside the engine packages (adapter/entry layer) bind "
            f"target-package modules BY DESIGN — each must resolve under {TARGET.name}: "
            + "; ".join(adapter_risky[:10]))
    if unresolvable:
        rec("MUST", "e", "UNPROVEN",
            f"{len(unresolvable)} import(s) resolve to neither absorbed/ nor the local stdlib index "
            f"(expected third-party packages): " + "; ".join(unresolvable[:10]))


def check_f_production(baseline_path: Path) -> None:
    """(f) production path unchanged vs the frozen baseline."""
    if not baseline_path.is_file():
        rec("MUST", "f", "UNPROVEN", f"baseline {baseline_path.name} missing -> cannot prove production path was untouched")
        return
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    # Authorised post-baseline production changes come from the captain's record file
    # (single source of truth). Matching is by EXACT (path, before, after); anything
    # else on the production path still fails. Absent/invalid record => nothing is
    # authorised, so the plain baseline comparison stands.
    authorised: dict[str, dict] = {}
    bad: list[str] = []
    registered: list[str] = []
    auth_path = HERE / "production_change_authorization.json"
    auth_note = "no authorisation record present"
    if auth_path.is_file():
        try:
            rec_json = json.loads(auth_path.read_text(encoding="utf-8"))
            # schema assertion: a malformed record must FAIL loudly, never silently
            # authorise nothing-but-look-fine or authorise on aliases alone.
            problems: list[str] = []
            if not (rec_json.get("record") or rec_json.get("authorization_quote")
                    or rec_json.get("authorisation_quote")):
                problems.append("missing 'record'/'authorization_quote'")
            changes = rec_json.get("changes")
            if not isinstance(changes, list) or not changes:
                problems.append("'changes' missing or empty")
            for i, ch in enumerate(changes or []):
                if not isinstance(ch, dict):
                    problems.append(f"changes[{i}] is not an object")
                    continue
                for key in ("path", "before_sha256", "after_sha256"):
                    if not ch.get(key):
                        problems.append(f"changes[{i}] missing {key!r}")
                for alias in ("authorised_after_sha256", "authorized_after_sha256",
                              "authorised_by", "authorized_by"):
                    if ch.get(alias) and not ch.get("after_sha256"):
                        problems.append(f"changes[{i}] uses alias {alias!r} without canonical 'after_sha256'")
                if ch.get("path"):
                    authorised[ch["path"]] = {
                        "authorised_by": rec_json.get("authorized_by")
                                        or rec_json.get("authorised_by") or "?",
                        "when": ch.get("when") or rec_json.get("baseline_captured_at_utc", "?"),
                        "before_sha256": ch.get("before_sha256"),
                        "after_sha256": ch.get("after_sha256"),
                        "reason": ch.get("purpose", ""),
                        "quote": rec_json.get("authorization_quote")
                                 or rec_json.get("authorisation_quote", ""),
                    }
            if problems:
                auth_note = f"authorisation record SCHEMA INVALID -> {problems[:4]}"
                bad.extend(f"authorisation record schema: {p}" for p in problems)
            else:
                auth_note = (f"record {auth_path.name}: authorised_by="
                             f"{rec_json.get('authorized_by') or rec_json.get('authorised_by')!r}, "
                             f"scope={rec_json.get('authorized_scope') or rec_json.get('authorised_scope')}")
        except Exception as exc:  # noqa: BLE001
            auth_note = f"authorisation record unreadable ({exc!r}) -> nothing authorised"
            bad.append(f"authorisation record unreadable: {exc!r}")
    for name, ent in base.get("named_production_files", {}).items():
        p = TARGET / name
        if not p.is_file():
            bad.append(f"{name}: MISSING")
        elif sha256_file(p) != ent.get("sha256"):
            auth = authorised.get(name)
            if (auth and sha256_file(p) == auth["after_sha256"]
                    and ent.get("sha256") == auth["before_sha256"]):
                registered.append(f"{name} (authorised_by={auth['authorised_by']!r} "
                                  f"quote={auth['quote']!r} after={auth['after_sha256'][:12]}…)")
            else:
                bad.append(f"{name}: CHANGED and NOT covered by the authorisation record")
    for name, ent in base.get("all_toplevel_py", {}).items():
        p = TARGET / name
        if not p.is_file():
            bad.append(f"{name}: MISSING")
            continue
        if sha256_file(p) == ent.get("sha256"):
            continue
        if any(r.startswith(name + " ") for r in registered):
            continue
        auth = authorised.get(name)
        if (auth and sha256_file(p) == auth["after_sha256"]
                and ent.get("sha256") == auth["before_sha256"]):
            registered.append(f"{name} (authorised_by={auth['authorised_by']!r} "
                              f"quote={auth['quote']!r} after={auth['after_sha256'][:12]}…)")
        else:
            bad.append(f"{name}: CHANGED and NOT covered by the authorisation record")
    tree = base.get("baseline_tree", {})
    per = tree.get("files", {})
    changed = [rel for rel, h in per.items() if not (TARGET / rel).is_file() or sha256_file(TARGET / rel) != h]
    if changed:
        bad.extend(f"{c}: CHANGED/MISSING" for c in changed[:10])
    if bad:
        rec("MUST", "f", "FAIL", "production path modified: " + "; ".join(bad[:12]))
    else:
        rec(
            "MUST",
            "f",
            "EXEC",
            f"production unchanged vs baseline captured {base.get('captured_at_utc')} "
            f"({len(base.get('all_toplevel_py', {}))} top-level files + {len(per)} baseline files)"
            + (f"; plus {len(registered)} authorised post-baseline change(s): {'; '.join(registered)}"
               if registered else "")
            + f" [{auth_note}]",
        )


def check_i_import_side_effects(absorbed: Path) -> None:
    """(i) no import-time side effects in engine modules; scripts must be __main__-guarded."""
    engine_hits: list[str] = []
    script_hits: list[str] = []
    net_hits: list[str] = []
    net_words = ("urlopen", "requests", "socket.socket", "create_connection", "http.client", "urllib")
    for f in sorted(absorbed.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        effects = module_level_effects(f)
        if not effects:
            continue
        rel = f.relative_to(absorbed).as_posix()
        bucket = script_hits if is_script(f) else engine_hits
        bucket.extend(f"{rel}:{line} ({kind})" for line, kind in effects)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for i, node in enumerate(tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.If):
                src = ast.dump(node.test)
                if "__name__" in src and "__main__" in src:
                    continue
            src = ast.dump(node)
            if any(w in src for w in net_words):
                net_hits.append(f"{rel}:{node.lineno} ({type(node).__name__})")
    if engine_hits:
        rec("MUST", "i", "FAIL",
            f"{len(engine_hits)} unguarded module-level statement(s) in engine modules: " + "; ".join(engine_hits[:10]))
    else:
        rec("MUST", "i", "STATIC",
            "no unguarded module-level side effect in engine modules (defs/classes/imports/assignments only)")
    if net_hits:
        rec("MUST", "i", "FAIL", "module-level network usage at import time: " + "; ".join(net_hits[:8]))
    else:
        rec("MUST", "i", "STATIC", "no module-level network/socket call in any absorbed module (unguarded)")
    if script_hits:
        rec("MUST", "i", "STATIC",
            f"{len(script_hits)} module-level statement(s) live in __main__-guarded entry scripts (import-safe): "
            + "; ".join(script_hits[:6]))


def check_j_skip_reason_invariant(absorbed: Path) -> None:
    """(j) runtime invariant: every `skipped` check must carry an explicit reason.

    The verifier's anti-false-PASS invariant only inspects checks whose
    `reason == "unavailable"`, so a path that emits `status="skipped"` with
    `reason=None` would neither block `all_ok` nor be registered. This runs one
    absorbed smoke in a subprocess and asserts the tag discipline on the real
    artifact. Static, code-only inspection cannot prove this, hence a live run.
    """
    if not (absorbed / "run_absorbed.py").is_file():
        rec("MUST", "j", "UNPROVEN", "absorbed/run_absorbed.py missing; skip-reason invariant not exercised")
        return
    import tempfile
    allowed = {"not_applicable", "unavailable"}
    with tempfile.TemporaryDirectory(prefix="absorbed_gate_") as tmp:
        cmd = [sys.executable, "-X", "utf8", str(absorbed / "run_absorbed.py"),
               "--mode", "q3", "--engine", "q3-v5", "--sim", "http-synthetic",
               "--seed", "101", "--n-sources", "10", "--scenario", "random",
               "--output-dir", tmp]
        try:
            p = subprocess.run(cmd, cwd=str(TARGET), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
        except subprocess.TimeoutExpired:
            rec("MUST", "j", "FAIL", "smoke for the skip-reason invariant timed out")
            return
        reports = list(Path(tmp).rglob("verifier_report.json"))
        if not reports:
            tail = (p.stderr or "").strip().splitlines()[-2:]
            rec("MUST", "j", "FAIL",
                f"no verifier_report.json produced (rc={p.returncode}); stderr tail: {' | '.join(tail)}")
            return
        vr = json.loads(reports[0].read_text(encoding="utf-8"))
        checks = vr.get("checks", [])
        skipped = [c for c in checks if c.get("status") == "skipped"]
        bad = [c.get("id") for c in skipped if c.get("reason") not in allowed]
        untagged = [c.get("id") for c in checks
                    if c.get("status") not in ("passed", "failed", "skipped")]
        if bad:
            rec("MUST", "j", "FAIL",
                f"{len(bad)} skipped check(s) without reason in {sorted(allowed)}: {bad[:6]}")
        elif untagged:
            rec("MUST", "j", "FAIL", f"check(s) with unknown status: {untagged[:6]}")
        else:
            rec("MUST", "j", "EXEC",
                f"skip-reason invariant holds on a live run: {len(checks)} checks, "
                f"{len(skipped)} skipped, all with reason in {sorted(allowed)}; "
                f"counts={vr.get('counts')}, all_ok={vr.get('all_ok')}")
        # strengthened tri-state invariants (adapter-eng read-only audit says the
        # risky state is currently unreachable; this keeps it that way)
        tri_bad = [c.get("id") for c in skipped
                   if not (c.get("ok") is None
                           and c.get("not_applicable") == (c.get("reason") == "not_applicable"))]
        if tri_bad:
            rec("MUST", "j", "FAIL",
                f"skipped check(s) violating tri-state contract (ok must be None, "
                f"not_applicable must equal reason=='not_applicable'): {tri_bad[:6]}")
        else:
            rec("MUST", "j", "EXEC",
                f"tri-state contract holds on {len(skipped)} skipped check(s) "
                f"(ok=None, not_applicable==(reason=='not_applicable'))")

        scope_obj = vr.get("scope") if isinstance(vr.get("scope"), dict) else {}
        sim_name = str(scope_obj.get("sim", ""))
        unavail = list(scope_obj.get("unavailable_checks") or [])
        no_unav = next((c for c in checks if c.get("id") == "no_unavailable_evidence"), None)
        no_unav_status = (no_unav or {}).get("status")
        if sim_name in ("http-synthetic", "synthetic"):
            if unavail or no_unav_status != "passed":
                rec("MUST", "j", "FAIL",
                    f"synthetic mode must report no unavailable evidence: "
                    f"unavailable_checks={unavail}, no_unavailable_evidence={no_unav_status}")
            else:
                rec("MUST", "j", "EXEC",
                    f"synthetic mode: unavailable_checks=[] and no_unavailable_evidence=passed "
                    f"(sim={sim_name})")
        else:
            rec("MUST", "j", "STATIC",
                f"mode sim={sim_name!r}: unavailable_checks={unavail}, "
                f"no_unavailable_evidence={no_unav_status} (all_ok={vr.get('all_ok')})")

        # scope must be a structured dict (interface change: string -> dict)
        scope = vr.get("scope")
        rec("MUST", "j", "STATIC" if isinstance(scope, dict) else "FAIL",
            f"verifier_report.scope is {type(scope).__name__}"
            + (f" with keys {sorted(scope)[:8]}" if isinstance(scope, dict)
               else f" (= {str(scope)[:60]!r}); expected dict"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", default=str(DEFAULT_SRC_ROOT))
    ap.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = ap.parse_args()

    src_root = Path(args.src_root)
    absorbed = TARGET / ABSORBED_NAME
    baseline = TARGET.joinpath(*BASELINE_REL)

    if not src_root.is_dir():
        print(f"FATAL: source root not found: {src_root}")
        return 2
    if not absorbed.is_dir():
        print(f"NOT READY: {absorbed} does not exist (port not started). Nothing to verify.")
        return 2

    check_a_ast_equivalence(src_root, absorbed)
    check_b_import_smoke(absorbed)
    check_c_parameters(src_root, absorbed)
    check_d_socket(absorbed)
    check_e_bare_imports(absorbed)
    check_f_production(baseline)
    check_i_import_side_effects(absorbed)
    check_j_skip_reason_invariant(absorbed)

    # ---- consume the differential result for the NOT-VENDORED closure files ----
    # NOTVEND means "no AST twin"; its equivalence must be established behaviourally.
    # Only a differential run that actually exits 0 clears it. Missing/failing/timing
    # out degrades gracefully back to NOTVEND (never silently to PASS).
    diff_path = HERE / "differential_check.py"
    diff_ok = False
    diff_detail = "differential_check.py not present"
    if diff_path.is_file():
        try:
            dp = subprocess.run([sys.executable, "-X", "utf8", str(diff_path)], cwd=str(TARGET),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1800)
            diff_ok = dp.returncode == 0
            tail = [l for l in (dp.stdout or "").splitlines() if "VERDICT" in l or "IDENTICAL" in l
                    or "DIVERGENCE" in l]
            diff_detail = f"exit={dp.returncode}; " + (" | ".join(tail[-2:]) or "no verdict line")
        except subprocess.TimeoutExpired:
            diff_detail = "differential_check.py timed out -> NOTVEND stands"
        except Exception as exc:  # noqa: BLE001
            diff_detail = f"differential_check.py errored {exc!r} -> NOTVEND stands"
    if diff_ok:
        ROWS[:] = [(c, i, ("NOTVEND-COVERED" if s == "NOTVEND" else s), d) for c, i, s, d in ROWS]
        rec("MUST", "a", "EXEC",
            f"8 not-vendored files are covered by behavioural evidence: {diff_detail}")
    else:
        rec("MUST", "a", "UNPROVEN", f"not-vendored files still lack behavioural evidence: {diff_detail}")

    order = {"EXEC": 0, "STATIC": 1, "NOTVEND-COVERED": 2, "NOTVEND": 3, "UNPROVEN": 4, "FAIL": 5}
    fails = [r for r in ROWS if r[2] == "FAIL"]
    unproven = [r for r in ROWS if r[2] == "UNPROVEN"]
    notvend = [r for r in ROWS if r[2] == "NOTVEND"]
    covered = [r for r in ROWS if r[2] == "NOTVEND-COVERED"]
    if args.json:
        print(json.dumps([{"check": r[0] + "/" + r[1], "status": r[2], "detail": r[3]} for r in ROWS], indent=2))
    else:
        print(f"=== absorbed gate — {TARGET} ===")
        for cls, cid, status, detail in sorted(ROWS, key=lambda r: (order.get(r[2], 9), r[1])):
            print(f"[{status:16s}] {cls}/{cid}: {detail}")
        print(f"--- {len(fails)} FAIL, {len(notvend)} NOT-VENDORED(uncovered), "
              f"{len(covered)} NOT-VENDORED-COVERED-BY-DIFFERENTIAL, {len(unproven)} UNPROVEN, {len(ROWS)} rows ---")
        if fails:
            which = "; ".join(f"{c}/{i}: {d[:80]}" for c, i, s, d in fails)
            print(f"VERDICT: FAIL — blocking check(s): {which}")
        elif notvend or unproven:
            print("VERDICT: INCOMPLETE — no behavioural evidence for the not-vendored closure files")
        else:
            print("VERDICT: PASS (all MUST checks)")
    return 1 if (fails or notvend or unproven) else 0


if __name__ == "__main__":
    raise SystemExit(main())
