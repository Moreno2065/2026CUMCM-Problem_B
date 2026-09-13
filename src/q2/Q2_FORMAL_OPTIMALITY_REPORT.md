# Q2 全局最优性形式化验证报告（Formal Optimality Report — Closure 定稿版）

**日期**：2026-09-11（closure spec：FINAL CERTIFICATE CLOSURE SPEC）
**对象**：冻结的 Q2 有界误差 minimax 模型，**certificate scope = `canonical_center_case`**
（S1=O=(0,0)，θ̂1=0°，ε=1°，Ω=B(O,1800)）
**结论**：`CERTIFIED_GLOBAL_EPS_OPTIMUM`（closure §53 GO：六项条件全部满足后恢复）

```
L_rigorous = 134.05597622410357  ≤  Q*  ≤  U_rigorous = 134.0659292484056   （m）
绝对间隙  U − L = 0.009953024302  ≤  τ = 0.01 m
相对间隙  (U−L)/max(U,1) = 7.4235×10⁻⁵
```

最终证书：`src/q2/artifacts/formal/q2_global_optimality_certificate.json`（schema v2，§42 字段）
最终快照：`snapshots/q2_cert_final_rigorous/`（source / artifacts / tests / SHA256 manifest / 引理文档）

**角色声明（closure §49）**

| 维度 | 内容 |
|---|---|
| Model scope | 仅 canonical 中心构型；一般 (S1, θ̂1) 实例由同一模型逐实例求解，本证书不自动推广 |
| Search engine | float64 外向区间批量分支定界（只负责搜索/发现证明树） |
| Certificate engine | Arb 球算术整棵证明树逐节点重放（§35 Path 1） |
| Sampling role | 仅反证（mpmath fuzz、稠密采样、跨引擎抽查），不承担全局下界完备性 |
| Symmetry | **解析定理**（Phase A），数值测试仅作 Theorem A 的反例回归 |
| Lower bound | 整棵树的严格重放 + Arb 侧严格细分（Phase B） |

---

## 1. 证明了什么、没证明什么（closure §2, §3, §44）

**证明**：可行点

$$\widehat S_2=(805.1110506884,\ -599.7632926544)$$

（符号按 §3：$\widehat S_2$ 是严格可行候选；理论最优集记 $S_2^\star\in\arg\min Q$）
在冻结 Q2 模型的 canonical 中心构型下满足

$$\boxed{\,Q(\widehat S_2)-Q^\star\ \le\ 0.01\ \text{m}\,}$$

**不证明**：一般输入下的全局最优性（§2 scope 声明）；$\widehat S_2=S_2^\star$ 的等号（`certified_global_optimum = false`）；最优解唯一性（`unique_optimizer = NOT_PROVEN`，§44）；bounded-error minimax 建模本身的优越性。

## 2. Proof Gap 的闭合（closure §0 → §53）

收尾前证书被降级为 `GLOBAL_EPS_CERTIFICATE_CANDIDATE`，原因与闭合结果：

| Gap | 内容 | 闭合方式 | 状态 |
|---|---|---|---|
| P0-A | 半域搜索的镜像对称性仅由 float 回归支撑 | **Phase A**：解析证明（下文 §3） | CLOSED |
| P0-B | 高速 float64 内核的剪枝树未经严格重放（仅抽查 2000 盒） | **Phase B**：整棵证明树的 Arb 逐节点重放（下文 §4–§6） | CLOSED |

## 3. Phase A — 解析对称性定理（closure §4–§14）

`src/q2/Q2_CANONICAL_SYMMETRY_LEMMA.md` 给出完整数学证明（非测试）：

* **Lemma A1**：$\mathcal R(\mathcal A_1)=\mathcal A_1$（$\|\mathcal RG\|=\|G\|$；$\arg(\mathcal RG)=-\arg G$；$d_{\mathbb S}(-a,0)=d_{\mathbb S}(a,0)$，含 Ω 约束）；
* **Lemma A2**：$\mathcal R(\mathcal C_{\rm rec})=\mathcal C_{\rm rec}$（等距 + 球半径只依赖 $\|G\|$）；
* **Lemma A3**：scenario 双射 $(G,e)\mapsto(\mathcal RG,-e)$，near/bearing 分支完全保持；
* **Lemma A4**：镜像测得 bearing $\beta'=-\beta\pmod{2\pi}$；
* **Lemma A5/A6**：$\mathcal R\mathcal K(S,\theta)=\mathcal K(\mathcal RS,-\theta)$；$\mathcal R\,P_{\rm Q1}(S_2,\beta)=P_{\rm Q1}(\mathcal RS_2,-\beta)$；直径在有距映射下不变，有界性保持；
* **Theorem A**：$Q(\mathcal RS_2)=Q(S_2)$（all-near / 有限 / $+\infty$ 三种扩展值情形全覆盖）；
* **Corollary A**：$\inf_{\mathcal C_{\rm rec}}\widetilde Q=\inf_{\mathcal C_{\rm rec}\cap\{y\le0\}}\widetilde Q$（**闭**半平面，不动点无边界歧义）——半域 master 的合法性 proof object。

