# Q2 代码修复与验证报告（最小补丁 + 独立 verifier）

**范围**：2026 CUMCM B 题问题 2 的既有 Python 实现（`src/q2/code`）。
**论文基线**：`src/q2/Q2_有界误差下的稳健主动测向选点模型_实现对齐修订版_v3.md`。
**策略**：不推翻架构、不改 Q1 数学语义、不引入概率假设；对每个确认风险只做最小补丁，并补齐独立验证链。
**全局最优声明**：

```text
CERTIFIED_GLOBAL_OPTIMUM = False
```

外层二维搜索仍只是“在冻结搜索协议下经独立复核稳定的数值近优点”，候选区域仍只是数值近似，二者均无集合包含证书。

---

## 1. 只读审计表

| file | current role | confirmed issue | severity | patch plan |
|---|---|---|---|---|
| `geometry/a1.py` | 构造物理首次观测集 A1 及其活动边界注册表 | `dimension = AREA if pieces else EMPTY`：任何产生闭包边界片的切触/退化几何都被静默升级为 AREA；另有外部站点切线候选把“圆心→站点”方向直接当作“站点→圆心”方向，导致外部切线附近的窄正面积楔被误判为 SEGMENT | P0 | 改为 fail-closed 内部见证分类器；显式 POINT/SEGMENT/EMPTY；外部站点切线轴反向后再加切线偏角；无法严格判定时抛 `A1DimensionClassificationError` |
| `geometry/angular_image.py` | near-aware 角像 | 双楔切触桥检测使用裸浮点 `== NEAR_RADIUS_M` | P1 | 改为尺度明确的紧 `math.isclose(..., abs_tol=TANGENCY_TOL_M)`，并加单元测试 |
| `geometry/crec.py` | 精确鲁棒可接收域 witness | `_deep_arc_stationary_points` 的高次多项式驻点解只有单一证据链 | P1 | 新增独立高密度弧参数扫描 + 局部精修 verifier，并对低估 fail-closed |
| `geometry/circular_intervals.py` | 圆周闭区间代数 | 未发现缺陷 | — | 不改 |
| `geometry/primitives.py` | 中性度量原语 | 未发现缺陷 | — | 不改 |
| `model/frozen_contract.py` | 冻结常数 | 未发现缺陷 | — | 不改 |
| `model/q1_adapter.py` | 纯两方位 Q1 适配器 | 未发现缺陷；数学语义未改 | — | 不改 |
| `solver/q2_point.py` | 单点 Q2 评价器 | ① 裸浮点 `epsilon != EPSILON_DEG`；② production 只调用 E1–E5 候选器，没有独立复核闭环 | P0/P1 | ① `math.isclose`；② 改调 `maximize_inner_verified` |
| `solver/inner_max.py` | E1–E5 内层最坏方位最大化 | 无独立验证闭环；E4/E5 根隔离结果被无条件当作最坏值返回 | P0 | 新增独立扫描 verifier + `maximize_inner_verified` facade；残余低估 hard fail |
| `solver/outer_search.py` | 确定性非证书外层搜索 | ① `_is_valid` 弱于 incumbent（缺 finite 检查）；② final neighbor loop 在生成邻居时中心会随 incumbent 移动；③ `derivation` 字符串与 docstring 把安全超集说成精确盒 | P1 | ① 统一复用 `is_valid_incumbent_result`；② 冻结中心 + 复核循环；③ 改为 `safe_superset_from_subset_of_mandatory_crec_disk_boxes` 并断言含 S1 |
| `solver/candidate_regions.py` | 自适应数值次水平集区域 | ① cell 内部只用 4 角点判定；② 中心点未在分类前采样；③ 无 kind/classification 字段 | P0 | ① 角点+中心全量参与有效性/阈值/Q 值域/near-Hero 判定；② 分类前补齐中心；③ 声明 `numerical_candidate_good_region_not_proof` 与 `corners_plus_center` |
| `solver/incumbent.py` | 评价登记表 + 已知最优 incumbent | 唯一持有完整（含 finite、all-near）有效谓词的地方，导致多处语义漂移 | P1 | 复用其既有 `is_valid_incumbent_result` 作为全局唯一有效谓词来源（该文件本身未改） |
| `solver/batch.py` | 串行/并行点批处理 | 未发现缺陷 | — | 不改 |
| `solver/gate_g.py` | Gate G 证据编排 | B1/B2 与论文 v3 互换；B1 只取单侧；B2 无 Ω 截断声明 | P1 | 互换标签；B1 双侧取优；B2 增加 canonical/truncated provenance |
| `solver/baselines.py` | 基线构造器 | docstring 把互换后的 provenance 写死 | P1 | 仅对齐文档，不改数值行为 |
| `verifier/verify_inner.py` | 对既有候选做稠密复核的 oracle | 缺少 production 级“独立求最大 + 提升/失败”闭环 | P0 | 新增 `verify_inner_max_independent` |
| `verifier/verify_crec.py` | Crec 稠密 oracle | 缺少逐条 deep arc witness 对拍 | P1 | 保持不动；新增 `verifier/verify_crec_deep.py` |
| `verifier/verify_gate_g.py` | 证据包独立校验 | 只校验单条 B1 provenance | P1 | 同时校验 B1/B2 provenance 与行点一致性 |

