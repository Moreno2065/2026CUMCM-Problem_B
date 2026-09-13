"""Is the candidate-choice label a function of observable state?

Input: ``tuning_runs/action_value_labels.jsonl`` produced by
``tools/action_value_labels.py``.  Every row is one (decision, action) pair with
``delta = production_total - total(action)`` in seconds; ``delta > 0`` means the
action was cheaper than what production did at that step, and the incumbent
(production's own action) is present in every choice set with ``delta = 0``.

This script answers three questions, in order:

1. **How much is at stake?**  Candidate spread, oracle value of a perfect
   one-step choice, how often production was already optimal.
2. **Is the label observable?**  Buckets of identical observable state whose
   label disagrees: any deterministic policy that reads only those features
   must answer identically to identical states, so those buckets cap what any
   such policy can reach.
3. **Can a small model capture it?**  Leave-one-decision-out and
   leave-one-episode-out evaluation of a depth<=3 tree and a linear model over
   a fixed feature list built only from online-observable quantities.  The
   reported value is the sum of realised ``delta`` of the chosen action, i.e.
   the label-space value of the rule; it is *not* a whole-episode policy gain
   (if several decisions changed at once the total is not the sum), which is
   why the oracle number is printed next to it as the ceiling of this
   experiment.

Diagnostic only (never usable online, never inside the model): the last block
repeats the evaluation with the source count ``n`` added to the features, to
show how much of the label lives outside the observable state.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text

ROOT = Path(__file__).resolve().parents[1]

STATE_FEATURES = (
    "step", "t_elapsed", "n_active", "n_ready", "n_unknown", "n_cleared",
    "n_certified", "n_confirmed", "cov_index", "cov_remaining", "d_active",
    "d_ready", "mec_mean", "mec_min", "mec_max", "n_direction_obs",
    "current_channel",
)
ACTION_FEATURES = (
    "kind_measure", "kind_clear", "pt_center", "pt_perp", "pt_nbv", "pt_ready",
    "is_current", "d_point", "d_ratio", "d_ch_mec", "ch_mec_radius",
    "ch_n_obs", "ch_n_direction", "bearing_gap",
)
# The four features pre-registered for the (stop x scan set) cell
# (ACTION_VALUE_LEARNABILITY.md section 10.3).  They are appended only with
# --features scan, so every first-half number stays exactly reproducible.
SCAN_FEATURES = ("scan_variant_is_default", "scan_set_size",
                 "scan_set_cost_s", "scan_set_active_reach")
FEATURES = STATE_FEATURES + ACTION_FEATURES
# Appended only when --features scan is given (pre-registered joint cell).
EXTRA_FEATURES = ()
# Discrete key for the "identical observable state" test - the same style of
# key section 21 used, plus the two continuous distances rounded to 100 m.
STATE_KEY = ("n_active", "n_ready", "n_unknown", "n_confirmed", "cov_index",
             "current_channel")
COARSE_KEY = ("n_active", "n_ready", "n_unknown", "cov_index")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def find_provenance(labels_path, explicit=None):
    """Locate the config snapshot written next to the labels, if any."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(labels_path.with_name(labels_path.stem
                                            + "_provenance.json"))
    candidates.append(Path(str(labels_path) + "_provenance.json"))
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else ROOT / candidate
        if path.exists():
            return path
    return None


def decision_key(row):
    return (row["mode"], int(row["n"]), int(row["seed"]), int(row["index"]))

def episode_key(row):
    return (row["mode"], int(row["n"]), int(row["seed"]))


def vector(row, with_n=False):
    values = [float(row["state"][name]) for name in STATE_FEATURES]
    action = row.get("action_features") or {}
    values += [float(action.get(name, -1.0)) for name in ACTION_FEATURES]
    values += [float(action.get(name, -1.0)) for name in EXTRA_FEATURES]
    if with_n:
        values.append(float(row["n"]))
    return values


def feature_names():
    return list(STATE_FEATURES) + list(ACTION_FEATURES) + list(EXTRA_FEATURES)


def group_by(rows, keyfunc):
    groups = {}
    for row in rows:
        groups.setdefault(keyfunc(row), []).append(row)
    return groups


# ----------------------------------------------------------------------
# static reference rules
# ----------------------------------------------------------------------

