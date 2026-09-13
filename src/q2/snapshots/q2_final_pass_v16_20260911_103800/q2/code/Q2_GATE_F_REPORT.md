# Q2 Gate F Report — deterministic outer search

**Status:** PASS  
**Source snapshot:** `q2_gate_e_pass_v1_20260911_042520`  
**Scope:** reproducible numerical search for a good admissible second station, with explicit non-certified semantics.

## Search contract

The outer search minimizes the frozen Gate E value numerically over admissible `S2`:

```math
\widehat S_2^\star \approx \arg\min_{S_2\in\mathcal C_{adm}} Q(S_2).
```

The search bounds are derived from the intersection of axis-aligned boxes of compatible Crec witness disks. This gives a compact geometry-relative superset and never invokes an arbitrary giant coordinate box. Deterministic seeds include analytic/symmetry layouts, boundary and interior points, and the actual coarse-grid winner when one exists.

The search combines a deterministic coarse grid, top-cell adaptive subdivision, and fixed-direction nonsmooth pattern refinement. Repeated runs, multiple resolutions/depths, and two translated/wrapped general inputs are tested. The history and every incumbent retain complete `Q2PointResult` provenance.

## Certificate boundary

`CERTIFIED_GLOBAL_OPTIMUM` is explicitly `false` in both the module and result. The method is described only as a deterministic search/refinement framework. No global-optimum, epsilon-optimal, or proved-optimum claim is made.

## Independent verification

`verify_outer.py` does not import `outer_search` or trust its cache. It recomputes the recommended point through the full A1→Crec→angular→inner→Q1 chain, then compares every immutable `Q2PointResult` field: station, Crec margin/state, near/image intervals, admissibility, Q, worst bearing/type/status, polygon, diameter witness, and active labels. It explicitly rejects a forged `certified_global_optimum=True`. A dense 5×5 local mesh and deterministic 16-direction perturbations at five scales are checked for a better nearby valid point.

## Verification results

```text
Gate F: 9 passed in 158.84s
Gate A–F: 109 passed in 210.66s
Q1 regression: 10 passed in 0.33s
Ruff: All checks passed
Independent recommendation/provenance verification: PASS
Multiresolution/general-input stability: PASS
```

The measured runtime is retained as evidence: Gate F is currently the dominant cost and may take minutes for larger configurations. This is a performance note, not a mathematical certificate.

## Gate boundary

Gate F stops before baselines, candidate regions, figures, and final-solution packaging. Those are Gate G responsibilities. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## Provenance

Gate F is frozen from `q2_gate_e_pass_v1_20260911_042520`. No Git operation is used; the next immutable manual snapshot is recorded by `SNAPSHOT_MANIFEST.md`.
