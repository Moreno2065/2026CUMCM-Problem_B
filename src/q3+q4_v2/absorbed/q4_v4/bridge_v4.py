"""Read-only reference imports; all new artifacts stay in the v4 workstream.

移植说明（absorbed 版）。本文件与源
Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\bridge_v4.py 的行为差异
**只与本机模块解析和“严格本地内存”卫生代码有关，不触及任何数值行为**：
- 源第 2-5、10-17 行：Path/sys/socket/urllib/json 卫生与 `sys.path.insert` 注入、
  `WORK`/`V3` 常量、`from bridge import *`、`import strategy_v3`、
  `import experiments_v3`。逐条处置见下。
"""
# --- 与源的差异 1（socket 卫生代码停用，保留 HTTP 通路） --------------------
# 源第 8-9 行原样为：
#     def deny(*a,**k):raise RuntimeError('Q4 v4 is local in memory only')
#     socket.socket=deny;socket.create_connection=deny;urllib.request.OpenerDirector.open=deny
# 该代码在 import 期把本进程的 socket / urllib HTTP 通路整体杀掉（urllib →
# http.client → socket.create_connection），会使目标包 v2 运行栈的
# baseline/code/api/client.py（urllib 实现，见其 docstring 第 2 行）在两个模式下全部失效：
#   python run.py --mode q4 --sim http            官方 HTTP 模拟器
#   python run.py --mode q4 --sim http-synthetic  本地 HTTP 全链路演练
# 因此这里**不再执行**上述三行 deny。恢复动作在本文件末尾显式给出。
# 影响面：仅“禁止外部 I/O”这一卫生约束；算法是纯内存几何/组合计算，
# 不发起任何网络调用，故数值行为与源完全一致。
#
# --- 与源的差异 2（实验链死 import 删除） -----------------------------------
# 源第 11-13 行 `from bridge import *`、`import strategy_v3`、`import experiments_v3`
# 在本包改为 `from .bridge import *`：相对 import 已使本地模块身份唯一
# （absorbed.q4_v4.*），源包那个“先 import numba 占住 coverage 名字”的顺序 hack
# 不再需要，故源第 5 行 `import numba` 已删除。
# 同时**删除** `import strategy_v3` 与 `import experiments_v3`：源用它们为
# experiments_v4.py 提供 v3 对照（`params=='v3'`）。这两个模块只被实验脚手架
# （未 vendor）引用，不在 solve() 闭包内；保留它们将迫使本包继续 vendor
# strategy_v3/experiments_v3 及其 v1/v2 世界模拟依赖（含只存在于 V1 目录的
# offline_world.py，以及第二、第三处 socket deny），与“自包含 solver”目标相悖。
# 被删除的名字：V3、V3_PARAMETERS、strategy_v3、v3_strategy、experiments_v3、
# v3_experiments（WORK 仍保留，供未 vendor 的实验入口按需使用）。
#
# --- 与源的差异 3（不做 sys.path 注入） -------------------------------------
# 源第 6-7、10、14-17 行的 WORK/V3 常量、`sys.path.insert(0,str(V3))` 注入与
# `V3_PARAMETERS` 读取已删除；本模块改为纯相对 import，不修改 sys.path。
#
# 相对 import 的必要性：目标包根目录与 baseline\\code 在运行期会被插入 sys.path
# （run.py:29-32、runtime.py:15-18），裸顶层 import（如 `from coverage import ...`）
# 会与目标包自带的顶层 geometry/ 、experiment/coverage.py 等撞名并**静默**解析到
# 错误模块。显式相对 import 使本地 coverage 的身份变为 absorbed.q4_v4.coverage，
# 不再遮蔽 PyPI coverage（本机 numba 0.62.1 导入期需要 PyPI coverage.types，
# 见 numba/misc/coverage_support.py），两种 import 顺序均可导入 —— 比源包更稳，
# 且算法等价（仅改变解析方式）。

from pathlib import Path

from .base import *
from .crossbar import probe_pair

WORK=Path(__file__).resolve().parent

# --- 卫生代码恢复（源第 9 行三行 deny 的对应物） -----------------------------
# 源在导入期执行 socket.socket=deny / socket.create_connection=deny /
# urllib.request.OpenerDirector.open=deny。本版不执行 deny，故**无需恢复**：
# 三个名字保持 site-packages 原值即可。此处显式书写一次，使“恢复”意图可审计、
# 且与源三处被禁用的目标一一对应。注意这必须位于 `from .base import *` 之后：
# 本文件不再传递任何 deny（差异 2 已删除 bridge/strategy_v3/experiments_v3 链，
# 而 .base 已剔除其 import 期 deny，见 base.py 文件头）。
import socket,urllib.request
socket.socket=socket.socket
socket.create_connection=socket.create_connection
urllib.request.OpenerDirector.open=urllib.request.OpenerDirector.open
