"""Shared fixture: a tiny recorded proof tree for replay tests (spec s.46).

The tiny tree is produced by the SAME recorder and replayed by the SAME
verifier as the real certificate tree - same frozen cuts, a small root box,
a loose tolerance so the run stays in seconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.q2.formal import proof_tree_replay as ptr
from src.q2.formal.interval_master import BatchMaster
from src.q2.formal.master_problem import load_records
from src.q2.formal.proof_tree import TreeMeta, TreeRecorder, finalize_and_save

ARTIFACTS = Path("src/q2/artifacts/formal")


def build_tiny_tree(out_dir: Path, b0=(700.0, 950.0, -700.0, -480.0),
                    tol=0.5, round_cap=64):
    u_cert = 134.0659292484056
    scen_recs, wit_recs = load_records(ARTIFACTS / "master_cuts.json")
    rec = TreeRecorder(b0, u_cert, n_scenarios=len(scen_recs))
    master = BatchMaster(b0=b0, upper_bound=u_cert, recorder=rec)
    for w in wit_recs:
        master.add_witness(w.to_witness())
    for s in scen_recs:
        master.add_scenario(s.to_scenario(), refresh_band=None)
    master.solve(tol=tol, round_cap=round_cap, max_boxes=200000,
                 time_budget_s=120.0)
    meta = TreeMeta(b0=b0, u_cert=u_cert, tol=tol, round_cap=round_cap,
                    max_boxes=200000, witness_count=len(wit_recs),
                    scenario_count=len(scen_recs), g0_anchor=(1000.0, 0.0))
    finalize_and_save(master, rec, meta, out_dir)
    return out_dir


@pytest.fixture(scope="session")
def tiny_tree(tmp_path_factory):
    out = tmp_path_factory.mktemp("tiny_tree")
    build_tiny_tree(out)
    return out


@pytest.fixture(scope="session")
def tiny_arr(tiny_tree):
    return dict(np.load(tiny_tree / "proof_tree.npz"))


@pytest.fixture(scope="session")
def tiny_replay(tiny_tree):
    return ptr.replay_proof_tree(tiny_tree, tau=0.01, cuts_dir=ARTIFACTS,
                                 expect_root_b0=False,
                                 refine_time_budget_s=30.0)


@pytest.fixture(scope="session")
def certificate_json():
    return json.loads((ARTIFACTS /
                       "q2_global_optimality_certificate.json").read_text(
                           encoding="utf-8"))
