# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\q2_adopted.py (157 行)
# 唯一改动：源第 12 行 "from geometry import ..." -> "from .geometry_src import ..."（1 处）。
# 常量(L=1500./R=1000./NEAR=5./VERSION)、异常文本、返回字典键名逐行未改。详见 MANIFEST.md。
"""Accepted Q2 route: annular-sector reception disks and tangency candidate.

Mathematical route from the user-supplied package (SHA256 459c4ea1...02a0a1),
accepted by user on 2026-09-11 after independent comparison. Reimplemented here
with separately checked bearing witnesses, angular upper bounds and rounding.
No claim of a completed proof of global minimax optimality.
"""
import math
import heapq
import numpy as np
from scipy.optimize import brentq
from .geometry_src import bearing_halfplanes,clip_polygon,diameter_bruteforce,minimum_circle

VERSION='q2_conditional_reception_tangency_v2'
L=1500.;R=1000.;NEAR=5.

def validate_error(error_deg):
    if not math.isfinite(error_deg) or error_deg not in (1.,1.005):
        raise ValueError('This validated route supports error_deg=1 or 1.005')

def reception_residuals(point,error_deg=1.):
    """Distance minus radius for the two exact conditional reception disks."""
    validate_error(error_deg)
    p=np.asarray(point,dtype=float)
    if p.shape!=(2,) or not np.all(np.isfinite(p)):raise ValueError('Finite 2D point required')
    a,b=p[0],abs(p[1]);d=math.radians(error_deg)
    return [math.hypot(a-r*math.cos(d),b+r*math.sin(d))-R for r in (NEAR,R)]

def candidate_region(error_deg=1.):
    validate_error(error_deg);d=math.radians(error_deg)
    return {'coordinate_frame':'first bearing forward a, left b; reflect b for right',
            'centers_for_b_nonnegative':[[r*math.cos(d),-r*math.sin(d)] for r in (NEAR,R)],
            'radius_m':R,'inner_radius_limit_m':NEAR,'outer_radius_m':L,
            'inequalities':'(a-r*cos(delta))^2+(abs(b)+r*sin(delta))^2<=1000^2 for r in {5,1000}',
            'conditional_radius':'R_source >= max(1000, distance_from_first)',
            'prior':'5<r<=1500, abs(phi)<=delta; use closure for supremum'}

def tangency_candidate(error_deg=1.):
    validate_error(error_deg);d=math.radians(error_deg)
    c=np.array([NEAR*math.cos(d),-NEAR*math.sin(d)])
    def quantities(t):
        dist=math.sqrt(L*L+t*t-2*L*t*math.cos(2*d))
        center=np.array([(L+t)*math.sin(3*d),(L-t)*math.cos(3*d)])/(2*math.sin(2*d))
        radius=dist/(2*math.sin(2*d))
        return dist,center,radius
    def residual(t):
        _,center,radius=quantities(t)
        return float(np.linalg.norm(center-c)-R-radius)
    # The default physical branch is bracketed explicitly; report the bracket and residual.
    lo,hi=1300.,1490.
    if residual(lo)*residual(hi)>=0:raise RuntimeError('Validated tangency branch not bracketed')
    t=float(brentq(residual,lo,hi,xtol=1e-11,rtol=1e-14))
    dist,center,_=quantities(t)
    p=c+R*(center-c)/np.linalg.norm(center-c)
    if max(reception_residuals(p,error_deg))>1e-8:raise RuntimeError('Tangency point outside reception region')
    return {'T_m':t,'point':p.tolist(),'pair_distance_m':dist,'root_residual_m':residual(t),
            'root_bracket_m':[lo,hi]}

def executable_point(point,error_deg=1.):
    """Nearest feasible centimetre grid point around the analytic point; verify before use."""
    p=np.asarray(point);rounded=np.round(p,2);candidates=[]
    for dx in [-.01,0.,.01]:
        for dy in [-.01,0.,.01]:
            q=np.round(rounded+[dx,dy],2)
            if max(reception_residuals(q,error_deg))<=0:
                candidates.append(q)
    if not candidates:raise RuntimeError('No feasible nearby centimetre point')
    return min(candidates,key=lambda q:float(np.linalg.norm(q-p))).tolist()

def outer_prior(error_deg=1.,arc_step_deg=.05):
    """Convex outer polygon containing the true annular sector, including arc tangents."""
    validate_error(error_deg)
    if not 0<arc_step_deg<=.1:raise ValueError('arc_step_deg must be in (0,0.1]')
    d=math.radians(error_deg);h=L*math.tan(d)
    p=np.array([[0,0],[L,-h],[L,h]],dtype=float)
    phi=np.linspace(-d,d,math.ceil(2*error_deg/arc_step_deg)+1)
    A=np.column_stack((np.cos(phi),np.sin(phi)));b=np.full(len(phi),L)
    A=np.vstack((A,[-1,0]));b=np.r_[b,-NEAR*math.cos(d)]
    return clip_polygon(p,A,b)

