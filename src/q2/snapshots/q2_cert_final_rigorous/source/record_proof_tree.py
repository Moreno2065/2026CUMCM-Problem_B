"""Re-record the master proof tree with identical frozen inputs (spec s.32).

The historical runs did not save a proof tree (OLD_TREE_NOT_REPLAYABLE), so
per spec s.32 we re-run the SAME master B&B - same 9 scenarios, same 20
witnesses, same root domain B0^-, same incumbent U, same tolerance - with
full tree recording enabled.  This is a re-recorded proof tree, not a model
change: no cut set, incumbent, objective or tolerance is touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from src.q2.formal.master_problem import load_records
from src.q2.formal.interval_master import BatchMaster
from src.q2.formal.proof_tree import (
    TreeMeta,
    TreeRecorder,
    finalize_and_save,
)

ARTIFACTS = Path("src/q2/artifacts/formal")
B0 = (0.0, 2000.0, -1000.0, 0.0)          # half-domain root (spec s.20)
G0 = (1000.0, 0.0)                        # verified A1 anchor
TAU = 0.01


def main() -> None:
    replay = json.loads((ARTIFACTS / "replay_result.json").read_text("utf-8"))
    u_cert = float(replay["upper_bound"])
    print(f"U_cert (frozen incumbent UB) = {u_cert!r}")

    scenarios, witnesses = load_records(ARTIFACTS / "master_cuts.json")
    assert len(scenarios) == 9 and len(witnesses) == 20, "cuts are frozen"

    rec = TreeRecorder(B0, u_cert, n_scenarios=len(scenarios))
    master = BatchMaster(b0=B0, upper_bound=u_cert, recorder=rec)

    t0 = time.time()
    for w in witnesses:
        n = master.add_witness(w.to_witness())
        rec.on_event("add_witness", pruned=n, gx=w.gx, gy=w.gy, radius=w.radius)
    print(f"witnesses added: live={master.lb.size} t={time.time()-t0:.1f}s")

    for s in scenarios:
        master.add_scenario(s.to_scenario(), refresh_band=None)
        rec.on_event("add_scenario", label=s.label, pruned_note="see lb")
    print(f"scenarios added: live={master.lb.size} t={time.time()-t0:.1f}s "
          f"L_setup={master.lower_bound:.10f}")

    stats = master.solve(tol=0.9 * TAU, round_cap=8192,
                         max_boxes=10_000_000, time_budget_s=3600.0)
    print(f"solve: L={stats.lower_bound!r} converged={stats.converged} "
          f"live={stats.live_boxes} rounds={stats.rounds} "
          f"t={time.time()-t0:.1f}s")

    meta = TreeMeta(b0=B0, u_cert=u_cert, tol=0.9 * TAU, round_cap=8192,
                    max_boxes=10_000_000, witness_count=len(witnesses),
                    scenario_count=len(scenarios), g0_anchor=G0)
    index = finalize_and_save(master, rec, meta, ARTIFACTS)
    print("status_counts:", json.dumps(index["status_counts"]))
    print("L_fast(recorded tree) =", index["master_lower_bound_fast"])
    print("live_final =", index["live_final_count"], "| nodes =",
          index["node_count"])

    # sanity against the independent replay re-solve (deterministic engine)
    assert stats.lower_bound <= u_cert, "L > U impossible (spec s.4)"
    if abs(stats.lower_bound - replay["lower_bound"]) > 1e-9:
        print(f"NOTE: L_new {stats.lower_bound!r} != replay L "
              f"{replay['lower_bound']!r} - allowed by spec s.32 "
              f"(certificate uses L_new)")
    if stats.live_boxes != 1012223:
        print(f"NOTE: live {stats.live_boxes} != replay 1012223 "
              "(allowed; same engine, recording is observation-only)")
    (ARTIFACTS / "proof_tree_record_summary.json").write_text(json.dumps({
        "L_fast": stats.lower_bound,
        "live_boxes": stats.live_boxes,
        "replay_L_reference": replay["lower_bound"],
        "replay_live_reference": 1012223,
        "converged": stats.converged,
        "node_count": index["node_count"],
        "status_counts": index["status_counts"],
    }, indent=1), encoding="utf-8")
    print("tree artifacts written to", ARTIFACTS)


if __name__ == "__main__":
    sys.exit(main())