---

## 2. P0-1：inner_max 的独立验证闭环

**原因**：`maximize_inner()` 的 E4/E5 依赖数值根隔离，不是完备的解析有限候选定理；若它漏峰，production 会静默返回低估的 worst-case Q。

**修改**

- `verifier/verify_inner.py` 新增 `IndependentInnerVerification` 与 `verify_inner_max_independent(...)`：只调用 Q1 adapter，不引用任何 `inner_max` 生产候选器（Gate E 结构守卫测试继续成立）。对 `allowed_beta` 的每个圆周闭区间做基础均匀采样，对近平行事件显式加密，再对若干局部高值峰做一维黄金分割精修；返回 `q_verify / beta_verify / q_main / beta_main / abs_gap / relative_gap / sample_count / refinement_rounds / converged / near_parallel_bands / failures`。
- `solver/inner_max.py` 新增 `InnerVerificationConfig`、`InnerMaxUnderestimateError` 与 `maximize_inner_verified(...)`：先取 E1–E5 主结果，再做独立扫描；若独立值显著更大则以 verifier 邻域为 seed 提升 production Q，并立即复核；若复核仍被超过则 hard fail，绝不返回已知低估值。
- `solver/q2_point.py` 的 production 路径改调 `maximize_inner_verified`。

**修改前后数学语义**

| | 修改前 | 修改后 |
|---|---|---|
| `Q(S_2)` | E1–E5 候选表上的最大值（可能低估） | E1–E5 主结果 ∪ 独立扫描闭环；低估则提升或 hard fail |
| 独立证据 | 无 | 结构不同的第二条证据链（不含根隔离） |

**实测**：108 点网格与新增测试族中，独立扫描未发现任何高于主结果的直径；个别 E5 主导点上 verifier 略低于主值（例如 `S2=(1120,-650)`，`Q_main=87.41977346016151`，`Q_verify=87.41969178192238`，`abs_gap=-8.17e-5 m`），即一侧下界而非低估，已如实记入 `q2_verification/inner_verifier_report.json`。

---

## 3. P0-2：candidate region 不能只用角点判定内部

**原因**：四角均满足 `Q <= threshold` 不能推出单元内部全部满足；单元内可能存在不可行岛或目标峰值。原实现只在 refine 阶段用角点，分类也只读角点。

**修改**

- 每个 cell 的分类样本改为 **4 corners + center**；分类前强制补齐所有叶单元中心点缓存。
- `_needs_refinement()` 纳入中心点：有效性变化、Crec/admissibility 变化、阈值穿越、Q 值域扩张（`q_range_refinement_ratio`，默认 0.25）、near-Hero 任一触发即细分；中心与角点分类不同必须细分。
- `_refinement_priority()` 同时读角点与中心，并把 Q 值域扩散度**有界地**纳入优先级（归一化后最多 10 分，避免淹没阈值穿越项）。
- `AdaptiveCandidateResult` 新增 `kind = numerical_candidate_good_region_not_proof` 与 `classification_samples = corners_plus_center`；三者同步输出同名字段：聚合 `q2_candidate_good_regions.json`、分 η 的 `q2_candidate_good_eta_XX.json`、以及 GeoJSON 的 `properties`。
- 命名刻意不使用 `certified_inside`：函数仍叫 `_cell_inside_threshold`，注释明确它是抽样数值分类而非集合包含证书。