def rule_always_production(rows):
    return None


def rule_nearest(rows):
    best = None
    for row in rows:
        if row["is_production"]:
            continue
        key = (row["action_features"]["d_point"],)
        if best is None or key < best[0]:
            best = (key, row)
    return best[1] if best else None


def rule_largest_mec_center(rows):
    best = None
    for row in rows:
        if row["is_production"] or not row["action_features"]["pt_center"]:
            continue
        key = (-row["action_features"]["ch_mec_radius"],)
        if best is None or key < best[0]:
            best = (key, row)
    return best[1] if best else None


def rule_largest_mec_perp(rows):
    best = None
    for row in rows:
        if row["is_production"] or not row["action_features"]["pt_perp"]:
            continue
        key = (-row["action_features"]["ch_mec_radius"],)
        if best is None or key < best[0]:
            best = (key, row)
    return best[1] if best else None


STATIC_RULES = {
    "always production (incumbent)": rule_always_production,
    "always nearest candidate": rule_nearest,
    "always centre of largest-MEC channel": rule_largest_mec_center,
    "always perpendicular baseline of largest-MEC channel":
        rule_largest_mec_perp,
}


def static_value(rows, picker):
    groups = group_by(rows, decision_key)
    total = 0.0
    switches = 0
    for group in groups.values():
        chosen = picker(group)
        if chosen is None:
            continue
        total += chosen["delta"]
        switches += 1
    return total, switches


# ----------------------------------------------------------------------
# model evaluation
# ----------------------------------------------------------------------

def fit_predict(model_kind, train_rows, test_rows, with_n=False):
    if not test_rows:
        return []
    X = np.asarray([vector(row, with_n) for row in train_rows], dtype=float)
    y = np.asarray([row["delta"] for row in train_rows], dtype=float)
    Xt = np.asarray([vector(row, with_n) for row in test_rows], dtype=float)
    if model_kind == "tree_reg":
        model = DecisionTreeRegressor(max_depth=3, min_samples_leaf=20,
                                      random_state=0)
        model.fit(X, y)
        return list(model.predict(Xt)), model
    if model_kind == "tree_cls":
        labels = (y > 0).astype(int)
        model = DecisionTreeClassifier(max_depth=3, min_samples_leaf=20,
                                       random_state=0)
        model.fit(X, labels)
        probabilities = model.predict_proba(Xt)
        column = list(model.classes_).index(1) if 1 in model.classes_ else None
        scores = (probabilities[:, column] if column is not None
                  else np.zeros(len(Xt)))
        return list(scores), model
    if model_kind == "ridge":
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0] = 1.0
        model = Ridge(alpha=1.0)
        model.fit((X - mean) / std, y)
        return list(model.predict((Xt - mean) / std)), (model, mean, std)
    raise ValueError(model_kind)


def evaluate_loo(rows, model_kind, holdout="decision", threshold=0.0,
                 with_n=False):
    """Leave-one-decision/one-episode-out evaluation in label space."""
    if holdout == "decision":
        folds = [(key, group) for key, group in
                 sorted(group_by(rows, decision_key).items())]
    elif holdout == "episode":
        folds = [(key, group) for key, group in
                 sorted(group_by(rows, episode_key).items())]
    else:
        raise ValueError(holdout)
    values = []
    for key, test_rows in folds:
        if holdout == "decision":
            train_rows = [row for row in rows
                          if decision_key(row) != key]
        else:
            train_rows = [row for row in rows
                          if episode_key(row) != key]
        if not train_rows:
            continue
        predictions, _ = fit_predict(model_kind, train_rows, test_rows,
                                     with_n=with_n)
        by_decision = {}
        for row, score in zip(test_rows, predictions):
            by_decision.setdefault(decision_key(row), []).append((score, row))
        for decision, pairs in by_decision.items():
            best_score, best_row = max(pairs, key=lambda item: item[0])
            if best_score > threshold:
                values.append((decision, best_row["delta"], best_row))
            else:
                values.append((decision, 0.0, None))
    return values


