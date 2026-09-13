# ABSORBED_SOLVERS_VERDICT.md —— 吸收交付：结论、证据与边界

> 本文件是**最终交付报告**（captain 汇总）。使用说明书见 `ABSORBED_SOLVERS.md`（267 行）；接口契约见 `absorbed/INTERFACE_MAP.md`；
> 逐文件来源与改写登记见 `absorbed/q3_v5/MANIFEST.md`（268 行）与 `absorbed/q4_v4/MANIFEST.md`（286 行）；
> 独立验证见 `verification/absorbed_static_report.md`。**本文件不修改任何被验证文件。**

---

## 1. 一句话结论

`D:\CUMCM2026\src\Q3_Q4_V3` 中**正式采用**的两台 SOTA solver 已被吸收进 `D:\CUMCM2026\src\q3+q4_v2`，成为 `absorbed/` 下**自包含、可运行、可复现**的路线：
- **Q3**：`code/src/q3_optimizer_v5.py::solve_optimized_v5`（`VERSION=q3_joint_search_clear_route_v5`）
- **Q4**：`workstreams/q4_deep_optimization_v4_20260912/strategy_v4.py::solve` + `results/selection_lock.json` 锁定参数（`q4_21station_exact_route_v4` / `quarter12` / **36 项**）

**独立判决：`verdict = pass`**（由 verifier 出具；captain 代为登记于任务 `t7`）。
**同 seed 同源数下 19/20 局更快、配对均值 −20.07%**，且 **Q3 两档与 Q4/10 稳健领先**；**Q4/16 不稳健、可能为负**（见 §4）。
**现有生产路径零改动**（逐字节哈希对照，见 §6）。

---

## 2. 交付物

```text
q3+q4_v2/
  ABSORBED_SOLVERS.md              使用说明（安装/命令/差异/降级/未验证项）
  ABSORBED_SOLVERS_VERDICT.md      本文件：结论、证据、边界
  absorbed/                        37 文件 / 314 KB / 5,356 行（自包含）
    __init__.py
    INTERFACE_MAP.md               v2 栈 ⇄ 源 solver client 契约（含 D1–D4 降级、R1–R11 风险）
    run_absorbed.py                统一入口（官方 http / http-synthetic / 进程内 synthetic）
    adapters/
      v3_client.py                 把 v2 ActionExecutor 包成源契约 client（rows 含 /enter /exit）
      socket_guard.py              socket/urllib 原生性守卫（import 前后身份断言）
      runtime_bridge.py            复用 v2 报告/指标；不复用 Mission 循环
      absorbed_verifier.py         自建 verifier（V1 协议 / V2 自述 / V3 合成真值 / V4 不变量）
    q3_v5/                         11 文件（引擎 + MANIFEST）
    q4_v4/                         18 文件（引擎 + locked.py + v4 锁副本 + MANIFEST）
  verification/                    新增验证产物（下列均可一键重跑）
    check_absorbed.py              吸收件门禁（AST 等价 / import 冒烟 / 锁 / socket / 撞名 / 生产哈希 / 副作用）
    differential_check.py          源 vs 移植差分（8 例，四维逐位 + 反证控制）
    differential_report.md         差分报告
    captain_differential_probe_q3.py / _q4.py   captain 自研探针（独立于上述差分的第二条路径）
    oracle_callgraph.py            名字级调用图（reachable=14 / zero_call=40 / missing_defs=0）
    oracle_smoke_matrix.py         冒烟矩阵（每局独立进程 + 进程内 socket preflight）
    oracle_captain_claims.py       对 captain 六条结论的独立复算（23/23）
    production_hashes_before.json  生产路径哈希基线（冻结于 2026-09-13T04:30:03Z）
    baseline_recommended_frozen.json  生产路线 20 局冻结基线
    absorbed_vs_baseline_matrix.json / three_leg_matrix.json / absorbed_sweep_verify.json  对照矩阵数据
    absorbed_static_report.md      独立验证报告（含 §5.5 终版：版本指纹 + 差分 + 判决）
```

