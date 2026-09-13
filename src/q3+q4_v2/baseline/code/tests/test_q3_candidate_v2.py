# -*- coding: utf-8 -*-
"""Q3 Candidate v2: retain useful incidental bearings without blind sweeps."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from experiment.suite import VARIANTS
from policy.scheduler import Mission
from state.channel_state import ChannelStatus


def test_q3_candidate_v2_is_isolated_from_frozen_candidate_v1():
    overrides, questions, _description = VARIANTS["q3_candidate_v2"]

    assert questions == ("q3",)
    assert overrides == {
        "tau": 0.15,
        "nbv_rule": "fixed_geometry",
        "channel_scan_mode": "useful_sweep",
    }
    assert VARIANTS["candidate_a1_a3"][0] == {
        "nbv_rule": "fixed_geometry",
        "channel_scan_mode": "sweep_all",
    }


def test_q3_candidate_v3_is_an_experimental_success_only_selective_branch():
    overrides, questions, _description = VARIANTS["q3_candidate_v3"]
    assert questions == ("q3",)
    assert overrides == {
        "tau": 0.15,
        "nbv_rule": "fixed_geometry",
        "channel_scan_mode": "selective_clear",
        "active_scan_margin_m": 500.0,
    }


def test_q3_useful_sweep_ablation_changes_only_scan_mode():
    overrides, questions, _description = VARIANTS["q3_useful_sweep"]

    assert questions == ("q3",)
    assert overrides == {"channel_scan_mode": "useful_sweep"}


def test_useful_sweep_skips_ready_terminal_and_duplicate_channels(tmp_path):
    runner = GameRunner(
        "Q3",
        executor=None,
        output_dir=str(tmp_path),
        config=MainlineConfig(channel_scan_mode="useful_sweep"),
    )
    position = (125.0, -75.0)

    for channel in runner.ks.channels.values():
        channel.status = ChannelStatus.CLEARED

    duplicate_unknown = runner.ks[1]
    duplicate_unknown.status = ChannelStatus.UNKNOWN
    duplicate_unknown.observations.append({
        "position": position,
        "result": "no_signal",
    })

    active = runner.ks[2]
    active.status = ChannelStatus.ACTIVE

    ready = runner.ks[3]
    ready.status = ChannelStatus.READY

    fresh_unknown = runner.ks[4]
    fresh_unknown.status = ChannelStatus.UNKNOWN

    runner.ks[5].status = ChannelStatus.CERTIFIED_ABSENT

    assert runner._scan_set(position) == [2, 4]


def test_selective_sweep_skips_active_channels_outside_signal_reach(tmp_path):
    runner = GameRunner(
        "Q3",
        executor=None,
        output_dir=str(tmp_path),
        config=MainlineConfig(channel_scan_mode="selective_sweep"),
    )
    position = (500.0, 0.0)
    for channel in runner.ks.channels.values():
        channel.status = ChannelStatus.CLEARED

    near_active = runner.ks[1]
    near_active.status = ChannelStatus.ACTIVE
    near_active.mec = ((0.0, 0.0), 100.0)

    far_active = runner.ks[2]
    far_active.status = ChannelStatus.ACTIVE
    far_active.mec = ((2500.0, 0.0), 100.0)

    unknown = runner.ks[3]
    unknown.status = ChannelStatus.UNKNOWN

    assert runner._scan_set(position) == [1, 3]

    wider = GameRunner(
        "Q3",
        executor=None,
        output_dir=str(tmp_path / "wider"),
        config=MainlineConfig(channel_scan_mode="selective_sweep",
                              active_scan_margin_m=1000.0),
    )
    for channel in wider.ks.channels.values():
        channel.status = ChannelStatus.CLEARED
    wider.ks[1].status = ChannelStatus.ACTIVE
    wider.ks[1].mec = ((0.0, 0.0), 100.0)
    wider.ks[2].status = ChannelStatus.ACTIVE
    wider.ks[2].mec = ((2500.0, 0.0), 100.0)
    wider.ks[3].status = ChannelStatus.UNKNOWN
    assert wider._scan_set(position) == [1, 2, 3]


def test_selective_sweep_skips_redundant_q3_unknown_stop(tmp_path):
    runner = GameRunner(
        "Q3",
        executor=None,
        output_dir=str(tmp_path),
        config=MainlineConfig(channel_scan_mode="selective_sweep"),
    )
    position = (0.0, 0.0)
    for channel in runner.ks.channels.values():
        channel.status = ChannelStatus.CLEARED

    redundant = runner.ks[1]
    redundant.status = ChannelStatus.UNKNOWN
    # Six prior no-signal disks at radius 500 m cover B(position, 1000 m).
    import math
    redundant.certificate_region.extend(
        (500.0 * math.cos(k * math.pi / 3.0),
         500.0 * math.sin(k * math.pi / 3.0))
        for k in range(6)
    )

    fresh = runner.ks[2]
    fresh.status = ChannelStatus.UNKNOWN

    assert runner._scan_set(position) == [2]


def test_certificate_scan_keeps_planned_channel_after_selective_filter(tmp_path):
    simulator = SyntheticSimulator("Q3", seed=7, n_sources=1)
    simulator.sources = []
    executor = ActionExecutor(SimulatorBackend(simulator))
    runner = GameRunner(
        "Q3",
        executor=executor,
        output_dir=str(tmp_path),
        simulator=simulator,
        config=MainlineConfig(channel_scan_mode="selective_clear"),
    )
    executor.enter()
    for channel in runner.ks.channels.values():
        channel.status = ChannelStatus.CLEARED

    channel = runner.ks[1]
    channel.status = ChannelStatus.UNKNOWN
    import math
    channel.certificate_region.extend(
        (500.0 * math.cos(k * math.pi / 3.0),
         500.0 * math.sin(k * math.pi / 3.0))
        for k in range(6)
    )

    mission = Mission("scan", (0.0, 0.0), channels=[1],
                      meta={"kind": "q3_backbone"})
    runner._execute(mission)

    assert executor.n_measures == 1
    assert runner.ks[1].observations[-1]["result"] == "no_signal"


def test_selective_clear_filters_only_information_safe_scans(tmp_path):
    runner = GameRunner(
        "Q3",
        executor=None,
        output_dir=str(tmp_path),
        config=MainlineConfig(channel_scan_mode="selective_clear"),
    )
    position = (500.0, 0.0)
    for channel in runner.ks.channels.values():
        channel.status = ChannelStatus.CLEARED
    runner.ks.channels[1].status = ChannelStatus.ACTIVE
    runner.ks.channels[1].mec = ((0.0, 0.0), 100.0)
    runner.ks.channels[2].status = ChannelStatus.ACTIVE
    runner.ks.channels[2].mec = ((2500.0, 0.0), 100.0)
    runner.ks.channels[3].status = ChannelStatus.UNKNOWN

    # The v2 useful sweep remains available and still scans all UNKNOWN/ACTIVE.
    assert runner._scan_set(position, scan_mode="useful_sweep") == [1, 2, 3]
    # v3 selective_clear uses the information-safe rule on every stop.
    assert runner._scan_set(position) == [1, 3]
    assert runner._scan_set(position, scan_mode="selective_sweep") == [1, 3]
    assert runner._clear_scan_mode(True) == "selective_sweep"
    assert runner._clear_scan_mode(False) is None
