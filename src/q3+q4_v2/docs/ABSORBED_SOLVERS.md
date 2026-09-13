# ABSORBED_SOLVERS.md —— 吸收进来的 Q3 / Q4 正式 SOTA 引擎

> 交付说明（captain 整合）。吸收对象是 `D:\CUMCM2026\src\Q3_Q4_V3` 中**正式采用**的两台 solver：
> Q3 `code\src\q3_optimizer_v5.py::solve_optimized_v5`，Q4 `workstreams\q4_deep_optimization_v4_20260912\strategy_v4.py::solve`
> + `results\selection_lock.json` 锁定参数（`quarter12`）。
> 探索/消融版本（`q3_deep_optimization_*`、`q4_deep_optimization_v5_*`、`q3_negative_route`、`q4_local_optimization*` 等）**未吸收**。

**一句话结论**：两台引擎已成为本包 `absorbed/` 下的**自包含、可运行**路线，直接驱动本包自己的协议/执行器/模拟器/验证栈；
现有生产路径 `production.py` / `run.py` / `runtime.py` / `compare.py` / `recommended.py` / `baseline/**` **零改动**
（已用 `verification/production_hashes_before.json` 基线逐字节比对：5/5 MATCH）。

---

## 1. 怎么跑

```powershell
# 官方 HTTP+JSON 模拟器（正式评测）
python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http `
  --base-url http://127.0.0.1:2026 --robot-id TEAM001 --output-dir runs/absorbed_q3_official

python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim http `
  --base-url http://127.0.0.1:2026 --robot-id TEAM001 --output-dir runs/absorbed_q4_official

# 本地 HTTP+JSON 全链路演练（走同一协议栈，可复现）
python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http-synthetic `
  --seed 101 --n-sources 10 --scenario random --output-dir runs/absorbed_q3_smoke

# 进程内（不开 socket，最快）
python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim synthetic `
  --seed 101 --n-sources 16 --scenario mixed --output-dir runs/absorbed_q4_smoke
```

- `--engine` 默认按 `--mode` 选择（q3→q3-v5，q4→q4-v4）；两者不匹配时报参数错误（退出码 2）。
- **退出码 0 当且仅当跑完且自建 verifier 通过**，否则 1。
- `--sim http` 为官方模式：无隐藏真值，真值类检查标 `skipped` 并进入 `not_performed`（带原因，不会假报 ok）。
- **谁负责 `/enter` 与 `/exit`**：**入口显式负责**，两台引擎都不调用（它们的第一个动作就是原点 `/measure`）。
  v2 侧同样不自动处理：`ActionExecutor.enter/exit` 是显式方法（`executor/action_executor.py:99-109`），
  `GameRunner.run` 也是显式调用（`experiment/runner.py:139,167`）。`run_absorbed.main` 的顺序是
  `client.act("/enter")` → `solve()` → `client.act("/exit")`（与源侧 `run_offline.py:22` 同形，`finally` 保证
  异常时也会 exit），因此 `--sim http` 的官方四步协议完整：`/enter`（带 `robot_id`）→ 若干 `/measure`、`/clear` → `/exit`。
  适配层的 `rows` 与 executor/api_log 都把这两个动作各记一行，`len(rows)` 与源侧 550/3500 上限逐值可比。
- 产物目录（合成模式实测 **11 件**，全部在 `output_dir` 下）：`metrics.json`、`run_report.json`（含
  `engine_parameters` 指纹、`socket_guard`、`degraded`、`artifacts`）、`verifier_report.json`
  （三态 `passed/failed/skipped` + **结构化 `scope` dict** + 逐项 `ok`(True/False/None) +
  `reason`(null/not_applicable/unavailable) + `not_applicable` + `not_performed` + 复算明细；
  检查数 Q3 **19** / Q4 **18**，语义与不变量见 §5.1、§5.2）、
  `solver_result.json` 与 `engine_result.json`（**同内容**：solver 原始返回，numpy/NaN 安全化；
  前者是 `INTERFACE_MAP §6.3` 的名称，后者为兼容保留）、`policy_config.json`（本次运行的引擎/参数身份
  快照，`kind="absorbed_run_configuration"`，**不是** v2 策略快照）、`actions.csv`、
  `api_log.jsonl`（executor 结构化调用日志）、`client_rows.jsonl`（适配层动作行，含 `/enter` 与 `/exit`）、
  `client_api_log.jsonl`（**`http` / `http-synthetic` 下 `ApiClient.log` 的原始 HTTP 日志**：
  `{time, endpoint, request, response, http_status, error}`，复用 `baseline/code/api/client.py:54,68-70`
  的日志能力；进程内 `synthetic` 模式无此文件），合成模式另有 `ground_truth.json`。
  注：吸收路径是原子 act 级、无 Mission，因此 `policy_config.json` 记录的是**运行配置**而非策略参数；
  引擎与参数来源同时记在 `run_report.json.engine_parameters`（name/version/source/sha256/count）。
