# Q2 Implementation Audit — frozen-contract intake

**Audit time:** 2026-09-11 (Asia/Taipei)  
**Scope of this audit:** read-only inspection of the supplied question materials, Q1 implementation, supporting notes, and the existing Q2 directory. No Q2 solver code was present or modified during inspection.

## 1. Repository and tree state

`D:\CUMCM2026` intentionally does not use Git. Gate provenance follows the manual immutable-snapshot protocol in `src/q2/code/MANUAL_SNAPSHOT_PROTOCOL.md`; run manifests record `snapshot_id`, `snapshot_created_at`, `source_snapshot`, and `verification_report` instead of a commit hash.

Relevant tree at audit time:

```text
D:\CUMCM2026
├─ B题
│  ├─ B题.pdf
│  ├─ 附件1.docx
│  └─ 附件2.docx
├─ 辅助材料
│  ├─ 经验.md
│  └─ 数学建模竞赛复盘与下一次作战手册_v3_主支线_调参消融_蒸馏经验.md
├─ src
│  ├─ q1
│  │  ├─ 问题一：有界测向误差下的交会定位区域模型.md
│  │  └─ code
│  │     ├─ q1_geometry.py
│  │     ├─ q1_verify.py
│  │     ├─ fuzz_crosscheck.py
│  │     ├─ tests/test_q1.py
│  │     ├─ README.md
│  │     └─ VALIDATION_REPORT.md
│  └─ q2
│     └─ Q2整体机制图：冻结版流程与几何分支.png
└─ q4.md
```

No markdown file matching `B题Q2·第五轮：P0修复与缺口2、3重闭合.md`, no later Q2 patch document, and no Q2 implementation source/tests were found at the beginning of this workspace audit.

## 2. Material facts retained for Q2

The official question and attachments establish the following non-negotiable input semantics:

- target domain is `Omega = B((0,0), 1800 m)`;
- a successful full-direction measurement has bounded angular error in `[-1°, +1°]`;
- the unknown effective reception radius is in `[1000 m, 1500 m]`;
- a full-direction measurement at distance at most `5 m` returns `near`, not a bearing;
- Q2 is for a known omnidirectional source after a successful first direction measurement;
- clearing at `<=20 m` is terminal, but the supplied frozen Q2 contract deliberately sets the all-near localization loss to `L_near=0`.

The file `src/q2/Q2整体机制图：冻结版流程与几何分支.png` is useful historical context for the two-registry separation and the all-near terminal branch. Its displayed reception formula is a simplified `dist(S2,A1)<=1000` form, however. It conflicts with the authoritative frozen contract supplied for this implementation:

```math
C_rec = intersection over G in A1 of B(G, max(1000, ||G-S1||)).
```

It must therefore **not** be used as the implementation specification for `C_rec`; the pasted frozen contract is authoritative.

### Post-audit reference reconciliation: `src/q2/q2.md`

The user subsequently supplied `src/q2/q2.md` as a reference. Its executable mathematical content corroborates the authoritative freeze: the same `A1`, the compatible-radius formula `max(1000, ||G-S1||)`, the exact `C_rec`, near-aware closed angular image, strict `>3epsilon` gate, pure Q1 polygon, E1--E5 candidate list, and the non-certifying deterministic outer search.

It is consequently a supporting specification for later gates. Its manuscript prose, citation suggestions, `[待填]` placeholders, and “作者写作备注” are editorial reference material only; they do not override the user-authorized implementation scope, Gate order, or mathematical contract.

## 3. Existing capabilities

### Q1 exact angular-only evaluator — present

`src/q1/code/q1_geometry.py` implements the frozen Q1 main chain using only `±epsilon` bearing wedges:

1. builds two closed half-planes for each bearing wedge;
2. enumerates all non-parallel boundary-line intersections;
3. filters feasible intersections;
4. determines unboundedness from common recession direction only after feasibility;
5. orders bounded vertices, classifies affine dimension, enumerates vertex pairs for diameter, and returns a diameter witness pair.

Its `solve_q1()` output already distinguishes `EMPTY`, `UNBOUNDED`, and bounded `OK` cases, carries ordered vertices, `diameter`, `diameter_pair`, and degeneracy/dimension information. The module header explicitly prohibits introducing the target disk, reception radii, or the near condition into Q1.

### Q1 independent verifier — present

