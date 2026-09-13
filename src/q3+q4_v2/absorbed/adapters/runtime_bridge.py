# -*- coding: utf-8 -*-
"""v2 运行栈桥：sys.path、后端构造、report_line 复用、JSON 安全化、参数指纹。

导入期零副作用：本模块 import 期只导入标准库；所有 v2 模块
（``api.*`` / ``executor.*`` / ``experiment.*``）都在函数内部导入，
因此 import 本模块不会触发任何 v2 依赖解析、不开 socket、不碰 sys.path。
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]      # .../src/q3+q4_v2
LEGACY_CODE = PACKAGE_ROOT / "baseline" / "code"        # 不可变协议/执行器快照

SIM_MODES = ("http", "http-synthetic", "synthetic")

# v2 ``runtime.report_line`` 的键集（runtime.py:749-770）。兜底实现必须逐键一致，
# 否则吸收运行与既有 learned/probabilistic/geometry 基线不可比。
REPORT_LINE_KEYS = (
    "complete", "failure", "cleared", "certified_absent", "sources",
    "T_total_s", "T_per_source_s", "source_count_for_average",
    "average_time_per_source_s", "average_time_per_source_basis",
    "measures", "switches", "clear_success", "clear_attempts",
    "verifier_all_ok", "wall_clock_s",
)


# ---------------------------------------------------------------------------
# sys.path
# ---------------------------------------------------------------------------

def ensure_v2_import_path():
    """把包根与 ``baseline/code`` 放到 sys.path 最前；幂等，仅调用期生效。

    顺序镜像 ``run.py:25-32``：包根在前（``production.py``、各策略包），
    ``baseline/code`` 在后（``api`` / ``executor`` / ``experiment`` /
    ``geometry`` / ``state`` / ``policy`` / ``verifier`` 快照）。
    包根下不存在与之同名的 ``api`` / ``executor`` / ``geometry`` 包
    （已逐个 read 核对），因此不会互相遮蔽。
    """
    entries = (str(PACKAGE_ROOT), str(LEGACY_CODE))
    for path in reversed(entries):
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    return list(entries)


# ---------------------------------------------------------------------------
# 后端构造（三种 --sim）
# ---------------------------------------------------------------------------

def build_backend(sim_mode, *, mode, seed=None, n_sources=None, scenario="random",
                  base_url="http://127.0.0.1:2026", robot_id="TEAM001",
                  timeout=5.0):
    """构造一次吸收运行的 executor / 模拟器 / HTTP 服务。

    ``mode`` 必须是 ``"Q3"`` / ``"Q4"``。返回 dict：

        executor / backend / simulator / server / needs_sockets / notes

    ``simulator`` 为 None 表示没有真值（官方 http 模式），verifier 会据此把
    真值类检查登记为 skipped 而不是假装通过。
    """
    if sim_mode not in SIM_MODES:
        raise ValueError("sim_mode must be one of %r" % (SIM_MODES,))
    ensure_v2_import_path()
    from executor.action_executor import ActionExecutor
    from experiment.simulator import (SimulatorBackend, SimulatorHTTPServer,
                                      SyntheticSimulator)

    notes = []
    simulator = None
    server = None
    if sim_mode == "http":
        from api.client import ApiClient
        from api.session import Session
        backend = Session(ApiClient(base_url, timeout=timeout,
                                    robot_id=robot_id))
        notes.append("official http: base_url=%s robot_id=%s；无真值，"
                     "verifier 只能做协议/几何一致性检查" % (base_url, robot_id))
    else:
        simulator = SyntheticSimulator(str(mode), int(seed),
                                       n_sources=n_sources,
                                       scenario=str(scenario))
        if sim_mode == "http-synthetic":
            server = SimulatorHTTPServer(simulator).start()
            from api.client import ApiClient
            from api.session import Session
            backend = Session(ApiClient(server.url, timeout=timeout,
                                        robot_id=robot_id))
            notes.append("http-synthetic: 本地 HTTP+JSON 全链路演练（真实 socket）"
                         " url=%s" % server.url)
        else:
            backend = SimulatorBackend(simulator, robot_id=robot_id)
            notes.append("synthetic: 进程内后端，不打开任何 socket"
                         "（socket 绑定被禁用时的规避路径）")
    executor = ActionExecutor(backend)
    return {
        "executor": executor,
        "backend": backend,
        "simulator": simulator,
        "server": server,
        "needs_sockets": sim_mode in ("http", "http-synthetic"),
        "notes": notes,
    }


def shutdown_backend(handles):
    """关闭 http-synthetic 起的本地服务；失败只记 note，不抛出。"""
    server = (handles or {}).get("server")
    if server is None:
        return
    try:
        server.shutdown()
    except Exception as exc:                                   # pragma: no cover
        (handles.setdefault("notes", [])).append(
            "HTTPServer shutdown failed: %s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------
# report_line 复用
# ---------------------------------------------------------------------------

def load_report_line():
    """惰性复用 v2 ``runtime.report_line``（runtime.py:749-770）。

    返回 ``(callable_or_None, reason_or_None)``。``runtime`` 会连带导入
    ``production`` 与各策略包，属重依赖；失败时返回 ``(None, reason)``，
    由 :func:`fallback_report_line` 用完全相同的键兜底，并把原因写进
    ``run_report.json`` 的 ``report_line_source`` 字段（不是静默降级）。
    """
    ensure_v2_import_path()
    try:
        from runtime import report_line as _report_line
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    return _report_line, None


def fallback_report_line(report):
    """``runtime.report_line`` 的逐键等价兜底（键集见 REPORT_LINE_KEYS）。"""
    metrics = report.get("metrics") or {}
    return {
        "complete": bool(report.get("complete")),
        "failure": report.get("failure"),
        "cleared": metrics.get("cleared_count"),
        "certified_absent": metrics.get("certified_absent_count"),
        "sources": metrics.get("sources_total"),
        "T_total_s": metrics.get("T_total_virtual"),
        "T_per_source_s": metrics.get("t_per_source_s"),
        "source_count_for_average": metrics.get("source_count_for_average"),
        "average_time_per_source_s": metrics.get("average_time_per_source_s"),
        "average_time_per_source_basis": metrics.get("average_time_per_source_basis"),
        "measures": metrics.get("n_measures"),
        "switches": metrics.get("n_switches"),
        "clear_success": metrics.get("n_clear_success"),
        "clear_attempts": metrics.get("n_clear_attempts"),
        "verifier_all_ok": report.get("verifier_all_ok"),
        "wall_clock_s": metrics.get("wall_clock_s"),
    }


# ---------------------------------------------------------------------------
# JSON 安全化
# ---------------------------------------------------------------------------

def json_safe(obj, _depth=0):
    """把引擎返回值转成 JSON 可序列化结构。

    引擎（numpy 实现）会在返回值里混入 ``ndarray`` / ``np.float64`` 等类型，
    直接 ``json.dump`` 会失败。本函数用鸭子类型（``tolist`` / ``item``）而非
    ``import numpy`` 处理，因此不新增依赖。

    非有限浮点（nan/inf）会被替换为 ``None``——JSON 无法表示它们，且吸收运行
    的有效路径不会产生非有限虚拟时间。
    """
    if _depth > 32:
        return repr(obj)
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): json_safe(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [json_safe(v, _depth + 1) for v in obj]
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        try:
            return json_safe(tolist(), _depth + 1)
        except Exception:
            pass
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return json_safe(item(), _depth + 1)
        except Exception:
            pass
    return repr(obj)


# ---------------------------------------------------------------------------
# 参数指纹与指标
# ---------------------------------------------------------------------------

def parameter_fingerprint(params):
    """锁定参数指纹（规范化 JSON 的 sha256；与源文件字节哈希不同口径）。"""
    if params is None:
        return {"sha256": None, "canonical_json_bytes": None, "count": None}
    canonical = json.dumps(json_safe(params), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    blob = canonical.encode("utf-8")
    try:
        count = len(params)
    except TypeError:                                          # pragma: no cover
        count = None
    return {"sha256": hashlib.sha256(blob).hexdigest(),
            "canonical_json_bytes": len(blob),
            "count": count}


def _augment_per_source(metrics):
    """写入 per-source 平均值（语义对齐 run.py:97-139，但不落盘）。"""
    known_count = metrics.get("sources_total")
    if known_count:
        denominator = int(known_count)
        basis = ("T_total_virtual / sources_total；sources_total 来自合成真值"
                 "（官方模式不可知，见 run.py 的 hidden-count 边界）")
    elif metrics.get("solver_complete") and metrics.get("cleared_count"):
        denominator = int(metrics["cleared_count"])
        basis = ("T_total_virtual / cleared_count after complete run; "
                 "cleared_count is observed from accepted clear results")
    else:
        denominator = None
        basis = None
    average = (metrics["T_total_virtual"] / denominator) if denominator else None
    metrics["source_count_for_average"] = denominator
    metrics["average_time_per_source_s"] = average
    metrics["average_time_per_source_basis"] = basis
    metrics["observed_cleared_source_count"] = metrics.get("cleared_count", 0)
    if average is not None:
        metrics["t_per_source_s"] = average
        metrics["t_per_source_basis"] = basis
    else:
        metrics.setdefault("t_per_source_s", None)
        metrics.setdefault("t_per_source_basis", None)
    # 口径别名：v2 metrics.json 用小写 t_per_source_s（run.py:127-131），
    # report_line 输出用大写 T_per_source_s（runtime.py:758）。两者同值，
    # 同时给出以免下游对照表因大小写取不到值。
    metrics["T_per_source_s"] = metrics["t_per_source_s"]


def build_metrics(executor, *, mode, engine, engine_version, cleared_count,
                  absent_count, sources_total, wall_clock_s, verifier_all_ok,
                  n_actions, complete, params_meta, locked_name=None, sim=None,
                  seed=None, n_sources=None, scenario=None):
    """吸收运行的 metrics（键与 v2 口径对齐，便于与既有基线对比）。

    字段名遵循 v2 口径，不自造名字：``cleared_count`` / ``certified_absent_count``
    / ``T_total_virtual`` / ``t_per_source_s``（metrics.json 口径，与 run.py 一致）、
    以及 ``T_per_source_s``（report_line 口径，runtime.py:758）同值别名；
    ``complete`` 与 run_report.json 同义。``locked_name`` 是 Q4 锁定参数名
    （quarter12；Q3 为 None）。
    """
    ledger = dict(getattr(executor, "ledger", {}) or {})
    metrics = {
        "mode": str(mode),
        "engine": str(engine),
        "engine_version": engine_version,
        "locked_name": locked_name,
        "sim": sim,
        "seed": (None if seed is None else int(seed)),
        "n_sources": (None if n_sources is None else int(n_sources)),
        "scenario": scenario,
        "complete": bool(complete),
        "cleared_count": int(cleared_count),
        "certified_absent_count": int(absent_count),
        "sources_total": (None if sources_total is None else int(sources_total)),
        "n_measures": int(getattr(executor, "n_measures", 0)),
        "n_switches": int(getattr(executor, "n_switches", 0)),
        "n_clear_attempts": int(getattr(executor, "n_clear_attempts", 0)),
        "n_clear_success": int(getattr(executor, "n_clear_success", 0)),
        "T_move": float(ledger.get("T_move", 0.0)),
        "T_measure": float(ledger.get("T_measure", 0.0)),
        "T_switch": float(ledger.get("T_switch", 0.0)),
        "T_clear": float(ledger.get("T_clear", 0.0)),
        "T_total_virtual": float(getattr(executor, "virtual_time", 0.0)),
        "T_total_local_ledger": float(
            getattr(executor, "local_virtual_time", 0.0)),
        "move_distance_m": float(getattr(executor, "move_distance", 0.0)),
        "n_actions": int(n_actions),
        "reconcile_warning_count": len(
            getattr(executor, "reconcile_warnings", []) or []),
        "wall_clock_s": float(wall_clock_s),
        "verifier_all_ok": bool(verifier_all_ok),
        "solver_complete": bool(complete),
        "parameter_name": (params_meta or {}).get("name"),
        "parameter_source": (params_meta or {}).get("source"),
        "parameter_sha256": (params_meta or {}).get("sha256"),
        "parameter_count": (params_meta or {}).get("count"),
    }
    _augment_per_source(metrics)
    return metrics
