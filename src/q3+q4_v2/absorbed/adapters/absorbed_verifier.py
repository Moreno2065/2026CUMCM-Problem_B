# -*- coding: utf-8 -*-
"""吸收运行结果的独立校验（静态可读、运行期可执行）。

设计原则：**只从被验证对象自己交回的观测量里复核**，不重新实现引擎算法，
不拿真值去「补足」引擎没有给出的证据。

真复用（v2 verifier 原语，逐条调用）：
- ``verifier/q3_cover_verifier.py:26`` ``verify_q3_cover(no_signal_points, ...)``
  -> Q3 缺席频道的 Ω 覆盖复核（采样密度取 ``experiment/runner.py:65-66`` 的
     ``VERIFY_BOUNDARY_SAMPLES=1440`` / ``VERIFY_GRID_STEP=90.0``，与生产
     verifier 的第二意见同口径）。
- ``verifier/geometry_verifier.py:15`` ``verify_mec_covers(polygon, center, radius)``
  -> 「已认证清除」不变式：清除前可行域的全部顶点必须落在 B(清除点, 20) 内。
- ``runtime.py:749-770`` ``report_line`` -> 由 ``runtime_bridge.load_report_line``
  惰性复用（本模块只登记是否复用成功）。

明确 **不复用**（并登记为 not_performed，不做静默近似）：
- ``experiment/runner.py:787-904`` ``GameRunner._verify`` 的结论全部来自
  ``self.ks``（``KnowledgeState``），而两台吸收引擎不维护 K_t，因此无法复用；
  本模块用「VERSION/SELECTED 参数 + 清除尝试记录 + 缺席证据 + 合成真值」重建
  可判定的部分。
- Q4 的 Δθ 三角/连续证书（``coverage.py`` / ``search_nets.py`` 内部判定）不从
  返回字典可重放，登记为 not_performed；Q4 缺席只复核引擎自身闭包规则
  （``strategy_v4.py:57`` 全部非退役站点 no_signal）与真值。
"""

from __future__ import annotations

from .runtime_bridge import json_safe

# 题设冻结常数（baseline/code/geometry/constants.py:19,26）——仅在 v2 依赖不可
# 导入时用于「结构检查」，几何检查此时已被登记为 skipped。
FALLBACK_MAX_SOURCES = 16
FALLBACK_CLEAR_RADIUS = 20.0

# 采样密度与生产 verifier 第二意见一致（experiment/runner.py:65-66）
VERIFY_BOUNDARY_SAMPLES = 1440
VERIFY_GRID_STEP = 90.0

# 引擎自带的动作上限（len(client.rows) 口径，含 /enter 与 /exit）
# q3_optimizer_v5.py:166 -> 550；strategy_v4.py:240 -> 3500
ENGINE_ACTION_CAPS = {"q3-v5": 550, "q4-v4": 3500}

_BOUND_TOL = 1e-6


def _load_v2():
    """惰性导入 v2 verifier 原语；返回 (primitives, reasons)。"""
    from .runtime_bridge import ensure_v2_import_path
    primitives = {"C": None, "verify_mec_covers": None, "verify_q3_cover": None}
    reasons = []
    try:
        ensure_v2_import_path()
    except Exception as exc:                                   # pragma: no cover
        reasons.append("ensure_v2_import_path: %s: %s"
                       % (type(exc).__name__, exc))
    try:
        from geometry import constants as C
        primitives["C"] = C
    except Exception as exc:
        reasons.append("geometry.constants: %s: %s"
                       % (type(exc).__name__, exc))
    try:
        from verifier.geometry_verifier import verify_mec_covers
        primitives["verify_mec_covers"] = verify_mec_covers
    except Exception as exc:
        reasons.append("verifier.geometry_verifier.verify_mec_covers: %s: %s"
                       % (type(exc).__name__, exc))
    try:
        from verifier.q3_cover_verifier import verify_q3_cover
        primitives["verify_q3_cover"] = verify_q3_cover
    except Exception as exc:
        reasons.append("verifier.q3_cover_verifier.verify_q3_cover: %s: %s"
                       % (type(exc).__name__, exc))
    return primitives, reasons