`src/q1/code/q1_verify.py` deliberately follows a separate chain: independent half-plane construction; SciPy HiGHS LP classification; LP-derived finite clipping box; sequential half-plane clipping; monotone-chain hull; rotating-calipers diameter. Existing Q1 tests cover empty, unbounded, near-parallel finite, degeneracy, wraparound, and diameter counterexamples. The recorded prior evidence is 10 deterministic tests and a 1400-case fixed-seed cross-check.

### Q2-specific geometry — absent at audit intake

There are no implementations of:

- `A1` construction or boundary extraction;
- circular arcs, arc clipping, or a robust circular-interval union;
- the two distinct boundary registries;
- exact radial-witness `C_rec` membership;
- near-circle clipping or multi-component angular images;
- Q2 inner E1–E5 candidate enumeration/root isolation;
- Q2 outer deterministic search;
- Q2 verifier/property/regression suites, artifacts, figures, or reports.

The existing Q2 PNG is a diagram, not an executable module or an oracle.

### Post-Gate-A implementation state

Gate A subsequently added `geometry/primitives.py`, `geometry/a1.py`, `verifier/verify_a1.py`, and `tests/test_gate_a.py`. These cover only neutral primitives, exact first-observation `A1`, `A1BoundaryRegistry`, and independent A1 boundary sampling.

The initial Gate A implementation omitted the deterministic upper-wedge/Omega tangent singleton. It is now represented by a neutral `BoundaryPoint`, with `A1Dimension` explicitly distinguishing `EMPTY=-1`, `POINT=0`, `SEGMENT=1`, and `AREA=2`. The verifier now reverse-checks independently derived ray-boundary samples against the registered geometry, so an empty registry cannot pass for a nonempty A1. `OMEGA` arc center/radius are also constructor invariants of `A1BoundaryRegistry`. The Gate A fixtures and verification report are in `src/q2/code/artifacts/`. Every later Q2 capability in the preceding list remains intentionally unimplemented until its assigned gate.

### Post-Gate-B implementation state

Gate B subsequently added `geometry/crec.py`, `verifier/verify_crec.py`, `tests/test_gate_b.py`, and the Gate B fixtures/report under `src/q2/code`. It implements only the frozen exact robust reception set, keeps a nominally separate `CrecWitnessRegistry`, propagates EMPTY/POINT/SEGMENT A1 states explicitly, and verifies analytic `Phi` against two dense oracles that do not call the solver. At the frozen Gate B snapshot, Gate C and all later solver modules remained unimplemented.

### Post-Gate-C implementation state

Gate C adds neutral `geometry/circular_intervals.py`, strict near-aware `geometry/angular_image.py`, independent `verifier/verify_angular.py`, and the permanent Gate C tests/fixtures/report. It clips only `A1BoundaryRegistry`, represents every spatial branch separately, preserves active near-circle and endpoint/tangent provenance, and forms the closed circular union before the frozen one-degree dilation. The verifier combines dense physical-boundary, active-near-circle, radial/interior, and independently reconstructed critical-cell oracles; it rejects both missing angles and fabricated gaps/coverage. Exact tangent and representable positive-clearance topologies are distinct. The Q1 adapter, `D_Q1`, E1-E5 inner maximizer, outer search, and final `S2*` remain intentionally unimplemented.

### Post-Gate-D implementation state

Gate D is now frozen as `q2_gate_d_pass_v1_20260911_034850`. `model/q1_adapter.py` exposes only the five-argument pure-Q1 contract and returns structured topology, vertex, diameter, witness, degeneracy, and provenance data. `verifier/verify_q1.py` independently invokes the existing Q1 verification chain without calling the adapter evaluator. Nine deterministic fixtures cover all five Q1 topologies plus quadrilateral/triangle/segment/point/empty/unbounded/near-parallel/wraparound/apex cases; negative tests reject reversed area order and forged metadata. A subprocess regression proves that an ambient top-level `q1_geometry` module cannot poison the verifier import and is restored afterward.

