# absorbed/q3_v5 — Q3 正式 SOTA solver 的自包含移植
# 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\q3_optimizer_v5.py（及递归 import 闭包，见 MANIFEST.md）
# 本包不做任何全局副作用：不改 sys.path、不修改 socket/urllib、不设 sys.dont_write_bytecode、不读文件。
"""Q3 正式采用 solver 的自包含引擎（VERSION='q3_joint_search_clear_route_v5'）。

用法：
    from absorbed.q3_v5 import solve_optimized_v5
    result = solve_optimized_v5(client, progress=print)

client 契约（与源 solver 一致，未改）：
    client.act('/measure', pos, channel) -> {'measure_result': 'direction'|'near'|'no_signal', 'svd_deg': float}
    client.act('/clear',   point, channel) -> {'clear_result': 'success'|'no_target_in_range'|...}
    client.position -> (x, y)   client.virtual -> 虚拟秒   client.rows -> 动作流水   client.channel -> 当前频道

包内所有 import 均为显式包内相对 import，因此不会与目标包运行时 sys.path 上的顶层模块
（geometry 包、policy、state、executor、experiment、coverage、base、candidate）发生同名静默解析。
vendored 文件清单、逐处 import 改写与删除说明见同目录 MANIFEST.md。
"""
from .q3_optimizer_v5 import VERSION, SELECTED_PARAMETERS, solve, solve_optimized_v5

__all__ = ['VERSION', 'SELECTED_PARAMETERS', 'solve', 'solve_optimized_v5']
