"""Phase-separation cost: how much travel goes between the certificate mesh and the rest?

For each run, every leg (the movement charged to an action) is classified by where
it starts and where it ends:

  * mesh -> mesh      the certificate tour itself,
  * other -> other    hunting / clearing / discovery inside the disk,
  * mesh -> other  \\  transition legs: leaving the mesh to do something else and
  * other -> mesh  /   coming back --- the "phase separation" overhead.

A large transition share means the policy keeps switching between the certificate
ring and the interior; a fused planner would collapse those legs.

Usage:
  python -X utf8 tools/phase_legs.py <run_dir> [...]
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.q4_sparse_mesh import q4_sparse25_points  # noqa: E402

SPEED = 5.0
TOL = 1.0


def analyse(run_dir: Path, n: int) -> dict | None:
    api = run_dir / "api_log.jsonl"
    if not api.exists():
        return None
    mesh = [(float(x), float(y)) for x, y in q4_sparse25_points()]

    def at_mesh(p):
        return any(math.dist(p, m) <= TOL for m in mesh)

    prev = (0.0, 0.0)
    buckets = {"mesh_mesh": 0.0, "mesh_other": 0.0, "other_mesh": 0.0, "other_other": 0.0}
    counts = {k: 0 for k in buckets}
    total = 0.0
    with api.open(encoding="utf-8") as fh:
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
            pos = (rec.get("request") or {}).get("position") or {}
            if "x" not in pos or "y" not in pos:
                continue
            cur = (float(pos["x"]), float(pos["y"]))
            mv = float((rec.get("dt") or {}).get("move") or 0.0)
            a, b = at_mesh(prev), at_mesh(cur)
            key = ("mesh" if a else "other") + "_" + ("mesh" if b else "other")
            buckets[key] += mv
            counts[key] += 1
            total += mv
            prev = cur

    transition = buckets["mesh_other"] + buckets["other_mesh"]
    return {
        "run": str(run_dir.relative_to(ROOT)),
        "n": n,
        "move_total_s": round(total, 1),
        "mesh_mesh_s": round(buckets["mesh_mesh"], 1),
        "other_other_s": round(buckets["other_other"], 1),
        "transition_s": round(transition, 1),
        "transition_share_pct": round(transition / total * 100, 1) if total else None,
        "counts": counts,
    }


def main(argv: list[str]) -> int:
    targets: list[tuple[Path, int]] = []
    for raw in argv[1:]:
        if "=" in raw and raw.split("=")[0].isdigit():
            n_str, pattern = raw.split("=", 1)
            n = int(n_str)
        else:
            pattern, n = raw, 16
        p = Path(pattern)
        if not p.is_absolute():
            p = ROOT / pattern
        targets.extend((Path(m), n) for m in sorted(glob.glob(str(p))))

    out = []
    print("{:<40}{:>4}{:>11}{:>11}{:>11}{:>11}{:>10}".format(
        "run", "N", "move_total", "mesh-mesh", "other-other", "transition", "trans%"))
    for d, n in targets:
        rec = analyse(d, n)
        if not rec:
            continue
        out.append(rec)
        print("{run:<40}{n:>4}{move_total_s:>11.1f}{mesh_mesh_s:>11.1f}{other_other_s:>11.1f}"
              "{transition_s:>11.1f}{transition_share_pct:>10.1f}".format(**rec))
    if out:
        dest = ROOT / "tuning_runs" / "phase_legs.json"
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
