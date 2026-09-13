# -*- coding: utf-8 -*-
"""把 v2 运行栈包装成 Q3_Q4_V3 solver 期望的 client 契约。

源契约的权威实现（只读核对，不是猜测）：
``Q3_Q4_V3/workstreams/q4_local_optimization_20260912/offline_world.py`` 的
``ObservationClient`` + ``World._act``（第 4-58 行），经 ``base.py:17`` ->
``bridge.py:11`` -> ``bridge_v4.py:11`` 的 star-import 暴露给 ``strategy_v4``；
调用方是 ``run_offline.py:22``：``c.act('/enter'); solve(c, **params); c.act('/exit')``。

契约逐项对照（源侧 -> 本适配层实现）：

======================  ==========================================  ==========================================
源侧                   v2 对应物                                    本适配层
======================  ==========================================  ==========================================
act('/enter')           ActionExecutor.enter()                      status/accepted/virtual_time_s
act('/exit')            ActionExecutor.exit()                       status/exit_reason
act('/measure',pos,ch)  ActionExecutor.move_and_measure(x,y,ch)     measure_result(+svd_deg)
act('/clear',p,ch)      ActionExecutor.clear_at(x,y,ch)             clear_result
position                 backend.position（Session/SimulatorBackend整）  同
channel                  backend.current_channel（只由 /measure 改）  同
virtual                  backend.virtual_time（服务端上报口径）       默认 reported，可切 local
rows                     由本模块按源侧行结构合成                     sequence/path/position/channel/response/分项时间/虚拟时间前后
======================  ==========================================  ==========================================

虚拟时间口径与源侧**逐项一致**（不改动）：move=距离/5、measure +5、换频道 +1
（仅相邻两次合法 /measure 频道不同；初始频道 1；/clear 不切频道）、clear 成功
+5 / 失败 +3、/enter 与 /exit 不推进。证据：v2 侧
``baseline/code/geometry/constants.py:20-24`` + ``executor/action_executor.py:123-189``
+ ``api/session.py:133-141`` + ``experiment/simulator.py:417-453``；源侧
``offline_world.py:33,37,51``。

已登记的降级（**不静默近似**，同样写进 ``ABSORBED_SOLVERS.md``）：

1. ``accepted=false``：v2 协议允许该响应（未声明字段/结构拒绝，
   ``api/protocol.py:251-262``），而源侧 ``offline_world`` 不存在该状态。
   默认 ``on_reject="raise"``：直接抛 :class:`AbsorbedActionRejected`，
   把原始响应带进异常文本，让运行以非零退出码失败而不是把「被拒」当成
   ``no_signal`` 继续算（那会污染几何状态）。``on_reject="return"`` 只用于
   调试，它返回的 reply **不含** ``measure_result`` / ``clear_result``，
   引擎随后会 KeyError（这是刻意的：拒绝无法映射成任何测量结果）。
2. ``rows`` 行结构：源侧行里 ``/enter`` 与 ``/exit`` 也各占一行
   （``offline_world.py:55-57``），且引擎用 ``len(client.rows)`` 当 sequence
   与动作上限（``q3_optimizer_v5.py:166`` 上限 550；
   ``strategy_v4.py:240`` 上限 3500）。本模块同样为每个 act 追加一行，
   因此 ``len(client.rows)`` 与源侧同口径（含 enter/exit）。
3. reply 里的 ``virtual_time_s`` 与 ``accepted`` 是 v2 侧信息，源侧没有；
   只会被记录，不会被引擎读取，不影响算法。
"""

from __future__ import annotations

import math
import time

ACT_PATHS = ("/enter", "/measure", "/clear", "/exit")
_VALID_ACT_PATHS = frozenset(ACT_PATHS)
_POSITION_BOUND = 2.0e6
_NUM_CHANNELS = 20

ROW_KEYS = ("sequence", "path", "position", "channel", "response",
            "movement_s", "switch_s", "operation_s",
            "virtual_before_s", "virtual_after_s")


class AbsorbedActionRejected(RuntimeError):
    """v2 运行栈返回 ``accepted=false``；源引擎的 offline world 无此状态。"""


