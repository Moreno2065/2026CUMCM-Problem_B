# -*- coding: utf-8 -*-
"""合成模拟器：进程内类 + 本地 HTTP 包装，接口与附件2 协议一致。

用途：离线演练与测试；与官方模拟器相同的判定语义子集：
- measure：dist≤5 且在覆盖角内 → near；dist≤R_eff 且在覆盖角内 →
  direction（全向 360°；定向为朝向 ±90° 闭半平面，含边界）；否则 no_signal。
- 测向误差：每个检测点位置的误差在局中固定（hash(position,seed) →
  [-0.99°,0.99°] 确定性映射，含两位小数舍入后总误差 ≤ 1°），同一位置
  重复测量返回相同 svd_deg。
- clear：dist≤20 → success（每源仅一次，重复 → no_target_in_range）。
- 虚拟时间账与频道切换规则与官方一致：move=距离/5，measure=+5，
  相邻两次合法 /measure 频道不同 +1（/clear 不切频道），clear 失败 +3、
  成功 +5；/enter、/exit、accepted=false 不推进。
- 幂等：同 request_id 同内容 → 返回首次响应；同 id 不同内容 → 409；
  结构错误 → 400（不占 request_id）；未声明字段 → 200 accepted=false
  （virtual_time_s 为 0）。

HTTP 包装：SimulatorHTTPServer（http.server 线程），实现 4 端点与
Content-Type / 大小 / BOM / 重复键检查，供 test_api_protocol.py 与
端到端 HTTP 模式演练（--sim http-synthetic）。
"""

import hashlib
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from geometry import constants as C
from geometry.wedge import bearing_of
from api import protocol

MAX_VIRTUAL_DURATION_S = 360000.0
MAX_REAL_DURATION_S = 1200.0


# ---------------------------------------------------------------------------
# 源生成
# ---------------------------------------------------------------------------

class Source:
    __slots__ = ("channel", "x", "y", "r_eff", "directional", "orientation",
                 "cleared")

    def __init__(self, channel, x, y, r_eff, directional, orientation):
        self.channel = int(channel)
        self.x = float(x)
        self.y = float(y)
        self.r_eff = float(r_eff)
        self.directional = bool(directional)
        self.orientation = float(orientation) % 360.0
        self.cleared = False

    @property
    def pos(self):
        return (self.x, self.y)

    def covers(self, p):
        """p 是否在该源覆盖内（定向：朝向 ±90° 闭半平面，含边界）。"""
        if not self.directional:
            return True
        dx, dy = p[0] - self.x, p[1] - self.y
        if math.hypot(dx, dy) <= 1e-9:
            return True  # 顶点属于闭半平面
        ang = math.degrees(math.atan2(dy, dx))
        diff = abs((ang - self.orientation + 180.0) % 360.0 - 180.0)
        return diff <= 90.0 + 1e-9

    def to_dict(self):
        return {"channel": self.channel, "x": self.x, "y": self.y,
                "r_eff": self.r_eff, "directional": self.directional,
                "orientation": self.orientation, "cleared": self.cleared}


def _gen_positions(rng, n, scenario):
    R = C.OMEGA_RADIUS
    if scenario == "boundary":
        # 源贴 ∂Ω（r ∈ [0.89, 1.0]·R，按面积均匀）
        return [_polar(R * math.sqrt(rng.uniform(0.89, 1.0)),
                       rng.uniform(0, 2 * math.pi)) for _ in range(n)]
    if scenario == "dense":
        cr = R * 0.6 * math.sqrt(rng.random())
        ca = rng.uniform(0, 2 * math.pi)
        cx, cy = cr * math.cos(ca), cr * math.sin(ca)
        pts = []
        while len(pts) < n:
            r = 300.0 * math.sqrt(rng.random())
            a = rng.uniform(0, 2 * math.pi)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            if math.hypot(x, y) <= R:
                pts.append((x, y))
        return pts
    if scenario == "sparse":
        pts = []
        tries = 0
        while len(pts) < n and tries < 20000:
            tries += 1
            p = _polar(R * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi))
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= 800.0
                   for q in pts):
                pts.append(p)
        while len(pts) < n:  # 拒采失败兜底（不应发生）
            pts.append(_polar(R * math.sqrt(rng.random()),
                              rng.uniform(0, 2 * math.pi)))
        return pts
    # random：Ω 内面积均匀
    return [_polar(R * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi))
            for _ in range(n)]


