# -*- coding: utf-8 -*-
"""Fig3 Q3 certificate accumulation（Addendum F.3）。

数据：results/figure_runs/q3_main 的 certificate.json（某 CERTIFIED_ABSENT
频道的 no_signal 停点全集）。左图：前半数停点时刻——排除盘未覆盖 Ω，
残留缺口可见；右图：全部停点——Ω ⊆ ∪B(S,1000)，证书闭合。
排除盘半径取 R_EFF_MIN=1000（题设下界，保守）。

重建：python figures/scripts/plot_fig3.py [--channel auto]
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (add_args, dump_data, load_json, save,  # noqa: E402
                     plt, CODE_ROOT)                          # noqa: E402

from matplotlib.patches import Circle  # noqa: E402

sys.path.insert(0, str(CODE_ROOT))
from geometry import constants as C  # noqa: E402
from geometry.certificate import q3_backbone_points, q3_certified  # noqa: E402

RUN = "figure_runs/q3_main"


def _pick_channel(cert):
    """选一个停点数适中的 CERTIFIED_ABSENT 频道。"""
    best, best_k = None, 1e9
    for cid, e in cert.items():
        if e["status"] == "CERTIFIED_ABSENT" and e["no_signal_points"]:
            k = len(e["no_signal_points"])
            if 3 <= k < best_k:
                best, best_k = cid, k
    if best is None:  # 兜底：任意有停点的缺席频道
        for cid, e in cert.items():
            if e["status"] == "CERTIFIED_ABSENT" and e["no_signal_points"]:
                best = cid
                break
    return best


def _draw_panel(ax, stops, title, covered_check=None):
    R = C.OMEGA_RADIUS
    ax.set_aspect("equal")
    ax.add_patch(Circle((0, 0), R, fill=False, edgecolor="#111111",
                        linewidth=1.6))
    # Ω 内部淡底
    ax.add_patch(Circle((0, 0), R, facecolor="#fef2f2", edgecolor="none",
                        zorder=0))
    # 排除盘（已证区域）
    for (x, y) in stops:
        ax.add_patch(Circle((x, y), C.R_EFF_MIN, facecolor="#bfdbfe",
                            edgecolor="#3b82f6", alpha=0.45, linewidth=0.7,
                            zorder=1))
    for i, (x, y) in enumerate(stops):
        ax.plot([x], [y], marker="o", color="#1e40af", markersize=6,
                zorder=3)
        ax.annotate("S%d" % (i + 1), (x, y), textcoords="offset points",
                    xytext=(5, 5), fontsize=8, color="#1e40af")
    # 骨架点参考
    bb = q3_backbone_points()
    ax.plot([p[0] for p in bb], [p[1] for p in bb], "x", color="#b45309",
            markersize=5, label="Q3 backbone points")
    ax.set_xlim(-R * 1.12, R * 1.12)
    ax.set_ylim(-R * 1.12, R * 1.12)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(title, fontsize=10)
    note = ""
    if covered_check is not None:
        note = "Ω ⊆ ∪B(S,1000): %s" % ("YES — certified"
                                       if covered_check else "NO — gap remains")
        ax.text(0, -R * 1.16, note, ha="center", fontsize=9.5,
                color="#15803d" if covered_check else "#b91c1c")
    return note


def main():
    p = add_args(argparse.ArgumentParser())
    p.add_argument("--run", default=RUN)
    p.add_argument("--channel", type=int, default=None)
    args = p.parse_args()
    run = Path(args.results) / args.run

    cert = load_json(run / "certificate.json")
    cid = str(args.channel) if args.channel else _pick_channel(cert)
    stops = [tuple(pt) for pt in cert[cid]["no_signal_points"]]
    assert stops, "channel %s has no no_signal stops" % cid

    half = stops[: max(1, (len(stops) + 1) // 2)]
    mid_covered = q3_certified(half)["certified"]
    full_covered = q3_certified(stops)["certified"]

    fig, axes = plt.subplots(1, 2, figsize=(13.4, 6.8))
    _draw_panel(axes[0], half,
                "mid-run: %d/%d no_signal stops — exclusion disks "
                "r=1000 m, residual gap" % (len(half), len(stops)),
                covered_check=mid_covered)
    _draw_panel(axes[1], stops,
                "final: all %d stops — certificate closes" % len(stops),
                covered_check=full_covered)
    axes[1].legend(fontsize=8.5, loc="upper right")
    fig.suptitle("Fig3  Q3 certificate accumulation (channel %s, %s)"
                 % (cid, args.run), fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))

    data = {
        "figure": "fig3_q3_certificate",
        "claim": "H.5 (Q3 disk-cover certificate), Addendum F.3",
        "run": args.run, "channel": int(cid),
        "no_signal_stops": [list(s) for s in stops],
        "exclusion_radius_m": C.R_EFF_MIN,
        "mid_run_certified": mid_covered,
        "final_certified": full_covered,
    }
    dump_data(args.out, "fig3_data.json", data)
    pdf, png = save(fig, args.out, "fig3_q3_certificate")
    print("fig3 ->", pdf, png)


if __name__ == "__main__":
    main()
