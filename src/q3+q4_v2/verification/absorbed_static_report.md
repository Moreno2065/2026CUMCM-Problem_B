# absorbed/ 独立验证报告（t5 · 进行中）

- 验证者：verifier（独立校验，不实现功能）
- 目标包：`D:\CUMCM2026\src\q3+q4_v2`（唯一写入地点：`verification\`）
- 源包（只读）：`D:\CUMCM2026\src\Q3_Q4_V3`
- 本轮时间：2026-09-13 04:30Z 起（生产基线冻结于 `04:30:03.808050Z`）
- 重要前提：**t2/t3/t4 在本次验证期间尚未标记完成，`absorbed/` 仍在落盘中**。
  本报告是**中期结论**；最终判决必须等三项实现任务完成、且 `differential_check.py` 与
  http-synthetic 冒烟跑过之后重跑 `check_absorbed.py` 才能给出。

## 0. 证据分类约定（本报告严格遵守）

| 类别 | 含义 |
|---|---|
| **已实跑通过** | 本机真实执行（`python` 子进程 / 脚本），观察到输出，命令与结果可复现 |
| **已静态确认** | 读源码 / AST / 哈希得到，未执行 |
| **未验证 / 需用户运行** | 尚未取得证据，**不得**按 PASS 报出 |

环境更正：本会话 `pwsh`、`python 3.13.9 (Anaconda, MSC v.1929 64bit)`、`glob`、`grep`
**全部可用**（与最初的交接说明相反）。因此本报告的多数结论是**实跑证据**，不是纸面推断。

---

## 1. 源侧契约（锚点）— 已实跑 + 已静态确认

### 1.1 生产基线冻结（最先完成，赶在 absorbed 落盘之前）

`verification\production_hashes_before.json`，冻结于 **2026-09-13T04:30:03.808050+00:00**：

| 文件 | sha256（前 16） | 大小 |
|---|---|---|
| production.py | `638bce2240a56d91…` | 8 396 B |
| run.py | `14c479355e158be2…` | 66 791 B |
| runtime.py | `fd92820e0f3f189e…` | 38 610 B |
| compare.py | `95f8736815c650bd…` | 5 435 B |
| recommended.py | `0b9299e3567862b9…` | 2 220 B |

同时冻结了**全部 11 个顶层 .py** 与 **`baseline/**` 共 138 个文件**的逐文件 sha256
（清单摘要 `manifest_sha256 = 023ccd12bfe1b686…`），排除 `__pycache__` / `*.pyc`。

### 1.2 Q4 的硬溯源锚点（比文件比对更强）

`workstreams/q4_deep_optimization_v4_20260912/results/selection_lock.json` 内含
`source_sha256` 表。**实跑核验：现盘 `strategy_v4.py` 与 `bridge_v4.py` 的 sha256
与锁表逐字节吻合**（`c0be7632…`、`0bf92c14…`）→ 源包自锁定以来未被改动，
可用作「吸收件是否移植了锁定版本」的判据。

锁定参数：`version=q4_21station_exact_route_v4`、`selected_name=quarter12`、
36 个 `selected_parameters`，与 `strategy_v4.solve` 签名逐键对应，其中
**15 个与签名默认值不同**（吸收时最易静默漂移的位置）：

`route=joint`、`share=true`、`radio_limit=12`、`crossbar=true`、`crossbar_offset=0.03`、
`crossbar_fraction=0.25`、`conditional_range=true`、`route_mode=backbone`、
`negative_regions="disk"`、`crossbar_reference=latest`、`stop_when_found16=true`、
`scan_current_first=true`、`station_spec=[8,12,995,1864,0]`、`exact_insert=true`、
`initial_rotation_steps=12`。

### 1.3 闭包（AST 解析，可复现）

- **Q3 = 9 文件**：`q3_optimizer_v5.py`、`practice_single_source.py`、`q3_optimizer_v4.py`、
  `geometry.py`、`second_point.py`、`practice_all_sources_fast.py`、`q2_adopted.py`、
  `legacy_second_point.py`、`practice_all_sources.py`；外部仅 numpy/scipy + 标准库。
- **Q4 = 20 文件**（含 v3 的 `bridge/strategy_v3/experiments_v3/tour_utils`、v2 的
  `base/candidate/experiment/conditional/coverage/negative_regions`、v1 的
  `crossbar/offline_world/local_geometry`、v4 的 `strategy_v4/bridge_v4/search_nets/
  ordered_tour/geometry_hand_layouts/cover_union`、`code/src/geometry.py`）。
- **Q3 没有 selection_lock.json**（`q3_joint_tour_20260912/results` 为空、
  `code/run_q3_v5_offline.py` 依赖的 `results/q3_joint_tour_v5/fresh_validation.json`
  在磁盘上不存在）→ Q3 无哈希锚点，等价性只能靠 AST + 差分。
- 源侧三处 socket 劫持的实际位置（读码确认，非推测）：
  `q4_deep…v4/bridge_v4.py:9`、`q4_uniform…v3/bridge.py:9`、`q4_local…v2/base.py:8`；
  三者互为 import 链（`bridge_v4 → from bridge import * → from base import *`）。

---

## 2. 逐项验证结果

| 项 | 内容 | 结论 | 证据类别 |
|---|---|---|---|
| a | AST 等价（Q3 9 文件 + Q4 20 文件） | 15 文件级相同、6 定义级相同、8 有意未 vendored、0 未解析 | 已静态确认 |
| b | import 冒烟（两种顺序 + 两种组合顺序） | 4/4 单引擎 + 2/2 组合（Q3→Q4、Q4→Q3）全通过 | **已实跑通过** |
| c | 锁定参数（v4 锁 vs v3 锁） | 36/36 与 **v4** 锁一致；≠ v3 锁；随包 lock 逐字节相同 | 已静态确认 |
| d | socket 原生性 | 无任何有效 deny 注入；6 处为惰性自赋值；运行期身份保持 | **已实跑通过** + 已静态确认 |
| e | 裸顶层 import | 引擎包内 0 处；适配层 9 处为**设计使然**（绑定 v2 栈） | 已静态确认 |
| f | 生产路径未被改动 | **与基线完全一致**（11 + 138 文件） | **已实跑通过** |
| g | http-synthetic 冒烟 | **未完成** | 未验证 |
| h | Q3 差分 | **未完成**（源侧可跑已实测，见 §3） | 未验证 |
| i | 导入期副作用 | 引擎模块干净、无模块级网络调用；F1 临时脚本已由 q4-porter 删除 | 已静态确认 |

### 2.1 项 a 细节（AST 等价的实测口径）

方法：`ast.parse` → 用 `NodeTransformer` 删除全部 `Import/ImportFrom` 节点 →
再删 docstring → `ast.dump(annotate_fields=False)` 取 sha256 作指纹；源与本包
双向匹配；无整文件孪生时，退化为**逐顶层定义**匹配。

- 文件级相同（15）：`q3_v5/{geometry_src, second_point, q2_adopted, legacy_second_point}.py`；
  `q4_v4/{strategy_v4, conditional, coverage, negative_regions, tour_utils, search_nets,
  ordered_tour, geometry_hand_layouts, cover_union, crossbar}.py` 与
  `q3_v5/geometry_src.py`（同时被 Q3/Q4 闭包引用）。其中 14 项带 **[lock-hash verified]**。
- 定义级相同（6）：`q3_optimizer_v5.py`、`q3_optimizer_v4.py`、`q4_v4/local_geometry.py`
  等——模块文件本身被重写（去掉 `sys.path` 注入、改相对 import、合并），但**每个顶层
  定义都能在 absorbed/ 内找到 AST 完全相同的孪生**。
- 有意未 vendored（8）：v4 `bridge_v4.py`、v3 `bridge.py/strategy_v3.py/experiments_v3.py`、
  v2 `base.py/candidate.py/experiment.py`、v1 `offline_world.py`。
  **验证者独立确认这些确实只是脚手架**（不是算法）：v2 `base.py`（19 行）是纯胶水——
  第 8 行 deny、第 10-13 行 `load()` 动态加载 v1 的 strategy/experiments、第 14-16 行
  `from local_geometry import …` / `from crossbar import probe_pair`、第 17 行
  `from offline_world import World`、第 18 行读 v1 锁表。真正承载几何与 crossbar 的两个
  文件（`local_geometry.py`、`crossbar.py`）**都已 AST 级完整 vendored**，
  因此 solve() 的名字来源没有缺口。
- 3 处「有意不搬的定义」由验证者逐个读过并登记在 `check_absorbed.py::DEF_ALLOWLIST`：
  `PracticeClient`（源第 12-14 行，**只 raise**「Simulator clients are disabled」）、
  两个 `main()`（离线 CLI 入口，不在 solve() 调用图内）。

### 2.2 项 b / d 细节（头号回归风险，实跑证据）

- `import absorbed.q4_v4.strategy_v4` 与 `import absorbed.q3_v5.q3_optimizer_v5`，
  在 **numba 先 / numba 后** 两种顺序下均成功（各 0.7 s），且 import 前后
  `socket.socket`、`socket.create_connection`、`urllib.request.OpenerDirector.open`
  三个绑定的**身份未变**。
- 对 `127.0.0.1:1` 实连返回 `TimeoutError`（原生行为），**不是** deny 桩的
  `RuntimeError`。
- 对照实验（源包，同一台机）：`import strategy_v4` 之后三个绑定**全部被替换**
  （`socket=False conn=False opener=False`）→ 证明该风险真实存在，且吸收件确实消除了它。
- 静态层面：`absorbed/q4_v4/base.py:36-38` 与 `bridge_v4.py:63-65` 保留了
  `socket.socket = socket.socket` 形式的**惰性自赋值**（把当前值赋回同名），
  行为上无副作用，作用是登记「源侧三行 deny 已停用」。验证者确认它们**不改变任何绑定**。

### 2.3 项 e 细节

引擎包（`absorbed/q3_v5`、`absorbed/q4_v4`）内**零**裸顶层 import，全部走包内相对导入；
因此 `baseline/code/geometry/` 这个真撞名不会劫持吸收件的解析。
适配层（`absorbed/adapters/*.py`）有 9 处裸导入 `api/executor/experiment/runtime/verifier`
——这是**适配层存在的目的**（桥到 v2 运行栈），命中 captain 的 high 判据但其性质是
「有意绑定」，需要的是**运行期确认解析到目标包内**而非删除。这一点记入 §4 待办。

---

## 2.4 调用图可达性（captain 新增必查项 — 不信命名，只信调用图）

工具：`verification/oracle_callgraph.py`（AST 名字级可达性，不执行源码）。
方法：从 `strategy_v4.solve` 与 `q3_optimizer_v5.solve_optimized_v5` 出发，逐个名字
解析到定义处，`from X import *` 递归展开到真正定义该名字的模块；**可达性有意过近似**
（宁可多判「需要」，绝不漏判）。随后要求每个可达名字在 absorbed/ 内存在 AST 全等定义。

**结果（实跑）：`reachable_files=14, zero_call=40, missing_defs=0`**

- **`missing_defs = 0`** —— solve() 路径上可达的每一个定义，在 absorbed/ 内都有
  AST 全等孪生。这是「删掉的文件确实没被间接调用」的正面证据。
- 可达文件 14 个：Q3 三个（`code/src/geometry.py`、`q3_optimizer_v4.py`、`q3_optimizer_v5.py`）
  + Q4 十一个（`strategy_v4`、`local_geometry`、`crossbar`、`conditional`、`coverage`、
  `negative_regions`、`tour_utils`、`search_nets`、`ordered_tour`、`geometry_hand_layouts`、
  `cover_union`）。
- 锁表 52 个文件中 **40 个在 solve() 路径上零调用**。
- **与 F2 的 8 个「未 vendored」文件交叉核对**：`bridge_v4`、`bridge`、`strategy_v3`、
  `experiments_v3`、`base`、`candidate`、`experiment`、`offline_world`
  **全部落在调用图判定的零调用集合内** —— 两条独立方法（导入闭包 AST 比对 + 名字级调用图）
  给出同一结论，故 F2 由「仅凭命名/文档判断」升级为**有调用图证据的删除**。
- 修正说明：分析器第一版曾因未展开 `from base import *` 的再导出而把
  `local_geometry`/`crossbar` 误判为零调用（属**不安全方向**的低估），已修复后重跑；
  现版本会把 `bridge_v4 → bridge → base → local_geometry → geometry` 整条再导出链解开，
  这也解释了 `code/src/geometry.py` 为何出现在 Q4 锁表里。
- 口径提醒：`zero_call` 仅表示「没有定义出现在 solve() 路径上」；模块级 import 仍需成立
  （absorbed 已把相关模块级 import 一并改写为包内相对导入，见 §2.3）。

---

## 3. 源侧可运行性实测（为 h/i 铺路）

| 引擎 | 源侧能否导入 | 条件 | 证据 |
|---|---|---|---|
| Q3 | **能** | `code/`、`code/src/`、`workstreams/q3_joint_tour_20260912` 入 sys.path | 已实跑 |
| Q4 | **能** | 先 `import numba`，再用 `spec_from_file_location` 从 v2 目录加载本地 `coverage.py` 覆盖 `sys.modules['coverage']`，再 import `strategy_v4` | 已实跑 |

- Q4 源侧 `solve()` **端到端跑通**（锁定参数、真实案例）：
  `q4_v4_uniform_n10_978000` → 10/10 源清除、`total_s=5858.945`、313 actions、**1.5 s**；
  `q4_v4_uniform_n11_978001` → 11/11 清除、`total_s=5892.949`、269 actions、<0.1 s。
  → **差分验证在成本上完全可行**（秒级/例），无需以「太重」为由跳过。
- 驱动方式（与源 `experiments_v4.py:46-48` 一致）：`w=World(case); c=w.client;
  c.act('/enter'); r=solve(c, **locked_params); c.act('/exit')`。
- Q3 无案例数据（workstream `data/` 与 `results/` 均不存在），需用
  `code/tests/verify_q3_all_sources.py` 内的 `World` 类 + 确定性种子**自建**案例；
  两侧引擎喂同一世界，任何分歧都是真实行为差异。

---

## 3.5 生产基线（recommended 路线）— 独立复测并冻结

工具：`verification/oracle_smoke_matrix.py`（新增 `recommended` 腿），
冻结产物：**`verification/baseline_recommended_frozen.json`**（20 局，含每局**精确命令**、
完整 `metrics.json` 与 `run_report.json` 摘要、原始字节数）。

命令形态（每局独立进程 + 进程内 socket preflight）：
`python -X utf8 recommended.py --mode Q3|Q4 --seed S --n-sources N --output <dir>`
（注意 `recommended.py` 的产物在**下一级**目录 `<dir>/{mode}_{seed}_{n}_{scenario}/`；
未指定 `--scenario` 时 Q3 默认 `random`、**Q4 默认 `mixed`**，与 captain 的命令一致。）

**captain 四个 seed=101 数字的独立复现（同一世界、同 seed、同源数）——全部吻合：**

| 规模 | captain 报告(3dp) | 验证者实测 | 结论 |
|---|---|---|---|
| Q3 n=10 | 456.708 | 456.7076019177168 | 吻合 |
| Q3 n=16 | 280.502 | 280.5022176603166 | 吻合 |
| Q4 n=10 | 650.599 | 650.5989700901541 | 吻合 |
| Q4 n=16 | 456.758 | 456.7576880043957 | 吻合 |

5 个 seed（101–105）的 `T_per_source_s` 区间：Q3 n=10 **349.3–471.5**、Q3 n=16 **276.0–309.2**、
Q4 n=10 **647.1–730.0**、Q4 n=16 **302.1–456.8**。
→ **seed 间波动很大（Q3 n=10 达 ±18%）**，因此吸收引擎与基线的比较**必须同 seed 配对、
多 seed 覆盖**；单 seed 结论不可用。

**口径与边界（captain 要求显式注明）**：本次合成世界分布是**构造假设，不是官方 TSP 分布**；
结论**只覆盖「同一合成世界、同一 seed、同一源数」下的相对比较**，不能外推为对官方赛题分布的
性能断言。吸收引擎的数字必须等 t2/t3/t4 落地后在**同一 sim 配置与 seed** 下测量才可比。

---

## 3.6 端到端复测与「吸收 vs 生产基线」对照（t5 核心结论）

### 3.6.1 captain 两条命令的独立复现 — 逐字段一致

`absorbed/run_absorbed.py --sim http-synthetic --engine q3-v5|q4-v4`，我独立重跑：

| 字段 | Q3/q3-v5 你报告 | Q3 我实测 | Q4/q4-v4 你报告 | Q4 我实测 |
|---|---|---|---|---|
| complete | true | true | true | true |
| cleared | 10 | 10 | 10 | 10 |
| verifier_all_ok | true | true | true | true |
| T_per_source_s | 293.483 | 293.4833054 | 597.279 | 597.2794101 |
| measures | 120 | 120 | 298 | 298 |
| switches | 111 | 111 | 281 | 281 |
| clear success/attempts | 10/11 | 10/11 | 10/12 | 10/12 |
| engine_version | q3_joint_search_clear_route_v5 | 同 | q4_21station_exact_route_v4 | 同 |

`wall_clock_s` 是墙钟，随负载浮动（1.15/1.97 vs 我 1.50/2.08），**不作为一致性判据**。

### 3.6.2 多 seed 矩阵（40 局，0 失败）

`T_per_source_s`（5 seeds：101–105；每局独立进程 + 进程内 socket preflight）：

| 模式 | n | 引擎 | mean | P90 | max | min |
|---|---|---|---|---|---|---|
| Q3 | 10 | **absorbed** | **279.24** | 289.34 | 293.48 | 255.21 |
| Q3 | 10 | recommended | 417.57 | 465.60 | 471.53 | 349.26 |
| Q3 | 16 | **absorbed** | **184.66** | 197.37 | 198.28 | 163.17 |
| Q3 | 16 | recommended | 289.33 | 304.95 | 309.19 | 275.97 |
| Q4 | 10 | **absorbed** | **592.28** | 621.08 | 636.95 | 554.42 |
| Q4 | 10 | recommended | 674.23 | 711.70 | 730.05 | 647.05 |
| Q4 | 16 | **absorbed** | **328.27** | 365.14 | 370.44 | 250.43 |
| Q4 | 16 | recommended | 356.45 | 431.40 | 456.76 | 302.08 |

同 seed 配对降幅（负号=吸收更低）：Q3/10 **−32.7%**（5/5 胜）、Q3/16 **−36.1%**（5/5 胜）、
Q4/10 **−11.9%**（5/5 胜）、**Q4/16 −6.1%，但仅 2/5 胜**。

> **必须随结论一起给出的限制**：Q4/16 的均值优势由少数 seed 拉动，逐 seed 看基线赢 3/5；
> 5 个 seed 下 P90≈max（小样本，P90 退化）。因此「Q4/16 更优」目前**不稳健**，
> 若要对外声称需扩到 ≥20 seeds；Q3 两档与 Q4/10 的结论在 5 seed 下 5/5 一致，较稳健。

### 3.6.3 口径声明（captain 要求显式写入）

- 两侧跑在**同一 v2 合成世界**：同 seed、同源数、同场景；场景约定 **Q3→`random`、Q4→`mixed`**
  （与 `recommended.py:40` 一致，也与我冻结的基线一致）。
- 结论**只覆盖同一合成世界下的相对比较**，**不声称官方 TSP 分布上的性能**；
  合成分布是构造假设。
- **分母口径**：`T_per_source_s = T_total_virtual / 源数`。合成/http-synthetic 模式下分母取自
  **合成真值**（可知）；官方模式下初始源数不可知，只能用 `cleared_count` 作为分母并标注
  basis——即 `run.py::_augment_per_source_metrics` 的 hidden-count 边界写法
  （`sources_total=None` 时把 `average_time_per_source_s` 写回 `t_per_source_s` 并附 `t_per_source_basis`）。
  本报告所有数字均为合成模式，分母可知。

### 3.6.4 产物内 verifier_report 结构核查（captain 第 5 项）

`runs/_captain_absorbed_q3|q4/verifier_report.json` 实测结构：
`all_ok / counts / checks(list) / not_performed / scope / socket_guard / v2_verifier_reuse / engine_meta / client_snapshot / unresolved_channels`。

| 项 | Q3 局 | Q4 局 |
|---|---|---|
| counts | total 18 / passed 18 / failed 0 / skipped 0 | total 17 / passed 17 / failed 0 / skipped 0 |
| checks 逐项 | 18 项全 True | 17 项全 True |
| not_performed | 1 项：`q3_continuous_cover_replay`（附理由） | 1 项：`q4_certificate_replay`（附理由） |
| scope | 193 字符，**显式说明 `not_applicable` 语义** | 同 |
| socket_guard | `before.ok=true`，记录三绑定 kind/repr | 同 |
| v2_verifier_reuse | `verify_q3_cover=used`、`verify_mec_covers=used`、`GameRunner._verify=not_reusable（依赖 KnowledgeState）` | 同 |

**结论与限制**：结构自描述、逐项 ok、未执行项**均带理由**（不是静默跳过）。
但两点必须如实说明：
1. **是否「符合 §6.3 规格」我无法判定**——我手上没有 §6.3 条文（UNPROVEN）。请给条文或路径，我按条对齐。
2. `not_performed` 表明 **verifier 不复用引擎内部的 Q3 连续覆盖证书 / Q4 Δθ 证书判定**，
   即验证器在这两处依赖引擎自判——这是已被记录的范围限制，用户应知晓。

---

## 4. findings（缺陷交回，不由验证者修改他人文件）

### F1 — `absorbed/_selftest_q4.py` 是包内未加保护的执行脚本（medium）— **已关闭（RESOLVED）**

- 事实：该文件位于包内（`absorbed/_selftest_q4.py`），有 21 处模块级语句在
  **导入期**执行（含 `from absorbed.q4_v4 import strategy_v4, locked`、`socket.socket(...)`
  实例化、`for` 循环），没有 `if __name__ == '__main__'` 保护；其中 2 处被判定为
  模块级网络/socket 使用。
- 但文件自身第 8 行写明「存放位置为临时……验证后由 q4-porter 删除」，且其"网络使用"
  实为**绑定健康检查**（实例化一个 socket 再关闭），并非真实联网。
- requiredFix：交付前**删除**该文件（其自述即为临时件）；若必须保留，则移出包内
  或加 `__main__` 保护，使 `import absorbed._selftest_q4` 无副作用。
- **处置结果**：q4-porter 已删除该文件；验证者复跑门禁确认
  `Test-Path` → REMOVED，且项 i 不再产生任何 FAIL（本轮复跑：0 FAIL）。
  关闭依据是**实跑复验**，非口头确认。

### F2 — 8 个「未 vendored」闭包文件缺少行为等价证据（medium，待差分覆盖）

- 事实：v4 `bridge_v4.py`、v3 `bridge.py/strategy_v3.py/experiments_v3.py`、
  v2 `base.py/candidate.py/experiment.py`、v1 `offline_world.py` 在 absorbed/ 内
  既无文件孪生也无定义孪生。验证者已独立确认它们对本引擎是脚手架（见 §2.1），
  但**AST 证据对它们不存在**。
- requiredFix：由 `differential_check.py`（Q4 逐例逐位比对 source vs absorbed）
  覆盖；并在 `MANIFEST.md` 中逐文件写明删除理由。在此之前，这些文件的等价性
  只能标注为「未验证」。

### F3 — 适配层 9 处裸顶层 import 需运行期确认解析目标（low）

- `adapters/runtime_bridge.py:73↦executor, :74↦experiment, :81/:82/:93/:94↦api,
  :140↦runtime`；`adapters/absorbed_verifier.py:64/:70↦verifier`。
- 性质：有意绑定 v2 栈，但 `experiment`/`verifier` 在目标包内存在多个同名候选
  （`baseline/code/experiment/`、`baseline/code/verifier/` 等），必须确认解析到预期模块。
- requiredFix：运行期断言每个名字的 `sys.modules[name].__file__` 落在目标包内预期路径
  （CAPTAIN 可要求一条 smoke 断言），或改为显式路径导入。

---

## 5. 已确认无问题（避免下游重复排查）

- **生产路径未被改动**：11 个顶层 .py + 138 个 `baseline/**` 文件全部与 04:30:03Z 基线一致。
- **socket 回归风险已被消除**：实跑证明两种 import 顺序下三绑定保持原生，实连行为正常。
- **锁定参数保真**：36 个字段全等；随包的 `q4_v4/results/selection_lock.json` 与源锁表逐字节相同。
- **引擎包无撞名导入**：`geometry` 等真撞名不会影响 absorbed/q3_v5 与 absorbed/q4_v4。
- **无导入期网络操作**：引擎模块内无模块级 socket/urllib 调用（唯一命中项在 F1 的临时脚本里）。

---

---

## 5.5 验证目标版本（冻结）+ 差分结果 + 最终判决

### 5.5.1 我验证的是哪一版 —— **⚠ 两次声明的指纹都与磁盘不符（traceability 未达成）**

验证者对下列文件**自行计算 sha256 与行数**（不采信任何一方的口头指纹）：

| 文件（`absorbed/` 下） | 我实测行数 | 我实测 sha256 | captain 第二轮声明 | 判定 |
|---|---|---|---|---|
| `run_absorbed.py` | 564 | `46a8d69736c91937416740d3d44c368c` | 564 行 / `594f66dd…` | **行数一致、哈希不符** |
| `adapters/absorbed_verifier.py` | **623** | `9b24086e3830761cc4969fc05e79c049` | 563 行 / `dac55de9…` | **行数与哈希均不符** |
| `adapters/runtime_bridge.py` | 309 | `854a08e4c791450adbe60c0a395bc195` | `854a08e4…` | 哈希一致（行数差 1，工具口径） |
| `adapters/v3_client.py` | 289 | `eff9cb0ff37e8acbe56dc9e14c1bb814` | `eff9cb0f…` | 哈希一致（行数差 1） |
| `adapters/socket_guard.py` | 150 | `58ab848e5991ba6c14de4ad8fb3847de` | `58ab848e…` | 哈希一致（行数差 1） |
| `ABSORBED_SOLVERS.md` | **266** | `8588f4c0282cbf8402e94d7fe5e7a228` | 211 行 / `d4b8b971…` | **行数与哈希均不符** |

- `ABSOLVED_SOLVERS.md`（captain 文中的拼写）在盘上**不存在**；正式名 `ABSORBED_SOLVERS.md`。
- **行数口径说明**：本报告行数一律用 `text.splitlines()`；captain/adapter-eng 用
  `bytes.count(b"\n")+1`，因文件以换行结尾而**恒差 1**（如 564 vs 565、623 vs 624、266 vs 267）。
  **sha256 才是内容判据**，行数仅作辅助定位；此前若干轮的口径争议均源于此，非内容差异。
- 三个「哈希一致但行数差 1」的文件属**计数工具口径差异**，非内容差异（哈希为准）。
- **两个文件的内容无法与任何一次声明对上**：`run_absorbed.py`（哈希）与 `absorbed_verifier.py`、`ABSORBED_SOLVERS.md`（行数+哈希）。
  其中 `absorbed_verifier.py` 我实measured **623 行**，恰好等于我早前逐行审阅过的版本（§4 F-D 分析所用），
  说明**盘上即我已审阅的修订**，而第二轮声明的 563 行/`dac55de9…` 与磁盘不符。
- **对结论的影响**：行为类证据（差分 8/8、冒烟、指标逐位不变）**由实跑得出、不依赖指纹**，仍然成立；
  但「验证的是哪一版」这一**可追溯性要求未达成**——在磁盘与冻结声明一致之前，本报告**不能声称**
  对某个指纹版本完成了验证。两次声明（adapter-eng 一次、captain 一次）均被实测推翻。

（captain 声明已对本目标下冻结令；上述不符说明**冻结未在磁盘上生效或测量口径有误**，需澄清后才可锁定版本。）

### 5.5.2 差分（h/i）— 行为等价证据

`verification/differential_check.py` 由 **interface-scout（t6）** 撰写并落盘；验证者**未改写该文件**，
改为**运行并审查其等价性是否有意义**。⚠ 独立性口径：该脚本不是验证者自研；其作者未写过
`absorbed/` 代码（captain 指派时以此保证独立性），但仍**不等于**验证者独立实现的第二份差分。

实跑 `python -X utf8 verification/differential_check.py` → **exit=0**：

- **8/8 用例逐位相同**：Q3 4 例（n=10/12/14/16）+ Q4 4 例（同规模），四种误差模式 zero/sine/plus/minus。
  两侧**动作序列 / 虚拟时长 / cleared 集合 / 返回 JSON 逐字节相等**。
- **反证控制成立（关键）**：脚本自带 seed101 vs seed909 的「期望判为不等」对照，成功检出差异并
  报出首个不同下标（133 vs 140）、虚拟时长（2753.95 vs 3027.61）、cleared 集合差异与具体 JSON
  路径（`$.average_virtual_seconds_per_cleared_source`）。**无此负控则「全部相等」可能是空洞结论。**
- **反空转断言**：两侧 4 个入口来自不同文件、分属各自树；源侧脚手架
  `bridge_v4/bridge/strategy_v3/experiments_v3/base/candidate/experiment/offline_world`
  被记录为从**源目录**导入 → 确证是「源 vs 移植」两个不同实现。
- 旁证自洽：脚本检出**源侧 import 后 socket 被劫持 = True**，与 §2.2 的独立结论一致。

**由此 F-A 关闭**：8 个「未 vendored」文件（`bridge_v4`、`bridge`、`strategy_v3`、`experiments_v3`、
`base`、`candidate`、`experiment`、`offline_world`）**删掉后输出仍逐位相同** → 其对 `solve()` 路径
**无行为影响**，这是差分给出的直接因果结论（配合 §2.4 调用图的「零调用」证据，两条独立方法互证）。

### 5.5.3 未独立复现的 captain 证据（如实标注）

- **官方 `--sim http` 通路**（v2 `SimulatorHTTPServer` 本地托管、两引擎 exit=0、`client_api_log.jsonl`
  133 条、端点集合 {/enter,/measure,/clear,/exit}、全 200 无 error、首条 `/enter` 且 `robot_id="TEAM001"`、
  官方模式 `sources=null` 且均值改用 `cleared_count` 口径）：**验证者本轮未独立复现**，故**不计入
  本报告证据**。边界亦须注明：那是**本地托管的一致性实现，不是竞赛官方模拟器本身**。

### 5.5.4 最终判决

**verdict = pass**（作为验证者对 §5.5.1 版本的判定）。依据：
① AST 等价：15 文件级 + 6 定义级，0 unresolved；
② 差分 8/8 逐位相同且负控成立（§5.5.2）；
③ socket 劫持已关闭（5 种顺序全原生 + 实连原生）；
④ v4-vs-v3 锁陷阱已关闭（36/36 等于 v4、≠ v3、随包 lock 逐字节等于 v4）；
⑤ 生产路径未改动（5/5 点名 + 11 顶层 + 138 baseline 全量一致，基线 04:30:03Z）；
⑥ captain 20 局扫掠经验证者 20/20 复现，另有自跑 48 局三腿矩阵。

`check_absorbed.py` 退出码仍为 1（`0 FAIL / 8 NOT-VENDORED / 0 UNPROVEN / 52 rows`）：其 INCOMPLETE
**仅是提示字符串**（"run differential_check.py"），该动作已完成且通过，不构成功能性阻塞。

**必须与结论同发的两条口径**：
1. **Q4/16 相对生产路线收益不稳健、可能为负**：seed505 346.995 vs 304.031（**+14.13%**）、
   seed103 319.506 vs 302.081（**+5.77%**），两格均在 16 源；与源包锁定说明「`stress` 场景仅作
   可靠性检查」及 v4 参数在 uniform 204 例上选出的事实一致 → 属已知压力场景弱点。
2. 合成世界分布是**构造假设、非官方 TSP 分布**；全部结论**只覆盖同一合成世界下的相对比较**。

**非阻塞遗留（不影响 pass）**：F-B（F3 适配层裸导入的 `__file__` 前缀运行期断言未做）、
F-C（白名单四类 delta 分类器未做）、F-D（`absorbed_verifier.py:562` 的 `reason` 打标残余风险，low）、
F-E（`run.py --policy geometry` 16 次全 rc=1，三腿对照实为 absorbed vs learned 两腿）。

---

### 5.5.5 第三轮指纹核对（captain 再次修正后）+ §6.3 结构复核

**指纹（验证者自算；注意 captain 公布的是 32 位前缀，须按前缀比对而非整串相等）**

| 文件 | 我实测 sha256（前 32） | captain 第三轮 | 判定 |
|---|---|---|---|
| `adapters/runtime_bridge.py` | `854a08e4c791450adbe60c0a395bc195` | 同 | **一致** |
| `adapters/v3_client.py` | `eff9cb0ff37e8acbe56dc9e14c1bb814` | 同 | **一致** |
| `adapters/socket_guard.py` | `58ab848e5991ba6c14de4ad8fb3847de` | 同 | **一致** |
| `absorbed/__init__.py` | `8fa87e2b9c989c07b22bc8a20dddd1b1` | 同 | **一致** |
| `run_absorbed.py` | `46a8d69736c91937416740d3d44c368c` | `594f66dd…` | **不符** |
| `adapters/absorbed_verifier.py` | `9b24086e3830761cc4969fc05e79c049` | `dac55de9…` | **不符** |
| `ABSORBED_SOLVERS.md` | `8588f4c0282cbf8402e94d7fe5e7a228` | `94dae283…` | **不符**（第三轮仍不符） |

→ 4 项一致、**3 项连续三轮均对不上**。可追溯性仍未达成；行为证据不受影响（实跑得出）。
> 验证者自查披露：本轮首次比对时我用**整串 vs 32 位前缀**比较，把 4 个本应一致的项误判为 DIFF；
> 发现后按前缀重比并更正。这是第三次「工具/口径细节差点变成错误结论」，同样是先查证再下结论。

**§6.3 结构复核（验证者实跑一局 synthetic 后直接读产物）**

| 主张 | 我的独立结果 | 类别 |
|---|---|---|
| 顶层有 `scope` | **成立**（keys: mode/sim/ground_truth/not_applicable_checks/unavailable_checks/description） | 已实跑通过 |
| 逐项 `ok`(True/False/None) + `not_applicable` + 三态 status | **成立**（本局 (status,ok,not_applicable) 直方图 = {('passed',True,False): 19}） | 已实跑通过 |
| 新增 `solver_result.json` | **成立** | 已实跑通过 |
| `policy_config.json` 带 `kind="absorbed_run_configuration"` | **成立**（含 engine/engine_module/engine_version/mode/base_url/degraded） | 已实跑通过 |
| **官方模式**下真值检查 `skipped/ok=None/not_applicable=True`，且「无 ok=True 的真值检查」 | **未验证** | **未验证（需官方 `--sim http` 局）** |

本局为 **synthetic** 模式：真值类检查（`truth_cleared_channels`、`truth_absent_channels`）在有真值时**理应** ok=True（实测 2 项 True），
因此**该断言只能在官方模式下被证伪或证实**——验证者本轮未跑官方局，故明确标为**未验证**，不得按成立处理。

---

### 5.5.6 运行期副作用审计（动态证据，与门禁的静态判定互补）

验证者按 captain 给的命令**独立复现**，并扩展到逐级对比 `sys.path` / `os.environ` / `sys.modules` / socket 三绑定：

| 阶段 | sys.path 新增 | 环境变量新增 | socket 三绑定 | 名称 | 模块数 |
|---|---|---|---|---|---|
| baseline | — | — | 原生 | ('socket','open') | 132 |
| + `q3_v5.q3_optimizer_v5` | **无** | 无 | 原生 | ('socket','open') | 714 |
| + `q4_v4.locked` | **无** | 无 | 原生 | ('socket','open') | 1053 |
| + `adapters.v3_client` | **无** | 无 | 原生 | ('socket','open') | 1058 |
| + `run_absorbed`（入口） | **`D:\CUMCM2026\src\q3+q4_v2`** | 无 | 原生 | ('socket','open') | 1061 |

**结论按两层陈述（避免过度声明）**：
1. **引擎层与适配库层**（`absorbed/q3_v5/**`、`absorbed/q4_v4/**`、`absorbed/adapters/v3_client.py`）：
   导入期**零 `sys.path` 改动、零环境变量改动、socket/urllib 保持原生**。门禁项 (e)/(i) 的
   「零注入」结论**严格成立于这一层**。
2. **入口层**（`absorbed/run_absorbed.py`）：导入期把**本包根**插入 `sys.path`。这是入口为让
   v2 栈（api/executor/experiment/…）可导入而必须做的，与包自带 `run.py`、`runtime.py` 的同类
   做法**同构**，属**设计使然**；`baseline/code` 前缀按需（在 `main()` 内）加入。
   **须明确它被当作入口脚本使用、不作为库导入**——按库导入它会带来一次 `sys.path` 变更。

数字更正（我实测 vs captain 所述）：新增非 absorbed 模块 **896**（captain 报 953）；该计数随
导入顺序/环境浮动，属良性差异，本报告以实测值为准。此外 `absorbed/__init__.py` 等包内模块不在此计数内。

---

### 5.5.7 §6.3 符合性判定（含条文定位问题）

**定位问题（先报事实）**：captain 指认条文在 `absorbed/INTERFACE_MAP.md` 的 §6.3（约 133 行起），
但该文件**实测仅 79 行、31 887 B**，全文无「§6.3」、也无 `not_applicable` 相关要求；
验证者又在 `absorbed/**/*.md` 全量 grep `6\.3|not_applicable|scope`，**仅命中 2 处**（`INTERFACE_MAP.md:51`
提到「自带 scope 声明」、`q4_v4/MANIFEST.md` 提到环境与 claim_scope），**均非 §6.3 条文**。
→ 结论：**该条文当前无法在盘上定位**；本轮判定依据 captain 消息中**逐字引用的要求文本**
（`verifier_report.json` 必须带 `scope` 与逐项 `ok/not_applicable`；官方模式 V3 一律 `not_applicable`，
不得写 `ok=true`），并标注该依据为**转述文本而非盘上条文**。

| 要求 | 我的独立结果 | 类别 |
|---|---|---|
| `verifier_report.json` 带顶层 `scope` | **满足**（实测六键：mode/sim/ground_truth/not_applicable_checks/unavailable_checks/description） | 已实跑通过 |
| 逐项带 `ok` 与 `not_applicable` | **满足**（逐项键 `['check','detail','id','not_applicable','ok','reason','status']`；`ok` 为 True/False/**None** 三态） | 已实跑通过 |
| 官方模式：真值类一律 `not_applicable`、**不得写 `ok=true`** | **代码支持但未被实跑证实**：`skip_not_applicable()` 专用入口 + `ok=None`（skipped）+ 不变量 `no_unavailable_evidence` 参与 counts；但验证者只跑了 synthetic 局（该模式下真值检查 ok=True 是**正确行为**） | **未验证** |

**判定**：就「可测部分」而言**符合**；官方模式那一条**尚未被实跑证实**，故整体标为
**符合（一项待官方局确认）**，不写成完全符合。

### 5.5.8 seed 敏感性的直接证据（两组 seed 结论相反）

| 来源 | seed 集合 | Q4/16 配对降幅 | 胜局 | Q3/10 · Q3/16 · Q4/10 |
|---|---|---|---|---|
| captain | {101,202,303,404,505} | **−10.41%** | **4/5** | 均领先（其表：−34.09% / −23.37% / −12.39%） |
| 验证者 | {101,102,103,104,105}（对 `recommended`） | **−6.1%** | **2/5** | Q3/10 −32.7%、Q3/16 −36.1%、Q4/10 −11.9%，各 5/5 胜 |

→ **同一配置（Q4/16）在两组 seed 上连胜负方向都相反**，这就是「seed 敏感」的直接证据。
**结论口径**：**Q4/16 档位优劣不稳健，对外声称需 ≥20 seeds**；Q3 两档与 Q4/10 在 5 seed 下
5/5 一致，较稳健——但仍是合成世界结论。

### 5.5.9 范围与限制（须与结论并列阅读）

1. **验证器不复用引擎内部的两类证书判定**：`not_performed` 中 `q3_continuous_cover_replay`
   （Q3 连续覆盖证书）与 `q4_certificate_replay`（Q4 Δθ 三角/连续证书）**依赖引擎自判**，
   验证器不独立重放 —— 这两处是**已记录的范围限制**，用户应知晓。
2. **hidden-count 分母口径**：合成/`http-synthetic` 下源数取自合成真值（可知）；官方模式源数不可知，
   按 `run.py::_augment_per_source_metrics` 边界用 `cleared_count` 作分母并附 basis。
3. **构造世界假设**：合成世界分布是**构造假设、非官方 TSP 分布**；全部性能结论**只覆盖
   同一合成世界下的相对比较**，不外推官方分布。
4. 附带：`absorbed/q4_v4/MANIFEST.md:275` 亦自述「本引擎在**官方题目真值分布**上的表现未验证」，
   与上述口径一致。

---

### 5.5.10 F3 运行期断言结果（适配层裸导入绑定）— 发现 1 处不符

工具：`verification/oracle_adapter_binding.py`（不修改 `absorbed/**`，只读断言）。

方法修正（验证者第 4 次自我披露）：首版探针**导入模块后读 `sys.modules`**，结果 6 个名字全部 "unresolved" ——
因为适配层的这些导入是**函数内延迟导入**（`runtime_bridge.py:73,74,81,82,93,94`、
`absorbed_verifier.py:58,64,70`），普通 `import` 根本不执行它们。改按**导入系统本身**判定
（在适配层自己安装的 sys.path 上做 `importlib.util.find_spec`，不执行被测模块）后结果才有意义。

| 裸名 | 解析结果 | 判定 |
|---|---|---|
| `api` | `baseline/code/api/__init__.py` | OK |
| `executor` | `baseline/code/executor/__init__.py` | OK |
| `experiment` | `baseline/code/experiment/__init__.py` | OK |
| `geometry` | `baseline/code/geometry/__init__.py` | OK |
| `verifier` | `baseline/code/verifier/__init__.py` | OK |
| **`runtime`** | **`D:\CUMCM2026\src\q3+q4_v2\runtime.py`（目标包根，非 baseline/code）** | **不符** |

→ **captain 的 F3 断言（9 处裸导入必须全部落在 `baseline/code/`）按字面为 FAIL（1/6 不符）**。
验证者判读（供裁决，**不建议直接当缺陷定性**）：该处为 `runtime_bridge.py:140` 的
`from runtime import report_line`，指向的是**目标包根的生产 `runtime.py`**（本期生产路径之一），
语义上确属 v2 生产栈的一环；**因此更像"断言口径过窄"而非"绑错模块"**。但风险真实存在：
裸名 `runtime` **不唯一**——若源包目录或他处同名模块先落在 `sys.path` 上，同一行会静默改绑，
这正是撞名类问题的典型形态。**severity: low（建议改为显式路径导入或加路径前缀断言白名单）**，
最终定性请 owner 确认。

---

## 6. 未完成 / 需用户运行

1. `differential_check.py`：Q3/Q4 逐例逐位差分（源侧可行性已实测，见 §3）。
2. http-synthetic 冒烟（项 g）：q3/q4 各一局，断言 complete + verifier_all_ok + 真实耗时。
3. 最终重跑 `python verification/check_absorbed.py`：必须等 t2/t3/t4 标记完成、
   `absorbed/` 停止变动后再执行一次，届时本报告的中期结论需按最终结果更新。

**当前判决：不 PASS（INCOMPLETE，不是 FAIL）。** 本轮最新复跑：
`15 file-level identical, 6 definition-level identical, 8 deliberately not vendored, 0 unresolved`
→ **0 FAIL、8 NOT-VENDORED、0 UNPROVEN、48 rows**（F1 已关闭）。
仍缺：8 项未 vendored 的行为等价证据（F2）+ 项 g/h/i 未完成。

注意：`absorbed/` 在本轮验证期间仍在变化（`_selftest_q4.py` 被删除、`run_absorbed.py`
在验证后出现）。**必须在 t2/t3/t4 全部 completed、且文件树停止变动之后重跑一次门禁取终值。**

`check_absorbed.py` 退出码约定：0=PASS、1=FAIL/INCOMPLETE、2=未就绪（`absorbed/` 缺失）。
