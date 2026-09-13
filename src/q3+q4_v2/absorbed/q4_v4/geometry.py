"""Planar bearing sets. Angles public API: degrees; lengths: metres.

Double precision implementation; tolerance checks are numerical, not exact arithmetic.
No simulator access or assumptions about error probability.
"""
from itertools import combinations
import math
import numpy as np
from scipy.optimize import linprog

TOL = 1e-8

def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]

def hull(points):
    p = sorted(set((float(x), float(y)) for x,y in points))
    if len(p) <= 1:
        return np.array(p, dtype=float).reshape(-1,2)
    def half(seq):
        q=[]
        for x in seq:
            while len(q)>1 and cross(np.subtract(q[-1],q[-2]),np.subtract(x,q[-1])) <= 1e-12:
                q.pop()
            q.append(x)
        return q
    return np.array(half(p)[:-1]+half(p[::-1])[:-1])

def bearing_halfplanes(position, bearing_deg, error_deg=1.):
    s=np.asarray(position,dtype=float)
    if s.shape != (2,) or not np.all(np.isfinite(s)) or not np.isfinite(bearing_deg):
        raise ValueError('Finite two-dimensional position and bearing required')
    if not np.isfinite(error_deg) or not 0 <= error_deg < 90:
        raise ValueError('error_deg must be in [0,90)')
    lo,hi=np.deg2rad([bearing_deg-error_deg,bearing_deg+error_deg])
    # cross(u_lo, X-S)>=0 and cross(u_hi, X-S)<=0.
    A=np.array([[math.sin(lo),-math.cos(lo)],[-math.sin(hi),math.cos(hi)]])
    b=A@s
    if error_deg == 0:
        u=np.array([math.cos(lo),math.sin(lo)])
        A=np.vstack((A,-u));b=np.append(b,-u@s)
    return A,b

def observation_constraints(observations, error_deg=1.):
    rows=[bearing_halfplanes(o[:2],o[2],error_deg) for o in observations]
    if not rows:
        return np.empty((0,2)),np.empty(0)
    return np.vstack([r[0] for r in rows]),np.concatenate([r[1] for r in rows])

def clip_polygon(poly,A,b,tol=TOL):
    """Sutherland-Hodgman clipping, retaining boundary and degenerate sets."""
    p=[np.asarray(v,dtype=float) for v in poly]
    for a,bi in zip(A,b):
        if not p: break
        out=[]
        prev=p[-1];dp=float(a@prev-bi);prev_in=dp<=tol
        for cur in p:
            dc=float(a@cur-bi);cur_in=dc<=tol
            if cur_in != prev_in:
                den=dp-dc
                if abs(den)>1e-16:
                    out.append(prev+(cur-prev)*(dp/den))
            if cur_in: out.append(cur)
            prev,dp,prev_in=cur,dc,cur_in
        p=[]
        for v in out:
            if not p or np.linalg.norm(v-p[-1])>tol:
                p.append(v)
        if len(p)>1 and np.linalg.norm(p[0]-p[-1])<=tol: p.pop()
    return np.array(p,dtype=float).reshape(-1,2)

def polytope(A,b,method='clip'):
    """Return empty/unbounded/bounded and ordered extreme points.

    LP extrema bound the set before clipping. No guessed bounding box truncates it.
    Pair enumeration is a separate reference construction.
    """
    A=np.asarray(A,dtype=float).reshape(-1,2);b=np.asarray(b,dtype=float)
    if len(A)!=len(b) or not np.all(np.isfinite(A)) or not np.all(np.isfinite(b)):
        raise ValueError('Invalid halfplanes')
    if not len(A):return {'status':'unbounded','vertices':np.empty((0,2))}
    kw=dict(A_ub=A,b_ub=b,bounds=[(None,None)]*2,method='highs')
    feasibility=linprog([0.,0.],**kw)
    if feasibility.status==2:return {'status':'empty','vertices':np.empty((0,2))}
    if not feasibility.success:raise RuntimeError(feasibility.message)
    extrema=[]
    for c in ([1,0],[-1,0],[0,1],[0,-1]):
        r=linprog(c,**kw)
        if r.status==3:return {'status':'unbounded','vertices':np.empty((0,2))}
        if not r.success:raise RuntimeError(r.message)
        extrema.append(r.fun)
    if method=='pairs':
        p=[]
        for i,j in combinations(range(len(b)),2):
            aa=A[[i,j]]
            if abs(np.linalg.det(aa))<1e-13:continue
            v=np.linalg.solve(aa,b[[i,j]])
            if np.max(A@v-b)<=1e-6:p.append(v)
        if not p:p=[feasibility.x]
        p=hull(p)
    elif method=='clip':
        xmin,xmax,ymin,ymax=extrema[0],-extrema[1],extrema[2],-extrema[3]
        pad=1e-7*max(1,abs(xmin),abs(xmax),abs(ymin),abs(ymax))
        p=clip_polygon([[xmin-pad,ymin-pad],[xmax+pad,ymin-pad],
                        [xmax+pad,ymax+pad],[xmin-pad,ymax+pad]],A,b)
        p=hull(p)
    else:raise ValueError('Unknown construction method')
    if len(p)==0:raise RuntimeError('Feasible LP but clipping empty: numerical failure')
    if np.max(A@p.T-b[:,None])>1e-5:raise RuntimeError('Vertex residual too large')
    return {'status':'bounded','vertices':p}