Gate D evidence is stored in `src/q2/code/artifacts/q2_gate_d_fixtures.json`, `q2_gate_d_verification_report.json`, and `Q2_GATE_D_REPORT.md`. The combined Gate A--D suite reports 86 passed and the frozen Q1 regression reports 10 passed. Gates E--G remain intentionally unimplemented and `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

### Post-Gate-E implementation state

Gate E is now frozen as `q2_gate_e_pass_v1_20260911_042520`. `solver/inner_max.py` retains the complete E1 endpoint, E2 apex, E3 one-sided parallel, E4 stationary, and E5 envelope-switch candidate families. Root isolation is deterministic and adaptive, with endpoint/midpoint/turning/curvature subdivision, safeguarded bisection or even-root minimization, and residual/segment rechecks. `solver/q2_point.py` enforces outside-Crec rejection, all-near `Q=0` bypass, strict raw-image `>3epsilon` admissibility, unbounded `+inf`, and winner-only geometry provenance. `verifier/verify_inner.py` independently samples pure Q1 bearings per connected interval and cannot call the production candidate path.

Gate E evidence is stored in `src/q2/code/artifacts/q2_gate_e_fixtures.json`, `q2_gate_e_verification_report.json`, and `Q2_GATE_E_REPORT.md`. The combined Gate A--E suite reports 100 passed and the frozen Q1 regression reports 10 passed. Gates F--G remain intentionally unimplemented and `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

### Post-Gate-F implementation state

Gate F is now frozen as `q2_gate_f_pass_v1_20260911_050600`. `solver/outer_search.py` performs a deterministic, explicitly non-certified search inside a compact Crec-derived witness-box intersection. It combines fixed analytic/symmetry/boundary/interior seeds, coarse-grid evaluation, top-cell subdivision, and deterministic local pattern refinement. `verifier/verify_outer.py` re-evaluates the recommendation through the full Q2 chain, checks every immutable `Q2PointResult` field, rejects forged certificate flags, and checks a dense local mesh plus multiscale directional perturbations.

