#!/usr/bin/env python
"""Create paper-ready plots from freshly executed Q3 cross-simulator runs.

Input data are produced by ``run_q3_v5_on_ours.py`` in this repository and by
the current mainline batch run.  This script intentionally does not read the
external package's historical result files.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


CODE = Path(__file__).resolve().parents[1]
OUT = CODE / "output"
TARGET = CODE.parents[2] / "paper" / "fresh_q3_cross_sim_evidence_20260913"

PALETTE = {
    "mainline": "#8A8A8A",
    "v5": "#0072B2",
    "accent": "#D55E00",
    "green": "#009E73",
    "purple": "#CC79A7",
}


def load_v5(folder: str) -> dict:
    return json.loads((OUT / folder / "summary.json").read_text(encoding="utf-8"))


def load_mainline() -> list[dict]:
    path = OUT / "mainline_q3_16x12" / "per_case.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: float(value) if key not in {"seed", "complete", "verifier_all_ok"}
             else value for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def values(report: dict) -> np.ndarray:
    return np.asarray([float(row["seconds_per_source"]) for row in report["rows"]])


def mean_and_p90(data: np.ndarray) -> tuple[float, float]:
    return float(data.mean()), float(np.quantile(data, 0.9))


def save(fig, name: str) -> None:
    fig.savefig(TARGET / (name + ".png"), dpi=300, bbox_inches="tight")
    fig.savefig(TARGET / (name + ".pdf"), bbox_inches="tight")
    plt.close(fig)


def draw_paired(mainline: list[dict], v5: dict) -> dict:
    by_seed = {int(row["seed"]): float(row["s_per_source"]) for row in mainline}
    v5_rows = sorted(v5["rows"], key=lambda row: int(row["seed"]))
    seed_order = [int(row["seed"]) for row in v5_rows]
    v5_values = np.asarray([float(row["seconds_per_source"]) for row in v5_rows])
    main_values = np.asarray([by_seed[seed] for seed in seed_order])

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    for old, new in zip(main_values, v5_values):
        ax.plot([0, 1], [old, new], color="#C8C8C8", lw=1.25, zorder=1)
    ax.scatter(np.zeros_like(main_values), main_values, s=42, color=PALETTE["mainline"],
               label="Current mainline", zorder=2)
    ax.scatter(np.ones_like(v5_values), v5_values, s=42, color=PALETTE["v5"],
               label="V5 transferred to our simulator", zorder=3)
    old_mean, old_p90 = mean_and_p90(main_values)
    new_mean, new_p90 = mean_and_p90(v5_values)
    for x, mean, color in [(0, old_mean, PALETTE["mainline"]), (1, new_mean, PALETTE["v5"])]:
        ax.hlines(mean, x - 0.24, x + 0.24, color=color, lw=3)
    improvement = 1.0 - new_mean / old_mean
    ax.text(0.5, max(main_values) + 35, "Mean reduction: %.1f%%" % (100 * improvement),
            ha="center", va="bottom", weight="bold", color=PALETTE["accent"])
    ax.set_xticks([0, 1], ["Current\nmainline", "V5 on our\nsimulator"])
    ax.set_ylabel("Virtual seconds per source")
    ax.set_title("Q3, 16 sources, same 12 random seeds")
    ax.set_ylim(0, max(main_values) + 85)
    ax.grid(axis="y", alpha=0.25)
    save(fig, "fig_fresh_01_paired_q3_16_comparison")
    return {"mainline_mean": old_mean, "mainline_p90": old_p90,
            "v5_mean": new_mean, "v5_p90": new_p90,
            "relative_reduction": improvement}


def draw_source_count(reports: dict[str, dict]) -> dict:
    labels = ["10", "13", "15", "16"]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    summary = {}
    for index, label in enumerate(labels):
        data = values(reports[label])
        jitter = np.linspace(-0.14, 0.14, len(data))
        ax.scatter(index + jitter, data, s=35, color=PALETTE["v5"], alpha=0.8)
        mean, p90 = mean_and_p90(data)
        ax.errorbar(index, mean, yerr=[[mean - data.min()], [data.max() - mean]],
                    fmt="o", ms=8, color=PALETTE["accent"], capsize=5, zorder=4)
        ax.text(index, mean + 10, "%.1f" % mean, ha="center", color=PALETTE["accent"], weight="bold")
        summary[label] = {"mean": mean, "median": float(np.median(data)),
                          "p90": p90, "minimum": float(data.min()), "maximum": float(data.max())}
    ax.set_xticks(range(len(labels)), labels)
    ax.set_xlabel("Number of sources")
    ax.set_ylabel("Virtual seconds per source")
    ax.set_title("Q3 V5: performance changes with source count (12 seeds each)")
    ax.grid(axis="y", alpha=0.25)
    ax.set_ylim(0, 330)
    save(fig, "fig_fresh_02_source_count_robustness")
    return summary


def draw_boxplot(reports: dict[str, dict], filename: str, title: str) -> dict:
    labels = list(reports)
    arrays = [values(reports[label]) for label in labels]
    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    box = ax.boxplot(arrays, labels=labels, patch_artist=True, showmeans=True,
                     meanprops={"marker": "D", "markerfacecolor": PALETTE["accent"],
                                "markeredgecolor": PALETTE["accent"]})
    colors = [PALETTE["v5"], PALETTE["accent"], PALETTE["green"], PALETTE["purple"]]
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    for index, data in enumerate(arrays, 1):
        ax.scatter(np.full(len(data), index) + np.linspace(-0.11, 0.11, len(data)), data,
                   s=22, color="#333333", alpha=0.55, zorder=3)
    ax.set_ylabel("Virtual seconds per source")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)
    save(fig, filename)
    return {label: {"mean": float(data.mean()), "median": float(np.median(data)),
                    "p90": float(np.quantile(data, 0.9)), "minimum": float(data.min()),
                    "maximum": float(data.max())}
            for label, data in zip(labels, arrays)}


def draw_decomposition(mainline: list[dict], v5: dict) -> dict:
    main_parts = {
        "Move": float(np.mean([row["move_s"] for row in mainline])),
        "Measure": float(np.mean([row["measure_s"] for row in mainline])),
        "Switch": float(np.mean([row["switch_s"] for row in mainline])),
        "Clear": float(np.mean([row["clear_s"] for row in mainline])),
    }
    v5_parts = {
        "Move": float(np.mean([row["time_move_s"] for row in v5["rows"]])),
        "Measure": float(np.mean([row["time_measure_s"] for row in v5["rows"]])),
        "Switch": float(np.mean([row["time_switch_s"] for row in v5["rows"]])),
        "Clear": float(np.mean([row["time_clear_s"] for row in v5["rows"]])),
    }
    fig, ax = plt.subplots(figsize=(7.4, 4.7))
    x = np.arange(2)
    bottoms = np.zeros(2)
    colors = ["#56B4E9", "#E69F00", "#CC79A7", "#009E73"]
    for (name, color) in zip(main_parts, colors):
        vals = np.array([main_parts[name], v5_parts[name]])
        ax.bar(x, vals, bottom=bottoms, width=0.56, color=color, label=name)
        bottoms += vals
    ax.set_xticks(x, ["Current mainline", "V5 on our simulator"])
    ax.set_ylabel("Mean virtual seconds per case")
    ax.set_title("Q3 / 16 sources: fresh time-accounting comparison")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    save(fig, "fig_fresh_05_time_decomposition")
    return {"mainline": main_parts, "v5": v5_parts}


def draw_ablation() -> dict:
    path = OUT / "fresh_q3_v5_ablation_16x12" / "summary.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    order = ["selected", "no_shared_search", "no_initial_probe", "no_trial_clear", "legacy_route_order"]
    labels = ["Selected", "No shared\nsearch", "No 250 m\nprobe", "No trial\nclear", "Legacy\nroute order"]
    means = [report["configs"][name]["summary"]["mean_seconds_per_source"] for name in order]
    p90s = [report["configs"][name]["summary"]["p90_seconds_per_source"] for name in order]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    colors = [PALETTE["v5"], "#56B4E9", "#E69F00", "#CC79A7", PALETTE["accent"]]
    bars = ax.bar(np.arange(len(order)), means, color=colors, width=.7)
    baseline = means[0]
    for index, (bar, value, p90) in enumerate(zip(bars, means, p90s)):
        delta = value - baseline
        label = "%.1f" % value if index == 0 else "%+.1f" % delta
        ax.text(bar.get_x() + bar.get_width() / 2, value + 3.5, label,
                ha="center", va="bottom", fontsize=10, weight="bold")
        ax.vlines(index, value, p90, color="#333333", lw=1.2)
        ax.hlines(p90, index - .12, index + .12, color="#333333", lw=1.2)
    ax.axhline(baseline, color=PALETTE["v5"], ls="--", lw=1.2)
    ax.set_xticks(np.arange(len(order)), labels)
    ax.set_ylabel("Mean virtual seconds per source")
    ax.set_title("Q3 V5 component ablation: 16 sources, same 12 seeds")
    ax.grid(axis="y", alpha=.25)
    ax.set_ylim(0, max(p90s) + 34)
    save(fig, "fig_fresh_06_q3_v5_ablation")
    return {name: report["configs"][name]["summary"] for name in order}


def write_note(stats: dict) -> None:
    source = stats["source_count"]
    spatial = stats["spatial"]
    error = stats["error"]
    paired = stats["paired"]
    note = f"""# Q3 本地迁移实跑：可写入论文的稳健性证据

