# -*- coding: utf-8 -*-
"""确定性证书模块。

Q3（全向源）圆盘覆盖证书：
    no_signal @ S  =>  B(S, 1000) 内无该频道未清除源。
    证书成立 ⟺ Ω ⊆ ∪ B(S_i, 1000)。
    判定为精确 arrangement 检查（非纯采样）：
      1. 若某圆盘完全包含 Ω（‖S‖+1800 ≤ 1000），直接成立；
      2. ∂Ω 覆盖检查：每个圆盘在 ∂Ω 上覆盖一段（或零/整圈）圆弧，
         对圆弧区间做精确并集判定；
      3. 若 ∂Ω 被完整覆盖，未覆盖区域只能是边界由圆盘圆弧组成的
         内部空洞；逐圆盘求其边界圆上"未被其它圆盘覆盖且位于 Ω 内"
         的弧段，弧中点沿外法向多尺度探针探测，命中未覆盖点即失败。
    另提供可选网格二次确认 q3_certified_grid_confirm。

Q4（定向源）δ-稳健凸包证书，参数 (s, δ) = (620, 370)：
    A_δ(x) = { no_signal 点 p : ‖p−x‖ ≤ 1000−δ = 630 }
    若 B(x, δ) ⊆ conv(A_δ(x))，则 B(x, δ) 内不可能存在该频道未清除定向源
    （任何 180° 闭半平面都含至少一个见证点 p，且对任意 G ∈ B(x,δ)，
      ‖p−G‖ ≤ ‖p−x‖+δ ≤ 1000 ≤ R_eff，与 no_signal 矛盾）。
    精确判定：B(x,δ) ⊆ conv(A) ⟺ x ∈ conv(A) 且 conv 每条边到 x 的
    距离 ≥ δ（内切条件），凸集性质保证该条件充要。
    频道完成判定：Ω ⊆ ∪_{certified x_i} B(x_i, δ)（复用 Q3 圆盘覆盖判定）。
"""

import math

from .constants import (
    EPS,
    OMEGA_RADIUS,
    R_EFF_MIN,
    Q4_GRID_SPACING,
    Q4_DELTA,
    Q4_LATTICE_SPACING,
    Q4_LATTICE_BOUND,
    Q4_LATTICE_COUNT,
    LATTICE_MATCH_TOL,
)
from .polygon import convex_hull, area, edge_distance

# 证书判定的覆盖容差：距离 ≤ r + COVER_TOL 视为被覆盖。
# 取极小值保证证书几乎不放宽；构造余量（100 m / 12.25 m）远大于此。
COVER_TOL = 1e-6


# ---------------------------------------------------------------------------
# 圆-圆求交
# ---------------------------------------------------------------------------

def circle_circle_intersections(c0, r0, c1, r1, eps=EPS):
    """两圆边界交点，返回 0/1/2 个点。同心或重合圆返回空 list。"""
    dx = c1[0] - c0[0]
    dy = c1[1] - c0[1]
    d = math.hypot(dx, dy)
    if d <= eps:
        return []
    if d > r0 + r1 + eps or d < abs(r0 - r1) - eps:
        return []
    a = (r0 * r0 - r1 * r1 + d * d) / (2.0 * d)
    h2 = r0 * r0 - a * a
    h = math.sqrt(max(h2, 0.0))
    mx = c0[0] + a * dx / d
    my = c0[1] + a * dy / d
    if h <= eps:
        return [(mx, my)]
    rx = -dy / d * h
    ry = dx / d * h
    return [(mx + rx, my + ry), (mx - rx, my - ry)]


# ---------------------------------------------------------------------------
# Q3 圆盘覆盖证书
# ---------------------------------------------------------------------------

