"""Feasibility check for the small hybrid model (no end-to-end RL).

Question: using ONLY observable features of a joint candidate, can a small
model rank candidates well enough to pick one whose full-run cost beats what
production chose?  If not, generating thousands of rollout labels is pointless.

Method: leave-one-decision-out.  For every held-out decision point, fit a small
ridge/GBDT regressor on the other points' (features -> full-run total) pairs,
then take the argmin over that point's candidates and compare its true total
with production's true total on the same point.
"""
from __future__ import annotations

import glob
import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(paths):
    states = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for state in data["states"]:
            rows = [r for r in state.get("rows", []) if r.get("features")]
            if len(rows) < 5:
                continue
            production = next((r for r in rows
                               if r["features"]["is_production"] > 0.5), None)
            if production is None:
                continue
            states.append({
                "case": "%s/%d" % (data["mode"], data["n"]),
                "seed": data["seed"],
                "index": state["index"],
                "baseline": data["baseline"],
                "rows": rows,
                "production_total": production["total"],
            })
    return states


def matrix(rows):
    keys = sorted(rows[0]["features"])
    return np.array([[r["features"][k] for k in keys] for r in rows],
                    dtype=float), keys


def fit_predict(train_rows, test_rows, kind="ridge"):
    x_train, keys = matrix(train_rows)
    y_train = np.array([r["total"] for r in train_rows], dtype=float)
    x_test = np.array([[r["features"][k] for k in keys] for r in test_rows],
                      dtype=float)
    if kind == "ridge":
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0)
    else:
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(random_state=0)
    model.fit(x_train, y_train)
    return model.predict(x_test)


def main():
    paths = sys.argv[1:] or sorted(glob.glob(
        str(ROOT / "tuning_runs" / "teacher_v3_*.json")))
    states = load(paths)
    if len(states) < 3:
        print("need at least 3 decision points, have %d" % len(states))
        return 1
    print("decision points: %d (candidates: %s)" %
          (len(states), [len(s["rows"]) for s in states]))
    for kind in ("ridge", "gbdt"):
        gains = []
        picks_production = 0
        for held in states:
            train = [r for s in states if s is not held for r in s["rows"]]
            test = held["rows"]
            pred = fit_predict(train, test, kind)
            order = np.argsort(pred)
            # Ignore the production row itself only when it is not predicted
            # best: the model must genuinely prefer a different action.
            best_pred = test[order[0]]
            gain = held["production_total"] - best_pred["total"]
            gains.append(gain)
            picks_production += 1 if best_pred["features"]["is_production"] > .5 else 0
            spec = best_pred["spec"]
            label = ("PRODUCTION" if isinstance(spec, str) else
                     "%s/%s/%s" % (spec.get("kind"), spec.get("point_name"),
                                   spec.get("variant")))
            print("  [%s] %s seed%d idx%-3d pred_pick=%-24s true=%7.0f "
                  "prod=%7.0f gain=%+7.0f" %
                  (kind, held["case"], held["seed"], held["index"], label,
                   best_pred["total"], held["production_total"], gain))
        print("%s: mean gain %+.0f s, median %+.0f s, positive %d/%d, "
              "picked production %d/%d" %
              (kind, statistics.mean(gains), statistics.median(gains),
               sum(1 for g in gains if g > 0), len(gains),
               picks_production, len(gains)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
