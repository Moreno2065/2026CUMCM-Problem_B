# -*- coding: utf-8 -*-
"""plot 脚本公共助手：路径、matplotlib 初始化、保存、数据加载。"""

import json
import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]   # code/
sys.path.insert(0, str(CODE_ROOT))

# 托管 python 的 CJK/字体设置；不可用时退化默认（图注保持英文）
try:
    sys.path.insert(0, str(Path(sys.executable).parent.parent.parent))
    from daimon_runtime import setup_plot
    setup_plot()
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E401

# A compact publication preset shared by all figure scripts.  Keep vector text
# editable in the PDF master and use fonts that are available on Windows while
# retaining a portable DejaVu fallback.
matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Microsoft YaHei", "DejaVu Sans"],
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "axes.linewidth": 0.8,
    "axes.edgecolor": "#4B5563",
    "axes.unicode_minus": False,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "xtick.color": "#4B5563",
    "ytick.color": "#4B5563",
    "legend.fontsize": 8,
    "legend.frameon": False,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "savefig.facecolor": "white",
})

RESULTS = CODE_ROOT / "results"
FIGURES = CODE_ROOT / "figures"


def save(fig, out_dir, name, dpi=300):
    """保存 PDF master + PNG preview，并返回路径对。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / ("%s.pdf" % name)
    png = out_dir / ("%s.png" % name)
    fig.savefig(str(pdf), bbox_inches="tight")
    fig.savefig(str(png), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return pdf, png


def dump_data(out_dir, name, obj):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    if p.suffix == ".json":
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
    else:
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(obj if isinstance(obj, str) else "".join(obj))
    return p


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def add_args(parser):
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--out", default=str(FIGURES))
    return parser
