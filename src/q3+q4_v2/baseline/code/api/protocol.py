# -*- coding: utf-8 -*-
"""协议层：请求/响应 JSON 的构造、编码与严格解析校验（附件2 通信协议）。

冻结事实（附件2 为准）：
- 4 端点：POST /enter /measure /clear /exit；HTTP+JSON；
  Content-Type: application/json（仅允许 charset=utf-8 参数）。
- 请求体：UTF-8 无 BOM、无重复键、≤ 65536 字节。
- 公共字段：arena_id="default"，robot_id（1..64 字节 ASCII），
  request_id（会话内幂等键，1..128 字节）。
- 响应公共字段：accepted, real_timestamp_ms, virtual_time_s。
  accepted=false 时只有这 3 个字段，且 virtual_time_s 为 0（不可当当前时刻）。
- virtual_time_s 为浮点（最多 6 位小数），禁止按整数解析。
- /measure 请求：{position:{x,y}, channel:int}；channel 必须 1..20 整数
  （1.0 可，1.5 拒）；|x|,|y| ≤ 2e6 且有限。
- /measure 响应：measure_result ∈ {no_signal, near, direction}；
  direction 时带 svd_deg（两位小数，[0,360)）。
- /clear 响应：clear_result ∈ {success, no_target_in_range}。
- /enter 响应：max_virtual_duration_s / max_real_duration_s /
  remaining_real_duration_s。
- /exit 响应：exit_reason。
- 未声明字段（请求侧）⇒ HTTP 200 + accepted=false（服务端行为）；
  本模块对请求构造与响应解析都做字段白名单校验，尽早暴露偏差。
- JSON 重复键 ⇒ 结构错误；解析时用 object_pairs_hook 检测并抛错。
"""

import json
import math

ARENA_ID = "default"
MAX_REQUEST_BYTES = 65536
NUM_CHANNELS = 20
POSITION_BOUND = 2.0e6

ENDPOINTS = ("/enter", "/measure", "/clear", "/exit")

COMMON_REQUEST_FIELDS = ("arena_id", "robot_id", "request_id")
ENDPOINT_EXTRA_FIELDS = {
    "/enter": (),
    "/measure": ("position", "channel"),
    "/clear": ("position", "channel"),
    "/exit": (),
}

MEASURE_RESULTS = ("no_signal", "near", "direction")
CLEAR_RESULTS = ("success", "no_target_in_range")

# 响应白名单（accepted=true 时，公共字段之外允许出现的字段）
_RESPONSE_REQUIRED = {
    "/enter": ("max_virtual_duration_s", "max_real_duration_s",
               "remaining_real_duration_s"),
    "/measure": ("measure_result",),
    "/clear": ("clear_result",),
    "/exit": ("exit_reason",),
}
_RESPONSE_OPTIONAL = {
    "/enter": ("position", "channel"),
    "/measure": ("svd_deg",),
    "/clear": (),
    "/exit": (),
}
_COMMON_RESPONSE_FIELDS = ("accepted", "real_timestamp_ms", "virtual_time_s")


class ProtocolError(Exception):
    """协议结构/字段违规（请求构造侧 bug 或响应不符合契约）。"""


class DuplicateKeyError(ProtocolError):
    """JSON 文本中存在重复键。"""


# ---------------------------------------------------------------------------
# 请求字段校验
# ---------------------------------------------------------------------------

def _has_control_or_invisible(text):
    """t10 校准（附件2 §5.1）：robot_id/request_id 不能包含控制字符或
    不可见格式字符（Unicode 类别 Cc/Cf，含 ASCII 控制区与 DEL）。
    可见空格 (U+0020) 允许；零宽/双向格式符 (Cf) 拒绝。"""
    for ch in text:
        if ch == " ":
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            return True
        import unicodedata
        if unicodedata.category(ch) in ("Cc", "Cf"):
            return True
    return False


def validate_robot_id(robot_id):
    if not isinstance(robot_id, str):
        raise ProtocolError("robot_id must be str")
    try:
        raw = robot_id.encode("ascii", "strict")  # 非 ASCII 抛错
    except UnicodeEncodeError:
        raise ProtocolError("robot_id must be ASCII")
    if not (1 <= len(raw) <= 64):
        raise ProtocolError("robot_id must be 1..64 bytes ASCII")
    if _has_control_or_invisible(robot_id):
        raise ProtocolError("robot_id must not contain control or invisible "
                            "format characters")
    return robot_id