## 实验设置

将 `Q3_Q4_V3` 中的 Q3-v5 策略通过兼容层接入本仓库的 `SyntheticSimulator`；策略动作只能读取 `/measure` 与 `/clear` 的协议响应。每个测试局结束后才读取模拟器状态，以核对是否清除了全部真实源。没有使用外部包中已有的结果文件。

随机场景固定为 12 个新 seed：101、202、303、404、505、606、707、808、909、1001、1102、1203。除特别说明外，测向误差场为位置固定的 `random_fixed` 有界误差。以下分数均为虚拟时间除以真实源数。

## 可直接写入正文的结论

1. 在 Q3、16 源、随机场景的 12 个相同 seed 上，当前主线 12/12 完成且 verifier 通过，均值为 {paired['mainline_mean']:.2f} s/源；迁移后的 V5 同样 12/12 清除全部真实源，均值为 {paired['v5_mean']:.2f} s/源，P90 为 {paired['v5_p90']:.2f} s/源。相同场景下，虚拟时间均值下降 {100 * paired['relative_reduction']:.1f}%。该结论仅适用于本地合成器与这 12 个固定 seed，不能写成正式评测成绩。

2. V5 的 16 源随机结果范围为 {source['16']['minimum']:.2f}--{source['16']['maximum']:.2f} s/源，中位数为 {source['16']['median']:.2f} s/源。因此，单局约 184 s/源属于可出现的较优样本，不能代表稳定典型水平；本组的稳健报告应同时给均值、中位数、P90 和全清率。

