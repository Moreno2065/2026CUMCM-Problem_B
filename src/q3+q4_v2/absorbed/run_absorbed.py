# -*- coding: utf-8 -*-
"""吸收引擎统一入口：Q3 v5 / Q4 v4 直接驱动 v2 运行栈。

契约（captain 固定，名字不改）：

    --mode {q3,q4}  --engine {q3-v5,q4-v4}（默认按 mode 选）
    --sim {http,http-synthetic}（本项目另加 synthetic，见下）
    --base-url --robot-id --seed --n-sources --scenario --output-dir

行为：q3 调 ``absorbed.q3_v5.q3_optimizer_v5.solve_optimized_v5(client)``；
q4 调 ``absorbed.q4_v4.locked.solve_locked(client)``。跑完写
``metrics.json`` / ``run_report.json``（另有 ``verifier_report.json`` /
``engine_result.json`` / ``actions.csv`` / ``api_log.jsonl``），stdout 打一行
摘要；**退出码 0 仅当跑完且 verifier 通过，否则 1**（参数错误 2）。

已登记的降级（与 ``ABSORBED_SOLVERS.md`` 同步，落进 run_report.json）：

1. ``accepted=false``：v2 可返回该响应而源引擎的 offline world 不存在该状态，
   默认 ``--on-reject raise`` 直接失败，**不**把它当成 ``no_signal``。
2. ``rows`` 含 ``/enter`` 与 ``/exit`` 两行（与源侧同口径，保证 len(rows) 与
   动作上限 550 / 3500 逐值可比）。
3. reply 额外携带 ``accepted`` / ``virtual_time_s``（仅记录，引擎不读）。
4. 生产 verifier（``runner.py:787-904``）依赖 KnowledgeState，吸收引擎不维护
   K_t：本入口改用独立 verifier，真复用 ``verify_q3_cover`` /
   ``verify_mec_covers``，Q4 证书重放登记为 not_performed。
5. ``--sim synthetic`` 是附加取值（契约只列 http/http-synthetic）：进程内后端，
   不打开任何 socket，用于 vendored bridge 全局禁用 socket 时的规避路径。

导入期零副作用：本模块 import 期只导入标准库与 ``absorbed.adapters``
（后者 import 期同样只依赖标准库）；引擎与 v2 运行栈都在 ``main()`` 内部导入。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    # 仅为让 `python absorbed/run_absorbed.py` 能解析 absorbed 包。非网络/socket
    # 操作；作为 absorbed.run_absorbed 导入时该插入是幂等的。
    sys.path.insert(0, str(ROOT))

from absorbed.adapters import absorbed_verifier, runtime_bridge, socket_guard
from absorbed.adapters.v3_client import AbsorbedSolverClient

SCENARIOS = ("random", "boundary", "dense", "sparse", "edge_facing", "mixed")
ENGINE_FOR_MODE = {"q3": ("q3-v5",), "q4": ("q4-v4",)}
DEFAULT_ENGINE = {"q3": "q3-v5", "q4": "q4-v4"}

SOURCE_Q3 = "Q3_Q4_V3/code/src/q3_optimizer_v5.py"
SOURCE_Q4_STRATEGY = ("Q3_Q4_V3/workstreams/q4_deep_optimization_v4_20260912/"
                      "strategy_v4.py")
SOURCE_Q4_LOCK = ("Q3_Q4_V3/workstreams/q4_deep_optimization_v4_20260912/"
                  "results/selection_lock.json")

DEGRADATIONS = (
    {"id": "accepted_false",
     "what": ("v2 协议允许 accepted=false（api/protocol.py:251-262），源引擎的 "
              "offline world 不存在该状态"),
     "policy": ("默认 --on-reject raise：抛 AbsorbedActionRejected 并以非零退出码"
                "失败，绝不把被拒映射成 no_signal"),
     "impact": "官方模拟器返回结构拒绝时本入口失败而非继续计算"},
    {"id": "rows_include_enter_exit",
     "what": ("源侧 rows 把 /enter、/exit 也各记一行（offline_world.py:55-57），"
              "引擎用 len(client.rows) 当 sequence 与动作上限"),
     "policy": "适配层为每个 act 追加一行，与源侧同口径",
     "impact": "动作上限（Q3 550 / Q4 3500）与源侧逐值可比"},
    {"id": "reply_extra_fields",
     "what": "适配层 reply 额外带 accepted/virtual_time_s（源侧没有）",
     "policy": "仅记录，引擎不读取",
     "impact": "无算法影响"},
    {"id": "verifier_reuse_limits",
     "what": ("生产 verifier（runner.py:787-904）全部结论来自 KnowledgeState，"
              "吸收引擎不维护 K_t"),
     "policy": ("改用独立 verifier：真复用 verify_q3_cover / verify_mec_covers "
                "+ 合成真值；Q4 证书重放登记 not_performed"),
     "impact": "Q4 证书独立重放本次未做，见 verifier_report.json"},
    {"id": "synthetic_sim_extension",
     "what": "--sim 增加 synthetic（进程内）取值，契约只列 http/http-synthetic",
     "policy": "附加取值，不改动两个契约取值的行为",
     "impact": "socket 绑定被 vendored bridge 禁用时的可用规避路径"},
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="run_absorbed.py",
        description=("吸收后的 SOTA 引擎统一入口：Q3 v5 / Q4 v4 驱动 v2 运行栈"
                     "（官方 http、本地 http-synthetic 或进程内 synthetic），"
                     "跑完写 metrics.json / run_report.json 并打印一行摘要。"),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--mode", choices=("q3", "q4"), required=True,
                        help="题目：q3=全向源，q4=定向源")
    parser.add_argument("--engine", choices=("q3-v5", "q4-v4"), default=None,
                        help="吸收引擎；默认按 mode 选择（q3->q3-v5, q4->q4-v4）")
    parser.add_argument("--sim", choices=runtime_bridge.SIM_MODES,
                        default="http",
                        help=("http=官方模拟器；http-synthetic=本地 HTTP+JSON "
                              "演练；synthetic=进程内（附加取值，不开 socket）"))
    parser.add_argument("--base-url", default="http://127.0.0.1:2026",
                        help="--sim http 时官方模拟器的根地址")
    parser.add_argument("--robot-id", default="TEAM001",
                        help="协议 robot_id（ASCII，1..64 字节）")
    parser.add_argument("--seed", type=int, default=101,
                        help="合成模式随机种子（--sim http 时不使用）")
    parser.add_argument("--n-sources", type=int, default=None,
                        help="合成模式源数（默认由模拟器在 10..16 内取）")
    parser.add_argument("--scenario", choices=SCENARIOS, default="random",
                        help="合成模式场景")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="结果目录；默认 runs/absorbed_<mode>_<engine>")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="HTTP 单次请求超时（秒）")
    parser.add_argument("--on-reject", choices=("raise", "return"), default="raise",
                        help="v2 返回 accepted=false 时的处理；见模块 docstring")
    parser.add_argument("--virtual-source", choices=("reported", "local"),
                        default="reported",
                        help="client.virtual 口径：reported=服务端上报（默认）")
    parser.add_argument("--real-time-budget", type=float, default=0.0,
                        help="现实时间闸门（秒）；0=关闭")
    parser.add_argument("--quiet", action="store_true",
                        help="不打印引擎 progress 行（仍打印一行摘要）")
    return parser


# ---------------------------------------------------------------------------
# 引擎装载（导入发生在调用方守护之下）
# ---------------------------------------------------------------------------

def load_engine(engine, progress=None):
    """按固定契约导入引擎并读取 VERSION / 锁定参数。

    契约：
    - ``absorbed.q3_v5.q3_optimizer_v5``：``VERSION``、``SELECTED_PARAMETERS``、
      ``solve_optimized_v5(client, progress=None)``
    - ``absorbed.q4_v4.locked``：``VERSION``、``SELECTED_NAME``、
      ``LOCKED_PARAMETERS``、``solve_locked(client)``
    """
    if engine == "q3-v5":
        from absorbed.q3_v5 import q3_optimizer_v5 as module
        version = getattr(module, "VERSION", None)
        params = getattr(module, "SELECTED_PARAMETERS", None)
        entry = getattr(module, "solve_optimized_v5", None)
        if entry is None or params is None:
            raise RuntimeError(
                "引擎契约不符：absorbed.q3_v5.q3_optimizer_v5 必须导出 "
                "SELECTED_PARAMETERS 与 solve_optimized_v5")

        def solve(client, _entry=entry, _progress=progress):
            return _entry(client, progress=_progress)

        return {"engine": engine, "module": module.__name__, "version": version,
                "params_name": None, "params": params,
                "source": SOURCE_Q3, "solve": solve}

    from absorbed.q4_v4 import locked
    version = getattr(locked, "VERSION", None)
    name = getattr(locked, "SELECTED_NAME", None)
    params = getattr(locked, "LOCKED_PARAMETERS", None)
    entry = getattr(locked, "solve_locked", None)
    if entry is None or params is None:
        raise RuntimeError(
            "引擎契约不符：absorbed.q4_v4.locked 必须导出 LOCKED_PARAMETERS "
            "与 solve_locked")
    return {"engine": engine, "module": "absorbed.q4_v4.locked",
            "version": version, "params_name": name, "params": params,
            "source": "absorbed/q4_v4/results/selection_lock.json（源："
                      + SOURCE_Q4_LOCK + "）",
            "solve": lambda client, _entry=entry: _entry(client)}


def _count_absent(mode, result):
    """缺席频道数（按引擎返回字段逐键判读，不做推算）。"""
    if not isinstance(result, dict):
        return 0
    if str(mode).upper() == "Q3":
        return (len(result.get("negative_observations") or {})
                + len(result.get("count_inferred_absent_channels") or []))
    return len(result.get("absent_channels") or [])


# ---------------------------------------------------------------------------
# 产物
# ---------------------------------------------------------------------------

def _write_json(path, payload):
    Path(path).write_text(
        json.dumps(runtime_bridge.json_safe(payload), ensure_ascii=False,
                   indent=1) + "\n", encoding="utf-8")


def _write_rows_csv(path, rows):
    fields = ["sequence", "path", "x", "y", "channel", "result",
              "movement_s", "switch_s", "operation_s",
              "virtual_before_s", "virtual_after_s"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            response = row.get("response") or {}
            position = row.get("position") or None
            writer.writerow({
                "sequence": row.get("sequence"),
                "path": row.get("path"),
                "x": None if not position else position[0],
                "y": None if not position else position[1],
                "channel": row.get("channel"),
                "result": (response.get("measure_result")
                           or response.get("clear_result")
                           or response.get("status")),
                "movement_s": row.get("movement_s"),
                "switch_s": row.get("switch_s"),
                "operation_s": row.get("operation_s"),
                "virtual_before_s": row.get("virtual_before_s"),
                "virtual_after_s": row.get("virtual_after_s"),
            })


def _write_api_log(path, entries):
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(runtime_bridge.json_safe(entry),
                                    ensure_ascii=False) + "\n")


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(runtime_bridge.json_safe(row),
                                    ensure_ascii=False) + "\n")


def _summary_line(report):
    """复用 v2 ``runtime.report_line``；不可用时逐键兜底并记录原因。"""
    report_line, reason = runtime_bridge.load_report_line()
    if report_line is not None:
        try:
            line = report_line(report)
            line["engine"] = report.get("engine")
            line["engine_version"] = report.get("engine_version")
            line["degraded"] = bool((report.get("degraded") or {}).get("active"))
            return line, "runtime.report_line"
        except Exception as exc:
            reason = "%s: %s" % (type(exc).__name__, exc)
    line = runtime_bridge.fallback_report_line(report)
    line["engine"] = report.get("engine")
    line["engine_version"] = report.get("engine_version")
    line["degraded"] = bool((report.get("degraded") or {}).get("active"))
    return line, "fallback_report_line (%s)" % reason


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = build_parser().parse_args(argv)
    engine = args.engine or DEFAULT_ENGINE[args.mode]
    if engine not in ENGINE_FOR_MODE[args.mode]:
        print("[absorbed] --mode %s 不能搭配 --engine %s"
              % (args.mode, engine), file=sys.stderr)
        return 2
    mode = args.mode.upper()
    output_dir = (Path(args.output_dir) if args.output_dir is not None
                  else ROOT / "runs" / ("absorbed_%s_%s" % (args.mode, engine)))
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    notes = []
    engine_info = None
    params_meta = None
    handles = None
    client = None
    result = None
    failure = None
    progress = (None if args.quiet
                else (lambda message: print("[progress] %s" % message,
                                            file=sys.stderr)))

    # --- socket 通路自检：import 之前 ---------------------------------
    guard_handles = socket_guard.capture()
    guard_before = socket_guard.check_pristine("before-engine-import")

    # --- 导入引擎（唯一的导入点） --------------------------------------
    try:
        engine_info = load_engine(engine, progress=progress)
    except Exception as exc:
        failure = "engine_import_failed: %s: %s" % (type(exc).__name__, exc)
        traceback.print_exc()

    # --- socket 通路自检：import 之后 ---------------------------------
    guard_after = socket_guard.compare(guard_handles, "after-engine-import")
    guard_block = {
        "before": guard_before,
        "after": guard_after,
        "ok": bool(guard_before.get("ok")) and bool(guard_after.get("ok")),
        "needs_sockets": args.sim in ("http", "http-synthetic"),
        "policy": "abort-if-needs-sockets-else-warn-and-register",
    }
    if failure is None and not guard_block["ok"]:
        print("[absorbed] BLOCKER: " + socket_guard.remediation(),
              file=sys.stderr)
        if guard_block["needs_sockets"]:
            failure = "socket_binding_tampered"
            notes.append("vendored 引擎在导入期替换了 socket/urllib 绑定；"
                         "--sim %s 需要真实 socket，已按 blocker 中止" % args.sim)
        else:
            notes.append("vendored 引擎在导入期替换了 socket/urllib 绑定；"
                         "--sim synthetic 不需要 socket，已继续并登记降级"
                         "（HTTP 通路本次不可用）")

    if engine_info is not None:
        fingerprint = runtime_bridge.parameter_fingerprint(engine_info["params"])
        params_meta = {
            "engine": engine,
            "name": engine_info["params_name"],
            "version": engine_info["version"],
            "source": engine_info["source"],
            "sha256": fingerprint["sha256"],
            "canonical_json_bytes": fingerprint["canonical_json_bytes"],
            "count": fingerprint["count"],
            "hash_basis": "sha256(canonical json of parameters, sort_keys=True)",
        }

    # --- 跑一局 --------------------------------------------------------
    if failure is None:
        try:
            handles = runtime_bridge.build_backend(
                args.sim, mode=mode, seed=args.seed, n_sources=args.n_sources,
                scenario=args.scenario, base_url=args.base_url,
                robot_id=args.robot_id, timeout=args.timeout)
            notes.extend(handles["notes"])
            client = AbsorbedSolverClient(
                handles["executor"], on_reject=args.on_reject,
                virtual_source=args.virtual_source,
                real_time_budget_s=args.real_time_budget)
            client.act("/enter")
            try:
                result = engine_info["solve"](client)
            finally:
                try:
                    client.act("/exit")
                except Exception as exc:
                    notes.append("exit failed: %s: %s"
                                 % (type(exc).__name__, exc))
            if not isinstance(result, dict):
                failure = "engine_result_not_a_dict: %s" % type(result).__name__
        except Exception as exc:
            failure = "%s: %s" % (type(exc).__name__, exc)
            traceback.print_exc()
        finally:
            if handles is not None:
                before = len(handles.get("notes", []))
                runtime_bridge.shutdown_backend(handles)
                notes.extend(handles.get("notes", [])[before:])

    complete = bool(failure is None and isinstance(result, dict))
    verifier_report = absorbed_verifier.verify_absorbed_run(
        mode, engine, (engine_info or {}).get("version"), result, client,
        simulator=(handles or {}).get("simulator"),
        executor=(handles or {}).get("executor"),
        engine_meta=params_meta, socket_guard=guard_block, sim=args.sim)
    wall = time.monotonic() - started
    simulator = (handles or {}).get("simulator")
    sources_total = (len(getattr(simulator, "sources", []) or [])
                     if simulator is not None else None)

    metrics_executor = (handles or {}).get("executor")
    metrics = runtime_bridge.build_metrics(
        metrics_executor,
        mode=mode, engine=engine,
        engine_version=(engine_info or {}).get("version"),
        cleared_count=(len(result.get("cleared_sources") or [])
                       if isinstance(result, dict) else 0),
        absent_count=_count_absent(mode, result),
        sources_total=sources_total, wall_clock_s=wall,
        verifier_all_ok=verifier_report["all_ok"],
        n_actions=len(getattr(client, "rows", []) or []),
        complete=complete, params_meta=params_meta,
        locked_name=(engine_info or {}).get("params_name"),
        sim=args.sim, seed=args.seed, n_sources=args.n_sources,
        scenario=args.scenario)
    if metrics_executor is None:
        # executor 未建起来（引擎导入失败 / blocker 中止）：指标退化为占位，
        # 口径与 build_metrics 同名同义，verifier_all_ok 必为 False。
        metrics = {
            "mode": mode,
            "engine": engine,
            "engine_version": (engine_info or {}).get("version"),
            "locked_name": (engine_info or {}).get("params_name"),
            "sim": args.sim,
            "seed": args.seed,
            "n_sources": args.n_sources,
            "scenario": args.scenario,
            "complete": complete,
            "cleared_count": 0,
            "certified_absent_count": _count_absent(mode, result),
            "sources_total": sources_total,
            "n_measures": 0, "n_switches": 0,
            "n_clear_attempts": 0, "n_clear_success": 0,
            "T_move": 0.0, "T_measure": 0.0, "T_switch": 0.0, "T_clear": 0.0,
            "T_total_virtual": 0.0, "T_total_local_ledger": 0.0,
            "move_distance_m": 0.0, "n_actions": 0,
            "reconcile_warning_count": 0,
            "wall_clock_s": wall,
            "verifier_all_ok": False,
            "solver_complete": complete,
            "parameter_name": (params_meta or {}).get("name"),
            "parameter_source": (params_meta or {}).get("source"),
            "parameter_sha256": (params_meta or {}).get("sha256"),
            "parameter_count": (params_meta or {}).get("count"),
            "t_per_source_s": None,
        }

    degrade_reasons = []
    if args.on_reject != "raise":
        degrade_reasons.append(
            "on_reject=%s（诊断模式：accepted=false 不再抛出，引擎取不到 "
            "measure_result/clear_result）" % args.on_reject)
    if args.virtual_source != "reported":
        degrade_reasons.append(
            "virtual_source=local（client.virtual 改用 executor 本地账本口径）")
    if not guard_block["ok"]:
        degrade_reasons.append(
            "socket/urllib 绑定在引擎导入后被替换（见 socket_guard）")
    degraded = {"active": bool(degrade_reasons), "reasons": degrade_reasons}

    # INTERFACE_MAP §6.3 的 policy_config.json：吸收路径没有 Mission/策略快照，
    # 因此这里记录**本次运行的引擎与参数身份**并显式标注 kind，避免被误读为
    # v2 production.dump_policy_snapshot 的策略快照。
    policy_config = {
        "kind": "absorbed_run_configuration",
        "note": ("吸收路径是原子 act 级、无 Mission/策略快照；本文件是运行配置快照，"
                 "不是 v2 策略参数快照（引擎身份与锁定参数指纹在此固化）。"),
        "mode": mode,
        "engine": engine,
        "engine_version": (engine_info or {}).get("version"),
        "engine_module": (engine_info or {}).get("module"),
        "parameters": params_meta,
        "sim": args.sim,
        "seed": args.seed,
        "n_sources": args.n_sources,
        "scenario": args.scenario,
        "base_url": args.base_url,
        "robot_id": args.robot_id,
        "on_reject": args.on_reject,
        "virtual_source": args.virtual_source,
        "real_time_budget_s": args.real_time_budget,
        "degradations": list(DEGRADATIONS),
        "degraded": degraded,
    }

    report = {
        "mode": mode,
        "engine": engine,
        "engine_version": (engine_info or {}).get("version"),
        "degraded": degraded,
        "engine_module": (engine_info or {}).get("module"),
        "engine_source": {"q3": SOURCE_Q3,
                          "q4": [SOURCE_Q4_STRATEGY, SOURCE_Q4_LOCK]}[args.mode],
        "engine_parameters": params_meta,
        "complete": complete,
        "failure": failure,
        "verifier_all_ok": bool(verifier_report["all_ok"]),
        "sim": args.sim,
        "base_url": args.base_url,
        "robot_id": args.robot_id,
        "seed": args.seed,
        "n_sources": args.n_sources,
        "scenario": args.scenario,
        "n_actions": len(getattr(client, "rows", []) or []),
        "wall_clock_s": wall,
        "output_dir": str(output_dir),
        "metrics": metrics,
        "socket_guard": guard_block,
        "notes": notes,
        "degradations": list(DEGRADATIONS),
        "artifacts": {
            "metrics": "metrics.json",
            "run_report": "run_report.json",
            "verifier_report": "verifier_report.json",
            "engine_result": "engine_result.json",
            "actions": "actions.csv",
            "api_log": "api_log.jsonl",
            "client_rows": "client_rows.jsonl",
            "client_api_log": "client_api_log.jsonl（http / http-synthetic 的 ApiClient 原始 HTTP 日志）",
            "solver_result": "solver_result.json（与 engine_result.json 同内容；INTERFACE_MAP §6.3 名称）",
            "policy_config": "policy_config.json（吸收运行配置快照，非 v2 策略快照）",
            "ground_truth": "ground_truth.json（仅合成模式）",
        },
    }
    summary, summary_source = _summary_line(report)
    report["report_line"] = summary
    report["report_line_source"] = summary_source

    write_notes = []
    for name, payload in (("metrics.json", metrics),
                          ("verifier_report.json", verifier_report),
                          ("run_report.json", report),
                          ("engine_result.json", result),
                          ("solver_result.json", result),
                          ("policy_config.json", policy_config)):
        try:
            _write_json(output_dir / name, payload)
        except Exception as exc:
            write_notes.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    try:
        _write_rows_csv(output_dir / "actions.csv",
                        list(getattr(client, "rows", []) or []))
    except Exception as exc:
        write_notes.append("actions.csv: %s: %s" % (type(exc).__name__, exc))
    try:
        _write_api_log(output_dir / "api_log.jsonl",
                       list(getattr(metrics_executor, "api_log", []) or []))
    except Exception as exc:
        write_notes.append("api_log.jsonl: %s: %s" % (type(exc).__name__, exc))
    try:
        _write_jsonl(output_dir / "client_rows.jsonl",
                     list(getattr(client, "rows", []) or []))
    except Exception as exc:
        write_notes.append("client_rows.jsonl: %s: %s"
                           % (type(exc).__name__, exc))
    api_client_log = list(getattr(getattr((handles or {}).get("backend"),
                                          "client", None), "log", []) or [])
    if api_client_log:
        try:
            _write_jsonl(output_dir / "client_api_log.jsonl", api_client_log)
        except Exception as exc:
            write_notes.append("client_api_log.jsonl: %s: %s"
                               % (type(exc).__name__, exc))
    if simulator is not None:
        try:
            _write_json(output_dir / "ground_truth.json",
                        simulator.ground_truth())
        except Exception as exc:
            write_notes.append("ground_truth.json: %s: %s"
                               % (type(exc).__name__, exc))
    if write_notes:
        for note in write_notes:
            print("[absorbed] artifact write failed: %s" % note, file=sys.stderr)

    print(json.dumps(runtime_bridge.json_safe(summary), ensure_ascii=False))
    ok = bool(report["complete"] and report["verifier_all_ok"])
    if not ok:
        print("[absorbed] run incomplete or verifier failed: complete=%s "
              "verifier_all_ok=%s failure=%s"
              % (report["complete"], report["verifier_all_ok"], failure),
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
