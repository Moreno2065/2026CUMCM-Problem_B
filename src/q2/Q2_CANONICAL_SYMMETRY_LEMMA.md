# Q2 CANONICAL SYMMETRY LEMMA — 解析镜像对称性定理（证书 proof object）

**状态**：PROVEN（本文档为数学证明，不是测试报告）
**适用范围（certificate scope）**：`canonical_center_case`，即

$$S_1=O=(0,0),\qquad \hat\theta_1=0^\circ,\qquad \varepsilon=1^\circ,\qquad \Omega=B(O,1800).$$

**作用**：本定理是全局 master 搜索被严格约化到半平面 $\{y\le 0\}$ 的合法性依据
（Theorem A + Corollary A）。此前的回归测试
`tests_formal/test_proof_invariants.py::test_reflection_symmetry_of_Q`
自本定理生效起**降级为 Theorem A 的反例回归测试（falsification only）**，
不再作为半域约化的证明依据。

---

## 0. 记号与预备事实

**镜像算子**

$$\mathcal R:\mathbb R^2\to\mathbb R^2,\qquad \mathcal R(x,y)=(x,-y).$$

$\mathcal R$ 是等距对合（involution）：$\mathcal R^2=\mathrm{id}$，且对一切 $X,Y\in\mathbb R^2$

$$\text{(F1)}\qquad \|\mathcal RX-\mathcal RY\|=\|X-Y\|,$$

因为 $\mathcal R$ 是线性正交映射（$R=\mathrm{diag}(1,-1)$，$R^\top R=I$）。
等价地 $\mathcal R z=\overline z$（复共轭）。

**圆上幅角**。对 $z\neq 0$ 记 $\arg z\in\mathbb R/2\pi\mathbb Z\simeq\mathbb S^1$。
由 $\mathcal Rz=\overline z$：

$$\text{(F2)}\qquad \arg(\mathcal Rz)\equiv-\arg z \pmod{2\pi}\qquad(z\neq 0).$$

（证明：$\overline z = |z|e^{-i\arg z}$。）

**圆距** $d_{\mathbb S}(a,b)=\min_{k\in\mathbb Z}|a-b+2k\pi|\ge 0$。直接验证两个恒等式：

$$\text{(F3)}\qquad d_{\mathbb S}(-a,0)=d_{\mathbb S}(a,0),$$

$$\text{(F4)}\qquad d_{\mathbb S}(-a,-b)=d_{\mathbb S}(a,b),$$

（因为 $|-a-(-b)+2k\pi|=|{-(a-b)}+2k\pi|=|a-b-2k\pi|$，且 $k\mapsto-k$ 是双射。）

**直径在等距下不变**。对任意集合 $P\subseteq\mathbb R^2$：

$$\text{(F5)}\qquad \operatorname{diam}(\mathcal RP)=\operatorname{diam}(P),$$

由 (F1)：$\sup_{X,Y\in P}\|\mathcal RX-\mathcal RY\|=\sup_{X,Y\in P}\|X-Y\|$；
且 $P$ 有界 $\iff\mathcal RP$ 有界（$\mathcal R$ 是同胚）。

**冻结模型对象**（与规范 §0 冻结链逐字一致，此处不重定义）：

$$\mathcal A_1=\{G:\ \|G\|\le 1800,\ 5<\|G\|\le 1500,\ d_{\mathbb S}(\arg G,0)\le\varepsilon\},$$

$$\mathcal C_{\rm rec}=\bigcap_{G\in\mathcal A_1}B\big(G,\max\{1000,\|G\|\}\big)\quad(\text{canonical: } S_1=0),$$

$$\mathcal A_1^{\rm dir}(S_2)=\{G\in\mathcal A_1:\|G-S_2\|>5\},\qquad
\overline\Theta_2^{\rm dir}(S_2)=\overline{\arg\big(\mathcal A_1^{\rm dir}(S_2)-S_2\big)},$$

$$\widehat\Theta_2^{\rm dir}(S_2)=\overline\Theta_2^{\rm dir}(S_2)\oplus[-\varepsilon,\varepsilon],$$

$$\mathcal K(S,\theta)=\{X:\ d_{\mathbb S}(\arg(X-S),\theta)\le\varepsilon\},\qquad
P_{\rm Q1}(S_2,\beta)=\mathcal K(S_1,0)\cap\mathcal K(S_2,\beta),$$

