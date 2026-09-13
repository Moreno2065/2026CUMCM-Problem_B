# Q2 Gate B Report — exact robust reception set

**Status:** PASS  
**Source snapshot:** `q2_gate_a_pass_v1_20260911_020726`  
**Scope:** `CrecWitnessRegistry`, exact `Phi(S2)` evaluation, and independent Verifier B only.

## Implemented definition

Gate B implements the frozen set

```math
\mathcal C_{\rm rec}
=
\bigcap_{G\in\mathcal A_1}
B\left(G,\max\{1000,\|G-S_1\|\}\right),
```

with

```math
\Phi(S_2)=\max_{G\in\overline{\mathcal A}_1}
\left[\|S_2-G\|-\max\{1000,\|G-S_1\|\}\right].
```

Membership is exactly `Phi(S2) <= 0` up to the common `1e-9 m` evaluation tolerance. The public result contains membership, signed maximum violation, margin, active witness point/type/source, finite candidate count, and A1 dimension.

The implementation never substitutes the conservative `intersection B(G,1000)` expression for the Hero model.

## Radial reduction and finite candidates

For every feasible direction, the implementation preserves the three frozen branches verbatim:

```text
rho_hi <= 1000       -> {rho_lo, rho_hi}
rho_lo < 1000 < hi   -> {rho_lo, 1000}
rho_lo >= 1000       -> {rho_lo}
```

It does not manufacture a `rho=1000` witness when 1000 is outside the radial interval, and it never registers `rho=1500` as a deep-end witness.

Constant-compatible-radius arcs use their two endpoints and an in-arc antipodal point. A separate regression showed that a deep `Omega-rho_lo` arc cannot in general be treated as a plain farthest-point arc because its objective is `distance(S2,G)-distance(S1,G)`. Those arcs therefore add every real in-arc root of the finite half-angle polynomial for the unsquared derivative; all algebraic roots are filtered against the original derivative. The deterministic B-F8 case would underestimate `Phi` by about `0.0830865 m` if only arc endpoints were retained.

## Registry separation and degeneracy

`CrecWitnessRegistry` is a distinct nominal type from `A1BoundaryRegistry`. Their active labels cannot be interchanged, although both may contain the same neutral `CircularArc` value. Constructor tests reject a deep-end `rho=1500` witness, reject incompatible radius modes, retain Gate A's ban on `rho=1000` in A1, and reject an A1 registry passed where a Crec registry is required.

`A1Dimension.EMPTY` fails fast as invalid first-observation geometry. `A1Dimension.POINT` becomes exactly one compatible reception disk; the permanent tangent singleton therefore produces `B(T,1000)` and passes at offsets `0`, `999.999`, and `1000 m`, while failing at `1000.001 m`. Verifier B independently recovers both a wedge-side/Omega tangent and the interior `rho=1500`/Omega tangent `S1=(3300,0), bearing=180.5 deg, T=(1800,0)` by closed-form candidate enumeration rather than an angle grid. The currently unreachable `SEGMENT` state is explicitly blocked rather than silently treated as area. A Crec registry is also rejected if its first-station or Omega metadata does not match the owning A1.

## Independent verification

Verifier B does not import the Crec solver, call `is_in_crec`, or inspect `CrecWitnessRegistry`. Its first oracle independently generates interior and boundary targets from the original A1 inequalities. Its second oracle independently scans both direction and the full radial interval and directly evaluates the unreduced objective.

Nine deterministic fixtures B-F1 through B-F9 pass, covering central geometry, Omega outward truncation, angle wrap, an external station, both POINT tangent mechanisms, strict compatible deep-radius information (`1000 < 1100 < 1200`), an interior antipodal maximum, and the additional deep-Omega stationary maximum. A permanent fixed-seed property test covers 500 randomized nondegenerate configurations, including `S1 in Crec`, analytic non-underestimation, and dense checks of every analytic PASS. Rigid-motion covariance and `359.5 deg == -0.5 deg` are also regression-tested.

Across the supplemental 500-case analytic-vs-dense run, the smallest observed `analytic Phi - dense Phi` was `-4.547473508864641e-13 m`, which is floating-point roundoff and far below the `2e-6 m` comparison tolerance. The largest observed gap was `4.043853550683707e-06 m`, with analytic evaluation above the dense lower bound as required.

## Verification results

```text
Q2 Gate A: 10 passed
Q2 Gate B: 25 passed
Q1 regression: 10 passed
Python compile: PASS
Independent 500-case Crec cross-check: PASS
Forbidden Gate C-or-later files: 0
```

Gate C near-aware angular images, circular-interval business logic, the Q1 adapter, E1-E5 inner maximizer, outer search, and final `S2*` remain absent. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`. Gate B stops here.

## Provenance

An earlier candidate snapshot `q2_gate_b_pass_v1_20260911_023026` is explicitly invalidated because its POINT verifier missed an interior `rho=1500`/Omega tangency. This repaired Gate is frozen under snapshot id `q2_gate_b_pass_v2_20260911_024014`, created directly from `q2_gate_a_pass_v1_20260911_020726`. The machine-readable provenance is in `artifacts/q2_gate_b_verification_report.json`.
