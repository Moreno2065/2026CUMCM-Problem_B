# 论文图证据契约

后端固定为 Python/matplotlib，输出固定为高分辨率 RGB JPEG。所有定量图从 `tables/*.csv` 读取，不在绘图脚本中手工录入实验数值。

## 核心结论

在保留确定性证书与独立验证门槛的条件下，V2 通过联合路线与观测驱动的局部决策显著减少 V1 的固定扫描、往返和重复测量成本；Q3 的主要贡献来自联合路线，Q4 的主要贡献来自 crossbar 条件探点。

## 图形角色

| 图 | 原型 | 唯一证据任务 | 主要审稿风险及控制 |
|---|---|---|---|
| Fig. 7 | schematic-led composite | 把 V1 明确固定为状态—证书—终止的可执行基线 | 不把 V1 写成 V2，也不把保证性上界写成经验效率 |
| Fig. 8 | schematic-led composite | 明确 V1 保证层与 V2 决策层的继承关系 | 不把 V1 的 7/31/100 点写成 V2 实际结构 |
| Fig. 9 | quantitative grid | 展示 120 个严格配对案例中的总体和分源数提升 | 显示样本数、95% bootstrap CI 与逐例散点 |
| Fig. 10 | quantitative grid | 隔离 Q3 模块贡献 | 消融均值只使用 verifier 通过局；小效应如实显示 |
| Fig. 11 | quantitative grid | 隔离 Q4 模块贡献并显示安全性负对照 | 效率与 verifier 通过率分轴，不用失败局“低耗时”获益 |
| Fig. 12 | quantitative grid | 检查锁定参数邻域的敏感性 | 标注只是事后敏感性分析，不据此重选参数 |
| Fig. 13 | quantitative grid | 分解节时来自移动、测量、换频和清除的哪些部分 | 使用同一 60-case 聚合口径 |
| Fig. 14 | asymmetric mixed-modality | 用代表案例解释 Q3 联合路线如何穿插搜索与清除 | 代表例只解释机制，不替代统计 |
| Fig. 15 | asymmetric mixed-modality | 用代表案例解释 Q4 21 站骨干与局部服务 | 站网和实际轨迹均来自运行产物 |

## 统计与来源

- 主比较：每问题 60 对案例；源数 10、13、16 各 20 对。
- 区间：以案例为重采样单位，固定随机种子 20260913，10,000 次 percentile bootstrap。
- 消融：每变体在 10/16 源各 20 个共同案例；不通过 verifier 的局只计入安全性通过率。
- 敏感性：每参数点 10 个固定 13 源案例；所有点均通过 verifier；结果不用于重新锁参。
- 来源：`tables/run_level.csv`、`tables/paired_effects.csv`、`tables/ablation_run_level.csv`、`tables/ablation_summary.csv`、`tables/tuning_summary.csv` 与代表运行的 `actions.csv/ground_truth.json`。

## 输出约束

- 白底、统一方法配色、无彩虹色图、非红绿唯一编码。
- V1 为冷灰紫，V2 为深蓝；负对照为红色叉号或斜线纹理。
- 最终 Word 显示尺寸下中文正文与坐标标签可读；每图最短边不少于 1600 px。
- 图目录只允许 `.jpg`；绘图数据与脚本另存，不混入交付图目录。