> **回归发现（已修复）**：第一版实现把未归一化的 Q 值域扩散度直接加入优先级，且 Q 值域触发条件不加限制。重新生成生产证据时发现细分预算被大量消耗在 Q 量级上万、远离阈值带的单元上，导致 4 个 η 档的候选区域面积全部塌缩为 0。修复方式：Q 值域触发仅在“单元最大 Q ≤ 2 × 最大阈值”（即可能属于近优带）时生效；优先级中的扩散度归一化并封顶为 10。修复后生产配置下四档面积恢复为正（125 / 743 / 3288 / 12970 m²），且全量测试恢复通过。

**修改前后数学语义**

| | 修改前 | 修改后 |
|---|---|---|
| cell 分类样本 | 4 corners | 4 corners + center |
| 细分触发 | 角点有效性/阈值/near-Hero | 上述 + 中心 + Q 值域 |
| 输出语义 | 隐式“看似内部” | 显式 `numerical_candidate_good_region_not_proof` |

**分辨率收敛（真实结果，未做粉饰）**：新增 `verifier/verify_candidate_resolution.py`，对同一冻结目标在 coarse / medium / fine 三档重建 Hero 搜索与 η=5% 区域（fine 档即生产配置 `base_resolution=21, max_refinement_depth=6, target_boundary_resolution_m=5, max_refined_cells_per_level=32`，并按生产方式做镜像配对细分），报告 `qhat_star` 相对散布、面积相对散布、连通分支数与边界样本 Hausdorff-like 距离。脚本不预置任何“必须小于某百分比”的硬门。

实测（`q2_verification/candidate_region_resolution_stability.json`）：

| level | qhat_star / m | 5% 面积 / m² | 连通分支 | 叶单元数 |
|---|---:|---:|---:|---:|
| coarse | 134.231688 | 0.0 | 0 | 400 |
| medium | 134.138626 | 629.757 | 4 | 976 |
| fine | 134.098174 | 0.0 | 0 | 976 |

`qhat_star` 相对散布约 `9.96e-4`；面积相对散布为 `1.0`（即完全不稳定），连通分支数为 `(0, 4, 0)`。

**这是本次修复中最重要的一条负面证据，必须原样写入论文**：5% 次水平集相对整个搜索盒非常薄，而自适应细分每层只允许 `max_refined_cells_per_level` 个单元（生产为 32），因此“4 角点+中心是否全部落在阈值内”的判定对 Hero 位置与阈值只有厘米级敏感度。同一生产配置下，Hero 从 `(800.10, -606.39)` 平移约 6.6 m 到 `(796.58, -610.97)` 就足以让被判为“内部”的单元集合从非空塌缩为空。

结论：**数值候选区域的分辨率收敛性尚未建立**，论文不得声称该区域已收敛，也不得把它当作带集合包含证书的严格内逼近；只能表述为“在固定的最高细分预算下得到的数值近优采样”，并同时给出面积与分辨率敏感性。若要让面积稳定，需要把细分预算从“每层 32 个单元”改为与阈值带长度成比例的预算（例如沿带的自适应条带细分），这超出本次最小补丁的范围，已在剩余限制中登记。

生产证据包 `artifacts/gate_g_representative/` 使用的是最高细分预算，四个 η 档面积均为正（125 / 743 / 3288 / 12970 m²），但其非空性依赖固定的 closure seed，不能作为收敛证据。

---

## 4. P0-3：A1 退化维数 fail-closed

**原因**：`AREA if pieces else EMPTY` 会把切触/线接触等退化几何误标为 AREA，使 `crec` 中“SEGMENT 被显式阻断”的保护失效。

**修改**

- 新增 `A1DimensionClassificationError`、`INTERIOR_MARGIN_M/RAD`、`INTERIOR_SCAN_SAMPLES`。
- `_strict_interior_witness()`：只有当某方向上的径向区间在 `5 < rho < 1500` 内严格正宽、点严格位于 Ω 内、方位严格位于首测向楔内时，才认定存在二维内部见证 → `AREA`。
- 若无内部见证，`_degenerate_dimension()` 再按 boundary arrangement 判定：
  - 存在正长度边界片且其自身中点是 A1 成员 → `SEGMENT`（仿射/拓扑 1 维退化集，`build_crec` 继续 hard fail，这是期望行为）；
  - 否则存在孤立点 → `POINT`；
  - 否则无点 → `EMPTY`；
  - 存在正长度但无法认证为 A1 成员的边界片 → 抛 `A1DimensionClassificationError`，**绝不默认 AREA**。

