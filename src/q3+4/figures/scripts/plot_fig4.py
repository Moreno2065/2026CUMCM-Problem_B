# -*- coding: utf-8 -*-
"""Fig4 — Q4 robust certificate 构造示意（合成几何，双 panel）。

左 panel：31 点三角格点充分扫描集 + 过半平面引理
  （任意以 G∈Ω 为边界点的闭半平面至少含一个格点）。
右 panel：候选点 x 的见证点构造 —— A_δ(x) 为 ‖p−x‖ ≤ R_EFF_MIN−δ=630 m
  内的 no-signal 点，conv(A_δ(x)) ⊇ B(x, δ=370 m)。
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CODE_ROOT, add_args, dump_data, save  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Polygon  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402

from geometry.certificate import q4_lattice_points  # noqa: E402
from geometry.constants import (OMEGA_RADIUS, Q4_DELTA, Q4_LATTICE_SPACING,  # noqa: E402
                                R_EFF_MIN)

R_WITNESS = R_EFF_MIN - Q4_DELTA  # 630 m

NAVY = "#24557A"
BLUE = "#4C8EC9"
TEAL = "#2A9D8F"
CORAL = "#D95D4F"
INK = "#27313A"
MUTED = "#667085"
GRID = "#E8EDF2"


def halfplane_poly(x, normal, lo=-2100, hi=2100, n=121):
    """过 x、法向 normal 的半平面 {p : (p-x)·n >= 0} 的可视化多边形
    （裁到绘图框内的矩形近似）。"""
    nx, ny = normal
    tx, ty = -ny, nx  # 边界方向
    pts = []
    # 边界长线段两端
    for s in (-4000, 4000):
        pts.append((x[0] + s * tx, x[1] + s * ty))
    # 沿法向推出
    for s in (4000, -4000):
        pts.append((x[0] + s * tx + 4000 * nx, x[1] + s * ty + 4000 * ny))
    return pts


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()

    lattice = q4_lattice_points()
    assert len(lattice) == 31

    # 候选点（合成）：Ω 内部偏右下
    x = (700.0, -500.0)
    # 任意定向半平面（法向 35°）
    th = math.radians(35.0)
    normal = (math.cos(th), math.sin(th))
    inside = [p for p in lattice
              if (p[0] - x[0]) * normal[0] + (p[1] - x[1]) * normal[1] >= -1e-9]

    # 见证点：630 m 环上均匀 6 点（合成示意）
    witnesses = [(x[0] + R_WITNESS * math.cos(math.radians(a)),
                  x[1] + R_WITNESS * math.sin(math.radians(a)))
                 for a in (10, 70, 130, 190, 250, 310)]

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 5.0),
                             gridspec_kw={"wspace": 0.20})

    # ---- 左：格点 + 半平面引理 ----
    ax = axes[0]
    ax.add_patch(Circle((0, 0), OMEGA_RADIUS, fill=False, lw=1.6,
                        ec=INK, zorder=3))
    ax.text(0, OMEGA_RADIUS + 90, r"$\Omega$ (r=1800 m)", ha="center",
            fontsize=9, color=MUTED)
    hp = halfplane_poly(x, normal)
    ax.add_patch(Polygon(hp, closed=True, fc=BLUE, alpha=0.12,
                         ec="none", zorder=1))
    # 半平面边界线（过 x）
    tx, ty = -normal[1], normal[0]
    ax.plot([x[0] - 2600 * tx, x[0] + 2600 * tx],
            [x[1] - 2600 * ty, x[1] + 2600 * ty],
            color=BLUE, lw=1.3, ls=(0, (4, 2)), zorder=2)
    in_set = set(map(tuple, inside))
    out = [p for p in lattice if tuple(p) not in in_set]
    ax.scatter([p[0] for p in out], [p[1] for p in out], s=25, c="#98A2B3",
               marker="o", edgecolor="white", linewidth=0.4, zorder=4,
               label="lattice points (31 total)")
    ax.scatter([p[0] for p in inside], [p[1] for p in inside], s=45,
               c=NAVY, marker="o", edgecolor="white", linewidth=0.5,
               zorder=5, label="points in half-plane")
    ax.scatter([x[0]], [x[1]], marker="*", s=210, c=CORAL,
               ec=INK, lw=0.6, zorder=6, label=r"candidate $G$")
    # Point to the half-plane boundary rather than to G.  Keeping this callout
    # in the empty upper-left margin keeps it off the circle and lattice points.
    ax.annotate("Every closed half-plane through $G$\ncontains a lattice point",
                xy=(-1400, 2500), xytext=(-2700, 2680), fontsize=8.5,
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9),
                color=INK,
                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                          ec="none", alpha=0.88))
    ax.set_xlim(-3100, 3100)
    ax.set_ylim(-3100, 3100)
    ax.set_aspect("equal")
    ax.set_xlabel(r"$x$ (m)")
    ax.set_ylabel(r"$y$ (m)")
    ax.set_title("(a) Lattice coverage", loc="left", fontweight="semibold",
                 color=INK, y=1.055, pad=0)
    ax.text(0.0, 1.012, "31-point triangular lattice  ·  spacing 950 m",
            transform=ax.transAxes, fontsize=8, color=MUTED, va="bottom")
    ax.legend(loc="lower right", labelspacing=0.35, handletextpad=0.5)

    # ---- 右：见证点凸包 + 内切盘 ----
    ax = axes[1]
    ax.add_patch(Circle(x, R_WITNESS, fill=False, ls=(0, (4, 2)), lw=1.3,
                        ec=MUTED, zorder=2,
                        label=""))
    hull = Polygon(witnesses, closed=True, fc=TEAL, alpha=0.18,
                   ec=TEAL, lw=1.6, zorder=2)
    ax.add_patch(hull)
    ax.add_patch(Circle(x, Q4_DELTA, fc=CORAL, alpha=0.24,
                        ec=CORAL, lw=1.4, zorder=3))
    ax.scatter([p[0] for p in witnesses], [p[1] for p in witnesses],
               marker="x", s=72, c=INK, lw=1.8, zorder=5,
               label=r"no-signal witnesses $p$")
    ax.scatter([x[0]], [x[1]], marker="*", s=220, c=CORAL,
               ec=INK, lw=0.6, zorder=6, label=r"candidate $x$")
    for p in witnesses:
        ax.plot([x[0], p[0]], [x[1], p[1]], color="#B8C2CC", lw=0.7, zorder=1)
    ax.annotate(r"$B(x,\delta)\subseteq\operatorname{conv}(A_\delta(x))$"
                "\n" r"$\delta=370\ \mathrm{m}$",
                xy=(x[0] + Q4_DELTA * 0.72, x[1] + Q4_DELTA * 0.72),
                xytext=(x[0] + 520, x[1] + 760), fontsize=8.5,
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9),
                color=INK,
                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                          ec="none", alpha=0.88))
    ax.annotate("Witness radius\n" + r"$R_{\mathrm{eff,min}}-\delta=630\ \mathrm{m}$",
                xy=(x[0] - R_WITNESS * 0.71, x[1] - R_WITNESS * 0.71),
                xytext=(x[0] - 1450, x[1] - 1120), fontsize=8.3,
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9),
                color=INK)
    ax.set_xlim(x[0] - 1650, x[0] + 1650)
    ax.set_ylim(x[1] - 1650, x[1] + 1650)
    ax.set_aspect("equal")
    ax.set_xlabel(r"$x$ (m)")
    ax.set_ylabel(r"$y$ (m)")
    ax.set_title("(b) Witness-hull certificate", loc="left",
                 fontweight="semibold", color=INK, y=1.055, pad=0)
    ax.text(0.0, 1.012, "No-signal stops within 630 m of the candidate",
            transform=ax.transAxes, fontsize=8, color=MUTED, va="bottom")
    ax.legend(loc="lower right", labelspacing=0.35, handletextpad=0.5)

    for ax in axes:
        ax.set_facecolor("#FCFDFE")
        ax.grid(color=GRID, linewidth=0.55, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.xaxis.set_major_locator(MultipleLocator(1000 if ax is axes[0] else 500))
        ax.yaxis.set_major_locator(MultipleLocator(1000 if ax is axes[0] else 500))

    fig.suptitle("Robust absence certificate", x=0.07, y=0.985,
                 ha="left", fontsize=12, fontweight="semibold", color=INK)
    fig.text(0.07, 0.944, "Lattice sweep and per-candidate witness hull",
             ha="left", va="top", fontsize=8.2, color=MUTED)
    fig.subplots_adjust(left=0.07, right=0.985, bottom=0.11, top=0.86,
                        wspace=0.20)

    pdf, png = save(fig, args.out, "fig4_q4_robust_certificate")

    data = {
        "figure": "fig4_q4_robust_certificate",
        "kind": "synthetic_schematic",
        "claim_map": ["H.5"],
        "constants": {
            "OMEGA_RADIUS": OMEGA_RADIUS,
            "Q4_LATTICE_SPACING": Q4_LATTICE_SPACING,
            "Q4_DELTA": Q4_DELTA,
            "R_EFF_MIN": R_EFF_MIN,
            "R_WITNESS": R_WITNESS,
        },
        "lattice_points": [list(p) for p in lattice],
        "candidate_point_x": list(x),
        "halfplane_normal_deg": 35.0,
        "n_lattice_in_halfplane": len(inside),
        "witnesses": [list(p) for p in witnesses],
        "note": "Synthetic geometry drawn with geometry.certificate.q4_lattice_points(); "
                "witness ring radius = R_EFF_MIN - Q4_DELTA = 630 m.",
        "outputs": {"pdf": str(pdf), "png": str(png)},
    }
    dump_data(args.out, "fig4_data.json", data)
    print("wrote", pdf, png)


if __name__ == "__main__":
    main()