## 3. 怎么跑（三条命令，可直接复制）

```powershell
# 官方 HTTP+JSON 模拟器（正式评测）
python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http `
  --base-url http://127.0.0.1:2026 --robot-id TEAM001 --output-dir runs/absorbed_q3_official
python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim http `
  --base-url http://127.0.0.1:2026 --robot-id TEAM001 --output-dir runs/absorbed_q4_official

# 本地全链路演练（真实 socket + 同一协议栈，可复现）
python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http-synthetic `
  --seed 101 --n-sources 10 --scenario random --output-dir runs/absorbed_q3_smoke
python -X utf8 absorbed/run_absorbed.py --mode q4 --engine q4-v4 --sim http-synthetic `
  --seed 101 --n-sources 10 --scenario mixed  --output-dir runs/absorbed_q4_smoke
```
退出码 **0 当且仅当跑完且自建 verifier 通过**；`--sim http` 为官方模式（无隐藏真值，几何复算项标 `not_applicable`，不会写成 `ok=true`）。

## 4. 性能对照（同 seed、同源数、同场景；全部 `complete` 且 `verifier_all_ok`）

**captain 20 局配对**（seed {101,202,303,404,505}，absorbed vs 生产 `recommended`）：

| 配置 | 吸收均值 | 基线均值 | 配对降幅 | 逐 seed 胜出 |
|---|---:|---:|---:|---:|
| Q3 / 10 源 | 280.230 | 426.255 | **−34.09%** | 5/5 |
| Q3 / 16 源 | 205.853 | 268.903 | **−23.37%** | 5/5 |
| Q4 / 10 源 | 598.038 | 685.940 | **−12.39%** | 5/5 |
| Q4 / 16 源 | 309.924 | 350.811 | −10.41% | 4/5 |
| **合计** | — | — | **−20.07%（中位 −23.25%）** | **19/20** |

**verifier 独立矩阵**（另一组 5 seed，40 局）：Q3/10 −32.7%（5/5）、Q3/16 −36.1%（5/5）、Q4/10 −11.9%（5/5）、**Q4/16 −6.1%（仅 2/5 胜）**。

**⚠ 必须同发的两条口径**
1. **Q4/16 不稳健、可能为负**：verifier 在其 48 局矩阵里发现 **seed505 慢 14.13%**、**seed103 慢 5.77%**（均为 16 源）；captain 独立复现 seed505 的 +14.13%。两组不同 seed 集对 Q4/16 给出相反结论 ⇒ 该档位**需 ≥20 seeds 才能定论**，不可对外声称"全面提升"。原因与源包锁定说明一致：`quarter12` 是在 **uniform 204 例**上按 pooled time 选出的，16 源/压力场景只作**可靠性检查**、非优化目标。
2. **合成世界是构造假设，不是官方 TSP 分布**；以上结论只覆盖「同一合成世界、同一 seed、同一源数」的相对比较。

## 5. 两个已关闭的高危项（若未拦下，吸收会静默报废）

| 风险 | 后果 | 证据 |
|---|---|---|
| 源包 import 期 `socket.socket=deny; socket.create_connection=deny; urllib.request.OpenerDirector.open=deny`（闭包内 3–4 处） | 一旦 import Q4 引擎即**永久**掐死 urllib → 官方 http 与本地 http-synthetic 全废 | 吸收件已停用/原位恢复；**5 种 import 顺序 + 组合顺序**全部原生；对 127.0.0.1 实连得原生 `TimeoutError` 而非 deny 的 `RuntimeError`；机制是**结构性**的（`no_unavailable_evidence` 参与计数） |
| `bridge_v4.py:16` 读的是 **v3** 锁 | 吸收后会**静默跑成上一代参数** | 随包锁与 **v4** 锁逐字节相等（≠v3，4899 B vs 8432 B）；`LOCKED_PARAMETERS` 36/36 等于 v4 锁；`solve` 签名 36 参数与源逐参数/逐默认值一致 |

