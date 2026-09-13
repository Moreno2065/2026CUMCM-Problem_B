# -*- coding: utf-8 -*-
"""socket / urllib 绑定防护：捕获 Q3_Q4_V3 vendored bridge 的全局禁用桩。

背景（源包实测，只读）：

- ``Q3_Q4_V3/workstreams/q4_uniform_optimization_v3_20260912/bridge.py:8-9``
- ``Q3_Q4_V3/workstreams/q4_local_optimization_v2_20260912/base.py:7-8``
- ``Q3_Q4_V3/workstreams/q4_deep_optimization_v4_20260912/bridge_v4.py:8-9``

三处在**导入期**都执行同一段代码（只有异常文本不同）::

    def deny(*a, **k): raise RuntimeError('... is local in memory only')
    socket.socket = deny
    socket.create_connection = deny
    urllib.request.OpenerDirector.open = deny

这是全局副作用：一旦被逐字 vendored，本进程内 ``socket.socket`` 与
``urllib.request`` 全部失效，v2 的 ``ApiClient``（urllib 实现，
``baseline/code/api/client.py:72-88``）与 ``SimulatorHTTPServer``
（``baseline/code/experiment/simulator.py:603-635``）都无法再工作。

本模块只做「观测 + 判定」，**不做任何网络/socket 操作**，也不修改绑定：
在 import 引擎之前记录三个绑定的身份，import 之后再比较身份。身份比较是
唯一可靠的判定（``repr`` 可能被伪造，类型判定会被同名函数绕过）。

规避方式（命中 blocker 时）：
1. 首选由 q4-porter 在 vendored 副本里**停用**这三行（它们是源包「纯离线」
   的自我保护，不是算法语义，停止注入后算法逐行不变）；
2. 次选：用 ``--sim synthetic``（进程内后端，不打开任何 socket）跑通吸收
   验证；但 HTTP 通路仍然不可用，必须在 ``ABSORBED_SOLVERS.md`` 登记。
"""

from __future__ import annotations

import socket
import types
import urllib.request

GUARDED = ("socket.socket",
           "socket.create_connection",
           "urllib.request.OpenerDirector.open")

_FUNCTION_KINDS = ("function", "builtin_function_or_method")


class SocketBindingTampered(RuntimeError):
    """导入 vendored 引擎后，进程级 socket/urllib 绑定被替换。"""


def _bindings():
    """当前三个受保护绑定的句柄（不可 JSON 化，仅用于身份比较）。"""
    return {
        "socket.socket": socket.socket,
        "socket.create_connection": socket.create_connection,
        "urllib.request.OpenerDirector.open":
            urllib.request.OpenerDirector.open,
    }


def _kind(obj):
    if isinstance(obj, type):
        return "class"
    if isinstance(obj, types.FunctionType):
        return "function"
    if isinstance(obj, types.BuiltinFunctionType) or \
            isinstance(obj, types.BuiltinMethodType):
        return "builtin_function_or_method"
    if isinstance(obj, types.MethodType):
        return "method"
    return type(obj).__name__


def _short(obj, limit=120):
    try:
        text = repr(obj)
    except Exception as exc:                      # pragma: no cover
        text = "<repr failed: %r>" % (exc,)
    return text if len(text) <= limit else text[:limit] + "..."


def describe():
    """可 JSON 化的绑定描述（报告用，不含句柄）。"""
    out = {}
    for name, obj in _bindings().items():
        out[name] = {"kind": _kind(obj), "repr": _short(obj), "id": id(obj)}
    return out


def capture():
    """记录句柄快照；返回值只能与 :func:`compare` 配对使用。"""
    return _bindings()


def check_pristine(when):
    """import 之前的断言：三个绑定仍是 stdlib 原物（类/函数），不是 deny 桩。

    返回可 JSON 化的报告 ``{"when", "ok", "problems", "bindings"}``。
    这里用「类型像不像 stdlib 原物」判定，而不是身份，因为此时没有更早的
    基线可比；``deny`` 桩是普通函数，``socket.socket`` 是类，二者不会混淆。
    """
    handles = _bindings()
    problems = []
    kind = _kind(handles["socket.socket"])
    if kind != "class":
        problems.append(
            "socket.socket 在引擎导入前就已被替换（kind=%s repr=%s）"
            % (kind, _short(handles["socket.socket"])))
    for name in GUARDED[1:]:
        kind = _kind(handles[name])
        if kind not in _FUNCTION_KINDS:
            problems.append(
                "%s 在引擎导入前就已被替换（kind=%s repr=%s）"
                % (name, kind, _short(handles[name])))
    return {"when": when, "ok": not problems, "problems": problems,
            "bindings": describe()}


def compare(before, when):
    """import 之后的断言：与 :func:`capture` 的身份快照逐一比较。

    ``before`` 必须是 ``capture()`` 的返回值（句柄 dict）。
    """
    after = _bindings()
    changed = []
    for name in GUARDED:
        old = before.get(name)
        new = after[name]
        if new is not old:
            changed.append({"binding": name,
                            "before": {"kind": _kind(old) if old is not None
                                       else "missing",
                                       "repr": _short(old)},
                            "after": {"kind": _kind(new),
                                      "repr": _short(new)}})
    return {"when": when, "ok": not changed, "changed": changed,
            "bindings": describe()}


def remediation():
    """命中 blocker 时的规避方式（写入 stderr 与 ABSORBED_SOLVERS.md）。"""
    return (
        "vendored bridge 在导入期把 socket.socket / socket.create_connection / "
        "urllib.request.OpenerDirector.open 替换成了 raise 桩：\n"
        "  修复：在 absorbed/q4_v4 的 vendored bridge 副本里删除/停用这三行\n"
        "        （源包 bridge_v4.py:9、bridge.py:9、base.py:8 的 deny 注入），\n"
        "        它们是源包「纯离线」自我保护，与算法数值行为无关；\n"
        "  规避：改用 --sim synthetic（进程内后端，不需要 socket）先跑通吸收验证，\n"
        "        但 HTTP 通路（--sim http / http-synthetic）在本次运行中不可用。\n"
        "  另注：base.py:8 的 denylist 也覆盖 urllib.request.OpenerDirector.open，\n"
        "        因此即使 socket 被恢复，urllib 路径仍会失败，必须一并处理。")
