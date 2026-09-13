# Q2 final immutable snapshot — Gate G′ V3

snapshot_id = q2_final_pass_v16_20260911_103800
snapshot_created_at = 2026-09-11T10:38:00+08:00
gate_status = GATE_G_PRIME=PASS; MULTIPROCESS_BACKEND=ADOPTED; CLEAN_ROOM_HANDOFF=PASS; FINAL_ACCEPTANCE_V3=PASS
source_snapshot = q2_gate_g_pass_v1_20260911_054813
verification_report = q2/code/artifacts/q2_final_verification_report.json
evidence_config = q2/code/artifacts/q2_final_evidence_config.json
benchmark = q2/code/artifacts/q2_batch_benchmark.json
git = not used
source_file_count = 290
snapshot_file_count = 290
hash_audit = SOURCE_FILES=290 SNAPSHOT_FILES=290 MISSING=0 EXTRA=0 HASH_MISMATCH=0

## Changes in this snapshot

- Dynamic Hero closure automatically discovers/promotes the better sampled evidence and rebuilds final mirror-paired regions with no hardcoded production seed.
- Persisted closure provenance and independent verifier checks close the stale-Hero evidence gap.
- Baseline numeric row positions are persisted; B1/B2 remain explicit infeasible markers and Hero is drawn at row index 3.
- Serial evaluation remains the reference; ProcessPool is an equivalent optional backend.
- Q1 Numba disk caching is disabled for safe clean-room imports; `__pycache__` is excluded from handoff.

## Verification

Q2 = 148 passed, 1 skipped  
Q1 = 11 passed  
Ruff (Q2) = All checks passed  
Gate G′ production checks = 7 passed  
Clean-room ZIP = 1 passed in 497.88s on the v13 executable tree

## Claim boundary

`CERTIFIED_GLOBAL_OPTIMUM = false`. Hero and eta candidate regions are deterministic numerical evidence; candidate regions are sampled non-proof sets. Gate H is not implemented.
