"""Command-line interface for the frozen Q1 solver.

Default backend: Numba. Use --backend reference for the audited pure-Python path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from q1_geometry import measurements_from_dicts, solve_q1


def main() -> None:
    ap = argparse.ArgumentParser(description="CUMCM 2026 B Q1 localization solver")
    ap.add_argument("input", type=Path, help="JSON input file")
    ap.add_argument("--backend", choices=["numba", "reference"], default="numba")
    ap.add_argument("--verify", action="store_true", help="run independent SciPy/LP verifier")
    ap.add_argument("-o", "--output", type=Path, help="optional output JSON path")
    args = ap.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    epsilon = float(payload.get("epsilon_deg", 1.0))
    measurements = measurements_from_dicts(payload["measurements"])
    result = solve_q1(measurements, epsilon_deg=epsilon, backend=args.backend)

    out = result.as_dict()
    out["backend_requested"] = args.backend

    if args.verify:
        from q1_verify import verify_measurements

        out["verification"] = verify_measurements(
            measurements, main=result, epsilon_deg=epsilon
        )

    text = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
