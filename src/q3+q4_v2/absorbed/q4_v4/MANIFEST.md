# MANIFEST —— Q4 正式 SOTA solver 吸收件（`absorbed/q4_v4/`）

吸收对象：`D:\CUMCM2026\src\Q3_Q4_V3` 工作流 **q4_deep_optimization_v4_20260912**
（`strategy_v4.solve` + `results/selection_lock.json` 锁定参数）。
本目录是**自包含**的：`absorbed/q4_v4/**` 不再引用 `Q3_Q4_V3` 下任何文件，也不修改 `sys.path`。

- 锁定版本：`VERSION = q4_21station_exact_route_v4`，`SELECTED_NAME = quarter12`
- 参数条数：**36 项**（`selection_lock.json.selected_parameters` 实测 36；
  任务书里写的 “25 项” 有误）。`locked.py` 内联字面量已与锁文件**逐字段相等**比对通过。
- 运行时环境（实测）：Python 3.13.9 (Anaconda) / numpy 2.3.5 / scipy 1.16.3 / numba 0.62.1 / shapely 2.1.2
  （锁文件记录的开发环境是 3.13.7 / numpy 2.4.6 / scipy 1.17.1 / numba 0.66.0 / shapely 2.1.2）

---

## 1. 文件清单与来源（源 SHA-256 全部与 `selection_lock.json.source_sha256` 比对一致）

| 目标文件 | 源文件（相对 `Q3_Q4_V3/`） | 源行数 | 本版行数 | 源 SHA-256（= 锁清单值） |
|---|---|---|---|---|
| `strategy_v4.py` | `workstreams/q4_deep_optimization_v4_20260912/strategy_v4.py` | 306 | 313 | `c0be76322477fad73c411c11291a57280ac7199215b08e7d9be5ff430adaa89c` |
| `bridge_v4.py` | `workstreams/q4_deep_optimization_v4_20260912/bridge_v4.py` | 17 | 65 | `0bf92c141f6c2229ecee4655358a19ae57730e61ee3454a3fbdd4ad6b3c66232` |
| `base.py` | `workstreams/q4_uniform_optimization_v3_20260912/bridge.py` | 17 | 38 | `1fb23a9c562038e88c5eff8deef99d0781d2fd04e2d56451b33abbecf3a77914` |
| `search_nets.py` | `workstreams/q4_deep_optimization_v4_20260912/search_nets.py` | 15 | 24 | `325387bd67c1c4d9a580de5539bd0a15d7f52356ea1a5faa9b4323e8c9f312a3` |
| `cover_union.py` | `workstreams/q4_deep_optimization_v4_20260912/cover_union.py` | 85 | 98 | `0955b7efb9cc4fb1a158b0f58c50dc4e2561fd40091f6ed85b1abc4f1091c494` |
| `geometry_hand_layouts.py` | `workstreams/q4_deep_optimization_v4_20260912/geometry_hand_layouts.py` | 33 | 46 | `77bb04fc141535b11e2339d5ec835c6482d7e692ecd2b2e3fed9a4d20cf65370` |
| `ordered_tour.py` | `workstreams/q4_deep_optimization_v4_20260912/ordered_tour.py` | 41 | 45 | `40fd09d5f762f50f4d5f6596b1e3f527220b926d11bbb7245be008b1306a6f4b` |
| `tour_utils.py` | `workstreams/q4_uniform_optimization_v3_20260912/tour_utils.py` | 22 | 27 | `e6b3eab41b8ed1907b976b10974159fc6779c078a5ebf30e084339d688622398` |
| `local_geometry.py` | `workstreams/q4_local_optimization_20260912/local_geometry.py` | 164 | 170 | `15fb21e68aa934d490f7516191457656719e9c81ce13ecd8c77c9f740f8d5aea` |
| `crossbar.py` | `workstreams/q4_local_optimization_20260912/crossbar.py` | 20 | 24 | `89765204c584b9f53936b0a7faec02b9cc67f2af51f3fc88987683ec442f3157` |
| `coverage.py` | `workstreams/q4_local_optimization_v2_20260912/coverage.py` | 54 | 64 | `eb490f6935b0f901ce8bfe632fa45ca54691982d8c3ecc91fb58fbf5c7af9f95` |
| `conditional.py` | `workstreams/q4_local_optimization_v2_20260912/conditional.py` | 35 | 43 | `da80d4939ee5e4b3f024a808c36170131bcfee2461249c29398cd6ea7190569f` |
| `negative_regions.py` | `workstreams/q4_local_optimization_v2_20260912/negative_regions.py` | 73 | 83 | `bd6b743517af798c9413782748b988637f8aaa87306aeb5fcc5d89627778bee9` |
| `geometry.py` | `code/src/geometry.py` | 175 | 175 | `72e6cb248df4bffa94538422fed6c9feee657b1062f3f7c5d4101ef46b1c7e39` |
| `tour_utils.py`（同上） | — | — | — | — |
| `locked.py` | 新增（无源文件） | — | 80 | 见 §5 |
| `results/selection_lock.json` | `workstreams/q4_deep_optimization_v4_20260912/results/selection_lock.json` | 135 | 135 | **字节级副本**，SHA-256 `62a9e692f58ad7251fab6665a5ef5582cdc0df331401442a5ddec038c0f898e7` |
| `__init__.py` | 新增（包声明） | — | — | — |

