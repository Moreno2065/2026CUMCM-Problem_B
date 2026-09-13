# -*- coding: utf-8 -*-
"""测向楔形 W(S, θ̂, ±1°) 与可行域求交。

楔形定义：从检测点 S 出发，真实方位角 θ 落在 [θ̂-1°, θ̂+1°]（闭区间，
含边界）内的所有点，再交 B(S, 1500)（有效接收半径上界）。

角度约定：度，正东 0°，逆时针为正，范围 [0, 360)。

实现要点：
- 楔形表示为两个闭半平面之交，天然处理 bearing 跨越 0°/360° 的 wrap
  （不直接做角度区间比较，而是用方向向量的叉积判断）。
- 由于楔形张角固定为 2°（< 180°），两个半平面即可精确界定，
  不存在"近平行射线"导致的歧义分支。
- 交集为空返回 None，调用方必须显式报告。
"""

import math

from .constants import (
    BEARING_ERROR_DEG,
    EPS,
    R_EFF_MAX,
    DISK_POLYGON_SIDES,
)
from .polygon import clip_halfplane, clip_circle


def _dir_vec(deg):
    rad = math.radians(deg % 360.0)
    return (math.cos(rad), math.sin(rad))


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def in_wedge(S, theta_hat_deg, p, tol_deg=BEARING_ERROR_DEG, eps=EPS):
    """判断点 p 是否在闭楔形 W(S, θ̂, ±tol) 内（含 S 本身）。

    p 相对 S 的方位角须落在 [θ̂-tol, θ̂+tol] 的 CCW 区间内。
    用叉积表达，自动处理 0°/360° wrap。
    """
    vx, vy = p[0] - S[0], p[1] - S[1]
    if math.hypot(vx, vy) <= eps:
        return True  # 楔形顶点 S 属于楔形
    d_lo = _dir_vec(theta_hat_deg - tol_deg)   # 下边界方向
    d_hi = _dir_vec(theta_hat_deg + tol_deg)   # 上边界方向
    v = (vx, vy)
    # v 在 d_lo 的 CCW 侧：cross(d_lo, v) >= 0
    # v 在 d_hi 的 CW 侧： cross(v, d_hi) >= 0
    return _cross2(d_lo, v) >= -eps and _cross2(v, d_hi) >= -eps


def wedge_intersect(poly, S, theta_hat_deg, tol_deg=BEARING_ERROR_DEG,
                    n_circle=DISK_POLYGON_SIDES):
    """计算 P ∩ W(S, θ̂, ±tol) ∩ B(S, 1500)。

    返回新的凸多边形顶点 list；交集为空返回 None。

    实现：楔形 = 两个闭半平面之交。
    - 下边界射线方向 d_lo = dir(θ̂ - tol)：保留 cross(d_lo, x-S) >= 0
      即法向 n_lo = 左旋 d_lo 90° 的外法向…… 直接用法向形式：
      cross(d, v) = d.x*v.y - d.y*v.x = (-d.y, d.x)·v，
      所以 cross(d_lo, x-S) >= 0 ⟺ (-d_lo.y, d_lo.x)·(x-S) >= 0。
    - 上边界：cross(x-S, d_hi) >= 0 ⟺ (d_hi.y, -d_hi.x)·(x-S) >= 0。
    """
    if poly is None:
        return None
    d_lo = _dir_vec(theta_hat_deg - tol_deg)
    d_hi = _dir_vec(theta_hat_deg + tol_deg)
    out = clip_halfplane(poly, S, (-d_lo[1], d_lo[0]), keep_negative=False)
    if out is None:
        return None
    out = clip_halfplane(out, S, (d_hi[1], -d_hi[0]), keep_negative=False)
    if out is None:
        return None
    # 有效接收半径上界约束：源距 S <= 1500（外切多边形近似，保守超集）
    out = clip_circle(out, S, R_EFF_MAX, n_circle)
    return out


def bearing_of(S, p):
    """p 相对 S 的方位角（度，[0,360)，正东 0°，CCW 为正）。"""
    return math.degrees(math.atan2(p[1] - S[1], p[0] - S[0])) % 360.0


def bearing_range(poly, S, eps=EPS):
    """从 S 看凸多边形 P 的方位角范围（CCW 区间 [lo, hi]，度）。

    - 若 S 在 P 内（或边界上距某顶点 <= eps），返回 (0.0, 360.0) 表示全圆。
    - 否则取所有顶点方位角的最小覆盖弧，返回 (lo, hi)，
      满足从 lo 逆时针转到 hi 覆盖全部顶点，且 hi-lo <= 360。
    """
    from .polygon import contains_point

    if contains_point(poly, S, eps=-eps):
        return (0.0, 360.0)
    angs = []
    for v in poly:
        if math.hypot(v[0] - S[0], v[1] - S[1]) <= eps:
            return (0.0, 360.0)
        angs.append(bearing_of(S, v))
    angs.sort()
    # 最小覆盖弧 = 全圆减去最大空隙
    max_gap = -1.0
    gap_start = 0.0
    m = len(angs)
    for i in range(m):
        a1 = angs[i]
        a2 = angs[(i + 1) % m] + (360.0 if i == m - 1 else 0.0)
        gap = a2 - a1
        if gap > max_gap:
            max_gap = gap
            gap_start = a2
    lo = gap_start
    hi = gap_start + (360.0 - max_gap)
    return (lo, hi)
