"""Sound exclusion of continuously illuminated regions after negative replies.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_local_optimization_v2_20260912\\negative_regions.py 的差异，仅 import 相关）：
- 源第 6 行 `from base import clip_polygon` → 本版 `from .local_geometry import clip_polygon`。
- 源第 7 行 `from local_geometry import hull` → 本版 `from .local_geometry import hull`。
  （源靠 base.py 注入 V1 目录 + wildcard 传递；本版显式指向本包内 local_geometry）
- 其余（halfplanes/triangle_region/certified_regions/subtract/refine 全部函数体、
  lru_cache 容量 8192/2048、mode 默认 'short'、异常文本 'Negative-region union removed
  all feasible positions' / 'Negative-region difference complexity guard'、返回字典键）
  与源逐行一致。
"""
from functools import lru_cache
import math
import numpy as np
from scipy.spatial import Delaunay,QhullError
from .local_geometry import clip_polygon
from .local_geometry import hull

def halfplanes(poly):
    p=np.asarray(poly);e=np.roll(p,-1,axis=0)-p;A=np.column_stack((e[:,1],-e[:,0]));A=A/np.maximum(np.linalg.norm(A,axis=1)[:,None],1e-12)
    return A,np.sum(A*p,axis=1)

@lru_cache(maxsize=8192)
def triangle_region(key,mode):
    p=hull(key)
    if len(p)!=3:return None
    edge=max(math.dist(a,b) for a in p for b in p)
    if mode=='short':
        if edge>1000-1e-5:return None
        region=p
    else:
        if edge>2000-1e-4:return None
        region=p
        # A regular inscribed polygon is a subset of the 1000m reception disk.
        m=48;angles=(np.arange(m)+.5)*2*math.pi/m;A=np.column_stack((np.cos(angles),np.sin(angles)))
        apothem=(1000-1e-4)*math.cos(math.pi/m)
        for centre in p:
            region=clip_polygon(region,A,A@centre+apothem)
            if len(region)<3:return None
        region=hull(region)
    if len(region)<3:return None
    A,b=halfplanes(region)
    return {'triangle':p,'region':region,'A':A,'b':b,'lower':region.min(axis=0),'upper':region.max(axis=0),'edge_max':edge}

@lru_cache(maxsize=2048)
def certified_regions(key,mode):
    p=np.array(key)
    if len(p)<3:return []
    try:tri=Delaunay(p).simplices
    except QhullError:return []
    result=[]
    for t in tri:
        r=triangle_region(tuple(sorted(tuple(map(float,v)) for v in p[t])),mode)
        if r is not None:result.append(r)
    return result

def subtract(poly,region):
    """Exact polygon difference as convex pieces, excluding a shrunken interior."""
    remaining=np.asarray(poly);pieces=[];A=region['A'];b=region['b']-1e-5
    for normal,rhs in zip(A,b):
        if not len(remaining):break
        outside=clip_polygon(remaining,[-normal],[-rhs])
        if len(outside):pieces.append(outside)
        remaining=clip_polygon(remaining,[normal],[rhs])
    return pieces

def refine(poly,negative_points,mode='short',details=False):
    key=tuple(sorted(set(tuple(map(float,p)) for p in negative_points)))
    regions=certified_regions(key,mode);pieces=[np.asarray(poly)];used=[]
    lower=np.min(poly,axis=0);upper=np.max(poly,axis=0)
    for region in regions:
        if np.any(region['upper']<lower-1e-6) or np.any(region['lower']>upper+1e-6):continue
        updated=[]
        for p in pieces:
            if np.any(region['upper']<p.min(axis=0)-1e-6) or np.any(region['lower']>p.max(axis=0)+1e-6):updated.append(p);continue
            updated.extend(subtract(p,region))
        pieces=updated;used.append(region)
        if not pieces:raise RuntimeError('Negative-region union removed all feasible positions')
        if len(pieces)>500:raise RuntimeError('Negative-region difference complexity guard')
    result=hull(np.vstack(pieces))
    meta={'mode':mode,'negative_points':[list(p) for p in key],'certified_region_count':len(regions),'applied_region_count':len(used),'remaining_piece_count':len(pieces)}
    if details:meta['certified_regions']=[{'triangle':r['triangle'].tolist(),'region':r['region'].tolist(),'maximum_triangle_edge_m':r['edge_max']} for r in used]
    return result,meta
