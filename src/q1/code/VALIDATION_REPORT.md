# Q1 Implementation Validation Report

Contract: `Q1_MATH_v1.2 — FROZEN`  
Implementation package: `q1_implementation`

## Scope

The implementation follows the frozen Q1 definition: the localization region is the intersection of the +/-1 degree bearing wedges only. The 1800 m target disk, 1000-1500 m reception-radius prior, and <=5 m `near` rule are not added to the Q1 localization polygon.

## Deterministic regression suite

Command:

```bash
pytest -q
```

Result:

```text
10 passed
```

Covered cases include T1-T8 plus JSON serialization of the `UNBOUNDED` state.

## Frozen numerical oracles

### T2 - two-station noncoverage counterexample

- diameter: `48.86413922424396 m`
- covered by diametral disk: `False`
- maximum radial excess: `0.24936586421624796 m`
- diametral-disk violation ratio `rho_viol`: `1.010206497778335`
- deterministic MEC radius: `24.43333319631437 m`
- `2*r_MEC/d`: `1.0000517182626134`
- main-vs-verifier diameter relative difference: `1.4541e-16`

### T3 - realizable equilateral-triangle counterexample

- `L = 485.9944562442088 m`
- diameter: `20.00000000000002 m`
- covered by diametral disk: `False`
- `2*r_MEC/d = 1.1547005383792506 = 2/sqrt(3)` within floating tolerance

### T8 - near-unbounded but finite geometry

- diameter: `100244.33804648512 m`
- independent verifier diameter: `100244.33804668505 m`
- relative difference: `1.9944e-12`
- implementation does not clip the result with an arbitrary finite bounding box

## Deterministic randomized cross-check

Command:

```bash
python fuzz_crosscheck.py --realizable 600 --arbitrary 800 --seed 20260910
```

Result:

```text
cases = 1400
status_counts = {'OK': 640, 'UNBOUNDED': 167, 'EMPTY': 593}
status_mismatch = 0
diameter_mismatch_gt_1e-8 = 0
worst_diameter_rel_diff = 1.1690624887395455e-09
```

The 600 realizable cases were generated from a hidden true source with station distances 100-900 m and bearing errors sampled inside [-1,1] degrees. The 800 arbitrary cases intentionally exercise contradictory and unbounded configurations.

## Evidence-chain separation

Main chain A uses:

- independent wedge half-planes;
- all boundary-line pair intersections;
- feasibility filtering / Proposition 2A;
- bearing-arc recession test;
- pairwise vertex diameter;
- analytic diametral-disk test.

Verifier B independently re-derives the bearing half-planes and uses:

- SciPy HiGHS LP for EMPTY / UNBOUNDED / bounded classification;
- four LP extrema for a certified finite clipping box;
- sequential half-plane clipping;
- monotone-chain convex hull;
- rotating calipers;
- deterministic 2-point / 3-point support-circle MEC enumeration.

Thus the verifier does not reuse the main chain's intersection, boundedness, diameter, or coverage implementation.

## v1.1 Numba-default backend validation

- Public `solve_q1` default backend changed to `numba`.
- Frozen mathematical contract `Q1_MATH_v1.2` unchanged.
- JIT scope is limited to the O(n^3) boundary-pair intersection / feasibility-filter hot loop.
- `fastmath=False`; compiled kernel uses deterministic serial execution.
- Pure-Python `solve_q1_reference` retained as the audited reference backend.
- Added hard-fixture regression asserting default Numba and reference agree on T2 and T8.
- Full regression after change: 11/11 PASS.

Warm-run benchmark in the validation environment:

| n | Numba ms | Reference ms | Speedup |
|---:|---:|---:|---:|
| 2 | 0.031 | 0.031 | 1.0x |
| 10 | 0.218 | 0.609 | 2.8x |
| 20 | 0.686 | 3.10 | 4.5x |
| 50 | 3.62 | 30.9 | 8.6x |
| 100 | 13.7 | 201.7 | 14.7x |
