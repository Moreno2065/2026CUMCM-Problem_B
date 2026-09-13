# -*- coding: utf-8 -*-
"""Fig8 — certificate / resolution progress（A4 mainline vs nearest_cert，
Q3/Q4 双 panel）。

基于 channel_state_history.jsonl 的逐步快照：
- 粗阶梯线：已了结频道比例（status ∈ {CLEARED, CERTIFIED_ABSENT}）。
- 细线：未了结频道的 certificate_coverage_est 均值。
注意（如实呈现）：A4 两 variant 输出逐字节相同，曲线重合，
为等价退化（H.4 neutral）；以实线/虚线叠加并文字注明。
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_args, dump_data, read_jsonl, save  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

PANELS = [("q3", "a4_q3_mainline", "a4_q3_nearest",
           "Q3: a4_nearest_cert vs mainline"),
          ("q4", "a4_q4_mainline", "a4_q4_nearest",
           "Q4: a4_nearest_cert vs mainline")]
RESOLVED = ("CLEARED", "CERTIFIED_ABSENT")


def load_progress(run_dir):
    """返回 (times, resolved_frac, mean_unresolved_cov, n_channels)。"""
    recs = read_jsonl(Path(run_dir) / "channel_state_history.jsonl")
    times, resolved, cov = [], [], []
    for r in recs:
        chans = r["channels"]
        n = len(chans)
        res = sum(1 for v in chans.values() if v["status"] in RESOLVED)
        unres_cov = [v.get("certificate_coverage_est", 0.0)
                     for v in chans.values() if v["status"] not in RESOLVED]
        times.append(r["virtual_time"])
        resolved.append(res / n)
        # 无未了结频道时记 NaN（折线自然断开），避免末端伪降到 0
        cov.append(sum(unres_cov) / len(unres_cov) if unres_cov
                   else float("nan"))
    return times, resolved, cov, len(recs[0]["channels"])


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    base = Path(args.results) / "figure_runs"

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0))
    csv_rows = [["question", "variant", "virtual_time", "resolved_fraction",
                 "mean_unresolved_coverage_est"]]
    meta = {}
    colors = {"mainline": "tab:blue", "a4_nearest_cert": "tab:orange"}

    for ax, (q, run_m, run_n, title) in zip(axes, PANELS):
        for label, run, ls in (("mainline", run_m, "-"),
                               ("a4_nearest_cert", run_n, "--")):
            t, res, cov, nch = load_progress(base / run)
            col = colors[label]
            ax.step(t, res, where="post", lw=2.2, color=col, ls=ls,
                    label="%s: resolved fraction" % label)
            ax.plot(t, cov, lw=1.1, color=col, ls=ls, alpha=0.55,
                    label="%s: mean coverage (unresolved)" % label)
            for ti, ri, ci in zip(t, res, cov):
                csv_rows.append([q, label, "%.3f" % ti, "%.4f" % ri,
                                 "" if ci != ci else "%.4f" % ci])
            if label == "mainline":
                meta[q] = {"n_channels": nch, "t_end": t[-1],
                           "resolved_end": res[-1]}
        ax.set_xlabel("virtual time (s)")
        ax.set_ylabel("fraction of channels")
        ax.set_ylim(-0.05, 1.08)
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.3)
        ax.text(0.02, 0.97, "variants byte-identical: curves coincide\n"
                "(equivalence degeneration, H.4 neutral)",
                transform=ax.transAxes, fontsize=7.5, color="0.3", va="top")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, ncol=2, loc="upper center",
               bbox_to_anchor=(0.5, 0.935), framealpha=0.95)
    fig.suptitle("Mission progress: channel resolution and certificate "
                 "coverage (mainline vs a4_nearest_cert)", fontsize=12,
                 y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    pdf, png = save(fig, args.out, "fig8_certificate_progress")

    out_csv = Path(args.out) / "fig8_data.csv"
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(csv_rows)
    meta_full = {"figure": "fig8_certificate_progress", "claim_map": ["H.4"],
                 "source": "channel_state_history.jsonl per-step snapshots",
                 "resolved_definition": "status in {CLEARED, CERTIFIED_ABSENT}",
                 "equivalence_note": "a4_nearest_cert output is byte-identical "
                                     "to mainline; curves coincide by "
                                     "construction (equivalence degeneration).",
                 "panels": meta,
                 "outputs": {"pdf": str(pdf), "png": str(png),
                             "csv": str(out_csv)}}
    dump_data(args.out, "fig8_meta.json", meta_full)
    print("wrote", pdf, png, out_csv)


if __name__ == "__main__":
    main()