## 6. 生产路径零改动（红线）

`production.py / run.py / runtime.py / compare.py / recommended.py` 与基线 `verification/production_hashes_before.json`（冻结于 **2026-09-13T04:30:03Z**，早于 `absorbed/` 落盘）**5/5 逐字节一致**；另有 11 个顶层 `.py` + `baseline/**` 138 个文件一致、0 MISMATCH。
（过程更正：本目录**不是 git 仓库**，早前有人引用过的 `git status --porcelain` 匹配数为 0 属**空证据**，已改用哈希基线。）
**适用范围限定**：以上"零改动"仅覆盖**吸收期间**。吸收完成之后，依用户指令修复 `--policy geometry` 而**修改过 `run.py`**（其余四个点名文件仍逐字节未变）——该次授权变更的指纹、改法与回归证据见 **§11**；`verifier` 的门禁据此把它登记为"经授权的基线后变更"，而不是静默放行。

## 7. 等价性证据（吸收是否忠实的核心）

- **AST 等价**：15 文件级 + 6 定义级完全一致，0 unresolved；19/20 个 Q4 闭包文件带 **lock-hash verified**（sha256 与 v4 锁表一致）。
- **行为等价（差分）**：`verification/differential_check.py` → `VERDICT: PASS`、exit 0，**8/8 用例四维逐位相同**（Q3 动作 133/124/141/131、Q4 281/281/278/255；动作序列含 `/enter` `/exit`、虚拟时长、cleared 集合、返回 JSON 逐字节）。**含反证控制**（不同世界必须被判不等 → 实测检出差异）与**反空转断言**（两侧入口分属不同树/不同函数对象），因此"8/8 相等"不是空洞通过。
- **调用图**：`reachable_files=14 / zero_call=40 / missing_defs=0` → 8 个未 vendor 脚手架在 `solve()` 路径**零调用**；与差分构成**两条独立方法互证**。
- **导入态**：引擎包与 `adapters/v3_client.py` 导入期**零 `sys.path` 改动、零环境变量改动**；仅入口脚本 `run_absorbed.py` 把本包根加入 `sys.path`（与包自带 `run.py:29-32`、`runtime.py:15-18` 同构）。
- **不变量**：真实回合 `len(client_rows) == len(api_log)`（Q3 133=133、Q4 312=312，含 `/enter` `/exit`）。

## 8. 非阻塞遗留（不影响 pass，但如实列出）

| id | 级别 | 内容 |
|---|---|---|
| F-B | low | F3：`absorbed/adapters/*` 9 处裸导入的运行期 `__file__` 前缀断言未做（设计使然，解析到 `baseline/code` 的 v2 模块） |
| F-C | low | 白名单四类 delta 分类器（去劫持/去 sys.path/import 前缀/删死链）未做 |
| F-D | low | `absorbed_verifier.py` 的 `reason` 打标残余风险；经作者逐行枚举证明**当前不可达**（仅 2 处构造 skipped、均强制非 None reason，9 个调用点全经 helper） |
| F-E | **既存缺陷（与吸收无关）** | `run.py --policy geometry` 在任何配置下**构造即崩**：`TypeError: Scheduler.__init__() got an unexpected keyword argument 'q3_observation_adaptive'`（Q4 报 `q4_risky_clear_radius`）。根因：`run.py:1027` 把生产 scheduler kwargs 整体转发给 `GeometryJointScheduler.__init__`，后者把未识别键透传给 `Scheduler.__init__`。**这是你包里原有的问题**，会导致三腿对照实际只有两腿（absorbed / learned）可用 |

## 9. 验证独立性与已知偏差（如实披露）

