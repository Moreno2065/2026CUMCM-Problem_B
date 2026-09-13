# Q2 Gate G′ Report

**Status:** PASS  
**Evidence configuration:** `q2-final-evidence-v6-dynamic-closure`  
**Model:** frozen; no Gate A–F semantics changed

## Production evidence

The representative case is `S1=(0,0) m`, `theta1=0°`, `epsilon=1°`. The run uses the deterministic outer-search budget `(7,2,8)`, eight candidate-point workers, a `21×21` adaptive base grid, six refinement levels, a `5 m` target boundary scale, and a 32-cell-per-level cap.

The reported numerical Hero is:

```text
S2 = (800.1012338639696, -606.388471543349) m
qhat_star = 134.07676525132717 m
```

The adaptive-surface closure check is now mandatory: an independent unpaired probe automatically found `(800.0736125053295,-606.4160929019891)` with `Q=134.07805576181698 m`, locally refined it to the reported Hero, re-evaluated it through the authoritative `evaluate_q2_point`, and rebuilt the published regions. The final closure artifact records `hero_minus_best_evaluated=0` and no valid evaluated point below Hero within `1e-9 m`; production uses no hardcoded closure seed.

For the x-axis symmetric representative, refinement is paired with each geometric mirror cell. The persisted GeoJSON point counts and retained-cell areas are mirror-balanced for all four eta values. The mirror Hero is Crec-feasible/admissible with `|ΔQ|=2.2737367544323206e-13 m`.

## Adaptive numerical candidate regions

The four GeoJSON products are sampled numerical sets, explicitly **not proof regions**. Their production approximate areas are:

| eta | approximate area (m²) |
|---:|---:|
| 1% | 183.2200398695128 |
| 2% | 1031.818119265147 |
| 5% | 4175.488277026264 |
| 10% | 14165.802029911278 |

## Figure and baseline checks

Seven figure families are rendered from persisted JSON sidecars. The baseline sidecar stores numeric row indices (`B0=0`, `Hero=3`) separately from infeasible markers (`B1=1`, `B2=2`), so the Hero bar is drawn at its semantic row position. B1/B2 retain `Q=null` and an explicit `Infeasible` marker.

## Gate disposition

```text
GATE_G_PRIME = PASS
MULTIPROCESS_BACKEND = ADOPTED
CERTIFIED_GLOBAL_OPTIMUM = false
```
