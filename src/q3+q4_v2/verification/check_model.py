"""Audit model arithmetic and copied evidence; NOT a new controller benchmark.

Standard library only. Run from any directory. Generated JSON includes the
executed checks, evidence hashes and explicit scope limitations.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "verification/model_checks.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def close(a, b, tol=1e-9):
    if not math.isclose(a, b, rel_tol=tol, abs_tol=tol):
        raise AssertionError(f"{a!r} != {b!r}")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_snapshot():
    manifest = read_json(ROOT / "SOURCE_MANIFEST.json")
    require(manifest["count"] == len(manifest["files"]), "manifest count")
    targets = set()
    for record in manifest["files"]:
        target = record["target"]
        require(target not in targets, f"duplicate manifest target: {target}")
        targets.add(target)
        path = (ROOT / target).resolve()
        require(path.is_relative_to(ROOT), f"target outside package: {target}")
        data = path.read_bytes()
        require(len(data) == record["bytes"], f"size changed: {target}")
        require(hashlib.sha256(data).hexdigest() == record["sha256"].lower(),
                f"hash changed: {target}")
    return {"copied_files_verified": len(targets), "method": "SHA-256 of package copies"}


def check_ledger(folder):
    metrics = read_json(folder / "metrics.json")
    with (folder / "actions.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    phases = defaultdict(float)
    row_total = 0.0
    for row in rows:
        cost = sum(float(row[key]) for key in
                   ("movement_time", "switch_time", "action_time"))
        row_total += cost
        phases[row["policy_mode"]] += cost
    total = metrics["T_total_virtual"]
    close(sum(metrics[key] for key in ("T_move", "T_measure", "T_switch", "T_clear")),
          total, 1e-7)
    close(row_total, total, 1e-7)
    close(metrics["T_move"], metrics["total_move_distance_m"] / 5)
    close(metrics["T_measure"], 5 * metrics["n_measures"])
    close(metrics["T_switch"], metrics["n_switches"])
    close(metrics["T_clear"], 3 * metrics["n_clear_attempts"] + 2 * metrics["n_clear_success"])
    return metrics, dict(phases)


def check_history():
    evidence = ROOT / "baseline/evidence"
    q3, phases = check_ledger(evidence / "q3_official_v3")
    close(q3["T_total_virtual"], 6192.722578)
    require(q3["sources_total"] is None, "must not infer official hidden source count")
    q4 = []
    for folder in sorted((evidence / "q4_e1_matched").iterdir()):
        metrics, _ = check_ledger(folder)
        truth = read_json(folder / "ground_truth.json")
        n = len(truth)
        require(n == metrics["sources_total"] == metrics["cleared_count"], "Q4 counts")
        require(len({s["channel"] for s in truth}) == n, "duplicate truth channel")
        q4.append({"case": folder.name, "source_count": n,
                   "directional_count": sum(s["directional"] for s in truth),
                   "time_s": metrics["T_total_virtual"],
                   "seconds_per_source": metrics["T_total_virtual"] / n})
    require([(r["source_count"], r["directional_count"]) for r in q4] ==
            [(10, 10), (12, 12), (10, 10), (10, 10), (10, 10), (14, 4)], "Q4 scenario mix")
    mean_q4 = sum(r["seconds_per_source"] for r in q4) / len(q4)
    close(mean_q4, 1077.72193937453)
    return {"q3": {"total_time_s": q3["T_total_virtual"],
                    "cleared_count": q3["cleared_count"], "initial_source_count": None,
                    "seconds_per_cleared": q3["T_total_virtual"] / q3["cleared_count"],
                    "move_fraction": q3["T_move"] / q3["T_total_virtual"],
                    "measure_switch_fraction": (q3["T_measure"] + q3["T_switch"]) / q3["T_total_virtual"],
                    "phase_costs_s": phases,
                    "mechanical_cert_deletion_per_cleared":
                    (q3["T_total_virtual"] - phases["certificate"]) / q3["cleared_count"],
                    "cert_deletion_is_executable_or_lower_bound": False},
            "q4_mean_per_case_seconds_per_source": mean_q4, "q4_cases": q4}


def cardinality_weights(likelihoods, lo, hi):
    coef = [1.0]
    for absent, present in likelihoods:
        nxt = [0.0] * (len(coef) + 1)
        for i, value in enumerate(coef):
            nxt[i] += value * absent
            nxt[i + 1] += value * present
        coef = nxt
    count = len(likelihoods)
    return {n: coef[n] / math.comb(count, n) / (hi - lo + 1)
            for n in range(lo, hi + 1)}


def check_cardinality():
    likelihoods = [(0.2, 0.8), (0, 0.4), (1, 0.5), (0.3, 0.7),
                   (0.9, 0.1), (1, 1), (0.8, 0.3)]
    weights = cardinality_weights(likelihoods, 2, 4)
    brute = dict.fromkeys(range(2, 5), 0.0)
    for bits in itertools.product((0, 1), repeat=7):
        n = sum(bits)
        if n in brute:
            value = math.prod(likelihoods[i][bit] for i, bit in enumerate(bits))
            brute[n] += value / math.comb(7, n) / 3
    for n in weights:
        close(weights[n], brute[n])
    prior = cardinality_weights([(1, 1)] * 20, 10, 16)
    for value in prior.values():
        close(value, 1 / 7)
    known16 = [(0, 1)] * 16 + [(1, 1)] * 4
    weights16 = cardinality_weights(known16, 10, 16)
    close(sum(weights16.values()), weights16[16])
    outsider_present = cardinality_weights(known16[:16] + [(0, 1)] + known16[17:], 10, 16)
    close(sum(outsider_present.values()), 0)
    weights10 = cardinality_weights([(0, 1)] * 10 + [(1, 1)] * 10, 10, 16)
    require(sum(weights10[n] for n in range(11, 17)) > 0, "10 detected cannot close all channels")
    # Independent ternary enumeration checks the Q4 mixed-type extension.
    typed_likelihoods = [(0.3, 0.4, 0.8), (0, 0.7, 0.2), (1, 0.2, 0.6),
                         (0.8, 0.5, 0.4), (1, 1, 1)]
    pi = 0.37

    def mixed_weights(liks):
        coef = {(0, 0): 1.0}
        for absent, omni, directional in liks:
            nxt = defaultdict(float)
            for (n, k), value in coef.items():
                nxt[n, k] += value * absent
                nxt[n + 1, k] += value * (1 - pi) * omni
                nxt[n + 1, k + 1] += value * pi * directional
            coef = nxt
        return {n: sum(coef.get((n, k), 0) for k in range(1, n)) /
                (math.comb(len(liks), n) * (1 - (1 - pi) ** n - pi ** n) * 3)
                for n in range(2, 5)}

    mixed = mixed_weights(typed_likelihoods)
    enumerated = dict.fromkeys(range(2, 5), 0.0)
    for types in itertools.product((0, 1, 2), repeat=5):
        n, k = sum(t != 0 for t in types), sum(t == 2 for t in types)
        if n in enumerated and 1 <= k < n:
            value = math.prod(typed_likelihoods[i][t] * (1 if t == 0 else
                              ((1 - pi) if t == 1 else pi)) for i, t in enumerate(types))
            enumerated[n] += value / (math.comb(5, n) * (1 - (1 - pi) ** n - pi ** n) * 3)
    for n in mixed:
        close(mixed[n], enumerated[n])
    for value in mixed_weights([(1, 1, 1)] * 5).values():
        close(value, 1 / 3)
    return {"enumerated_worlds": 128, "DP_matches_enumeration": True,
            "unobserved_N_prior_preserved": True, "known16_outside_existence_probability": 0,
            "known10_can_still_have_undetected_sources": True,
            "Q4_typed_worlds_enumerated": 243, "Q4_mixed_DP_matches_enumeration": True,
            "Q4_mixed_unobserved_N_prior_preserved": True}


def check_probe():
    p = 4 / 9
    v0 = 60
    # Independent explicit branch sum: success costs 5; failure costs 3+60.
    branch_sum = p * 5 + (1 - p) * (3 + v0)
    close(branch_sum, 3 + 2 * p + (1 - p) * v0)
    close(branch_sum, 37.22222222222222)
    thresholds = {}
    for detour in (0, 40):
        threshold = (detour + 3) / (v0 - 2)
        close(detour + 3 + 2 * threshold + (1 - threshold) * v0, v0)
        thresholds[str(detour)] = threshold
    return {"illustrative_only": True, "success_probability": p,
            "expected_cost_s": branch_sum, "saving_vs_60_s": v0 - branch_sum,
            "break_even_probability_by_detour_seconds": thresholds}


def check_visibility_orientation():
    def visible(point, radius=1000):
        return math.hypot(*point) <= radius and point[0] >= 0
    require(not visible((-10, 0)) and math.hypot(-10, 0) <= 20,
            "blind side clear can succeed")
    require(visible((0, 10)), "closed directional boundary")
    require(not visible((-1, 0)), "near is not sufficient without visibility")
    angles = [(i + 0.5) * 2 * math.pi / 36000 for i in range(36000)]
    first = [a for a in angles if math.cos(a) >= 0]
    second = [a for a in first if math.sin(a) < 0]
    old_fraction = len(first) / len(angles)
    ratio = len(second) / len(first)
    close(old_fraction, 0.5)
    close(ratio, 0.5)
    close(old_fraction * ratio, 0.25)
    # Reapplying the same inequality changes no membership: incremental weight 1.
    repeated = [a for a in second if math.sin(a) < 0]
    close(len(repeated) / len(second), 1)
    return {"blind_side_clear": True, "closed_halfplane_boundary": True,
            "orientation_marginal_fraction": 0.25, "repeated_constraint_weight": 1.0,
            "scope": "local ideal half-plane example, not posterior engine verification"}


def check_cost_sequence():
    # Costs computed from an explicit serial sequence; true clear outcomes are supplied.
    actions = [("measure", (100, 0), 4, False), ("clear", (100, 0), 9, False),
               ("measure", (100, 0), 4, False), ("clear", (100, 0), 4, True),
               ("measure", (100, 100), 9, False)]
    p, frequency, total, switches = (0, 0), 1, 0, 0
    for kind, point, channel, success in actions:
        total += math.dist(p, point) / 5
        if kind == "measure":
            switched = channel != frequency
            total += 5 + switched
            switches += switched
            frequency = channel
        else:
            total += 3 + 2 * success
        p = point
    close(total, 65)
    require(switches == 2 and frequency == 9, "clear must preserve measurement channel")
    return {"serial_example_cost_s": total, "switch_count": switches,
            "ending_measurement_channel": frequency}


def mst_disk_bound(centers):
    points = [(0, 0)] + centers
    radii = [0] + [20] * len(centers)
    done, total = {0}, 0.0
    while len(done) < len(points):
        cost, target = min((max(0, math.dist(points[i], points[j]) - radii[i] - radii[j]), j)
                           for i in done for j in range(len(points)) if j not in done)
        total += cost
        done.add(target)
    return 5 * len(centers) + total / 5


def check_bound():
    rng = random.Random(20260911)
    smallest_gap = float("inf")
    for _ in range(100):
        n = rng.randint(2, 16)
        centers = []
        for _ in range(n):
            radius, angle = 1800 * math.sqrt(rng.random()), rng.random() * 2 * math.pi
            centers.append((radius * math.cos(angle), radius * math.sin(angle)))
        lb = mst_disk_bound(centers)
        rng.shuffle(centers)
        route = [(0, 0)]
        for x, y in centers:
            radius, angle = 20 * math.sqrt(rng.random()), rng.random() * 2 * math.pi
            route.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
        feasible = 5 * n + sum(math.dist(a, b) for a, b in zip(route, route[1:])) / 5
        require(lb <= feasible + 1e-9, "lower bound exceeds sampled feasible route")
        smallest_gap = min(smallest_gap, feasible - lb)
    return {"sampled_feasible_routes": 100, "smallest_route_minus_bound_s": smallest_gap,
            "scope": "numerical sanity check; general proof is in model section 10"}


def check_metrics_conventions():
    per_case_mean = (1000 / 10 + 800 / 16) / 2
    pooled = (1000 + 800) / (10 + 16)
    close(per_case_mean, 75)
    require(abs(per_case_mean - pooled) > 1, "mean and pooled ratio must differ")
    upper = 1 - 0.05 ** (1 / 1000)
    close(upper, 0.0029912495450953314)
    return {"per_case_mean_example": per_case_mean, "pooled_ratio_example": pooled,
            "Q3_reference_seconds_per_source": 2820 / 16,
            "zero_failures_1000_one_sided_95pct_failure_upper": upper}


def check_links():
    files = [ROOT / "README.md", ROOT / "MODEL_PERFORMANCE_V2.md",
             ROOT / "IMPLEMENTATION_SEQUENCE.md", ROOT / "references/SOURCES_AND_DECISIONS.md"]
    checked = 0
    for doc in files:
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#")):
                continue
            path = (doc.parent / target.split("#")[0]).resolve()
            require(path.is_relative_to(ROOT), f"new document link outside package: {target}")
            if path != REPORT:
                require(path.exists(), f"broken link in {doc.name}: {target}")
            checked += 1
    for name in ("problem.txt", "attachment1.txt", "attachment2.txt"):
        require((ROOT / "inputs" / name).stat().st_size > 100, f"empty extracted text: {name}")
    return {"internal_links_checked": checked, "extracted_input_texts": 3,
            "legacy_document_links_excluded": True}


def main():
    functions = [check_snapshot, check_history, check_cardinality, check_probe,
                 check_visibility_orientation, check_cost_sequence, check_bound,
                 check_metrics_conventions, check_links]
    results = []
    for function in functions:
        try:
            detail = function()
            results.append({"name": function.__name__, "passed": True, "detail": detail})
        except Exception as exc:
            results.append({"name": function.__name__, "passed": False,
                            "error": f"{type(exc).__name__}: {exc}"})
    passed = all(result["passed"] for result in results)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "scope": "model arithmetic, local relations, copied provenance and historical ledgers",
              "new_controller_implemented": False, "new_policy_benchmarked": False,
              "new_model_trained": False, "all_checks_passed": passed,
              "check_count": len(results), "checks": results,
              "model_sha256": hashlib.sha256((ROOT / "MODEL_PERFORMANCE_V2.md").read_bytes()).hexdigest()}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_passed": passed, "check_count": len(results),
                      "failed": [r for r in results if not r["passed"]], "report": str(REPORT)},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
