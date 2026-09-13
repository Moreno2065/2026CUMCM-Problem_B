# Q3 ML experimental branch

> 2026-09-11 replay-label revision 的完整事实记录见
> [`docs/experiments/q3_ml_experimental.md`](experiments/q3_ml_experimental.md)。

## 定位

`q3_ml_experimental` 是 Q3-only 的离线学习排序支线。它不替换冻结
模型，也不改变 Q3 的几何更新、圆盘证书、`READY` 或
`CERTIFIED_ABSENT` 判定。

运行配置中 `q3_ml_ranker` 默认关闭；开启后，排序器只能在现有
`localization` 候选中选择一个，候选生成、`tau` 门槛和后续状态更新仍由
主线代码负责。Q4 会强制忽略该开关。

## 学习对象

排序器是无第三方依赖的线性 pairwise ranker，特征固定为：

- 主线教师的 `gain/cost` 分数；
- `gain`、`cost`；
- 当前点到候选点的距离；
- `approach` / `nbv` 类型标记。

当前训练默认要求离线分支回放得到的 `long_horizon_cost_s`：在同一决策状态
分别执行候选并沿用同一后续策略直到完成，实际增量虚拟时间较低者作为
preferred。旧的 teacher-score trace 不再默认视为长期收益标签；缺失决策位置
或回放状态无法可靠克隆时直接阻断。训练不会读取 holdout、官方演练或运行时
新数据。

## 训练与启用

先用独立的 teacher/tune 结果生成模型：

```text
python cli.py train-q3-ranker \
  --traces <teacher-trace-1.jsonl> <teacher-trace-2.jsonl> \
  --output <q3_ml_ranker.json>
```

再在实验配置中显式开启：

```yaml
q3_ml_ranker: true
q3_ml_model_path: <q3_ml_ranker.json>
```

不提供模型路径时使用内置的可审计 surrogate，便于跑通支线；正式实验应
使用带有 `model_version`、特征 schema、训练样本数和 SHA-256 的模型 artifact。

## 证据要求

支线结果必须与 `mainline` 使用相同案例、误差字段、预算和成功定义，并保留：

1. 单测与非有限输入拒绝；
2. verifier 与无假证书检查；
3. synthetic adversarial；
4. matched-case 消融；
5. 未参与训练的 holdout；
6. 额外排序计算开销。

只有在正确性 100%、holdout 不劣且收益稳定时，才可另行评审是否形成新的
Candidate；不得回写当前冻结配置。当前新 replay 数据尚未完成全量训练和
holdout 评估，仍只能作为实验支线。
