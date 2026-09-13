# Q3/Q4 Candidate v1 性能横向比较与晋升报告

生成时间：2026-09-11（Asia/Taipei）  
结论：**晋升 Candidate v1（A1 固定几何选点 + A3 全频道扫描），冻结 `tau=0.15`；不启动 E3/E4。**

机器可读门禁总表：[`gate_report.json`](gate_report.json)。

## 1. 冻结的交付配置

配置文件：[`configs/candidate_v1_FROZEN_CONFIG.yaml`](../../configs/candidate_v1_FROZEN_CONFIG.yaml)

| 开关 | 最终值 |
|---|---|
| `tau` | `0.15` |
| 选点规则 | `nbv_rule: fixed_geometry`（A1） |
| 停点扫描 | `channel_scan_mode: sweep_all`（A3） |
| 复用 | `opportunistic_reuse: true` |
| 证书选择 | `cert_select: gain_cost` |
| Q4 策略 | `q4_naive: false` |

参数来自独立 tune 集（种子块 `600000+`）的 16 点网格、Q3/Q4 各 6 例，共 192 局。所有点均满足 clearance=100%。按“最小平均 `t_per_source_s`，2% 内再取更小标准差”的预注册规则，原始最小点为 `tau=0.20`（898.22 s/source），选择更稳的 `tau=0.15`（906.95 s/source，std=480.96）。选择记录见 [`tuning/selection.json`](tuning/selection.json)。

## 2. 横向性能：新鲜 matched-case 消融

以下每格为 6 个**同一案例**的算术平均虚拟时间 `t_per_source_s`；括号为标准差。每一个变体均为 6/6 成功，最小 clearance ratio 都是 1.0。`ΔT`、测量数和距离是逐案例对齐后再取均值，故不等同于两个均值相减。

| 题目 | 分支 | 平均 s/source (std) | 相对基线 | 配对 ΔT（s/局） | 配对 Δ测量数 | 配对 Δ移动距离（m） |
|---|---|---:|---:|---:|---:|---:|
| Q3 | 基线（NBV + state-aware） | 659.31 (124.94) | — | 0.00 | 0.00 | 0.00 |
| Q3 | A1：固定几何 | 558.80 (82.06) | -15.24% | -1,074.32 | -207.00 | +685.90 |
| Q3 | A3：全频道扫描 | 515.35 (100.75) | -21.83% | -1,555.33 | -171.33 | -2,752.46 |
| Q3 | **A1+A3 Candidate v1** | **479.66 (91.08)** | **-27.25%** | **-1,940.38** | **-213.17** | **-3,430.25** |
| Q4 | 基线（NBV + state-aware） | 2,192.89 (523.52) | — | 0.00 | 0.00 | 0.00 |
| Q4 | A1：固定几何 | **1,487.93 (170.52)** | **-32.15%** | **-7,525.47** | **-1,772.50** | +13,265.17 |
| Q4 | A3：全频道扫描 | 1,879.96 (518.92) | -14.27% | -3,457.85 | -405.50 | -4,676.74 |
| Q4 | **A1+A3 Candidate v1** | **1,493.72 (231.41)** | **-31.88%** | **-7,467.91** | **-1,438.50** | +6,205.47 |

原始可复核汇总：[`matched/branch_matrix_q3/suite_summary.json`](matched/branch_matrix_q3/suite_summary.json)、[`matched/branch_matrix_q4/suite_summary.json`](matched/branch_matrix_q4/suite_summary.json)。

### 分支决策

等权合并 Q3/Q4 的平均时间为：基线 1,426.10、A1 1,023.37、A3 1,197.66、Candidate v1 **986.69 s/source**。Candidate v1 比基线低 **30.81%**，比单独 A1 低 **3.58%**，因而在全题目标下排名第一。

Q4 上 Candidate v1 比单独 A1 高 5.79 s/source（0.39%）；该很小的代价没有抵消其 Q3 的明显收益，且 48 个 matched-case 运行全部通过。故保留 A3 进入主候选，而不是针对 Q4 单独退回 A1。E3/E4 不启动：其增益尚未在与 A1/A3 隔离的数据上证明，加入会开启新的候选、调参、冻结和 holdout 周期，当前不应污染已冻结的晋升结论。

## 3. 冻结后的泛化与正确性

所有候选集与历史主线隔离：tune `600000+`、matched ablation `700000+`、stress `800000+`、holdout `900000+`。结果如下。

| 阶段 | 配置/数据 | 局数 | 完整成功与 verifier | 备注 |
|---|---|---:|---:|---|
| 单元测试 | 全测试集 | 170 | 170 passed | 另对 Q3 收敛模块以 `PYTHONHASHSEED=0..5` 各跑一次，均 13 passed |
| 调参 | 16 tau × 6 Q3 × 6 Q4 | 192 | 192/192 | 全部 clearance=1.0 |
| 调参前 stress | Candidate v1，独立 stress | 26 | 26/26 | 晋升前安全门 |
| matched 消融 | 4 分支 × 6 Q3 + 4 分支 × 6 Q4 | 48 | 48/48 | 上表的归因证据 |
| 冻结后 stress | 冻结 `tau=0.15` | 26 | 26/26 | Q3 12/12；Q4 14/14 |
| 新鲜 holdout | 冻结 `tau=0.15` | 13 | 13/13 | Q3 6/6；Q4 7/7 |

