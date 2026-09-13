"""Two-sided transverse probes with a certified consequence if both are dark.

移植说明（absorbed 版）：与源 Q3_Q4_V3\\workstreams\\q4_local_optimization_20260912\\crossbar.py 逐行一致，
仅模块 docstring 补注。无 import 改写（只依赖 math/numpy）。
"""
import math
import numpy as np

def probe_pair(poly,reference_position,reference_bearing,position,offset=.25,error=1.005):
    p=np.asarray(poly);s=np.asarray(reference_position);a=math.radians(reference_bearing)
    u=np.array([math.cos(a),math.sin(a)]);v=np.array([-u[1],u[0]])
    forward=(p-s)@u;d=(float(forward.min())+float(forward.max()))/2
    halfwidth=max(d*math.tan(math.radians(error))+1e-5,offset*(float(forward.max())-float(forward.min())))
    points=[s+d*u+sign*halfwidth*v for sign in (-1,1)]
    bound=max(float(np.max(np.linalg.norm(p-q,axis=1))) for q in points)
    if bound>1000-1e-6:
        halfwidth=d*math.tan(math.radians(error))+1e-5
        points=[s+d*u+sign*halfwidth*v for sign in (-1,1)]
        bound=max(float(np.max(np.linalg.norm(p-q,axis=1))) for q in points)
    if bound>1000-1e-6:raise RuntimeError('Crossbar range certificate not established')
    points.sort(key=lambda q:math.dist(position,q))
    return points, {'reference_position':s.tolist(),'reference_bearing_deg':reference_bearing,'error_bound_deg':error,
        'unit_forward':u.tolist(),'unit_transverse':v.tolist(),'section_distance_m':d,'halfwidth_m':halfwidth,
        'maximum_vertex_distance_m':bound,'cut_normal':u.tolist(),'cut_rhs':float(u@s+d)+1e-7}