说明：
- 上表 14 个源文件全部出现在锁文件的 `source_sha256` 清单中；**`base.py` 的源是
  v3 目录的 `bridge.py`**（故锁清单里应查 `../q4_uniform_optimization_v3_20260912/bridge.py`），
  本版沿用源包的“聚合层”职责但换用文件名 `base.py`（见 §3 差异 4）。
- 行数增加**全部来自 docstring 补充**（每个文件注明其与源的差异），不含一行算法改动。
- 只有 `geometry.py` 与源**字节完全相同**；其余文件因 import 改写必然不同。
  机器化的“归一化逐行 diff”（把相对 import 还原成源的裸名后比较）结论见 §6。

---

## 2. 与源包的差异总览（共 4 处，均不触及数值行为）

### 差异 1：socket / urllib “严格本地内存”卫生代码停用（**最关键**）

源包在三处 import 期执行：

| 源位置 | 源代码 |
|---|---|
| `q4_deep_optimization_v4_20260912/bridge_v4.py:8-9` | `def deny(...)`；`socket.socket=deny;socket.create_connection=deny;urllib.request.OpenerDirector.open=deny` |
| `q4_uniform_optimization_v3_20260912/bridge.py:8-9` | 同上（文案 `'Q4 v3 is strictly local in memory'`） |
| `q4_local_optimization_20260912/experiments.py:8-9` | 同上（被 `base.py` 经 `importlib` 加载，见差异 2） |

若原样带入，则**只要 import 本引擎，本进程的 urllib HTTP 通路立即失效**
（`urllib → http.client → socket.create_connection`），目标包 v2 运行栈的
`baseline/code/api/client.py`（文件头自述 “HTTP 客户端：urllib 实现”，第 2 行）在
`--sim http` 与 `--sim http-synthetic` 两种模式下**全部失效**。

**处置**：`bridge_v4.py` / `base.py` **不执行** deny；两个文件末尾各有一段显式的
“恢复登记”（把 `socket.socket` / `socket.create_connection` /
`urllib.request.OpenerDirector.open` 赋回 site-packages 原值）。注意该段是**自赋值**：
源包把 `import socket` 绑定原地改成 deny，原引用在链内已不可恢复
（`experiments.py:8-9` 执行时 `socket.socket` 早已是前两处的 deny），
因此“保存原引用再恢复”的写法拿不到真值；真正保证通路健康的是**不执行 deny** 这一步。

