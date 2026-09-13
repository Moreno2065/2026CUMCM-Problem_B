# Q2 Gate D Report — pure Q1 adapter and independent verifier

**Status:** PASS  
**Source snapshot:** `q2_gate_c_pass_v1_20260911_033242`  
**Scope:** a deliberately model-neutral adapter for the frozen two-bearing Q1 polygon and an independent verification chain.

## Frozen contract implemented

The public evaluator is exactly:

```text
evaluate_q1(S1, theta1, S2, beta, epsilon)
```

It constructs two closed Q1 bearing wedges and delegates only to the validated Q1 geometry evaluator. It has no dependency on `Omega`, A1, Crec, near-distance rules, or the 5/1000/1500 m physical constraints. The result exposes status, boundedness, affine dimension, ordered vertices, diameter, a vertex witness pair, degeneracy label, and evaluator provenance.

The adapter preserves all five Q1 topologies:

| State | Representation |
|---|---|
| `EMPTY` | no vertices, no diameter, no affine dimension |
| `POINT` | one ordered vertex, zero-dimensional |
| `SEGMENT` | two ordered endpoints, one-dimensional |
| `AREA` | positively oriented cyclic vertex order |
| `UNBOUNDED` | no finite vertex polygon and infinite diameter |

## Fixture coverage

Nine permanent fixtures cover quadrilateral, triangle, segment, point, empty, unbounded, near-parallel, wraparound, and both-station-apex inclusion. Negative tests forge reversed area order and metadata, and inject a poison top-level `q1_geometry` module to verify import isolation. Inputs and expected topology are recorded in `artifacts/q2_gate_d_fixtures.json`.

## Independent verification

`verify_q1.py` does not call `evaluate_q1`. It invokes the independent Q1 verification chain (`q1_verify.verify_measurements`) and then separately checks status, boundedness, dimension, ordered-vertex agreement, diameter, witness validity, degeneracy, normalized bearings, and provenance. Area comparison allows only cyclic shifts, not reversed orientation. A controlled temporary module alias prevents a pre-existing ambient `q1_geometry` module from changing the verifier dependency and restores the ambient module afterward.

## Verification results

```text
Q2 Gate A–D: 86 passed
Q1 regression: 10 passed
Python compile: PASS
Ruff: All checks passed
Ambient-module isolation regression: PASS
Spec-compliance review: PASS
Code-quality review: PASS after P1 import-isolation repair
```

The complete machine-readable evidence is in `artifacts/q2_gate_d_verification_report.json`; the deterministic inputs are in `artifacts/q2_gate_d_fixtures.json`.

## Gate boundary

Gate D stops at the pure Q1 adapter. No E1–E5 inner maximizer, outer optimization, candidate region, baseline, figure, or final-solution artifact is implemented in this gate. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## Provenance

Gate D is frozen from `q2_gate_c_pass_v1_20260911_033242`. No Git operation is used; the next immutable manual snapshot is recorded by `SNAPSHOT_MANIFEST.md`.