def _boundary_arcs(centers, R, r, eps=EPS):
    """每个圆盘在 ∂B(0,R) 上覆盖的圆弧区间列表（弧度，[0,2π) 内，可能 split）。

    返回 (intervals, full_circle_covered)。
    圆盘覆盖 ∂Ω 上点 p=R(cosφ,sinφ) ⟺ cos(φ−φ_S) ≥ (R²+d²−r²)/(2Rd)。
    """
    intervals = []
    for S in centers:
        d = math.hypot(S[0], S[1])
        if d <= eps:
            if R <= r + COVER_TOL:
                return [], True
            continue
        c = (R * R + d * d - r * r) / (2.0 * R * d)
        if c <= -1.0:
            return [], True  # 整圈覆盖
        if c >= 1.0:
            continue  # 不覆盖任何边界点
        phi_s = math.atan2(S[1], S[0]) % (2.0 * math.pi)
        alpha = math.acos(max(-1.0, min(1.0, c)))
        lo = phi_s - alpha
        hi = phi_s + alpha
        two_pi = 2.0 * math.pi
        lo_m = lo % two_pi
        hi_m = hi % two_pi
        if lo_m <= hi_m:
            intervals.append((lo_m, hi_m))
        else:
            intervals.append((lo_m, two_pi))
            intervals.append((0.0, hi_m))
    return intervals, False


def _arcs_cover_circle(intervals, tol=1e-9):
    """判断 [0, 2π) 是否被区间并集完整覆盖。"""
    two_pi = 2.0 * math.pi
    iv = sorted(intervals)
    covered_to = 0.0
    for lo, hi in iv:
        if lo > covered_to + tol:
            return False
        covered_to = max(covered_to, hi)
    return covered_to >= two_pi - tol


def q3_certified(no_signal_points, omega_radius=OMEGA_RADIUS,
                 cover_r=R_EFF_MIN):
    """精确判定 Ω ⊆ ∪ B(S_i, cover_r)。

    参数：
        no_signal_points : 该频道全部 no_signal 检测点 list[(x, y)]
        omega_radius     : Ω 半径（默认 1800）
        cover_r          : 排除圆半径（默认 1000 = R_eff 下界）

    返回 dict:
        certified        : bool
        reason           : 说明
        uncovered_point  : 若不成立，给出一个未被覆盖的见证点（可为 None）
    """
    centers = [(float(p[0]), float(p[1])) for p in no_signal_points]
    R = float(omega_radius)
    r = float(cover_r)
    if not centers:
        return {"certified": False, "reason": "no no_signal points",
                "uncovered_point": (0.0, 0.0)}

    # (c) 某圆盘完全包含 Ω
    for S in centers:
        if math.hypot(S[0], S[1]) + R <= r + COVER_TOL:
            return {"certified": True,
                    "reason": "single disk contains Omega",
                    "uncovered_point": None}

    # (a) ∂Ω 圆弧并集精确覆盖检查
    intervals, full = _boundary_arcs(centers, R, r)
    if not full and not _arcs_cover_circle(intervals):
        return {"certified": False,
                "reason": "Omega boundary not fully covered",
                "uncovered_point": _find_uncovered_boundary_point(
                    centers, R, r)}

    # (b) ∂Ω 已全覆盖：检查内部空洞。
    # 拓扑事实：∂Ω 被并集覆盖后，Ω 内未覆盖区域只能是边界完全由
    # 圆盘圆弧组成的"空洞"。空洞边界弧必为某圆盘 ∂D_i 上"未被其它
    # 圆盘覆盖且位于 Ω 内"的弧段。因此对每个圆盘求其边界圆上的
    # 未覆盖弧段，并在弧中点沿外法向微探针探测：探针点未被任何圆盘
    # 覆盖且仍在 Ω 内 ⇒ 空洞存在 ⇒ 证书不成立。
    hole = _find_interior_hole(centers, R, r)
    if hole is not None:
        return {"certified": False,
                "reason": "interior hole detected",
                "uncovered_point": hole}
    return {"certified": True,
            "reason": "boundary arcs cover Omega and no interior hole",
            "uncovered_point": None}


# 空洞探针步长（米）：远小于本问题任何几何尺度（余量 ≥ 12 m），
# 也远大于 COVER_TOL；< 2*PROBE 宽的狭缝视为容差内退化。
HOLE_PROBE = 0.5


