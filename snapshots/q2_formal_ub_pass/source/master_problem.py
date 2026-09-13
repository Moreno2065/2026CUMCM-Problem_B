"""Master-problem data model and JSON serialization (spec s.8, s.39, s.52).

The finite master relaxation at round k is

    L_k = inf_{S2 in D_k} max_{s in S_k} loss(S2; s),
    D_k = B0 cap_{G in W_k} B(G, max(1000, |G|)),   D_k supseteq Crec.

This module only defines the serializable records (scenarios, reception
witnesses) used by the proof loop, the artifacts, and the replay verifier.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from src.q2.formal.interval_master import BatchMaster, ReceptionWitness
from src.q2.formal.scenario_loss import Scenario


@dataclass(frozen=True)
class ScenarioRecord:
    gx: float
    gy: float
    e_deg: float
    label: str
    added_iteration: int
    support_type: str = ""
    eta: float = 0.0

    def to_scenario(self) -> Scenario:
        return Scenario(self.gx, self.gy, self.e_deg, label=self.label)


@dataclass(frozen=True)
class WitnessRecord:
    gx: float
    gy: float
    radius: float
    added_iteration: int
    violation: float = 0.0

    def to_witness(self) -> ReceptionWitness:
        return ReceptionWitness(self.gx, self.gy, self.radius)


def records_to_master(
    scenarios: list[ScenarioRecord],
    witnesses: list[WitnessRecord],
    b0: tuple[float, float, float, float],
    upper_bound: float,
) -> BatchMaster:
    """Rebuild a master with the recorded cuts (order preserved).

    NOTE: the rebuilt master has unevaluated live boxes (root only); the
    replay must re-run the B&B.  The recorded sets are the proof objects.
    """
    m = BatchMaster(b0=b0, upper_bound=upper_bound)
    for w in witnesses:
        m.add_witness(w.to_witness())
    for s in scenarios:
        m.add_scenario(s.to_scenario(), refresh_band=None)
    return m


def dump_records(scenarios: list[ScenarioRecord],
                 witnesses: list[WitnessRecord], path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scenarios": [asdict(s) for s in scenarios],
                "witnesses": [asdict(w) for w in witnesses],
            },
            f, indent=1,
        )


def load_records(path) -> tuple[list[ScenarioRecord], list[WitnessRecord]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return (
        [ScenarioRecord(**s) for s in data["scenarios"]],
        [WitnessRecord(**w) for w in data["witnesses"]],
    )
