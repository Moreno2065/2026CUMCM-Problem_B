"""Can any observable feature predict the stop choice?  Quantify the ceiling.

Each labelled decision (from ``tools/stop_choice_labels.py``) carries the
realised consequence of taking the certificate stop instead of the policy's
choice at that decision: a positive gain means the certificate was cheaper.

Decision value of a rule R is the sum of those realised gains over the
decisions where R says "take the certificate"; "always work" scores 0 by
construction, and the oracle (which knows the sign of every gain) scores the
sum of all positive gains.

Reported:
  * how much is at stake on this dimension;
  * the leave-one-out value of the best single-observable-feature threshold;
  * the number of decision pairs with (near-)identical observable state but
    opposite outcomes - the part no observable policy can resolve, since a
    deterministic observable policy must answer identically to identical
    states.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

FEATURES = ("coverage_index", "n_unknown", "n_active", "n_ready", "n_confirmed",
            "dist_work", "dist_ring", "dist_ratio", "mean_mec_active")
STATE_KEY = ("coverage_index", "n_unknown", "n_active", "n_ready", "n_confirmed")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def value_of(rows, decide):
    """Sum of realised gains where the rule chooses the certificate."""
    return sum(row["certificate_gain"] for row in rows if decide(row))


def best_threshold(train, feature):
    best = None
    for value in sorted({row[feature] for row in train}):
        for direction in (1, -1):
            decide = (lambda row, v=value, d=direction:
                      (row[feature] >= v) if d > 0 else (row[feature] <= v))
            score = value_of(train, decide)
            if best is None or score > best[0]:
                best = (score, feature, value, direction)
    return best


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                 else "tuning_runs/stop_choice_labels.jsonl")
    rows = load(path)
    if not rows:
        print("no labels")
        return 1
    gains = [row["certificate_gain"] for row in rows]
    positive = [g for g in gains if g > 0]
    negative = [g for g in gains if g <= 0]
    print("labelled decisions: %d over %d cases" %
          (len(rows), len({(r["mode"], r["n"], r["seed"]) for r in rows})))
    print("certificate better in %d (%.0f%%)" %
          (len(positive), 100.0 * len(positive) / len(rows)))
    print("sum of positive gains (oracle value)      : %+8.0f s" % sum(positive))
    print("sum of all gains (always-certificate rule): %+8.0f s" % sum(gains))
    print("always-work rule                          : %+8.0f s" % 0.0)
    print("mean gain when certificate wins %+.0f s ; mean loss when it loses "
          "%+.0f s" % (statistics.mean(positive) if positive else 0.0,
                       statistics.mean(negative) if negative else 0.0))

    # Leave-one-out value of the best observable single-feature threshold.
    loo_value = 0.0
    picks = []
    for index, row in enumerate(rows):
        train = [r for j, r in enumerate(rows) if j != index]
        best = None
        for feature in FEATURES:
            candidate = best_threshold(train, feature)
            if candidate and (best is None or candidate[0] > best[0]):
                best = candidate
        _, feature, value, direction = best
        take = ((row[feature] >= value) if direction > 0
                else (row[feature] <= value))
        if take:
            loo_value += row["certificate_gain"]
        picks.append((feature, value, direction))
    print("\nleave-one-out observable threshold rule   : %+8.0f s "
          "(oracle is %+.0f s)" % (loo_value, sum(positive)))
    counts = {}
    for pick in picks:
        counts[pick] = counts.get(pick, 0) + 1
    top_rule, top_count = max(counts.items(), key=lambda kv: kv[1])
    print("   most often selected rule: %s (chosen %d/%d folds)"
          % (str(top_rule), top_count, len(picks)))

    # Identical observable state, opposite outcome.
    buckets = {}
    for row in rows:
        key = tuple(row[feature] for feature in STATE_KEY)
        buckets.setdefault(key, []).append(row)
    conflicts = 0
    conflict_rows = 0
    irreducible = 0.0
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        signs = {row["certificate_gain"] > 0 for row in group}
        if len(signs) > 1:
            conflicts += 1
            conflict_rows += len(group)
            # A deterministic observable policy must answer identically; the
            # best it can do is the larger side.
            pos = [r["certificate_gain"] for r in group
                   if r["certificate_gain"] > 0]
            neg = [r["certificate_gain"] for r in group
                   if r["certificate_gain"] <= 0]
            irreducible += (sum(neg) if len(pos) >= len(neg) else sum(pos))
    print("state buckets with conflicting outcomes  : %d (covering %d "
          "decisions)" % (conflicts, conflict_rows))
    print("value unreachable by any deterministic observable rule (upper "
          "estimate): %+.0f s" % irreducible)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
