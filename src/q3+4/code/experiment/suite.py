# -*- coding: utf-8 -*-
"""套件执行、消融 variant 注册表与调参筛选框架（Addendum B/C/G/I/J）。

variant 注册表（Addendum C，matched-case：所有 variant 读同一冻结案例
文件，唯一改变一个模块，由 config 开关切换）：
- mainline            : 冻结主线
- a1_fixed_geometry   : A1 baseline，观测点选择 → 固定几何规则
                        （localization.fixed_geometry_point）
- a2_no_reuse         : A2 baseline，关闭机会式停点复用（NBV 候选去掉
                        当前点/中点；发现性 UNKNOWN 扫描两者都保留）
- a3_sweep_all        : A3 baseline，每停点机械扫描全部未结频道
- a4_nearest_cert     : A4 baseline，证书残差选点 → 最近未访点
- q4_naive_q3_style   : C.5 对照，Q4 误用 Q3 式 1000 m 圆盘证书
                        （不健全；假证书由 ground-truth 后置检查发现，
                        不计成功——C.6 失败案例保留）
- q3_ml_experimental  : Q3-only offline linear candidate ranker；只重排
                        已生成 NBV 候选，默认关闭且不改变证书判定

输出结构：<out_root>/<suite>/<variant>/<case_id>/（Addendum E 全证据）
        + <out_root>/<suite>/suite_summary.json（含 paired difference）
        + <out_root>/<suite>/stats.json + summary.md（Addendum G）
"""

import csv
import json
import os

from executor.action_executor import ActionExecutor
from .casefile import load_case_set
from .config import load_config
from .metrics import aggregate_cases
from .runner import GameRunner
from .simulator import SimulatorBackend, SyntheticSimulator

# variant 注册表：name -> (config overrides, 适用 question, 说明)
VARIANTS = {
    "mainline": ({}, ("q3", "q4"), "冻结主线"),
    "candidate_a1_a3": (
        {"nbv_rule": "fixed_geometry", "channel_scan_mode": "sweep_all"},
        ("q3", "q4"),
        "candidate v1：A1 固定几何 + A3 全频道扫描（组合候选）",
    ),
    "q3_candidate_v2": (
        {"tau": 0.15,
         "nbv_rule": "fixed_geometry",
         "channel_scan_mode": "useful_sweep"},
        ("q3",),
        "Q3 Candidate v2：冻结 Q3 策略 + 去重有效伴随扫描",
    ),
    "q3_candidate_v3": (
        {"tau": 0.15,
         "nbv_rule": "fixed_geometry",
         "channel_scan_mode": "selective_clear",
         "active_scan_margin_m": 500.0},
        ("q3",),
        "Q3 Candidate v3：信息安全 selective bearing + 500m margin",
    ),
    "q3_useful_sweep": (
        {"channel_scan_mode": "useful_sweep"},
        ("q3",),
        "Q3 useful-sweep 单因素消融",
    ),
    "q3_ml_experimental": (
        {"q3_ml_ranker": True},
        ("q3",),
        "Q3 实验支线：离线线性排序器（只重排既有 NBV 候选）",
    ),
    "a1_fixed_geometry": (
        {"nbv_rule": "fixed_geometry"}, ("q3", "q4"),
        "A1 baseline：观测点选择=固定几何规则"),
    "a2_no_reuse": (
        {"opportunistic_reuse": False}, ("q3", "q4"),
        "A2 baseline：禁止机会式复用（定位须专门机动）"),
    "a3_sweep_all": (
        {"channel_scan_mode": "sweep_all"}, ("q3", "q4"),
        "A3 baseline：每停点机械扫描全部未结频道"),
    "a4_nearest_cert": (
        {"cert_select": "nearest"}, ("q3", "q4"),
        "A4 baseline：证书残差选点=最近未访点"),
    "q4_naive_q3_style": (
        {"q4_naive": True}, ("q4",),
        "C.5 对照：Q4 误用 Q3 式圆盘证书（不健全，仅供对照）"),
    "e1_sparse25": (
        {"q4_certificate_layout": "sparse25"}, ("q4",),
        "E1：Q4 证书布局改为 sparse25"),
    "e2_joint_state": (
        {"q4_joint_rank": True}, ("q4",),
        "E2：Q4 联合状态排序"),
    "e3_lookahead2": (
        {"cert_route_mode": "lookahead2"}, ("q4",),
        "E3：证书路径使用两步前瞻"),
    "e4_residual_sparsify": (
        {"q4_residual_sparsify": True}, ("q4",),
        "E4：Q4 残差证书稀疏化"),
    "e_all": (
        {"q4_certificate_layout": "sparse25",
         "q4_joint_rank": True,
         "cert_route_mode": "lookahead2",
         "q4_residual_sparsify": True},
        ("q4",),
        "E1-E4 全部启用"),
}