**修改前后数学语义**

| | 修改前 | 修改后 |
|---|---|---|
| 维数来源 | 是否产生边界片 | 是否证明存在二维内部见证 |
| 退化切触 | 可能 AREA | POINT / SEGMENT / EMPTY / 显式异常 |
| 不可判定 | 默认 AREA | 显式抛错（fail-closed） |

**测试**：`tests/q2/test_a1_dimension.py` 覆盖中心普通楔 → AREA、Ω 截断、S1 在 Ω 外、0/360° wrap、切触单点 → POINT、不可行首测 → EMPTY 且 `build_crec` 抛错、以及退化分类器的 fail-closed 单元测试。

新增外部切线回归：取 `S1=(2000,0)`、`theta1=180°-asin(1800/2000)-1°+0.0001°`，该构型的 A1 具有严格二维内部，必须分类为 `AREA` 并能继续构造 `Crec`；修复前会被误判为 `SEGMENT` 并在 `build_crec()` 中拒绝。该测试固定在 `tests/q2/test_a1_dimension.py::test_narrow_wedge_beyond_external_tangent_is_area_and_builds_crec`。

---

## 5. P1 补丁

### 5.1 浮点脆弱比较

- `solver/q2_point.py`：`epsilon != EPSILON_DEG` → `math.isclose(epsilon, EPSILON_DEG, rel_tol=0.0, abs_tol=1e-12)`。
- `geometry/angular_image.py`：切触桥的 `== NEAR_RADIUS_M` → `math.isclose(..., rel_tol=0.0, abs_tol=TANGENCY_TOL_M)`。新增常量 `TANGENCY_TOL_M = 1e-15`，其注释明确要求它必须**小于**Gate C 亚纳米楔通道测试的最小正间隙（5e-14 m），否则会把真实亚纳米通道误判为切触。该 helper 不改变 `merged_closure = raw` 的目标语义（新增测试断言 `image.merged_closure == raw`）。

### 5.2 有效谓词统一

`solver/outer_search.py` 与 `solver/candidate_regions.py` 的 `_is_valid` 均改为复用 `solver/incumbent.py::is_valid_incumbent_result`（`in_crec and (admissible or all_near) and Q is not None and finite`），消除了“粗网格把 `Q=inf` 当 valid、incumbent 又拒绝”的语义漂移。

### 5.3 final neighbor check 固定中心

原因：原循环里 `evaluate()` 会更新 incumbent，第一个方向找到更优点后，后续“邻居”实际围绕新中心生成，`no_known_better_neighbor` 不再是固定中心的邻域结论。

修改：每轮先 `center = incumbent.result` 快照，一次性生成全部 16 方向邻点后批量评价；若发现更优则交回局部模式精修，精修结束后重新做固定中心邻域检查；最多 3 轮，只有干净通过才置 `no_known_better_neighbor = True`。字段名保持“no_known_better_neighbor”，未升级为局部最优证书。

### 5.4 search bounds 只澄清不重写

`derive_search_bounds()` 语义澄清为 `B_search ⊇ C_rec`：docstring 说明它取“部分必要 witness 圆盘”的轴对齐包围盒交集，可能偏松但不会删掉真实 Crec 点；`derivation` 改为 `safe_superset_from_subset_of_mandatory_crec_disk_boxes`；新增断言 `S1 ∈ B_search`（因 `S1 ∈ C_rec`）。每个真实候选仍必须调用精确 `is_in_crec()`。

### 5.5 Crec deep-arc witness 独立数值对拍

新增 `verifier/verify_crec_deep.py`：

- `verify_crec_deep_arc_witnesses(...)` 对每条 `RADIAL_DEPTH` 的 Ω 弧，比较主候选器的最大 violation 与独立高密度（默认 2049）弧参数扫描 + 黄金分割精修的最大 violation，给出逐弧 gap 与 pass/fail。
- `verified_in_crec(...)`：快速判定与独立扫描一致时返回快速结果；若独立扫描发现更大 violation，则采用更大值；若这改变了归属判定，则返回修正后的 fail-closed 结果；无法界定时抛 `CrecUnderestimateError`。