- `metrics.json` 字段名与 v2 口径对齐（不自造名字），可满足同 seed 对照表：
  `complete`、`cleared_count`、`certified_absent_count`、`T_total_virtual`、`t_per_source_s`（run.py 口径）
  与同值别名 `T_per_source_s`（`runtime.py:758` report_line 口径）、`n_measures`、`n_switches`、
  `n_clear_success`、`n_clear_attempts`、`T_move/T_measure/T_switch/T_clear`、`wall_clock_s`、`verifier_all_ok`、
  `engine`、`engine_version`、`locked_name`（Q4=`quarter12`，Q3=`None`）、`sim`、`seed`、`n_sources`、`scenario`、
  `parameter_name/parameter_source/parameter_sha256/parameter_count`。
- `run_report.json.degraded.active`：仅当本次**实际**启用了降级（`--on-reject return`、`--virtual-source local`、
  或 socket 绑定被改）时为 true，并逐条给出原因；正常路径为 false。

## 2. 实测结果（captain 亲自实跑，seed 101 / 10 源 / 同一合成世界）

| 引擎 | T_total_s | **T_per_source_s** | vs 生产 learned | measures | switches | 清除(成功/尝试) | wall_clock | complete | verifier_all_ok |
|---|---|---|---|---|---|---|---|---|---|
| Q3 `q3-v5` | 2934.833 | **293.483** | **-35.7%**（456.708 → 293.483） | 120 | 111 | 10 / 11 | 1.15 s | ✅ | ✅ |
| Q3 生产 `learned` | 4567.076 | 456.708 | — | 142 | 125 | 10 / 13 | 0.28 s | ✅ | ✅ |
| Q4 `q4-v4` | 5972.794 | **597.279** | **-8.2%**（650.599 → 597.279） | 298 | 281 | 10 / 12 | 1.97 s | ✅ | ✅ |
| Q4 生产 `learned` | 6505.990 | 650.599 | — | 358 | 335 | 10 / 10 | 0.12 s | ✅ | ✅ |

复现命令见上；生产基线为 `python -X utf8 recommended.py --mode <Q3|Q4> --seed 101 --n-sources 10 --output runs/_captain_baseline`。
**口径边界**：同一 v2 合成世界（同 seed / 源数 / 场景；Q3 用 `random`，Q4 用 `mixed`）的相对比较；
世界分布是构造假设，**不代表官方 TSP 分布**。多 seed 统计由 `verification/` 的独立复核给出。
表中 Q4 吸收行用的是 `mixed`（约 50% 定向），而生产基线是默认**全定向**场景；同场景对照（`random`，全定向）为
**600.941 vs 650.599 = −7.6%**（293/272，exit 0）。

**本会话追加实测（adapter-eng，全部真跑）**：Q3 202/16/`boundary` = 217.534 s/源（128/115，exit 0）；
Q4 303/13/`random` = 513.805 s/源（298/274，exit 0）；`--sim synthetic`（进程内，不开 socket）与
`--sim http-synthetic` 的虚拟时长**逐位一致**（2934.833054）；`--sim http` 指向死端口 = 失败路径，
退出码 1 且 `run_report.json` / `verifier_report.json` 仍落盘（`complete=false`）。
上述每次运行均满足：`reconcile_warnings == []`（v2 本地虚拟时间账与服务端上报零偏差）、
`socket_guard.ok == true`、`len(rows) == len(api_log)`。

## 3. 目录结构

