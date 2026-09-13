"""Render publication-facing Q2 figures from the frozen representative sidecars.

The evidence JSON remains the numerical source of truth.  This module only changes
presentation: Chinese labels, readable scale choices, and panel layouts suited to
the manuscript's fixed Word figure boxes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm
from matplotlib.patches import FancyBboxPatch, Rectangle


CODE_ROOT = Path(__file__).resolve().parents[1]
SOURCE = CODE_ROOT / "artifacts" / "gate_g_representative"
OUTPUT = CODE_ROOT / "figures" / "paper"

BLUE = "#2468A2"
LIGHT_BLUE = "#BFD7EA"
TEAL = "#3A8D91"
GREEN = "#5AAE61"
LIGHT_GREEN = "#DCEFD9"
RED = "#C44E52"
LIGHT_RED = "#F4D6D4"
GRAY = "#747474"
LIGHT_GRAY = "#E8E8E8"
DARK = "#252525"


def _configure() -> None:
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "DengXian", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "legend.frameon": False,
            "legend.fontsize": 7,
        }
    )


def _load(name: str) -> dict[str, Any]:
    with (SOURCE / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)["data"]


def _save(fig: plt.Figure, stem: str, *, dpi: int = 300) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("svg", "pdf"):
        fig.savefig(OUTPUT / f"{stem}.{suffix}", bbox_inches="tight")
    fig.savefig(OUTPUT / f"{stem}.png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _style_xy(ax: plt.Axes) -> None:
    ax.set_xlabel("x / m")
    ax.set_ylabel("y / m")
    ax.grid(color=LIGHT_GRAY, linewidth=0.55, zorder=0)
    ax.set_aspect("equal", adjustable="box")


def _plot_key_points(ax: plt.Axes, data: dict[str, Any], *, labels: bool) -> None:
    s1 = data["S1"]
    hero = data["geometry"]["hero_S2"]
    mirror = data["geometry"]["mirror_S2"]
    ax.scatter(*s1, marker="^", s=38, color=DARK, zorder=8)
    ax.scatter(*hero, marker="*", s=95, color=BLUE, zorder=8)
    ax.scatter(*mirror, marker="D", s=38, color=TEAL, zorder=8)
    if labels:
        ax.annotate("首次检测点 $S_1$", s1, xytext=(5, 7), textcoords="offset points")
        ax.annotate(r"数值近优点 $\hat S_2$", hero, xytext=(5, -13), textcoords="offset points", color=BLUE)
        ax.annotate("镜像点", mirror, xytext=(5, 5), textcoords="offset points", color=TEAL)


def render_geometry_overview() -> None:
    data = _load("q2_geometry_overview")
    geom = data["geometry"]
    fig, (ax, zoom) = plt.subplots(
        1,
        2,
        figsize=(6.39, 5.0),
        gridspec_kw={"width_ratios": [1.05, 1.0]},
        constrained_layout=True,
    )
    omega = np.asarray(geom["omega_boundary"])
    a1 = np.asarray(geom["a1_fill_polygon"])

    ax.fill(omega[:, 0], omega[:, 1], color="#F7F9FB", zorder=0)
    ax.plot(omega[:, 0], omega[:, 1], color=GRAY, linewidth=1.0)
    ax.fill(a1[:, 0], a1[:, 1], color=LIGHT_RED, alpha=0.9, zorder=3)
    ax.plot(a1[:, 0], a1[:, 1], color=RED, linewidth=1.1, zorder=4)
    _plot_key_points(ax, data, labels=True)
    ax.set_xlim(-1950, 1950)
    ax.set_ylim(-1950, 1950)
    ax.text(-1750, 1680, r"目标圆域 $\Omega$", color=GRAY)
    ax.set_title("(a) 全局位置关系", loc="left", fontweight="bold")
    _style_xy(ax)

    zoom.fill(a1[:, 0], a1[:, 1], color=LIGHT_RED, alpha=0.95)
    zoom.plot(a1[:, 0], a1[:, 1], color=RED, linewidth=1.3)
    for curve in geom["a1_boundary"]:
        pts = np.asarray(curve["points"])
        if len(pts):
            zoom.plot(pts[:, 0], pts[:, 1], color=RED if "wedge" in curve["label"] else TEAL, linewidth=1.0)
    zoom.scatter(*data["S1"], marker="^", s=38, color=DARK, zorder=8)
    zoom.axhline(0, color=GRAY, linewidth=0.7, linestyle="--")
    zoom.set_xlim(-30, 1600)
    zoom.set_ylim(-42, 42)
    zoom.set_title("(b) $A_1$ 局部放大", loc="left", fontweight="bold")
    zoom.text(470, 21, "目标可行集 $A_1$", color=RED, ha="center")
    zoom.annotate("$S_1$", data["S1"], xytext=(5, -15), textcoords="offset points", color=DARK)
    zoom.set_xlabel("x / m")
    zoom.set_ylabel("y / m")
    zoom.grid(color=LIGHT_GRAY, linewidth=0.55, zorder=0)
    zoom.set_aspect("auto")
    _save(fig, "q2_geometry_overview")


def _circular_segments(center: float, half_width: float) -> list[tuple[float, float]]:
    lo = center - half_width
    hi = center + half_width
    if lo < 0:
        return [(0.0, hi), (360.0 + lo, 360.0)]
    if hi > 360:
        return [(lo, 360.0), (0.0, hi - 360.0)]
    return [(lo, hi)]


def render_angular_image() -> None:
    data = _load("q2_angular_image")
    raw = data["geometry"]["raw_intervals_deg"]
    expanded = data["expanded_intervals_deg"]
    theta = data["theta1_deg"] % 360
    beta = data["geometry"]["worst_beta_deg"]
    fig, ax = plt.subplots(figsize=(6.39, 5.0), constrained_layout=True)
    for i, (lo, hi) in enumerate(raw):
        ax.plot([lo, hi], [i, i], color=LIGHT_BLUE, linewidth=11, solid_capstyle="butt", zorder=2)
    for i, (lo, hi) in enumerate(expanded):
        ax.plot([lo, hi], [i, i], color=BLUE, linewidth=4.5, solid_capstyle="butt", zorder=3)
    for lo, hi in _circular_segments(theta, 3.0):
        ax.axvspan(lo, hi, color=LIGHT_RED, alpha=0.95, zorder=0)
    ax.axvline(0, color=DARK, linewidth=1.1)
    ax.axvline(360, color=DARK, linewidth=1.1)
    ax.axvline(beta, color=RED, linestyle="--", linewidth=1.2)
    ax.text(beta + 7, 0.43, r"临界读数 $\beta^*=38.6676^\circ$", color=RED, ha="left")
    ax.text(6, 0.38, r"禁区 $\pm3\varepsilon$", color=RED, ha="left")
    ax.text(358, 0.38, r"禁区", color=RED, ha="right")
    ax.text(np.mean(raw[0]), -0.27, "原始方位集合", color="#6C86A0", ha="center")
    ax.text(np.mean(expanded[0]), 0.18, "误差扩张后的读数集合", color=BLUE, ha="center")
    ax.set_xlim(0, 360)
    ax.set_ylim(-0.55, 0.65)
    ax.set_yticks([0], ["分支 1"])
    ax.set_xlabel("示向度 / °")
    ax.set_ylabel("闭区间分支")
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.6)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    _save(fig, "q2_angular_image")


def render_crec() -> None:
    data = _load("q2_crec")
    surface = data["surface"]
    inside = np.asarray([x["S2"] for x in surface if x["in_crec"]])
    outside = np.asarray([x["S2"] for x in surface if not x["in_crec"]])
    fig, ax = plt.subplots(figsize=(6.39, 5.0), constrained_layout=True)
    ax.scatter(outside[:, 0], outside[:, 1], s=5, color=LIGHT_GRAY, label="不可保证接收", rasterized=True)
    ax.scatter(inside[:, 0], inside[:, 1], s=7, color="#9DCEA3", label="鲁棒可检测", rasterized=True)
    _plot_key_points(ax, data, labels=False)
    ax.annotate("数值近优点", data["geometry"]["hero_S2"], xytext=(5, -13), textcoords="offset points", color=BLUE)
    ax.set_xlim(data["bounds"][0] - 70, data["bounds"][1] + 70)
    ax.set_ylim(data["bounds"][2] - 50, data["bounds"][3] + 50)
    ax.legend(loc="upper right")
    _style_xy(ax)
    _save(fig, "q2_crec")


def render_q_surface() -> None:
    data = _load("q2_q_surface")
    finite = [x for x in data["surface"] if isinstance(x["Q"], (int, float))]
    x = np.asarray([v["S2"][0] for v in finite])
    y = np.asarray([v["S2"][1] for v in finite])
    q = np.asarray([v["Q"] for v in finite])
    fig, ax = plt.subplots(figsize=(6.39, 5.0), constrained_layout=True)
    scatter = ax.scatter(x, y, c=q, s=11, cmap="Blues_r", norm=LogNorm(vmin=q.min(), vmax=q.max()), rasterized=True)
    hero = data["geometry"]["hero_S2"]
    mirror = data["geometry"]["mirror_S2"]
    ax.scatter([hero[0], mirror[0]], [hero[1], mirror[1]], marker="*", s=95, color=RED, edgecolor="white", linewidth=0.5, zorder=5)
    ax.annotate("较优区域", hero, xytext=(-8, -16), textcoords="offset points", color=RED, ha="right")
    cbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.03)
    cbar.set_label("最坏交会直径 $Q(S_2)$ / m")
    ax.set_xlim(data["bounds"][0] - 70, data["bounds"][1] + 70)
    ax.set_ylim(data["bounds"][2] - 50, data["bounds"][3] + 50)
    _style_xy(ax)
    _save(fig, "q2_q_surface")


def render_candidate_region() -> None:
    data = _load("q2_optimum_and_candidate_region")
    cells = data["candidate_region_cells"]["0.05"]
    fig, ax = plt.subplots(figsize=(6.39, 5.0), constrained_layout=True)
    hero = data["geometry"]["hero_S2"]
    for cell in cells:
        if cell["y_max"] >= 0:
            continue
        ax.add_patch(
            Rectangle(
                (cell["x_min"], cell["y_min"]),
                cell["x_max"] - cell["x_min"],
                cell["y_max"] - cell["y_min"],
                facecolor=LIGHT_GREEN,
                edgecolor=GREEN,
                linewidth=0.3,
            )
        )
    ax.scatter(*hero, marker="*", s=110, color=BLUE, zorder=6)
    ax.annotate("数值近优点", hero, xytext=(7, -14), textcoords="offset points", color=BLUE)
    ax.text(0.03, 0.96, r"绿色单元：$Q(S_2)\leq1.05\hat Q$", transform=ax.transAxes, va="top", color=GREEN)
    ax.text(0.03, 0.89, "上侧分支由关于首次示向轴的镜像对称得到", transform=ax.transAxes, va="top", color=GRAY)
    ax.set_xlim(715, 890)
    ax.set_ylim(-710, -455)
    _style_xy(ax)
    _save(fig, "q2_optimum_and_candidate_region")


def _flow_box(ax: plt.Axes, x: float, y: float, title: str, body: str, color: str) -> None:
    box = FancyBboxPatch(
        (x, y),
        0.27,
        0.24,
        boxstyle="round,pad=0.015,rounding_size=0.02",
        linewidth=1.0,
        edgecolor=color,
        facecolor="white",
    )
    ax.add_patch(box)
    ax.text(x + 0.018, y + 0.18, title, color=color, fontweight="bold", fontsize=9, va="center")
    ax.text(x + 0.018, y + 0.09, body, color=DARK, fontsize=7.2, va="center", linespacing=1.35)


def render_flowchart() -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5.0), constrained_layout=True)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.03, 0.63, "1  首次观测", "输入 $S_1,\\hat\\theta_1,\\varepsilon$\n采用确定性误差边界", BLUE),
        (0.365, 0.63, "2  目标可行集", "构造 $A_1$\n消去未知接收半径", TEAL),
        (0.70, 0.63, "3  鲁棒可检测域", "构造 $C_{\\rm rec}$\n保证第二次继续接收", GREEN),
        (0.70, 0.22, "4  可接受行动域", "构造 $C_{\\rm adm}$\n执行 $3\\varepsilon$ 安全门", RED),
        (0.365, 0.22, "5  最坏情形评价", "计算 $Q(S_2)=\\max_\\beta D_{\\rm Q1}$\n含 near 分支", "#8B6BB1"),
        (0.03, 0.22, "6  选点与候选域", "求数值近优点 $\\hat S_2$\n构造 $C_{\\rm good}(\\eta)$", BLUE),
    ]
    for args in boxes:
        _flow_box(ax, *args)
    arrow = dict(arrowstyle="-|>", color=GRAY, lw=1.3, shrinkA=5, shrinkB=5)
    ax.annotate("", (0.365, 0.75), (0.30, 0.75), arrowprops=arrow)
    ax.annotate("", (0.70, 0.75), (0.635, 0.75), arrowprops=arrow)
    ax.annotate("", (0.835, 0.46), (0.835, 0.63), arrowprops=arrow)
    ax.annotate("", (0.635, 0.34), (0.70, 0.34), arrowprops=arrow)
    ax.annotate("", (0.30, 0.34), (0.365, 0.34), arrowprops=arrow)
    ax.text(0.5, 0.04, "有界误差观测  →  可靠可检测  →  有界交会  →  最坏直径最小化", ha="center", color=GRAY, fontsize=8)
    _save(fig, "q2_flowchart")


def render_worst_case_intersection() -> None:
    data = _load("q2_worst_case_intersection")
    polygon = np.asarray(data["worst_polygon"])
    witness = np.asarray(data["geometry"]["diameter_witness_pair"])
    hero = np.asarray(data["geometry"]["hero_S2"])
    s1 = np.asarray(data["S1"])
    fig, (loc, zoom) = plt.subplots(
        1,
        2,
        figsize=(6.39, 5.0),
        gridspec_kw={"width_ratios": [0.78, 1.35]},
        constrained_layout=True,
    )
    loc.scatter(*s1, marker="^", s=38, color=DARK)
    loc.scatter(*hero, marker="*", s=90, color=BLUE)
    loc.scatter(polygon[:, 0], polygon[:, 1], s=14, color=RED)
    loc.plot([s1[0], polygon.mean(axis=0)[0]], [s1[1], polygon.mean(axis=0)[1]], color=GRAY, linewidth=0.7, linestyle="--")
    loc.plot([hero[0], polygon.mean(axis=0)[0]], [hero[1], polygon.mean(axis=0)[1]], color=GRAY, linewidth=0.7, linestyle="--")
    loc.annotate("$S_1$", s1, xytext=(4, 5), textcoords="offset points")
    loc.annotate(r"$\hat S_2$", hero, xytext=(4, -12), textcoords="offset points", color=BLUE)
    loc.annotate("交会区域", polygon.mean(axis=0), xytext=(-8, 7), textcoords="offset points", color=RED, ha="right")
    loc.set_xlim(-100, 1750)
    loc.set_ylim(-760, 180)
    loc.set_title("(a) 空间位置", loc="left", fontweight="bold")
    _style_xy(loc)

    closed = np.vstack([polygon, polygon[0]])
    zoom.fill(closed[:, 0], closed[:, 1], color=LIGHT_BLUE, alpha=0.9)
    zoom.plot(closed[:, 0], closed[:, 1], color=BLUE, linewidth=1.2)
    zoom.plot(witness[:, 0], witness[:, 1], color=RED, linewidth=2.0, marker="o", markersize=4)
    midpoint = witness.mean(axis=0)
    diameter = np.linalg.norm(witness[1] - witness[0])
    zoom.annotate(f"直径见证\n{diameter:.4f} m", midpoint, xytext=(8, 12), textcoords="offset points", color=RED)
    pad_x = 0.10 * (polygon[:, 0].max() - polygon[:, 0].min())
    pad_y = 0.16 * (polygon[:, 1].max() - polygon[:, 1].min())
    zoom.set_xlim(polygon[:, 0].min() - pad_x, polygon[:, 0].max() + pad_x)
    zoom.set_ylim(polygon[:, 1].min() - pad_y, polygon[:, 1].max() + pad_y)
    zoom.set_title("(b) 交会区域局部放大", loc="left", fontweight="bold")
    _style_xy(zoom)
    _save(fig, "q2_worst_case_intersection")


def render_baseline_comparison() -> None:
    data = _load("q2_baseline_comparison")
    rows = data["rows"]
    fig, (diam, feasible) = plt.subplots(
        1,
        2,
        figsize=(7.2, 3.45),
        gridspec_kw={"width_ratios": [1.18, 1.0]},
        constrained_layout=True,
    )
    method_names = ["可行参考点", "正交简化点 1", "正交简化点 2", "本文 minimax 点"]
    y = np.arange(len(rows))
    finite_rows = [(i, row) for i, row in enumerate(rows)
                   if isinstance(row["Q"], (int, float))]
    for i, row in finite_rows:
        color = BLUE if row["method"] == "Hero" else GRAY
        diam.hlines(i, 100, row["Q"], color=color, linewidth=2.4, zorder=2)
        diam.scatter(row["Q"], i, color=color, s=58, zorder=3,
                     edgecolor="white", linewidth=0.7)
        diam.annotate(f'{row["Q"]:.2f} m', (row["Q"], i),
                      xytext=(6, 0), textcoords="offset points", va="center",
                      color=DARK, fontsize=7.5)
    for i, row in enumerate(rows):
        if not isinstance(row["Q"], (int, float)):
            diam.axhspan(i - 0.42, i + 0.42, color=LIGHT_RED, alpha=0.45,
                         zorder=0)
            diam.text(112, i, "不满足约束", ha="left", va="center",
                      color=RED, fontsize=7.5, fontweight="bold")
    diam.set_xscale("log")
    diam.set_xlim(90, 7000)
    diam.set_ylim(len(rows) - 0.5, -0.5)
    diam.set_yticks(y, method_names)
    diam.set_xlabel("最坏定位直径 $Q$ / m（对数尺度）")
    diam.set_title("(a) 定位质量", loc="left", fontweight="bold", pad=9)
    diam.grid(axis="x", which="both", color=LIGHT_GRAY, linewidth=0.6)
    diam.tick_params(axis="y", length=0)
    reduction = rows[0]["Q"] / rows[3]["Q"]
    diam.text(0.98, 0.03, f"本文方法将 $Q$ 缩小 {reduction:.1f} 倍",
              transform=diam.transAxes, ha="right", va="bottom",
              color=BLUE, fontsize=7.5, fontweight="bold")

    matrix = np.asarray([[r["Crec_feasible"], r["admissible"]] for r in rows], dtype=int)
    feasible.imshow(matrix, cmap=mpl.colors.ListedColormap([LIGHT_RED, LIGHT_GREEN]), vmin=0, vmax=1, aspect="auto")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            feasible.text(j, i, "通过" if matrix[i, j] else "未通过",
                          ha="center", va="center", fontsize=8.5,
                          color=GREEN if matrix[i, j] else RED,
                          fontweight="bold")
    feasible.set_xticks([0, 1], ["鲁棒可检测", "可接受"])
    feasible.set_yticks(range(4), method_names)
    feasible.set_title("(b) 约束可行性", loc="left", fontweight="bold", pad=9)
    feasible.tick_params(length=0)
    for spine in feasible.spines.values():
        spine.set_visible(False)
    feasible.set_xticks(np.arange(-0.5, 2, 1), minor=True)
    feasible.set_yticks(np.arange(-0.5, 4, 1), minor=True)
    feasible.grid(which="minor", color="white", linewidth=1.5)
    _save(fig, "q2_baseline_comparison")


def main() -> None:
    _configure()
    render_geometry_overview()
    render_angular_image()
    render_crec()
    render_q_surface()
    render_candidate_region()
    render_flowchart()
    render_worst_case_intersection()
    render_baseline_comparison()


if __name__ == "__main__":
    main()
