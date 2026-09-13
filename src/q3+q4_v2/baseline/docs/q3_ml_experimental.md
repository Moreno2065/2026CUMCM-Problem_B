# Q3 ML experimental branch — replay-label revision

日期：2026-09-11  
状态：实验支线；未接入主线。

## 边界

`q3_ml_experimental` 仍然只服务 Q3 候选排序。`FROZEN_CONFIG`、冻结数学模型、Q4 主线、几何约束、verifier、`READY`、`CERTIFIED_ABSENT`、可行域硬裁剪和证书逻辑均未修改。

在线 ranker 只能重排 localization 已经生成并通过主线门槛的候选点；它不能创建候选、改变 `tau`、改变状态更新或参与证书判定。默认配置仍关闭，Q4 会忽略该开关。

## 本轮修正

### 1. 训练/推理特征一致

- runner 在 scheduler 决策前把真实机器人位置记录为 trace 的 `position`。
- `fit_pairwise` 接收 `(preferred, rejected, position)`，训练距离使用该决策位置；缺失位置的 active trace 直接阻断。
- ranker 产生 `q3-linear-ranker-v2` artifact，并从训练 pair 只拟合 z-score `means/scales`；推理复用 artifact 中的统计量。旧 v1 artifact 仍可读取，但不会获得新的归一化统计量。

### 2. 长期收益标签

`policy/q3_ml_replay.py` 提供离线分支回放：在决策边界深拷贝 synthetic simulator、executor、KnowledgeState 和 scheduler，先执行一个候选，再由同一 deterministic policy 继续到任务完成，标签为该分支的增量虚拟时间 `long_horizon_cost_s`。

克隆失败、分支不能完成、没有后续 mission 或超过步数上限时抛出 `ReplayBlocked`，不生成伪标签。在线 scheduler 不调用该模块。

trainer 默认要求 `long_horizon_cost_s`；只有显式选择旧的 `score` 字段时才允许复现历史 teacher-score 训练，旧数据不再被默认当作长期收益标签。

训练后的在线边界还包含 conservative takeover gate：模型首选与 deterministic
首选不一致时，只有候选值正常且 top-two ML margin 达到离线校准阈值才接管；
低 margin、异常候选或 gate disabled 均回退 deterministic 选择。gate 的校准
只读取 explore trace 中的 replay 标签，不读取源真值，也不改变候选池、
`READY`、证书或可行域逻辑。

## 数据隔离

对 `src/q3+4/code/cases` 的历史 JSON 案例做 canonical hash 审计时得到：819 个案例、685 个唯一 hash、123 个重复 hash 组；按 tune/ablation/stress/holdout 分组仍有 8 个跨 split hash 重叠。已确认的例子包括 `candidate_v1` holdout 与 `q3_ml_budget_20260911/block01` ablation 共享 `case_seed=900000`。因此旧 budget 数据不能宣称为完全独立 holdout，旧目录未覆盖。

新数据写入：

`src/q3+4/code/cases/q3_ml_replay_20260911_v1/`

| split | 案例数 | seed 区间 | canonical hash |
|---|---:|---:|---:|
| train | 500 | 2,000,000–2,000,499 | 500，全部唯一 |
| explore | 1,000 | 3,000,000–3,000,999 | 1,000，全部唯一 |
| holdout | 1,000 | 4,000,000–4,000,999 | 1,000，全部唯一 |

manifest：`cases/q3_ml_replay_20260911_v1/manifest.json`；SHA-256：`b85ba78438a7823ad6b2cce1898018dc11dd7791db49a3140c7b0427869af7a8`。新三 split 内部 `cross_split_ok=true`、`unique_hashes=2500`；与历史案例文件的跨 split 审计没有发现新 hash 碰撞。历史目录自身的重复副本仍保留并单独记录。

## 已实际验证

- Q3 ML 与案例隔离 targeted：21 passed。
- 全套 pytest：338 passed，0 failed，411.80 s。
- targeted ruff：`All checks passed`。
- 相关源码 `py_compile`：通过。
- 一局新 train case 的 replay smoke：10 源、53 个 baseline decisions、36 个可标注 active decisions、72 个候选长期标签、88.534 s。
- 新隔离 train case `q3_ml_train_00001` 已持久化 53/36 replay trace；独立
  explore case `q3_ml_explore_00001` 已持久化 59/43 replay trace。
- pilot 模型使用 train trace 的 36 个 pair、train-only z-score；在独立
  explore trace 上校准 gate，得到 `enabled=false`（24 个模型/基线分歧中没有
  能证明最差不退化的接管子集）。模型 SHA-256：
  `c11cb417985914669cefe6fecf24fea8345393ee7aa6bb4d6a273faf812f48ec`。
- 新 holdout 前 20 局 matched 验证：Candidate v1 与 gated replay pilot
  都是 20/20 成功、0 verifier failure；mean/median `t_per_source` 分别为
  `466.668/484.741 s`，paired ΔT（ML−baseline）为 mean `0.000 s`、
  median `0.000 s`、worst regression `0.000 s`。这证明 gate 没有退化，
  但没有证明收益。按当前 Candidate v1 mean 基线，20% 改善门槛为
  `373.335 s/source`；pilot 未达到。
- 新 synthetic adversarial 8 局（`dense/sparse/boundary/r_eff_low/rim/`
  `near_early/parallel_bearing/empty_channels`）同样为 baseline 与 pilot
  各 8/8 成功、0 verifier failure；两者 mean/median `t_per_source` 为
  `479.465/496.367 s`，paired ΔT mean/median/worst regression 为
  `0.000/0.000/0.000 s`。adversarial 与新 holdout 共 1008 个 canonical
  hash，`cross_split_ok=true`、无重复。

## 尚未完成

本轮只完成 pilot replay 训练与一组 20 局新 holdout 验证；没有声称完成 500 局
长期标签训练、5,000–20,000 局扩展训练、完整 matched/stress/最终 holdout
评估或主线接入。单个 10 源案例的长期回放 smoke 已耗时 88.534 s，按当前
未优化的串行实现直接处理 500 局成本过高；pilot gate 因没有安全接管子集而
保持关闭。

下一阶段必须在新标签正确性确认后，再做批量回放/并行化、训练集归一化锁定、tune 与 matched/stress/holdout 三组对照，并报告 mean、median、worst ΔT、verifier failures、成功率、尾部退化和额外计算开销。只要 worst-case 回归或 holdout 不稳定，继续保持实验支线。