def direct_pair_witness(point,error_deg=1.):
    """Root of the actual angle gap, independent of the tangency T formula."""
    validate_error(error_deg);q=np.array([point[0],abs(point[1])]);d=math.radians(error_deg)
    low=L*np.array([math.cos(d),-math.sin(d)])
    def upper(t):return t*np.array([math.cos(d),math.sin(d)])
    def f(t):
        u=low-q;v=upper(t)-q
        return math.atan2(abs(u[0]*v[1]-u[1]*v[0]),float(u@v))-2*d
    radii=np.linspace(1200,L,301)
    bracket=next(((a,b) for a,b in zip(radii[:-1],radii[1:]) if f(a)*f(b)<=0),None)
    if bracket is None:raise ValueError('Candidate outside validated far-pair branch')
    t=float(brentq(f,*bracket,xtol=1e-10));up=upper(t)
    gap_residual=math.degrees(f(t))
    if point[1]<0:low[1]*=-1;up[1]*=-1
    return {'first_bearing_deg':0.,'source_pair':[low.tolist(),up.tolist()],
            'T_m':t,'distance_m':float(np.linalg.norm(low-up)),
            'angle_gap_residual_deg':gap_residual}

def certify_plan(point,error_deg=1.,gap_m=.003,max_evaluations=10000):
    """Lower witness and complete angular interval upper bound for this candidate."""
    if not math.isfinite(gap_m) or gap_m<=0:raise ValueError('Positive finite gap required')
    p=outer_prior(error_deg);q=np.asarray(point,dtype=float);lower=direct_pair_witness(q,error_deg)
    ref=math.degrees(math.atan2(*(p.mean(axis=0)-q)[::-1]))
    angles=np.rad2deg(np.arctan2(p[:,1]-q[1],p[:,0]-q[0]));rel=(angles-ref+180)%360-180
    edges=np.roll(p,-1,axis=0)-p
    inside=np.all(edges[:,0]*(q[1]-p[:,1])-edges[:,1]*(q[0]-p[:,0])>=-1e-8)
    if inside or np.ptp(rel)>=180:lo,hi=ref-180,ref+180
    else:lo,hi=ref+min(rel)-error_deg,ref+max(rel)+error_deg
    heap=[];serial=0
    def add(a,b):
        nonlocal serial
        A,rhs=bearing_halfplanes(q,(a+b)/2,error_deg+(b-a)/2)
        post=clip_polygon(p,A,rhs);value=diameter_bruteforce(post)[0] if len(post) else 0.
        heapq.heappush(heap,(-value,serial,float(a),float(b)));serial+=1
    intervals=np.linspace(lo,hi,math.ceil((hi-lo)/2)+1)
    for a,b in zip(intervals[:-1],intervals[1:]):add(a,b)
    while -heap[0][0]>lower['distance_m']+gap_m and serial<max_evaluations:
        _,_,a,b=heapq.heappop(heap);mid=(a+b)/2;add(a,mid);add(mid,b)
    upper=-heap[0][0]
    if upper+1e-7<lower['distance_m']:raise RuntimeError('Upper bound contradicts feasible pair')
    return {'lower_m':lower['distance_m'],'upper_m':upper,'gap_m':upper-lower['distance_m'],
            'target_gap_m':gap_m,'target_gap_met':upper<=lower['distance_m']+gap_m,
            'evaluations':serial,'witness':lower,'prior_outer_vertices':len(p),
            'angle_range_deg':[float(lo),float(hi)],
            'angle_cover':[{'lo':a,'hi':b,'upper_m':-x} for x,_,a,b in sorted(heap,key=lambda x:x[2])],
            'interpretation':'Continuous-set mathematical upper bound evaluated in double precision'}

def to_global(point,first_position,bearing_deg):
    s=np.asarray(first_position,dtype=float)
    if s.shape!=(2,) or not np.all(np.isfinite(s)) or not math.isfinite(bearing_deg):raise ValueError('Invalid first observation')
    a=math.radians(bearing_deg);Rmat=np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])
    return s+Rmat@np.asarray(point)

def plan_second_point(error_deg=1.,first_position=(0.,0.),bearing_deg=0.,include_certificate=True):
    analytic=dict(tangency_candidate(error_deg));point=executable_point(analytic['point'],error_deg)
    # Separate theoretical point from centimetre-rounded executable positions.
    output={'version':VERSION,'error_deg':error_deg,'analytic':analytic,'practical_point':point,
            'first_position':list(first_position),'first_bearing_deg':bearing_deg,
            'candidate_global_points':[to_global([point[0],sgn*point[1]],first_position,bearing_deg).tolist() for sgn in [1,-1]],
            'reception_region':candidate_region(error_deg),'reception_distance_residuals_m':reception_residuals(point,error_deg),
            'guaranteed_reception':max(reception_residuals(point,error_deg))<=1e-8,
            'move_m':math.hypot(*point),'move_time_s':math.hypot(*point)/5,
            'same_channel_measurement_time_s':5.,'global_optimality_proof':'not_complete',
            'user_acceptance':'2026-09-11 对方更好那你直接按照对方的来'}
    if include_certificate:
        output['certificate']=certify_plan(point,error_deg)
        if not output['certificate']['target_gap_met']:raise RuntimeError('Selected-point verification incomplete')
    return output

def update_after_direction(point,beta_deg,error_deg=1.,poly=None):
    """Local-coordinate posterior outer polygon and enclosing circle; geometry only."""
    prior=outer_prior(error_deg) if poly is None else poly
    A,b=bearing_halfplanes(point,beta_deg,error_deg);post=clip_polygon(prior,A,b)
    circle=minimum_circle(post) if len(post) else None
    return {'vertices':post,'diameter':diameter_bruteforce(post)[0],
            'circle':circle,'direct_clear_guaranteed':bool(circle is not None and circle['radius']<=20),
            'set_kind':'outer_polygon_of_annular_sector_intersection'}
