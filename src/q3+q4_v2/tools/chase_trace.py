"""Chase forensics from the decision trace: what does each Q4 localization
decision actually buy?

Reads ``decision_trace.jsonl`` of one run and reports, per ACTIVE-channel
decision, the selected candidate (kind, travel, gain proxy, cross-angle value)
plus the observed MEC radius before/after, so the policy's localization
behaviour can be judged against the geometry it is supposed to exploit.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path


def load(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    path = Path(sys.argv[1])
    trace = load(path)
    obs = []
    with open(path.parent / "observations.csv", encoding="utf-8") as handle:
        import csv
        for row in csv.DictReader(handle):
            obs.append(row)
    radius = {}
    for row in obs:
        radius[(row["channel"], float(row.get("virtual_time") or 0))] = row

    kinds = Counter()
    travel_by_kind = Counter()
    angle_by_kind = {}
    for row in trace:
        if row.get("policy_mode") != "learned_search_active":
            continue
        selected = row.get("selected") or {}
        kind = selected.get("kind", "?")
        cost = float(selected.get("cost") or 0.0)
        kinds[kind] += 1
        travel_by_kind[kind] += cost
    total = sum(travel_by_kind.values())
    print("decisions: %d, selected cost sum %.0f s" % (sum(kinds.values()), total))
    for kind, count in kinds.most_common():
        print("   %-18s %4d  cost_sum %7.0f s" % (kind, count,
                                                  travel_by_kind[kind]))
    # candidate ranking quality: was the selected the best by gain/cost?
    regret = []
    for row in trace:
        if row.get("policy_mode") != "learned_search_active":
            continue
        cands = row.get("candidates") or []
        selected = row.get("selected") or {}
        if len(cands) < 2:
            continue
        best = max(cands, key=lambda c: float(c.get("score") or -1e9))
        if best.get("point") != selected.get("point"):
            continue
        scores = sorted((float(c.get("score") or 0.0) for c in cands),
                        reverse=True)
        regret.append(scores[0] - scores[1] if len(scores) > 1 else 0.0)
    if regret:
        regret.sort()
        print("top-1 vs top-2 score margin: median %.2f p90 %.2f" %
              (regret[len(regret) // 2], regret[int(0.9 * len(regret)) - 1]))


if __name__ == "__main__":
    main()
