# Q3/Q4 最终交付验收记录

验收日期：2026-09-13

## 版本口径

- `Q3_Q4_Paper_Model_Narrative_v2.0.md` 按用户指定归类为 V1 保证性叙述，SHA-256 为 `95774d80c6edf6bf71366c50573a4e3af2a95d7ce3308a1bf117585896aa1a02`。
- V1 可执行比较基线为 `src/q3+4/code/configs/candidate_v1_FROZEN_CONFIG.yaml` 与对应 CLI。
- V2 最终求解器为 Q3 `q3_joint_search_clear_route_v5`、Q4 `q4_21station_exact_route_v4`。
- 论文统一采用“V1 保证层继承、V2 决策层升级”的叙述；V1 负责状态、证书、停止与 verifier 门禁，V2 在同一门禁下优化合法动作次序和共享路线。

## 主实验与统计证据

- 120 个共同案例、每例两种策略，共 240 次主运行；`tables/run_level.csv` 中 240/240 均为 `accepted=True`。
- Q3：V1/V2 平均每源虚拟时间为 447.49/232.83 s，平均降低 48.0%，95% bootstrap CI 为 46.6%～49.3%，60/60 配对案例更快。
- Q4：V1/V2 平均每源虚拟时间为 1119.44/454.95 s，平均降低 59.4%，95% bootstrap CI 为 57.9%～60.9%，60/60 配对案例更快。
- 置信区间采用案例级重采样、固定种子 20260913、10000 次 percentile bootstrap。

## 消融与敏感性

- 消融共 520 次运行，503 次通过完整门禁；17 次失败全部来自 Q4 去除 16 源基数停止的 16 源负对照。这 17 次只用于报告安全性，不进入效率比较。
- Q3 主要效率来源为联合开放路线；Q4 主要效率来源为 crossbar 条件探点。
- 锁定参数邻域敏感性共 270 次运行，270/270 通过 verifier；结果只作事后稳健性检查，不用于重新选参。

## 图件与论文

- `paper_evidence/figures/` 仅含图 7～15 共 9 个 RGB JPG，无 PNG、PDF 或其他格式；最小边长不低于 1614 px。
- 图 7～15 均有源数据、生成脚本、文件尺寸与 SHA-256 清单；图号在 Markdown 和 Word 中均按 7、8、9、10、11、12、13、14、15 排列。
- 最终 Word：`paper/B题论文_Q3Q4_V1V2最终替换版.docx`，SHA-256 为 `214bdc90d6304733f4c2b8a5ebc6876da35267d89987fd08a8d6847c359b4139`。
- Q1/Q2 分析区 XML 哈希为 `c2d31856e515eff57c087405843569df308fbbca92a58a6ef580972da6cafaba`，Q1/Q2 模型区 XML 哈希为 `9a9a4240cbc2309270916b487e912b4e3e10a95a5fdeccf82769f2c85add2fb2`；替换前后均一致。
- 公共符号表中 9 个 Q3/Q4 条目已更新，旧“31 点三角格点”和“100 点光学兜底”表述已清除。
- Word 导出为 28 页 A4 QA PDF 后逐页检查；未发现图表裁切、标题孤行、表格断裂或附录缺项。QA PDF 和渲染 PNG 不属于论文图件交付格式。

## 自动化检查与已知限制

- `python -m pytest src/q3+q4_v2/paper_pipeline/tests -q -p no:cacheprovider`：25 passed。
- V1 原仓库测试：334 passed、4 failed。4 个失败均来自遗留 Addendum F 图件测试；其所需的 8 个 `src/q3+4/code/figures/scripts/plot_fig*.py` 已不存在。V1 算法、状态机与 verifier 测试通过。为保持 V1 冻结基线，未修改其算法代码或把该缺失伪装为通过。
