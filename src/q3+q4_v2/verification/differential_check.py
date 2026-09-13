#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t6 差分验证：源引擎 vs 吸收件引擎，逐位行为等价（Q3 + Q4）。

用法（在 D:\\CUMCM2026\\src\\q3+q4_v2 下）::

    python -X utf8 verification/differential_check.py

依赖：仅标准库 + numpy（吸收件引擎自身需要 numpy/scipy/numba，那是被测对象）。
退出码：0 = 全部用例 PASS；1 = 有 FAIL 或无法建立对照。

设计（为什么这样比才有意义）
----------------------------
* 两个引擎各自跑在**独立的**确定性 mock client 上（同一 case 规格 → 同一世界），
  然后比对两侧记录：动作序列、虚拟时长、清除集合、返回 JSON。
  若两侧动作不同，mock 的状态会从分歧点开始分叉 —— 这本身就是 FAIL 的证据。
* mock 的语义逐条照抄源包权威实现
  ``workstreams/q4_local_optimization_20260912/offline_world.py:21-58``（World._act）：
  move=dist/5、measure +5s、换频道 +1s（仅 /measure 触发，比较“上一次测量频道”，初值 1）、
  /clear 不换频道、clear 成功 +5s/失败 +3s、/enter /exit 不推进；
  ``rows`` 每次 act 追加一行（含 /enter、/exit），行结构与 :55-57 一致。
* **反空转（anti-vacuity）**：脚本先导入 absorbed 侧并固定其源文件路径，再导入源侧；
  并断言 4 个入口函数来自不同文件、且分别位于各自树内 —— 否则“相等”可能只是
  两侧导入了同一个模块（例如 absorbed 里残留裸 import 时会被源目录抢占）。
* 源侧 Q4 无法直接 import（`import numba` 会把 site-packages 的 PyPI coverage 装进
  sys.modules，随后 `from coverage import ...` 拿错模块；预置本地目录则 numba 崩溃）。
  本脚本按可行垫片处理：先 `import numba` → 用 importlib 从
  ``q4_local_optimization_v2_20260912/coverage.py`` 加载本地 coverage 并替换
  ``sys.modules['coverage']`` → 再 import strategy_v4。**全程只读源包**。
  注意：源侧 import 链会在导入期执行 `socket.socket=deny` /
  `create_connection=deny` / `OpenerDirector.open=deny`（bridge_v4.py:8-9 等），
  所以本源必须走进程内 mock，绝不能再走 HTTP —— 这也正是吸收件必须删掉它们的理由。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import socket
import sys
import traceback

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"D:\CUMCM2026\src\Q3_Q4_V3"
SRC_Q3_CODE = os.path.join(SRC, "code")
SRC_Q3_SRC = os.path.join(SRC, "code", "src")
SRC_Q4_V4 = os.path.join(SRC, "workstreams", "q4_deep_optimization_v4_20260912")
SRC_Q4_V2 = os.path.join(SRC, "workstreams", "q4_local_optimization_v2_20260912")

# 锁文件里“未 vendor / 被删除的实验脚手架”清单（t6 验收第 5 条点名的 8 个名字）。
SCAFFOLDING = ("bridge_v4", "bridge", "strategy_v3", "experiments_v3",
               "base", "candidate", "experiment", "offline_world")

FAILURES = []
NOTES = []


def log(msg):
    print(msg, flush=True)


def under(path, root):
    if not path:
        return False
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == \
            os.path.abspath(root)
    except ValueError:
        return False


def origin(obj):
    """入口函数所在的真实文件（反空转的锚点）。"""
    return os.path.abspath(getattr(obj, "__code__", None).co_filename) \
        if getattr(obj, "__code__", None) is not None else None


# ---------------------------------------------------------------------------
# 1. 先导入 absorbed 侧（此时 sys.path 里没有源包目录）
# ---------------------------------------------------------------------------

