# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\practice_single_source.py (22 行)
# 改动：① 删除 ROOT=Path(...).parents[1] 与 sys.path.insert(...)（源 5-6 行）；
#       ② 删除离线桩 class PracticeClient（源 12-14 行，只 raise RuntimeError）与常量 URL（源 10 行）；
#       ③ 2 处顶层 import 改为显式包内相对 import（geometry -> geometry_src）。
# 理由：PracticeClient 是不接真实 socket 的离线桩，绝不能进入本包进程；URL/ROOT 只被各模块 main()
#       使用，而 main() 因构造该桩已一并删除。ERROR=1.005（q3_optimizer_v4 使用）与
#       search_points()（practice_all_sources.coverage_sites 使用）保留。import math / numpy 在源
#       文件中即未被使用，为「除 import 行外逐行一致」而未删。详见 MANIFEST.md。
"""Offline geometry compatibility exports; simulator client is disabled."""
import math
import numpy as np
from .geometry_src import bearing_halfplanes,clip_polygon,minimum_circle
from .second_point import outer_prior,plan_second_point,to_global
ERROR=1.005

def search_points():
    # Four 1200m-wide cells per axis cover [-2400,2400]^2; max nearest distance 600sqrt2<1000.
    points=[(0.,0.)]
    for i,y in enumerate((-1800.,-600.,600.,1800.)):
        xs=(-1800.,-600.,600.,1800.) if i%2==0 else (1800.,600.,-600.,-1800.)
        points.extend((x,y) for x in xs)
    return points
