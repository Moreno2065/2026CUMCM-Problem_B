# 2026 CUMCM B 题：Q3/Q4 在线定位清除策略与实验设计
## Gemini 答复审订版 v1.0

> **定位**：本文件不是“炫技方案清单”，而是把原 Gemini 答复中可用的思路保留，把不成立的几何结论、与题设不匹配的概率模型、错误计时和可疑文献全部剔除后，整理成可继续建模、编码和演练的技术底稿。  
> **依据**：2026 CUMCM 本科组 B 题题面、附件 1《模拟器使用说明》、附件 2《模拟器通信接口说明及编程指南》以及当前 Q1–Q4 执行报告。  
> **核心纪律**：能证明的不要调参；能由 Q1/Q2 在线求解的不要冻结成经验常数；Q3/Q4 的调参与消融只围绕真正的策略自由度展开。

---

# 0. 先给结论

这道题应明确拆成两种不同工作范式：

\[
\boxed{
Q1,Q2:
\text{数学模型}
\rightarrow
\text{算法实现}
\rightarrow
\text{数值验证/可视化}
}
\]

\[
\boxed{
Q3,Q4:
\text{保证性骨架}
\rightarrow
\text{可运行 baseline}
\rightarrow
\text{演练日志}
\rightarrow
\text{策略优化}
\rightarrow
\text{少量关键消融}
\rightarrow
\text{冻结}
\rightarrow
\text{正式测试}
}
\]

因此：

- Q1 基本没有“超参数调优”或“消融实验”；
- Q2 的第二检测点、基线长度、交会角主要是**决策变量**，优先由几何优化求解，而不是作为经验超参数反复试；
- Q3/Q4 才有真正需要演练筛选的在线策略参数；
- Q3/Q4 的代码应共享一个 runner / state machine / logging / geometry backbone，不能写成两套独立系统；
- 端到端 RL / POMDP / 深度策略网络暂不进入主线。

---

# 1. 先纠正原 Gemini 答复中的关键技术错误

## 1.1 一次测量不固定等于 6 秒

官方规则为：

\[
T_{\rm measure}
=
T_{\rm move}
+
T_{\rm switch}
+
5{\rm s}.
\]

只有本次 `/measure` 的频道与当前测向频道不同，才增加：

\[
T_{\rm switch}=1{\rm s}.
\]

如果频道不变，则本次原地测量只增加 5 s 虚拟时间。

因此，在同一位置顺序扫描 20 个频道，若先测当前频道，再遍历其余频道，动作耗时为：

\[
20\times 5+19\times 1
=
119{\rm s},
\]

而不是固定的 120 s。

`/clear` 的频道参数只指定目标频道，不会切换测向机当前频道。

---

## 1.2 “虚拟耗时”不能与 20 分钟程序运行时间混为一谈

检测 5 s、换频 1 s、移动距离/5 等均属于**虚拟世界时间**。

程序运行时间最长约 20 分钟属于现实 wall-clock 限制。一次 `/measure` 增加 5 s 虚拟时间，并不要求现实中等待 5 s。

因此：

> “停 10 次、每次扫 20 个频道，就把 20 分钟程序窗口全部耗光”

这个说法错误。

不过，大量扫描仍然会显著恶化题目要求统计的“平均定位清除时间”，所以减少不必要检测依然是核心优化目标，只是优化对象是**虚拟任务时间**，不是把 HTTP 调用当成现实睡眠计时。

---

## 1.3 “原点 + 4 个外围锚点即可完整覆盖 Q3”不成立

目标域半径为：

\[
R=1800{\rm m},
\]

全向源最小有效接收半径为：

\[
r_{\min}=1000{\rm m}.
\]

若只使用 4 个等角外围锚点，考虑目标圆边界上相邻锚点方向的角平分线。即便允许自由选择外围半径 \(a\)，到最近外围锚点的最小可能距离仍不小于：

\[
R\sin45^\circ
=
1800\times\frac{\sqrt2}{2}
\approx1272.8{\rm m}
>1000{\rm m}.
\]

因此 4 外围点无法给出完整覆盖保证。

5 个等角外围点同样有：

\[
1800\sin36^\circ
\approx1058.0{\rm m}
>1000{\rm m},
\]

仍不足。

所以原答复中的“四点/五点天网骨架”不得进入主线。

