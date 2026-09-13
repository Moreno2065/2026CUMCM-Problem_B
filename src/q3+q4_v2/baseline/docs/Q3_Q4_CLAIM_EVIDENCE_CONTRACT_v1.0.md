# Q3_Q4_CLAIM_EVIDENCE_CONTRACT_v1.0

> 依据 Addendum H 节填写。每条 claim 附本次实验（Gate 4–7）实际结果与结论。
> 数据来源：`code/results/`（tuning / ablation / holdout / stress），全部数字来自实际运行输出。
> 冻结配置：`code/configs/FROZEN_CONFIG.yaml`（τ=0.05，freeze_time=2026-09-11T17:04:57+08:00，git=N/A）。
> matched-case：同一 suite 内所有 variant 读取同一冻结案例文件（`code/cases/ablation/ablation_q3|q4.json`）。

---

## H.1 NBV Claim

```yaml
component: ACTIVE 模式观测点选择（policy/localization.py NBV + approach 直达链）
claim: 主动观测策略降低定位成本
controlled_comparison: A1 — mainline（ΔR_MEC/cost NBV + MEC 直达链）vs
  a1_fixed_geometry（固定几何选点：MEC 中心沿最近 bearing 垂直方向偏移
  min(300, 0.5·R_MEC) m，取远离最近观测点一侧；唯一改变观测点选择规则）
metric: 每源观测次数；平均定位清除时间；MEC 半径下降速度（m/次更新）；总虚拟时间
case_set: cases/ablation/ablation_q3.json + ablation_q4.json（各 6 案例）
success_condition: matched cases 下稳定 improvement（paired ΔT < 0 且
  定位指标更优）
failure_condition: 无稳定 improvement → 降级为方法组成，不声称效率提升
required_figure: Figure 5（MEC radius vs observation count/time）
required_table: A1 paired 表（results/ablation/ablation_a1_q3|q4/summary.md）
```

**实际结果**（paired Δ = baseline − mainline，负 = baseline 更快）：

| 集 | mean ΔT (s) | median ΔT (s) | 每源观测数（mainline→baseline） | MEC 下降速度 mean（m/次） |
|---|---|---|---|---|
| ablation_q3 | −1215.1 | −1366.7 | 57.5/45.2/42.9/57.3/68.3/31.3 → 37.0/31.3/35.7/31.6/50.6/16.1 | 215.9 → 417.5 |
| ablation_q4 | −3360.0 | −2755.4 | 197.1/100.2/168.1/163.1/143.7/185.9 → 60.2/49.8/52.3/59.7/69.1/40.5 | 303.7 → 504.2 |

clearance ratio 两边均 100%（6/6 + 6/6 success）。

**结论：不支持（降级）。** 固定几何 baseline 在全部 12 个 matched case 上总时间与每源观测数均优于冻结 NBV/直达链（MEC 中心重复确认每步仅 ~0.5× 收缩，而垂直偏移构造的大基线交会单次收缩更快）。按 H.1 规则：不删除结果，**NBV 降级为方法组成，不声称效率提升**。该结果同时提示主线的 MEC 直达链效率偏弱，列为后续支线（E3 lookahead/route insertion 之外）的改进方向，但本阶段不因结果改代码/参数（冻结纪律）。

---

## H.2 Opportunity Reuse Claim

```yaml
component: 停点机会式复用（NBV 候选中的当前点/当前→MEC 中点）
claim: 机会复用减少专用定位移动
controlled_comparison: A2 — mainline vs a2_no_reuse（NBV 候选去掉机会式
  停点，定位须专门机动；发现性 UNKNOWN 扫描两者都保留；唯一改变是否
  复用既定路线停点）
metric: dedicated localization distance；总移动距离；平均定位清除时间；总虚拟时间
case_set: cases/ablation/ablation_q3.json + ablation_q4.json
success_condition: dedicated distance 稳定下降
failure_condition: 仅降距离但总时间不降 → 只能 claim 距离减少
required_figure: Figure 6（paired difference）
required_table: A2 paired 表
```

**实际结果**：

- Q3：6/6 案例逐字节相同（ΔT=0，dedicated distance 相同）——Q3 直达链主导，机会式候选从未被选中。
- Q4：dedicated localization distance 6/6 案例 mainline 更低（如 case1 12006 m vs 19680 m，case2 13461 vs 19452，case4 15881 vs 20092）；总移动距离 5/6 案例 mainline 更低；但 paired ΔT 混合（[+3769, +5714, −3002, −1715, +1381, −7426]，mean −213.1 s）。

**结论：部分支持（限缩 claim）。** 机会式复用在 Q4 上**稳定减少专用定位移动**（6/6 paired 改善）；总时间不降（mean ΔT 不稳定、符号混合）。按 H.2 规则：**只能 claim「机会复用减少 Q4 专用定位距离」，不能 claim 总效率提升**；Q3 上该机制无实际触发（0 差异）。

---

## H.3 Channel Scheduling Claim

```yaml
component: 停点频道扫描集合（runner._scan_set）
claim: 状态感知频道调度减少无效检测
controlled_comparison: A3 — mainline（只扫 UNKNOWN + 同点去重）vs
  a3_sweep_all（每停点机械扫描全部未结频道；唯一改变扫描集合）
metric: measure count；switch count；detect/switch 时间；总虚拟时间
case_set: cases/ablation/ablation_q3.json + ablation_q4.json
success_condition: matched cases 下 mainline 检测数/时间稳定更低
failure_condition: 无稳定 improvement → 降级为方法组成
required_figure: Figure 7（time decomposition）
required_table: A3 paired 表
```

