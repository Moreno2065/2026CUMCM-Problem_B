# 快照沿革（手动快照纪律，规范 §38/§53/§48；本任务不使用 Git）

## 正式证明循环阶段（2026-09-11 上午）

| 快照 | 创建时间 | 现状 | 说明 |
|---|---|---|---|
| `q2_pre_formal` | 早于 formal 循环 | **已被外部清理** | 进入 formal loop 前的源码状态。12:51 前后被并行会话删除，无法如实重建（"pre" 语义不可事后伪造）；源码版本链由各快照的 `source_manifest_sha256.json` 与 `q2_formal_ub_pass` 共同承载。 |
| `q2_formal_ub_pass` | 首次合法 UB 时创建；13:18 被并行会话重建 | 在 | state：U=134.06600939472236，incumbent=(805.1110506884, −599.7632926544)。 |
| `q2_formal_cert_candidate` | gap 首次 ≤ τ 时创建 | **已被外部清理**（同一 12:51 清理动作） | 其内容被 `q2_formal_cert_final` 完全取代。 |
| `q2_formal_cert_final` | FINAL REPLAY PASS 后创建 | 在 | 快速循环版证书快照（schema v1）。 |

## 证书收尾阶段（closure spec §48，2026-09-11 下午）

| 快照 | 现状 | 说明 |
|---|---|---|
| `q2_cert_candidate_pre_closure` | 在 | 收尾开始前状态；证书状态已按 §0 降级为 `GLOBAL_EPS_CERTIFICATE_CANDIDATE`（原因：P0-A 对称性缺解析证明、P0-B 剪枝树未严格重放）。 |
| `q2_symmetry_proven` | 在 | Phase A 完成：`Q2_CANONICAL_SYMMETRY_LEMMA.md`（Lemma A1–A6 + Theorem A + Corollary A）+ `canonical_symmetry_lemma.json` + T1 数值回归。 |
| `q2_proof_tree_recorded` | 在 | Phase B 树重录完成：3,022,561 节点（SPLIT 1,511,280 / PRUNE_A 463,354 / PRUNE_B 35,704 / LIVE_FINAL 1,012,223），L_fast=134.0569292534515 与独立 replay 完全一致；`OLD_TREE_NOT_REPLAYABLE` → 按 §32 以完全相同的冻结 cuts/incumbent/根域/容差重录。 |
| `q2_cert_final_rigorous` | **在**（全树重放 PASS 后创建） | 最终严格证书快照（schema v2，§42 字段）：L=134.05597622410357 ≤ Q* ≤ U=134.0659292484056，gap=0.0099530；manifest SHA256 与证书字段一致，已程序化核验。 |

并行会话活动记录（2026-09-11）：12:10–12:17 修复 `tests_formal` 三个测试；12:34–12:35 改 `code/geometry/a1.py`、`tests/q2/test_a1_dimension.py`；12:51 删除三个 formal 快照；12:53 改 `tests/q2/test_symmetry.py`（修复一个顺序相关失败）；12:55 改 `tools/generate_q2_verification.py`；13:18 重建 `q2_formal_ub_pass`；13:50 刷新 `q2_formal_cert_final`；14:0x 将两份 formal 报告移至 `src/q2/`。期间 `src/q2/artifacts/formal/` 的证书数字与 formal 层源码未被改动。