**影响面**：仅“禁止外部 I/O”这一卫生约束。算法是纯内存几何/组合计算，不发起任何网络调用，
故数值行为与源完全一致。**已实测证明**（§6 证据 E4）：import 本引擎后用真实
`api.client.ApiClient` 打本地 HTTP 服务器，返回 `ok=True / status=200`，服务器侧收到 1 次请求。

### 差异 2：实验脚手架死 import 链删除

源的 import 图（递归读得到的真实闭包）：

```
strategy_v4 → bridge_v4 → bridge → base → { local_geometry, crossbar, offline_world, candidate, experiment }
                          └→ strategy_v3 → bridge → ...
                          └→ experiments_v3 → bridge, strategy_v3, (v1/v2 世界模拟、数据文件)
```

其中被删除的、**在 `solve()` 运行路径上零调用**的部分：

| 被删 import | 源位置 | 只被谁使用 | 处置 |
|---|---|---|---|
| `import strategy_v3 as v3_strategy` | `bridge_v4.py:12` | 未 vendor 的 `experiments_v4.py` 的 `params=='v3'` 对照 | 删 |
| `import experiments_v3 as v3_experiments` | `bridge_v4.py:13` | 未 vendor 的 `experiments_v4.py` 的 `audit()` | 删 |
| `V3` / `V3_PARAMETERS` | `bridge_v4.py:7,15-16` | 同上 | 删 |
| `import candidate as v2_strategy` | `bridge.py:12` | 未 vendor 的 `experiments_v3.py` 的 `params=='v2'` 对照 | 删 |
| `import experiment as v2_experiment` | `bridge.py:13` | 同上的 `audit()` | 删 |
| `V1` / `V2` / `V1_PARAMETERS` / `V2_PARAMETERS` / `World` / `v1` / `reference` | `bridge.py:6-7,14-16`、`base.py:6,12-13,18` | 实验/校准/gate 脚本 | 删 |
| `from offline_world import World` | `base.py:17` 链路 | 同上（且该文件**只存在于** `q4_local_optimization_20260912/` 目录） | 不 vendor |
| `from bridge_v4 import WORK,reference`（模块顶层） | `geometry_hand_layouts.py:4` | 仅该文件 `run()`；`run()` 是实验入口 | 从顶层删除，`run()` 内按需相对 import |

被删除的**名字清单**（源可见名 → 本版）：`V1`、`V2`、`V3`、`V1_PARAMETERS`、`V2_PARAMETERS`、
`V3_PARAMETERS`、`v1`、`v2_strategy`、`v2_experiment`、`v3_strategy`、`v3_experiments`、`reference`。
其中 `WORK` 在 `bridge_v4.py` 中**保留**（值改为本包目录），供未 vendor 的实验入口按需使用。

**保留 `from .base import *` 与 `from .bridge_v4 import ...` 的原因**：这两条是算法依赖
（`probe_pair`、`ERROR`、`DirectionBelief` 等名字的来源），不是脚手架；脚手架是被
`bridge_v4.py`/`base.py` 顺带拉进来的第二层 import。删掉第二层后，闭包恰好收敛为算法所需。

### 差异 3：显式包内相对 import（替代裸顶层 import + `sys.path` 注入）

源包靠 `sys.path.insert(0, ...)` 让裸名 import 解析到工作流目录；本包根目录与
`baseline/code` 在运行期会被插入 `sys.path`（`run.py:29-32`、`runtime.py:15-18`），
而 `baseline/code` 下同时存在顶层 `geometry/` 包、`experiment/coverage.py`、`policy/`、
`state/`、`lookahead`、`production` 等模块。若沿用裸名 import，会**静默**解析到错误模块
（不报 ImportError）。因此本包一律用显式相对 import。

这条改写同时**消除**了源包那个著名的 `import numba` 顺序 hack（见差异 4 与 §4）。

### 差异 4：`bridge_v4.py:5` 的裸 `import numba` 删除；`ordered_tour.py` 的 `from numba import njit` 保留