- `verdict=pass` 由 **verifier** 出具；它同时披露：所用的差分脚本是 **interface-scout**（未写过 `absorbed/` 任何一行代码）所写，它是**运行并审查**而非自研第二份差分——该保留已原样保留。
- captain 另写了两份自研探针（`captain_differential_probe_q3/q4.py`）双向通过，但**标注为 captain 自证**，不作为第三方证据。
- **一处版本记录偏差**：`verification/absorbed_static_report.md` §5.5.1 记录的指纹取自 captain 早期转述（536/`1421822d…`、552/`7923738f…`、211/`d4b8b971…`），**已过期**。当前真实冻结值如下；代码文件自 12:43:56 起未再变动：

```
absorbed/run_absorbed.py                 565 行  46a8d69736c91937416740d3d44c368cbb3258208eb7e4883ff3d76196676a3f
absorbed/adapters/absorbed_verifier.py   624 行  9b24086e3830761cc4969fc05e79c0490e888f2e07095e5610359fbc5194a3d2
absorbed/adapters/runtime_bridge.py      310 行  854a08e4c791450adbe60c0a395bc19572a1e4db5973b7ecfe8e7e1cedb84f8b
absorbed/adapters/v3_client.py           290 行  eff9cb0ff37e8acbe56dc9e14c1bb81427b932f65f33d46aeb0ce6e0e3f2de43
absorbed/adapters/socket_guard.py        151 行  58ab848e5991ba6c14de4ad8fb3847de67ea566fe2ad83f66df4833a1beb6159
absorbed/adapters/__init__.py             39 行  1cdbcb7801114326417d1748af1babe6675cdae1b3faf0917a37f2bdafd65b09
absorbed/__init__.py                      31 行  8fa87e2b9c989c07b22bc8a20dddd1b1c9a99e8527fed65d1a5559e763ce20ed
ABSORBED_SOLVERS.md                      267 行  8588f4c0282cbf8402e94d7fe5e7a2282938a4913dc08389edb744722a90b94d
```
- **未独立复现**：官方 `--sim http` 通路（本地托管一致性服务，133 条 API 全 200、首条 `/enter`、`robot_id` 正确）为**单方证据（adapter-eng）**，verifier 声明未独立复现、故未计入其报告。该证据验证的是 HTTP 通路，**不是竞赛官方模拟器本身**。

## 10. 一键复现

```powershell
cd D:\CUMCM2026\src\q3+q4_v2
python -X utf8 verification/check_absorbed.py        # 门禁（静态+import+锁+socket+生产哈希+副作用）
python -X utf8 verification/differential_check.py    # 源 vs 移植差分 → VERDICT: PASS
python -X utf8 verification/oracle_captain_claims.py # captain 六条结论的独立复算（23/23）
python -X utf8 verification/captain_differential_probe_q3.py
python -X utf8 verification/captain_differential_probe_q4.py
```

---

## 11. 吸收完成后的一次**用户授权变更**：修复 `run.py --policy geometry`

**背景（既存缺陷，非吸收引入）**：`--policy geometry`（以及 `probabilistic`）在原包里**构造即崩**——`run.py` 把 `production.scheduler_kwargs(mode)` 的整包转发给被选中的调度器，而其类链上的 `Scheduler.__init__` 不接受未知键：

```
--policy geometry --mode q3  →  TypeError: Scheduler.__init__() got an unexpected keyword argument 'q3_observation_adaptive'
--policy geometry --mode q4  →  TypeError: Scheduler.__init__() got an unexpected keyword argument 'q4_risky_clear_radius'
```

后果：一局都跑不起来（verifier 记录 16/16 次 `exit_code=1`、约 0.36 s 退出、无产物），"三腿对照"实际只有两腿。**用户随后明确要求修复。**

**红线口径更新（重要）**

| 阶段 | 生产路径状态 |
|---|---|
| **吸收期间**（04:30:03Z → 交付） | 5 个点名文件 + 11 个顶层 `.py` + `baseline/**` 138 文件 **逐字节未改动**（原基线证据仍有效，见 §6） |
| **吸收完成之后** | 依用户指令**仅修改 `run.py`**（**执行者：captain**；指令原文「把 geometry 修好」/「修 `--policy geometry`」）；`production.py` / `runtime.py` / `compare.py` / `recommended.py` **仍逐字节未变** |

