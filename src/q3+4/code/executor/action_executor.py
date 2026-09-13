# -*- coding: utf-8 -*-
"""ActionExecutor：数学动作 → API 调用 + 本地虚拟时间账。

后端接口（HTTP Session 与合成模拟器适配器都实现同一接口）：
    backend.enter()                 -> dict（已校验，accepted=true）
    backend.measure(position, ch)   -> dict（accepted 可能为 false）
    backend.clear(position, ch)     -> dict
    backend.exit()                  -> dict
    backend.position / backend.current_channel / backend.virtual_time
    backend.max_virtual_duration_s / backend.real_time_exceeded()

本地虚拟时间账（附件2 冻结）：
    移动      = 距离 / 5
    检测      = +5 s
    换频道    = +1 s（仅相邻两次合法 /measure 频道不同；/clear 不切频道）
    清除失败  = +3 s；清除成功 = +5 s
    /enter、/exit 不推进；accepted=false 不推进。

每次合法响应后与 response.virtual_time_s 对账：|本地累计 − 响应| > 1e-3
记一条对账警告（不中断），供 verifier/报告审查。
"""

import math

from geometry import constants as C

RECONCILE_TOL = 1e-3


class MeasureOutcome:
    __slots__ = ("accepted", "result", "svd_deg", "position", "channel",
                 "vtime_before", "vtime_after", "dt_move", "dt_measure",
                 "dt_switch", "raw")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class ClearOutcome:
    __slots__ = ("accepted", "success", "clear_result", "position", "channel",
                 "vtime_before", "vtime_after", "dt_move", "dt_clear", "raw")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class ActionExecutor:
    """把策略层的动作翻译为后端调用，并维护本地虚拟时间账。"""

    def __init__(self, backend):
        self.backend = backend
        # 本地账本分项
        self.ledger = {"T_move": 0.0, "T_measure": 0.0,
                       "T_switch": 0.0, "T_clear": 0.0}
        self.move_distance = 0.0
        self.n_measures = 0
        self.n_switches = 0
        self.n_clear_attempts = 0
        self.n_clear_success = 0
        self.reconcile_warnings = []
        self.api_log = []           # 每次调用的结构化日志（spec §9）
        self._last_measure_channel = None
        self._local_vtime = 0.0
        self._seq = 0

    # ------------------------------------------------------------------
    # 状态查询（以后端为准）
    # ------------------------------------------------------------------

    @property
    def position(self):
        return self.backend.position

    @property
    def current_channel(self):
        return self.backend.current_channel

    @property
    def virtual_time(self):
        return self.backend.virtual_time

    @property
    def local_virtual_time(self):
        return self._local_vtime

    @property
    def max_virtual_duration_s(self):
        return self.backend.max_virtual_duration_s

    def real_time_exceeded(self):
        return self.backend.real_time_exceeded()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def enter(self):
        resp = self.backend.enter()
        self._log("/enter", {}, resp, dt={})
        self._last_measure_channel = None
        self._local_vtime = resp["virtual_time_s"]  # enter 不推进，应为 0
        return resp

    def exit(self):
        resp = self.backend.exit()
        self._log("/exit", {}, resp, dt={})
        return resp

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def move_and_measure(self, x, y, channel):
        """移动到 (x,y) 并在该点检测 channel。返回 MeasureOutcome。

        accepted=false（业务拒绝）时不推进任何本地状态，result=None。
        """
        channel = int(channel)
        target = (float(x), float(y))
        v0 = self.virtual_time
        dt_move = self._dist(self.position, target) / C.MOVE_SPEED
        dt_switch = C.SWITCH_TIME if (
            self._last_measure_channel is not None
            and self._last_measure_channel != channel) else 0.0
        resp = self.backend.measure(target, channel)
        dt = {"move": 0.0, "measure": 0.0, "switch": 0.0, "clear": 0.0}
        outcome = MeasureOutcome(
            accepted=resp["accepted"], result=None, svd_deg=None,
            position=self.position, channel=channel,
            vtime_before=v0, vtime_after=v0,
            dt_move=0.0, dt_measure=0.0, dt_switch=0.0, raw=resp)
        if resp["accepted"]:
            outcome.result = resp["measure_result"]
            outcome.svd_deg = resp.get("svd_deg")
            outcome.position = self.position
            outcome.dt_move = dt_move
            outcome.dt_measure = C.MEASURE_TIME
            outcome.dt_switch = dt_switch
            dt.update(move=dt_move, measure=C.MEASURE_TIME,
                      switch=dt_switch)
            self.ledger["T_move"] += dt_move
            self.ledger["T_measure"] += C.MEASURE_TIME
            self.ledger["T_switch"] += dt_switch
            self.move_distance += dt_move * C.MOVE_SPEED
            self.n_measures += 1
            if dt_switch:
                self.n_switches += 1
            self._last_measure_channel = channel
            self._local_vtime += dt_move + C.MEASURE_TIME + dt_switch
            outcome.vtime_after = self.virtual_time
            self._reconcile("/measure", resp)
        self._log("/measure",
                  {"position": {"x": target[0], "y": target[1]},
                   "channel": channel}, resp, dt=dt)
        return outcome

    def clear_at(self, x, y, channel):
        """移动到 (x,y) 并对 channel 执行清除。返回 ClearOutcome。"""
        channel = int(channel)
        target = (float(x), float(y))
        v0 = self.virtual_time
        dt_move = self._dist(self.position, target) / C.MOVE_SPEED
        resp = self.backend.clear(target, channel)
        dt = {"move": 0.0, "measure": 0.0, "switch": 0.0, "clear": 0.0}
        outcome = ClearOutcome(
            accepted=resp["accepted"], success=None, clear_result=None,
            position=self.position, channel=channel,
            vtime_before=v0, vtime_after=v0, dt_move=0.0, dt_clear=0.0,
            raw=resp)
        if resp["accepted"]:
            outcome.clear_result = resp["clear_result"]
            outcome.success = (resp["clear_result"] == "success")
            dt_clear = C.CLEAR_SUCCESS_TIME if outcome.success \
                else C.CLEAR_FAIL_TIME
            outcome.position = self.position
            outcome.dt_move = dt_move
            outcome.dt_clear = dt_clear
            dt.update(move=dt_move, clear=dt_clear)
            self.ledger["T_move"] += dt_move
            self.ledger["T_clear"] += dt_clear
            self.move_distance += dt_move * C.MOVE_SPEED
            self.n_clear_attempts += 1
            if outcome.success:
                self.n_clear_success += 1
            self._local_vtime += dt_move + dt_clear
            outcome.vtime_after = self.virtual_time
            self._reconcile("/clear", resp)
        self._log("/clear",
                  {"position": {"x": target[0], "y": target[1]},
                   "channel": channel}, resp, dt=dt)
        return outcome

    # ------------------------------------------------------------------
    # 对账与日志
    # ------------------------------------------------------------------

    def _reconcile(self, endpoint, resp):
        diff = abs(self._local_vtime - float(resp["virtual_time_s"]))
        if diff > RECONCILE_TOL:
            self.reconcile_warnings.append({
                "endpoint": endpoint,
                "local_virtual_time": self._local_vtime,
                "reported_virtual_time_s": float(resp["virtual_time_s"]),
                "abs_diff": diff,
            })

    def _log(self, endpoint, request_extra, resp, dt):
        self._seq += 1
        self.api_log.append({
            "seq": self._seq,
            "endpoint": endpoint,
            "request": request_extra,
            "response": resp,
            "virtual_time_local": self._local_vtime,
            "dt": dt,
        })

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
