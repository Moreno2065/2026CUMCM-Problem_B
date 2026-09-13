# Q3/Q4 模型修订 v2.1（评审采纳版）

> **历史记录，非当前实施依据。** 当前唯一契约为 [v2.2 合并模型与执行契约](D:/CUMCM2026/src/q3+4/Q3_Q4_IMPLEMENTATION_SPEC_v2.2_CONSOLIDATED.md)。本页的 140 tests、演示成绩及代码描述属于先前版本，本轮未重新验证。下述“fallback_exhausted 后标 CERTIFIED_ABSENT”已废止：已确认存在目标的兜底耗尽是异常和未完成，不能证空。本页旧 24 次测量预算、半径恰为 20 m 的采样覆盖验收、2750 m 环上有两个格点等描述，也不能替代 v2.2 的 6 次预算、连续覆盖认证与完整 31 点构造。原文用于审计追溯。

**基础**：v2.0 冻结文件（`Q3_Q4_Paper_Model_Narrative_v2.0.md` 等）不改动；本文档记录对评审意见（`docs/review_feedback.txt`）第 1、2、3、5 点的采纳实现与证明梗概，第 4 点记入"延后事项"。

**代码落点**：`code/`（policy/、geometry/、state/、experiment/、verifier/），测试 `code/tests/`。全部 140 个测试通过（`python -m pytest tests/ -q`）。

---

## 采纳改动一览

| # | 评审点 | 改动 | 主要落点 |
|---|--------|------|----------|
| 1 | Q4 缺"已发现必能清除"保证 | FALLBACK_CLEAR 有限步兜底 + ACTIVE 进展预算 | `policy/fallback.py`、`geometry/fallback_cover.py`、`policy/scheduler.py` |
| 2 | Q3 可简化为确定性收敛链 | 删除"先有效交会"限制，首测后直达 MEC 圆心 | `policy/approach.py` |
| 3 | Q4 73 点兜底偏保守 | 证书兜底扫描点集改为 31 点三角格点 | `policy/certificate_policy.py`、`state/channel_state.py` |
| 5a | 选点贴近清除任务 | NBV 默认 ΔR_MEC/cost（ΔD 保留可选） | `geometry/nbv.py`、`policy/localization.py` |
| 5b | 清除点不必是 MEC 圆心 | READY 清除点取 Z_c 内最近点 | `policy/scheduler.py::_clear_target` + `geometry/clear_zone.py` |
| 5c | 跨案例统计口径 | T_j/n_j 逐案例 + 算术平均聚合 | `experiment/metrics.py` |

---

## 改动 1：Q4 有限步清除兜底（FALLBACK_CLEAR）

**机制**。对每个 ACTIVE 频道跟踪"有效收缩"：R_MEC 相对上次主频道测量下降 ≥ 10% 计为有效；连续 K=3 次测量无有效收缩（含 no_signal 与几何矛盾）→ 进入兜底。另设 ACTIVE 进展预算（24 次主频道测量未 READY 强制转兜底），且 NBV 候选点耗尽（无可评观测点）也直接转兜底——三条路径共同保证"任何 ACTIVE 频道有限步内离开 ACTIVE"。

**兜底执行**。用半径 20 m 圆盘三角格点覆盖该频道当前可行域（凸多边形），贪心最近邻排序后逐个 /clear：

- 格点最近邻间距 a = 20√3 ≈ 34.641 m，行距 30 m。三角格点的覆盖半径（平面任意点到最近格点的最大距离）恰为 a/√3 = 20 m，故覆盖无缝。
- 光学清除不受辐射朝向影响（题设），因此只要源在可行域内（观测一致性保证），必在有限个点内被某次 /clear 命中。
- 序列走完仍未命中 ⇒ 可行域与观测矛盾：记 anomaly，频道标记 CERTIFIED_ABSENT（`absent_basis="fallback_exhausted"`），并由 `verify_fallback_cover`（顶点 + 5 m 网格采样复核 可行域 ⊆ ∪B(p_i, 20)）独立复核，不得静默。

**有限性证明梗概**。可行域 P_c 是 Ω 外切多边形经有限次半平面/圆盘裁剪得到的**有界**凸多边形，面积 ≤ π·1800²；覆盖点数 N ≈ (area + 边界带)/1039.2 m² 有限。每次 /clear 消耗且仅消耗一个格点，序列严格递减 ⇒ 有限步内必然终止（成功 CLEARED 或走完转 CERTIFIED_ABSENT）。结合 READY（有限次清除）与 CERTIFICATE（31 点有限扫描），全任务完成性闭合。

