# t6 差分验证报告：源引擎 vs 吸收件引擎（逐位行为等价）

执行者：interface-scout（独立执行者）· 工件：`verification/differential_check.py`
复现：`cd D:\CUMCM2026\src\q3+q4_v2 && python -X utf8 verification/differential_check.py` → **exit 0，3.34 s**
（输出含 `VERDICT: PASS`；本报告所有数字均取自该次实跑，未做任何手工修饰）

## 0. 结论

**PASS。** 在 8 个确定性用例（Q3 四例、Q4 四例，源数 10/12/14/16，误差模式 zero/sine/plus/minus）上，
源包引擎与吸收件引擎的**动作序列、虚拟时长、清除集合、返回 JSON 逐位相同**（JSON 归一化后逐字节相等 8/8）。

同时对 t5 门禁缺失的行为证据给出可直接消费的答案：**被删除的 8 个脚手架文件在 `solve()` 运行路径上零调用**
（§5 因果链 + 三路独立证据）。本报告不修改任何被验证文件。

## 1. 运行方式与环境

| 项 | 值 |
|---|---|
| python / numpy | 3.13.9 (Anaconda) / 2.3.5 |
| numba / scipy / shapely | 0.62.1 / 1.16.3（导入源 Q4 链时实际用到）/ 未参与 |
| 吸收件入口 | `absorbed/q3_v5/q3_optimizer_v5.py`、`absorbed/q4_v4/strategy_v4.py`、`absorbed/q4_v4/locked.py` |
| 源侧入口 | `Q3_Q4_V3/code/src/q3_optimizer_v5.py`、`.../q4_deep_optimization_v4_20260912/strategy_v4.py` |
| 源侧只读性 | 全程 `read/import`，未写入源包任何文件（脚本内无 `open(...,'w')` 指向 SRC） |

**源侧 Q4 导入垫片（独立复现，非采信）**：本机 `import numba` 会先把 site-packages 的 PyPI `coverage`
装进 `sys.modules`，随后源 `candidate.py:8` 的 `from coverage import ...` 拿错模块；预置本地目录则 numba 崩溃。
脚本做法：`import numba` → 用 `importlib.util.spec_from_file_location` 从
`q4_local_optimization_v2_20260912\coverage.py` 加载本地 coverage 并替换 `sys.modules['coverage']` → 再 import strategy_v4。
实跑打印：`coverage: ...\site-packages\coverage\__init__.py -> ...\q4_local_optimization_v2_20260912\coverage.py`。

## 2. 为什么这个 PASS 可信（反空转 + 反证控制）

1. **反空转（anti-vacuity）**：先导入 absorbed 侧并固定入口文件的真实路径，再导入源侧；断言四个入口源码文件分属
   各自树内、且函数对象互不相同。实跑：
   `ported-q3 → ...\absorbed\q3_v5\q3_optimizer_v5.py`、`source-q3 → ...\Q3_Q4_V3\code\src\q3_optimizer_v5.py`，
   Q4 同理。**若吸收件里残留裸顶层 import（如 `from coverage import ...` / `import geometry`），源侧路径会因为
   在 sys.path 中而抢占，比对就退化成"自己比自己"** —— 这条断言专门堵住该情形。
2. **absorbed 侧导入后 `sys.modules` 中不得出现 8 个脚手架顶层名**：实跑 = `无`。
3. **反证控制（falsification control）**：用两个**不同世界**（seed 101 vs 909）的两侧引擎比对，必须被"判为不等"。
   实跑：`检出差异 ✓`，理由
   `动作序列不同（首个不同下标 5，长度 133 vs 140）; 虚拟时长不同：2753.9537... vs 3027.6093...; 清除集合不同; 返回 JSON 不同：$.average_virtual_seconds_per_cleared_source`。
   ⇒ 比对器对差异敏感，8/8 相等不是恒真。
4. **锁参数用源侧 v4 锁**：源侧调用 `strategy_v4.solve(client, **<源 v4 锁 selected_parameters>)`（读源包
   `results/selection_lock.json`），移植侧调用 `locked.solve_locked`；另断言
   `absorbed.locked.LOCKED_PARAMETERS == 源 v4 锁 selected_parameters` → **True**，36 项，
   `version=q4_21station_exact_route_v4`、`selected_name=quarter12`。（未使用 v3 锁。）

## 3. 用例与结果

| # | 用例 | 源动作数 | 移植动作数 | 虚拟时长(s) | 清除 | 返回 JSON | 结论 |
|---|---|---|---|---|---|---|---|
| 1 | q3 seed101 n10 zero | 133 | 133 | 2753.9538 | 10 | 逐字节相等 | PASS |
| 2 | q3 seed202 n12 sine | 124 | 124 | 3136.5734 | 12 | 逐字节相等 | PASS |
| 3 | q3 seed303 n14 plus | 141 | 141 | 3138.7189 | 14 | 逐字节相等 | PASS |
| 4 | q3 seed404 n16 minus | 131 | 131 | 3210.5945 | 16 | 逐字节相等 | PASS |
| 5 | q4 seed101 n10 zero | 281 | 281 | 5869.4563 | 10 | 逐字节相等 | PASS |
| 6 | q4 seed202 n12 sine | 281 | 281 | 6164.4855 | 12 | 逐字节相等 | PASS |
| 7 | q4 seed303 n14 plus | 278 | 278 | 6507.6780 | 14 | 逐字节相等 | PASS |
| 8 | q4 seed404 n16 minus | 255 | 255 | 6505.7733 | 16 | 逐字节相等 | PASS |

