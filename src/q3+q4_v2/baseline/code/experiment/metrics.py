# -*- coding: utf-8 -*-
"""指标统计：清除率、平均定位清除时间、移动距离、动作计数、时间分解。

平均定位清除时间 = Σ(清除成功虚拟时刻 − 首次 direction 虚拟时刻) / 清除数
（仅统计经 direction 定位后清除的频道；near 直达清除不计入分母，
单独给出 near_clear_count）。

跨案例统计口径（v2.1，评审第 5 点 / 题面口径）：
- 每案例给出 t_per_source_s = T_j / n_j（本案例总虚拟时间 / 源数）；
- 多案例聚合用 aggregate_cases()：聚合值 = 各案例 T_j/n_j 的算术平均
  （不是总时间/总源数）；同时给出 pooled 口径（ΣT_j/Σn_j）并标注，
  两者都写入，禁止混用。
"""

T_PER_SOURCE_BASIS = ("T_j/n_j per case: total virtual time of case j "
                      "divided by its source count n_j")
AGGREGATE_BASIS = ("arithmetic mean of per-case T_j/n_j "
                   "(NOT total_time/total_sources)")


def branch_metrics(ks, config, decision_trace=None):
    """Return stable, scalar E1-E4 evidence metrics for one run.

    ``joint_state_evaluations`` counts certificate candidate records actually
    scored by E2.  ``lookahead_decisions`` counts executed selections carrying
    E3 lookahead metadata.  Q3 treats every Q4-only field as non-applicable or
    zero, so suite schemas never depend on the enabled branch set.
    """
    if getattr(ks, "mode", None) != "Q4":
        return {
            "q4_certificate_layout": None,
            "q4_certificate_point_count": 0,
            "joint_state_evaluations": 0,
            "lookahead_decisions": 0,
            "q4_certified_cells_raw": 0,
            "q4_certified_cells_retained": 0,
            "q4_certified_cells_pruned": 0,
        }

    layout = getattr(config, "q4_certificate_layout", "lattice31")
    point_count = {"lattice31": 31, "sparse25": 25}.get(layout, 0)
    raw = sum(max(0, int(getattr(ch,
                                 "q4_certified_centers_raw_count", 0)))
              for ch in ks.channels.values())
    retained = sum(len(getattr(ch, "certified_centers", ()))
                   for ch in ks.channels.values())

    joint_evaluations = 0
    lookahead_decisions = 0
    for trace in decision_trace or ():
        if not isinstance(trace, dict):
            continue
        candidates = trace.get("candidates")
        if isinstance(candidates, list):
            joint_evaluations += sum(
                1 for candidate in candidates
                if isinstance(candidate, dict)
                and "joint_state_score" in candidate)
        selected = trace.get("selected")
        if isinstance(selected, dict) and "lookahead_depth" in selected:
            lookahead_decisions += 1

    return {
        "q4_certificate_layout": layout,
        "q4_certificate_point_count": point_count,
        "joint_state_evaluations": joint_evaluations,
        "lookahead_decisions": lookahead_decisions,
        "q4_certified_cells_raw": raw,
        "q4_certified_cells_retained": retained,
        "q4_certified_cells_pruned": max(0, raw - retained),
    }


def _first_vtime(ch_state, result):
    for obs in ch_state.observations:
        if obs["result"] == result:
            return obs["virtual_time"]
    return None


def compute_metrics(executor, ks, wall_clock_s, n_sources=None,
                    anomalies=None, fallback_records=None, config=None,
                    decision_trace=None):
    cleared = ks.cleared
    certified = ks.certified_absent

    loc_times = []
    near_clears = 0
    for ch in cleared:
        t_dir = _first_vtime(ch, "direction")
        t_clr = _first_vtime(ch, "cleared")
        if t_dir is not None and t_clr is not None:
            loc_times.append(t_clr - t_dir)
        else:
            near_clears += 1
    avg_loc = sum(loc_times) / len(loc_times) if loc_times else None

    ledger = dict(executor.ledger)
    ledger_sum = sum(ledger.values())
    total_v = executor.virtual_time
    metrics = {
        "cleared_count": len(cleared),
        "certified_absent_count": len(certified),
        "sources_total": n_sources,
        "clear_rate": (len(cleared) / n_sources)
        if n_sources else None,
        "avg_localize_clear_time_s": avg_loc,
        "near_clear_count": near_clears,
        # 题面口径：每案例 T_j / n_j
        "t_per_source_s": (total_v / n_sources) if n_sources else None,
        "t_per_source_basis": T_PER_SOURCE_BASIS,
        "total_move_distance_m": executor.move_distance,
        "n_measures": executor.n_measures,
        "n_switches": executor.n_switches,
        "n_clear_attempts": executor.n_clear_attempts,
        "n_clear_success": executor.n_clear_success,
        "T_move": ledger["T_move"],
        "T_measure": ledger["T_measure"],
        "T_switch": ledger["T_switch"],
        "T_clear": ledger["T_clear"],
        "T_ledger_sum": ledger_sum,
        "T_total_virtual": total_v,
        # 时间分解之和应等于总虚拟时间（±1e-3 由验收测试断言）
        "ledger_minus_total": ledger_sum - total_v,
        "wall_clock_s": wall_clock_s,
        "reconcile_warnings": list(executor.reconcile_warnings),
        "anomalies": list(anomalies or []),
        # FALLBACK_CLEAR 触发/结果记录（评审第 1 点对账；几何快照不入指标）
        "fallback_records": [
            {k: v for k, v in rec.items() if k not in ("region", "points")}
            for rec in (fallback_records or [])],
        "status_summary": ks.summary(),
    }
    metrics.update(branch_metrics(ks, config, decision_trace))
    return metrics


def aggregate_cases(metrics_list):
    """多案例聚合（评审第 5 点）：各案例 T_j/n_j 的算术平均为主口径。

    参数：各案例 compute_metrics 返回的 dict 列表。
    返回 dict:
        mean_t_per_source_s   : (1/m) Σ_j T_j/n_j —— 主口径
        pooled_time_per_source: (Σ_j T_j)/(Σ_j n_j) —— 参考口径（标注，
                                不作为跨案例比较依据）
        basis                 : 口径说明
        n_cases               : 参与聚合的案例数
    """
    cases = [m for m in metrics_list
             if m.get("t_per_source_s") is not None]
    n = len(cases)
    mean_tps = (sum(m["t_per_source_s"] for m in cases) / n) if n else None
    total_t = sum(m["T_total_virtual"] for m in cases)
    total_src = sum(m["sources_total"] for m in cases)
    pooled = (total_t / total_src) if total_src else None
    return {
        "mean_t_per_source_s": mean_tps,
        "pooled_time_per_source_s": pooled,
        "basis": AGGREGATE_BASIS,
        "pooled_basis": "sum(T_j)/sum(n_j) — reference only, not the "
                        "cross-case comparison metric",
        "n_cases": n,
    }
