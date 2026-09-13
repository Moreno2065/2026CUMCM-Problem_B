# 最快路线审计

## 当前生产状态（观察-only v1）

当前可执行入口是 `recommended.py`。命令行的 `--n-sources` 和
`--scenario` 只用于生成仿真案例及输出目录，不参与控制器选择。Q3 使用
学习价值＋搜索，并依据已经观测到的 ACTIVE/READY/CLEARED 数量切换扫描余量
和一次性小 MEC 试探；Q4 对所有源数和场景使用同一个学习价值＋搜索控制器，
保留 sparse25 有限证书与 16 源基数证书回退。这样在线策略没有提前知道源数
或场景标签。

三路线的同预算配对摘要在
`comparison_runs/three_route_fair_observation_v1/summary.json`。它固定
`max_steps=20000`、相同 simulator/executor/verifier、5 个共同 seed，并按
均值、中位数、P90、最大值和全清状态统计。60/60 局都
`complete=true` 且 `verifier_all_ok=true`。当前观察-only 学习路线的结果为：

| 案例 | 几何定位＋联合 | 概率＋试探 | 学习价值＋搜索 |
|---|---:|---:|---:|
| Q3，10 源 | 516.340 | 526.577 | **437.356** |
| Q3，16 源 | 355.333 | 344.909 | **269.228** |
| Q4，10 源 | 1097.995 | 855.120 | **819.871** |
| Q4，16 源 | 595.890 | 490.811 | **417.799** |

上表是虚拟秒/源的均值；同一摘要还给出每组 P90、最大值、失败数和逐局
计时。它是本地合成仿真证据，不等同于朋友的未知地图或官方评测。

Q4 联合覆盖实验确实把“沿途完成证书”实现进了代码，但未经观测门控时会在
blind-side 场景反复追同一个 ACTIVE 源，尾部变差。加入方向/无信号比例门控后
可避免失控，却没有在公平留出集上稳定击败当前学习路线，因此保留在
`tuning_runs/q4_joint_gate_*` 作为实验路线，不进入当前生产入口。这个门控
结论避免把一次均值收益误当成稳定性能提升。

这份审计回答“能否从方法路线上确保最快”：可以用同场、同预算、同计时器做可复现的经验竞争，但当前证据不能给出所有场景上的全局最快证明。

## 同预算设置

- 固定 `seed=101`，分别测试 10 源和 16 源；Q3 使用 `random`，Q4 使用 `mixed`。
- 三个控制器共用同一个模拟器、执行器、虚拟计时、清除判定和 verifier。
- 三者共用 `nbv_mode=radius`、`opportunistic_reuse=true`、`cert_route_mode=lookahead2`、`q4_joint_rank=true`、`q4_residual_sparsify=true`、Q4 `sparse25` 证书布局。
- 学习路线只能读取在线可见状态；当前权重是透明先验，尚未声称完成大规模训练。
- 最新学习路线在 Q3 已知频道数少于 12 时使用低密度权重，达到 12 后切换高密度权重；Q4 已知频道数达到 12 后对定向兜底覆盖采用测向 warm-start。两者都不改变状态转移或证书集合。
- 推荐主入口的 Q3 清除后扫描采用 `selective_clear`，ACTIVE 余量按源数取 175/150 m；Q4 保持 `state_aware`。该开关只筛选清除后的辅助反馈，不改变主测量、清除成功判定、状态转移或证书集合。

## 历史分场景门控（离线证据）

本节以下的 v7–v14 数字保留用于追溯参数搜索；其中按 `n_sources` 或
`scenario` 选择参数的入口已经从当前生产入口移除。它们不能被解释为在线
策略预先知道测试标签。

在同一执行器上继续做了小步参数搜索后，当前生产入口采用以下门控：Q3 对 10 源使用 175 m ACTIVE 余量和 75 m 一次性 MEC 试探；16 源的 `dense` 场景保留 150 m、30 m 与环顺序 `(0,1,5,4,3,2)`，其余 `random/boundary/sparse` 场景使用 60 m、40 m 与环顺序 `(4,5,0,1,2,3)`。失败仍按正常 3 s 失败成本记账，且不会重复。Q4 显式 `dense` 使用概率路线；learned 16 源分支默认使用 250/500 m，`mixed` 且 16 源在留出复核中锁定为 200/400 m，并加载 `model_q4_mixed16.json`、ACTIVE 重复上限 2、测向 warm-start 75 m；`boundary`/`edge_facing` 的 learned 分支分别启用 30/50 m 一次性试探，`sparse` 保持 0 m。两题在确认 16 个不同存在源后启用基数上限，将其余 UNKNOWN 频道登记为 `cardinality` 依据的不存在；这不读取模拟器真值，也不跳过已确认源的清除。所有试探都保留原有限兜底和完成判据。

## 实测排名

下表保留早期单 seed 三路线配对，作为路线筛选历史；当前推荐入口的最新十 seed 和场景覆盖结果见后文，不能用这张早期表替代最新值。

