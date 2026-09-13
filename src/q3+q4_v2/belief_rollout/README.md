# CLI-selectable observation-only rollout

## 2026-09-12: particle-clear feedback fix

The particle candidate stores `meta['kind']='belief_particle_clear'`. The
continuation previously checked a nonexistent boolean key instead, so the
hypothetical miss branch skipped the live controller's same-stop feedback
measurement. That check is fixed and covered by an execution regression test.
This is a conditional clear/miss/measure rollout, not a general POMCP tree.

The tested Q4 configuration is:

```powershell
python -X utf8 "src/q3+4_v2/run.py" --mode q4 --sim http --solver belief-rollout --rollout-worlds 16 --rollout-candidates 6 --rollout-every 1 --rollout-budget 60 --rollout-margin 10 --rollout-min-win-fraction 0.75 --rollout-objective mean --rollout-clear-radius 80 --rollout-clear-candidates 3 --rollout-clear-only --rollout-step-limit 300
```

Use this command from `D:\CUMCM2026`; HTTP actions are sent to the configured
server. All measurements here were local synthetic experiments, not official
submissions. The controller does not receive synthetic N, seed or scenario.

Eight reused Q4/16 seeds improved from 366.379 to 360.015 s/source. Three new
seeds (`926001,926003,926009`) improved from 366.281 to 363.943. Across all
eleven, 366.352 became 361.086: eight wins, three ties, no regression in this
sample. The six fresh Q4/10 and Q4/13 cases did not trigger search and exactly
matched the baseline. All 34 episodes completed and passed the verifier and
per-mission plan/execution audit. A single selected-action benefit is not a
guarantee for untested worlds. Maximum observed compute time was 60.13 seconds.

Reproduce with `python -X utf8 -m belief_rollout.benchmark`, setting
`--worlds 16 --candidates 6 --period 1 --budget 60 --margin 10
--min-win-fraction 0.75 --clear-radius 80 --clear-candidates 3 --clear-only
--step-limit 300` and the desired `--cases`, `--seeds`, and a new `--tag`.
Saved results are `tuning_runs/belief_rollout/particle_feedback_fix_8/results.json`
and `tuning_runs/belief_rollout/particle_feedback_fix_fresh3/results.json`.

The older generic measurement-rollout settings below describe earlier
experiments and do not enable the tested particle-clear configuration.

This is an experimental solver. `run.py` still defaults to `learned`.
No neural network is trained and no official evaluation is used by these
experiments. The new policy is selected explicitly with either
`--solver belief-rollout` or `--policy belief-rollout`.

Run from `D:\CUMCM2026`:

```powershell
python -X utf8 "src/q3+4_v2/run.py" --mode q4 --sim synthetic --seed 101 --n-sources 16 --scenario mixed --solver belief-rollout
```

Set the search budget explicitly:

```powershell
python -X utf8 "src/q3+4_v2/run.py" --mode q4 --sim synthetic --seed 101 --n-sources 16 --scenario mixed --solver belief-rollout --rollout-worlds 4 --rollout-candidates 9 --rollout-every 3 --rollout-budget 240 --rollout-margin 20
```

The current conservative Q4 preset uses paired median improvement and rejects
an action unless at least three of four hypothetical worlds prefer it:

```powershell
python -X utf8 "src/q3+4_v2/run.py" --mode q4 --sim http --solver belief-rollout --rollout-worlds 4 --rollout-candidates 9 --rollout-every 3 --rollout-budget 240 --rollout-margin 20 --rollout-objective median --rollout-min-win-fraction 0.75
```

| Argument | Default | Meaning |
|---|---:|---|
| `--solver` / `--policy` | `learned` | Select `belief-rollout` to enable this experiment |
| `--rollout-worlds` | 4 | Hypothetical maps per decision |
| `--rollout-candidates` | 9 | Candidate actions including the original action |
| `--rollout-every` | 3 | Attempt a search every third decision; 1 checks every decision |
| `--rollout-budget` | 240 | Total real seconds allocated to search per episode; 0 disables search |
| `--rollout-margin` | 20 | Required predicted improvement in total virtual seconds, not seconds per source |
| `--rollout-objective` | `mean` | Aggregate paired world deltas by `mean` or robust `median` |
| `--rollout-min-win-fraction` | 0.5 | Minimum fraction of paired worlds in which an alternative must win |

The generic defaults remain backward-compatible. For Q4, use the conservative
`median` / `0.75` pair above; its held-out results are reported in `RESULTS.md`.

