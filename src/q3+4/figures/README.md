# Addendum F 图表目录（figures/）

本目录收 F.1–F.8 全部图：每图含 PDF master、PNG preview、figure_data
（CSV/JSON）与可重复 plot script（`scripts/plot_figN.py`）。
**图注目前一律英文**（托管 python 的 CJK 字体在 Agg 后端下不稳定）；
论文排版阶段再统一中文化，届时只需改各脚本字符串。

## 一键重建

```bash
cd code
python cli.py figures --experiment results --out figures
```

依次以子进程调用 8 个脚本，全部成功后写 `figures_manifest.json`
（含每脚本执行记录与各图 PDF/PNG 存在性校验）；任何脚本失败即返回
非零退出码。单张重建（每个脚本独立可跑）：

```bash
python figures/scripts/plot_fig1.py [--results results] [--out figures]
python figures/scripts/plot_fig2.py [--run figure_runs/q3_a1 --channel 12]
...  # plot_fig3.py … plot_fig8.py 同理
```

## 各图说明与 claim 映射

| 图 | 文件 | 内容 | 数据来源 | Claim 映射 |
|----|------|------|----------|-----------|
| F.1 | `fig1_method_loop.{pdf,png}` + `fig1_data.json` | 方法闭环示意：主任务定位-清除、伴随扫描、收尾补差三层，锚定 figure_runs 两局 metrics | `results/figure_runs/{q3_main,q4_main}/metrics.json` | 方法总览 |
| F.2 | `fig2_bounded_bearing_geometry.{pdf,png}` + `fig2_data.json` | bounded-bearing 几何：±1° wedge 交会、可行域首/中/末快照、MEC、保证清除区 B(c, 20−r) ⊆ Z_c | `results/figure_runs/q3_a1/`（channel 12） | H.5 几何构造 |
| F.3 | `fig3_q3_certificate.{pdf,png}` + `fig3_data.json` | Q3 排除证书累积：前 25 停点残余缺口（q3_certified 判 NO）vs 全覆盖闭合（YES），R_EFF_MIN=1000 | `results/figure_runs/q3_main/certificate.json` + observations | H.5 证书构造 |
| F.4 | `fig4_q4_robust_certificate.{pdf,png}` + `fig4_data.json` | Q4 鲁棒证书（合成几何）：31 点三角格点半平面引理 + 见证点凸包 B(x,δ=370) ⊆ conv(A_δ(x)) | `geometry/certificate.py::q4_lattice_points()`（合成，已批准） | H.5 证书构造 |
| F.5 | `fig5_localization_convergence.{pdf,png}` + `fig5_data.csv` | 定位收敛：每频道 MEC 半径 vs 观测序号，median + IQR（**不用 95% CI**） | `figure_runs/{q3_main,q4_main}/localization_history/` | H.1 相关 |
| F.6 | `fig6_ablation_paired.{pdf,png}` + `fig6_data.csv` | 消融配对 ΔT 点图（9 类别），q4_naive 假证书案例红 × 标注（C.6 失败） | `results/ablation/*/stats.json` + `suite_summary.json` | H.1–H.4 + H.5 |
| F.7 | `fig7_time_decomposition.{pdf,png}` + `fig7_data.csv` | 时间分解堆叠条：4 个正交账本分量（和恒等于 T）；residual cert time 仅括注 | `results/ablation/*/<variant>/<case>/metrics.json` + suite_summary | H.3 |
| F.8 | `fig8_certificate_progress.{pdf,png}` + `fig8_data.csv` | 任务进度：已了结频道比例（阶梯）+ 未了结频道 mean coverage；两 variant 曲线重合 | `figure_runs/a4_*/channel_state_history.jsonl` | H.4（等价退化） |

## 口径与替代处理说明

- **Fig2 用 A1 variant 局（q3_a1）而非 mainline**：mainline 局观测点沿
  楔形轴共线、交会不清晰；A1 基线的垂直偏移才有真交会。几何构造
  （wedge/可行域/MEC/保证清除区）两 variant 相同，仅轨迹不同。
- **Fig5 的观测序号是每频道重编号**（1..n）：原始记录里的
  `observation_count` 是全局计数，直接画会把频道错开。
- **Fig7 堆叠只画账本四分量**（T_move/T_measure/T_switch/T_clear，
  ledger 恒等式保证其和 = T_total_virtual）。residual certificate time
  是模式视角量，与账本分量定义重叠，仅以 `(resid-cert …)` 括注标在
  条顶，不参与堆叠。
- **Fig8 的 A4 两 variant 逐字节相同**：曲线重合为等价退化（H.4
  neutral），图内与图注如实注明，不伪装差异。
- **Fig8 数据源改为 channel_state_history.jsonl**（逐步全频道快照），
  而非 certificate_history：后者对 lattice31 闭合频道 coverage_ratio
  恒停 0，无法反映证书达成。resolved = status ∈ {CLEARED,
  CERTIFIED_ABSENT}；未了结频道集合为空时 mean coverage 记 NaN
  （折线自然断开），不做伪降到 0。
- **Fig6 假证书案例**取自 `q4_naive_vs_mainline/suite_summary.json`
  的 `cases_by_variant.q4_naive_q3_style`：ablation_q4_02/04/05/06
  （success=False，false_certified_absent=1，漏源频道 2/7/4/17）。

## 验收

每张图生成后以 PNG 目检（无空白、无不可读重叠、轴标签齐全）；
`tests/test_figures.py` 提供烟雾测试（全量 build_figures + 逐图
PDF/PNG/data 文件存在且非空）。
