# `_legacy_superseded_v6`：退出论文引用链的旧 Q2 产物（归档，不删除）

本目录是 **只读归档副本**，由 `src/q2/code/tools/archive_q2_legacy_artifacts.py`
生成（生成时间 2026-09-11T15:51:16.252646+08:00）。目录布局与 `src/q2/code/` 下的相对路径一一对应。

## 这些文件为什么退出当前论文引用链

1. **配置身份对不上。** `artifacts/q2_final_evidence_config.json` 声明
   `config_id = "q2-final-evidence-v6-dynamic-closure"`。
   在当前 `src/q2/code` 源码树中，**没有任何生成器会输出这个 id**。
2. **原生成器缺失。** 仓库内唯一的 Q2 Gate G 打包脚本是
   `tools/generate_q2_closure_artifacts.py`，它声明
   `q2-final-evidence-v5-hero-closure`，且写入
   `artifacts/gate_g_representative/`（上一轮已用修复后的 evaluator 重新生成），
   而不是本归档对应的顶层 `artifacts/` 与 `figures/`。
   核查方式：扫描 `src/q2/code/**/*.py` 中 `q2-final-evidence-v6-dynamic-closure` 字面量、
   `evidence_config_id` / `config_id` 赋值与输出目录字面量。
   命中数 = 0，
   故 `legacy_generator_unavailable = True`。
3. **方法标签是旧代命名。** 本归档整体标记 `legacy_method_labeling = true`：
   这批产物同属旧的 B1/B2 命名与打包体系，不能直接当作当前方法身份体系
   （`method_id` / `paper_alias` / `formula_or_constructor`）的证据。
   每个条目另存 `method_label_tokens_found`，记录该文件内容里实际扫到的标签 token。
4. **本轮已确认 5% 候选域未收敛。** 旧产物中记录的候选域面积/连通分支不具备
   “全域已完整提取”的含义，继续引用会把未收敛结果包装成结论。

因此本目录内所有文件均带 `superseded = true`、`not_for_current_paper = true`。
**当前论文与测试只应读取 `artifacts/gate_g_representative/`（现行实现）与
`artifacts/q2_release_verified_v1/`（本轮发布目录）。**

## 「归档 ≠ 复现」

把文件复制到这里 **不构成** 对旧流程的复现：

- 旧 `q2-final-evidence-v6-dynamic-closure` 生成器在树内不存在，因此
  **既不能逐字节重现，也不能用同一个 config id 重跑**。
- 归档只保证“内容被完整保存且哈希可核对”（见 `MANIFEST.json` 的
  `sha256` / `archive_sha256` / `copy_verified`），不保证流程可执行。
- 若要重新生成等价证据，只能用现行生成命令：
  `PYTHONPATH=. python src/q2/code/tools/generate_q2_closure_artifacts.py`
  （输出到 `artifacts/gate_g_representative/`，config id 为
  `q2-final-evidence-v5-hero-closure`）。任何新产物都不得标注为 v6 流程的输出。
- 旧配置到现行实现的逐项映射见
  `../q2_release_verified_v1/resolved_config.json` 与
  `tools/resolve_q2_evidence_config.py`；未映射字段在该文件中显式列出。

## 内容清点

- 范围内文件：71
- 已复制并校验哈希：71 / 71
- 缺失（清单中列出但仓库中不存在，未报错退出）：0
- 归档总字节：16514059

## 非破坏性保证

归档前后对 `src/q2/code`、`artifacts/`、`figures/` 重新计数：
```json
{
  "code_root_files_before": 236,
  "code_root_files_after": 236,
  "artifacts_files_before": 110,
  "artifacts_files_after": 110,
  "figures_files_before": 37,
  "figures_files_after": 37,
  "counts_exclude": [
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "src/q2/code/artifacts/_legacy_superseded_v6"
  ],
  "source_deleted": false,
  "source_counts_unchanged": true
}
```

清单与逐条哈希见 `MANIFEST.json`（机器可读）与 `MANIFEST.md`（可读）。