def validate_request_id(request_id):
    if not isinstance(request_id, str) or not request_id:
        raise ProtocolError("request_id must be non-empty str")
    if not (1 <= len(request_id.encode("utf-8")) <= 128):
        raise ProtocolError("request_id must be 1..128 bytes")
    if _has_control_or_invisible(request_id):
        raise ProtocolError("request_id must not contain control or "
                            "invisible format characters")
    return request_id


def validate_channel(channel):
    """channel 必须 1..20 整数；接受 1.0 这类整数值浮点，拒绝 1.5。"""
    if isinstance(channel, bool):
        raise ProtocolError("channel must be int in 1..%d" % NUM_CHANNELS)
    if isinstance(channel, float):
        if not channel.is_integer():
            raise ProtocolError("channel must be integral, got %r" % channel)
        channel = int(channel)
    if not isinstance(channel, int):
        raise ProtocolError("channel must be int in 1..%d" % NUM_CHANNELS)
    if not (1 <= channel <= NUM_CHANNELS):
        raise ProtocolError("channel out of range: %r" % channel)
    return channel


def validate_position(position):
    """position = {"x": .., "y": ..}；|x|,|y| ≤ 2e6 且有限。"""
    if not isinstance(position, dict):
        raise ProtocolError("position must be an object")
    if set(position.keys()) != {"x", "y"}:
        raise ProtocolError("position must have exactly keys {x, y}")
    out = {}
    for k in ("x", "y"):
        v = position[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ProtocolError("position.%s must be a number" % k)
        v = float(v)
        if not math.isfinite(v) or abs(v) > POSITION_BOUND:
            raise ProtocolError("position.%s out of bounds: %r" % (k, v))
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# 请求构造与编码
# ---------------------------------------------------------------------------

def build_request(endpoint, robot_id, request_id, position=None, channel=None,
                  arena_id=ARENA_ID):
    """构造并校验请求体 dict。字段顺序固定：公共字段在前。"""
    if endpoint not in ENDPOINTS:
        raise ProtocolError("unknown endpoint %r" % endpoint)
    validate_robot_id(robot_id)
    validate_request_id(request_id)
    if arena_id != ARENA_ID:
        raise ProtocolError("arena_id must be %r" % ARENA_ID)
    req = {"arena_id": arena_id, "robot_id": robot_id,
           "request_id": request_id}
    extras = ENDPOINT_EXTRA_FIELDS[endpoint]
    if "position" in extras:
        if position is None:
            raise ProtocolError("%s requires position" % endpoint)
        req["position"] = validate_position(position)
    if "channel" in extras:
        if channel is None:
            raise ProtocolError("%s requires channel" % endpoint)
        req["channel"] = validate_channel(channel)
    return req


def encode_request(req):
    """dict → UTF-8 bytes（无 BOM）；超 65536 字节抛错。"""
    data = json.dumps(req, ensure_ascii=True, separators=(",", ":")
                      ).encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        raise ProtocolError("request body exceeds %d bytes" % MAX_REQUEST_BYTES)
    return data


# ---------------------------------------------------------------------------
# 严格 JSON 解析（重复键检测 / BOM 拒绝）
# ---------------------------------------------------------------------------

def _no_duplicate_object(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise DuplicateKeyError("duplicate JSON key: %r" % k)
        obj[k] = v
    return obj


def decode_json_strict(data):
    """严格解析 JSON 文本为 dict：拒绝 BOM、重复键、非对象顶层。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ProtocolError("JSON body must not carry a BOM")
    try:
        obj = json.loads(data.decode("utf-8"),
                         object_pairs_hook=_no_duplicate_object)
    except DuplicateKeyError:
        raise
    except (ValueError, UnicodeDecodeError) as e:
        raise ProtocolError("invalid JSON body: %s" % e)
    if not isinstance(obj, dict):
        raise ProtocolError("JSON body top level must be an object")
    return obj


# ---------------------------------------------------------------------------
# 响应校验
# ---------------------------------------------------------------------------

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v)


def validate_response(endpoint, resp):
    """校验并规范化响应 dict。

    - 公共字段必须存在且类型正确；
    - accepted=false ⇒ 只允许 3 个公共字段，virtual_time_s 必须为 0；
    - accepted=true ⇒ 按端点白名单校验必需/可选字段；
    - 返回规范化后的 dict（不修改原 dict）。
    """
    if endpoint not in ENDPOINTS:
        raise ProtocolError("unknown endpoint %r" % endpoint)
    if not isinstance(resp, dict):
        raise ProtocolError("response must be an object")
    for f in _COMMON_RESPONSE_FIELDS:
        if f not in resp:
            raise ProtocolError("response missing common field %r" % f)
    accepted = resp["accepted"]
    if not isinstance(accepted, bool):
        raise ProtocolError("accepted must be bool")
    if not _is_number(resp["real_timestamp_ms"]):
        raise ProtocolError("real_timestamp_ms must be a finite number")
    vt = resp["virtual_time_s"]
    if not _is_number(vt) or vt < 0:
        raise ProtocolError("virtual_time_s must be a non-negative number")
    vt = float(vt)  # 浮点语义，禁止当整数解析

    if not accepted:
        extra = set(resp.keys()) - set(_COMMON_RESPONSE_FIELDS)
        if extra:
            raise ProtocolError(
                "accepted=false response must carry only the 3 common "
                "fields, got extra %r" % sorted(extra))
        if vt != 0.0:
            raise ProtocolError(
                "accepted=false response must have virtual_time_s == 0")
        return {"accepted": False,
                "real_timestamp_ms": resp["real_timestamp_ms"],
                "virtual_time_s": 0.0}

    allowed = set(_COMMON_RESPONSE_FIELDS) | set(_RESPONSE_REQUIRED[endpoint]) \
        | set(_RESPONSE_OPTIONAL[endpoint])
    unknown = set(resp.keys()) - allowed
    if unknown:
        raise ProtocolError("response has undeclared fields %r for %s"
                            % (sorted(unknown), endpoint))
    missing = [f for f in _RESPONSE_REQUIRED[endpoint] if f not in resp]
    if missing:
        raise ProtocolError("response missing fields %r for %s"
                            % (missing, endpoint))

    out = dict(resp)
    out["virtual_time_s"] = vt

    if endpoint == "/enter":
        for f in _RESPONSE_REQUIRED["/enter"]:
            if not _is_number(resp[f]) or resp[f] < 0:
                raise ProtocolError("%s must be a non-negative number" % f)
            out[f] = float(resp[f])
        if "channel" in resp:
            out["channel"] = validate_channel(resp["channel"])
        if "position" in resp:
            pos = resp["position"]
            # enter 响应的 position 允许为数组 [x, y] 或对象 {x, y}
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                pos = {"x": pos[0], "y": pos[1]}
            out["position"] = validate_position(pos)

    elif endpoint == "/measure":
        mr = resp["measure_result"]
        if mr not in MEASURE_RESULTS:
            raise ProtocolError("bad measure_result %r" % mr)
        if mr == "direction":
            if "svd_deg" not in resp:
                raise ProtocolError("direction result must carry svd_deg")
            svd = resp["svd_deg"]
            if not _is_number(svd) or not (0.0 <= svd < 360.0):
                raise ProtocolError("svd_deg out of range: %r" % svd)
            svd = float(svd)
            # 保留两位小数：|svd - round(svd,2)| 必须极小
            if abs(svd - round(svd, 2)) > 1e-9:
                raise ProtocolError("svd_deg must carry at most 2 decimals: "
                                    "%r" % svd)
            out["svd_deg"] = round(svd, 2)
        elif "svd_deg" in resp:
            raise ProtocolError("svd_deg only allowed with direction result")

    elif endpoint == "/clear":
        cr = resp["clear_result"]
        if cr not in CLEAR_RESULTS:
            raise ProtocolError("bad clear_result %r" % cr)

    elif endpoint == "/exit":
        if not isinstance(resp["exit_reason"], str):
            raise ProtocolError("exit_reason must be str")

    return out