**实测**：在深部进入工况（`S1=(3000,0), θ1=180°`，产生 `crec_omega_truncated_rho_lo` 且 `radius_mode=radial_depth`）下，对多个候选第二点的独立扫描 gap 均为 0，未发现主候选器低估。明细见 `q2_verification/crec_witness_verifier.json`。

### 5.6 1500 m 语义

`OUTER_RADIUS_M = 1500` 未删除。`CrecWitnessLabel.RHO_1500_AS_DEEP_END_WITNESS` 的构造期守卫保留，并新增测试断言任何支持维度的 Crec 注册表都不含该 witness，同时确认 A1 的径向区间始终受 1500 m 上界约束。

### 5.7 all-near 与 180° 反向共线

- `all_near` 分支与 `angular.all_near` 全保留。构造性测试：POINT 退化 A1 且第二点与单点重合 → `all_near=True`、`Q=0.0`。论文中不作为主场景。
- 未新增任何 180° 硬禁区。新增测试：同一 `S_2=(950,120)` 上，`β≈θ_1+180°`（187.2°）的交会直径有界且为 `133.44 m`，正交方位（270°）为 `33.44 m`；只断言“有界 + 明显更差”的序关系，不硬编码倍率。`3ε` 门只负责有界性：`S_2=(600,y)` 当 `y` 从 120 降到 75 时最坏直径单调爆炸（约 1628 → 45376 m），`y=70` 时不可容许、`Q=None`。

### 5.8 Baseline 与论文对齐

按 v3 正文：**B1 = 中心射线中点 90° 启发式**（双侧同时评价，取对 baseline 更有利的一侧），**B2 = 中心射线解析 max-min-angle 启发式**（Ω 截断时标记为 canonical heuristic，不再声称解析最优）。

- `gate_g.py`：B1/B2 标签互换；`_right_angle_heuristic` 改为双侧选择器并返回逐侧 witness；原 `_b1_provenance` 改为 `_b2_provenance`，新增 `status / analytic_optimality_claimed / omega_truncated / clamped` 字段；两侧与 B2 的 clamp 都在 provenance 里显式披露（`componentwise_to_crec_derived_bounds`）。
- `baselines.py` 仅改文档，未改数值。
- `verifier/verify_gate_g.py` 独立重算 B1/B2 两条 provenance 并核对 `rows[1]`/`rows[2]` 的点。
- 所有 baseline 仍统一经 `evaluate_q2_point()` 重新得到 Q/Crec/admissibility。

### 5.9 Symmetry 仅作 special-case verifier

`_is_x_axis_symmetric_case()` 保持只识别 `S1=(0,0), θ1=0°`。新增 `verifier/verify_symmetry.py` 输出 `symmetry_report.json`：Hero 与镜像点经同一评价器复核、Q 差在容差内、候选区域采样点的镜像配对计数与正/负半区面积差。未把“双翼候选区域”升级为一般定理。

---

## 6. 测试与验证结果

### 6.1 全量测试

命令（必须从仓库根目录运行，测试使用 `src.q2.code...` 绝对导入）：

```bash
cd D:/CUMCM2026 && python -m pytest src/q2/code/tests/ -q -p no:cacheprovider
```

结果（最终验证时间点 `2026-09-11 13:55`）：**201 passed，1 skipped，0 failed**，耗时 `1292 s`（21 分 32 秒）。

完善过程：首轮全量运行有 1 项失败，源于我新增的对称性测试遗漏了镜像 seed（`extra_seeds`），已修正；随后为满足题目点名的候选区域字段要求，又在区域 JSON/GeoJSON 中补入 `classification_samples` 并重新生成证据产物。以上最终数字是在**当前仓库状态**（含 §6.4 所述的并发 `a1.py` 修正）下重跑得到的。

`passed` 覆盖原有 Gate A–G′、final-package、clean-room、batch 回归，以及本次新增的 7 个测试文件：

```text
tests/q2/test_a1_dimension.py
tests/q2/test_crec_verifier.py
tests/q2/test_angular_image_near.py
tests/q2/test_inner_max_independent.py
tests/q2/test_outer_search_validity.py
tests/q2/test_candidate_region_resolution.py
tests/q2/test_symmetry.py
```

