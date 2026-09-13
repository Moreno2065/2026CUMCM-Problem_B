# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\q3_optimizer_v4.py (251 行)
# 改动：① 删除 ROOT=Path(__file__).resolve().parents[2] 与 sys.path.insert（源 6-7 行），
#       及随之无用的 from pathlib import Path / sys；
#       ② 4 处顶层 import 改为显式包内相对 import（practice_all_sources_fast / practice_single_source /
#       geometry_src / q2_adopted）。
# 算法、VERSION='q3_negative_evidence_flexible_sectors_v4'、SELECTED_PARAMETERS(16 键)、异常文本、
# 返回字典键名逐行未改。详见 MANIFEST.md。
"""Offline prototype: share bearing observations among sources before choosing a route."""
import math
from functools import lru_cache
import numpy as np
from .practice_all_sources_fast import initial_polygon,covered_cells,CELL_CENTRES
from .practice_single_source import minimum_circle,clip_polygon,bearing_halfplanes,ERROR
from .geometry_src import hull
from .q2_adopted import reception_residuals

def exclude_disk(poly,centre,radius=1000-1e-5):
    """Convex hull of a convex polygon outside an open disk, computed by edge intersections."""
    centre=np.asarray(centre);p=np.asarray(poly);out=[]
    if np.all(np.linalg.norm(p-centre,axis=1)>=radius):return p
    for i,a in enumerate(p):
        b=p[(i+1)%len(p)];v=b-a;w=a-centre
        if np.linalg.norm(w)>=radius-1e-8:out.append(a)
        qa=float(v@v);qb=2*float(v@w);qc=float(w@w)-radius*radius
        disc=qb*qb-4*qa*qc
        if qa>1e-16 and disc>=0:
            for t in ((-qb-math.sqrt(disc))/(2*qa),(-qb+math.sqrt(disc))/(2*qa)):
                if 0<=t<=1:out.append(a+t*v)
    return hull(out).reshape(-1,2)

def negative_refine(poly,negative,positive,kind):
    p=poly
    if kind in ('bisector','both'):
        for n in negative:
            n=np.asarray(n)
            for s in positive:
                s=np.asarray(s);p=clip_polygon(p,[2*(n-s)],[float(n@n-s@s)+1e-6])
    if kind in ('disk','both'):
        for n in negative:
            p=exclude_disk(p,n)
            if not len(p):break
    if not len(p):raise RuntimeError('Empty region after negative evidence')
    return p

def first_route_target(position,known,ends=None,end_costs=None):
    channels=sorted(known);points=np.array([known[c]['center'] for c in channels]);n=len(channels)
    distances=np.linalg.norm(points[:,None,:]-points[None,:,:],axis=2)
    start=np.linalg.norm(points-position,axis=1)
    end=np.min(np.linalg.norm(points[:,None,:]-np.asarray(ends)[None,:,:],axis=2),axis=1) if ends is not None and len(ends) else np.zeros(n)
    if end_costs is not None:end=np.array(end_costs)
    if n<=10:
        @lru_cache(None)
        def tail(last,mask):
            if not mask:return float(end[last])
            return min(float(distances[last,j])+tail(j,mask^(1<<j)) for j in range(n) if mask&(1<<j))
        return channels[min(range(n),key=lambda i:(start[i]+tail(i,((1<<n)-1)^(1<<i)),i))]
    # Larger pending sets: compare nearest-neighbour open routes from each first source.
    choices=[]
    for first in range(n):
        route=[first];remaining=set(range(n))-{first};cost=start[first]
        while remaining:
            j=min(remaining,key=lambda j:(distances[route[-1],j],j));cost+=distances[route[-1],j];route.append(j);remaining.remove(j)
        choices.append((cost+end[route[-1]],first))
    return channels[min(choices)[1]]

@lru_cache(maxsize=4096)
def _continuous_cover(key):
    if not key:return False
    stations=np.array(key);todo=[(0.,0.,1800.,0)]
    while todo:
        x,y,half,depth=todo.pop();q=np.array([x,y])
        if max(abs(x)-half,0)**2+max(abs(y)-half,0)**2>1800**2+1e-6:continue
        distance=float(np.min(np.linalg.norm(stations-q,axis=1)))
        if distance+math.sqrt(2)*half<=1000-1e-6:continue
        if x*x+y*y<=1800**2 and distance>1000:return False
        if depth>=18:return False
        h=half/2
        todo.extend((x+sx*h,y+sy*h,h,depth+1) for sx,sy in ((-1,-1),(-1,1),(1,-1),(1,1)))
    return True