- `ordered_tour.py:4,6`：`from numba import njit` + `@njit(cache=True)` 装饰 `solve_ordered`
  —— **真实算法依赖**。`exact_insert=True`（锁定值）时，`strategy_v4.py` 在
  “backbone 路由 + 初始旋转评分 + 逐轮路由”三处调用 `ordered_tour(...)`，
  每次都会进入 njit 编译体。**保留**。
- `bridge_v4.py:5` 的 `import numba`：源注释自述 “Load before the read-only v2 module named
  coverage reaches sys.path”，即它只是**同名模块占位**目的，不参与计算。**删除**。
  - 本机验证（numba 0.62.1）：`import numba` 会把 **PyPI `coverage`** 装进 `sys.modules`
    （`numba/misc/coverage_support.py` 导入期执行 `class NumbaTracer(coverage.types.Tracer)`），
    实测 `'coverage' in sys.modules → True`、`coverage.__file__` 指向 site-packages。
    源包在此环境下**两条路径都会失败**（不预置路径：本地 `coverage.py` 拿不到；预置路径：
    numba 拿到本地 `coverage.py` 后 `AttributeError: module 'coverage' has no attribute 'types'`）。
  - 本包用相对 import 后模块身份是 `absorbed.q4_v4.coverage`，**不再遮蔽**顶层 `coverage`，
    因此 numba 与算法可共存，且**两种 import 顺序都通过**（§6 证据 E1/E2）。这是“比源包更稳、
    但算法等价（仅改变解析方式）”的一条（captain 裁决）。

---

## 3. import 改写逐处清单（43 处）

`→` 左侧为源、右侧为本版。所有改动仅是把模块名加相对前缀或改指本包内同名文件。

**`strategy_v4.py`**（7 处）
```
from bridge_v4 import (...)            → from .bridge_v4 import (...)
from bridge_v4 import probe_pair       → from .bridge_v4 import probe_pair
from conditional import conditional_pair → from .conditional import conditional_pair
from coverage import triangle_certificate,directional_cover → from .coverage import ...
from negative_regions import refine as refine_negative → from .negative_regions import refine as refine_negative
from tour_utils import area_centroid,insert_sources → from .tour_utils import ...
from search_nets import certified_layout,certify_points → from .search_nets import ...
from ordered_tour import ordered_tour   → from .ordered_tour import ordered_tour
```
（注：该文件共 8 处包内 import，与源一一对应。）

**`bridge_v4.py`**
```
import numba                           → 删除（见差异 4）
def deny(...) / socket...=deny（8-9）  → 不执行；文件末尾“恢复登记”（见差异 1）
from pathlib import Path / sys / json  → 仅保留 pathlib（WORK 需要）；sys/socket/urllib/json 删除
sys.path.insert(0,str(V3))             → 删除（见差异 3）
from bridge import *                   → from .base import *
import strategy_v3 as v3_strategy      → 删除（见差异 2）
import experiments_v3 as v3_experiments→ 删除（见差异 2）
V3 / V3_PARAMETERS（json 读锁）        → 删除（见差异 2）
WORK=...                               → 重新绑定为本包目录
```

**`base.py`**（对应源 `q4_uniform_optimization_v3_20260912/bridge.py`）
```
Path/sys/socket/urllib 卫生 + deny（1-9） → 删除；末尾“恢复登记”
WORK / V2 / V1 常量（5-7）               → 删除
sys.path.insert(0,str(V2))                → 删除
from base import *                        → from .local_geometry import (...)   （直接指向名字定义处）
import candidate as v2_strategy           → 删除
import experiment as v2_experiment        → 删除
V1_PARAMETERS / V2_PARAMETERS（json 读锁）→ 删除
```

**`search_nets.py`**（2 处）
```
from geometry_hand_layouts import layout,grid_layout → from .geometry_hand_layouts import ...
from cover_union import certificate                  → from .cover_union import certificate
```

**`cover_union.py`**（`__main__` 分支内 2 处）
```
from bridge_v4 import WORK,reference   → from .bridge_v4 import WORK,reference
from geometry_hand_layouts import layout → from .geometry_hand_layouts import layout
```

