# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\legacy_second_point.py (87 行)
# 唯一改动：源第 4 行 "from geometry import ..." -> "from .geometry_src import ..."（1 处，
# 显式包内相对 import，避免与目标包顶层 geometry 同名）。算法逐行未改。详见 MANIFEST.md。
"""Distribution-free second-point planning in local first-bearing coordinates."""
import math
import numpy as np
from .geometry_src import bearing_halfplanes, clip_polygon, diameter_bruteforce, minimum_circle

def initial_outer_triangle(error_deg=1.,max_range=1500.):
    h=max_range*math.tan(math.radians(error_deg))
    return np.array([[0.,0.],[max_range,-h],[max_range,h]])

def height_limit(u,error_deg=1.,max_range=1500.,min_range=1000.):
    if abs(u)>min_range or abs(u-max_range)>min_range:return -1.
    h=max_range*math.tan(math.radians(error_deg))
    return min(math.sqrt(max(0,min_range**2-u**2)),
               math.sqrt(max(0,min_range**2-(u-max_range)**2))-h)

def reception_radius_needed(point,poly):
    return float(np.max(np.linalg.norm(np.asarray(poly)-point,axis=1)))

def certify_point(point,error_deg=1.,bin_width_deg=1.,poly=None):
    """Upper bound for EVERY second bearing, not merely a sample maximum.

    Each beta bin of width w is enclosed by a wedge at its midpoint with
    half-angle error+w/2. Clipping the prior polygon by that wider wedge contains
    all possible posterior sets in the bin. Polygon diameter then upper-bounds
    their diameters. True error distribution is never used.
    """
    if not 0<bin_width_deg<=10:raise ValueError('bin_width_deg must be in (0,10]')
    point=np.asarray(point,dtype=float)
    if point.shape!=(2,) or not np.all(np.isfinite(point)):raise ValueError('Invalid point')
    poly=initial_outer_triangle(error_deg) if poly is None else np.asarray(poly)
    required=reception_radius_needed(point,poly)
    center=np.mean(poly,axis=0)
    ref=math.degrees(math.atan2(*(center-point)[::-1]))
    ang=np.rad2deg(np.arctan2(poly[:,1]-point[1],poly[:,0]-point[0]))
    rel=(ang-ref+180)%360-180
    # If point inside/on prior, use full circle (safe also for degeneracy).
    edges=np.roll(poly,-1,axis=0)-poly
    inside=np.all(edges[:,0]*(point[1]-poly[:,1])-edges[:,1]*(point[0]-poly[:,0])>=-1e-8)
    if inside or np.ptp(rel)>=180:
        lo,hi=ref-180,ref+180
    else:lo,hi=ref+float(min(rel))-error_deg,ref+float(max(rel))+error_deg
    count=max(1,math.ceil((hi-lo)/bin_width_deg));width=(hi-lo)/count
    best_upper=0.;best_lower=0.;worst=None;witness=None
    # Lower is a witness for the outer-triangle relaxed problem, not necessarily actual sector.
    for beta in lo+(np.arange(count)+.5)*width:
        A,b=bearing_halfplanes(point,beta,error_deg+width/2)
        enlarged=clip_polygon(poly,A,b)
        if not len(enlarged):continue
        du,_=diameter_bruteforce(enlarged)
        if du>best_upper:best_upper=du;worst=(beta,enlarged)
        A,b=bearing_halfplanes(point,beta,error_deg)
        exact=clip_polygon(poly,A,b)
        if len(exact):
            dl,pair=diameter_bruteforce(exact)
            if dl>best_lower:
                best_lower=dl
                witness={'second_bearing_deg':float(beta),'source_pair':exact[list(pair)].tolist()}
    return {'point':point.tolist(),'reception_radius_needed_m':required,
            'guaranteed_reception':required<=1000+1e-8,
            'diameter_upper_m':best_upper,'relaxed_diameter_lower_m':best_lower,
            'radius_upper_via_jung_m':best_upper/math.sqrt(3),
            'move_m':float(np.linalg.norm(point)),'move_time_s':float(np.linalg.norm(point)/5),
            'angle_bins':count,'bin_width_deg':width,
            'relaxed_lower_witness':witness,
            'worst_bin_center_deg':None if worst is None else float(worst[0])}

def plan_second_point(error_deg=1.,bin_width_deg=1.):
    """Finite candidate search. No claim of continuous global optimality."""
    candidates=[]
    for u in np.arange(500,1000.01,25.):
        hm=height_limit(u,error_deg)
        if hm<=0:continue
        for f in [.25,.5,.75,.9,1.]:
            candidates.append(certify_point([u,f*hm],error_deg,bin_width_deg))
    feasible=[r for r in candidates if r['guaranteed_reception']]
    best=min(feasible,key=lambda r:(r['diameter_upper_m'],r['move_m']))
    return best,candidates

def to_global(point,first_position,bearing_deg):
    a=math.radians(bearing_deg);R=np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])
    return np.asarray(first_position)+R@point

def update_after_direction(point,beta_deg,error_deg=1.,poly=None):
    poly=initial_outer_triangle(error_deg) if poly is None else poly
    A,b=bearing_halfplanes(point,beta_deg,error_deg);p=clip_polygon(poly,A,b)
    return {'vertices':p,'diameter':diameter_bruteforce(p)[0],
            'circle':minimum_circle(p) if len(p) else None}
