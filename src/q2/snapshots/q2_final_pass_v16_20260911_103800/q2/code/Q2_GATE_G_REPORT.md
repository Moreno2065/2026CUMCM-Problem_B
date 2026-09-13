# Q2 Gate G Report — baselines, candidate regions, and evidence package

**Status:** PASS  
**Source snapshot:** `q2_gate_f_pass_v1_20260911_050600`  
**Scope:** reproducible B0/B1/B2/Hero comparison, numerical candidate-good regions, seven figure families, and independently checked evidence artifacts.

## Evidence contract

Gate G packages one representative illustrative input, not a universal deployment claim:

```text
S1 = (0, 0) m, theta1 = 0 deg, epsilon = 1 deg
```

All four rows call the same frozen `evaluate_q2_point` metric. B0 is a feasible reference near the Crec-derived search-box center; B1 is the frozen center-ray max-min-angle heuristic; B2 is the right-angle radial heuristic; Hero is the deterministic Gate F numerical recommendation.

## Frozen B1 heuristic

For `rho_a=5 m`, `rho_b=1500 m`, `L=1495 m`, and reception radius `1000 m`, the center-ray max-min-angle construction uses

```math
x^* = 5 + 1000^2/1495 = 673.8963210702341\text{ m},
```

```math
|y^*| = 1000\sqrt{1-(1000/1495)^2}=743.3557100464799\text{ m}.
```

The positive-perpendicular branch is rotated by the first bearing, translated by `S1`, and clamped componentwise to the Crec-derived search bounds. The unclamped and persisted points are recorded in `q2_method_provenance.json`. If the resulting point is infeasible, the row remains honestly infeasible; it is never replaced by Hero.

## Candidate-good regions

The package stores eta values `1%`, `2%`, `5%`, and `10%` relative to the numerical `qhat_star` from Hero. These are finite sampled sets with the explicit semantics `numerical_candidate_good_region_not_proof`; they are not certified sublevel sets or global-optimality regions.

## Figures

Seven named figure families are emitted, each with a JSON data sidecar and SVG/PDF/PNG renderings:

1. geometry overview;
2. Crec feasibility;
3. angular image;
4. Q surface;
5. numerical optimum and candidate region;
6. baseline comparison;
7. worst-case intersection.

Sidecar metadata fixes meter units, equal axes, muted baseline styling, a non-rainbow `Blues` colormap, and the illustrative case label.

## Independent verification

`verify_gate_g.py` independently recomputes all rows and Hero, exact-compares the evidence table, combined and eta-specific candidate-region files, B1 provenance, and every figure sidecar. It checks SVG/PDF/PNG headers and fresh candidate-point thresholds, and rejects tampered table, region, figure, qhat, or certificate fields. It does not call `build_gate_g_case` or `search_outer`.

## Verification results

```text
Gate G: 11 passed in 78.61s
Ruff: All checks passed
Persistent representative verifier: PASS
Rows: 4; candidate points checked: 4; figure files checked: 21
B1 formula/provenance regression: PASS
Artifact tamper regressions: PASS
Illustrative general-input regressions: PASS
Specification review: PASS
Code-quality review: PASS
```

`CERTIFIED_GLOBAL_OPTIMUM` remains `false`. Gate G makes no universal `S2` claim and does not add Gate H.

## Provenance

Gate G is frozen from `q2_gate_f_pass_v1_20260911_050600`. No Git operation is used; the next immutable manual snapshot is recorded by `SNAPSHOT_MANIFEST.md`.
