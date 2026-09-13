# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\practice_all_sources_fast.py (166 行)
# 改动：① 删除 main()（源 131-164 行）与 "if __name__=='__main__':main()"（源 166 行），以及只为
#       main() 服务的 import（pathlib.Path、argparse、datetime、hashlib、json、time、PracticeClient/ROOT/URL）；
#       ② 2 处顶层 import 改为显式包内相对 import（practice_single_source / practice_all_sources）。
# 理由：main() 会构造离线桩 PracticeClient（只 raise）并写源包 results/ 目录。除上述外逐行未改：
#       VERSION、CELL、centres/X/Y/ALL_CENTRES/nearest/CELL_CENTRES/HALFDIAG 与
#       covered_cells/initial_polygon/discovery/localize/solve_all_fast 全部保留（含 v5 未调用的部分）。
#       v5 实际使用 initial_polygon / covered_cells / CELL_CENTRES。详见 MANIFEST.md。
"""Time-oriented Q3 practice candidates: posterior centres and shared search coverage."""
import math
from functools import lru_cache
import numpy as np
from .practice_single_source import (ERROR, bearing_halfplanes,
                                   clip_polygon, minimum_circle, outer_prior, to_global)
from .practice_all_sources import coverage_sites

VERSION='q3_centres_compact_search_v2'
CELL=50.
centres=np.arange(-1800+CELL/2,1800,CELL)
X,Y=np.meshgrid(centres,centres)
ALL_CENTRES=np.column_stack((X.ravel(),Y.ravel()))
nearest=np.maximum(np.abs(ALL_CENTRES)-CELL/2,0)
CELL_CENTRES=ALL_CENTRES[np.sum(nearest**2,axis=1)<=1800**2+1e-8]
HALFDIAG=CELL/math.sqrt(2)

def covered_cells(position):
    # Entire square, including all target-disk points in it, lies in a 1000m disk.
    return np.linalg.norm(CELL_CENTRES-np.asarray(position),axis=1)+HALFDIAG<=1000-1e-6

def initial_polygon(station,theta):
    d=math.radians(ERROR);near=5*math.cos(d);slope=math.tan(d)
    # Four-vertex outer trapezoid contains the annular bearing sector.
    # Avoid dozens of almost-collinear arc vertices in the support-circle enumeration.
    p=np.array([to_global(v,station,theta) for v in
                ([near,-near*slope],[1500,-1500*slope],[1500,1500*slope],[near,near*slope])])
    # Tangent polygon is an outer approximation to the original 1800m target disk.
    a=np.arange(72)*2*math.pi/72
    return clip_polygon(p,np.column_stack((np.cos(a),np.sin(a))),np.full(72,1800.))

def discovery(station,response):
    d={'station':list(station),'first_response':response}
    if response['measure_result']=='near':
        d['target']=np.asarray(station);d['polygon']=None
    else:
        d['polygon']=initial_polygon(station,response['svd_deg'])
        if not len(d['polygon']):raise RuntimeError('Empty first-observation region')
        circle=minimum_circle(d['polygon'])
        if circle['radius']>=1000-1e-6:raise RuntimeError('Initial centre reception certificate failed')
        d['target']=circle['center']
    return d

def localize(client,channel,d):
    history=[];p=d['polygon'];last=d['first_response']
    if p is None:
        target=d['target'];history.append({'near':True,'position':target.tolist(),'bound_m':5.})
    else:
        for step in range(12):
            circle=minimum_circle(p);target=circle['center']
            if circle['radius']<=20-1e-6:
                history.append({'decision':'clear','vertices':p.tolist(),'circle_center':target.tolist(),
                                'bound_m':circle['radius']})
                break
            if circle['radius']>=1000-1e-6:raise RuntimeError('Centre not guaranteed to receive source')
            response=client.act('/measure',target,channel)
            h={'position':target.tolist(),'prior_vertices':p.tolist(),'prior_circle_radius_m':circle['radius'],
               'response':response}
            if response['measure_result']=='near':
                h.update(near=True,bound_m=5.);history.append(h);break
            if response['measure_result']!='direction':raise RuntimeError('Unexpected signal loss in centre localization')
            A,b=bearing_halfplanes(target,response['svd_deg'],ERROR);p=clip_polygon(p,A,b)
            if not len(p):raise RuntimeError('Empty posterior: inconsistent direction observations')
            post=minimum_circle(p)
            h.update(vertices=p.tolist(),circle_center=post['center'].tolist(),bound_m=post['radius'])
            history.append(h)
        else:raise RuntimeError('Centre localization iteration budget reached')
    answer=client.act('/clear',target,channel)
    if answer['clear_result']!='success':raise RuntimeError('Certified clear failed')
    return {'channel':channel,'first_station':d['station'],'first_response':d['first_response'],
            'clear_point':target.tolist(),'localization_history':history,
            'virtual_time_after_clear_s':client.virtual}

