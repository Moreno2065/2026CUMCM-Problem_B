# -*- coding: utf-8 -*-
"""协议测试：本地 HTTP 模拟服务下的契约符合性。

覆盖：
- enter 成功 / 重复 enter 拒绝；
- measure 三分支（direction / near / no_signal）；
- clear 两分支（success / no_target_in_range）；
- 未声明字段 ⇒ 200 + accepted=false（只有 3 个公共字段，virtual_time_s=0）；
- request_id 同内容重放返回首次响应（不重复执行）；
- 同 id 不同内容 ⇒ 409；
- accepted=false 不推进虚拟时间；
- 结构错误（channel 1.5 / 越界坐标 / 重复键 / BOM / 坏 Content-Type）
  ⇒ 400 / 415；
- protocol 单元级校验与响应白名单。
"""

import json
import urllib.request
import urllib.error

import pytest

from api import protocol
from api.client import ApiClient
from api.protocol import ProtocolError, DuplicateKeyError
from api.session import Session
from executor.action_executor import ActionExecutor
from experiment.simulator import (
    SimulatorHTTPServer,
    Source,
    SyntheticSimulator,
)

ROBOT = "TEST01"


@pytest.fixture(scope="module")
def server():
    """固定源的合成模拟器 HTTP 服务：channel 5 全向源 @ (1000, 0)。"""
    sim = SyntheticSimulator("Q3", 0, n_sources=1)
    sim.sources = [Source(5, 1000.0, 0.0, 1500.0, False, 0.0)]
    srv = SimulatorHTTPServer(sim).start()
    yield srv
    srv.shutdown()


@pytest.fixture()
def client(server):
    return ApiClient(server.url, timeout=5.0, robot_id=ROBOT)


def _fresh_session(client):
    """每个用例独立会话（重复 enter 拒绝，所以要新模拟器或新服务）。"""
    return Session(client, robot_id=ROBOT)


# ---------------------------------------------------------------------------
# 会话生命周期（按序执行：一个会话内串完 enter/measure/clear/exit）
# ---------------------------------------------------------------------------

class TestSessionFlow:
    def test_full_flow(self, server, client):
        s = _fresh_session(client)
        # enter 成功：响应含三类时长字段；初始位置 (0,0) 频道 1
        resp = s.enter()
        assert resp["accepted"] is True
        assert resp["max_virtual_duration_s"] == 360000.0
        assert resp["max_real_duration_s"] == 1200.0
        assert 0.0 <= resp["remaining_real_duration_s"] <= 1200.0
        assert s.position == (0.0, 0.0)
        assert s.current_channel == 1
        assert s.virtual_time == 0.0

        # measure → direction（dist=1000 ≤ R_eff=1500，全向）
        r1 = s.measure((0.0, 0.0), 5)
        assert r1["accepted"] and r1["measure_result"] == "direction"
        svd = r1["svd_deg"]
        assert 0.0 <= svd < 360.0
        assert abs(svd - round(svd, 2)) < 1e-9
        # 真方位 0°（源在正东），误差 ≤1°（含跨 360 wrap）
        err = min(abs(svd - 0.0), 360.0 - abs(svd - 0.0))
        assert err <= 1.0 + 1e-9
        # 虚拟时间：移动 0 + 换频 1（首测频道 5 ≠ 初始频道 1，t10 校准）+ 检测 5
        assert abs(r1["virtual_time_s"] - 6.0) < 1e-6
        assert abs(s.virtual_time - 6.0) < 1e-6

        # 换频道测无源频道 → no_signal；+1s 换频
        r2 = s.measure((0.0, 0.0), 7)
        assert r2["accepted"] and r2["measure_result"] == "no_signal"
        assert abs(r2["virtual_time_s"] - 12.0) < 1e-6

        # 靠近源 → near（移动 1003m=200.6s，换频 +1，检测 +5）
        r3 = s.measure((1003.0, 0.0), 5)
        assert r3["accepted"] and r3["measure_result"] == "near"
        assert abs(r3["virtual_time_s"] - (12.0 + 200.6 + 1.0 + 5.0)) < 1e-6

        # clear 成功（dist=3 ≤ 20；移动 0，不切频道，+5）
        r4 = s.clear((1003.0, 0.0), 5)
        assert r4["accepted"] and r4["clear_result"] == "success"
        assert abs(r4["virtual_time_s"] - (218.6 + 5.0)) < 1e-6

        # 重复 clear 同一源 → no_target_in_range（+3）
        r5 = s.clear((1003.0, 0.0), 5)
        assert r5["accepted"] and r5["clear_result"] == "no_target_in_range"
        assert abs(r5["virtual_time_s"] - (223.6 + 3.0)) < 1e-6

        # exit
        r6 = s.exit()
        assert r6["accepted"] and r6["exit_reason"] == "user_exit"
        assert abs(r6["virtual_time_s"] - 226.6) < 1e-6   # exit 不推进

        # 会话关闭后再 measure → accepted=false
        r7 = client.measure((0.0, 0.0), 5, "after-exit-1")
        assert r7.status == 200 and r7.body["accepted"] is False

    def test_duplicate_enter_rejected(self, server, client):
        # 上一用例已 exit；重新 enter 合法，再重复 enter 拒绝
        s = _fresh_session(client)
        assert s.enter()["accepted"] is True
        r = client.enter("dup-enter-1")
        assert r.status == 200 and r.body["accepted"] is False
        assert set(r.body.keys()) == {"accepted", "real_timestamp_ms",
                                      "virtual_time_s"}
        s.exit()


