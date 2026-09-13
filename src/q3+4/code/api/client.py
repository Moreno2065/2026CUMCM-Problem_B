# -*- coding: utf-8 -*-
"""HTTP 客户端：urllib 实现，5s 超时，严格请求构造，每次调用写日志。

契约（附件2）：
- POST {base_url}{endpoint}，Content-Type: application/json。
- 必须同时检查 HTTP 状态码与 accepted 字段（本层只搬运，判定在 session）。
- HTTP 400/409/415：读取响应体并原样上交；连接失败（无 JSON 体）标记
  error，由 session 决定是否按幂等键重试。
- 日志：每次调用记录 {time, endpoint, request, response, http_status,
  error}，供 replay / debug / 论文证据。
"""

import time
import urllib.error
import urllib.request

from . import protocol


class ClientReply:
    """一次 HTTP 调用的结构化结果。

    status: HTTP 状态码；连接失败为 None。
    body  : 解析后的 dict；连接失败或非法 JSON 为 None。
    error : 连接/解析错误描述；正常为 None。
    """

    __slots__ = ("status", "body", "error", "raw")

    def __init__(self, status, body, error=None, raw=None):
        self.status = status
        self.body = body
        self.error = error
        self.raw = raw

    @property
    def ok(self):
        return self.status == 200 and self.body is not None

    def __repr__(self):
        return "ClientReply(status=%r, error=%r, body=%r)" % (
            self.status, self.error, self.body)


class ApiClient:
    """官方模拟器 HTTP 客户端（urllib，默认 5s 超时）。"""

    def __init__(self, base_url, timeout=5.0, robot_id="TEAM001",
                 arena_id=protocol.ARENA_ID):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.robot_id = protocol.validate_robot_id(robot_id)
        self.arena_id = arena_id
        self.log = []  # 每次调用的完整日志

    # ------------------------------------------------------------------

    def _url(self, endpoint):
        return self.base_url + endpoint

    def post(self, endpoint, payload):
        """发送一个已构造好的请求体 dict，返回 ClientReply。

        永不抛出网络异常；所有失败都收敛进 ClientReply.error。
        请求构造/编码问题（ProtocolError）仍会抛出——那属于本地 bug。
        """
        data = protocol.encode_request(payload)
        entry = {"time": time.time(), "endpoint": endpoint,
                 "request": payload, "response": None,
                 "http_status": None, "error": None}
        self.log.append(entry)
        req = urllib.request.Request(
            self._url(endpoint), data=data, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            # 400/409/415 等：读取错误体上交
            try:
                raw = e.read()
            except Exception:
                raw = b""
            status = e.code
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            entry["error"] = "connection failed: %s" % e
            return ClientReply(None, None, error=entry["error"])

        entry["http_status"] = status
        try:
            body = protocol.decode_json_strict(raw) if raw else None
        except protocol.ProtocolError as e:
            entry["error"] = "bad response body: %s" % e
            entry["response"] = None
            return ClientReply(status, None,
                               error=entry["error"], raw=raw)
        entry["response"] = body
        return ClientReply(status, body, raw=raw)

    # ------------------------------------------------------------------
    # 便捷方法（请求构造走 protocol 白名单校验）
    # ------------------------------------------------------------------

    def call(self, endpoint, request_id, position=None, channel=None):
        payload = protocol.build_request(
            endpoint, robot_id=self.robot_id, request_id=request_id,
            position=position, channel=channel, arena_id=self.arena_id)
        return self.post(endpoint, payload)

    def enter(self, request_id):
        return self.call("/enter", request_id)

    def measure(self, position, channel, request_id):
        return self.call("/measure", request_id,
                         position={"x": float(position[0]),
                                   "y": float(position[1])},
                         channel=channel)

    def clear(self, position, channel, request_id):
        return self.call("/clear", request_id,
                         position={"x": float(position[0]),
                                   "y": float(position[1])},
                         channel=channel)

    def exit(self, request_id):
        return self.call("/exit", request_id)
