# absorbed/q3_v5 — MANIFEST（Q3 正式 SOTA solver 自包含移植）

源包（只读）：`D:\CUMCM2026\src\Q3_Q4_V3`
目标包：`D:\CUMCM2026\src\q3+q4_v2`
本目录写入者：q3-porter（范围 `absorbed\q3_v5\**`）。**q3-porter 本人未修改任何生产文件**（production.py / run.py / runtime.py / compare.py / recommended.py / baseline/**）；本目录内所有产出均由 q3-porter 写入，最后写入时间见 §9 时间线。

> ⚠ **关于「生产路径零改动」的限定（勿再无条件引用）**：`run.py` 在**吸收阶段之后**被修改过一次 —— **修改者：captain；依据：用户明确指令**（授权原文「把 geometry 修好 / 修 --policy geometry」），范围**仅 `run.py`**，书面登记见 `verification\production_change_authorization.json`（`authorized_by: "user"`、`authorized_scope: ["run.py"]`；其余四个点名文件与 `baseline/**`、`absorbed/**` 列入 `still_forbidden`）。现状 68 547 B / 1127 行 / mtime 2026-09-13 12:59:51 / sha256 `def842f4ae28…`（前像 `14c479355e15…`，66 791 B）。因此「生产路径零改动」只在**吸收阶段**成立；本 MANIFEST 只能声明「**q3-porter 未改动任何生产文件**」，不能声明全队零改动。verifier 门禁 `[FAIL] MUST/f` 即由该变更触发，授权后按精确 `(path, before, after)` 匹配消费。详见 §9。

## 0. 结论摘要

- Q3 正式采用的 solver = `q3_optimizer_v5.solve_optimized_v5(client, progress=None)`，`VERSION='q3_joint_search_clear_route_v5'`。
- 递归读 import 得到闭包 **9 个源文件 / 1308 行**，全部 vendored 到本目录；闭包内每个模块级 import 都指向本包内部。
- 第三方依赖仅 **numpy + scipy**（`scipy.optimize.linprog` / `brentq` / `minimize`）。无 numba、无 shapely、无 socket/urllib/requests、无文件读取。
- 本包不再注入 `sys.path`，也不做任何全局状态修改；**全部 import 为显式包内相对 import**，不经过 `sys.path` 解析，故与目标包顶层模块不会同名冲突。
- 状态：**静态核对与运行期验证均通过**（环境更正后 shell 实测，全部 `EXIT=0`）：9 个模块导入成功且 `__file__` 全在包内、VERSION/参数/签名与源逐一相等、16 项数值输出逐位相同、整局 `solve()` 在相同 mock client 下结果 JSON 完全一致。详见 §7（已执行）与 §7b（仍未覆盖）。

## 1. 文件清单（源路径 / 源行数 / 目标行数）

| 目标文件（本目录） | 源绝对路径 | 源行数 | 目标行数 | 改动性质 |
|---|---|---|---|---|
| `__init__.py` | （新增，无源） | — | 21 | 包声明 + 再导出契约 |
| `q3_optimizer_v5.py` | `D:\CUMCM2026\src\Q3_Q4_V3\code\src\q3_optimizer_v5.py` | 270 | 275 | 仅 import 改写 + 删路径注入 |
| `q3_optimizer_v4.py` | `...\code\src\q3_optimizer_v4.py` | 251 | 255 | 仅 import 改写 + 删路径注入 |
| `geometry_src.py` | `...\code\src\geometry.py` | 175 | 180 | **改名**，正文逐行未改 |
| `q2_adopted.py` | `...\code\src\q2_adopted.py` | 157 | 160 | 1 处 import 改写 |
| `legacy_second_point.py` | `...\code\src\legacy_second_point.py` | 87 | 90 | 1 处 import 改写 |
| `second_point.py` | `...\code\src\second_point.py` | 11 | 14 | 2 处 import 改写 |
| `practice_single_source.py` | `...\code\practice_single_source.py` | 22 | 22 | import 改写 + 删桩/ROOT/URL |
| `practice_all_sources_fast.py` | `...\code\practice_all_sources_fast.py` | 166 | 136 | import 改写 + 删 main() |
| `practice_all_sources.py` | `...\code\practice_all_sources.py` | 169 | 125 | import 改写 + 删 main() |

行数自洽：每个文件 = 源行数 + 头部注释行数（3~8）− 被删除行数（0~37）。逐行比对与 AST 口径见 §7。

### 1b. SHA-256（本次落盘版本，`Get-FileHash -Algorithm SHA256` 实测；供 t5 逐位复核）

| 目标文件（absorbed\q3_v5\） | 目标 SHA-256 | 对应源文件 | 源 SHA-256 |
|---|---|---|---|
| `__init__.py` | `c5f417fc7e96bc2ab51d9959c33dbecd90754e7800e697f2c677c526b9dac092` | （新增，无源） | — |
| `q3_optimizer_v5.py` | `be215589c4f911527b579f4aa4f570b1a5d99d4c190467bd88d1c8e5c582a361` | `code\src\q3_optimizer_v5.py` | `4e6993f0451fdd2850c5c757a15eb5f591f9b909a0882b8dc95a8d0efd9ee455` |
| `q3_optimizer_v4.py` | `ce510a694ceb4bd4780d5e884774adffb4482a06755f757ce67ca77ea8bd7d70` | `code\src\q3_optimizer_v4.py` | `2c244af92339ec791cba23c25848211269674d6c9e9dd5c52003ceca5ed74e58` |
| `geometry_src.py` | `bbf4fdfd6f04d163fb88278363ba66c57ac46a2a541d0e5b6fc20994dcd13923` | `code\src\geometry.py` | `72e6cb248df4bffa94538422fed6c9feee657b1062f3f7c5d4101ef46b1c7e39` |
| `q2_adopted.py` | `b61bae6ec18f6118f6a51277fadde1532126f8a3260e8337f2038113b7839f73` | `code\src\q2_adopted.py` | `beda550a5b092279f0676a0c4ace1ba3fcd64375b5e58a13ebe70304f588b1ac` |
| `legacy_second_point.py` | `ae0e6cde372b28a366d50849fc09b05fe426774281617b5e608cfba2cc4af2ae` | `code\src\legacy_second_point.py` | `b704be105ad41fece3332d718ba832c56c8cee086a0fc14482fddcd3066e7c05` |
| `second_point.py` | `aec259eb4c61481b8b54fc7b86ac376dff51639ef2ddf5f4f2d73e944b059128` | `code\src\second_point.py` | `3496dd66a999b077bb6721bf3d9624472f5814c2a05a8246425ccd3cbc701b20` |
| `practice_single_source.py` | `e724572c174de1f4c4e05dfb0131187be369ef2a5d56c9a2ff8e10dc7f20317b` | `code\practice_single_source.py` | `b08cb2546594fff502de91ac1acee2e4c07230b6fe632ed30101e2ac24efaca6` |
| `practice_all_sources_fast.py` | `2aa877e271457a4124617e7a9d60154912c4b4eab50ffaa73bd4def6b51ae8c4` | `code\practice_all_sources_fast.py` | `959b06a84f13c6e3c6acaa8dfdf827f11138ba3856bb689477d9611cc9e5a4b4` |
| `practice_all_sources.py` | `45cc4d07c040d814e6f00188792dc6e31ee040029b8e450821e968fdcf4e4528` | `code\practice_all_sources.py` | `5a9dff69a11846985a31c24e022fe61ebd2d75f4c057f49f9137a8cbf03d8525` |

（MANIFEST.md 自身未列入：它会被后续补充而变哈希。复现：`Get-ChildItem D:\CUMCM2026\src\q3+q4_v2\absorbed\q3_v5\*.py | %{ (Get-FileHash $_.FullName -Algorithm SHA256).Hash }`）

## 2. 逐处 import 改写（全部 old → new）

**q3_optimizer_v5.py**
| 源行 | old | new |
|---|---|---|
| 2 | `from pathlib import Path` | 删除（仅用于 ROOT 注入） |
| 3 | `import math,sys` | `import math` |
| 6 | `ROOT=Path(__file__).resolve().parents[2]` | 删除 |
| 7 | `sys.path.insert(0,str(ROOT/'code'))` | 删除 |
| 8 | `import practice_single_source` | `from . import practice_single_source` |
| 9-10 | `from q3_optimizer_v4 import (...)` | `from .q3_optimizer_v4 import (...)` |

> 源第 8 行的 `practice_single_source` 在 v5 正文中**未被调用**（通读 270 行确认）；为保持依赖边与逐行一致而保留相对 import 形式。

**q3_optimizer_v4.py**
| 源行 | old | new |
|---|---|---|
| 2 | `from pathlib import Path` | 删除 |
| 3 | `import math,sys` | `import math` |
| 6-7 | `ROOT=...` / `sys.path.insert(...)` | 删除 |
| 8 | `from practice_all_sources_fast import initial_polygon,covered_cells,CELL_CENTRES` | `from .practice_all_sources_fast import ...` |
| 9 | `from practice_single_source import minimum_circle,clip_polygon,bearing_halfplanes,ERROR` | `from .practice_single_source import ...` |
| 10 | `from geometry import hull` | `from .geometry_src import hull` |
| 11 | `from q2_adopted import reception_residuals` | `from .q2_adopted import reception_residuals` |

**geometry_src.py**：无 import 可改（源文件只 import 标准库/numpy/scipy）。

**q2_adopted.py**
| 源行 | old | new |
|---|---|---|
| 12 | `from geometry import bearing_halfplanes,clip_polygon,diameter_bruteforce,minimum_circle` | `from .geometry_src import bearing_halfplanes,clip_polygon,diameter_bruteforce,minimum_circle` |

**legacy_second_point.py**
| 源行 | old | new |
|---|---|---|
| 4 | `from geometry import bearing_halfplanes, clip_polygon, diameter_bruteforce, minimum_circle` | `from .geometry_src import ...` |

**second_point.py**
| 源行 | old | new |
|---|---|---|
| 4-8 | `from q2_adopted import (...)` | `from .q2_adopted import (...)` |
| 9-11 | `from legacy_second_point import (...)` | `from .legacy_second_point import (...)` |

**practice_single_source.py**
| 源行 | old | new |
|---|---|---|
| 2 | `from pathlib import Path` | 删除 |
| 3 | `import math,sys` | `import math` |
| 5-6 | `ROOT=Path(__file__).resolve().parents[1]` / `sys.path.insert(0,str(ROOT/'code/src'))` | 删除 |
| 7 | `from geometry import bearing_halfplanes,clip_polygon,minimum_circle` | `from .geometry_src import ...` |
| 8 | `from second_point import outer_prior,plan_second_point,to_global` | `from .second_point import ...` |

**practice_all_sources_fast.py**
| 源行 | old | new |
|---|---|---|
| 2 | `from pathlib import Path` | 删除 |
| 3 | `import argparse, datetime, hashlib, json, math, time` | `import math` |
| 6-7 | `from practice_single_source import (PracticeClient, ROOT, URL, ERROR, bearing_halfplanes, clip_polygon, minimum_circle, outer_prior, to_global)` | `from .practice_single_source import (ERROR, bearing_halfplanes, clip_polygon, minimum_circle, outer_prior, to_global)` |
| 8 | `from practice_all_sources import coverage_sites` | `from .practice_all_sources import coverage_sites` |

**practice_all_sources.py**
| 源行 | old | new |
|---|---|---|
| 2 | `from pathlib import Path` | 删除 |
| 3 | `import argparse, datetime, hashlib, json, math, sys, time` | `import math` |
| 5-7 | `from practice_single_source import (PracticeClient, ROOT, URL, ERROR, search_points, bearing_halfplanes, clip_polygon, minimum_circle, outer_prior, plan_second_point, to_global)` | `from .practice_single_source import (ERROR, search_points, bearing_halfplanes, clip_polygon, minimum_circle, outer_prior, plan_second_point, to_global)` |

## 3. 删除清单（逐项 + 理由）

| # | 删除内容 | 位置 | 理由 |
|---|---|---|---|
| D1 | `sys.path` 注入：`ROOT=Path(__file__).resolve().parents[...]` + `sys.path.insert(...)` | v5 源 6-7；v4 源 6-7；practice_single_source 源 5-6 | 指向源包目录；且目标包运行时已把包根与 baseline\code 插入 sys.path，注入会造成跨包解析与同名冲突 |
| D2 | 离线桩 `class PracticeClient`（`__init__` 直接 `raise RuntimeError`） | practice_single_source 源 12-14 | 本队硬约束：不得 vendor 只 raise 的离线桩；本包必须走真实 socket 通路 |
| D3 | 常量 `URL='offline://disabled'` | practice_single_source 源 10 | 仅被各模块 main() 的练习模式门禁使用 |
| D4 | `main()` 及其 `if __name__=='__main__':main()` | practice_all_sources 源 121-165 / 168-169；practice_all_sources_fast 源 131-164 / 166 | main() 构造 PracticeClient（D2）并把结果写入源包 `results/` 目录，不属于 solver 闭包 |
| D5 | 仅为 main() 服务的 import：`pathlib.Path`、`argparse`、`datetime`、`hashlib`、`json`（fast+all）、`sys`/`time`（all） | 见 §2 | 随 D4 一起失效；逐处确认过非 main() 代码未使用这些名字 |
| D6 | 文件名 `geometry.py` → `geometry_src.py` | 全闭包 | 见 §4 |

保留但「在源文件中即未被使用」的名字（为满足「除 import 行外逐行一致」而未删）：`practice_single_source` 的 `import math` / `import numpy as np`、`practice_all_sources_fast` 从 practice_single_source 引入的 `outer_prior`、v5 的 `import practice_single_source`。

## 4. 命名冲突排查（硬约束 2）

目标包运行时会把 `<包根>` 与 `<包根>\baseline\code` 置于 `sys.path` 最前（`run.py:29-32`、`runtime.py:15-18`），且 `runtime.py:24` 有 `from geometry import constants as C`。因此**同名文件会被静默解析到别的模块**。

| vendored 模块 | 与目标包顶层同名？ | 处理 |
|---|---|---|
| `geometry.py`（源名） | **是**（顶层 `geometry` 包） | **改名为 `geometry_src.py`** |
| `q3_optimizer_v5.py` / `q3_optimizer_v4.py` / `q2_adopted.py` / `legacy_second_point.py` / `second_point.py` / `practice_single_source.py` / `practice_all_sources_fast.py` / `practice_all_sources.py` | 以 `run.py:34-49`、`runtime.py:20-29` 出现的顶层名（api, executor, experiment, geometry, lookahead, production, runtime, policy, state, 各策略包）+ captain 给定清单（geometry, policy, state, executor, experiment, coverage, base, candidate）核对：无同名 | 保留原名 |

`geometry` 改名的**全部引用点**（本包内 4 处，均已写为 `from .geometry_src import ...`）：
1. `q2_adopted.py:11`
2. `legacy_second_point.py:7`
3. `practice_single_source.py:12`
4. `q3_optimizer_v4.py:14`（`hull`）

未枚举目标包整棵目录树（本会话 glob 不可用），但**相对 import 不经过 `sys.path`**，即使存在未登记的同名顶层模块也不会被解析到；该性质由 §2 的「全部 import 均带前导点」静态保证。

## 5. 全局副作用排查（硬约束 3：socket / urllib / 网络禁用）

**结论：Q3 闭包内不存在任何 socket/urllib 猴补丁、网络禁用代码或其它全局状态修改。**

逐文件静态核对（证据 = 这些文件的完整 import 段，已逐个 read）：

| 文件 | 全部顶层 import | 模块级附加语句 |
|---|---|---|
| `geometry_src.py` | `itertools.combinations`、`math`、`numpy`、`scipy.optimize.linprog` | `TOL = 1e-8` |
| `q2_adopted.py` | `math`、`heapq`、`numpy`、`scipy.optimize.brentq` | `VERSION` / `L` / `R` / `NEAR` |
| `legacy_second_point.py` | `math`、`numpy`、`.geometry_src` | 无（仅 def） |
| `second_point.py` | `.q2_adopted`、`.legacy_second_point` | 无（纯再导出） |
| `practice_single_source.py` | `math`、`numpy`、`.geometry_src`、`.second_point` | `ERROR=1.005` |
| `practice_all_sources.py` | `math`、`numpy`、`.practice_single_source` | `VERSION` / `STRATEGIES` |
| `practice_all_sources_fast.py` | `math`、`functools.lru_cache`、`numpy`、`.practice_single_source`、`.practice_all_sources` | `VERSION`/`CELL` 与 `centres/X/Y/ALL_CENTRES/nearest/CELL_CENTRES/HALFDIAG`（纯 numpy 计算，无 IO） |
| `q3_optimizer_v4.py` | `math`、`functools.lru_cache`、`numpy`、4 个包内模块 | 无（仅 def） |
| `q3_optimizer_v5.py` | `math`、`numpy`、`scipy.optimize.minimize`、`.practice_single_source`、`.q3_optimizer_v4` | `VERSION` / `SELECTED_PARAMETERS` |

对照（源包 Q4 侧确实存在此类 hook，但**不在 Q3 闭包内**，因此被自然排除）：
`D:\CUMCM2026\src\Q3_Q4_V3\workstreams\q4_deep_optimization_v4_20260912\bridge_v4.py`
- 第 3 行 `import sys,socket,urllib.request,json`
- 第 4 行 `sys.dont_write_bytecode=True`
- 第 5 行 `import numba  # Load before the read-only v2 module named coverage reaches sys.path.`
- 第 9 行 `socket.socket=deny;socket.create_connection=deny;urllib.request.OpenerDirector.open=deny`

该文件是 Q4 v4 工作区的桥接脚本，**未被 Q3 闭包中任何文件 import**（Q3 侧 9 个文件的 import 段已在 §2 全部列出，可逐条核对），故本包导入时不会禁用 socket，`--sim http` 与 `--sim http-synthetic` 的真实 socket 通路不受影响。若后续有人把 Q4 的 bridge 引入本包，必须先摘掉这两行全局补丁。

## 6. 契约（与源一致，未改）

- `VERSION = 'q3_joint_search_clear_route_v5'`（源 `q3_optimizer_v5.py:264` → 本目录 `q3_optimizer_v5.py:269`）
- `SELECTED_PARAMETERS`：21 键，逐字段与源 `:265` 一致（route_mode/probe/share_at_search/share_during/share_ratio/offset/advance/unknown_scan/rotation/exact_positive/info_points/arc_scan/estimate/trial_radius/trial_limit/probe_count/site_passes/site_bonus/planning_radius/commit/sweep_advance）
- `solve_optimized_v5(client, progress=None)`（源 `:267-270` → 本目录 `:272-275`）：`result = solve(client, progress=progress, **SELECTED_PARAMETERS)`，随后 `result.update(version=..., parameters=...)` 返回字典。
- `solve(...)` 的 22 个形参名与默认值逐字未改。
- 依赖链（静态核对通过，无循环）：`q3_optimizer_v5` → {`.practice_single_source`, `.q3_optimizer_v4`}；`.q3_optimizer_v4` → {`.practice_all_sources_fast`, `.practice_single_source`, `.geometry_src`, `.q2_adopted`}；`.practice_all_sources_fast` → {`.practice_single_source`, `.practice_all_sources`}；`.practice_all_sources` → `.practice_single_source`；`.practice_single_source` → {`.geometry_src`, `.second_point`}；`.second_point` → {`.q2_adopted`, `.legacy_second_point`}。另有 `initial_polygon` 的再导出链：`practice_all_sources_fast.initial_polygon` → `q3_optimizer_v4` 命名空间 → v5 的 `from .q3_optimizer_v4 import initial_polygon`。
- client 契约（调用方须提供，源 solver 依赖）：`act('/measure', pos, channel) -> {'measure_result','svd_deg'}`、`act('/clear', point, channel) -> {'clear_result'}`、属性 `position` / `virtual` / `rows` / `channel`。

## 7. 运行期验证（已执行；队长已更正「shell 不可用」为早期瞬时故障）

工作目录 `D:\CUMCM2026\src\q3+q4_v2`，环境 python 3.13.9 (Anaconda)，全部命令 `EXIT=0`。

**V0 队长指定的最小命令（逐字执行）**
```
python -X utf8 -c 'from absorbed.q3_v5 import q3_optimizer_v5 as m;print(m.VERSION);print(sorted(m.SELECTED_PARAMETERS))'
```
输出：
```
q3_joint_search_clear_route_v5
['advance', 'arc_scan', 'commit', 'estimate', 'exact_positive', 'info_points', 'offset', 'planning_radius', 'probe', 'probe_count', 'rotation', 'route_mode', 'share_at_search', 'share_during', 'share_ratio', 'site_bonus', 'site_passes', 'sweep_advance', 'trial_limit', 'trial_radius', 'unknown_scan']
```
与队长实测的源侧输出（`q3_joint_search_clear_route_v5`、21 项）一致。

**V1 导入 + 契约一致性**（源模块与 vendored 模块同进程对比；脚本经 `python -X utf8 -` 从 stdin 执行）
```
MODFILES_ALL_INSIDE_PACKAGE True []      # 9 个模块的 __file__ 全部位于 absorbed\q3_v5
IMPORT_COUNT 9
SRC_VERSION q3_joint_search_clear_route_v5
VENDORED_VERSION q3_joint_search_clear_route_v5
VERSION_EQUAL True
PARAMS_EQUAL True N 21
SIG_ENTRY_EQUAL True                     # inspect.signature(solve_optimized_v5) 两边相等
SIG_SOLVE_EQUAL True                     # solve() 22 个形参名与默认值两边相等
SIG_SOLVE (client, route_mode='joint', probe=0.0, share_at_search=True, share_during=False, share_ratio=0.7, offset=0.1, advance=0.25, unknown_scan=False, rotation=0.0, exact_positive=False, info_points=False, arc_scan=0, estimate='circle', trial_radius=0.0, trial_limit=12, probe_count=1, site_passes=0, site_bonus=0.0, planning_radius=0.0, commit=False, sweep_advance=0.0, progress=None)
PKG_REEXPORT q3_joint_search_clear_route_v5 True absorbed.q3_v5.q3_optimizer_v5
```

**V2 AST 等价（剥掉 Import/ImportFrom，全树递归）**：9 个文件逐个 `ast.parse` → `NodeTransformer` 删除所有 Import/ImportFrom → `ast.dump` 比对。结果：

| 文件 | 结果 | source_only（唯一差异） |
|---|---|---|
| geometry_src.py | `FULL-AST-EQ` | — |
| q2_adopted.py | `FULL-AST-EQ` | — |
| legacy_second_point.py | `FULL-AST-EQ` | — |
| second_point.py | `FULL-AST-EQ` | — |
| q3_optimizer_v5.py | `FULL-AST-DIFF`（target_only `[]`） | `assign ROOT`、`call sys.path.insert(0, str(ROOT / 'code'))` |
| q3_optimizer_v4.py | `FULL-AST-DIFF`（target_only `[]`） | 同上 |
| practice_single_source.py | `FULL-AST-DIFF`（target_only `[]`） | `assign ROOT`、`call sys.path.insert(0, str(ROOT / 'code/src'))`、`assign URL`、`class PracticeClient` |
| practice_all_sources_fast.py | `FULL-AST-DIFF`（target_only `[]`） | `def main`、`if __name__ == '__main__'` |
| practice_all_sources.py | `FULL-AST-DIFF`（target_only `[]`） | `def main`、`if __name__ == '__main__'` |

5 个文件均报 `target_equals_source_minus_source_only_in_order: True`、`target_only: []`，即 **目标 AST = 源 AST − 已批准删除（D1/D2/D3/D4），无任何未登记改动**。`FILES_COMPARED 9 / AST_DIFFERING 5`。

**V3 数值逐位等价**（源 vs vendored，同一进程、同输入）：`ALL_NUMERIC_EQUAL True of 16`，覆盖 `initial_polygon`、`minimum_circle(center+radius)`、`bearing_halfplanes(A,b)`、`clip_polygon`、`hull`、`q2.outer_prior`、`q2.reception_residuals`、`q2.to_global`、`negative_refine`、`exclude_disk`、`continuous_cover`、`project_to_disks`、`first_route_target`、`v5.open_tour`、`v5.site_on_route`、`practice_fast.covered_cells`。

**V4 整局 `solve()` 行为等价（q3-porter 同进程实测）**：同一份确定性 mock client（12 个源均布在半径 600 m、频道 13-20 为空；measure/clear 各计 5 s；clear 需落在真实源 20 m 内），分别调用源 `solve_optimized_v5` 与 vendored `solve_optimized_v5`：
```
SOURCE   outcome: ok actions: 110 virtual: 550.0
VENDORED outcome: ok actions: 110 virtual: 550.0
OUTCOME_EQUAL True / ACTIONS_EQUAL True / VIRTUAL_EQUAL True / RESULT_JSON_EQUAL True
CLEARED_COUNT 12 12      CLEARED_CHANNELS True [1,...,12]
DIFFERING_TOP_LEVEL_KEYS []
```
整局返回字典经 `json.dumps(sort_keys=True)` 完全相同 → 端到端行为一致（该 mock 为验证用桩，不是官方模拟器）。该结果已由 **verifier 独立复现**（跨进程、独立 mock 实现，见 V7）。

**V5 静态扫描（AST + tokenize）**：16 处内部 import 全部带前导点；绝对 import 仅 `math/numpy/scipy/functools/heapq/itertools`（`UNEXPECTED_ABSOLUTE_ROOTS []`）；可执行代码中 `sys/socket/urllib/requests/http/os/subprocess` 引用 `EXECUTABLE_TOTAL 0`；20 处 `Q3_Q4_V3`/`sys.path` 提及**全部位于注释或 docstring**（来源说明白名单），`code_token_hits` 全为空。

**V6 stub client 冒烟**（只实现 `act` / `position` / `virtual` / `rows` / `channel` 的确定性 stub；脚本经 `python -X utf8 -` 从 stdin 执行，**不落盘、未写入 absorbed/**）：
- STUB-A（`measure` 恒返回 `no_signal`、`clear` 恒 `no_target_in_range`）→ `outcome=RAISE RuntimeError: Source count outside Q3 bounds @ D:\CUMCM2026\src\q3+q4_v2\absorbed\q3_v5\q3_optimizer_v5.py:261`，`actions=140 virtual=700.0`。即**没有 import 期/调用期崩溃**，异常是引擎自身的计数契约检查（对应源 `:256`），属可解释 RuntimeError。
- STUB-B（12 个源均布半径 600 m；`measure` 返回精确方位、`clear` 需落在真实源 20 m 内）→ `outcome=OK cleared_count=12 actions=110 virtual=550.0 cleared=[1..12]`。
- 两个 stub 的 `contract_members` 均为 `['act','position','virtual','rows','channel']`。

**V2 的 `python -X utf8 -c "..."` 形式**（队长要求现场跑出）：
```
python -X utf8 -c "<剥 Import/ImportFrom 后比对 ast.dump 的一行式>"     # EXIT=0
```
逐文件输出：`PASS` = geometry_src / q2_adopted / legacy_second_point / second_point；`FAIL`（`target_only=[]`）= 5 个文件，`source_only` 即 D1–D4。过程记录：首次把 diff 明细塞进 `-c` 一行时括号写错，python 报 `SyntaxError`（EXIT=1，无结果产生）；修正后的一行式与同逻辑 stdin 脚本均 EXIT=0。

**V7 verifier 独立复现（跨进程、独立 mock 实现）** —— **证据归属：verifier**；脚本 `verification\oracle_q3_mock_diff.py`（未复用 q3-porter 的任何脚本，其 mock 与本目录 STUB-B 实现不同），源引擎与移植引擎**各自独立进程**运行：

| 用例 | 源引擎 | 移植引擎 | 比对结果 |
|---|---|---|---|
| mock（12 源 ring） | `outcome=ok, actions=110, virtual=550.0, cleared=12, channels=[1..12]` | 同 | `outcome / actions / virtual / result_json_equal=True / cleared_count / cleared_channels / differing_top_level_keys=[]` **全 PASS** |
| blind stub（恒 `no_signal` / `no_target_in_range`） | `RuntimeError, actions=140, virtual=700.0` | 同 | 错误类型 + actions + virtual 全等 |

- q3-porter 的同进程参考值（110 / 550.0 / 12）与 STUB-A 的（140 / 700.0）**逐位命中**。
- **跨进程确定性获独立支持**：q3-porter 为同进程跑，verifier 为两进程各跑一次，外层结果相同。
- blind 用例只比错误类型与计数、不比异常文本：异常消息内嵌各自文件路径（源树 vs absorbed 树必然不同），比文本会假 FAIL。
- **覆盖范围限定**：本条只证明「同输入行为等价」，不代表 Q3 接收/清除的业务口径正确（见 §7b 第 2 条）。
- **环境限定**：上述确定性均在**同一台机、同一 numpy/scipy** 下取得；mock 几何为纯浮点运算，理论上跨环境仍确定，但若引擎侧引入依赖 `set` 迭代序或字符串哈希序的逻辑则可能漂移 —— 本包当前相关集合仅含小整数、迭代处均走 `sorted()`，故「无随机」前提成立。

**V8 端到端 `absorbed/run_absorbed.py --mode q3`（证据归属：captain 提出、verifier 独立复现；q3-porter __未__复现）**
命令（captain 实跑，exit=0）：
```
python -X utf8 absorbed/run_absorbed.py --mode q3 --engine q3-v5 --sim http-synthetic --seed 101 --n-sources 10 --scenario random --output-dir runs/_captain_absorbed_q3
```
输出要点：`complete=true, cleared=10, certified_absent=10, verifier_all_ok=true, T_per_source_s=293.483, measures=120, switches=111, clear_success/attempts=10/11, wall_clock_s=1.149, engine_version=q3_joint_search_clear_route_v5`；同 seed 生产 learned 路线 456.708 s → **减少 35.7%**。
说明：本条由 captain 报告；**verifier 已在其独立 40 局矩阵中复现该格**（其 `T_per_source_s=293.4833054` 与 captain 的 293.483 一致），故归属记为「captain 提出 + verifier 独立复现」。q3-porter **未参与该次运行、也未复现其日志与产物**；如需第三方复核，可在获授权后只读检查 `runs/_captain_absorbed_q3/` 下的报告文件。

### 7b. 仍未覆盖 / 无法确认（勿当作已验证）

1. **真实模拟器端到端（对 q3-porter 而言未跑）**：captain 已用 `absorbed/run_absorbed.py --sim http-synthetic` 跑通 q3（见 V8，证据归属 captain 提出 + verifier 独立复现，q3-porter 未复现）；官方 `--sim http`（真实服务器）通路、以及 verifier 对产物 `metrics.json` / `verifier_report.json` 的判定，仍属 t4/t5 覆盖范围。
2. **与官方模拟器世界模型的一致性未验证**：V4 与 V7 只证明「源引擎 vs 移植引擎在相同输入下完全一致」，不证明 Q3 的接收/清除经济口径正确。
3. 跨 numpy/scipy 版本行为未验证（同环境内一致）。
4. `absorbed\__init__.py`（adapter-eng 负责）本次存在且导入正常；若其内容变化，本包相对 import 不受影响，但未做该文件回归。

## 8. 复现命令（可原样重跑）

```
python -X utf8 -c 'from absorbed.q3_v5 import q3_optimizer_v5 as m;print(m.VERSION);print(sorted(m.SELECTED_PARAMETERS))'
python -X utf8 -c 'import absorbed.q3_v5.geometry_src as g, absorbed.q3_v5.practice_all_sources_fast as f;print(g.TOL, f.CELL, len(f.CELL_CENTRES))'
findstr /S /N /C:"sys.path" /C:"socket" /C:"urllib" /C:"Q3_Q4_V3" D:\CUMCM2026\src\q3+q4_v2\absorbed\q3_v5\*.py
```
V1-V5 的 AST / 数值 / 整局比对脚本较长，均以 `$py = @'...'@; $py | python -X utf8 -`（即 `python -X utf8 -` 从 stdin 读脚本）方式执行，不落盘；V0 的输出即为本会话中记录到的那一份。

> 备注：本文件所在的 9 个 Python 文件是**未做任何数值改动的搬运**；`findstr` 的命中只会出现在各文件头部注释（来源说明）与本 MD 内。

## 9. 生产文件实测（只读取证；响应 verifier 门禁 `[FAIL] MUST/f`）

`Get-FileHash -Algorithm SHA256` + `Get-Item`，2026-09-13 本会话实测：

| 生产文件 | 字节 | mtime | SHA-256 |
|---|---|---|---|
| `run.py` | 68 547 | 2026-09-13 12:59:51 | `def842f4ae28c7f878141d4e1d2904959fb91b8f25dd72e6f75c931550f1c174` |
| `production.py` | 8 396 | 2026-09-12 22:43:14 | `638bce2240a56d914cd67630e65089cdd96062f76f93cd276ea8589f8945886c` |
| `runtime.py` | 38 610 | 2026-09-13 00:46:15 | `fd92820e0f3f189e63c09e2de2da6755ca21c6b529ee2e594659e1de2921c376` |
| `compare.py` | 5 435 | 2026-09-12 08:05:43 | `95f8736815c650bdf3a90f811e337bcd7c502e82691cc93ca34cc82cb9c59595` |
| `recommended.py` | 2 220 | 2026-09-12 11:41:05 | `0b9299e3567862b918af2b9efc6a8528b247492813b687523c98c816a6bddd46` |

取证结论（全部只读、可复现）：

- **无 git 仓库**：`git -C D:\CUMCM2026 rev-parse --show-toplevel` → `fatal: not a git repository`，因此无法生成 diff。
- **本机不存在可回滚前像**：`D:\CUMCM2026\src` 下全部 `run.py*`（6 份：本文件、`baseline\code\run.py`、`src\q3+4\code\run.py`、3 个策略子目录的 `run.py`）逐份 SHA-256 比对，**无一份等于 verifier 记录的基线哈希 `14c479355e15…`**。
  - 补充（**verifier 结论**，与本条互为佐证）：`verification\production_hashes_before.json` 是 **hash-only 基线**（只含 sha256/size/mtime，**不存文件内容**），故它**能证明完整性、不能用于回滚**。两条合起来 → **就地回滚不可行**，因此「书面授权 + 逐项登记 + 门禁按精确 `(path, before, after)` 三元组匹配」是唯一可行收口，而非技术性次优选择。方法学教训（供后来者）：*hash-only 基线可证明完整，但若要可回滚，基线必须存内容或至少一份压缩副本*。
- **变更位置定位**：`run.py` 第 1–65 行与 q3-porter 本会话早期读数完全一致（`SCENARIOS:52`、`SCAN_MODES:53`、`SCHEDULERS:55` 起点未移动），文件尾为 `raise SystemExit(main())`（:1122）后跟 4 个空行；本会话早期该文件为 1087 行，现为 1127 行 → **变更为第 65 行之后的约 +40 行（parser / main 区域）**。
- **变更与本包无关**：`run.py` 中 `absorbed|ABSORBED|q3-v5|q4-v4|q3_optimizer_v5|strategy_v4|locked` 的 grep 命中数为 **0**。
- **时间线（mtime）**：`absorbed/**` 全部写入落在 12:31:02–12:54:50（本包 MANIFEST 最后写入 12:54:50）→ `run.py` 变更 **12:59:51**（晚于本包全部写入）→ verifier 的 `verification/**` 落在 12:47:34–13:02:09。
- **归属（已确认；q3-porter 独立复核了三段证据链）**：**captain 依用户明确指令修改，范围仅 `run.py`**；书面登记 `verification\production_change_authorization.json`（mtime 2026-09-13 13:03:37）。复核结果：① 授权记录的 `after_sha256` 与磁盘现状**逐位相同**（`def842f4ae28c7f878141d4e1d2904959fb91b8f25dd72e6f75c931550f1c174` / 68 547 B）；② 授权记录的 `before_sha256` 与 `verification\production_hashes_before.json`（基线，捕获于 `2026-09-13T04:30:03Z`）中 `run.py` 条目**相同**（`14c479355e158be2d574af500bd289de66a4a47b376ee94a00ca4a70078aa7ac` / 66 791 B）；③ 其余 4 个点名文件的现状哈希与基线**逐位相同**（见上表）→ 与授权声明的「唯一改动 = `run.py`、其余仍禁止」一致。q3-porter 不是改动者（写入范围仅 `absorbed\q3_v5\**`，工具历史可查）。
- **该变更的回归证据**：由 captain 报告（`learned` q3 `4567.076019` vs 基线 `4567.076019177168`、`learned` q4 mixed `6505.989701` vs `6505.989700901541`，多条路线由「构造即崩」转为可跑），记录在 `verification\production_change_authorization.json` 的 `regression_evidence`；**q3-porter 未复跑这些回归**，故此处不作「已验证」呈现。
- **语义更正**：本节先前写的「归属无法由磁盘确定」**作废** —— captain 已自报并留下登记文件，q3-porter 已按上述三段证据链独立复核。§9 上方四条取证与时间线保留，用于证明该变更**与 `absorbed/` 无关**。
