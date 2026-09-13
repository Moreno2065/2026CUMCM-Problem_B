# Q2 Final Implementation Report — Gate G′

**Status:** implementation and handoff complete through Gate G′  
**Frozen model:** unchanged  
**Final snapshot:** `q2_final_pass_v16_20260911_103800`

Gate G′ remains evidence-layer work only. The frozen A1/Crec/angular/Q1/E1–E5 semantics and the deterministic non-certified outer search are unchanged.

## G′ additions

1. The adaptive candidate-region builder supports mirror-cell pairing for the symmetric representative. Point samples and retained-cell areas are checked for mirror balance at eta `1%`, `2%`, `5%`, and `10%`.
2. Gate G now closes the Hero/adaptive-surface loop. A valid surface point below Hero is locally refined and re-evaluated through the authoritative single-point evaluator before promotion; adaptive regions are then rebuilt. The final artifact asserts that the valid surface minimum is not below Hero within tolerance.
3. Baseline figure sidecars persist numeric row positions, keeping B1/B2 as explicit infeasible markers while drawing Hero at row index 3.
4. The ProcessPool candidate-point backend remains optional, spawn-safe, order-preserving, and exactly equivalent to the serial reference evaluator.
5. The handoff is validated from a clean extraction with an isolated `PYTHONPATH`.

The representative Hero is `(800.1012338639696, -606.388471543349) m` with `qhat_star=134.07676525132717 m`. The closure probe discovers and promotes better sampled evidence without a hardcoded production seed. Candidate regions are numerical sampled sets, not proof regions. `CERTIFIED_GLOBAL_OPTIMUM = false`; no universal optimum or Gate H claim is emitted.