# ---------------------------------------------------------------------------
# 幂等与错误语义（独立服务，互不影响）
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_server():
    sim = SyntheticSimulator("Q3", 1, n_sources=1)
    sim.sources = [Source(5, 1000.0, 0.0, 1500.0, False, 0.0)]
    srv = SimulatorHTTPServer(sim).start()
    yield srv
    srv.shutdown()


def test_unknown_field_rejected_and_time_frozen(fresh_server):
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    # 未声明字段 ⇒ 200 + accepted=false，只有 3 个公共字段
    payload = protocol.build_request("/measure", ROBOT, "uf-1",
                                     position={"x": 0.0, "y": 0.0},
                                     channel=5)
    payload["evil_field"] = 1
    r = c.post("/measure", payload)
    assert r.status == 200 and r.body["accepted"] is False
    assert set(r.body.keys()) == {"accepted", "real_timestamp_ms",
                                  "virtual_time_s"}
    assert r.body["virtual_time_s"] == 0
    # accepted=false 不推进虚拟时间：随后的合法 measure 只计自身耗时
    # （该会话首测频道 5 ≠ 初始频道 1 ⇒ +1s 换频，t10 校准）
    r2 = s.measure((0.0, 0.0), 5)
    assert abs(r2["virtual_time_s"] - 6.0) < 1e-6
    s.exit()


def test_request_id_replay_and_conflict(fresh_server):
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    # 首次 measure
    r1 = c.measure((0.0, 0.0), 5, "idem-1")
    assert r1.body["accepted"] and r1.body["measure_result"] == "direction"
    # 同 id 同内容重放：返回首次响应（逐字段一致，不重复执行）
    r2 = c.measure((0.0, 0.0), 5, "idem-1")
    assert r2.status == 200 and r2.body == r1.body
    # 同 id 不同内容 ⇒ 409
    r3 = c.measure((10.0, 0.0), 5, "idem-1")
    assert r3.status == 409
    # 虚拟时间只推进了一次（5s）
    assert abs(s.virtual_time - 0.0) < 1e-9  # session 状态只被 r1 推进过
    r4 = s.measure((0.0, 0.0), 7)            # 换频 +1 + 检测 5（首测已 +1）
    assert abs(r4["virtual_time_s"] - (6.0 + 6.0)) < 1e-6
    s.exit()


