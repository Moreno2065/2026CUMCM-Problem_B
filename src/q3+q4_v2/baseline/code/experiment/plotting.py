# -*- coding: utf-8 -*-
"""Figure 生成（Addendum F）。

流程固定为 raw evidence → figure_data → plot script → final figure。
build_figures 依次以子进程调用 figures/scripts/plot_fig1.py … plot_fig8.py
（每个脚本独立可重跑：python figures/scripts/plot_figN.py
 [--results code/results] [--out code/figures]），随后盘点证据并写
figures_manifest.json。
"""

import json
import os
import subprocess
import sys

EXPECTED_FIGURES = {
    "fig1_method_loop": "方法闭环图（F.1）",
    "fig2_bounded_bearing_geometry": "bounded-bearing geometry（F.2）",
    "fig3_q3_certificate": "Q3 certificate accumulation（F.3）",
    "fig4_q4_robust_certificate": "Q4 robust convex certificate（F.4）",
    "fig5_localization_convergence": "localization convergence（F.5）",
    "fig6_ablation_paired": "ablation paired comparison（F.6）",
    "fig7_time_decomposition": "time decomposition（F.7）",
    "fig8_certificate_progress": "certificate progress（F.8）",
}

_SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "figures", "scripts")
PLOT_SCRIPTS = [os.path.join(_SCRIPT_DIR, "plot_fig%d.py" % i)
                for i in range(1, 9)]


def _inventory_run(run_dir):
    """单局目录的 figure 证据盘点。"""
    fd = os.path.join(run_dir, "figure_data")
    inv = {"run_dir": run_dir,
           "has_figure_data": os.path.isdir(fd),
           "figure_data_files": sorted(os.listdir(fd))
           if os.path.isdir(fd) else [],
           "has_decision_trace": os.path.isfile(
               os.path.join(run_dir, "decision_trace.jsonl")),
           "has_localization_history": os.path.isdir(
               os.path.join(run_dir, "localization_history")),
           "has_certificate_history": os.path.isdir(
               os.path.join(run_dir, "certificate_history"))}
    return inv


def _run_plot_scripts(results_dir, out_dir):
    """依次子进程调 8 个 plot 脚本，返回每脚本执行记录。"""
    records = []
    for script in PLOT_SCRIPTS:
        if not os.path.isfile(script):
            records.append({"script": script, "ok": False,
                            "error": "script missing"})
            continue
        proc = subprocess.run(
            [sys.executable, script, "--results", os.path.abspath(results_dir),
             "--out", os.path.abspath(out_dir)],
            capture_output=True, text=True)
        records.append({"script": os.path.basename(script),
                        "ok": proc.returncode == 0,
                        "returncode": proc.returncode,
                        "stdout_tail": (proc.stdout or "")[-400:],
                        "stderr_tail": (proc.stderr or "")[-400:]})
        if proc.returncode != 0:
            break  # 有序失败即停，避免半套图静默通过
    return records


def build_figures(experiment_dir, out_dir=None, render=True):
    """重建 Addendum F 全部图，并输出 figures_manifest.json。

    experiment_dir：结果根目录（通常 code/results，需含 figure_runs/ 与
    ablation/）。render=False 时只做证据盘点（兼容骨架阶段用法）。
    返回 manifest dict。
    """
    if not os.path.isdir(experiment_dir):
        raise ValueError("experiment dir not found: %s" % experiment_dir)
    out_dir = out_dir or os.path.join(experiment_dir, "figures")
    os.makedirs(out_dir, exist_ok=True)

    runs = []
    if os.path.isfile(os.path.join(experiment_dir, "metrics.json")):
        runs.append(_inventory_run(experiment_dir))
    for name in sorted(os.listdir(experiment_dir)):
        sub = os.path.join(experiment_dir, name)
        if os.path.isdir(sub) and os.path.isfile(
                os.path.join(sub, "metrics.json")):
            runs.append(_inventory_run(sub))

    plot_records = _run_plot_scripts(experiment_dir, out_dir) \
        if render else []

    produced = {}
    for key in EXPECTED_FIGURES:
        pdf = os.path.join(out_dir, key + ".pdf")
        png = os.path.join(out_dir, key + ".png")
        produced[key] = {
            "pdf": os.path.isfile(pdf) and os.path.getsize(pdf) > 0,
            "png": os.path.isfile(png) and os.path.getsize(png) > 0,
        }

    manifest = {
        "experiment_dir": os.path.abspath(experiment_dir),
        "out_dir": os.path.abspath(out_dir),
        "stage": "rendered — Addendum F figures F.1-F.8",
        "expected_figures": EXPECTED_FIGURES,
        "plot_scripts": plot_records,
        "all_scripts_ok": bool(plot_records) and all(
            r["ok"] for r in plot_records),
        "produced": produced,
        "all_figures_present": all(
            v["pdf"] and v["png"] for v in produced.values()),
        "n_runs": len(runs),
        "runs": runs,
        "evidence_complete": bool(runs) and all(
            r["has_figure_data"] and r["has_decision_trace"]
            and r["has_localization_history"]
            and r["has_certificate_history"] for r in runs),
    }
    mp = os.path.join(out_dir, "figures_manifest.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return manifest