```
run.py  before  66 791 B  14c479355e158be2d574af500bd289de66a4a47b376ee94a…
run.py  after   68 547 B  def842f4ae28c7f878141d4e1d2904959fb91b8f25dd72e6f75c931550f1c174   (1 127 行)
```

**改法（construct-and-retry，行为恒等）**：新增 `_build_scheduler(scheduler_cls, mode, kwargs)`——先用**完整 kwargs** 构造；**仅当**捕获 `TypeError: ... unexpected keyword argument 'X'` 时，剔除**恰好那一个** X 再重试，直到成功；返回 `(scheduler, effective_kwargs, dropped_keys)`，`dropped_keys` 非空时打印到 stdout（不静默）。能接受全部键的路线（生产默认 `learned`）**第一次即构造成功、零键剔除**，代码路径与改前完全一致。

**回归与增值证据（captain 实测）**

| 路线 | 结果 |
|---|---|
| `learned` / q3 | `T_total_virtual=4567.076019` vs 基线 `4567.076019177168`（同值，仅 6 位 vs 全精度）、`measures=142 / switches=125 / cleared=10`、`complete=True / verifier_all_ok=True` → **一致** |
| `learned` / q4（`--scenario mixed`） | `6505.989701` vs 基线 `6505.989700901541`、`measures=358 / switches=335` → **一致** |
| `geometry` / q3、q4 | 由 `rc=1` → **`exit=0, complete=True, verifier_all_ok=True`**（496.965668 / 779.700825） |
| `probabilistic` / q3、q4 | 同样复活（501.041791 / 782.919023） |

**方法学教训（自我纠错，如实披露）**：第一版修法是"按 `inspect.signature` 预过滤 kwargs"，**改坏了 `learned`/q4**（667.17 vs 650.60 s/源，measures 368 vs 358）——被 captain 自己的回归检查抓到后立即改为 construct-and-retry。**预过滤会静默改变行为；construct-and-retry 只在真的 `TypeError` 时才动手。**

**一处口径纠正**：`run.py` 的 `--scenario` **默认 `random`**，而 `recommended.py` 对 Q4 默认 `mixed`。跨入口比较性能**必须显式对齐场景**，否则会把"世界不同"误读成行为差异（我第一次回归就是这样误报的）。

**由此产生的一次数字分歧与对齐（已闭环）**：`--policy geometry --mode q4` 实测 `T_per_source_s` 为 **793.4863693**（`--scenario mixed`）与 **779.7008251**（省略 `--scenario`，即默认 `random`）；`geometry --mode q3` 两边同为 **496.9656684**。差异**100% 来自场景**，与本次修复或引擎无关。

**一处曾被误判为"静默失效"的双源隐患（已更正方向）**：同一件授权在两处曾使用不同键名——本记录用 `authorized_by` / `changes[].after_sha256`，而 verifier 门禁的早期中间版本用 `authorised_by` / `after_sha256` / `when`。经 verifier 复核，**该风险的方向是 fail-closed 而非 fail-open**：放行要求「当前哈希 == `after`」且「基线哈希 == `before`」且 path 命中；键名改动会取到 `None` → 两个等式都不成立 → 落到 `not covered` → **FAIL**；`changes` 读不到则**任何改动都 FAIL**。因此**不存在"静默通过"**。verifier 已把门禁改为**每次运行都重读本记录文件**（单一事实源，不把副本内联进代码），并进一步**在读 JSON 前做 schema 断言**：缺 `changes[].path` / `before_sha256` / `after_sha256`、`changes` 为空、或用别名替代规范键，一律 **FAIL**——该断言已用**真实负例**验证（删掉 `changes[0].after_sha256` → `VERDICT: FAIL` / exit 1；恢复 → `PASS` / exit 0）。本记录保留**双拼写别名**仅供可读性，**不能替代规范键**，并新增 `_provenance` 记录对它的两次编辑。

