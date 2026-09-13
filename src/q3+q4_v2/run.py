# -*- coding: utf-8 -*-
"""v2 在线运行入口：合成、HTTP 演练和官方 HTTP+JSON 模拟器。

官方模拟器只需要提供四个 POST 端点：``/enter``、``/measure``、
``/clear``、``/exit``。本入口复用 v1 已核对的严格协议客户端与会话层，
但执行的是 ``q3+4_v2`` 的调度器和 ``V2GameRunner``。

示例（官方模拟器）：
    python -X utf8 src/q3+4_v2/run.py --mode q3 --sim http \
        --base-url http://127.0.0.1:2026 --robot-id TEAM001

示例（本地 HTTP+JSON 全链路演练）：
    python -X utf8 src/q3+4_v2/run.py --mode q4 --sim http-synthetic \
        --seed 101 --n-sources 10 --scenario mixed
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
LEGACY_CODE = HERE / "baseline" / "code"
# runtime.py imports the immutable protocol/executor/geometry snapshot as
# top-level packages.  Put the v2 strategy folders first, then that snapshot.
for _path in (str(HERE), str(LEGACY_CODE)):
    while _path in sys.path:
        sys.path.remove(_path)
sys.path[0:0] = [str(HERE), str(LEGACY_CODE)]

from api.client import ApiClient
from api.session import Session
from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.simulator import SimulatorBackend, SimulatorHTTPServer, SyntheticSimulator
from geometry_joint.scheduler import GeometryJointScheduler
from learned_search.scheduler import LearnedSearchScheduler
from probabilistic_search.scheduler import BeliefProbeScheduler
import production
from runtime import V2GameRunner, report_line
from belief_rollout.scheduler import BeliefRolloutScheduler
from constraint_search.scheduler import ConstraintSearchScheduler
from constraint_search.macro import ConstraintMacroScheduler
from compact_ring.scheduler import CompactRingScheduler
from q4_bisect.scheduler import Q4BisectScheduler
from q4_shadow.scheduler import Q4ShadowScheduler


SCENARIOS = ("random", "boundary", "dense", "sparse", "edge_facing", "mixed")
SCAN_MODES = ("state_aware", "sweep_all", "useful_sweep",
              "selective_sweep", "selective_clear")
SCHEDULERS = {
    "learned": LearnedSearchScheduler,
    "probabilistic": BeliefProbeScheduler,
    "geometry": GeometryJointScheduler,
    "belief-rollout": BeliefRolloutScheduler,
    "constraint-search": ConstraintSearchScheduler,
    "constraint-macro": ConstraintMacroScheduler,
    "compact-ring": CompactRingScheduler,
    "q4-bisect": Q4BisectScheduler,
    "q4-shadow": Q4ShadowScheduler,
}


def _positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _nonnegative_float(value):
    import math
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def _positive_float(value):
    number = _nonnegative_float(value)
    if number <= 0.0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _unit_interval(value):
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return number


def _augment_per_source_metrics(report, output_dir):
    """Add a remote-safe average-per-source record to this run's artifacts.

    The official API does not return the initial source count.  Once the
    runner is complete, ``cleared_count`` is the observed number of real
    sources; certified-absent channels are excluded.  This keeps the hidden
    count out of ``sources_total`` while still recording the requested
    average in both JSON artifacts.
    """
    metrics = report["metrics"]
    known_count = metrics.get("sources_total")
    if known_count:
        denominator = int(known_count)
        basis = metrics.get("t_per_source_basis")
    elif report.get("complete") and metrics.get("cleared_count", 0):
        denominator = int(metrics["cleared_count"])
        basis = (
            "T_total_virtual / cleared_count after complete run; "
            "cleared_count is observed from accepted clear results")
    else:
        denominator = None
        basis = metrics.get("t_per_source_basis")

    average = (metrics["T_total_virtual"] / denominator
               if denominator else None)
    metrics["source_count_for_average"] = denominator
    metrics["average_time_per_source_s"] = average
    metrics["average_time_per_source_basis"] = basis
    metrics["observed_cleared_source_count"] = metrics.get("cleared_count", 0)
    # Keep the long-standing t_per_source_s field useful for an official
    # completed run while preserving sources_total=None as a hidden-count
    # boundary.  Synthetic runs already have the same value and basis.
    if known_count is None and average is not None:
        metrics["t_per_source_s"] = average
        metrics["t_per_source_basis"] = basis

    output_path = Path(output_dir)
    (output_path / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    report["metrics"] = metrics
    (output_path / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=(
            "Q3/Q4 v2 在线搜索清除：支持官方 HTTP+JSON 模拟器，"
            "并保存可复核的轨迹、API 日志和 verifier 报告。"),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--mode", choices=("q3", "q4"), required=True,
                        help="题目：q3=全向源，q4=定向源")
    parser.add_argument("--sim", choices=("http", "http-synthetic", "synthetic"),
                        default="http",
                        help=(
                            "http=官方模拟器；http-synthetic=本地 HTTP+JSON "
                            "演练；synthetic=进程内离线演练"))
    parser.add_argument("--base-url", default="http://127.0.0.1:2026",
                        help="--sim http 时官方模拟器的根地址")
    parser.add_argument("--robot-id", default="TEAM001",
                        help="协议 robot_id（ASCII，1..64 字节）")
    parser.add_argument("--policy", "--solver", choices=tuple(SCHEDULERS),
                        default="learned",
                        help="在线调度器；belief-rollout=实验性观测采样回放搜索")
    rollout = parser.add_argument_group("belief-rollout 搜索预算（仅该策略使用）")
    rollout.add_argument("--rollout-worlds", type=_positive_int, default=4,
                         help="每次搜索使用的假设地图数")
    rollout.add_argument("--rollout-candidates", type=_positive_int, default=9,
                         help="每次比较的联合动作上限，包含原策略动作")
    rollout.add_argument("--rollout-every", type=_positive_int, default=3,
                         help="每隔多少次决策尝试搜索；1=每次")
    rollout.add_argument("--rollout-budget", type=_nonnegative_float, default=240.0,
                         help="整局搜索计算预算（现实秒）；0=完全复现原策略")
    rollout.add_argument("--rollout-margin", type=_nonnegative_float, default=20.0,
                         help="预测剩余总时间至少减少多少虚拟秒才替换原动作")
    rollout.add_argument("--rollout-min-win-fraction", type=_unit_interval,
                         default=0.5,
                         help="候选动作至少在多少比例的假设地图中获胜")
    rollout.add_argument("--rollout-objective", choices=("mean", "median"),
                         default="mean", help="假设地图收益的聚合方式")
    rollout.add_argument("--rollout-clear-radius", type=_nonnegative_float,
                         default=0.0,
                         help="MEC 半径不超过该值时把粒子试清加入候选；0=关闭")
    rollout.add_argument("--rollout-clear-candidates", type=int, default=3,
                         help="每次搜索最多加入的粒子试清候选数")
    rollout.add_argument("--rollout-clear-only", action="store_true",
                         help="消融：仅比较原策略动作与粒子试清，不加入其他补测候选")
    rollout.add_argument("--rollout-step-limit", type=_positive_int, default=300,
                         help="每条假设后续回放的最大动作步数")
    segment = parser.add_argument_group("constraint-macro 实验搜索预算（Q3）")
    segment.add_argument("--segment-budget", type=_nonnegative_float, default=60.0)
    segment.add_argument("--segment-worlds", type=_positive_int, default=3)
    segment.add_argument("--segment-margin", type=_nonnegative_float, default=100.0)
    segment.add_argument("--segment-min-win-fraction", type=float, default=1.0)
    compact = parser.add_argument_group("compact-ring 联合覆盖定位参数（Q3）")
    compact.add_argument("--compact-performance-preset", action="store_true",
                         help="启用经14个独立种子验证的稳定提速组合")
    compact.add_argument("--compact-joint-service-preset", action="store_true",
                         help="Q3实验：覆盖锚点、近ACTIVE和READY共同重排（15源随机小样本有效）")
    compact.add_argument("--compact-ring-radius", type=_nonnegative_float, default=940.0)
    compact.add_argument("--compact-ring-points", type=_positive_int, default=8)
    compact.add_argument("--compact-ring-active-max-directions", type=int,
                         default=0,
                         help="每频道在固定覆盖点最多测向次数；0=不限制，UNKNOWN 证书扫描不受影响")
    compact.add_argument("--compact-center-anchor", action="store_true",
                         help="证书增加原点锚点；配合6×1150 m可构成7点Q3覆盖（实验）")
    compact.add_argument("--compact-center-warmup-resultant-threshold",
                         type=_unit_interval, default=0.0,
                         help="原点测向合成长度达到此值时，先完成若干外环锚点；0=关闭")
    compact.add_argument("--compact-center-warmup-min-stops", type=int,
                         default=3,
                         help="原点测向集中时，服务插入前至少完成的证书站数")
    compact.add_argument("--compact-coverage-optical-max-points", type=int,
                         default=0,
                         help="覆盖阶段允许的单源保证清除圆点数上限；0=关闭")
    compact.add_argument("--compact-coverage-optical-max-entries", type=int,
                         default=1,
                         help="覆盖阶段最多启动多少个有限光学收尾支线")
    compact.add_argument("--compact-coverage-optical-max-entry", type=_nonnegative_float,
                         default=0.0,
                         help="覆盖阶段光学支线首个清除点最大距离米数；0=不限制")
    compact.add_argument("--compact-active-stop-radius", type=_nonnegative_float, default=80.0)
    compact.add_argument("--compact-enroute-clear-radius", type=_nonnegative_float, default=20.0)
    compact.add_argument("--compact-enroute-detour", type=_nonnegative_float, default=350.0)
    compact.add_argument("--compact-probe-radius", type=_nonnegative_float, default=0.0)
    compact.add_argument("--compact-optical-cover-points", type=int, default=10,
                         help="环后允许用多少个20米清除圆覆盖小可行域；0=关闭")
    compact.add_argument("--compact-search-budget", type=_nonnegative_float, default=0.0,
                         help="环后宏搜索现实秒预算；0=使用快速确定性后段")
    compact.add_argument("--compact-finish-active-at-cap", action="store_true",
                         help="确认16源后跳过UNKNOWN，但完成当前停点ACTIVE测量")
    compact.add_argument("--compact-route-active",
                         action=argparse.BooleanOptionalAction, default=True,
                         help="环后将ACTIVE补测点与READY清除点联合求开放路径")
    compact.add_argument("--compact-route-active-attempts", type=_positive_int, default=3)
    compact.add_argument("--compact-enroute-measure-detour", type=_nonnegative_float,
                         default=350.0)
    compact.add_argument("--compact-route-cluster-radius", type=_nonnegative_float,
                         default=0.0,
                         help="环后在同一停点合并附近ACTIVE补测；0=关闭")
    compact.add_argument("--compact-route-cluster-max", type=int, default=0,
                         help="一次停点最多合并几个ACTIVE频道；0=关闭")
    compact.add_argument("--compact-route-cluster-min-saving",
                         type=_nonnegative_float, default=35.0,
                         help="删除未来补测点至少节省的开放路径米数")
    compact.add_argument("--compact-route-alternatives", action="store_true",
                         help="联合优化ACTIVE补测点候选和开放路径顺序")
    compact.add_argument("--compact-fusion-budget", type=_nonnegative_float,
                         default=0.0,
                         help="同站合并补测的整局回放预算（现实秒）；0=关闭")
    compact.add_argument("--compact-fusion-worlds", type=_positive_int, default=4,
                         help="同站合并候选的观测相容假设数")
    compact.add_argument("--compact-fusion-margin", type=_nonnegative_float,
                         default=10.0, help="合并至少节省的预测整局虚拟秒数")
    compact.add_argument("--compact-fusion-views-only", action="store_true",
                         help="消融：只比较沿当前路段提前补测与原停点")
    compact.add_argument("--compact-clear-region-route", action="store_true",
                         help="结合进站与离站距离，在保证清除区域内联合选点")
    compact.add_argument("--compact-route-quality-slack",
                         type=_nonnegative_float, default=5.0,
                         help="候选点最坏MEC半径相对最优值允许多出的米数")
    compact.add_argument("--compact-route-point-passes", type=_positive_int,
                         default=2,
                         help="补测点和路径顺序交替优化轮数")
    bisect = parser.add_argument_group("q4-bisect 中段双探点参数（Q4）")
    bisect.add_argument("--q4-bisect-enabled",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="启用几何中点双探点；可关闭以做独立消融")
    bisect.add_argument("--q4-bisect-tail-only",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="仅在所有 UNKNOWN 已处理后启用双探点定位")
    bisect.add_argument("--q4-bisect-max-axial", type=_nonnegative_float,
                        default=1600.0,
                        help="允许双探点的最大纵深上界（米）")
    bisect.add_argument("--q4-bisect-ready-first",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="先清除已有 READY，再处理 ACTIVE 双探点")
    bisect.add_argument("--q4-bisect-min-no-shrink", type=int, default=4,
                        help="连续多少次未有效收缩后启用双探点")
    bisect.add_argument("--q4-bisect-max-rounds", type=_positive_int, default=2,
                        help="每频道最多执行多少轮双探点")
    bisect.add_argument("--q4-bisect-enroute-detour",
                        type=_nonnegative_float, default=500.0,
                        help="证书尚未结束时允许的最大插入绕路（米）")
    bisect.add_argument("--q4-bisect-min-known", type=int, default=16,
                        help="至少确认多少个存在频道后启用双探点")
    bisect.add_argument("--q4-bisect-min-area", type=_nonnegative_float,
                        default=5000.0,
                        help="仅对面积不小于此值的难源启用（平方米）")
    bisect.add_argument("--q4-bisect-round-budget", type=_positive_int,
                        default=6, help="整局双探点轮数上限")
    shadow = parser.add_argument_group(
        "q4-shadow 快速主策略＋风险影子模型参数（Q4）")
    shadow.add_argument("--shadow-enabled",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="只在风险门控触发时启用稳健后验选点")
    shadow.add_argument("--shadow-min-spacing", type=_nonnegative_float,
                        default=0.0,
                        help="Q4 同频道历史测点最小间距；50米仅供消融")
    shadow.add_argument("--shadow-no-shrink-trigger", type=_positive_int,
                        default=4, help="连续无有效收缩风险阈值")
    shadow.add_argument("--shadow-measure-trigger", type=_positive_int,
                        default=8, help="ACTIVE 主测量次数风险阈值")
    shadow.add_argument("--shadow-no-signal-trigger", type=_positive_int,
                        default=2, help="已有正观测后的 no_signal 风险阈值")
    shadow.add_argument("--shadow-fast-no-shrink-limit", type=_positive_int,
                        default=8,
                        help="未确认满12个频道前，连续无有效收缩多少次后进入精确兜底")
    shadow.add_argument("--shadow-fast-no-shrink-limit-high",
                        type=_positive_int, default=5,
                        help="确认至少12个频道后，连续无有效收缩多少次后进入精确兜底")
    shadow.add_argument("--shadow-min-gain", type=_nonnegative_float,
                        default=5.0,
                        help="影子动作预测至少节省多少秒才接管")
    shadow.add_argument("--shadow-min-p-signal", type=_unit_interval,
                        default=0.20, help="影子动作最低保守接收概率")
    shadow.add_argument("--shadow-prior-directional", type=_unit_interval,
                        default=0.60, help="外生定向源比例先验均值")
    shadow.add_argument("--shadow-prior-strength", type=_nonnegative_float,
                        default=8.0, help="定向比例 beta 先验强度")
    shadow.add_argument("--shadow-quantile-z", type=_nonnegative_float,
                        default=1.645,
                        help="定向比例后验上分位数的正态近似 z 值")
    shadow.add_argument("--shadow-route",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="发现重定价后用多起点开放路径优化证书后缀")
    shadow.add_argument("--shadow-dynamic-scan-price",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="按剩余 UNKNOWN 证据逐步重定价扫描点")
    shadow.add_argument("--shadow-max-per-channel", type=_positive_int,
                        default=1, help="每个难源最多允许影子接管次数")
    shadow.add_argument("--shadow-global-budget", type=_positive_int,
                        default=4, help="整局影子接管次数上限")
    shadow.add_argument("--shadow-max-extra-immediate",
                        type=_nonnegative_float, default=100.0,
                        help="影子动作相对主动作允许增加的即时秒数")
    shadow.add_argument("--shadow-max-extra-at-cap",
                        type=_nonnegative_float, default=25.0,
                        help="在线确认16频道后允许增加的即时秒数")
    shadow.add_argument("--q4-discovery-p-threshold",
                        type=_unit_interval, default=0.01,
                        help="达到频道数门槛后，Q4机会扫描的后验概率阈值")
    shadow.add_argument("--q4-discovery-base-threshold",
                        type=_unit_interval, default=0.01,
                        help="达到频道数门槛前的保守后验概率阈值")
    shadow.add_argument("--q4-discovery-trigger-known", type=int, default=0,
                        help="确认至少这些存在频道后启用积极机会扫描")
    shadow.add_argument("--q4-discovery-max-channels", type=int, default=1,
                        help="每个机会停点最多补测多少个UNKNOWN；0=不限")
    shadow.add_argument("--shadow-tail-pool",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="确认足够频道后联合比较所有ACTIVE与READY路线")
    shadow.add_argument("--shadow-tail-route-weight",
                        type=_nonnegative_float, default=1.00,
                        help="联合尾程开放路径在动作评分中的权重")
    shadow.add_argument("--shadow-tail-min-known", type=int, default=16,
                        help="至少确认多少存在频道后启用联合尾程候选池")
    shadow.add_argument("--shadow-ready-batch-min", type=_positive_int,
                        default=1,
                        help="至少积累多少READY后才暂缓清除以批量排序；1=立即清除")
    shadow.add_argument("--shadow-tail-points-per-channel", type=int,
                        default=1, help="联合尾程为每个ACTIVE保留的候选测点数")
    shadow.add_argument("--shadow-tail-gain-weight",
                        type=_nonnegative_float, default=0.35,
                        help="联合尾程对测向收缩收益的秒/米权重")
    shadow.add_argument("--shadow-tail-region-route",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="尾程按访问顺序逐段投影到合法清除区域")
    shadow.add_argument("--shadow-global-enroute",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="按覆盖前缀+READY开放路线决定是否途中清除")
    shadow.add_argument("--shadow-global-enroute-horizon", type=int,
                        default=3, help="全局途中清除比较的覆盖前缀长度")
    shadow.add_argument("--shadow-global-enroute-margin",
                        type=_nonnegative_float, default=0.0,
                        help="全局路线允许插入清除的最大额外距离")
    shadow.add_argument("--shadow-enroute-detour",
                        type=_nonnegative_float, default=500.0,
                        help="覆盖途中插入READY/试清允许的最大绕路（米）")
    shadow.add_argument("--shadow-enroute-clear-region",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="READY顺路清除时在合法清除区内同时贴合覆盖前后两段")
    shadow.add_argument("--shadow-full-certificate-insert",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="仅当插入READY清除会缩短完整证书后续路线时才在证书前清除")
    shadow.add_argument("--shadow-full-certificate-insert-min-saving",
                        type=_nonnegative_float, default=25.0,
                        help="完整证书路线插入READY清除所需的最小净节省米数")
    shadow.add_argument("--shadow-full-certificate-insert-max-active",
                        type=int, default=-1,
                        help="插入READY清除时允许的最多ACTIVE数；-1=不限制")
    shadow.add_argument("--shadow-full-certificate-insert-scan",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="插入READY清除后是否机会测量频道")
    shadow.add_argument("--shadow-certificate-dp-insert",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="在固定证书顺序中用DP联合插入READY清除")
    shadow.add_argument("--shadow-certificate-dp-max-active",
                        type=int, default=2,
                        help="证书DP插入允许的最多ACTIVE数")
    shadow.add_argument("--shadow-certificate-dp-max-ready",
                        type=int, default=3,
                        help="证书DP插入允许的最多READY数（风险门槛）")
    shadow.add_argument("--shadow-certificate-dp-min-unknown",
                        type=int, default=10,
                        help="证书DP插入所需的最少UNKNOWN数")
    shadow.add_argument("--shadow-certificate-dp-min-saving",
                        type=_nonnegative_float, default=0.0,
                        help="证书DP插入所需的最小预测总路程节省米数")
    shadow.add_argument("--shadow-early-cover-points", type=int, default=0,
                        help="ACTIVE可行域的20米精确覆盖点不超过此数时提前清除；0=关闭")
    shadow.add_argument("--shadow-early-cover-entry",
                        type=_nonnegative_float, default=None,
                        help="提前精确覆盖首点最大前往距离（米）")
    shadow.add_argument("--shadow-joint-active-limit", type=int, default=3,
                        help="每个Q4覆盖停点最多顺带补测多少个ACTIVE")
    shadow.add_argument("--shadow-joint-min-mec", type=_nonnegative_float,
                        default=0.0,
                        help="Q4 ACTIVE MEC半径不大于此值时停止在证书站顺带补测；0=关闭")
    shadow.add_argument("--shadow-joint-min-p-signal", type=_unit_interval,
                        default=0.30,
                        help="Q4证书站顺带ACTIVE补测所需的最小保守接收概率；0=关闭")
    shadow.add_argument("--shadow-probe-remeasure",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="Q4试探清除失败后原地补测同一ACTIVE频道")
    shadow.add_argument("--shadow-inplace-shots", type=int, default=0,
                        choices=(0, 2, 3),
                        help="Q4小MEC试探失败后原地追加的有限清除数；0=关闭")
    shadow.add_argument("--shadow-discovery-ring",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="高密度Q4先走870米十二点发现环，不足16再回严格证书")
    shadow.add_argument("--shadow-discovery-ring-threshold", type=int,
                        default=6, help="原点至少发现多少频道才继续紧凑发现环")
    shadow.add_argument("--shadow-discovery-ring-radius", type=_positive_float,
                        default=870.0, help="Q4紧凑发现环的半径米数")
    shadow.add_argument("--shadow-discovery-ring-points", type=_positive_int,
                        default=12, help="Q4紧凑发现环的停点数")
    shadow.add_argument("--shadow-observed-order",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="用原点观测在Q4证书最短路附近选择访问方向")
    shadow.add_argument("--shadow-observed-order-fraction",
                        type=_unit_interval, default=0.10,
                        help="Q4证书顺序允许为早发现牺牲的相对路程")
    shadow.add_argument("--shadow-oriented-certificate-order",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="首站观测在等长稀疏25点证书遍历中选择朝向")
    shadow.add_argument("--shadow-oriented-certificate-mode",
                        choices=("tail", "front"), default="tail",
                        help="等长证书朝向按末端尾程或首段定位几何选择")
    shadow.add_argument("--shadow-stop-channel-order",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="覆盖停点内按Q4后验接收概率优先测UNKNOWN")
    shadow.add_argument("--shadow-coverage-deferral",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="覆盖强制前允许一次有冷却的ACTIVE补测")
    shadow.add_argument("--shadow-deferral-min-active", type=int, default=6,
                        help="触发一次性覆盖让步所需ACTIVE数量")
    shadow.add_argument("--shadow-deferral-budget", type=int, default=4,
                        help="整局最多允许的覆盖让步次数")
    shadow.add_argument("--shadow-deferral-margin",
                        type=_nonnegative_float, default=0.0,
                        help="ACTIVE评分需领先覆盖至少多少秒")
    shadow.add_argument("--shadow-segment-active",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="Q4在强制证书线段内插入零绕路的ACTIVE补测")
    shadow.add_argument("--shadow-segment-min-value",
                        type=_nonnegative_float, default=80.0,
                        help="Q4零绕路ACTIVE补测的最小几何价值")
    shadow.add_argument("--shadow-discovery-order",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="使用按最晚源发现时间离线优化的固定sparse25顺序")
    shadow.add_argument("--shadow-fallback-order",
                        choices=("greedy", "center", "center_route",
                                 "route_center", "bearing"),
                        default="greedy",
                        help="Q4有限覆盖兜底点的访问顺序")
    shadow.add_argument("--shadow-fallback-posterior",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="按位置后验命中率/前往成本排序完整兜底覆盖")
    compact.add_argument("--compact-shape-cover", action="store_true",
                         help="细长可行域使用解析条带清除覆盖")
    compact.add_argument("--compact-route-free-probe-radius",
                         type=_nonnegative_float, default=0.0,
                         help="已决定前往的ACTIVE补测点先试清；0=关闭")
    compact.add_argument("--compact-local-finish-steps", type=int, default=0,
                         help="进入ACTIVE邻域后最多连续追加的补测次数；0=关闭")
    compact.add_argument("--compact-local-finish-budget",
                         type=_nonnegative_float, default=0.0,
                         help="单源连续收尾允许的追加移动米数")
    compact.add_argument("--compact-local-finish-max-radius",
                         type=_nonnegative_float, default=80.0)
    compact.add_argument("--compact-local-finish-min-shrink",
                         type=_nonnegative_float, default=0.05)
    compact.add_argument("--compact-local-finish-min-known", type=int,
                         default=0)
    compact.add_argument("--compact-terminal-scan-radius",
                         type=_nonnegative_float, default=0.0,
                         help="环上额外评估可一次进入清除的ACTIVE；0=关闭")
    compact.add_argument("--compact-terminal-scan-worst",
                         type=_nonnegative_float, default=20.0,
                         help="环上终局测量预测的最大后验MEC半径")
    compact.add_argument("--compact-post-clear-worst",
                         type=_nonnegative_float, default=0.0,
                         help="清除停点仅顺测最坏后验半径不超过该值的ACTIVE；0=历史自动扫描")
    compact.add_argument("--compact-joint-ring-route", action="store_true",
                         help="把剩余覆盖锚点与READY/小ACTIVE放入同一开放路径")
    compact.add_argument("--compact-joint-ring-max-known", type=int, default=0,
                         help="达到该已发现数后停止源节点牵引，仅收锚点；0=不门控")
    compact.add_argument("--compact-joint-ring-min-stops", type=int, default=0,
                         help="至少访问这些环锚点后才允许源节点牵引")
    compact.add_argument("--compact-joint-ring-active-radius",
                         type=_nonnegative_float, default=None,
                         help="联合环路可插入 ACTIVE 的 MEC 半径；默认沿用环上80m门槛")
    compact.add_argument("--compact-joint-ring-active-attempts", type=int,
                         default=None,
                         help="每个 ACTIVE 在证书阶段最多被插入几次；默认沿用尾段次数")
    compact.add_argument("--compact-joint-ring-min-directions", type=int,
                         default=1,
                         help="ACTIVE 参与联合环路前至少需要的真实 direction 观测数")
    compact.add_argument("--compact-joint-ring-service-worst",
                         type=_nonnegative_float, default=0.0,
                         help="服务停点顺测 ACTIVE 的最坏后验 MEC 半径；0=关闭")
    compact.add_argument("--compact-joint-ring-or-opt", action="store_true",
                         help="联合环路节点超过16时，在2-opt后启用1/2节点重插入")
    compact.add_argument("--compact-joint-clear-witness", action="store_true",
                         help="联合路线上 READY 清除点也扫描 UNKNOWN，并精确裁掉冗余锚点")
    compact.add_argument("--compact-joint-clear-witness-useful-only",
                         action="store_true",
                         help="仅当清除点扫描可删至少一个后续锚点时，才执行 UNKNOWN 见证扫描")
    compact.add_argument("--compact-joint-clear-witness-max-unknown",
                         type=int, default=0,
                         help="见证扫描时最多允许的 UNKNOWN 数；0=不按数量限制")
    compact.add_argument("--compact-joint-anchor-substitution",
                         action="store_true",
                         help="READY清除点若可替换未访问锚点，则融合清除与该锚点的 UNKNOWN 扫描")
    compact.add_argument("--compact-joint-anchor-substitution-max-unknown",
                         type=int, default=0,
                         help="锚点替代扫描时最多允许的 UNKNOWN 数；0=不按数量限制")
    compact.add_argument("--compact-service-certificate", action="store_true",
                         help="让已知源停点扫描 UNKNOWN，并在精确覆盖仍成立时替换未来锚点")
    compact.add_argument("--compact-service-certificate-radius",
                         type=_nonnegative_float, default=250.0,
                         help="可作为证书服务点的 ACTIVE MEC 半径上限米数")
    compact.add_argument("--compact-service-certificate-max-services",
                         type=int, default=8,
                         help="每次决策枚举的服务停点上限")
    compact.add_argument("--compact-service-certificate-depth", type=int,
                         default=2,
                         help="联合替换的服务点/锚点数，范围 1--3")
    compact.add_argument("--compact-service-certificate-active-candidates",
                         type=int, default=1,
                         help="每个 ACTIVE 供证书替代搜索的测向候选数；1=原局部测点")
    compact.add_argument("--compact-service-certificate-rollout",
                         action="store_true",
                         help="用完整观测回放决定服务停点证书模板；需同时设置覆盖回放预算")
    compact.add_argument("--compact-service-certificate-min-saving",
                         type=_nonnegative_float, default=35.0,
                         help="替换锚点所需的剩余路径净节省米数")
    compact.add_argument("--compact-tail-rollout-budget",
                         type=_nonnegative_float, default=0.0,
                         help="所有频道已确认后的后验回放搜索现实秒预算；0=关闭")
    compact.add_argument("--compact-tail-rollout-worlds", type=_positive_int,
                         default=4, help="每次尾段回放的观测相容假设地图数")
    compact.add_argument("--compact-tail-rollout-candidates", type=_positive_int,
                         default=10, help="每次尾段回放比较的根动作上限")
    compact.add_argument("--compact-tail-rollout-margin",
                         type=_nonnegative_float, default=15.0,
                         help="候选预计节省至少多少虚拟秒才接管")
    compact.add_argument("--compact-tail-rollout-min-win-fraction",
                         type=_unit_interval, default=0.75,
                         help="候选必须在此比例的假设地图中优于基线")
    compact.add_argument("--compact-tail-rollout-objective",
                         choices=("mean", "median"), default="median")
    compact.add_argument("--compact-tail-rollout-step-limit", type=_positive_int,
                         default=180, help="每条假设回放的最大后续动作数")
    compact.add_argument("--compact-coverage-rollout-budget",
                         type=_nonnegative_float, default=0.0,
                         help="覆盖中有限源服务支线的现实秒预算；0=关闭")
    compact.add_argument("--compact-coverage-rollout-worlds", type=_positive_int,
                         default=3, help="每个覆盖支线回放的观测相容假设地图数")
    compact.add_argument("--compact-coverage-rollout-candidates",
                         type=_positive_int, default=5,
                         help="每个覆盖点比较的源服务支线数")
    compact.add_argument("--compact-coverage-rollout-points", type=_positive_int,
                         default=3, help="每个源交给完整成本比较的测量点数")
    compact.add_argument("--compact-coverage-rollout-service-scan",
                         action="store_true",
                         help="支线服务停点同时扫描 UNKNOWN，由完整成本回放决定是否值回票价")
    compact.add_argument("--compact-coverage-rollout-service-channels",
                         type=int, default=0,
                         help="服务扫描另比较 proximity 排序 UNKNOWN 前缀；0=只比较全扫")
    compact.add_argument("--compact-coverage-rollout-post-service-scan",
                         action="store_true",
                         help="实验：源补测后原地扫描UNKNOWN再重排；默认关闭")
    compact.add_argument("--compact-coverage-rollout-margin",
                         type=_nonnegative_float, default=10.0,
                         help="支线预计节省至少多少虚拟秒才接管")
    compact.add_argument("--compact-coverage-rollout-min-win-fraction",
                         type=_unit_interval, default=0.75,
                         help="支线必须在此比例的相容地图中优于继续覆盖")
    compact.add_argument("--compact-coverage-branch-actions", type=_positive_int,
                         default=2, help="离开覆盖主线后最多执行的源服务动作数")
    compact.add_argument("--compact-coverage-branch-detour",
                         type=_nonnegative_float, default=350.0,
                         help="源服务支线相对直达原覆盖点的最大额外移动米数")
    compact.add_argument("--compact-coverage-rollout-step-limit", type=_positive_int,
                         default=220, help="每条覆盖支线回放的最大后续动作数")
    compact.add_argument("--compact-acif-translate", type=_nonnegative_float,
                         default=0.0,
                         help="ACIF：将未访问证书锚点向已知任务平移的单轮上限米数；0=关闭")
    compact.add_argument("--compact-acif-margin", type=_nonnegative_float,
                         default=0.0,
                         help="ACIF 移动后要求保留的 Q3 边界覆盖余量米数")
    compact.add_argument("--compact-acif-route-aware", action="store_true",
                         help="ACIF 仅接受能缩短剩余证书+已知任务开放路径的平移")
    compact.add_argument("--compact-acif-min-route-gain",
                         type=_nonnegative_float, default=1.0,
                         help="route-aware ACIF 接受一次锚点平移所需的最小预计节路米数")
    compact.add_argument("--compact-acif-active-target-radius",
                         type=_nonnegative_float, default=0.0,
                         help="ACIF 可对 MEC 半径不超过该值的 ACTIVE 目标对齐；0=保留仅近源中心目标")
    compact.add_argument("--compact-adaptive-ring-points", type=int, default=0,
                         help="首站低发现率时改用的 Q3 证书总点数；0=关闭")
    compact.add_argument("--compact-adaptive-ring-radius",
                         type=_nonnegative_float, default=0.0,
                         help="自适应替代环半径（米）；必须和点数构成有效 Q3 覆盖")
    compact.add_argument("--compact-adaptive-ring-known-max", type=int,
                         default=-1,
                         help="首站已发现频道数不超过此值时才改环；-1=关闭")
    compact.add_argument("--compact-adaptive-ring-rollout", action="store_true",
                         help="用观测相容完整回放比较原证书与自适应替代环；需同时设置覆盖回放预算")
    parser.add_argument("--model", default=None,
                        help="learned/rollout 基础策略的模型 JSON；省略时使用包内模型")
    parser.add_argument("--seed", type=int, default=None,
                        help="合成模式随机种子；官方模式不使用")
    parser.add_argument("--n-sources", type=int, default=None,
                        help="合成模式源数；官方模式不使用")
    parser.add_argument("--scenario", choices=SCENARIOS, default="random",
                        help="合成模式场景")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="结果目录；默认写入 src/q3+4_v2/runs/")
    parser.add_argument("--max-steps", type=int, default=20000,
                        help="策略循环安全上限")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="HTTP 单次请求超时（秒）")
    parser.add_argument("--q4-certificate-layout",
                        choices=("sparse25", "lattice31"), default="sparse25",
                        help="Q4 证书停点布局")
    parser.add_argument("--scan-mode", choices=SCAN_MODES, default=None,
                        help="停点顺带扫描模式；默认 Q3 selective_clear、Q4 state_aware")
    parser.add_argument("--active-scan-margin", type=float, default=None,
                        help="ACTIVE 顺带扫描的额外距离余量（米）")
    return parser


def _build_scheduler(scheduler_cls, mode, kwargs):
    """Construct the scheduler, dropping only keys its class chain rejects.

    ``production.py`` publishes one flat configuration for the whole policy
    suite.  A scheduler that accepts the whole dict is built with the dict
    untouched, so the production routes keep their exact behaviour.  Only when
    the constructor raises ``TypeError`` for an unknown keyword -- e.g.
    ``--policy geometry``, whose chain reaches ``Scheduler.__init__`` that
    declares no ``**kwargs`` -- is exactly that key removed and the build
    retried.  No other value is ever altered.

    Returns ``(scheduler, effective_kwargs, dropped_keys)``.
    """
    import re

    pattern = re.compile(r"unexpected keyword argument '([^']+)'")
    remaining = dict(kwargs)
    dropped = []
    while True:
        try:
            scheduler = scheduler_cls(mode, **remaining)
        except TypeError as exc:
            match = pattern.search(str(exc))
            name = match.group(1) if match else None
            if name is None or name not in remaining:
                raise
            dropped.append(name)
            remaining.pop(name)
            continue
        return scheduler, remaining, dropped


def _scheduler_kwargs(mode, args):
    """Production scheduler configuration, plus CLI overrides.

    The defaults come from ``production.py`` so the official entry runs the
    exact policy that the local benchmark scores.  Runner-owned keys are split
    out here and never reach the scheduler constructor.
    """
    overrides = {
        "q4_certificate_layout": args.q4_certificate_layout,
        "max_steps": args.max_steps,
    }
    if args.scan_mode:
        overrides["channel_scan_mode"] = args.scan_mode
    if args.active_scan_margin is not None:
        overrides["active_scan_margin_m"] = args.active_scan_margin
    kwargs, _runner = production.split_config(mode, **overrides)
    if args.policy in ("learned", "belief-rollout", "constraint-search",
                       "constraint-macro", "compact-ring", "q4-bisect",
                       "q4-shadow") and args.model:
        kwargs["model_path"] = args.model
    if args.policy == "belief-rollout":
        kwargs.update(br_worlds=args.rollout_worlds,
                      br_candidates=args.rollout_candidates,
                      br_period=args.rollout_every,
                      br_budget_s=args.rollout_budget,
                      br_margin_s=args.rollout_margin,
                      br_min_win_fraction=args.rollout_min_win_fraction,
                      br_objective=args.rollout_objective,
                      br_clear_radius=args.rollout_clear_radius,
                      br_clear_candidates=args.rollout_clear_candidates,
                      br_clear_only=args.rollout_clear_only,
                      br_step_limit=args.rollout_step_limit)
    if args.policy in ("constraint-macro", "compact-ring"):
        kwargs.update(segment_budget=(args.compact_search_budget
                                      if args.policy == "compact-ring"
                                      else args.segment_budget),
                      segment_worlds=args.segment_worlds,
                      segment_margin=args.segment_margin,
                      segment_min_win_fraction=args.segment_min_win_fraction)
    if args.policy == "compact-ring":
        kwargs.update(compact_ring_radius=args.compact_ring_radius,
                      compact_ring_points=args.compact_ring_points,
                      compact_ring_active_max_directions=
                      args.compact_ring_active_max_directions,
                      compact_center_anchor=args.compact_center_anchor,
                      compact_center_warmup_resultant_threshold=
                      args.compact_center_warmup_resultant_threshold,
                      compact_center_warmup_min_stops=
                      args.compact_center_warmup_min_stops,
                      compact_coverage_optical_max_points=
                      args.compact_coverage_optical_max_points,
                      compact_coverage_optical_max_entries=
                      args.compact_coverage_optical_max_entries,
                      compact_coverage_optical_max_entry_m=
                      args.compact_coverage_optical_max_entry,
                      compact_active_stop_radius=args.compact_active_stop_radius,
                      compact_enroute_clear_radius=args.compact_enroute_clear_radius,
                      compact_enroute_detour=args.compact_enroute_detour,
                      compact_probe_radius=args.compact_probe_radius,
                      compact_optical_cover_points=args.compact_optical_cover_points,
                      compact_truncate_active_at_cardinality=
                      not args.compact_finish_active_at_cap,
                      compact_route_active=args.compact_route_active,
                      compact_route_active_attempts=
                      args.compact_route_active_attempts,
                      compact_enroute_measure_detour=
                      args.compact_enroute_measure_detour,
                      compact_route_cluster_radius=
                      args.compact_route_cluster_radius,
                      compact_route_cluster_max=args.compact_route_cluster_max,
                      compact_route_cluster_min_saving=
                      args.compact_route_cluster_min_saving,
                      compact_route_alternatives=args.compact_route_alternatives,
                      compact_fusion_budget=args.compact_fusion_budget,
                      compact_fusion_worlds=args.compact_fusion_worlds,
                      compact_fusion_margin=args.compact_fusion_margin,
                      compact_fusion_views_only=args.compact_fusion_views_only,
                      compact_clear_region_route=args.compact_clear_region_route,
                      compact_route_quality_slack=args.compact_route_quality_slack,
                      compact_route_point_passes=args.compact_route_point_passes,
                      compact_shape_cover=args.compact_shape_cover,
                      compact_route_free_probe_radius=
                      args.compact_route_free_probe_radius,
                      compact_local_finish_steps=args.compact_local_finish_steps,
                      compact_local_finish_budget=args.compact_local_finish_budget,
                      compact_local_finish_max_radius=
                      args.compact_local_finish_max_radius,
                      compact_local_finish_min_shrink=
                      args.compact_local_finish_min_shrink,
                      compact_local_finish_min_known=
                      args.compact_local_finish_min_known,
                      compact_terminal_scan_radius=
                      args.compact_terminal_scan_radius,
                      compact_terminal_scan_worst=
                      args.compact_terminal_scan_worst,
                      compact_post_clear_worst=
                      args.compact_post_clear_worst,
                      compact_joint_ring_route=
                      args.compact_joint_ring_route,
                      compact_joint_ring_max_known=
                      args.compact_joint_ring_max_known,
                      compact_joint_ring_min_stops=
                      args.compact_joint_ring_min_stops,
                      compact_joint_ring_active_radius=
                      args.compact_joint_ring_active_radius,
                      compact_joint_ring_active_attempts=
                      args.compact_joint_ring_active_attempts,
                      compact_joint_ring_min_directions=
                      args.compact_joint_ring_min_directions,
                      compact_joint_ring_service_worst=
                      args.compact_joint_ring_service_worst,
                      compact_joint_ring_or_opt=args.compact_joint_ring_or_opt,
                      compact_joint_clear_witness=
                      args.compact_joint_clear_witness,
                      compact_joint_clear_witness_useful_only=
                      args.compact_joint_clear_witness_useful_only,
                      compact_joint_clear_witness_max_unknown=
                      args.compact_joint_clear_witness_max_unknown,
                      compact_joint_anchor_substitution=
                      args.compact_joint_anchor_substitution,
                      compact_joint_anchor_substitution_max_unknown=
                      args.compact_joint_anchor_substitution_max_unknown,
                      compact_service_certificate=
                      args.compact_service_certificate,
                      compact_service_certificate_radius=
                      args.compact_service_certificate_radius,
                      compact_service_certificate_max_services=
                      args.compact_service_certificate_max_services,
                      compact_service_certificate_depth=
                      args.compact_service_certificate_depth,
                      compact_service_certificate_active_candidates=
                      args.compact_service_certificate_active_candidates,
                      compact_service_certificate_rollout=
                      args.compact_service_certificate_rollout,
                      compact_service_certificate_min_saving_m=
                      args.compact_service_certificate_min_saving,
                      compact_tail_rollout_budget=args.compact_tail_rollout_budget,
                      compact_tail_rollout_worlds=args.compact_tail_rollout_worlds,
                      compact_tail_rollout_candidates=
                      args.compact_tail_rollout_candidates,
                      compact_tail_rollout_margin_s=
                      args.compact_tail_rollout_margin,
                      compact_tail_rollout_min_win_fraction=
                      args.compact_tail_rollout_min_win_fraction,
                      compact_tail_rollout_objective=
                      args.compact_tail_rollout_objective,
                      compact_tail_rollout_step_limit=
                      args.compact_tail_rollout_step_limit,
                      compact_coverage_rollout_budget=
                      args.compact_coverage_rollout_budget,
                      compact_coverage_rollout_worlds=
                      args.compact_coverage_rollout_worlds,
                      compact_coverage_rollout_candidates=
                      args.compact_coverage_rollout_candidates,
                      compact_coverage_rollout_points=
                      args.compact_coverage_rollout_points,
                      compact_coverage_rollout_service_scan=
                      args.compact_coverage_rollout_service_scan,
                      compact_coverage_rollout_service_channels=
                      args.compact_coverage_rollout_service_channels,
                      compact_coverage_rollout_post_service_scan=
                      args.compact_coverage_rollout_post_service_scan,
                      compact_coverage_rollout_margin_s=
                      args.compact_coverage_rollout_margin,
                      compact_coverage_rollout_min_win_fraction=
                      args.compact_coverage_rollout_min_win_fraction,
                      compact_coverage_branch_actions=
                      args.compact_coverage_branch_actions,
                      compact_coverage_branch_detour_m=
                      args.compact_coverage_branch_detour,
                      compact_coverage_rollout_step_limit=
                      args.compact_coverage_rollout_step_limit,
                      compact_acif_translate_m=args.compact_acif_translate,
                      compact_acif_translate_margin_m=args.compact_acif_margin,
                      compact_acif_route_aware=args.compact_acif_route_aware,
                      compact_acif_min_route_gain_m=
                      args.compact_acif_min_route_gain,
                      compact_acif_active_target_radius=
                      args.compact_acif_active_target_radius,
                      compact_adaptive_ring_points=
                      args.compact_adaptive_ring_points,
                      compact_adaptive_ring_radius=
                      args.compact_adaptive_ring_radius,
                      compact_adaptive_ring_known_max=
                      args.compact_adaptive_ring_known_max,
                      compact_adaptive_ring_rollout=
                      args.compact_adaptive_ring_rollout)
    if args.policy in ("q4-bisect", "q4-shadow"):
        kwargs.update(q4_bisect_enabled=args.q4_bisect_enabled,
                      q4_bisect_tail_only=args.q4_bisect_tail_only,
                      q4_bisect_max_axial_m=args.q4_bisect_max_axial,
                      q4_bisect_ready_first=args.q4_bisect_ready_first,
                      q4_bisect_min_no_shrink=args.q4_bisect_min_no_shrink,
                      q4_bisect_max_rounds=args.q4_bisect_max_rounds,
                      q4_bisect_enroute_detour_m=
                      args.q4_bisect_enroute_detour,
                      q4_bisect_min_known=args.q4_bisect_min_known,
                      q4_bisect_min_area_m2=args.q4_bisect_min_area,
                      q4_bisect_global_round_budget=
                      args.q4_bisect_round_budget)
    if args.policy == "q4-shadow":
        kwargs.update(
            shadow_enabled=args.shadow_enabled,
            shadow_min_spacing_m=args.shadow_min_spacing,
            shadow_no_shrink_trigger=args.shadow_no_shrink_trigger,
            shadow_measure_trigger=args.shadow_measure_trigger,
            shadow_no_signal_trigger=args.shadow_no_signal_trigger,
            q4_no_shrink_limit=args.shadow_fast_no_shrink_limit,
            q4_no_shrink_limit_high=
            args.shadow_fast_no_shrink_limit_high,
            shadow_min_takeover_gain_s=args.shadow_min_gain,
            shadow_min_signal_probability=args.shadow_min_p_signal,
            shadow_prior_directional=args.shadow_prior_directional,
            shadow_prior_strength=args.shadow_prior_strength,
            shadow_quantile_z=args.shadow_quantile_z,
            shadow_route_enabled=args.shadow_route,
            shadow_dynamic_scan_price=args.shadow_dynamic_scan_price,
            shadow_max_takeovers_per_channel=args.shadow_max_per_channel,
            shadow_global_takeover_budget=args.shadow_global_budget,
            shadow_max_extra_immediate_s=args.shadow_max_extra_immediate,
            shadow_max_extra_at_cap_s=args.shadow_max_extra_at_cap,
            q4_discovery_probability_threshold=
            args.q4_discovery_p_threshold,
            q4_discovery_probability_base_threshold=
            args.q4_discovery_base_threshold,
            q4_discovery_probability_trigger_known=
            args.q4_discovery_trigger_known,
            q4_discovery_max_channels_per_stop=
            args.q4_discovery_max_channels,
            shadow_tail_pool_enabled=args.shadow_tail_pool,
            shadow_tail_route_weight=args.shadow_tail_route_weight,
            shadow_tail_pool_min_known=args.shadow_tail_min_known,
            ready_batch_min=args.shadow_ready_batch_min,
            shadow_tail_points_per_channel=
            args.shadow_tail_points_per_channel,
            shadow_tail_gain_weight=args.shadow_tail_gain_weight,
            shadow_tail_region_route=args.shadow_tail_region_route,
            shadow_global_enroute=args.shadow_global_enroute,
            shadow_global_enroute_horizon=
            args.shadow_global_enroute_horizon,
            shadow_global_enroute_margin_m=
            args.shadow_global_enroute_margin,
            rolling_enroute_detour_m=args.shadow_enroute_detour,
            shadow_enroute_clear_region=args.shadow_enroute_clear_region,
            shadow_full_certificate_insert=
            args.shadow_full_certificate_insert,
            shadow_full_certificate_insert_min_saving_m=
            args.shadow_full_certificate_insert_min_saving,
            shadow_full_certificate_insert_max_active=
            args.shadow_full_certificate_insert_max_active,
            shadow_full_certificate_insert_scan=
            args.shadow_full_certificate_insert_scan,
            shadow_certificate_dp_insert=
            args.shadow_certificate_dp_insert,
            shadow_certificate_dp_max_active=
            args.shadow_certificate_dp_max_active,
            shadow_certificate_dp_max_ready=
            args.shadow_certificate_dp_max_ready,
            shadow_certificate_dp_min_unknown=
            args.shadow_certificate_dp_min_unknown,
            shadow_certificate_dp_min_saving_m=
            args.shadow_certificate_dp_min_saving,
            early_fallback_max_points=args.shadow_early_cover_points,
            early_fallback_max_entry_m=args.shadow_early_cover_entry,
            rolling_joint_active_limit=args.shadow_joint_active_limit,
            q4_joint_min_mec_m=args.shadow_joint_min_mec,
            shadow_joint_min_signal_probability=
            args.shadow_joint_min_p_signal,
            rolling_probe_remeasure=args.shadow_probe_remeasure,
            rolling_inplace_shots=args.shadow_inplace_shots,
            q4_discovery_ring=args.shadow_discovery_ring,
            q4_discovery_threshold=args.shadow_discovery_ring_threshold,
            q4_discovery_ring_radius_m=args.shadow_discovery_ring_radius,
            q4_discovery_ring_points=args.shadow_discovery_ring_points,
            q4_observed_order=args.shadow_observed_order,
            q4_observed_order_fraction=
            args.shadow_observed_order_fraction,
            shadow_stop_channel_order=args.shadow_stop_channel_order,
            shadow_coverage_deferral=args.shadow_coverage_deferral,
            shadow_coverage_deferral_min_active=
            args.shadow_deferral_min_active,
            shadow_coverage_deferral_budget=args.shadow_deferral_budget,
            shadow_coverage_deferral_margin_s=args.shadow_deferral_margin,
            shadow_segment_active=args.shadow_segment_active,
            shadow_segment_min_value=args.shadow_segment_min_value,
            shadow_discovery_order=args.shadow_discovery_order,
            shadow_oriented_certificate_order=
            args.shadow_oriented_certificate_order,
            shadow_oriented_certificate_mode=
            args.shadow_oriented_certificate_mode,
            fallback_order_mode=args.shadow_fallback_order,
            shadow_fallback_posterior=args.shadow_fallback_posterior)
    return kwargs


def _runner_config(mode, args):
    overrides = {
        "q4_certificate_layout": args.q4_certificate_layout,
        "max_steps": args.max_steps,
    }
    if args.scan_mode:
        overrides["channel_scan_mode"] = args.scan_mode
    if args.active_scan_margin is not None:
        overrides["active_scan_margin_m"] = args.active_scan_margin
    return MainlineConfig(**production.runner_kwargs(mode, **overrides))


def _make_backend(mode, args, seed):
    """Return ``(backend, simulator, http_server)`` for one run."""
    if args.sim == "http":
        client = ApiClient(args.base_url, timeout=args.timeout,
                           robot_id=args.robot_id)
        return Session(client, robot_id=args.robot_id), None, None

    simulator = SyntheticSimulator(
        mode, seed, n_sources=args.n_sources, scenario=args.scenario)
    if args.sim == "synthetic":
        return SimulatorBackend(simulator, robot_id=args.robot_id), simulator, None

    server = SimulatorHTTPServer(simulator).start()
    client = ApiClient(server.url, timeout=args.timeout,
                       robot_id=args.robot_id)
    return Session(client, robot_id=args.robot_id), simulator, server


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.compact_joint_service_preset:
        # This is intentionally an explicit experiment preset, not a hidden
        # production default.  It has a paired Q3/15 improvement record but
        # must still be checked on the actual evaluation distribution.
        args.compact_performance_preset = True
        args.compact_joint_ring_route = True
        args.compact_joint_ring_active_radius = 200.0
        args.compact_joint_ring_service_worst = 20.0
        args.compact_joint_anchor_substitution = True
    if args.compact_performance_preset:
        args.compact_terminal_scan_radius = 80.0
        args.compact_terminal_scan_worst = 20.0
        args.compact_local_finish_steps = 2
        args.compact_local_finish_budget = 300.0
        args.compact_local_finish_max_radius = 80.0
        args.compact_local_finish_min_shrink = 0.05
        args.compact_local_finish_min_known = 14
    mode = args.mode.upper()
    if args.policy in ("constraint-search", "constraint-macro", "compact-ring") and mode != "Q3":
        raise SystemExit("constraint policies currently support --mode q3 only")
    if args.policy in ("q4-bisect", "q4-shadow") and mode != "Q4":
        raise SystemExit("q4-bisect/q4-shadow currently support --mode q4 only")

    seed = args.seed
    if args.sim != "http" and seed is None:
        seed = random.randint(0, 2 ** 31 - 1)

    label = "remote" if args.sim == "http" else str(seed)
    policy_label = (args.policy + "_" if args.policy in
                    ("belief-rollout", "constraint-search",
                     "constraint-macro", "compact-ring", "q4-bisect",
                     "q4-shadow") else "")
    output_dir = args.output_dir or HERE / "runs" / (
        f"{args.mode}_{policy_label}{args.sim}_{label}")

    backend, simulator, server = _make_backend(mode, args, seed)
    try:
        runner = V2GameRunner(
            mode,
            ActionExecutor(backend),
            str(output_dir),
            simulator=simulator,
            max_steps=args.max_steps,
            config=_runner_config(mode, args),
        )
        scheduler_cls = SCHEDULERS[args.policy]
        # One flat production configuration.  The builder drops a key only when
        # the scheduler's own class chain rejects it, so the production routes
        # keep their exact behaviour while every registered route constructs.
        scheduler_config = _scheduler_kwargs(mode, args)
        scheduler, effective_config, dropped_keys = _build_scheduler(
            scheduler_cls, mode, scheduler_config)
        runner.attach_scheduler(scheduler)
        if dropped_keys:
            print("[policy] %s: dropped keys not accepted by %s: %s"
                  % (args.policy, scheduler_cls.__name__, dropped_keys))
        production.dump_policy_snapshot(
            output_dir, mode, scheduler_config,
            vars(runner.config))
        report = runner.run()
        if args.policy in ("constraint-macro", "compact-ring"):
            (output_dir / "segment_search.json").write_text(json.dumps(
                {"stats": runner.scheduler.segment_stats,
                 "decisions": runner.scheduler.segment_log}, indent=2), encoding="utf-8")
        if args.policy == "compact-ring":
            (output_dir / "stop_fusion.json").write_text(json.dumps(
                {"stats": runner.scheduler.fusion_stats,
                 "decisions": runner.scheduler.fusion_log}, indent=2), encoding="utf-8")
            (output_dir / "coverage_rollout.json").write_text(json.dumps(
                {"stats": runner.scheduler.coverage_rollout_stats,
                 "decisions": runner.scheduler.coverage_rollout_log},
                indent=2), encoding="utf-8")
            (output_dir / "tail_rollout.json").write_text(json.dumps(
                {"stats": runner.scheduler.tail_rollout_stats,
                 "decisions": runner.scheduler.tail_rollout_log},
                indent=2), encoding="utf-8")
            (output_dir / "compact_ring.json").write_text(json.dumps(
                runner.scheduler.compact_stats, indent=2), encoding="utf-8")
        if args.policy in ("q4-bisect", "q4-shadow"):
            (output_dir / "q4_bisect.json").write_text(json.dumps(
                runner.scheduler.q4_bisect_stats, indent=2), encoding="utf-8")
        if args.policy == "q4-shadow":
            (output_dir / "q4_shadow.json").write_text(json.dumps(
                runner.scheduler.shadow_stats, ensure_ascii=False, indent=2),
                encoding="utf-8")
        if args.policy == "belief-rollout":
            (output_dir / "rollout_search.json").write_text(
                json.dumps({"stats": runner.scheduler.rollout_stats,
                            "decisions": runner.scheduler.rollout_log},
                           ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if server is not None:
            server.shutdown()

    report = _augment_per_source_metrics(report, output_dir)
    summary = report_line(report)
    summary.update({
        "mode": mode,
        "sim": args.sim,
        "policy": args.policy,
        "output_dir": str(output_dir),
    })
    if args.policy == "belief-rollout":
        summary["rollout"] = runner.scheduler.rollout_stats
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report.get("complete") and report.get("verifier_all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())





