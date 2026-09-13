# -*- coding: utf-8 -*-
"""Fig5 — localization convergence（Q3/Q4 双 panel）。

每频道细线（mec_radius vs observation_index），加按 obs index 聚合的
median 线与 IQR band。不用 95% CI（样本间非独立，避免伪造区间）。
数据源：figure_runs/q3_main, figure_runs/q4_main 的
localization_history/channel_*.jsonl。
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import RESULTS, add_args, dump_data, read_jsonl, save  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

RUNS = [("q3_main", "Q3 mainline run (holdout_q3_01, 10 sources)"),
        ("q4_main", "Q4 mainline run (holdout_q4_02, 13 sources)")]


def load_channels(run_dir):
    hist = Path(run_dir) / "localization_history"
    out = {}
    for f in sorted(hist.glob("channel_*.jsonl")):
        ch = f.stem.split("_", 1)[1]
        recs = read_jsonl(f)
        # 注意：记录里的 observation_count 是全局计数；Fig5 需要
        # 每频道自己的收敛序列，故按文件内顺序重编号为 1..n。
        pts = [(i + 1, r["virtual_time"], r["mec_radius"], r["diameter"])
               for i, r in enumerate(recs)]
        if pts:
            out[ch] = pts
    return out


def median_iqr(channels, key_idx):
    """按 observation_index 聚合：median 与 IQR。"""
    max_obs = max(p[0] for pts in channels.values() for p in pts)
    med, q1, q3, xs = [], [], [], []
    for k in range(1, max_obs + 1):
        vals = []
        for pts in channels.values():
            # 每频道 obs_count 从 1 递增；取该 index 记录
            if k <= len(pts) and pts[k - 1][0] == k:
                vals.append(pts[k - 1][key_idx])
        if len(vals) >= 2:
            xs.append(k)
            med.append(statistics.median(vals))
            q = statistics.quantiles(vals, n=4)
            q1.append(q[0])
            q3.append(q[2])
    return xs, med, q1, q3


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    base = Path(args.results) / "figure_runs"

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0))
    csv_rows = [["case_id", "channel", "observation_index", "virtual_time",
                 "diameter", "mec_radius", "method"]]

    for ax, (run, title) in zip(axes, RUNS):
        channels = load_channels(base / run)
        for ch, pts in sorted(channels.items(), key=lambda kv: int(kv[0])):
            xs = [p[0] for p in pts]
            ys = [p[2] for p in pts]
            ax.plot(xs, ys, lw=0.8, alpha=0.35, color="tab:blue")
            for p in pts:
                csv_rows.append([run, ch, p[0], "%.3f" % p[1],
                                 "%.3f" % p[3], "%.3f" % p[2],
                                 "bounded-bearing MEC"])
        xs, med, q1, q3 = median_iqr(channels, key_idx=2)
        ax.fill_between(xs, q1, q3, color="tab:orange", alpha=0.25,
                        label="IQR across channels")
        ax.plot(xs, med, color="tab:orange", lw=2.2,
                label="median across channels")
        ax.set_xlabel("observation index (per channel)")
        ax.set_ylabel("MEC radius (m)")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8.5, loc="upper right")

    fig.suptitle("Localization convergence: per-channel MEC radius vs observation count",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    pdf, png = save(fig, args.out, "fig5_localization_convergence")

    # CSV 导出
    out_csv = Path(args.out) / "fig5_data.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(csv_rows)

    meta = {
        "figure": "fig5_localization_convergence",
        "claim_map": ["H.1"],
        "sources": {run: str(base / run / "localization_history")
                    for run, _ in RUNS},
        "aggregation": "median + IQR across channels per observation index "
                       "(no fabricated 95% CI)",
        "outputs": {"pdf": str(pdf), "png": str(png),
                    "csv": str(out_csv)},
    }
    dump_data(args.out, "fig5_meta.json", meta)
    print("wrote", pdf, png, out_csv)


if __name__ == "__main__":
    main()
