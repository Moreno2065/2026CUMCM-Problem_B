# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\src\q3_optimizer_v5.py (270 行)
# 改动：① 删除 ROOT=Path(__file__).resolve().parents[2] 与 sys.path.insert（源 6-7 行），及随之无用的
#       from pathlib import Path / sys；② 2 处顶层 import 改为显式包内相对 import。
#       "import practice_single_source"（源第 8 行）在源文件中未被调用，为保持依赖边与逐行一致而保留，
#       改写为 "from . import practice_single_source"。
# 契约未动：VERSION='q3_joint_search_clear_route_v5'（源 264 行）、SELECTED_PARAMETERS 21 键（源 265 行）、
# solve_optimized_v5(client, progress=None)（源 267-270 行）= solve(client, progress=progress, **SELECTED_PARAMETERS)。
# 算法、默认参数、异常文本、返回字典键名逐行未改。详见 MANIFEST.md。
"""Joint search/localization route candidates; observations only, no world internals."""
import math
import numpy as np
from scipy.optimize import minimize
from . import practice_single_source
from .q3_optimizer_v4 import (initial_polygon,minimum_circle,negative_refine,clip_polygon,
    bearing_halfplanes,ERROR,continuous_cover,project_to_disks,first_route_target,exclude_disk)


def open_tour(position,points,first_bonus=None):
    """Multistart nearest-neighbour followed by open-path 2-opt."""
    p=np.vstack((np.asarray(position),np.asarray(points)));n=len(points)
    D=np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2).tolist()
    if first_bonus is not None:
        for j,value in enumerate(first_bonus,1):D[0][j]-=value
    starts=[]
    for first in range(1,n+1):
        route=[0,first];remaining=set(range(1,n+1))-{first}
        while remaining:
            j=min(remaining,key=lambda j:(D[route[-1]][j],j));route.append(j);remaining.remove(j)
        cost=sum(D[a][b] for a,b in zip(route,route[1:]));starts.append((cost,route))
    candidates=[]
    for cost,route in sorted(starts)[:4]:
        for _ in range(2*n):
            best=(0.,None,None)
            for i in range(1,n):
                for j in range(i+1,n+1):
                    delta=D[route[i-1]][route[j]]-D[route[i-1]][route[i]]
                    if j<n:delta+=D[route[i]][route[j+1]]-D[route[j]][route[j+1]]
                    if delta<best[0]-1e-8:best=(delta,i,j)
            delta,i,j=best
            if i is None:break
            route[i:j+1]=reversed(route[i:j+1]);cost+=delta
        candidates.append((cost,route))
    cost,route=min(candidates)
    return [i-1 for i in route[1:]],cost


def site_on_route(before,after,corners):
    """Convex sum-of-distances positioning in the four-disk lens."""
    before=np.asarray(before);after=np.asarray(after)
    initial=project_to_disks(before,corners)
    def objective(p):return np.linalg.norm(p-before)+np.linalg.norm(p-after)
    def gradient(p):
        a=p-before;b=p-after
        return a/max(np.linalg.norm(a),1e-10)+b/max(np.linalg.norm(b),1e-10)
    result=minimize(objective,initial,jac=gradient,method='SLSQP',
                    constraints={'type':'ineq','fun':lambda p:990**2-np.sum((corners-p)**2,axis=1),
                                 'jac':lambda p:2*(corners-p)},options={'maxiter':30,'ftol':1e-7})
    candidate=project_to_disks(result.x,corners)
    return candidate if objective(candidate)<objective(initial) else initial


