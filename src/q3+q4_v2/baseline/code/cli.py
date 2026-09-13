# -*- coding: utf-8 -*-
"""统一 CLI（Addendum J）：run / experiment / tune / train-q3-ranker /
figures / cases / freeze。

示例：
    python cli.py run --question q3 --policy mainline \
        --case cases/tune/tune_q3.json --case-id tune_q3_01 \
        --config configs/default_mainline.yaml --output results/run_001
    python cli.py run --question q3 --sim http \
        --base-url http://127.0.0.1:2026 --robot-id TEAM001 \
        --output results/official_001
    python cli.py experiment --suite mainline \
        --cases cases/ablation/ablation_q3.json \
        --config configs/default_mainline.yaml --output results/ablation_aX
    python cli.py tune --parameter tau --cases cases/tune/tune_q3.json \
        --config configs/default_mainline.yaml --tau-grid 0.0,0.05,0.1 \
        --output results/tune_tau
    python cli.py figures --experiment results/ablation_aX/mainline
    python cli.py cases --output cases/
    python cli.py freeze --config configs/default_mainline.yaml \
        --tune-results results/tune_tau/tune_results.json \
        --output configs/FROZEN_CONFIG.yaml
    python cli.py train-q3-ranker --traces results/teacher/*/decision_trace.jsonl \
        --output models/q3_ml_ranker.json

run.py 保持可用（单局直连入口）；本 CLI 是实验基础设施入口。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.client import ApiClient
from api.session import Session
from executor.action_executor import ActionExecutor
from experiment.casefile import (
    generate_all_case_sets,
    load_case,
    load_case_set,
)
from experiment.config import load_config
from experiment.freeze import freeze_config
from experiment.plotting import build_figures
from experiment.runner import GameRunner
from experiment.simulator import (
    SimulatorBackend,
    SimulatorHTTPServer,
    SyntheticSimulator,
)
from experiment.suite import POLICY_VARIANTS, run_tune

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "configs", "default_mainline.yaml")


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def _load_single_case(path, case_id=None):
    """--case 接受单案例文件或案例集文件（集文件需 --case-id 选择）。"""
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if "cases" in obj:
        cases = load_case_set(path)["cases"]
        if case_id is None:
            ids = [c["case_id"] for c in cases]
            raise SystemExit(
                "--case 指向案例集（%d 案例），请用 --case-id 选择：%s"
                % (len(cases), ", ".join(ids[:8])
                   + (" ..." if len(ids) > 8 else "")))
        for c in cases:
            if c["case_id"] == case_id:
                return c
        raise SystemExit("case_id %r not found in %s" % (case_id, path))
    return load_case(path)


def cmd_run(args):
    config = load_config(args.config)
    # variant 开关（Addendum C）：--policy 非 mainline 时派生配置
    if args.policy != "mainline":
        from experiment.suite import VARIANTS
        overrides, questions, _ = VARIANTS[args.policy]
        if args.question not in questions:
            raise SystemExit("variant %r 不适用于 %s" % (args.policy,
                                                         args.question))
        config = config.derive(**overrides)
    mode = args.question.upper()
    server = None
    sim = None
    case = None

    if args.sim == "http":
        # 官方模拟器直连（移动由 /measure、/clear 的 position 隐式完成；
        # 不存在 /move 端点，Addendum L）
        client = ApiClient(args.base_url, timeout=args.timeout,
                           robot_id=args.robot_id)
        backend = Session(client)
    else:
        if args.case is None:
            raise SystemExit("--sim synthetic/http-synthetic 需要 --case")
        case = _load_single_case(args.case, args.case_id)
        if case["question"] != args.question:
            raise SystemExit("case question %r != --question %r"
                             % (case["question"], args.question))
        sim = SyntheticSimulator.from_case(case)
        if args.sim == "http-synthetic":
            server = SimulatorHTTPServer(sim).start()
            client = ApiClient(server.url, timeout=args.timeout,
                               robot_id=args.robot_id)
            backend = Session(client)
        else:
            backend = SimulatorBackend(sim, robot_id=args.robot_id)

    try:
        executor = ActionExecutor(backend)
        runner = GameRunner(mode, executor, args.output,
                            simulator=sim, config=config, case=case,
                            config_path=args.config,
                            policy_variant=args.policy,
                            max_steps=args.max_steps)
        report = runner.run()
    finally:
        if server is not None:
            server.shutdown()

    m = report["metrics"]
    print("=" * 60)
    print("question=%s policy=%s case=%s"
          % (args.question, args.policy,
             case["case_id"] if case else "(official)"))
    print("complete=%s failure=%s steps=%d verifier_all_ok=%s"
          % (report["complete"], report["failure"], report["steps"],
             report["verifier_all_ok"]))
    print("cleared=%d certified_absent=%d sources=%s"
          % (m["cleared_count"], m["certified_absent_count"],
             m["sources_total"]))
    print("T_total=%.1fs (move=%.1f measure=%.1f switch=%.1f clear=%.1f)"
          % (m["T_total_virtual"], m["T_move"], m["T_measure"],
             m["T_switch"], m["T_clear"]))
    print("move_distance=%.0fm measures=%d switches=%d clears=%d/%d"
          % (m["total_move_distance_m"], m["n_measures"], m["n_switches"],
             m["n_clear_success"], m["n_clear_attempts"]))
    print("wall_clock=%.2fs output=%s" % (m["wall_clock_s"],
                                          report["output_dir"]))
    print("=" * 60)
    return 0 if (report["complete"] and report["verifier_all_ok"]) else 1


def cmd_experiment(args):
    from experiment.suite import run_ablation
    variants = tuple(v.strip() for v in args.variants.split(",")) \
        if args.variants else (args.policy,)
    summary = run_ablation(args.suite, args.cases, args.config,
                           args.output, variants=variants,
                           max_steps=args.max_steps, slim=args.slim)
    for var in summary["variants"]:
        s = summary["summary_by_variant"][var]
        print("variant=%s cases=%d success=%d clearance_min=%s"
              % (var, s["n_cases"], s["success_count"],
                 s["clearance_ratio_min"]))
    for pd in summary["paired_differences"]:
        if pd["dT"]:
            print("paired ΔT (%s - %s): mean=%.1f median=%.1f"
                  % (pd["variant"], pd["base"], pd["dT"]["mean"],
                     pd["dT"]["median"]))
    print("summary: %s" % os.path.join(args.output, args.suite,
                                       "suite_summary.json"))
    return 0


def cmd_tune(args):
    grid = None
    if args.tau_grid:
        grid = [float(v) for v in args.tau_grid.split(",")]
    out = run_tune(args.parameter, args.cases, args.config, args.output,
                   tau_grid=grid, max_steps=args.max_steps)
    print("tune_results: %s" % os.path.join(args.output,
                                            "tune_results.json"))
    print("note: selected_tau 由下一阶段 pilot 决定后回填（Addendum B.4）")
    return 0 if all(r["clearance_ok"] for r in out["results"]) else 1


def cmd_train_q3_ranker(args):
    from policy.q3_ml_train import train_q3_ranker
    report = train_q3_ranker(
        args.traces, args.output, epochs=args.epochs,
        learning_rate=args.learning_rate, min_gap=args.min_gap,
        calibration_trace_paths=args.calibration_traces,
        min_saving_s=args.min_saving_s)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def cmd_figures(args):
    manifest = build_figures(args.experiment, out_dir=args.output)
    print("figures rendered: all_scripts_ok=%s all_figures_present=%s"
          % (manifest["all_scripts_ok"], manifest["all_figures_present"]))
    for rec in manifest["plot_scripts"]:
        print("  %s: %s" % (rec["script"],
                            "ok" if rec["ok"] else "FAILED rc=%s %s"
                            % (rec.get("returncode"),
                               rec.get("stderr_tail", "")[:200])))
    print("manifest: %s" % os.path.join(manifest["out_dir"],
                                        "figures_manifest.json"))
    return 0 if manifest["all_scripts_ok"] \
        and manifest["all_figures_present"] else 1


def cmd_cases(args):
    written = generate_all_case_sets(args.output, tag=args.tag,
                                     seed_offset=args.seed_offset)
    for name, paths in written.items():
        print("%s/: %d files -> %s" % (name, len(paths),
                                       os.path.abspath(args.output)))
    return 0


def cmd_freeze(args):
    payload = freeze_config(args.config, args.tune_results, args.output)
    print("FROZEN_CONFIG written: %s" % os.path.abspath(args.output))
    print("tau=%g spec=%s model=%s git=%s"
          % (payload["tau"], payload["spec_version"],
             payload["model_version"], payload["git_commit"]))
    return 0


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="2026 CUMCM B 题 Q3/Q4 实验基础设施统一 CLI"
                    "（Addendum J）")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="单局运行（案例文件或官方 HTTP）")
    pr.add_argument("--question", choices=("q3", "q4"), required=True)
    pr.add_argument("--policy", choices=POLICY_VARIANTS,
                    default="mainline")
    pr.add_argument("--case", default=None,
                    help="案例 JSON（单案例或案例集+--case-id）")
    pr.add_argument("--case-id", default=None)
    pr.add_argument("--config", default=DEFAULT_CONFIG)
    pr.add_argument("--output", required=True)
    pr.add_argument("--sim", choices=("synthetic", "http",
                                      "http-synthetic"),
                    default="synthetic")
    pr.add_argument("--base-url", default="http://127.0.0.1:2026")
    pr.add_argument("--robot-id", default="TEAM001")
    pr.add_argument("--timeout", type=float, default=5.0)
    pr.add_argument("--max-steps", type=int, default=20000)
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("experiment", help="套件/消融执行（matched-case）")
    pe.add_argument("--suite", required=True,
                    help="套件名（结果子目录名）")
    pe.add_argument("--cases", required=True, help="案例集 JSON")
    pe.add_argument("--config", default=DEFAULT_CONFIG)
    pe.add_argument("--output", required=True, help="结果根目录")
    pe.add_argument("--policy", choices=POLICY_VARIANTS,
                    default="mainline")
    pe.add_argument("--variants", default=None,
                    help="逗号分隔 variant 列表（覆盖 --policy），"
                         "如 mainline,a1_fixed_geometry")
    pe.add_argument("--slim", action="store_true",
                    help="每案例只保留摘要证据（metrics/verifier/"
                         "decision_trace 等）")
    pe.add_argument("--max-steps", type=int, default=None)
    pe.set_defaults(func=cmd_experiment)

    pt = sub.add_parser("tune", help="C 类参数（tau）筛选框架")
    pt.add_argument("--parameter", choices=("tau",), required=True)
    pt.add_argument("--cases", required=True, help="tune 案例集 JSON")
    pt.add_argument("--config", default=DEFAULT_CONFIG)
    pt.add_argument("--tau-grid", default=None,
                    help="逗号分隔候选；缺省仅跑配置默认值占位"
                         "（grid 数值由下一阶段 pilot 决定）")
    pt.add_argument("--output", required=True)
    pt.add_argument("--max-steps", type=int, default=None)
    pt.set_defaults(func=cmd_tune)

    pm = sub.add_parser(
        "train-q3-ranker",
        help="从离线 decision_trace 训练 Q3 实验排序器")
    pm.add_argument("--traces", nargs="+", required=True,
                    help="一个或多个 active_localization decision_trace.jsonl")
    pm.add_argument("--output", required=True,
                    help="输出 JSON 模型 artifact")
    pm.add_argument("--epochs", type=int, default=8)
    pm.add_argument("--learning-rate", type=float, default=0.05)
    pm.add_argument("--min-gap", type=float, default=0.0,
                     help="教师 score 的最小偏好差；默认 0")
    pm.add_argument("--calibration-traces", nargs="*", default=None,
                    help="独立 replay-label trace；用于离线 takeover gate 校准")
    pm.add_argument("--min-saving-s", type=float, default=0.0,
                    help="校准 gate 要求的最差 replay saving（秒）")
    pm.set_defaults(func=cmd_train_q3_ranker)

    pf = sub.add_parser("figures", help="重建 Addendum F 全部图（F.1-F.8）")
    pf.add_argument("--experiment", required=True,
                    help="结果根目录（需含 figure_runs/ 与 ablation/）")
    pf.add_argument("--output", "--out", dest="output", default=None,
                    help="图输出目录（默认 <experiment>/figures）")
    pf.set_defaults(func=cmd_figures)

    pc = sub.add_parser("cases", help="重新生成四个隔离案例集")
    pc.add_argument("--output", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "cases"))
    pc.add_argument("--tag", default=None,
                    help="新模型版本的案例命名空间（字母/数字/下划线）")
    pc.add_argument("--seed-offset", type=int, default=0,
                    help="整体平移四个隔离 seed block，用于未见候选语料")
    pc.set_defaults(func=cmd_cases)

    pz = sub.add_parser("freeze", help="生成 FROZEN_CONFIG.yaml")
    pz.add_argument("--config", default=DEFAULT_CONFIG)
    pz.add_argument("--tune-results", required=True)
    pz.add_argument("--output", required=True)
    pz.set_defaults(func=cmd_freeze)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
