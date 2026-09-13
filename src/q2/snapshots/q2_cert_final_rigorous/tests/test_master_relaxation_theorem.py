"""THEOREM B - Master Relaxation Lower Bound: structural and numeric tests
(closure spec s.38, s.46, s.24-25).

The theorem chain:

    L_rigorous = min_live LB_Arb(B)
                <= inf_{D_k ∩ {y<=0}} M(S2)
                <= inf_{C_rec ∩ {y<=0}} Q~(S2) = Q*            (Corollary A)

requires, per box: LB(B) = max_j lb_j(B) <= inf_B M, each lb_j a rigorous
scenario lower bound with the mixed-box convention of spec s.25 (0, never a
bearing bound), and D_k ⊇ C_rec (finite witness relaxation).
"""

import math

import numpy as np

from src.q2.formal import batch_kernel as bk
from src.q2.formal.master_problem import load_records
from src.q2.formal.rigorous_arithmetic import Ivl, set_precision_bits
from src.q2.formal.scenario_loss import box_loss_lower, float_point_loss
from src.q2.formal.ivl_geometry import IvlPoint

from pathlib import Path

ARTIFACTS = Path("src/q2/artifacts/formal")
rng = np.random.default_rng(20260913)


def _scen_objs():
    scen_recs, _ = load_records(ARTIFACTS / "master_cuts.json")
    return [s.to_scenario() for s in scen_recs]


def test_lb_is_max_of_scenario_bounds_and_below_true_inf():
    """s.24: LB(B) = max_j lb_j(B) <= inf_B M; falsification direction."""
    scen = _scen_objs()
    set_precision_bits(128)
    for _ in range(25):
        cx = float(rng.uniform(500, 1200))
        cy = float(rng.uniform(-700, -100))
        w = float(10 ** rng.uniform(-2, 1.0))
        box = (cx, cx + w, cy, cy + w)
        s2box = IvlPoint(Ivl.from_bounds(box[0], box[1]),
                         Ivl.from_bounds(box[2], box[3]))
        lbs = []
        branches = []
        for s in scen:
            lower, br = box_loss_lower(s2box, s)
            branches.append(br)
            if lower is not None:
                lbs.append(lower.lower_float())
        lb = max(lbs) if lbs else 0.0
        # dense falsification: LB must not exceed the sampled infimum
        samp = min(max(float_point_loss(x, y, s) for s in scen)
                   for x in np.linspace(box[0], box[1], 5)
                   for y in np.linspace(box[2], box[3], 5))
        assert lb <= samp + 1e-9, (box, lb, samp)


def test_mixed_boxes_use_zero_lower_bound():
    """s.25: a box straddling the near circle gets LB 0, never a bearing
    bound misapplied to the whole mixed box."""
    scen = _scen_objs()[0]
    set_precision_bits(128)
    # box centred on the 5 m circle around G
    gx, gy = scen.gx, scen.gy
    box = (gx - 1.0, gx + 1.0, gy - 1.0, gy + 1.0)
    s2box = IvlPoint(Ivl.from_bounds(box[0], box[1]),
                     Ivl.from_bounds(box[2], box[3]))
    lower, br = box_loss_lower(s2box, scen)
    assert br in ("mixed", "near")
    if br == "mixed":
        assert lower.lower_float() <= 0.0


def test_dk_contains_crec_witness_semantics():
    """D_k = B0 ∩ ∩_w complement(B(w, R_w)) ⊇ C_rec requires every Crec
    point to satisfy ||X - w|| <= R_w with R_w = max(1000, |w|)."""
    _, wit_recs = load_records(ARTIFACTS / "master_cuts.json")
    assert len(wit_recs) == 20
    for w in wit_recs:
        assert w.radius == max(1000.0, math.hypot(w.gx, w.gy))


def test_theorem_b_chain_present_in_replay_artifacts():
    """The rigorous LB artifact must carry the THEOREM B chain statement."""
    import json
    p = ARTIFACTS / "rigorous_master_lower_bound.json"
    if not p.exists():
        import pytest
        pytest.skip("rigorous_master_lower_bound.json not generated yet")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "THEOREM B" in d["theorem"]
    assert "Q*" in d["chain"] and "Corollary A" in d["chain"]


def test_symmetry_artifact_backs_the_half_domain():
    """The half-domain step of THEOREM B rests on Corollary A (analytic)."""
    import json
    d = json.loads((ARTIFACTS / "canonical_symmetry_lemma.json").read_text(
        encoding="utf-8"))
    assert d["claims"]["half_domain_equivalent"] is True
    assert d["status"] == "PROVEN_ANALYTIC"
