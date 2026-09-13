# -*- coding: utf-8 -*-
"""合成完成性测试（核心验收）。

Q3：≥10 个随机 seed（含源在边界、密集、稀疏场景）：全部源 100% 清除，
其余频道 CERTIFIED_ABSENT，策略正常退出，verifier_report 全部通过。
Q4：≥10 个随机 seed（含全定向、定向源朝边缘、混合场景）：全部完成
（CLEARED ∨ CERTIFIED_ABSENT 全覆盖或 16 源早停），无遗漏。
指标合理性：时间分解之和 = 总虚拟时间（±1e-3）；对账零警告。
失败案例不删除：max_steps 截断局的报告与交付物完整保留。
"""

import json
import os
import time

import pytest

from executor.action_executor import ActionExecutor
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from state.channel_state import ChannelStatus

# (seed, scenario, n_sources)
Q3_CASES = [
    (11, "random", 12),
    (12, "random", 10),
    (13, "random", 15),
    (14, "random", None),
    (15, "random", 11),
    (21, "boundary", 12),
    (22, "boundary", 13),
    (31, "dense", 14),
    (32, "dense", 10),
    (41, "sparse", 12),
    (51, "random", 16),          # 触发 16 源早停
]

Q4_CASES = [
    (101, "random", 12),          # 全定向
    (102, "random", 10),
    (103, "random", 14),
    (104, "random", None),
    (111, "edge_facing", 12),     # 定向源朝外（最不利）
    (112, "edge_facing", 13),
    (113, "edge_facing", 11),
    (121, "mixed", 12),           # 定向/全向混合
    (122, "mixed", 15),
    (123, "mixed", None),
    (131, "random", 16),          # 触发 16 源早停
]


def _run(mode, seed, scenario, n_sources, out_dir, max_steps=20000):
    sim = SyntheticSimulator(mode, seed, n_sources=n_sources,
                             scenario=scenario)
    ex = ActionExecutor(SimulatorBackend(sim))
    runner = GameRunner(mode, ex, out_dir, simulator=sim,
                        max_steps=max_steps)
    t0 = time.time()
    report = runner.run()
    wall = time.time() - t0
    return sim, runner, report, wall


def _check_game(mode, seed, scenario, n_sources, tmp_path, tag):
    out = tmp_path / ("%s_%d_%s" % (mode.lower(), seed, tag))
    sim, runner, report, wall = _run(mode, seed, scenario, n_sources,
                                     str(out))
    ks = runner.ks
    early_stop = len(ks.cleared) >= 16

    # 完成性与失败记录
    assert report["complete"], \
        "incomplete: %s" % json.dumps(report["metrics"], default=str)
    assert report["failure"] is None
    # 全部源被清除（100%）
    for s in sim.sources:
        assert s.cleared, "source on channel %d not cleared" % s.channel
    # 无源频道全部 CERTIFIED_ABSENT（16 源早停时豁免：零风险早停）
    if not early_stop:
        src_channels = {s.channel for s in sim.sources}
        for cid, ch in ks.channels.items():
            if cid in src_channels:
                assert ch.status == ChannelStatus.CLEARED, cid
            else:
                assert ch.status == ChannelStatus.CERTIFIED_ABSENT, cid
    # 独立复核全过
    assert report["verifier_all_ok"]
    # 指标合理性：时间分解之和 = 总虚拟时间（±1e-3）
    m = report["metrics"]
    assert abs(m["T_ledger_sum"] - m["T_total_virtual"]) <= 1e-3
    assert m["n_clear_success"] == len(sim.sources)
    assert m["reconcile_warnings"] == []
    assert m["clear_rate"] == 1.0
    # 单局 wall-clock 预算（报告记录实际值）
    assert wall < 90.0, "game too slow: %.1fs" % wall
    # 交付物齐全
    for name in ("trajectory.csv", "observations.csv", "state_history.json",
                 "certificate.json", "metrics.json", "verifier_report.json",
                 "api_log.jsonl", "ground_truth.json",
                 os.path.join("figure_data", "mec_radius.csv"),
                 os.path.join("figure_data", "certificate_growth.csv"),
                 os.path.join("figure_data", "trajectory.csv")):
        assert (out / name).exists(), name
    return report, wall


@pytest.mark.parametrize("seed,scenario,n_sources", Q3_CASES)
def test_q3_completion(seed, scenario, n_sources, tmp_path):
    _check_game("Q3", seed, scenario, n_sources, tmp_path, scenario)


@pytest.mark.parametrize("seed,scenario,n_sources", Q4_CASES)
def test_q4_completion(seed, scenario, n_sources, tmp_path):
    _check_game("Q4", seed, scenario, n_sources, tmp_path, scenario)


def test_failure_case_recorded_not_deleted(tmp_path):
    """max_steps 截断 ⇒ 局失败但报告与交付物完整保留。"""
    out = tmp_path / "failure_case"
    sim, runner, report, _ = _run("Q3", 99, "random", 12, str(out),
                                  max_steps=3)
    assert report["complete"] is False
    assert report["failure"] == "max_steps_exceeded"
    for name in ("metrics.json", "verifier_report.json",
                 "run_report.json", "trajectory.csv", "state_history.json"):
        assert (out / name).exists()
    saved = json.loads((out / "run_report.json").read_text(
        encoding="utf-8"))
    assert saved["failure"] == "max_steps_exceeded"
