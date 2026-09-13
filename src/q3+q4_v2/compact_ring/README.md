# compact-ring（Q3 实验策略）

这是一条独立 CLI 策略，不改变 `learned` 生产入口。它不使用场景标签、
真实源数或模拟器真值，也不训练神经网络。

默认动作结构：

1. 从原点直接走向半径 940 m 的八点环，不在原点扫描；
2. 每个环点测所有 UNKNOWN，并测 MEC 半径仍大于 80 m 的 ACTIVE；
3. 对 MEC≤80 m 且相对下一环点绕路不超过 350 m 的 ACTIVE，沿环顺路
   补测一次；若成为 READY，则顺路保证清除；
4. 观测确认 16 个源后停止剩余 UNKNOWN 和环点；
5. 环后把 ACTIVE 的补测点与 READY 清除点放入同一候选池，对当前固定节点求
   Held–Karp 精确开放路径；每次只执行第一步并用新观测重规划；
6. ACTIVE 的可行域若能由不超过 10 个 20 m 清除圆覆盖，直接执行有限
   光学覆盖，失败清除作为排除信息；其余交给原定位器；
7. 默认关闭 80/100 m 的赌博式中心试探和假设世界宏搜索。

八点环由项目的精确 `q3_certified` 判定器验证。开放路线长度为
5976.113970 m，最坏边界距离为 998.595 m，小于 1000 m 保证接收距离。

本地演练：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q3 --sim synthetic `
  --n-sources 15 --seed 101 --solver compact-ring `
  --compact-performance-preset
```

冲榜实验 preset（与上面不同，当前只在 Q3/15 随机种子上有小样本配对结果）：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q3 --sim synthetic `
  --n-sources 15 --seed 101 --solver compact-ring `
  --compact-joint-service-preset
```

官方 HTTP 接口：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q3 --sim http `
  --base-url http://127.0.0.1:2026 --solver compact-ring `
  --compact-performance-preset
