# -*- coding: utf-8 -*-
"""τ pilot 选择 + FROZEN_CONFIG 冻结 + tuning 报告（Addendum B.4-B.6，Gate 4/5）。

读取 results/tuning/tune_q3|q4/tune_results.json，按 B.5 规则选 tau，
生成 configs/FROZEN_CONFIG.yaml 与 results/tuning/tuning_report.{json,md}。

用法：python pilot_tune_freeze.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from experiment.freeze import freeze_config
from experiment.suite import select_tau

ROOT = os.path.dirname(os.path.abspath(__file__))
TUNE_DIR = os.path.join(ROOT, "results", "tuning")


def main():
    trs = []
    for q in ("q3", "q4"):
        with open(os.path.join(TUNE_DIR, "tune_%s" % q,
                               "tune_results.json"),
                  encoding="utf-8") as f:
            trs.append(json.load(f))

    tau, rationale = select_tau(trs)

    # 回填 selected_tau 到两份 tune_results（B.5 可追溯）
    for q, tr in zip(("q3", "q4"), trs):
        tr["selected_tau"] = tau
        tr["selection_rationale"] = rationale["rule"]
        with open(os.path.join(TUNE_DIR, "tune_%s" % q,
                               "tune_results.json"), "w",
                  encoding="utf-8") as f:
            json.dump(tr, f, ensure_ascii=False, indent=1)
            f.write("\n")

    # B.6 冻结
    payload = freeze_config(
        os.path.join(ROOT, "configs", "default_mainline.yaml"),
        {"selected_tau": tau,
         "case_set": "tune_q3.json+tune_q4.json (seed block 100000+)",
         "selection_metric": "Addendum B.5 primary/secondary",
         "selection_rule": rationale["rule"],
         "results": []},
        os.path.join(ROOT, "configs", "FROZEN_CONFIG.yaml"))

    # 报告
    report = {"selected_tau": tau, "rationale": rationale,
              "frozen_config": payload,
              "tune_sets": ["tune_q3.json", "tune_q4.json"],
              "tau_grid": [0.0, 0.02, 0.05, 0.1, 0.2]}
    with open(os.path.join(TUNE_DIR, "tuning_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")

    lines = ["# τ 调参 pilot 报告（Addendum B.4/B.5，Gate 4）", ""]
    lines.append("- tau_grid = [0.0, 0.02, 0.05, 0.1, 0.2]（τ 单位 = "
                 "gain/cost = 每虚拟秒可行域 MEC 半径收缩米数，"
                 "与实现语义一致）")
    lines.append("- tune 集：tune_q3.json（6 案例）+ tune_q4.json"
                 "（6 案例），每候选 12 局")
    lines.append("- **冻结 τ = %g**" % tau)
    lines.append("- 选择规则：%s" % rationale["rule"])
    lines.append("")
    lines.append("## 候选汇总（q3+q4 合并 12 案例）")
    lines.append("")
    lines.append("| τ | clearance_ok | mean t/src (s) | std | "
                 "mean measures | mean switches | mean move (m) | "
                 "mean cert done (s) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for c in rationale["all_candidates"]:
        tps = c["t_per_source_s"]
        nm = c["n_measures"]
        ns = c["n_switches"]
        mv = c["move_m"]
        cc = c["cert_completion_s"]
        lines.append("| %g | %s | %.1f | %.1f | %s | %s | %s | %s |"
                     % (c["tau"], c["clearance_ok"],
                        tps["mean"] if tps else float("nan"),
                        tps["std"] if tps else float("nan"),
                        "%.1f" % nm["mean"] if nm else "N/A",
                        "%.1f" % ns["mean"] if ns else "N/A",
                        "%.0f" % mv["mean"] if mv else "N/A",
                        "%.0f" % cc["mean"] if cc else "N/A"))
    lines.append("")
    lines.append("## 接近带（与最优 mean 差 <2%）内候选")
    lines.append("")
    for c in rationale["close_candidates"]:
        lines.append("- τ=%g：mean=%.1f s，std=%.1f s"
                     % (c["tau"], c["mean"], c["std"]))
    lines.append("")
    lines.append("冻结文件：`configs/FROZEN_CONFIG.yaml`（freeze_time=%s，"
                 "git=%s）。冻结后正式评估不得再修改 τ（B.6）。"
                 % (payload["freeze_time"], payload["git_commit"]))
    lines.append("")
    with open(os.path.join(TUNE_DIR, "tuning_report.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("selected tau = %g" % tau)
    print("FROZEN_CONFIG: configs/FROZEN_CONFIG.yaml")
    print("report: results/tuning/tuning_report.{json,md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