def import_ported():
    sys.path.insert(0, HERE)
    from absorbed.q3_v5 import q3_optimizer_v5 as pq3
    from absorbed.q4_v4 import locked as pq4locked
    from absorbed.q4_v4 import strategy_v4 as pq4
    entries = {
        "ported-q3": (origin(pq3.solve_optimized_v5), pq3.solve_optimized_v5),
        "ported-q4": (origin(pq4.solve), pq4.solve),
        "ported-q4-locked": (origin(pq4locked.solve_locked),
                             pq4locked.solve_locked),
    }
    return pq3, pq4locked, pq4, entries


# ---------------------------------------------------------------------------
# 2. 再导入源侧
# ---------------------------------------------------------------------------

def _load_local_coverage():
    """把本地 coverage.py 装进 sys.modules['coverage']（见模块 docstring）。"""
    import numba  # noqa: F401  必须最先导入：让 numba 用自己的 coverage_support 收尾
    key = "coverage"
    before = getattr(sys.modules.get(key), "__file__", None)
    spec = importlib.util.spec_from_file_location(
        key, os.path.join(SRC_Q4_V2, "coverage.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    NOTES.append("source Q4 shim: sys.modules['coverage'] %s -> %s"
                 % (before, module.__file__))
    return module


def self_test(sq3, pq3):
    """反证控制：拿两个**不同世界**的两侧引擎比对，必须被判为不等。

    若这里也“相等”，说明比对器恒真（例如把响应归一化掉了），
    那后面 8/8 PASS 就毫无意义。此控制失败即整体 FAIL。
    """
    case_a = make_case("q3", 101, 10, "zero")
    case_b = make_case("q3", 909, 10, "zero")
    run_a = run_engine(sq3.solve_optimized_v5, case_a)
    run_b = run_engine(pq3.solve_optimized_v5, case_b)
    ok, _detail, problem = compare(case_a, run_a, run_b)
    detected = not ok
    log("  反证控制（seed101 vs seed909，期望“判为不等”）：%s"
        % ("检出差异 ✓" if detected else "错误地判为相等 ✗"))
    if detected:
        log("    检出理由：%s" % problem)
    return detected


def _socket_patched():
    """源侧 import 链是否已把 socket 打死（bridge_v4.py:8-9 那三行）。"""
    return getattr(socket.socket, "__name__", "") == "deny"


def import_source(entries):
    sys.path.insert(0, SRC_Q3_SRC)
    sys.path.insert(0, SRC_Q3_CODE)
    import q3_optimizer_v5 as sq3
    _load_local_coverage()
    sys.path.insert(0, SRC_Q4_V4)
    import strategy_v4 as sq4
    entries["source-q3"] = (origin(sq3.solve_optimized_v5),
                            sq3.solve_optimized_v5)
    entries["source-q4"] = (origin(sq4.solve), sq4.solve)
    return sq3, sq4


def check_anti_vacuity(entries, staged_modules):
    """入口文件必须分属两棵树；且脚手架 8 名在 absorbed 侧不得出现。"""
    ok = True
    for name in ("ported-q3", "ported-q4", "ported-q4-locked"):
        path = entries[name][0]
        if not under(path, HERE):
            FAILURES.append("anti-vacuity: %s 来自 %s（不在 absorbed 树内）"
                            % (name, path))
            ok = False
    for name in ("source-q3", "source-q4"):
        path = entries[name][0]
        if not under(path, SRC):
            FAILURES.append("anti-vacuity: %s 来自 %s（不在源包树内）"
                            % (name, path))
            ok = False
    if entries["ported-q3"][1] is entries["source-q3"][1]:
        FAILURES.append("anti-vacuity: Q3 两侧是同一个函数对象")
        ok = False
    if entries["ported-q4"][1] is entries["source-q4"][1]:
        FAILURES.append("anti-vacuity: Q4 两侧是同一个函数对象")
        ok = False
    # absorbed 侧导入后，8 个脚手架模块名不得出现在 sys.modules
    leaked = sorted(n for n in SCAFFOLDING if n in staged_modules)
    if leaked:
        FAILURES.append("anti-vacuity: absorbed 侧导入了脚手架顶层名 %s" % leaked)
        ok = False
    return ok


def scaffolding_evidence(staged_modules):
    """源侧带进来的脚手架证据（证明对照是真的把源包整套脚手架一起跑了）。"""
    rows = []
    for name in SCAFFOLDING:
        mod = sys.modules.get(name)
        rows.append((name, getattr(mod, "__file__", None),
                     "imported" if mod is not None else "absent"))
    absent = [n for n, f, s in rows if s == "absent"]
    if absent:
        NOTES.append("source-side scaffolding not in sys.modules: %s" % absent)
    return rows


# ---------------------------------------------------------------------------
# 3. 确定性 mock client（照 offline_world.py:21-58 的语义）
# ---------------------------------------------------------------------------

class MockClient:
    """源契约的最小确定性世界：无随机、无 IO、每次 act 追加一行。"""

    def __init__(self, case):
        self.sources = {s["channel"]: s for s in case["sources"]}
        self.error_mode = case["error_mode"]
        self.position = (0.0, 0.0)
        self.channel = 1
        self.virtual = 0.0
        self.rows = []
        self.cleared = set()
        self.entered = False
        self.finished = False

    def _error(self, position, channel):
        mode = self.error_mode
        if mode == "plus":
            return 1.0
        if mode == "minus":
            return -1.0
        if mode == "zero":
            return 0.0
        if mode == "sine":
            return math.sin(position[0] * 0.011 + position[1] * 0.017
                            + channel * 0.731)
        raise ValueError("unknown error_mode %r" % (mode,))

    def act(self, path, position=None, channel=None):
        before = self.virtual
        movement = switch = operation = 0.0
        if path == "/enter":
            if self.entered:
                raise RuntimeError("Enter twice")
            self.entered = True
            reply = {"status": "success"}
        elif path == "/exit":
            self.finished = True
            reply = {"status": "success", "exit_reason": "user_exit"}
        else:
            if not self.entered or self.finished:
                raise RuntimeError("No active offline session")
            if path not in ("/measure", "/clear"):
                raise ValueError(path)
            point = (float(position[0]), float(position[1]))
            channel = int(channel)
            movement = math.dist(self.position, point) / 5.0
            self.position = point
            src = self.sources.get(channel)
            present = src is not None and channel not in self.cleared
            distance = math.dist(point, src["position"]) if present else math.inf
            if path == "/measure":
                switch = int(channel != self.channel)
                self.channel = channel
                operation = 5.0
                visible = False
                if present and distance <= src["radius"] + 1e-10:
                    if src["type"] == "omni":
                        visible = True
                    else:
                        ang = math.radians(src["direction_deg"])
                        dx = point[0] - src["position"][0]
                        dy = point[1] - src["position"][1]
                        visible = math.cos(ang) * dx + math.sin(ang) * dy >= -1e-10
                if not visible:
                    reply = {"measure_result": "no_signal"}
                elif distance <= 5.0 + 1e-10:
                    reply = {"measure_result": "near"}
                else:
                    angle = math.degrees(math.atan2(
                        src["position"][1] - point[1],
                        src["position"][0] - point[0]))
                    reply = {"measure_result": "direction",
                             "svd_deg": round((angle + self._error(point, channel))
                                              % 360.0, 2) % 360.0}
            else:
                success = present and distance <= 20.0 + 1e-10
                operation = 5.0 if success else 3.0
                if success:
                    self.cleared.add(channel)
                reply = {"clear_result": "success" if success
                         else "no_target_in_range"}
            self.virtual += movement + switch + operation
        self.rows.append({
            "sequence": len(self.rows) + 1, "path": path,
            "position": list(position) if position is not None else None,
            "channel": channel, "response": dict(reply),
            "movement_s": movement, "switch_s": switch,
            "operation_s": operation, "virtual_before_s": before,
            "virtual_after_s": self.virtual})
        return reply


# ---------------------------------------------------------------------------
# 4. 用例（确定性：种子 + 源数 + 误差模式）
# ---------------------------------------------------------------------------

def make_case(mode, seed, n_sources, error_mode):
    rng = np.random.default_rng(seed)
    channels = sorted(rng.choice(np.arange(1, 21), size=n_sources,
                                 replace=False).tolist())
    sources = []
    for channel in channels:
        angle = rng.uniform(0.0, 2.0 * math.pi)
        radius = 1800.0 * math.sqrt(rng.uniform())
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        r_eff = float(rng.uniform(1000.0, 1500.0))
        if mode == "q3":
            sources.append({"channel": channel, "position": [x, y],
                            "radius": r_eff, "type": "omni"})
        else:
            # Q4：定向源，朝向均匀（题设口径），并按源包 dev 数据的混样比例
            # 保留少量全向源以便覆盖两条可见性分支。
            directional = (channel % 5 != 0)
            sources.append({
                "channel": channel, "position": [x, y], "radius": r_eff,
                "type": "dir" if directional else "omni",
                "direction_deg": float(rng.uniform(0.0, 360.0))})
    return {"name": "%s_seed%d_n%d_%s" % (mode, seed, n_sources, error_mode),
            "mode": mode, "seed": seed, "sources": sources,
            "error_mode": error_mode}


CASES = [
    make_case("q3", 101, 10, "zero"),
    make_case("q3", 202, 12, "sine"),
    make_case("q3", 303, 14, "plus"),
    make_case("q3", 404, 16, "minus"),
    make_case("q4", 101, 10, "zero"),
    make_case("q4", 202, 12, "sine"),
    make_case("q4", 303, 14, "plus"),
    make_case("q4", 404, 16, "minus"),
]


# ---------------------------------------------------------------------------
# 5. 跑一例 + 逐位比对
# ---------------------------------------------------------------------------

def run_engine(engine, case):
    client = MockClient(case)
    result = None
    error = None
    try:
        client.act("/enter")
        result = engine(client)
        client.act("/exit")
    except Exception as exc:            # noqa: BLE001 记录而不是中断
        error = "%s: %s" % (type(exc).__name__, exc)
    return {"rows": client.rows, "virtual": client.virtual,
            "cleared": sorted(client.cleared), "result": result,
            "error": error, "n_rows": len(client.rows)}


def normalize(obj):
    """JSON 投影：numpy → python，tuple → list，dict 键 → str。"""
    if isinstance(obj, np.ndarray):
        return [normalize(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {str(k): normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(v) for v in obj]
    return obj


def first_diff(a, b, path="$"):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return None if a == b else "%s: %r != %r" % (path, a, b)
    if isinstance(a, bool) or isinstance(b, bool) or type(a) is not type(b):
        return None if a == b else "%s: %r (%s) != %r (%s)" % (
            path, a, type(a).__name__, b, type(b).__name__)
    if isinstance(a, dict):
        ka, kb = set(a.keys()), set(b.keys())
        if ka != kb:
            return "%s: 键集合不同 only-source=%s only-ported=%s" % (
                path, sorted(ka - kb)[:5], sorted(kb - ka)[:5])
        for key in sorted(ka):
            diff = first_diff(a[key], b[key], "%s.%s" % (path, key))
            if diff:
                return diff
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s: 长度 %d != %d" % (path, len(a), len(b))
        for index, (x, y) in enumerate(zip(a, b)):
            diff = first_diff(x, y, "%s[%d]" % (path, index))
            if diff:
                return diff
        return None
    if isinstance(a, str):
        return None if a == b else "%s: %r != %r" % (path, a, b)
    return None if a == b else "%s: %r != %r" % (path, a, b)


def compare(case, src, por):
    """返回 (ok, detail dict, first_diff_text)。"""
    detail = {}
    problems = []

    if src["error"] or por["error"]:
        if src["error"] != por["error"]:
            problems.append("异常不同：source=%r ported=%r"
                            % (src["error"], por["error"]))
        detail["equivalent_failure"] = (src["error"] == por["error"]
                                        and src["error"] is not None)
    if src["rows"] != por["rows"]:
        first = next((i for i, (x, y) in enumerate(zip(src["rows"], por["rows"]))
                      if x != y), min(len(src["rows"]), len(por["rows"])))
        problems.append("动作序列不同（首个不同下标 %d，长度 %d vs %d）"
                        % (first, len(src["rows"]), len(por["rows"])))
        detail["rows_first_diff"] = first
    if src["virtual"] != por["virtual"]:
        problems.append("虚拟时长不同：%r vs %r"
                        % (src["virtual"], por["virtual"]))
    if src["cleared"] != por["cleared"]:
        problems.append("清除集合不同：%s vs %s" % (src["cleared"], por["cleared"]))

    result_diff = None
    jsrc = json.dumps(normalize(src["result"]), sort_keys=True)
    jpor = json.dumps(normalize(por["result"]), sort_keys=True)
    if jsrc != jpor:
        result_diff = first_diff(normalize(src["result"]),
                                normalize(por["result"]))
        problems.append("返回 JSON 不同：%s" % (result_diff or "?"))
    detail["json_bytes"] = len(jsrc)
    detail["json_equal"] = jsrc == jpor

    # 动作序列两端必须是 /enter 与 /exit（含 enter/exit 口径）
    paths = [row["path"] for row in por["rows"]]
    if not paths or paths[0] != "/enter" or paths[-1] != "/exit":
        problems.append("动作序列未含 /enter 或 /exit：首=%r 末=%r"
                        % (paths[:1], paths[-1:]))

    detail.update({
        "name": case["name"], "src_rows": src["n_rows"], "por_rows": por["n_rows"],
        "virtual": por["virtual"], "cleared": len(por["cleared"]),
        "sources": len(case["sources"]),
        "src_error": src["error"], "por_error": por["error"],
        "keys": (sorted(por["result"]) if isinstance(por["result"], dict) else None),
        "cleared_count_field": (por["result"].get("cleared_count")
                                if isinstance(por["result"], dict) else None),
    })
    return (not problems), detail, ("; ".join(problems) if problems else None)


# ---------------------------------------------------------------------------

def main():
    log("=" * 78)
    log("t6 差分验证：源引擎 vs 吸收件引擎（逐位行为等价）")
    log("=" * 78)
    log("python %s | numpy %s" % (sys.version.split()[0], np.__version__))
    log("HERE  = %s" % HERE)
    log("SRC   = %s" % SRC)
    if not os.path.isdir(SRC):
        log("FAIL: 源包目录不存在: %s" % SRC)
        return 1

    try:
        pq3, pq4locked, pq4, entries = import_ported()
    except Exception:                    # noqa: BLE001
        log("FAIL: 导入 absorbed 侧失败")
        traceback.print_exc()
        return 1
    staged_modules = set(sys.modules)
    log("")
    log("-- absorbed 侧入口（导入后固定）--")
    for key in ("ported-q3", "ported-q4", "ported-q4-locked"):
        log("  %-16s %s" % (key, entries[key][0]))
    log("  absorbed 侧导入后 sys.modules 中的脚手架顶层名: %s"
        % (sorted(n for n in SCAFFOLDING if n in staged_modules) or "无"))
    socket_after_ported = _socket_patched()
    log("  absorbed 侧导入后 socket 是否被劫持: %s" % socket_after_ported)
    if socket_after_ported:
        FAILURES.append("absorbed 侧导入即劫持 socket（deny 未被移除）")

    try:
        sq3, sq4 = import_source(entries)
    except Exception:                    # noqa: BLE001
        log("FAIL: 导入源侧失败")
        traceback.print_exc()
        return 1
    log("")
    log("-- 源侧入口（含 numba/coverage 垫片）--")
    for key in ("source-q3", "source-q4"):
        log("  %-16s %s" % (key, entries[key][0]))
    if not check_anti_vacuity(entries, staged_modules):
        log("")
        log("反空转检查未通过：")
        for item in FAILURES:
            log("  - %s" % item)
        return 1
    log("  反空转检查：通过（两侧入口分属不同树，且 absorbed 侧未引入脚手架）")
    log("")
    log("-- 反证控制 --")
    if not self_test(sq3, pq3):
        FAILURES.append("反证控制失败：比对器未能检出两个不同世界的差异")
    socket_after_source = _socket_patched()
    log("  源侧导入后 socket 是否被劫持: %s（源包 import 副作用，吸收件已移除）"
        % socket_after_source)

    log("")
    log("-- 锁参数一致性 --")
    lock_src = os.path.join(SRC_Q4_V4, "results", "selection_lock.json")
    with open(lock_src, "r", encoding="utf-8") as handle:
        locked_json = json.load(handle)
    locked_src_params = locked_json["selected_parameters"]
    ok_lock = (pq4locked.LOCKED_PARAMETERS == locked_src_params)
    log("  selection_lock.version = %s | selected_name = %s | 参数 %d 项"
        % (locked_json["version"], locked_json["selected_name"],
           len(locked_src_params)))
    log("  absorbed.locked.LOCKED_PARAMETERS == v4 锁 selected_parameters: %s"
        % ok_lock)
    if not ok_lock:
        FAILURES.append("locked.LOCKED_PARAMETERS 与 v4 selection_lock.json 不等")
        diff = first_diff(normalize(locked_src_params),
                          normalize(pq4locked.LOCKED_PARAMETERS))
        log("  首个差异：%s" % diff)
    log("  absorbed.locked.VERSION = %s | SELECTED_NAME = %s"
        % (pq4locked.VERSION, pq4locked.SELECTED_NAME))

    log("")
    log("-- 源侧脚手架证据（sys.modules）--")
    for name, path, state in scaffolding_evidence(staged_modules):
        log("  %-16s %-9s %s" % (name, state, path))

    log("")
    log("-- 逐例比对 --")
    header = ("%-26s %5s %5s %10s %4s %4s  %s"
              % ("case", "src#", "por#", "virtual", "clr", "src", "verdict"))
    log(header)
    log("-" * len(header))
    results = []
    for case in CASES:
        engine_src = sq3.solve_optimized_v5 if case["mode"] == "q3" else \
            (lambda client, _p=locked_src_params, _s=sq4: _s.solve(client, **_p))
        engine_por = pq3.solve_optimized_v5 if case["mode"] == "q3" else \
            pq4locked.solve_locked
        src_run = run_engine(engine_src, case)
        por_run = run_engine(engine_por, case)
        ok, detail, problem = compare(case, src_run, por_run)
        results.append((case, ok, detail, problem))
        if not ok:
            FAILURES.append("%s: %s" % (case["name"], problem))
        log("%-26s %5d %5d %10.4f %4d %4s  %s"
            % (case["name"], detail["src_rows"], detail["por_rows"],
               detail["virtual"], detail["cleared"],
               "err" if detail["src_error"] else "ok",
               "PASS" if ok else "FAIL"))
        if not ok:
            log("     首个差异：%s" % problem)
        if detail.get("equivalent_failure"):
            log("     注：两侧以相同异常结束（等价失败）: %s"
                % detail["src_error"])

    log("")
    log("-- 汇总 --")
    q3 = [r for r in results if r[0]["mode"] == "q3"]
    q4 = [r for r in results if r[0]["mode"] == "q4"]
    log("  Q3 用例 %d 个（PASS %d）：%s"
        % (len(q3), sum(1 for r in q3 if r[1]),
           ", ".join("%s=%d acts/%.1fs/%d clears"
                     % (r[0]["name"].split("_seed")[0] + " n" + str(r[2]["sources"]),
                        r[2]["por_rows"], r[2]["virtual"], r[2]["cleared"])
                     for r in q3)))
    log("  Q4 用例 %d 个（PASS %d）" % (len(q4), sum(1 for r in q4 if r[1])))
    log("  JSON 逐字节相等：%d/%d" % (sum(1 for r in results if r[2]["json_equal"]),
                                     len(results)))
    completed = [r for r in results if not r[2]["src_error"]]
    log("  正常跑完（无异常）：%d/%d" % (len(completed), len(results)))
    for note in NOTES:
        log("  note: %s" % note)

    if FAILURES:
        log("")
        log("VERDICT: FAIL（%d 项）" % len(FAILURES))
        for item in FAILURES:
            log("  - %s" % item)
        return 1
    if len(completed) != len(results):
        log("")
        log("VERDICT: FAIL（存在等价失败用例，不能作为逐位等价证据）")
        return 1
    log("")
    log("VERDICT: PASS — 源引擎与吸收件引擎在 %d 个确定性用例上"
        "动作序列/虚拟时长/清除集合/返回 JSON 逐位相同" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
