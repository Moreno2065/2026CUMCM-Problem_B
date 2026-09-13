# -*- coding: utf-8 -*-
"""absorbed/ —— 从 Q3_Q4_V3 吸收进来的 SOTA solver 引擎。

本目录是**自包含**的：吸收后的代码不再依赖 D:\\CUMCM2026\\src\\Q3_Q4_V3。

子包：
- q3_v5/  Q3 正式 solver（q3_optimizer_v5.solve_optimized_v5）
- q4_v4/  Q4 正式 solver（strategy_v4.solve + locked.solve_locked）
- adapters/ v2 运行栈适配层

用法（在 D:\\CUMCM2026\\src\\q3+q4_v2 下）：
    python -X utf8 absorbed/run_absorbed.py --help

    python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http-synthetic --seed 101 --n-sources 10 --scenario random --output-dir runs/absorbed_q3_smoke

    python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim http-synthetic --seed 101 --n-sources 10 --scenario mixed --output-dir runs/absorbed_q4_smoke

引擎版本索引（真值以引擎文件自身为准）：
- absorbed/q3_v5/q3_optimizer_v5.py  VERSION="q3_joint_search_clear_route_v5"，入口 solve_optimized_v5(client, progress=None)
- absorbed/q4_v4/locked.py           VERSION="q4_21station_exact_route_v4"，SELECTED_NAME="quarter12"，入口 solve_locked(client)

导入期约定（硬约束）：本包及子模块在 import 期不做任何网络/socket 操作，也不修改
sys.path；v2 运行栈的导入与路径准备都在函数调用内部完成
（absorbed.adapters.runtime_bridge.ensure_v2_import_path），因此 --help 与离线
路径不受任何网络/绑定状态影响。

注意：本文件必须存在（非空包标记）。若 absorbed/ 缺少 __init__.py，
Python 会把它当 namespace package，一旦全机其它位置也存在名为 absorbed 的
目录，两个 namespace 会**静默合并**，导致解析到非本包的模块。
"""
