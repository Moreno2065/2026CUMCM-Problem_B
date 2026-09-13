"""Generate the traceable, Chinese-language paper figures as JPEG only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch
import numpy as np


V1 = "#6F7898"
V2 = "#1769AA"
V2_LIGHT = "#8CB9D9"
ACCENT = "#D97745"
NEGATIVE = "#B64342"
NEUTRAL = "#60656F"
GRID = "#D9DDE5"


def expected_figure_names() -> list[str]:
    return [
        "fig07_v1_baseline.jpg",
        "fig08_framework.jpg",
        "fig09_paired_performance.jpg",
        "fig10_q3_ablation.jpg",
        "fig11_q4_ablation.jpg",
        "fig12_sensitivity.jpg",
        "fig13_time_breakdown.jpg",
        "fig14_q3_route.jpg",
        "fig15_q4_route.jpg",
    ]


def _configure() -> None:
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "Arial Unicode MS",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "font.size": 8.5,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "legend.frameon": False,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
        }
    )


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"no figure data for {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(
        path,
        dpi=400,
        facecolor="white",
        edgecolor="white",
        bbox_inches="tight",
        pad_inches=0.08,
        format="jpg",
        pil_kwargs={"quality": 96, "subsampling": 0, "optimize": True},
    )
    plt.close(fig)


def _panel(ax, label: str) -> None:
    ax.text(-0.12, 1.05, label, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top")


def _v1_baseline(evidence: Path, figures: Path, data_root: Path) -> None:
    """Draw the frozen guarantee-first V1 state machine used as baseline."""
    rows = [
        {"from": "UNKNOWN", "event": "direction/near", "to": "ACTIVE/READY"},
        {"from": "UNKNOWN", "event": "完整发现证书均无信号", "to": "CERTIFIED_ABSENT"},
        {"from": "ACTIVE", "event": "定位集合收缩", "to": "READY"},
        {"from": "READY", "event": "clear=success", "to": "CLEARED"},
        {"from": "GLOBAL", "event": "16 源清除或 20 频道均闭合", "to": "STOP"},
    ]
    _write_csv(data_root / "fig07_v1_baseline.csv", rows)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 7); ax.axis("off")
    ax.set_title("V1 冻结基线：先保证可发现、可清除、可终止",
                 fontsize=12.5, fontweight="bold", pad=14)

    def box(x, y, w, h, label, color=V1, fill="#EEF0F6"):
        patch = FancyBboxPatch((x, y), w, h,
                               boxstyle="round,pad=0.03,rounding_size=0.08",
                               facecolor=fill, edgecolor=color, linewidth=1.3)
        ax.add_patch(patch)
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                fontsize=9, fontweight="bold")

    box(0.45, 4.45, 2.0, 0.9, "UNKNOWN")
    box(3.35, 4.45, 2.0, 0.9, "ACTIVE")
    box(6.25, 4.45, 2.0, 0.9, "READY")
    box(9.15, 4.45, 2.0, 0.9, "CLEARED", ACCENT, "#FFF4EC")
    box(3.35, 1.65, 3.0, 0.9, "CERTIFIED_ABSENT")
    box(8.5, 1.65, 3.0, 0.9, "STOP", ACCENT, "#FFF4EC")

    def arrow(a, b, label, color=NEUTRAL, label_pos=None):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12,
                                     color=color, linewidth=1.2))
        x, y = label_pos or ((a[0]+b[0])/2, (a[1]+b[1])/2 + 0.62)
        ax.text(x, y, label,
                ha="center", va="bottom", fontsize=7.5, color=color)

    arrow((2.45, 4.9), (3.35, 4.9), "direction / near", label_pos=(2.9, 5.55))
    arrow((5.35, 4.9), (6.25, 4.9), "集合收缩", label_pos=(5.8, 5.55))
    arrow((8.25, 4.9), (9.15, 4.9), "clear=success", ACCENT, (8.7, 5.55))
    arrow((1.45, 4.43), (3.85, 2.57), "有限发现证书均无信号", label_pos=(2.4, 3.45))
    arrow((6.35, 2.1), (8.5, 2.1), "与 CLEARED 共同闭合全部频道", ACCENT, (7.45, 2.72))
    arrow((10.15, 4.43), (10.15, 2.57), "已清除 16 个源", ACCENT, (10.72, 3.45))
    ax.text(6, 0.65,
            "V1 固定扫描/返回结构是可执行的安全基线；V2 仅优化动作次序与共享路径，不放松上述终止门槛。",
            ha="center", color=NEUTRAL, fontsize=8.3)
    _save(fig, figures / "fig07_v1_baseline.jpg")


def _framework(evidence: Path, figures: Path, data_root: Path) -> None:
    nodes = [
        {"layer": "input", "node": "有界误差观测与动作日志"},
        {"layer": "guarantee", "node": "集合知识状态"},
        {"layer": "guarantee", "node": "发现/清除证书"},
        {"layer": "guarantee", "node": "基数停止与 verifier"},
        {"layer": "decision", "node": "联合开放路线"},
        {"layer": "decision", "node": "共享/条件探点"},
        {"layer": "decision", "node": "试探清除与负反馈"},
        {"layer": "output", "node": "全部清除 + 可审计终止"},
    ]
    _write_csv(data_root / "fig08_framework.csv", nodes)
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
    ax.text(5, 9.95, "从确定性证书基线到联合搜索—定位—清除策略",
            ha="center", va="top", fontsize=12.5, fontweight="bold")
    ax.text(5, 9.05, "保证层回答“能否可靠完成”，决策层回答“下一步如何更省时”",
            ha="center", color=NEUTRAL, fontsize=9.5)

    def box(x, y, w, h, text, fc, ec, lw=1.2):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.03,rounding_size=0.08",
                               facecolor=fc, edgecolor=ec, linewidth=lw)
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=9, linespacing=1.35)
        return patch

    box(3.3, 7.85, 3.4, 0.75, "有界误差观测与动作日志", "#F4F5F8", NEUTRAL)
    ax.text(0.45, 6.75, "V1：确定性证书基线", color=V1, fontsize=10.5,
            fontweight="bold", rotation=90, va="center")
    for x, text in zip((1.0, 3.65, 6.3), ("集合知识状态", "发现与清除证书", "基数停止与 verifier")):
        box(x, 6.1, 2.15, 1.15, text, "#EEF0F6", V1)
    ax.add_patch(FancyBboxPatch((0.75, 5.75), 7.95, 1.85,
                               boxstyle="round,pad=0.05", fill=False,
                               edgecolor=V1, linewidth=1.6, linestyle="--"))
    ax.text(9.15, 6.68, "保留", color=V1, fontsize=9, ha="center")
    ax.add_patch(FancyArrowPatch((8.6, 6.65), (7.9, 6.65), arrowstyle="-|>",
                                 mutation_scale=12, color=V1, linewidth=1.3))

    ax.text(0.45, 3.65, "V2：联合决策层", color=V2, fontsize=10.5,
            fontweight="bold", rotation=90, va="center")
    for x, text in zip((1.0, 3.65, 6.3), ("联合开放路线", "共享/条件探点", "试探清除与负反馈")):
        box(x, 3.05, 2.15, 1.15, text, "#E8F2F8", V2)
    ax.add_patch(FancyBboxPatch((0.75, 2.7), 7.95, 1.85,
                               boxstyle="round,pad=0.05", fill=False,
                               edgecolor=V2, linewidth=1.6))
    ax.text(9.15, 3.63, "优化", color=V2, fontsize=9, ha="center")
    ax.add_patch(FancyArrowPatch((8.6, 3.6), (7.9, 3.6), arrowstyle="-|>",
                                 mutation_scale=12, color=V2, linewidth=1.3))
    for x in (2.08, 4.72, 7.37):
        ax.add_patch(FancyArrowPatch((x, 6.08), (x, 4.22), arrowstyle="-|>",
                                     mutation_scale=11, color="#8A91A0", linewidth=1.0))
    box(2.75, 0.85, 4.5, 0.95, "全部真实源清除  +  终止证据可审计", "#FFF4EC", ACCENT, 1.5)
    for x in (3.1, 5.0, 6.9):
        ax.add_patch(FancyArrowPatch((x, 3.0), (x, 1.78), arrowstyle="-|>",
                                     mutation_scale=11, color=ACCENT, linewidth=1.0))
    ax.text(5, 0.25, "V1 不是被丢弃的旧方案，而是 V2 的安全约束与比较基线",
            ha="center", fontsize=8.8, color=NEUTRAL)
    _save(fig, figures / "fig08_framework.jpg")


def _paired(evidence: Path, figures: Path, data_root: Path) -> None:
    rows = _read_csv(evidence / "tables/run_level.csv")
    effects = _read_csv(evidence / "tables/paired_effects.csv")
    _write_csv(data_root / "fig09_paired_performance.csv", rows)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.6), constrained_layout=True)
    markers = {10: "o", 13: "s", 16: "^"}
    for ax, question, panel in zip(axes, ("q3", "q4"), ("a", "b")):
        qrows = [r for r in rows if r["question"] == question]
        lookup = {}
        for row in qrows:
            lookup.setdefault(row["case_hash"], {})[row["policy"]] = row
        for count in (10, 13, 16):
            pairs = [v for v in lookup.values()
                     if int(v["v1_frozen"]["source_count"]) == count]
            x = [float(v["v1_frozen"]["t_per_source_s"]) for v in pairs]
            y = [float(v["v2_final"]["t_per_source_s"]) for v in pairs]
            ax.scatter(x, y, s=25, alpha=0.72, marker=markers[count],
                       color=V2, edgecolor="white", linewidth=0.4,
                       label=f"{count} 个源（n=20）")
        all_values = [float(r["t_per_source_s"]) for r in qrows]
        upper = math.ceil(max(all_values) / 100) * 100
        ax.plot([0, upper], [0, upper], linestyle="--", color=NEUTRAL, linewidth=1,
                label="等耗时线")
        ax.set(xlim=(0, upper), ylim=(0, upper), xlabel="V1 每源虚拟时间（s）",
               ylabel="V2 每源虚拟时间（s）", title=question.upper())
        ax.set_aspect("equal", adjustable="box")
        ax.grid(color=GRID, linewidth=0.6, alpha=0.7)
        effect = next(r for r in effects if r["question"] == question and r["source_count"] == "all")
        text = (f"平均降低 {float(effect['relative_reduction_pct']):.1f}%\n"
                f"95% CI {float(effect['relative_reduction_ci95_low_pct']):.1f}%–"
                f"{float(effect['relative_reduction_ci95_high_pct']):.1f}%\n"
                f"更快 {effect['wins_v2']}/{effect['n_pairs']}")
        ax.text(0.04, 0.96, text, transform=ax.transAxes, va="top",
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=V2, alpha=0.94))
        ax.legend(loc="lower right", fontsize=7.2)
        _panel(ax, panel)
    fig.suptitle("严格配对案例中的 V1–V2 每源虚拟时间", fontsize=13, fontweight="bold")
    _save(fig, figures / "fig09_paired_performance.jpg")


def _ablation_q3(evidence: Path, figures: Path, data_root: Path) -> None:
    rows = [r for r in _read_csv(evidence / "tables/ablation_summary.csv")
            if r["question"] == "q3" and r["variant_id"] != "q3_full"]
    _write_csv(data_root / "fig10_q3_ablation.csv", rows)
    registry = json.loads((evidence / "variant_registry.json").read_text(encoding="utf-8"))
    labels = {r["variant_id"]: r["label_zh"] for r in registry["variants"]}
    variants = list(dict.fromkeys(r["variant_id"] for r in rows))
    y = np.arange(len(variants)); width = 0.34
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    for offset, count, color in ((-width/2, 10, V2_LIGHT), (width/2, 16, V2)):
        values = [float(next(r for r in rows if r["variant_id"] == v and int(r["source_count"]) == count)["paired_delta_vs_full_pct"])
                  for v in variants]
        values = [0.0 if abs(value) < 0.05 else value for value in values]
        bars = ax.barh(y + offset, values, height=width, color=color,
                       label=f"{count} 个源（20 对）")
        for bar, value in zip(bars, values):
            ax.text(value + (0.45 if value >= 0 else -0.45), bar.get_y()+bar.get_height()/2,
                    f"{value:+.1f}%", ha="left" if value >= 0 else "right", va="center", fontsize=7.5)
    ax.axvline(0, color=NEUTRAL, linewidth=0.9)
    ax.set_yticks(y, [labels[v] for v in variants])
    ax.invert_yaxis(); ax.set_xlabel("相对完整 V2 的每源时间变化（%）")
    ax.set_title("Q3：联合路线贡献占主导", fontweight="bold")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.legend(loc="lower right")
    ax.text(0.01, -0.13, "正值表示关闭该模块后更慢；所有 240 个消融运行均通过 verifier。",
            transform=ax.transAxes, color=NEUTRAL, fontsize=8)
    _save(fig, figures / "fig10_q3_ablation.jpg")


def _ablation_q4(evidence: Path, figures: Path, data_root: Path) -> None:
    rows = [r for r in _read_csv(evidence / "tables/ablation_summary.csv")
            if r["question"] == "q4" and r["variant_id"] != "q4_full"]
    _write_csv(data_root / "fig11_q4_ablation.csv", rows)
    registry = json.loads((evidence / "variant_registry.json").read_text(encoding="utf-8"))
    labels = {r["variant_id"]: r["label_zh"] for r in registry["variants"]}
    variants = list(dict.fromkeys(r["variant_id"] for r in rows))
    y = np.arange(len(variants)); width = 0.34
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 5.2), constrained_layout=True,
                                 gridspec_kw={"width_ratios": [1.35, 1]})
    for offset, count, color in ((-width/2, 10, V2_LIGHT), (width/2, 16, V2)):
        values = []
        for variant in variants:
            row = next(r for r in rows
                       if r["variant_id"] == variant and int(r["source_count"]) == count)
            # Efficiency is meaningful only for runs that pass the complete
            # verifier.  The n=16 no-count-stop negative control passes only
            # 3/20 cases, so plotting its conditional mean as an ordinary bar
            # would reward a method that fails the safety/termination gate.
            if variant == "q4_no_count_stop" and float(row["acceptance_rate"]) < 1.0:
                values.append(np.nan)
            else:
                values.append(float(row["paired_delta_vs_full_pct"]))
        ax.barh(y + offset, values, height=width, color=color, label=f"{count} 个源")
    failed_index = variants.index("q4_no_count_stop")
    ax.text(0.4, y[failed_index] + width/2, "不纳入效率比较\n（仅 3/20 通过）",
            color=NEGATIVE, fontsize=7, va="center", ha="left")
    ax.axvline(0, color=NEUTRAL, linewidth=0.9)
    ax.set_yticks(y, [labels[v] for v in variants]); ax.invert_yaxis()
    ax.set_xlabel("相对完整 V2 的每源时间变化（%）")
    ax.set_title("效率影响", fontweight="bold"); ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.legend(loc="lower right"); _panel(ax, "a")
    x = np.arange(len(variants))
    for offset, count, color in ((-width/2, 10, V2_LIGHT), (width/2, 16, V2)):
        values = [100*float(next(r for r in rows if r["variant_id"] == v and int(r["source_count"]) == count)["acceptance_rate"])
                  for v in variants]
        bars = ax2.bar(x + offset, values, width=width, color=color)
        for bar, value, variant in zip(bars, values, variants):
            if value < 100:
                bar.set_color(NEGATIVE); bar.set_hatch("///")
                ax2.text(bar.get_x()+bar.get_width()/2, value+2, f"{value:.0f}%",
                         ha="center", va="bottom", fontsize=7, color=NEGATIVE)
    ax2.set_xticks(x, [labels[v].replace("无 ", "") for v in variants], rotation=48, ha="right")
    ax2.set_ylim(0, 108); ax2.set_ylabel("完整 verifier 通过率（%）")
    ax2.set_title("安全性门禁", fontweight="bold"); ax2.grid(axis="y", color=GRID, linewidth=0.6)
    _panel(ax2, "b")
    fig.suptitle("Q4：crossbar 决定主要效率，基数停止保证终止证据完整", fontsize=12.5, fontweight="bold")
    _save(fig, figures / "fig11_q4_ablation.jpg")


def _sensitivity(evidence: Path, figures: Path, data_root: Path) -> None:
    summary = _read_csv(evidence / "tables/tuning_summary.csv")
    registry = json.loads((evidence / "variant_registry.json").read_text(encoding="utf-8"))
    rows = []
    for sweep in registry["tuning"]:
        for value in sweep["values"]:
            variant_id = f"{sweep['question']}_{sweep['parameter']}_{str(value).replace('.', 'p')}"
            match = next(r for r in summary if r["variant_id"] == variant_id)
            rows.append({**sweep, "value": value,
                         "mean_t_per_source_s": match["mean_t_per_source_s"],
                         "n": match["n_accepted"]})
    _write_csv(data_root / "fig12_sensitivity.csv", rows)
    display = {
        "probe": "探点距离",
        "share_ratio": "共享阈值",
        "trial_radius": "试探半径",
        "planning_radius": "规划半径",
        "radio_limit": "无线测量上限",
        "crossbar_offset": "crossbar 偏移",
        "crossbar_fraction": "crossbar 分数",
        "initial_rotation_steps": "旋转候选数",
    }
    fig, axes = plt.subplots(3, 3, figsize=(7.2, 6.6), constrained_layout=True)
    chosen = registry["tuning"]
    for ax, sweep, panel in zip(axes.flat, chosen, "abcdefghi"):
        points = [r for r in rows if r["question"] == sweep["question"] and r["parameter"] == sweep["parameter"]]
        x = np.array([float(r["value"]) for r in points]); y = np.array([float(r["mean_t_per_source_s"]) for r in points])
        color = V2 if sweep["question"] == "q3" else ACCENT
        ax.plot(x, y, "o-", color=color, linewidth=1.7, markersize=4)
        locked_index = [float(v) for v in x].index(float(sweep["locked_value"]))
        ax.scatter([x[locked_index]], [y[locked_index]], s=65, facecolors="white",
                   edgecolors=NEGATIVE, linewidth=1.6, zorder=4)
        margin = max(1.0, (max(y)-min(y))*0.8)
        ax.set_ylim(min(y)-margin, max(y)+margin)
        ax.set_title(f"{sweep['question'].upper()} · {display[sweep['parameter']]}")
        ax.set_xlabel("参数值"); ax.set_ylabel("每源时间（s）")
        ax.set_xticks(x)
        ax.tick_params(axis="x", labelsize=7)
        ax.grid(color=GRID, linewidth=0.5); _panel(ax, panel)
    fig.suptitle("锁定参数邻域的事后敏感性（每点 n=10，不用于重新调参）",
                 fontsize=12.2, fontweight="bold")
    _save(fig, figures / "fig12_sensitivity.jpg")


def _breakdown(evidence: Path, figures: Path, data_root: Path) -> None:
    rows = _read_csv(evidence / "tables/run_level.csv")
    components = ["T_move", "T_measure", "T_switch", "T_clear"]
    labels = ["移动", "测量", "换频", "清除"]
    colors = ["#6F7898", "#4C9BC6", "#E0A66A", "#B9B4D8"]
    data = []
    for question in ("q3", "q4"):
        for policy in ("v1_frozen", "v2_final"):
            group = [r for r in rows if r["question"] == question and r["policy"] == policy]
            for comp in components:
                value = np.mean([float(r[comp])/int(r["source_count"]) for r in group])
                data.append({"question": question, "policy": policy, "component": comp,
                             "mean_seconds_per_source": value, "n": len(group)})
    _write_csv(data_root / "fig13_time_breakdown.csv", data)
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    groups = [("q3", "v1_frozen"), ("q3", "v2_final"), ("q4", "v1_frozen"), ("q4", "v2_final")]
    x = np.arange(4); bottoms = np.zeros(4)
    for comp, label, color in zip(components, labels, colors):
        values = np.array([next(r["mean_seconds_per_source"] for r in data if r["question"] == q and r["policy"] == p and r["component"] == comp) for q,p in groups])
        ax.bar(x, values, bottom=bottoms, color=color, width=0.62, label=label)
        bottoms += values
    for i, total in enumerate(bottoms):
        ax.text(i, total+max(bottoms)*0.02, f"{total:.0f}s", ha="center", fontweight="bold")
    ax.set_xticks(x, ["Q3\nV1 基线", "Q3\nV2 最终", "Q4\nV1 基线", "Q4\nV2 最终"])
    ax.set_ylabel("平均每源虚拟时间（s）"); ax.set_title("节时主要来自移动与测量成本同步下降", fontweight="bold")
    ax.set_ylim(0, max(bottoms) * 1.16)
    ax.grid(axis="y", color=GRID, linewidth=0.6); ax.legend(ncol=2, loc="upper left")
    _save(fig, figures / "fig13_time_breakdown.jpg")


def _route(evidence: Path, figures: Path, data_root: Path, question: str, case_id: str, filename: str) -> None:
    run = evidence / "runs" / "v2_final" / question / case_id
    actions = _read_csv(run / "actions.csv")
    points = []
    for row in actions:
        if row.get("x") not in (None, "") and row.get("y") not in (None, ""):
            points.append({**row, "x": float(row["x"]), "y": float(row["y"])})
    _write_csv(data_root / f"{filename[:-4]}.csv", points)
    truth = json.loads((run / "ground_truth.json").read_text(encoding="utf-8"))
    result = json.loads((run / "engine_result.json").read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    domain = Circle((0, 0), 1800, facecolor="#F7F8FA", edgecolor=NEUTRAL, linewidth=1.0)
    ax.add_patch(domain)
    xy = np.array([[p["x"], p["y"]] for p in points])
    ax.plot(xy[:,0], xy[:,1], color="#AAB0BA", linewidth=0.75, zorder=1)
    measure = np.array([[p["x"], p["y"]] for p in points if p["path"] == "/measure"])
    clear = np.array([[p["x"], p["y"]] for p in points if p["path"] == "/clear"])
    if len(measure): ax.scatter(measure[:,0], measure[:,1], s=11, color=V2, alpha=0.62, label="测量位置", zorder=2)
    if len(clear): ax.scatter(clear[:,0], clear[:,1], s=24, marker="x", color=ACCENT, linewidth=1.1, label="清除尝试", zorder=3)
    tx = [float(r["x"]) for r in truth]; ty = [float(r["y"]) for r in truth]
    ax.scatter(tx, ty, s=35, marker="*", color=NEGATIVE, edgecolor="white", linewidth=0.3,
               label="真实干扰源（仅用于离线核验）", zorder=4)
    if question == "q4":
        stations = np.array(result.get("stations") or [])
        if len(stations): ax.scatter(stations[:,0], stations[:,1], s=34, facecolors="none", edgecolors=V1,
                                     linewidth=0.9, label="21 站证书网", zorder=2)
    ax.scatter([0], [0], marker="P", s=45, color="#222222", label="起点", zorder=5)
    ax.set_aspect("equal", adjustable="box"); ax.set_xlim(-2850, 2850); ax.set_ylim(-2850, 2850)
    ax.set_xlabel("x（m）"); ax.set_ylabel("y（m）"); ax.grid(color=GRID, linewidth=0.5)
    if question == "q3":
        title = "Q3 代表案例：搜索站、定位点与清除点共用一条开放路线"
        note = "13 个源，路线用于解释机制；总体效果见图 9"
    else:
        title = "Q4 代表案例：21 站骨干中动态插入局部定位与清除"
        note = "13 个混合源，圆外站点属于连续覆盖证书的一部分"
    ax.set_title(title, fontweight="bold")
    ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, color=NEUTRAL,
            bbox=dict(fc="white", ec="none", alpha=0.85))
    ax.legend(loc="upper right", fontsize=7.2)
    _save(fig, figures / filename)


def generate(evidence: Path) -> dict:
    _configure()
    figures = evidence / "figures"; figures.mkdir(parents=True, exist_ok=True)
    data_root = evidence / "figure_data"; data_root.mkdir(parents=True, exist_ok=True)
    unexpected = [p for p in figures.iterdir() if p.name not in expected_figure_names()]
    if unexpected:
        raise ValueError(f"unexpected pre-existing figure files: {[p.name for p in unexpected]}")
    _v1_baseline(evidence, figures, data_root)
    _framework(evidence, figures, data_root)
    _paired(evidence, figures, data_root)
    _ablation_q3(evidence, figures, data_root)
    _ablation_q4(evidence, figures, data_root)
    _sensitivity(evidence, figures, data_root)
    _breakdown(evidence, figures, data_root)
    _route(evidence, figures, data_root, "q3", "paper_q3_n13_s950020", "fig14_q3_route.jpg")
    _route(evidence, figures, data_root, "q4", "paper_q4_n13_s960020", "fig15_q4_route.jpg")
    manifest = {
        "backend": "Python/matplotlib",
        "format": "JPEG RGB only",
        "figures": [],
    }
    for name in expected_figure_names():
        path = figures / name
        manifest["figures"].append(
            {"name": name, "size_bytes": path.stat().st_size,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    (evidence / "figures_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    generate(args.evidence_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