_Q4_E_FACTORS = (
    ("q4_certificate_layout", "sparse25"),
    ("q4_joint_rank", True),
    ("cert_route_mode", "lookahead2"),
    ("q4_residual_sparsify", True),
)
for _mask in range(16):
    _bits = format(_mask, "04b")
    _overrides = {
        key: value
        for bit, (key, value) in zip(_bits, _Q4_E_FACTORS)
        if bit == "1"
    }
    VARIANTS["e_combo_%s" % _bits] = (
        _overrides, ("q4",), "E1-E4 mask %s" % _bits)

POLICY_VARIANTS = tuple(VARIANTS)

# 证据瘦身：variant 批量跑时保留的文件/目录（C.6 要求失败案例证据保留）
_LITE_KEEP = ("metrics.json", "verifier_report.json", "run_report.json",
              "provenance.json", "config.yaml", "actions.csv",
              "decision_trace.jsonl", "ground_truth.json")

_BRANCH_METRIC_FIELDS = (
    "q4_certificate_layout", "q4_certificate_point_count",
    "joint_state_evaluations", "lookahead_decisions",
    "q4_certified_cells_raw", "q4_certified_cells_retained",
    "q4_certified_cells_pruned",
)
_CASE_METRICS_CSV_FIELDS = (
    "variant", "case_id", "case_seed", "scenario", "success", "complete",
    "verifier_all_ok", "clearance_ratio", "t_per_source_s",
    "T_total_virtual", "avg_localize_clear_time_s", "total_move_distance_m",
    "n_measures", "n_switches",
) + _BRANCH_METRIC_FIELDS


def _run_one_case(case, config, config_path, out_dir,
                  policy_variant="mainline", max_steps=None):
    sim = SyntheticSimulator.from_case(case)
    backend = SimulatorBackend(sim)
    executor = ActionExecutor(backend)
    kw = {"max_steps": max_steps} if max_steps else {}
    runner = GameRunner(case["question"].upper(), executor, out_dir,
                        simulator=sim, config=config, case=case,
                        config_path=config_path,
                        policy_variant=policy_variant, **kw)
    report = runner.run()
    return report, runner


def _ground_truth_check(runner):
    """ground-truth 后置检查（C.5/C.6）：假证书与漏源如实记录。

    返回 {"false_certified_absent": n, "false_cert_channels": [...],
          "missed_sources": [...]}。sound 主线下恒为零。
    """
    sim = runner.simulator
    if sim is None:
        return {"false_certified_absent": 0, "false_cert_channels": [],
                "missed_sources": []}
    cleared_channels = {c.channel_id for c in runner.ks.cleared}
    false_certs = []
    missed = []
    for s in sim.sources:
        if s.cleared:
            continue
        missed.append(s.channel)
        ch = runner.ks[s.channel]
        from state.channel_state import ChannelStatus
        if ch.status == ChannelStatus.CERTIFIED_ABSENT:
            false_certs.append({"channel": s.channel,
                                "absent_basis": ch.absent_basis})
    return {"false_certified_absent": len(false_certs),
            "false_cert_channels": false_certs,
            "missed_sources": sorted(missed),
            "uncleared_channels": sorted(
                c for c in
                {s.channel for s in sim.sources} - cleared_channels)}