---

## 1.4 Q3 当前可用的是“中心 + 6 外围”的 7 点充分覆盖骨架

取中心：

\[
O=(0,0),
\]

以及 6 个等角外围点：

\[
S_k
=
a
\left(
\cos\frac{k\pi}{3},
\sin\frac{k\pi}{3}
\right),
\quad
k=0,\ldots,5.
\]

一个特别干净的鲁棒取值是：

\[
a=900\sqrt3
\approx1558.846{\rm m}.
\]

对整个半径 1800 m 目标圆盘，可以证明任意点到这 7 个检测点中最近一个的距离不超过：

\[
900{\rm m}.
\]

因此相对于最小接收半径 1000 m，具有：

\[
100{\rm m}
\]

的确定性几何余量。

这只是**一个充分构造**，并未证明 7 点在点数或路径长度意义下全局最优。

---

## 1.5 Q4 中“signal → no_signal”不能直接解释为穿过定向辐射边界

对定向源，`no_signal` 至少存在以下原因：

\[
\boxed{
\text{频道不存在/目标已清除}
\lor
d>R_{\rm eff}
\lor
\text{检测点不在 180^\circ 定向覆盖半平面内}
}
\]

而：

\[
R_{\rm eff}\in[1000,1500]{\rm m}
\]

且未知。

因此从两个离散测点：

\[
S_i:\text{direction},
\qquad
S_{i+1}:\text{no\_signal}
\]

不能推出机器狗一定跨越了发射半平面的边界，也不能“直接锁死定向法向量”。

此外，题目明确规定**移动过程中不能有效检测**。机器狗只能停止后调用 `/measure`，不存在连续监测意义上的“精确阶跃断点”。

所以原答复中的“狄拉克刀锋 / 精确切平面”不得作为 Q4 完成性证明。

如果未来已经由其它信息证明两个检测点都位于接收半径之内，则 signal/no-signal 转换可以成为**辅助的方向约束**，但不是主证书。

---

## 1.6 “1146 m 临界律”只能说明横向误差，不等于能直接清除

由单次示向度误差：

\[
|\epsilon|\le1^\circ
\]

可得到：若真实目标到检测点距离为 \(R\)，目标到测得中心射线的最大横向偏差不超过：

\[
\Delta_\perp
\le
R\sin1^\circ.
\]

当：

\[
R\le
\frac{20}{\sin1^\circ}
\approx1145.97{\rm m},
\]

确实有：

\[
\Delta_\perp\le20{\rm m}.
\]

但这只约束**横向偏差**。

单次 bearing 并不能告诉我们目标沿射线方向的距离。因此：

\[
\Delta_\perp\le20
\not\Rightarrow
\text{一次 `/clear` 必然命中}.
\]

原答复中“向前 100 m、偏 15° 再走 30 m 即足以锁定”的具体数字没有证明，不能冻结。

这个思想可以降级为后续实验支线：

> **Bearing-guided interception：沿方位方向前进，并利用沿途新观测持续收缩 set-membership 定位区域。**

是否触发清除，应由定位区域的几何保证决定，而不是固定走一个“经验微扰”。

---

## 1.7 Q1 的圆覆盖反例中锐角/钝角关系写反了

若三角形最长边为 \(AB\)，第三点为 \(C\)，以 \(AB\) 为直径作圆：

- \(\angle ACB=90^\circ\)：\(C\) 在圆上；
- \(\angle ACB>90^\circ\)：\(C\) 在圆内；
- \(\angle ACB<90^\circ\)：\(C\) 在圆外。

因此若要说明“直径等于定位区域直径的圆未必能覆盖定位区域”，可直接使用等边三角形：

\[
D=a,
\qquad
R_{\rm MEC}
=
\frac{a}{\sqrt3}
>
\frac a2.
\]

其中 \(R_{\rm MEC}\) 为最小包围圆半径。

原答复把钝角/锐角条件写反，必须修正。

---

# 2. 这题到底有哪些东西需要“调参”

原答复最大的问题之一，是把**决策变量、几何设计量、超参数**混在一起。

建议分成三类。

## 2.1 A 类：应由数学证明或题目边界决定，不作为调参对象

例如：