## 12. 验证契约（原 `absorbed/INTERFACE_MAP.md` §6.3 重录）

原始 §0–§13 / 205 行版接口图在第 5 轮被一次"按骨架 ≤200 行落盘"的压缩重写覆盖，**§6.3 条文随之从盘上消失**（verifier 曾据实报告"条文定位不到、只能依据我消息中的转述文本判定"）。此处重录，避免再引用一个不存在的章节：

- `verifier_report.json` **必须**带顶层 **`scope`**（结构化 dict：`mode` / `sim` / `ground_truth` / `not_applicable_checks` / `unavailable_checks` / `description`）；
- 逐项检查**必须**给出 **`ok`（三态 `True/False/None`）** 与 **`not_applicable`**，并保留 `status` 与 `reason ∈ {null, not_applicable, unavailable}`；
- **官方 `--sim http` 模式下真值类检查一律 `not_applicable`，不得写成 `ok=true`**；
- 不变量：**合成模式下 `unavailable_checks` 必须为空且 `no_unavailable_evidence` 必须 `passed`**；任何 `unavailable` 都要变成一条 failed 检查，从而阻止 `all_ok`。

实现位置：`absorbed/adapters/absorbed_verifier.py`；门禁内三条加严断言见 `verification/check_absorbed.py::check_j_skip_reason_invariant`。

## 13. 三份独立差分的交叉比对

见 `verification/differential_crosscheck.md`：interface-scout 的 `differential_check.py`（8 例）、verifier 自写的 `oracle_q3_mock_diff.py`（跨进程 2 例）、captain 的两个探针（各 1 例）——**三者结论一致**，各自的口径与覆盖范围差异逐条列出。

## 14. 遗留项状态更新（相对 §8）

| id | 原状态 | 现状态 |
|---|---|---|
| F-A 差分未交付 | medium | **已关闭**——三份彼此独立的差分结论一致 |
| F-B F3 断言口径 | low | **判 PASS（口径修正版）**：`runtime → 目标包根` 属正确解析；白名单 = 包根 ∪ `baseline/code` |
| F-C 34 处四类外差异 | low | **批准扩为 8 类**（补：删 `ROOT` 赋值 / 删离线标记 / 删 `__main__` 保护块 / docstring 改写）+ **硬不变量 `target_only = ∅`** |
| F-D `reason` 打标残余 | low | **已关闭**——门禁内三条加严断言实跑通过 |
| F-E `--policy geometry` | 既存缺陷 | **已修复**（见 §11），三腿对照恢复可用 |
| F-F 官方模式语义 + 不变量失败分支的独立构造 | — | **已关闭（已实跑）**：verifier 在**两个引擎 + 官方模式**上亲手构造反例——Q3 `ENTRY_EXIT 1`、唯一 failed=`no_unavailable_evidence`、counts `{19,16,1,2}`；Q4 `{18,15,1,2}`；官方 `--sim http` `ENTRY_EXIT 0`、**`any ok=True truth check: False`**、`unavailable_checks=[]`、`no_unavailable_evidence=passed` |

## 15. 最终门禁结果（授权变更落地后）

```
python -X utf8 verification/check_absorbed.py
--- 0 FAIL, 0 NOT-VENDORED(uncovered), 8 NOT-VENDORED-COVERED-BY-DIFFERENTIAL, 0 UNPROVEN, 57 rows ---
VERDICT: PASS (all MUST checks)          exit = 0
```

门禁在收敛过程中做了两处**增强**（都不是放宽）：

