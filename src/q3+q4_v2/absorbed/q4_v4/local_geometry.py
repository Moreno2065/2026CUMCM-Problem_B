"""Pure geometry for Q4. No environment, client, network or hidden scene inputs.

移植说明（absorbed 版，与源 Q3_Q4_V3\\workstreams\\q4_local_optimization_20260912\\local_geometry.py 的差异，仅 import 相关）：
- 源第 2-3 行 `from pathlib import Path` / `import ... sys` 与第 6 行
  `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'code/src'))`
  已删除：源用该注入把 Q3_Q4_V3\\code\\src 加到 sys.path 再 `from geometry import ...`。
  本包改为显式包内相对 import `from .geometry import ...`（对应 vendored geometry.py）。
- 其余（ERROR 常量、全部函数体、数值表达式、异常文本、返回字典键）与源逐行一致。
"""
import math, random
sys_dont_write_bytecode = True
import numpy as np
from .geometry import bearing_halfplanes, clip_polygon, hull, minimum_circle as enumerated_circle

ERROR = 1.005

def minimum_circle(poly):
    """Randomized incremental support circle; deterministic shuffle, no scene RNG."""
    p=[tuple(map(float,x)) for x in poly]
    if not p:raise RuntimeError('Empty circle input')
    random.Random(60491).shuffle(p)
    def contains(c,q):return c is not None and math.dist(c[0],q)<=c[1]+1e-8
    def diameter(a,b):return ((.5*(a[0]+b[0]),.5*(a[1]+b[1])),.5*math.dist(a,b))
    def cross(a,b):return a[0]*b[1]-a[1]*b[0]
    def circum(a,b,c):
        bx,by=b[0]-a[0],b[1]-a[1];cx,cy=c[0]-a[0],c[1]-a[1];den=2*(bx*cy-by*cx)
        if abs(den)<1e-12:return None
        bb=bx*bx+by*by;cc=cx*cx+cy*cy
        o=(a[0]+(cy*bb-by*cc)/den,a[1]+(bx*cc-cx*bb)/den)
        return o,max(math.dist(o,x) for x in (a,b,c))
    def two(points,a,b):
        diam=diameter(a,b);left=right=None;ab=(b[0]-a[0],b[1]-a[1])
        for r in points:
            if contains(diam,r):continue
            cr=cross(ab,(r[0]-a[0],r[1]-a[1]));c=circum(a,b,r)
            if c is None:continue
            side=cross(ab,(c[0][0]-a[0],c[0][1]-a[1]))
            if cr>0 and (left is None or side>left[2]):left=(c[0],c[1],side)
            if cr<0 and (right is None or side<right[2]):right=(c[0],c[1],side)
        candidates=[c[:2] for c in (left,right) if c is not None]
        return min(candidates,key=lambda c:c[1]) if candidates else diam
    circle=None
    for i,a in enumerate(p):
        if contains(circle,a):continue
        circle=(a,0.)
        for j,b in enumerate(p[:i]):
            if contains(circle,b):continue
            circle=diameter(a,b) if circle[1]==0 else two(p[:j+1],a,b)
    centre=np.asarray(circle[0]);radius=max(circle[1],float(np.max(np.linalg.norm(np.asarray(poly)-centre,axis=1))))
    return {'center':centre,'radius':radius,'support':None}

def stations_and_triangles(inner=990., outer=None,layout='8_16'):
    if layout=='12_12':
        outer=(1800.5/math.cos(math.pi/12)) if outer is None else outer
        points=[[0.,0.]]+[[inner*math.cos((k+.5)*math.pi/6),inner*math.sin((k+.5)*math.pi/6)] for k in range(12)]
        points += [[outer*math.cos(k*math.pi/6),outer*math.sin(k*math.pi/6)] for k in range(12)]
        triangles=[]
        for k in range(12):triangles += [(0,1+k,1+(k+1)%12),(13+k,13+(k+1)%12,1+k),(13+k,1+k,1+(k-1)%12)]
        return np.array(points),triangles
    if layout!='8_16':raise ValueError(layout)
    outer = (1800.5 / math.cos(math.pi/16)) if outer is None else outer
    points = [[0.,0.]]
    points += [[inner*math.cos(k*math.pi/4), inner*math.sin(k*math.pi/4)] for k in range(8)]
    points += [[outer*math.cos(k*math.pi/8), outer*math.sin(k*math.pi/8)] for k in range(16)]
    triangles=[]
    for k in range(8):
        a=1+k; b=1+(k+1)%8
        x=9+2*k; y=9+(2*k+1)%16; z=9+(2*k+2)%16
        triangles += [(0,a,b),(a,x,y),(a,y,b),(b,y,z)]
    return np.array(points), triangles

def initial_polygon(station,theta):
    s=np.asarray(station);a=math.radians(theta);u=np.array([math.cos(a),math.sin(a)]);v=np.array([-u[1],u[0]])
    delta=math.radians(ERROR);near=5*math.cos(delta);slope=math.tan(delta)
    p=np.array([s+x*u+y*v for x,y in ((near,-near*slope),(1500,-1500*slope),(1500,1500*slope),(near,near*slope))])
    angles=np.arange(72)*math.pi/36
    return clip_polygon(p,np.column_stack((np.cos(angles),np.sin(angles))),np.full(72,1800.))