def continuous_cover(points):return _continuous_cover(tuple(sorted(set(tuple(map(float,p)) for p in points))))

def project_to_disks(position,centres,radius=990.):
    position=np.asarray(position);centres=np.asarray(centres)
    if np.max(np.linalg.norm(centres-position,axis=1))<=radius:return position.copy()
    candidates=[]
    for c in centres:
        v=position-c;length=np.linalg.norm(v)
        if length:candidates.append(c+v*(radius/length))
    for i,a in enumerate(centres):
        for b in centres[i+1:]:
            v=b-a;length=np.linalg.norm(v)
            if 0<length<=2*radius:
                midpoint=(a+b)/2;normal=np.array([-v[1],v[0]])/length;h=math.sqrt(max(0.,radius*radius-length*length/4))
                candidates.extend([midpoint+h*normal,midpoint-h*normal])
    feasible=[p for p in candidates if np.max(np.linalg.norm(centres-p,axis=1))<=radius+1e-7]
    if not feasible:raise RuntimeError('No feasible sector observation point')
    return min(feasible,key=lambda p:math.dist(p,position))

def solve_joint(client,known_range=1500.,unknown_gain=0,search='nearest',offset=.1,advance=.25,search_power=1.,negative_mode='both',route='nearest',station_radius=1250.,share_during=False,count_stop=False,coverage='cells',interleave=False,close_clear=False,initial_probe=None,finish_unknown=False,progress=None):
    sites=np.array([[0.,0.]]+[[station_radius*math.cos(k*math.pi/3),station_radius*math.sin(k*math.pi/3)] for k in range(6)])
    sector_corners={k+1:np.array([[r*math.cos(k*math.pi/3+a),r*math.sin(k*math.pi/3+a)] for r in (990.,1800.) for a in (-math.pi/6,math.pi/6)]) for k in range(6)}
    remaining=set(range(1,21));known={};cleared=[];absent=set();observations={c:[] for c in remaining}
    negative={c:[] for c in remaining};positive={c:[] for c in remaining};cover=np.zeros((21,len(CELL_CENTRES)),dtype=bool);unused=set(range(1,7))
    visits=[]
    iterations={c:0 for c in remaining}
    if search=='adaptive':
        pool=np.vstack((sites,np.array([[x,y] for x in range(-1500,1501,375) for y in range(-1500,1501,375)])))
        masks=np.array([covered_cells(p) for p in pool],dtype=np.int32)
    def observe(c,pos,kind):
        pos=np.asarray(pos,dtype=float);reply=client.act('/measure',pos,c)
        rec={'position':pos.tolist(),'response':reply,'kind':kind,'sequence':len(client.rows)}
        observations[c].append(rec)
        if reply['measure_result']=='no_signal':
            negative[c].append(pos.tolist());cover[c]|=covered_cells(pos)
            if c in known and known[c]['polygon'] is not None:
                p=negative_refine(known[c]['polygon'],negative[c],positive[c],negative_mode)
                circ=minimum_circle(p);known[c].update(polygon=p,center=circ['center'],radius=circ['radius'])
            if (continuous_cover(negative[c]) if coverage=='continuous' else np.all(cover[c])):
                if c in known:raise RuntimeError('Known source contradicts negative coverage')
                absent.add(c);remaining.remove(c)
        else:
            positive[c].append(pos.tolist())
            if reply['measure_result']=='near':
                known[c]={'polygon':None,'center':pos,'radius':5.,'last_position':pos}
            else:
                if c in known:
                    p=known[c]['polygon']
                    if p is None:raise RuntimeError('Near source should be cleared without further measurement')
                    A,b=bearing_halfplanes(pos,reply['svd_deg'],ERROR);p=clip_polygon(p,A,b)
                else:p=initial_polygon(pos,reply['svd_deg'])
                if not len(p):raise RuntimeError('Empty observation intersection')
                p=negative_refine(p,negative[c],positive[c],negative_mode)
                circ=minimum_circle(p)
                known[c]={'polygon':p,'center':circ['center'],'radius':circ['radius'],'last_position':pos}
        if c in known:
            d=known[c];rec.update(posterior_vertices=None if d['polygon'] is None else d['polygon'].tolist(),
                circle_center=d['center'].tolist(),bound_m=d['radius'])
        return reply
    def scan_site(pos,index):
        visits.append({'position':list(pos),'fixed_site_index':index})
        mask=covered_cells(pos)
        for c in sorted(remaining-set(known)):
            if coverage=='continuous' or np.any(mask & ~cover[c]):observe(c,pos,'search')
    def share(include_unknown=True):
        pos=np.asarray(client.position)
        if known_range:
            for c in sorted(known):
                d=known[c]
                if d['radius']<=20-1e-6 or math.dist(pos,d['last_position'])<150:continue
                if math.dist(pos,d['center'])>known_range:continue
                # Test expected information gain at the current region centre; only a routing heuristic.
                delta=d['center']-pos
                if np.linalg.norm(delta)<1e-5:continue
                angle=math.degrees(math.atan2(delta[1],delta[0]))%360
                A,b=bearing_halfplanes(pos,angle,ERROR);poly=clip_polygon(d['polygon'],A,b)
                if len(poly) and minimum_circle(poly)['radius']<.7*d['radius']:
                    observe(c,pos,'shared_bearing')
        if unknown_gain and include_unknown:
            mask=covered_cells(pos)
            for c in sorted(remaining-set(known)):
                if np.count_nonzero(mask & ~cover[c])>=unknown_gain:observe(c,pos,'shared_search')
        if finish_unknown and include_unknown:
            for c in sorted(remaining-set(known)):
                if continuous_cover(negative[c]+[pos.tolist()]):observe(c,pos,'finish_channel')
    scan_site(sites[0],0)
    while remaining:
        if known:
            if route=='nearest':c=min(known,key=lambda c:(math.dist(client.position,known[c]['center']),c))
            else:
                end_costs=None
                if route=='next_site' and search=='sectors' and unused:
                    end_costs=[min(math.dist(known[c]['center'],project_to_disks(known[c]['center'],sector_corners[i])) for i in unused) for c in sorted(known)]
                c=first_route_target(np.asarray(client.position),known,sites[sorted(unused)] if route=='next_site' else None,end_costs=end_costs)
            d=known[c]
            steps=iterations[c]
            while d['radius']>20-1e-6:
                if d['radius']>=1000-1e-6:raise RuntimeError('Centre reception certificate failed')
                prior=d['radius'];target=d['center'].copy()
                prior_poly=d['polygon'].copy()
                if offset and steps%2==0 and d['polygon'] is not None:
                    poly=d['polygon'];dist=np.sum((poly[:,None,:]-poly[None,:,:])**2,axis=2)
                    ia,ib=np.unravel_index(np.argmax(dist),dist.shape)
                    u=poly[ia]-poly[ib];u=u/np.linalg.norm(u)
                    if np.dot(u,np.array(client.position)-target)<0:u=-u
                    v=np.array([-u[1],u[0]])
                    choices=[target+advance*prior*u+sign*offset*prior*v for sign in (-1,1)]
                    choices=[p for p in choices if np.max(np.linalg.norm(poly-p,axis=1))<1000-1e-6]
                    if choices:target=min(choices,key=lambda p:math.dist(p,client.position))
                conditional_probe=False
                if initial_probe is not None and steps==0 and prior>200:
                    ref=next(o for o in observations[c] if o['response']['measure_result']=='direction')
                    angle=math.radians(ref['response']['svd_deg']);u=np.array([math.cos(angle),math.sin(angle)]);v=np.array([-u[1],u[0]])
                    a,b=initial_probe
                    if max(reception_residuals([a,b],ERROR))>1e-6:raise RuntimeError('Invalid conditional reception probe')
                    choices=[np.array(ref['position'])+a*u+sign*b*v for sign in (-1,1)]
                    target=min(choices,key=lambda q:math.dist(q,client.position));conditional_probe=True
                response=observe(c,target,'localization');steps+=1
                iterations[c]=steps
                observations[c][-1]['prior_radius_m']=prior
                observations[c][-1]['max_vertex_distance_m']=float(np.max(np.linalg.norm(prior_poly-target,axis=1)))
                observations[c][-1]['conditional_probe']=conditional_probe
                if response['measure_result']=='no_signal':raise RuntimeError('Guaranteed measurement lost signal')
                if share_during:share(False)
                d=known[c]
                if steps>12:raise RuntimeError('Iteration limit')
                if interleave:break
            if d['radius']>20-1e-6:continue
            clear_point=project_to_disks(client.position,d['polygon'],20-1e-6) if close_clear and d['polygon'] is not None else d['center']
            reply=client.act('/clear',clear_point,c)
            if reply['clear_result']!='success':raise RuntimeError('Certified clear failed')
            clear_bound=float(np.max(np.linalg.norm(d['polygon']-clear_point,axis=1))) if d['polygon'] is not None else 5.
            cleared.append({'channel':c,'clear_point':clear_point.tolist(),'bound_m':clear_bound,
                            'observations':observations[c],'virtual_time_after_clear_s':client.virtual})
            known.pop(c);remaining.remove(c)
            if progress:progress(f'已清除 {len(cleared)} 个源；最近频道 {c}；虚拟时间 {client.virtual:.2f} 秒')
            if count_stop and len(cleared)==16:break
            share()
        else:
            if search=='sectors':
                if not unused:raise RuntimeError('Unresolved channels after all sector visits')
                choices={i:project_to_disks(client.position,sector_corners[i]) for i in unused}
                i=min(unused,key=lambda i:(math.dist(client.position,choices[i]),i));unused.remove(i)
                scan_site(choices[i],i);visits[-1]['sector_corners']=sector_corners[i].tolist()
                continue
            if search=='adaptive':
                weight=np.sum(~cover[sorted(remaining)],axis=0,dtype=np.int32)
                gains=masks@weight
                costs=np.linalg.norm(pool-np.array(client.position),axis=1)+30*len(remaining)
                score=gains/np.power(costs,search_power)
                idx=int(np.argmax(score))
                if gains[idx]<=0:raise RuntimeError('No new coverage available')
                scan_site(pool[idx],None)
                continue
            if not unused:raise RuntimeError('Unresolved channels after full coverage')
            def rank(i):
                dist=math.dist(client.position,sites[i])
                gain=sum(np.count_nonzero(covered_cells(sites[i]) & ~cover[c]) for c in remaining)
                if search=='gain':return -(gain/(dist+200)),i
                return dist,i
            i=min(unused,key=rank);unused.remove(i);scan_site(sites[i],i)
    if not 10<=len(cleared)<=16:raise RuntimeError('Invalid Q3 source count')
    return {'strategy':'joint_negative','parameters':{'known_range':known_range,'unknown_gain':unknown_gain,'search':search,'offset':offset,'advance':advance,'search_power':search_power,'negative_mode':negative_mode,'route':route,'station_radius':station_radius,'share_during':share_during,'count_stop':count_stop,'coverage':coverage,'interleave':interleave,'close_clear':close_clear,'initial_probe':initial_probe,'finish_unknown':finish_unknown},
            'cleared_count':len(cleared),'cleared_sources':cleared,'cleared_channels':sorted(x['channel'] for x in cleared),
            'negative_observations':{str(c):negative[c] for c in sorted(absent)},'search_sites':sites.tolist(),
            'scan_visits':visits,'observations':{str(c):observations[c] for c in range(1,21)},
            'source_upper_bound_stop':len(cleared)==16 and count_stop,'count_inferred_absent_channels':sorted(remaining) if len(cleared)==16 and count_stop else [],
            'average_virtual_seconds_per_cleared_source':client.virtual/len(cleared)}


VERSION = "q3_negative_evidence_flexible_sectors_v4"
SELECTED_PARAMETERS = {'known_range': 1500.0, 'unknown_gain': 0, 'search': 'sectors', 'offset': 0.1, 'advance': 0.25, 'search_power': 1.0, 'negative_mode': 'both', 'route': 'next_site', 'station_radius': 1250.0, 'share_during': False, 'count_stop': True, 'coverage': 'continuous', 'interleave': True, 'close_clear': True, 'initial_probe': None, 'finish_unknown': False}

def solve_optimized(client, progress=None):
    return solve_joint(client, progress=progress, **SELECTED_PARAMETERS)
