# -*- coding: utf-8 -*-
"""t10 回归锁：同点测向误差固定性（题面附录2(1)：同一地点电磁环境固定，
重复检测不改变检测误差）。

锁定三条不变量：
1. 同一 (seed, 位置) 任意次测量误差恒定（不重采样）；
2. 不同 seed（不同电磁环境实例）误差场不同；
3. 全局误差界：|舍入后总误差| ≤ 1°（含 360° wrap）；
4. svd_deg 两位小数、[0,360) 归一化。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiment.simulator import SyntheticSimulator, Source  # noqa: E402


def _mk(seed):
    sim = SyntheticSimulator("Q3", seed, n_sources=1)
    sim.sources = [Source(5, 1000.0, 0.0, 1500.0, False, 0.0)]
    return sim


def _svd(sim, x, y):
    sim.entered = True
    res = sim._measure_result((x, y), 5)
    assert res["measure_result"] == "direction"
    return res["svd_deg"]


def test_same_point_error_fixed():
    """同点重复测量返回相同 svd_deg（误差是位置的纯函数）。"""
    sim = _mk(123)
    svds = {_svd(sim, 300.0, 400.0) for _ in range(25)}
    assert len(svds) == 1, "same point must not resample error: %r" % svds
    # 不同点位误差一般不同（hash 场几乎必然），且各点自身固定
    a = _svd(sim, 300.0, 400.0)
    b = _svd(sim, 300.0, 400.5)
    c = _svd(sim, 300.0, 400.0)
    assert a == c and isinstance(b, float)


def test_seed_changes_error_field():
    """不同 seed ⇒ 不同电磁环境实例（误差场不同）。"""
    vals = set()
    for seed in (1, 2, 3, 4, 5, 6, 7, 8):
        vals.add(_svd(_mk(seed), 300.0, 400.0))
    assert len(vals) > 1, "different seeds should differ somewhere"


def test_error_bound_and_rounding():
    """误差全局 ≤1°（含 wrap），svd 两位小数、[0,360)。
    源固定在 (1000,0)；真实方位 = atan2(0-y, 1000-x)。"""
    import math
    SRC = (1000.0, 0.0)
    for seed in range(20):
        sim = _mk(seed)
        for (x, y) in ((300.0, 400.0), (400.0, -300.0), (1000.0, -50.0),
                       (0.0, 0.0), (500.0, -900.0)):
            svd = _svd(sim, x, y)
            assert 0.0 <= svd < 360.0
            assert abs(svd - round(svd, 2)) < 1e-9
            true = math.degrees(math.atan2(SRC[1] - y, SRC[0] - x)) % 360.0
            err = abs((svd - true + 180.0) % 360.0 - 180.0)
            assert err <= 1.0 + 1e-9, (seed, x, y, svd, true)


def test_same_point_repeat_via_session():
    """端到端：同会话同点同频道两次 measure ⇒ 同 svd（若官方语义下
    策略试图用重复测量降噪，此测试保证 mock 不会给它虚假收益）。"""
    sim = _mk(77)
    sim.entered = True
    r1 = sim._measure_result((300.0, 400.0), 5)
    r2 = sim._measure_result((300.0, 400.0), 5)
    assert r1["svd_deg"] == r2["svd_deg"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
