"""Probe: can a *larger, witness-supported* delta shrink the Q4 certificate?

Motivation (captain, 2026-09-12):
  ``certificate.q4_certify_point(x, A, delta)`` is sound for any delta: if
  ``B(x, delta)`` sits inside ``conv(A_delta(x))`` with ``A_delta(x) = {p in A :
  |p - x| <= R_eff - delta}``, then no uncleared directional source can lie in
  ``B(x, delta)``.  The engine pins ``delta = Q4_DELTA = 370``, which forces
  centers spaced <= 2*delta = 740 m, i.e. ~24 centres to cover Omega --- the same
  order as the 25-point sparse mesh that costs ~16 km of travel per Q4/10 run.
  A larger delta (witnesses available closer to the centre) needs far fewer
  centres and therefore a much shorter tour.

This tool is pure offline analysis over measurements already taken in a real run:
  * witness set per channel = every no_signal measurement of that channel;
  * candidate centres = the positions where those measurements were taken;
  * for delta in {370, 450, 500, 550, 600, 630}: certify each (centre, channel)
    with the *existing* ``q4_certify_point``, then greedily cover Omega with the
    certified centres (``q3_certified(..., cover_r=delta)`` for the cover test);
  * report per delta: mean/max centres needed, tour length of the selected
    centres (nearest neighbour + 2-opt, open path from origin) and the implied
    travel seconds vs the measured mesh travel.

Usage:
  python -X utf8 tools/adaptive_delta_probe.py <run_dir> [<run_dir> ...]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from geometry.certificate import q3_certified, q4_certify_point  # noqa: E402

SPEED = 5.0
DELTAS = (370.0, 450.0, 500.0, 550.0, 600.0, 630.0)
OMEGA_R = 1800.0


def _no_signal_by_channel(api_log: Path) -> dict[object, list[tuple[float, float]]]:
    out: dict[object, list[tuple[float, float]]] = {}
    for line in api_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("endpoint") != "/measure":
            continue
        if (rec.get("response") or {}).get("measure_result") != "no_signal":
            continue
        req = rec.get("request") or {}
        pos = req.get("position") or {}
        if "x" not in pos or "y" not in pos:
            continue
        out.setdefault(req.get("channel"), []).append((float(pos["x"]), float(pos["y"])))
    return out


def _cover_ok(centers: list[tuple[float, float]], delta: float) -> bool:
    if not centers:
        return False
    return bool(q3_certified(centers, omega_radius=OMEGA_R, cover_r=delta)["certified"])


def _greedy_cover(certified_by_delta: dict[float, set[tuple[float, float]]],
                  delta: float) -> list[tuple[float, float]]:
    """Greedy set cover over Omega sampled on a polar grid (cheap, monotone).

    A point g is covered by centre x when |g - x| <= delta.  Sampling is dense
    enough (30 m rings / 3 deg) that this over-estimates required centres by a
    negligible amount; the exact cover is re-checked with q3_certified.
    """
    cands = sorted(certified_by_delta[delta])
    if not cands:
        return []
    samples: list[tuple[float, float]] = []
    r = 0.0
    while r <= OMEGA_R:
        n = max(8, int(2 * math.pi * max(r, 60.0) / 60.0))
        for k in range(n):
            a = 2 * math.pi * k / n
            samples.append((r * math.cos(a), r * math.sin(a)))
        r += 30.0
    remaining = set(range(len(samples)))
    chosen: list[tuple[float, float]] = []
    while remaining:
        best, best_gain = None, 0
        for c in cands:
            gain = 0
            for i in remaining:
                if math.dist(c, samples[i]) <= delta:
                    gain += 1
                    if gain <= best_gain:
                        break
            if gain > best_gain:
                best, best_gain = c, gain
        if best is None or best_gain == 0:
            break
        chosen.append(best)
        remaining = {i for i in remaining if math.dist(best, samples[i]) > delta}
    if not _cover_ok(chosen, delta):  # exact re-check; if it fails, report as-is
        return chosen + [(-1.0, -1.0)]
    return chosen


def _tour_len(centers: list[tuple[float, float]]) -> float:
    pts = [(0.0, 0.0)] + list(centers)
    if len(pts) <= 2:
        return 0.0
    order = [0]
    left = set(range(1, len(pts)))
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda i: math.dist(last, pts[i]))
        order.append(nxt)
        left.discard(nxt)
    improved = True
    while improved:  # 2-opt
        improved = False
        for i in range(1, len(order) - 2):
            for j in range(i + 1, len(order) - 1):
                a, b = pts[order[i - 1]], pts[order[i]]
                c, d = pts[order[j]], pts[order[j + 1]]
                if math.dist(a, b) + math.dist(c, d) > math.dist(a, c) + math.dist(b, d) + 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
    return sum(math.dist(pts[order[i]], pts[order[i + 1]]) for i in range(len(order) - 1))


def probe(run_dir: Path) -> dict:
    per_ch = _no_signal_by_channel(run_dir / "api_log.jsonl")
    res: dict[str, object] = {"run": str(run_dir.relative_to(ROOT)), "channels": len(per_ch),
                              "witnesses": {str(k): len(v) for k, v in per_ch.items()},
                              "by_delta": {}}
    for delta in DELTAS:
        certified: set[tuple[float, float]] = set()
        for _ch, pts in per_ch.items():
            for x in set(pts):
                if any(math.dist(x, p) <= 1.0 for p in ()):  # placeholder, no-op
                    continue
                if q4_certify_point(x, pts, delta=delta)["certified"]:
                    certified.add(x)
        chosen = _greedy_cover({delta: certified}, delta)
        failed = (-1.0, -1.0) in chosen
        pts_for_tour = [c for c in chosen if c != (-1.0, -1.0)]
        tl = _tour_len(pts_for_tour)
        res["by_delta"][str(int(delta))] = {
            "centres_available": len(certified),
            "centres_chosen": len(pts_for_tour),
            "cover_exact_ok": (not failed) and bool(pts_for_tour),
            "tour_m": round(tl, 1),
            "tour_s": round(tl / SPEED, 1),
        }
    return res


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
            print(f"skip: {raw}")
            continue
        rec = probe(run_dir)
        out.append(rec)
        print(f"{rec['run']}  channels={rec['channels']}")
        for d, v in rec["by_delta"].items():
            print(
                "  delta={:>3}  available={:>3}  chosen={:>3}  cover_ok={}  tour={:>7.1f} m ({:>6.1f} s)".format(
                    d, v["centres_available"], v["centres_chosen"], v["cover_exact_ok"],
                    v["tour_m"], v["tour_s"]
                )
            )
    dest = ROOT / "tuning_runs" / "adaptive_delta_probe.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