$$D_{\rm Q1}(S_2,\beta)=\operatorname{diam}P_{\rm Q1}(S_2,\beta),\qquad
Q(S_2)=\sup_{\beta\in\widehat\Theta_2^{\rm dir}(S_2)}D_{\rm Q1}(S_2,\beta)$$

（all-near 情形 $Q=0$；扩展值语义见规范 §1：存在无界 outcome 则 $\widetilde Q=+\infty$）。

---

## Lemma A1 — 第一次物理可行集镜像不变

**断言**：$\mathcal R(\mathcal A_1)=\mathcal A_1$。

**证明**。设 $G\neq O$（$\mathcal A_1$ 中 $G$ 满足 $\|G\|>5>0$）。三项约束逐一验证：

1. $\|\mathcal RG\|=\|G\|$：$\mathcal R$ 正交（(F1) 取 $Y=O$）。
2. 由 1，$\|\mathcal RG\|\le1800\iff\|G\|\le1800$ 且 $5<\|\mathcal RG\|\le1500\iff 5<\|G\|\le1500$。
3. $d_{\mathbb S}(\arg(\mathcal RG),0)\le\varepsilon\iff d_{\mathbb S}(\arg G,0)\le\varepsilon$：
   由 (F2)，$\arg(\mathcal RG)\equiv-\arg G$；由 (F3)，$d_{\mathbb S}(-\arg G,0)=d_{\mathbb S}(\arg G,0)$。

于是 $G\in\mathcal A_1\Rightarrow\mathcal RG\in\mathcal A_1$，即 $\mathcal R(\mathcal A_1)\subseteq\mathcal A_1$。
反向包含用对合性：$G\in\mathcal A_1\Rightarrow G=\mathcal R(\mathcal RG)$ 且 $\mathcal RG\in\mathcal A_1
\Rightarrow G\in\mathcal R(\mathcal A_1)$。故 $\mathcal R(\mathcal A_1)=\mathcal A_1$。$\square$

---

## Lemma A2 — 鲁棒接收域镜像不变

**断言**：$\mathcal R(\mathcal C_{\rm rec})=\mathcal C_{\rm rec}$。

**证明**。设 $X\in\mathcal C_{\rm rec}$，任取 $G'\in\mathcal A_1$。由 Lemma A1 取
$G=\mathcal RG'\in\mathcal A_1$。由 $X\in\mathcal C_{\rm rec}$ 与 $G$ 对应的球约束：

$$\|X-G\|\ \le\ \max\{1000,\|G-S_1\|\}=\max\{1000,\|G\|\}\qquad(S_1=O).$$

而由 (F1)：

$$\|\mathcal RX-G'\|=\|\mathcal RX-\mathcal RG\|=\|X-G\|\ \le\ \max\{1000,\|G\|\}=\max\{1000,\|G'\|\},$$

最后一步用 $\|G'\|=\|\mathcal RG\|=\|G\|$。由于 $G'\in\mathcal A_1$ 任意，
$\mathcal RX\in\mathcal C_{\rm rec}$，即 $\mathcal R(\mathcal C_{\rm rec})\subseteq\mathcal C_{\rm rec}$；
对合性给出反向包含。$\square$

---

## Lemma A3 — scenario 一一对应与 near/bearing 分支保持

对物理 scenario 集 $\mathcal S_{\rm phys}=\{(G,e):G\in\mathcal A_1,\ e\in[-\varepsilon,\varepsilon]\}$
定义镜像映射

$$\Phi:\mathcal S_{\rm phys}\to\mathcal S_{\rm phys},\qquad \Phi(G,e)=(\mathcal RG,\,-e).$$

**断言**：$\Phi$ 是良定义的双射（$\Phi^{-1}=\Phi$），且对任意 $S_2$：

$$\|S_2-G\|\le 5\iff\|\mathcal RS_2-\mathcal RG\|\le 5,$$

即 near/bearing outcome 类型在 $\Phi$ 下完全保持。

