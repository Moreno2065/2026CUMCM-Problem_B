# Gate G implementation plan — evidence packaging

## Scope

Do not change Hero mathematics. Build the paper-facing evidence layer on top of Gate F/E.

## Required modules

- `solver/gate_g.py`: deterministic B0/B1/B2/Hero evaluation, candidate-good regions for eta 1/2/5/10%, figure data and figure rendering (SVG/PDF/PNG), compact evidence table, and arbitrary-input demonstration.
- `verifier/verify_gate_g.py`: independently recompute headline method rows and candidate-region membership; check figure data and output existence/format.
- `tests/test_gate_g.py`: baselines executable, all four eta regions saved, seven named figures in three formats, data/table schema, general-input demo, no unsupported claim text.

## Frozen evidence rules

- B0 feasible/naive, B1 center-ray max-min-angle heuristic, B2 90-degree intersection heuristic, Hero deterministic Gate F search; all rows use the same Gate E `Q` metric.
- Preserve honest infeasible/admissibility/`Q=None` rows; never silently replace a failed baseline with Hero.
- Save `C_good(eta)` separately for eta=1%, 2%, 5%, 10% using numerical `Qhat*`; never call it a proof region.
- Generate seven named figures (`q2_geometry_overview`, `q2_crec`, `q2_angular_image`, `q2_q_surface`, `q2_optimum_and_candidate_region`, `q2_baseline_comparison`, `q2_worst_case_intersection`) as SVG, PDF, and PNG with equal geometry axes, explicit units, muted baselines, and no rainbow colormap.
- Generate compact evidence table with method, S2, Q, Crec/admissibility, move distance, all-near, worst beta, runtime, verification.
- Include at least two arbitrary legal `(S1, theta1)` demonstrations and label representative cases as illustrative; never claim a unique universal S2 or a global optimum.

## Verification

Independent verifier recomputes all table headline rows through `evaluate_q2_point` and checks all figure/data artifacts. Run Gates A–F and Q1 regressions before Gate G freeze. `CERTIFIED_GLOBAL_OPTIMUM` remains false.