def _extra_metrics(runner):
    """消融专项指标（从 runner 记录提取，不读文件）。"""
    dedicated_dist = 0.0
    cert_time = 0.0
    cert_dist = 0.0
    for a in runner.actions:
        if a["policy_mode"] == "active_localization":
            dedicated_dist += a["movement_distance"]
        elif a["policy_mode"] == "certificate":
            cert_time += (a["movement_time"] + a["switch_time"]
                          + a["action_time"])
            cert_dist += a["movement_distance"]
    # MEC 半径下降速度：每频道 (首条 r − 末条 r) / 更新次数 的平均
    drops = []
    for cid, entries in runner.loc_history.items():
        if len(entries) >= 2:
            r0 = entries[0]["mec_radius"]
            r1 = entries[-1]["mec_radius"]
            if r0 and r1 is not None:
                drops.append((r0 - r1) / (len(entries) - 1))
    # 证书完成时刻：所有 CERTIFIED_ABSENT 频道最后观测时刻的最大值
    from state.channel_state import ChannelStatus
    cert_done = 0.0
    for ch in runner.ks.channels.values():
        if ch.status == ChannelStatus.CERTIFIED_ABSENT \
                and ch.observations:
            cert_done = max(cert_done,
                            ch.observations[-1]["virtual_time"])
    return {
        "dedicated_localization_distance_m": dedicated_dist,
        "residual_certificate_time_s": cert_time,
        "residual_certificate_distance_m": cert_dist,
        "mec_drop_per_update_m": (sum(drops) / len(drops)) if drops else None,
        "certificate_completion_time_s": cert_done,
    }


def _case_entry(case, report, runner=None):
    m = report["metrics"]
    entry = {
        "case_id": case["case_id"],
        "case_seed": case["case_seed"],
        "scenario": case.get("scenario"),
        "error_field_type": case.get("error_field_type"),
        "success": bool(report["complete"] and report["verifier_all_ok"]),
        "complete": report["complete"],
        "verifier_all_ok": report["verifier_all_ok"],
        "failure": report["failure"],
        "clearance_ratio": (m["cleared_count"] / m["sources_total"])
        if m["sources_total"] else None,
        "t_per_source_s": m["t_per_source_s"],
        "T_total_virtual": m["T_total_virtual"],
        "avg_localize_clear_time_s": m["avg_localize_clear_time_s"],
        "total_move_distance_m": m["total_move_distance_m"],
        "n_measures": m["n_measures"],
        "n_switches": m["n_switches"],
        "obs_per_source": (m["n_measures"] / m["sources_total"])
        if m["sources_total"] else None,
        "T_measure": m["T_measure"],
        "T_switch": m["T_switch"],
        "wall_clock_s": m["wall_clock_s"],
        "output_dir": report["output_dir"],
    }
    entry.update({key: m.get(key) for key in _BRANCH_METRIC_FIELDS})
    if runner is not None:
        gt = _ground_truth_check(runner)
        entry.update(gt)
        entry.update(_extra_metrics(runner))
        # 假证书/漏源 ⇒ 不成功（C.6：记录为失败，不删除）
        if gt["false_certified_absent"] or gt["missed_sources"]:
            entry["success"] = False
    return entry


