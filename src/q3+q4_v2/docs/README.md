# Q3/Q4 性能重建工作区

本目录对应用户要求的新文件夹 `q3+4_v2`。本轮模型、文献、原始依据、历史对照快照及验证结果均放在这里。

当前状态：**三条新控制器已经实现，并在相同执行器、20000 步预算、场景和 verifier 下竞争；当前推荐入口是 observation-only 控制器，不用源数或场景标签选策略。Q3 保留稳定的观测自适应与有限兜底，Q4 使用统一学习价值＋滚动候选池，并保留 sparse25/基数证书回退。** 学习路线仍未声称经过大规模训练。旧版分场景门控、冻结配置和官方演练结果属于历史对照，不能作为当前在线策略的先验。

本轮有 135 份来源快照；9 组核对覆盖哈希、历史成本、源数/类型后验、试探清除、可见边界、计时、路线下界算例和文件链接。三路线实测摘要见 `comparison_runs/final_101_10_sparse25_v10/summary_101_10.json`，16 源压力摘要见 `comparison_runs/final_101_16_sparse25_v9/summary_101_16.json`。

学习路线的多 seed 复核见 `comparison_runs/final_learned_multiseed_v3/summary.json`。
当前 observation-only 三路线配对摘要见 `comparison_runs/three_route_fair_observation_v1/summary.json`：60/60 局全清且 verifier 通过，均值、P90、最大值和失败数按 Q3/Q4、10/16 源分组保存。两题在确认 16 个不同存在源后都应用题面最大源数的基数上限，把剩余 UNKNOWN 频道标为可验证的不存在。历史分场景覆盖仍见 `experiments/mainline_scenario_coverage_v7/summary.json`，仅用于参数溯源。

Q3 覆盖环半径的结构消融（1130/1150/1200 m）及新增 seed 复核见 `experiments/q3_ring_radius_ablation_summary.json`；候选半径没有稳定收益，默认锁定 1200 m。

## 入口

- [性能模型](MODEL_PERFORMANCE_V2.md)：目标、概率状态、动作、成本、搜索、机器学习和实验定义。
- [最快路线审计](FASTEST_ROUTE_AUDIT.md)：同预算排名、目标差距和“最快”结论边界。
- [研究依据与取舍](references/SOURCES_AND_DECISIONS.md)：原始题面、研究论文及适用边界。
- [实施与验证顺序](IMPLEMENTATION_SEQUENCE.md)：从可运行基线到学习搜索的可比较阶段。
- [模型数值核对结果](verification/model_checks.json)：局部成本算例、历史账本复算及已执行检查。
- [来源清单](SOURCE_MANIFEST.json)：复制文件的原路径、包内路径、大小和 SHA-256。
- [官方来源核对](OFFICIAL_SOURCE_AUDIT.md)：官方题面页、压缩包和本地输入哈希核对。
- [三路线对比器](compare.py)：同一 seed、源数、场景和执行器下的配对演练。
- [v2 在线入口](run.py)：连接官方 HTTP+JSON 模拟器，或用 `http-synthetic` 走同一协议链路做离线演练。
- [三路线公平配对摘要](comparison_runs/three_route_fair_observation_v1/summary.json)：同一 20000 步预算、同一 verifier、60 局共同案例，以及均值/中位数/P90/最大值。
- [推荐路线入口](recommended.py)：统一 observation-only 控制器；Q3 的密度阈值来自运行中观测，Q4 不按场景切换路线。

官方模拟器测试：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q3 --sim http `
  --base-url http://127.0.0.1:2026 --robot-id TEAM001 `
  --output-dir runs/official_q3
```

启动前把 `--base-url` 换成官方模拟器地址。程序会按
`/enter → /measure → /clear → /exit` 调用，并在输出目录写入
`api_log.jsonl`、`trajectory.csv`、`metrics.json`、`verifier_report.json`
和 `run_report.json`；官方模式没有隐藏真值，因此不会生成
`ground_truth.json`。

完整运行的 `metrics.json` 与终端摘要还会记录
`average_time_per_source_s`（同时保留 `t_per_source_s`）。官方模式不公开
初始源数，因此该值在完成后按观测到的 `cleared_count` 计算，并在
`source_count_for_average`、`average_time_per_source_basis` 中记录分母和口径。
本地先验证 HTTP+JSON 链路时可运行：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q4 --sim http-synthetic `
  --seed 101 --n-sources 10 --scenario mixed `
  --output-dir runs/http_q4_smoke
```