- Q3 保证性覆盖点集；
- Q4 保守完成性扫描点集；
- \(\pm1^\circ\) 测向误差；
- 1000–1500 m 有效接收半径边界；
- 20 m 清除半径；
- 5 m `near` 阈值；
- 5 m/s 移动速度；
- 5 s 检测时间；
- 1 s 换频时间。

这些不是“调参空间”。

---

## 2.2 B 类：应在线求解的决策变量，不宜粗暴冻结成经验常数

典型是 Q2/Q3/Q4 的第二检测点。

如果当前已有定位集合：

\[
\mathcal P_c,
\]

第二检测点 \(S_2\) 应由一个明确的几何准则产生，例如：

\[
S_2^\star
=
\arg\min_{S_2\in\mathcal C}
\sup_{\text{admissible observations}}
\operatorname{diam}
\left(
\mathcal P_c
\cap
\mathcal W(S_2,\theta_2,\pm1^\circ)
\right).
\]

或者，在 Q3/Q4 中只允许从机器狗已有任务路径上的候选点集合：

\[
\mathcal C_{\rm route}
\]

中选取，使得：

\[
\text{额外移动距离}\approx0.
\]

所以所谓“固定基线 300 m”“固定 90° 横移”更适合作 baseline，而不是最终方案。

---

## 2.3 C 类：真正值得用演练测试筛选的策略参数

例如：

- 什么时候做全频道扫描；
- 什么时候只扫描 active channels；
- 路径上的机会观测点最小间隔；
- 何时中断当前目标、转去处理另一个更成熟的定位目标；
- 一次机会测量预期减少多少定位不确定性才值得支付 5/6 s；
- Q4 中何时启动保守定向源兜底搜索；
- 搜索/清除任务的优先队列规则。

这里可以做小规模参数筛选。

但不建议立刻引入：

\[
\alpha T_{\rm move}
+
\beta T_{\rm detect}
-
\gamma {\rm Gain}
\]

然后同时调 \(\alpha,\beta,\gamma\)。

比赛里更稳的是：

- 分层规则；
- lexicographic priority；
- 少量可解释阈值；
- 离散候选菜单。

原则：

\[
\boxed{
\text{Robust Good}
>
\text{Fragile Best}
}
\]

---

# 3. Q3 主线：全向源条件下的可证明在线搜索清除

## 3.1 每个频道维护显式状态

建议频道状态机至少包含：

```text
UNKNOWN
DETECTED
LOCALIZING
CLEARED
CERTIFIED_ABSENT
```

每个频道维护：

```text
channel_id
status
bearing_observations[]
no_signal_points[]
localization_polygon
last_seen_position
planned_observation_candidates[]
clear_attempts[]
```

不要使用“概率很低所以当不存在”这种无法证明的状态。

---

## 3.2 Q3 的确定性完成证书

全向源满足：

\[
R_{\rm eff}\ge1000{\rm m}.
\]

如果对某频道 \(c\)，在位置 \(S\) 检测得到：

```text
no_signal
```

则：

\[
B(S,1000)
\]

内不存在该频道的未清除全向干扰源。

对该频道累计：

\[
\mathcal N_c
=
\{S_i:
\text{measure}(S_i,c)=\text{no\_signal}\},
\]

得到确定性排除区域：

\[
\mathcal E_c
=
\bigcup_{S_i\in\mathcal N_c}B(S_i,1000).
\]

若：

\[
\Omega
\subseteq
\mathcal E_c,
\]

则：

```text
status = CERTIFIED_ABSENT
```

严格停止条件为：

\[
\boxed{
\forall c\in\{1,\ldots,20\},
\quad
c=\text{CLEARED}
\;\lor\;
c=\text{CERTIFIED\_ABSENT}
}
\]

另外，因为源总数最多 16 个：

\[
N_{\rm cleared}=16
\Rightarrow
\text{立即完成}.
\]

这条 16 源早停是零风险优化。

---

## 3.3 7 点覆盖不是主巡逻路线，而是兜底证书

完整从零执行 7 点全频道扫描会产生较大虚拟时间，所以它不应被机械地当成固定主路线。

更合理的是：

> 搜索、定位、清除过程中，所有 `no_signal` 本身都在给频道累积排除证书。

最终只补访问尚未覆盖的必要锚点。

因此 Q3 的优化目标可以理解为：

\[
\boxed{
\text{让正常任务轨迹尽可能顺便完成最终覆盖证书}
}
\]