| 案例 | 几何联合 | 概率试探 | 学习价值 | 当前最快 |
|---|---:|---:|---:|---|
| Q3，10 源 | 581.753 | 565.708 | **527.384** | 学习价值＋搜索 |
| Q4，10 源 | 993.824 | **810.212** | 857.695 | 概率试探＋搜索 |
| Q3，16 源 | 437.713 | 387.167 | **360.553** | 学习价值＋搜索 |
| Q4，16 源 | 1053.870 | 707.466 | **575.015** | 学习价值＋搜索 |

单位为虚拟秒/源；四个案例的 12 行结果都满足 `complete=true`、全源清除，且 `verifier_all_ok=true`。原始摘要：

- `comparison_runs/final_101_10_sparse25_v10/summary_101_10.json`
- `comparison_runs/final_101_16_sparse25_v9/summary_101_16.json`
- `comparison_runs/final_learned_multiseed_v3/summary.json`
- `comparison_runs/q4_belief_multiseed_v1/summary.json`
- `comparison_runs/final_recommended_multiseed_v4/summary.json`（历史 v4）
- `experiments/q3_dynamic_coverage_order/summary.json`（当前门控规则的 20 seed 留出复核）

早期五 seed 复核用于筛选模型和参数：Q3 学习路线平均为 525.715/392.202 秒/源（10/16 源），Q4 学习路线为 868.562/607.438 秒/源，概率路线为 844.820/585.744 秒/源。随后在十个共同 seed 上重新评估并按源数选择主线，结果以 v4 摘要为准；这些复核均全清且 verifier 通过，只用于经验选择，不替代正式评测集。

五 seed 的概率路线结果仅用于历史筛选；v4 是旧的 N 分段选择记录，当前主线以 v7 和后文的 v4 场景覆盖为准。单个 seed 仍可能改变排名，选择结果不是逐局必然胜负。

## 推荐主入口的最新复核

（历史 v11）为避免把一次 seed 的配对结果当成稳定结论，主入口曾在同一执行器、同一预算和十个 seed 上重跑，结果保留在 `comparison_runs/final_recommended_multiseed_v11/summary.json`。该段参数已被当前 v2 入口替代；当前数字见本文末尾的“当前生产复核覆盖”。

`selective_clear` 的安全条件是：Q3 清除后，只有在该点仍可能产生新的 1000 m 排除盘，或活动频道的 MEC 包络可能与停点相交时，才保留辅助测量；相同过滤用于 Q4 会变慢，故 Q4 主入口没有启用它。

场景交叉复核还发现一个密度特例：调用方显式指定 Q4 `dense` 时，推荐入口切换到概率路线。最新 5-seed 覆盖中，16 源 Q4 dense 为 **287.052 秒/源**，mixed 为 **405.897**，boundary 为 **592.790**，sparse 为 **550.026**，edge_facing 为 **671.167**；对应 Q3 16 源 random/boundary/dense/sparse 为 **269.228/311.277/67.576/352.290** 秒/源。90 局全部完成且 verifier 通过。原始记录见 `experiments/mainline_scenario_coverage_v7/summary.json`；早期消融仍保留在 `experiments/q4_strategy_scenarios/summary.json` 和 `experiments/q4_risky_clear/summary.json`。

为检查 Q4 mixed 16 源下的路线选择是否只是单一路线偶然占优，又在同一执行器、同一十个 seed、同一基数上限下直接重跑三条控制器；下表是启用本轮高密度参数前的路线选择基准：`LearnedSearchScheduler` 平均 **475.92 s/源**，`BeliefProbeScheduler` **540.00 s/源**，`GeometryJointScheduler` **659.01 s/源**；30/30 局均完成并通过 verifier。原始记录见 `experiments/q4_strategy_cardinality_compare/summary.json`。因此当前 Q4 mixed 主线选学习路线有直接配对证据，dense 仍按场景覆盖选择概率路线。

最新生产参数又在 5 个共同 seed、10/16 源的 Q3 random 与 Q4 mixed 上把三条路线各跑一遍，共 60 局；60/60 局全清且 verifier 通过。Q3 学习路线平均为 **427.83/269.23 s/源（10/16 源）**，几何路线为 **516.34/355.33**，概率路线为 **526.58/344.91**；Q4 mixed 学习路线为 **819.87/405.90 s/源（10/16 源）**，概率路线为 **855.12/490.81**，几何路线为 **1097.99/595.89**。这是当前三路线在相同案例、预算与成功标准下的最新配对证据，原始摘要见 `comparison_runs/three_route_multiseed_v2/summary.json`。

随后把 Q3/Q4 的 16 源主线单独用五个共同 seed（101、202、303、404、505）重跑，形成 30 局的 v3 配对审计；30/30 局仍全清且 verifier 通过。Q3 random 的学习/概率/几何平均分别为 **269.228/396.399/468.795 s/源**，Q4 mixed 分别为 **405.897/490.811/595.890 s/源**。这组结果与场景覆盖 v7 的主线均值一致，作为当前生产路线的最新路线级证据，原始摘要见 `comparison_runs/three_route_v3_5seed/summary.json`。本轮还验证了“按 ACTIVE 数量自适应缩短 Q3 覆盖环”的候选；它在部分留出种子上变快，却在正式主线种子上回退，因此只保留为离线消融，不进入推荐入口。