def summarize_values(values):
    deltas = [value for _, value, _ in values]
    switches = [item for item in values if item[2] is not None]
    positive = [value for _, value, row in values if row is not None
                and value > 0]
    negative = [value for _, value, row in values if row is not None
                and value <= 0]
    total = sum(deltas)
    ordered = sorted(deltas)
    return {
        "decisions": len(deltas),
        "value": round(total, 1),
        "mean": round(statistics.mean(deltas), 2) if deltas else 0.0,
        "median": round(statistics.median(deltas), 1) if deltas else 0.0,
        "p90": round(ordered[int(0.9 * (len(ordered) - 1))], 1) if ordered
              else 0.0,
        "max": round(max(deltas), 1) if deltas else 0.0,
        "min": round(min(deltas), 1) if deltas else 0.0,
        "switches": len(switches),
        "switch_precision": (round(len(positive) / len(switches), 3)
                             if switches else None),
        "gain_when_switched": (round(statistics.mean(positive), 1)
                               if positive else 0.0),
        "loss_when_switched": (round(statistics.mean(negative), 1)
                               if negative else 0.0),
    }


def per_case_values(values):
    buckets = {}
    for decision, value, row in values:
        mode, n, seed, _ = decision
        buckets.setdefault((mode, n), []).append(value)
    return {("%s/%d" % key): round(sum(bucket), 1)
            for key, bucket in sorted(buckets.items())}


# ----------------------------------------------------------------------
# oracle / conflict analysis
# ----------------------------------------------------------------------

def oracle_of(groups):
    total = 0.0
    spreads = []
    production_best = 0
    for group in groups.values():
        valid = [row for row in group if row.get("complete")
                 and row.get("verifier_ok")]
        if not valid:
            continue
        best = max(row["delta"] for row in valid)
        worst = min(row["delta"] for row in valid)
        total += max(0.0, best)
        spreads.append(best - worst)
        incumbent = next((row for row in valid if row["is_production"]), None)
        if incumbent is not None and best <= 1e-9:
            production_best += 1
    return total, spreads, production_best


def oracle_by_case(groups):
    """Where the measured one-step value sits, case by case."""
    buckets = {}
    for key, group in groups.items():
        valid = [row for row in group if row.get("complete")
                 and row.get("verifier_ok")]
        if not valid:
            continue
        best = max(row["delta"] for row in valid)
        entry = buckets.setdefault(("%s/%d" % (key[0], key[1])),
                                   {"decisions": 0, "oracle": 0.0,
                                    "positive": 0, "spreads": []})
        entry["decisions"] += 1
        entry["oracle"] += max(0.0, best)
        entry["positive"] += 1 if best > 1e-9 else 0
        entry["spreads"].append(max(row["delta"] for row in valid)
                                - min(row["delta"] for row in valid))
    out = {}
    for name, entry in sorted(buckets.items()):
        out[name] = {
            "decisions": entry["decisions"],
            "oracle_s": round(entry["oracle"], 1),
            "share_switchable": round(entry["positive"]
                                      / max(1, entry["decisions"]), 3),
            "spread_median_s": round(statistics.median(entry["spreads"]), 1),
        }
    return out


def conflict_report(rows, key_names, max_examples=6):
    groups = group_by(rows, decision_key)
    buckets = {}
    for key, group in groups.items():
        first = group[0]
        state_key = tuple(first["state"][name] for name in key_names)
        buckets.setdefault(state_key, []).append((key, group))
    conflicts = []
    for state_key, entries in buckets.items():
        if len(entries) < 2:
            continue
        bests = []
        for key, group in entries:
            valid = [row for row in group if row.get("complete")
                     and row.get("verifier_ok")]
            if not valid:
                continue
            bests.append((key, max(row["delta"] for row in valid)))
        if len(bests) < 2:
            continue
        signs = {best > 1e-9 for _, best in bests}
        if len(signs) > 1:
            conflicts.append((state_key, bests))
    loss = 0.0
    for state_key, bests in conflicts:
        positive = [best for _, best in bests if best > 1e-9]
        negative = [best for _, best in bests if best <= 1e-9]
        # A deterministic policy reading only this key answers identically to
        # every decision in the bucket.  "Switch" earns pos+neg, "stay" earns 0,
        # so the best such policy earns max(0, pos+neg) and the rest of the
        # bucket's oracle value (pos) is unreachable *on this key*.
        pos_sum = sum(positive)
        achievable = max(0.0, pos_sum + sum(negative))
        loss += pos_sum - achievable
    conflicts.sort(key=lambda item: -sum(best for _, best in item[1]))
    return {
        "buckets": len(buckets),
        "buckets_with_conflict": len(conflicts),
        "decisions_in_conflict": sum(len(bests) for _, bests in conflicts),
        "unreachable_s": round(loss, 1),
        "examples": [{"state": dict(zip(key_names, state_key)),
                      "decisions": [{"case": "%s/%d seed %d step %d" % key,
                                     "best_delta": round(best, 1)}
                                    for key, best in bests]}
                     for state_key, bests in conflicts[:max_examples]],
    }