**证明**。$\Phi$ 良定义：$\mathcal RG\in\mathcal A_1$（Lemma A1），$-e\in[-\varepsilon,\varepsilon]$。
$\Phi^2=\mathrm{id}$：$\mathcal R(\mathcal RG)=G$，$-(-e)=e$。故 $\Phi$ 是双射。
分支保持：(F1) 取 $Y=S_2$、$X=G$：$\|\mathcal RS_2-\mathcal RG\|=\|S_2-G\|$，
故 $\|\cdot\|\le5$ 两侧同真假。$\square$

---

## Lemma A4 — 第二真实 bearing 与测得 bearing 的镜像

**断言**：设 $\|S_2-G\|>5$，$\alpha=\arg(G-S_2)$，$\beta=\alpha+e$；则镜像场景
$(\mathcal RG,-e)$ 在 $\mathcal RS_2$ 处满足

$$\alpha'=\arg(\mathcal RG-\mathcal RS_2)\equiv-\alpha \pmod{2\pi},
\qquad
\beta'=\alpha'-e\equiv-\beta \pmod{2\pi}.$$

**证明**。$\mathcal RG-\mathcal RS_2=\mathcal R(G-S_2)=\overline{G-S_2}\neq0$
（因 $\|G-S_2\|>5$），由 (F2) 得 $\alpha'=-\alpha$；再 $\beta'=(-\alpha)+(-e)=-\beta$。$\square$

---

## Lemma A5 — Q1 纯角锥镜像

**断言**：对任意 $S,\theta$（$S$ 任意，$\theta\in\mathbb S^1$）：

$$\mathcal R\big(\mathcal K(S,\theta)\big)=\mathcal K(\mathcal RS,-\theta).$$

特别地 canonical 第一锥满足 $\mathcal R\mathcal K(S_1,0)=\mathcal K(S_1,0)$（$S_1=O$）。

**证明**。设 $Y=\mathcal RX$，$X\in\mathcal K(S,\theta)$。则

$$\arg(\mathcal RY-\mathcal RS)=\arg\big(\mathcal R(Y-S)\big)\equiv-\arg(Y-S)\pmod{2\pi}$$

（$Y\ne S\iff X\ne S$；锥定义中 $X=S$ 的顶点情形单独处理：$X=S\in\mathcal K(S,\theta)$
且 $\mathcal RS\in\mathcal K(\mathcal RS,-\theta)$，顶点映顶点，无碍）。
于是由 (F4)：

$$d_{\mathbb S}\big(\arg(\mathcal RY-\mathcal RS),-\theta\big)
=d_{\mathbb S}\big(-\arg(Y-S),-\theta\big)
=d_{\mathbb S}\big(\arg(Y-S),\theta\big)\le\varepsilon,$$

即 $Y\in\mathcal K(\mathcal RS,-\theta)$。得 $\subseteq$；对合性给出相等。
canonical 情形：$\mathcal RS_1=S_1=O$，$-0=0$。$\square$

---

## Lemma A6 — Q1 定位区域与直径镜像

**断言**：对一切 $S_2,\beta$：

$$\mathcal R\,P_{\rm Q1}(S_2,\beta)=P_{\rm Q1}(\mathcal RS_2,-\beta),
\qquad
D_{\rm Q1}(\mathcal RS_2,-\beta)=D_{\rm Q1}(S_2,\beta),$$

且有界/无界状态保持：$P_{\rm Q1}(S_2,\beta)$ 有界 $\iff P_{\rm Q1}(\mathcal RS_2,-\beta)$ 有界。

**证明**。由 Lemma A5 与 $\mathcal R(A\cap B)=\mathcal RA\cap\mathcal RB$（$\mathcal R$ 双射）：

$$\mathcal R\,P_{\rm Q1}(S_2,\beta)
=\mathcal R\big(\mathcal K(S_1,0)\cap\mathcal K(S_2,\beta)\big)
=\mathcal K(\mathcal RS_1,0)\cap\mathcal K(\mathcal RS_2,-\beta)
=P_{\rm Q1}(\mathcal RS_2,-\beta)$$

（末步 canonical：$\mathcal RS_1=S_1$）。直径与有界性由 (F5)。$\square$

---

## Theorem A — 冻结 Q 目标镜像不变（正式定理）

**断言**：对一切 $S_2\in\mathbb R^2$（含扩展值三种情形）：

$$\boxed{\,Q(\mathcal RS_2)=Q(S_2).\,}$$

**证明**。分三种情形。

