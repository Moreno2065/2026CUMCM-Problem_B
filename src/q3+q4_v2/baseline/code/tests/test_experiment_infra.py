# -*- coding: utf-8 -*-
"""Addendum 实验基础设施测试：案例文件、误差场、证据契约、隔离、
FROZEN_CONFIG、/move 勘误、τ 默认行为不变。"""

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor.action_executor import ActionExecutor
from experiment.casefile import (
    generate_all_case_sets,
    generate_case,
    load_case,
    load_case_set,
    save_case,
    validate_case,
)
from experiment.config import (
    MainlineConfig,
    ConfigError,
    config_sha256,
    load_config,
)
from experiment.freeze import FROZEN_REQUIRED_FIELDS, freeze_config
from experiment.runner import GameRunner
from experiment.simulator import (
    ERROR_FIELD_TYPES,
    SimulatorBackend,
    SyntheticSimulator,
    _ef_params,
    bearing_error,
)

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_DIR = os.path.join(CODE_ROOT, "cases")


def _run_case(case, out_dir, config=None, config_path=None):
    sim = SyntheticSimulator.from_case(case)
    ex = ActionExecutor(SimulatorBackend(sim))
    return GameRunner(case["question"].upper(), ex, str(out_dir),
                      simulator=sim, config=config, case=case,
                      config_path=config_path).run()


# ---------------------------------------------------------------------------
# 案例文件往返（Addendum D.4）
# ---------------------------------------------------------------------------

def test_case_roundtrip_byte_identical(tmp_path):
    """生成→保存→加载→模拟：同一案例文件两局结果逐字节一致。"""
    case = generate_case("q3", 123456, case_id="rt_q3", scenario="random",
                         n_sources=3)
    path = tmp_path / "rt_q3.json"
    save_case(case, str(path))
    loaded = load_case(str(path))
    assert loaded == case

    _run_case(loaded, tmp_path / "run_a")
    _run_case(loaded, tmp_path / "run_b")
    for name in ("trajectory.csv", "observations.csv", "actions.csv",
                 "decision_trace.jsonl", "channel_state_history.jsonl"):
        a = (tmp_path / "run_a" / name).read_bytes()
        b = (tmp_path / "run_b" / name).read_bytes()
        assert a == b, name


def test_case_generate_deterministic_and_validated():
    c1 = generate_case("q4", 777, scenario="edge_facing", n_sources=4)
    c2 = generate_case("q4", 777, scenario="edge_facing", n_sources=4)
    assert c1 == c2
    assert validate_case(c1)
    # Q3 案例 directions 全 null；Q4 edge_facing 全定向
    q3 = generate_case("q3", 778, n_sources=3)
    assert all(d is None for d in q3["directions"])
    assert all(d is not None for d in c1["directions"])
    bad = dict(q3, positions=[[9999.0, 0.0]] * 3)
    with pytest.raises(ValueError):
        validate_case(bad)


def test_from_case_matches_case_fields():
    """from_case 构造的局与案例文件字段一一对应。"""
    case = generate_case("q4", 4242, scenario="mixed", n_sources=5,
                         error_field_type="structured")
    sim = SyntheticSimulator.from_case(case)
    gt = {s["channel"]: s for s in sim.ground_truth()}
    assert len(gt) == 5
    for ch, (x, y), r, d in zip(case["channels"], case["positions"],
                                case["receive_radii"], case["directions"]):
        s = gt[ch]
        assert (s["x"], s["y"]) == (x, y)
        assert s["r_eff"] == r
        assert s["directional"] == (d is not None)
    assert sim.error_field_type == "structured"


# ---------------------------------------------------------------------------
# 三种误差场（Addendum D.1/D.2）
# ---------------------------------------------------------------------------

def test_error_fields_same_point_fixed_and_bounded():
    for ef in ERROR_FIELD_TYPES:
        for seed in (1, 300000):
            params = _ef_params(seed)
            for x, y in ((0.0, 0.0), (500.5, -700.25), (1799.9, 0.1),
                         (-1600.0, -300.0)):
                vals = {bearing_error(ef, params, seed, x, y)
                        for _ in range(4)}
                assert len(vals) == 1, (ef, x, y)      # 同点固定
                (v,) = vals
                assert -1.0 <= v <= 1.0, (ef, x, y, v)  # ±1° 有界


def test_boundary_field_magnitudes():
    """boundary 场：ε ∈ {−0.99°, +0.99°}（舍入后总误差 ≤ 1°）。"""
    params = _ef_params(99)
    vals = {bearing_error("boundary", params, 99, float(i), float(j))
            for i in (-300, 0, 300) for j in (-300, 300)}
    assert vals == {-0.99, 0.99}