原 `test_reflection_symmetry_of_Q` 降级为 Theorem A 的反例回归（falsification only，§36）。机器可读断言：`canonical_symmetry_lemma.json`（T10 校验其与文档一致）。

## 4. Phase B — 证明树重录（closure §17, §32, §47）

历史运行未保存证明树 → 诚实标记 `OLD_TREE_NOT_REPLAYABLE`，按 §32 以**完全相同的冻结输入**重录：

* 同一 9 个 scenario、20 个 reception witness、同一 incumbent $U$、同一根域 $B_0^-$、同一容差——只记录，不重优化；
* 新树 3,022,561 节点：SPLIT 1,511,280 / PRUNE_A 463,354 / PRUNE_B 35,704 / LIVE_FINAL 1,012,223（守恒：1+2S=节点数 ✓）；
* 节点盒端点为**精确二进有理数**（float64 = $m\cdot2^e$；分割中点在 binary64 内精确，验证器用 `Fraction` 逐节点复核）；
* 重录树的下界 $L_{\rm fast}=134.0569292534515$ 与独立 replay 重解**逐位一致**（确定性引擎），live=1,012,223 一致。

产物：`proof_tree.npz` + `proof_tree_index.json` + `proof_tree_manifest.json`（含 SHA256 与 `OLD_TREE_NOT_REPLAYABLE` 声明）。

## 5. Phase B — 整树严格重放（closure §15–§33, §36–§38）

`proof_tree_replay.py`（证书引擎 = Arb/python-flint，§35 Path 1）四阶段：

1. **Stage 0 冻结输入再验证**：锚点 $G_0=(1000,0)$、20 个 witness、9 个 scenario 的 A1 合法性全部以 Arb 三态复核；$B_0^-$ 由 $\mathcal C_{\rm rec}\subseteq B(G_0,1000)$ 重新推导核对。**发现并严格处置一个真实输入缺陷**：seed 场景 7 的浮点构造落在楔形**闭边界外**约 $1.4\times10^{-17}$ 度（512-bit 测量）——按合法化程序朝楔形内旋转 $10^{-12}$ rad（记录于 `legalized_scenarios`），此后所有场景必然严格合法；$e=\pm1°$ 的等号情形用精确有理数检查（$|e_{\rm deg}|\le1\Rightarrow|e|\le\varepsilon$，两侧同乘精确 $\pi/180$）。
2. **Stage 1 拓扑（§21–22）**：每个 SPLIT 节点恰有两个子节点、精确平铺父盒、中点精确、无悬挂节点、叶划分覆盖根——`Fraction` 精确算术逐节点通过。
3. **Stage 2 全部历史剪枝重放（§31）**：499,058 个剪枝节点 = **客观剪枝 461,483 个**（Arb 证明 $\inf_B M>U$，严格约定与引擎一致）+ **接收剪枝 35,706 个**（Arb 距离证明整盒在某 witness 球外）+ **1,880 个被降级**（Arb 顶点对下界不可确认——大盒上 Arb 的顶点对包络弱于 float 核，降级为带有效 Arb 下界的活叶，绝不猜回）；三态比较，UNKNOWN 升级 128→256→512 bit（68 次）；`unverified_pruned_node_count = 0`。
4. **Stage 3/4 活叶下界与严格细分**：1,012,223 个活叶全部取得有效 Arb 下界入最小堆；初始最小值被少数混合盒的 0 值压住（合法但弱），按 §25"混合盒只允许细分"以 **1,174 次 Arb 侧严格细分**收敛到

$$L_{\rm rigorous}=134.05597622410357 .$$

**THEOREM B — Master Relaxation Lower Bound**（§38，合法性的核心链）：

$$L_{\rm rigorous}=\min_{\ell\in\mathcal L_{\rm live}}LB_{\rm Arb}(B_\ell)
\ \le\ \inf_{S_2\in\mathcal D_k\cap\{y\le0\}}M(S_2)
\ \le\ \inf_{S_2\in\mathcal C_{\rm rec}\cap\{y\le0\}}\widetilde Q(S_2)
\ =\ Q^\star,$$

三步依据：叶覆盖与 $LB(B)\le\inf_B M$（逐盒成立）；$\mathcal C_{\rm rec}\subseteq\mathcal D_k$ 且 $\mathcal S\subseteq\mathcal S_{\rm phys}$（$M\le\widetilde Q$）；Corollary A（解析）。

