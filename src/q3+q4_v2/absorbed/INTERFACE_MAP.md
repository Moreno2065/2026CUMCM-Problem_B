# v2 运行栈 ↔ Q3_Q4_V3 client 契约 接口图

`absorbed/INTERFACE_MAP.md`（t1 交付物 · interface-scout）。**只写结论 + file:line 证据**；未决项集中在 §7。
`HERE` = `D:\CUMCM2026\src\q3+q4_v2`；`LEG` = `HERE\baseline\code`；源包 = `D:\CUMCM2026\src\Q3_Q4_V3`（只读）。

## 1. 契约（权威来源，已被 adapter-eng 与 verifier 双向确认）

- 源 solver 期望：`client.act(path, position=None, channel=None)`；`/measure` → `{'measure_result': 'no_signal'|'near'|'direction', 'svd_deg'(仅 direction)}`；`/clear` → `{'clear_result': 'success'|'no_target_in_range'}`；属性 `client.position` / `client.virtual` / `client.rows` / `client.channel`。
- 权威实现：`workstreams\q4_local_optimization_20260912\offline_world.py:4-58`（`ObservationClient` + `World._act`）；Q3 侧同源参考 `code\tests\verify_q3_all_sources.py:11-52`（`World`）。
- 计时口径（`offline_world.py:33,37,51`）：move = dist/5；measure +5 s；换频道 +1 s（**仅由 `/measure` 触发**，比较“上一次测量频道”，初值 1）；`/clear` **不**换频道；clear 成功 +5 s、失败 +3 s；`/enter`、`/exit` 不推进。与 v2 `geometry\constants.py:20-24` 及 `executor\action_executor.py:126-128` 完全一致。
- `rows`：每次 act（**含 `/enter`、`/exit`**）恰好追加一行（`offline_world.py:55-57`）⇒ `len(rows)` 就是动作序号；上限语义 550（Q3，`q3_optimizer_v5.py:166`）/ 3500（Q4，`strategy_v4.py:240`）。三台 solver 只用 `len(client.rows)`：`q3_optimizer_v5.py:75,125,166,231`、`strategy_v4.py:32,39,45,105,136,153,166,202,236,240`。
- 其它用法：`position` 供 `np.asarray/math.dist/[position]+list`（`q3_optimizer_v5.py:100,119,122`；`strategy_v4.py:78,194,226`）；`virtual` 只出现在报告字段（`q3_optimizer_v5.py:137,140,261`；`strategy_v4.py:158,304`）；`channel` 仅 Q4 `strategy_v4.py:89`；reply 被 `copy()` 并写入结果 JSON（`strategy_v4.py:45,154`）⇒ **reply 必须 JSON 可序列化**。

## 2. v2 侧对应符号（file:line）

