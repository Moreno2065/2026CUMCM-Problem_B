# absorbed/q3_v5 — 源：D:\CUMCM2026\src\Q3_Q4_V3\code\practice_all_sources.py (169 行)
# 改动：① 删除 main()（源 121-165 行）与 "if __name__ == '__main__': main()"（源 168-169 行），
#       以及只为 main() 服务的 import（pathlib.Path、argparse、datetime、hashlib、json、sys、time、
#       PracticeClient/ROOT/URL）；
#       ② 顶层 "from practice_single_source import ..." 改为显式包内相对 import，并去掉 PracticeClient/ROOT/URL。
# 理由：main() 会构造离线桩 PracticeClient（只 raise）并把结果写进源包 results/ 目录，不属于 solver 闭包。
#       其余逐行未改：VERSION、STRATEGIES、coverage_sites / prepare_detection / clear_detected / solve_all 全保留。
#       本模块被 practice_all_sources_fast 以 coverage_sites 引用，故必须随包 vendor。详见 MANIFEST.md。
"""Q3 omnidirectional all-source prototype; executes only in human-confirmed practice."""
import math
import numpy as np
from .practice_single_source import (ERROR, search_points,
                                   bearing_halfplanes, clip_polygon, minimum_circle,
                                   outer_prior, plan_second_point, to_global)

VERSION = 'q3_seven_sites_batch_greedy_v1'
STRATEGIES = ('grid_immediate', 'seven_batch_fixed', 'seven_batch_greedy')


def coverage_sites(strategy):
    if strategy == 'grid_immediate':
        return [list(p) for p in search_points()]
    rho = 900 * math.sqrt(3)
    return [[0., 0.], [rho, 0.], [rho/2, 1350.], [-rho/2, 1350.],
            [-rho, 0.], [-rho/2, -1350.], [rho/2, -1350.]]


def prepare_detection(station, response):
    d = {'station': list(station), 'first_response': response}
    if response['measure_result'] == 'direction':
        theta = response['svd_deg']
        d['second_points'] = plan_second_point(ERROR, station, theta,
                                               include_certificate=False)['candidate_global_points']
    return d


def clear_detected(client, channel, detection, choose_nearest):
    station = detection['station']; first = detection['first_response']; history = []
    if first['measure_result'] == 'near':
        target = np.asarray(station)
        history.append({'near': True, 'position': list(station), 'bound_m': 5.})
    else:
        theta = first['svd_deg']
        poly = np.array([to_global(p, station, theta) for p in outer_prior(ERROR)])
        choices = detection['second_points']
        target = np.asarray(min(choices, key=lambda p: math.dist(client.position, p))
                            if choose_nearest else choices[0])
        for step in range(10):
            position = target.copy()
            response = client.act('/measure', position, channel)
            kind = response['measure_result']
            if kind == 'near':
                history.append({'near': True, 'position': position.tolist(), 'bound_m': 5.})
                break
            if kind != 'direction':
                raise RuntimeError(f'Channel {channel}: signal lost during guaranteed Q3 localization')
            A, b = bearing_halfplanes(position, response['svd_deg'], ERROR)
            poly = clip_polygon(poly, A, b)
            if not len(poly):
                raise RuntimeError(f'Channel {channel}: inconsistent bearings, empty posterior')
            circle = minimum_circle(poly); target = circle['center']
            history.append({'position': position.tolist(), 'bearing_deg': response['svd_deg'],
                            'vertices': poly.tolist(), 'circle_center': target.tolist(),
                            'bound_m': circle['radius']})
            if circle['radius'] <= 20 - 1e-6:
                break
        else:
            raise RuntimeError(f'Channel {channel}: localization budget exhausted')
    response = client.act('/clear', target, channel)
    if response['clear_result'] != 'success':
        raise RuntimeError(f'Channel {channel}: clear failed; preserve observations for review')
    return {'channel': channel, 'first_station': station, 'first_response': first,
            'clear_point': target.tolist(), 'localization_history': history,
            'virtual_time_after_clear_s': client.virtual}


def solve_all(client, strategy='seven_batch_greedy', progress=None):
    if strategy not in STRATEGIES:
        raise ValueError('Unknown Q3 strategy')
    sites = coverage_sites(strategy); remaining = list(range(len(sites)))
    unresolved = set(range(1, 21)); negative = {c: [] for c in unresolved}
    cleared = []; visited = []
    while remaining and unresolved:
        index = min(remaining, key=lambda i: (math.dist(client.position, sites[i]), i)) \
            if strategy == 'seven_batch_greedy' else remaining[0]
        remaining.remove(index); station = sites[index]; visited.append(index); pending = {}
        # Scan at this exact site even if an immediate baseline clear leaves it.
        for channel in sorted(unresolved):
            response = client.act('/measure', station, channel)
            kind = response['measure_result']
            if kind == 'no_signal':
                negative[channel].append(index)
                continue
            if kind not in ('near', 'direction'):
                raise RuntimeError('Unknown scan response')
            detection = prepare_detection(station, response)
            if strategy == 'grid_immediate':
                result = clear_detected(client, channel, detection, False)
                cleared.append(result); unresolved.remove(channel)
            else:
                pending[channel] = detection
        while pending:
            def priority(c):
                d = pending[c]
                points = d.get('second_points', [d['station']])
                return min(math.dist(client.position, p) for p in points), c
            channel = min(pending, key=priority) if strategy == 'seven_batch_greedy' else min(pending)
            result = clear_detected(client, channel, pending.pop(channel), strategy == 'seven_batch_greedy')
            cleared.append(result); unresolved.remove(channel)
            if progress:
                progress(f'已清除 {len(cleared)} 个源；最近频道 {channel}；虚拟时间 {client.virtual:.2f} 秒')
        if len(cleared) > 16:
            raise RuntimeError('More than 16 sources: Q3 contract mismatch')
    # Never infer absence from a single no_signal or from clearing ten sources.
    certified = all(set(negative[c]) == set(range(len(sites))) for c in unresolved)
    if not certified or not 10 <= len(cleared) <= 16:
        raise RuntimeError('All-source certificate or Q3 count range failed')
    return {'version': VERSION, 'strategy': strategy, 'cleared_count': len(cleared),
            'cleared_channels': sorted(r['channel'] for r in cleared), 'cleared_sources': cleared,
            'sites': sites, 'visited_site_indices': visited,
            'absent_channel_negative_sites': {str(c): negative[c] for c in sorted(unresolved)},
            'completion_basis': 'Each of 20 channels cleared or negative at every covering site',
            'all_sources_cleared_under_q3_model': True,
            'simulator_total_sources': None, 'observed_clearance_ratio': None,
            'average_virtual_seconds_per_cleared_source': client.virtual / len(cleared)}
