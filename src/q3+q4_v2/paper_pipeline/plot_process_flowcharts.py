"""Generate Q1/Q3/Q4 manuscript process flowcharts as high-resolution JPG only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon


NAVY = "#293B5F"
BLUE = "#2474B5"
LIGHT_BLUE = "#EAF3FA"
ORANGE = "#D9763D"
LIGHT_ORANGE = "#FFF1E8"
GREEN = "#2F7D5C"
LIGHT_GREEN = "#EAF6EF"
GRAY = "#667085"
LIGHT_GRAY = "#F3F5F8"
RED = "#B94A48"
FONT_SCALE = 1.20
OUTPUT_DPI = 320


def configure() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [
            "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS",
        ],
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })


def box(ax, xy, wh, text, *, fc=LIGHT_BLUE, ec=BLUE, fs=11.5,
        weight="normal", radius=0.025, zorder=3):
    x, y = xy
    w, h = wh
    patch = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=2.2, zorder=zorder,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fs * FONT_SCALE,
            color=NAVY, fontweight=weight, linespacing=1.35, zorder=zorder + 1)
    return patch


def diamond(ax, xy, wh, text, *, fc=LIGHT_ORANGE, ec=ORANGE, fs=11):
    x, y = xy
    w, h = wh
    pts = [(x, y + h / 2), (x + w / 2, y), (x, y - h / 2), (x - w / 2, y)]
    patch = Polygon(pts, closed=True, facecolor=fc, edgecolor=ec,
                    linewidth=2.2, zorder=3)
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fs * FONT_SCALE,
            color=NAVY, linespacing=1.3, zorder=4)
    return patch


def arrow(ax, start, end, *, label=None, color=GRAY, rad=0.0,
          label_xy=None, style="-|>", lw=1.6, dashed=False):
    patch = FancyArrowPatch(
        start, end, arrowstyle=style, mutation_scale=18,
        connectionstyle=f"arc3,rad={rad}", linewidth=lw * 1.2,
        linestyle="--" if dashed else "-", color=color, zorder=2,
    )
    ax.add_patch(patch)
    if label:
        if label_xy is None:
            label_xy = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.018)
        ax.text(*label_xy, label, ha="center", va="center", fontsize=11.2,
                color=color, bbox=dict(facecolor="white", edgecolor="none", pad=1.2),
                zorder=5)
    return patch


def route_arrow(ax, points, *, label=None, label_xy=None, color=GRAY,
                lw=1.6, dashed=False, style="-|>"):
    """Draw an explicit right-angle route so connectors never cross nodes."""
    path = MplPath(points, [MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 1))
    patch = FancyArrowPatch(
        path=path, arrowstyle=style, mutation_scale=18,
        linewidth=lw * 1.2, linestyle="--" if dashed else "-",
        color=color, zorder=2,
    )
    ax.add_patch(patch)
    if label:
        if label_xy is None:
            label_xy = points[len(points) // 2]
        ax.text(*label_xy, label, ha="center", va="center", fontsize=11.2,
                color=color, bbox=dict(facecolor="white", edgecolor="none", pad=1.2),
                zorder=5)
    return patch


def title(ax, main, sub):
    ax.text(0.5, 0.965, main, ha="center", va="top", fontsize=24,
            fontweight="bold", color="#111827")
    ax.text(0.5, 0.915, sub, ha="center", va="top", fontsize=13,
            color=GRAY)


def footer(ax, text):
    ax.text(0.5, 0.025, text, ha="center", va="bottom", fontsize=11.5,
            color=GRAY)


def setup():
    # A physically larger canvas creates real whitespace between nodes; the
    # increased export DPI then preserves that separation when zoomed in.
    fig, ax = plt.subplots(figsize=(18.0, 11.5), dpi=160)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def q1_flow(out: Path) -> None:
    fig, ax = setup()
    title(ax, "Q1：有界测向误差下的定位区域、直径与覆盖判定",
          "从原始示向观测到可审计几何结论；不引入概率误差假设")

    box(ax, (0.10, 0.79), (0.15, 0.10), "输入 n 次观测\n(Si, αi)，ε=1°", fc=LIGHT_GRAY, ec=NAVY)
    box(ax, (0.30, 0.79), (0.17, 0.10), "角度归一化\n每次观测化为\n2 个线性半平面")
    box(ax, (0.52, 0.79), (0.18, 0.10), "枚举非平行\n边界线交点\n并作全约束过滤")
    diamond(ax, (0.73, 0.79), (0.15, 0.14), "存在可行点？")
    box(ax, (0.90, 0.79), (0.12, 0.09), "EMPTY\n无一致定位区", fc="#FDECEC", ec=RED)

    arrow(ax, (0.175, 0.79), (0.205, 0.79))
    arrow(ax, (0.385, 0.79), (0.425, 0.79))
    arrow(ax, (0.61, 0.79), (0.655, 0.79))
    arrow(ax, (0.805, 0.79), (0.84, 0.79), label="否", color=RED,
          label_xy=(0.825, 0.825))

    diamond(ax, (0.73, 0.57), (0.17, 0.15), "存在公共\n逃逸方向？")
    arrow(ax, (0.73, 0.72), (0.73, 0.65), label="是", color=GREEN,
          label_xy=(0.765, 0.685))
    box(ax, (0.91, 0.57), (0.13, 0.09), "UNBOUNDED\nD = ∞", fc=LIGHT_ORANGE, ec=ORANGE)
    arrow(ax, (0.815, 0.57), (0.845, 0.57), label="是", color=ORANGE,
          label_xy=(0.83, 0.605))

    box(ax, (0.54, 0.43), (0.22, 0.11), "有界区域重建\n顶点去重与逆时针排序\n判定点 / 线段 / 多边形")
    arrow(ax, (0.69, 0.51), (0.62, 0.475), label="否", color=BLUE,
          label_xy=(0.65, 0.535))
    box(ax, (0.29, 0.43), (0.18, 0.10), "枚举顶点对\n求最远点对 (A,B)\n与直径 D")
    arrow(ax, (0.43, 0.43), (0.38, 0.43))
    diamond(ax, (0.10, 0.43), (0.16, 0.15), "全部顶点均在\n直径圆内？")
    arrow(ax, (0.20, 0.43), (0.19, 0.43))

    box(ax, (0.10, 0.22), (0.16, 0.09), "覆盖成立\n输出：是", fc=LIGHT_GREEN, ec=GREEN, weight="bold")
    box(ax, (0.31, 0.22), (0.18, 0.09), "存在超出顶点\n输出：否及最大超出量", fc="#FDECEC", ec=RED)
    route_arrow(ax, [(0.068, 0.385), (0.068, 0.30), (0.10, 0.265)],
                label="是", color=GREEN, label_xy=(0.085, 0.31))
    route_arrow(ax, [(0.132, 0.385), (0.132, 0.325), (0.31, 0.325), (0.31, 0.265)],
                label="否", color=RED, label_xy=(0.225, 0.345))

    box(ax, (0.62, 0.22), (0.27, 0.11),
        "独立验证\nLP 判定状态 + 半平面裁剪\n凸包 / 旋转卡壳 / 最小覆盖圆",
        fc=LIGHT_GRAY, ec=NAVY, fs=10.5)
    arrow(ax, (0.40, 0.22), (0.485, 0.22), dashed=True, color=NAVY,
          label="交叉核验", label_xy=(0.442, 0.255))
    route_arrow(ax, [(0.18, 0.22), (0.21, 0.22), (0.21, 0.175),
                     (0.47, 0.175), (0.485, 0.195)],
                dashed=True, color=NAVY)
    box(ax, (0.88, 0.22), (0.15, 0.10), "最终输出\n状态、顶点、D\n直径圆覆盖结论", fc=LIGHT_GREEN, ec=GREEN, weight="bold")
    arrow(ax, (0.755, 0.22), (0.805, 0.22), color=GREEN)

    footer(ax, "核心原则：无界区域不作有限截断；直径圆是否覆盖必须逐顶点检验。")
    fig.savefig(out / "q1_process_flow.jpg", dpi=OUTPUT_DPI, bbox_inches="tight",
                pad_inches=0.25, facecolor="white",
                pil_kwargs={"quality": 95, "subsampling": 0})
    plt.close(fig)


def q3_flow(out: Path) -> None:
    fig, ax = setup()
    title(ax, "Q3：V1 保证门禁下的联合搜索—定位—清除闭环",
          "V1 决定动作是否合法与何时可停止；V2 优化动作次序和共享路线")

    # Top row: state construction and the only terminal branch.
    box(ax, (0.09, 0.82), (0.14, 0.10), "原点观测\n初始化 20 个频道\n知识状态 Kc", fc=LIGHT_GRAY, ec=NAVY)
    box(ax, (0.27, 0.82), (0.15, 0.10), "更新集合状态\nPc / Ec / Oc / sc")
    box(ax, (0.46, 0.82), (0.15, 0.10), "建立任务池\n扫描 / 定位 / 清除")
    diamond(ax, (0.66, 0.82), (0.14, 0.14), "满足终止证据？")
    box(ax, (0.87, 0.82), (0.16, 0.10), "独立 verifier\n账本闭合", fc=LIGHT_GREEN, ec=GREEN)
    arrow(ax, (0.16, 0.82), (0.195, 0.82))
    arrow(ax, (0.345, 0.82), (0.385, 0.82))
    arrow(ax, (0.535, 0.82), (0.59, 0.82))
    arrow(ax, (0.73, 0.82), (0.79, 0.82), label="是", color=GREEN,
          label_xy=(0.76, 0.85))

    # Middle row reads right-to-left, making the action-planning chain explicit.
    box(ax, (0.66, 0.64), (0.24, 0.10),
        "V1 保证层筛选合法动作\n禁止伪证空、越权清除和提前停止",
        fc=LIGHT_ORANGE, ec=ORANGE, fs=10.8, weight="bold")
    arrow(ax, (0.66, 0.75), (0.66, 0.70), label="否", color=ORANGE,
          label_xy=(0.69, 0.725))
    box(ax, (0.43, 0.64), (0.16, 0.10), "候选动作计价\n移动 + 测量 + 换频\n+ 清除 + 残余任务")
    box(ax, (0.25, 0.64), (0.15, 0.10), "合并共享站点\n多频道同站测量\n条件探点 / 试探清除")
    box(ax, (0.08, 0.64), (0.12, 0.10), "构造开放路线 π\n连续投影\n次序细化")
    arrow(ax, (0.54, 0.64), (0.51, 0.64))
    arrow(ax, (0.35, 0.64), (0.325, 0.64))
    arrow(ax, (0.175, 0.64), (0.14, 0.64))

    # Feedback is summarized in one state-transition node.  This eliminates
    # the four crossing branch lines present in the earlier draft.
    box(ax, (0.08, 0.43), (0.13, 0.10), "执行首个动作\n记录真实反馈", fc=LIGHT_BLUE, ec=BLUE, weight="bold")
    box(ax, (0.29, 0.43), (0.16, 0.10), "识别反馈类型\ndirection / near\nclear / finite-certificate", fc=LIGHT_ORANGE, ec=ORANGE, fs=9.8)
    box(ax, (0.57, 0.43), (0.30, 0.16),
        "频道状态转移\n"
        "direction → ACTIVE，收缩 Pc    |    near / Pc≤20 m → READY\n"
        "清除成功 → CLEARED              |    有限证书 → CERTIFIED_ABSENT",
        fc=LIGHT_BLUE, ec=BLUE, fs=9.5)
    box(ax, (0.88, 0.43), (0.14, 0.11),
        "刷新任务池\n保留全部观测与负反馈\n返回终止检查",
        fc=LIGHT_GRAY, ec=NAVY, fs=9.5)
    route_arrow(ax, [(0.08, 0.585), (0.08, 0.48)])
    arrow(ax, (0.145, 0.43), (0.21, 0.43))
    arrow(ax, (0.37, 0.43), (0.42, 0.43))
    arrow(ax, (0.72, 0.43), (0.81, 0.43))

    ax.add_patch(FancyBboxPatch((0.18, 0.17), 0.64, 0.085,
                                boxstyle="round,pad=0.01,rounding_size=0.02",
                                facecolor="white", edgecolor=ORANGE,
                                linestyle="--", linewidth=1.5))
    ax.text(0.50, 0.2125,
            "终止条件：已清除 16 个不同频道，或 20 个频道均 CLEARED / CERTIFIED_ABSENT",
            ha="center", va="center", fontsize=12.0, color=NAVY)
    footer(ax, "联合路线是效率层；集合状态、有限证书、基数停止和 verifier 是不可放松的保证层。")
    fig.savefig(out / "q3_process_flow.jpg", dpi=OUTPUT_DPI, bbox_inches="tight",
                pad_inches=0.25, facecolor="white",
                pil_kwargs={"quality": 95, "subsampling": 0})
    plt.close(fig)


def q4_flow(out: Path) -> None:
    fig, ax = setup()
    title(ax, "Q4：21 站连续覆盖证书与 crossbar 条件定位流程",
          "定向源的单次 no_signal 不等于频道不存在；证空必须由完整几何证据闭合")

    # Top row: geometry construction and terminal audit.
    box(ax, (0.09, 0.82), (0.14, 0.10), "原点首次观测\n初始化频道状态", fc=LIGHT_GRAY, ec=NAVY)
    box(ax, (0.29, 0.82), (0.17, 0.10), "比较 12 个刚性旋转\n选择预测路线最短的\n21 站骨干")
    box(ax, (0.49, 0.82), (0.16, 0.10), "中心 1 点\n内环 8 点（995 m）\n外环 12 点（1864 m）")
    diamond(ax, (0.68, 0.82), (0.14, 0.14), "满足终止证据？")
    box(ax, (0.87, 0.82), (0.16, 0.10), "独立 verifier\n完成与账本核验", fc=LIGHT_GREEN, ec=GREEN)
    arrow(ax, (0.16, 0.82), (0.205, 0.82))
    arrow(ax, (0.375, 0.82), (0.41, 0.82))
    arrow(ax, (0.57, 0.82), (0.61, 0.82))
    arrow(ax, (0.75, 0.82), (0.79, 0.82), label="是", color=GREEN,
          label_xy=(0.77, 0.85))

    # One-way execution row; there are no return lines through this row.
    box(ax, (0.68, 0.64), (0.20, 0.10), "联合路线选择下一动作\n证书站 / 定位 / 清除", fc=LIGHT_BLUE, ec=BLUE)
    arrow(ax, (0.68, 0.75), (0.68, 0.70), label="否", color=ORANGE,
          label_xy=(0.71, 0.725))
    box(ax, (0.43, 0.64), (0.17, 0.10), "执行测量或清除\n记录位置、频道与反馈")
    box(ax, (0.19, 0.64), (0.16, 0.10), "解析本次反馈\n正观测 / no_signal\n清除结果", fc=LIGHT_ORANGE, ec=ORANGE)
    arrow(ax, (0.58, 0.64), (0.515, 0.64))
    arrow(ax, (0.345, 0.64), (0.27, 0.64))

    # Put the full decision hierarchy in one auditable node.  It keeps the
    # priority order visible without a web of crossing yes/no connectors.
    box(ax, (0.50, 0.39), (0.70, 0.24),
        "证据判定与状态更新（按优先级）\n"
        "① 正观测：更新定向可行域 P，继续定位或试探清除\n"
        "② 21 个必要站点全部 no_signal：置 CERTIFIED_ABSENT，证书闭合\n"
        "③ 满足 crossbar：构造 x+、x−；双侧均 no_signal 则加入截面负约束，否则转常规定位/清除\n"
        "④ 其余情况：保留已有证据，继续完成 21 站骨干测量",
        fc=LIGHT_BLUE, ec=BLUE, fs=10.0)
    route_arrow(ax, [(0.19, 0.585), (0.19, 0.53), (0.50, 0.53), (0.50, 0.51)])

    box(ax, (0.50, 0.17), (0.28, 0.085),
        "写回频道状态与证书账本\n刷新任务池", fc=LIGHT_GRAY, ec=NAVY, weight="bold")
    arrow(ax, (0.50, 0.27), (0.50, 0.225))

    # A single external loop replaces four overlapping curved arrows.
    route_arrow(ax, [(0.64, 0.17), (0.94, 0.17), (0.94, 0.56),
                     (0.68, 0.56), (0.68, 0.585)],
                color=NAVY, dashed=True, label="下一轮：先检查终止证据，再选择动作",
                label_xy=(0.79, 0.56))

    footer(ax, "终止条件：清除 16 个不同频道，或所有频道由 CLEARED / CERTIFIED_ABSENT 完整闭合。")
    fig.savefig(out / "q4_process_flow.jpg", dpi=OUTPUT_DPI, bbox_inches="tight",
                pad_inches=0.25, facecolor="white",
                pil_kwargs={"quality": 95, "subsampling": 0})
    plt.close(fig)


def main() -> int:
    configure()
    root = Path(__file__).resolve().parents[1]
    out = root / "paper_evidence" / "flowcharts"
    out.mkdir(parents=True, exist_ok=True)
    q1_flow(out)
    q3_flow(out)
    q4_flow(out)
    files = []
    for path in sorted(out.glob("*.jpg")):
        files.append({
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (root / "paper_evidence" / "flowcharts_manifest.json").write_text(
        json.dumps({"format": "JPEG RGB only", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(files, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