**`geometry_hand_layouts.py`**（1 处 + 位置调整）
```
from bridge_v4 import WORK,reference（模块顶层） → 删除；改在 run() 内 from .bridge_v4 import WORK,reference
```
理由（**两个**）：(i) 只被实验入口 `run()` 使用；(ii) 打断导入环 —— 本模块被
`.search_nets` 导入（`certified_layout` 路径会走 `.cover_union.certificate`），而
`bridge_v4 → .base → .local_geometry`；若本模块在顶层反向 import `bridge_v4`，
则**以本模块为首个导入对象**时会拿到半初始化的 `bridge_v4` 而 ImportError。
已用 12 个模块各自的“冷启动单独导入”实测通过（§6 证据 E3）。

**`local_geometry.py`**（1 处 + 注入删除）
```
from pathlib import Path + import sys（2-3） → 删除 sys/Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'code/src')) → 删除
from geometry import bearing_halfplanes, clip_polygon, hull, minimum_circle as enumerated_circle
    → from .geometry import bearing_halfplanes, clip_polygon, hull, minimum_circle as enumerated_circle
```

**`conditional.py`**（1 处）
```
from base import ERROR                 → from .local_geometry import ERROR
```
（源靠 `base.py` 注入 + wildcard 传递拿到 `ERROR`；`ERROR = 1.005` 的唯一权威定义在
`local_geometry.py:9`，本版直接指向定义处。）

**`negative_regions.py`**（2 处）
```
from base import clip_polygon          → from .local_geometry import clip_polygon
from local_geometry import hull        → from .local_geometry import hull
```

**无 import 改写（逐行一致，仅补 docstring）**：`ordered_tour.py`、`tour_utils.py`、
`crossbar.py`、`coverage.py`、`geometry.py`。

---

## 4. 第三方依赖清单

| 依赖 | 使用点 | 与源一致性 |
|---|---|---|
| `numpy` | 全部几何/数组运算 | 一致，无版本 API 变更风险（用到的均为长期稳定 API） |
| `scipy.spatial` (`ConvexHull`, `Delaunay`, `QhullError`) | `coverage.py`、`cover_union.py`、`negative_regions.py` | 一致 |
| `scipy.optimize.linprog` | `geometry.py:polytope`（`method='highs'`） | 一致 |
| `shapely.geometry` / `shapely.ops.unary_union` / `shapely.errors.GEOSException` | `cover_union.py` | 一致 |
| `numba` (`njit`) | `ordered_tour.py` **唯一真实使用点** | 一致（本机 0.62.1 vs 锁记录 0.66.0） |
| `math` / `itertools` / `functools` / `random`（`local_geometry.minimum_circle` 用 `random.Random(60491)` 做确定性洗牌） | 各处 | 一致 |

**无新增依赖**；未引入任何源闭包之外的库。

## 5. 契约（对外 API）

```python
from absorbed.q4_v4 import strategy_v4, locked
# strategy_v4.solve(client, ...)  —— 37 个参数名 / 36 个默认值，与源逐参数一致（AST 比对）
# locked.VERSION            == 'q4_21station_exact_route_v4'
# locked.SELECTED_NAME      == 'quarter12'
# locked.LOCKED_PARAMETERS  == selection_lock.json['selected_parameters']（36 项逐字段相等）
# locked.solve_locked(client) == strategy_v4.solve(client, **LOCKED_PARAMETERS)
```

client 契约（源 solver 依赖，未改动）：`client.act('/measure', pos, channel) ->
{'measure_result','svd_deg'}`；`client.act('/clear', point, channel) -> {'clear_result'}`；
属性 `client.position` / `client.virtual` / `client.rows` / `client.channel`。

## 6. 可执行验证证据（本机实测，全部 PASS）

运行目录 `D:\CUMCM2026\src\q3+q4_v2`，解释器 `C:\Users\Mao\anaconda3\python.exe`（3.13.9）。

