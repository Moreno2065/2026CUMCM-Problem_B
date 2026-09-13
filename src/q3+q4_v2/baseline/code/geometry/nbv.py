# -*- coding: utf-8 -*-
"""NBV（Next-Best-View）评价：J(S) = Q(S)，最坏情况定位区域直径。

对候选检测点 S：
- 真实源在可行域 P_c 内 => S 处真实 bearing 落在 bearing_range(P_c, S)；
- 考虑测向误差 ±1°，可采纳的示向度 θ̂ ∈ [θ_min - 1°, θ_max + 1°]；
- 在该区间上以确定性步长（默认 0.5°）扫描假设示向度，
  计算交集后区域直径 D(P ∩ W(S, θ̂) ∩ B(S,1500))，取最大值（最坏情况）；
- gain = D(P) - max_θ̂ D(...)，score = gain / cost。

纪律：禁止 Monte Carlo 随机撒点作为唯一评价手段——此处为确定性扫描。
"""

import math

from .constants import (
    BEARING_ERROR_DEG,
    EPS,
    MEASURE_TIME,
    MOVE_SPEED,
    DISK_POLYGON_SIDES,
)
from .diameter import diameter_value
from .mec import mec
from .wedge import bearing_range, wedge_intersect

DEFAULT_SCAN_STEP_DEG = 0.5


def _scan_worst(poly, S, measure_fn, step_deg, tol_deg, n_circle):
    """公共扫描骨架：对可采纳示向度区间扫描，返回 (worst_value, worst_bearing)。

    measure_fn(out) 把交集后区域映射为标量（直径或 MEC 半径）；
    out 为 None（空交）时计 0。
    """
    if poly is None:
        return 0.0, None
    lo, hi = bearing_range(poly, S, eps=EPS)
    # 可采纳示向度区间：真 bearing ± tol
    lo -= tol_deg
    hi += tol_deg
    if hi - lo >= 360.0:
        hi = lo + 360.0  # 全圆扫描
    worst_v = -1.0
    worst_bearing = None
    n_steps = max(1, int(math.ceil((hi - lo) / step_deg)))
    for k in range(n_steps + 1):
        theta = lo + k * step_deg
        if theta > hi + 1e-12:
            break
        out = wedge_intersect(poly, S, theta, tol_deg=tol_deg,
                              n_circle=n_circle)
        v = measure_fn(out) if out is not None else 0.0
        if v > worst_v:
            worst_v = v
            worst_bearing = theta % 360.0
    return max(worst_v, 0.0), worst_bearing


def worst_case_diameter(poly, S, step_deg=DEFAULT_SCAN_STEP_DEG,
                        tol_deg=BEARING_ERROR_DEG,
                        n_circle=DISK_POLYGON_SIDES):
    """在 S 处测量后，最坏情况（对可采纳示向度取 sup）的交集后区域直径。

    返回 (max_diameter, worst_bearing)。交集恒为空时返回 (0, None)。
    """
    return _scan_worst(poly, S, diameter_value, step_deg, tol_deg, n_circle)


def worst_case_radius(poly, S, step_deg=DEFAULT_SCAN_STEP_DEG,
                      tol_deg=BEARING_ERROR_DEG,
                      n_circle=DISK_POLYGON_SIDES):
    """在 S 处测量后，最坏情况的交集后区域 MEC 半径（评审第 5 点 ΔR_MEC）。

    最终清除判据是 R_MEC ≤ 20 m，因此以最坏情况 MEC 半径下降量为 gain
    比直径更贴近清除任务。返回 (max_radius, worst_bearing)。
    """
    return _scan_worst(poly, S, lambda out: mec(out)[1], step_deg, tol_deg,
                       n_circle)


def nbv_score(poly, S, current_pos=None, cost=None,
              step_deg=DEFAULT_SCAN_STEP_DEG, tol_deg=BEARING_ERROR_DEG,
              mode="diameter"):
    """计算候选检测点 S 的 NBV 评分。

    参数：
        poly        : 当前可行域（凸多边形顶点 list）
        S           : 候选检测点 (x, y)
        current_pos : 机器狗当前位置（用于默认 cost = 移动距离/速度 + 检测耗时）
        cost        : 显式给定成本（秒）；优先级高于 current_pos
        step_deg    : bearing 确定性扫描步长（度）
        mode        : "diameter"（ΔD 直径，默认兼容）或 "radius"（ΔR_MEC，
                      评审第 5 点：MEC 半径下降量最坏情况为 gain）

    返回 dict: {"gain", "cost", "score", "worst_diameter"/"worst_radius",
                "worst_bearing", "mode"}
    """
    if mode not in ("diameter", "radius"):
        raise ValueError("mode must be 'diameter' or 'radius'")
    if mode == "diameter":
        base = diameter_value(poly) if poly is not None else 0.0
        worst, worst_bearing = worst_case_diameter(poly, S, step_deg, tol_deg)
    else:
        base = mec(poly)[1] if poly is not None else 0.0
        worst, worst_bearing = worst_case_radius(poly, S, step_deg, tol_deg)
    gain = base - worst
    if cost is None:
        if current_pos is not None:
            move = math.hypot(S[0] - current_pos[0], S[1] - current_pos[1])
            cost = move / MOVE_SPEED + MEASURE_TIME
        else:
            cost = MEASURE_TIME
    cost = max(cost, 1e-9)
    return {
        "gain": gain,
        "cost": cost,
        "score": gain / cost,
        "worst_diameter": worst if mode == "diameter" else None,
        "worst_radius": worst if mode == "radius" else None,
        "worst_bearing": worst_bearing,
        "mode": mode,
    }
