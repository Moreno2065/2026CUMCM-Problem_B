"""Continuous source-position/all-emission-direction search certificates.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_local_optimization_v2_20260912\\coverage.py 的差异，仅 import 相关）：
- 源：`import math` / `from functools import lru_cache` / `import numpy as np` /
  `from scipy.spatial import ConvexHull,Delaunay,QhullError`（第三方 scipy 依赖保留）。
- 本版无任何改写：该文件不含包内 import。其余与源逐行一致。
- 命名注意：本模块在本机**不得**以顶层名 `coverage` 被 import —— 本机装有 PyPI
  `coverage` 包，且 numba 导入期会把它装进 sys.modules（numba/misc/coverage_support.py
  在执行 `class NumbaTracer(coverage.types.Tracer)` 时触发）。本包一律用
  `from .coverage import ...`，故本模块身份是 absorbed.q4_v4.coverage，不遮蔽顶层 coverage。
"""
import math
from functools import lru_cache
import numpy as np
from scipy.spatial import ConvexHull,Delaunay,QhullError

def convex_radius(point,sites):
    """Signed distance to the nearest hull edge, positive inside the hull."""
    if len(sites)<3:return -math.inf
    try:h=ConvexHull(sites)
    except QhullError:return -math.inf
    return float(np.min(-(h.equations[:,:2]@point+h.equations[:,2])))

def triangle_certificate(sites,radius=999.8):
    p=np.asarray(sites);tri=Delaunay(p).simplices;h=ConvexHull(p)
    edges=np.vstack((tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]));length=np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1)
    max_edge=float(np.max(length));inradius=float(np.min(-h.equations[:,2]))
    return {'passed':max_edge<=radius and inradius>=1800.01,'max_edge_m':max_edge,'hull_inradius_m':inradius,'triangles':tri.tolist()}

def directional_cover(sites,minimum_radius=1000-1e-5,max_depth=16,keep_cells=False):
    """Sufficient continuous certificate; never interprets sampled success as proof.

    For each square, select stations within R of every square point. Require their
    convex hull to contain the square's circumscribed disk. Recursively subdivide
    when this sufficient test is inconclusive. Squares outside the source disk
    are skipped using their exact closest-point distance.
    """
    stations=np.unique(np.asarray(sites,dtype=float),axis=0)
    if len(stations)<3:return {'passed':False,'reason':'fewer_than_three_sites'}
    initial=triangle_certificate(stations,minimum_radius)
    if initial['passed']:return {'passed':True,'method':'triangles','triangle_certificate':initial,'cells':[],'checked_nodes':1}
    todo=[(0.,0.,1800.,0)];certified=[];checked=0
    while todo:
        x,y,h,depth=todo.pop();checked+=1
        if max(abs(x)-h,0)**2+max(abs(y)-h,0)**2>1800**2+1e-8:continue
        centre=np.array([x,y]);delta=h*math.sqrt(2);dist=np.linalg.norm(stations-centre,axis=1)
        near=stations[dist+delta<=minimum_radius]
        margin=convex_radius(centre,near)
        if margin>=delta+1e-8:
            if keep_cells:certified.append([x,y,h,len(near),margin])
            continue
        if x*x+y*y<=1800**2:
            local=stations[dist<=minimum_radius]
            if convex_radius(centre,local)<-1e-8 and float(dist.min())>1e-7:
                return {'passed':False,'reason':'counterexample_position','position':[x,y],'checked_nodes':checked,'nearest_hull_margin_m':convex_radius(centre,local)}
        if depth>=max_depth:return {'passed':False,'reason':'subdivision_budget','square':[x,y,h],'checked_nodes':checked}
        q=h/2
        todo.extend((x+sx*q,y+sy*q,q,depth+1) for sx,sy in ((-1,-1),(-1,1),(1,-1),(1,1)))
    return {'passed':True,'method':'square_hulls','checked_nodes':checked,'certified_cell_count':len(certified),'cells':certified,'minimum_reception_radius_m':minimum_radius}

@lru_cache(maxsize=1024)
def cached_cover(key):return directional_cover(np.array(key))

def coverage_passes(sites):return cached_cover(tuple(sorted(tuple(map(float,p)) for p in sites)))['passed']