def solve(client,route_mode='joint',probe=0.,share_at_search=True,share_during=False,
          share_ratio=.7,offset=.1,advance=.25,unknown_scan=False,rotation=0.,
          exact_positive=False,info_points=False,arc_scan=0,estimate='circle',trial_radius=0.,trial_limit=12,
          probe_count=1,site_passes=0,site_bonus=0.,planning_radius=0.,commit=False,sweep_advance=0.,progress=None):
    corners={k+1:np.array([[r*math.cos(rotation+k*math.pi/3+a),r*math.sin(rotation+k*math.pi/3+a)]
                           for r in (990.,1800.) for a in (-math.pi/6,math.pi/6)]) for k in range(6)}
    remaining=set(range(1,21));unused=set(corners);known={};cleared=[];absent=set()
    obs={c:[] for c in remaining};negative={c:[] for c in remaining};positive={c:[] for c in remaining}
    iterations={c:0 for c in remaining};visits=[];routing=[]
    trials={c:0 for c in remaining};clear_attempts=[]
    committed=None
    sweep_start=None;sweep_direction=1
    arc_corners=np.array([[[r*math.cos(rotation+k*math.pi/36+a),r*math.sin(rotation+k*math.pi/36+a)]
                           for r in (990.,1800.) for a in (-math.pi/6,-math.pi/6+math.pi/36)] for k in range(72)])
    arc_cover=np.zeros((21,72),dtype=bool)
    def arc_mask(pos):return np.max(np.linalg.norm(arc_corners-pos,axis=2),axis=1)<=990+1e-7
    def observe(c,pos,kind):
        pos=np.array(pos,dtype=float);reply=client.act('/measure',pos,c)
        rec={'position':pos.tolist(),'response':reply,'kind':kind,'sequence':len(client.rows)};obs[c].append(rec)
        if reply['measure_result']=='no_signal':
            negative[c].append(pos.tolist())
            if arc_scan:arc_cover[c]|=arc_mask(pos)
            if c in known:
                poly=negative_refine(known[c]['polygon'],negative[c],positive[c],'both')
                circle=minimum_circle(poly);known[c].update(polygon=poly,center=circle['center'],radius=circle['radius'])
            elif (arc_scan and np.all(arc_cover[c])) or continuous_cover(negative[c]):absent.add(c);remaining.remove(c)
        else:
            positive[c].append(pos.tolist())
            if reply['measure_result']=='near':known[c]={'polygon':None,'center':pos,'radius':5.,'last_position':pos}
            else:
                if c in known:
                    A,b=bearing_halfplanes(pos,reply['svd_deg'],ERROR);poly=clip_polygon(known[c]['polygon'],A,b)
                else:poly=initial_polygon(pos,reply['svd_deg'])
                if exact_positive:
                    angles=np.arange(72)*math.pi/36;A=np.column_stack((np.cos(angles),np.sin(angles)))
                    for p in positive[c]:poly=clip_polygon(poly,A,A@p+1500.)
                poly=negative_refine(poly,negative[c],positive[c],'both');circle=minimum_circle(poly)
                known[c]={'polygon':poly,'center':circle['center'],'radius':circle['radius'],'last_position':pos}
        if c in known:
            d=known[c];rec.update(posterior_vertices=None if d['polygon'] is None else d['polygon'].tolist(),
                                 circle_center=d['center'].tolist(),bound_m=d['radius'])
        return reply
    def share():
        pos=np.array(client.position)
        for c in sorted(known):
            d=known[c]
            if d['radius']<=20-1e-6 or math.dist(pos,d['last_position'])<150:continue
            if math.dist(pos,d['center'])>1500:continue
            delta=d['center']-pos
            if np.linalg.norm(delta)<1e-5:continue
            angle=math.degrees(math.atan2(delta[1],delta[0]))%360
            A,b=bearing_halfplanes(pos,angle,ERROR);poly=clip_polygon(d['polygon'],A,b)
            if len(poly) and minimum_circle(poly)['radius']<share_ratio*d['radius']:observe(c,pos,'shared_bearing')
    def scan(pos,index,kind='search'):
        visits.append({'position':list(pos),'fixed_site_index':index})
        if index:visits[-1]['sector_corners']=planned_corners[index].tolist() if arc_scan else corners[index].tolist()
        for c in sorted(remaining-set(known)):observe(c,pos,kind)
        if share_at_search:share()
    def clear(c,trial=False):
        nonlocal committed
        d=known[c]
        if trial:
            poly=d['polygon'];vertex=min(poly,key=lambda p:math.dist(client.position,p))
            delta=d['center']-vertex;length=np.linalg.norm(delta)
            point=vertex+delta*min(1.,18/max(length,1e-10))
        else:point=project_to_disks(client.position,d['polygon'],20-1e-6) if d['polygon'] is not None else d['center']
        response=client.act('/clear',point,c)
        bound=float(np.max(np.linalg.norm(d['polygon']-point,axis=1))) if d['polygon'] is not None else 5.
        record={'sequence':len(client.rows),'channel':c,'position':point.tolist(),'response':response,'trial':trial,
                'prior_vertices':None if d['polygon'] is None else d['polygon'].tolist(),'prior_bound_m':bound}
        clear_attempts.append(record)
        if response['clear_result']!='success':
            if not trial or response['clear_result']!='no_target_in_range':raise RuntimeError('Certified clear failed')
            trials[c]+=1;poly=exclude_disk(d['polygon'],point,20-1e-5)
            if not len(poly):raise RuntimeError('Clear-negative region became empty')
            circle=minimum_circle(poly);d.update(polygon=poly,center=circle['center'],radius=circle['radius'])
            record.update(posterior_vertices=poly.tolist(),circle_center=circle['center'].tolist(),bound_m=circle['radius'])
            return False
        cleared.append({'channel':c,'clear_point':point.tolist(),'bound_m':min(bound,20.),
                        'bound_source':'successful_clear_response' if trial else 'prior_geometry','observations':obs[c],
                        'virtual_time_after_clear_s':client.virtual})
        known.pop(c);remaining.remove(c)
        if committed==c:committed=None
        if progress:progress(f'已清除 {len(cleared)} 个源；最近频道 {c}；虚拟时间 {client.virtual:.2f} 秒')
        if arc_scan and len(cleared)<16:
            pos=np.array(client.position);mask=arc_mask(pos)
            for c in sorted(remaining-set(known)):
                if np.count_nonzero(mask&~arc_cover[c])>=arc_scan:observe(c,pos,'opportunistic_search')
        return True
    scan([0.,0.],0)
    for probe_step in range(probe_count if probe else 0):
        if not known:break
        candidates=[probe*np.array([math.cos(a),math.sin(a)]) for a in np.arange(0,2*math.pi,math.pi/6)]
        # Bearing diversity identifies a shared transverse probe using only current regions.
        def gain(p):
            total=0.
            for d in known.values():
                if d['radius']<=20:continue
                delta=d['center']-p;angle=math.degrees(math.atan2(delta[1],delta[0]))%360
                A,b=bearing_halfplanes(p,angle,ERROR);poly=clip_polygon(d['polygon'],A,b)
                if len(poly):total+=d['radius']-minimum_circle(poly)['radius']
            return total
        candidates=[p for p in candidates if math.dist(client.position,p)>probe*.75]
        target=max(candidates,key=gain)
        candidates_c=sorted(known)
        for c in candidates_c:
            if known[c]['radius']>20:observe(c,target,'joint_probe')
        if unknown_scan:scan(target,None,'probe_search')
    while remaining:
        if len(client.rows)>=550:raise RuntimeError('Exploration action cap')
        if len(cleared)==16:break
        ready=[c for c,d in known.items() if d['radius']<=20-1e-6 and math.dist(client.position,d['center'])<=40]
        if ready:
            clear(min(ready,key=lambda c:(math.dist(client.position,known[c]['center']),c)));share();continue
        active_sites=sorted(unused) if remaining-set(known) else []
        planned_corners=dict(corners)
        if arc_scan and remaining-set(known):
            needed=np.any(~arc_cover[sorted(remaining-set(known))],axis=0)
            active_sites=[];planned_corners={}
            for i in range(1,7):
                indices=np.flatnonzero(needed[(i-1)*12:i*12])+(i-1)*12
                if not len(indices):continue
                active_sites.append(i)
                planned_corners[i]=np.vstack((arc_corners[indices[0]][[0,2]],arc_corners[indices[-1]][[1,3]]))
        choices={i:project_to_disks(client.position,planned_corners[i]) for i in active_sites}
        action=None
        if committed in known:
            action=('source',committed)
        elif not known or route_mode=='scan_first' and choices:
            if not choices:raise RuntimeError('No pending action can resolve channels')
            i=min(choices,key=lambda i:(math.dist(client.position,choices[i]),i));action=('site',i)
        elif route_mode=='v4':
            end_cost=[min(math.dist(d['center'],project_to_disks(d['center'],corners[i])) for i in active_sites)
                      for c,d in sorted(known.items())] if active_sites else None
            c=first_route_target(np.array(client.position),known,end_costs=end_cost);action=('source',c)
        elif route_mode=='near_joint':
            candidates=[(math.dist(client.position,d['center']),0,c) for c,d in known.items()]
            candidates +=[(math.dist(client.position,p),1,i) for i,p in choices.items()]
            _,kind,index=min(candidates);action=('site' if kind else 'source',index)
        else:
            labels=[('source',c) for c in sorted(known)]+[('site',i) for i in active_sites]
            def estimated(d):
                if estimate=='centroid' and d['polygon'] is not None and len(d['polygon'])>=3:
                    p=d['polygon'];q=np.roll(p,-1,axis=0);cross=p[:,0]*q[:,1]-p[:,1]*q[:,0]
                    if abs(cross.sum())>1e-10:return np.sum((p+q)*cross[:,None],axis=0)/(3*cross.sum())
                return d['center']
            planned_sites=[project_to_disks(planning_radius*np.array([math.cos(rotation+(i-1)*math.pi/3),math.sin(rotation+(i-1)*math.pi/3)]),planned_corners[i])
                           if planning_radius else choices[i] for i in active_sites]
            points=[estimated(known[c]) for c in sorted(known)]+planned_sites
            bonus=[0.]*len(known)+[site_bonus]*len(active_sites)
            if route_mode=='sweep':
                angles=[math.atan2(p[1],p[0]) for p in points]
                def sweep_order(start,direction):
                    keys=[(direction*(a-start)-(math.radians(sweep_advance) if labels[i][0]=='site' else 0))%(2*math.pi) for i,a in enumerate(angles)]
                    return sorted(range(len(points)),key=lambda i:(keys[i],i))
                if sweep_start is None:
                    candidates=[]
                    for start in np.arange(0,2*math.pi,math.pi/12):
                        for direction in (-1,1):
                            order=sweep_order(start,direction);path=[client.position]+[points[i] for i in order]
                            cost=sum(math.dist(a,b) for a,b in zip(path,path[1:]));candidates.append((cost,start,direction))
                    _,sweep_start,sweep_direction=min(candidates)
                order=sweep_order(sweep_start,sweep_direction);path=[client.position]+[points[i] for i in order]
                cost=sum(math.dist(a,b) for a,b in zip(path,path[1:]))
            else:order,cost=open_tour(client.position,points,bonus)
            for _ in range(site_passes):
                for k,idx in enumerate(order):
                    if labels[idx][0]!='site':continue
                    before=client.position if k==0 else points[order[k-1]]
                    points[idx]=project_to_disks(before,planned_corners[labels[idx][1]]) if k==len(order)-1 else site_on_route(before,points[order[k+1]],planned_corners[labels[idx][1]])
                order,cost=open_tour(client.position,points,bonus)
            for idx,(kind,c) in enumerate(labels):
                if kind=='site':choices[c]=points[idx]
            action=labels[order[0]]
            routing.append({'sequence_before':len(client.rows),'labels':labels,'order':order,'estimated_distance_m':cost})
        kind,index=action
        if kind=='site':
            if not arc_scan:unused.remove(index)
            scan(choices[index],index);continue
        c=index;d=known[c]
        if commit:committed=c
        if d['radius']<=20-1e-6:clear(c);share();continue
        if d['radius']<=trial_radius and trials[c]<trial_limit:
            clear(c,True);share();continue
        prior=d['radius'];poly=d['polygon'];target=d['center'].copy();steps=iterations[c]
        if prior>=1000-1e-6:raise RuntimeError('Reception bound violated')
        if offset and steps%2==0:
            distances=np.sum((poly[:,None,:]-poly[None,:,:])**2,axis=2);ia,ib=np.unravel_index(np.argmax(distances),distances.shape)
            u=poly[ia]-poly[ib];u=u/np.linalg.norm(u)
            if np.dot(u,np.array(client.position)-target)<0:u=-u
            v=np.array([-u[1],u[0]])
            targets=[target+advance*prior*u+sign*offset*prior*v for sign in (-1,1)]
            targets=[p for p in targets if np.max(np.linalg.norm(poly-p,axis=1))<1000-1e-6]
            if targets:target=min(targets,key=lambda p:math.dist(client.position,p))
        bound=float(np.max(np.linalg.norm(poly-target,axis=1)))
        reply=observe(c,target,'localization');iterations[c]+=1
        obs[c][-1].update(prior_radius_m=prior,max_vertex_distance_m=bound,conditional_probe=False)
        if reply['measure_result']=='no_signal' or iterations[c]>12:raise RuntimeError('Guaranteed localization failed')
        if share_during:share()
    if not 10<=len(cleared)<=16:raise RuntimeError('Source count outside Q3 bounds')
    return {'strategy':'joint_tour','cleared_count':len(cleared),'cleared_sources':cleared,
            'cleared_channels':sorted(x['channel'] for x in cleared),'observations':{str(c):obs[c] for c in obs},
            'negative_observations':{str(c):negative[c] for c in sorted(absent)},'scan_visits':visits,
            'source_upper_bound_stop':len(cleared)==16,'count_inferred_absent_channels':sorted(remaining) if len(cleared)==16 else [],
            'average_virtual_seconds_per_cleared_source':client.virtual/len(cleared),'route_decisions':routing,'clear_attempts':clear_attempts}


VERSION = 'q3_joint_search_clear_route_v5'
SELECTED_PARAMETERS = {'route_mode': 'joint', 'probe': 250, 'share_at_search': True, 'share_during': False, 'share_ratio': 0.7, 'offset': 0.1, 'advance': 0.25, 'unknown_scan': False, 'rotation': 0.0, 'exact_positive': False, 'info_points': False, 'arc_scan': 0, 'estimate': 'circle', 'trial_radius': 40, 'trial_limit': 12, 'probe_count': 1, 'site_passes': 1, 'site_bonus': 0.0, 'planning_radius': 1500, 'commit': False, 'sweep_advance': 0.0}

def solve_optimized_v5(client, progress=None):
    result = solve(client, progress=progress, **SELECTED_PARAMETERS)
    result.update(version=VERSION, parameters=SELECTED_PARAMETERS.copy())
    return result