而不是：

> “先正常搜索，最后再额外走完整 7 点扫描。”

---

# 4. 最值得保留的 Gemini 思路：机会式基线复用

这一条值得进入主线候选。

## 4.1 核心思想

机器狗为目标 A 执行移动任务：

\[
S_i\rightarrow S_j,
\]

这段位移天然改变了对其它未清除频道 B、C、D 的观测几何。

因此，不必总为每个频道专门执行：

\[
\text{detect}
\rightarrow
\text{专门横移}
\rightarrow
\text{第二次 detect}.
\]

可以改成：

\[
\boxed{
\text{已有任务移动}
+
\text{沿途停点机会观测}
}
\]

即：

> **Opportunistic Baseline Reuse / 任务路径复用的机会式交会**

---

## 4.2 它并不是“零成本”

机会观测仍会产生：

\[
5{\rm s}
\]

检测时间，以及可能的：

\[
1{\rm s}
\]

换频时间。

真正接近于零的是：

\[
\text{额外基线移动成本}.
\]

因此论文不要写“零成本交会”，而应写：

> 通过复用既定任务位移形成测向基线，减少专门为交会产生的附加移动距离。

---

## 4.3 如何决定某个沿途点值不值得测

对于频道 \(c\)，当前定位区域为：

\[
\mathcal P_c.
\]

对未来任务路线上的候选停点 \(S\)，估计其最坏情况下的定位收缩收益：

\[
\Delta D_c(S)
=
D(\mathcal P_c)
-
\sup_{\theta\in\Theta_{\rm admissible}}
D\bigl(
\mathcal P_c
\cap
\mathcal W(S,\theta,\pm1^\circ)
\bigr).
\]

如果候选点本来就在路径上，则主要付出的是 5/6 s 测量成本。

工程实现时不必一开始求连续全局最优，可以：

1. 从未来路线离散出若干候选停点；
2. 用 Q2 几何评价函数打分；
3. 选收益足够高的点；
4. 不为了“完美 90° 交会”专门绕远路。

这是 Q2 向 Q3/Q4 最自然的模块复用方式。

---

# 5. 清除触发条件：不要只看定位多边形直径

`/clear` 能保证成功的条件是：

> 存在一个清除位置 \(x\)，使真实源无论在当前定位可行域的哪里，都距 \(x\) 不超过 20 m。

若当前定位区域为：

\[
\mathcal P_c,
\]

应计算其**最小包围圆**：

\[
{\rm MEC}(\mathcal P_c).
\]

若：

\[
R_{\rm MEC}(\mathcal P_c)\le20{\rm m},
\]

则以最小包围圆圆心作为 clear 点，可给出确定性清除保证。

所以：

\[
\boxed{
R_{\rm MEC}\le20
}
\]

比“定位区域直径足够小”更直接。

特别注意：

\[
D(\mathcal P_c)\le40
\]

对任意二维集合并不自动保证存在半径 20 m 的覆盖圆。

如果 `/measure` 返回：

```text
near
```

则已知机器狗与该源距离不超过 5 m，可以直接在当前位置尝试 `/clear`。

---

# 6. 频道调度：保留 Active / Dormant 思想，但不用“熵”这个词硬包装

原 Gemini 的频道剪枝方向是对的，但“信道熵修剪”并没有必要。

建议用更准确的状态调度。

## 6.1 三类集合

```text
CLEARED:
    已清除频道，永久删除

ACTIVE:
    已检测到，当前正在定位/等待机会观测的频道

UNKNOWN:
    尚未发现且尚未完成无源证书的频道
```

Q3 中还可加入：

```text
CERTIFIED_ABSENT:
    已完成全域无源证明
```

---

## 6.2 扫频原则

**骨干/证书节点：**

优先扫描所有 `UNKNOWN` 频道，使本次停点同时积累发现机会与 no_signal 排除证据。

**目标定位支线：**

优先只测当前需要更新的 `ACTIVE` 频道，不机械全扫 20 个频道。

**清除后：**

频道立刻进入 `CLEARED`，不再检测。

这样能直接减少：

- 5 s 检测动作；
- 1 s 换频道动作；
- 不必要的日志与策略分支。

---

## 6.3 不允许的错误剪枝

不能执行：