新增测试覆盖题目点名的 12 类场景：中心 A1 正常工况、Ω 截断、S1 在 Ω 外但几何合法、`0/360°` wrap、near 边界、all-near 退化、`3ε` 边界、反向共线有界退化、E4 驻点与 E5 包络切换、Crec deep-arc 驻点、`workers=1` 与 `workers=2` 一致、候选区域 coarse→fine。所有测试均使用固定输入或固定种子，不依赖随机幸运种子。

`test_gate_f.py` 中断言搜索盒 provenance 字符串的两处已随 `derivation` 语义澄清同步更新。

### 6.2 独立验证 JSON

| 文件 | 结论 |
|---|---|
| `inner_verifier_report.json` | 15 个探针（含 Hero、镜像、两条 baseline、中心射线近 `3ε` 边界点、区域低 Q/高 Q 样本）；11 个可评价点全部 `abs_gap = 0.0 m`，`passed = true` |
| `crec_witness_verifier.json` | 覆盖两个工况：`centered`（深弧 witness 数 0）与 `deep_entry_s1_outside_omega`（`S1=(3000,0), θ1=180°`，深弧 witness 数 1）；共 12 个探针、6 条深弧记录，逐弧 `gap` 最大 `2.27e-13 m`（纯浮点残差），独立稠密 (θ,ρ) oracle 全部通过，`passed = true` |
| `candidate_region_resolution_stability.json` | `qhat` 相对散布 `9.96e-4`；5% 面积 `0 / 629.757 / 0 m²`，连通分支 `(0,4,0)`，面积相对散布 `1.0`；**未收敛，如实报告** |
| `symmetry_report.json` | 中心工况 Hero 与镜像 Q 差 `2.27e-13 m`；候选区域采样点镜像配对 351 对、0 未配对；正/负半区面积完全相等；`passed = true` |

### 6.3 一条值得写进论文的额外发现

`verify_inner_max_independent` 的“近平行事件显式加密”分支**在可容许点上永远不会被触发**：可容许性要求 `dist_S(Θ̄₂^dir, θ̂₁) > 3ε`，因此膨胀后的允许区间端点距 `θ̂₁` 严格大于 `2ε`，而平行事件恰好位于 `β = θ̂₁ ± 2ε` 与 `θ̂₁ + π ± 2ε`。前两者被门限严格排除；后两者只有在角像跨度越过 `θ̂₁ + π` 附近时才会落入区间，而代表性工况的角像（约 `187.6°–356.6°`）并不覆盖该处。

因此该加密分支是**防御性**的：它在结构上不会在生产可容许点上触发，但仍是必要的完备性保护（若未来放宽 `3ε` 门或改变允许集合定义，它就会生效）。单元测试用一条刻意跨越 `θ̂₁ + π` 的合成允许区间验证该机制确实会创建加密带，并另有一条测试断言可容许点上加密带计数为 0。

### 6.3 最终硬门自检

```text
[x] py_compile / tests PASS
[x] Q1 adapter 未被改数学语义（model/q1_adapter.py 与 src/q1/** 均未修改；已与快照逐文件比对确认未变）
[x] Crec main vs independent verifier 无未解释低估（深弧 gap 全为 0）
[x] inner Q main vs independent verifier 无未解释低估（探针 gap 全为 0；108 点网格亦无 promote）
[x] outer search valid predicate 统一且 finite（外层与 incumbent 共用 is_valid_incumbent_result）
[x] fixed-center final neighbor check PASS
[x] candidate region 明确标记 numerical/not proof（kind = numerical_candidate_good_region_not_proof）
[!] candidate region resolution stability 已报告 —— 已报告，但结论是「未收敛」，不是「已收敛」
[x] centered symmetry check PASS
[x] anti-parallel 没被错误列为 unbounded（187.2° 处直径 133.44 m，有界）
[x] 1500 m 没被错误从 A1 删除（OUTER_RADIUS_M=1500 保留，禁用的只是 deep-end witness）
[x] all-near 保留为 degenerate completeness branch
[x] global optimum claim 仍为 FALSE（CERTIFIED_GLOBAL_OPTIMUM = False，代码中无 global optimum 断言）
```

其中 `candidate region resolution stability` 一项按要求「只报告真实收敛、不预置硬门」，因此报告结果是负面的。按第 16 节规则，这不属于「静默降级」：它被显式标注为未收敛，并登记为剩余限制第 3 条。

