# Q2 Gate C Angular Image Implementation Plan

> **For agentic workers:** Execute inline with test-driven development. Git/worktree/commit steps are replaced by the approved immutable snapshot protocol.

**Goal:** Construct the exact closed bearing-angle image of `A1` after strict near partitioning, expand it by the frozen one-degree measurement error, independently verify it, and stop before Gate D.

**Architecture:** `geometry/circular_intervals.py` is a neutral circle-set algebra. `geometry/angular_image.py` clips only `A1BoundaryRegistry` primitives by the open 5 m near disk, adds active near-circle arcs, builds an unrestricted boundary-component graph, and maps every component through endpoint/tangent extrema. `verifier/verify_angular.py` independently samples original A1 boundaries and radial interiors without importing the angular-image solver.

**Tech Stack:** Python dataclasses/enums, existing `Point2`/`LineSegment`/`CircularArc`/`BoundaryPoint`, pytest, deterministic JSON fixtures; no Q1 or Crec witness consumption.

---

### Task 1: Neutral circular interval algebra

**Files:** create `geometry/circular_intervals.py`, create `tests/test_gate_c.py`.

- [x] Write failing tests for empty/full states, `359..1` wrap, `-180/+180`, touching merge, dilation merge, dilation to full circle, disjoint unions, containment, normalization, and angular distance.
- [x] Run the focused tests and confirm they fail because the module is absent.
- [x] Implement canonical closed segments on `[0,2pi]`, circular wrap normalization, union, dilation, membership, rotation, and distance.
- [x] Run the interval tests and Gate A/B regressions.

### Task 2: POINT, all-near, and API semantics

**Files:** create `geometry/angular_image.py`, extend `tests/test_gate_c.py`.

- [x] Write failing tests for tangent POINT A1 at distances greater than, equal to, and less than 5 m.
- [x] Implement `AngularImageResult`, endpoint provenance, strict actual-bearing semantics, closed worst-case union, one-degree expansion, and POINT/all-near handling.
- [x] Add type-level rejection of anything other than `A1BoundaryRegistry`, including `CrecWitnessRegistry`.
- [x] Run focused tests and retain red/green evidence.

### Task 3: Near clipping and unrestricted components

**Files:** modify `geometry/angular_image.py`, extend `tests/test_gate_c.py`.

- [x] Add failing fixtures for ordinary, wrap, `S2=S1`, full-circle, near-crossing, and the permanent three-component geometry.
- [x] Clip every A1 line/arc against the near disk, retain all outside subpieces, and add all active near-circle arcs from line-circle and circle-circle event cuts.
- [x] Build a dynamic endpoint graph with no branch-count cap. Treat a complete near-circle loop inside A1 as a hole of one spatial component rather than a second component.
- [x] Extract per-component angular intervals using line endpoints, arc endpoints, valid carrier-circle tangencies, and direct near-arc parameters.
- [x] Merge component images with neutral circular-set union and compute dilation.

### Task 4: Independent Verifier C and property tests

**Files:** create `verifier/verify_angular.py`, extend `tests/test_gate_c.py`.

- [x] Add failing tests that prove Verifier C does not import `angular_image` and that dense boundary/radial bearings are contained in analytic closure and its dilated error set.
- [x] Independently sample all A1 primitives, near-circle directions, and A1 radial interiors; directly apply strict `distance>5` before `atan2`.
- [x] Add rigid rotation, translation, wrap equivalence, rho=1000 exclusion, rho=1500 eligibility, arbitrary component count, and 500 fixed-seed configurations.
- [x] Record maximum missing angle, endpoint disagreement, observed component/interval counts, full-circle cases, and all-near cases.

### Task 5: Gate evidence and immutable snapshot

**Files:** create Gate C fixtures/report/verification JSON/test output under `src/q2/code`; create a new top-level Gate C snapshot.

- [x] Run Gate A, Gate B, Gate C, Q1 regression, compile, independence, and Gate-boundary checks.
- [x] Confirm `q1_adapter.py`, `inner_max.py`, `outer_search.py`, and final `S2*` code remain absent.
- [x] Write provenance with `source_snapshot=q2_gate_b_pass_v2_20260911_024014`.
- [x] Copy the full `src/q2/` tree to a new non-existing Gate C snapshot, verify all source hashes, and stop without starting Gate D.
