# Q4 joint-route transfer experiment

This package tests direct transfers of the successful Q3 route ideas while
preserving the production Q4 certificate and completion contract. It is not
wired into `run.py` because every direct variant regressed at least one source
count on the three development seeds (`101`, `303`, `505`).

Seconds per source:

| Variant | Q4/10 | Q4/13 | Q4/16 |
|---|---:|---:|---:|
| Production | 690.861 | 568.621 | 385.351 |
| ACTIVE/READY tail route | 690.343 | 582.761 | 412.617 |
| READY-only route | 700.599 | 577.535 | 393.329 |
| ACTIVE approach-only route | 690.861 | 584.279 | 446.988 |
| One ACTIVE scan at coverage stops | 736.489 | 587.627 | 399.838 |

The geometric reason is specific to Q4: Euclidean proximity does not imply a
directional source will be visible. Spatial batching can therefore select a
short route that produces `no_signal`, fails to shrink the feasible set and
later triggers a much longer fallback. A READY source also normally becomes
ready while the robot is already close, so deferring it into a batch loses the
locality that production already exploits.

These negative results motivated the sampled-world rollout. It keeps the
production certificate and completion logic, predicts directional visibility
under observation-consistent hypotheses, and changes only the first action.
See `../belief_rollout/RESULTS.md` for the held-out robust-selector results.
