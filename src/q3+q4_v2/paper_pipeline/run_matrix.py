"""Run matched V1/V2 paper cases with resumable provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable

PACKAGE_PARENT = Path(__file__).resolve().parent.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from paper_pipeline.commands import build_command
from paper_pipeline.matrix import canonical_payload_hash


def _source_rows(case: dict) -> list[tuple]:
    rows = []
    for channel, position, radius, direction in zip(
        case["channels"],
        case["positions"],
        case["receive_radii"],
        case["directions"],
    ):
        rows.append(
            (
                int(channel),
                float(position[0]),
                float(position[1]),
                float(radius),
                direction is not None,
                None if direction is None else float(direction),
            )
        )
    return sorted(rows)


def _truth_rows(truth: list[dict]) -> list[tuple]:
    rows = []
    for row in truth:
        directional = bool(
            row.get("directional", row.get("orientation") is not None)
        )
        orientation = (
            None
            if not directional or row.get("orientation") is None
            else float(row["orientation"])
        )
        rows.append(
            (
                int(row["channel"]),
                float(row["x"]),
                float(row["y"]),
                float(row["r_eff"]),
                directional,
                orientation,
            )
        )
    return sorted(rows)


def ground_truth_matches_case(
    case: dict, truth: list[dict], tolerance: float = 1e-9
) -> bool:
    expected = _source_rows(case)
    actual = _truth_rows(truth)
    if len(expected) != len(actual):
        return False
    for lhs, rhs in zip(expected, actual):
        if lhs[0] != rhs[0] or lhs[4] != rhs[4]:
            return False
        for left, right in zip(lhs[1:4], rhs[1:4]):
            if not math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance):
                return False
        if lhs[5] is None or rhs[5] is None:
            if lhs[5] is not rhs[5]:
                return False
        elif not math.isclose(lhs[5], rhs[5], rel_tol=0.0, abs_tol=tolerance):
            return False
    return True


def _json_hash(payload: object) -> str:
    data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _load_case_sets(evidence_root: Path) -> dict[str, dict]:
    result = {}
    for question in ("q3", "q4"):
        path = evidence_root / "cases" / f"paper_{question}.json"
        result[question] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _selected_cases(case_set: dict, phase: str) -> list[dict]:
    cases = case_set["cases"]
    if phase == "main":
        return cases
    if phase == "smoke":
        return [cases[0]]
    selected = []
    for source_count in (10, 13, 16):
        selected.extend(
            [c for c in cases if c["source_count"] == source_count][:3]
        )
    return selected


def _already_closed(run_dir: Path, case: dict) -> bool:
    process_path = run_dir / "paper_process.json"
    metrics_path = run_dir / "metrics.json"
    verifier_path = run_dir / "verifier_report.json"
    if not all(path.is_file() for path in (process_path, metrics_path, verifier_path)):
        return False
    process = json.loads(process_path.read_text(encoding="utf-8"))
    return bool(
        process.get("exit_code") == 0
        and process.get("world_match") is True
        and process.get("case_payload_sha256") == canonical_payload_hash(case)
    )


def run_one(
    policy: str,
    case: dict,
    case_set_path: Path,
    evidence_root: Path,
    repo_root: Path,
    resume: bool,
) -> dict:
    run_dir = (
        evidence_root
        / "runs"
        / policy
        / case["question"]
        / case["case_id"]
    )
    if resume and _already_closed(run_dir, case):
        return {"policy": policy, "case_id": case["case_id"], "status": "reused"}
    run_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(policy, case, case_set_path, run_dir, repo_root)
    command_payload = {
        "argv": command,
        "case_payload_sha256": canonical_payload_hash(case),
        "policy": policy,
    }
    (run_dir / "paper_command.json").write_text(
        json.dumps(command_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    wall = time.monotonic() - started
    (run_dir / "paper_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "paper_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    truth_path = run_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.is_file() else []
    world_match = ground_truth_matches_case(case, truth) if truth else False
    process = {
        "policy": policy,
        "case_id": case["case_id"],
        "case_payload_sha256": canonical_payload_hash(case),
        "command_sha256": _json_hash(command_payload),
        "exit_code": completed.returncode,
        "wall_clock_s": wall,
        "world_match": world_match,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
    }
    (run_dir / "paper_process.json").write_text(
        json.dumps(process, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        **process,
        "status": "accepted" if completed.returncode == 0 and world_match else "failed",
        "run_dir": str(run_dir),
    }


def execute(
    repo_root: Path,
    evidence_root: Path,
    phase: str,
    policies: list[str],
    resume: bool,
) -> list[dict]:
    case_sets = _load_case_sets(evidence_root)
    rows = []
    for question, case_set in case_sets.items():
        case_set_path = evidence_root / "cases" / f"paper_{question}.json"
        for case in _selected_cases(case_set, phase):
            for policy in policies:
                rows.append(
                    run_one(
                        policy,
                        case,
                        case_set_path,
                        evidence_root,
                        repo_root,
                        resume,
                    )
                )
                status_path = evidence_root / "paired_run_status.json"
                status_path.write_text(
                    json.dumps({"runs": rows}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
    return rows


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[3])
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(__file__).parents[1] / "paper_evidence",
    )
    parser.add_argument("--phase", choices=("smoke", "pilot", "main"), default="pilot")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--policies", default="v1_frozen,v2_final", help="comma-separated policy ids"
    )
    args = parser.parse_args(argv)
    if args.workers != 1:
        parser.error("paper runs are deliberately serialized; use --workers 1")
    phase = "smoke" if args.smoke else args.phase
    policies = [value.strip() for value in args.policies.split(",") if value.strip()]
    rows = execute(
        args.repo_root.resolve(),
        args.evidence_root.resolve(),
        phase,
        policies,
        args.resume,
    )
    failed = [row for row in rows if row.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
