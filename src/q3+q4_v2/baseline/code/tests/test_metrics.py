# -*- coding: utf-8 -*-
"""跨案例统计口径测试（评审第 5 点，v2.1）。

- 每案例 metrics 含 t_per_source_s = T_j/n_j 及口径标注；
- aggregate_cases：聚合值 = 各案例 T_j/n_j 的算术平均，
  不是总时间/总源数（两者同时给出并标注）。
"""

from experiment.metrics import T_PER_SOURCE_BASIS, aggregate_cases


def _fake_case(total, n_sources):
    return {"T_total_virtual": float(total), "sources_total": n_sources,
            "t_per_source_s": float(total) / n_sources}


def test_aggregate_is_arithmetic_mean_not_pooled():
    # 案例 1：100 s / 10 源 = 10；案例 2：300 s / 2 源 = 150
    cases = [_fake_case(100.0, 10), _fake_case(300.0, 2)]
    agg = aggregate_cases(cases)
    assert agg["n_cases"] == 2
    # 主口径：算术平均 (10 + 150)/2 = 80
    assert abs(agg["mean_t_per_source_s"] - 80.0) < 1e-9
    # pooled 口径（参考）：400/12 ≈ 33.3，两者必须区分
    assert abs(agg["pooled_time_per_source_s"] - 400.0 / 12.0) < 1e-9
    assert abs(agg["mean_t_per_source_s"]
               - agg["pooled_time_per_source_s"]) > 1.0
    assert "arithmetic mean" in agg["basis"]
    assert "not" in agg["pooled_basis"]


def test_aggregate_empty_and_skips_missing():
    assert aggregate_cases([])["mean_t_per_source_s"] is None
    agg = aggregate_cases([_fake_case(50.0, 5),
                           {"T_total_virtual": 1.0, "sources_total": 1,
                            "t_per_source_s": None}])
    assert agg["n_cases"] == 1
    assert agg["mean_t_per_source_s"] == 10.0


def test_metrics_json_per_case_fields(tmp_path):
    """端到端：metrics.json 含 t_per_source_s 与口径标注。"""
    import json

    from executor.action_executor import ActionExecutor
    from experiment.runner import GameRunner
    from experiment.simulator import SimulatorBackend, SyntheticSimulator

    sim = SyntheticSimulator("Q3", 3, n_sources=2, scenario="dense")
    ex = ActionExecutor(SimulatorBackend(sim))
    out = tmp_path / "q3_metrics_case"
    report = GameRunner("Q3", ex, str(out), simulator=sim).run()
    assert report["complete"]
    m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert m["t_per_source_basis"] == T_PER_SOURCE_BASIS
    assert abs(m["t_per_source_s"]
               - m["T_total_virtual"] / m["sources_total"]) < 1e-9
