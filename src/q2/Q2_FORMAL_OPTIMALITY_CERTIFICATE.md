# Q2 全局最优性证书（Paper-Ready Certificate — Closure 定稿版）

状态：**CERTIFIED_GLOBAL_EPS_OPTIMUM**（closure §53 GO 后恢复；§2 合法状态；Claim A）
**Scope：`canonical_center_case`**（S1=O，θ̂1=0°，ε=1°，Ω=B(O,1800)）

---

## 1. 证书数字

$$
\boxed{\;L_{\rm rigorous}=134.05597622410357\ \le\ Q^\star\ \le\ U_{\rm rigorous}=134.0659292484056\;}\ \text{（m）}
$$

$$
U_{\rm rigorous}-L_{\rm rigorous}=0.009953024302\ \le\ \tau=0.01\ \text{m},
\qquad
\tau_{\rm rel}=7.42\times10^{-5}.
$$

**可行点（incumbent，符号 $\widehat S_2$，§3）**

$$
\widehat S_2=(805.1110506884,\ -599.7632926544),
$$

$$
Q(\widehat S_2)\in[\,134.065916938941538\ldots,\ 134.066009059081892\ldots\,]\ \text{m}
$$

（Arb 外向十进制包络；closure §39 以 256-bit 重认证得 $Q\in[134.06592067413175,\ 134.06592958404886]$，
$\widehat S_2\in\mathcal C_{\rm rec}$ 严格可行裕度下界 $8.0282\times10^{-5}$ m $>0$。）

**all-near**：`false`（严格证明 $\max_{G\in\overline{\mathcal A}_1}\|\widehat S_2-G\|\approx10^3$ m $\gg5$）。

## 2. 论文结论措辞（closure §50 成功版模板）

> 为验证问题 2 求解器的全局优化能力，本文选取 $S_1=O,\ \hat\theta_1=0^\circ$ 的标准中心构型进行严格数值验证。由目标集合、接收约束及测向模型关于第一示向轴的解析镜像对称性，可将全局搜索严格约化至一个半平面。随后使用确定性分支定界生成搜索树，并由独立的区间/球算术验证器对整棵证明树中的空间覆盖和全部剪枝决策逐节点重放。最终得到
>
> $$L\le Q^\star\le U,$$
>
> 且
>
> $$U-L\le0.01\ \text{m}.$$
>
> 因此所得可行点 $\widehat S_2$ 在该标准构型的冻结有界误差 minimax 模型下距全局最优值不超过 $0.01$ m。

## 3. 证明义务闭合（closure §53 GO 六条）

| 义务 | 结果 |
|---|---|
| Analytic symmetry proof | **PASS** — Lemma A1–A6 + Theorem A + Corollary A（`Q2_CANONICAL_SYMMETRY_LEMMA.md`，数学证明） |
| Full tree coverage | **PASS** — 1,511,280 个分割节点精确平铺根盒 $B_0^-$，叶划分完整，无悬挂节点（`Fraction` 精确算术逐节点核验） |
| Historical pruning decisions rigorous | **PASS** — 499,058 个历史剪枝全部重放：461,483 个客观剪枝（Arb 证明 $\inf_B M>U$）+ 35,706 个接收剪枝（Arb 距离证明球外）+ 1,880 个降级为带有效 Arb 下界的活叶 |
| Unverified pruned nodes | **0** |
| $L_{\rm rigorous}\le Q^\star\le U_{\rm rigorous}$ | **PASS**（THEOREM B：$L\le\inf_{\mathcal D_k\cap\{y\le0\}}M\le\inf_{\mathcal C_{\rm rec}\cap\{y\le0\}}\widetilde Q=Q^\star$，末步为 Corollary A） |
| $U-L\le0.01$ m | **PASS**（0.0099530） |

**三引擎分工（§49）**：搜索 = float64 批量区间分支定界（只发现证明树）；证书 = Arb 球算术整树重放（下界）+ 256-bit 再认证（上界）；采样 = 仅反证。

**解析对称性（§49）**：`symmetry_lemma_analytic = true`；`half_domain_reduction_certified = true`。数值对称性测试保留为 Theorem A 的反例回归，不承担证明。

## 4. 机器可读证书（closure §42 schema v2）

`src/q2/artifacts/formal/q2_global_optimality_certificate.json` 关键字段：

```json
{
  "scope": "canonical_center_case",
  "status": "CERTIFIED_GLOBAL_EPS_OPTIMUM",
  "certified_global_optimum": false,
  "certified_epsilon_global_optimum": true,
  "epsilon_optimality_tolerance_m": "0.01",
  "rigorous_lower_bound_m": "134.05597622410357",
  "rigorous_upper_bound_m": "134.0659292484056",
  "absolute_gap_m": "0.009953024302035374",
  "incumbent_symbol": "S2_hat",
  "symmetry_lemma_analytic": true,
  "half_domain_reduction_certified": true,
  "proof_tree_complete": true,
  "proof_tree_coverage_verified": true,
  "historical_prunes_replayed": true,
  "unverified_pruned_nodes": 0,
  "lower_bound_engine": "Arb proof-tree replay",
  "upper_bound_engine": "Arb",
  "float_batch_engine_used_only_for_search": true,
  "sampling_used_as_proof": false,
  "unique_optimizer": "NOT_PROVEN"
}
```

源码版本绑定：快照 `snapshots/q2_cert_final_rigorous/`，manifest SHA256 见证书字段 `source_sha256_manifest`（与快照内 `source_manifest_sha256.json` 一致，已程序化核验）。

## 5. 最优解集外包络（§43 重放版，信息性）

重放存活活叶（每个带有效 Arb 下界）：

```
box_count = 1,013,143
x ∈ [546.875, 897.4609375] m,  y ∈ [-820.3125, -404.296875] m
（半域；镜像区域由 Theorem A 给出）  max box diameter = 4.367 m
```

外近似，非唯一性声明（`unique_optimizer = NOT_PROVEN`）。

## 6. 诚实备注（§41/§45/§51）

* 严格重放的下界（134.05598）比快速引擎的搜索级下界（134.05693）低约 $9.5\times10^{-4}$ m：Arb 顶点对包络在大盒上弱于 float 核 + 1,880 个剪枝降级为活叶的诚实代价；经 1,174 次 Arb 侧严格细分收敛到证书值。旧快速下界仍是合法下界，仅不再作为证书数字。
* 场景措辞（§45 修正）：所选 9 个严格合法 scenarios 已足以使有限松弛问题的严格全局下界收紧到目标证书精度；有限 scenario 集无需覆盖完整物理 scenario 集，其子集性质本身保证所得到的是原问题的合法下界。
* 本证书不证明：一般 $(S_1,\hat\theta_1)$ 实例的全局最优性；$\widehat S_2$ 的唯一性；任何未定义的现实性能。
