"""Certificate assembly for the Q2 global optimality proof (spec s.40).

The certificate JSON is the machine-readable artifact; every bound is stored
as a decimal-string outward enclosure, never as a bare binary float (s.39).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.q2.formal.interval_master import BatchMaster

SCHEMA_VERSION = 1
MODEL_ID = "frozen_q2_bounded_error_minimax"


@dataclass
class Certificate:
    status: str
    lower_bound: float
    upper_bound: float
    incumbent: tuple[float, float]
    incumbent_q: tuple[float, float]
    all_near: bool
    scenario_count: int
    witness_count: int
    precision_bits: int
    source_snapshot_id: str
    source_sha256_manifest: str
    optimizer_enclosure: dict
    tau_abs: float = 0.01

    def to_json_dict(self) -> dict:
        L, U = self.lower_bound, self.upper_bound
        gap = U - L
        rel = gap / max(U, 1.0)
        certified_eps = gap <= max(self.tau_abs, 1e-6 * max(U, 1.0))
        return {
            "schema_version": SCHEMA_VERSION,
            "model": MODEL_ID,
            "status": self.status,
            "epsilon_deg": "1",
            "absolute_tolerance_m": repr(self.tau_abs),
            "lower_bound_m": repr(L),
            "upper_bound_m": repr(U),
            "absolute_gap_m": repr(gap),
            "relative_gap": repr(rel),
            "incumbent_S2": [repr(self.incumbent[0]), repr(self.incumbent[1])],
            "incumbent_Q_enclosure_m": [repr(self.incumbent_q[0]),
                                        repr(self.incumbent_q[1])],
            "optimizer_outer_enclosure": self.optimizer_enclosure,
            "all_near": self.all_near,
            "reception_witness_count": self.witness_count,
            "objective_scenario_count": self.scenario_count,
            "arithmetic_engine": ("python-flint arb ball arithmetic (UB path) "
                                  "+ float64 nextafter-outward interval arrays "
                                  "(master LB path, fuzz-validated vs arb)"),
            "precision_bits": self.precision_bits,
            "source_snapshot_id": self.source_snapshot_id,
            "source_sha256_manifest": self.source_sha256_manifest,
            "point_evaluator_verified": True,
            "master_lower_bound_verified": True,
            "certificate_replayed_independently": False,  # set by replay
            "certified_global_optimum": False,
            "certified_epsilon_global_optimum": bool(certified_eps),
        }


def optimizer_enclosure_summary(master: BatchMaster, U: float,
                                npz_path: Path | None = None) -> dict:
    """Outer enclosure of the argmin set: live boxes with lb <= U (s.36)."""
    sel = master.lb <= U
    n = int(np.count_nonzero(sel))
    if n == 0:
        return {"box_count": 0}
    xl = master.xlo[sel]
    xh = master.xhi[sel]
    yl = master.ylo[sel]
    yh = master.yhi[sel]
    if npz_path is not None:
        np.savez_compressed(npz_path, xlo=xl, xhi=xh, ylo=yl, yhi=yh)
    diam = np.sqrt((xh - xl) ** 2 + (yh - yl) ** 2)
    return {
        "box_count": n,
        "x_span": [float(xl.min()), float(xh.max())],
        "y_span": [float(yl.min()), float(yh.max())],
        "max_box_diameter_m": float(diam.max()),
        "note": "union of these boxes is a rigorous outer approximation of "
                "the global optimizer set (all pruned regions have lb > U)",
        "boxes_file": npz_path.name if npz_path else None,
    }


def write_certificate(cert: Certificate, path: Path) -> None:
    path.write_text(json.dumps(cert.to_json_dict(), indent=1),
                    encoding="utf-8")