| 环节 | 符号 |
|---|---|
| 协议 | `api\protocol.py:34` `ENDPOINTS`(4 端点)；`:44/:45` 结果枚举；`:32` `POSITION_BOUND=2e6`；`:117/:132` `validate_channel/validate_position`；`:251-262` `accepted=false` 只带 3 个公共字段且 `virtual_time_s=0`；`:308-309` 非 direction 禁止 `svd_deg` |
| HTTP 客户端 | `api\client.py:45` `ApiClient(base_url, timeout=5.0, robot_id="TEAM001")`；`:61` `post()`（urllib）；`:111-126` `enter/measure/clear/exit` |
| 会话 | `api\session.py:28` `Session(client)`；`:33-38` `position/current_channel=1/virtual_time/real_deadline`；`:99-120` `enter()`；`:122-131` `measure()`（**accepted 才**推进）；`:133-141` `clear()`（不切频道）；`:79-93` 400/415→`ProtocolError`，409/其它→`SessionError` |
| 执行器 | `executor\action_executor.py:49` `ActionExecutor(backend)`；`:72/:76/:80` `position/current_channel/virtual_time`；`:99/:106` `enter/exit`；`:115-159` `move_and_measure(x,y,ch)->MeasureOutcome`（`.result/.svd_deg` 在 `:137-138`）；`:161-195` `clear_at(x,y,ch)->ClearOutcome`（`.clear_result/.success` 在 `:175-176`）；`:63,211-220` `api_log`；`:85-86` `local_virtual_time` |
| 模拟器 | `experiment\simulator.py:206` `SyntheticSimulator(mode,seed,n_sources,scenario,...)`；`:281-297` `_measure_result`（≤5 near / ≤r_eff direction，svd 两位小数 `:293`）；`:299-306` `_clear_result`（≤20）；`:417-438` `_do_measure`；`:440-453` `_do_clear`；`:478` `SimulatorBackend`；`:603` `SimulatorHTTPServer`；`:470-471` `ground_truth()` |
| 配置 | `experiment\config.py:69` `MainlineConfig(...)`；`production.py:120-136` `runner_kwargs(mode)`；`:201-207` `dump_policy_snapshot()` |
| 运行与计时 | `runtime.py:685-746` `run_case(mode,seed,n_sources,scenario,scheduler_cls,output_dir,...)`；`:749-770` `report_line(report)`；`run.py:961-976` `_make_backend`（http / http-synthetic 两种构造） |
| 调度接口 | `policy\scheduler.py`（`plan_stop_measures` 导入点 `runtime.py:29`、`experiment\runner.py:39`）；`experiment\runner.py:155-161` `scheduler.decide(ks,pos,ch)->Mission`；`runtime.py:333-346` 读 `mission.kind/target/channel/channels/meta`；循环 `runner.py:134-175` |
| 验证器 | `baseline\code\verifier\{geometry,q3_cover,q4_grid,q4_sparse}_*.py`（导入点 `runner.py:42-52`）；入口 `runner.py:787-904` `_verify()`（`all_ok` 起点 `True` 在 `:794`）——**见 §5 第 4 条** |

## 3. sys.path 与撞名（已实测）

