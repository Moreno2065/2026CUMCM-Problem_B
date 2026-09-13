"""Build an explicit, content-addressed inventory of paper source files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable


SOURCE_ROLES = {
    "src/q3+q4_v2/Q3_Q4_Paper_Model_Narrative_v2.0.md": (
        "v1", "guarantee_narrative"
    ),
    "src/q3+4/code/configs/candidate_v1_FROZEN_CONFIG.yaml": (
        "v1", "frozen_baseline_config"
    ),
    "src/q3+4/code/cli.py": ("v1", "baseline_entry"),
    "src/q3+q4_v2/recommended.py": ("v2", "intermediate_policy"),
    "src/q3+q4_v2/production.py": ("v2", "intermediate_policy"),
    "src/q3+q4_v2/run.py": ("v2", "intermediate_entry"),
    "src/q3+q4_v2/absorbed/q3_v5/q3_optimizer_v5.py": (
        "v2", "final_engine"
    ),
    "src/q3+q4_v2/absorbed/q4_v4/strategy_v4.py": (
        "v2", "final_engine"
    ),
    "src/q3+q4_v2/absorbed/q4_v4/locked.py": (
        "v2", "final_engine_lock"
    ),
    "src/q3+q4_v2/absorbed/q4_v4/results/selection_lock.json": (
        "v2", "selection_evidence"
    ),
    "src/q3+q4_v2/absorbed/run_absorbed.py": ("v2", "final_entry"),
    "src/q3+q4_v2/absorbed/adapters/absorbed_verifier.py": (
        "v2", "independent_verifier"
    ),
    "src/q3+q4_v2/ABSORBED_SOLVERS_VERDICT.md": (
        "v2", "adoption_verdict"
    ),
    "src/q3+q4_v2/baseline/docs/performance_comparison_report.md": (
        "v1", "baseline_performance_report"
    ),
}


@dataclass(frozen=True)
class SourceManifest:
    records: list[dict]

    @property
    def by_relpath(self) -> dict[str, dict]:
        return {row["relpath"]: row for row in self.records}


def _record(repo_root: Path, relpath: str, generation: str, role: str) -> dict:
    path = repo_root / Path(relpath)
    data = path.read_bytes()
    stat = path.stat()
    return {
        "relpath": relpath,
        "generation": generation,
        "role": role,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mtime_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def build_source_manifest(repo_root: Path | str) -> SourceManifest:
    root = Path(repo_root).resolve()
    records = [
        _record(root, relpath, generation, role)
        for relpath, (generation, role) in SOURCE_ROLES.items()
    ]
    return SourceManifest(records=records)


def write_manifest(manifest: SourceManifest, output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "version_rule": (
            "Q3_Q4_Paper_Model_Narrative_v2.0.md is V1; all other "
            "listed files under q3+q4_v2 are classified explicitly."
        ),
        "records": manifest.records,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    write_manifest(build_source_manifest(args.repo_root), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