def duplicate_state_report(rows):
    """Identical *full* observable state (continuous features rounded)."""
    groups = group_by(rows, decision_key)
    buckets = {}
    for key, group in groups.items():
        first = group[0]
        signature = tuple(round(float(first["state"][name]), 1)
                          for name in STATE_FEATURES)
        buckets.setdefault(signature, []).append((key, group))
    duplicates = 0
    conflicts = []
    for signature, entries in buckets.items():
        if len(entries) < 2:
            continue
        duplicates += 1
        bests = []
        for key, group in entries:
            valid = [row for row in group if row.get("complete")
                     and row.get("verifier_ok")]
            if not valid:
                continue
            bests.append((key, max(row["delta"] for row in valid)))
        if len(bests) >= 2 and len({best > 1e-9 for _, best in bests}) > 1:
            conflicts.append((signature, bests))
    conflicts.sort(key=lambda item: -sum(best for _, best in item[1]))
    return {
        "duplicate_state_buckets": duplicates,
        "duplicate_state_buckets_with_conflict": len(conflicts),
        "examples": [{"state": dict(zip(STATE_FEATURES, signature)),
                      "decisions": [{"case": "%s/%d seed %d step %d" % key,
                                     "best_delta": round(best, 1)}
                                    for key, best in bests]}
                     for signature, bests in conflicts[:4]],
    }


def breakeven_report(rows):
    """Mean right-switch gain vs mean wrong-switch loss per switch target."""
    groups = group_by(rows, decision_key)
    targets = dict(SWITCH_CRITERIA)
    targets["oracle best candidate"] = lambda group: max(
        (row for row in group if row.get("complete") and row.get("verifier_ok")),
        key=lambda row: row["delta"])
    out = {}
    for name, picker in targets.items():
        deltas = []
        for group in groups.values():
            pick = picker(group)
            if pick is None:
                continue
            deltas.append(float(pick["delta"]))
        positive = [value for value in deltas if value > 1e-9]
        negative = [value for value in deltas if value <= 1e-9]
        mean_pos = statistics.mean(positive) if positive else 0.0
        mean_neg = statistics.mean(negative) if negative else 0.0
        out[name] = {
            "decisions": len(deltas),
            "share_positive": round(len(positive) / max(1, len(deltas)), 3),
            "mean_gain_when_right": round(mean_pos, 1),
            "mean_loss_when_wrong": round(mean_neg, 1),
            "breakeven_precision": (round(abs(mean_neg)
                                          / (mean_pos + abs(mean_neg)), 3)
                                    if (mean_pos + abs(mean_neg)) > 0 else None),
        }
    return out


# ----------------------------------------------------------------------
# single-threshold ("stump") rule family - the analogue of section 21's test
# ----------------------------------------------------------------------

STUMP_FEATURES = ("step", "t_elapsed", "n_active", "n_ready", "n_unknown",
                  "cov_index", "cov_remaining", "d_active", "d_ready",
                  "mec_mean", "mec_min", "mec_max", "n_direction_obs")

SWITCH_CRITERIA = {
    "nearest candidate": rule_nearest,
    "centre of largest-MEC": rule_largest_mec_center,
    "perp of largest-MEC": rule_largest_mec_perp,
}


def stump_data(rows):
    """Per-decision: state features + realised delta of each switch target."""
    groups = group_by(rows, decision_key)
    data = {}
    for key, group in sorted(groups.items()):
        chosen = {}
        for name, picker in SWITCH_CRITERIA.items():
            pick = picker(group)
            chosen[name] = 0.0 if pick is None else float(pick["delta"])
        data[key] = {
            "state": {name: float(group[0]["state"][name])
                      for name in STUMP_FEATURES},
            "delta": chosen,
        }
    return data


