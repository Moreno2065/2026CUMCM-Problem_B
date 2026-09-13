# Complete-episode evaluation, 2026-09-12

Verdict: keep `belief-rollout` as an opt-in experiment. It has **not** shown
a large or uniform gain. The original `learned` policy remains the default.

## Conservative Q4 selector

Post-analysis of the original validation failures found that the mean selector
could be dominated by one extreme hypothetical world. A candidate whose paired
deltas were `[-2.5, -430.1, -2.5, -2.5]` passed a 20 second mean margin even
though its median improvement was only 2.5 seconds. The Q4 selector was
therefore retested with `--rollout-objective median` and
`--rollout-min-win-fraction 0.75`; the simulator, candidate generator and
production continuation policy were unchanged.

Five new seeds (`910003`, `910019`, `910031`, `910051`, `910057`) were fixed
before the final run:

| Group | Production mean | Robust rollout mean | Delta | Production max | Rollout max |
|---|---:|---:|---:|---:|---:|
| Q4/10 | 736.686 | 736.686 | 0.000 | 830.329 | 830.329 |
| Q4/13 | 552.453 | 545.999 | -6.453 | 613.016 | 613.016 |
| Q4/16 | 400.039 | 396.046 | -3.993 | 466.661 | 464.281 |

All 30 episodes (15 production/rollout pairs) completed and passed the verifier with zero
plan/execution mismatches. No rollout episode was slower than its paired
production episode. This is evidence for a conservative, modest Q4 gain; it is
not evidence for the 184 or 290 seconds/source target. Raw output is under
`../tuning_runs/belief_rollout/q4_median_holdout5/`.

On the six earlier development/validation seeds, the same fixed selector left
the maximum unchanged and changed the means by `-0.511` seconds/source for
Q4/13 and `-9.796` for Q4/16. Because those seeds influenced the selector,
they are diagnostic data rather than held-out evidence.

The final candidate generator reserves slots for both center approaches and
crossing baselines. Its defaults are 4 worlds, 9 candidates, a search attempt
every 3 decisions, a 20 virtual-second improvement margin, and a total search
budget of 240 real seconds. Neither true N nor scenario selects policy knobs.

## Development cases

Seeds: 101, 303, 505. Seconds per source; negative delta is faster.

| Group | Original mean | Rollout mean | Delta | Original max | Rollout max |
|---|---:|---:|---:|---:|---:|
| Q3/16 | 266.962 | 267.147 | +0.185 | 280.502 | 281.020 |
| Q4/16 | 385.351 | 379.884 | -5.467 | 456.758 | 451.848 |

All three Q4 development episodes improved modestly. That observation alone
was not used as proof of a general improvement.

Raw paired results and source hashes:
`../tuning_runs/belief_rollout/default_balanced/results.json`.

## Fixed validation cases

Seeds 730013, 730021, 730033 were fixed before this validation run. No policy
parameter was changed after seeing these results. Each group has only three
episodes; its maximum is reported instead of presenting a poorly resolved P90.

| Group | Original mean | Rollout mean | Delta | Original max | Rollout max |
|---|---:|---:|---:|---:|---:|
| Q3/10 | 436.194 | 436.194 | 0.000 | 464.645 | 464.645 |
| Q3/13 | 413.623 | 404.219 | -9.404 | 448.390 | 430.533 |
| Q3/16 | 319.829 | 319.829 | 0.000 | 340.639 | 340.639 |
| Q4/10 | 708.856 | 708.856 | 0.000 | 743.443 | 743.443 |
| Q4/13 | 560.729 | 564.062 | +3.333 | 617.638 | 630.705 |
| Q4/16 | 459.433 | 449.253 | -10.180 | 538.505 | 550.059 |

Q4/16's validation mean improved by 2.2%, but its slowest episode worsened.
Q4/13 also worsened. Q3/16 made no action changes in these validation episodes.
This does not meet a criterion of a substantial, stable speedup.

Raw paired results and source hashes:
`../tuning_runs/belief_rollout/validation_fixed/results.json`.

## Checks

- Final development plus validation: 24 paired cases, **48/48 episodes**
  complete and verifier-passing.
- Action-plan audit on those same episodes: **2624 matched**, 14 legitimate
  cardinality-related prefixes, **0 mismatches**.
- The longest wall-clock episode in that set was **7.99 s** on this machine.
  This is not an estimate for larger search budgets or other hardware.
- Seven focused checks passed: snapshot callback isolation, Q3 exclusions,
  Q4 directional negative observations, historical reply determinism,
  action cost semantics, isolated repeatable rollouts, and CLI forwarding.
- Search disabled: four Q3/Q4 cases reproduced the baseline metrics exactly.
- Default entry equivalence: 3/3 existing cases passed after CLI integration.
- New CLI in-process vs local HTTP: same actions/counts and virtual total
  within 1e-6 s for Q3/16, seed 101, 2 worlds / 5 candidates / every 5 decisions.
- Python compilation passed. No official test attempt was used.

The sampling and branch tests verify implementation properties; they do not
establish statistical calibration of the hypothesis distribution.

## Earlier prototypes and interpretation

The first pool filled with source centers before reaching crossing-baseline
candidates. With 4 worlds / 12 candidates / every decision it worsened the
three-seed means by 20.892 s/source on Q3/16 and 26.357 on Q4/16. A larger
16-world configuration with a more conservative margin made no Q3 overrides
on those seeds. Those are older prototype results, not results of the final
balanced candidate generator. They are retained under
`dev_w4_c12_p1` and `dev_w16_c9_p3_m80` for transparency.

What is demonstrated: a deployable, observation-only, no-training rollout
interface can replace selected actions, using full continuation costs and
the actual executor rather than one-step proxy gains. What is not
demonstrated: near-optimal performance, a reliable 10–20% gain, or a route
that jointly performs discovery, absence certification and clearance.

The scope limit is material: the experimental search begins only after
UNKNOWN is empty and skips READY/fallback states. It cannot recover travel
or scanning time already spent discovering sources and resolving unknown
channels. Extending planning into those stages would require a model for
unseen sources and joint source-count uncertainty, plus separate validation;
it is not an effect that increasing `--rollout-worlds` alone can deliver.