覆盖：Q3/Q4 各 4 例（≥3 达标）；源数 10/12/14/16（含 Q3 的 16 源早停）；误差模式 zero/±1/sine
（对应源侧 `plus/minus/zero/sine`，幅值 ≤1° 且同点固定）。Q4 每例含定向与全向两类源（`channel%5!=0` 为定向），
覆盖 `World._act` 的可见性两支。全部 8 例均正常跑完（无异常），无"等价失败"用例。

## 4. "逐位"的定义与比对维度

| 维度 | 判据 |
|---|---|
| 动作序列（含 `/enter`、`/exit`） | 两侧 rows 列表**整表 `==`**（含每行的 `sequence/path/position/channel/response/movement_s/switch_s/operation_s/virtual_before_s/virtual_after_s`）；另断言首行 `/enter`、末行 `/exit` |
| 虚拟时长 | 最终 `client.virtual` **精确相等**（float `==`，非容差比较） |
| 清除集合 | mock 的 `cleared` 集合精确相等 |
| 返回 JSON | numpy→Python、tuple→list、dict 键→str 归一化后 `json.dumps(sort_keys=True)` **逐字节相等**；不等时给出首个差异路径 |
| 异常 | 两侧异常字符串必须相同（本批无异常） |

mock client 语义逐条照抄源包权威实现 `q4_local_optimization_20260912/offline_world.py:21-58`：move=dist/5、
measure +5 s、换频道 +1 s（仅 `/measure` 触发、比较"上一次测量频道"、初值 1）、`/clear` 不换频道、
clear 成功 +5 s / 失败 +3 s、`/enter` `/exit` 不推进；rows 每次 act 追加一行（含 enter/exit），行结构与
`offline_world.py:55-57` 一致。世界确定性由 `numpy.random.default_rng(seed)` 生成，无随机、无 IO。

## 5. 关键问题：8 个未 vendor 脚手架文件删除后，`solve()` 行为是否无差异？

**答：无差异（本报告范围内）。** 因果链如下。

**证据 1 — 源侧确实带着整套脚手架跑**（import 期 `sys.modules`，实跑）：

| 模块 | 状态 | 源文件 |
|---|---|---|
| `bridge_v4` | imported | `q4_deep_optimization_v4_20260912/bridge_v4.py` |
| `bridge` | imported | `q4_uniform_optimization_v3_20260912/bridge.py` |
| `strategy_v3` | imported | `.../q4_uniform_optimization_v3_20260912/strategy_v3.py` |
| `experiments_v3` | imported | `.../q4_uniform_optimization_v3_20260912/experiments_v3.py` |
| `base` | imported | `q4_local_optimization_v2_20260912/base.py` |
| `candidate` | imported | `.../q4_local_optimization_v2_20260912/candidate.py` |
| `experiment` | imported | `.../q4_local_optimization_v2_20260912/experiment.py` |
| `offline_world` | imported | `q4_local_optimization_20260912/offline_world.py` |

**证据 2 — 吸收件侧完全不引入它们**：absorbed 侧导入后 `sys.modules` 中的脚手架顶层名 = `无`。

**证据 3 — 磁盘事实（精确到文件名，修正任务描述的"8 个被删除"表述）**：

| 名字 | 在 `absorbed/q4_v4/` | 说明 |
|---|---|---|
| `bridge.py`、`strategy_v3.py`、`experiments_v3.py` | **不存在** | 4 个文件确被删除 |
| `candidate.py`、`experiment.py`、`offline_world.py` | **不存在** | 同上（`offline_world.py` 只存在于 v1 目录） |
| `bridge_v4.py` | 存在（65 行，源 17 行） | **裁剪派生**，非副本：sha12 `b47186669426` ≠ 源 `0bf92c141f6c` |
| `base.py` | 存在（38 行，源 v3 `bridge.py` 17 行） | **裁剪派生**：sha12 `5909371eafb7` ≠ 源 `1fb23a9c5620`（其源为 v3 `bridge.py`，见 MANIFEST §表） |

⇒ 严格说：**6 个文件被整体删除，2 个（`bridge_v4.py`/`base.py`）以裁剪版保留**。裁剪掉的是
① 实验/校准/gate 链（`strategy_v3`/`experiments_v3`/`candidate`/`v2 experiments`/`v1 candidate+experiments`），
② `WORK/V1/V2/V3*_PARAMETERS` 等只被上述脚本消费的常量，③ import 期 `sys.path` 注入与 deny 卫生代码。
这些名字在 `strategy_v4.solve` 的函数体内**一次都不出现**（`solve` 只用到 `bridge_v4` 导出的 12 个几何/路由名字、
7 个算法子模块，以及 `numpy`/`math`）；`solve_locked` 只做 `solve(client, **LOCKED_PARAMETERS)`。
**因此"删掉它们"不改变 `solve()` 的输入、状态与返回值 —— 与证据 1+2 的动态结果一致。**