def _as_point(value):
    if value is None:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except Exception:
        return None


def _channel_of(record):
    try:
        return int(record["channel"])
    except Exception:
        return None


def _lookup(mapping, channel):
    """键可能是 int 或 str（引擎内是 int，落盘 JSON 后是 str）。"""
    if mapping is None:
        return None
    if channel in mapping:
        return mapping[channel]
    return mapping.get(str(channel))


def verify_absorbed_run(mode, engine, engine_version, result, adapter,
                        *, simulator=None, executor=None, engine_meta=None,
                        socket_guard=None, sim=None):
    """复核一次吸收运行；返回可 JSON 化的 verifier report。

    ``all_ok`` 为真当且仅当没有任何 **已执行** 检查失败；被跳过（skipped）的
    检查一定带 reason 并进入 ``not_performed``，不会伪装成通过。
    """
    mode = str(mode).upper()
    engine = str(engine)
    executor = executor if executor is not None else getattr(adapter, "executor",
                                                            None)
    checks = []
    not_performed = []
    primitives, v2_reasons = _load_v2()
    C = primitives["C"]
    max_sources = int(getattr(C, "MAX_SOURCES", FALLBACK_MAX_SOURCES))
    clear_radius = float(getattr(C, "CLEAR_RADIUS", FALLBACK_CLEAR_RADIUS))

    def add(check_id, description, status, detail=None, reason=None):
        """reason ∈ {None, "not_applicable", "unavailable"}（切片口径见模块 docstring）。"""
        checks.append({"id": check_id, "check": description, "status": status,
                       # INTERFACE_MAP §6.3 口径：逐项 ok/not_applicable。
                       # 本模块保留更严格的三态 status；skipped 一律 ok=None，
                       # **永不**写成 ok=true。
                       "ok": (True if status == "passed" else
                              False if status == "failed" else None),
                       "reason": reason,
                       "not_applicable": (reason == "not_applicable"),
                       "detail": json_safe(detail)})

    def skip_not_applicable(check_id, description, why):
        """**模式性**不适用：该检查在当前模式下本就不该跑（如官方模式无真值）。"""
        not_performed.append({"id": check_id, "reason": why,
                              "reason_kind": "not_applicable"})
        add(check_id, description, "skipped", {"reason": why},
            reason="not_applicable")

    def skip_unavailable(check_id, description, why):
        """**本应可跑但证据/工具缺失**：这是缺陷信号，必须阻止 all_ok=true。

        （`no_unavailable_evidence` 检查项把这条不变量变成可计数的失败，
        因此官方模式下的工具缺失同样不会被吞掉。）
        """
        not_performed.append({"id": check_id, "reason": why,
                              "reason_kind": "unavailable"})
        add(check_id, description, "skipped", {"reason": why},
            reason="unavailable")

    # ------------------------------------------------------------------
    # 0. 结构
    # ------------------------------------------------------------------
    if not isinstance(result, dict):
        add("result_shape", "引擎返回值是 dict", "failed",
            {"type": type(result).__name__})
        return _finish(checks, not_performed, v2_reasons, engine_meta,
                       socket_guard, adapter, [], False, mode=mode, sim=sim)
    entries = result.get("cleared_sources")
    if not isinstance(entries, list):
        entries = []
        add("result_shape", "返回字典含 cleared_sources 列表", "failed",
            {"keys": sorted(map(str, result.keys()))[:40]})
        return _finish(checks, not_performed, v2_reasons, engine_meta,
                       socket_guard, adapter, [], False, mode=mode, sim=sim)
    add("result_shape", "返回字典含 cleared_sources 列表", "passed",
        {"keys": sorted(map(str, result.keys()))[:40],
         "n_cleared_entries": len(entries)})

    cleared_channels = []
    bad_entries = []
    for entry in entries:
        channel = _channel_of(entry)
        if channel is None:
            bad_entries.append(repr(entry)[:120])
        else:
            cleared_channels.append(channel)
    add("cleared_entries_channel_field",
        "每个 cleared_sources 记录都带 channel",
        "passed" if not bad_entries else "failed",
        {"bad_entries": bad_entries[:5], "n_bad": len(bad_entries)})

    reported_count = result.get("cleared_count", len(cleared_channels))
    try:
        reported_count = int(reported_count)
    except Exception:
        reported_count = -1
    add("cleared_count_consistent",
        "cleared_count 与 cleared_sources 条数一致",
        "passed" if reported_count == len(cleared_channels) else "failed",
        {"cleared_count": reported_count, "entries": len(cleared_channels)})
    add("cleared_count_bounds",
        "清除数落在题设区间 [10, %d]" % max_sources,
        "passed" if 10 <= reported_count <= max_sources else "failed",
        {"cleared_count": reported_count})
    add("cleared_channels_unique",
        "已清除频道互不重复且落在 1..20",
        "passed" if (len(set(cleared_channels)) == len(cleared_channels)
                     and all(1 <= c <= 20 for c in cleared_channels))
        else "failed",
        {"channels": sorted(cleared_channels)})

    # ------------------------------------------------------------------
    # 1. 清除尝试：报告的界与独立重算的界一致（复用 verify_mec_covers）
    # ------------------------------------------------------------------
    attempts = result.get("clear_attempts")
    if not isinstance(attempts, list):
        attempts = []
    by_channel = {}
    for record in attempts:
        channel = _channel_of(record)
        point = _as_point(record.get("position"))
        response = record.get("response") or {}
        success = (response.get("clear_result") == "success")
        if channel is None or point is None:
            continue
        by_channel.setdefault(channel, []).append(
            {"point": point, "success": success, "record": record})

    verify_mec = primitives["verify_mec_covers"]
    if verify_mec is None:
        skip_unavailable("clear_attempt_bound_identity",
                         "清除尝试报告的 prior_bound_m 与独立重算一致",
                         "v2 verifier.geometry_verifier 不可导入："
                         + "; ".join(v2_reasons))
        skip_unavailable("certified_clear_geometry",
                         "prior_geometry 清除的全部顶点落在 B(清除点, 20) 内",
                         "v2 verifier.geometry_verifier 不可导入")
    elif not attempts:
        skip_unavailable("clear_attempt_bound_identity",
                         "清除尝试报告的 prior_bound_m 与独立重算一致",
                         "引擎未返回 clear_attempts（本应可跑但证据缺失）")
        skip_unavailable("certified_clear_geometry",
                         "prior_geometry 清除的全部顶点落在 B(清除点, 20) 内",
                         "引擎未返回 clear_attempts（本应可跑但证据缺失）")
    else:
        mismatches = []
        recalculated = {}
        checked = 0
        for channel, records in sorted(by_channel.items()):
            for row in records:
                record = row["record"]
                vertices = record.get("prior_vertices")
                reported = record.get("prior_bound_m")
                if vertices:
                    out = verify_mec(vertices, row["point"], clear_radius)
                    expected = out.get("max_dist")
                    checked += 1
                else:
                    expected = 5.0          # prior is the 5 m near disk
                recalculated[channel] = {"expected": expected,
                                         "point": row["point"],
                                         "success": row["success"],
                                         "vertices": bool(vertices)}
                if reported is None or expected is None:
                    mismatches.append({"channel": channel,
                                       "reported": reported,
                                       "expected": expected})
                    continue
                if abs(float(reported) - float(expected)) > _BOUND_TOL:
                    mismatches.append({"channel": channel,
                                       "reported": float(reported),
                                       "expected": float(expected)})
        add("clear_attempt_bound_identity",
            "清除尝试报告的 prior_bound_m 与独立重算的 max 顶点距离一致",
            "passed" if not mismatches else "failed",
            {"n_attempts": len(attempts), "n_vertices_checked": checked,
             "n_mismatch": len(mismatches), "mismatch": mismatches[:8]})

        violations = []
        n_guaranteed = 0
        for entry in entries:
            channel = _channel_of(entry)
            basis = entry.get("bound_source")
            if basis != "prior_geometry" or channel not in recalculated:
                continue
            info = recalculated[channel]
            if not info["vertices"]:
                n_guaranteed += 1
                continue
            vertices = None
            for row in by_channel.get(channel, []):
                if row["success"]:
                    vertices = row["record"].get("prior_vertices")
                    break
            if not vertices:
                continue
            out = verify_mec(vertices, info["point"], clear_radius)
            n_guaranteed += 1
            if not out.get("ok"):
                violations.append({"channel": channel,
                                   "max_dist": out.get("max_dist"),
                                   "radius": clear_radius})
        add("certified_clear_geometry",
            "bound_source=prior_geometry 的清除：可行域全部顶点落在 B(清除点, 20)",
            "passed" if not violations else "failed",
            {"n_checked": n_guaranteed, "violations": violations[:8]})

    # ------------------------------------------------------------------
    # 2. 缺席声明
    # ------------------------------------------------------------------
    geometric_absent = set()
    cardinality_absent = set()
    unresolved = []

    if mode == "Q3":
        negatives = result.get("negative_observations") or {}
        verify_q3 = primitives["verify_q3_cover"]
        if verify_q3 is None:
            skip_unavailable("q3_absence_cover",
                             "Q3 几何缺席频道的 no_signal 点集覆盖 Ω",
                             "v2 verifier.q3_cover_verifier 不可导入："
                             + "; ".join(v2_reasons))
        elif not negatives:
            inferred = list(result.get("count_inferred_absent_channels") or [])
            if inferred:
                skip_not_applicable(
                    "q3_absence_cover",
                    "Q3 几何缺席频道的 no_signal 点集覆盖 Ω",
                    "本局缺席全部来自 %d 个基数推断（已清除 %d 个即上界），"
                    "不存在几何覆盖声明可供复算"
                    % (len(inferred), reported_count))
            else:
                skip_unavailable(
                    "q3_absence_cover",
                    "Q3 几何缺席频道的 no_signal 点集覆盖 Ω",
                    "引擎既未返回 negative_observations 也无基数依据"
                    "（本应可跑但缺席证据缺失）")
        else:
            results = {}
            for key, points in sorted(negatives.items(), key=lambda kv: str(kv[0])):
                points = list(points or [])
                try:
                    out = verify_q3(points,
                                    boundary_samples=VERIFY_BOUNDARY_SAMPLES,
                                    grid_step=VERIFY_GRID_STEP)
                except Exception as exc:
                    results[str(key)] = {"ok": False,
                                         "error": "%s: %s" % (type(exc).__name__, exc)}
                    continue
                results[str(key)] = {"ok": bool(out.get("ok")),
                                     "uncovered_count": out.get("uncovered_count"),
                                     "max_min_dist": out.get("max_min_dist"),
                                     "n_points": len(points)}
            bad = {k: v for k, v in results.items() if not v.get("ok")}
            add("q3_absence_cover",
                "Q3 几何缺席频道：no_signal 点集覆盖 Ω（verify_q3_cover 独立复算）",
                "passed" if not bad else "failed",
                {"n_channels": len(results), "n_failed": len(bad),
                 "failed": bad, "all": results})
            geometric_absent = {int(k) for k in results}
        for channel in (result.get("count_inferred_absent_channels") or []):
            cardinality_absent.add(int(channel))
        stop_flag = bool(result.get("source_upper_bound_stop"))
        if cardinality_absent:
            ok = stop_flag and reported_count == max_sources
            add("q3_cardinality_absent",
                "基数缺席（已清除 %d 个即上界）成立" % max_sources,
                "passed" if ok else "failed",
                {"source_upper_bound_stop": stop_flag,
                 "cleared_count": reported_count,
                 "channels": sorted(cardinality_absent)})
        declared = [int(c) for c in (result.get("cleared_channels") or [])]
        if declared:
            add("q3_cleared_channels_field",
                "cleared_channels 字段与 cleared_sources 一致",
                "passed" if sorted(declared) == sorted(cleared_channels)
                else "failed",
                {"declared": sorted(declared),
                 "entries": sorted(cleared_channels)})

    else:                                                    # mode == "Q4"
        absent = {int(c) for c in (result.get("absent_channels") or [])}
        stations = result.get("stations") or []
        required = result.get("required_station_indices")
        negatives = result.get("all_station_no_signal_channels") or {}
        active_count = (len(required) if required is not None
                        else len(stations))
        stop_flag = bool(result.get("count_upper_bound_stop"))
        by_reason = []
        for channel in sorted(absent):
            points = _lookup(negatives, channel) or []
            n_no_signal = len(set(points))
            if n_no_signal == active_count and active_count > 0:
                geometric_absent.add(channel)
                by_reason.append({"channel": channel, "basis": "all_stations",
                                  "n_no_signal": n_no_signal,
                                  "active_stations": active_count})
            elif stop_flag and reported_count == max_sources:
                cardinality_absent.add(channel)
                by_reason.append({"channel": channel, "basis": "cardinality16",
                                  "n_no_signal": n_no_signal,
                                  "active_stations": active_count})
            else:
                by_reason.append({"channel": channel,
                                  "basis": "unsupported_claim",
                                  "n_no_signal": n_no_signal,
                                  "active_stations": active_count})
        unsupported = [r for r in by_reason if r["basis"] == "unsupported_claim"]
        add("q4_absent_basis",
            "Q4 每个缺席频道都有可复核依据（全站点 no_signal 或 16 基数）",
            "passed" if not unsupported else "failed",
            {"n_absent": len(absent), "active_stations": active_count,
             "count_upper_bound_stop": stop_flag,
             "cleared_count": reported_count,
             "n_unsupported": len(unsupported),
             "unsupported": unsupported[:8], "detail": by_reason[:24]})

    # ------------------------------------------------------------------
    # 3. 完成性：20 个频道都有终态
    # ------------------------------------------------------------------
    resolved = set(cleared_channels) | geometric_absent | cardinality_absent
    unresolved = sorted(set(range(1, 21)) - resolved)
    add("completion_all_channels_resolved",
        "20 个频道都被清除或判定缺席（无悬空频道）",
        "passed" if not unresolved else "failed",
        {"n_resolved": len(resolved), "unresolved_channels": unresolved})

    # ------------------------------------------------------------------
    # 4. 合成真值（官方 http 模式没有真值 -> 明确 skipped）
    # ------------------------------------------------------------------
    sources = {}
    if simulator is not None:
        for src in getattr(simulator, "sources", []) or []:
            sources[int(getattr(src, "channel", -1))] = src
    if simulator is None:
        for check_id in ("truth_cleared_channels", "truth_absent_channels"):
            skip_not_applicable(check_id, "合成真值核对",
                                "官方 http 模式无真值来源（模式性不适用）")
    else:
        truth_fail = []
        for channel in sorted(cleared_channels):
            src = sources.get(channel)
            if src is None:
                truth_fail.append({"channel": channel,
                                   "problem": "真值中不存在该频道源"})
                continue
            if not bool(getattr(src, "cleared", False)):
                truth_fail.append({"channel": channel,
                                   "problem": "真值源未被清除"})
                continue
            point = None
            for row in by_channel.get(channel, []):
                if row["success"]:
                    point = row["point"]
                    break
            if point is None:
                entry = next((e for e in entries
                              if _channel_of(e) == channel), {})
                point = _as_point(entry.get("point")
                                  or entry.get("clear_point"))
            if point is None:
                truth_fail.append({"channel": channel,
                                   "problem": "无成功清除点可核对"})
                continue
            distance = ((point[0] - float(src.x)) ** 2
                        + (point[1] - float(src.y)) ** 2) ** 0.5
            if distance > clear_radius + _BOUND_TOL:
                truth_fail.append({"channel": channel,
                                   "problem": "清除点距真值源超过 20 m",
                                   "distance_m": distance})
        add("truth_cleared_channels",
            "每个已清除频道在真值中确实存在、已清除且清除点距源 ≤ 20 m",
            "passed" if not truth_fail else "failed",
            {"n_cleared": len(cleared_channels), "n_failed": len(truth_fail),
             "failures": truth_fail[:8]})

        absence_fail = []
        for channel in sorted(geometric_absent | cardinality_absent):
            src = sources.get(channel)
            if src is not None and not bool(getattr(src, "cleared", False)):
                absence_fail.append({
                    "channel": channel,
                    "problem": "缺席声明与真值冲突（该频道真值源仍存在）",
                    "source_position": [float(src.x), float(src.y)]})
        add("truth_absent_channels",
            "每个缺席频道在真值中确实不存在未清除的源",
            "passed" if not absence_fail else "failed",
            {"n_absent": len(geometric_absent | cardinality_absent),
             "n_failed": len(absence_fail), "failures": absence_fail[:8]})

    # ------------------------------------------------------------------
    # 5. 行结构与虚拟时间（客户端侧证据）
    # ------------------------------------------------------------------
    rows = list(getattr(adapter, "rows", []) or [])
    add("rows_present", "客户端动作记录非空", "passed" if rows else "failed",
        {"n_rows": len(rows)})
    from .v3_client import ROW_KEYS
    bad_rows = [i for i, row in enumerate(rows)
                if tuple(sorted(row)) != tuple(sorted(ROW_KEYS))]
    add("rows_reference_shape",
        "动作记录键集与源侧 offline_world 行结构一致",
        "passed" if not bad_rows else "failed",
        {"expected_keys": list(ROW_KEYS), "n_bad": len(bad_rows),
         "first_bad_index": (bad_rows[0] if bad_rows else None)})
    regressions = []
    previous = None
    for index, row in enumerate(rows):
        current = row.get("virtual_after_s")
        if current is None:
            continue
        if previous is not None and float(current) < previous - 1e-9:
            regressions.append({"index": index, "before": previous,
                                "after": float(current)})
        previous = float(current)
    add("virtual_time_monotonic", "动作记录的虚拟时间非递减",
        "passed" if not regressions else "failed",
        {"n_rows": len(rows), "n_regressions": len(regressions),
         "regressions": regressions[:5]})
    cap = ENGINE_ACTION_CAPS.get(engine)
    if cap is None:
        skip_unavailable("action_cap", "动作数不超过引擎自带上限",
                         "未知引擎名 %r（无法判定上限，属本应可跑但配置缺失）"
                         % engine)
    else:
        add("action_cap", "动作数不超过引擎自带上限 %d" % cap,
            "passed" if len(rows) <= cap else "failed",
            {"n_rows": len(rows), "cap": cap})

    warnings = list(getattr(executor, "reconcile_warnings", []) or [])
    add("v2_virtual_time_reconcile",
        "v2 本地虚拟时间账与服务端上报值无对账告警（容差 1e-3）",
        "passed" if not warnings else "failed",
        {"n_warnings": len(warnings), "warnings": warnings[:5]})

    # ------------------------------------------------------------------
    # 6. 登记项
    # ------------------------------------------------------------------
    if socket_guard is not None:
        ok = bool(socket_guard.get("ok"))
        add("socket_bindings_intact",
            "导入 vendored 引擎前后，socket/urllib 绑定未被替换",
            "passed" if ok else "failed", socket_guard)
    if mode == "Q4":
        not_performed.append({
            "id": "q4_certificate_replay",
            "reason": ("Q4 Δθ 三角/连续证书由引擎内部判定（coverage/search_nets），"
                       "不从返回字典可重放；生产 verifier（runner.py:787-904）"
                       "依赖 KnowledgeState，吸收引擎不维护 K_t，因此本项无法重放。")})
    else:
        not_performed.append({
            "id": "q3_continuous_cover_replay",
            "reason": ("Q3 连续覆盖证书由引擎内部判定（q3_optimizer_v4."
                       "continuous_cover）；本 verifier 不复用该判定，改用它交回的 "
                       "no_signal 点集独立复算 Ω ⊆ ∪B(p, r_eff_min)"
                       "（verify_q3_cover，采样第二意见）。")})
    not_performed.append({
        "id": "v2_metrics_compute_metrics",
        "reason": ("baseline/code/experiment/metrics.py 的 compute_metrics 需要 "
                   "KnowledgeState；吸收运行以 executor 账本重建同名字段，"
                   "字段口径见 absorbed/adapters/runtime_bridge.build_metrics。")})
    return _finish(checks, not_performed, v2_reasons, engine_meta, socket_guard,
                   adapter, unresolved, simulator is not None, mode=mode, sim=sim)