**点数对账**。首测后楔形扇区面积约 3.9 万 m²，面积法估计 ≈ 38 点；细长沙漏形可行域的边界带使实际格点数偏大（演示局实测最大 96 点、最小 3 点），触发记录同时写入 `estimated_points` 与 `n_points`（metrics.json → fallback_records）。

**调度保证**。FALLBACK_CLEAR 为频道级状态，调度优先级最高（FALLBACK_CLEAR > READY > ACTIVE > CERTIFICATE），进入后不被其他频道打断；兜底 /clear 未命中不计入 clear_failure（多数格点本无目标）。

## 改动 2：Q3 确定性 MEC 收敛链

**数学链**（替代 v2.0"首次发现后必须先获得有效交会（≥2 次 bearing）才允许径向移动"）：

1. 首次 direction 后，可行域 ⊆ 半角 1° 楔形 ∩ B(S, 1500)。该扇形（三极值点：顶点 S 与两外角）的 MEC 半径 R0 = 1500/(2·cos1°) ≈ 750.114 m。
2. Q3 全向源：走到当前可行域 MEC 圆心 c，dist(c, 真源) ≤ R_MEC ≤ 750.114 < 1000 ≤ R_eff ⇒ 下一次测量**必然**返回 direction 或 near（无覆盖角约束）。
3. 在 MEC 圆心再测得 direction：新可行域 ⊆ B(c, R_k) ∩ 半角 1° 楔形，同一扇形论证 ⇒ R_{k+1} ≤ R_k/(2cos1°)，q = 1/(2cos1°) ≈ 0.50008。
4. 归纳：首次测向后最多再取 ⌈ln(750.114/20)/ln(2cos1°)⌉ = **6 次**方向观测必达 R_MEC ≤ 20（READY）；near 更早结束。

**工程语义**。Q3 下任何 ACTIVE 频道均可直达 MEC 圆心（`ApproachTracker(mode="Q3").eligible` 恒真）；MEC 圆心 no_signal 属理论不可能的矛盾工况：记 anomaly、可行域保持不变、连续计数，连续 2 次 → 对该频道走 Q4 同款 FALLBACK_CLEAR。NBV/机会式观测机制保留用于跨频道选择与 Q4 主路径的并行优化，Q3 直达链不依赖它。机器狗每次 /measure 仍可同时服务多个频道（停点批量扫描逻辑不变）。

**对抗验证**（`tests/test_q3_convergence.py`）：1000 组随机场景 + 手造边界场景（源距检测点恰 1500 m、误差恒取边界值/交替），逐步断言归纳不变式 dist(c_k, G) ≤ R_k、信号保证 R_k < 1000、收缩比 ≤ q（含 128 边多边形近似 5e-4 容差）、≤ 6 次方向观测内 READY。

## 改动 3：Q4 证书策略接 31 点格点

Q4 CERTIFICATE 模式的兜底扫描点集改为 `q4_lattice_points()`：边长 s=950 m 等边三角格点，保留距原点 ≤ 1800+950=2750 m 的格点，恰 **31 点**（生成器断言 + 评审独立枚举一致）。

**充分性证明梗概**（为何 31 点全 no_signal ⇒ 频道无未清除源）：

1. 任意 G∈Ω 落在某个单位网格三角形内（格点凸包覆盖 Ω，边界余量 ≥ 100 m）；
2. 该三角形三顶点距 G 均 ≤ 950 m（凸集内点到顶点距离 ≤ 最大边长）；
3. 三顶点距原点 ≤ 2750，都在扫描集内，且 950 ≤ 1000 ≤ R_eff（最小接收半径）；
4. 任何以 G 为边界点的闭半平面至少包含其中一个顶点（否则 conv(顶点) 不可能含 G）；
5. 该顶点处必返回 direction 或 near。退化情形（G 在格点/网格边上）由邻接顶点补足同一论证。

**频道证书完成判定**（`ChannelState.refresh_certificate`，Q4）：31 点全部 no_signal（`q4_channel_certified_lattice`）**或** 既有 δ-稳健凸包证书覆盖 Ω（机会式早证，保留 620 m 网格细胞机制）。格点访问顺序由 ΔC/cost 评估给出（就近缺口优先；31 点中 2 点在 2750 m 环上移动成本高，调度照常按成本评估）。runner 的 verifier 新增 `q4_lattice_static`（格点集独立复核）与 `q4_lattice_channel`（频道级复核）。

## 改动 4：NBV 评价指标升级为 ΔR_MEC

