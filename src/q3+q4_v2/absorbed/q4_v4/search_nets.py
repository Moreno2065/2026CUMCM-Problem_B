"""Certified station layouts, isolated from any case truths or outcomes.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\search_nets.py 的差异，仅 import 相关）：
- 源第 4-5 行 `from geometry_hand_layouts import layout,grid_layout` /
  `from cover_union import certificate` → 本版加相对前缀（`from .geometry_hand_layouts` /
  `from .cover_union`），避免与目标包顶层模块撞名。
- 其余（lru_cache 容量 256、receiver_radius=999.、target_expansion=.02、
  `parameters[0]=='grid'` 分派、异常文本 'Uncertified directional search layout'、
  certificate 仅取 dict 键 passed、返回三元组顺序）与源逐行一致。
"""
from functools import lru_cache
from scipy.spatial import Delaunay
from .geometry_hand_layouts import layout,grid_layout
from .cover_union import certificate

@lru_cache(maxsize=256)
def certified_layout(parameters):
    sites=grid_layout(*parameters[1:]) if parameters[0]=='grid' else layout(*parameters)
    cert=certificate(sites,keep_regions=False)
    if not cert['passed']:raise RuntimeError('Uncertified directional search layout')
    return sites,Delaunay(sites).simplices.tolist(),cert

@lru_cache(maxsize=256)
def certify_points(key):return certificate(key,keep_regions=False,receiver_radius=999.,target_expansion=.02)