```

所有关键阈值均可由 `run.py --help` 查看和覆盖。`compact-ring` 只支持 Q3；

## 结构先验实验开关

`--compact-performance-preset` 启用当前推荐的稳定组合：环上只追加预测能把
MEC 压到 20 m 的终局测量；已发现至少 14 个频道后，允许对刚访问的 ACTIVE
连续补测至多 2 次，追加移动预算 300 m。它只使用在线观测。

`--compact-joint-service-preset` 在该组合上增加“剩余覆盖锚点、MEC≤200 m 的
ACTIVE 补测点、READY 清除点”共同开放路径重排；服务点只顺测预测最坏后验半径
不超过 20 m 的其他 ACTIVE。若一个 READY 清除点本身可替换尚未访问的证书锚点，
它会在同一位置完成清除和该锚点的 UNKNOWN 扫描，保持八点证书数不变。它不读取
真值或源数。当前结果仅支持将它作为显式冲榜开关，尚未证明对其他源数稳定。

以下开关均默认关闭，供复现实验使用：

- `--compact-fusion-budget 10`：环后用观测相容假设回放，比较原动作、同站
  追加 ACTIVE 测量、替换补测站，以及沿原路段提前补测。后续使用当前
  compact-ring 控制器，保留实际清除成本。`--compact-fusion-worlds` 默认 4，
  `--compact-fusion-margin` 默认 10 虚拟秒；样本只用于评分，不作完成证明。
- `--compact-fusion-views-only`：上述搜索只保留沿路段提前补测的候选。
- `--compact-clear-region-route`：将合法清除区域上的选点与开放路径顺序
  交替优化，兼顾进站和离站距离。每个新点都检查覆盖全部可行域顶点；
  预测路线缩短不代表更新观测后的整局必然缩短。

这些新增选项尚无跨组稳定收益，不属于 performance preset。
回放候选、预算消耗和选中动作写入每局 `stop_fusion.json`。

- `--compact-finish-active-at-cap`：确认 16 个源后跳过剩余 UNKNOWN，继续完成
  当前停点已经排入计划的 ACTIVE 测量。
- `--compact-route-cluster-radius R --compact-route-cluster-max K`：在环后
  ACTIVE 补测点合并邻近频道；`--compact-route-cluster-min-saving` 设置删除
  一个未来路径节点所需的最小预测节省米数。
- `--compact-route-alternatives`：对每个 ACTIVE 枚举信息质量合格的多个补测点，
  与开放路径顺序交替优化。质量和轮数分别由
  `--compact-route-quality-slack`、`--compact-route-point-passes` 控制。
- `--compact-shape-cover`：对宽度小于 40 米的凸可行域构造解析条带圆盘覆盖，
  并与原三角格点覆盖比较最坏完成成本。
- `--compact-route-free-probe-radius R`：已经决定前往某 ACTIVE 补测点时，
  先在该点试清；失败后保留 20 米排除圆并在原地完成原定测量。
- `--compact-joint-ring-route`：把未访问的证书锚点、READY 清除点和小半径
  ACTIVE 补测点放入同一开放路径。可用 `--compact-joint-ring-max-known` 和
  `--compact-joint-ring-min-stops` 门控；该分支方差较大，只用于实验冲榜。
- `--compact-joint-ring-or-opt`：当联合节点超过 Held–Karp 的 16 点上限时，在
  最近邻 + 2-opt 后继续尝试一、两个节点的严格缩短重插入。默认关闭，需用整局
  结果确认局部路线改善不会因新观测而反噬。
- `--compact-joint-anchor-substitution`：若 READY 的合法清除位置替换一个未访问
  锚点后仍通过精确 Q3 覆盖判定，则该停点融合清除和 UNKNOWN 扫描。替换前只做
  规划校验；实际扫描完成后才对仍 UNKNOWN 的频道登记证据。可用
  `--compact-joint-anchor-substitution-max-unknown` 限制扫描发生时的 UNKNOWN 数。
- `--compact-center-anchor --compact-ring-points 6 --compact-ring-radius 1150`：
  使用“原点 + 六个外环点”的另一组 7 点 Q3 证书。它有较长的纯覆盖路线，只有
  原点的早期方向信息能减少后续回访时才可能得益，默认关闭。
- `--compact-service-certificate`：让一个已知源的服务停点也扫描所有仍
  UNKNOWN 的频道，并在扫描真正返回后逐频道登记 `no_signal` 见证。只有每个
  仍 UNKNOWN 频道的“已观测见证 + 尚未访问锚点”仍通过精确 Q3 覆盖检验时，才
  删除冗余锚点；计划中的服务点只用于比较候选，绝不提前计入证书。半径、候选数、
  联合深度和最小路径节省分别由同名前缀的四个参数控制。
- `--compact-post-clear-worst R`：用最坏后验 MEC 半径筛选清除停点的顺带
  ACTIVE 测量；跨种子结果不如历史自动扫描，默认 0。
- `--compact-coverage-rollout-budget S`：覆盖中比较“直接访问下一锚点”和
  “处理一个源后强制回到该锚点”的完整后续成本。支线最多由
  `--compact-coverage-branch-actions` 个源动作及
  `--compact-coverage-branch-detour` 米额外路径组成；每次只提交第一个动作。
  `--compact-coverage-rollout-points` 让同一源的多个测点以整局回放成本竞争。
  `--compact-coverage-rollout-service-scan` 额外枚举
  “UNKNOWN + 该 ACTIVE”同站扫描，仍由回放比较其真实换频与测量成本。
  `--compact-coverage-rollout-post-service-scan` 是另一项更激进的原地扫描
  实验，初测存在回退，默认关闭且不属于推荐组合。
  `--compact-coverage-rollout-budget 0` 为默认关闭；每局日志写入
  `coverage_rollout.json`（候选、相容世界成本与实际接管），尾段回放也写入
  `tail_rollout.json`。

这些开关没有读取 `n_sources`、`scenario` 或源真值。最新跨种子结果记录在
`RESULTS.md`；推荐组合仍需显式传入 preset，不改变原 compact 默认配置。
Q4 的半平面发射使这个圆盘覆盖证明不成立。

实测与消融见 [RESULTS.md](RESULTS.md)。
