# Gate E implementation plan — exact inner worst-case maximizer

## Scope

Implement only the inner objective for a fixed second station:

```text
S2 -> near-aware expanded bearing set -> max_beta D_Q1(S2, beta)
```

Do not add outer search, baselines, candidate regions, figures, or final-solution artifacts in Gate E.

## Required modules

- `solver/inner_max.py`: deterministic finite candidate construction for E1–E5 and the fixed-station objective.
- `solver/q2_point.py`: structured `evaluate_q2_point` output with Crec, near-aware angular, admissibility, worst-bearing and Q1 provenance.
- `verifier/verify_inner.py`: independent dense-beta and boundary/event cross-check; it must not call the production maximizer to generate the oracle.
- `tests/test_gate_e.py`: deterministic adversarial fixtures plus fixed-seed randomized valid stations.

## Frozen behavior

- reject stations outside `Crec` before bearing optimization;
- all-near returns `Q=0` and bypasses the angular admissibility gate;
- otherwise require `dist_S(circle_image, theta1) > 3*epsilon` strictly;
- an unbounded Q1 bearing returns `Q=+inf`;
- finite candidates retain provenance `E1` endpoint, `E2` apex, `E3` one-sided parallel limit, `E4` pair-distance stationary, or `E5` pair-pair envelope switch;
- root candidates are bracketed/deterministic, checked against the analytic segment and re-evaluated in Q1; no random Newton-only or coarse sweep final decision.

## Verification gates

1. TDD RED tests for E1–E5, all-near, inadmissible, outside-Crec, unbounded, wraparound, near-parallel, and provenance.
2. Independent dense-beta verifier with adaptive refinement around candidate/event bearings.
3. Minimum 500 fixed-seed valid second-station cases; analytic result must never be below the independent dense upper observation beyond a documented numerical tolerance.
4. Run Gate A–D and Q1 regressions before freezing evidence.

## Provenance and evidence

Store `q2_gate_e_fixtures.json`, `q2_gate_e_verification_report.json`, `q2_gate_e_test_output.txt`, and `Q2_GATE_E_REPORT.md` only after the tests and independent review pass. Freeze a new manual snapshot with a manifest; `CERTIFIED_GLOBAL_OPTIMUM` remains `false`.
