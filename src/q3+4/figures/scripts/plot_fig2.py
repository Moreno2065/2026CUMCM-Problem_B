# -*- coding: utf-8 -*-
"""Fig2 bounded-bearing geometry（Addendum F.2）。

从 results/figure_runs/q3_a1（A1 基线局：观测点垂直楔形轴偏移，交会清晰） 的真实证据取一个频道：
- bearing wedge（±1°）多次交会（observations.csv 的 direction 观测）；
- 可行域收缩快照叠加（localization_history 的 vertices，首/中/末）；
- 最终 MEC 圆；guaranteed clear region Z_c = ∩B(v,20)（画保守内接圆
  B(c_mec, 20 − r_mec)，Z_c 必包含它——由 MEC 定义可证）。

重建：python figures/scripts/plot_fig2.py [--run figure_runs/q3_a1 --channel 12]
"""

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (add_args, dump_data, read_jsonl, save,  # noqa: E402
                     plt, CODE_ROOT)                          # noqa: E402

from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Patch, Polygon  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402

sys.path.insert(0, str(CODE_ROOT))
from geometry import constants as C  # noqa: E402

RUN = "figure_runs/q3_a1"

NAVY = "#24557A"
BLUE = "#4C8EC9"
PALE_BLUE = "#DCEAF5"
TEAL = "#2A9D8F"
AMBER = "#E9A23B"
CORAL = "#D95D4F"
PALE_GREEN = "#DDF1E8"
INK = "#27313A"
MUTED = "#667085"
GRID = "#E8EDF2"


def wedge_poly(S, bearing_deg, half=C.BEARING_ERROR_DEG,
               r=C.R_EFF_MAX, n=24):
    """楔形 ∩ B(S,r) 的多边形近似（仅作图）。"""
    a0 = math.radians(bearing_deg - half)
    a1 = math.radians(bearing_deg + half)
    pts = [S]
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        pts.append((S[0] + r * math.cos(a), S[1] + r * math.sin(a)))
    return pts