def _angle_intervals_mod(lo, hi):
    """把 [lo, hi]（弧度，lo<=hi，宽度 <= 2π）规范为 [0,2π) 内的区间列表。"""
    two_pi = 2.0 * math.pi
    if hi - lo >= two_pi - 1e-12:
        return [(0.0, two_pi)]
    lo_m = lo % two_pi
    hi_m = hi % two_pi
    if lo_m <= hi_m:
        return [(lo_m, hi_m)]
    return [(lo_m, two_pi), (0.0, hi_m)]


def _subtract_intervals(base_intervals, cover_intervals, tol=1e-12):
    """从 base 区间集合中减去 cover 区间并集，返回剩余区间列表。

    所有区间均在 [0, 2π] 内。区间半宽 < tol 的残余直接丢弃。
    """
    result = []
    for blo, bhi in base_intervals:
        segs = [(blo, bhi)]
        for clo, chi in sorted(cover_intervals):
            new_segs = []
            for lo, hi in segs:
                if chi <= lo + tol or clo >= hi - tol:
                    new_segs.append((lo, hi))
                    continue
                if clo > lo + tol:
                    new_segs.append((lo, min(clo, hi)))
                if chi < hi - tol:
                    new_segs.append((max(chi, lo), hi))
            segs = new_segs
            if not segs:
                break
        result.extend(segs)
    return [(lo, hi) for lo, hi in result if hi - lo > 1e-9]


def _find_interior_hole(centers, R, r):
    """在 ∂Ω 已被覆盖的前提下，探测 Ω 内部的未覆盖空洞。

    对每个圆盘 D_i：
      1. 求 ∂D_i 落在 Ω 内的角度区间（相对 c_i 指向原点的方向）；
      2. 求 ∂D_i 被其它圆盘 D_j 覆盖的角度区间；
      3. 差集非空 ⇒ 取弧中点 m，沿外法向（远离 c_i）探针 q=m+δ·n，
         q 在 Ω 内且未被任何圆盘覆盖 ⇒ 返回 q 作为空洞见证点。
    全部圆盘无空洞弧 ⇒ 返回 None。

    注：覆盖弧半角公式 arccos(d/(2r)) 利用了本问题所有覆盖圆半径
    相等（Q3: 1000 m，Q4: δ=370 m）的事实；不等半径需推广公式。
    """
    n = len(centers)
    for i in range(n):
        ci = centers[i]
        d0 = math.hypot(ci[0], ci[1])
        # 1. ∂D_i 在 Ω 内的角度区间
        if d0 <= EPS:
            inside = [(0.0, 2.0 * math.pi)] if r <= R + COVER_TOL else []
        else:
            c_ratio = (r * r + d0 * d0 - R * R) / (2.0 * r * d0)
            if c_ratio <= -1.0:
                inside = [(0.0, 2.0 * math.pi)]      # 整圆在 Ω 内
            elif c_ratio >= 1.0:
                inside = []                           # 整圆在 Ω 外
            else:
                gamma = math.acos(max(-1.0, min(1.0, c_ratio)))
                phi_o = math.atan2(-ci[1], -ci[0])    # 指向原点方向
                inside = _angle_intervals_mod(phi_o - gamma,
                                              phi_o + gamma)
        if not inside:
            continue
        # 2. ∂D_i 被其它圆盘覆盖的角度区间
        cover = []
        for j in range(n):
            if j == i:
                continue
            cj = centers[j]
            d = math.hypot(cj[0] - ci[0], cj[1] - ci[1])
            if d <= EPS:
                continue  # 同心：同半径圆重合，边界被自身覆盖语义跳过
            # ‖c_i + r·u − c_j‖² = r² + d² − 2 r d cos(φ−φ_j) ≤ r²
            #   ⟺ cos(φ−φ_j) ≥ d / (2r)
            c_ratio = d / (2.0 * r)
            if c_ratio >= 1.0:
                continue                      # D_j 不覆盖 ∂D_i 上任何弧
            if c_ratio <= -1.0:
                cover = [(0.0, 2.0 * math.pi)]  # 整圆被覆盖（不可能但保险）
                break
            beta = math.acos(max(-1.0, min(1.0, c_ratio)))
            phi_j = math.atan2(cj[1] - ci[1], cj[0] - ci[0])
            cover.extend(_angle_intervals_mod(phi_j - beta, phi_j + beta))
        # 3. 未覆盖且在 Ω 内的弧段
        holes = _subtract_intervals(inside, cover)
        for lo, hi in holes:
            mid = 0.5 * (lo + hi)
            nx = math.cos(mid)
            ny = math.sin(mid)
            # 多尺度探针：狭缝/大空洞都能命中
            for probe in (HOLE_PROBE, 5.0, 25.0):
                q = (ci[0] + (r + probe) * nx, ci[1] + (r + probe) * ny)
                if math.hypot(q[0], q[1]) > R + COVER_TOL:
                    continue
                if all(math.hypot(q[0] - s[0], q[1] - s[1]) > r + COVER_TOL
                       for s in centers):
                    return q
    return None