**实际结果**（mean per case）：

| 集 | variant | measures | T_measure (s) | T_switch (s) | mean ΔT (s) |
|---|---|---|---|---|---|
| q3 | mainline | 550 | 2752 | 499 | — |
| q3 | sweep_all | 385 | 1927 | 358 | −1862.4（baseline 更快） |
| q4 | mainline | 1754 | 8770 | 1600 | — |
| q4 | sweep_all | 1428 | 7140 | 1314 | −2637.9（baseline 更快） |

**结论：不支持（降级）。** 机械全扫 baseline 反而检测数、换频数与总时间全部更低——原因是停点免费顺带测量 ACTIVE 频道带来额外 bearing 观测，加速定位与证书闭合，净收益超过"少测"的节省。按 H.3 规则：**状态感知调度降级为方法组成，不声称减少无效检测**；sweep_all 作为候选改进列入支线评估（晋级需满足 A.3 且不破坏完成性证明，本阶段冻结不改主线）。

---

## H.4 Certificate Selection Claim

```yaml
component: CERTIFICATE 残差选点（policy/certificate_policy.py）
claim: 边际证书收益选点降低 residual completion cost
controlled_comparison: A4 — mainline（max ΔC/cost）vs a4_nearest_cert
  （最近未访证书点；唯一改变残差选点规则）
metric: residual certificate time；residual movement distance；最终总虚拟时间
case_set: cases/ablation/ablation_q3.json + ablation_q4.json
success_condition: matched cases 下稳定收益
failure_condition: 无稳定收益 → 退回 nearest-gap mainline 或降级
required_figure: Figure 8（certificate coverage ratio vs virtual time）
required_table: A4 paired 表
```

**实际结果**：q3 与 q4 全部 12 案例两 variant **逐字节相同**（ΔT=0，
residual cert time/distance 相同）。原因：本实现中证书候选几乎总由
"当前位置机会点 + 就近缺口"主导，两种选点规则在这些案例上选中同一点。

**结论：无法区分（neutral）。** A4 在本案例集上未产生任何行为差异，
既不支持也不否定。按 H.4：mainline 维持现状（max ΔC/cost 与 nearest
等价退化），该 claim 不进正文；如需区分需构造证书候选真正分叉的
专项案例（列入后续工作）。

---

## H.5 Deterministic Certificate Claim

```yaml
component: Q3 圆盘覆盖证书 + Q4 δ-稳健凸包/31 点格点证书 + 独立 verifier
claim: 证书层给出确定性缺席证明（无 false CERTIFIED_ABSENT）
controlled_comparison: 不依赖消融；来自形式推导 + 独立 verifier +
  adversarial synthetic tests + C.5 对照（naive Q3-style 在 Q4 上必假证）
metric: verifier_all_ok；false_certified_absent 计数；clearance ratio
case_set: cases/stress/（D.3 全场景族 26 案例）+ cases/holdout/（13 案例）
  + C.5 对照（ablation_q4）
success_condition: 全部 mainline 局 verifier PASS 且 ground-truth
  后置检查零假证书
failure_condition: 任何 false CERTIFIED_ABSENT 或 verifier FAIL
required_figure: Figure 3/4（证书构造图）
required_table: stress/holdout 统计表
```

**实际结果**：

- stress 集 26/26、holdout 集 13/13：complete=True、verifier_all_ok=True、ground-truth 后置检查 false_certified_absent=0、clearance ratio=100%。
- C.5 对照（ablation_q4，naive Q3-style vs directional-aware mainline）：

| variant | success | clearance_min | false CERTIFIED_ABSENT | mean T (s) |
|---|---|---|---|---|
| mainline（Q4 证书层） | 6/6 | 1.00 | 0 | 19608.7 |
| naive Q3-style | 2/6 | 0.90 | 4 案例各 1 个（频道 2/7/4/17 漏源） | 14566.3 |

naive 的"更快"（mean ΔT −5042 s）正是 Addendum C.6 警告的伪优势：
因提前假证而缩短时间，漏源率 4/6。所有假证书均被 ground-truth
后置检查发现并记为失败（未删除）。

**结论：支持。** Q4 定向感知证书层的必要性由对照直接证明（clearance
1.00 vs 0.90）；mainline 在 39 个 stress+holdout 案例上零假证书、
verifier 全 PASS。

---

## 总结论一览

| Claim | 结论 | 依据 |
|---|---|---|
| H.1 NBV 降定位成本 | **降级**（baseline 全胜，不声称效率提升） | A1 paired（12/12 baseline 更快） |
| H.2 机会复用 | **限缩**：仅 claim Q4 专用定位距离减少（6/6），不 claim 总效率 | A2 paired |
| H.3 状态感知调度 | **降级**（机械全扫反而更优） | A3 paired |
| H.4 证书残差选点 | **neutral**（两规则在本集行为等价） | A4 paired（12/12 相同） |
| H.5 确定性证书 | **支持** | stress 26/26 + holdout 13/13 零假证 + C.5 对照 |

> Gate 纪律：τ 已于 Gate 5 冻结（0.05）；Gate 6/7 全部使用
> FROZEN_CONFIG；holdout 结果未用于任何参数修改；失败案例全部保留。