```text
原点 no_signal
→ 把该频道永久休眠
→ 后面不再扫描
```

因为源可能存在，只是距离原点超过其有效接收半径。

任何永久排除都必须来自：

\[
\text{完整的空间证书},
\]

而不是单点经验。

---

# 7. Q4：定向源下必须重建“完成证书”

Q4 最关键的变化不是“定位公式变了”，而是：

\[
\boxed{
\text{单个 no\_signal 不再产生圆形空域证书}
}
\]

因此 Q3 的停止逻辑不能直接复制。

---

## 7.1 一旦检测到定向源，后续定位仍可大量复用 Q1/Q2/Q3

只要某个定向频道在一个测点返回：

```text
direction
```

就仍然得到：

\[
\pm1^\circ
\]

的 bearing 约束。

后续可以继续：

- 定位多边形求交；
- Q2 第二观测点设计；
- 机会式基线复用；
- MEC 清除判定；
- 动态目标调度。

而且 `/clear` 成功条件只看 20 m 距离，与定向源朝向无关。

因此 Q4 不是重写整个系统，而是：

\[
\boxed{
\text{Q3 backbone}
+
\text{新的“发现/完成证书层”}
}
\]

---

## 7.2 一个可继续证明的保守方向：三角格点 hitting certificate

定向源有效覆盖角为 180°，可视为以源位置 \(G\) 为顶点的某个闭半平面，同时还受：

\[
R_{\rm eff}\ge1000
\]

的距离限制。

考虑边长：

\[
s\le1000{\rm m}
\]

的等边三角网格。

如果对任意目标位置 \(G\in\Omega\)，都存在一个网格三角形：

\[
G\in
{\rm conv}\{V_1,V_2,V_3\},
\]

且三个顶点均被纳入扫描点集，则：

\[
\|G-V_i\|\le s\le1000.
\]

同时，由：

\[
G\in{\rm conv}\{V_1,V_2,V_3\},
\]

可以推出：

> 对任何经过 \(G\) 的闭半平面，三个顶点中至少有一个位于该半平面内。

否则三个顶点全部位于另一侧开半平面，其凸包不可能包含 \(G\)。

这意味着：

> 对任意 180° 定向方向，至少有一个三角形顶点既在覆盖半平面中，又距源不超过 1000 m。

因此该顶点理论上应能检测到源。

这是目前比“signal 消失就是边界”更有希望形成**确定性 Q4 兜底证书**的方向。

---

## 7.3 但 Q4 三角格点还不能直接宣布冻结

正式冻结前仍需关闭：

- 目标恰落在格点/网格边上的退化情况；
- 有限目标圆盘边界处需要加入多少域外格点；
- 是否需要一层外扩邻接点以处理格点退化；
- 扫描点的有限集合如何自动生成；
- 对任一 \(G\in\Omega\) 的覆盖/凸包充分性如何由独立 verifier 数值检查；
- 点数与总路径长度；
- 是否有比 \(s=1000\) 更稀疏但仍可证明的构造。

因此当前状态应写：

```text
Q4 triangular-lattice deterministic fallback:
CORE SUFFICIENCY IDEA = PROMISING
FINITE CONSTRUCTION = NOT YET FROZEN
```

不要像原 Gemini 那样看到一个漂亮几何直觉就直接宣布“绝杀”。

---

# 8. Q3/Q4 的任务调度：先用可解释规则，不急着 POMDP

可以把当前所有未完成任务放进优先队列：

```text
TASK_DISCOVER_UNKNOWN
TASK_REFINE_ACTIVE_CHANNEL
TASK_CLEAR_READY_TARGET
TASK_COMPLETE_CERTIFICATE
```

优先级建议采用分层规则，而不是一上来调三四个连续权重。

例如：

```text
1. 若某频道已满足 MEC <= 20 m：
       优先比较其清除点绕路成本，近则立即清除

2. 若下一既定路线点能显著改善多个 ACTIVE 频道：
       优先机会观测

3. 若未知频道的确定性覆盖证书仍有大缺口：
       向兼具探索与证书价值的骨干点移动

4. Q3 收尾：
       补齐 7 点证书缺口

5. Q4 收尾：
       启动冻结后的定向源保守 completion route
```

等 baseline 跑通，再根据演练日志决定是否需要更复杂的插入重规划或 TSP 层。

---