```text
absorbed/
  INTERFACE_MAP.md            v2 运行栈 ⇄ 源 solver client 契约（含 D1–D4 降级、R1–R11 风险）
  run_absorbed.py             统一入口（官方 http / http-synthetic / synthetic）
  adapters/
    v3_client.py              把 v2 ActionExecutor 包成源 solver 期望的 client
    socket_guard.py           socket/urllib 原生性守卫
    runtime_bridge.py         复用 v2 报告/指标（不碰 Mission 循环）
    absorbed_verifier.py      自建 verifier（V1 协议 / V2 solver 自述 / V3 合成真值 / V4 rows 不变量）
  q3_v5/                      Q3 引擎（11 文件，含 MANIFEST.md）
  q4_v4/                      Q4 引擎（17 文件，含 MANIFEST.md、results/selection_lock.json）
```

## 4. 与源包的差异（全部显式登记，均不改变数值行为）

1. **socket/urllib 劫持已停用**：源包在 import 期执行 `socket.socket=deny; socket.create_connection=deny;
   urllib.request.OpenerDirector.open=deny`（4 处）。原样带入会让本包一 import 引擎就**永久掐死 HTTP 通路**
   （`urllib → http.client → socket.create_connection`）。吸收件已停用（`absorbed/q4_v4/bridge_v4.py:63-65`、
   `absorbed/q4_v4/base.py:36-38` 把三个绑定原位赋回 stdlib 原物），并实测 import 前后
   `socket.socket.__name__ == 'socket'`、`OpenerDirector.open.__name__ == 'open'`。
   入口侧另有**独立防护**（`absorbed/adapters/socket_guard.py`）：在 import 引擎**前后各断言一次**，用
   **身份比较**（不是名称、不是类型名）判定三个绑定未被替换；命中即按 blocker 处理
   （`--sim http|http-synthetic` 直接中止、退出码 1；`--sim synthetic` 继续但把原因写进 `notes` 与 `degraded`），
   修复与规避方式打印在 stderr 并登记于本文件 §5/D5。实测（进程内）：两次 smoke 的
   `run_report.json.socket_guard.before.bindings == after.bindings` 且 `ok == true`。
   **另在独立进程复验**（劫持只对该进程生效，故必须换新进程验证）：先 `import absorbed.q4_v4.locked` 与
   `absorbed.q3_v5.q3_optimizer_v5`，再检查 —— `socket.socket` 仍是原生类、`socket.create_connection`
   仍是原生函数、`OpenerDirector.open` 仍解析为 `urllib.request.OpenerDirector.open`；随后对 127.0.0.1 的
   `urllib.request.urlopen` 返回 **200**（真实 HTTP 往返），`socket.create_connection` 也走到原生超时
   （若是 deny 桩会抛 `RuntimeError`）。结论：导入两台引擎后 socket/urllib 原生性完好，无 blocker。
2. **import 全部改为包内显式相对 import**：本包运行期把 `HERE` 与 `HERE\baseline\code` 插到 `sys.path`，
   裸 `from geometry import ...` 会静默绑定到本包的 `geometry/` 包。Q3 的 `code\src\geometry.py` 因此改名
   `geometry_src.py`（引用点 4 处全改）。
3. **删除 solve() 路径零调用的死链**（`strategy_v3` / `experiments_v3` / 仅存在于 v1 目录的 `offline_world` 等），
   避免把实验脚手架与重复劫持带进 solver 闭包；逐条登记在各 `MANIFEST.md`。
4. **裸 `import numba` 已删**（源包用它规避 `coverage` 撞名的顺序 hack；本机 numba 0.62.1 下该 hack 已失效）。
   `ordered_tour.py` 的 `from numba import njit` 是**真依赖**，保留（`exact_insert=True` 时每次路由调用）。
5. **锁定参数取 v4 锁**：源 `bridge_v4.py:16` 读的是 **v3** 锁；吸收件的 `results/selection_lock.json` 是 **v4** 锁
   逐字节副本，`locked.LOCKED_PARAMETERS` 与 v4 锁 `selected_parameters` **36 项逐字段相等**（实测 `True`）。

## 5. 语义差异与边界（不可直接横比 / 不可复用之处）

- **D1 动作被拒**：v2 有 `accepted=false`，源契约无此态 → 适配层 fail loud（`--on-reject raise`，默认），
  可设 `--on-reject return` 仅用于诊断；诊断模式已实现为可观测状态：`run_report.json.degraded.active == true`
  并带原因（实测 `{"active": true, "reasons": ["on_reject=return…", "virtual_source=local…"]}`）。
  注意 `return` 模式**不伪造** `measure_result`/`clear_result`，引擎随后会 KeyError——这是刻意的。
