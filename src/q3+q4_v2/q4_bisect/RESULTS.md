# Q4 midpoint-pair bisection: frozen result

## Final policy

`q4-bisect` is an independently selectable Q4 policy.  It keeps the complete
production discovery, certificate, rolling scheduler, and optical fallback.
It inserts a certified two-point localization action only when all of the
following observable conditions hold:

- 16 channels have already been confirmed present;
- the channel is still `ACTIVE`, has at least four consecutive ineffective
  localization updates, and its feasible area is at least 5000 m²;
- the first point adds no more than 500 m to the next pending coverage leg;
- the channel has used fewer than two pair rounds and the game fewer than six;
- no `READY` channel or active fallback currently takes priority.

No source count, scenario label, source position, radius, or orientation is
read from the simulator.  The `16` gate is reached from observations alone.
Consequently the policy cannot change a 10--15 source run.

The defaults exposed by `run.py` are the frozen configuration.  Reproduce one
synthetic case with:

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q4 --sim synthetic `
  --policy q4-bisect --seed 101 --n-sources 16 --scenario random
```

## Frozen unseen random comparison

The configuration was frozen before evaluating these ten seeds.  Values are
seconds per source and each row is a paired deterministic run.

| seed | production | q4-bisect | delta |
|---:|---:|---:|---:|
| 135791 | 525.415 | 525.415 | 0.000 |
| 246803 | 456.732 | 444.097 | -12.635 |
| 357919 | 517.175 | 517.175 | 0.000 |
| 468031 | 485.309 | 485.309 | 0.000 |
| 579143 | 508.025 | 496.284 | -11.741 |
| 680257 | 529.135 | 528.947 | -0.188 |
| 791369 | 446.550 | 449.426 | +2.876 |
| 802483 | 484.040 | 474.649 | -9.391 |
| 812341 | 516.368 | 503.121 | -13.247 |
| 923457 | 514.634 | 514.873 | +0.239 |
| **mean** | **498.338** | **493.930** | **-4.409** |

Outcome: five wins, three exact non-triggers, and two regressions.  All twenty
paired runs completed, passed the verifier, and retained the true source in
every audited feasible polygon.  This is a modest mean improvement and a
useful tail rescue, not evidence that Q4 has reached its global optimum.

The immutable raw result is
[`final_budget6_random16_unseen10/results.json`](../tuning_runs/q4_bisect/final_budget6_random16_unseen10/results.json).

## Other checks

- Observable 16-channel gate: on five development seeds each, Q4/10 and Q4/13
  are exactly identical to production.  Q4/16 changes from 450.533 to 443.113
  s/source on the same block.  Raw result:
  [`gated16_n3_r2_dev5/results.json`](../tuning_runs/q4_bisect/gated16_n3_r2_dev5/results.json).
- Geometry: 300,000 randomized states, including 224,939 far-half cases,
  found zero counterexamples.  The analytic maximum probe distance is
  751.254 m, below the guaranteed 1000 m reception radius; first-round probe
  separation is 26.1905 m.  Run `q4_bisect/checks.py` to repeat it.
- Plan versus execution: the final audit records 164 exact missions, one legal
  cardinality truncation, and zero mismatches for both policies.
- Direct simulator versus synthetic HTTP: both produce 3256.426561 s total,
  203.526660 s/source, 189 actions, and zero action differences within `1e-5`.
- Model checks: 9/9 passed.

The pressure tests show why the global six-round budget is retained: it turns
the three-case dense block from a +2.162 regression into a -4.929 s/source
improvement.  Edge-facing and boundary blocks improve by about 14.2 s/source;
the sparse block has high variance, including one large win and one small
regression.  These blocks were used during development and are not holdout
evidence.

## Safety boundary

The half-space cut is applied only after two physical `no_signal` records at
the planned pair.  A direction result rejected by the baseline consistency
filter is not treated as negative evidence.  The derived cut changes only the
source-position feasible polygon; it never certifies a channel absent and
never replaces the existing finite optical fallback.
