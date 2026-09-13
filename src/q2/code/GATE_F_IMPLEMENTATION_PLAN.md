# Gate F implementation plan — deterministic outer search

## Scope

Implement only a reproducible numerical search for

```text
argmin_{S2 in C_adm} Q(S2)
```

using the frozen Gate E evaluator. This gate must never claim a certified global optimum, epsilon-optimality, or a proof. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## Required modules

- `solver/outer_search.py`: compact Crec-derived bounding box, deterministic adaptive spatial subdivision, incumbent tracking, and stable local refinement.
- `verifier/verify_outer.py`: independent recomputation of the recommended point and dense local perturbation/refinement checks; do not trust solver cache.
- `tests/test_gate_f.py`: deterministic seeds/layouts, boundary/interior candidates, multiresolution stability, general-input demo, and no-certificate negative assertions.

## Frozen behavior

- derive search bounds from A1/Crec geometry; never expose or search a giant arbitrary box such as `[-2e6,2e6]^2`;
- evaluate only points that are in Crec and admissible (all-near remains a valid terminal `Q=0`);
- deterministic seeds include analytic/baseline-inspired, coarse-grid best, symmetry-related when valid, boundary and interior points;
- use deterministic adaptive subdivision plus one stable local nonsmooth refinement method; no GA/PSO/RL/neural optimizer;
- retain full Q2 point provenance and re-evaluate the incumbent independently;
- compare grid resolution, subdivision depth, and starting layouts; preserve no-known-better-neighbor evidence.

## Verification and evidence

At least deterministic representative/general-input cases, multiresolution checks, dense local mesh and adversarial perturbations must pass. Store Gate F fixtures, verification JSON, test output, and report only after A–E regressions and Q1 regression pass. Freeze a manual snapshot; no Git.