- `run.py:25-32`、`runtime.py:15-18` 在导入期把 `HERE` 与 `HERE\baseline\code` 插到 `sys.path[0:0]`（顺序：HERE 在 0，LEG 在 1）。
- 因此顶层名**已被占用**：包 `geometry\`、`policy\`、`state\`、`executor\`、`experiment\`、`verifier\`、`api\`、`tests\`；模块 `lookahead.py`、`production.py`、`rolling.py`、`runtime.py`、`run.py`、`compare.py`、`recommended.py`、`cli.py`、`conftest.py`。
- **唯一真撞名是 `geometry`**：`baseline\code\geometry\__init__.py:4` 只导出 `constants`。实测：目标包路径就位后 `import geometry` → `baseline\code\geometry\__init__.py`；`from geometry import hull/bearing_halfplanes/clip_polygon/minimum_circle` **全部 `ImportError`**（活体例子：源 `q3_optimizer_v4.py:10`）。
- 结论（已落地）：absorbed 内**零裸顶层 import**，全部显式相对 import；源 `geometry.py` 改名 `geometry_src.py`（见 `absorbed\q3_v5\geometry_src.py`、`absorbed\q4_v4\geometry.py` 为包内副本）。
- 另一重撞名：`coverage.py`。源 `strategy_v4.py:8` `from coverage import ...` 在本机会拿到 PyPI `coverage`（§8 第 3 条）⇒ 必须 `from .coverage import ...`。

## 4. 适配类设计（captain 批准，adapter-eng 已实现）

实际落地签名（**以代码为准**，与本文件早前建议名不同）：

- `class AbsorbedSolverClient`（`absorbed\adapters\v3_client.py:69`）
  `__init__(self, executor, *, on_reject="raise", virtual_source="reported", real_time_budget_s=0.0, clock=None)`（`:91-92`）。首参是 **`executor`**（非 `action_executor`）；额外 `real_time_budget_s` 默认 0 = 关闭，与源侧一致。`:93-96` 校验枚举；`:103` `self.rows=[]`；`:104` `self.rejects=[]`。
- 属性：`executor`（`:113`）；`position` → `self._executor.position`（`:117-119`）；`channel` → `int(self._executor.current_channel)`（`:122-124`）；`virtual` → `virtual_source=="local"` 时取 `executor.local_virtual_time`，否则取 `executor.virtual_time`（`:127-131`，默认 `"reported"` = 源侧口径）；`n_acts` → `len(self.rows)`（`:134-135`）。
- `act(self, path, position=None, channel=None)`（`:141`，签名同源 `offline_world.py:21`）：`:150-151` 非法 path → `ValueError`；`:154` 现实时间闸门；`:161-167` `/enter` → `executor.enter()`，reply `{'status':'success','accepted':True,'virtual_time_s':v0}`；`:169-174` `/exit` → `executor.exit()`；`/measure` → `executor.move_and_measure`；`/clear` → `executor.clear_at`；每次 act 追加一行，形状 `ROW_KEYS`（`:60-62`：`sequence/path/position/channel/response/movement_s/switch_s/operation_s/virtual_before_s/virtual_after_s`）。会话顺序对齐源侧：重复 enter → `RuntimeError('Enter twice')`（`:163`）；会话未开 → `RuntimeError('No active offline session')`（`:171,183`）。
- 实现要点：本模块**不 import 任何 v2 模块**，只按鸭子类型调用 executor（`:74-76`）⇒ import 期零副作用、可离线构造。

## 5. 差异与降级（必须显式登记，不许静默近似）

1. **`accepted=false` 在源侧无对应态**（源 world 恒 `accepted=True`，`offline_world.py:25,27,44,53`；v2 可返回，`protocol.py:251-262`）→ 默认 `on_reject="raise"` 抛 `AbsorbedActionRejected`（`:65-66`），把原始响应带进异常；`"return"` 仅供调试，其 reply **不含** `measure_result/clear_result`（引擎随后 KeyError，刻意如此）。禁止映射成 `no_signal`（会污染几何状态）。
2. **`/enter` / `/exit` 字段**：v2 响应多带 `accepted` / `real_timestamp_ms` / `virtual_time_s` / `max_*_duration_s`；适配层补 `status` 字段并透传，**不改数值语义**。
3. **虚拟时间口径**：v2 权威值来自响应 `virtual_time_s`（`session.py:119,130,140`；`simulator.py:495-499`），另有本地账 `executor.local_virtual_time`（`action_executor.py:85-86`）与 `RECONCILE_TOL=1e-3` 对账（`:27,201-209`）。源侧是纯本地累加（`offline_world.py:54`），差别 ≤1e-6/动作且**不参与分支**（§1 末条）⇒ 无决策影响。
4. **v2 verifier 不可复用**：`GameRunner._verify()`（`runner.py:787-904`）的 `all_ok` 从 `True` 起算（`:794`），全部检查来自 v2 证书/MEC 状态；套在吸收引擎上会**空检查通过 = 假 PASS**。⇒ 吸收路径用 `absorbed\adapters\absorbed_verifier.py`（自带 scope 声明，`:549`；rows 结构与上限核对 `:457-488`）。
5. **动作粒度**：v2 是 Mission/stop-plan 级（`runner.py:155-161` + `runtime.py:324-332,364-365,548` 会把一个停点展开成多频道序列），源 solver 是原子 act 级 ⇒ 吸收路径**不走** v2 停点合并/`measure_last` 链/cardinality 截断；与 v2 现有策略比 `n_switches/T_switch` 天然不同，属**策略差异而非协议缺陷**，已登记进 `ABSORBED_SOLVERS.md`。
6. `/clear` 语义一致（20 m、每源一次、不切频道），**无降级**。
7. 误差场数值口径不同（v2 `error_field_type∈{random_fixed,boundary,structured}`，`simulator.py:164-203`；源 world 用 `plus/minus/zero/sine/hash`，`offline_world.py:13-20`），但同为“同点固定、幅值 ≤1°”⇒ 决策路径一致、案例结果不同，**不要“修正”**。

## 6. 入口（captain 批准，已实现）

`absorbed\run_absorbed.py`：`--mode {q3,q4}` `--engine {q3-v5,q4-v4}` `--sim {http,http-synthetic}` `--base-url` `--robot-id` `--seed` `--n-sources` `--scenario` `--output-dir`（另有 `--timeout/--on-reject/--virtual-source/--real-time-budget/--quiet`，`:103-132`）。

- 分派：q3 → `solve_optimized_v5(client)`（`:154`）；q4 → `absorbed.q4_v4.locked.solve_locked(client)`（`:171`）；调用序列同源 `run_offline.py:22`（`act('/enter')` → solve → `act('/exit')`）。
- 复用：`runtime.report_line`（`:245-260`，带 fallback 并记录来源）；`production.dump_policy_snapshot`；`runtime_bridge.json_safe` 做 numpy 安全编码（`:198-199`）；`output_dir.mkdir`（`:277`）。
- 产物：`engine_result.json` / `actions.csv` / `api_log.jsonl` / `client_rows.jsonl` / `client_api_log.jsonl`（HTTP 原始日志）（`:13,495-497,524-540`），另由 `absorbed_verifier` 产出 `verifier_report.json` 等。
- 退出码：`:560` `return 0 if ok else 1`。

## 7. TODO / 未决

- **未跑**：`absorbed.q3_v5` / `absorbed.q4_v4` 端到端差分（源树 vs 移植，同 seed 逐位）；`run_absorbed.py --sim http-synthetic` 两局；`solve_locked` 行为等价性；官方 `--sim http`（需真实 base-url）。→ 归 t6/t7。
- 未做哈希实算（仅逐字符比对）；`@njit(cache=True)` 在目标目录的写权限已由 `absorbed\q4_v4\__pycache__\ordered_tour.solve_ordered-*.nbc/.nbi` 的存在间接证明可写，但未做正式验证。
- 源包证据缺口：参考 client `rows` 的行内字段是否有 solver 之外的消费者——三台 solver 只用 `len(rows)`（§1），故适配层按参考 schema 自建行即可；`practice_all_sources_fast.py:161` 的 `row['response']['clear_result']` 属离线桩路径，`response` 键必须存在（已提供）。

## 8. 实测环境事实（captain 亲测；带 * 者为 interface-scout 独立复跑一致）

- 本机 `python 3.13.9 (Anaconda)` 可执行；numpy 2.3.5 / scipy 1.16.3 / numba 0.62.1 / shapely 2.1.2。*shell / glob / grep 均可用。
- 目标包全栈可用：`python -X utf8 run.py --mode q3 --sim http-synthetic --seed 101 --n-sources 10 --scenario random --output-dir runs/_captain_smoke` → `complete=true, verifier_all_ok=true, wall_clock_s=1.428`。
- **Q4 闭包在本机无法直接导入**：`import numba` 会把 PyPI `coverage` 装进 `sys.modules`（`numba/misc/coverage_support.py:114`），随后 `candidate.py:8` 的 `from coverage import ...` 拿错模块；预置本地目录反而令 numba 崩溃 ⇒ **必须显式相对 import**。*复跑：`import numba`(0.62.1) 后 `sys.modules['coverage'].__file__` = `anaconda3\Lib\site-packages\coverage\__init__.py`，`from coverage import triangle_certificate` → `ImportError`。
- **socket 劫持 3 处**（import 期置 `socket.socket=deny` / `create_connection=deny` / `OpenerDirector.open=deny`）：`bridge_v4.py:9`、v3 `bridge.py:9`、v2 `base.py:8`（另 v1 `experiments.py:9` 经 `base.py:13` 间接触发）⇒ 不删除则本包 urllib 通路立刻失效（*复跑：同款三行后 `urlopen` → `RuntimeError`）。已由 `absorbed\adapters\socket_guard.py` 处置。
- **源 Q3 侧可正常导入**：`VERSION=q3_joint_search_clear_route_v5`、21 项参数、`solve_optimized_v5(client, progress=None)`。*复跑一致。
- *Q4 锁定参数：`strategy_v4.solve` 形参 **36 个** = `selection_lock.selected_parameters` **36 个**，同名同序、set diff 为空，`station_spec` 是唯一 None 默认；`version=q4_21station_exact_route_v4`（任务描述里的“25 项”应改为 36 项）。
- *v2 执行器端到端：enter 后 `rows=1, virtual=0`；`move(0,0,1)` `vt=5.0, dt=(0,5,0)`；`move(120,0,3)` `vt=35.0, dt=(24,5,1)` 且 `channel=3`；`clear(0,0,3)` `no_target_in_range, dt_clear=3.0`、channel 不变；`exit` 后 `rows=5`；`local==virtual`、无对账警告 ⇒ §1 的 `/enter`、`/exit` 各占一行与 `len(rows)` 口径成立。