def _polar(r, a):
    return (r * math.cos(a), r * math.sin(a))


def make_sources(mode, seed, n_sources=None, scenario="random"):
    """按场景生成源列表（确定性，依赖 seed）。"""
    import random
    rng = random.Random(seed)
    if n_sources is None:
        n_sources = rng.randint(10, C.MAX_SOURCES)
    n_sources = max(1, min(int(n_sources), C.NUM_CHANNELS))
    channels = rng.sample(range(1, C.NUM_CHANNELS + 1), n_sources)
    positions = _gen_positions(rng, n_sources, scenario)
    sources = []
    for ch, (x, y) in zip(channels, positions):
        r_eff = rng.uniform(C.R_EFF_MIN, C.R_EFF_MAX)
        if mode == "Q3":
            directional, orient = False, 0.0
        else:
            if scenario == "mixed":
                directional = rng.random() < 0.5
            else:
                directional = True
            if scenario == "edge_facing":
                # 朝向背离 Ω 中心（最不利：中心方向观测不到）
                orient = bearing_of((0.0, 0.0), (x, y)) \
                    + rng.uniform(-10.0, 10.0)
            else:
                orient = rng.uniform(0.0, 360.0)
        sources.append(Source(ch, x, y, r_eff, directional, orient))
    return sources


# ---------------------------------------------------------------------------
# 合成模拟器（进程内协议语义）
# ---------------------------------------------------------------------------

ERROR_FIELD_TYPES = ("random_fixed", "boundary", "structured")
ERROR_FIELD_VERSION = 1


def _ef_params(seed):
    """由 seed 确定性派生误差场参数（boundary/structured 用）。"""
    import random
    rng = random.Random("ef|%s" % (seed,))
    return {
        "axis_deg": rng.uniform(0.0, 360.0),   # boundary 半平面分割轴
        "wave_deg": rng.uniform(0.0, 360.0),   # structured 波向
        "phase": rng.uniform(0.0, 2.0 * math.pi),
        "wavelength": 3600.0,                  # 低频：一个周期横跨 Ω
    }


def bearing_error(error_field_type, params, seed, x, y):
    """ε(S,c)∈[-1°,1°]，同点同频道固定（Addendum D.1/D.2 三类误差场）。

    random_fixed : hash(seed,x,y) → (-0.99°,0.99°)（既有默认方式）。
    boundary     : ε=±0.99°（两位小数舍入后总误差 ≤ 1°）。符号按几何不利
                   半平面规则：位置在 axis 一侧取 +0.99、另一侧 −0.99——
                   同侧观测点共享同号最大误差，对 bearing 交会最不利。
    structured   : 空间相关低频平滑场 ε=0.99·sin(2π·(p·u)/L + φ)，
                   有界且同点固定。
    """
    if error_field_type == "boundary":
        a = math.radians(params["axis_deg"])
        side = x * math.cos(a) + y * math.sin(a)
        return 0.99 if side >= 0.0 else -0.99
    if error_field_type == "structured":
        w = math.radians(params["wave_deg"])
        proj = x * math.cos(w) + y * math.sin(w)
        return 0.99 * math.sin(2.0 * math.pi * proj / params["wavelength"]
                               + params["phase"])
    # random_fixed（默认）
    h = hashlib.sha256(("%s|%0.6f|%0.6f" % (seed, x, y))
                       .encode("utf-8")).digest()
    u = int.from_bytes(h[:8], "big") / float(1 << 64)   # [0,1)
    return (2.0 * u - 1.0) * 0.99                       # (-0.99, 0.99)


