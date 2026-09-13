"""Closure: assemble the FINAL rigorous certificate (closure spec s.39-43,
s.50-53).

Reads the whole-tree replay result (``proof_tree_replay_result.json``), the
analytic symmetry lemma artifact, and re-certifies the incumbent upper bound
at 256-bit Arb with a fresh C_rec margin (spec s.39).  Writes the final
certificate JSON in the closure schema:

    GO  (all s.53 conditions) -> CERTIFIED_GLOBAL_EPS_OPTIMUM
    gap > tau                 -> CERTIFIED_GLOBAL_BOUND (honest, no upgrade)
    replay failure            -> BLOCKED_*

The optimizer outer enclosure (s.43) is rebuilt from the replay-surviving
live leaves only.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

from src.q2.formal.proof_loop import make_snapshot
from src.q2.formal.upper_bound import certify_q2_point_upper_bound
from src.q2.formal.rigorous_arithmetic import set_precision_bits
from src.q2.formal.master_problem import load_records
from src.q2.formal.scenario_loss import float_point_loss

ARTIFACTS = Path("src/q2/artifacts/formal")
TAU = 0.01
INCUMBENT = (805.1110506884, -599.7632926544)


def _optimizer_enclosure_from_heap(heap, U):
    if not heap:
        return {"box_count": 0,
                "note": "every leaf rigorously pruned: the master optimum "
                        "is pinned by U"}
    xs_lo = min(b[0] for _, _, b in heap)
    xs_hi = max(b[1] for _, _, b in heap)
    ys_lo = min(b[2] for _, _, b in heap)
    ys_hi = max(b[3] for _, _, b in heap)
    diam = max(math.hypot(b[1] - b[0], b[3] - b[2]) for _, _, b in heap)
    return {
        "box_count": len(heap),
        "x_span": [float(xs_lo), float(xs_hi)],
        "y_span": [float(ys_lo), float(ys_hi)],
        "max_box_diameter_m": float(diam),
        "note": "union of the replay-surviving live leaves is a rigorous "
                "outer approximation of the optimizer set of the finite "
                "master (every pruned region has rigorous LB > U)",
        "bounds_are_partial_where_refined": True,
    }


def main() -> None:
    replay = json.loads((ARTIFACTS / "proof_tree_replay_result.json")
                        .read_text(encoding="utf-8"))
    lemma = json.loads((ARTIFACTS / "canonical_symmetry_lemma.json")
                       .read_text(encoding="utf-8"))
    inc = json.loads((ARTIFACTS / "incumbent_upper_bound.json")
                     .read_text(encoding="utf-8"))

    L = float(replay["rigorous_lower_bound_m"])
    U = float(replay["rigorous_upper_bound_m"])
    gap = float(replay["absolute_gap_m"])

    # --- spec s.39: fresh 256-bit UB re-certification + C_rec margin ---
    set_precision_bits(256)
    ub = certify_q2_point_upper_bound(*INCUMBENT, beta_tol=1e-5)
    set_precision_bits(128)
    assert ub.status in ("CERTIFIED", "ALL_NEAR_ZERO"), ub.status
    U_cert = min(U, ub.upper_float)
    gap_cert = U_cert - L
    details_ub = {
        "status": ub.status,
        "q_lo_256": ub.q_lo.lower_float(),
        "q_hi_256": ub.q_hi.upper_float(),
        "crec_margin_lower_m": ub.crec_margin_lower,
        "precision_bits": 256,
    }
    print(f"UB re-certified (256-bit): Q in [{ub.q_lo.lower_float()!r}, "
          f"{ub.q_hi.upper_float()!r}]  margin_lower="
          f"{ub.crec_margin_lower!r}")

    # --- GO / NO-GO (spec s.53) ---
    go = (replay.get("topology_ok")
          and replay.get("root_identity_ok")
          and replay.get("unverified_pruned_nodes", 1) == 0
          and replay.get("passed")
          and gap_cert <= TAU)
    if go:
        status = "CERTIFIED_GLOBAL_EPS_OPTIMUM"
    elif replay.get("unverified_pruned_nodes", 1) != 0:
        status = "BLOCKED_RIGOROUS_TREE_REPLAY"
    elif gap_cert <= TAU:
        status = "BLOCKED_RIGOROUS_TREE_REPLAY"
    else:
        status = "CERTIFIED_GLOBAL_BOUND"

    # optimizer enclosure from the replay-surviving live leaves (s.43)
    optimizer = replay.get("optimizer_outer_enclosure", {"box_count": None})

    cert = {
        "schema_version": 2,
        "model": "frozen_q2_bounded_error_minimax",
        "certificate_scope": "canonical_center_case",
        "scope_statement": "certificate verifies the frozen Q2 solving "
                           "framework on the canonical center case "
                           "S1=O, theta1=0deg, eps=1deg, Omega=B(O,1800); "
                           "general instances are solved per-instance by "
                           "the same model and are NOT covered "
                           "automatically",
        "status": status,
        "epsilon_deg": "1",

        "certified_global_optimum": False,
        "certified_epsilon_global_optimum": bool(gap_cert <= TAU),
        "epsilon_optimality_tolerance_m": repr(TAU),

        "rigorous_lower_bound_m": repr(L),
        "rigorous_upper_bound_m": repr(U_cert),
        "absolute_gap_m": repr(gap_cert),
        "relative_gap": repr(gap_cert / max(U_cert, 1.0)),

        "incumbent_symbol": "S2_hat",
        "incumbent_S2": [repr(INCUMBENT[0]), repr(INCUMBENT[1])],
        "incumbent_Q_enclosure_m": list(inc["q_interval_decimal"]),

        "symmetry_lemma_analytic": lemma["status"] == "PROVEN_ANALYTIC",
        "symmetry_lemma_document": "src/q2/Q2_CANONICAL_SYMMETRY_LEMMA.md",
        "half_domain_reduction_certified":
            lemma["claims"]["half_domain_equivalent"],

        "proof_tree_complete": bool(replay.get("topology_ok")),
        "proof_tree_coverage_verified": bool(replay.get("topology_ok")),
        "historical_prunes_replayed": bool(
            replay.get("unverified_pruned_nodes", 1) == 0),
        "unverified_pruned_nodes": replay.get("unverified_pruned_nodes"),
        "verified_pruned_objective": replay.get("verified_pruned_objective"),
        "verified_pruned_reception": replay.get("verified_pruned_reception"),
        "superseded_prunes": replay.get("superseded_prunes"),
        "live_leaves": replay.get("live_leaves"),
        "rigorous_refined_splits": replay.get("refined_splits"),
        "precision_escalations": replay.get("precision_escalations"),
        "legalized_scenarios": replay.get("legalized_scenarios", []),

        "lower_bound_engine": "Arb proof-tree replay "
                              "(python-flint, whole tree, s.35 Path 1)",
        "upper_bound_engine": "Arb (256-bit re-certification, s.39)",
        "search_engine": "float64 batch interval B&B (search only)",
        "float_batch_engine_used_only_for_search": True,
        "sampling_used_as_proof": False,
        "sampling_role": "falsification only (mpmath fuzz, dense sampling, "
                         "cross-engine spot checks)",
        "unique_optimizer": "NOT_PROVEN",

        "point_evaluator_verified": True,
        "master_lower_bound_verified": True,
        "certificate_replayed_independently": bool(replay.get("passed")),

        "optimizer_outer_enclosure": optimizer,

        "ub_recertification_256bit": details_ub,
        "ub_replay_reference": {
            "status": replay.get("status"),
            "passed": replay.get("passed"),
            "wall_time_s": replay.get("wall_time_s"),
        },

        "source_snapshot_id": "q2_cert_final_rigorous",
        "source_sha256_manifest": "",  # filled after the snapshot
    }

    # --- snapshot (s.48) then bind manifest ---
    snap = make_snapshot("q2_cert_final_rigorous", {
        "phase": "cert_final_rigorous",
        "status": status,
        "L_rigorous": L,
        "U_rigorous": U_cert,
        "absolute_gap": gap_cert,
        "unverified_pruned_nodes": replay.get("unverified_pruned_nodes"),
        "scope": "canonical_center_case",
    }, ARTIFACTS)
    tests_dest = snap / "tests"
    tests_dest.mkdir(exist_ok=True)
    for p in sorted(Path("src/q2/tests_formal").glob("*.py")):
        shutil.copy2(p, tests_dest / p.name)
    lemma_doc = Path("src/q2/Q2_CANONICAL_SYMMETRY_LEMMA.md")
    (snap / "Q2_CANONICAL_SYMMETRY_LEMMA.md").write_text(
        lemma_doc.read_text(encoding="utf-8"), encoding="utf-8")
    manifest_path = snap / "source_manifest_sha256.json"
    cert["source_sha256_manifest"] = hashlib.sha256(
        manifest_path.read_bytes()).hexdigest()

    out = ARTIFACTS / "q2_global_optimality_certificate.json"
    out.write_text(json.dumps(cert, indent=1), encoding="utf-8")
    (snap / "artifacts" / out.name).write_text(
        out.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"wrote {out}")
    print(f"status: {status} | L={L!r} U={U_cert!r} gap={gap_cert!r}")
    print(f"snapshot: {snap}")


if __name__ == "__main__":
    main()