（历史 v14）Q4 mixed、16 源曾只改变 25 点有限覆盖证书的访问顺序；该组训练/留出数字仍保留在 `tuning_runs/q4_order_holdout_summary.json`，但当前生产顺序已用 v2 的独立 20 种子复核重新锁定，详见本文末尾。

用当前主线在 Q3 的 `random/boundary/dense/sparse` 与 Q4 的 `mixed/boundary/dense/sparse/edge_facing` 上各跑 5 个 seed、10/16 源，共 90 局，全部 `complete=true`、全源清除且 `verifier_all_ok=true`；最新摘要为 `experiments/mainline_scenario_coverage_v7/summary.json`。这证明了当前完成性路径在这些已覆盖场景内没有漏清，但仍不等于对朋友未知场景的全局证明。

## 与朋友参照的距离

朋友参照为 Q3 `2820/16=176.25` 秒/源、Q4 `290` 秒/源。历史十 seed 主入口数字不再代表当前 v2；当前五 seed 汇总及目标差距见本文末尾。因此当前路线有同预算、多 seed、全清验证的性能证据，但仍不能写成已经达到朋友目标或对未知场景全局最快。

为检查“缩短 Q3 覆盖环”这条结构路线，我保留相同的七点证书和 verifier，只改变六个外环点的半径。1200 m 是默认值；用 1130 m 只在中心 ACTIVE 数量不超过 4 时启用的密度门控，在新增五个 seed 上平均为 491.528/403.176 秒/源（10/16 源），而同一批 1200 m 基线为 469.658/396.145 秒/源；固定 1150 m 在十个 seed 上为 523.886/395.844 秒/源，而对应 1200 m 十 seed 合并平均为 497.687/394.173 秒/源。所有候选均全清且 verifier 通过，但候选没有稳定收益，所以主路线恢复并锁定 1200 m。逐局原始结果见 `experiments/q3_ring_radius_ablation_summary.json`。

## 结论边界

当前生产路线是固定预算下五个共同 seed 的观察-only 配对结果；历史 v7–v14
数字仍可用于解释参数来源，但不再代表在线入口的标签分支。单个 seed 仍可能
改变排名。由于朋友的地图、误差场、混合比例和评测实现尚未提供，也没有对
所有可能场景做穷举或全局最优证书，所以不能保证任何未知场景中它一定最快。
下一步若要提高可信度，应把朋友的原始场景和日志接入同一配对运行器，再锁定
独立留出集上的路线和参数。

复核入口：`python -X utf8 compare.py --seed 101 --n-sources 10 --q3-scenario random --q4-scenario mixed --output comparison_runs/final_101_10_sparse25_v10`，16 源只需把 `--n-sources` 改为 `16` 并使用 `final_101_16_sparse25_v9` 输出目录。

## 当前生产复核覆盖（v2，2026-09-12）

上面的历史门控和 v11/v14 数字保留用于追溯；当前 `recommended.py` 已锁定到
同一 observation-only 接口。Q3 没有启用 13 点环、强制 MEC 圆心或 140 m
试探。Q4 没有启用直接试探和短发现环，而是启用滚动候选池（horizon=3、
coverage_period=3、每个停点最多附带 1 个 ACTIVE 测量）以及
`q4_no_shrink_limit_high=8`。这些开关只改变动作竞争顺序；稀疏覆盖证书、
基数证书、清除条件和 verifier 保持不变。

证书顺序使用 observation-only 门控：中心停点的方向观测占比达到 0.1 才切换到
候选开放路径，低于阈值则保持近邻顺序；该门控不读取源数或场景标签。

最新五种共同种子结果见 `tuning_runs/final_recommended_v2_summary.json`：20/20
局完成并通过 verifier，Q3/16 为 **269.228 s/源（P90 280.502）**，Q4/16
为 **383.173 s/源（P90 445.614）**；Q3/10 为 437.356，Q4/10 为 801.032。
四组都没有命中朋友参照（Q3 176.25、Q4 290 s/源）。因此当前结论是“全清
路径稳定、滚动 Q4 有平均收益”，不是“已达到目标”或“对未知地图最快”。

开放路径 2-opt 只重排有限兜底序列的安全后缀，保留已经尝试的前缀；140 m
试探、13 点覆盖、Q3 直达圆心和 Q4 发现环仍是可复现实验参数。它们在共同种子
上没有证明稳定优于当前主线，故没有推入生产入口。

Q4 的 25 点证书顺序另做了独立 20 种子留出复核：当前顺序 468.039、候选顺序
464.710 s/源（16 源），并降低了 P90 和最大值。候选只交换证书访问顺序，不删
减任何证书点，已经纳入 `recommended.py`；10 源均值基本不变，因此入口没有
按源数做标签分支。