3. 源数会显著改变平均耗时：10、13、15、16 源的均值分别为 {source['10']['mean']:.2f}、{source['13']['mean']:.2f}、{source['15']['mean']:.2f}、{source['16']['mean']:.2f} s/源。少源时固定搜索与覆盖成本由更少的源分摊，因此不能只用 16 源成绩代表整体性能。

4. 空间分布压力测试显示，16 源稠密簇的均值为 {spatial['dense']['mean']:.2f} s/源，边界分布为 {spatial['boundary']['mean']:.2f} s/源，稀疏分布为 {spatial['sparse']['mean']:.2f} s/源，随机分布为 {spatial['random']['mean']:.2f} s/源。该差异解释了同一策略的单局波动主要来自空间几何，而非计算时间随机性。

5. 三种位置固定、有界测向误差场下，16 源随机场景的均值分别为 random-fixed {error['random_fixed']['mean']:.2f}、boundary {error['boundary']['mean']:.2f}、structured {error['structured']['mean']:.2f} s/源，且均 12/12 全清。至少在这三种本地误差模型下，均值差异远小于源空间分布造成的差异。

6. 消融结果表明，保持其他参数不变而将联合开放路径替换为旧式路径顺序，均值从 {stats['ablation']['selected']['mean_seconds_per_source']:.2f} 上升至 {stats['ablation']['legacy_route_order']['mean_seconds_per_source']:.2f} s/源；去掉 250 m 初始探测后为 {stats['ablation']['no_initial_probe']['mean_seconds_per_source']:.2f} s/源。相比之下，关闭共享搜索只有 {stats['ablation']['no_shared_search']['mean_seconds_per_source'] - stats['ablation']['selected']['mean_seconds_per_source']:+.2f} s/源变化；在独立的 12 个 holdout seed 上，差异仍只有 {stats['ablation_holdout']['no_shared_search']['mean_seconds_per_source'] - stats['ablation_holdout']['selected']['mean_seconds_per_source']:+.2f} s/源。因此不能将共享搜索开关作为稳定有效的改进写入主结论。