def diameter_bruteforce(p):
    p=np.asarray(p).reshape(-1,2)
    if not len(p):return None,None
    d2=np.sum((p[:,None,:]-p[None,:,:])**2,axis=2)
    i,j=np.unravel_index(np.argmax(d2),d2.shape)
    return math.sqrt(float(d2[i,j])),(int(i),int(j))

def diameter_calipers(p):
    p=np.asarray(p).reshape(-1,2);n=len(p)
    if n<=2:return diameter_bruteforce(p)
    # Requires CCW convex polygon; hull() also removes intermediate collinear points.
    j=1;best=-1.;pair=None
    for i in range(n):
        ni=(i+1)%n;edge=p[ni]-p[i]
        def area(k):return cross(edge,p[k]-p[i])
        for _ in range(n):
            nj=(j+1)%n
            if area(nj)>area(j)+1e-10:j=nj
            else:break
        cand=[j]
        if abs(area((j+1)%n)-area(j))<=1e-10:cand.append((j+1)%n)
        for k in cand:
            for v in [i,ni]:
                d2=float(np.sum((p[v]-p[k])**2))
                if d2>best:best=d2;pair=(v,k)
    return math.sqrt(max(0,best)),pair

def circumcircle(a,b,c):
    a,b,c=map(np.asarray,(a,b,c));u=b-a;v=c-a
    mat=2*np.array([u,v])
    if abs(np.linalg.det(mat))<1e-12:return None
    o=a+np.linalg.solve(mat,[u@u,v@v])
    return o,float(np.linalg.norm(o-a))

def minimum_circle(p):
    """Enumerate 1/2/3 support points, O(v^4); transparent for small bearing polygons."""
    p=np.asarray(p).reshape(-1,2);n=len(p)
    if not n:return None
    best=None
    def consider(c,r,support):
        nonlocal best
        if best is not None and r>=best['radius']:return
        if np.max(np.linalg.norm(p-c,axis=1)) <= r+1e-7:
            # Inflate at machine scale so the returned circle actually contains vertices.
            r=max(r,float(np.max(np.linalg.norm(p-c,axis=1))))
            best={'center':c,'radius':r,'support':support}
    for i in range(n):consider(p[i],0,[i])
    for i,j in combinations(range(n),2):
        consider((p[i]+p[j])/2,float(np.linalg.norm(p[i]-p[j])/2),[i,j])
    for i,j,k in combinations(range(n),3):
        circle=circumcircle(p[i],p[j],p[k])
        if circle is not None:consider(*circle,[i,j,k])
    if best is None:raise RuntimeError('No enclosing support circle')
    return best

def solve_bearings(observations,error_deg=1.,method='clip'):
    A,b=observation_constraints(observations,error_deg);r=polytope(A,b,method)
    if r['status']!='bounded':
        r.update(diameter=math.inf if r['status']=='unbounded' else None,circle=None)
        return r
    p=r['vertices'];d,pair=diameter_calipers(p);circle=minimum_circle(p)
    r.update(diameter=d,diameter_pair=pair,circle=circle,
             equal_diameter_circle_covers=bool(circle['radius']<=d/2+1e-7))
    return r
