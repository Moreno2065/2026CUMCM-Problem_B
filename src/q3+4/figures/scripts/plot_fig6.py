# -*- coding: utf-8 -*-
"""Fig6 — ablation paired comparison（ΔT 逐案例点图）。

x 类别：A1-q3, A1-q4, A2-q3, A2-q4, A3-q3, A3-q4, A4-q3, A4-q4, Q4naive-q4。
每案例一个点（dT = variant − mainline），mean 横线。
q4_naive 中 success=False 且 false_certified_absent>0 的案例以红色 × 标注。
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_args, dump_data, load_json, save  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

SUITES = [  # (label, suite_dir, variant_name)
    ("A1-q3", "ablation_a1_q3", "a1_fixed_geometry"),
    ("A1-q4", "ablation_a1_q4", "a1_fixed_geometry"),
    ("A2-q3", "ablation_a2_q3", "a2_no_reuse"),
    ("A2-q4", "ablation_a2_q4", "a2_no_reuse"),
    ("A3-q3", "ablation_a3_q3", "a3_sweep_all"),
    ("A3-q4", "ablation_a3_q4", "a3_sweep_all"),
    ("A4-q3", "ablation_a4_q3", "a4_nearest_cert"),
    ("A4-q4", "ablation_a4_q4", "a4_nearest_cert"),
    ("Q4naive-q4", "q4_naive_vs_mainline", "q4_naive_q3_style"),
]


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    abl = Path(args.results) / "ablation"

    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    csv_rows = [["case_id", "variant", "metric", "value", "success"]]
    cat_data = []

    for xi, (label, suite, variant) in enumerate(SUITES):
        stats = load_json(abl / suite / "stats.json")
        pairs = None
        for pd_ in stats["paired_differences"]:
            if pd_["variant"] == variant:
                pairs = pd_["pairs"]
                break
        assert pairs, "no pairs for %s in %s" % (variant, suite)

        # 失败案例集合（含假证书频道）
        false_cert = {}
        summary_path = abl / suite / "suite_summary.json"
        if summary_path.exists():
            summ = load_json(summary_path)
            for c in summ["cases_by_variant"].get(variant, []):
                if c.get("false_certified_absent", 0) > 0:
                    chans = [f["channel"] for f in c.get("false_cert_channels", [])]
                    false_cert[c["case_id"]] = chans

        dts = []
        jitter = 0.09
        fc_notes = []
        for i, p in enumerate(pairs):
            dts.append(p["dT"])
            off = -jitter + 2 * jitter * (i % 3) / 2.0
            bad = p["case_id"] in false_cert or not p["variant_success"]
            if p["case_id"] in false_cert:
                ax.scatter(xi + off, p["dT"], marker="x", s=110, lw=2.4,
                           c="tab:red", zorder=6)
                chans = ",".join("ch%d" % c for c in false_cert[p["case_id"]])
                fc_notes.append("%s(%s)" % (p["case_id"].replace("ablation_", ""),
                                            chans))
            else:
                ax.scatter(xi + off, p["dT"], marker="o", s=38,
                           c="tab:red" if bad else "tab:blue",
                           alpha=0.85, zorder=5)
            csv_rows.append([p["case_id"], label, "dT_vs_mainline_s",
                             "%.3f" % p["dT"], str(p["variant_success"])])
        if fc_notes:
            ax.annotate("false cert:\n" + "\n".join(fc_notes),
                        xy=(xi, max(dts)), xytext=(xi - 0.55, 0.86),
                        textcoords=("data", "axes fraction"),
                        fontsize=7.5, color="tab:red", va="top",
                        arrowprops=dict(arrowstyle="-", color="tab:red",
                                        lw=0.7))
        m = statistics.mean(dts)
        ax.plot([xi - 0.22, xi + 0.22], [m, m], color="k", lw=2.2, zorder=7)
        ax.text(xi, m - 0.02 * (ax.get_ylim()[1] - ax.get_ylim()[0])
                if ax.get_ylim()[1] > 0 else m,
                "mean=%.1f" % m, fontsize=7, va="top", ha="center",
                color="k")
        cat_data.append({"category": label, "suite": suite, "n": len(dts),
                         "mean_dT": m, "dT": dts})

    ax.axhline(0, color="0.4", lw=1.0, ls="--")
    ax.set_xticks(range(len(SUITES)))
    ax.set_xticklabels([s[0] for s in SUITES], fontsize=9)
    ax.set_ylabel(r"$\Delta T$ = variant $-$ mainline total virtual time (s)")
    ax.set_title("Ablation paired comparison: per-case $\\Delta T$ "
                 "(negative = variant faster)\nred $\\times$: case with "
                 "false absence certificate (C.6 failure)", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker="o", ls="", c="tab:blue",
                      label="case (paired $\Delta$T)"),
               Line2D([], [], marker="x", ls="", c="tab:red", lw=2.2,
                      label="false-certificate case"),
               Line2D([], [], color="k", lw=2.2, label="category mean")]
    ax.legend(handles=handles, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    pdf, png = save(fig, args.out, "fig6_ablation_paired")

    out_csv = Path(args.out) / "fig6_data.csv"
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(csv_rows)

    meta = {"figure": "fig6_ablation_paired",
            "claim_map": ["H.1", "H.2", "H.3", "H.4", "H.5"],
            "sources": [str(abl / s / "stats.json") for _, s, _ in SUITES],
            "categories": cat_data,
            "outputs": {"pdf": str(pdf), "png": str(png),
                        "csv": str(out_csv)}}
    dump_data(args.out, "fig6_meta.json", meta)
    print("wrote", pdf, png, out_csv)


if __name__ == "__main__":
    main()
