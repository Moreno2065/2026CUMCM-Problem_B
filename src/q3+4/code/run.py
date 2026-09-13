# -*- coding: utf-8 -*-
"""CLI 入口：2026 CUMCM B 题 Q3/Q4 机器狗在线搜索清除程序。

示例：
    python run.py --mode q3 --sim synthetic --seed 101 --output-dir out/q3
    python run.py --mode q4 --sim synthetic --seed 202 --scenario edge_facing
    python run.py --mode q3 --sim http-synthetic --seed 7   # 走本地 HTTP 全链路
    python run.py --mode q3 --sim http --base-url http://127.0.0.1:2026 \
        --robot-id TEAM001                                   # 官方模拟器
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.client import ApiClient
from api.session import Session
from executor.action_executor import ActionExecutor
from experiment.runner import GameRunner
from experiment.simulator import (
    SimulatorBackend,
    SimulatorHTTPServer,
    SyntheticSimulator,
)

SCENARIOS = ("random", "boundary", "dense", "sparse", "edge_facing", "mixed")


def build_parser():
    p = argparse.ArgumentParser(
        prog="run.py",
        description="2026 CUMCM B 题 Q3/Q4：基于集合知识状态与确定性证书的"
                    "在线搜索清除（三模式词典式调度 READY>ACTIVE>CERTIFICATE）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mode", choices=("q3", "q4"), required=True,
                   help="q3=全向源（圆盘覆盖证书）；q4=定向源（δ-稳健凸包证书）")
    p.add_argument("--sim", choices=("synthetic", "http", "http-synthetic"),
                   default="synthetic",
                   help="synthetic=进程内合成模拟器；http=官方模拟器 HTTP；"
                        "http-synthetic=本地 HTTP 包装的合成模拟器（端到端演练）")
    p.add_argument("--base-url", default="http://127.0.0.1:2026",
                   help="--sim http 时的模拟器地址")
    p.add_argument("--robot-id", default="TEAM001",
                   help="参赛队号（1..64 字节 ASCII）")
    p.add_argument("--seed", type=int, default=None,
                   help="合成场景随机种子（默认随机）")
    p.add_argument("--n-sources", type=int, default=None,
                   help="源数量（默认随机 10..16）")
    p.add_argument("--scenario", choices=SCENARIOS, default="random",
                   help="合成场景：boundary=源贴边界；dense=密集；"
                        "sparse=稀疏；edge_facing=定向源朝外（Q4）；"
                        "mixed=定向/全向混合（Q4）")
    p.add_argument("--output-dir", default=None,
                   help="交付物输出目录（默认 ./output/<mode>_<sim>_<seed>）")
    p.add_argument("--max-steps", type=int, default=20000,
                   help="策略循环安全上限")
    p.add_argument("--timeout", type=float, default=5.0,
                   help="HTTP 单次请求超时（秒）")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    mode = args.mode.upper()
    seed = args.seed
    if seed is None:
        import random
        seed = random.randint(0, 2 ** 31 - 1)
    output_dir = args.output_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output", "%s_%s_%d" % (args.mode, args.sim, seed))

    sim = None
    server = None
    if args.sim == "synthetic":
        sim = SyntheticSimulator(mode, seed, n_sources=args.n_sources,
                                 scenario=args.scenario)
        backend = SimulatorBackend(sim, robot_id=args.robot_id)
    elif args.sim == "http-synthetic":
        sim = SyntheticSimulator(mode, seed, n_sources=args.n_sources,
                                 scenario=args.scenario)
        server = SimulatorHTTPServer(sim).start()
        client = ApiClient(server.url, timeout=args.timeout,
                           robot_id=args.robot_id)
        backend = Session(client)
    else:  # http：官方模拟器（本环境不实际连接，仅保证代码路径正确）
        client = ApiClient(args.base_url, timeout=args.timeout,
                           robot_id=args.robot_id)
        backend = Session(client)

    try:
        executor = ActionExecutor(backend)
        runner = GameRunner(mode, executor, output_dir,
                            simulator=sim, max_steps=args.max_steps)
        report = runner.run()
    finally:
        if server is not None:
            server.shutdown()

    m = report["metrics"]
    print("=" * 60)
    print("mode=%s sim=%s seed=%d scenario=%s"
          % (args.mode, args.sim, seed, args.scenario))
    print("complete=%s failure=%s steps=%d"
          % (report["complete"], report["failure"], report["steps"]))
    print("cleared=%d certified_absent=%d sources=%s"
          % (m["cleared_count"], m["certified_absent_count"],
             m["sources_total"]))
    print("T_total=%.1fs (move=%.1f measure=%.1f switch=%.1f clear=%.1f)"
          % (m["T_total_virtual"], m["T_move"], m["T_measure"],
             m["T_switch"], m["T_clear"]))
    print("move_distance=%.0fm measures=%d switches=%d clears=%d/%d"
          % (m["total_move_distance_m"], m["n_measures"], m["n_switches"],
             m["n_clear_success"], m["n_clear_attempts"]))
    if m["avg_localize_clear_time_s"] is not None:
        print("avg_localize_clear=%.1fs" % m["avg_localize_clear_time_s"])
    print("verifier_all_ok=%s reconcile_warnings=%d anomalies=%d"
          % (report["verifier_all_ok"], len(m["reconcile_warnings"]),
             len(m["anomalies"])))
    print("wall_clock=%.2fs output=%s" % (m["wall_clock_s"],
                                          report["output_dir"]))
    print("=" * 60)
    return 0 if (report["complete"] and report["verifier_all_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