**情形 1（all-near）**。$\mathcal A_1\subseteq B(S_2,5)$
$\iff\forall G\in\mathcal A_1:\|G-S_2\|\le5$。由 Lemma A1/A3，
$G\mapsto\mathcal RG$ 是 $\mathcal A_1$ 的双射且 $\|\mathcal RG-\mathcal RS_2\|=\|G-S_2\|$，
故上式 $\iff\forall G'\in\mathcal A_1:\|G'-\mathcal RS_2\|\le5\iff\mathcal A_1\subseteq B(\mathcal RS_2,5)$。
两侧 $Q$ 均为冻结定义下的 $0$。$\checkmark$

**情形 2（无界 outcome，$\widetilde Q=+\infty$）**。由 Lemma A4/A6 的双射
$\beta\mapsto-\beta$：$\widehat\Theta_2^{\rm dir}$（见情形 3 第 1 步）被映到镜像测得集，
且 $P_{\rm Q1}(S_2,\beta)$ 无界 $\iff P_{\rm Q1}(\mathcal RS_2,-\beta)$ 无界（(F5) 与同胚性）。
故存在无界 outcome $\iff$ 镜像点存在无界 outcome，扩展值两侧同为 $+\infty$。$\checkmark$

**情形 3（正常 bearing 情形）**。逐层追踪冻结定义：

1. $\mathcal A_1^{\rm dir}(\mathcal RS_2)=\mathcal R\big(\mathcal A_1^{\rm dir}(S_2)\big)$：
   $G'\in\mathcal A_1^{\rm dir}(\mathcal RS_2)\iff G'\in\mathcal A_1,\ \|G'-\mathcal RS_2\|>5
   \iff\mathcal RG'\in\mathcal A_1,\ \|\mathcal RG'-S_2\|>5$（Lemma A1 + (F1)）
   $\iff G'=\mathcal RG,\ G\in\mathcal A_1^{\rm dir}(S_2)$。
2. $\overline\Theta_2^{\rm dir}(\mathcal RS_2)=-\,\overline\Theta_2^{\rm dir}(S_2)$：
   由 1 与 (F2)，$\arg\big(\mathcal A_1^{\rm dir}(\mathcal RS_2)-\mathcal RS_2\big)
   =-\arg\big(\mathcal A_1^{\rm dir}(S_2)-S_2\big)$（作为 $\mathbb S^1$ 子集）；
   取闭包与取负交换（取负是圆同胚）。
3. $\widehat\Theta_2^{\rm dir}(\mathcal RS_2)=-\,\widehat\Theta_2^{\rm dir}(S_2)$：
   $-(A\oplus[-\varepsilon,\varepsilon])=(-A)\oplus[-\varepsilon,\varepsilon]$。
4. 由 3 与 Lemma A6，替换变量 $\beta'=-\beta$（$\mathbb S^1$ 上的双射）：

$$Q(\mathcal RS_2)=\sup_{\beta'\in-\widehat\Theta_2}D_{\rm Q1}(\mathcal RS_2,\beta')
=\sup_{\beta\in\widehat\Theta_2}D_{\rm Q1}(\mathcal RS_2,-\beta)
=\sup_{\beta\in\widehat\Theta_2}D_{\rm Q1}(S_2,\beta)=Q(S_2).\ \square$$

**等价的 scenario 表述**（与规范 §6 的一致性）：同一双射 $\Phi$ 下，
对一切 $s\in\mathcal S_{\rm phys}$ 有
$\ell(\mathcal RS_2;\Phi s)=\ell(S_2;s)$：near 分支由 Lemma A3；bearing 分支由
Lemma A4（$\beta'=-\beta$）与 Lemma A6（$D_{\rm Q1}$ 不变，无界状态保持）。
对 $s$ 取上确界即得 $Q(\mathcal RS_2)=Q(S_2)$。两条路径等价。$\square$

---

## Corollary A — 半域优化严格等价（half-domain reduction）

**断言**：记 $\mathcal C_{\rm rec}^-=\mathcal C_{\rm rec}\cap\{(x,y):y\le0\}$（**闭**半平面），则

$$\boxed{\ \inf_{S_2\in\mathcal C_{\rm rec}}\widetilde Q(S_2)
=\inf_{S_2\in\mathcal C_{\rm rec}^-}\widetilde Q(S_2)=Q^\star.\ }$$