class AbsorbedSolverClient:
    """Q3_Q4_V3 solver 期望的 client（包装 v2 ``ActionExecutor``）。

    参数
    ----
    executor      : ``executor.action_executor.ActionExecutor`` 实例（必需）。
                    本模块不 import 任何 v2 模块，只按鸭子类型调用，
                    因此 import 期零副作用、可离线构造。
    on_reject     : ``"raise"``（默认）或 ``"return"``；见模块 docstring 降级 1。
    virtual_source: ``"reported"``（默认，服务端上报口径 = 源侧语义）或
                    ``"local"``（executor 本地账本；用于对账诊断）。
    real_time_budget_s: >0 时启用现实时间闸门（官方模拟器有 1200 s 上限）；
                    超时抛 RuntimeError。0（默认）表示关闭，与源侧一致。

    用法（与 ``run_offline.py:22`` 同形）::

        client = AbsorbedSolverClient(executor)
        client.act("/enter")
        result = solve_locked(client)
        client.act("/exit")
    """

    def __init__(self, executor, *, on_reject="raise", virtual_source="reported",
                 real_time_budget_s=0.0, clock=None):
        if on_reject not in ("raise", "return"):
            raise ValueError("on_reject must be 'raise' or 'return'")
        if virtual_source not in ("reported", "local"):
            raise ValueError("virtual_source must be 'reported' or 'local'")
        self._executor = executor
        self.on_reject = on_reject
        self.virtual_source = virtual_source
        self.real_time_budget_s = float(real_time_budget_s or 0.0)
        self._clock = clock or time.monotonic
        self._t0 = None
        self.rows = []
        self.rejects = []
        self._entered = False
        self._exited = False

    # ------------------------------------------------------------------
    # 契约属性
    # ------------------------------------------------------------------

    @property
    def executor(self):
        return self._executor

    @property
    def position(self):
        """当前坐标（元组）。引擎会做 ``np.asarray`` / ``math.dist``，元组可用。"""
        return self._executor.position

    @property
    def channel(self):
        """当前频道：v2 侧只由合法 ``/measure`` 更新，``/clear`` 不切频道。"""
        return int(self._executor.current_channel)

    @property
    def virtual(self):
        """虚拟秒。默认取后端上报值（与源侧 ``client.virtual`` 同口径）。"""
        if self.virtual_source == "local":
            return float(self._executor.local_virtual_time)
        return float(self._executor.virtual_time)

    @property
    def n_acts(self):
        return len(self.rows)

    # ------------------------------------------------------------------
    # act：唯一动作入口
    # ------------------------------------------------------------------

    def act(self, path, position=None, channel=None):
        """执行一次动作并返回源侧形状的 reply dict。

        ``path`` ∈ ``/enter`` / ``/measure`` / ``/clear`` / ``/exit``。
        非法动作与非法会话顺序的行为对齐源侧
        （``offline_world.py:23-32``）：重复 enter -> ``RuntimeError('Enter twice')``；
        会话未开或已结束后再动 -> ``RuntimeError('No active offline session')``；
        坐标/频道非法 -> ``ValueError('Invalid action')``。
        """
        if path not in _VALID_ACT_PATHS:
            raise ValueError(path)
        if self._t0 is None:
            self._t0 = self._clock()
        self._check_real_budget()

        v0 = self.virtual
        movement = switch = operation = 0.0
        row_position = None
        row_channel = None

        if path == "/enter":
            if self._entered:
                raise RuntimeError("Enter twice")
            self._executor.enter()          # v2 侧在 Session/ActionExecutor 内校验
            self._entered = True
            reply = {"status": "success", "accepted": True,
                     "virtual_time_s": v0}

        elif path == "/exit":
            if not self._entered or self._exited:
                raise RuntimeError("No active offline session")
            resp = self._executor.exit()
            self._exited = True
            reply = {
                "status": "success" if resp.get("accepted") else "rejected",
                "exit_reason": resp.get("exit_reason", "user_exit"),
                "accepted": bool(resp.get("accepted")),
                "virtual_time_s": v0,
            }

        else:
            if not self._entered or self._exited:
                raise RuntimeError("No active offline session")
            point, ch = _validate_action(position, channel)
            row_position = point
            row_channel = ch
            if path == "/measure":
                outcome = self._executor.move_and_measure(point[0], point[1], ch)
                if not outcome.accepted:
                    reply = self._reject(path, point, ch, outcome.raw)
                else:
                    reply = {"measure_result": outcome.result, "accepted": True}
                    if outcome.svd_deg is not None:
                        reply["svd_deg"] = outcome.svd_deg
                    reply["virtual_time_s"] = self.virtual
                    movement = float(outcome.dt_move)
                    switch = float(outcome.dt_switch)
                    operation = float(outcome.dt_measure)
            else:                                        # "/clear"
                outcome = self._executor.clear_at(point[0], point[1], ch)
                if not outcome.accepted:
                    reply = self._reject(path, point, ch, outcome.raw)
                else:
                    reply = {"clear_result": outcome.clear_result,
                             "accepted": True, "virtual_time_s": self.virtual}
                    movement = float(outcome.dt_move)
                    operation = float(outcome.dt_clear)

        v1 = self.virtual
        self._record(path, row_position, row_channel, reply, v0, v1,
                     movement, switch, operation)
        return reply

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _reject(self, path, point, channel, raw):
        raw = dict(raw or {})
        self.rejects.append({"path": path, "position": list(point),
                             "channel": channel, "raw": raw})
        if self.on_reject == "raise":
            raise AbsorbedActionRejected(
                "v2 运行栈对 %s 返回 accepted=false（源引擎 offline world 无此状态，"
                "适配层不静默近似）：position=%r channel=%r raw=%r"
                % (path, list(point), channel, raw))
        return {"accepted": False, "rejected": True, "path": path, "raw": raw}

    def _record(self, path, position, channel, reply, v0, v1,
                movement, switch, operation):
        self.rows.append({
            "sequence": len(self.rows) + 1,
            "path": path,
            "position": (None if position is None
                         else [float(position[0]), float(position[1])]),
            "channel": (None if channel is None else int(channel)),
            "response": dict(reply),
            "movement_s": float(movement),
            "switch_s": float(switch),
            "operation_s": float(operation),
            "virtual_before_s": float(v0),
            "virtual_after_s": float(v1),
        })

    def _check_real_budget(self):
        if self.real_time_budget_s <= 0.0 or self._t0 is None:
            return
        elapsed = self._clock() - self._t0
        if elapsed > self.real_time_budget_s:
            raise RuntimeError(
                "real time budget exceeded: %.1fs > %.1fs"
                % (elapsed, self.real_time_budget_s))

    def snapshot(self):
        """报告用摘要（不落 engine 内部状态）。"""
        return {
            "n_acts": len(self.rows),
            "n_rejects": len(self.rejects),
            "entered": self._entered,
            "exited": self._exited,
            "virtual_source": self.virtual_source,
            "on_reject": self.on_reject,
            "real_time_budget_s": self.real_time_budget_s,
            "virtual": self.virtual,
            "rows_reference_shape_ok": all(
                tuple(sorted(row)) == tuple(sorted(ROW_KEYS))
                for row in self.rows),
        }


def _validate_action(position, channel):
    """对齐源侧校验（``offline_world.py:32``）：|x|,|y| ≤ 2e6 且 1 ≤ ch ≤ 20。"""
    if position is None or channel is None:
        raise ValueError("Invalid action")
    try:
        x = float(position[0])
        y = float(position[1])
    except Exception:
        raise ValueError("Invalid action")
    if not (math.isfinite(x) and math.isfinite(y)
            and abs(x) <= _POSITION_BOUND and abs(y) <= _POSITION_BOUND):
        raise ValueError("Invalid action")
    try:
        ch = int(channel)
    except Exception:
        raise ValueError("Invalid action")
    if not 1 <= ch <= _NUM_CHANNELS:
        raise ValueError("Invalid action")
    return (x, y), ch