# 9. 调参与消融：只做真正值钱的

Q3/Q4 工作量已经很大，不建议比赛里跑“科研全家桶”。

## 9.1 调参只筛真正的策略自由度

可考虑筛：

- opportunistic measurement 最小收益阈值；
- full-scan 的触发位置/频率；
- active target 的优先级规则；
- 是否允许一次路线同时服务多个频道；
- Q4 何时切换到保守 completion mode。

Pilot 可以：

- 少案例；
- 低复杂度；
- 自建 synthetic simulator 固定案例；
- 小离散参数菜单。

不要做几十上百 trial 的 HPO，除非运行成本极低且主线已经完全稳定。

---

## 9.2 正文优先保留两个 Q3 消融

### Ablation A：频道剪枝

\[
\text{All-Unresolved Full Scan}
\quad vs \quad
\text{State-Aware Channel Scheduling}
\]

指标：

- 总检测次数；
- 总换频次数；
- 检测/换频虚拟时间；
- 总任务时间；
- 清除率。

### Ablation B：专用交会移动 vs 机会式基线复用

\[
\text{Dedicated Baseline Motion}
\quad vs \quad
\text{Opportunistic Baseline Reuse}
\]

指标：

- 额外定位移动距离；
- 每源平均观测次数；
- 定位到 MEC \(\le20\) 的时间；
- 总任务时间；
- 清除率。

---

## 9.3 Q4 如果时间允许，再加一个关键消融

\[
\text{Naive Q3 Adaptation}
\quad vs \quad
\text{Directional-Aware Completion Strategy}
\]

这里最重要的不是把时间再降 3%，而是验证：

\[
\text{clearance ratio}
\]

是否能稳定保持在 100%。

---

## 9.4 正式对照不要依赖“官方随机演练恰好一样”

官方演练测试随机生成案例，并未给出可以固定隐藏 case seed 重放的保证。

因此真正 matched-case 的消融应优先在自建 synthetic simulator 中完成：

```text
same source count
same channels
same positions
same R_eff
same directional angles
same deterministic measurement-error field
same case seed
```

官方演练用于：

> **外部行为验证与真实性检查**

而不是假装成完全 matched 的实验台。

---

# 10. 这题需要哪些 Figure

图仍然重要，但每张图都必须承担论证职责。

## 10.1 Q1：交会定位几何图

内容：

- 检测点 \(S_1,S_2,\ldots\)；
- 每个示向度的 \(\pm1^\circ\) 可行楔形；
- 求交得到的定位多边形；
- 最远点对；
- 定位区域直径；
- 必要时叠加最小包围圆。

作用：

> 一张图交代 Q1 的集合定义、直径与后续 clear guarantee 的区别。

---

## 10.2 Q2：第二检测点候选区域图

不是“参数敏感性图”，而是**决策空间图**。

可绘制：

\[
S_2=(x,y)
\rightarrow
J(S_2)
\]

其中 \(J\) 为预先冻结的 worst-case 定位质量指标。

图中标出：

- 第一检测点；
- 当前 bearing cone；
- 劣质近共线区域；
- 高质量交会区域；
- 若需要，叠加等移动距离线；
- 最终推荐候选带。

---

## 10.3 Q3：完整一局轨迹 + 证书积累图

建议用一张高信息密度主图表达：

- 半径 1800 m 目标圆；
- 探索/证书骨干点；
- 机会观测停点；
- 清除机动；
- 已清除目标；
- 典型 2–3 个频道的定位区域收缩；
- 最终 Q3 证书覆盖状态。

重点不是把所有 bearing 线画成毛线球，而是让评委看清：

\[
\text{移动任务}
\rightarrow
\text{顺路观测}
\rightarrow
\text{定位收缩}
\rightarrow
\text{清除}
\rightarrow
\text{证书收口}.
\]

---

## 10.4 Q4：定向源完成性几何图

如果三角格点证书最终成立，推荐画：

- 一个未知定向源；
- 任意 180° 覆盖半平面；
- 包含源位置的网格三角形；
- 三个顶点；
- “任何半平面至少命中一个近邻顶点”的几何关系。

这比“信号刀锋”漂亮得多，而且是真的数学。

---

## 10.5 成本分解

用堆叠条形图而不是饼图，分解：

- movement；
- measurement；
- channel switching；
- optical localization；
- clearing。

