# Q3 负观测约束与整段搜索实验

实现两层独立对照：

- `--solver constraint-search`：保留非凸位置集合，接入 Q3 无信号的 1000 米排除圆、失败清除的 20 米排除圆，以及 near 的位置范围。动作选择沿用生产调度。
- `--solver constraint-macro`：在新状态上比较反馈驱动的单源/双源接近、交会、清除方案；可以在 UNKNOWN 尚未清空时搜索。执行器按显式频道集合计价与执行。无需训练神经网络。

默认 `--solver learned` 保持生产行为。上述两种策略只支持 Q3，Q4 的定向无信号不能使用同一排除圆。既有 `baseline/` 快照未改。

## 运行

在 `src/q3+4_v2` 中执行（下列命令只用本地合成模拟器）：

```powershell
python -X utf8 run.py --mode q3 --sim synthetic --solver constraint-macro --n-sources 15 --seed 101 --scenario random
python -X utf8 run.py --mode q3 --sim synthetic --solver constraint-search --n-sources 15 --seed 101 --scenario random
python -X utf8 constraint_search/checks.py
python -X utf8 constraint_search/benchmark.py --policies production constraints macro --counts 10 13 15 16 --seeds 101 303 505 --tag my_new_run
```

Shapely 2.1.2 已在本机 Python 中可用；依赖见 `requirements.txt`。新输出默认目录包含策略名，避免覆盖同种子的生产输出。benchmark 要求使用尚未存在的 tag。

## 状态的保守性

位置集合用 Shapely Polygon/MultiPolygon 保存，孔洞和分块会参与后续交集；`feasible_region` 仅为兼容旧调度与验证器的凸包视图。原有正观测圆盘使用外切近似；排除圆使用半径减少 1e-6 米的 128 边内接多边形，避免圆盘离散化误删合法位置。测向半平面额外放宽 1e-7 度处理数值边界。位置集合不是协议所有潜变量的精确后验。

UNKNOWN 的集合为空也不会自行宣告缺席，仍使用原有独立证书判据；ACTIVE 集合为空报告几何矛盾。失败清除在该停点原计划的伴随测量执行完后、下一决策前加入位置排除，保持计划账与执行账一致。

## 整段搜索

每次比较基线动作与最多四个附加方案：近源一/二的单源完成、双源完成，以及先执行基线再双源完成。方案最多执行八个动作，依据每次真实返回的方位/near/失败结果更新下一测点。下一段开始前执行一次生产动作，保留覆盖进度。

候选在三个由当前观测生成的地图假设中回放；整段结束后交还带新状态的生产控制器，计算整局剩余账本，未完成分支记为无穷大。候选必须在全部假设完成、所有假设都胜出、均值至少省 100 秒，并改善 mean + 0.2 max，才可取代原动作。这是第一版冻结验证出现尾部回退后采用的稳健门控。

默认整局最多 300 次假设回放；60 秒搜索墙钟预算是额外安全上限。`--segment-budget 0` 关闭搜索，行为应与 `constraint-search` 一致。300 次额度保证通常由确定的工作量截断，而非机器负载决定动作。

未知源数量只使用题目 10–16 上界与已观测到的频道数；未知频道按剩余位置面积抽样，位置/半径须符合已有无信号。这是未校准的规划先验，不是缺席证书。控制器不读取真实 N、seed、scenario、源位置或朝向。真实地图仅由 benchmark 的独立审计器用于验证位置集合包含真源。

## 验证与限制

数据在 `tuning_runs/constraint_search/`，包含逐动作账本、完整局结果、代码散列、每次候选成本与独立真源包含检查。`VALIDATION_PLAN.json` 固定第二组评价种子及采用条件。有限假设搜索没有策略改进保证，不能把预测遗憾或一次大幅提速当成稳定收益。未使用官方正式测试机会。

最终结果与采用结论见 `RESULTS.md`（实验完成后写入）。
