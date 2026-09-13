# -*- coding: utf-8 -*-
"""会话生命周期管理：enter → loop → exit。

职责（附件2 + spec v2.1）：
- 维护 position / current_channel / virtual_time / real_deadline；
- request_id 生成（会话内幂等键，新动作必须用新 id）；
- 仅在网络超时/断连时用相同 request_id + 相同内容重试（有界次数）；
- 同时检查 HTTP 状态码与 accepted；结构错误（400）说明本地请求构造
  有 bug，直接抛 ProtocolError；409 说明幂等键复用冲突，抛 SessionError；
- 通信异常绝不推进本地状态——只有 accepted=true 的响应才更新状态。
"""

import time

from . import protocol


class SessionError(Exception):
    """会话级不可恢复错误（含重试耗尽的通信失败）。"""


class Session:
    """一次测试会话。作为 ActionExecutor 的 HTTP 后端。"""

    MAX_RETRIES = 2          # 网络失败时的同 request_id 重试次数
    RETRY_BACKOFF_S = 0.25   # 第 k 次重试前 sleep k * BACKOFF

    def __init__(self, client, robot_id=None, arena_id=protocol.ARENA_ID):
        self.client = client
        self.robot_id = robot_id or client.robot_id
        self.arena_id = arena_id
        # 会话状态（enter 前为协议初始值）
        self.position = (0.0, 0.0)
        self.current_channel = 1
        self.virtual_time = 0.0
        self.max_virtual_duration_s = 360000.0
        self.max_real_duration_s = 1200.0
        self.real_deadline = None       # wall-clock 截止时间戳
        self.remaining_real_duration_s = None
        self.entered = False
        self.exited = False
        self._req_counter = 0

    # ------------------------------------------------------------------
    # request_id / 发送
    # ------------------------------------------------------------------

    def new_request_id(self):
        self._req_counter += 1
        rid = "%s-%06d" % (self.robot_id, self._req_counter)
        return protocol.validate_request_id(rid)

    def _send(self, endpoint, request_id, position=None, channel=None):
        """发送 + 重试 + 状态码/响应校验，返回规范化响应 dict。

        - 连接失败：相同 request_id + 相同内容重试 ≤ MAX_RETRIES 次；
        - HTTP 400/415：本地请求构造 bug → ProtocolError；
        - HTTP 409：幂等键冲突 → SessionError；
        - HTTP 200：protocol.validate_response 后返回（accepted 可能
          为 false，由调用方按业务拒绝处理，不更新状态）。
        """
        attempt = 0
        while True:
            if position is None:
                reply = self.client.call(endpoint, request_id)
            else:
                reply = self.client.call(
                    endpoint, request_id,
                    position={"x": float(position[0]), "y": float(position[1])},
                    channel=channel)
            if reply.error is not None and reply.status is None:
                # 纯连接失败：允许同 id 同内容重试
                if attempt < self.MAX_RETRIES:
                    attempt += 1
                    time.sleep(self.RETRY_BACKOFF_S * attempt)
                    continue
                raise SessionError("connection failed after %d attempts: %s"
                                   % (attempt + 1, reply.error))
            if reply.status in (400, 415):
                raise protocol.ProtocolError(
                    "%s rejected as malformed (HTTP %d): %r"
                    % (endpoint, reply.status, reply.body))
            if reply.status == 409:
                raise SessionError(
                    "request_id conflict (HTTP 409) on %s id=%s"
                    % (endpoint, request_id))
            if reply.status != 200:
                raise SessionError("unexpected HTTP status %r on %s"
                                   % (reply.status, endpoint))
            if reply.body is None:
                raise SessionError("empty/invalid JSON body on %s"
                                   % endpoint)
            return protocol.validate_response(endpoint, reply.body)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def enter(self):
        if self.entered:
            raise SessionError("enter called twice")
        resp = self._send("/enter", self.new_request_id())
        if not resp["accepted"]:
            raise SessionError("enter not accepted: %r" % resp)
        self.entered = True
        self.max_virtual_duration_s = resp["max_virtual_duration_s"]
        self.max_real_duration_s = resp["max_real_duration_s"]
        self.remaining_real_duration_s = resp["remaining_real_duration_s"]
        # 用响应里的 remaining 而不是假定 1200
        self.real_deadline = time.time() + self.remaining_real_duration_s
        if "position" in resp:
            self.position = (resp["position"]["x"], resp["position"]["y"])
        else:
            self.position = (0.0, 0.0)  # 协议初始位置
        if "channel" in resp:
            self.current_channel = resp["channel"]
        else:
            self.current_channel = 1    # 协议初始频道
        self.virtual_time = resp["virtual_time_s"]  # enter 不推进，应为 0
        return resp

    def measure(self, position, channel):
        """accepted=true 时推进 position / current_channel / virtual_time。"""
        self._require_open("/measure")
        resp = self._send("/measure", self.new_request_id(),
                          position=position, channel=channel)
        if resp["accepted"]:
            self.position = (float(position[0]), float(position[1]))
            self.current_channel = int(channel)
            self.virtual_time = resp["virtual_time_s"]
        return resp

    def clear(self, position, channel):
        """accepted=true 时推进 position 与 virtual_time；/clear 不切频道。"""
        self._require_open("/clear")
        resp = self._send("/clear", self.new_request_id(),
                          position=position, channel=channel)
        if resp["accepted"]:
            self.position = (float(position[0]), float(position[1]))
            self.virtual_time = resp["virtual_time_s"]
        return resp

    def exit(self):
        if not self.entered or self.exited:
            raise SessionError("exit called out of order")
        resp = self._send("/exit", self.new_request_id())
        if resp["accepted"]:
            self.exited = True
            self.virtual_time = resp["virtual_time_s"]
        return resp

    # ------------------------------------------------------------------

    def _require_open(self, endpoint):
        if not self.entered or self.exited:
            raise SessionError("%s outside of an open session" % endpoint)

    def real_time_exceeded(self):
        return self.real_deadline is not None \
            and time.time() > self.real_deadline

    def virtual_time_exceeded(self):
        return self.virtual_time > self.max_virtual_duration_s