def exclude_disk(poly, centre, radius=20-1e-5):
    """Convex outer hull after an unsuccessful optical operation."""
    p=np.asarray(poly);centre=np.asarray(centre);out=[]
    if np.all(np.linalg.norm(p-centre,axis=1)>=radius):return p
    for i,a in enumerate(p):
        b=p[(i+1)%len(p)];v=b-a;w=a-centre
        if np.linalg.norm(w)>=radius-1e-8:out.append(a)
        qa=float(v@v);qb=2*float(v@w);qc=float(w@w)-radius**2;disc=qb*qb-4*qa*qc
        if qa>1e-16 and disc>=0:
            for t in ((-qb-math.sqrt(disc))/(2*qa),(-qb+math.sqrt(disc))/(2*qa)):
                if 0<=t<=1:out.append(a+t*v)
    return hull(out).reshape(-1,2)

def optical_cover(poly, position, spacing=27.5):
    """Cover the entire oriented bounding rectangle by radius <20 disks."""
    p=np.asarray(poly);delta=p[:,None,:]-p[None,:,:];i,j=np.unravel_index(np.argmax(np.sum(delta**2,axis=2)),delta.shape[:2])
    u=p[i]-p[j];u=u/max(np.linalg.norm(u),1e-12);v=np.array([-u[1],u[0]])
    basis=np.array([u,v]);local=p@basis.T;lo=local.min(axis=0);hi=local.max(axis=0)
    n=np.maximum(1,np.ceil((hi-lo)/spacing).astype(int));step=(hi-lo)/n
    coords=[lo[k]+step[k]*(np.arange(n[k])+.5) for k in range(2)]
    candidates=[]
    for swap in (False,True):
        for reverse in (False,True):
            pts=[]
            outer=range(n[1] if not swap else n[0])
            if reverse:outer=reversed(list(outer))
            for index,a in enumerate(outer):
                inner=range(n[0] if not swap else n[1])
                if index%2:inner=reversed(list(inner))
                for b in inner:
                    xy=[coords[0][b],coords[1][a]] if not swap else [coords[0][a],coords[1][b]]
                    pts.append(np.array(xy)@basis)
            length=math.dist(position,pts[0])+sum(math.dist(a,b) for a,b in zip(pts,pts[1:]))
            candidates.append((length,pts))
    return min(candidates,key=lambda x:x[0])[1], {'basis':basis.tolist(),'lower':lo.tolist(),'upper':hi.tolist(),
        'counts':n.tolist(),'step':step.tolist(),'cell_radius_m':float(np.linalg.norm(step)/2),'spacing':spacing}

def open_tour(position,points):
    if not len(points):return []
    p=np.vstack((position,points));n=len(points);D=np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2).tolist()
    routes=[]
    for first in range(1,n+1):
        route=[0,first];left=set(range(1,n+1))-{first}
        while left:
            j=min(left,key=lambda x:(D[route[-1]][x],x));left.remove(j);route.append(j)
        routes.append((sum(D[a][b] for a,b in zip(route,route[1:])),route))
    improved=[]
    for cost,route in sorted(routes)[:3]:
        for _ in range(2*n):
            change=(0.,None,None)
            for i in range(1,n):
                for j in range(i+1,n+1):
                    gain=D[route[i-1]][route[j]]-D[route[i-1]][route[i]]
                    if j<n:gain+=D[route[i]][route[j+1]]-D[route[j]][route[j+1]]
                    if gain<change[0]-1e-8:change=(gain,i,j)
            gain,i,j=change
            if i is None:break
            route[i:j+1]=reversed(route[i:j+1]);cost+=gain
        improved.append((cost,route))
    return [x-1 for x in min(improved)[1][1:]]

class DirectionBelief:
    """Outer location sets conditional on contiguous emission-angle intervals."""
    def __init__(self,poly,positives,negatives,width_deg=4.):
        count=math.ceil(360/width_deg);self.width=2*math.pi/count;self.factor=2*math.sin(self.width/4)
        self.parts={k:np.asarray(poly).copy() for k in range(count)}
        self.normals={k:np.array([math.cos(k*self.width),math.sin(k*self.width)]) for k in range(count)}
        for p in positives:self.update_sign(p,True)
        for p in negatives:self.update_sign(p,False)
    def update_sign(self,point,positive):
        point=np.asarray(point);new={}
        for k,p in self.parts.items():
            u=self.normals[k];bound=self.factor*float(np.max(np.linalg.norm(p-point,axis=1)))+1e-7
            sign=1 if positive else -1
            q=clip_polygon(p,[sign*u],[sign*float(u@point)+bound])
            if len(q):new[k]=q
        self.parts=new
    def restrict(self,poly):
        # Convex hull polygon converted into outward edge halfplanes.
        if len(poly)<3:
            lo=np.min(poly,axis=0)-1e-7;hi=np.max(poly,axis=0)+1e-7
            A=np.array([[1,0],[-1,0],[0,1],[0,-1]]);b=np.array([hi[0],-lo[0],hi[1],-lo[1]])
        else:
            edge=np.roll(poly,-1,axis=0)-poly;A=np.column_stack((edge[:,1],-edge[:,0]));b=np.sum(A*poly,axis=1)+1e-7
        new={}
        for k,p in self.parts.items():
            q=clip_polygon(p,A,b)
            if len(q):new[k]=q
        self.parts=new
    def polygon(self):
        if not self.parts:raise RuntimeError('Direction belief empty')
        return hull(np.vstack(list(self.parts.values())))