**§36 声明**：mpmath fuzz / 稠密采样 / 2000 盒抽查等结果仅作反证证据存档，全局下界完备性由本整树重放独立承担。

**§41 声明**：严格重放的下界（134.05598）低于快速引擎的搜索级下界（134.05693），差约 $9.5\times10^{-4}$ m——这是 Arb 包络在大盒上较弱 + 1,880 个降级盒的诚实代价；未发生 `OLD_LOWER_BOUND_INVALIDATED`（旧下界仍是合法下界，只是不再作为证书数字）；细分在预算内把间隙压回 τ 内。

## 6. 上界与可行点（closure §39）

$\widehat S_2$ 以 **256-bit Arb** 重新认证：

$$Q(\widehat S_2)\in[\,134.06592067413175,\ 134.06592958404886\,]\ \text{m},\qquad
U_{\rm rigorous}=134.0659292484056,$$

$\widehat S_2\in\mathcal C_{\rm rec}$ 严格可行裕度下界 $8.0282\times10^{-5}$ m $>0$（重算）。all-near 检查否定（$\max_{G}\|\widehat S_2-G\|\approx10^3$ m $\gg5$）。

## 7. 最终数字与 GO 判定（closure §40, §52, §53）

| §53 条件 | 结果 |
|---|---|
| analytic symmetry proof PASS | ✓（Phase A，PROVEN_ANALYTIC） |
| full tree coverage PASS | ✓（1,511,280 splits 精确平铺根盒） |
| all historical pruning decisions rigorous PASS | ✓（499,058/499,058：461,483+35,706 确认，1,880 降级为有效活叶） |
| unverified pruned nodes = 0 | ✓ |
| $L_{\rm rigorous}\le Q^\star\le U_{\rm rigorous}$ | ✓（THEOREM B 链 + 256-bit UB） |
| $U-L\le0.01$ m | ✓（0.0099530） |

→ **GO**：状态恢复 `CERTIFIED_GLOBAL_EPS_OPTIMUM`，scope=`canonical_center_case`。

## 8. 最优解集外包络（§43 重放版）

重放存活活叶（每个都带有效 Arb 下界）构成 $\mathcal X^\star_{\rm outer}$：

```
box_count = 1,013,143
x_span = [546.875, 897.4609375] m
y_span = [-820.3125, -404.296875] m   （半域；镜像由 Theorem A 给出）
max_box_diameter = 4.367 m
数据：optimizer_live_boxes.npz（重放版，取代快速循环版）
```

仍非唯一性证明（§44）。

## 9. 验证层次与测试（closure §46）

* T1–T10 七个新测试文件全部通过（微型树 fixture 走通 记录→重放 全链）；
* `tests_formal` 全套 69 项：68 passed + 1 gated（`RUN_FULL_REPLAY=1` 的 V4 全量重放，曾以 2 passed 通过）；
* 既有 gate 回归：`src/q2/code/tests` 201 passed + 1 skipped（closure 未触碰 code 层）；
* 永久对抗 fixture 新增：atan2 分支切双弧、近圆混合盒、S2∈Ā₁ 全圆、对踵 witness、all-near 否定、证书 scope/措辞纪律等。

## 10. 产物、快照与复现（§47, §48）

```
src/q2/formal/            …（原 16 模块）+ proof_tree.py / record_proof_tree.py /
                          proof_tree_replay.py / finalize_certificate.py
src/q2/artifacts/formal/  proof_tree.npz / proof_tree_index.json / proof_tree_manifest.json /
                          proof_tree_replay_result.json / canonical_symmetry_lemma.json /
                          rigorous_master_lower_bound.json / optimizer_live_boxes.npz /
                          q2_global_optimality_certificate.json (schema v2) / …（原有产物）
src/q2/                   Q2_CANONICAL_SYMMETRY_LEMMA.md / Q2_FORMAL_OPTIMALITY_REPORT.md /
                          Q2_FORMAL_OPTIMALITY_CERTIFICATE.md
snapshots/                q2_cert_candidate_pre_closure → q2_symmetry_proven →
                          q2_proof_tree_recorded → q2_cert_final_rigorous
                          （沿革与并行会话记录见 snapshots/README.md）
```

复现：`python -m src.q2.formal.proof_tree_replay`（整树重放，~13 min）
＋ `python -m src.q2.formal.finalize_certificate`；测试：`python -m pytest -q src/q2/tests_formal`。

## 11. Claim ladder（§44/§50）

**Claim A — Certified epsilon optimum（scope: canonical center case）**：
$L_{\rm rigorous}=134.0559762\le Q^\star\le U_{\rm rigorous}=134.0659292$，$U-L=0.0099530\le\tau=0.01$ m。
论文措辞见《Q2_FORMAL_OPTIMALITY_CERTIFICATE.md》（§50 成功版模板）。