def _find_uncovered_boundary_point(centers, R, r, n_samples=4096):
    """在 ∂Ω 上找一个未被覆盖的点（用于失败见证；确定性密集采样）。"""
    for k in range(n_samples):
        phi = 2.0 * math.pi * k / n_samples
        p = (R * math.cos(phi), R * math.sin(phi))
        if all(math.hypot(p[0] - S[0], p[1] - S[1]) > r + COVER_TOL
               for S in centers):
            return p
    return None


def q3_certified_grid_confirm(no_signal_points, omega_radius=OMEGA_RADIUS,
                              cover_r=R_EFF_MIN, grid_step=20.0):
    """可选的网格二次确认：对 Ω 做网格采样，返回最大"到最近圆心距离"。

    若该值 ≤ cover_r，采样意义上覆盖成立（仅作二次确认，不作主判定）。
    返回 (max_min_dist, worst_point)。
    """
    centers = [(float(p[0]), float(p[1])) for p in no_signal_points]
    R = float(omega_radius)
    worst = -1.0
    worst_p = None
    n = int(math.ceil(2.0 * R / grid_step)) + 1
    for i in range(n):
        for j in range(n):
            x = -R + i * grid_step
            y = -R + j * grid_step
            if math.hypot(x, y) > R:
                continue
            if centers:
                d = min(math.hypot(x - S[0], y - S[1]) for S in centers)
            else:
                d = float("inf")
            if d > worst:
                worst = d
                worst_p = (x, y)
    return worst, worst_p


def q3_backbone_points():
    """Q3 七点充分覆盖骨架：center (0,0) + 6 个等角外围点。

    外围半径 a = 900√3 ≈ 1558.846 m。
    保证 Ω 内任意点到最近检测点 ≤ 900 m（相对 1000 m 有 100 m 确定性余量）。
    """
    a = 900.0 * math.sqrt(3.0)
    pts = [(0.0, 0.0)]
    for k in range(6):
        ang = math.pi / 3.0 * k
        pts.append((a * math.cos(ang), a * math.sin(ang)))
    return pts


# ---------------------------------------------------------------------------
# Q4 δ-稳健凸包证书
# ---------------------------------------------------------------------------