- **D2 通信异常**：400/415/409 由 v2 会话层抛错，适配层原样上抛，入口捕获写 `failure` 并退出 1。
- **D3 误差场口径**：v2 误差场（`random_fixed` / `boundary` / `structured`，`experiment/simulator.py:164-203`）与
  源参考 world（plus/minus/zero/sine/hash）**数值不同但同为「同点固定、幅值 ≤1°」**（题设要求）→ 决策代码路径一致、
  案例结果不同，**不要"修正"**。
- **D4 案例分布**：v2 合成器 `n_sources` 默认 10..16、上限 20（`experiment/simulator.py:128-129`）；Q3 恒全向、
  Q4 恒定向（`scenario='mixed'` 时约 50%，`simulator.py:141-149`）。两台 solver 在 `len(cleared) < 10` 或 `> 16` 时
  直接 raise（`q3_optimizer_v5.py:256`；`strategy_v4.py:300`）→ `--n-sources <10` 必须作为**预期失败**如实上报，
  不许吞掉。
- **R5 不可复用 `GameRunner._verify()`**：其 `all_ok` 从 `True` 起算且检查全部来自 v2 证书状态，
  套在吸收引擎上会**空检查通过 = 假 PASS**。吸收件改用自建 verifier（V1–V4）。
- **R7 无 stop-plan 合并**：吸收路径是原子 act 级，**没有** v2 策略的停点合并，因此 `switches` / `T_switch`
  与 v2 现有策略**不可直接横比**（属策略差异而非协议缺陷）。
- **官方模式**：无隐藏真值、真实时钟预算、wall-clock 不确定 → 真值类检查标 `skipped` 并进入 `not_performed`
  （带原因，不会假报 ok）。

### 5.1 verifier 报告语义：三态 + `reason` 三值 + 结构化 `scope`

- **⚠ 下游接口变更（P0）**：`verifier_report.json` 顶层 `scope` 由「说明字符串」升级为**结构化 dict**；
  任何按字符串消费 `scope` 的下游（如 `verification/check_absorbed.py`）必须改读 dict。
  老字段 `ground_truth_available` 保留未删。
  ```json
  {"mode": "Q3|Q4", "sim": "http|http-synthetic|synthetic|unknown",
   "ground_truth": "available|unavailable",
   "not_applicable_checks": ["<check id>", "..."],
   "unavailable_checks": ["<check id>", "..."],
   "description": "<复核范围说明；官方模式真值类检查 not_applicable，不会写成 ok=true>"}
  ```
- 逐项字段：`status ∈ {passed, failed, skipped}`；`ok ∈ {True, False, None}`
  （`skipped` 一律 `None`，**永不**把跳过写成通过）；**`reason ∈ {null, "not_applicable", "unavailable"}`**；
  `not_applicable == (reason == "not_applicable")`。
- `reason` 的两类跳过（`absorbed/adapters/absorbed_verifier.py:134` `skip_not_applicable` /
  `:141` `skip_unavailable`）：
  - `not_applicable` = **模式性不适用**：官方 `--sim http` 无真值 → 两条真值检查（`truth_cleared_channels`、
    `truth_absent_channels`）；Q3 缺席**全部**来自 16 基数推断时无几何覆盖声明可复算；
  - `unavailable` = **本应可跑但证据/工具缺失**：v2 verifier 不可导入、引擎未交回 `clear_attempts`、
    Q3 既无 `negative_observations` 又无基数依据、未知引擎名。
- 检查数（实测）：合成模式 **Q3 19 / Q4 18，全部 passed**；官方模式 **Q3 19 / Q4 18
  = passed 17/16 + skipped 2**（两条 `not_applicable`），`unavailable_checks` 为空。

### 5.2 不变量：`unavailable` 必须阻断 `all_ok`（假 PASS 通道已关闭，含反例）

**规则**：只要出现任一 `reason == "unavailable"` 的检查，`all_ok` 必须为 `false`；`not_applicable` 不阻断。
**实现路径**：`absorbed_verifier.py` L562 汇总 `unavailable_ids` → **L566 新增独立检查项
`no_unavailable_evidence`**（它参与 `counts`，因此失败即计入 `failed`）→ L582 `all_ok = counts["failed"] == 0`。
**captain 裁定（已批准从严）**：官方模式下若 v2 verifier 不可导入，同样判 `unavailable` 并**阻断**——
"验证工具坏了不该给 PASS"，故**不**按模式放宽、不加 mode 门控。

