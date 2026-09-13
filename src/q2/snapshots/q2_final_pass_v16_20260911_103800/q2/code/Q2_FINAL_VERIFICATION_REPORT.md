# Q2 Final Verification Report — G′ / V3

**Status:** PASS  
**Final snapshot:** `q2_final_pass_v16_20260911_103800`

## Test counts

| Scope | Result |
|---|---:|
| Q2 A–G + final-package + G′ + batch backend | 148 passed, 1 skipped |
| Q1 regression | 11 passed |
| Ruff | All checks passed |
| G′ production artifact checks | 7 passed |
| Clean-room ZIP test | 1 passed in 497.88s |

The skipped item is the environment-gated wrapper for the clean-room test; the required isolated ZIP execution is run separately.

## Independent checks

- The adaptive surface is checked against the final Hero after a bounded promotion/refinement loop; no valid production surface point is better than Hero within `1e-9 m`.
- Symmetric adaptive refinement uses paired mirror cells and permanent point/area balance regressions.
- B1/B2 serialize `Q=null`; the baseline sidecar records numeric positions and the renderer places Hero at row index 3.
- Figures are regenerated from saved JSON sidecars with editable-text SVG, PDF, and 300-dpi PNG outputs.
- The optional ProcessPool candidate-point backend is exactly equivalent to serial for workers `1/2/4/8`; the serial evaluator remains the reference.
- The clean-room ZIP is tested from an isolated extraction with the extracted root as the sole `PYTHONPATH`.

## Claim boundary

`CERTIFIED_GLOBAL_OPTIMUM = false`. Hero and eta candidate regions are deterministic numerical evidence for the supplied representative case, not a global certificate.
