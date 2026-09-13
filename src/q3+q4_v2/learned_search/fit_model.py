"""Fit the tiny learned-search model from decision trace JSONL files.

This is an offline utility, not a test. It uses a dependency-free ridge normal
equation and expects each selected candidate trace to contain ``features`` and
``target_remaining_loss`` fields produced by a later data collector.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("traces", nargs="+", type=Path)
    p.add_argument("--output", type=Path, default=Path(__file__).with_name("model_fitted.json"))
    p.add_argument("--ridge", type=float, default=1e-3)
    args = p.parse_args(argv)
    rows = []
    for path in args.traces:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if "features" in item and "target_remaining_loss" in item:
                    rows.append((list(map(float, item["features"])), float(item["target_remaining_loss"])))
    if not rows:
        raise SystemExit("no labelled feature rows")
    n = len(rows[0][0]) + 1
    gram = [[0.0] * n for _ in range(n)]
    vec = [0.0] * n
    for features, target in rows:
        x = [1.0] + features
        for i in range(n):
            vec[i] += x[i] * target
            for j in range(n):
                gram[i][j] += x[i] * x[j]
    for i in range(n):
        gram[i][i] += args.ridge
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(gram[r][col]))
        if abs(gram[pivot][col]) < 1e-12:
            raise SystemExit("singular feature matrix")
        gram[col], gram[pivot] = gram[pivot], gram[col]
        vec[col], vec[pivot] = vec[pivot], vec[col]
        scale = gram[col][col]
        gram[col] = [v / scale for v in gram[col]]
        vec[col] /= scale
        for row in range(n):
            if row == col:
                continue
            factor = gram[row][col]
            gram[row] = [a - factor * b for a, b in zip(gram[row], gram[col])]
            vec[row] -= factor * vec[col]
    output = {"schema": "learned_search_v1", "features": ["gain_per_cost", "cluster", "radius_norm", "distance_norm", "bearing_count", "unknown_pressure", "same_channel"], "weights": [-v for v in vec[1:]], "bias": -vec[0], "source": "ridge fit from labelled decision traces", "rows": len(rows), "ridge": args.ridge}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