class SyntheticSimulator:
    def __init__(self, mode, seed, n_sources=None, scenario="random",
                 error_field_type="random_fixed",
                 error_field_version=ERROR_FIELD_VERSION):
        if mode not in ("Q3", "Q4"):
            raise ValueError("mode must be 'Q3' or 'Q4'")
        if error_field_type not in ERROR_FIELD_TYPES:
            raise ValueError("error_field_type must be one of %r"
                             % (ERROR_FIELD_TYPES,))
        self.mode = mode
        self.seed = seed
        self.scenario = scenario
        self.error_field_type = error_field_type
        self.error_field_version = int(error_field_version)
        self._ef_params = _ef_params(seed)
        self.sources = make_sources(mode, seed, n_sources, scenario)
        # 会话状态
        self.entered = False
        self.exited = False
        self.robot_id = None
        self.position = (0.0, 0.0)
        self.virtual_time = 0.0
        self._last_measure_channel = None
        self._t0 = None
        self._idempotency = {}   # request_id -> (fingerprint, status, body)

    # ------------------------------------------------------------------
    # 测向误差：位置固定 ⇒ 误差固定（题设）；三种误差场见 bearing_error
    # ------------------------------------------------------------------

    def _bearing_error(self, x, y):
        return bearing_error(self.error_field_type, self._ef_params,
                             self.seed, x, y)

    # ------------------------------------------------------------------
    # 案例文件构造（Addendum D.4）：同一 case file ⇒ 完全相同的局
    # ------------------------------------------------------------------

    @classmethod
    def from_case(cls, case):
        """从冻结案例 dict 构造模拟器（不重新随机生成源）。"""
        mode = case["question"].upper()
        sim = cls(mode, case["case_seed"],
                  n_sources=case["source_count"],
                  error_field_type=case.get("error_field_type",
                                            "random_fixed"),
                  error_field_version=case.get("error_field_version",
                                               ERROR_FIELD_VERSION))
        sim.scenario = case.get("scenario", "case_file")
        sources = []
        for ch, (x, y), r_eff, direc in zip(case["channels"],
                                            case["positions"],
                                            case["receive_radii"],
                                            case["directions"]):
            directional = direc is not None
            sources.append(Source(ch, x, y, r_eff, directional,
                                  direc if directional else 0.0))
        sim.sources = sources
        return sim

    # ------------------------------------------------------------------
    # 判定
    # ------------------------------------------------------------------

    def _live_source(self, channel):
        for s in self.sources:
            if s.channel == channel and not s.cleared:
                return s
        return None

    def _measure_result(self, position, channel):
        src = self._live_source(channel)
        if src is None:
            return {"measure_result": "no_signal"}
        d = math.hypot(position[0] - src.x, position[1] - src.y)
        if not src.covers(position):
            return {"measure_result": "no_signal"}
        if d <= C.NEAR_THRESHOLD:
            return {"measure_result": "near"}
        if d <= src.r_eff:
            svd = (bearing_of(position, src.pos)
                   + self._bearing_error(*position)) % 360.0
            svd = round(svd, 2)
            if svd >= 360.0:
                svd = 0.0
            return {"measure_result": "direction", "svd_deg": svd}
        return {"measure_result": "no_signal"}

    def _clear_result(self, position, channel):
        src = self._live_source(channel)
        if src is not None and math.hypot(position[0] - src.x,
                                          position[1] - src.y) \
                <= C.CLEAR_RADIUS:
            src.cleared = True
            return "success"
        return "no_target_in_range"

    # ------------------------------------------------------------------
    # 协议处理：handle(endpoint, payload) -> (http_status, body)
    # ------------------------------------------------------------------

    def handle(self, endpoint, payload):
        now_ms = int(time.time() * 1000)

        def reject200():
            return 200, {"accepted": False, "real_timestamp_ms": now_ms,
                         "virtual_time_s": 0}

        def err400(msg):
            return 400, {"error": msg}

        if endpoint not in protocol.ENDPOINTS:
            return 404, {"error": "unknown endpoint %r" % endpoint}
        if not isinstance(payload, dict):
            return err400("body must be a JSON object")

        allowed = set(protocol.COMMON_REQUEST_FIELDS) | set(
            protocol.ENDPOINT_EXTRA_FIELDS[endpoint])
        if set(payload.keys()) - allowed:
            return reject200()                       # 未声明字段
        for f in protocol.COMMON_REQUEST_FIELDS:
            if f not in payload:
                return err400("missing field %r" % f)
        for f in protocol.ENDPOINT_EXTRA_FIELDS[endpoint]:
            if f not in payload:
                return err400("missing field %r" % f)

        # 公共字段结构校验
        try:
            protocol.validate_robot_id(payload["robot_id"])
            protocol.validate_request_id(payload["request_id"])
        except protocol.ProtocolError as e:
            return err400(str(e))
        if payload["arena_id"] != protocol.ARENA_ID:
            return reject200()
        if self.robot_id is not None and payload["robot_id"] != self.robot_id:
            return err400("robot_id mismatch")
        if endpoint in ("/measure", "/clear"):
            try:
                protocol.validate_channel(payload["channel"])
                pos = protocol.validate_position(payload["position"])
            except protocol.ProtocolError as e:
                return err400(str(e))
        else:
            pos = None

        # 幂等。request_id 是会话内幂等键：会话未开启时的 /enter 开启
        # 新会话，先清空上一会话的幂等表，再做重放检查。
        if endpoint == "/enter" and not self._open():
            self._idempotency.clear()
        rid = payload["request_id"]
        fingerprint = json.dumps(payload, sort_keys=True)
        if rid in self._idempotency:
            fp, st, body = self._idempotency[rid]
            if fp == fingerprint:
                return st, dict(body)              # 重放首次响应
            return 409, {"error": "request_id conflict"}

        # 端点语义
        if endpoint == "/enter":
            status, body = self._do_enter(payload, now_ms, reject200)
        elif endpoint == "/measure":
            status, body = self._do_measure(pos, payload["channel"],
                                            now_ms, reject200)
        elif endpoint == "/clear":
            status, body = self._do_clear(pos, payload["channel"],
                                          now_ms, reject200)
        else:
            status, body = self._do_exit(now_ms, reject200)

        if status == 200:
            self._idempotency[rid] = (fingerprint, status, dict(body))
        return status, body

    def _open(self):
        return self.entered and not self.exited

    def _vt(self):
        return round(self.virtual_time, 6)

    def _do_enter(self, payload, now_ms, reject200):
        if self._open():
            return reject200()                       # 重复 enter 拒绝
        self.entered = True
        self.exited = False
        self.robot_id = payload["robot_id"]
        self.position = (0.0, 0.0)
        self.virtual_time = 0.0
        self._last_measure_channel = None
        self._t0 = time.time()
        remaining = max(0.0, MAX_REAL_DURATION_S)
        return 200, {"accepted": True, "real_timestamp_ms": now_ms,
                     "virtual_time_s": 0.0,
                     "max_virtual_duration_s": MAX_VIRTUAL_DURATION_S,
                     "max_real_duration_s": MAX_REAL_DURATION_S,
                     "remaining_real_duration_s": remaining}

    def _do_measure(self, pos, channel, now_ms, reject200):
        if not self._open():
            return reject200()
        p = (pos["x"], pos["y"])
        dt = math.hypot(p[0] - self.position[0],
                        p[1] - self.position[1]) / C.MOVE_SPEED
        dt += C.MEASURE_TIME
        if self._last_measure_channel is not None \
                and self._last_measure_channel != int(channel):
            dt += C.SWITCH_TIME
        res = self._measure_result(p, int(channel))
        self.virtual_time += dt                      # accepted 才推进
        self.position = p
        self._last_measure_channel = int(channel)
        body = {"accepted": True, "real_timestamp_ms": now_ms,
                "virtual_time_s": self._vt()}
        body.update(res)
        return 200, body

    def _do_clear(self, pos, channel, now_ms, reject200):
        if not self._open():
            return reject200()
        p = (pos["x"], pos["y"])
        result = self._clear_result(p, int(channel))
        dt = math.hypot(p[0] - self.position[0],
                        p[1] - self.position[1]) / C.MOVE_SPEED
        dt += C.CLEAR_SUCCESS_TIME if result == "success" \
            else C.CLEAR_FAIL_TIME
        self.virtual_time += dt
        self.position = p                            # /clear 不切频道
        return 200, {"accepted": True, "real_timestamp_ms": now_ms,
                     "virtual_time_s": self._vt(),
                     "clear_result": result}

    def _do_exit(self, now_ms, reject200):
        if not self._open():
            return reject200()
        self.exited = True
        return 200, {"accepted": True, "real_timestamp_ms": now_ms,
                     "virtual_time_s": self._vt(),
                     "exit_reason": "normal"}

    # ------------------------------------------------------------------

    def real_time_exceeded(self):
        return self._t0 is not None \
            and (time.time() - self._t0) > MAX_REAL_DURATION_S

    def ground_truth(self):
        return [s.to_dict() for s in self.sources]