`--policy` 的生产路线为 `learned`，还可选择 `probabilistic`、`geometry`
以及独立实验路线。Q4 的 `q4-bisect` 在在线确认 16 个存在频道后，对连续
定位无收缩的难源使用带几何证明的中段双探点；`q4-shadow` 以它为快速主策略，
仅在可观测停滞时让小型稳健后验一次性改选测点。两者结果分别见
[q4_bisect/RESULTS.md](q4_bisect/RESULTS.md) 和
[q4_shadow/RESULTS.md](q4_shadow/RESULTS.md)。远端模式的控制器只使用已收到的
观测，不读取源数、场景或隐藏真值。

## 文件组织

```text
q3+4_v2/
  MODEL_PERFORMANCE_V2.md
  IMPLEMENTATION_SEQUENCE.md
  inputs/                     原题 PDF、接口 DOCX、提取文本
  references/                 文献与决策依据
  baseline/
    code/                     历史 Python 源码、配置、测试、已有模型快照
    docs/                     历史模型、契约、学习结果说明
    evidence/                 Q3 一局账本、Q4 六局配对证据与分支选择记录
  tools/collect_sources.ps1    收集来源并核对哈希
  compare.py                  三策略等预算配对演练入口
  recommended.py              observation-only Q3/Q4 推荐路线入口
  run.py                      官方 HTTP+JSON／本地 HTTP 演练入口
  geometry_joint/             几何定位＋联合路线实现
  probabilistic_search/       概率推断＋试探清除实现
  learned_search/             学习策略／价值＋搜索实现
  q4_bisect/                  Q4 中段双探点实验策略、证明抽查和冻结结果
  q4_shadow/                  Q4 快速主策略、风险影子后验及配对审计
  verification/
    check_model.py            本轮模型算术与局部关系核对
    model_checks.json         检查结果，不是新策略跑分
  SOURCE_MANIFEST.json
```

`baseline/` 仅用于追溯和实施复用。没有复制大量历史重复实验目录、缓存、加密行为日志或旧测试临时目录。旧模型中指向原工作区的链接保持原样，以保留原文；本轮交付的入口与验证使用包内路径。

复核命令，在本目录执行：

```powershell
python -X utf8 verification/check_model.py
```

若需要重新收集来源，在原工作区仍可用且历史文件未变化时运行：

```powershell
powershell -NoProfile -File tools/collect_sources.ps1
```

收集器发现已有快照与当前源文件不同会停止，不会静默覆盖。工作区目前不是 Git 仓库，使用来源哈希标识此次快照。

## 本轮目标复核与当前生产版本

最新生产配置保存在 `production.py`（`recommended.py` 与 `run.py` 共用同一份配置，`tools/check_entry_equivalence.py` 检查两者逐字段一致）。Q4 在 v2 基础上启用合并路由：覆盖停点按交会角补测 ACTIVE，绕路 ≤500 m 的可清除源就地清除。当前权威摘要为 [final_recommended_v3_summary.json](tuning_runs/final_recommended_v3_summary.json)，7 种子复核与被否方案见 [ROUND1_MERGED_ROUTING.md](tuning_runs/ROUND1_MERGED_ROUTING.md)。

最终五种共同种子配对记录见 [final_recommended_v2_summary.json](tuning_runs/final_recommended_v2_summary.json)。20/20 局完成并通过 verifier：Q3/16 平均 **269.228 s/源**、P90 **280.502 s/源**，Q4/16 平均 **383.173 s/源**、P90 **445.614 s/源**；Q3/10 平均 437.356，Q4/10 平均 801.032。朋友参照为 Q3 176.25、Q4 290 s/源，当前生产配置尚未达到，且四组 `target_hit_count` 都为 0。

三路线同场基准仍见 [three_route_fair_observation_v1/summary.json](comparison_runs/three_route_fair_observation_v1/summary.json)，滚动消融见 [three_route_rolling_16_summary.json](tuning_runs/three_route_rolling_16_summary.json)。Q3 的滚动候选在共同种子上变慢，故没有进入生产；Q4 的滚动候选降低了平均移动成本，但尾部仍明显受场景影响。140 m 直接试探、13 点环、强制 Q3 MEC 圆心和 Q4 短发现环都保留为可复现实验开关，没有因为单个种子收益替换主线。

Q4 证书访问顺序在独立 20 种子留出集上由 468.039 降到 464.710 s/源（16 源），并同步降低 P90；它保留全部 25 个证书点，只优化开放路径顺序。这个收益已锁入当前入口，但仍不构成未知地图上的最快证明。正式评测时仍应只依赖在线观测；命令行源数和场景参数只用于生成案例与统计分组。