1. **消费差分产物**：`differential_check.py` 存在且实跑 `exit=0` 时，8 个「有意不 vendor」项标记为 `NOT-VENDORED-COVERED-BY-DIFFERENTIAL` 而不再阻断；产物缺失 / 未 PASS / 超时则**优雅降级**回 `NOTVEND`（不会变成"总是通过"）。
2. **消费授权变更记录**：门禁**每次运行都重读** `verification/production_change_authorization.json`（**单一事实源**，不把副本内联进代码），并只对**精确匹配的 `(path, before_sha256, after_sha256)` 三元组**放行；记录缺失或无法解析时**不授权任何改动**（退回纯基线比对）。任何**未登记**的生产路径改动仍然 FAIL。

检查项数量由 52 行增至 **57 行**，新增的全部是**加严项**：跳过期三态契约（`skipped ⇒ ok is None` 且 `not_applicable == (reason=='not_applicable')`）、合成模式 `unavailable_checks` 必须为空且 `no_unavailable_evidence` 必须 `passed`、`scope` 必须为 **dict**、以及差分消费与授权变更的逐项判定。

**由此 `absorbed/` 吸收交付物的全部 MUST 检查通过**；本文档 §8/§14 列的遗留项除 `compact-ring --mode q4`（`run.py:1031` 的**有意守卫**，非缺陷）外，均已在 §14 标为关闭或已裁定。

### 15.1 对抗性自检：授权例外是"失败即关闭"（fail-closed）

为证明该例外**不是"有这个文件就放行"**，captain 亲自做了一次篡改试验（改完即恢复）：

```
篡改授权记录里的 after_sha256（1 个字符）
  → [FAIL] MUST/f: production path modified: run.py: CHANGED and NOT covered by the authorisation record
  → --- 1 FAIL, 0 NOT-VENDORED(uncovered), 0 UNPROVEN, 57 rows ---   VERDICT: FAIL   exit = 1
恢复记录
  → --- 0 FAIL, 0 NOT-VENDORED(uncovered), 8 NOT-VENDORED-COVERED-BY-DIFFERENTIAL, 0 UNPROVEN, 57 rows ---
  → VERDICT: PASS (all MUST checks)   exit = 0
```

⇒ 记录缺失、JSON 不可解析、或 `(path, before_sha256, after_sha256)` 任一不符，门禁都会**退回纯基线比对并 FAIL**；**检查没有被削弱**，只是认得了这一次经用户授权的变更。

### 15.2 一条流程教训（供后来者）

本项目的基线 `production_hashes_before.json` 是 **hash-only**（只存 sha256 / size / mtime）：它能证明"未被改动"，但**不能用于回滚**（盘上也没有 pristine 副本、且本目录不是 git 仓库）。因此当一次**用户授权的变更**发生之后，"授权 + 逐项登记 + 门禁精确三元组匹配"是**唯一可行**的收口方式，而不是次优选择。**若要保留可回滚能力，基线必须存内容而非只存哈希。**

### 15.3 两次"就地编辑他人产物"的处置与教训（如实登记）

| 事件 | 处置 | 现状 |
|---|---|---|
| **verifier** 做 schema 负例测试时，**就地**修改了本报告的配套记录 `verification/production_change_authorization.json`（删 `changes[0].after_sha256`），随后就地恢复 | 逻辑内容已恢复且门禁复验 `PASS`/exit 0；**但字节布局与 sha256 已不同于原稿**（~2 756 B → 2 938 B），文件内留 `_restored_by_verifier` 说明 | 见 `_provenance` 第 1 条 |
| **captain** 随后修正过时的 `schema_note`（它仍描述门禁读"内联注册表"），并把自己这次编辑也登记进文件 | 仅改说明字段，内容与哈希值不变；门禁复验仍 `PASS`/exit 0（记录现 3 555 B / `c203243a…`） | 见 `_provenance` 第 2 条 |

**教训（verifier 主动提出并写入其报告方法学节）**：**负例测试必须作用于副本，绝不能原地修改他人的产物**。它整轮反复强调"不改他人文件"，却在收尾时破例一次——两次事件都说明：**规则要落到机制上（复制/临时目录）才可靠，靠自觉会在疲劳时失效。**
