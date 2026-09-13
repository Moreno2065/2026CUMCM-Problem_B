"""Full proof-tree recording for the finite master B&B (closure spec s.17-19,
s.31-32, s.47).

The fast float64 batch engine remains the SEARCH engine; this module turns it
into a *recorded* search: every split and every prune decision of the master
is appended to a proof tree with exact (dyadic) box endpoints, so an
independent rigorous verifier can later replay the whole tree
(``proof_tree_replay.py``).

Node record (spec s.19):

    node_id (list slot), parent_id, depth,
    x/y interval endpoints - exact dyadic rationals (every float64 IS the
        exact rational m*2^e; the verifier re-derives it via
        float.as_integer_ratio, so no endpoint semantics are lost),
    status: LIVE -> SPLIT | PRUNED_OBJECTIVE_BOUND | PRUNED_INFEASIBLE_RECEPTION
            | LIVE_FINAL,
    fast claimed lower bound lb_fast,
    split axis / exact split value / children ids,
    prune reason + triggering scenario hint (prune_scen).

Per-scenario fast lower bounds are NOT stored per node; they are exactly
recoverable from the endpoints with the deterministic batch kernel
(``scenario_loss_lower_batch``), which the verifier uses as an evaluation
ORDER hint only - all proof decisions are made by the Arb engine.

Prune reasons (spec s.23):

    PRUNE_A  objective lower bound  lb > U   (strict, matching the master's
             own convention ``keep &= c_lb <= U``);
    PRUNE_B  verified outside relaxed domain D_k: box strictly outside a
             witness ball.

The recording is pure observation: with ``recorder=None`` the master's
float64 arithmetic is bit-for-bit unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

STATUS_LIVE = 0
STATUS_SPLIT = 1
STATUS_PRUNE_A = 2
STATUS_PRUNE_B = 3
STATUS_LIVE_FINAL = 4

STATUS_NAMES = {
    STATUS_LIVE: "LIVE",
    STATUS_SPLIT: "SPLIT",
    STATUS_PRUNE_A: "PRUNED_OBJECTIVE_BOUND",
    STATUS_PRUNE_B: "PRUNED_INFEASIBLE_RECEPTION",
    STATUS_LIVE_FINAL: "LIVE_FINAL",
}


class TreeRecorder:
    """Accumulates proof-tree nodes while the master search runs."""

    def __init__(self, b0: tuple[float, float, float, float], u_cert: float,
                 n_scenarios: int):
        self.b0 = tuple(float(v) for v in b0)
        self.u_cert = float(u_cert)
        self.n_scenarios = int(n_scenarios)
        self.t0 = time.time()
        # node attributes; list slot == node_id (root = 0)
        self.parent: list[int] = [-1]
        self.depth: list[int] = [0]
        self.xlo: list[float] = [self.b0[0]]
        self.xhi: list[float] = [self.b0[1]]
        self.ylo: list[float] = [self.b0[2]]
        self.yhi: list[float] = [self.b0[3]]
        self.status: list[int] = [STATUS_LIVE]
        self.lb_fast: list[float] = [0.0]
        self.split_axis: list[int] = [-1]        # 0=x, 1=y, -1=leaf
        self.split_value: list[float] = [math.nan]
        self.left: list[int] = [-1]
        self.right: list[int] = [-1]
        self.prune_scen: list[int] = [-2]        # -2 n/a, -1 accumulated-max
        self.events: list[dict] = []
        self.n_nodes = 1
        self.counts = {STATUS_NAMES[s]: 0 for s in
                       (STATUS_SPLIT, STATUS_PRUNE_A, STATUS_PRUNE_B,
                        STATUS_LIVE_FINAL)}

    # -- node creation ---------------------------------------------------
    def _new_node(self, parent: int, depth: int, box, status: int,
                  lb: float) -> int:
        nid = self.n_nodes
        self.n_nodes += 1
        self.parent.append(parent)
        self.depth.append(depth)
        self.xlo.append(box[0]); self.xhi.append(box[1])
        self.ylo.append(box[2]); self.yhi.append(box[3])
        self.status.append(status)
        self.lb_fast.append(lb)
        self.split_axis.append(-1); self.split_value.append(math.nan)
        self.left.append(-1); self.right.append(-1)
        self.prune_scen.append(-2)
        if status in (STATUS_SPLIT, STATUS_PRUNE_A, STATUS_PRUNE_B,
                      STATUS_LIVE_FINAL):
            self.counts[STATUS_NAMES[status]] += 1
        return nid

    # -- hooks called by BatchMaster ---------------------------------------
    def register_root(self) -> None:
        self.on_event("root", box=list(self.b0))

    def on_split(self, parent_node: int, parent_depth: int, parent_box,
                 parent_lb: float, axis: int, value: float,
                 left_box, left_lb: float, left_pruned: int | None,
                 left_scen_hint: int,
                 right_box, right_lb: float, right_pruned: int | None,
                 right_scen_hint: int) -> tuple[int, int, bool, bool]:
        """Register a split of the existing live node ``parent_node``.

        The live node is converted IN PLACE into a SPLIT node (its box and
        fast lb are already stored); both children become new nodes: a kept
        child starts as LIVE (the master may split or prune it later); a
        child the fast engine pruned immediately becomes a terminal leaf
        with the given prune status.
        Returns (left_id, right_id, left_alive, right_alive).
        """
        pid = parent_node
        self.status[pid] = STATUS_SPLIT
        self.lb_fast[pid] = parent_lb
        self.split_axis[pid] = axis
        self.split_value[pid] = value
        self.counts[STATUS_NAMES[STATUS_SPLIT]] += 1

        def child(box, lb, pruned_status, scen_hint):
            if pruned_status is None:
                return self._new_node(pid, parent_depth + 1, box,
                                      STATUS_LIVE, lb), True
            nid = self._new_node(pid, parent_depth + 1, box,
                                 pruned_status, lb)
            self.prune_scen[nid] = scen_hint
            return nid, False

        lid, l_alive = child(left_box, left_lb, left_pruned, left_scen_hint)
        rid, r_alive = child(right_box, right_lb, right_pruned,
                             right_scen_hint)
        self.left[pid] = lid
        self.right[pid] = rid
        return lid, rid, l_alive, r_alive

    def on_prune_existing(self, node_id: int, reason: int,
                          scen_hint: int) -> None:
        """Mark an existing live node as pruned (bulk prune via _restrict)."""
        self.status[node_id] = reason
        self.prune_scen[node_id] = scen_hint
        self.counts[STATUS_NAMES[reason]] += 1

    def on_event(self, kind: str, **meta) -> None:
        self.events.append({"kind": kind,
                            "t_s": round(time.time() - self.t0, 3), **meta})


@dataclass
class TreeMeta:
    b0: tuple[float, float, float, float]
    u_cert: float
    tol: float
    round_cap: int
    max_boxes: int
    witness_count: int
    scenario_count: int
    g0_anchor: tuple[float, float]


def finalize_and_save(master, recorder: TreeRecorder, meta: TreeMeta,
                      out_dir: Path) -> dict:
    """Mark surviving live boxes LIVE_FINAL and write the tree artifacts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for nid in master.rec_node:
        recorder.status[nid] = STATUS_LIVE_FINAL
    live_final = recorder.status.count(STATUS_LIVE_FINAL)
    recorder.counts[STATUS_NAMES[STATUS_LIVE_FINAL]] = live_final
    n = recorder.n_nodes
    npz_path = out_dir / "proof_tree.npz"
    np.savez_compressed(
        npz_path,
        status=np.array(recorder.status, dtype=np.int8),
        parent=np.array(recorder.parent, dtype=np.int64),
        depth=np.array(recorder.depth, dtype=np.int32),
        xlo=np.array(recorder.xlo, dtype=np.float64),
        xhi=np.array(recorder.xhi, dtype=np.float64),
        ylo=np.array(recorder.ylo, dtype=np.float64),
        yhi=np.array(recorder.yhi, dtype=np.float64),
        lb_fast=np.array(recorder.lb_fast, dtype=np.float64),
        split_axis=np.array(recorder.split_axis, dtype=np.int8),
        split_value=np.array(recorder.split_value, dtype=np.float64),
        left=np.array(recorder.left, dtype=np.int64),
        right=np.array(recorder.right, dtype=np.int64),
        prune_scen=np.array(recorder.prune_scen, dtype=np.int16),
    )
    index = {
        "root_box": list(recorder.b0),
        "root_note": "B0^- = [G0x-1000, G0x+1000] x [G0y-1000, 0] with "
                     "G0=(1000,0) a verified A1 anchor (spec s.20); "
                     "dyadic endpoints",
        "u_cert_decimal": repr(meta.u_cert),
        "upper_bound_at_decision": "constant for every node = u_cert_decimal "
                                   "(single strict global UB throughout)",
        "tol": meta.tol,
        "round_cap": meta.round_cap,
        "max_boxes": meta.max_boxes,
        "witness_count": meta.witness_count,
        "scenario_count": meta.scenario_count,
        "g0_anchor": list(meta.g0_anchor),
        "node_count": n,
        "status_counts": recorder.counts,
        "live_final_count": live_final,
        "master_lower_bound_fast": (float(master.lb.min())
                                    if master.lb.size else None),
        "live_boxes": int(master.lb.size),
        "endpoints_exact": "float64 values are exact dyadic rationals m*2^e; "
                           "split midpoints exact in binary64 for widths "
                           ">= 1e-9 (min_width), far above the 2^-53 ulp "
                           "scale at these magnitudes",
        "prune_convention": "PRUNE_A iff fast_lb > U (strict), matching the "
                            "master's own rule keep &= lb <= U",
        "scenario_lower_bounds_recovery": "per-scenario fast bounds are "
                                          "recoverable from endpoints via "
                                          "batch_kernel.scenario_loss_lower_batch",
        "events": recorder.events,
        "wall_time_s": round(time.time() - recorder.t0, 1),
    }
    (out_dir / "proof_tree_index.json").write_text(
        json.dumps(index, indent=1), encoding="utf-8")
    manifest = {
        "schema": "q2-proof-tree-v1",
        "files": {
            "proof_tree.npz": hashlib.sha256(npz_path.read_bytes()).hexdigest(),
            "proof_tree_index.json": hashlib.sha256(
                (out_dir / "proof_tree_index.json").read_bytes()).hexdigest(),
        },
        "search_engine": "float64 batch interval B&B (search only, spec s.16)",
        "certificate_engine": "Arb proof-tree replay (proof_tree_replay.py)",
        "old_tree_status": "OLD_TREE_NOT_REPLAYABLE: the historical runs did "
                           "not record a tree; per spec s.32 the master was "
                           "re-run with identical frozen cuts (9 scenarios, "
                           "20 witnesses), identical incumbent U, identical "
                           "root domain and tolerance, with tree recording "
                           "enabled. This is a re-recorded proof tree, not a "
                           "model change.",
        "meta": {
            "b0": list(meta.b0), "u_cert": repr(meta.u_cert),
            "tol": meta.tol, "round_cap": meta.round_cap,
            "max_boxes": meta.max_boxes,
            "witness_count": meta.witness_count,
            "scenario_count": meta.scenario_count,
            "g0_anchor": list(meta.g0_anchor),
        },
    }
    (out_dir / "proof_tree_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    return index