def test_structured_field_spatially_smooth():
    """structured 场：低频平滑（相邻点误差接近），有界且同点固定。"""
    import math
    params = _ef_params(7)
    e1 = bearing_error("structured", params, 7, 100.0, 0.0)
    e2 = bearing_error("structured", params, 7, 101.0, 0.0)
    assert abs(e1 - e2) < 0.01      # 1 m 位移误差变化极小（低频）
    # 沿波向移动半波长 ⇒ sin 精确翻转
    w = math.radians(params["wave_deg"])
    half = params["wavelength"] / 2.0
    e3 = bearing_error("structured", params, 7,
                       100.0 + half * math.cos(w), half * math.sin(w))
    assert abs(e1 + e3) < 1e-9


def test_error_field_recorded_in_case_and_provenance(tmp_path):
    case = generate_case("q3", 5150, n_sources=2,
                         error_field_type="boundary")
    assert case["error_field_type"] == "boundary"
    assert case["error_field_version"] == 1
    out = tmp_path / "run"
    _run_case(case, out)
    prov = json.loads((out / "provenance.json")
                      .read_text(encoding="utf-8"))
    assert prov["error_field_type"] == "boundary"
    assert prov["error_field_version"] == 1
    assert prov["case_id"] == case["case_id"]
    assert prov["case_seed"] == case["case_seed"]


# ---------------------------------------------------------------------------
# 证据契约（Addendum E）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def evidence_run(tmp_path_factory):
    case = generate_case("q3", 24680, case_id="evidence_q3",
                         n_sources=3)
    out = tmp_path_factory.mktemp("evidence")
    report = _run_case(case, out, config=MainlineConfig())
    return out, report


def test_evidence_files_exist(evidence_run):
    out, report = evidence_run
    assert report["complete"] and report["verifier_all_ok"]
    for name in ("config.yaml", "provenance.json", "actions.csv",
                 "observations.csv", "trajectory.csv",
                 "channel_state_history.jsonl", "decision_trace.jsonl",
                 "metrics.json", "verifier_report.json"):
        assert (out / name).is_file(), name
    assert (out / "localization_history").is_dir()
    assert (out / "certificate_history").is_dir()
    assert (out / "figure_data").is_dir()
    assert os.listdir(out / "localization_history")     # 有 ACTIVE 更新
    assert os.listdir(out / "certificate_history")      # 有证书进展


def test_evidence_field_completeness(evidence_run):
    out, _ = evidence_run
    prov = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    for k in ("model_version", "spec_version", "git_commit", "case_id",
              "case_seed", "policy_variant", "frozen_config_hash",
              "start_time"):
        assert k in prov, k

    with open(out / "actions.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    need = {"step", "virtual_time_before", "virtual_time_after",
            "action_type", "target_x", "target_y", "channel",
            "policy_mode", "reason_code", "movement_distance",
            "movement_time", "switch_time", "action_time"}
    assert need <= set(rows[0].keys())
    assert {r["action_type"] for r in rows} >= {"enter", "measure",
                                                "clear", "exit"}

    with open(out / "observations.csv", encoding="utf-8") as f:
        orows = list(csv.DictReader(f))
    need_obs = {"step", "virtual_time", "x", "y", "channel", "result",
                "bearing_deg", "status_before", "status_after"}
    assert need_obs <= set(orows[0].keys())

    traces = [json.loads(line) for line in
              open(out / "decision_trace.jsonl", encoding="utf-8")]
    assert traces
    for t in traces:
        for k in ("ready", "active", "unknown", "policy_mode",
                  "candidates", "selected", "tie_break",
                  "opportunistic_insertions", "certificate_gain_estimate",
                  "fallback_trigger"):
            assert k in t, k
    # 不得只存最终选择：至少一个决策带有候选评分
    assert any(t["candidates"] for t in traces)
    cand = next(c for t in traces for c in t["candidates"]
                if c.get("gain") is not None)
    assert "gain" in cand and "cost" in cand

    loc = out / "localization_history"
    first = json.loads(open(next(iter(loc.iterdir())),
                            encoding="utf-8").readline())
    for k in ("vertices", "area", "diameter", "mec_center", "mec_radius",
              "guaranteed_clear_region", "observation_count"):
        assert k in first, k

    cert = out / "certificate_history"
    centry = json.loads(open(next(iter(cert.iterdir())),
                             encoding="utf-8").readline())
    for k in ("virtual_time", "certificate_measure", "coverage_ratio",
              "new_gain", "certificate_source_stop"):
        assert k in centry, k


