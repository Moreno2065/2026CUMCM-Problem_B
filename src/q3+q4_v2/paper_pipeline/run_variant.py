"""Run verified ablation and parameter-sensitivity variants of final engines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Iterable

PACKAGE_PARENT = Path(__file__).resolve().parent.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from absorbed.adapters import absorbed_verifier, runtime_bridge
from absorbed.adapters.v3_client import AbsorbedSolverClient
from paper_pipeline.matrix import canonical_payload_hash
from paper_pipeline.variants import build_registry, effective_parameters


def select_cases(cases: list[dict], kind: str, phase: str) -> list[dict]:
    if kind == "ablation":
        selected = [case for case in cases if case["source_count"] in (10, 16)]
        if phase == "pilot":
            return [
                case for count in (10, 16)
                for case in [c for c in selected if c["source_count"] == count][:2]
            ]
        return selected
    selected = [case for case in cases if case["source_count"] == 13]
    return selected[:2] if phase == "pilot" else selected[:10]


def _engine(question: str):
    if question == "q3":
        from absorbed.q3_v5 import q3_optimizer_v5 as module
        return "q3-v5", module.VERSION, module.solve
    from absorbed.q4_v4 import strategy_v4 as module
    from absorbed.q4_v4 import locked
    return "q4-v4", locked.VERSION, module.solve


def _source_hash(question: str) -> str:
    path = PACKAGE_PARENT / "absorbed" / (
        "q3_v5/q3_optimizer_v5.py" if question == "q3" else "q4_v4/strategy_v4.py"
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _absent_count(question: str, result: dict) -> int:
    if question == "q3":
        return len(result.get("negative_observations") or {}) + len(
            result.get("count_inferred_absent_channels") or []
        )
    return len(result.get("absent_channels") or [])


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(runtime_bridge.json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_actions(path: Path, rows: list[dict]) -> None:
    fields = [
        "sequence", "path", "x", "y", "channel", "result",
        "movement_s", "switch_s", "operation_s", "virtual_before_s",
        "virtual_after_s",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            response = row.get("response") or {}
            position = row.get("position") or []
            writer.writerow(
                {
                    "sequence": row.get("sequence"),
                    "path": row.get("path"),
                    "x": position[0] if position else None,
                    "y": position[1] if position else None,
                    "channel": row.get("channel"),
                    "result": response.get("measure_result")
                    or response.get("clear_result")
                    or response.get("status"),
                    "movement_s": row.get("movement_s"),
                    "switch_s": row.get("switch_s"),
                    "operation_s": row.get("operation_s"),
                    "virtual_before_s": row.get("virtual_before_s"),
                    "virtual_after_s": row.get("virtual_after_s"),
                }
            )


def run_case(
    case: dict,
    variant_id: str,
    parameters: dict,
    output_dir: Path,
    resume: bool = True,
) -> dict:
    process_path = output_dir / "paper_process.json"
    if resume and process_path.is_file():
        process = json.loads(process_path.read_text(encoding="utf-8"))
        if process.get("accepted") is True:
            return process
    output_dir.mkdir(parents=True, exist_ok=True)
    question = case["question"]
    engine, version, solve = _engine(question)
    before_hash = _source_hash(question)
    handles = runtime_bridge.build_backend(
        "synthetic",
        mode=question.upper(),
        seed=case["case_seed"],
        n_sources=case["source_count"],
        scenario=case["scenario"],
        base_url="http://127.0.0.1:2026",
        robot_id="TEAM001",
        timeout=5.0,
    )
    client = AbsorbedSolverClient(handles["executor"], on_reject="raise")
    started = time.monotonic()
    failure = None
    result = None
    try:
        client.act("/enter")
        try:
            result = solve(client, **parameters)
        finally:
            client.act("/exit")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    wall = time.monotonic() - started
    simulator = handles.get("simulator")
    executor = handles.get("executor")
    fingerprint = runtime_bridge.parameter_fingerprint(parameters)
    params_meta = {
        "engine": engine,
        "name": variant_id,
        "version": version,
        "source": "paper_pipeline/variant_registry.json",
        "sha256": fingerprint["sha256"],
        "canonical_json_bytes": fingerprint["canonical_json_bytes"],
        "count": fingerprint["count"],
    }
    if isinstance(result, dict):
        result.update(version=version, parameters=parameters, paper_variant=variant_id)
    verifier = absorbed_verifier.verify_absorbed_run(
        question.upper(),
        engine,
        version,
        result,
        client,
        simulator=simulator,
        executor=executor,
        engine_meta=params_meta,
        socket_guard={"ok": True, "needs_sockets": False},
        sim="synthetic",
    )
    sources_total = len(getattr(simulator, "sources", []) or [])
    metrics = runtime_bridge.build_metrics(
        executor,
        mode=question.upper(),
        engine=engine,
        engine_version=version,
        cleared_count=len((result or {}).get("cleared_sources") or []),
        absent_count=_absent_count(question, result or {}),
        sources_total=sources_total,
        wall_clock_s=wall,
        verifier_all_ok=verifier["all_ok"],
        n_actions=len(client.rows),
        complete=failure is None and isinstance(result, dict),
        params_meta=params_meta,
        locked_name=variant_id,
        sim="synthetic",
        seed=case["case_seed"],
        n_sources=case["source_count"],
        scenario=case["scenario"],
    )
    metrics["variant_id"] = variant_id
    metrics["t_per_source_s"] = (
        metrics["T_total_virtual"] / sources_total if sources_total else None
    )
    after_hash = _source_hash(question)
    accepted = bool(
        failure is None
        and verifier["all_ok"]
        and metrics["cleared_count"] == sources_total
        and before_hash == after_hash
    )
    process = {
        "variant_id": variant_id,
        "question": question,
        "case_id": case["case_id"],
        "case_hash": canonical_payload_hash(case),
        "source_hash_before": before_hash,
        "source_hash_after": after_hash,
        "parameter_sha256": fingerprint["sha256"],
        "failure": failure,
        "accepted": accepted,
        "wall_clock_s": wall,
    }
    for name, payload in (
        ("metrics.json", metrics),
        ("verifier_report.json", verifier),
        ("engine_result.json", result),
        ("parameters.json", {"variant_id": variant_id, "parameters": parameters}),
        ("ground_truth.json", simulator.ground_truth()),
        ("paper_process.json", process),
    ):
        _write_json(output_dir / name, payload)
    _write_actions(output_dir / "actions.csv", list(client.rows))
    runtime_bridge.shutdown_backend(handles)
    return process


def _load_cases(evidence_root: Path, question: str) -> list[dict]:
    return json.loads(
        (evidence_root / "cases" / f"paper_{question}.json").read_text(encoding="utf-8")
    )["cases"]


def execute(evidence_root: Path, kind: str, phase: str, resume: bool) -> list[dict]:
    registry = build_registry()
    jobs = []
    if kind == "ablation":
        for variant in registry["variants"]:
            question = variant["question"]
            base = registry["base_parameters"][question]
            params = effective_parameters(base, variant["overrides"])
            for case in select_cases(_load_cases(evidence_root, question), kind, phase):
                jobs.append((variant["variant_id"], question, case, params))
    else:
        for sweep in registry["tuning"]:
            question = sweep["question"]
            base = registry["base_parameters"][question]
            for value in sweep["values"]:
                variant_id = f"{question}_{sweep['parameter']}_{str(value).replace('.', 'p')}"
                params = effective_parameters(base, {sweep["parameter"]: value})
                for case in select_cases(_load_cases(evidence_root, question), kind, phase):
                    jobs.append((variant_id, question, case, params))
    rows = []
    root = evidence_root / kind
    for variant_id, question, case, params in jobs:
        output = root / variant_id / question / case["case_id"]
        rows.append(run_case(case, variant_id, params, output, resume=resume))
        _write_json(root / f"{kind}_status.json", {"jobs": rows})
    return rows


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--kind", choices=("ablation", "tuning"), required=True)
    parser.add_argument("--phase", choices=("pilot", "main"), default="pilot")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    if args.registry and not args.registry.is_file():
        parser.error(f"registry not found: {args.registry}")
    rows = execute(args.evidence_root.resolve(), args.kind, args.phase, args.resume)
    return 1 if any(not row.get("accepted") for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
