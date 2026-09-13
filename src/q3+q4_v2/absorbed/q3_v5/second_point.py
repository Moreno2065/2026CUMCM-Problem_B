# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\second_point.py (11 行)
# 唯一改动：2 处顶层 import 改为显式包内相对 import（q2_adopted / legacy_second_point）。
# 该文件本身是纯再导出 shim，逐行未改。详见 MANIFEST.md。
"""Current Q2 route is the user-accepted conditional reception / tangency method.
Legacy helpers remain available solely to reproduce the v1 comparison.
"""
from .q2_adopted import (
    VERSION, candidate_region, reception_residuals, tangency_candidate,
    executable_point, outer_prior, direct_pair_witness, certify_plan,
    plan_second_point, to_global, update_after_direction,
)
from .legacy_second_point import (
    initial_outer_triangle, height_limit, reception_radius_needed, certify_point,
)
