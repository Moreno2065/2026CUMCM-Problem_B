"""Q4 local prototypes. Decisions use public responses and known problem bounds only.

移植说明（absorbed 版）：本文件与源
Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\strategy_v4.py 逐行一致，
**唯一差异是第 4-12 行的 import 语句**（裸顶层 import → 显式包内相对 import）。
solve() 的签名、默认参数、全部函数体、常量、数值表达式、异常文本与返回字典键
均未改动。相对 import 的必要性与 numba/coverage 命名冲突的处置见 MANIFEST.md。
"""
import math
import numpy as np
from .bridge_v4 import (ERROR,DirectionBelief,bearing_halfplanes,clip_polygon,exclude_disk,
    initial_polygon,minimum_circle,open_tour,optical_cover,stations_and_triangles)
from .bridge_v4 import probe_pair
from .conditional import conditional_pair
from .coverage import triangle_certificate,directional_cover
from .negative_regions import refine as refine_negative
from .tour_utils import area_centroid,insert_sources
from .search_nets import certified_layout,certify_points
from .ordered_tour import ordered_tour

def solve(client,route='sequential',share=False,directional=False,angle_bin=4.,trial_radius=40.,
          probe_offset=.25,radio_limit=8,search_first=False,source_bias=0.,crossbar=False,crossbar_offset=.2,crossbar_after_dark=False,
          station_layout='8_16',station_inner=990.,crossbar_fraction=.5,conditional_range=False,
          route_mode='joint',route_estimate=.5,opportunistic=False,drop_sites=False,share_ratio=.7,negative_regions=False,
          crossbar_reference='first',stop_when_found16=False,scan_current_first=False,
          near_clear_distance=50.,near_clear_radius=20.,station_spec=None,
          opportunistic_distance=650.,opportunistic_candidates=3,exact_insert=False,
          cumulative_points=0.,cumulative_cap=2,initial_rotation_steps=0,initial_reflection=False,
          initial_rotation_span=math.pi/2):
    if station_spec is None:sites,triangles=stations_and_triangles(station_inner,layout=station_layout)
    else:sites,triangles,_=certified_layout(tuple(station_spec));sites=sites.copy()
    unused=set(range(1,len(sites)));initial_station_count=len(sites)
    unknown=set(range(1,21));known={};cleared=[];absent=set();observations={c:[] for c in range(1,21)}
    negatives={c:set() for c in range(1,21)};visits=[];attempts=[];fallbacks=[];crossbar_records=[];retired=set();coverage_changes=[];negative_region_records=[]
    sweep_start=None;sweep_direction=1;discovery_stops=[];rotation_record=None
    backbone=[i+1 for i in open_tour([0.,0.],sites[1:])] if route_mode=='backbone' else []
    def stop_unknown_if_full():
        if stop_when_found16 and unknown and len(cleared)+len(known)==16:
            discovery_stops.append({'sequence':len(client.rows),'cleared_channels':[s['channel'] for s in cleared],
                'known_channels':sorted(known),'stopped_unknown_channels':sorted(unknown)})
            absent.update(unknown);unknown.clear()
    def update(d,p):
        if not len(p):raise RuntimeError('Empty position region')
        if negative_regions and len(negatives[d['channel']])>=3:
            prior=p.copy();p,meta=refine_negative(p,sites[sorted(negatives[d['channel']])],negative_regions,details=True)
            negative_region_records.append({'channel':d['channel'],'sequence':len(client.rows),'prior_vertices':prior.tolist(),'posterior_vertices':p.tolist(),**meta})
        d['polygon']=p;circ=minimum_circle(p);d['center']=circ['center'];d['radius']=circ['radius']
    def observe(c,pos,kind,site=None):
        pos=np.asarray(pos,dtype=float);d=known.get(c);prior=None if d is None else d['polygon']
        guaranteed=prior is not None and float(np.max(np.linalg.norm(prior-pos,axis=1)))<=1000-1e-6
        reply=client.act('/measure',pos,c)
        rec={'sequence':len(client.rows),'position':pos.tolist(),'kind':kind,'response':reply.copy(),
             'within_min_reception_radius':bool(guaranteed),'prior_vertices':None if prior is None else prior.tolist()}
        observations[c].append(rec)
        if reply['measure_result']=='no_signal':
            if site is not None:negatives[c].add(site)
            if d is not None:
                d['last_negative']=True
                if guaranteed and directional:
                    d['negative_points'].append(pos.tolist())
                    if d['belief'] is None:d['belief']=DirectionBelief(d['polygon'],d['positive_points'],d['negative_points'],angle_bin)
                    else:d['belief'].update_sign(pos,False)
                    update(d,d['belief'].polygon())
            elif len(negatives[c])==len(sites)-len(retired):absent.add(c);unknown.remove(c)
        else:
            if d is None:
                d={'polygon':None,'center':pos,'radius':5.,'positive_points':[],'negative_points':[],'belief':None,
                   'radios':0,'last_negative':False,'last_measure':pos,'trial_count':0,'stalled':0,'channel':c};known[c]=d;unknown.remove(c)
            d['positive_points'].append(pos.tolist());d['last_negative']=False
            if reply['measure_result']=='near':
                d['polygon']=None;d['center']=pos;d['radius']=5.
            else:
                A,b=bearing_halfplanes(pos,reply['svd_deg'],ERROR)
                p=initial_polygon(pos,reply['svd_deg']) if d['polygon'] is None else clip_polygon(d['polygon'],A,b)
                if d['belief'] is not None:
                    d['belief'].restrict(p);d['belief'].update_sign(pos,True);p=d['belief'].polygon()
                update(d,p)
            d['last_measure']=pos
        if c in known:
            d=known[c];d['last_measure']=pos;rec.update(posterior_vertices=None if d['polygon'] is None else d['polygon'].tolist(),
                circle_center=d['center'].tolist(),circle_radius_m=d['radius'],orientation_bins=0 if d['belief'] is None else len(d['belief'].parts))
        return reply
    def sharing():
        if not share:return
        pos=np.asarray(client.position)
        for c in sorted(known):
            d=known[c]
            if d['polygon'] is None or d['radius']<=20 or math.dist(pos,d['last_measure'])<120 or math.dist(pos,d['center'])>1500:continue
            v=d['center']-pos
            if np.linalg.norm(v)<1e-7:continue
            A,b=bearing_halfplanes(pos,math.degrees(math.atan2(v[1],v[0])),ERROR);p=clip_polygon(d['polygon'],A,b)
            if len(p) and minimum_circle(p)['radius']<share_ratio*d['radius']:observe(c,pos,'shared_bearing')
    def scan(i):
        visits.append(i)
        channels=sorted(unknown)
        if scan_current_first and client.channel in unknown:
            j=channels.index(client.channel);channels=channels[j:]+channels[:j]
        for c in channels:
            if c not in unknown:continue
            observe(c,sites[i],'search',i);stop_unknown_if_full()
        sharing()
    def opportunistic_scan():
        if not opportunistic or not unknown or not unused or len(cleared)==16:return
        pos=np.asarray(client.position);indices=sorted(unused,key=lambda i:math.dist(pos,sites[i]))
        # Only test nearby pending sites; exact continuous coverage remains the gate.
        for i in indices[:opportunistic_candidates]:
            if math.dist(pos,sites[i])>opportunistic_distance:continue
            candidate=sites.copy();candidate[i]=pos;active=sorted(set(range(len(sites)))-retired)
            cert=certify_points(tuple(map(tuple,candidate[active]))) if opportunistic=='union' else triangle_certificate(candidate[active])
            if not cert['passed']:continue
            before=sites[i].copy();sites[i]=pos;unused.remove(i)
            rec={'sequence_before':len(client.rows),'replacement_index':i,'old_point':before.tolist(),'new_point':pos.tolist(),'certificate':cert}
            if drop_sites:
                for j in sorted(unused):
                    active=sorted(set(range(len(sites)))-retired-{j})
                    other=certify_points(tuple(map(tuple,sites[active]))) if opportunistic=='union' else triangle_certificate(sites[active])
                    if other['passed']:
                        retired.add(j);unused.remove(j);rec['retired_index']=j;rec['retirement_certificate']=other;break
            coverage_changes.append(rec);scan(i);return
    def cumulative_scan():
        nonlocal sites
        if not cumulative_points or not unknown or not unused or len(sites)-initial_station_count>=12:return
        pos=np.asarray(client.position)
        if not 600<=np.linalg.norm(pos)<=1450:return
        if any(math.dist(pos,sites[i])<100 for i in visits):return
        pool=sorted((i for i in unused if np.linalg.norm(sites[i])<1500 and math.dist(pos,sites[i])<850),key=lambda i:math.dist(pos,sites[i]))
        if not pool:return
        active=set(range(len(sites)))-retired;augmented=np.vstack((sites,pos));new_id=len(sites)
        decision=None
        for i in pool[:2]:
            ids=sorted(active-{i});base=certify_points(tuple(map(tuple,sites[ids])))
            after=certify_points(tuple(map(tuple,augmented[ids+[new_id]])))
            if after['passed']:
                decision={'drop':i,'fraction':1.,'certificate':after};break
            missing=base.get('missing_area_m2');remaining=after.get('missing_area_m2')
            if missing is None or remaining is None or missing<=0:continue
            fraction=1-remaining/missing
            overhead=len(sites)-len(retired)-initial_station_count
            if fraction>=cumulative_points and overhead<cumulative_cap:
                decision={'drop':None,'fraction':fraction,'deferred_site':i,'before_missing_m2':missing,'after_missing_m2':remaining};break
        if decision is None:return
        sites=augmented
        rec={'mode':'cumulative','sequence_before':len(client.rows),'added_index':new_id,'new_point':pos.tolist(),
             'decision':decision,'retired_indices':[]}
        if decision['drop'] is not None:
            retired.add(decision['drop']);unused.remove(decision['drop']);rec['retired_indices'].append(decision['drop'])
        # Every actual retirement receives a continuous certificate using only
        # already measured points and retained future search points.
        for i in pool:
            if i not in unused:continue
            ids=sorted(set(range(len(sites)))-retired-{i});proof=certify_points(tuple(map(tuple,sites[ids])))
            if proof['passed']:
                retired.add(i);unused.remove(i);rec['retired_indices'].append(i)
        rec['certificate']=certify_points(tuple(map(tuple,sites[sorted(set(range(len(sites)))-retired)])))
        if not rec['certificate']['passed']:raise RuntimeError('Cumulative coverage update failed')
        coverage_changes.append(rec);scan(new_id)
    def clear_at(c,point,kind,certificate=None):
        d=known[c];prior=d['polygon'];reply=client.act('/clear',point,c)
        bound=5. if prior is None else float(np.max(np.linalg.norm(prior-point,axis=1)))
        rec={'sequence':len(client.rows),'channel':c,'position':list(point),'kind':kind,'prior_bound_m':bound,
             'prior_vertices':None if prior is None else prior.tolist(),'response':reply.copy(),'certificate':certificate}
        attempts.append(rec)
        if reply['clear_result']=='success':
            cleared.append({'channel':c,'point':list(point),'bound_source':'prior_geometry' if bound<=20 else 'successful_clear_response',
                'prior_bound_m':bound,'virtual_after_s':client.virtual});known.pop(c);opportunistic_scan();cumulative_scan();return True
        if bound<=20-1e-6:raise RuntimeError('Certified optical clear failed')
        p=exclude_disk(prior,point)
        if d['belief'] is not None:
            d['belief'].restrict(p);p=d['belief'].polygon()
        update(d,p);rec['posterior_vertices']=p.tolist();return False
    def optical_finish(c):
        d=known[c];poly=d['polygon'].copy();points,cert=optical_cover(poly,client.position)
        fallbacks.append({'channel':c,'sequence_before':len(client.rows),'prior_vertices':poly.tolist(),'certificate':cert,'point_count':len(points)})
        for p in points:
            if clear_at(c,p,'grid_fallback',cert):return
        raise RuntimeError('Exhausted proven optical cover')
    def crossbar_plan(c):
        d=known[c];refs=[o for o in observations[c] if o['response']['measure_result']=='direction']
        if crossbar_reference=='first':refs=refs[:1]
        elif crossbar_reference=='latest':refs=refs[-1:]
        options=[]
        for ref in refs:
            try:
                fraction=crossbar_fraction
                if fraction=='centroid':
                    a=math.radians(ref['response']['svd_deg']);u=np.array([math.cos(a),math.sin(a)]);s=np.asarray(ref['position']);proj=(d['polygon']-s)@u
                    fraction=float(np.clip(((area_centroid(d['polygon'])-s)@u-proj.min())/max(np.ptp(proj),1e-9),.05,.95))
                if conditional_range:points,cert=conditional_pair(d['polygon'],ref['position'],ref['response']['svd_deg'],client.position,crossbar_offset,fraction)
                else:points,cert=probe_pair(d['polygon'],ref['position'],ref['response']['svd_deg'],client.position,crossbar_offset)
            except RuntimeError:
                continue
            score=math.dist(client.position,points[0])+.25*math.dist(points[0],points[1])
            options.append((score,points,cert))
        if not options:raise RuntimeError('No certified crossbar reference')
        _,points,cert=min(options,key=lambda x:x[0]);return points,cert
    def local_step(c):
        d=known[c]
        if d['radius']<=20-1e-6:
            clear_at(c,d['center'],'certified');sharing();return
        if trial_radius and d['radius']<=trial_radius and d['trial_count']<12:
            p=d['polygon'];vertex=min(p,key=lambda x:math.dist(client.position,x));v=d['center']-vertex
            target=vertex+v*min(1.,18/max(np.linalg.norm(v),1e-12));d['trial_count']+=1
            clear_at(c,target,'early_optical');sharing();return
        if d['radios']>=radio_limit or (not directional and not crossbar and d['last_negative']) or d['stalled']>=3:
            optical_finish(c);sharing();return
        prior=d['radius'];poly=d['polygon'];target=d['center'].copy()
        if crossbar and (not crossbar_after_dark or d['last_negative']):
            points,cert=crossbar_plan(c)
            rec={'channel':c,'sequence_before':len(client.rows),'prior_vertices':poly.tolist(),'points':[p.tolist() for p in points],'certificate':cert,'outcomes':[]}
            for p in points:
                reply=observe(c,p,'crossbar');d['radios']+=1;rec['outcomes'].append(reply['measure_result'])
                if reply['measure_result']!='no_signal':break
            if rec['outcomes']==['no_signal','no_signal']:
                p=clip_polygon(d['polygon'],[cert['cut_normal']],[cert['cut_rhs']])
                if d['belief'] is not None:d['belief'].restrict(p);p=d['belief'].polygon()
                update(d,p);rec['posterior_vertices']=p.tolist()
            crossbar_records.append(rec)
            d['stalled']=d['stalled']+1 if d['radius']>.95*prior else 0
            return
        if d['last_negative'] and directional:
            delta=poly[:,None,:]-poly[None,:,:];i,j=np.unravel_index(np.argmax(np.sum(delta**2,axis=2)),delta.shape[:2]);u=poly[i]-poly[j];u/=max(np.linalg.norm(u),1e-12);v=np.array([-u[1],u[0]])
            if np.dot(u,np.asarray(d['positive_points'][-1])-target)<0:u=-u
            target=target+.35*prior*u+((-1)**d['radios'])*probe_offset*prior*v
        observe(c,target,'localization');d['radios']+=1
        d['stalled']=d['stalled']+1 if d['radius']>.95*prior else 0
    scan(0)
    if initial_rotation_steps and known and unknown and route_mode=='backbone':
        # The first observation is at the origin. Rigidly rotating or reflecting
        # the unvisited net preserves its continuous disk coverage certificate.
        original_sites=sites.copy();centres=[d['center'].copy() for c,d in sorted(known.items())];options=[]
        for reflection in ([1.,-1.] if initial_reflection else [1.]):
            for step in range(initial_rotation_steps):
                angle=step*initial_rotation_span/initial_rotation_steps
                transform=np.array([[math.cos(angle),-reflection*math.sin(angle)],[math.sin(angle),reflection*math.cos(angle)]])
                transformed=original_sites@transform.T
                points=centres+[transformed[i] for i in backbone]
                if len(centres)<=10:_,score=ordered_tour(client.position,points,len(centres))
                else:
                    route_order=insert_sources(client.position,points,list(range(len(centres),len(points))),list(range(len(centres))))
                    route_points=[client.position]+[points[j] for j in route_order];score=sum(math.dist(a,b) for a,b in zip(route_points,route_points[1:]))
                options.append((score,reflection,step,angle,transformed))
        score,reflection,step,angle,sites=min(options,key=lambda x:(x[0],x[1]!=1,x[2]))
        rotation_record={'sequence':len(client.rows),'angle_rad':angle,'reflection':reflection,'known_channels':sorted(known),
                         'known_centres':[p.tolist() for p in centres],'original_stations':original_sites.tolist(),
                         'station_order':backbone,'predicted_route_m':score,'candidate_count':len(options),'unrotated_route_m':options[0][0]}
    while unknown or known:
        if len(client.rows)>3500:raise RuntimeError('Local development action guard exceeded')
        if len(cleared)==16:break
        stop_unknown_if_full()
        ready=[c for c,d in known.items() if d['radius']<=near_clear_radius and math.dist(client.position,d['center'])<=near_clear_distance]
        if ready:local_step(min(ready,key=lambda c:math.dist(client.position,known[c]['center'])));continue
        active_sites=sorted(unused) if unknown else []
        if not known or (search_first and active_sites):
            if not active_sites:raise RuntimeError('No action resolves remaining channels')
            pool=[i for i in active_sites if np.linalg.norm(sites[i])>1500] if route_mode=='outer_first' else active_sites
            if not pool:pool=active_sites
            order=open_tour(client.position,sites[pool])
            i=next(i for i in backbone if i in unused) if route_mode=='backbone' else pool[order[0]] if route=='joint' else min(pool,key=lambda i:math.dist(client.position,sites[i]))
            unused.remove(i);scan(i);continue
        if route=='sequential':
            c=min(known,key=lambda c:math.dist(client.position,known[c]['center']));local_step(c)
        else:
            labels=[('source',c) for c in sorted(known)]+[('site',i) for i in active_sites]
            def estimate(c):
                d=known[c]
                if route_estimate==.5 or d['polygon'] is None:return d['center']
                if route_estimate=='centroid':return area_centroid(d['polygon'])
                if route_estimate=='action':
                    if d['radius']<=20 or d['radios']>=radio_limit:return d['center']
                    if trial_radius and d['radius']<=trial_radius:
                        vertex=min(d['polygon'],key=lambda x:math.dist(client.position,x));v=d['center']-vertex
                        return vertex+v*min(1.,18/max(np.linalg.norm(v),1e-12))
                    return crossbar_plan(c)[0][0]
                ref=next(o for o in observations[c] if o['response']['measure_result']=='direction');s=np.asarray(ref['position']);a=math.radians(ref['response']['svd_deg']);u=np.array([math.cos(a),math.sin(a)]);p=d['polygon'];projection=(p-s)@u
                return s+(float(projection.min())+route_estimate*float(np.ptp(projection)))*u
            points=[estimate(c) for c in sorted(known)]+[sites[i] for i in active_sites]
            if route_mode=='backbone':
                site_map={i:j for j,(kind,i) in enumerate(labels) if kind=='site'}
                source_indices=[j for j,(kind,_) in enumerate(labels) if kind=='source']
                site_indices=[site_map[i] for i in backbone if i in site_map]
                if exact_insert:
                    permutation=source_indices+site_indices
                    best,_=ordered_tour(client.position,[points[j] for j in permutation],len(source_indices))
                    order=[permutation[j] for j in best]
                else:order=insert_sources(client.position,points,site_indices,source_indices)
            elif route_mode=='sweep':
                angles=[math.atan2(p[1],p[0]) for p in points]
                def sweep(a,direction):return sorted(range(len(points)),key=lambda j:(direction*(angles[j]-a))%(2*math.pi))
                if sweep_start is None:
                    options=[]
                    for a in np.arange(0,2*math.pi,math.pi/8):
                        for sign in (-1,1):
                            order=sweep(a,sign);path=[client.position]+[points[j] for j in order];cost=sum(math.dist(x,y) for x,y in zip(path,path[1:]));options.append((cost,a,sign))
                    _,sweep_start,sweep_direction=min(options)
                order=sweep(sweep_start,sweep_direction)
            elif route_mode=='nearest':order=sorted(range(len(points)),key=lambda j:math.dist(client.position,points[j]))
            elif route_mode=='outer_first' and active_sites:
                outer=[j for j,(k,i) in enumerate(labels) if k=='site' and np.linalg.norm(sites[i])>1500]
                order=sorted(outer,key=lambda j:math.dist(client.position,points[j])) if outer else open_tour(client.position,points)
            else:order=open_tour(client.position,points)
            kind,i=labels[order[0]]
            if source_bias:
                near=min(known,key=lambda c:math.dist(client.position,known[c]['center']))
                if math.dist(client.position,known[near]['center'])<=source_bias:kind,i='source',near
            if kind=='site':unused.remove(i);scan(i)
            else:local_step(i)
    if not 10<=len(cleared)<=16:raise RuntimeError('Q4 cleared count outside source-count bounds')
    return {'strategy':'q4_local_prototype','cleared_sources':cleared,'cleared_count':len(cleared),'absent_channels':sorted(absent),
        'count_upper_bound_stop':len(cleared)==16,'remaining_unknown_channels':sorted(unknown),'observations':observations,
        'scan_visits':visits,'stations':sites.tolist(),'coverage_triangles':triangles,'clear_attempts':attempts,'optical_fallbacks':fallbacks,
        'all_station_no_signal_channels':{c:sorted(negatives[c]) for c in absent},'crossbar_records':crossbar_records,'virtual_time_s':client.virtual,
        'required_station_indices':sorted(set(range(len(sites)))-retired),'coverage_changes':coverage_changes,'negative_region_records':negative_region_records,
        'discovery_upper_bound_stops':discovery_stops,'station_spec':station_spec,'initial_rotation':rotation_record}
