"""Generate deterministic, matched synthetic cases for the paper evaluation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
from typing import Iterable


MATRIX_SPEC = {
    "q3": {"seed_start": 950000, "scenario": "random"},
    "q4": {"seed_start": 960000, "scenario": "mixed"},
}
SOURCE_COUNTS = (10, 13, 16)
SEEDS_PER_COUNT = 20


def _casefile_module(repo_root: Path):
    code_root = repo_root / "src" / "q3+4" / "code"
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    return importlib.import_module("experiment.casefile")


def canonical_payload_hash(case: dict) -> str:
    payload = {key: value for key, value in case.items() if key != "case_id"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_case_sets(repo_root: Path | str) -> dict[str, dict]:
    root = Path(repo_root).resolve()
    casefile = _casefile_module(root)
    result: dict[str, dict] = {}
    for question, spec in MATRIX_SPEC.items():
        cases = []
        for block_index, source_count in enumerate(SOURCE_COUNTS):
            first_seed = spec["seed_start"] + block_index * SEEDS_PER_COUNT
            for offset in range(SEEDS_PER_COUNT):
                seed = first_seed + offset
                case_id = f"paper_{question}_n{source_count}_s{seed}"
                cases.append(
                    casefile.generate_case(
                        question=question,
                        case_seed=seed,
                        case_id=case_id,
                        scenario=spec["scenario"],
                        n_sources=source_count,
                        error_field_type="random_fixed",
                    )
                )
        result[question] = {
            "set_name": f"paper_{question}_paired_v1_v2",
            "purpose": "paired final paper evaluation; never used for tuning",
            "question": question,
            "cases": cases,
        }
    return result


def write_case_sets(repo_root: Path | str, output_root: Path | str) -> list[Path]:
    root = Path(repo_root).resolve()
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    sets = build_case_sets(root)
    written = []
    manifest_rows = []
    for question, case_set in sets.items():
        path = destination / f"paper_{question}.json"
        path.write_text(
            json.dumps(case_set, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
        for case in case_set["cases"]:
            manifest_rows.append(
                {
                    "question": question,
                    "case_id": case["case_id"],
                    "case_seed": case["case_seed"],
                    "source_count": case["source_count"],
                    "scenario": case["scenario"],
                    "payload_sha256": canonical_payload_hash(case),
                }
            )
    manifest = {
        "schema_version": 1,
        "tuning_status": "held_out_final_evaluation_only",
        "source_counts": list(SOURCE_COUNTS),
        "seeds_per_count": SEEDS_PER_COUNT,
        "cases": manifest_rows,
    }
    manifest_path = destination / "matrix_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(manifest_path)
    return written


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[3])
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    write_case_sets(args.repo_root, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