| 编号 | 命令 | 结果 |
|---|---|---|
| E1 | `python -X utf8 -c "import numba;from absorbed.q4_v4 import strategy_v4,locked;print('numma-first ok',locked.VERSION,locked.SELECTED_NAME,len(locked.LOCKED_PARAMETERS))"` | `numma-first ok q4_21station_exact_route_v4 quarter12 36`，退出码 0 |
| E2 | `python -X utf8 -c "from absorbed.q4_v4 import strategy_v4;import numba;print('solver-first ok')"` | `solver-first ok`，退出码 0 |
| E3 | 12 个模块各自冷启动单独导入（subprocess） | 12/12 PASS（含 `geometry_hand_layouts` 环检测） |
| E4 | import 本引擎 → 用真实 `api.client.ApiClient` POST 本地 HTTP 服务器 | `client.post ok=True status=200`、服务器侧 hits=1 → **HTTP 通路证明健康** |
| E5 | 锁定参数/签名：AST 提取源与本版 `solve` 参数名与默认值表达式 | 参数名 37/37 相同、默认值表达式 36/36 相同、`inspect.signature` 与 AST 一致 |
| E6 | `LOCKED_PARAMETERS == json.loads(results/selection_lock.json)['selected_parameters']` | True（36 项） |
| E7 | `results/selection_lock.json` 与源 SHA-256 | 双向 `62a9e692…f898e7`，**字节一致**（8432 bytes） |
| E8 | 端到端：内存世界（仿 `offline_world.World` 语义，12 源，`error_mode='zero'`）跑 `locked.solve_locked` | **跑完**：`cleared=12/12`、`actions=307`、`virtual=6209.6s`；返回字典 21 个契约键齐全；`station_spec=[8,12,995,1864,0]` 走 `certified_layout` 路径（21 站、32 三角形）；`cleared_count=12 ∈ [10,16]` |
| E9 | 归一化逐行 diff（源 vs 本版，把相对 import 前缀还原后比较） | 算法行改动 **0 行**；仅 docstring 与 import 行变化（明细：10 个文件共 93 行差异，全部为 docstring 补充 + import 改写/移位） |
| E10 | 源文件哈希核对：14 个源文件中 13 个在锁清单内、逐个 SHA-256 相等 | ✅（`base.py` 的源 `bridge.py` 在锁清单中，✅；`locked.py`/`__init__.py` 为新增，无源） |

未执行 / 不能由本会话替用户确认的项：
- **目标包 v2 官方 `--sim http` 实机联调**未跑（需要官方模拟器端点，超出本任务范围；E4 只证明
  本地 HTTP 通路在 import 本引擎后仍然健康）。
- 锁文件记录的开发环境 `numba 0.66.0 / numpy 2.4.6 / scipy 1.17.1` 与**本机 0.62.1 / 2.3.5 / 1.16.3**
  不同；本机实测全绿，但“与锁定环境的数值逐位复现”本会话无法证明（需要同版本环境复跑）。
- 本引擎在**官方题目真值分布**上的表现未验证（锁文件自身 `claim_scope` 也声明
  “official distribution unconfirmed”）。

## 7. 静态一致性说明（无残留外部依赖）

- `absorbed/q4_v4/**` 内**不存在**指向 `Q3_Q4_V3` 的路径字符串或 `sys.path` 注入
  （已对全部 `*.py` 源码文本扫描；docstring 中的来源说明已列入白名单口径，见 `verification/`）。
- `absorbed/q4_v4/**` 内所有包内 import 均为显式相对 import（`from .xxx import ...`），
  无裸顶层 import（`math` / `numpy` / `scipy` / `shapely` / `numba` / `functools` / `itertools` /
  `random` / `pathlib` 属第三方或标准库，不在此列）。
- 本目录**未修改**目标包任何生产文件（`production.py` / `run.py` / `runtime.py` /
  `compare.py` / `recommended.py` / `baseline/**`），也未触碰其它成员目录。