def main():
    p = add_args(argparse.ArgumentParser())
    p.add_argument("--run", default=RUN)
    p.add_argument("--channel", type=int, default=12)
    args = p.parse_args()
    run = Path(args.results) / args.run

    # 该频道的 direction 观测
    dirs = []
    with open(run / "observations.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["channel"]) == args.channel \
                    and row["result"] == "direction":
                dirs.append((float(row["x"]), float(row["y"]),
                             float(row["bearing_deg"]),
                             float(row["virtual_time"])))
    hist = read_jsonl(run / "localization_history"
                      / ("channel_%02d.jsonl" % args.channel))
    assert dirs and hist, "no evidence for channel %d" % args.channel

    fig, (overview, zoom) = plt.subplots(
        1, 2, figsize=(10.8, 5.25),
        gridspec_kw={"width_ratios": [0.92, 1.35], "wspace": 0.18},
    )

    # 楔形（前 3 次交会）
    wedge_cols = ["#DCEAF5", "#BED8EE", "#93BFE2"]
    for i, (x, y, b, vt) in enumerate(dirs[:3]):
        overview.add_patch(Polygon(wedge_poly((x, y), b), closed=True,
                                   facecolor=wedge_cols[i], edgecolor=BLUE,
                                   alpha=0.25, linewidth=0.75, zorder=1))
        overview.plot([x], [y], marker="o", color=NAVY, markersize=5.3,
                      markeredgecolor="white", markeredgewidth=0.6,
                      zorder=4)
        offsets = [(7, 5), (7, -16), (7, 7)]
        overview.annotate(r"$S_%d$  ($t=%.0f$ s)" % (i + 1, vt), (x, y),
                          textcoords="offset points", xytext=offsets[i],
                          fontsize=7.5, color=NAVY,
                          bbox=dict(boxstyle="round,pad=0.14", fc="white",
                                    ec="none", alpha=0.82))

    # 可行域快照：首 / 中 / 末
    snaps = sorted({0, len(hist) // 2, len(hist) - 1})
    snap_cols = {0: (CORAL, "after first bearing"),
                 len(hist) // 2: (AMBER, "intermediate"),
                 len(hist) - 1: (TEAL, "final")}
    for k in snaps:
        e = hist[k]
        overview.add_patch(Polygon(e["vertices"], closed=True, fill=False,
                                   edgecolor=snap_cols[k][0], linewidth=1.45,
                                   zorder=3))

        # The detail panel deliberately crops the kilometre-scale first set.
        # This makes the final tens-of-metres certificate readable.
        zoom.add_patch(Polygon(
            e["vertices"], closed=True,
            facecolor=PALE_GREEN if k == len(hist) - 1 else "none",
            edgecolor=snap_cols[k][0],
            alpha=0.72 if k == len(hist) - 1 else 1.0,
            linewidth=2.0 if k == len(hist) - 1 else 1.35,
            zorder=3 if k == len(hist) - 1 else 2,
        ))

    # 最终 MEC 与保证清除区
    last = hist[-1]
    cx, cy = last["mec_center"]
    r = last["mec_radius"]
    zoom.add_patch(Circle((cx, cy), r, fill=False, edgecolor=NAVY,
                          linestyle=(0, (4, 2)), linewidth=1.7, zorder=4))
    r_clear = max(0.0, C.CLEAR_RADIUS - r)
    zoom.add_patch(Circle((cx, cy), r_clear, facecolor="#B9E3D5",
                          edgecolor=TEAL, alpha=0.95, linewidth=1.25,
                          zorder=5))
    cp = last["guaranteed_clear_region"]["clear_point"] or [cx, cy]
    zoom.plot([cp[0]], [cp[1]], marker="*", color=CORAL, markersize=14,
              markeredgecolor=INK, markeredgewidth=0.6, zorder=7)

    # 总览面板：仅用于交代三个观测点的空间关系。
    xs = [v[0] for v in hist[0]["vertices"]] + [d[0] for d in dirs[:3]]
    ys = [v[1] for v in hist[0]["vertices"]] + [d[1] for d in dirs[:3]]
    pad = 250.0
    overview.set_xlim(min(xs) - pad, max(xs) + pad)
    overview.set_ylim(min(ys) - pad, max(ys) + pad)
    overview.add_patch(Circle((cx, cy), 85, fill=False, edgecolor=NAVY,
                              linestyle=(0, (3, 2)), linewidth=1.2,
                              zorder=6))
    overview.annotate("final region\nshown at right", xy=(cx + 55, cy - 55),
                      xytext=(620, 900), fontsize=7.3, color=NAVY,
                      arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.8))

    # 主面板：放大最终证书，同时保留第二次交会边界作为尺度参照。
    zoom.set_xlim(798, 858)
    zoom.set_ylim(1124, 1184)
    zoom.plot([dirs[2][0]], [dirs[2][1]], marker="o", color=NAVY,
              markersize=5.3, markeredgecolor="white", markeredgewidth=0.6,
              zorder=6)
    zoom.annotate(r"$S_3$", (dirs[2][0], dirs[2][1]),
                  xytext=(-13, 8), textcoords="offset points",
                  color=NAVY, fontsize=8)
    zoom.annotate(r"final feasible set", (834.2, 1140.2),
                  xytext=(14, 25), textcoords="offset points", color=TEAL,
                  fontsize=8, fontweight="bold",
                  arrowprops=dict(arrowstyle="->", color=TEAL, lw=0.9))
    zoom.annotate(r"MEC  $r=13.8$ m", (cx + r, cy),
                  xytext=(12, -18), textcoords="offset points", color=NAVY,
                  fontsize=8,
                  arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.8))

    for axis in (overview, zoom):
        axis.set_aspect("equal", adjustable="box")
        axis.set_facecolor("#FCFDFE")
        axis.grid(color=GRID, linewidth=0.6, zorder=0)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.set_xlabel(r"$x$ (m)")
        axis.set_ylabel(r"$y$ (m)")

    overview.xaxis.set_major_locator(MultipleLocator(400))
    overview.yaxis.set_major_locator(MultipleLocator(400))
    zoom.xaxis.set_major_locator(MultipleLocator(10))
    zoom.yaxis.set_major_locator(MultipleLocator(10))

    overview.set_title("(a) Observation geometry", loc="left",
                       fontweight="semibold", color=INK, y=1.055, pad=0)
    overview.text(0.0, 1.012, "Three bearings over the full trajectory",
                  transform=overview.transAxes, fontsize=7.8,
                  color=MUTED, va="bottom")
    zoom.set_title("(b) Final localization certificate", loc="left",
                   fontweight="semibold", color=INK, y=1.055, pad=0)
    radii = [hist[k]["mec_radius"] for k in snaps]
    zoom.text(0.0, 1.012,
              "MEC radius: " + "  →  ".join(f"{value:.1f} m" for value in radii),
              transform=zoom.transAxes, fontsize=7.8, color=TEAL,
              fontweight="bold", va="bottom")

    handles = [
        Patch(facecolor="none", edgecolor=CORAL, linewidth=1.5,
              label="first feasible set"),
        Patch(facecolor="none", edgecolor=AMBER, linewidth=1.5,
              label="second feasible set"),
        Patch(facecolor=PALE_GREEN, edgecolor=TEAL, linewidth=1.7,
              label="final feasible set"),
        Line2D([], [], color=NAVY, linestyle=(0, (4, 2)), linewidth=1.7,
               label="minimum enclosing circle"),
        Patch(facecolor="#B9E3D5", edgecolor=TEAL,
              label=r"guaranteed-clear disk $B(c,20-r)$"),
        Line2D([], [], marker="*", color="none", markerfacecolor=CORAL,
               markeredgecolor=INK, markersize=10, label="certified clear point"),
    ]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.52, 0.02),
               ncol=3, frameon=False, fontsize=7.4, columnspacing=1.5,
               handlelength=2.2, handletextpad=0.55)

    fig.suptitle("Successive bearing intersections", x=0.065, y=0.985,
                 ha="left", fontsize=12, fontweight="semibold", color=INK)
    fig.text(0.065, 0.944,
             r"Channel %d  ·  $\pm1^\circ$ bounded bearings  ·  "
             "kilometre-scale ambiguity contracts to a 13.8 m MEC" % args.channel,
             ha="left", va="top", fontsize=8.2, color=MUTED)
    fig.subplots_adjust(left=0.065, right=0.985, bottom=0.19, top=0.84,
                        wspace=0.18)

    data = {
        "figure": "fig2_bounded_bearing_geometry",
        "claim": "H.5 / method geometry (Addendum F.2)",
        "run": args.run, "channel": args.channel,
        "direction_observations": [
            {"x": x, "y": y, "bearing_deg": b, "virtual_time": vt}
            for x, y, b, vt in dirs],
        "snapshots": [{"observation_count": hist[k]["observation_count"],
                       "mec_radius": hist[k]["mec_radius"],
                       "vertices": hist[k]["vertices"]} for k in snaps],
        "final_mec": {"center": [cx, cy], "radius": r},
        "guaranteed_clear_inner_disk_radius": r_clear,
    }
    dump_data(args.out, "fig2_data.json", data)
    pdf, png = save(fig, args.out, "fig2_bounded_bearing_geometry")
    print("fig2 ->", pdf, png)


if __name__ == "__main__":
    main()