def q4_certify_point(x, no_signal_points, delta=Q4_DELTA,
                     r_eff_min=R_EFF_MIN):
    """判定 B(x, δ) ⊆ conv(A_δ(x))，A_δ(x) = {p : ‖p−x‖ ≤ r_eff_min − δ}。

    精确充要条件（conv 为凸集）：
      1. |A_δ| ≥ 3 且凸包二维（面积 > 0）；
      2. x 在凸包内；
      3. 凸包每条边所在直线到 x 的距离 ≥ δ。
      （2+3 ⟺ B(x,δ) ⊆ conv(A_δ)：每个方向 u 上 x·u+δ ≤ max p·u
        恰好等价于 x 到每条支撑边距离 ≥ δ。）

    返回 dict:
        certified          : bool
        reason             : 说明
        witness_count      : 见证点数量
        min_edge_distance  : x 到凸包边的最小距离（未通过时可能为负/None）
        hull               : 凸包顶点（未形成二维凸包时为 None）
    """
    r_witness = r_eff_min - delta
    xx = (float(x[0]), float(x[1]))
    A = [(float(p[0]), float(p[1])) for p in no_signal_points
         if math.hypot(p[0] - xx[0], p[1] - xx[1]) <= r_witness + EPS]
    if len(A) < 3:
        return {"certified": False,
                "reason": "fewer than 3 witnesses within %.1f" % r_witness,
                "witness_count": len(A), "min_edge_distance": None,
                "hull": None}
    hull = convex_hull(A)
    if len(hull) < 3 or area(hull) <= EPS:
        return {"certified": False, "reason": "witness hull is degenerate",
                "witness_count": len(A), "min_edge_distance": None,
                "hull": hull if len(hull) >= 3 else None}
    dmin = edge_distance(hull, xx)
    if dmin < 0.0:
        return {"certified": False, "reason": "x outside witness hull",
                "witness_count": len(A), "min_edge_distance": dmin,
                "hull": hull}
    if dmin < delta - COVER_TOL:
        return {"certified": False,
                "reason": "inscribed radius %.3f < delta %.3f" % (dmin, delta),
                "witness_count": len(A), "min_edge_distance": dmin,
                "hull": hull}
    return {"certified": True,
            "reason": "B(x,delta) inscribed in conv(A_delta)",
            "witness_count": len(A), "min_edge_distance": dmin,
            "hull": hull}


def q4_grid_points(spacing=Q4_GRID_SPACING, radius=OMEGA_RADIUS,
                   delta=Q4_DELTA):
    """覆盖 Ω 的等边三角格点（含边界外扩环）。

    行距 h = s·√3/2 ≈ 536.94 m，奇数行横向偏移 s/2。
    三角格点覆盖半径为 s/√3 ≈ 357.75 m < δ = 370 m，
    确定性余量 ≈ 12.25 m，因此 ∪B(x_i, δ) ⊇ Ω。
    为使 Ω 边界带也被覆盖，格点生成范围外扩至 ‖p‖ ≤ radius + delta。
    点数约 40（与 narrative 第 7 节构造性上界一致）。
    """
    s = float(spacing)
    h = s * math.sqrt(3.0) / 2.0
    reach = radius + delta
    pts = []
    k = 0
    y = -reach
    # 对齐到行网格：从 -reach 起逐行
    y0 = -math.ceil(reach / h) * h
    y = y0
    k = int(round(-math.ceil(reach / h)))
    while y <= reach + EPS:
        offset = 0.0 if (k % 2 == 0) else s / 2.0
        m = int(math.ceil((-reach - offset) / s))
        x = offset + m * s
        while x <= reach + EPS:
            if math.hypot(x, y) <= reach + EPS:
                pts.append((x, y))
            x += s
        y += h
        k += 1
    return pts


def q4_channel_certified(certified_centers, omega_radius=OMEGA_RADIUS,
                         delta=Q4_DELTA):
    """频道完成判定：Ω ⊆ ∪_{certified x_i} B(x_i, δ)。

    直接复用 Q3 的精确圆盘覆盖判定（把 B(x_i, δ) 当作覆盖圆）。
    """
    return q3_certified(certified_centers, omega_radius=omega_radius,
                        cover_r=delta)


def q4_grid_coverage_margin(grid_points, radius=OMEGA_RADIUS,
                            n_samples=720, grid_step=30.0):
    """数值确认 ∪B(x_i, δ) 对 Ω 的覆盖余量。

    组合 ∂Ω 密集采样 + 内部网格采样，返回
    (max_min_dist, worst_point)：Ω 采样点到最近格点距离的最大值。
    该值 ≤ δ 即（采样意义下）覆盖成立；理论余量 δ − s/√3 ≈ 12.25 m。
    """
    pts = grid_points
    worst = -1.0
    worst_p = None

    def upd(p):
        nonlocal worst, worst_p
        d = min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in pts)
        if d > worst:
            worst = d
            worst_p = p

    for k in range(n_samples):
        phi = 2.0 * math.pi * k / n_samples
        upd((radius * math.cos(phi), radius * math.sin(phi)))
    n = int(math.ceil(2.0 * radius / grid_step)) + 1
    for i in range(n):
        for j in range(n):
            x = -radius + i * grid_step
            y = -radius + j * grid_step
            if math.hypot(x, y) <= radius:
                upd((x, y))
    return worst, worst_p