def _finish(checks, not_performed, v2_reasons, engine_meta, socket_guard,
            adapter, unresolved, ground_truth_available, mode="Q3", sim=None):
    # 不变量（captain 规格）：出现 "unavailable"（本应可跑但证据/工具缺失）时
    # **必须**阻止 all_ok=true；"not_applicable"（模式性不适用）不阻断。
    # 该不变量本身作为一个可计数的检查项参与 counts，因此不会被吞掉。
    unavailable_ids = [c["id"] for c in checks if c.get("reason") == "unavailable"]
    not_applicable_ids = [c["id"] for c in checks
                          if c.get("reason") == "not_applicable"]
    checks.append({
        "id": "no_unavailable_evidence",
        "check": ("不存在「本应可跑但证据/工具缺失」的检查"
                  "（unavailable 必须阻断通过）"),
        "status": "failed" if unavailable_ids else "passed",
        "ok": not unavailable_ids,
        "reason": None,
        "not_applicable": False,
        "detail": {"unavailable_checks": unavailable_ids,
                   "not_applicable_checks": not_applicable_ids,
                   "policy": ("unavailable 一律阻断 all_ok（官方模式同样适用："
                              "非模式性缺失即视为缺陷）；"
                              "not_applicable 不阻断")},
    })
    counts = {"total": len(checks), "passed": 0, "failed": 0, "skipped": 0}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    all_ok = counts["failed"] == 0
    scope = {
        "mode": str(mode).upper(),
        "sim": sim if sim is not None else "unknown",
        "ground_truth": ("available" if ground_truth_available
                         else "unavailable"),
        "not_applicable_checks": not_applicable_ids,
        "unavailable_checks": unavailable_ids,
        "description": ("独立复核范围：结构与协议自述、清除尝试界与认证清除几何"
                        "（verify_mec_covers）、Q3 缺席覆盖（verify_q3_cover）、"
                        "完成性与 rows/虚拟时间不变量；合成模式另有真值核对。"
                        "不复用 GameRunner._verify（依赖 KnowledgeState）。"
                        "官方 http 模式无真值 → 真值类检查 not_applicable，"
                        "不会写成 ok=true。"),
    }
    reuse = {
        "verify_q3_cover": "used",
        "verify_mec_covers": "used",
        "report_line": "runtime_bridge.load_report_line（惰性）",
        "GameRunner._verify": "not_reusable: 依赖 KnowledgeState",
        "import_reasons": list(v2_reasons),
    }
    if any(check["id"] == "q3_absence_cover"
           and check["status"] == "skipped" for check in checks):
        reuse["verify_q3_cover"] = "unavailable_or_no_evidence"
    if any(check["id"] == "clear_attempt_bound_identity"
           and check["status"] == "skipped" for check in checks):
        reuse["verify_mec_covers"] = "unavailable_or_no_evidence"
    return {
        "all_ok": bool(all_ok),
        "scope": scope,
        "checks": checks,
        "counts": counts,
        "not_performed": not_performed,
        "v2_verifier_reuse": reuse,
        "ground_truth_available": bool(ground_truth_available),
        "unresolved_channels": list(unresolved),
        "engine_meta": json_safe(engine_meta or {}),
        "socket_guard": json_safe(socket_guard or {}),
        "client_snapshot": json_safe(
            adapter.snapshot() if hasattr(adapter, "snapshot") else {}),
    }
