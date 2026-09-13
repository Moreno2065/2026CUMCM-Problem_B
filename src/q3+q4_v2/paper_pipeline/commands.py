"""Subprocess command construction for fair V1/V2 paper runs."""

from __future__ import annotations

from pathlib import Path
import sys


POLICIES = ("v1_frozen", "v2_adaptive", "v2_final")


def _ensure_output_scope(output_dir: Path, repo_root: Path) -> Path:
    output = output_dir.resolve()
    allowed = (
        repo_root.resolve()
        / "src"
        / "q3+q4_v2"
        / "paper_evidence"
        / "runs"
    )
    try:
        output.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(
            f"output must stay under {allowed.as_posix()}"
        ) from exc
    return output


def build_command(
    policy: str,
    case: dict,
    case_set_path: Path | str,
    output_dir: Path | str,
    repo_root: Path | str,
) -> list[str]:
    if policy not in POLICIES:
        raise ValueError(f"unknown paper policy: {policy}")
    root = Path(repo_root).resolve()
    output = _ensure_output_scope(Path(output_dir), root)
    question = str(case["question"]).lower()

    if policy == "v1_frozen":
        return [
            sys.executable,
            str(root / "src/q3+4/code/cli.py"),
            "run",
            "--question",
            question,
            "--policy",
            "candidate_a1_a3",
            "--case",
            str(Path(case_set_path).resolve()),
            "--case-id",
            str(case["case_id"]),
            "--config",
            str(
                root
                / "src/q3+4/code/configs/candidate_v1_FROZEN_CONFIG.yaml"
            ),
            "--output",
            str(output),
            "--sim",
            "synthetic",
            "--max-steps",
            "20000",
        ]

    if policy == "v2_adaptive":
        return [
            sys.executable,
            str(root / "src/q3+q4_v2/run.py"),
            "--mode",
            question,
            "--sim",
            "synthetic",
            "--policy",
            "learned",
            "--seed",
            str(case["case_seed"]),
            "--n-sources",
            str(case["source_count"]),
            "--scenario",
            str(case["scenario"]),
            "--output-dir",
            str(output),
            "--max-steps",
            "20000",
        ]

    engine = {"q3": "q3-v5", "q4": "q4-v4"}[question]
    return [
        sys.executable,
        str(root / "src/q3+q4_v2/absorbed/run_absorbed.py"),
        "--mode",
        question,
        "--engine",
        engine,
        "--sim",
        "synthetic",
        "--seed",
        str(case["case_seed"]),
        "--n-sources",
        str(case["source_count"]),
        "--scenario",
        str(case["scenario"]),
        "--output-dir",
        str(output),
        "--quiet",
    ]