**证明**。$\mathcal C_{\rm rec}=\mathcal C_{\rm rec}^-\cup\mathcal R(\mathcal C_{\rm rec}^-)$：
任取 $X\in\mathcal C_{\rm rec}$。若 $y_X\le0$ 则 $X\in\mathcal C_{\rm rec}^-$；
若 $y_X>0$ 则 $\mathcal RX$ 的纵坐标 $-y_X<0$，且 $\mathcal RX\in\mathcal C_{\rm rec}$（Lemma A2），
故 $X=\mathcal R(\mathcal RX)\in\mathcal R(\mathcal C_{\rm rec}^-)$。
而由 Theorem A，$Q$（从而 $\widetilde Q$）在 $\mathcal R$-轨道上取常值，于是两个 infimum
都在同一值集上取：

$$\{\widetilde Q(X):X\in\mathcal C_{\rm rec}\}
=\{\widetilde Q(X):X\in\mathcal C_{\rm rec}^-\}\ \cup\ \{\widetilde Q(\mathcal RX):X\in\mathcal C_{\rm rec}^-\}
=\{\widetilde Q(X):X\in\mathcal C_{\rm rec}^-\}.$$

（$y=0$ 的点属于闭半域，不存在边界遗漏。）故两 infimum 相等，且按冻结定义都等于 $Q^\star$。$\square$

**推论（master 域合法性）**。对任意仅与 $y$ 无关对称性假设的有限松弛域
$\mathcal D\supseteq\mathcal C_{\rm rec}$ 与任意有限 scenario 集 $\mathcal S\subseteq\mathcal S_{\rm phys}$：

$$\inf_{S_2\in\mathcal D\cap\{y\le0\}}\ \max_{s\in\mathcal S}\ell(S_2;s)
\ \le\ \inf_{S_2\in\mathcal C_{\rm rec}^-}\widetilde Q(S_2)\ =\ Q^\star .$$

注意：**master 域 $\mathcal D$ 本身不需要镜像对称**——Corollary A 直接把
"在全 $\mathcal C_{\rm rec}$ 上取 inf" 约化为 "在闭半域上取 inf"，搜索域取
$\mathcal D\cap\{y\le0\}$ 只会使 inf 不减，不破坏下界合法性。
完整链条（Theorem B — Master Relaxation Lower Bound）：

$$L_{\rm rigorous}=\min_{\ell\in\mathcal L_{\rm live}}LB_{\rm Arb}(B_\ell)
\ \le\ \inf_{S_2\in\mathcal D\cap\{y\le0\}}M(S_2)
\ \le\ \inf_{S_2\in\mathcal C_{\rm rec}^-}\widetilde Q(S_2)
\ =\ Q^\star,$$

其中第一步由树重放逐叶给出（$M\ge LB(B)$ 逐盒成立，$\mathcal L_{\rm live}$ 覆盖
$\mathcal D\cap\{y\le0\}$），中间一步由 $\mathcal C_{\rm rec}\subseteq\mathcal D$ 与
$\mathcal S\subseteq\mathcal S_{\rm phys}$（故 $M\le\widetilde Q$），最后一步即 Corollary A。

---

## 适用范围与推广备注（scope statement）

1. 本证明只使用三条 canonical 事实：$S_1=O$（镜像轴过 $S_1$）、$\hat\theta_1=0$
   （镜像轴即第一示向线）、$\Omega=B(O,1800)$ 圆心在 $O$（$\|\mathcal RG\|=\|G\|$ 保持
   $\Omega$ 约束）。**certificate scope 因此锁定为 `canonical_center_case`**；
   一般 $(S_1,\hat\theta_1)$ 实例不自动继承本引理（除非 $\Omega$ 同样以 $S_1$ 为心，
   此时证明经旋转-平移归一后逐字成立——此推广不在本证书范围内，仅作备注）。
2. 本证明不依赖任何数值实验；`test_reflection_symmetry_of_Q` 等数值测试
   保留为 Theorem A 的反例回归（falsification only，规范 §36）。
3. 半域取**闭**半平面 $y\le0$：镜像不动点（$y=0$）无需二选一，避免开闭边界歧义。

---

## 机器可读断言

见 `src/q2/artifacts/formal/canonical_symmetry_lemma.json`
（`claims` 字段与本文各 Lemma/Corollary 一一对应）。
