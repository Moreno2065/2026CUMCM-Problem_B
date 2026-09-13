"""Audit how much of a Q4 episode is spent visiting the 25-point sparse mesh.

Reads one or more run directories (each containing ``api_log.jsonl``) and reports,
per run:
  * total travel (sum of straight-line /move legs, metres) and its seconds;
  * how many of the 25 fixed mesh points were actually visited (tolerance sweep);
  * travel attributable to the mesh visit sequence (open tour over visited mesh
    points, in visit order) and the corresponding seconds;
  * measurements taken at (or within tol of) mesh points, and how many distinct
    (mesh point, channel) pairs were witnessed there.

This is a measurement tool: it changes nothing and only reads artifacts.
Usage:
  python -X utf8 tools/audit_q4_mesh_visit.py <run_dir> [<run_dir> ...]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.q4_sparse_mesh import q4_sparse25_points  # noqa: E402

SPEED = 5.0


def _actions(api_log: Path):
    """Yield (virtual_time_s, endpoint, position_xy, channel, dt_move_s, dt_measure_s, dt_switch_s, dt_clear_s).

    The engine records no ``/move`` endpoint: movement is charged to the next
    action through ``dt.move``.
    """
    with api_log.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ep = rec.get("endpoint")
            if ep not in ("/measure", "/clear"):
                continue
            req = rec.get("request") or {}
            pos = req.get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            dt = rec.get("dt") or {}
            resp = rec.get("response") or {}
            yield (
                float(resp.get("virtual_time_s") or 0.0),
                ep,
                (float(pos["x"]), float(pos["y"])),
                req.get("channel"),
                float(dt.get("move") or 0.0),
                float(dt.get("measure") or 0.0),
                float(dt.get("switch") or 0.0),
                float(dt.get("clear") or 0.0),
            )


def audit(run_dir: Path) -> dict:
    api_log = run_dir / "api_log.jsonl"
    mesh = [(float(x), float(y)) for x, y in q4_sparse25_points()]

    total_move_s = 0.0
    mesh_move_s = 0.0
    visit_order: list[int] = []
    seen_points: set[int] = set()
    per_channel: dict[object, set[int]] = {}
    measures = 0
    measures_at_mesh = 0
    mesh_clear = 0

    for _t, ep, pos, ch, dt_move, _dtm, _dts, _dtc in _actions(api_log):
        total_move_s += dt_move
        best, best_d = None, 1e9
        for idx, mp in enumerate(mesh):
            d = math.dist(pos, mp)
            if d < best_d:
                best, best_d = idx, d
        at_mesh = best is not None and best_d <= 1.0
        if at_mesh:
            mesh_move_s += dt_move
            if best not in seen_points:
                seen_points.add(best)
                visit_order.append(best)
        if ep == "/measure":
            measures += 1
            if at_mesh:
                measures_at_mesh += 1
                per_channel.setdefault(ch, set()).add(best)
        elif ep == "/clear" and at_mesh:
            mesh_clear += 1

    coverage = sorted(
        ({"channel": ch, "witnessed_points": len(pts)} for ch, pts in per_channel.items()),
        key=lambda r: (-r["witnessed_points"], str(r["channel"])),
    )
    full = [r["channel"] for r in coverage if r["witnessed_points"] >= len(mesh)]

    return {
        "run": str(run_dir.relative_to(ROOT)),
        "total_move_s": round(total_move_s, 1),
        "total_travel_m": round(total_move_s * SPEED, 1),
        "mesh_points_total": len(mesh),
        "mesh_points_visited_le1m": len(seen_points),
        "mesh_move_s": round(mesh_move_s, 1),
        "mesh_travel_m": round(mesh_move_s * SPEED, 1),
        "measurements_total": measures,
        "measurements_at_mesh_le1m": measures_at_mesh,
        "clears_at_mesh_le1m": mesh_clear,
        "distinct_mesh_channel_witnesses": sum(len(v) for v in per_channel.values()),
        "channels_with_full_25_witnesses": full,
        "channel_witness_coverage": coverage[:8],
        "mesh_visit_order": visit_order,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = []
    for raw in argv[1:]:
        run_dir = Path(raw)
        if not run_dir.is_absolute():
            run_dir = ROOT / raw
        if not (run_dir / "api_log.jsonl").exists():
            print(f"skip (no api_log.jsonl): {raw}")
            continue
        rec = audit(run_dir)
        out.append(rec)
        print(
            "{run}\n"
            "  travel {total_travel_m} m ({total_move_s} s) | mesh-点动作移动 "
            "{mesh_travel_m} m ({mesh_move_s} s) | mesh visited {mesh_points_visited_le1m}/25\n"
            "  measures {measurements_total} ({measurements_at_mesh_le1m} at mesh) | clears@mesh "
            "{clears_at_mesh_le1m} | mesh×channel witnesses {distinct_mesh_channel_witnesses} | "
            "25/25 满覆盖频道 {channels_with_full_25_witnesses}".format(**rec)
        )
        print(f"  top witness coverage: {rec['channel_witness_coverage']}")
    if out:
        dest = ROOT / "tuning_runs" / "q4_mesh_visit_audit.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
