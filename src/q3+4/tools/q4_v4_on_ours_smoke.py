"""Run the external Q4-v4 *source defaults* on our SyntheticSimulator.

This is deliberately an adapter, not a port: the strategy file stays untouched
under ``src/Q3_Q4_V3`` and this script never opens a result, selection-lock, or
case JSON.  The external tree has a historical import chain that eagerly reads
old selection locks.  To keep this experiment source-only, ``bridge_v4`` is
provided in-memory with precisely the geometry symbols used by ``strategy_v4``.

Usage (the requested smoke test):
    python src/q3+4/tools/q4_v4_on_ours_smoke.py --seed 101 --n-sources 16
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUR_CODE = ROOT / "src" / "q3+4" / "code"
OUR_SIMULATOR = OUR_CODE / "experiment" / "simulator.py"
FOREIGN_ROOT = ROOT / "src" / "Q3_Q4_V3"
V1 = FOREIGN_ROOT / "workstreams" / "q4_local_optimization_20260912"
V2 = FOREIGN_ROOT / "workstreams" / "q4_local_optimization_v2_20260912"
V3 = FOREIGN_ROOT / "workstreams" / "q4_uniform_optimization_v3_20260912"
V4 = FOREIGN_ROOT / "workstreams" / "q4_deep_optimization_v4_20260912"


def _load_module(name: str, path: Path) -> types.ModuleType:
    """Load one file under a controlled module name."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_our_simulator() -> types.ModuleType:
    # Its imports use the local ``geometry`` package; load it before the foreign
    # code, whose historical geometry is a different top-level module name.
    sys.path.insert(0, str(OUR_CODE))
    return _load_module("ours_synthetic_simulator", OUR_SIMULATOR)


def _install_source_only_foreign_bridge() -> None:
    """Install the minimal bridge required by strategy_v4 without lock files.

    The strategy itself is unchanged.  This only replaces the historical
    bridge's bookkeeping imports (which read selection_lock.json even though
    strategy_v4 does not need the selected parameters when called with defaults).
    """
    # ``local_geometry.py`` imports a foreign top-level module named geometry.
    # Keep our simulator's package cached afterwards, while preserving the
    # foreign functions that local_geometry bound during import.
    our_geometry = sys.modules.get("geometry")
    foreign_geometry = _load_module("_foreign_q4_geometry", FOREIGN_ROOT / "code" / "src" / "geometry.py")
    sys.modules["geometry"] = foreign_geometry
    try:
        local_geometry = _load_module("local_geometry", V1 / "local_geometry.py")
    finally:
        if our_geometry is None:
            sys.modules.pop("geometry", None)
        else:
            sys.modules["geometry"] = our_geometry

    crossbar = _load_module("_foreign_q4_crossbar", V1 / "crossbar.py")

    # V2 helper modules refer to ``base.ERROR`` and ``base.clip_polygon``.
    # They receive exactly the geometry functions used in the original bridge.
    base = types.ModuleType("base")
    for name in dir(local_geometry):
        if not name.startswith("_"):
            setattr(base, name, getattr(local_geometry, name))
    sys.modules["base"] = base

    bridge = types.ModuleType("bridge_v4")
    for name in (
        "ERROR", "DirectionBelief", "bearing_halfplanes", "clip_polygon",
        "exclude_disk", "initial_polygon", "minimum_circle", "open_tour",
        "optical_cover", "stations_and_triangles",
    ):
        setattr(bridge, name, getattr(local_geometry, name))
    bridge.probe_pair = crossbar.probe_pair
    bridge.WORK = V4
    # Imported only by a layout helper's dormant ``run`` function.
    bridge.reference = types.SimpleNamespace()
    sys.modules["bridge_v4"] = bridge

    # The remaining source helpers are resolved by their original bare imports.
    # Insert in reverse so the intended final priority is V4, V3, then V2.
    for path in (V2, V3, V4):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    # Numba imports the installed ``coverage`` package during initialization.
    # Now that Numba is already loaded, intentionally replace that module with
    # the strategy's historical geometric helper of the same name.
    _load_module("coverage", V2 / "coverage.py")


