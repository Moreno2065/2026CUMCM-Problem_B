"""Aggregate matched paper runs and create traceable statistical claims."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Iterable

PACKAGE_PARENT = Path(__file__).resolve().parent.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from paper_pipeline.matrix import canonical_payload_hash


def accepted(metrics: dict) -> bool:
    complete = bool(
        metrics.get("complete", (metrics.get("status_summary") or {}).get("complete"))
    )
    total = metrics.get("sources_total")
    cleared = metrics.get("cleared_count")
    return bool(
        complete
        and total not in (None, 0)
        and cleared == total
        and metrics.get("verifier_all_ok") is True
    )


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def paired_effect(
    rows: list[dict], bootstrap_samples: int = 10_000, rng_seed: int = 20260913
) -> dict:
    by_case: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_hash"], {})[row["policy"]] = row
    pairs = [
        (values["v1_frozen"], values["v2_final"])
        for values in by_case.values()
        if "v1_frozen" in values and "v2_final" in values
    ]
    if not pairs:
        raise ValueError("no matched V1/V2 pairs")
    v1 = [float(pair[0]["t_per_source_s"]) for pair in pairs]
    v2 = [float(pair[1]["t_per_source_s"]) for pair in pairs]
    deltas = [right - left for left, right in zip(v1, v2)]
    mean_v1 = statistics.fmean(v1)
    mean_v2 = statistics.fmean(v2)
    reduction = 100.0 * (mean_v1 - mean_v2) / mean_v1
    rng = random.Random(rng_seed)
    boot_reductions = []
    n = len(pairs)
    for _ in range(bootstrap_samples):
        sampled = [pairs[rng.randrange(n)] for _ in range(n)]
        sampled_v1 = statistics.fmean(
            float(pair[0]["t_per_source_s"]) for pair in sampled
        )
        sampled_v2 = statistics.fmean(
            float(pair[1]["t_per_source_s"]) for pair in sampled
        )
        boot_reductions.append(100.0 * (sampled_v1 - sampled_v2) / sampled_v1)
    return {
        "n_pairs": n,
        "mean_v1_s": mean_v1,
        "mean_v2_s": mean_v2,
        "mean_delta_s": statistics.fmean(deltas),
        "median_delta_s": statistics.median(deltas),
        "relative_reduction_pct": reduction,
        "relative_reduction_ci95_low_pct": _quantile(boot_reductions, 0.025),
        "relative_reduction_ci95_high_pct": _quantile(boot_reductions, 0.975),
        "wins_v2": sum(right < left for left, right in zip(v1, v2)),
        "ties": sum(math.isclose(right, left) for left, right in zip(v1, v2)),
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": rng_seed,
    }


def summarize_variant_rows(rows: list[dict]) -> list[dict]:
    """Summarize only accepted efficiency values while retaining safety rate."""
    keys = sorted(
        {
            (row["variant_id"], row.get("question", ""), row.get("source_count", "all"))
            for row in rows
        },
        key=lambda item: (item[1], str(item[2]), item[0]),
    )
    output = []
    for variant_id, question, source_count in keys:
        group = [
            row for row in rows
            if row["variant_id"] == variant_id
            and row.get("question", "") == question
            and row.get("source_count", "all") == source_count
        ]
        valid = [row for row in group if row["accepted"]]
        times = [float(row["t_per_source_s"]) for row in valid]
        output.append(
            {
                "variant_id": variant_id,
                "question": question,
                "source_count": source_count,
                "n_runs": len(group),
                "n_accepted": len(valid),
                "acceptance_rate": len(valid) / len(group),
                "mean_t_per_source_s": statistics.fmean(times) if times else math.nan,
                "median_t_per_source_s": statistics.median(times) if times else math.nan,
                "p90_t_per_source_s": _quantile(times, 0.9) if times else math.nan,
            }
        )
    return output


def _case_lookup(evidence_root: Path) -> dict[str, dict]:
    lookup = {}
    for question in ("q3", "q4"):
        case_set = json.loads(
            (evidence_root / "cases" / f"paper_{question}.json").read_text(
                encoding="utf-8"
            )
        )
        for case in case_set["cases"]:
            lookup[case["case_id"]] = case
    return lookup


def load_run_rows(evidence_root: Path) -> list[dict]:
    cases = _case_lookup(evidence_root)
    rows = []
    for metrics_path in sorted((evidence_root / "runs").rglob("metrics.json")):
        relative = metrics_path.relative_to(evidence_root / "runs")
        if len(relative.parts) < 4:
            continue
        policy, question, case_id = relative.parts[:3]
        if policy not in ("v1_frozen", "v2_final") or case_id not in cases:
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        case = cases[case_id]
        process_path = metrics_path.parent / "paper_process.json"
        process = (
            json.loads(process_path.read_text(encoding="utf-8"))
            if process_path.is_file()
            else {}
        )
        complete = bool(
            metrics.get("complete", (metrics.get("status_summary") or {}).get("complete"))
        )
        sources_total = int(metrics["sources_total"])
        cleared_count = int(metrics["cleared_count"])
        row = {
            "policy": policy,
            "question": question,
            "case_id": case_id,
            "case_hash": canonical_payload_hash(case),
            "case_seed": int(case["case_seed"]),
            "source_count": int(case["source_count"]),
            "scenario": case["scenario"],
            "complete": complete,
            "verifier_all_ok": metrics.get("verifier_all_ok") is True,
            "world_match": process.get("world_match") is True,
            "cleared_count": cleared_count,
            "sources_total": sources_total,
            "clear_rate": cleared_count / sources_total,
            "t_per_source_s": float(
                metrics.get(
                    "t_per_source_s",
                    float(metrics["T_total_virtual"]) / sources_total,
                )
            ),
            "T_total_virtual": float(metrics["T_total_virtual"]),
            "T_move": float(metrics["T_move"]),
            "T_measure": float(metrics["T_measure"]),
            "T_switch": float(metrics["T_switch"]),
            "T_clear": float(metrics["T_clear"]),
            "move_distance_m": float(
                metrics.get("move_distance_m", metrics.get("total_move_distance_m"))
            ),
            "n_measures": int(metrics["n_measures"]),
            "n_switches": int(metrics["n_switches"]),
            "n_clear_attempts": int(metrics["n_clear_attempts"]),
            "parameter_sha256": metrics.get("parameter_sha256", "v1-frozen-config"),
            "metrics_path": str(metrics_path.relative_to(evidence_root)).replace("\\", "/"),
        }
        ledger = row["T_move"] + row["T_measure"] + row["T_switch"] + row["T_clear"]
        row["ledger_error_s"] = ledger - row["T_total_virtual"]
        row["accepted"] = bool(
            accepted(row)
            and row["world_match"]
            and abs(row["ledger_error_s"]) < 1e-6
        )
        rows.append(row)
    return rows


def _summary(rows: list[dict]) -> list[dict]:
    output = []
    keys = sorted({(r["policy"], r["question"], r["source_count"]) for r in rows})
    for policy, question, source_count in keys:
        group = [
            r for r in rows
            if r["policy"] == policy
            and r["question"] == question
            and r["source_count"] == source_count
        ]
        valid = [r for r in group if r["accepted"]]
        times = [r["t_per_source_s"] for r in valid]
        output.append(
            {
                "policy": policy,
                "question": question,
                "source_count": source_count,
                "n_runs": len(group),
                "n_accepted": len(valid),
                "completion_rate": len(valid) / len(group),
                "mean_t_per_source_s": statistics.fmean(times),
                "median_t_per_source_s": statistics.median(times),
                "p90_t_per_source_s": _quantile(times, 0.9),
                "max_t_per_source_s": max(times),
                "mean_total_virtual_s": statistics.fmean(
                    r["T_total_virtual"] for r in valid
                ),
                "mean_move_distance_m": statistics.fmean(
                    r["move_distance_m"] for r in valid
                ),
                "mean_measures": statistics.fmean(r["n_measures"] for r in valid),
                "mean_switches": statistics.fmean(r["n_switches"] for r in valid),
                "mean_clear_attempts": statistics.fmean(
                    r["n_clear_attempts"] for r in valid
                ),
            }
        )
    return output


def _load_variant_rows(evidence_root: Path, kind: str) -> list[dict]:
    cases = _case_lookup(evidence_root)
    rows = []
    root = evidence_root / kind
    if not root.is_dir():
        return rows
    for process_path in sorted(root.rglob("paper_process.json")):
        process = json.loads(process_path.read_text(encoding="utf-8"))
        metrics_path = process_path.parent / "metrics.json"
        parameters_path = process_path.parent / "parameters.json"
        if not metrics_path.is_file() or not parameters_path.is_file():
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        params = json.loads(parameters_path.read_text(encoding="utf-8"))
        case_id = process["case_id"]
        case = cases[case_id]
        sources_total = int(metrics["sources_total"])
        rows.append(
            {
                "kind": kind,
                "variant_id": process["variant_id"],
                "question": process["question"],
                "case_id": case_id,
                "case_hash": canonical_payload_hash(case),
                "case_seed": case["case_seed"],
                "source_count": case["source_count"],
                "accepted": process.get("accepted") is True,
                "verifier_all_ok": metrics.get("verifier_all_ok") is True,
                "cleared_count": metrics.get("cleared_count"),
                "sources_total": sources_total,
                "t_per_source_s": float(metrics["T_total_virtual"]) / sources_total,
                "T_total_virtual": float(metrics["T_total_virtual"]),
                "T_move": float(metrics["T_move"]),
                "T_measure": float(metrics["T_measure"]),
                "T_switch": float(metrics["T_switch"]),
                "T_clear": float(metrics["T_clear"]),
                "n_measures": int(metrics["n_measures"]),
                "n_switches": int(metrics["n_switches"]),
                "n_clear_attempts": int(metrics["n_clear_attempts"]),
                "parameter_sha256": process["parameter_sha256"],
                "parameters_json": json.dumps(
                    params["parameters"], ensure_ascii=False, sort_keys=True
                ),
                "metrics_path": str(metrics_path.relative_to(evidence_root)).replace("\\", "/"),
            }
        )
    return rows


def _add_full_model_deltas(rows: list[dict], summaries: list[dict]) -> None:
    by_key = {
        (row["variant_id"], row["case_hash"]): row
        for row in rows
        if row["accepted"]
    }
    for summary in summaries:
        question = summary["question"]
        full_id = f"{question}_full"
        pairs = []
        for row in rows:
            if (
                row["variant_id"] == summary["variant_id"]
                and row["source_count"] == summary["source_count"]
                and row["accepted"]
            ):
                full = by_key.get((full_id, row["case_hash"]))
                if full is not None:
                    pairs.append((full["t_per_source_s"], row["t_per_source_s"]))
        if pairs:
            mean_full = statistics.fmean(left for left, _ in pairs)
            mean_variant = statistics.fmean(right for _, right in pairs)
            summary["paired_n_vs_full"] = len(pairs)
            summary["paired_delta_vs_full_s"] = mean_variant - mean_full
            summary["paired_delta_vs_full_pct"] = (
                100.0 * (mean_variant - mean_full) / mean_full
            )
        else:
            summary["paired_n_vs_full"] = 0
            summary["paired_delta_vs_full_s"] = math.nan
            summary["paired_delta_vs_full_pct"] = math.nan


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"no rows for {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(evidence_root: Path) -> dict:
    rows = load_run_rows(evidence_root)
    if len(rows) != 240:
        raise ValueError(f"expected 240 matched run rows, found {len(rows)}")
    rejected = [row for row in rows if not row["accepted"]]
    if rejected:
        raise ValueError(f"{len(rejected)} runs failed acceptance gate")
    tables = evidence_root / "tables"
    _write_csv(tables / "run_level.csv", rows)
    summaries = _summary(rows)
    _write_csv(tables / "main_summary.csv", summaries)
    effects = []
    for question in ("q3", "q4"):
        for source_count in (None, 10, 13, 16):
            group = [
                row for row in rows
                if row["question"] == question
                and (source_count is None or row["source_count"] == source_count)
            ]
            effect = paired_effect(group)
            effect = {
                "question": question,
                "source_count": "all" if source_count is None else source_count,
                **effect,
            }
            effects.append(effect)
    _write_csv(tables / "paired_effects.csv", effects)
    variant_counts = {}
    for kind in ("ablation", "tuning"):
        variant_rows = _load_variant_rows(evidence_root, kind)
        if not variant_rows:
            continue
        summaries_for_kind = summarize_variant_rows(variant_rows)
        if kind == "ablation":
            _add_full_model_deltas(variant_rows, summaries_for_kind)
        _write_csv(tables / f"{kind}_run_level.csv", variant_rows)
        _write_csv(tables / f"{kind}_summary.csv", summaries_for_kind)
        variant_counts[kind] = len(variant_rows)
    claims = []
    for effect in effects:
        scope = f"{effect['question'].upper()}"
        if effect["source_count"] != "all":
            scope += f"，{effect['source_count']} 个源"
        claims.append(
            {
                "claim_id": f"paired_{effect['question']}_{effect['source_count']}",
                "status": "allowed",
                "scope": scope,
                "statement": (
                    f"在 {effect['n_pairs']} 个共同案例上，V2 相对 V1 的每源虚拟时间"
                    f"平均降低 {effect['relative_reduction_pct']:.1f}%"
                    f"（95% bootstrap CI "
                    f"{effect['relative_reduction_ci95_low_pct']:.1f}%–"
                    f"{effect['relative_reduction_ci95_high_pct']:.1f}%），"
                    f"其中 {effect['wins_v2']}/{effect['n_pairs']} 个案例更快。"
                ),
                "source_table": "tables/paired_effects.csv",
                "metric": "T_total_virtual / sources_total",
                "baseline": "V1 deterministic-certificate frozen baseline",
                "method": "V2 absorbed final engine",
            }
        )
    claims.append(
        {
            "claim_id": "acceptance_all_runs",
            "status": "allowed",
            "scope": "Q3/Q4 paired final evaluation",
            "statement": "240/240 次运行均完成全部清除、通过 verifier 且计时账本闭合。",
            "source_table": "tables/run_level.csv",
        }
    )
    claims_payload = {
        "schema_version": 1,
        "claim_boundary": (
            "Claims apply only to the held-out synthetic matched cases in this evidence set; "
            "they are not per-instance or global optimality guarantees."
        ),
        "claims": claims,
    }
    (evidence_root / "claims.json").write_text(
        json.dumps(claims_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = ["# 可引用结论", "", "所有性能结论仅适用于本次共同合成案例，不构成逐例或全局最优保证。", ""]
    md.extend(f"- `{claim['claim_id']}`：{claim['statement']}" for claim in claims)
    (evidence_root / "claims.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {
        "run_rows": len(rows),
        "summary_rows": len(summaries),
        "effects": effects,
        "variant_rows": variant_counts,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    aggregate(args.evidence_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