def best_stump(keys, data):
    """Best (criterion, feature, direction, threshold) on the given decisions."""
    best_value, best_rule = 0.0, None
    for criterion in SWITCH_CRITERIA:
        for feature in STUMP_FEATURES:
            pairs = sorted((data[key]["state"][feature],
                            data[key]["delta"][criterion]) for key in keys)
            count = len(pairs)
            suffix = [0.0] * (count + 1)
            for index in range(count - 1, -1, -1):
                suffix[index] = suffix[index + 1] + pairs[index][1]
            prefix = 0.0
            for index in range(count):
                if suffix[index] > best_value:
                    best_value = suffix[index]
                    best_rule = (criterion, feature, 1, pairs[index][0])
                prefix += pairs[index][1]
                if prefix > best_value:
                    best_value = prefix
                    best_rule = (criterion, feature, -1, pairs[index][0])
    return best_value, best_rule


def apply_stump(rule, entry):
    if rule is None:
        return 0.0
    criterion, feature, direction, threshold = rule
    value = entry["state"][feature]
    take = (value >= threshold) if direction > 0 else (value <= threshold)
    return entry["delta"][criterion] if take else 0.0


def evaluate_stumps(rows, holdout="decision"):
    data = stump_data(rows)
    if holdout == "decision":
        folds = [(key, [key]) for key in sorted(data)]
    else:
        folds = []
        episodes = {}
        for key in sorted(data):
            episodes.setdefault(tuple(key[:3]), []).append(key)
        for episode, keys in episodes.items():
            folds.append((episode, sorted(keys)))
    values = []
    picked = {}
    for key, held in folds:
        held_set = set(held)
        train = [item for item in data if item not in held_set]
        _, rule = best_stump(train, data)
        picked[rule] = picked.get(rule, 0) + 1
        for item in held:
            value = apply_stump(rule, data[item])
            values.append((item, value, rule if value != 0.0 else None))
    summary = summarize_values(values)
    summary["most_common_rule"] = str(max(picked.items(),
                                          key=lambda item: item[1])[0])
    return summary


# ----------------------------------------------------------------------
# permutation null
# ----------------------------------------------------------------------

def permutation_null(rows, model_kind, holdout="decision", repeats=10,
                     with_n=False, seed=0):
    """Label-space LOO value when the deltas are shuffled across rows."""
    rng = np.random.default_rng(seed)
    values = []
    deltas = np.asarray([row["delta"] for row in rows], dtype=float)
    for repeat in range(repeats):
        shuffled = deltas.copy()
        rng.shuffle(shuffled)
        copy = [dict(row, delta=float(shuffled[index]))
                for index, row in enumerate(rows)]
        result = summarize_values(evaluate_loo(copy, model_kind,
                                               holdout=holdout,
                                               with_n=with_n))
        values.append(result["value"])
    return {"repeats": repeats, "values": values,
            "mean": round(float(np.mean(values)), 1),
            "max": round(float(np.max(values)), 1)}


# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels",
                        default="tuning_runs/action_value_labels.jsonl")
    parser.add_argument("--json", default="tuning_runs/action_value_signal.json")
    parser.add_argument("--no-positions", action="store_true",
                        help="accepted for symmetry; positions are never "
                             "in the feature list")
    parser.add_argument("--permutations", type=int, default=10)
    parser.add_argument("--features", default="base", choices=("base", "scan"),
                        help="base = 17 state + 14 action features "
                             "(first half); scan = those plus the four "
                             "pre-registered scan-set features (joint cell)")
    parser.add_argument("--provenance", default=None,
                        help="config snapshot written next to the labels "
                             "(default: <labels stem>_provenance.json)")
    args = parser.parse_args()

    global EXTRA_FEATURES
    if args.features == "scan":
        EXTRA_FEATURES = SCAN_FEATURES

    rows = load(ROOT / args.labels)
    groups = group_by(rows, decision_key)
    valid_rows = [row for row in rows if row.get("complete")
                  and row.get("verifier_ok")]
    invalid = len(rows) - len(valid_rows)
    provenance_path = find_provenance(ROOT / args.labels, args.provenance)
    report = {
        "labels_file": args.labels,
        "labels_sha256": hashlib.sha256(
            (ROOT / args.labels).read_bytes()).hexdigest(),
        "labels_provenance": (provenance_path.relative_to(ROOT).as_posix()
                              if (provenance_path is not None
                                  and provenance_path.exists()) else None),
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "command": "python -X utf8 " + " ".join(sys.argv),
        "decisions": len(groups),
        "rows": len(rows),
        "invalid_rows": invalid,
        "cases": sorted({"%s/%d" % (row["mode"], row["n"]) for row in rows}),
        "seeds": sorted({int(row["seed"]) for row in rows}),
    }
    print("labels %s  (sha256 %s)" % (args.labels, report["labels_sha256"][:16]))
    print("provenance %s" % report["labels_provenance"])

    print("=" * 78)
    print("1. WHAT IS AT STAKE (production policy, forced single decision)")
    print("=" * 78)
    print("decisions %d over %d cases ; label rows %d (invalid %d)"
          % (len(groups), len(report["cases"]), len(rows), invalid))
    selfcheck = [abs(row["selfcheck_error_s"]) for row in rows]
    print("production replay self-check: max %.2e s (%d/%d rows)"
          % (max(selfcheck) if selfcheck else 0.0,
             sum(1 for value in selfcheck if value < 1e-6), len(selfcheck)))
    oracle, spreads, production_best = oracle_of(groups)
    ordered = sorted(spreads)
    report["oracle_s"] = round(oracle, 1)
    report["production_optimal"] = production_best
    report["production_optimal_share"] = (round(production_best / len(groups), 3)
                                          if groups else None)
    report["spread_median"] = round(statistics.median(ordered), 1) if ordered \
        else 0.0
    report["spread_max"] = round(max(ordered), 1) if ordered else 0.0
    report["spread_p90"] = round(ordered[int(0.9 * (len(ordered) - 1))], 1) \
        if ordered else 0.0
    print("production action already optimal : %d/%d (%.0f%%)"
          % (production_best, len(groups),
             100.0 * production_best / max(1, len(groups))))
    print("oracle value of a perfect one-step choice: %+.0f s" % oracle)
    print("candidate spread at one decision: median %.0f s, p90 %.0f s, "
          "max %.0f s" % (report["spread_median"], report["spread_p90"],
                          report["spread_max"]))
    print("\nstatic reference rules (same label-space metric):")
    report["static_rules"] = {}
    for name, picker in STATIC_RULES.items():
        value, switches = static_value(valid_rows, picker)
        report["static_rules"][name] = {"value": round(value, 1),
                                        "switches": switches}
        print("   %-46s %+9.0f s over %3d switches" % (name, value, switches))

    print("\nbreak-even economics of a switch decision:")
    report["breakeven"] = breakeven_report(valid_rows)
    for name, item in report["breakeven"].items():
        print("   %-28s positive in %3d%% | mean gain %+7.1f s | mean loss "
              "%+8.1f s | break-even precision %.2f"
              % (name, 100 * item["share_positive"],
                 item["mean_gain_when_right"], item["mean_loss_when_wrong"],
                 item["breakeven_precision"]))
    report["oracle_by_case"] = oracle_by_case(groups)
    print("\nwhere the value sits (per case, dev seeds 101..505):")
    for name, item in report["oracle_by_case"].items():
        print("   %-7s decisions %2d | oracle %+7.0f s | switchable share "
              "%.0f%% | spread median %6.0f s"
              % (name, item["decisions"], item["oracle_s"],
                 100 * item["share_switchable"], item["spread_median_s"]))

    print()
    print("=" * 78)
    print("2. IS THE LABEL AN OBSERVABLE FUNCTION?  (identical-state conflicts)")
    print("=" * 78)
    report["conflict_fine"] = conflict_report(valid_rows, STATE_KEY)
    report["conflict_coarse"] = conflict_report(valid_rows, COARSE_KEY)
    report["duplicate_state"] = duplicate_state_report(valid_rows)
    for name, key in (("key = %s" % (STATE_KEY,), "conflict_fine"),
                      ("key = %s" % (COARSE_KEY,), "conflict_coarse")):
        item = report[key]
        print("%s\n   buckets %d ; conflicting %d (covering %d decisions) ; "
              "value unreachable by any deterministic rule on this key "
              "%+.0f s" % (name, item["buckets"], item["buckets_with_conflict"],
                           item["decisions_in_conflict"], item["unreachable_s"]))
    item = report["duplicate_state"]
    print("identical full observable state (continuous features rounded to "
          "0.1)\n   duplicate buckets %d ; conflicting %d"
          % (item["duplicate_state_buckets"],
             item["duplicate_state_buckets_with_conflict"]))
    for example in item["examples"]:
        print("   conflicting duplicate state %s"
              % json.dumps(example["state"], ensure_ascii=False))
        for entry in example["decisions"]:
            print("      %-28s best_delta %+.0f s"
                  % (entry["case"], entry["best_delta"]))
    for example in report["conflict_fine"]["examples"][:3]:
        print("   example state %s" % json.dumps(example["state"],
                                                 ensure_ascii=False))
        for entry in example["decisions"]:
            print("      %-28s best_delta %+.0f s"
                  % (entry["case"], entry["best_delta"]))

    print()
    print("=" * 78)
    print("3. CAN A SMALL OBSERVABLE MODEL CAPTURE IT?  (leave-one-out)")
    print("=" * 78)
    report["models"] = {}
    for model_kind in ("tree_reg", "tree_cls", "ridge"):
        for holdout in ("decision", "episode"):
            values = evaluate_loo(valid_rows, model_kind, holdout=holdout)
            summary = summarize_values(values)
            summary["per_case"] = per_case_values(values)
            report["models"]["%s/%s" % (model_kind, holdout)] = summary
            print("%-10s leave-one-%-8s value %+8.0f s | switches %3d "
                  "(precision %s) | mean %+.1f median %+.1f p90 %+.1f max %+.1f"
                  % (model_kind, holdout, summary["value"], summary["switches"],
                     summary["switch_precision"], summary["mean"],
                     summary["median"], summary["p90"], summary["max"]))
            print("            per case: %s"
                  % json.dumps(summary["per_case"], ensure_ascii=False))
    print("   ceiling in this experiment: oracle %+.0f s ; incumbent 0 s"
          % oracle)

    print()
    print("=" * 78)
    print("3b. SINGLE-THRESHOLD ('stump') RULES ON OBSERVABLE STATE")
    print("=" * 78)
    report["stumps"] = {}
    for holdout in ("decision", "episode"):
        summary = evaluate_stumps(valid_rows, holdout=holdout)
        report["stumps"][holdout] = summary
        print("best rule, leave-one-%-8s value %+8.0f s | switches %3d | "
              "switch precision %s | mean %+.1f median %+.1f min %+.1f"
              % (holdout, summary["value"], summary["switches"],
                 summary["switch_precision"], summary["mean"],
                 summary["median"], summary["min"]))
        print("   most often selected rule: %s"
              % summary["most_common_rule"])

    print()
    print("3c. permutation null (deltas shuffled across rows, same procedure)")
    report["permutation_null"] = {}
    for model_kind in ("tree_reg", "tree_cls"):
        item = permutation_null(valid_rows, model_kind, "decision",
                                repeats=args.permutations)
        report["permutation_null"][model_kind] = item
        observed = report["models"]["%s/decision" % model_kind]["value"]
        print("   %-9s shuffled value mean %+.0f s, max %+.0f s ; observed "
              "%+.0f s" % (model_kind, item["mean"], item["max"], observed))

    # readable rule from the full-data tree, for the "summarisable?" question
    train_rows = valid_rows
    X = np.asarray([vector(row) for row in train_rows], dtype=float)
    y = np.asarray([row["delta"] for row in train_rows], dtype=float)
    tree = DecisionTreeRegressor(max_depth=3, min_samples_leaf=20,
                                 random_state=0).fit(X, y)
    text = export_text(tree, feature_names=feature_names())
    report["tree_text"] = text
    print("\nfull-data depth-3 regression tree (descriptive only):")
    for line in text.splitlines():
        print("   " + line)

    print()
    print("=" * 78)
    print("4. DIAGNOSTIC ONLY: how much lives in the hidden source count n")
    print("=" * 78)
    values = evaluate_loo(valid_rows, "tree_reg", holdout="episode",
                          with_n=True)
    summary_n = summarize_values(values)
    report["with_n_episode_tree_reg"] = summary_n
    print("tree_reg leave-one-episode-out WITH n : value %+.0f s | switches %d "
          "| precision %s" % (summary_n["value"], summary_n["switches"],
                              summary_n["switch_precision"]))
    print("(n is never available online; the gap measures how much of the "
          "label is not observable.)")

    print()
    print("=" * 78)
    print("5. GATE VERDICT (task step 1: is the label learnable at all?)")
    print("=" * 78)
    model_values = {key: value["value"] for key, value in report["models"].items()}
    best_key = max(model_values, key=lambda key: model_values[key])
    best_value = model_values[best_key]
    stump_best = max(item["value"] for item in report["stumps"].values())
    null_max = max(item["max"] for item in report["permutation_null"].values())
    conflict_fine = report["conflict_fine"]["buckets_with_conflict"]
    conflict_full = report["duplicate_state"]["duplicate_state_buckets_with_conflict"]
    # The task's pass condition, verbatim: (1) leave-one-out value relative to
    # "always take the production action" must be > 0, and (2) there must be no
    # bucket of identical observable state whose label disagrees.  The
    # pre-registered second half (ACTION_VALUE_LEARNABILITY.md section 10.4)
    # sharpens (1) to: some model kind must be > 0 at BOTH leave-one-decision
    # and leave-one-episode level.  The permutation null and the
    # single-threshold rule are supporting checks.
    by_level = {}
    for key, value in report["models"].items():
        kind, level = key.split("/")
        by_level.setdefault(kind, {})[level] = value["value"]
    ok_kinds = sorted(kind for kind, levels in by_level.items()
                      if levels.get("decision", -1e9) > 0
                      and levels.get("episode", -1e9) > 0)
    gate_loo = bool(ok_kinds)
    gate_conflict = (conflict_fine == 0 and conflict_full == 0)
    gate_pass = gate_loo and gate_conflict
    report["gate"] = {
        "best_model": best_key, "best_model_value": best_value,
        "best_stump_value": stump_best, "permutation_null_max": null_max,
        "conflict_buckets_state_key": conflict_fine,
        "conflict_buckets_full_signature": conflict_full,
        "condition_1_loo_positive": bool(gate_loo),
        "condition_1_kinds_positive_at_both_levels": ok_kinds,
        "condition_2_no_conflicting_bucket": bool(gate_conflict),
        "condition_1_margin_s": round(best_value, 1),
        "features": feature_names(),
        "learnable": bool(gate_pass),
        "criterion": "learnable iff (1) best leave-one-out value for the "
                     "observed (state, action) features is > 0 seconds "
                     "relative to always taking the production action, AND "
                     "(2) no two decisions with identical observable state "
                     "carry opposite labels.  Supporting checks: permutation "
                     "null band and the single-threshold rule family.",
    }
    print("condition 1 - LOO value > 0 vs always-production:")
    print("   best observable model : %s  %+.0f s  -> %s"
          % (best_key, best_value, "PASS" if gate_loo else "FAIL"))
    print("   pre-registered reading (both LOO levels > 0): %s"
          % ("PASS for " + ",".join(ok_kinds) if ok_kinds else "FAIL (no model "
             "is positive at both leave-one-decision and leave-one-episode)"))
    print("condition 2 - no identical-state bucket with opposite labels:")
    print("   state-key buckets with conflicts : %d ; full-feature-signature "
          "buckets with conflicts : %d  -> %s"
          % (conflict_fine, conflict_full, "PASS" if gate_conflict else "FAIL"))
    print("supporting: best single-threshold rule %+.0f s ; permutation-null "
          "max %+.0f s ; incumbent +0 s ; oracle ceiling %+.0f s"
          % (stump_best, null_max, oracle))
    print("VERDICT: %s"
          % ("LEARNABLE - proceed to state-conditional selection"
             if gate_pass else
             "NOT LEARNABLE from the tested observable features - stop "
             "(task step 1 fails, no training / no production change)"))

    out = ROOT / args.json
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
