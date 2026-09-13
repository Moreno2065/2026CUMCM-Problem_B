# Q2 Gate E Report — exact fixed-station inner maximizer

**Status:** PASS  
**Source snapshot:** `q2_gate_d_pass_v1_20260911_034850`  
**Scope:** deterministic E1–E5 candidate maximization of the frozen inner objective and an independent dense-beta verifier.

## Frozen objective

For a second station inside `Crec`, Gate E evaluates

```math
Q(S_2)=\max_{\beta\in\widehat{\Theta}_2^{dir}(S_2)}D_{Q1}(S_2,\beta).
```

The fixed-station result includes the required provenance: station, Crec membership and margin, all-near state, raw and expanded angular intervals, strict admissibility, `Q`, worst bearing, candidate type, Q1 status/polygon/witness, and active geometry labels.

## E1–E5 candidate construction

The production path partitions each allowed circular interval at apex and parallel events, then retains:

1. E1 interval endpoints;
2. E2 second-cone apex events;
3. E3 exact parallel events and legal left/right one-sided limits;
4. E4 pair-distance stationary roots;
5. E5 pair-pair envelope-switch roots.

E4/E5 roots use deterministic adaptive interval subdivision with endpoint/midpoint/turning/curvature checks, safeguarded bisection or deterministic absolute-minimum isolation for even roots, and final residual/segment/finite rechecks. The former fixed 24-cell sign scan and endpoint margin were removed. Permanent tests cover clustered roots, an even root, and a root 1e-10 from an endpoint.

## Boundary behavior

- Outside `Crec`: reject before angular or inner optimization.
- All-near: bypass angular admissibility and return `Q=0`.
- Otherwise: require `dist(raw angular closure, theta1) > 3 epsilon` strictly.
- Any unbounded Q1 candidate or proven one-sided divergence returns `+inf`.
- Winner provenance reports only the Crec witness, winner candidate source, and the angular boundary source that generated the winning expanded endpoint; it does not claim every boundary event is active.

## Independent verification

`verify_inner.py` imports only the pure Q1 adapter. It does not import or call `construct_inner_candidates` or `maximize_inner`. Its dense oracle samples each canonical interval independently, refines local peaks within that component, and applies a zero-tolerance membership filter before evaluation. This prevents wraparound/disconnected intervals from generating illegal beta values in the gap. The permanent gap regression has canonical components `[0,66.716097°]` and `[270.108676°,360]`, production and dense values zero, and no sample near the forbidden 181.13° gap.

## Verification results

```text
Gate E: 14 passed
Gate A–E: 100 passed
Q1 regression: 10 passed
Ruff: All checks passed
500 fixed-seed valid/admissible stations: PASS
Adaptive-root, E3 one-sided, provenance, and wrap-gap regressions: PASS
Specification review: PASS
Code-quality review: PASS after hardening
```

Machine-readable evidence is in `artifacts/q2_gate_e_fixtures.json` and `artifacts/q2_gate_e_verification_report.json`.

## Gate boundary

Gate E stops at the fixed-station inner objective. No outer search, candidate-good region, baseline, figure, or final-solution artifact is implemented. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## Provenance

Gate E is frozen from `q2_gate_d_pass_v1_20260911_034850`. No Git operation is used; the next immutable manual snapshot is recorded by `SNAPSHOT_MANIFEST.md`.
