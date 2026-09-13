# -*- coding: utf-8 -*-
"""全局数值容差与题设冻结常数。

所有几何模块统一从这里取容差，禁止在算法内部散落魔数。
"""

# ---- 数值容差 ----
EPS = 1e-9            # 通用浮点容差（米）
EPS_ANGLE = 1e-9      # 角度容差（度）
EPS_AREA = 1e-9       # 面积容差（平方米）
MEC_ACCEPT_EPS = 1e-6 # MEC 验收容差：所有顶点 d <= R + MEC_ACCEPT_EPS（米）

# ---- 题设冻结常数（禁止修改）----
OMEGA_RADIUS = 1800.0        # 目标区域 Ω 半径（米），圆心原点
BEARING_ERROR_DEG = 1.0      # 测向误差界 ±1°（有界误差）
R_EFF_MIN = 1000.0           # 有效接收半径下界（米）
R_EFF_MAX = 1500.0           # 有效接收半径上界（米）
NEAR_THRESHOLD = 5.0         # near 阈值（米）
CLEAR_RADIUS = 20.0          # 清除半径（米）
MOVE_SPEED = 5.0             # 移动速度（米/秒）
MEASURE_TIME = 5.0           # 检测耗时（秒）
SWITCH_TIME = 1.0            # 换频道耗时（秒，仅频道变化时）
CLEAR_FAIL_TIME = 3.0        # clear 未发现耗时（秒）
CLEAR_SUCCESS_TIME = 5.0     # clear 成功耗时（秒）
NUM_CHANNELS = 20            # 频道数 1..20
MAX_SOURCES = 16             # 源总数上界（早停条件）

# ---- Q4 δ-稳健凸包证书参数（narrative 第 7 节冻结）----
Q4_GRID_SPACING = 620.0      # 三角格点间距 s（米）
Q4_DELTA = 370.0             # δ（米），B(x,δ) ⊆ conv(A_δ(x))

# ---- Q4 三角格点 31 点扫描证书参数（评审第 3 点）----
Q4_LATTICE_SPACING = 950.0   # 等边三角格点边长 s（米）= 清除保证距离上界
Q4_LATTICE_BOUND = OMEGA_RADIUS + Q4_LATTICE_SPACING  # 2750 m 格点保留界
Q4_LATTICE_COUNT = 31        # 评审独立枚举的格点数（生成器断言用）
LATTICE_MATCH_TOL = 1e-6     # 实测点与格点匹配的容差（米）

# ---- 清除区 Z_c = ∩ B(v, 20)（评审第 5 点）----
CLEAR_ZONE_EPS = 1e-6        # Z_c 可行性/投影验收容差（米）

# ---- 工程取舍：圆盘外切正多边形近似边数 ----
# 外切多边形包含真实圆盘 => 可行域为真实可行域超集 => 清除保证保守安全。
# 128 边时顶点超出圆半径的相对量 1/cos(π/128)-1 ≈ 3.0e-4，
# 对 1500 m 圆盘约 0.45 m，远小于 20 m 清除判据，可接受。
DISK_POLYGON_SIDES = 128
