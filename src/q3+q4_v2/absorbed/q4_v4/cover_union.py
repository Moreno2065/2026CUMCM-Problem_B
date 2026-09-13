"""Finite continuous certificate using all triangles and inward reception disks.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\cover_union.py 的差异，仅 import 相关）：
- 源第 76-77 行位于 `if __name__=='__main__':` 分支内（`from bridge_v4 import WORK,reference`、
  `from geometry_hand_layouts import layout`）→ 本版改为包内相对 import
  （`from .bridge_v4 import WORK,reference` / `from .geometry_hand_layouts import layout`）。
  该分支只在直接执行本文件时运行，不进入 solve() 闭包。
- 第三方依赖保留：scipy.spatial(ConvexHull,QhullError)、shapely.geometry(Polygon,Point,
  MultiPoint)、shapely.ops.unary_union、shapely.errors(GEOSException)。
- 其余（exact_margin/certificate 全部函数体、默认参数 disk_sides=256/target_sides=2048/
  keep_regions=False/receiver_radius=1000-1e-4/target_expansion=1e-4、数值常数
  1800/2000/1e-5/1e-6/1e-7/20_000_000.、异常分支与返回字典全部键与 reason 文本）
  与源逐行一致。
"""
from itertools import combinations
import math,time
import numpy as np
from scipy.spatial import ConvexHull,QhullError
from shapely.geometry import Polygon,Point,MultiPoint
from shapely.ops import unary_union
from shapely.errors import GEOSException

def exact_margin(x,stations,radius=1000):
    p=np.asarray(stations);q=p[np.linalg.norm(p-x,axis=1)<=radius]
    if len(q)==0:return -math.inf
    if np.min(np.linalg.norm(q-x,axis=1))<1e-9:return 0.
    if len(q)<3:return -math.inf
    try:h=ConvexHull(q)
    except QhullError:return -math.inf
    return float(np.min(-(h.equations[:,:2]@x+h.equations[:,2])))

def certificate(stations,disk_sides=256,target_sides=2048,keep_regions=False,receiver_radius=1000-1e-4,target_expansion=1e-4):
    started=time.perf_counter();p=np.asarray(stations);disks=[Point(x).buffer(receiver_radius,quad_segs=disk_sides//4) for x in p]
    regions=[];witnesses=[];pairs=np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2)
    for ids in combinations(range(len(p)),3):
        if max(pairs[a,b] for a,b in combinations(ids,2))>=2000-2e-4:continue
        triangle=Polygon(p[list(ids)])
        if triangle.area<1e-9:continue
        region=triangle
        for j in ids:
            # Every exact intermediate region is convex. Rebuilding its hull
            # removes duplicate floating vertices that can break GEOS union.
            region=region.intersection(disks[j]).convex_hull
        if region.is_empty or region.area<1e-9:continue
        regions.append(region)
        if keep_regions:witnesses.append({'station_indices':list(ids),'vertices':list(region.exterior.coords)})
    try:union=unary_union(regions)
    except GEOSException as exc:
        # Numerical failure is a rejection. Never repair a polygon outwards or
        # accept an unverified region just to keep a candidate evaluation alive.
        return {'passed':False,'reason':'numeric_union_failure','error':str(exc),'missing_area_m2':None,
                'runtime_s':time.perf_counter()-started,'optimizer_penalty':20_000_000.}
    a=2*math.pi*np.arange(target_sides)/target_sides;R=(1800+target_expansion)/math.cos(math.pi/target_sides)
    target=Polygon(np.column_stack((R*np.cos(a),R*np.sin(a))));missing=target.difference(union)
    covered=missing.is_empty;patch_certificates=[]
    # Certify finite residual polygons geometrically; never dismiss them merely
    # because their area is small (GEOS may leave microscopic seam polygons).
    if not covered:
        residuals=list(missing.geoms) if hasattr(missing,'geoms') else [missing]
        for geom in residuals:
            xmin,ymin,xmax,ymax=geom.bounds;centre=np.array([(xmin+xmax)/2,(ymin+ymax)/2]);rad=math.hypot(xmax-xmin,ymax-ymin)/2
            upper=np.linalg.norm(p-centre,axis=1)+rad;ids=np.flatnonzero(upper<=receiver_radius-1e-5)
            if len(ids)<3:break
            try:h=ConvexHull(p[ids]);margin=float(np.min(-(h.equations[:,:2]@centre+h.equations[:,2])))
            except QhullError:break
            if margin<rad+1e-6:break
            patch_certificates.append({'bounds':[xmin,ymin,xmax,ymax],'centre':centre.tolist(),'circumradius_m':rad,
                'station_indices':ids.tolist(),'maximum_range_upper_m':float(upper[ids].max()),'hull_margin_m':margin})
        covered=len(patch_certificates)==len(residuals)
    result={'passed':covered,'method':'all-triangle union of inward disk intersections','disk_sides':disk_sides,'target_sides':target_sides,
        'target_outer_radius_m':R,'receiver_polygon_circumradius_m':receiver_radius,'region_count':len(regions),'missing_area_m2':missing.area,
        'certified_remainder_patches':patch_certificates,'runtime_s':time.perf_counter()-started}
    if not covered:
        parts=list(missing.geoms) if hasattr(missing,'geoms') else [missing];points=[]
        for geom in sorted(parts,key=lambda g:g.area,reverse=True)[:20]:
            points.append(np.array(geom.representative_point().coords[0]))
            if hasattr(geom,'exterior'):points.extend(np.asarray(geom.exterior.coords)[::max(1,len(geom.exterior.coords)//12)])
        examples=[(exact_margin(x,p),x) for x in points if np.linalg.norm(x)<=1800]
        if examples:
            margin,x=min(examples,key=lambda pair:pair[0]);result.update(worst_checked_margin_m=margin,checked_position=x.tolist())
            if margin<-1e-7:result['reason']='actual_counterexample'
            else:result['reason']='inward_approximation_inconclusive'
        else:result['reason']='only_outer_target_sliver_checked'
    else:result['reason']='continuous_certificate'
    if keep_regions:result['regions']=witnesses
    return result

if __name__=='__main__':
    from .bridge_v4 import WORK,reference
    from .geometry_hand_layouts import layout
    trials=[(8,12,950,1865,0),(8,12,990,1865,0),(8,12,970,1875,0),(8,12,950,1900,0),(8,12,990,1900,0),
        (9,12,950,1865,0),(9,12,990,1865,0),(8,13,950,1860,0),(8,13,990,1870,0),
        (8,14,950,1850,0),(8,14,990,1850,0),(8,15,990,1841,0)]
    rows=[]
    for params in trials:
        p=layout(*params);r=certificate(p,keep_regions=True);rows.append({'parameters':params,'stations':p.tolist(),'certificate':r})
        print(params,{k:v for k,v in r.items() if k!='regions'},flush=True)
        reference.write_json(WORK/'geometry/union_layout_trials.json',rows)
