"""Assemble the final machine-replayable certificate (spec s.40, s.53).

.. deprecated:: Closure phase (FINAL CERTIFICATE CLOSURE SPEC).
   This builder writes the OLD v1 schema certificate from the fast-loop
   replay artifacts.  The shipped certificate is now produced by
   ``finalize_certificate.py`` (schema v2, §42).  Running this script again
   would OVERWRITE the closure certificate - do not run it.

Reads the frozen artifacts (replay result, incumbent UB certification, cut
records, optimizer enclosure), builds the snapshot ``q2_formal_cert_final``
(source + artifacts + tests + SHA256 manifest, no git), and writes

    src/q2/artifacts/formal/q2_global_optimality_certificate.json

The certificate claims a status only as strong as the recorded replay: the
``CERTIFIED_GLOBAL_EPS_OPTIMUM`` status requires ``replay_result.json`` with
``passed == true`` (spec s.41).  All bound fields are decimal strings; the
incumbent Q enclosure is taken verbatim from the outward Arb decimal
enclosure produced by the certification, never from bare floats.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from src.q2.formal.certificate import Certificate
from src.q2.formal.proof_loop import make_snapshot

ARTIFACTS = Path("src/q2/artifacts/formal")
SNAPSHOTS = Path("snapshots")
SNAPSHOT_ID = "q2_formal_cert_final"

_REPLAY_SUMMARY_KEYS = (
    "passed", "ub_recertified", "master_replayed",
    "sampled_boxes_checked", "max_cross_engine_excess", "wall_time_s",
)


def main() -> None:
    replay = json.loads((ARTIFACTS / "replay_result.json")
                        .read_text(encoding="utf-8"))
    inc = json.loads((ARTIFACTS / "incumbent_upper_bound.json")
                     .read_text(encoding="utf-8"))
    opt = json.loads((ARTIFACTS / "optimizer_boxes.json")
                     .read_text(encoding="utf-8"))
    cuts = json.loads((ARTIFACTS / "master_cuts.json")
                      .read_text(encoding="utf-8"))

    replayed = bool(replay.get("passed"))
    if replayed:
        status = replay["status"]
        lower = float(replay["lower_bound"])
        upper = float(replay["upper_bound"])
    else:
        # replay did not pass: the strongest honest status is the
        # numerical-enclosure one (spec s.2 / s.44 - never upgrade wording)
        status = "CERTIFIED_GLOBAL_OPTIMUM_TO_NUMERICAL_ENCLOSURE"
        mlb = json.loads((ARTIFACTS / "master_lower_bound.json")
                         .read_text(encoding="utf-8"))
        lower = float(mlb["lower_bound"])
        upper = float(mlb["upper_bound"])

    cert = Certificate(
        status=status,
        lower_bound=lower,
        upper_bound=upper,
        incumbent=(float(inc["incumbent_S2"][0]),
                   float(inc["incumbent_S2"][1])),
        incumbent_q=(float(inc["q_lo"]), float(inc["q_hi"])),
        all_near=bool(inc["all_near"]),
        scenario_count=len(cuts["scenarios"]),
        witness_count=len(cuts["witnesses"]),
        precision_bits=256,  # replay re-certification precision (s.41 step 3)
        source_snapshot_id=SNAPSHOT_ID,
        source_sha256_manifest="",   # filled after the snapshot is built
        optimizer_enclosure=opt,
    )
    d = cert.to_json_dict()
    d["certificate_replayed_independently"] = replayed
    d["incumbent_Q_enclosure_m"] = list(inc["q_interval_decimal"])
    d["replay"] = {k: replay[k] for k in _REPLAY_SUMMARY_KEYS if k in replay}

    # --- snapshot (s.53): source + artifacts + tests + sha256 manifest ---
    snap = make_snapshot(SNAPSHOT_ID, {
        "status": status,
        "lower_bound": lower,
        "upper_bound": upper,
        "absolute_gap": upper - lower,
        "replay_passed": replayed,
        "incumbent": inc["incumbent_S2"],
    }, ARTIFACTS)
    tests_dest = snap / "tests"
    tests_dest.mkdir(exist_ok=True)
    for p in sorted(Path("src/q2/tests_formal").glob("*.py")):
        shutil.copy2(p, tests_dest / p.name)
    manifest_path = snap / "source_manifest_sha256.json"
    d["source_sha256_manifest"] = hashlib.sha256(
        manifest_path.read_bytes()).hexdigest()

    out = ARTIFACTS / "q2_global_optimality_certificate.json"
    out.write_text(json.dumps(d, indent=1), encoding="utf-8")
    # keep the snapshot self-contained (it was built before the certificate)
    (snap / "artifacts" / out.name).write_text(
        out.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"wrote {out}")
    print(f"snapshot: {snap}")
    print(f"status: {status} | L={lower!r} U={upper!r} gap={upper - lower!r}")


if __name__ == "__main__":
    main()
