# CUMCM 2026 B题 - Q1 实现

对应冻结数学契约：`Q1_MATH_v1.2`。

## 主链 A

`测向读数 -> ±1°闭示向锥 -> 2n 个半平面 -> 全边界线对交点 -> 可行性过滤 -> EMPTY -> 公共逃逸方向 -> UNBOUNDED -> 顶点/维数 -> O(k²)直径 -> 直径圆覆盖判定`

主链只使用 Python 标准库，不依赖 SciPy/Shapely/CGAL。

**模型边界保持冻结**：Q1 定位区域只取示向锥交集，不额外与 1800 m 目标圆、1000-1500 m 接收半径或 5 m near 条件相交。

## 独立链 B

`q1_verify.py` 使用另一套证据链：

- SciPy HiGHS LP 独立判定 `EMPTY / UNBOUNDED / bounded`；
- 有界时用四个 LP 极值给出认证矩形，不使用拍脑袋 bounding box；
- 序贯半平面裁剪 + monotone-chain convex hull；
- rotating calipers 计算直径；
- MEC 用全部 2 点/3 点支撑圆确定性枚举，不使用随机 Welzl。

## 输入格式

JSON：

```json
{
  "epsilon_deg": 1.0,
  "measurements": [
    {"x": -500, "y": 0, "bearing_deg": 0, "label": "S1"},
    {"x": -250, "y": -433.0127, "bearing_deg": 60, "label": "S2"}
  ]
}
```

`bearing_deg` 可写成任意实数；实现入口统一 canonicalize 到 `[0,360)`。

## 运行

```bash
python q1_cli.py example_input.json --verify
```

输出包含：

- `status`: `EMPTY / UNBOUNDED / OK`
- `dimension`: 有界非空时为 `0/1/2`
- `vertices`: 有界定位域顶点（逆时针）
- `area`
- `diameter` 与 `diameter_pair`（`UNBOUNDED` 时 `diameter=null` 且 `diameter_is_infinite=true`）
- `covered_by_diameter_disk`
- `diameter_disk_center`, `diameter_disk_radius`
- `max_radial_excess`: 若不覆盖，最坏顶点超出直径圆的距离
- `rho_viol`: 最大顶点圆心距离 / `(d/2)`
- `verification`: 独立链 B 的 LP/HPI/卡壳/MEC 结果

## 回归测试

```bash
pytest -q
```

已落地冻结讨论中的 T1-T8，并额外覆盖 `n=1 -> UNBOUNDED`。

其中 T2 严格区分：

- `rho_viol = 1.01020649778`：**直径圆违反比例**；
- `2*r_MEC/d = 1.000051718263`：**最小覆盖圆比例**。

二者不可混用。

## 确定性随机对拍

除 T1-T8 外，可运行：

```bash
python fuzz_crosscheck.py --realizable 600 --arbitrary 800 --seed 20260910
```

该脚本固定 seed，只用于实现验证，不参与模型选择。

## 默认 Numba 后端（v1.1）

`solve_q1(...)` 现在默认 `backend="numba"`。仅将最耗时的
`边界线对求交 + 对全部半平面做可行性过滤` 三重循环 JIT 编译；
状态机、顶点排序、直径与覆盖判定仍复用冻结的 Python 数学逻辑。

- `fastmath=False`：避免近平行/边界判号被浮点重排改变；
- `@njit(cache=True)`：首次编译后缓存机器码；
- 若运行环境没有 Numba，则默认入口自动回退 `reference`，数学语义不变；
- 显式 reference：`solve_q1(..., backend="reference")` 或 `solve_q1_reference(...)`。

推荐运行：

```bash
python -m pytest -q
python q1_cli.py example_input.json --verify
python q1_cli.py example_input.json --backend reference --verify
```

当前环境（Numba 0.65.1 / NumPy 2.3.5）热启动基准：

| n | Numba | Reference | 加速比 |
|---:|---:|---:|---:|
| 2 | 0.031 ms | 0.031 ms | ~1.0x |
| 10 | 0.218 ms | 0.609 ms | 2.8x |
| 20 | 0.686 ms | 3.10 ms | 4.5x |
| 50 | 3.62 ms | 30.9 ms | 8.6x |
| 100 | 13.7 ms | 201.7 ms | 14.7x |

这些数字用于工程取舍，不进入论文数学模型。
