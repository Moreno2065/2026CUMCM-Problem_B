# -*- coding: utf-8 -*-
"""t36: Q4 fallback clear-ladder geometry -- counterfactual replay.

What the code actually does (verified, not assumed)
---------------------------------------------------
``geometry/fallback_cover.py`` builds the fallback ladder with
``disk_lattice_cover(poly, radius=CLEAR_RADIUS=20)``:

* triangular lattice, nearest-neighbour spacing ``a = sqrt(3) * r = 20*sqrt(3)
  = 34.641 m``, row spacing ``h = a*sqrt(3)/2 = 30 m``;
* covering radius of a triangular lattice is ``a/sqrt(3) = r = 20 m`` exactly,
  so the ladder *is* a guaranteed 20 m cover of the feasible polygon (with zero
  margin);
* the polygon is the observation-consistent feasible region P_c, and the visit
  order is ``order_greedy`` (nearest neighbour from the current position).

The task's premise used the *square*-lattice formula ``covering = s/sqrt(2)``,
which would demand ``s <= 20*sqrt(2) = 28.28 m``.  For the implemented
triangular lattice the guarantee condition is ``s <= 20*sqrt(3) = 34.64 m``, so
the shipped spacing already satisfies it.  A 28.28 m square lattice has the same
20 m covering radius but **more points per unit area** (800 m^2/point vs
1039 m^2/point), i.e. it is denser, not better.

Counterfactual (offline projection, no runtime change)
------------------------------------------------------
For every channel with at least one clear attempt we rebuild the ladder over the
convex hull of the channel's *observed* attempt points (a stand-in for the same
feasible region), start from the first attempt, order the points with the same
greedy rule, and count steps / walking metres until the first point within 20 m
of the true source.  Three ladders are compared against the observed attempts:

  (obs) the recorded attempt sequence (reference);
  (cur) the shipped triangular lattice, a = 34.641 m;
  (sq)  a 28.284 m square lattice (same covering radius, denser);
  (hex28) a 28.284 m triangular lattice (covering radius 16.33 m, denser).

Cost model: every visit costs 3 s when it misses and 5 s when it hits, plus
walking at 5 m/s.  Projections, not measurements -- stated in the report.

Pre-registration (fixed before computing): GO iff some cell saves
>= 5 s/source and no cell gets worse; otherwise NO-GO.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.constants import CLEAR_RADIUS, MOVE_SPEED                  # noqa: E402
from geometry.fallback_cover import (LATTICE_SPACING_FACTOR,            # noqa: E402
                                     disk_lattice_cover, order_greedy)
from geometry.polygon import convex_hull                                # noqa: E402

FAIL_SECONDS = 3.0
HIT_SECONDS = 5.0
SQUARE_SPACING = CLEAR_RADIUS * math.sqrt(2.0)          # 28.284 m
DEFAULT_ROOT = "tuning_runs/ab_probe/production"
DEFAULT_CELLS = ("Q4_10", "Q4_13", "Q4_16")
PRE_REGISTRATION = {
    "go_threshold_s_per_source": 5.0,
    "condition": "some cell saves >= 5 s/source and no cell gets worse",
    "cost_model": {"failed_attempt_s": FAIL_SECONDS, "hit_attempt_s": HIT_SECONDS,
                   "move_speed_mps": MOVE_SPEED},
    "region_model": "convex hull of the channel's observed attempt points",
    "start_model": "first observed attempt position",
    "order_model": "geometry.fallback_cover.order_greedy from the start",
    "decided_before_computing": True,
}


def sha16(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def square_lattice(poly, spacing, radius=CLEAR_RADIUS):
    """Square lattice (axis aligned) of points whose 20 m disk meets ``poly``."""
    if not poly:
        return []
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, x1 = min(xs) - radius, max(xs) + radius
    y0, y1 = min(ys) - radius, max(ys) + radius
    out = []
    k = 0
    y = y0
    while y <= y1 + 1e-9:
        x = x0
        while x <= x1 + 1e-9:
            if point_polygon_distance(poly, (x, y)) <= radius + 1e-9:
                out.append((x, y))
            x += spacing
        y += spacing
        k += 1
    return out


def point_polygon_distance(poly, p):
    from geometry.polygon import contains_point
    if contains_point(poly, p, eps=-1e-12):
        return 0.0
    best = float("inf")
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        abx, aby = b[0] - a[0], b[1] - a[1]
        apx, apy = p[0] - a[0], p[1] - a[1]
        l2 = abx * abx + aby * aby
        t = 0.0 if l2 <= 1e-18 else max(0.0, min(1.0, (apx * abx + apy * aby) / l2))
        d = math.hypot(apx - t * abx, apy - t * aby)
        best = min(best, d)
    return best


def replay_ladder(points, start, truth):
    """Steps and walking metres until the first point within CLEAR_RADIUS."""
    if not points:
        return None
    order = order_greedy(points, start)
    walk = 0.0
    here = (float(start[0]), float(start[1]))
    for index, point in enumerate(order):
        walk += math.hypot(point[0] - here[0], point[1] - here[1])
        here = point
        if math.hypot(point[0] - truth[0], point[1] - truth[1]) <= CLEAR_RADIUS + 1e-9:
            steps = index + 1
            return {"steps": steps, "walk_m": walk,
                    "time_s": walk / MOVE_SPEED
                    + FAIL_SECONDS * (steps - 1) + HIT_SECONDS,
                    "hit_distance_m": math.hypot(point[0] - truth[0],
                                                 point[1] - truth[1])}
    return {"steps": None, "walk_m": walk, "time_s": None, "hit_distance_m": None,
            "exhausted": True, "points": len(order)}


def read_attempts(run_dir):
    """Positions of every clear attempt per channel, in order."""
    actions = list(csv.DictReader(open(run_dir / "actions.csv", encoding="utf-8")))
    truth = {}
    for record in json.loads((run_dir / "ground_truth.json")
                             .read_text(encoding="utf-8")):
        truth[int(record["channel"])] = (float(record["x"]), float(record["y"]),
                                         bool(record.get("directional")))
    attempts = defaultdict(list)
    for row in actions:
        if row["action_type"] != "clear":
            continue
        try:
            point = (float(row["target_x"]), float(row["target_y"]))
            channel = int(row["channel"])
        except (TypeError, ValueError):
            continue
        attempts[channel].append({"point": point,
                                  "t": float(row["virtual_time_before"])})
    return attempts, truth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--cells", default=",".join(DEFAULT_CELLS))
    parser.add_argument("--out", default="tuning_runs/fallback_lattice.json")
    parser.add_argument("--md", default="tuning_runs/FALLBACK_LATTICE.md")
    args = parser.parse_args()

    started = time.time()
    report = {
        "tool": "tools/probe_fallback_lattice.py",
        "tool_sha256_16": sha16(Path(__file__)),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": args.root,
        "constants": {
            "clear_radius_m": CLEAR_RADIUS,
            "move_speed_mps": MOVE_SPEED,
            "lattice_spacing_factor": LATTICE_SPACING_FACTOR,
            "shipped_triangular_spacing_m": CLEAR_RADIUS * LATTICE_SPACING_FACTOR,
            "shipped_row_spacing_m": (CLEAR_RADIUS * LATTICE_SPACING_FACTOR
                                      * math.sqrt(3.0) / 2.0),
            "shipped_covering_radius_m": CLEAR_RADIUS,
            "guarantee_spacing_triangular_m": CLEAR_RADIUS * math.sqrt(3.0),
            "guarantee_spacing_square_m": CLEAR_RADIUS * math.sqrt(2.0),
            "square_28_3_spacing_m": SQUARE_SPACING,
            "area_per_point_triangular_m2":
                math.sqrt(3.0) / 2.0 * (CLEAR_RADIUS * LATTICE_SPACING_FACTOR) ** 2,
            "area_per_point_square_28_3_m2": SQUARE_SPACING ** 2,
        },
        "pre_registration": PRE_REGISTRATION,
        "code_facts": [],
        "ladders": {
            "cur_triangular_34_64": "geometry.fallback_cover.disk_lattice_cover"
                                    "(poly, radius=20)",
            "sq_28_28": "square lattice, spacing 20*sqrt(2)",
            "hex_28_28": "triangular lattice via disk_lattice_cover(poly, radius=20/sqrt(3))",
        },
        "cells": OrderedDict(),
        "notes": [
            "Projection, not a measurement: the alternative ladders are replayed "
            "over the convex hull of the *observed* attempt points, starting at "
            "the first observed attempt; the real trajectory and the real "
            "feasible polygon would differ.",
            "The observed attempt sequence is reported as the reference; the "
            "shipped-lattice replay validates the region/order model.",
            "No runtime file is modified and no new episode is run.",
        ],
    }
    for rel, needle in (
            ("baseline/code/geometry/fallback_cover.py",
             "LATTICE_SPACING_FACTOR = math.sqrt(3.0)"),
            ("baseline/code/geometry/fallback_cover.py",
             "a = LATTICE_SPACING_FACTOR * radius"),
            ("baseline/code/geometry/fallback_cover.py",
             "h = a * math.sqrt(3.0) / 2.0"),
            ("baseline/code/geometry/fallback_cover.py", "def order_greedy"),
            ("baseline/code/geometry/constants.py", "CLEAR_RADIUS"),
    ):
        path = ROOT / rel
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        report["code_facts"].append({"file": rel, "needle": needle,
                                     "present": needle in text})

    # ---- data pass -------------------------------------------------------
    per_channel_rows = []
    cells = [item.strip().replace(":", "_")
             for item in args.cells.split(",") if item.strip()]
    for cell in cells:
        directories = sorted(glob.glob(str(ROOT / args.root / (cell + "_*"))))
        cell_rows = []
        for directory in directories:
            run = Path(directory)
            if not (run / "actions.csv").exists():
                continue
            attempts, truth = read_attempts(run)
            n_sources = len({int(name.split("_")[2]) for name in [run.name]})
            for channel, entries in attempts.items():
                if channel not in truth:
                    continue
                source = (truth[channel][0], truth[channel][1])
                points = [entry["point"] for entry in entries]
                distances = [math.hypot(p[0] - source[0], p[1] - source[1])
                             for p in points]
                hit_index = next((i for i, d in enumerate(distances)
                                  if d <= CLEAR_RADIUS + 1e-9), None)
                steps_obs = (hit_index + 1) if hit_index is not None else len(points)
                walk_obs = sum(math.hypot(points[i + 1][0] - points[i][0],
                                          points[i + 1][1] - points[i][1])
                               for i in range(len(points) - 1))
                observed = {
                    "steps": steps_obs, "walk_m": walk_obs,
                    "time_s": (walk_obs / MOVE_SPEED
                               + FAIL_SECONDS * max(0, steps_obs - 1)
                               + (HIT_SECONDS if hit_index is not None else 0.0)),
                    "hit_distance_m": (distances[hit_index]
                                       if hit_index is not None else None),
                    "succeeded": hit_index is not None,
                }
                steps_between = [math.hypot(points[i + 1][0] - points[i][0],
                                            points[i + 1][1] - points[i][1])
                                 for i in range(len(points) - 1)]
                hull = convex_hull([(p[0], p[1]) for p in points]) \
                    if len(points) >= 3 else list(points)
                start = points[0]
                hull_pts = [(float(p[0]), float(p[1])) for p in hull]
                region = hull_pts if len(hull_pts) >= 3 else list(points)
                ladders = {}
                for name, pts in (
                        ("cur_triangular_34_64",
                         disk_lattice_cover(region, radius=CLEAR_RADIUS)),
                        ("sq_28_28", square_lattice(region, SQUARE_SPACING)),
                        ("hex_28_28",
                         disk_lattice_cover(region,
                                            radius=CLEAR_RADIUS / math.sqrt(3.0)))):
                    ladders[name] = replay_ladder(pts, start, source)
                cell_rows.append({
                    "run": run.name, "channel": channel,
                    "directional": truth[channel][2],
                    "attempts": len(points),
                    "first_attempt_distance_m": distances[0],
                    "min_attempt_distance_m": min(distances),
                    "observed": observed,
                    "median_step_m": statistics.median(steps_between)
                    if steps_between else None,
                    "true_source_in_hull": point_polygon_distance(
                        region, source) <= 1e-9 if len(region) >= 3 else None,
                    "ladders": ladders,
                    "ladder_sizes": {
                        "cur_triangular_34_64":
                            len(disk_lattice_cover(region, radius=CLEAR_RADIUS)),
                        "sq_28_28": len(square_lattice(region, SQUARE_SPACING)),
                        "hex_28_28": len(disk_lattice_cover(
                            region, radius=CLEAR_RADIUS / math.sqrt(3.0))),
                    },
                })
        per_channel_rows.extend(cell_rows)
        hard = [row for row in cell_rows if row["attempts"] > 1]
        summary = {
            "episodes": len({row["run"] for row in cell_rows}),
            "channels_with_attempts": len(cell_rows),
            "hard_channels": len(hard),
            "long_tail_channels": len([r for r in hard if r["attempts"] > 10]),
            "observed_attempts": sum(row["attempts"] for row in cell_rows),
            "hard_observed_attempts": sum(row["attempts"] for row in hard),
            "median_step_m": statistics.median(
                [row["median_step_m"] for row in cell_rows
                 if row["median_step_m"] is not None])
            if any(row["median_step_m"] is not None for row in cell_rows) else None,
            "truth_outside_hull_share": (
                100.0 * sum(1 for row in hard if row["true_source_in_hull"] is False)
                / len(hard)) if hard else None,
            "ladders": {},
        }
        for ladder in ("cur_triangular_34_64", "sq_28_28", "hex_28_28"):
            steps = [row["ladders"][ladder]["steps"] for row in hard
                     if row["ladders"][ladder]["steps"] is not None]
            summary["ladders"][ladder] = {
                "channels_hit": len(steps),
                "channels_exhausted": len(hard) - len(steps),
                "mean_steps": statistics.mean(steps) if steps else None,
                "median_steps": statistics.median(steps) if steps else None,
                "max_steps": max(steps) if steps else None,
            }
        report["cells"][cell] = {"summary": summary, "channels": cell_rows}

    # ---- per-cell savings ------------------------------------------------
    savings = {}
    for cell, data in report["cells"].items():
        rows = [row for row in data["channels"] if row["attempts"] > 1]
        total = defaultdict(float)
        detail = {}
        for ladder in ("cur_triangular_34_64", "sq_28_28", "hex_28_28"):
            delta = 0.0
            worse = 0
            for row in rows:
                cur = row["ladders"]["cur_triangular_34_64"]["time_s"]
                alt = row["ladders"][ladder]["time_s"]
                if cur is None or alt is None:
                    continue
                delta += cur - alt
                worse += 1 if alt > cur else 0
            detail[ladder] = {"delta_time_s": delta, "worse_channels": worse}
        n_sources = 0
        for directory in sorted(glob.glob(str(ROOT / args.root / (cell + "_*")))):
            metrics = Path(directory) / "metrics.json"
            if metrics.exists():
                n_sources += int(json.loads(metrics.read_text(encoding="utf-8"))
                                 .get("sources_total") or 0)
        detail["sources_total"] = n_sources
        for ladder in ("sq_28_28", "hex_28_28"):
            detail[ladder]["saved_per_source_s"] = (
                detail[ladder]["delta_time_s"] / n_sources if n_sources else None)
        detail["cur_triangular_34_64"]["saved_per_source_s"] = 0.0
        savings[cell] = detail
    report["savings"] = savings
    best_cell = None
    for cell, detail in savings.items():
        for ladder in ("sq_28_28", "hex_28_28"):
            saved = detail[ladder]["saved_per_source_s"] or 0.0
            if best_cell is None or saved > best_cell[2]:
                best_cell = (cell, ladder, saved, detail[ladder]["worse_channels"])
    go = bool(best_cell and best_cell[2] >= PRE_REGISTRATION["go_threshold_s_per_source"]
              and not any((detail[ladder]["saved_per_source_s"] or 0.0) < 0
                          for cell, detail in savings.items()
                          for ladder in ("sq_28_28", "hex_28_28")))
    report["verdict"] = {
        "verdict": "GO" if go else "NO-GO",
        "best_cell": best_cell[0] if best_cell else None,
        "best_ladder": best_cell[1] if best_cell else None,
        "best_saved_per_source_s": best_cell[2] if best_cell else None,
        "threshold_s_per_source": PRE_REGISTRATION["go_threshold_s_per_source"],
        "any_cell_worse": bool(any((detail[ladder]["saved_per_source_s"] or 0.0) < 0
                                  for cell, detail in savings.items()
                                  for ladder in ("sq_28_28", "hex_28_28"))),
    }
    report["wall_seconds"] = round(time.time() - started, 2)
    out_path = ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    md_path = ROOT / args.md
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print("verdict: %s ; written %s and %s (%.1f s)"
          % (report["verdict"]["verdict"], out_path, md_path,
             report["wall_seconds"]))
    return 0


def render_markdown(report):
    lines = []
    add = lines.append
    add("# Q4 清除阶梯几何：现阶梯 vs 28.28 m 保证型格点（离线反事实）")
    add("")
    add("> 由 `tools/probe_fallback_lattice.py` 生成（脚本哈希 `%s`，生成于 %s）。"
        % (report["tool_sha256_16"], report["generated_utc"]))
    add("> **投影，不是实测**：替代阶梯在「该频道已尝试点的凸包」上重放、从第一次尝试位置出发；"
        "真实轨迹与真实可行域会不同。")
    add("")
    add("## 0. 预注册（先写后算）")
    add("")
    add("```json")
    add(json.dumps(report["pre_registration"], ensure_ascii=False, indent=1))
    add("```")
    add("")
    add("## 1. 现阶梯的实际几何（代码核实）")
    add("")
    c = report["constants"]
    add("| 项 | 值 |")
    add("|---|---|")
    add("| 成功半径 `CLEAR_RADIUS` | %.0f m |" % c["clear_radius_m"])
    add("| 格点间距因子（三角格点） | √3 ≈ %.3f |" % c["lattice_spacing_factor"])
    add("| **实测步距** `a = √3·r` | **%.3f m**（行距 %.1f m） |" %
        (c["shipped_triangular_spacing_m"], c["shipped_row_spacing_m"]))
    add("| 三角格点覆盖半径 `a/√3` | **%.1f m = r**（零余量，恰好保证） |"
        % c["shipped_covering_radius_m"])
    add("| 保证 20 m 覆盖所需的**三角**间距上限 | %.3f m |" %
        c["guarantee_spacing_triangular_m"])
    add("| 保证 20 m 覆盖所需的**方格**间距上限 | %.3f m |" %
        c["guarantee_spacing_square_m"])
    add("| 每点面积（现三角） / 28.28 m 方格 | %.0f m² / %.0f m² |" %
        (c["area_per_point_triangular_m2"], c["area_per_point_square_28_3_m2"]))
    add("")
    add("**结论（口径纠正）**：题目按**方格**公式给出 `s ≤ 20√2 = 28.28 m`；"
        "但代码实现是**三角格点**（`fallback_cover.LATTICE_SPACING_FACTOR = √3`），"
        "其覆盖半径为 `a/√3`，因此保证条件是 `a ≤ 20√3 = 34.641 m`。"
        "**现阶梯的步距 34.641 m 恰好等于该上限**（覆盖半径 = 20 m，零余量）——"
        "它已经是「保证型」，只是没有余量；而 28.28 m 方格在同为 20 m 覆盖半径的前提下"
        "**更密**（800 m²/点 vs 1039 m²/点，+30% 点数）。")
    add("")
    add("代码事实核对（%d/%d 命中）：" %
        (sum(1 for item in report["code_facts"] if item["present"]),
         len(report["code_facts"])))
    for item in report["code_facts"]:
        add("- `%s` → `%s` %s" % (item["file"], item["needle"],
                                  "命中" if item["present"] else "**未命中**"))
    add("")
    add("## 2. 运行数据交叉验证")
    add("")
    add("| 格 | 局数 | 有尝试的频道 | 其中多次尝试 | 长尾(>10 次) | 观测尝试总数 | 连续尝试步距中位 | 真源落在尝试点凸包外 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cell, data in report["cells"].items():
        s = data["summary"]
        add("| %s | %d | %d | %d | %d | %d | %s | %s |" %
            (cell, s["episodes"], s["channels_with_attempts"], s["hard_channels"],
             s["long_tail_channels"], s["observed_attempts"],
             "%.1f m" % s["median_step_m"] if s["median_step_m"] else "-",
             "%.0f%%" % s["truth_outside_hull_share"]
             if s["truth_outside_hull_share"] is not None else "-"))
    add("")
    add("## 3. 反事实：到首次命中的步数（多次尝试频道）")
    add("")
    add("| 格 | 阶梯 | 命中频道 | 未命中(耗尽) | 平均步数 | 中位步数 | 最大步数 |")
    add("|---|---|---:|---:|---:|---:|---:|")
    for cell, data in report["cells"].items():
        for ladder, values in data["summary"]["ladders"].items():
            add("| %s | %s | %d | %d | %s | %s | %s |" %
                (cell, ladder, values["channels_hit"], values["channels_exhausted"],
                 "%.1f" % values["mean_steps"] if values["mean_steps"] is not None else "-",
                 "%.1f" % values["median_steps"] if values["median_steps"] is not None else "-",
                 values["max_steps"] if values["max_steps"] is not None else "-"))
    add("")
    add("### 3b. 长尾（观测尝试 > 10 次）被削掉多少")
    add("")
    add("| 格 | 长尾频道数 | 观测尝试均值/最大 | 现阶梯步数均值 | sq_28_28 步数均值 | hex_28_28 步数均值 |")
    add("|---|---:|---|---:|---:|---:|")
    for cell, data in report["cells"].items():
        tail = [row for row in data["channels"] if row["attempts"] > 10]
        if not tail:
            continue

        def mean_steps(ladder):
            values = [row["ladders"][ladder]["steps"] for row in tail
                      if row["ladders"][ladder]["steps"] is not None]
            return statistics.mean(values) if values else None
        add("| %s | %d | %.1f / %d | %s | %s | %s |" %
            (cell, len(tail),
             statistics.mean(row["attempts"] for row in tail),
             max(row["attempts"] for row in tail),
             "%.1f" % mean_steps("cur_triangular_34_64")
             if mean_steps("cur_triangular_34_64") is not None else "-",
             "%.1f" % mean_steps("sq_28_28")
             if mean_steps("sq_28_28") is not None else "-",
             "%.1f" % mean_steps("hex_28_28")
             if mean_steps("hex_28_28") is not None else "-"))
    add("")
    add("## 4. 折算 s/源（每步 3 s 失败 + 5 s 命中 + 5 m/s 行走）")
    add("")
    add("| 格 | 阶梯 | 相对现阶梯的 Δ时间 (s) | 变差频道数 | **s/源** |")
    add("|---|---|---:|---:|---:|")
    for cell, detail in report["savings"].items():
        for ladder in ("sq_28_28", "hex_28_28"):
            add("| %s | %s | %+.0f | %d | **%+.2f** |" %
                (cell, ladder, detail[ladder]["delta_time_s"],
                 detail[ladder]["worse_channels"],
                 detail[ladder]["saved_per_source_s"] or 0.0))
    add("")
    add("## 5. 判定")
    add("")
    v = report["verdict"]
    add("- 预注册阈值：任一格 ≥ %.1f s/源且无格变差 ⇒ GO。" %
        v["threshold_s_per_source"])
    add("- 最佳组合：%s × %s = **%+.2f s/源**；任一格变差：%s。"
        % (v["best_cell"], v["best_ladder"], v["best_saved_per_source_s"] or 0.0,
           v["any_cell_worse"]))
    add("")
    add("**判定：%s**" % v["verdict"])
    add("")
    add("## 6. 复现命令")
    add("")
    add("```powershell")
    add("python -X utf8 tools/probe_fallback_lattice.py")
    add("python -X utf8 verification/check_model.py")
    add("```")
    add("")
    add("## 7. 边界")
    add("")
    for note in report["notes"]:
        add("- " + note)
    add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