### 6.4 并发修改声明（重要）

本仓库同时存在**另一条独立工作流**：`formal/`、`artifacts/formal/`、`Q2_FORMAL_OPTIMALITY_REPORT.md`、`Q2_FORMAL_OPTIMALITY_CERTIFICATE.md`、`tests_formal/`，以及在 `2026-09-11 12:35` 修改了 `code/geometry/a1.py` 的外部切线轴修正。该工作流建立的是「冻结模型下的 ε-最优区间证书」，其结论仍显式保留 `certified_global_optimum = false`（仅在区间包络意义下报告），与本次修复的 `CERTIFIED_GLOBAL_OPTIMUM = False` 不冲突。

- 该工作流在本报告涉及文件中的唯一改动是 `code/geometry/a1.py` 的外部站点切线轴反向修正（原实现把「圆心→站点」方向当成「站点→圆心」方向，会在外部切触附近漏掉窄正面积楔）。该修正不在本次最小补丁范围内。
- 本次修复的全部 A1 相关测试（`test_gate_a.py`、`tests/q2/test_a1_dimension.py`、`test_gate_c.py`，共 49 项）在该修正之后重新运行并通过。
- 本次修复的完整全量套件结论（200 passed / 1 skipped）是在该修正之前的一次运行中得到的；修正之后已重新运行全量套件，最终数字见 §6.1。若在最终验证时间点之后还有并发修改，本报告的结论需按新状态重跑。

---

## 7. 剩余限制（remaining limitations）

1. **无全局最优证书**：外层搜索仍是确定性的粗网格—细分—模式搜索，没有覆盖整个二维域的下界或 branch-and-bound 证书；`CERTIFIED_GLOBAL_OPTIMUM = False` 保持不变。
2. **候选区域只是数值近似**：4 角点+中心是有限样本，不能证明单元内部处处满足 `Q <= threshold`；输出字段刻意命名为 `numerical_candidate_good_region_not_proof`。
3. **候选区域的分辨率收敛性未建立（最重要）**：实测 coarse/medium/fine 三档的 5% 面积分别为 `0 / 629.757 / 0 m²`，连通分支数 `(0, 4, 0)`，面积相对散布为 `1.0`。原因是 5% 次水平集相对搜索盒极薄，而自适应细分每层只允许 32 个单元，导致“4 角点+中心全在阈值内”的判定对 Hero 位置/阈值只有厘米级敏感度。论文因此**不得**声称该区域已收敛；只能给出“固定最高细分预算下的数值近优采样”，并同时报告面积与分辨率敏感性。根本修复需要改成沿阈值带的按长度自适应细分预算。
4. **独立内层扫描是下界而非上界**：独立扫描为有限采样，可能低于主候选值（已实测个别负 gap，例如 `S2=(1120,-650)` 处 `gap=-8.17e-5 m`）；其作用是“防止主结果低估”，不是给出新的上界证明。
5. **E4 分支未在测试族中成为最坏值**：固定拓扑段内最远点对距离的驻点根确实存在，但在所有被测构型中，最坏 β 都落在 E1 端点或 E5 包络切换点，未出现 E4 主导 case；E4 仍是防御性分支，论文不应声称其主导。
6. **`SEGMENT` 的精确 Crec 未实现**：1 维退化 A1 仍由 `build_crec()` 显式 hard fail，这是设计上的 fail-closed，不是遗漏。
7. **`all-near` 只在 POINT/低维退化 A1 下可构造**：对具有宏观径向深度的正面积 A1，`A1^dir` 不可能为空，因此该分支是完备性兜底而非主叙事。
8. **旧的手工 v6 交接产物未重新生成**：`src/q2/code/artifacts/q2_*.{json,csv}` 与 `src/q2/code/figures/*` 属于此前由**仓库内已不存在**的 `q2-final-evidence-v6-dynamic-closure` 流程产出的冻结交接包，其中仍带有修复前的 B1/B2 标注。仓库内可复现的 `artifacts/gate_g_representative/`（配置 `q2-final-evidence-v5-hero-closure`）已用修复后代码重新生成并与新标注一致。若论文使用 v6 交接包，需先用修复后代码按 `artifacts/q2_final_evidence_config.json` 重跑该流程。读取这些文件的 `test_final_package` / `test_gate_g_prime` 仍通过，因为它们只断言方法名/位置与未变的 Hero 值（Q=134.07676525132717）。
9. **提交用代码需脱敏**：按赛题要求，附录/支撑材料中的代码应隐去参赛队号。