def _load_foreign_solver() -> Any:
    # Avoid cache files beside the external source tree when ordered_tour's
    # numba function is first compiled.
    os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "q4_v4_numba_cache"))
    # The foreign source has a helper named ``coverage.py``.  Numba must load
    # before that helper reaches sys.modules, otherwise it mistakes the helper
    # for its optional Python coverage package.
    import numba  # noqa: F401
    _install_source_only_foreign_bridge()
    return importlib.import_module("strategy_v4").solve


class StrategyClient:
    """Compatibility client for the external solver's small public interface."""

    def __init__(self, simulator_module: types.ModuleType, sim: Any):
        self._backend = simulator_module.SimulatorBackend(sim, robot_id="Q4V4SMOKE")
        self._sim = sim
        self.rows: list[dict[str, Any]] = []

    @property
    def position(self) -> tuple[float, float]:
        return self._sim.position

    @property
    def channel(self) -> int:
        return self._backend.current_channel

    @property
    def virtual(self) -> float:
        return self._sim.virtual_time

    def act(self, path: str, position: Any = None, channel: Any = None) -> dict[str, Any]:
        before = self.virtual
        if path == "/enter":
            reply = self._backend.enter()
        elif path == "/exit":
            reply = self._backend.exit()
        elif path == "/measure":
            reply = self._backend.measure(position, int(channel))
        elif path == "/clear":
            reply = self._backend.clear(position, int(channel))
        else:
            raise ValueError("unsupported action %r" % path)
        self.rows.append({
            "sequence": len(self.rows) + 1,
            "path": path,
            "position": None if position is None else [float(position[0]), float(position[1])],
            "channel": None if channel is None else int(channel),
            "response": dict(reply),
            "virtual_before_s": before,
            "virtual_after_s": self.virtual,
        })
        return reply


def run(seed: int, n_sources: int, scenario: str, error_field: str) -> dict[str, Any]:
    simulator_module = _load_our_simulator()
    solver = _load_foreign_solver()
    sim = simulator_module.SyntheticSimulator(
        "Q4", seed=seed, n_sources=n_sources, scenario=scenario,
        error_field_type=error_field,
    )
    client = StrategyClient(simulator_module, sim)
    client.act("/enter")
    # Intentionally no kwargs: this is strategy_v4's source-declared defaults.
    result = solver(client)
    client.act("/exit")

    truth = sim.ground_truth()
    cleared = [source for source in truth if source["cleared"]]
    measure_rows = [r for r in client.rows if r["path"] == "/measure"]
    clear_rows = [r for r in client.rows if r["path"] == "/clear"]
    return {
        "experiment": "external Q4-v4 source defaults on ours SyntheticSimulator",
        "parameters_source": "strategy_v4.solve defaults only; no historical JSON read",
        "seed": seed,
        "scenario": scenario,
        "error_field": error_field,
        "source_count": len(truth),
        "cleared_count": len(cleared),
        "all_cleared": len(cleared) == len(truth),
        "virtual_time_s": sim.virtual_time,
        "seconds_per_source": sim.virtual_time / len(truth),
        "actions": len(client.rows),
        "measure_actions": len(measure_rows),
        "clear_actions": len(clear_rows),
        "successful_clears": sum(
            r["response"].get("clear_result") == "success" for r in clear_rows
        ),
        "failed_clears": sum(
            r["response"].get("clear_result") == "no_target_in_range" for r in clear_rows
        ),
        "solver_reported_cleared": result.get("cleared_count"),
        "exited": sim.exited,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--n-sources", type=int, default=16)
    parser.add_argument("--scenario", default="random",
                        choices=("random", "boundary", "dense", "sparse", "mixed", "edge_facing"))
    parser.add_argument("--error-field", default="random_fixed",
                        choices=("random_fixed", "boundary", "structured"))
    args = parser.parse_args()
    print(json.dumps(run(args.seed, args.n_sources, args.scenario, args.error_field),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