def test_structure_errors_400(fresh_server):
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    c.enter("se-enter")
    # channel 1.5：客户端构造层直接拒（ProtocolError）；
    # 绕过构造层发原始体 ⇒ 服务端 400
    with pytest.raises(ProtocolError):
        c.measure((0.0, 0.0), 1.5, "se-bad-ch")
    bad = {"arena_id": "default", "robot_id": ROBOT, "request_id": "se-bad-ch",
           "position": {"x": 0.0, "y": 0.0}, "channel": 1.5}
    r = c.post("/measure", bad)
    assert r.status == 400
    # 越界坐标：同样客户端拒 + 服务端 400
    with pytest.raises(ProtocolError):
        c.measure((2.0e6 + 1.0, 0.0), 5, "se-bad-pos")
    bad2 = {"arena_id": "default", "robot_id": ROBOT,
            "request_id": "se-bad-pos",
            "position": {"x": 2.0e6 + 1.0, "y": 0.0}, "channel": 5}
    r = c.post("/measure", bad2)
    assert r.status == 400
    # 400 不占 request_id：修正后同 id 可复用
    r = c.measure((0.0, 0.0), 5, "se-bad-pos")
    assert r.status == 200 and r.body["accepted"] is True
    # channel 7.0（整数值浮点）可接受
    r = c.measure((0.0, 0.0), 7.0, "se-float-ch")
    assert r.status == 200 and r.body["accepted"] is True
    # 重复键 JSON ⇒ 400
    raw = (b'{"arena_id":"default","robot_id":"T","request_id":"dup-key-1",'
           b'"request_id":"x"}')
    req = urllib.request.Request(fresh_server.url + "/enter", data=raw,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "duplicate keys must be rejected"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    # 坏 Content-Type ⇒ 415
    req = urllib.request.Request(
        fresh_server.url + "/enter",
        data=b'{"arena_id":"default"}', method="POST",
        headers={"Content-Type": "text/plain; charset=gbk"})
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 415


# ---------------------------------------------------------------------------
# protocol 单元级
# ---------------------------------------------------------------------------

class TestProtocolUnit:
    def test_channel_validation(self):
        assert protocol.validate_channel(1) == 1
        assert protocol.validate_channel(20) == 20
        assert protocol.validate_channel(1.0) == 1
        with pytest.raises(ProtocolError):
            protocol.validate_channel(1.5)
        with pytest.raises(ProtocolError):
            protocol.validate_channel(0)
        with pytest.raises(ProtocolError):
            protocol.validate_channel(21)
        with pytest.raises(ProtocolError):
            protocol.validate_channel(True)
        with pytest.raises(ProtocolError):
            protocol.validate_channel("5")

    def test_position_validation(self):
        p = protocol.validate_position({"x": 2.0e6, "y": -2.0e6})
        assert p == {"x": 2.0e6, "y": -2.0e6}
        for bad in ({"x": 2.0e6 + 1, "y": 0}, {"x": 0},
                    {"x": 0, "y": 0, "z": 0}, {"x": float("nan"), "y": 0},
                    {"x": float("inf"), "y": 0}, {"x": "0", "y": 0}):
            with pytest.raises(ProtocolError):
                protocol.validate_position(bad)

    def test_ids(self):
        protocol.validate_robot_id("A" * 64)
        with pytest.raises(ProtocolError):
            protocol.validate_robot_id("")
        with pytest.raises(ProtocolError):
            protocol.validate_robot_id("A" * 65)
        with pytest.raises(ProtocolError):
            protocol.validate_robot_id("队")       # 非 ASCII
        protocol.validate_request_id("r" * 128)
        with pytest.raises(ProtocolError):
            protocol.validate_request_id("r" * 129)

    def test_decode_strict(self):
        assert protocol.decode_json_strict(b'{"a":1}') == {"a": 1}
        with pytest.raises(DuplicateKeyError):
            protocol.decode_json_strict(b'{"a":1,"a":2}')
        with pytest.raises(ProtocolError):
            protocol.decode_json_strict(b'\xef\xbb\xbf{"a":1}')   # BOM
        with pytest.raises(ProtocolError):
            protocol.decode_json_strict(b'[1,2]')                  # 非对象
        with pytest.raises(ProtocolError):
            protocol.decode_json_strict(b'{bad json')

    def test_response_validation(self):
        base = {"accepted": False, "real_timestamp_ms": 1, "virtual_time_s": 0}
        out = protocol.validate_response("/measure", dict(base))
        assert out["accepted"] is False
        # accepted=false 带多余字段 → 拒
        with pytest.raises(ProtocolError):
            protocol.validate_response("/measure",
                                       dict(base, measure_result="near"))
        # accepted=false 但 virtual_time_s 非 0 → 拒
        with pytest.raises(ProtocolError):
            protocol.validate_response("/measure",
                                       dict(base, virtual_time_s=3.0))
        # virtual_time_s 浮点语义（6 位小数），不当整数解析
        ok = {"accepted": True, "real_timestamp_ms": 1,
              "virtual_time_s": 0.000001, "measure_result": "near"}
        out = protocol.validate_response("/measure", dict(ok))
        assert out["virtual_time_s"] == 0.000001
        # direction 必须带合法 svd_deg
        with pytest.raises(ProtocolError):
            protocol.validate_response(
                "/measure", {"accepted": True, "real_timestamp_ms": 1,
                             "virtual_time_s": 5.0,
                             "measure_result": "direction"})
        with pytest.raises(ProtocolError):
            protocol.validate_response(
                "/measure", {"accepted": True, "real_timestamp_ms": 1,
                             "virtual_time_s": 5.0,
                             "measure_result": "direction",
                             "svd_deg": 12.345})          # 超过两位小数
        with pytest.raises(ProtocolError):
            protocol.validate_response(
                "/measure", {"accepted": True, "real_timestamp_ms": 1,
                             "virtual_time_s": 5.0,
                             "measure_result": "direction",
                             "svd_deg": 360.0})           # 越界
        # 未声明响应字段 → 拒
        with pytest.raises(ProtocolError):
            protocol.validate_response(
                "/clear", {"accepted": True, "real_timestamp_ms": 1,
                           "virtual_time_s": 5.0, "clear_result": "success",
                           "surprise": 1})


# ---------------------------------------------------------------------------
# executor 对账（HTTP 全链路）
# ---------------------------------------------------------------------------

def test_executor_reconcile_over_http(fresh_server):
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    ex = ActionExecutor(s)
    ex.enter()
    o1 = ex.move_and_measure(0.0, 0.0, 5)
    assert o1.accepted and o1.result == "direction"
    o2 = ex.move_and_measure(1003.0, 0.0, 5)   # near
    assert o2.accepted and o2.result == "near"
    o3 = ex.clear_at(1003.0, 0.0, 5)
    assert o3.accepted and o3.success
    ex.exit()
    assert ex.reconcile_warnings == []
    assert abs(ex.local_virtual_time - ex.virtual_time) < 1e-6
    assert len(ex.api_log) == 5   # enter + 2 measure + clear + exit


# ---------------------------------------------------------------------------
# t10 口径校准回归锁（对齐附件2 官方语义）
# ---------------------------------------------------------------------------

def test_first_measure_channel1_no_switch(fresh_server):
    """首测频道=初始频道 1 ⇒ 无换频，恰好 5s（附件2 §4.3）。"""
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    r = s.measure((0.0, 0.0), 1)
    assert r["accepted"] and abs(r["virtual_time_s"] - 5.0) < 1e-6
    s.exit()


def test_first_measure_other_channel_switches(fresh_server):
    """首测频道≠1 ⇒ +1s 换频（附件2 §1.4 初始频道=1）。"""
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    r = s.measure((0.0, 0.0), 5)
    assert r["accepted"] and abs(r["virtual_time_s"] - 6.0) < 1e-6
    s.exit()


def test_oversized_body_413(fresh_server):
    """请求体 > 65536 字节 ⇒ HTTP 413（附件2 §5.3）。"""
    big = b'{"arena_id":"default","robot_id":"' + b"A" * 70000 + b'"}'
    req = urllib.request.Request(fresh_server.url + "/enter", data=big,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "oversized body must be rejected"
    except urllib.error.HTTPError as e:
        assert e.code == 413


def test_query_param_and_trailing_slash_404(fresh_server):
    """路径必须精确；查询参数与尾随斜杠 ⇒ 404（附件2 §5.1）。"""
    for bad_path in ("/enter?x=1", "/enter/"):
        req = urllib.request.Request(
            fresh_server.url + bad_path,
            data=b'{"arena_id":"default","robot_id":"T","request_id":"q1"}',
            method="POST",
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "%s must be rejected" % bad_path
        except urllib.error.HTTPError as e:
            assert e.code == 404


def test_error_bodies_carry_common_fields(fresh_server):
    """400/409 错误响应也必须携带 accepted/real_timestamp_ms/virtual_time_s
    （附件2 §5.3：所有能形成 HTTP 响应的错误都返回 JSON 且至少含三字段）。"""
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    bad = {"arena_id": "default", "robot_id": ROBOT, "request_id": "eb-1",
           "position": {"x": 0.0, "y": 0.0}, "channel": 1.5}
    r = c.post("/measure", bad)
    assert r.status == 400
    assert r.body["accepted"] is False
    assert "real_timestamp_ms" in r.body and "virtual_time_s" in r.body
    # 409：先占用 id，再同 id 异内容
    r1 = c.measure((0.0, 0.0), 1, "eb-2")
    assert r1.body["accepted"] is True
    r2 = c.measure((10.0, 0.0), 1, "eb-2")
    assert r2.status == 409
    assert r2.body["accepted"] is False
    assert "real_timestamp_ms" in r2.body and "virtual_time_s" in r2.body
    s.exit()


def test_accepted_false_does_not_occupy_request_id(fresh_server):
    """accepted=false 的 200 不占用 request_id，修正后同 id 可复用
    （附件2 §5.3：业务上已被接受的动作才占用该 id）。"""
    c = ApiClient(fresh_server.url, robot_id=ROBOT)
    s = Session(c)
    s.enter()
    payload = protocol.build_request("/measure", ROBOT, "reuse-1",
                                     position={"x": 0.0, "y": 0.0},
                                     channel=5)
    payload["evil_field"] = 1                     # 未声明字段 ⇒ accepted=false
    r = c.post("/measure", payload)
    assert r.status == 200 and r.body["accepted"] is False
    # 同 id 修正后重发 ⇒ 正常执行（若被旧实现占用，这里会错误重放）
    r2 = c.measure((0.0, 0.0), 5, "reuse-1")
    assert r2.status == 200 and r2.body["accepted"] is True
    assert abs(r2.body["virtual_time_s"] - 6.0) < 1e-6
    s.exit()


def test_control_chars_rejected():
    """robot_id/request_id 不能含控制字符或不可见格式字符（附件2 §5.1）。"""
    with pytest.raises(ProtocolError):
        protocol.validate_request_id("ab\ncd")
    with pytest.raises(ProtocolError):
        protocol.validate_request_id("ab\u200bcd")   # 零宽空格 (Cf)
    with pytest.raises(ProtocolError):
        protocol.validate_robot_id("a\tb")
    assert protocol.validate_request_id("ok-id_1") == "ok-id_1"


def test_late_enter_remaining_injectable():
    """晚启动场景：/enter 的 remaining_real_duration_s 可注入 <1200
    （附件2 §6.2：范围为 0..1200 的实际剩余）。"""
    sim = SyntheticSimulator("Q3", 0, n_sources=1,
                             remaining_real_duration_s=600)
    status, body = sim.handle("/enter", {"arena_id": "default",
                                         "robot_id": ROBOT,
                                         "request_id": "late-1"})
    assert status == 200 and body["accepted"] is True
    assert body["remaining_real_duration_s"] == 600.0
