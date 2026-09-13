"""absorbed/q4_v4 的参考名字汇聚层（对应源 Q3_Q4_V3\\workstreams\\q4_uniform_optimization_v3_20260912\\bridge.py）。

源 bridge.py 的职责是：注入 V1/V2 目录到 sys.path、做“严格本地内存”socket 卫生、
再用 `from base import *` 把 V2 目录的 base.py 里的几何名字上抛给 v3/v4 策略；
它同时把 v1/v2 的世界模拟与实验脚手架（World/v1/reference/V1_PARAMETERS/
V2_PARAMETERS）一并带进 import 图。

本文件**只保留名字汇聚职责**，即转发 local_geometry.py 与 crossbar.py 的导出，
理由与逐条处置见 MANIFEST.md：
- 源第 2-4 行 Path/sys/socket/urllib 卫生与第 8 行 deny()、第 9 行三处 deny 调用
  → 全部删除（会让 v2 的 urllib HTTP 通路失效；算法为纯内存计算，不发起网络调用）。
  bridge_v4.py 文件末尾对本文件未执行的 deny 做了显式“恢复”登记。
- 源第 5-7 行 WORK/V2/V1 常量、第 10 行 `sys.path.insert(0,str(V2))`
  → 删除（改相对 import，不修改 sys.path；相对 import 的必要性见 bridge_v4.py 文件头）。
- 源第 11 行 `from base import *` → `from .base import *`（本包同名文件，
  源解析到 q4_local_optimization_v2_20260912\\base.py）。
- 源第 12-13 行 `import candidate as v2_strategy` / `import experiment as v2_experiment`
  → 删除。二者只为 experiments_v3/v4 的对照配置服务（`params=='v2'`），不在 solve()
  闭包内；保留将连带 vendor v1/v2 世界模拟、只存在于 V1 目录的 offline_world.py，
  以及第二、第三处 socket deny。
- 源第 14-18 行 WORK/V2 常量与 V2_PARAMETERS 读取（读 V2/results/selection_lock.json）
  → 删除。被删名字：V2、V2_PARAMETERS、v2_strategy、v2_experiment、V1、V1_PARAMETERS、
  World、v1、reference。WORK 也一并删除（本文件无使用者；bridge_v4 自建 WORK）。
"""
import socket,urllib.request

from .local_geometry import (ERROR,DirectionBelief,bearing_halfplanes,clip_polygon,exclude_disk,
    initial_polygon,minimum_circle,open_tour,optical_cover,stations_and_triangles)
from .crossbar import probe_pair

# 卫生代码停用登记（源 bridge.py:8-9 原地为）
#     def deny(*a,**k):raise RuntimeError('Q4 v3 is strictly local in memory')
#     socket.socket=deny;socket.create_connection=deny;urllib.request.OpenerDirector.open=deny
# 本版不执行 deny，故上述三处 socket/urllib 名字保持 site-packages 原值；
# 末尾显式书写“恢复”以与源三处被禁用的目标一一对应（见 bridge_v4.py 同款段落）。
socket.socket=socket.socket
socket.create_connection=socket.create_connection
urllib.request.OpenerDirector.open=urllib.request.OpenerDirector.open