**证据 4 — 导入期副作用确有差异，但被正确隔离**：源侧导入后 `socket` 被劫持 = **True**
（`bridge_v4.py:8-9` 等三行 deny 真的执行了）；吸收件导入后 = **False**。即两侧在**导入副作用**上不同
（这正是吸收件必须做的修正），而 **`solve()` 行为**相同。本检查因此只在进程内用 mock 驱动，绝不再走 HTTP。

## 6. 独立发现（1 条，已排除，供 t5/t7 参考）

* **原始文本扫描会对裁剪文件误报 deny**（low / 非缺陷）：`absorbed/q4_v4/bridge_v4.py:55-65` 与
  `base.py:33-38` 各有一段**可执行但自赋值**的卫生登记块：
  `socket.socket=socket.socket`、`socket.create_connection=socket.create_connection`、
  `urllib.request.OpenerDirector.open=urllib.request.OpenerDirector.open`（注释明确写着"本版不执行 deny"）。
  我的三路核对都判为**惰性**：① `ast` 遍历未见任何 `deny` 调用（只有三个自赋值）；② 运行期断言
  `socket` 未被劫持（§5 证据 4）；③ 门禁自身的分类器已把它们归入 `noop`
  （`verification/check_absorbed.py:663-686`：`stub`/`other` 才 FAIL，`noop` 记为
  "inert self-assignment(s) documenting source removals"）。⇒ **无需修复，也不是门禁误报源**；
  仅提示：任何按裸正则扫描 `socket.socket=` 的工具都应复用门禁的 kind 分类或运行期断言。

## 7. 覆盖边界与残余风险（未验证项，如实声明）

* 用例是**内存构造世界**（我的确定性 mock），**不是官方模拟器**；吸收件在官方分布上的行为等价性未证。
* 动态等价只覆盖**锁定配置**（`solve_locked`）与上述 8 例所经过的分支；`solve()` 中由其他参数（如
  `opportunistic=True`、`drop_sites=True`、`cumulative_points>0`、`route='sequential'`）打开的分支未被动态覆盖
  —— 其等价性依据是 MANIFEST 声明的**逐行一致**（静态），本报告不重复主张。
* Q3 侧同样只覆盖 `SELECTED_PARAMETERS`（21 项）这一配置。
* 未做：官方 `--sim http` 端到端、`run_absorbed.py` 的产物比对（属 t4/t7 范围）、哈希实算（本次仅 sha256 前缀核对）。
* 源侧 Q4 导入会**全局劫持 socket**（§5 证据 4）——因此任何在同一进程里导入源 Q4 之后再走 HTTP 的脚本都会失败；
  这是源包特性，不是吸收件缺陷。

## 8. 门禁消费说明（给 t7 的可操作清单）

**关键：门禁不会因为本报告而自动转 PASS。** `verification/check_absorbed.py:878-896` 的终局逻辑是
`fails → FAIL；elif notvend or unproven → INCOMPLETE；else → PASS`，而 8 个未 vendor 文件在闭包检查里被
**永久记为 `NOTVEND`**（`:453-457`，其文案本身就写着 "equivalence must be covered by differential_check.py;
require a written justification in MANIFEST.md"）。该文件**没有任何代码读取本报告或执行本脚本**
（全文件仅有的 `subprocess` 调用是 `:495`/`:549`/`:710` 的内联 socket/import 断言）。

⇒ 门禁原文 `run differential_check.py before reporting PASS` 是**给评审者的指令**，不是自动集成点。
t7 的终值应写成**有据的覆盖判定**，而不是期望门禁自己变绿：

1. 跑 `python -X utf8 verification/differential_check.py` → 期望末行 `VERDICT: PASS`、`exit 0`（约 3.3 s）。
2. 跑门禁 → 期望 `VERDICT: INCOMPLETE` + N 条 `NOTVEND`/`UNPROVEN`；**这不是新增缺陷**，是同一批文件的静态口径。
3. 把每条 NOTVEND 文件对上 §5 证据 3 的磁盘事实（6 个整体缺失 / 2 个裁剪派生，附 sha 前缀与行数）。
4. 确认"未 vendor 的理由"已写进 MANIFEST（门禁 `:456` 的硬要求）：`absorbed/q4_v4/MANIFEST.md` §差异 2
   （`:86-101`）已逐条列出被删 import 及其唯一消费方（未 vendor 的 `experiments_v4.py`/`experiments_v3.py` 等）。
5. 报告措辞：**不要写"门禁 PASS"**；写"门禁 `INCOMPLETE` 的 NOTVEND 行已被本报告的行为等价证据覆盖"，
   并同时给出两个退出码（gate=1、differential=0）。