`geometry/nbv.py` 新增 `worst_case_radius`：对可采纳示向度区间确定性扫描（沿用 16 边圆盘粗近似评价路径 + 精确上界剪枝，剪枝界 gain ≤ R_MEC(P)），取交集后 MEC 半径的最大值；gain = R_MEC(P) − max R_MEC(交集)。`policy/localization.py` 默认 `NBV_GAIN_MODE="radius"`（ΔD 直径模式保留，config 可选）。动机：最终清除判据是 R_MEC ≤ 20 m，半径下降量比直径更贴近清除任务。

## 改动 5：清除点选为 Z_c 最近点

READY（MEC 触发，R_MEC ≤ 20）频道的实际清除点：`closest_clear_point(可行域顶点, 参考点=机器狗当前位置)`，即 Z_c = ∩_{v∈P_c} B(v,20) 内距当前位置最近者。

**等价性梗概**：圆盘是凸集，P_c = conv(顶点) ⊆ B(x,20) ⟺ 全部顶点 ∈ B(x,20)，故交集只需对顶点取；Z_c 非空 ⟺ R_MEC ≤ 20（MEC 圆心即见证点）。Z_c 内任何位置距源 ≤ 20 m 都保证清除，取最近点减少绕路。near 触发的 READY 不变（clear_position = near 位置）。scheduler 的 READY 最小绕路选择改用该点评估。

## 改动 6：跨案例统计口径

`metrics.json` 新增 `t_per_source_s = T_total_virtual / n_sources`（题面口径 T_j/n_j，附 `t_per_source_basis` 标注）；`experiment/metrics.py::aggregate_cases(metrics_list)` 实现多案例聚合：主口径 = 各案例 T_j/n_j 的**算术平均**（`mean_t_per_source_s`），同时给出 pooled 口径 ΣT_j/Σn_j 并标注"仅参考、不作跨案例比较依据"。

---

## 端到端演示对比（改动前后同 seed）

| 局 | 口径 | 总虚拟时间 (s) | 移动距离 (m) | 测量次数 | 清除尝试 | T_j/n_j (s) |
|---|---|---|---|---|---|---|
| Q3 seed 101（14 源） | 改动前 `demo_output/q3_seed101` | 9303.0 | 27895 | 619 | 14 | 664.5 |
| Q3 seed 101 | 改动后 `demo_output/revision_q3` | **8055.4**（−13.4%） | **26397**（−5.4%） | 460 | 14 | 575.4 |
| Q4 seed 202（16 源） | 改动前 `demo_output/q4_seed202` | 21675.8 | 39224 | 2341 | 16 | 1354.7 |
| Q4 seed 202 | 改动后 `demo_output/revision_q4` | **13359.2**（−38.4%） | **27381**（−30.2%） | 1286 | 100 | 835.0 |

Q4 演示局中 FALLBACK_CLEAR 触发 13/16 频道（定向源背对检测点为常态），全部在有限步内清除成功（used 1–24 点 / 序列 3–96 点），verifier 全过、时间分解对账零警告。清除尝试次数上升是兜底逐点扫描的预期代价，总时间与移动距离仍大幅下降（31 点格点替代 73 点兜底 + MEC 收敛链减少了定位往返）。

---

## 延后事项（future work，本次不实现）

**评审第 4 点：(位置, R_eff, 朝向) 联合可行域模型与"正测点凸包安全区"选点。**

- 已发现频道的 no_signal 语义为"距离超接收半径 ∨ 检测点在辐射半平面外"，与有信号历史联合可排除部分 (位置, R_eff, 朝向) 组合；完整模型需维护三维联合可行集合再投影到位置集合，属研究级扩展。
- "同一源接收区域为凸集 ⇒ 已有有信号测点凸包内必能再次接收"可用于在凸包安全区内优先选择有利交会的测点，但它本身不能替代 FALLBACK_CLEAR 的完成性保证。
- 两项均不改变 v2.1 的正确性论证（兜底不依赖 no_signal 的定位信息量），仅影响 Q4 正常路径的效率上界，记入后续工作。

---

## 验收摘要

- `python -m pytest tests/ -q`：**140 passed**（含新增 `test_q3_convergence.py` 12 项、`test_q4_fallback.py` 12 项）。
- 合成完成性：Q3 11 局 + Q4 11 局全部 100% 完成、verifier 全过、时间分解对账 |ledger−total| ≤ 1e-3、零 reconcile 警告。
- 保留断言未削弱：READY>ACTIVE>CERTIFICATE 优先级、最小绕路、停点扫描顺序、证书残余补访等原测试全部保留并通过（仅按 v2.1 语义更新直达确认与 Q4 证书点集两处期望）。