# ---------------------------------------------------------------------------
# 进程内后端（与 api.session.Session 同接口，供 ActionExecutor 使用）
# ---------------------------------------------------------------------------

class SimulatorBackend:
    """把 SyntheticSimulator 适配为 ActionExecutor 后端接口。"""

    def __init__(self, sim, robot_id="SYNTH"):
        self.sim = sim
        self.robot_id = robot_id
        self._req = 0

    # -- 状态属性（executor 只读） --
    @property
    def position(self):
        return self.sim.position

    @property
    def current_channel(self):
        # 模拟器内频道状态 = 最近一次合法 /measure 的频道
        ch = self.sim._last_measure_channel
        return ch if ch is not None else 1

    @property
    def virtual_time(self):
        return self.sim.virtual_time

    @property
    def max_virtual_duration_s(self):
        return MAX_VIRTUAL_DURATION_S

    def real_time_exceeded(self):
        return self.sim.real_time_exceeded()

    # -- 动作 --
    def _call(self, endpoint, position=None, channel=None):
        self._req += 1
        payload = protocol.build_request(
            endpoint, robot_id=self.robot_id,
            request_id="syn-%06d" % self._req,
            position=({"x": float(position[0]), "y": float(position[1])}
                      if position is not None else None),
            channel=channel)
        status, body = self.sim.handle(endpoint, payload)
        if status == 400:
            raise protocol.ProtocolError("simulator 400 on %s: %r"
                                         % (endpoint, body))
        if status == 409:
            raise protocol.ProtocolError("simulator 409 on %s" % endpoint)
        if status != 200:
            raise protocol.ProtocolError("simulator HTTP %d on %s"
                                         % (status, endpoint))
        return protocol.validate_response(endpoint, body)

    def enter(self):
        return self._call("/enter")

    def measure(self, position, channel):
        return self._call("/measure", position=position, channel=channel)

    def clear(self, position, channel):
        return self._call("/clear", position=position, channel=channel)

    def exit(self):
        return self._call("/exit")


