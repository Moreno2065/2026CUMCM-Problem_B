# Q2 Gate B Exact Crec Implementation Plan

> Execution mode: inline, test-first. Git/worktree/commit steps are intentionally replaced by the approved immutable snapshot protocol.

**Goal:** Implement and independently verify the frozen robust reception set `Crec`, and stop before Gate C.

**Architecture:** `geometry/crec.py` owns a nominally isolated witness registry, exact radial reduction, finite arc candidate evaluation, and the provenance-rich membership result. `verifier/verify_crec.py` independently samples the original A1 target set and densely maximizes the unreduced objective without using the witness registry. Gate A remains the sole owner of A1 geometry.

**Tech stack:** Python dataclasses/enums, existing neutral Q2 primitives, pytest, deterministic JSON fixtures, NumPy only for finite polynomial-root extraction on deep Omega witness arcs.

---

### Task 1: Public Crec contract and degenerate states

**Files:**

- Create: `src/q2/code/tests/test_gate_b.py`
- Create: `src/q2/code/geometry/crec.py`

- [ ] Add failing tests for `InvalidFirstObservationGeometry`, POINT-A1 single-disk membership, result provenance fields, and explicit SEGMENT rejection.
- [ ] Run the focused tests and confirm failure because `geometry.crec` is absent.
- [ ] Add `CrecEvaluation`, `CrecRegion`, `build_crec`, and POINT/EMPTY/SEGMENT handling.
- [ ] Run the focused tests and retain the passing output.

### Task 2: Registry isolation and radial witness construction

**Files:**

- Modify: `src/q2/code/tests/test_gate_b.py`
- Modify: `src/q2/code/geometry/crec.py`

- [ ] Add failing tests proving `A1BoundaryRegistry` and `CrecWitnessRegistry` are different nominal types, `rho=1000` remains illegal in A1, a `rho=1500` deep-end Crec label is rejected, and an A1 registry cannot construct a Crec region.
- [ ] Add tests for the three frozen radial branches: `{lo,hi}`, `{lo,1000}`, and `{lo}`.
- [ ] Implement `CrecWitnessLabel`, `CrecWitnessPiece`, `CrecWitnessRegistry`, angular cut construction, and exact branch-preserving witness arcs.
- [ ] Run Gate A and Gate B tests.

### Task 3: Exact finite candidate maximization

**Files:**

- Modify: `src/q2/code/tests/test_gate_b.py`
- Modify: `src/q2/code/geometry/crec.py`

- [ ] Add the antipodal-interior regression and a deep compatible-radius case that distinguishes Hero Crec from the 1000 m baseline.
- [ ] For fixed-compatible-radius arcs, evaluate endpoints plus an in-arc antipode.
- [ ] For deep Omega `rho_lo` arcs, evaluate endpoints plus all real in-arc stationary roots of `distance(X,G)-distance(S1,G)`; filter algebraic roots against the unsquared derivative.
- [ ] Deduplicate candidates, compute exact `Phi`, margin, active witness provenance, and candidate count.
- [ ] Run the focused regressions and all Gate B tests.

### Task 4: Independent Verifier B and properties

**Files:**

- Create: `src/q2/code/verifier/verify_crec.py`
- Modify: `src/q2/code/tests/test_gate_b.py`

- [ ] Add failing tests for independent dense target sampling, independent dense `(theta,rho)` maximization, analytic non-underestimation, rigid-motion covariance, wrap equivalence, `S1 in Crec`, and POINT-A1 equivalence.
- [ ] Implement Verifier B without importing or calling `is_in_crec` and without reading `CrecWitnessRegistry`.
- [ ] Record the worst analytic-minus-dense gap over deterministic fixtures and fixed-seed randomized cases.
- [ ] Run Gate A, Gate B, and Q1 regression suites.

### Task 5: Gate evidence and immutable snapshot

**Files:**

- Create: `src/q2/code/artifacts/q2_gate_b_fixtures.json`
- Create: `src/q2/code/artifacts/q2_gate_b_verification_report.json`
- Create: `src/q2/code/artifacts/Q2_GATE_B_REPORT.md`
- Create: `src/q2/code/artifacts/q2_gate_b_test_output.txt`
- Create: `snapshots/<new-gate-b-snapshot-id>/SNAPSHOT_MANIFEST.md`

- [ ] Re-run Gate A, Gate B, Q1 regression, and independent dense verifier checks from the current working tree.
- [ ] Confirm no Gate C or later business module exists.
- [ ] Write evidence with `source_snapshot=q2_gate_a_pass_v1_20260911_020726`.
- [ ] Copy the full `src/q2/` tree to a new non-existing Gate B PASS snapshot and verify required files plus source/snapshot hashes.
- [ ] Stop after reporting Gate B status; do not start Gate C.
