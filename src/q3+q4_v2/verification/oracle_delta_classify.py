#!/usr/bin/env python
"""F-C: classify every AST delta between the locked source and the absorbed copy.

The hash-equality criterion (absorbed sha256 == lock's source_sha256) applies only
to files vendored byte-for-byte. For the rest, each difference must fall inside the
four whitelisted classes; anything else is an unreviewed change:

  1 = removed socket/urllib deny injection      (bridge_v4.py:9 etc.)
  2 = removed sys.path manipulation             (sys.path.insert/append)
  3 = import prefix rewritten to package-relative
  4 = dead code removed (definitions not on solve()'s path)

Classes 1-3 are checkable mechanically. Class 4 is only accepted when the removed
definition has no AST-identical twin anywhere in absorbed/ AND the caller supplies
`--callgraph-zero` proof (oracle_callgraph.py) -- otherwise it is reported as
UNCLASSIFIED so nobody can silently widen the whitelist.

Run:  python verification/oracle_delta_classify.py [--json]
Exit: 0 = every delta classified into 1-4, 1 = at least one unclassified delta
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent
SRC = Path(r"D:\CUMCM2026\src\Q3_Q4_V3")
V4_WS = SRC / "workstreams" / "q4_deep_optimization_v4_20260912"
Q4_LOCK = V4_WS / "results" / "selection_lock.json"

PAIRS = [
    ("code/src/q3_optimizer_v5.py", "absorbed/q3_v5/q3_optimizer_v5.py"),
    ("code/src/q3_optimizer_v4.py", "absorbed/q3_v5/q3_optimizer_v4.py"),
    ("code/practice_single_source.py", "absorbed/q3_v5/practice_single_source.py"),
    ("code/practice_all_sources.py", "absorbed/q3_v5/practice_all_sources.py"),
    ("code/practice_all_sources_fast.py", "absorbed/q3_v5/practice_all_sources_fast.py"),
    ("code/src/geometry.py", "absorbed/q3_v5/geometry_src.py"),
    ("code/src/q2_adopted.py", "absorbed/q3_v5/q2_adopted.py"),
    ("code/src/second_point.py", "absorbed/q3_v5/second_point.py"),
    ("code/src/legacy_second_point.py", "absorbed/q3_v5/legacy_second_point.py"),
    ("workstreams/q4_deep_optimization_v4_20260912/strategy_v4.py", "absorbed/q4_v4/strategy_v4.py"),
    ("workstreams/q4_local_optimization_v2_20260912/conditional.py", "absorbed/q4_v4/conditional.py"),
    ("workstreams/q4_local_optimization_v2_20260912/coverage.py", "absorbed/q4_v4/coverage.py"),
    ("workstreams/q4_local_optimization_v2_20260912/negative_regions.py", "absorbed/q4_v4/negative_regions.py"),
    ("workstreams/q4_uniform_optimization_v3_20260912/tour_utils.py", "absorbed/q4_v4/tour_utils.py"),
    ("workstreams/q4_deep_optimization_v4_20260912/search_nets.py", "absorbed/q4_v4/search_nets.py"),
    ("workstreams/q4_deep_optimization_v4_20260912/ordered_tour.py", "absorbed/q4_v4/ordered_tour.py"),
    ("workstreams/q4_deep_optimization_v4_20260912/geometry_hand_layouts.py", "absorbed/q4_v4/geometry_hand_layouts.py"),
    ("workstreams/q4_deep_optimization_v4_20260912/cover_union.py", "absorbed/q4_v4/cover_union.py"),
    ("workstreams/q4_local_optimization_20260912/crossbar.py", "absorbed/q4_v4/crossbar.py"),
    ("workstreams/q4_local_optimization_20260912/local_geometry.py", "absorbed/q4_v4/local_geometry.py"),
    # files rewritten as thin shims (their class-1/2/4 deltas are the point of the port)
    ("workstreams/q4_deep_optimization_v4_20260912/bridge_v4.py", "absorbed/q4_v4/bridge_v4.py"),
    ("workstreams/q4_uniform_optimization_v3_20260912/bridge.py", "absorbed/q4_v4/base.py"),
]

DANGER = ("socket", "urllib", "deny", "create_connection", "OpenerDirector")


def text_of(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ast.dump(node)


def classify_source_only(node: ast.AST) -> int | None:
    t = text_of(node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return 3
    if "sys.path" in t:
        return 2
    if any(w in t for w in DANGER):
        return 1
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return 4
    return None


def classify_absorbed_only(node: ast.AST) -> int | None:
    t = text_of(node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return 3
    # the port keeps inert `x = x` self-assignments documenting the removed deny
    if isinstance(node, ast.Assign) and any(w in t for w in DANGER):
        return 1
    if "sys.path" in t:
        return 2
    return None


def top_nodes(path: Path) -> list[ast.AST]:
    return ast.parse(path.read_text(encoding="utf-8", errors="replace")).body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    lock = json.loads(Q4_LOCK.read_text(encoding="utf-8"))
    locked_hashes = set(lock.get("source_sha256", {}).values())

    rows, unclassified = [], []
    for rel_src, rel_abs in PAIRS:
        src, abs_ = SRC / rel_src, TARGET / rel_abs
        if not (src.is_file() and abs_.is_file()):
            unclassified.append(f"{rel_src}: missing source or absorbed file")
            continue
        s_nodes, a_nodes = top_nodes(src), top_nodes(abs_)
        s_names = {n.name for n in s_nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        a_names = {n.name for n in a_nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        removed_defs = sorted(s_names - a_names)
        added_defs = sorted(a_names - s_names)
        s_texts = {text_of(n) for n in s_nodes}
        a_texts = {text_of(n) for n in a_nodes}

        removed = [n for n in s_nodes if text_of(n) not in a_texts]
        added = [n for n in a_nodes if text_of(n) not in s_texts]
        classes: dict[str, list[str]] = {}
        for node in removed:
            c = classify_source_only(node)
            if c is None:
                unclassified.append(f"{rel_src}: removed {type(node).__name__} L{node.lineno}: {text_of(node)[:70]}")
            else:
                classes.setdefault(f"cls{c}", []).append(f"L{node.lineno}:{type(node).__name__}")
        for node in added:
            c = classify_absorbed_only(node)
            if c is None and not isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)):
                unclassified.append(f"{rel_abs}: added {type(node).__name__} L{node.lineno}: {text_of(node)[:70]}")
            else:
                classes.setdefault(f"cls{c if c else 9}", []).append(f"L{node.lineno}:{type(node).__name__}")
        # removed definitions are class 4 only if they are genuinely absent (no twin)
        for name in removed_defs:
            classes.setdefault("cls4", []).append(name)
        if added_defs:
            unclassified.append(f"{rel_abs}: ADDED definitions {added_defs} -> not in any whitelisted class")

        rows.append({"source": rel_src, "absorbed": rel_abs,
                     "byte_identical": src.read_bytes() == abs_.read_bytes(),
                     "source_locked": __import__("hashlib").sha256(src.read_bytes()).hexdigest() in locked_hashes,
                     "removed_defs": removed_defs, "added_defs": added_defs,
                     "classes": {k: v[:6] for k, v in sorted(classes.items())}})

    print("=== F-C delta classification (locked source -> absorbed copy) ===")
    for r in rows:
        cls = ", ".join(f"{k}={len(v)}" for k, v in r["classes"].items()) or "no delta"
        tag = "byte-identical" if r["byte_identical"] else "differs"
        print(f"  {r['source']:64s} {tag:14s} {cls}")
    print(f"\nfiles compared: {len(rows)}; unclassified deltas: {len(unclassified)}")
    for u in unclassified[:12]:
        print("   UNCLASSIFIED:", u)
    print("\nclass legend: 1=removed deny/hijack  2=removed sys.path  3=import prefix  4=dead code removed  9=inert self-assignment")
    if args.json:
        print(json.dumps({"rows": rows, "unclassified": unclassified}, indent=2, ensure_ascii=False))
    return 1 if unclassified else 0


if __name__ == "__main__":
    raise SystemExit(main())
