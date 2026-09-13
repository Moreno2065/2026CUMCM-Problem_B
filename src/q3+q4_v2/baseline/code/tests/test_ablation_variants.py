# -*- coding: utf-8 -*-
"""消融 variant 开关测试（Addendum C）：默认配置 = mainline 行为不变；
各 variant 只改一个模块且保持完成性；Q4 naive 假证书被后置检查发现。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiment.casefile import generate_case, save_case_set
from experiment.config import ConfigError, MainlineConfig, load_config
from experiment.metrics import branch_metrics
from experiment.suite import (
    POLICY_VARIANTS,
    VARIANTS,
    _case_entry,
    _run_one_case,
    _summaries,
    paired_diff,
    run_ablation,
    select_tau,
)
from state.knowledge_state import KnowledgeState


@pytest.fixture(scope="module")
def small_cases():
    return {
        "q3": generate_case("q3", 60606, n_sources=3, scenario="random"),
        "q4": generate_case("q4", 60606, n_sources=3,
                            scenario="edge_facing"),
    }


def test_variant_registry_single_module_change():
    """Controls are one-switch; named successor candidates are explicit."""
    assert VARIANTS["candidate_a1_a3"][0] == {
        "nbv_rule": "fixed_geometry",
        "channel_scan_mode": "sweep_all",
    }
    for name, (overrides, questions, desc) in VARIANTS.items():
        assert name in POLICY_VARIANTS
        if name == "mainline":
            assert overrides == {}
        elif name == "candidate_a1_a3":
            assert set(overrides) == {"nbv_rule", "channel_scan_mode"}
        elif name == "q3_candidate_v2":
            assert set(overrides) == {
                "tau", "nbv_rule", "channel_scan_mode",
            }
            assert questions == ("q3",)
        elif name == "q3_candidate_v3":
            assert set(overrides) == {
                "tau", "nbv_rule", "channel_scan_mode",
                "active_scan_margin_m",
            }
            assert questions == ("q3",)
        elif not name.startswith("e_"):
            assert len(overrides) == 1, (name, overrides)


def test_variant_config_defaults_are_mainline():
    d = MainlineConfig().to_dict()
    assert d["nbv_rule"] == "nbv"
    assert d["opportunistic_reuse"] is True
    assert d["channel_scan_mode"] == "state_aware"
    assert d["cert_select"] == "gain_cost"
    assert d["q4_naive"] is False
    assert d["q4_certificate_layout"] == "lattice31"
    assert d["q4_joint_rank"] is False
    assert d["cert_route_mode"] == "greedy"
    assert d["q4_residual_sparsify"] is False
    # derive 只改指定键
    d2 = MainlineConfig(tau=0.05).derive(nbv_rule="fixed_geometry")
    assert d2.tau == 0.05 and d2.nbv_rule == "fixed_geometry"
    assert d2.channel_scan_mode == "state_aware"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"q4_certificate_layout": "bogus"},
        {"cert_route_mode": "bogus"},
    ],
)
def test_q4_ablation_config_rejects_invalid_enums(kwargs):
    with pytest.raises(ConfigError):
        MainlineConfig(**kwargs)


def test_q4_ablation_config_roundtrip_and_allowed_keys(tmp_path):
    overrides = {
        "q4_certificate_layout": "sparse25",
        "q4_joint_rank": True,
        "cert_route_mode": "lookahead2",
        "q4_residual_sparsify": True,
    }
    configured = MainlineConfig(**overrides)
    assert MainlineConfig(**configured.to_dict()).to_dict() == \
        configured.to_dict()
    assert MainlineConfig().derive(**overrides).to_dict() == \
        configured.to_dict()

    config_path = tmp_path / "q4_ablation.json"
    config_path.write_text(__import__("json").dumps(overrides),
                           encoding="utf-8")
    loaded = load_config(str(config_path))
    assert {key: loaded.to_dict()[key] for key in overrides} == overrides


def test_q4_named_ablation_variants_have_exact_overrides():
    expected = {
        "e1_sparse25": {"q4_certificate_layout": "sparse25"},
        "e2_joint_state": {"q4_joint_rank": True},
        "e3_lookahead2": {"cert_route_mode": "lookahead2"},
        "e4_residual_sparsify": {"q4_residual_sparsify": True},
    }
    for name, overrides in expected.items():
        actual, questions, _ = VARIANTS[name]
        assert actual == overrides
        assert questions == ("q4",)

    all_overrides, questions, _ = VARIANTS["e_all"]
    assert all_overrides == {
        "q4_certificate_layout": "sparse25",
        "q4_joint_rank": True,
        "cert_route_mode": "lookahead2",
        "q4_residual_sparsify": True,
    }
    assert questions == ("q4",)


def test_q4_combo_variants_cover_all_16_masks():
    enabled = (
        ("q4_certificate_layout", "sparse25"),
        ("q4_joint_rank", True),
        ("cert_route_mode", "lookahead2"),
        ("q4_residual_sparsify", True),
    )
    combo_names = {name for name in VARIANTS if name.startswith("e_combo_")}
    assert combo_names == {"e_combo_%04d" % int(format(mask, "04b"))
                           for mask in range(16)}
    for mask in range(16):
        bits = format(mask, "04b")
        name = "e_combo_%s" % bits
        overrides, questions, _ = VARIANTS[name]
        expected = {
            key: value
            for bit, (key, value) in zip(bits, enabled)
            if bit == "1"
        }
        assert overrides == expected, name
        assert questions == ("q4",)


def test_branch_metrics_have_stable_defaults_and_exact_counts():
    q3 = branch_metrics(
        KnowledgeState("Q3"), MainlineConfig(), decision_trace=[])
    assert q3 == {
        "q4_certificate_layout": None,
        "q4_certificate_point_count": 0,
        "joint_state_evaluations": 0,
        "lookahead_decisions": 0,
        "q4_certified_cells_raw": 0,
        "q4_certified_cells_retained": 0,
        "q4_certified_cells_pruned": 0,
    }

    ks = KnowledgeState("Q4", q4_certificate_layout="sparse25")
    ks[1].q4_certified_centers_raw_count = 4
    ks[1].certified_centers = [(0.0, 0.0), (1.0, 1.0)]
    trace = [
        {"candidates": [
            {"joint_state_score": 0.2}, {"joint_state_score": 0.7}],
         "selected": {"lookahead_depth": 2}},
        {"candidates": [], "selected": None},
    ]
    got = branch_metrics(
        ks, MainlineConfig(q4_certificate_layout="sparse25",
                           q4_joint_rank=True,
                           cert_route_mode="lookahead2",
                           q4_residual_sparsify=True),
        decision_trace=trace)
    assert got == {
        "q4_certificate_layout": "sparse25",
        "q4_certificate_point_count": 25,
        "joint_state_evaluations": 2,
        "lookahead_decisions": 1,
        "q4_certified_cells_raw": 4,
        "q4_certified_cells_retained": 2,
        "q4_certified_cells_pruned": 2,
    }


def test_branch_metrics_are_exposed_in_case_and_summary():
    keys = (
        "q4_certificate_layout", "q4_certificate_point_count",
        "joint_state_evaluations", "lookahead_decisions",
        "q4_certified_cells_raw", "q4_certified_cells_retained",
        "q4_certified_cells_pruned",
    )
    metrics = {
        "cleared_count": 1, "sources_total": 1,
        "t_per_source_s": 10.0, "T_total_virtual": 10.0,
        "avg_localize_clear_time_s": None,
        "total_move_distance_m": 0.0, "n_measures": 1,
        "n_switches": 0, "T_measure": 5.0, "T_switch": 0.0,
        "wall_clock_s": 0.1,
        **branch_metrics(KnowledgeState("Q4"), MainlineConfig(), []),
    }
    case = {"case_id": "metric", "case_seed": 1}
    report = {"metrics": metrics, "complete": True,
              "verifier_all_ok": True, "failure": None,
              "output_dir": "unused"}
    entry = _case_entry(case, report)
    assert all(key in entry for key in keys)
    summary = _summaries([entry])
    assert summary["q4_certificate_layout"] == "lattice31"
    assert summary["verifier_success_count"] == 1
    assert summary["joint_state_evaluations"]["mean"] == 0.0
    assert summary["q4_certified_cells_pruned"]["mean"] == 0.0


def test_e_matched_base_config_is_candidate_v1_with_branches_disabled():
    cfg = load_config(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs", "e_branches_matched_base.yaml"))
    assert cfg.tau == 0.15
    assert cfg.nbv_rule == "fixed_geometry"
    assert cfg.channel_scan_mode == "sweep_all"
    assert cfg.q4_certificate_layout == "lattice31"
    assert cfg.q4_joint_rank is False
    assert cfg.cert_route_mode == "greedy"
    assert cfg.q4_residual_sparsify is False


def test_e_matrix_suite_writes_stable_branch_metrics_csv(tmp_path):
    case = generate_case("q4", 818181, n_sources=1, scenario="random")
    cases_path = tmp_path / "q4.json"
    save_case_set("e_matrix_smoke", "smoke", "q4", [case],
                  str(cases_path))
    variants = ("mainline", "e1_sparse25", "e2_joint_state",
                "e3_lookahead2", "e4_residual_sparsify", "e_all")
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs", "e_branches_matched_base.yaml")
    summary = run_ablation(
        "e_matrix_smoke", str(cases_path), config_path,
        str(tmp_path / "out"), variants=variants, slim=True)
    assert summary["config"]["tau"] == 0.15
    assert summary["config"]["nbv_rule"] == "fixed_geometry"
    assert summary["config"]["channel_scan_mode"] == "sweep_all"
    assert all(summary["summary_by_variant"][name]["success_count"] == 1
               for name in variants)
    csv_path = tmp_path / "out" / "e_matrix_smoke" / "case_metrics.csv"
    rows = csv_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].split(",")[-7:] == [
        "q4_certificate_layout", "q4_certificate_point_count",
        "joint_state_evaluations", "lookahead_decisions",
        "q4_certified_cells_raw", "q4_certified_cells_retained",
        "q4_certified_cells_pruned",
    ]
    assert len(rows) == len(variants) + 1


def test_all_variants_complete_on_small_case(small_cases, tmp_path):
    """所有 variant（含 baseline）在小案例上保持完成性（兜底保证）。"""
    for q, case in small_cases.items():
        for var, (ov, qs, _) in VARIANTS.items():
            if q not in qs or var == "q4_naive_q3_style":
                continue
            cfg = MainlineConfig().derive(**ov)
            rep, runner = _run_one_case(
                case, cfg, None,
                os.path.join(str(tmp_path), "%s_%s" % (q, var)),
                policy_variant=var)
            entry = _case_entry(case, rep, runner)
            assert rep["complete"], (q, var, rep["failure"])
            assert entry["success"], (q, var, entry["missed_sources"])


def test_q4_naive_false_certificate_detected(small_cases, tmp_path):
    """C.5：naive Q3-style 在不利定向案例上产生假证书，被 ground-truth
    后置检查发现且不计成功（失败案例保留不删除）。"""
    case = small_cases["q4"]
    cfg = MainlineConfig().derive(q4_naive=True)
    rep, runner = _run_one_case(case, cfg, None, str(tmp_path / "naive"),
                                policy_variant="q4_naive_q3_style")
    entry = _case_entry(case, rep, runner)
    assert entry["false_certified_absent"] > 0
    assert entry["missed_sources"]
    assert entry["success"] is False
    # 主线上同案例零假证书（对照）
    rep2, runner2 = _run_one_case(case, MainlineConfig(), None,
                                  str(tmp_path / "mainline"),
                                  policy_variant="mainline")
    entry2 = _case_entry(case, rep2, runner2)
    assert entry2["false_certified_absent"] == 0
    assert entry2["success"] is True


def test_paired_diff_and_select_tau():
    base = [{"case_id": "a", "T_total_virtual": 100.0,
             "total_move_distance_m": 500.0, "n_measures": 10,
             "n_switches": 9, "avg_localize_clear_time_s": 50.0,
             "success": True}]
    var = [{"case_id": "a", "T_total_virtual": 90.0,
            "total_move_distance_m": 450.0, "n_measures": 8,
            "n_switches": 7, "avg_localize_clear_time_s": 45.0,
            "success": True}]
    pd = paired_diff(base, var, "mainline", "x")
    assert pd["pairs"][0]["dT"] == -10.0
    assert pd["dT"]["mean"] == -10.0

    # select_tau：clearance 硬约束 + 2% 接近带内选 std 小者
    def mk(tau, tps, std, ok=True):
        return {"tau": tau, "clearance_ok": ok,
                "cases": [{"case_id": "c%d" % i, "t_per_source_s": tps + d,
                           "T_total_virtual": (tps + d) * 10,
                           "clearance_ratio": 1.0 if ok else 0.9,
                           "success": ok, "avg_localize_clear_time_s": 1.0,
                           "total_move_distance_m": 100.0,
                           "n_measures": 10, "n_switches": 9}
                          for i, d in enumerate((-std, std))],
                "summary": None}
    tr = {"results": [mk(0.0, 100.0, 5.0), mk(0.05, 100.5, 1.0),
                      mk(0.2, 90.0, 1.0, ok=False)]}
    tau, why = select_tau([tr])
    assert tau == 0.05       # 0.0 与 0.05 在 2% 带内，选 std 更小者
    assert why["close_candidates"]
