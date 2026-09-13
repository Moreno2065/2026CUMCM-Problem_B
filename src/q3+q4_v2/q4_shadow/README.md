# q4-shadow

Q4 的独立 CLI 策略：以 `q4-bisect` 为快速主策略，在主定位器出现可观测
停滞时让小型离散后验临时接管；同一后验也给清除后机会扫描定价。它不训练
神经网络，也不读取模拟器真值、场景标签或真实源数。

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q4 --sim synthetic `
  --policy q4-shadow --seed 101 --n-sources 16 --scenario random
```

正式 HTTP 入口：

```powershell
python -X utf8 src/q3+4_v2/run.py --mode q4 --sim http `
  --policy q4-shadow --base-url http://127.0.0.1:2026 `
  --robot-id TEAM001 --output-dir runs/official_q4_shadow
```

## 组合原则

这条策略没有照搬外部六步方案，而是按本仓库的消融结果取舍：

| 外部思路 | 当前实现 | 默认状态 |
|---|---|---|
| 朝向可行集、`P_signal`、似然加权 | `belief.py` 在硬可行多边形内生成位置、接收半径、全向/定向朝向假设，并用全部 `direction/no_signal` 条件化 | 仅风险时计算 |
| 50 m 最小测点间距 | `--shadow-min-spacing 50` 可复现 | 关闭；匹配消融变慢 2.82 s/源 |
| 多起点开放 TSP | 证书后缀实现为 `--shadow-route`；生产后段原本已有开放路径局部优化 | 关闭；固定证书顺序上破坏稳定性 |
| 扫描点逐步重定价 | 复用已有 discovery-NBV，开关为 `--shadow-dynamic-scan-price` | 关闭；全开版本发生大幅回退 |
| 定向比例贝叶斯估计 | 外生 Beta 先验加各已发现频道的软类型似然 | 开启 |
| 后验上分位数、历史无信号 | 同时计算后验均值和上分位方向比例，动作按两者较坏的剩余成本排序 | 开启 |
| 剩余成本 v2 | 移动/测量即时成本、MEC 残余、无信号惩罚、分支平衡组成小型代理 | 开启，仅用于选合法测点 |
| Q4 机会发现 | 对 UNKNOWN 的位置、半径、天线类型和朝向联合条件化；每个机会停点只测接收概率最高的一个频道 | 开启；阈值 0.01 |
| 联合尾程候选池 | 确认 16 个频道后，把所有 READY 清除与每个 ACTIVE 的下一补测同时放入候选池，并用 MEC 代表点开放 2-opt 路线估价 | 开启；路线权重 1.0 |

硬 `ChannelState`、缺位证书、`READY` 判据、有限光学兜底和退出条件始终是
权威状态。概率模型只能替换一次合法 `measure`，不能宣布清除或缺位。

## 风险保险丝

- 连续四次无有效 MEC 收缩，或主定位测量达到八次，才唤醒影子；
- `no_signal` 只进入后验，不单独触发，避免把覆盖扫描误判成定位失败；
- 每频道最多接管一次，整局最多四次；
- 候选的保守接收概率至少 0.20，预测剩余成本至少低 5 秒；
- 尚未确认满 16 个频道时最多多付 100 秒即时成本；在线确认满 16 后收紧到
  25 秒，因为此时额外发现价值已经消失。
- 机会扫描每站最多增加一个 UNKNOWN 测量；可用
  `--q4-discovery-p-threshold`、`--q4-discovery-max-channels` 和
  `--q4-discovery-trigger-known` 调整。保守对照可把前两个概率阈值都设为 0.15。
- 联合尾程默认在确认 16 个存在频道后启动；可用 `--no-shadow-tail-pool`
  关闭，或用 `--shadow-tail-route-weight` 调整路线权重。

完整结果与结论边界见 [RESULTS.md](RESULTS.md)。
| 后验有限兜底排序 | 完整清除覆盖不变，按位置后验命中质量与前往成本决定访问顺序 | 开启；`--no-shadow-fallback-posterior` 可关闭 |
