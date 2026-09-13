# -*- coding: utf-8 -*-
"""Independent audit of the six captain decision tools and their headline numbers.

Read-only: nothing under tools/ is modified.  Every number below is recomputed
by this file's own code (own api_log parser, own MST, own Held-Karp, own
nearest-neighbour + 2-opt + or-opt, own precedence models, own mesh geometry).
The frozen tool outputs are read only to build the comparison table.

Run:
  python -X utf8 tools/audit_captain_tools.py
"""
from __future__ import annotations

import itertools
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEED = 5.0


# ---------------------------------------------------------------- mesh ----
def mesh25():
    pts = [(0.0, 0.0)]
    for k in range(12):
        a = math.radians(15.0 + 30.0 * k)
        pts.append((950.0 * math.cos(a), 950.0 * math.sin(a)))
    for k in range(12):
        a = math.radians(30.0 * k)
        pts.append((1870.0 * math.cos(a), 1870.0 * math.sin(a)))
    return pts


# ----------------------------------------------------------- api log ------
def load_actions(run_dir):
    rows = []
    with (run_dir / "api_log.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            req = rec.get("request") or {}
            pos = req.get("position") or {}
            rows.append({
                "t": float((rec.get("response") or {}).get("virtual_time_s") or 0.0),
                "ep": rec.get("endpoint"),
                "pos": (float(pos["x"]), float(pos["y"]))
                if "x" in pos and "y" in pos else None,
                "ch": req.get("channel"),
                "dt": rec.get("dt") or {},
                "resp": rec.get("response") or {},
            })
    return rows


def recon(run_dir, actions):
    s = {k: 0.0 for k in ("move", "measure", "switch", "clear")}
    for a in actions:
        for k in s:
            s[k] += float(a["dt"].get(k) or 0.0)
    m = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    n_actions_csv = 0
    ac = run_dir / "actions.csv"
    if ac.is_file():
        n_actions_csv = max(0, len(ac.read_text(encoding="utf-8").splitlines()) - 1)
    return {
        "sum_dt_move_s": round(s["move"], 4),
        "metrics_T_move": m.get("T_move"),
        "diff_move": round(s["move"] - float(m.get("T_move") or 0.0), 6),
        "sum_dt_measure_s": round(s["measure"], 4),
        "metrics_T_measure": m.get("T_measure"),
        "diff_measure": round(s["measure"] - float(m.get("T_measure") or 0.0), 6),
        "sum_dt_switch_s": round(s["switch"], 4),
        "metrics_T_switch": m.get("T_switch"),
        "diff_switch": round(s["switch"] - float(m.get("T_switch") or 0.0), 6),
        "sum_dt_clear_s": round(s["clear"], 4),
        "metrics_T_clear": m.get("T_clear"),
        "diff_clear": round(s["clear"] - float(m.get("T_clear") or 0.0), 6),
        "sum_all_four_s": round(sum(s.values()), 4),
        "metrics_T_ledger_sum": m.get("T_ledger_sum"),
        "diff_ledger": round(sum(s.values()) - float(m.get("T_ledger_sum") or 0.0), 6),
        "n_api_records": len(actions),
        "n_actions_csv_rows": n_actions_csv,
    }


def stop_counts(actions):
    """Three dedup conventions on the (measure|clear) position sequence."""
    a = [x for x in actions if x["ep"] in ("/measure", "/clear") and x["pos"]]
    no_dedup = len(a)
    lb = []          # route_lb: collapse consecutive equal positions only
    for x in a:
        if not lb or math.dist(lb[-1], x["pos"]) > 1e-9:
            lb.append(x["pos"])
    prec = []        # route_lb_prec: collapse consecutive equal pos AND same kind
    kinds = []
    for x in a:
        if prec and math.dist(prec[-1], x["pos"]) <= 1e-9 and kinds[-1] == x["ep"]:
            continue
        prec.append(x["pos"])
        kinds.append(x["ep"])
    return {"no_dedup": no_dedup, "route_lb_rule": len(lb),
            "route_lb_prec_rule": len(prec)}


# --------------------------------------------------- mesh attribution -----
def mesh_attribution(run_dir, actions, tol=1.0):
    mesh = mesh25()
    total = 0.0
    at_mesh = 0.0
    visit = []
    seen = set()
    for x in actions:
        mv = float(x["dt"].get("move") or 0.0)
        total += mv
        if x["ep"] not in ("/measure", "/clear") or not x["pos"]:
            continue
        d, idx = min(((math.dist(x["pos"], mp), i) for i, mp in enumerate(mesh)))
        if d <= tol:
            at_mesh += mv
            if idx not in seen:
                seen.add(idx)
                visit.append(idx)
    # fairer alternative: only the part of each leg that is "on the mesh tour"
    tour_m = 0.0
    for i in range(1, len(visit)):
        tour_m += math.dist(mesh[visit[i - 1]], mesh[visit[i]])
    return {
        "total_move_s": round(total, 1),
        "dest_at_mesh_move_s": round(at_mesh, 1),
        "dest_at_mesh_travel_m": round(at_mesh * SPEED, 1),
        "mesh_points_visited_le1m": len(seen),
        "mesh_visit_order_len": len(visit),
        "mesh_tour_only_m": round(tour_m, 1),
    }


# ------------------------------------------------------------- MST --------
def mst(points):
    n = len(points)
    if n < 2:
        return 0.0, []
    inside = {0}
    best = [math.dist(points[0], points[i]) for i in range(n)]
    par = [0] * n
    edges = []
    total = 0.0
    while len(inside) < n:
        nxt = min((i for i in range(n) if i not in inside), key=lambda i: best[i])
        total += best[nxt]
        edges.append((par[nxt], nxt, best[nxt]))
        inside.add(nxt)
        for i in range(n):
            if i not in inside:
                d = math.dist(points[nxt], points[i])
                if d < best[i]:
                    best[i] = d
                    par[i] = nxt
    return total, edges


def held_karp(points):
    """Exact open Hamiltonian path from index 0, free end."""
    n = len(points)
    if n == 1:
        return 0.0
    if n == 2:
        return math.dist(points[0], points[1])
    dist = [[math.dist(a, b) for b in points] for a in points]
    full = 1 << (n - 1)
    INF = float("inf")
    dp = [[INF] * (n - 1) for _ in range(full)]
    for j in range(n - 1):
        dp[1 << j][j] = dist[0][j + 1]
    for mask in range(full):
        for j in range(n - 1):
            cur = dp[mask][j]
            if cur == INF or not (mask >> j) & 1:
                continue
            for k in range(n - 1):
                if (mask >> k) & 1:
                    continue
                v = cur + dist[j + 1][k + 1]
                if v < dp[mask | (1 << k)][k]:
                    dp[mask | (1 << k)][k] = v
    return min(dp[full - 1])


# ------------------------------------------------------ route models ------
def build_stops(actions):
    stops, kinds, chans = [], [], []
    for x in actions:
        if x["ep"] not in ("/measure", "/clear") or not x["pos"]:
            continue
        if stops and math.dist(stops[-1], x["pos"]) <= 1e-9 and kinds[-1] == x["ep"]:
            continue
        stops.append(x["pos"])
        kinds.append(x["ep"])
        chans.append(x["ch"])
    return stops, kinds, chans


def preds_strict(kinds, chans):
    preds = [set() for _ in kinds]
    seen = {}
    for i, (k, c) in enumerate(zip(kinds, chans)):
        if k == "/measure":
            seen.setdefault(c, []).append(i)
        else:
            preds[i] |= set(seen.get(c, []))
    return preds


def preds_first(kinds, chans):
    """More realistic: a clear needs *at least one* earlier localization of the
    channel -- modelled as: the clear must follow the first prior measure."""
    preds = [set() for _ in kinds]
    first = {}
    for i, (k, c) in enumerate(zip(kinds, chans)):
        if k == "/measure":
            first.setdefault(c, i)
        else:
            j = first.get(c)
            if j is not None:
                preds[i].add(j)
    return preds


def preds_last(kinds, chans):
    """Relaxation: only the most recent prior measure of the channel must
    precede the clear (the earlier ones are incidental)."""
    preds = [set() for _ in kinds]
    last = {}
    for i, (k, c) in enumerate(zip(kinds, chans)):
        if k == "/measure":
            last[c] = i
        else:
            j = last.get(c)
            if j is not None:
                preds[i].add(j)
    return preds


def preds_none(kinds, chans):
    return [set() for _ in kinds]


def plen(pts, order):
    return sum(math.dist(pts[order[i]], pts[order[i + 1]])
               for i in range(len(order) - 1))


def feasible(order, preds):
    pos = {n: i for i, n in enumerate(order)}
    return all(pos[u] < pos[v] for v, ps in enumerate(preds) for u in ps)


def greedy(pts, preds):
    n = len(pts) - 1
    placed, order = {0}, [0]
    while len(order) < n + 1:
        cur = pts[order[-1]]
        cand = [v for v in range(1, n + 1) if v not in placed and preds[v] <= placed]
        if not cand:
            cand = [v for v in range(1, n + 1) if v not in placed]
        if not cand:
            break
        best = min(cand, key=lambda v: math.dist(cur, pts[v]))
        order.append(best)
        placed.add(best)
    return order


def or_opt(pts, order, preds, rounds=4):
    n = len(order)
    for _ in range(rounds):
        improved = False
        for i in range(1, n):
            node = order[i]
            rest = order[:i] + order[i + 1:]
            base = plen(pts, order)
            bo, bl = order, base
            for k in range(1, len(rest)):
                cand = rest[:k] + [node] + rest[k:]
                ln = plen(pts, cand)
                if ln + 1e-9 < bl and feasible(cand, preds):
                    bo, bl = cand, ln
            if bl + 1e-9 < base:
                order = bo
                improved = True
        if not improved:
            break
    return order


def route_models(run_dir, actions):
    stops, kinds, chans = build_stops(actions)
    pts = [(0.0, 0.0)] + stops
    out = {"stops": len(stops)}
    for name, fn in (("strict_all_prior_measures", preds_strict),
                     ("first_prior_measure_only", preds_first),
                     ("last_prior_measure_only", preds_last),
                     ("unconstrained", preds_none)):
        raw = fn(kinds, chans)
        preds = [set()] + [{u + 1 for u in p} for p in raw]
        order = or_opt(pts, greedy(pts, preds), preds)
        ok = feasible(order, preds)
        out[name] = {
            "precedence_edges": sum(len(p) for p in preds),
            "path_m": round(plen(pts, order), 1),
            "path_s": round(plen(pts, order) / SPEED, 1),
            "feasible_assert": bool(ok),
        }
    return out


# ------------------------------------------------------- tail cost --------
def tail(actions):
    buckets = {"clear_ok": 0.0, "clear_fail": 0.0, "measure": 0.0, "switch": 0.0,
               "other": 0.0}
    n_ok = n_fail = n_meas = 0
    total = 0.0
    first_ok_t = last_ok_t = None
    after_first = 0.0
    after_last = 0.0
    for x in actions:
        mv = float(x["dt"].get("move") or 0.0)
        total += mv
        t = x["t"]
        if x["ep"] == "/clear":
            if x["resp"].get("clear_result") == "success":
                buckets["clear_ok"] += mv
                n_ok += 1
                if first_ok_t is None:
                    first_ok_t = t
                last_ok_t = t
            else:
                buckets["clear_fail"] += mv
                n_fail += 1
        elif x["ep"] == "/measure":
            buckets["measure"] += mv
            n_meas += 1
        elif x["ep"] == "/switch_channel":
            buckets["switch"] += mv
        else:
            buckets["other"] += mv
    # two readings of "after the last success"
    seen_ok = False
    cur_last = None
    for x in actions:
        mv = float(x["dt"].get("move") or 0.0)
        t = x["t"]
        if x["ep"] == "/clear" and x["resp"].get("clear_result") == "success":
            cur_last = t
            seen_ok = True
            continue
        if seen_ok and cur_last is not None and t > cur_last:
            after_first += mv
    if last_ok_t is not None:
        for x in actions:
            if x["t"] > last_ok_t:
                after_last += float(x["dt"].get("move") or 0.0)
    return {
        "move_total_s": round(total, 1),
        "clear_success_move_s": round(buckets["clear_ok"], 1),
        "clear_fail_move_s": round(buckets["clear_fail"], 1),
        "measure_move_s": round(buckets["measure"], 1),
        "n_clear_success": n_ok, "n_clear_fail": n_fail, "n_measure": n_meas,
        "after_all_successes_have_started_s": round(after_first, 1),
        "after_last_success_s": round(after_last, 1),
    }


def main():
    rep = {"inputs": {}, "headlines": {}, "tools": {}}

    q4_10 = ROOT / "tuning_runs" / "ab_probe" / "production" / "Q4_10_101"
    q4_16 = ROOT / "tuning_runs" / "ab_probe" / "production" / "Q4_16_101"
    fv3_q4_10 = ROOT / "tuning_runs" / "final_recommended_v3" / "Q4_10_101"
    fv3_q4_16 = ROOT / "tuning_runs" / "final_recommended_v3" / "Q4_16_101"

    a10 = load_actions(q4_10)
    a16 = load_actions(q4_16)
    rep["inputs"] = {
        "Q4_10_101": {"dir": str(q4_10.relative_to(ROOT)),
                      "recon": recon(q4_10, a10),
                      "stops": stop_counts(a10),
                      "mesh": mesh_attribution(q4_10, a10)},
        "Q4_16_101": {"dir": str(q4_16.relative_to(ROOT)),
                      "recon": recon(q4_16, a16),
                      "stops": stop_counts(a16),
                      "mesh": mesh_attribution(q4_16, a16)},
    }
    # cross-check the two run dirs used by different tools for the same episode
    m10 = json.loads((q4_10 / "metrics.json").read_text(encoding="utf-8"))
    m10b = json.loads((fv3_q4_10 / "metrics.json").read_text(encoding="utf-8"))
    m16 = json.loads((q4_16 / "metrics.json").read_text(encoding="utf-8"))
    m16b = json.loads((fv3_q4_16 / "metrics.json").read_text(encoding="utf-8"))
    rep["run_dir_equivalence"] = {
        "Q4_10_101 ab_probe_vs_final_recommended_v3 T_total_virtual":
            [m10.get("T_total_virtual"), m10b.get("T_total_virtual")],
        "Q4_16_101 ab_probe_vs_final_recommended_v3 T_total_virtual":
            [m16.get("T_total_virtual"), m16b.get("T_total_virtual")],
    }

    # ---- headline (b): MST over origin + mesh --------------------------
    mesh = mesh25()
    pts = [(0.0, 0.0)] + mesh
    m, edges = mst(pts)
    deg = {}
    for u, v, _w in edges:
        deg[u] = deg.get(u, 0) + 1
        deg[v] = deg.get(v, 0) + 1
    max_edge = max(math.dist(pts[i], pts[j])
                   for i in range(len(pts)) for j in range(len(pts)) if i != j)
    hk_inner = held_karp([(0.0, 0.0)] + mesh[1:13])
    hk_outer = held_karp([(0.0, 0.0)] + mesh[13:25])
    is_path = all(d <= 2 for d in deg.values())
    rep["headlines"]["b_mst_origin_plus_mesh_m"] = round(m, 1)
    rep["headlines"]["b_mst_is_hamiltonian_path"] = is_path
    rep["headlines"]["b_mst_degrees"] = {str(k): v for k, v in sorted(deg.items())}
    rep["headlines"]["b_origin_degree"] = deg.get(0, 0)
    rep["headlines"]["b_mst_minus_diameter_m"] = round(m - max_edge, 1)
    rep["headlines"]["b_held_karp_inner_m"] = round(hk_inner, 1)
    rep["headlines"]["b_held_karp_outer_m"] = round(hk_outer, 1)
    rep["headlines"]["b_inner_plus_outer_sum_m"] = round(hk_inner + hk_outer, 1)
    rep["headlines"]["b_note"] = (
        "an open Hamiltonian path is itself a spanning tree, so MST is valid "
        "for the path too; MST-minus-diameter is valid but weaker")

    # reproduce mesh_tour_floor.py's ring construction to expose the root cause
    rings = sorted(mesh, key=lambda p: math.hypot(*p))
    t_inner, t_outer = rings[:12], rings[12:]
    rep["headlines"]["b_tool_ring_split_debug"] = {
        "rings_len": len(rings),
        "tool_inner_len": len(t_inner),
        "tool_outer_len": len(t_outer),
        "tool_inner_has_origin_twice":
            any(math.dist(p, (0.0, 0.0)) <= 1e-12 for p in t_inner),
        "tool_inner_radii": sorted(round(math.hypot(*p), 1) for p in t_inner),
        "tool_outer_radii": sorted(round(math.hypot(*p), 1) for p in t_outer),
        "hk_tool_inner_reproduced_m": round(
            held_karp([(0.0, 0.0)] + t_inner), 1),
        "hk_tool_outer_reproduced_m": round(
            held_karp([(0.0, 0.0)] + t_outer), 1),
    }

    # ---- headline (c): precedence models --------------------------------
    rep["tools"]["route_lb_prec"] = {
        "Q4_16_101": route_models(q4_16, a16),
        "Q4_10_101": route_models(q4_10, a10),
    }
    act16 = sum(float(x["dt"].get("move") or 0.0) for x in a16)
    rep["headlines"]["c_actual_move_s_Q4_16_101"] = round(act16, 1)

    # ---- headline (d): tail -------------------------------------------------
    rep["tools"]["q4_tail_cost"] = {
        "Q4_16_101": tail(a16), "Q4_16_202": tail(load_actions(
            ROOT / "tuning_runs" / "ab_probe" / "production" / "Q4_16_202")),
        "Q4_16_303": tail(load_actions(
            ROOT / "tuning_runs" / "ab_probe" / "production" / "Q4_16_303")),
        "Q4_16_404": tail(load_actions(
            ROOT / "tuning_runs" / "ab_probe" / "production" / "Q4_16_404")),
        "Q4_10_101": tail(a10),
    }
    t16 = [rep["tools"]["q4_tail_cost"]["Q4_16_%d" % s]
           for s in (101, 202, 303, 404)]
    rep["headlines"]["d_clear_fail_range_s"] = [
        min(x["clear_fail_move_s"] for x in t16),
        max(x["clear_fail_move_s"] for x in t16)]
    rep["headlines"]["d_measure_move_range_s_n16"] = [
        min(x["measure_move_s"] for x in t16),
        max(x["measure_move_s"] for x in t16)]
    rep["headlines"]["d_measure_move_Q4_10_101_s"] = \
        rep["tools"]["q4_tail_cost"]["Q4_10_101"]["measure_move_s"]

    # ---- headline (a): mesh attribution, correct pairing -----------------
    rep["headlines"]["a_mesh_travel_Q4_10_101_m"] = \
        rep["inputs"]["Q4_10_101"]["mesh"]["dest_at_mesh_travel_m"]
    rep["headlines"]["a_mesh_travel_Q4_16_101_m"] = \
        rep["inputs"]["Q4_16_101"]["mesh"]["dest_at_mesh_travel_m"]

    dest = ROOT / "tuning_runs" / "captain_tools_audit.json"
    dest.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:6000])
    print("\nwrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