**反例构造方法**（可复现；用 v2 合成世界真值搭一个「其余检查全绿」的结果字典，只破坏一个条件）：
1. `runtime_bridge.build_backend("synthetic", mode="Q3", seed=101, n_sources=10, scenario="random")` 起
   executor / simulator；逐频道 `/measure` 后按真值 `/clear` 清掉 10 个源，得到 `cleared_sources` 与 `clear_attempts`；
   缺席几何证据用 **8×940 m 环**（`verify_q3_cover` 实测 `max_min_dist = 998.59 ≤ 1000`，与生产 Q3 覆盖同源）。
2. **TEST 1 · 合成模式 + 证据缺失**：把 `clear_attempts` 清空 → 几何两项判 `unavailable`：
   `all_ok = False`，唯一 `failed` = `no_unavailable_evidence`，
   `scope.unavailable_checks = ['clear_attempt_bound_identity', 'certified_clear_geometry']`，
   `counts = {'total': 18, 'passed': 15, 'failed': 1, 'skipped': 2}`。
3. **TEST 2 · 官方模式无真值**（同一结果字典 + `simulator=None, sim="http"`）：`all_ok = True`，
   真值检查 `status=skipped / ok=None / reason="not_applicable" / not_applicable=True`，
   `scope.not_applicable_checks = ['truth_cleared_channels', 'truth_absent_channels']`、`unavailable_checks = []`、
   `no_unavailable_evidence = passed`。
→ 两类跳过的处置**不对称且方向正确**：证据缺失阻断通过，模式性不适用不阻断。

## 6. 与现有生产路线的关系

吸收件是**并行新增路线**，不改变 `learned` / `probabilistic` / `geometry` 等既有路线，也不改 `run.py` 的
`SCHEDULERS` 注册。原因：两台引擎是「一次 `solve()` 跑完整局」的闭包式求解器，而本包 `Scheduler` 是
`Mission` 增量接口，改写成 Scheduler 会破坏源的证书语义。**若**要把吸收件作为默认生产入口，请改用它自己的
入口 `absorbed/run_absorbed.py`（官方模拟器用法见 §1），而不是修改 `production.py`。

## 7. 复现与独立验证入口

```powershell
python -X utf8 verification/check_absorbed.py      # 吸收件静态+运行期自检（verifier 交付）
python -X utf8 verification/check_model.py         # 本轮模型算术/局部关系核对（原有）
```

- `absorbed/INTERFACE_MAP.md`：v2 栈与源契约的逐符号对照、降级清单、风险表。
- `absorbed/q3_v5/MANIFEST.md`、`absorbed/q4_v4/MANIFEST.md`：逐文件来源、源 SHA-256（与 v4 锁清单比对）、
  逐处 import 改写、删除项登记、未验证项声明。
- `verification/production_hashes_before.json`：生产路径未改动的哈希基线（5/5 MATCH）。

## 8. 未验证 / 需注意

- 本机运行环境与源锁定环境存在版本差：Python 3.13.9 / numpy 2.3.5 / scipy 1.16.3 / numba 0.62.1 / shapely 2.1.2
  （源锁记录 3.13.7 / 2.4.6 / 1.17.1 / 0.66.0 / 2.1.2）。AST 级逐行等价与多 seed 统计见 `verification/` 的独立复核报告。
- `@njit(cache=True)` 需要可写的缓存目录（`absorbed/q4_v4/__pycache__/`）；只读部署需设 `NUMBA_CACHE_DIR`。
- 合成世界是构造假设，官方分布未证实；官方模式的成绩需以官方模拟器实测为准。
- **未接竞赛官方服务**：`--sim http` 已验证失败路径与「本地托管一致性服务上的完整四步协议」（§11 第 4 条，
  `/enter`→`/measure`/`/clear`→`/exit` 全 200），但**未**与竞赛官方实现做端到端一致性验证；官方模式下
  真值类检查按设计为 `skipped`。

## 9. t4 新增文件（只新增；生产路径零改动）