def _stats(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    q1 = vals[n // 4]
    q3 = vals[(3 * n) // 4]
    return {"n": n, "mean": mean, "median": med, "std": var ** 0.5,
            "iqr": q3 - q1, "best": vals[0], "worst": vals[-1]}


def _summaries(entries):
    """Addendum G 汇总：n/success/clearance/mean/median/std/IQR/best/worst。"""
    cr = _stats([e["clearance_ratio"] for e in entries])
    layouts = sorted({e.get("q4_certificate_layout") for e in entries
                      if e.get("q4_certificate_layout") is not None})
    return {
        "n_cases": len(entries),
        "success_count": sum(1 for e in entries if e["success"]),
        "verifier_success_count": sum(
            1 for e in entries
            if e.get("verifier_all_ok", e.get("success", False))),
        "q4_certificate_layout": (layouts[0] if len(layouts) == 1
                                  else layouts or None),
        "clearance_ratio_min": min(
            (e["clearance_ratio"] for e in entries
             if e["clearance_ratio"] is not None), default=None),
        "clearance_ratio_mean": cr["mean"] if cr else None,
        "t_per_source_s": _stats([e["t_per_source_s"] for e in entries]),
        "avg_localize_clear_time_s": _stats(
            [e["avg_localize_clear_time_s"] for e in entries]),
        "total_move_distance_m": _stats(
            [e["total_move_distance_m"] for e in entries]),
        "n_measures": _stats([e["n_measures"] for e in entries]),
        "n_switches": _stats([e["n_switches"] for e in entries]),
        "certificate_completion_time_s": _stats(
            [e.get("certificate_completion_time_s") for e in entries]),
        "q4_certificate_point_count": _stats(
            [e.get("q4_certificate_point_count") for e in entries]),
        "joint_state_evaluations": _stats(
            [e.get("joint_state_evaluations") for e in entries]),
        "lookahead_decisions": _stats(
            [e.get("lookahead_decisions") for e in entries]),
        "q4_certified_cells_raw": _stats(
            [e.get("q4_certified_cells_raw") for e in entries]),
        "q4_certified_cells_retained": _stats(
            [e.get("q4_certified_cells_retained") for e in entries]),
        "q4_certified_cells_pruned": _stats(
            [e.get("q4_certified_cells_pruned") for e in entries]),
    }


def _agg(entries):
    return aggregate_cases([{
        "t_per_source_s": e["t_per_source_s"],
        "T_total_virtual": e["T_total_virtual"],
        "sources_total": (e["T_total_virtual"] / e["t_per_source_s"]
                          if e["t_per_source_s"] else None),
    } for e in entries if e["t_per_source_s"] is not None])


def paired_diff(base_entries, variant_entries, base_name, var_name):
    """matched-case paired difference（Addendum G）：ΔX_i = X_var − X_base。"""
    base = {e["case_id"]: e for e in base_entries}
    pairs = []
    for e in variant_entries:
        b = base.get(e["case_id"])
        if b is None:
            continue
        pairs.append({
            "case_id": e["case_id"],
            "dT": (e["T_total_virtual"] - b["T_total_virtual"])
            if None not in (e["T_total_virtual"], b["T_total_virtual"])
            else None,
            "d_move_m": e["total_move_distance_m"]
            - b["total_move_distance_m"],
            "d_measures": e["n_measures"] - b["n_measures"],
            "d_switches": e["n_switches"] - b["n_switches"],
            "d_avg_loc_clear_s": (
                e["avg_localize_clear_time_s"]
                - b["avg_localize_clear_time_s"])
            if None not in (e.get("avg_localize_clear_time_s"),
                            b.get("avg_localize_clear_time_s")) else None,
            "base_success": b["success"], "variant_success": e["success"],
        })
    return {
        "base": base_name, "variant": var_name,
        "n_pairs": len(pairs),
        "dT": _stats([p["dT"] for p in pairs]),
        "d_move_m": _stats([p["d_move_m"] for p in pairs]),
        "d_measures": _stats([p["d_measures"] for p in pairs]),
        "d_avg_loc_clear_s": _stats([p["d_avg_loc_clear_s"]
                                     for p in pairs]),
        "pairs": pairs,
    }


def _write_markdown(path, summary):
    """suite 可读摘要（Addendum G 表 + paired difference）。"""
    lines = ["# Suite %s" % summary["suite"], ""]
    lines.append("- case_set: `%s`（question=%s, n=%d）"
                 % (summary["case_set"], summary["question"],
                    len(summary["cases_by_variant"].get(
                        summary["variants"][0], []))))
    lines.append("- config: `%s`" % json.dumps(summary["config"],
                                               ensure_ascii=False))
    lines.append("")
    for var in summary["variants"]:
        s = summary["summary_by_variant"][var]
        lines.append("## variant `%s`" % var)
        lines.append("")
        lines.append("| 指标 | n | success | clearance_min | mean | "
                     "median | std | best | worst |")
        lines.append("|---|---|---|---|---|---|---|---|---|")

        def row(name, st, fmt="%.1f"):
            if not st:
                lines.append("| %s | - | - | - | N/A | | | | |" % name)
                return
            lines.append("| %s | %d |  |  | %s | %s | %s | %s | %s |"
                         % (name, st["n"], fmt % st["mean"],
                            fmt % st["median"], fmt % st["std"],
                            fmt % st["best"], fmt % st["worst"]))

        lines.append("| 案例总数 | %d | %d | %s | | | | | |"
                     % (s["n_cases"], s["success_count"],
                        s["clearance_ratio_min"]))
        row("t_per_source_s", s["t_per_source_s"])
        row("avg_localize_clear_s", s["avg_localize_clear_time_s"])
        row("move_distance_m", s["total_move_distance_m"])
        row("n_measures", s["n_measures"])
        row("n_switches", s["n_switches"])
        row("cert_completion_s", s["certificate_completion_time_s"])
        row("q4_certificate_points", s["q4_certificate_point_count"],
            fmt="%.0f")
        row("joint_state_evaluations", s["joint_state_evaluations"],
            fmt="%.0f")
        row("lookahead_decisions", s["lookahead_decisions"], fmt="%.0f")
        row("q4_certified_cells_raw", s["q4_certified_cells_raw"],
            fmt="%.0f")
        row("q4_certified_cells_retained",
            s["q4_certified_cells_retained"], fmt="%.0f")
        row("q4_certified_cells_pruned", s["q4_certified_cells_pruned"],
            fmt="%.0f")
        lines.append("")
    for pd in summary.get("paired_differences", []):
        lines.append("## paired difference: `%s` − `%s`（n=%d）"
                     % (pd["variant"], pd["base"], pd["n_pairs"]))
        lines.append("")
        lines.append("| case_id | ΔT (s) | Δmove (m) | Δmeasures | "
                     "Δswitches |")
        lines.append("|---|---|---|---|---|")
        for p in pd["pairs"]:
            lines.append("| %s | %s | %s | %s | %s |"
                         % (p["case_id"],
                            "%.1f" % p["dT"] if p["dT"] is not None
                            else "N/A",
                            "%.0f" % p["d_move_m"], p["d_measures"],
                            p["d_switches"]))
        if pd["dT"]:
            lines.append("")
            lines.append("mean ΔT = %.1f s，median ΔT = %.1f s"
                         % (pd["dT"]["mean"], pd["dT"]["median"]))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _slim_run_dir(run_dir):
    """证据瘦身：variant 批量跑只留 _LITE_KEEP（摘要证据）。"""
    import shutil
    for name in os.listdir(run_dir):
        if name in _LITE_KEEP:
            continue
        p = os.path.join(run_dir, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)


def run_suite(suite_name, cases_path, config_path, out_root,
              policy_variant="mainline", max_steps=None, slim=False):
    """套件执行：同案例集 × 单 variant（向后兼容的单 variant 入口）。"""
    return run_ablation(suite_name, cases_path, config_path, out_root,
                        variants=(policy_variant,), max_steps=max_steps,
                        slim=slim)


def run_ablation(suite_name, cases_path, config_path, out_root,
                 variants=("mainline",), max_steps=None, slim=False):
    """多 variant matched-case 套件（Addendum C/G）。

    每个 variant 只改一个模块（见 VARIANTS 注册表），全部读取同一冻结
    案例文件。返回 summary dict。
    """
    for v in variants:
        if v not in VARIANTS:
            raise ValueError("unknown variant %r (registry: %r)"
                             % (v, tuple(VARIANTS)))
    base_config = load_config(config_path)
    case_set = load_case_set(cases_path)
    suite_dir = os.path.join(out_root, suite_name)
    os.makedirs(suite_dir, exist_ok=True)

    cases_by_variant = {}
    summary_by_variant = {}
    agg_by_variant = {}
    for var in variants:
        overrides, questions, desc = VARIANTS[var]
        if case_set["question"] not in questions:
            continue
        cfg = base_config.derive(**overrides)
        entries = []
        for case in case_set["cases"]:
            case_dir = os.path.join(suite_dir, var, case["case_id"])
            report, runner = _run_one_case(case, cfg, config_path, case_dir,
                                           policy_variant=var,
                                           max_steps=max_steps)
            entries.append(_case_entry(case, report, runner))
            e = entries[-1]
            print("[%s/%s] %s: success=%s T=%.0fs t/src=%s wall=%.1fs"
                  % (suite_name, var, case["case_id"], e["success"],
                     e["T_total_virtual"],
                     "%.1f" % e["t_per_source_s"]
                     if e["t_per_source_s"] is not None else "N/A",
                     e["wall_clock_s"]))
            if slim:
                _slim_run_dir(case_dir)
        cases_by_variant[var] = entries
        summary_by_variant[var] = _summaries(entries)
        agg_by_variant[var] = _agg(entries)

    variants_run = list(cases_by_variant)
    paired = []
    if len(variants_run) > 1:
        ref = variants_run[0]
        for var in variants_run[1:]:
            paired.append(paired_diff(cases_by_variant[ref],
                                      cases_by_variant[var], ref, var))

    summary = {
        "suite": suite_name,
        "variants": variants_run,
        "variant_descriptions": {v: VARIANTS[v][2] for v in variants_run},
        "case_set": os.path.basename(cases_path),
        "question": case_set["question"],
        "config": base_config.to_dict(),
        "config_path": config_path,
        "aggregate_by_variant": agg_by_variant,
        "summary_by_variant": summary_by_variant,
        "paired_differences": paired,
        "cases_by_variant": cases_by_variant,
        "note": "failed cases are kept and counted as failures "
                "(Addendum C.6); false certificates detected via "
                "ground-truth post-check never count as success",
    }
    sp = os.path.join(suite_dir, "suite_summary.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
        f.write("\n")
    # Addendum G：stats.json + markdown 表
    stats = {"suite": suite_name, "variants": variants_run,
             "summary_by_variant": summary_by_variant,
             "paired_differences": paired}
    with open(os.path.join(suite_dir, "stats.json"), "w",
              encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(os.path.join(suite_dir, "case_metrics.csv"), "w",
              encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CASE_METRICS_CSV_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for variant in variants_run:
            for entry in cases_by_variant[variant]:
                writer.writerow({"variant": variant, **entry})
    _write_markdown(os.path.join(suite_dir, "summary.md"), summary)
    return summary


def run_tune(parameter, cases_path, config_path, out_root,
             tau_grid=None, max_steps=None):
    """C 类参数筛选（Addendum B.4/B.5）：逐 tau 候选 × 逐案例 mainline。"""
    if parameter != "tau":
        raise ValueError("only C-class parameter is 'tau' (Addendum B.1)")
    base = load_config(config_path)
    grid = [float(v) for v in tau_grid] if tau_grid else [base.tau]
    case_set = load_case_set(cases_path)

    results = []
    for tau in grid:
        cfg = base.derive(tau=tau)
        cand_dir = os.path.join(out_root, "tau_%g" % tau)
        entries = []
        for case in case_set["cases"]:
            report, runner = _run_one_case(
                case, cfg, config_path,
                os.path.join(cand_dir, case["case_id"]),
                max_steps=max_steps)
            entries.append(_case_entry(case, report, runner))
            _slim_run_dir(os.path.join(cand_dir, case["case_id"]))
        summ = _summaries(entries)
        ok_clearance = (summ["clearance_ratio_min"] is not None
                        and summ["clearance_ratio_min"] >= 1.0 - 1e-9)
        results.append({
            "tau": tau,
            "clearance_ok": ok_clearance,     # primary 硬约束（B.5）
            "aggregate": _agg(entries),
            "summary": summ,
            "cases": entries,
        })
        tps = summ["t_per_source_s"]
        print("tau=%g: clearance_ok=%s success=%d/%d mean_t/src=%s"
              % (tau, ok_clearance, summ["success_count"],
                 summ["n_cases"],
                 "%.1f" % tps["mean"] if tps else "N/A"))

    out = {
        "parameter": "tau",
        "case_set": os.path.basename(cases_path),
        "question": case_set["question"],
        "config_path": config_path,
        "selected_tau": None,   # 由选择规则回填（select_tau）
        "selection_metric": "Addendum B.5 primary/secondary",
        "results": results,
    }
    os.makedirs(out_root, exist_ok=True)
    rp = os.path.join(out_root, "tune_results.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return out


def select_tau(tune_results_list):
    """B.5 选择规则：Robust Good > Fragile Best。

    输入：多个 tune_results（q3/q4 各一）。Primary：clearance 必须 100%
    （两集皆然）；其后 min mean t_per_source_s（两集合并案例）。性能接近
    （<2%）时选 std 更小者；再平手选更少检测者；再平手选更小 tau
    （更简单）。
    返回 (selected_tau, rationale dict)。
    """
    per_tau = {}
    for tr in tune_results_list:
        for r in tr["results"]:
            d = per_tau.setdefault(r["tau"], {"clearance_ok": True,
                                              "entries": []})
            d["clearance_ok"] &= r["clearance_ok"]
            d["entries"].extend(r["cases"])
    cands = []
    for tau, d in sorted(per_tau.items()):
        summ = _summaries(d["entries"])
        cands.append({"tau": tau, "clearance_ok": d["clearance_ok"],
                      "summary": summ})
    eligible = [c for c in cands if c["clearance_ok"]
                and c["summary"]["t_per_source_s"]]
    if not eligible:
        return None, {"reason": "no candidate with 100% clearance",
                      "candidates": cands}
    best_primary = min(c["summary"]["t_per_source_s"]["mean"]
                       for c in eligible)
    close = [c for c in eligible
             if c["summary"]["t_per_source_s"]["mean"]
             <= best_primary * 1.02]
    # 稳定性：std 小者优先；平手（<2%）比检测数；再平手取小 tau
    def stability_key(c):
        s = c["summary"]
        return (round(s["t_per_source_s"]["std"], 1),
                round(s["n_measures"]["mean"], 1)
                if s["n_measures"] else 0.0, c["tau"])
    close.sort(key=stability_key)
    chosen = close[0]
    return chosen["tau"], {
        "rule": "B.5: clearance==100% hard constraint; min mean "
                "t_per_source_s; within 2% -> smaller std -> fewer "
                "measures -> smaller tau",
        "best_primary_mean": best_primary,
        "close_candidates": [{"tau": c["tau"],
                              "mean": c["summary"]["t_per_source_s"]["mean"],
                              "std": c["summary"]["t_per_source_s"]["std"]}
                             for c in close],
        "all_candidates": [{
            "tau": c["tau"], "clearance_ok": c["clearance_ok"],
            "t_per_source_s": c["summary"]["t_per_source_s"],
            "n_measures": c["summary"]["n_measures"],
            "move_m": c["summary"]["total_move_distance_m"],
            "n_switches": c["summary"]["n_switches"],
            "cert_completion_s":
                c["summary"]["certificate_completion_time_s"],
        } for c in cands],
    }
