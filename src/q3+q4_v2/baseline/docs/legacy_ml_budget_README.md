# Q3 ML self-learning budget run

日期：2026-09-11  
支线：`q3_ml_experimental`  
基线：Candidate v1 冻结配置（`candidate_v1_FROZEN_CONFIG.yaml`）

## 数据与训练

- `block01`–`block07` 使用 seed offset `700000`–`760000`，共 42 个 Q3
  teacher 训练案例；全部冻结主线成功。
- `block08` 使用 seed offset `770000`，完全留作最终评估，未参与训练。
- round 1：42 个 teacher trace，661 个偏好对。
- round 2：42 个 teacher trace + 42 个支线探索 trace，共 84 个 trace、
  1737 个偏好对。
- round 2 模型：`models/q3_ml_ranker_budget_r2.json`，SHA-256：
  `42fea625ffc52b6a11bc52bbf30edf31758951e5ac7a4bed7fda1b1ddbd8d234`。

支线探索只使用 `block01`–`block07` 的 ablation 集；`block08` 的
matched、stress、holdout 均在训练完成后才运行。

## round 2 结果

`ΔT = q3_ml_experimental - mainline`，负值表示更快。

| 集合 | 案例 | 成功 | verifier 失败 | 平均 ΔT | 中位数 ΔT | 最差 ΔT |
|---|---:|---:|---:|---:|---:|---:|
| matched | 6 | 6/6 | 0 | -16.4 s | +4.7 s | +245.5 s |
| stress | 12 | 12/12 | 0 | +9.3 s | 0.0 s | +541.7 s |
| holdout | 6 | 6/6 | 0 | -48.0 s | +36.4 s | +408.7 s |

结果文件：

- `r2_matched/q3_ml_budget_r2_matched_20260911/suite_summary.json`
- `r2_stress/q3_ml_budget_r2_stress_20260911/suite_summary.json`
- `r2_holdout/q3_ml_budget_r2_holdout_20260911/suite_summary.json`

## 门槛结论

所有案例均完成且 verifier 通过，没有假证书；但收益不稳定，stress 和
holdout 都存在明显最差退化，不能满足“稳定收益、最差不回归”的晋升条件。

因此本轮模型继续保留在实验支线，未改写 `FROZEN_CONFIG`，未进入官方演练
或正式测试。

## 2026-09-11 replay-label 修正记录

对历史 `src/q3+4/code/cases` 做 canonical case hash 审计后，确认本目录之前
不能作为完全独立的数据证据：819 个案例中只有 685 个唯一 hash，存在 123 组
重复；按 tune/ablation/stress/holdout 分组有 8 个跨 split hash 重叠。例如
`candidate_v1` holdout 与本目录 `block01` ablation 共享 `case_seed=900000`。
旧数据未覆盖，旧 round 1/round 2 结果仍保留，但不再标记为独立 holdout 证据。

新的、未覆盖旧目录的数据集写入：

`src/q3+4/code/cases/q3_ml_replay_20260911_v1/`

- train：500 局，seed `2000000–2000499`；
- explore：1000 局，seed `3000000–3000999`；
- holdout：1000 局，seed `4000000–4000999`；
- 新三 split 共 2500 个唯一 canonical hash，manifest 的
  `cross_split_ok=true`；与历史案例文件的跨 split 审计没有新 hash 碰撞。
- manifest SHA-256：
  `b85ba78438a7823ad6b2cce1898018dc11dd7791db49a3140c7b0427869af7a8`。

本轮还修复了决策位置进入 trace、训练/推理距离特征一致性、训练集归一化、
长期分支回放标签和缺失标签阻断。新数据尚未完成全量 replay、模型训练、
matched/stress/最终 holdout 对照；因此本 README 不新增全量收益结论，也不声称
主线接入。已完成的 pilot 闭环如下：

- `replay_labels/train_q3_00001.jsonl`：53 个 baseline decisions、36 个可标注
  active decisions；
- `replay_labels/explore_q3_00001.jsonl`：59 个 baseline decisions、43 个可标注
  active decisions；
- `models/q3_ml_ranker_replay_pilot.json`：36 个 replay pair，SHA-256
  `c11cb417985914669cefe6fecf24fea8345393ee7aa6bb4d6a273faf812f48ec`；
- explore calibration 得到 `takeover_gate.enabled=false`，因为 24 个分歧
  没有形成 worst-saving 不低于 0 的安全接管子集；
- 新 holdout 前 20 局：baseline 与 gated pilot 均 20/20 成功、0 verifier
  failure，mean/median `t_per_source` 均为 `466.668/484.741 s`，paired
  ΔT（ML−baseline）mean/median/worst regression 为 `0.000/0.000/0.000 s`；
  相对 Candidate v1 的 20% 目标为 `373.335 s/source`，pilot 未达到。
- 新 synthetic adversarial 8 局（dense、sparse、boundary、r_eff_low、rim、
  near_early、parallel_bearing、empty_channels）：两组均 8/8 成功、0 verifier
  failure；mean/median `t_per_source` 均为 `479.465/496.367 s`，paired ΔT
  mean/median/worst regression 为 `0.000/0.000/0.000 s`。该组与新 holdout
  共 1008 个 canonical hash，审计无重复且 `cross_split_ok=true`。

这些结果只说明 pilot gate 的安全回退行为，没有证明收益，更不能替代 500 局
标签训练或完整 holdout。单个 10 源案例 replay smoke 已耗时 88.534 s，当前
串行实现不适合直接启动 500 局长任务；后续应先做可复现的批量/并行化，再扩大
训练规模。