| 文件 | 作用 |
|---|---|
| `absorbed/adapters/v3_client.py` | 把 v2 `ActionExecutor` 包成源引擎期望的 client（`act`/`position`/`channel`/`virtual`/`rows`），落 D1/D2/D3 降级；纯鸭子类型，不 import v2 |
| `absorbed/adapters/runtime_bridge.py` | `sys.path` 准备（镜像 `run.py:25-32`）、三种 `--sim` 的后端构造、`runtime.report_line` 惰性复用与逐键兜底、JSON 安全化、参数指纹、metrics |
| `absorbed/adapters/absorbed_verifier.py` | 独立 verifier：真复用 `verify_q3_cover` / `verify_mec_covers` + 合成真值；三态结论 + `not_performed` |
| `absorbed/adapters/socket_guard.py` | 导入引擎前后的 socket/urllib 绑定身份断言、blocker 判定与修复说明 |
| `absorbed/adapters/__init__.py` | 适配层再导出 |
| `absorbed/run_absorbed.py` | 统一入口（CLI / 跑一局 / 校验 / 落盘 / 一行摘要 / 退出码） |
| `absorbed/__init__.py` | 包声明、引擎版本索引、导入期零副作用约定 |
| `ABSORBED_SOLVERS.md` | 本文件（captain 整合；t4 校正了产物清单、verifier 三态、socket 防护与 §10 片段） |

导入期零副作用：以上模块 import 期只依赖标准库，不构造客户端、不开 socket、不改 `sys.path`
（`sys.path` 与 v2 运行栈的导入都在 `main()` / 函数内部完成），因此 `--help` 在任何环境下都可用。

## 10. 可选、默认不启用的注册片段（**不改 `run.py`**）

```python
# ---- 可选、默认不启用：请勿直接修改 run.py ---------------------------------
# 吸收引擎是"自驱动"的：它们在 solve() 内部自己跑 act() 循环，不实现
#     Scheduler.decide(ks, position, channel) -> Mission
# 契约，因此**不能**像 learned / probabilistic / geometry 那样塞进 run.py:55-65 的
# SCHEDULERS 字典。现状（推荐、已实测）是用独立入口：
#     python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http ...
# 若将来确要并入 run.py，需要先写一个 Mission 适配器（把引擎的每个原子动作包装成
# 单动作 Mission，并接受失去 stop-plan 合并），再在 SCHEDULERS 里加一行。
# 该适配器本会话**未实现、未验证**，且属于修改生产路径，须 captain 另行批准。
ABSORBED_SCHEDULERS_PLACEHOLDER = {}   # 有意留空：默认不启用
```

## 11. 本任务验收命令与实测退出码（t5 可直接复跑）

| # | 命令 | 实测 |
|---|---|---|
| 1 | `python -X utf8 absorbed/run_absorbed.py --help` | 退出码 **0**，打印完整用法（导入期无副作用） |
| 2 | `python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http-synthetic --seed 101 --n-sources 10 --scenario random --output-dir runs/absorbed_q3_smoke` | 退出码 **0**；`complete=true`、`cleared=10`、`verifier_all_ok=true`（**19/19 passed**，含新增 `no_unavailable_evidence`） |
| 3 | `python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim http-synthetic --seed 101 --n-sources 10 --scenario mixed --output-dir runs/absorbed_q4_smoke` | 退出码 **0**；`complete=true`、`cleared=10`、`verifier_all_ok=true`（**18/18 passed**，含新增 `no_unavailable_evidence`） |
| 4 | **官方 `--sim http` 通路**（用 v2 `SimulatorHTTPServer` 在 127.0.0.1 起一个符合四步协议的服务，再 `--sim http --base-url <url>` 跑两台引擎） | 两台均退出码 **0**、`complete=true`、`cleared=10`、`verifier_all_ok=true`；`client_api_log.jsonl` 133 条、端点集合 `{/enter,/measure,/clear,/exit}`、**全部 HTTP 200**、`/enter` 请求带 `robot_id=TEAM001`；官方模式 `sources=null`（无真值），per-source 均值改用 `cleared_count` 口径（与 `run.py` 的 hidden-count 边界一致） |

> 第 4 条用的是**本地托管的一致性服务**，验证的是官方 HTTP 通路（urllib → `Session` → `ApiClient` → 四端点协议），
> **不是**竞赛官方模拟器本身；官方实跑仍需在 `--base-url` 指向真实服务时复测（见 §8 未验证项）。
