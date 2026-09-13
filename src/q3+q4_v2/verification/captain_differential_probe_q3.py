# -*- coding: utf-8 -*-
"""captain 侧差分探针：同一确定性 mock client 驱动「源」与「移植」Q3 引擎，逐位比对。

放置于临时目录，不写入目标仓库（避免与 interface-scout 的 differential_check.py 冲突）。
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r'D:\CUMCM2026\src\q3+q4_v2')
SRC = Path(r'D:\CUMCM2026\src\Q3_Q4_V3')


def norm(obj):
    if isinstance(obj, dict):
        return {str(k): norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [norm(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return norm(obj.tolist())
    if isinstance(obj, np.generic):
        return norm(obj.item())
    if isinstance(obj, float):
        return round(obj, 9)
    return obj


class MockClient:
    """确定性世界：channels 1..12 在半径 600 m 均布，13..20 为空。"""

    def __init__(self):
        self.sources = {}
        for i in range(12):
            ang = math.radians(30.0 * i)
            self.sources[i + 1] = np.array([600.0 * math.cos(ang), 600.0 * math.sin(ang)])
        self.absent = set(range(13, 21))
        self.position = np.array([0.0, 0.0])
        self.virtual = 0.0
        self.channel = 1
        self.rows = []
        self._last_measure_channel = 1

    def act(self, path, position=None, channel=None):
        if path in ('/enter', '/exit'):
            self.rows.append({'path': path, 'position': None, 'channel': None})
            if path == '/enter':
                return {'status': 'success'}
            return {'status': 'success', 'exit_reason': 'user_exit'}
        point = np.asarray(position, dtype=float)
        self.virtual += float(np.linalg.norm(point - self.position)) / 5.0
        self.position = point
        if path == '/measure':
            cid = int(channel)
            if cid != self._last_measure_channel:
                self.virtual += 1.0
                self._last_measure_channel = cid
            self.virtual += 5.0
            self.channel = cid
            if cid in self.absent:
                reply = {'measure_result': 'no_signal'}
            else:
                delta = self.sources[cid] - point
                dist = float(np.linalg.norm(delta))
                if dist <= 5.0:
                    reply = {'measure_result': 'near'}
                elif dist <= 1000.0:
                    reply = {'measure_result': 'direction',
                             'svd_deg': math.degrees(math.atan2(delta[1], delta[0])) % 360.0}
                else:
                    reply = {'measure_result': 'no_signal'}
        elif path == '/clear':
            cid = int(channel)
            ok = cid in self.sources and float(np.linalg.norm(self.sources[cid] - point)) <= 20.0
            self.virtual += 5.0 if ok else 3.0
            if ok:
                del self.sources[cid]
            reply = {'clear_result': 'success' if ok else 'no_target_in_range'}
        else:
            raise ValueError(path)
        self.rows.append({'path': path, 'position': point.tolist(), 'channel': int(channel)})
        return reply


def drive(solve_fn):
    client = MockClient()
    client.act('/enter')
    result = solve_fn(client)
    client.act('/exit')
    return result, client


def load_source_q3():
    sys.path.insert(0, str(SRC / 'code' / 'src'))
    sys.path.insert(0, str(SRC / 'code'))
    import q3_optimizer_v5  # noqa
    return q3_optimizer_v5.solve_optimized_v5


def main():
    print('=== Q3 差分探针（源 vs 移植）===')
    sys.path.insert(0, str(ROOT))
    from absorbed.q3_v5 import q3_optimizer_v5 as ported_mod

    src_fn = load_source_q3()
    src_res, src_client = drive(src_fn)
    ported_res, ported_client = drive(ported_mod.solve_optimized_v5)

    a = json.dumps(norm(src_res), sort_keys=True, ensure_ascii=False)
    b = json.dumps(norm(ported_res), sort_keys=True, ensure_ascii=False)
    print('RESULT_JSON_EQUAL     :', a == b)
    if a != b:
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print('  first diff at char', i)
                print('  src   :', a[max(0, i - 120):i + 120])
                print('  ported:', b[max(0, i - 120):i + 120])
                break
        ka = set(norm(src_res))
        kb = set(norm(ported_res))
        print('  src-only keys:', sorted(ka - kb), '| ported-only keys:', sorted(kb - ka))

    sa = [(r['path'], r['channel'], None if r['position'] is None else [round(v, 9) for v in r['position']])
          for r in src_client.rows]
    sb = [(r['path'], r['channel'], None if r['position'] is None else [round(v, 9) for v in r['position']])
          for r in ported_client.rows]
    print('ACTION_SEQUENCE_EQUAL :', sa == sb, '| n_actions src/ported =', len(sa), '/', len(sb))
    print('VIRTUAL_EQUAL         :', round(src_client.virtual, 9) == round(ported_client.virtual, 9),
          '| virtual =', round(src_client.virtual, 6))
    ca = src_res.get('cleared_channels')
    cb = ported_res.get('cleared_channels')
    print('CLEARED_SET_EQUAL     :', ca == cb, '| cleared =', ca)
    print('VERSION src/ported    :', src_res.get('version'), '/', ported_res.get('version'))
    return 0 if (a == b and sa == sb and ca == cb) else 1


if __name__ == '__main__':
    raise SystemExit(main())