def solve_all_fast(client,strategy='centre_compact',progress=None):
    if strategy not in ('centre_seven','centre_shared','centre_compact','centre_compact_route'):raise ValueError(strategy)
    sites=coverage_sites('seven_batch_greedy')
    if strategy in ('centre_compact','centre_compact_route'):
        sites=[[0.,0.]]+[[1250*math.cos(i*math.pi/3),1250*math.sin(i*math.pi/3)] for i in range(6)]
    distances=np.linalg.norm(np.array(sites)[:,None,:]-np.array(sites)[None,:,:],axis=2)
    @lru_cache(None)
    def tail_cost(last,remaining):
        if not remaining:return 0.
        return min(distances[last,j]+tail_cost(j,tuple(k for k in remaining if k!=j)) for j in remaining)
    remaining=set(range(1,21));pending={};absent=set();cleared=[];visits=[];negative={c:[] for c in remaining}
    cover=np.zeros((21,len(CELL_CENTRES)),dtype=bool)
    masks=[covered_cells(p) for p in sites]
    if not np.all(np.logical_or.reduce(masks)):raise RuntimeError('Seven sites do not cover certificate cells')
    def scan(station,index=None):
        mask=covered_cells(station)
        found=[]
        for c in sorted(remaining-set(pending)):
            if strategy=='centre_shared' and not np.any(mask & ~cover[c]):continue
            response=client.act('/measure',station,c)
            if response['measure_result']=='no_signal':
                cover[c]|=mask;negative[c].append(list(map(float,station)))
                if np.all(cover[c]):absent.add(c);remaining.remove(c)
            elif response['measure_result'] in ('near','direction'):
                pending[c]=discovery(station,response);found.append(c)
            else:raise RuntimeError('Unknown scan response')
        visits.append({'position':list(map(float,station)),'fixed_site_index':index,'found_channels':found})
    scan(sites[0],0);unused=set(range(1,len(sites)))
    while remaining:
        if pending:
            c=min(pending,key=lambda c:(math.dist(client.position,pending[c]['target']),c))
            item=localize(client,c,pending.pop(c));cleared.append(item);remaining.remove(c)
            if progress:progress(f'已清除 {len(cleared)} 个源；最近频道 {c}；虚拟时间 {client.virtual:.2f} 秒')
            if len(cleared)>16:raise RuntimeError('Q3 source-count contract violated')
            if strategy=='centre_shared' and remaining-set(pending):scan(client.position)
        else:
            if not unused:raise RuntimeError('Search exhausted without full channel certificate')
            def rank(i):
                distance=math.dist(client.position,sites[i])
                if strategy!='centre_shared':return distance,i
                gain=sum(int(np.count_nonzero(masks[i] & ~cover[c])) for c in remaining)
                return -(gain/(distance+300.)),i
            if strategy=='centre_compact_route':
                index=min(unused,key=lambda i:(math.dist(client.position,sites[i])+tail_cost(i,tuple(sorted(unused-{i}))),i))
            else:index=min(unused,key=rank)
            unused.remove(index);scan(sites[index],index)
    if not 10<=len(cleared)<=16:raise RuntimeError('Q3 count outside 10..16')
    if set(range(1,21))!=absent|{x['channel'] for x in cleared}:raise RuntimeError('Incomplete channel partition')
    return {'version':VERSION,'strategy':strategy,'cleared_count':len(cleared),
            'cleared_channels':sorted(x['channel'] for x in cleared),'cleared_sources':cleared,
            'search_sites':sites,'scan_visits':visits,'negative_observations':{str(c):negative[c] for c in sorted(absent)},
            'coverage_certificate':{'method':'Every 50m square intersecting target disk contained in a negative-observation 1000m disk',
                                    'cell_width_m':CELL,'cell_count':len(CELL_CENTRES),'all_absent_channels_covered':all(np.all(cover[c]) for c in absent)},
            'all_sources_cleared_under_q3_model':True,'simulator_total_sources':None,'observed_clearance_ratio':None,
            'average_virtual_seconds_per_cleared_source':client.virtual/len(cleared)}
