# 差分交叉比对小结 —— 三份彼此独立的「源 vs 移植」行为等价验证

> 目的：把**三份由不同作者、不同方法、不同覆盖面**的差分放在一起对齐，给出共同结论、逐项口径差异、以及**仍然没有被覆盖的边界**。
> 本文件由 captain 汇总；三份差分的原始产物各自独立、未经改写。

## 1. 结论（三者一致）

**在各自覆盖的用例上，`Q3_Q4_V3` 的源引擎与 `absorbed/` 的移植引擎行为逐位等价**：返回 JSON 归一化后逐字节相同、动作序列（含 `/enter`、`/exit`）整表相同、虚拟时长精确相等、清除集合相同。

这条结论同时覆盖了吸收件主动删掉的 8 个「脚手架」文件（v4 `bridge_v4`、v3 `bridge`/`strategy_v3`/`experiments_v3`、v2 `base`/`candidate`/`experiment`、v1 `offline_world`）——其中 **6 个整体缺失、`bridge_v4.py` 与 `base.py` 是裁剪派生**（65/38 行 vs 源 17/17 行，sha 不同）。源侧加载它们、移植侧不加载，输出仍逐位相同 ⇒ **它们对 `solve()` 路径无行为影响**。这与 `verification/oracle_callgraph.py` 的「名字级可达性 `zero_call=40 / missing_defs=0`」构成**两条独立方法互证**。

## 2. 三份差分逐项对照

| 维度 | 轨道 1 · `differential_check.py` | 轨道 2 · `oracle_q3_mock_diff.py` | 轨道 3 · `captain_differential_probe_q3/q4.py` |
|---|---|---|---|
| 作者 | interface-scout（**未写过 `absorbed/` 任何一行**） | verifier（同样未写过实现） | captain（**代登者**，非实现者） |
| 进程模型 | 同进程双引擎 | **源/移植各起独立进程** | 同进程双引擎 |
| mock 来源 | 自研 | 自研（独立于轨道 1 的 mock） | 自研 |
| 用例数 | **8**（Q3 4 + Q4 4） | **2**（**仅 Q3**） | **2**（Q3 1 + Q4 1） |
| 用例参数 | n=10/12/14/16；误差场 zero/sine/plus/minus | 12 源环（半径 600 m）+ blind 恒无信号 | n=12；确定性几何 |
| 结果 | Q3 动作 133/124/141/131；Q4 281/281/278/255；**JSON 逐字节相等 8/8** | mock：两侧 `ok / 110 actions / 550.0 s / 12 clears`；blind：两侧同为 `RuntimeError / 140 / 700.0` | Q3 `128/128 动作, virtual 2612.076878`；Q4 `239/239, virtual 5407.076877`，cleared 集合与 strategy 名相同 |
| 反空转设计 | **有**：先断言 4 个入口分属两棵树、函数对象不同；absorbed 侧 `sys.modules` 无脚手架名 | 有：两侧入口来自不同文件/不同树 | 部分：按绝对路径分别导入两棵树 |
| 反证控制（负控） | **有**：seed101 vs seed909 必须被判**不等** → 实测检出差异（首个不同下标 5、长度 133 vs 140、JSON 路径 `$.average_virtual_seconds_per_cleared_source`） | blind 用例保证比对器对「全无信号」这一极端世界同样成立 | 无独立负控；但**由 verifier 亲自复跑并逐项核对**，数字与其自身轨道交叉 |
| 锁定参数来源 | **直接读源包 v4 锁**，并断言 `absorbed.locked.LOCKED_PARAMETERS == 源 v4 锁` → True | 不涉及（Q3 无锁） | 直接读源包 v4 锁（探针内断言 36 项） |
| 复跑命令 | `python -X utf8 verification/differential_check.py`（→ `VERDICT: PASS`，exit 0） | `python -X utf8 verification/oracle_q3_mock_diff.py` | `python -X utf8 verification/captain_differential_probe_q3.py` / `_q4.py` |

**独立性加权**（如实标注，不拔高）：
- 轨道 1、2 的作者都**没有实现过 `absorbed/` 的代码**，是标准的第三方验证；
- 轨道 3 的作者（captain）虽然是**任务代登者**（`t2/t3/t4` 由我结案），但**不是 `absorbed/` 代码的作者**；且它的每个数字都由 **verifier 亲自重跑复现**（Q3 `128/128`、`2612.076878`；Q4 `239/239`、`5407.076877`），因此该轨道以「**captain 编写 + verifier 执行**」的形式进入证据链，而不是自证。

## 3. 仍然**没有被覆盖**的边界（务必与结论同读）

1. **世界是构造的**：三份差分全部使用内存构造的确定性世界（非官方模拟器）；结论只覆盖「同输入 ⇒ 同输出」，**不代表业务口径或官方分布下的正确性**。
2. **动态等价只覆盖锁定配置**：用例走的是锁定参数（Q3 `q3_joint_search_clear_route_v5` 的 21 项；Q4 `q4_21station_exact_route_v4` / `quarter12` 的 36 项）与这些用例经过的分支；其他参数分支（`opportunistic` / `drop_sites` / `cumulative_points` / `route='sequential'` 等）的等价性依据是各自 `MANIFEST.md` 的**逐行一致（静态）**，本文件不重复主张。
3. **Q4 没有跨进程复核**：跨进程形式只在 Q3 上做过（轨道 2）。
4. **官方 `--sim http` 通路未被任何差分覆盖**（该项仍是开放项 F-F 的一部分）。
5. **环境限定**：确定性在同机、同 numpy/scipy 下取得；mock 为纯浮点运算，且被测包内相关集合只含小整数、迭代处均走 `sorted()`，"无随机"这一前提在本包成立（由 q3-porter 记录其 `MANIFEST.md` §7 V7）。

## 4. 差异不冲突的解释

三份差分的**数值不同**（如动作数 128 vs 133 vs 110）**不是矛盾**：它们用的是**不同的 mock 世界**（源数、半径、误差场、空频道集合各不相同）与不同的用例规模，因此各局的动作数与虚拟时长本就不同。可比的是**同一份差分内部「源 vs 移植」的一致性**，这一点三份都成立。

## 5. 结论与应用

- 吸收件在**行为层面**是可替代的：删掉 8 个脚手架文件没有改变 `solve()` 的输出。
- 若要继续提高置信度，下一步应按优先级补：① 官方 `--sim http` 端到端（同时闭合 F-F 的两条）；② Q4 的跨进程复核；③ 其余参数分支的抽样差分。