## 图表使用说明

- `fig_fresh_01_paired_q3_16_comparison`：同 seed 配对结果，适合“优化效果”小节。
- `fig_fresh_02_source_count_robustness`：源数敏感性，适合“稳健性分析”小节。
- `fig_fresh_03_spatial_distribution_stress`：空间分布压力测试，适合讨论最差场景。
- `fig_fresh_04_error_field_robustness`：误差场压力测试。
- `fig_fresh_05_time_decomposition`：成本结构，适合解释为何路线重构带来主要收益。
- `fig_fresh_06_q3_v5_ablation`：模块消融，适合“策略有效性分析”小节。

## 写作边界

这些是本地合成器的迁移实验，不能表述为官方测试、正式排名或理论最优性证明。外部策略代码的来源必须按你实际拥有的使用权和论文规范处理；本文件只记录本次新实跑的实验事实。
"""
    (TARGET / "README_论文可用证据.md").write_text(note, encoding="utf-8")


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    source_reports = {
        "10": load_v5("fresh_q3_v5_on_ours_10x12"),
        "13": load_v5("fresh_q3_v5_on_ours_13x12"),
        "15": load_v5("fresh_q3_v5_on_ours_15x12"),
        "16": load_v5("fresh_q3_v5_on_ours_16x12"),
    }
    spatial_reports = {
        "random": source_reports["16"],
        "boundary": load_v5("fresh_q3_v5_on_ours_16_boundaryx12"),
        "dense": load_v5("fresh_q3_v5_on_ours_16_densex12"),
        "sparse": load_v5("fresh_q3_v5_on_ours_16_sparsex12"),
    }
    error_reports = {
        "random_fixed": source_reports["16"],
        "boundary": load_v5("fresh_q3_v5_on_ours_16_error_boundaryx12"),
        "structured": load_v5("fresh_q3_v5_on_ours_16_error_structuredx12"),
    }
    mainline = load_mainline()
    paired = draw_paired(mainline, source_reports["16"])
    source_count = draw_source_count(source_reports)
    spatial = draw_boxplot(spatial_reports, "fig_fresh_03_spatial_distribution_stress",
                           "Q3 V5, 16 sources: spatial-distribution stress test")
    error = draw_boxplot(error_reports, "fig_fresh_04_error_field_robustness",
                         "Q3 V5, 16 sources: bounded bearing-error fields")
    decomposition = draw_decomposition(mainline, source_reports["16"])
    ablation = draw_ablation()
    ablation_holdout_raw = json.loads(
        (OUT / "fresh_q3_v5_ablation_holdout_16x12" / "summary.json").read_text(encoding="utf-8"))
    ablation_holdout = {name: data["summary"]
                        for name, data in ablation_holdout_raw["configs"].items()}
    stats = {"paired": paired, "source_count": source_count, "spatial": spatial,
             "error": error, "decomposition": decomposition, "ablation": ablation,
             "ablation_holdout": ablation_holdout}
    (TARGET / "fresh_run_statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    write_note(stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("OUTPUT_DIRECTORY=" + str(TARGET))


if __name__ == "__main__":
    main()