# ---------------------------------------------------------------------------
# Q4 三角格点 31 点扫描证书（评审第 3 点）
# ---------------------------------------------------------------------------

def q4_lattice_points(spacing=Q4_LATTICE_SPACING, bound=Q4_LATTICE_BOUND):
    """边长 s=950 m 的等边三角格点，保留距原点 ≤ bound=2750 m 的格点。

    恰好 31 个点（评审独立枚举确认；默认参数下生成器断言该数）。

    构造：行距 h = s·√3/2 ≈ 822.72 m，奇数行（k 为奇）横向错开 s/2；
    行 k ∈ {−3,…,3} 的点数分布为 2/5/6/5/6/5/2（上下对称），合计 31。

    证明梗概（为何该集合是 Q4 全频道充分扫描集）：
      1. 任意 G∈Ω 落在某个网格三角形内（格点外扩至 1800+950=2750，
         其凸包完整覆盖 Ω，边界余量 ≥ 100 m）；
      2. 该三角形三顶点距 G 均 ≤ 950 m
         （点到凸集内顶点距离 ≤ 最大边长，等边三角形边长即 950）；
      3. 三顶点距原点 ≤ 1800+950=2750，故都在扫描集内；
      4. 任何以 G 为边界点的闭半平面至少包含其中一个顶点
         （否则三角形凸包 conv(顶点) 不可能含 G）；
      5. 该顶点距 G ≤ 950 ≤ R_eff 且在覆盖半平面内 ⇒ 必返回
         direction 或 near（距离 0 时 near）。
      退化情形（G 恰在格点上或网格边上）由共线/邻接顶点补足同一论证。
    推论：某频道在全部 31 个点均 no_signal ⇒ 该频道不存在未清除源
    （不论全向/定向、不论朝向、不论 R_eff ≥ 1000）。
    """
    s = float(spacing)
    b = float(bound)
    h = s * math.sqrt(3.0) / 2.0
    pts = []
    k_max = int(math.floor(b / h)) + 1
    for k in range(-k_max, k_max + 1):
        y = k * h
        offset = (k % 2) * s / 2.0  # Python % 对负 k 仍给 0/1，保持镜像对称
        m0 = int(math.floor((-b - offset) / s)) - 1
        m1 = int(math.ceil((b - offset) / s)) + 1
        for m in range(m0, m1 + 1):
            x = offset + m * s
            if math.hypot(x, y) <= b + EPS:
                pts.append((x, y))
    pts.sort(key=lambda p: (p[1], p[0]))
    if s == Q4_LATTICE_SPACING and b == Q4_LATTICE_BOUND:
        assert len(pts) == Q4_LATTICE_COUNT, \
            "lattice enumeration gave %d, expected %d" % (len(pts),
                                                          Q4_LATTICE_COUNT)
    return pts


def q4_channel_certified_lattice(no_signal_points,
                                 spacing=Q4_LATTICE_SPACING,
                                 bound=Q4_LATTICE_BOUND):
    """频道级判定：31 点全集 ⊆ no_signal 点集 ⇒ True（频道无未清除源）。

    no_signal_points 为该频道全部 no_signal 检测点 list[(x, y)]；
    匹配容差 LATTICE_MATCH_TOL（实测点应恰为格点，容差仅吸收浮点噪声）。
    """
    lattice = q4_lattice_points(spacing, bound)
    ns = [(float(p[0]), float(p[1])) for p in no_signal_points]
    for q in lattice:
        if not any(math.hypot(p[0] - q[0], p[1] - q[1]) <= LATTICE_MATCH_TOL
                   for p in ns):
            return False
    return True