# ---------------------------------------------------------------------------
# HTTP 包装（本地服务，供协议测试与端到端演练）
# ---------------------------------------------------------------------------

class _SimHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):   # 静音
        pass

    def _send_json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        sim = self.server.sim
        path = self.path.split("?", 1)[0]
        if path not in protocol.ENDPOINTS:
            return self._send_json(404, {"error": "unknown endpoint"})
        # Content-Type: application/json（仅允许 charset=utf-8 参数）
        ctype = self.headers.get("Content-Type", "")
        parts = [p.strip() for p in ctype.split(";")]
        if parts[0].lower() != "application/json":
            return self._send_json(415, {"error": "unsupported media type"})
        for prm in parts[1:]:
            kv = [t.strip() for t in prm.split("=", 1)]
            if len(kv) != 2 or kv[0].lower() != "charset" \
                    or kv[1].lower() != "utf-8":
                return self._send_json(415, {"error": "unsupported media "
                                             "type parameter"})
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._send_json(400, {"error": "bad content length"})
        if length > protocol.MAX_REQUEST_BYTES:
            return self._send_json(400, {"error": "request too large"})
        raw = self.rfile.read(length)
        try:
            payload = protocol.decode_json_strict(raw)
        except protocol.ProtocolError as e:
            return self._send_json(400, {"error": str(e)})
        status, body = sim.handle(path, payload)
        self._send_json(status, body)


class SimulatorHTTPServer:
    """把合成模拟器包装成本地 HTTP 服务（后台线程）。"""

    def __init__(self, sim, host="127.0.0.1", port=0):
        self.sim = sim
        self._httpd = ThreadingHTTPServer((host, port), _SimHandler)
        self._httpd.sim = sim
        self._httpd.daemon_threads = True
        self._thread = None

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05},
                                        daemon=True)
        self._thread.start()
        return self

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.shutdown()
