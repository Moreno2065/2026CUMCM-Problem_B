# Q2 Gate D Pure Q1 Adapter Plan

**Source snapshot:** `q2_gate_c_pass_v1_20260911_033242`

## Frozen scope

Implement only the pure adapter
`(S1, theta1, S2, beta, epsilon) -> P_Q1 -> D_Q1`.
The adapter may call the validated Q1 solver, but its public signature must not
accept or import Omega, A1, Crec, physical radii, near state, or physical arcs.
No Gate E/F/G logic is allowed.

## Tasks

1. Add `model/q1_adapter.py` with structured status, affine dimension, ordered
   vertices, diameter, diameter witness pair, and degeneracy provenance.
2. Add `verifier/verify_q1.py` using the independent Q1 verifier chain and
   direct equivalence checks.
3. Add deterministic D fixtures for quadrilateral, triangle, segment, point,
   empty, unbounded, near-parallel, wraparound, and apex inclusion.
4. Add purity/isolation tests and fixed-seed rigid/wrap regressions.
5. Run Gate A/B/C and Q1 regressions, then create an immutable Gate D snapshot.

## Gate boundary

Do not create `solver/inner_max.py`, `solver/q2_point.py`, `solver/outer_search.py`,
baselines, candidate-region artifacts, figures, or final solution artifacts in
Gate D.