The budget is checked between rollouts, so an already started rollout may
finish slightly after the budget. Once it is spent, later decisions use the
base policy. More samples/candidates are additional computation, not a
promise of better episode performance.

All existing backends work: `synthetic`, `http-synthetic`, and `http`.
In remote mode, omit `--seed`, `--n-sources`, and `--scenario`; they are only
synthetic-case generator settings. The `--sim http` path sends real actions
to the configured server, exactly as the original entry did.

Without `--output-dir`, the experimental solver writes to
`runs/q4_belief-rollout_synthetic_<seed>/` (with the chosen mode/backend),
separately from the original solver's default directory. Alongside the
ordinary action ledger and verifier report, it writes:

- `rollout_search.json`: sampling counts, candidates, per-world continuation
  costs, selected action, and actual search wall time.
- `policy_config.json`: resolved arguments and code hashes.

## Implemented scope

The implementation searches only when UNKNOWN is empty, there are at least
two ACTIVE sources, there are no READY sources, and no fallback is executing.
The production policy remains responsible for discovery, certificates,
READY clears, and finite fallback progress. This deliberately narrow first
experiment does **not** implement a joint discovery/certificate/clear planner.

At an eligible decision:

1. Preserve the original action in the candidate pool. Add alternative
   measurement stops and explicitly selected primary-only / ACTIVE scan sets.
   Reserve candidate slots for both center approaches and crossing baselines.
2. Sample source positions in their convex feasible regions. Reject samples
   inconsistent with the actual bearing bounds, near observations, reception
   constraints, failed optical clears, or the 1800 m search domain.
3. For Q4, additionally sample antenna type, direction, and receive radius;
   reject hypotheses that cannot explain positive and negative observations.
4. For every candidate and the same set of hypothetical worlds, execute the
   candidate once, then run the original controller to completion using the
   real state updates and executor action sequence. All four time components
   are charged. A branch that does not finish is not an optimistic cheap result.
5. Compare mean paired continuation costs. Override the base action only if
   the predicted improvement exceeds the margin and at least half of the
   sampled worlds improve. Execute only that first action in the real episode.

The sampling distribution is a planning assumption, **not a calibrated
posterior**. Sampled probability is never used to certify absence or success.
Historical same-position measurements are replayed exactly; future errors
are independently generated bounded deterministic values. The policy never
uses the live simulator's source positions, seed, N, or scenario.

Branch snapshots explicitly exclude bound runner callbacks, preventing a
deep copy from following those callbacks into the live executor/simulator.
If an alternative wins, all unexecuted proposal bookkeeping is restored,
not just the coverage cursor. The hypothetical execution uses the original
`V2GameRunner` update logic but exports no imagined episode artifacts.

This is sampled one-step rollout with a base-policy continuation, not a full
POMCP implementation and not an exact Bellman solver. Neither finite sampling
nor the choice of a base policy establishes a real-world improvement theorem.
Relevant original references are [Silver and Veness, Monte-Carlo Planning in
Large POMDPs](https://papers.nips.cc/paper_files/paper/2010/hash/edfbe1afcf9246bb0d40eb4d8027d90f-Abstract.html)
and [Bhattacharya et al., Partitioned Rollout and Policy Iteration for POMDP](https://www.mit.edu/~dimitrib/RA-L20_published.pdf).

## Reproduce the checks and comparison

From `D:\CUMCM2026\src\q3+4_v2`:

```powershell
python -X utf8 belief_rollout/checks.py
python -X utf8 belief_rollout/benchmark.py --seeds 101 303 505 --cases Q3:16 Q4:16 --tag default_balanced
python -X utf8 belief_rollout/benchmark.py --seeds 730013 730021 730033 --cases Q3:10 Q3:13 Q3:16 Q4:10 Q4:13 Q4:16 --tag validation_fixed
```

The benchmark uses the same generated case for both policies, and checks
each policy's plan against its actual action ledger. Case seed/N/scenario
are supplied to the evaluation harness only. Reports contain code hashes;
changing a policy creates a different experiment even if its CLI label is
the same.

Seven focused checks cover callback isolation, Q3 negative observations,
Q4 backside observations, fixed measurement replay, four-component timing,
repeatable isolated branches, and CLI argument forwarding. The disabled
solver also reproduced four Q3/Q4 baseline cases. A local HTTP run matched
the in-process run's virtual total to within 1e-6 s; no official server was used.

See `RESULTS.md` for complete-episode results and their limitations.