同时把 baseline 与 proposed 放在一起比较。

这样可以直接回答：

> 我们的方法到底省在了哪里？

---

## 10.6 随机案例稳定性

若有足够演练：

- clearance ratio；
- average localization-clearance time；
- total virtual time；
- movement distance。

推荐使用：

- boxplot；
- ECDF；
- paired dot plot（matched synthetic cases）。

不建议双 Y 轴“清除率 + 时间”硬塞在一张图里。

---

# 11. ML / DL / POMDP / FIM 应该放在哪个位置

## 11.1 端到端 ML / RL 暂不进入主线

主要原因不是“神经网络不高级”，而是本题具有：

- 明确几何误差界；
- 强硬完成性要求；
- 单局目标数较少；
- 在线策略需要严格停止；
- 比赛时间有限。

主线更适合：

\[
\boxed{
\text{Robust Geometry}
+
\text{Deterministic Completion}
+
\text{Rule-based / Search-based Online Scheduling}
}
\]

RL 可以作为未来扩展，不值得现在承担交付风险。

---

## 11.2 POMDP / Bayesian entropy 只能作为概念性参考

题目没有给出：

- 测向误差概率分布；
- 不同位置误差独立性；
- 源位置先验；
- 定向角先验。

只给：

\[
\epsilon(S)\in[-1^\circ,1^\circ],
\]

以及同一地点误差在一段时间内固定。

因此本题主模型天然更匹配：

\[
\boxed{
\text{set-membership / bounded-error robust geometry}
}
\]

如果为了探索性支线人工设置 Bayesian prior，必须明确写成：

> scenario model / heuristic belief

不能把它当成题面保证。

---

## 11.3 FIM / GDOP 可以做理论旁证，但不应替代 Q2 的有界误差模型

经典 bearings-only literature 的确说明：

> 观测者机动和交会几何显著影响定位精度。

但 FIM/CRLB 依赖具体随机噪声模型。

本题已经明确给出的是：

\[
\pm1^\circ
\]

确定性有界误差。

因此正文更自然的主线仍然是：

\[
\text{worst-case localization region}.
\]

FIM/GDOP 最多作为 related interpretation：

> “良好的交会角与经典 bearings-only 几何精度理论一致。”

不要为了显得现代，把题目硬改造成另一个统计模型。

---

# 12. 可安全使用的文献

以下条目已重新核验，可作为背景文献候选。

### Bearings-only 观测机动

Yaakov Oshman, Pavel Davidson.  
**Optimization of Observer Trajectories for Bearings-Only Target Localization.**  
IEEE Transactions on Aerospace and Electronic Systems, 35(3): 892–902, 1999.  
DOI: 10.1109/7.784059.

用途：

> 说明观测者运动可以改善 bearings-only target localization 的可观测性/估计性能。

注意：

> 该文采用 FIM 优化框架，不应直接替代本题的 \(\pm1^\circ\) bounded-error set model。

---

### GDOP 几何背景

Nadav Levanon.  
**Lowest GDOP in 2-D Scenarios.**  
IEE Proceedings - Radar, Sonar and Navigation, 147(3): 149–155, 2000.  
DOI: 10.1049/ip-rsn:20000322.

用途：

> 作为“观测几何影响定位精度”的补充背景。

---

### 信息采集路径规划

Geoffrey A. Hollinger, Gaurav S. Sukhatme.  
**Sampling-based Robotic Information Gathering Algorithms.**  
The International Journal of Robotics Research, 33(9): 1271–1287, 2014.  
DOI: 10.1177/0278364914533443.

用途：

> 作为“信息获取与运动成本联合考虑”的 general background。

注意：

> 原 Gemini 答复将该文的标题、期刊、卷页均写错，原引用不可使用。

---

### Source Localization 的信息路径规划示例

Li Kexin, Mandar Chitre.  
**Informative Path Planning for Source Localization.**  
可检索到作者公开的 2019 两页论文版本。

该工作使用：

- 源位置概率分布；
- Bayesian update；
- entropy / information gain。

用途：

> 只适合说明信息路径规划这一研究方向存在。

注意：

> 它依赖明确概率模型，与本题的 bounded-error 设定不同，不建议作为主模型直接照搬。

---

## 不再使用的可疑引用

原 Gemini 答复中的：