Gate F evidence is stored in `src/q2/code/artifacts/q2_gate_f_fixtures.json`, `q2_gate_f_verification_report.json`, and `Q2_GATE_F_REPORT.md`. The combined Gate A--F suite reports 109 passed and the frozen Q1 regression reports 10 passed. Gate G remains intentionally unimplemented; `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.

## 4. Reuse boundary: permitted versus prohibited

| Existing Q1 item | Q2 status | Contractual reason |
|---|---|---|
| `Point`, `Measurement`, `Tolerance` value types | Allowed only at the pure-Q1 adapter boundary | They contain no physical prior or active-boundary semantics. |
| `solve_q1([S1, theta1], [S2, beta])` | Required reuse for `P_Q1(S2,beta)` after a thin pure adapter | It is the already validated four-half-plane evaluator and carries Q1 provenance. |
| `point_satisfies_all`, `build_halfplanes`, Q1 line-intersection logic | Allowed only inside a pure-Q1 boundary adapter/test | Inputs must be exactly two bearing measurements; no physical arc or radius may enter. |
| `q1_verify.verify_measurements` | Allowed only in Verifier D | It is independent evidence for the Q1 evaluator, not Q2 solver logic. |
| Q1 `common_escape_direction_deg` | Allowed only as part of the pure-Q1 result path | It decides four-half-plane unboundedness, not Q2 admissibility. |
| Any Q1 polygon/hull/diameter output | Prohibited as an A1, Crec, or angular-image primitive | Q1 polygons are intersections of angular wedges only. |
| `q1_verify` LP/clipping/calipers implementation | Prohibited in the Q2 Hero solver | It must remain an independent verifier chain. |
| Target disk, `5 m`, `1000 m`, `1500 m`, reception/near data | Strictly prohibited from Q1 adapter/evaluator signatures | Their appearance in `P_Q1` is a hard design error. |

The Q1 source has no generic `LineSegment` or `CircularArc` abstraction to reuse. Q2 will introduce its own neutral line/arc primitives. It may share numeric point/vector operations, but must never share an *active physical boundary registry* with Q1.

## 5. Mandatory registry isolation

Two separate nominal types and constructors will be introduced. They may store neutral `LineSegment`/`CircularArc` primitives, but cannot be substituted for one another.

| Registry | Sole consumers | Permitted active boundary labels | Explicitly rejected labels |
|---|---|---|---|
| `A1BoundaryRegistry` | `A1`, near-aware angular image | first-wedge lower/upper rays, active `rho=5`, active `rho=1500`, active `Omega` arcs | `rho=1000` |
| `CrecWitnessRegistry` | exact `is_in_crec` | `rho_lo`, `rho=1000`, necessary `Omega` truncation witness arcs | `rho=1500` as a deep-end reception witness |

Constructor assertions and regression tests will reject `rho=1000` in `A1BoundaryRegistry`, `rho=1500` as a `CrecWitnessRegistry` deep-end witness, and any physical arc passed to the Q1 adapter.

## 6. Planned Q2 file layout

All new source belongs under the existing `D:\CUMCM2026\src\q2` directory; generated evidence belongs in its prescribed child directories.

```text
src/q2/
├─ geometry/
│  ├─ primitives.py                 # vectors, line segments, oriented circular arcs
│  ├─ circular_intervals.py         # closed circular union, unwrap, dilation
│  ├─ a1.py                         # A1 and A1BoundaryRegistry
│  ├─ crec.py                       # CrecWitnessRegistry and radial-witness membership
│  └─ angular_image.py              # near clipping and componentwise angular image
├─ model/
│  ├─ frozen_contract.py            # immutable constants/config schema and typed outcomes
│  └─ q1_adapter.py                 # exact, angular-only P_Q1 adapter
├─ solver/
│  ├─ inner_max.py                  # E1-E5 finite candidate construction/isolation
│  ├─ q2_point.py                   # evaluate_q2_point provenance payload
│  ├─ outer_search.py               # deterministic global-search framework only
│  └─ baselines.py                  # B0/B1/B2 under the frozen metric
├─ verifier/
│  ├─ verify_a1.py
│  ├─ verify_crec.py
│  ├─ verify_angular.py
│  ├─ verify_q1.py
│  └─ verify_inner.py
├─ tests/
│  ├─ test_gate_a.py
│  ├─ test_gate_b.py
│  ├─ test_gate_c.py
│  ├─ test_gate_d.py
│  ├─ test_gate_e.py
│  └─ regression_cases.py
├─ figures/                         # generated only
└─ artifacts/                       # JSON, manifests, reports, regression fixtures
```

No outer-search claim will be stronger than **deterministic global-search framework** unless a separate branch-complete interval verifier later passes. `CERTIFIED_GLOBAL_OPTIMUM` remains `false` in every current configuration.

## 7. Frozen-object to module mapping

| Frozen object / invariant | Owner module | Public output / enforcement |
|---|---|---|
| `A1` = target disk ∩ first wedge ∩ `(5,1500]` range | `geometry/a1.py` | interior predicate, radial intervals, `A1BoundaryRegistry` |
| `C_rec` with `max(1000, ||G-S1||)` | `geometry/crec.py` | `is_in_crec(S2)` returns bool, margin, active witness, witness type |
| `overline(Theta_2^dir)` | `geometry/angular_image.py` | finite `CircularIntervalUnion`; all-near is empty |
| circular wrap/closure/dilation | `geometry/circular_intervals.py` | no ordinary min/max over raw degrees |
| pure `P_Q1(S2,beta)` | `model/q1_adapter.py` | accepts only two stations, two central bearings, epsilon |
| `D_Q1` and unboundedness | existing Q1 main chain, invoked by adapter | ordered vertices, diameter, pair, degeneracy |
| strict `dist_S(Theta_2^dir, theta1)>3epsilon` | `solver/q2_point.py` | `admissible` flag, not `>=` |
| all-near terminal loss | `solver/q2_point.py` | `all_near=true`, `Q=0`, no bearing gate |
| E1–E5 maximum over expanded intervals | `solver/inner_max.py` | candidate provenance `E1`–`E5`, deterministic root isolation |
| `Q(S2)` full provenance | `solver/q2_point.py` | all fields required by the frozen contract |
| `argmin_{S2 in C_adm} Q(S2)` | `solver/outer_search.py` | reproducible search history, never a certificate claim |
| independent evidence chains A–E | `verifier/` | dense-oracle and independent Q1 checks; no shared solver decision path |

## 8. Gate order and immediate Gate A acceptance criteria

The supplied freeze is treated as the approved implementation design. Gates will be run serially; a failure produces a preserved regression fixture and blocks later gates.

**Gate A — only the next implementation gate:**

1. Test-first neutral point/vector/line/arc primitives.
2. Test-first construction of `A1` and `A1BoundaryRegistry` for arbitrary valid first observations.
3. Verify boundary labels and all boundary samples against `Omega`, the first `±1°` wedge, and the `5–1500 m` radial constraints.
4. Add hard registry-isolation tests, including rejection of `rho=1000` from `A1BoundaryRegistry`.
5. Store a deterministic Gate A report and fixture inputs only after the tests pass.

Gate A will not implement `C_rec`, angular images, Q1 invocation, inner maximization, or outer search. Those belong respectively to Gates B–F.

## 9. Risks and stop conditions identified before coding

- The Q2 PNG’s simplified reception diagram must not silently override the exact frozen `max(1000,rho)` condition.
- The two registries have overlapping neutral geometry but different mathematical meaning; type separation is required, not a convention in comments.
- Physical clipping must occur only in Q2 geometry. The Q1 adapter must remain incapable of receiving any physical curve or radius.
- If a claimed radial-witness, near-clipping, or E1–E5 theorem fails during implementation, the process stops at that gate, preserves the smallest counterexample, adds a regression fixture, and writes `Q2_MODEL_BLOCKER_REPORT.md`. It will not change the frozen math unilaterally.

## 10. Post-Gate-G implementation state

The historical planning sections above are superseded by the recorded gate results. Gate G is frozen as `q2_gate_g_pass_v1_20260911_054813`. `solver/gate_g.py` packages the four required baselines B0/B1/B2/Hero under the same frozen `evaluate_q2_point` metric, numerical candidate-good sets for eta `1%/2%/5%/10%`, and seven named figure families. Each figure has a JSON data sidecar plus SVG/PDF/PNG renderings with meter units, equal axes, muted baselines, and a non-rainbow colormap.

The B1 row now carries the explicit frozen center-ray max-min-angle provenance:

```text
rho_a = 5 m, rho_b = 1500 m, L = 1495 m
x* = 673.8963210702341 m
|y*| = 743.3557100464799 m
```

The representative B1 point is retained as infeasible when fresh evaluation says it is outside `C_rec`; it is never silently replaced by Hero. `q2_method_provenance.json` and the evidence table persist the unclamped/clamped construction and formula constants. `verify_gate_g.py` independently recomputes all rows, Hero, candidate thresholds, provenance, sidecars, and rendered-file headers; tamper regressions cover the table, combined and eta-specific regions, figures, qhat, and certificate flag. It does not call the Gate G builder or outer search.

Gate G evidence is stored in `src/q2/code/artifacts/q2_gate_g_fixtures.json`, `q2_gate_g_verification_report.json`, `q2_gate_g_test_output.txt`, and `Q2_GATE_G_REPORT.md`. The Gate G suite reports 11 passed; full Q2 A–G regression reports 120 passed; Q1 regression reports 10 passed; Ruff reports clean. `CERTIFIED_GLOBAL_OPTIMUM` remains `false`, candidate regions remain numerical non-proof sets, and no Gate H is claimed.

## 11. Final acceptance status

Final acceptance is based on the clean A–G/Q1 regression and the manual snapshot protocol, not on Git provenance. The required acceptance invariants are all observed:

- Gate A singleton/tangent A1 and non-vacuous completeness checks remain covered;
- Gate B retains exact `max(1000, ||G-S1||)` reception semantics and registry separation;
- Gate C preserves near-aware closure, circular wrap, dilation, and active-boundary provenance;
- Gate D's adapter remains angular-only and independent verification remains isolated from Q2 physical geometry;
- Gate E retains E1–E5 candidates, strict raw-image admissibility, all-near `Q=0`, and adaptive root isolation;
- Gate F is deterministic and explicitly non-certified, with full recommendation provenance and local checks;
- Gate G artifacts, figures, baseline provenance, candidate sets, and independent verifier all pass;
- Q1 regression is green and the complete source tree passes Ruff.

The final immutable snapshot is `q2_final_pass_v4_20260911_061033`; `q2_final_pass_v1_20260911_054912`, `q2_final_pass_v2_20260911_060603`, and `q2_final_pass_v3_20260911_060833` are superseded by this artifact-layer completion. The v4 `SNAPSHOT_MANIFEST.md` is the authoritative provenance record. The machine-readable acceptance report is `src/q2/code/artifacts/q2_final_acceptance_report.json`. No Git operation is used. If a later mathematical blocker appears, work must resume from the latest PASS snapshot rather than layering patches over it.
