# Q2 Final Acceptance Report — G′ / clean-room handoff

**Status:** PASS  
**Acceptance label:** `FINAL_ACCEPTANCE_V3=PASS`  
**Final snapshot:** `q2_final_pass_v16_20260911_103800`  
**Source snapshot:** `q2_gate_g_pass_v1_20260911_054813`  
**Model status:** frozen model unchanged

## Acceptance result

```text
Q2 A–G + final-package + G′ + batch backend: 148 passed, 1 skipped
Q1 regression: 11 passed
Ruff: All checks passed
G′ production semantic/visual checks: 7 passed
Clean-room handoff: 1 passed
```

Gate G′ closes the three P0 evidence issues: Hero/surface closure, symmetric adaptive refinement, and numeric baseline bar positions. The handoff is independently executable in a fresh extraction directory.

## Gate disposition

| Gate | Result | Frozen responsibility |
|---|---|---|
| A | PASS | Exact A1, singleton/tangent support, boundary completeness, registry invariants |
| B | PASS | Exact robust reception set and independent Crec verification |
| C | PASS | Near-aware closed angular image, wrap/dilation, active-boundary provenance |
| D | PASS | Pure two-bearing Q1 adapter and independent Q1 verifier |
| E | PASS | E1–E5 fixed-station inner maximum, strict gate, all-near branch, adaptive roots |
| F | PASS | Deterministic non-certified outer search and recommendation provenance |
| G | PASS | B0/B1/B2/Hero evidence, surface, and saved figure sidecars |
| G′ | PASS | Surface closure, mirror-paired candidate regions, honest baselines, sidecar figures, clean-room handoff |

## Provenance

Manual immutable snapshots are used instead of Git. The final tree is copied into `snapshots/q2_final_pass_v16_20260911_103800/` with `SNAPSHOT_MANIFEST.md`; the handoff contains the same source and artifact tree. Machine-readable evidence is in `src/q2/code/artifacts/q2_final_acceptance_report.json` and `q2_final_verification_report.json`.

`CERTIFIED_GLOBAL_OPTIMUM = false`; candidate regions are numerical non-proof sets, and Gate H is not implemented.
