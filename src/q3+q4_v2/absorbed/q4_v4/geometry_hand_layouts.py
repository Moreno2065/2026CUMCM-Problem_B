"""Continuous all-direction coverage checks, not sampled-scene performance.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\geometry_hand_layouts.py 的差异，仅 import 相关）：
- 源第 4 行 `from bridge_v4 import WORK,reference` → 本版**从模块顶层删除**，改在
  run() 内部用相对 import（`from .bridge_v4 import WORK,reference`）。两个原因：
  (i) WORK/reference 只被 run() 使用，run() 是实验脚手架、不在 solve() 路径上；
  (ii) 更重要的是**打断导入环**：本模块被 .search_nets 导入（v4 目标站网路径
  certified_layout 会走 .cover_union.certificate），而 bridge_v4 → .base →
  .local_geometry；若本模块在顶层再反向 import bridge_v4，则
  `import absorbed.q4_v4.geometry_hand_layouts` 作为**首个**被导入的模块时
  会得到半初始化的 bridge_v4 并 ImportError。放在函数内解析可彻底避免。
- 其余（layout/grid_layout 全部数值、run() 的 trials 元组与 print 格式、import time）
  与源逐行一致；run() 仍然可用（内部相对 import 在调用时解析）。
"""
import math,time
import numpy as np
from .coverage import directional_cover,triangle_certificate

def layout(inner_count,outer_count,inner_radius,outer_radius,offset=0):
    return np.array([[0.,0.]]+[[inner_radius*math.cos(2*math.pi*k/inner_count+offset),inner_radius*math.sin(2*math.pi*k/inner_count+offset)] for k in range(inner_count)]+
        [[outer_radius*math.cos(2*math.pi*k/outer_count),outer_radius*math.sin(2*math.pi*k/outer_count)] for k in range(outer_count)])

def grid_layout(spacing,axis_extent):
    points=[[0.,0.]]
    for i in range(-2,3):
        for j in range(-2,3):
            if i==0 and j==0 or abs(i)==2 and abs(j)==2:continue
            x=i*spacing;y=j*spacing
            if abs(i)==2 and j==0:x=math.copysign(axis_extent,i)
            if abs(j)==2 and i==0:y=math.copysign(axis_extent,j)
            points.append([x,y])
    return np.asarray(points)

def run():
    from .bridge_v4 import WORK,reference
    trials=[(8,12,950,1900,0),(8,12,990,1900,0),(8,12,950,1950,0),(8,12,990,1950,0),
        (8,11,950,1900,0),(8,11,990,1950,0),(8,10,950,1950,0),(8,10,990,2000,0),
        (7,12,950,1900,0),(7,12,990,1900,0),(9,12,950,1900,0),(8,13,950,1900,0)]
    rows=[]
    for params in trials:
        start=time.perf_counter();p=layout(*params);cert=directional_cover(p,max_depth=14,keep_cells=True)
        row={'parameters':list(params),'stations':p.tolist(),'site_count':len(p),'certificate':cert,'runtime_s':time.perf_counter()-start};rows.append(row)
        print(params,len(p),{k:v for k,v in cert.items() if k not in ('cells',)},flush=True)
        reference.write_json(WORK/'geometry/hand_layouts.json',rows)

if __name__=='__main__':run()
