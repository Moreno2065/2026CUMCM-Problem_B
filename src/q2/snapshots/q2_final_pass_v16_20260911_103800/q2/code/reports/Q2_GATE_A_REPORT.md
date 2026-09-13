# Q2 Gate A Report — A1 physical geometry

**Status:** PASS  
**Scope:** neutral planar primitives, the frozen first-observation target set `A1`, and `A1BoundaryRegistry` only.

The implementation realizes

```math
A1 = Omega intersection K(S1, theta1) intersection {G: 5 < ||G-S1|| <= 1500}.
```

`A1BoundaryRegistry` is a separate nominal type. It admits only first-wedge line segments plus active `rho=5`, `rho=1500`, and `partial Omega` circular arcs. It rejects a `rho=1000` circle even if falsely tagged as an Omega arc, and verifies that every `Omega` arc uses the registry's own target-circle center and radius.

The independent Gate A verifier does not invoke `A1Region.contains`; it directly samples each registry primitive and checks the target circle, the first angular wedge, and the radial shell. It also independently derives 101 ray-boundary samples and checks their coverage by the registry, so it tests both registered-boundary soundness and sampled completeness.

The tangent regression

```math
Omega=B((0,0),1800),\quad S1=(2000,0),\quad
hat(theta1)=114.84193276316712 degrees
```

has `A1={T}`, where `T=(1620, 784.6018098373212)`. This is now represented as `A1Dimension.POINT` with one neutral `BoundaryPoint`; it cannot produce an empty-registry vacuous PASS. The deterministic fixture set covers central geometry, target-circle truncation, `0/360` wraparound, external first stations, and this singleton tangent. A fixed-seed set of 500 nondegenerate constructions also passes the independent completeness oracle.

Verification commands and results:

```text
python -B -m pytest -q -p no:cacheprovider .\src\q2\code\tests\test_gate_a.py
10 passed

python -B -m pytest -q -p no:cacheprovider .\src\q1\code\tests
10 passed
```

No `C_rec`, near-aware angular image, Q1 adapter, inner maximizer, or outer search code is present in this gate. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## Provenance

This project uses immutable manual snapshots, not Git. The approved Gate A source is archived under snapshot id `q2_gate_a_pass_v1_20260911_020726`; its provenance fields are recorded in `q2_gate_a_verification_report.json`. Later gates must name this snapshot as their `source_snapshot` until a newer PASS snapshot is created.
