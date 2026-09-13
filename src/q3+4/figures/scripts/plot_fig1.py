# -*- coding: utf-8 -*-
"""Fig1 方法闭环图（Addendum F.1，示意图）。

Claim：观测、定位、证书、决策和清除形成闭环。
- Clear / Localization 是主任务；
- UNKNOWN batch scan 是停点伴随机制；
- Certificate residual mode 是收尾补差，不是独立主发现通道。

示意图用 matplotlib patches 绘制；锚定真实运行数据（figure_runs 两局
metrics）写入 fig1_data.json。

重建：python figures/scripts/plot_fig1.py [--results code/results]
      [--out code/figures]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (add_args, dump_data, load_json, save,  # noqa: E402
                     plt)                                    # noqa: E402

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

BOX = dict(boxstyle="round,pad=0.45", linewidth=1.4)


def _box(ax, xy, text, fc, w=2.5, h=0.95, fs=10, ec="#333333"):
    x, y = xy
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                facecolor=fc, edgecolor=ec, **BOX))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs)


def _arrow(ax, p1, p2, label=None, color="#333333", style="-|>",
           rad=0.0, lw=1.4, ls="-", label_off=(0, 0.18)):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, color=color,
                                 mutation_scale=14, linewidth=lw,
                                 linestyle=ls,
                                 connectionstyle="arc3,rad=%f" % rad))
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + label_off[0], \
                 (p1[1] + p2[1]) / 2 + label_off[1]
        ax.text(mx, my, label, fontsize=8.5, color=color,
                ha="center", va="center")


def main():
    args = add_args(argparse.ArgumentParser()).parse_args()
    results = Path(args.results)

    # 锚定真实数据：两局 figure run 的指标摘要
    anchor = {}
    for name in ("q3_main", "q4_main"):
        mp = results / "figure_runs" / name / "metrics.json"
        if mp.is_file():
            m = load_json(mp)
            anchor[name] = {
                "T_total_virtual": m["T_total_virtual"],
                "cleared": m["cleared_count"],
                "certified_absent": m["certified_absent_count"],
                "n_measures": m["n_measures"],
            }

    fig, ax = plt.subplots(figsize=(10.5, 6.4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8.6)
    ax.axis("off")

    c_main = "#dbeafe"     # 主任务
    c_state = "#dcfce7"    # 状态
    c_cert = "#fef9c3"     # 证书
    c_aux = "#f3e8ff"      # 伴随机制

    # 闭环主环
    _box(ax, (2.2, 6.6), "Observe\n/measure at stop\n(+/-1 deg bearing)", c_main)
    _box(ax, (7.0, 6.6), "Set-valued update  K_t\nwedge ∩ / exclusion disk /\nwitness pool", c_state, w=3.4)
    _box(ax, (11.8, 6.6), "Decide\nlexicographic:\nFALLBACK>READY>ACTIVE>CERT",
         c_main, w=3.2)
    _box(ax, (11.8, 2.2), "Clear\n/clear (dist ≤ 20 m)", c_main)
    _box(ax, (7.0, 2.2), "Localization (ACTIVE→READY)\nR_MEC ≤ 20 m ⇒ Z_c = ∩B(v,20)",
         c_state, w=3.6)
    _box(ax, (2.2, 2.2), "Certificate (UNKNOWN→CERT_ABSENT)\nQ3: Ω ⊆ ∪B(S,1000)\nQ4: δ-robust hull / 31-pt lattice",
         c_cert, w=4.2, h=1.35)

    _arrow(ax, (3.5, 6.6), (5.3, 6.6), "bearing / no_signal / near")
    _arrow(ax, (8.7, 6.6), (10.2, 6.6), "READY / ACTIVE / UNKNOWN")
    _arrow(ax, (11.8, 6.1), (11.8, 2.7), "READY: go clear", rad=0.0)
    _arrow(ax, (10.5, 2.2), (8.8, 2.2), "cleared")
    _arrow(ax, (5.2, 2.2), (4.3, 2.2), None)
    _arrow(ax, (2.2, 2.9), (2.2, 6.1), "next stop", rad=0.0)
    _arrow(ax, (7.0, 6.1), (7.0, 2.75), "ACTIVE: NBV pick", rad=0.0,
           label_off=(1.9, 0))
    _arrow(ax, (7.0, 1.7), (7.0, 0.9), None, label_off=(0, 0))
    _arrow(ax, (2.2, 1.5), (2.2, 0.9), None)

    ax.text(4.6, 0.55, "loop closes: next observation stop",
            fontsize=8.5, color="#555555")

    # 伴随机制（非主发现通道）
    _box(ax, (2.2, 4.4), "UNKNOWN batch scan\n(at every stop, piggyback)",
         c_aux, w=3.0, h=0.85, fs=9, ec="#7c3aed")
    _arrow(ax, (2.2, 5.6), (2.2, 4.85), None, color="#7c3aed", ls="--")
    _arrow(ax, (3.7, 4.4), (5.6, 6.2), None, color="#7c3aed", ls="--",
           rad=-0.25)
    ax.text(3.4, 5.2, "feeds K_t", fontsize=8, color="#7c3aed")

    # 收尾补差语义
    _arrow(ax, (4.3, 2.75), (4.3, 4.1), None, color="#b45309", ls=":",
           rad=0.0)
    ax.text(4.6, 3.4, "residual mode:\nmop-up only, not a\ndiscovery channel",
            fontsize=8, color="#b45309")

    ax.set_title("Fig1  Closed loop: observe → update → localize/certify → "
                 "decide → clear\n(main task: Clear/Localization; batch scan "
                 "= piggyback; certificate residual = mop-up)",
                 fontsize=11)

    data = {
        "figure": "fig1_method_loop",
        "claim": "H-section loop semantics (Addendum F.1); supports H.1-H.5 "
                 "method overview",
        "nodes": ["observe", "set_update", "decide", "clear",
                  "localization", "certificate", "unknown_batch_scan"],
        "semantics": {"main_task": "Clear/Localization",
                      "batch_scan": "piggyback at stops",
                      "certificate_residual": "mop-up, not discovery"},
        "anchor_runs": anchor,
    }
    dump_data(args.out, "fig1_data.json", data)
    pdf, png = save(fig, args.out, "fig1_method_loop")
    print("fig1 ->", pdf, png)


if __name__ == "__main__":
    main()
