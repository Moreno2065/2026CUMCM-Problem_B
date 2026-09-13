# -*- coding: utf-8 -*-
"""Q4 正式 SOTA solver 的自包含移植件（源: Q3_Q4_V3 v4 工作流）。

版本标识与锁定参数由 locked.py 提供；算法入口为 strategy_v4.solve。

所有模块间 import 一律使用显式包内相对 import（``from .bridge import *``），
因为本包根目录与 baseline\\code 在运行期会被插入 sys.path（run.py:29-32、
runtime.py:15-18），裸顶层 import 会与本包自带的 geometry/ 、coverage/ 等
顶层模块撞名并**静默**解析到错误模块。
"""