---

## 8. 文件级 patch 清单与交付物位置

### 8.1 本次最小补丁改动的文件

**几何层**

| 文件 | 改动 |
|---|---|
| `geometry/a1.py` | 新增 `A1DimensionClassificationError`、内部见证容差常量、`_strict_interior_witness` / `_interior_witness_angles` / `_strict_radial_witness` / `_degenerate_dimension` / `_piece_has_positive_length` / `_piece_midpoint_in_a1`；`build_a1` 改为 fail-closed 维数分类（另含 §6.4 所述并发切线轴修正） |
| `geometry/angular_image.py` | 新增 `TANGENCY_TOL_M`，切触桥比较改为紧 `math.isclose` |

**求解层**

| 文件 | 改动 |
|---|---|
| `solver/q2_point.py` | epsilon 比较改 `math.isclose`；production 内层改调 `maximize_inner_verified` |
| `solver/inner_max.py` | 新增 `InnerVerificationConfig`、`InnerMaxUnderestimateError`、`maximize_inner_verified`、`_strictly_exceeds`、`_promote_from_verification` |
| `solver/outer_search.py` | `_is_valid`/`_result_key` 复用 incumbent 谓词；`derive_search_bounds` 语义澄清 + `derivation` 更名 + `S1 ∈ B_search` 断言；final neighbor 改为冻结中心 + 复核循环；删除失效的 `evaluate` 闭包 |
| `solver/candidate_regions.py` | 4 角点+中心分类、中心感知细分与优先级、有界 Q 值域触发、`q_range_refinement_ratio`、`kind`/`classification_samples` |
| `solver/gate_g.py` | B1/B2 互换；`_right_angle_heuristic` 改双侧并返回 provenance；`_b1_provenance` → `_b2_provenance`（含截断声明与 clamp 披露）；三处区域 JSON/GeoJSON 增加 `classification_samples` |
| `solver/baselines.py` | 仅 docstring 对齐 |

**验证层**

| 文件 | 改动 |
|---|---|
| `verifier/verify_inner.py` | 新增 `IndependentInnerVerification`、`verify_inner_max_independent` 及其独立采样/加密/精修辅助函数；事件带去重 |
| `verifier/verify_crec_deep.py` | **新增**：深弧独立对拍 + `verified_in_crec` fail-closed 门 |
| `verifier/verify_candidate_resolution.py` | **新增**：分辨率收敛研究 |
| `verifier/verify_symmetry.py` | **新增**：中心工况镜像 special-case verifier |
| `verifier/verify_gate_g.py` | 双 baseline provenance 校验；区域 payload 增加 `classification_samples` |

**测试与工具**

| 文件 | 改动 |
|---|---|
| `tests/test_gate_f.py` | 同步 `derivation` 字符串并加 `S1 ∈ B_search` 断言 |
| `tests/test_gate_g.py` | 同步 B1/B2 命名与 provenance 断言 |
| `tests/test_gate_g_prime.py` | 增加 `kind` / `classification_samples` 断言 |
| `tests/q2/test_*.py` | **新增 7 个测试文件**（见 §6.1） |
| `tools/generate_q2_verification.py` | **新增**：四个验证 JSON 的真实计算生成器 |
| `artifacts/gate_g_representative/*` | 用修复后代码重新生成（Hero 与 Q 未变：`(800.1012338639696, -606.388471543349)`，`Q = 134.07676525132717`） |

### 8.2 交付物

```text
src/q2/code/Q2_CODE_REPAIR_REPORT.md              ← 本文件
src/q2/code/q2_verification/
    inner_verifier_report.json
    crec_witness_verifier.json
    candidate_region_resolution_stability.json
    symmetry_report.json
```

生成脚本：`src/q2/code/tools/generate_q2_verification.py`（所有数值均由真实程序计算，无手工填写）。

复现命令：

```bash
cd D:/CUMCM2026
PYTHONPATH=. python src/q2/code/tools/generate_q2_verification.py
python -m pytest src/q2/code/tests/ -q -p no:cacheprovider
```
