# Q2 Gate C Report — near-aware closed angular image

**Status:** PASS  
**Source snapshot:** `q2_gate_b_pass_v2_20260911_024014`  
**Scope:** circular interval algebra, strict near clipping, per-component angular images, and independent Verifier C only.

## Frozen definition implemented

For a candidate second station `S2`, Gate C constructs

```math
\mathcal A_1^{\rm dir}(S_2)=\{G\in\mathcal A_1:\|G-S_2\|>5\},
```

then returns the closed circular image

```math
\overline{\Theta}_2^{\rm dir}(S_2)
=\overline{\arg(\mathcal A_1^{\rm dir}(S_2)-S_2)}
```

and its frozen second-measurement expansion by `[-1 deg,+1 deg]`. The strict actual-bearing predicate and the closed worst-case representation are kept distinct. A nonempty A1 wholly within the closed 5 m disk is reported as `all_near=True` with empty raw and expanded angular sets.

## Geometry and provenance

`CircularIntervalUnion` provides neutral EMPTY/FULL states, finite closed intervals, wrap normalization, union, touching merge, dilation, rotation, containment, and circular distances. Sub-picoradian positive gaps are not silently merged or promoted to FULL.

The angular solver accepts only `A1BoundaryRegistry`. It clips every physical A1 line/arc by the near disk, introduces active near-circle arcs, and connects all resulting primitives through a dynamically sized endpoint graph. There is no two-branch array or fixed branch-count cap. Every spatial component has its own raw circular interval union; the public merged closure is their circular union. Endpoint witnesses and boundary events retain component index, source physical piece, event kind, coordinates, and angle. `rho=1000` is never fabricated; active `rho=1500` arcs remain eligible, including an interior tangent extremum fixture.

Strict tangency is treated topologically rather than by a business tolerance. The permanent double-wedge case at `S2.x=5/sin(1 deg)` has two spatial components and FULL closed angular image. Representable positive clearances of `5e-14`, `8e-14`, and `1e-10 m` remain connected. POINT A1 similarly distinguishes exactly 5 m from every representable value strictly above 5 m.

## Independent verification

Verifier C does not import the production angular solver or Crec. It uses:

1. dense physical-boundary sampling plus independently generated active near-circle limit directions;
2. independent theta/rho interior sampling from the A1 inequalities;
3. a separately implemented critical-event/ray-feasibility reconstruction of the entire closed circular truth set.

The third path compares the claimed and independently reconstructed unions in both directions over the elementary cells induced by both endpoint sets. It permanently rejects a forged FULL result, a filled `0.2014 deg` forbidden gap, and a `1e-6 rad` artificial hole; therefore the verifier is not a one-sided or vacuous containment check.

Ten deterministic fixtures C-F1 through C-F10 cover ordinary geometry, 0/360 wrap, `S2=S1`, thin-wedge near crossing, the permanent three-spatial-component case, nondegenerate all-near, actual FULL coverage, POINT A1 strict-distance cases, an interior `rho=1500` arc tangent, and one-degree dilation merging two raw intervals.

The fixed-seed 500-case cross-check passed. Observed random spatial-component counts were `{1: 483, 2: 17}` and angular-interval counts were `{1: 483, 2: 17}`; 128 cases were FULL and none of this random sample happened to be all-near. Deterministic fixtures separately exercise all-near and three components. Maximum missing angle and maximum endpoint disagreement were both `0 rad`.

## Verification results

```text
Q2 Gate A: 10 passed
Q2 Gate B: 25 passed
Q2 Gate C: 29 passed
Q1 regression: 10 passed
Combined: 64 passed
Python AST compile: PASS (13 files)
Independent 500-case angular cross-check: PASS
Independent code review: PASS after all deterministic blockers were repaired
```

## Gate boundary

No `q1_adapter.py`, `D_Q1`, E1-E5 inner maximizer, outer search, or final `S2*` implementation exists. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`. Gate C stops here and does not start Gate D.

## Provenance

Gate C is frozen from `q2_gate_b_pass_v2_20260911_024014` under the snapshot recorded in `artifacts/q2_gate_c_verification_report.json`. No Git operation is used.
