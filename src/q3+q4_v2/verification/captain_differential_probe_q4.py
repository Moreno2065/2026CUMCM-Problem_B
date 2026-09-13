# -*- coding: utf-8 -*-
"""captain 侧差分探针（Q4）：源 strategy_v4.solve(+v4锁) vs 移植 locked.solve_locked。

Q4 源侧本机不能直接 import（numba 会把 PyPI coverage 装进 sys.modules），
故先 import numba，再把 v2 目录下的本地 coverage.py 装进 sys.modules['coverage']。
放临时目录，不写目标仓库。
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(r'D:\CUMCM2026\src\q3+q4_v2')
SRC = Path(r'D:\CUMCM2026\src\Q3_Q4_V3')
WS = SRC / 'workstreams'
V4 = WS / 'q4_deep_optimization_v4_20260912'
V3 = WS / 'q4_uniform_optimization_v3_20260912'
V2 = WS / 'q4_local_optimization_v2_20260912'
V1 = WS / 'q4_local_optimization_20260912'


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
    def __init__(self, n_sources=12):
        self.sources = {}
        for i in range(n_sources):
            ang = math.radians(360.0 / n_sources * i)
            self.sources[i + 1] = np.array([600.0 * math.cos(ang), 600.0 * math.sin(ang)])
        self.absent = set(range(n_sources + 1, 21))
        self.position = np.array([0.0, 0.0])
        self.virtual = 0.0
        self.channel = 1
        self.rows = []
        self._last = 1

    def act(self, path, position=None, channel=None):
        if path in ('/enter', '/exit'):
            self.rows.append({'path': path})
            return {'status': 'success'} if path == '/enter' else {'status': 'success', 'exit_reason': 'user_exit'}
        point = np.asarray(position, dtype=float)
        self.virtual += float(np.linalg.norm(point - self.position)) / 5.0
        self.position = point
        if path == '/measure':
            cid = int(channel)
            if cid != self._last:
                self.virtual += 1.0
                self._last = cid
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


def install_coverage_shim():
    import numba  # noqa: F401  （先加载，让 numba 用 PyPI coverage 完成定义）
    spec = importlib.util.spec_from_file_location('coverage', V2 / 'coverage.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['coverage'] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    print('=== Q4 差分探针（源 vs 移植）===')
    lock = json.loads((V4 / 'results' / 'selection_lock.json').read_text(encoding='utf-8'))
    params = lock['selected_parameters']
    print('lock:', lock['version'], lock['selected_name'], 'params=', len(params))

    local_cov = install_coverage_shim()
    print('coverage shim ->', getattr(local_cov, '__file__', '?'))
    sys.path[:0] = [str(V4), str(V3), str(V2), str(V1)]
    import strategy_v4  # noqa: E402

    sys.path.insert(0, str(ROOT))
    from absorbed.q4_v4 import locked, strategy_v4 as ported_strategy  # noqa: E402

    c1 = MockClient(); c1.act('/enter')
    r1 = strategy_v4.solve(c1, **params)
    c1.act('/exit')

    c2 = MockClient(); c2.act('/enter')
    r2 = locked.solve_locked(c2)
    c2.act('/exit')

    a = json.dumps(norm(r1), sort_keys=True, ensure_ascii=False)
    b = json.dumps(norm(r2), sort_keys=True, ensure_ascii=False)
    print('RESULT_JSON_EQUAL     :', a == b)
    if a != b:
        ka, kb = set(norm(r1)), set(norm(r2))
        print('  src-only keys:', sorted(ka - kb))
        print('  ported-only keys:', sorted(kb - ka))
        for k in sorted(ka & kb):
            if norm(r1[k]) != norm(r2[k]):
                print('  differing key:', k)
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print('  first char diff @', i)
                print('  src   :', a[max(0, i - 140):i + 140])
                print('  ported:', b[max(0, i - 140):i + 140])
                break
    sa = [(r['path'], r.get('channel'), None if 'position' not in r else [round(v, 9) for v in r['position']])
          for r in c1.rows]
    sb = [(r['path'], r.get('channel'), None if 'position' not in r else [round(v, 9) for v in r['position']])
          for r in c2.rows]
    print('ACTION_SEQUENCE_EQUAL :', sa == sb, '| n_actions src/ported =', len(sa), '/', len(sb))
    print('VIRTUAL_EQUAL         :', round(c1.virtual, 9) == round(c2.virtual, 9), '| virtual =', round(c1.virtual, 6))
    ca = [c['channel'] for c in r1.get('cleared_sources', [])]
    cb = [c['channel'] for c in r2.get('cleared_sources', [])]
    print('CLEARED_SET_EQUAL     :', ca == cb, '| cleared =', ca)
    print('STRATEGY src/ported   :', r1.get('strategy'), '/', r2.get('strategy'))
    return 0 if (a == b and sa == sb and ca == cb) else 1


if __name__ == '__main__':
    raise SystemExit(main())