本报告涉及的 305 个合成试验运行加上 13 个 HTTP 端到端演练，共 **318** 份 `verifier_report.json`；逐份扫描为 **318/318 `all_ok=true`**，没有假证书、漏源或未清空频道。

冻结 holdout 的性能范围如下（不是重新用于选参的数据）：

| 题目 | 成功 | 平均 s/source (std) | 中位数 | 最优—最差 | 平均测量数 | 平均移动距离 |
|---|---:|---:|---:|---:|---:|---:|
| Q3 | 6/6 | 465.61 (90.10) | 438.61 | 330.05—586.76 | 312.00 | 18,944.89 m |
| Q4 | 7/7 | 1,420.06 (336.32) | 1,614.03 | 932.13—1,823.92 | 887.71 | 55,799.81 m |

可复核汇总：[`frozen_holdout/frozen_holdout_q3/suite_summary.json`](frozen_holdout/frozen_holdout_q3/suite_summary.json)、[`frozen_holdout/frozen_holdout_q4/suite_summary.json`](frozen_holdout/frozen_holdout_q4/suite_summary.json)。

## 4. 协议端到端演练与正式测试状态

以冻结配置把 13 个 fresh holdout 再通过本地 `http-synthetic` 服务运行，覆盖真实客户端/Session/ActionExecutor/HTTP 协议路径：**13/13 complete + verifier 通过**。13 份 API 日志中记录 `/enter` 13 次、`/measure` 8,086 次、`/clear` 640 次、`/exit` 13 次。演练产物在 [`http_rehearsal/`](http_rehearsal/)。

这完成了本地 HTTP 的正式演练，但**不等于官方服务实测**。真实正式测试仍只缺官方 `base_url` 与正式 `robot_id`（或主办方提供的接入凭据）；在它们未提供前，不能诚实地声称已完成官方演练或正式测试。接入后应只使用上述冻结配置，先跑一局官方演练，核验输出的 `run_report.json`/`verifier_report.json`，再执行正式测试；不得修改 `tau` 或任一 A1/A3 开关。

最新可用性探测（2026-09-11）：本机 TCP `2026`、`80`、`443` 均无监听，项目文件中也未发现官方接入地址或正式队号配置；因此当前没有可安全发起的真实官方请求。

## 5. Experimental branch 实现盘点

以下盘点以当前代码的 variant registry、配置允许键和结果目录为准：

| 分支 | 当前状态 | 证据/边界 |
|---|---|---|
| A1 固定几何选点 | **已实现** | `a1_fixed_geometry` registry；Candidate matched-case 已重跑 |
| A2 关闭机会复用 | **已实现** | `a2_no_reuse` registry；保留为对照，不在 Candidate v1 |
| A3 全频道扫描 | **已实现** | `a3_sweep_all` registry；Candidate matched-case 已重跑 |
| A4 最近证书点 | **已实现** | `a4_nearest_cert` registry；历史 matched 结果为 neutral |
| Q4 naive Q3-style | **已实现（负对照）** | `q4_naive_q3_style`；已知不健全，不能晋级 |
| Candidate A1+A3 | **已实现并选定** | `candidate_a1_a3`；`tau=0.15` 已冻结 |
| **E1 更稀疏 Q4 证书** | **未实现** | 当前只有经过认证的 31 点基线；没有独立减点/新路线构造及 verifier |
| **E2 no_signal 联合状态** | **未实现** | 代码记录 `no_signal` 反馈，但没有规范中的潜在状态联合投影开关 |
| **E3 多步 lookahead / 路线插入** | **未实现** | 无 registry、配置键、handler 或独立结果目录 |
| **E4 证书残差稀疏化** | **未实现** | 无删点算法、覆盖证明、配置键或独立 verifier |

所以“未实现”不等于“实验失败”：E1–E4 目前只能标记为 deferred/closed，不能填写性能数字，更不能混入当前冻结结论。若要启动其中任一项，必须另开版本、另造 fresh cases、完成独立 verifier，再按同一门禁重新比较。

## 6. 最终执行口令

选择：**`candidate_v1_FROZEN_CONFIG.yaml`，A1+A3，`tau=0.15`，E3/E4=不启动。**

本地复核：

```powershell
cd D:\CUMCM2026\src\q3+4\code
python -m pytest tests -q --basetemp D:\CUMCM2026\src\q3+4\code\test_tmp_full_candidate -p no:cacheprovider
python cli.py run --question q4 --case cases\candidate_v1\holdout\holdout_q4.json --case-id candidate_v1_holdout_q4_07 --config configs\candidate_v1_FROZEN_CONFIG.yaml --sim http-synthetic --output results\candidate_v1\http_rehearsal\repeat_q4_07
```

真实官方服务到位后的入口（把占位值换为主办方提供的值）：

```powershell
python cli.py run --question q4 --config configs\candidate_v1_FROZEN_CONFIG.yaml --sim http --base-url <official_base_url> --robot-id <official_robot_id> --output results\candidate_v1\official_rehearsal_q4
```