> Lan & Schwager (2016), *Planning informative trajectories for multiple targets using generalized mutual information*, Automatica 72, 19–31

当前无法可靠核验为该作者/题名/期刊组合。

在找到 DOI 或正式出版页面之前：

\[
\boxed{
\text{不要引用}
}
\]

---

# 13. 推荐的 Q3/Q4 统一工程结构

```text
robot/
├─ api_client.py
├─ crash_recovery.py
├─ logger.py
├─ state.py
│
├─ geometry/
│  ├─ bearing_wedge.py
│  ├─ polygon_intersection.py
│  ├─ diameter.py
│  ├─ minimum_enclosing_circle.py
│  └─ q2_candidate_score.py
│
├─ policy/
│  ├─ channel_scheduler.py
│  ├─ opportunistic_measure.py
│  ├─ target_scheduler.py
│  ├─ q3_completion.py
│  └─ q4_completion.py
│
├─ verifier/
│  ├─ q3_cover_verifier.py
│  ├─ q4_grid_verifier.py
│  ├─ geometry_toy_cases.py
│  └─ log_replayer.py
│
└─ run.py
```

Q3/Q4 共用：

- API；
- 请求幂等；
- 位置/频道状态；
- bearing 几何；
- 定位区域；
- MEC；
- clear；
- 日志；
- 轨迹数据；
- 任务队列。

只替换/扩展：

```text
completion logic
discovery guarantee
directed-source handling
```

---

# 14. 最小可用主线

如果比赛时间开始吃紧，主线应砍成下面这样。

## Q3

\[
\boxed{
\text{7点保证骨架}
+
\text{频道状态机}
+
\text{Q1定位}
+
\text{Q2候选点}
+
\text{机会式基线复用}
+
\text{MEC清除}
}
\]

完成性：

\[
\text{CLEARED}
\lor
\text{CERTIFIED\_ABSENT}.
\]

---

## Q4

\[
\boxed{
\text{Q3通用backbone}
+
\text{定向源独立completion route}
}
\]

不能把 Q3 的单点 no_signal 证书直接搬过去。

如果 Q4 高级在线策略来不及：

> 宁可采用一个较保守、可证明的定向源扫描兜底，也不要交一个平均很快但偶尔漏最后一个源的 fancy heuristic。

---

# 15. 目前最值得实验的两个增强

如果只能选两个实验增强，我会选：

## A. Opportunistic Baseline Reuse

目标：

\[
\downarrow
\text{dedicated localization travel}.
\]

这是最可能显著减少移动时间、同时又高度 problem-specific 的机制。

---

## B. State-Aware Channel Scheduling

目标：

\[
\downarrow
\text{unnecessary measurements and channel switches}.
\]

它与确定性 completion certificate 兼容，不牺牲最终全清保证。

---

其它高级东西：

- dynamic TSP；
- MCTS；
- RL；
- POMDP；
- Bayesian HPO；
- “定向边界刀锋”；

全部排在这两项之后。

---

# 16. 当前建议的证据链

最终论文里，与其堆方法名，更应该形成：

\[
\boxed{
\text{Q1 bounded-error geometry}
}
\]

\[
\Downarrow
\]

\[
\boxed{
\text{Q2 robust observation-point design}
}
\]

\[
\Downarrow
\]

\[
\boxed{
\text{Q3 deterministic discovery/completion}
+
\text{opportunistic localization}
}
\]

\[
\Downarrow
\]

\[
\boxed{
\text{Q4 directional completion extension}
}
\]

再用：

\[
\boxed{
\text{synthetic matched-case ablation}
+
\text{official rehearsal validation}
+
\text{formal-test logs}
}
\]

把证据闭合。

这个叙事比：

> FIM + POMDP + 信息熵 + TSP + RL + 贝叶斯优化

更克制，也更贴题。

---

# 17. 一句话版本

> **Q1/Q2 用有界误差几何把“定位”做硬；Q3 用确定性覆盖保证不漏全向源，再靠机会式基线复用和频道剪枝压时间；Q4 不把 no_signal 当空域证书，而重新建立针对 180° 定向覆盖的完成性扫描结构。能推导的别调，真正的策略自由度才交给演练数据。**

比赛现场版：

> **别把一个能证明的几何题，调成一个靠运气活着的超参数动物园。**
