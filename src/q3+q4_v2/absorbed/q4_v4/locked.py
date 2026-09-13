"""Q4 正式采用版本的锁定参数与入口（吸收件）。

来源：D:\\CUMCM2026\\src\\Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\results\\selection_lock.json
  - VERSION           <- selection_lock.json['version']          = 'q4_21station_exact_route_v4'
  - SELECTED_NAME     <- selection_lock.json['selected_name']    = 'quarter12'
  - LOCKED_PARAMETERS <- selection_lock.json['selected_parameters']（36 项，逐字段一致，
                         含 station_spec=[8,12,995,1864,0]；注意任务描述里写的 “25 项” 有误）

同目录 results/selection_lock.json 是本锁文件的**字节级副本**（已用 SHA-256 核对：
62a9e692f58ad7251fab6665a5ef5582cdc0df331401442a5ddec038c0f898e7）。
本文件把参数内联为 Python 字面量，使 locked.solve_locked 不依赖运行期读 JSON。

用法：
    from absorbed.q4_v4 import locked
    result = locked.solve_locked(client)   # 等价于 strategy_v4.solve(client, **LOCKED_PARAMETERS)
"""
import math

from . import strategy_v4

VERSION = 'q4_21station_exact_route_v4'
SELECTED_NAME = 'quarter12'

# 逐字段抄自 results/selection_lock.json 的 selected_parameters（键序与源文件一致）。
LOCKED_PARAMETERS = {
    'route': 'joint',
    'share': True,
    'directional': False,
    'angle_bin': 4.0,
    'trial_radius': 40.0,
    'probe_offset': 0.25,
    'radio_limit': 12,
    'search_first': False,
    'source_bias': 0.0,
    'crossbar': True,
    'crossbar_offset': 0.03,
    'crossbar_after_dark': False,
    'station_layout': '8_16',
    'station_inner': 990.0,
    'crossbar_fraction': 0.25,
    'conditional_range': True,
    'route_mode': 'backbone',
    'route_estimate': 0.5,
    'opportunistic': False,
    'drop_sites': False,
    'share_ratio': 0.7,
    'negative_regions': 'disk',
    'crossbar_reference': 'latest',
    'stop_when_found16': True,
    'scan_current_first': True,
    'near_clear_distance': 50.0,
    'near_clear_radius': 20.0,
    'station_spec': [8, 12, 995, 1864, 0],
    'opportunistic_distance': 650.0,
    'opportunistic_candidates': 3,
    'exact_insert': True,
    'cumulative_points': 0.0,
    'cumulative_cap': 2,
    'initial_rotation_steps': 12,
    'initial_reflection': False,
    'initial_rotation_span': 1.5707963267948966,
}


def parity_notes():
    """返回锁文件里与求解无关但需随版本追溯的元信息（只读，不参与算法）。"""
    return {
        'locked_at_utc': '2026-09-12T08:41:25.837296+00:00',
        'selection_policy': ('All 204 seen uniform cases; choose lowest pooled time among '
                             'candidates improving both whole group and ten-source group by at '
                             'least 1% versus v3. All 355 seen non-uniform cases are reliability checks.'),
        'source_runtime': {'python': '3.13.7', 'numpy': '2.4.6', 'scipy': '1.17.1',
                           'shapely': '2.1.2', 'numba': '0.66.0'},
        'claim_scope': ('In-memory constructed uniform scenes; official distribution unconfirmed. '
                        'All source counts remain hidden online. No post-validation retuning.'),
        'initial_rotation_span_is_half_pi': LOCKED_PARAMETERS['initial_rotation_span'] == math.pi / 2,
    }


def solve_locked(client):
    """按锁定参数运行 Q4 正式 solver，返回 strategy_v4.solve 的原始结果字典。"""
    return strategy_v4.solve(client, **LOCKED_PARAMETERS)
