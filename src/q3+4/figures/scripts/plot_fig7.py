# -*- coding: utf-8 -*-
"""Fig7 — mission time decomposition（堆叠条形图，Q3/Q4 双 panel）。

堆叠分量只画 4 个正交账本项（T_move / T_measure / T_switch / T_clear，
其和恒等于 T_total_virtual）。residual certificate time 是模式视角量，
与账本分量定义重叠，故仅以括注文本标在条顶，不参与堆叠。
数据：results/ablation/*/<variant>/<case>/metrics.json 与 suite_summary.json。
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_args, dump_data, load_json, save  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

VARIANTS = ["mainline", "a1_fixed_geometry", "a2_no_reuse",
            "a3_sweep_all", "a4_nearest_cert"]
VSHORT = {"mainline": "mainline", "a1_fixed_geometry": "A1",
          "a2_no_reuse": "A2", "a3_sweep_all": "A3",
          "a4_nearest_cert": "A4"}
COMPS = [("T_move", "move", "tab:blue"),
         ("T_measure", "measure", "tab:orange"),
         ("T_switch", "switch", "tab:green"),
         ("T_clear", "clear", "tab:red")]


def collect(abl, q):
    """{variant: {"comps": {T_x: [vals]}, "resid": [vals], "n": int}}"""
    out = {v: {"comps": {c[0]: [] for c in COMPS}, "resid": [], "n": 0}
           for v in VARIANTS}
    for suite in sorted(abl.glob("ablation_*_%s" % q)):
        summ_path = suite / "suite_summary.json"
        resid_by_case = {}
        if summ_path.exists():
            summ = load_json(summ_path)
            for v, cases in summ["cases_by_variant"].items():
                for c in cases:
                    if c.get("residual_certificate_time_s") is not None:
                        resid_by_case[(v, c["case_id"])] = \
                            c["residual_certificate_time_s"]
        for v in VARIANTS:
            vdir = suite / v
            if not vdir.is_dir():
                continue
            for cdir in sorted(vdir.iterdir()):
                mp = cdir / "metrics.json"
                if not mp.exists():
                    continue
                m = load_json(mp)
                for key, _, _ in COMPS:
                    out[v]["comps"][key].append(m[key])
                out[v]["n"] += 1
                rv = resid_by_case.get((v, cdir.name))
                if rv is not None:
                    out[v]["resid"].append(rv)
    return out


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    abl = Path(args.results) / "ablation"

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2), sharey=False)
    csv_rows = [["question", "variant", "n_cases", "component",
                 "mean_s", "share_of_ledger"]]
    meta_q = {}

    for ax, q, title in zip(axes, ("q3", "q4"),
                            ("Q3 ablation suites", "Q4 ablation suites")):
        data = collect(abl, q)
        xs = list(range(len(VARIANTS)))
        bottoms = [0.0] * len(VARIANTS)
        means = {}
        for key, label, color in COMPS:
            vals = [statistics.mean(data[v]["comps"][key])
                    if data[v]["comps"][key] else 0.0 for v in VARIANTS]
            means[key] = vals
            ax.bar(xs, vals, bottom=bottoms, color=color, width=0.62,
                   label=label, edgecolor="white", lw=0.6)
            bottoms = [b + v for b, v in zip(bottoms, vals)]
        for xi, v in zip(xs, VARIANTS):
            tot = bottoms[xi]
            resid = statistics.mean(data[v]["resid"]) if data[v]["resid"] \
                else None
            note = "T=%.0f" % tot
            if resid is not None:
                note += "\n(resid-cert %.0f)" % resid
            ax.text(xi, tot + 0.02 * ax.get_ylim()[1] if False else tot * 1.01,
                    note, ha="center", va="bottom", fontsize=7.2)
            for key, _, _ in COMPS:
                csv_rows.append([q, v, data[v]["n"], key,
                                 "%.1f" % means[key][xi],
                                 "%.4f" % (means[key][xi] / tot if tot else 0)])
            csv_rows.append([q, v, data[v]["n"],
                             "residual_certificate_time_s(non-ledger,annot)",
                             "%.1f" % resid if resid is not None else "",
                             ""])
        meta_q[q] = {v: {"n_cases": data[v]["n"],
                         "mean_components": {k: means[k][i] for k, _, _ in COMPS},
                         "mean_residual_cert_s":
                             statistics.mean(data[v]["resid"])
                             if data[v]["resid"] else None}
                     for i, v in enumerate(VARIANTS)}
        ax.set_xticks(xs)
        ax.set_xticklabels([VSHORT[v] for v in VARIANTS], fontsize=9)
        ax.set_ylabel("mean virtual time per case (s)")
        ax.set_title(title, fontsize=10.5)
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylim(0, max(bottoms) * 1.18)

    handles = [plt.Rectangle((0, 0), 1, 1, fc=c) for _, _, c in COMPS]
    fig.legend(handles, [l for _, l, _ in COMPS], fontsize=9, ncol=4,
               loc="upper center", bbox_to_anchor=(0.5, 0.955),
               framealpha=0.95)
    fig.suptitle("Mission time decomposition by variant "
                 "(ledger components stack to T; residual-certificate time "
                 "annotated, not stacked)", fontsize=11.5, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    pdf, png = save(fig, args.out, "fig7_time_decomposition")

    out_csv = Path(args.out) / "fig7_data.csv"
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(csv_rows)
    meta = {"figure": "fig7_time_decomposition", "claim_map": ["H.3"],
            "sources": [str(abl)],
            "ledger_note": "stacked components are the four orthogonal ledger "
                           "terms (sum == T_total_virtual); residual "
                           "certificate time overlaps them by definition and "
                           "is only annotated in parentheses.",
            "by_question": meta_q,
            "outputs": {"pdf": str(pdf), "png": str(png),
                        "csv": str(out_csv)}}
    dump_data(args.out, "fig7_meta.json", meta)
    print("wrote", pdf, png, out_csv)


if __name__ == "__main__":
    main()
