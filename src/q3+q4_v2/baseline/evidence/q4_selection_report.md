# Task9 matched Q4 factorial selection report

Scope: `ablation_q4.json` only. Holdout was not read or used. All statistics below are over six matched cases; `std` is population standard deviation and `t_per_source_s` is per-case `T_j/n_j`.

## Inputs and execution

- Case file: `cases/e_branches_v1/ablation/ablation_q4.json`
- Config: `configs/e_branches_matched_base.yaml`
- Case SHA-256: `b2c3830a1c66c7e4bc35e75b48bc311ce1c98cc7aa2b2d48932148e07965714e`
- Config SHA-256 / provenance frozen-config hash: `fb94258dd5392c0627fbcdd88c29459a671b1ee9c79f516e857f976cf77c053b`
- Single-factor run count: 36 (6 variants × 6 cases); all 36 completed and passed.
- Factorial run count: 96 (16 masks × 6 cases); all 96 completed and passed.
- Factorial verifier reports scanned: 96/96; `all_ok=true`: 96/96.
- Case failures: 0; verifier failures: 0; clear-rate failures: 0.

The first full factorial invocation returned 1 after 34 cases without a suite summary. The affected `e_combo_0101` cases and remaining masks were rerun; the final factorial tree used here is complete and all 96 hard gates pass.

## Factorial results

Factor order is `E1 E2 E3 E4`; `✓` means enabled. Every row is correctness-eligible: 6/6 success, 6/6 verifier pass, and minimum clearance 1.0.

| Variant | E1 | E2 | E3 | E4 | t/source mean | median | std | measures mean | median | std | switches mean | median | std |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e_combo_0000 |  |  |  |  | 1334.028 | 1373.300 | 313.182 | 743.667 | 758.0 | 166.797 | 653.500 | 666.0 | 149.438 |
| e_combo_0001 |  |  |  | ✓ | 2674.885 | 2738.393 | 498.106 | 1358.500 | 1372.0 | 265.913 | 1201.167 | 1214.0 | 247.698 |
| e_combo_0010 |  |  | ✓ |  | 1359.111 | 1355.924 | 274.322 | 732.000 | 727.5 | 120.110 | 629.667 | 626.5 | 126.334 |
| e_combo_0011 |  |  | ✓ | ✓ | 2697.084 | 2695.136 | 442.735 | 1348.833 | 1370.0 | 225.203 | 1182.667 | 1178.0 | 217.774 |
| e_combo_0100 |  | ✓ |  |  | 1507.650 | 1547.625 | 344.840 | 765.667 | 828.5 | 180.091 | 669.667 | 711.5 | 149.905 |
| e_combo_0101 |  | ✓ |  | ✓ | 2762.852 | 2816.031 | 464.899 | 1273.000 | 1305.5 | 207.440 | 1131.333 | 1174.5 | 202.254 |
| e_combo_0110 |  | ✓ | ✓ |  | 1437.830 | 1442.926 | 364.923 | 773.167 | 721.5 | 221.522 | 665.333 | 622.0 | 187.931 |
| e_combo_0111 |  | ✓ | ✓ | ✓ | 2801.228 | 2859.931 | 480.701 | 1341.500 | 1397.5 | 227.172 | 1178.167 | 1227.5 | 204.691 |
| e_combo_1000 | ✓ |  |  |  | **1077.722** | 1018.359 | 312.550 | 683.000 | 600.5 | 194.661 | 608.167 | 547.0 | 180.816 |
| e_combo_1001 | ✓ |  |  | ✓ | 1093.054 | 1064.355 | **311.896** | 685.167 | 607.0 | 193.754 | 610.333 | 553.5 | 180.090 |
| e_combo_1010 | ✓ |  | ✓ |  | 1188.437 | 1095.985 | 422.568 | 780.333 | 678.5 | 325.447 | 676.167 | 588.5 | 283.275 |
| e_combo_1011 | ✓ |  | ✓ | ✓ | 1196.520 | 1120.233 | 420.672 | 782.000 | 683.5 | 324.569 | 677.667 | 593.0 | 282.626 |
| e_combo_1100 | ✓ | ✓ |  |  | 1305.335 | 1337.498 | 347.471 | 737.667 | 778.0 | 177.742 | 633.833 | 664.5 | 166.446 |
| e_combo_1101 | ✓ | ✓ |  | ✓ | 1316.211 | 1347.098 | 351.061 | 740.667 | 783.0 | 178.671 | 636.500 | 672.5 | 166.957 |
| e_combo_1110 | ✓ | ✓ | ✓ |  | 1188.437 | 1095.985 | 422.568 | 780.333 | 678.5 | 325.447 | 676.167 | 588.5 | 283.275 |
| e_combo_1111 | ✓ | ✓ | ✓ | ✓ | 1196.520 | 1120.233 | 420.672 | 782.000 | 683.5 | 324.569 | 677.667 | 593.0 | 282.626 |

## Frozen selection

The hard gate is: all six cases complete without run failure, all six `metrics.verifier_all_ok=true`, all six `verifier_report.all_ok=true`, and all six `clear_rate=1.0`. The composite pool is `e_combo_0001`–`e_combo_1111`; `e_combo_0000` is the no-branch reference.

The frozen ranking rule is: minimize mean `t_per_source_s`; if a candidate is within 2% of the best mean, choose lower `t_per_source_s` std, then fewer mean measures, then fewer mean switches, then lexicographically smaller mask. The best mean is `e_combo_1000` at 1077.722 s/source; the 2% limit is 1099.276 s/source. Only `e_combo_1000` and `e_combo_1001` are inside this band. `e_combo_1001` is selected because its std is lower (311.896 vs 312.550), despite a 15.332 s/source higher mean.

Selected correctness-eligible composite: **`e_combo_1001` (E1 + E4; E2/E3 off)**.

Selected metrics: mean/median/std `t_per_source_s` = 1093.054/1064.355/311.896 s; measures = 685.167/607.0/193.754; switches = 610.333/553.5/180.090. Against the matched mainline reference, mean `t_per_source_s` changes by −240.974 s (−18.063%). This is an ablation-set selection only, not a holdout result, global-optimality certificate, or mainline code/config change.

Machine-readable details are in [`selection_report.json`](selection_report.json).
