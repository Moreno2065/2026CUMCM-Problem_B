"""Scan the workspace for every seed actually used by a run.

The earlier "unused holdout" check looked at *directory names*, which misses runs
whose seed lives only inside ``provenance.json`` / ``policy_config.json`` and
misses anything created after the check.  This tool walks the whole workspace,
reads those JSON files, and reports the seed set really consumed.

Usage:
  python -X utf8 tools/seed_usage_scan.py [--candidates 700001,700002,...] [--json out.json]

Prints: number of scanned files, the sorted set of seeds found (with per-seed
file counts), and for --candidates whether each one is virgin (0 hits).
"""

from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_KEYS = ("case_seed", "seed", "scenario_seed")
SEED_RE = re.compile(r"(?<!\d)(\d{3,7})(?!\d)")


def scan() -> tuple[Counter, int]:
    hits: Counter = Counter()
    files = 0
    patterns = [
        "**/provenance.json",
        "**/policy_config.json",
        "**/ground_truth.json",
        "**/run_report.json",
        "**/metrics.json",
    ]
    seen_paths: set[str] = set()
    for pat in patterns:
        for raw in glob.glob(str(ROOT / pat), recursive=True):
            if raw in seen_paths:
                continue
            seen_paths.add(raw)
            if "__pycache__" in raw:
                continue
            p = Path(raw)
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            files += 1
            found: set[int] = set()

            def walk(node, key=None):
                if isinstance(node, dict):
                    for k, v in node.items():
                        walk(v, k)
                elif isinstance(node, list):
                    for v in node:
                        walk(v, key)
                else:
                    if key in SEED_KEYS and isinstance(node, (int, float)):
                        try:
                            found.add(int(node))
                        except (TypeError, ValueError):
                            pass
                    elif isinstance(node, str) and key in SEED_KEYS:
                        m = SEED_RE.search(node)
                        if m:
                            found.add(int(m.group(1)))

            walk(data)
            for s in found:
                hits[s] += 1
    return hits, files


def main(argv: list[str]) -> int:
    cands: list[int] = []
    dest = ROOT / "tuning_runs" / "seed_usage_scan.json"
    args = list(argv[1:])
    if "--candidates" in args:
        i = args.index("--candidates")
        cands = [int(x) for x in args[i + 1].split(",")]
    hits, files = scan()
    small = {s: c for s, c in hits.items() if s <= 100000}
    big = {s: c for s, c in hits.items() if s > 100000}
    print(f"scanned files: {files}")
    print(f"distinct seeds (<=100000): {len(small)}")
    print("  " + ", ".join(f"{s}x{c}" for s, c in sorted(small.items())))
    if big:
        print(f"distinct seeds (>100000): {len(big)}")
        print("  " + ", ".join(f"{s}x{c}" for s, c in sorted(big.items())[:60]))
    for s in cands:
        print(f"candidate {s}: {'VIRGIN' if hits[s] == 0 else f'{hits[s]} hits'}")
    out = {
        "scanned_files": files,
        "seeds_small": {str(k): v for k, v in sorted(small.items())},
        "seeds_big": {str(k): v for k, v in sorted(big.items())},
        "candidates": {str(s): hits[s] for s in cands},
    }
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