# ---------------------------------------------------------------------------
# 目录隔离与场景覆盖（Addendum B.3 / D.3）
# ---------------------------------------------------------------------------

def test_case_sets_isolation_and_counts():
    assert os.path.isdir(CASES_DIR), "run: python cli.py cases"
    id_sets = {}
    for name in ("tune", "ablation", "stress", "holdout"):
        mpath = os.path.join(CASES_DIR, name, "manifest.json")
        assert os.path.isfile(mpath), name
        ids = set()
        for q in ("q3", "q4"):
            cs = load_case_set(os.path.join(CASES_DIR, name,
                                            "%s_%s.json" % (name, q)))
            assert len(cs["cases"]) >= 6, (name, q)
            ids |= {c["case_id"] for c in cs["cases"]}
        id_sets[name] = ids
    names = list(id_sets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert not (id_sets[names[i]] & id_sets[names[j]]), \
                (names[i], names[j])


def test_generate_candidate_case_sets_are_isolated(tmp_path):
    """A new candidate must never tune or validate on exposed case IDs."""
    generate_all_case_sets(str(tmp_path), tag="candidate_v1",
                           seed_offset=500000)
    current = load_case_set(tmp_path / "candidate_v1" / "tune" /
                            "tune_q3.json")
    historical = load_case_set(os.path.join(CASES_DIR, "tune",
                                            "tune_q3.json"))
    assert current["set_name"] == "candidate_v1_tune_q3"
    assert min(c["case_seed"] for c in current["cases"]) >= 600000
    assert {c["case_id"] for c in current["cases"]}.isdisjoint(
        {c["case_id"] for c in historical["cases"]})


def test_stress_scenario_coverage():
    """D.3 场景族覆盖矩阵。"""
    fam_q3 = {"random_10", "random_16", "rim", "dense", "sparse",
              "r_eff_low", "r_eff_high", "parallel_bearing",
              "near_early", "empty_channels"}
    for q in ("q3", "q4"):
        cs = load_case_set(os.path.join(CASES_DIR, "stress",
                                        "stress_%s.json" % q))
        seen = set()
        efs = set()
        for c in cs["cases"]:
            efs.add(c["error_field_type"])
            sc = c["scenario"]
            if sc == "random" and c["source_count"] == 10:
                seen.add("random_10")
            elif sc == "random" and c["source_count"] == 16:
                seen.add("random_16")
            else:
                seen.add(sc)
        missing = fam_q3 - seen
        assert not missing, (q, missing)
        if q == "q4":
            assert "edge_facing" in seen     # Q4 不利定向
        assert efs == set(ERROR_FIELD_TYPES)  # 三类误差场
    # 边界源严格 ≥1700
    cs = load_case_set(os.path.join(CASES_DIR, "stress", "stress_q3.json"))
    rim = next(c for c in cs["cases"] if c["scenario"] == "rim")
    import math
    assert all(math.hypot(*p) >= 1700.0 - 1e-6 for p in rim["positions"])


# ---------------------------------------------------------------------------
# FROZEN_CONFIG（Addendum B.6）
# ---------------------------------------------------------------------------

def test_freeze_config(tmp_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("policy: mainline\ntau: 0.0\nnbv_mode: radius\n",
                        encoding="utf-8")
    tune_results = {"selected_tau": 0.05, "case_set": "tune_q3.json",
                    "results": [{"tau": 0.0}, {"tau": 0.05}]}
    out = tmp_path / "FROZEN_CONFIG.yaml"
    payload = freeze_config(str(cfg_path), tune_results, str(out))
    for k in FROZEN_REQUIRED_FIELDS:
        assert k in payload, k
    assert payload["tau"] == 0.05
    assert payload["spec_version"] == "v2.1+addendum"
    assert out.is_file()
    # 缺 selected_tau 时回退配置内 tau（机制路径）
    payload2 = freeze_config(str(cfg_path), {"results": []},
                             str(tmp_path / "F2.yaml"))
    assert payload2["tau"] == 0.0


def test_freeze_preserves_runtime_policy_switches(tmp_path):
    """A frozen candidate must retain every runtime-affecting switch."""
    cfg_path = tmp_path / "candidate.yaml"
    cfg_path.write_text(
        "policy: mainline\n"
        "tau: 0.0\n"
        "nbv_mode: radius\n"
        "nbv_rule: fixed_geometry\n"
        "channel_scan_mode: sweep_all\n",
        encoding="utf-8",
    )
    out = tmp_path / "FROZEN_CONFIG.yaml"
    freeze_config(str(cfg_path), {"selected_tau": 0.05, "results": []},
                  str(out))
    frozen = load_config(str(out))
    assert frozen.tau == 0.05
    assert frozen.nbv_rule == "fixed_geometry"
    assert frozen.channel_scan_mode == "sweep_all"


def test_freeze_preserves_all_runtime_switches_and_provenance(tmp_path):
    """Freezing must not silently reset any configured branch or runtime key."""
    cfg_path = tmp_path / "candidate_all_switches.yaml"
    cfg_path.write_text(
        "policy: mainline\n"
        "tau: 0.125\n"
        "nbv_mode: diameter\n"
        "max_steps: 321\n"
        "nbv_rule: fixed_geometry\n"
        "opportunistic_reuse: false\n"
        "channel_scan_mode: sweep_all\n"
        "cert_select: nearest\n"
        "q4_naive: true\n"
        "q4_certificate_layout: sparse25\n"
        "q4_joint_rank: true\n"
        "cert_route_mode: lookahead2\n"
        "q4_residual_sparsify: true\n"
        "q3_ml_ranker: true\n"
        "q3_ml_model_path: models/test-ranker.json\n"
        "active_scan_margin_m: 12.5\n",
        encoding="utf-8",
    )
    out = tmp_path / "FROZEN_CONFIG.yaml"
    payload = freeze_config(
        str(cfg_path), {"selected_tau": 0.25, "results": []}, str(out)
    )

    frozen = load_config(str(out))
    expected = {
        "policy": "mainline",
        "tau": 0.25,
        "nbv_mode": "diameter",
        "max_steps": 321,
        "nbv_rule": "fixed_geometry",
        "opportunistic_reuse": False,
        "channel_scan_mode": "sweep_all",
        "cert_select": "nearest",
        "q4_naive": True,
        "q4_certificate_layout": "sparse25",
        "q4_joint_rank": True,
        "cert_route_mode": "lookahead2",
        "q4_residual_sparsify": True,
        "q3_ml_ranker": True,
        "q3_ml_model_path": "models/test-ranker.json",
        "active_scan_margin_m": 12.5,
    }
    assert frozen.to_dict() == expected
    assert payload["frozen_config_hash"] == config_sha256(str(cfg_path))
    assert len(payload["tune_results_hash"]) == 64
    assert payload["git_commit"] == "N/A"
    assert out.read_text(encoding="utf-8").find(
        "q4_certificate_layout: sparse25") >= 0


# ---------------------------------------------------------------------------
# 勘误合规（Addendum K/L）：无 /move 端点
# ---------------------------------------------------------------------------

def test_no_move_endpoint_anywhere():
    """全代码库（除 tests 与文档）不得出现 /move 端点。"""
    scan_dirs = ("api", "executor", "experiment", "geometry", "policy",
                 "state", "verifier")
    files = [os.path.join(CODE_ROOT, f)
             for f in ("run.py", "cli.py", "conftest.py")]
    for d in scan_dirs:
        for root, _, fns in os.walk(os.path.join(CODE_ROOT, d)):
            if "__pycache__" in root:
                continue
            files.extend(os.path.join(root, fn) for fn in fns
                         if fn.endswith(".py"))
    assert files
    needle = '"/move"'
    for path in files:
        text = open(path, encoding="utf-8").read()
        assert needle not in text, path
        assert "POST /move" not in text, path
    from api import protocol
    assert "/move" not in protocol.ENDPOINTS
    assert set(protocol.ENDPOINTS) == {"/enter", "/measure", "/clear",
                                       "/exit"}


# ---------------------------------------------------------------------------
# τ 参数化默认行为不变（纪律：默认值 = 当前隐式值）
# ---------------------------------------------------------------------------

def test_tau_default_parity(tmp_path):
    """显式 tau=0.0 配置与不传配置的局逐字节一致。"""
    case = generate_case("q3", 97531, n_sources=3)
    _run_case(case, tmp_path / "plain")
    _run_case(case, tmp_path / "cfg", config=MainlineConfig(tau=0.0))
    for name in ("trajectory.csv", "observations.csv", "actions.csv",
                 "decision_trace.jsonl"):
        assert (tmp_path / "plain" / name).read_bytes() == \
               (tmp_path / "cfg" / name).read_bytes(), name


def test_config_loading_and_validation():
    cfg = load_config(os.path.join(CODE_ROOT, "configs",
                                   "default_mainline.yaml"))
    assert cfg.tau == 0.0 and cfg.nbv_mode == "radius"
    assert cfg.policy == "mainline"
    with pytest.raises(ConfigError):
        MainlineConfig(nbv_mode="bogus")
    with pytest.raises(ConfigError):
        MainlineConfig(tau=-1.0)
