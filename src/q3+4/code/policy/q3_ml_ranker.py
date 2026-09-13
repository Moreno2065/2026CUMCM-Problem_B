# -*- coding: utf-8 -*-
"""Q3-only offline learning-to-rank policy.

This module is intentionally a policy-side experiment, not a replacement for
the Q3 geometry or its certificate.  It learns a small linear pairwise ranker
from offline candidate preferences.  At runtime it may reorder already
validated localization candidates only; it cannot create candidates, alter
the feasible region, or change READY/CERTIFIED_ABSENT predicates.

The implementation uses only the Python standard library so an experiment is
reproducible in the existing runner.  A model is a plain JSON artifact with
finite weights and explicit feature names.  Missing or malformed artifacts
must fail closed at the integration boundary.
"""

import json
import math
import os


FEATURE_NAMES = (
    "score",          # deterministic teacher gain/cost score
    "gain",           # expected MEC reduction
    "cost",           # movement + measure + optional switch cost
    "distance",       # movement distance from current position
    "is_approach",    # one-hot candidate kind
    "is_nbv",
)
MODEL_VERSION = "q3-linear-ranker-v2"
SUPPORTED_MODEL_VERSIONS = ("q3-linear-ranker-v1", MODEL_VERSION)
DEFAULT_TAKEOVER_GATE = {
    "enabled": True,
    "min_ml_margin": 0.05,
}


def _finite(value, field):
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be finite" % field) from exc
    if not math.isfinite(out):
        raise ValueError("%s must be finite" % field)
    return out


def _point(candidate):
    point = candidate.get("point")
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("candidate point must be a pair")
    return (_finite(point[0], "candidate.point[0]"),
            _finite(point[1], "candidate.point[1]"))


def candidate_features(candidate, position=(0.0, 0.0)):
    """Return the fixed feature vector for one existing Q3 candidate."""
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    px, py = _point(candidate)
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        raise ValueError("position must be a pair")
    ox = _finite(position[0], "position[0]")
    oy = _finite(position[1], "position[1]")
    kind = str(candidate.get("kind", "nbv"))
    if kind not in ("nbv", "approach"):
        raise ValueError("unsupported candidate kind %r" % kind)
    return (
        _finite(candidate.get("score"), "candidate.score"),
        _finite(candidate.get("gain"), "candidate.gain"),
        _finite(candidate.get("cost"), "candidate.cost"),
        math.hypot(px - ox, py - oy),
        1.0 if kind == "approach" else 0.0,
        1.0 if kind == "nbv" else 0.0,
    )


def _identity_normalization():
    return {
        "method": "identity",
        "feature_names": list(FEATURE_NAMES),
        "means": [0.0] * len(FEATURE_NAMES),
        "scales": [1.0] * len(FEATURE_NAMES),
    }


def _fit_normalization(vectors):
    rows = [tuple(float(value) for value in row) for row in vectors]
    if not rows:
        return _identity_normalization()
    width = len(FEATURE_NAMES)
    means = [sum(row[i] for row in rows) / len(rows)
             for i in range(width)]
    scales = []
    for i in range(width):
        variance = sum((row[i] - means[i]) ** 2 for row in rows) \
            / len(rows)
        scale = math.sqrt(variance)
        scales.append(scale if scale > 1e-12 else 1.0)
    return {
        "method": "zscore_train_only",
        "feature_names": list(FEATURE_NAMES),
        "means": means,
        "scales": scales,
    }


def _validate_normalization(normalization):
    if normalization is None:
        return _identity_normalization()
    if not isinstance(normalization, dict):
        raise ValueError("normalization must be a mapping")
    if normalization.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("normalization feature schema mismatch")
    means = normalization.get("means")
    scales = normalization.get("scales")
    if not isinstance(means, (list, tuple)) or \
            not isinstance(scales, (list, tuple)) or \
            len(means) != len(FEATURE_NAMES) or \
            len(scales) != len(FEATURE_NAMES):
        raise ValueError("normalization statistics have wrong length")
    means = [_finite(value, "normalization.mean") for value in means]
    scales = [_finite(value, "normalization.scale") for value in scales]
    if any(value <= 0.0 for value in scales):
        raise ValueError("normalization scales must be > 0")
    return {
        "method": str(normalization.get("method", "unknown")),
        "feature_names": list(FEATURE_NAMES),
        "means": means,
        "scales": scales,
    }


class Q3LinearRanker:
    """Deterministic linear pairwise ranker for Q3 candidate ordering."""

    def __init__(self, weights, bias=0.0, metadata=None,
                 normalization=None):
        if not isinstance(weights, (list, tuple, dict)):
            raise ValueError("weights must be a sequence or mapping")
        if isinstance(weights, dict):
            vals = [weights.get(name, 0.0) for name in FEATURE_NAMES]
        else:
            vals = list(weights)
        if len(vals) != len(FEATURE_NAMES):
            raise ValueError("weights must contain %d values" %
                             len(FEATURE_NAMES))
        self.weights = tuple(_finite(v, "weight") for v in vals)
        self.bias = _finite(bias, "bias")
        self.metadata = dict(metadata or {})
        self.normalization = _validate_normalization(normalization)

    @classmethod
    def default(cls):
        """Built-in safe surrogate used when no trained artifact is supplied.

        It is deliberately close to the frozen gain/cost objective.  This
        keeps the branch runnable while making its behavior auditable; a real
        experiment should pass a model produced by :meth:`fit_pairwise`.
        """
        return cls({
            "score": 1.0,
            "gain": 0.0,
            "cost": -0.001,
            "distance": -0.0001,
            "is_approach": 0.0,
            "is_nbv": 0.0,
        }, metadata={"source": "builtin_safe_surrogate"})

    @classmethod
    def fit_pairwise(cls, pairs, epochs=8, learning_rate=0.05):
        """Fit a perceptron-style pairwise ranker from offline preferences.

        ``pairs`` is an iterable of ``(preferred, rejected)`` or
        ``(preferred, rejected, position)`` tuples.  The optional position is
        the robot position at the decision that produced the pair.  Training
        normalization is fitted only from these pair features and is reused
        unchanged at inference time.
        """
        try:
            epochs = int(epochs)
        except (TypeError, ValueError) as exc:
            raise ValueError("epochs must be a positive integer") from exc
        if epochs <= 0:
            raise ValueError("epochs must be a positive integer")
        learning_rate = _finite(learning_rate, "learning_rate")
        if learning_rate <= 0.0:
            raise ValueError("learning_rate must be > 0")
        materialized = list(pairs)
        feature_pairs = []
        raw_vectors = []
        for pair in materialized:
            if not isinstance(pair, (list, tuple)) or len(pair) not in (2, 3):
                raise ValueError("pair must contain 2 or 3 values")
            preferred, rejected = pair[:2]
            position = pair[2] if len(pair) == 3 else (0.0, 0.0)
            left = candidate_features(preferred, position)
            right = candidate_features(rejected, position)
            feature_pairs.append((left, right))
            raw_vectors.extend((left, right))
        normalization = _fit_normalization(raw_vectors)
        weights = [0.0] * len(FEATURE_NAMES)
        for _ in range(epochs):
            for left_raw, right_raw in feature_pairs:
                left = [
                    (value - mean) / scale
                    for value, mean, scale in zip(
                        left_raw, normalization["means"],
                        normalization["scales"])
                ]
                right = [
                    (value - mean) / scale
                    for value, mean, scale in zip(
                        right_raw, normalization["means"],
                        normalization["scales"])
                ]
                delta = [a - b for a, b in zip(left, right)]
                margin = sum(w * d for w, d in zip(weights, delta))
                if margin <= 0.0:
                    for i, d in enumerate(delta):
                        weights[i] += learning_rate * d
        return cls(weights, metadata={
            "source": "offline_pairwise_perceptron",
            "epochs": epochs,
            "learning_rate": learning_rate,
            "pair_count": len(materialized),
            "normalization": normalization["method"],
        }, normalization=normalization)

    def _features(self, candidate, position):
        raw = candidate_features(candidate, position)
        return tuple(
            (value - mean) / scale
            for value, mean, scale in zip(
                raw, self.normalization["means"],
                self.normalization["scales"])
        )

    def score(self, candidate, position=(0.0, 0.0)):
        values = self._features(candidate, position)
        return self.bias + sum(w * x for w, x in zip(self.weights, values))

    def to_dict(self):
        return {
            "model_version": MODEL_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "weights": list(self.weights),
            "bias": self.bias,
            "normalization": dict(self.normalization),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("ranker artifact must be a mapping")
        if payload.get("model_version") not in SUPPORTED_MODEL_VERSIONS:
            raise ValueError("unsupported Q3 ranker model version")
        if payload.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("Q3 ranker feature schema mismatch")
        return cls(payload.get("weights"), payload.get("bias", 0.0),
                   metadata=payload.get("metadata"),
                   normalization=payload.get("normalization"))

    @classmethod
    def load(cls, path):
        if not path:
            return cls.default()
        with open(os.fspath(path), "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path):
        parent = os.path.dirname(os.path.abspath(os.fspath(path)))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1,
                      allow_nan=False)
        return path


def rank_q3_candidates(model, candidates, position=(0.0, 0.0)):
    """Return copies of candidates ordered by ML score.

    The input list and candidate mappings are never mutated.  Candidate pool
    membership is preserved exactly; this is the safety boundary that keeps
    the experimental ranker out of Q3 certification semantics.
    """
    if not isinstance(model, Q3LinearRanker):
        raise ValueError("model must be Q3LinearRanker")
    if candidates is None:
        raise ValueError("candidates must be a sequence")
    rows = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a mapping")
        score = model.score(candidate, position)
        row = dict(candidate)
        row["ml_score"] = score
        point = _point(candidate)
        rows.append((row, index, point))
    rows.sort(key=lambda item: (-item[0]["ml_score"],
                                _finite(item[0].get("cost"),
                                        "candidate.cost"),
                                item[2][0], item[2][1],
                                str(item[0].get("channel", "")),
                                str(item[0].get("kind", "")),
                                item[1]))
    return [row for row, _, _ in rows]


def _deterministic_q3_candidates(candidates):
    """Return the existing gain/cost order used by the deterministic policy."""
    rows = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a mapping")
        score = _finite(candidate.get("score"), "candidate.score")
        cost = _finite(candidate.get("cost"), "candidate.cost")
        point = _point(candidate)
        rows.append((dict(candidate), index, score, cost, point))
    rows.sort(key=lambda item: (-item[2], item[3], item[4][0], item[4][1],
                                str(item[0].get("channel", "")),
                                str(item[0].get("kind", "")), item[1]))
    return [row for row, _, _, _, _ in rows]


def deterministic_q3_choice(candidates):
    """Return the top candidate under the frozen gain/cost tie-break."""
    ordered = _deterministic_q3_candidates(candidates)
    return ordered[0] if ordered else None


def _takeover_gate(model):
    gate = dict(DEFAULT_TAKEOVER_GATE)
    metadata = getattr(model, "metadata", {})
    configured = metadata.get("takeover_gate")
    if configured is not None:
        if not isinstance(configured, dict):
            raise ValueError("takeover_gate metadata must be a mapping")
        gate["enabled"] = bool(configured.get("enabled", True))
        value = _finite(configured.get("min_ml_margin"),
                        "takeover_gate.min_ml_margin")
        if value < 0.0:
            raise ValueError("takeover_gate.min_ml_margin must be >= 0")
        gate["min_ml_margin"] = value
    return gate


def select_q3_candidate(model, candidates, position=(0.0, 0.0)):
    """Select with a conservative ML takeover gate.

    The deterministic order remains the fallback.  ML may change the choice
    only when the candidate pool is sane and its top-two score margin clears
    the calibrated gate.  A model agreeing with the deterministic choice is
    accepted without a margin requirement because no takeover risk exists.
    """
    if not candidates:
        return None
    deterministic = _deterministic_q3_candidates(candidates)
    ranked = rank_q3_candidates(model, candidates, position)
    if not ranked:
        return None
    fallback = dict(deterministic[0])
    fallback.update({"takeover": False, "takeover_reason": "gate_fallback"})
    top = ranked[0]
    det_key = (fallback.get("channel"), tuple(fallback.get("point", ())),
               fallback.get("kind"))
    top_key = (top.get("channel"), tuple(top.get("point", ())),
               top.get("kind"))
    if top_key == det_key:
        top = dict(top)
        top.update({"takeover": False, "takeover_reason": "deterministic_agreement",
                    "deterministic": True})
        return top
    if not _takeover_gate(model)["enabled"]:
        fallback["takeover_reason"] = "gate_disabled"
        return fallback
    try:
        sane = (_finite(top.get("score"), "candidate.score") >= 0.0 and
                _finite(top.get("gain"), "candidate.gain") >= 0.0 and
                _finite(top.get("cost"), "candidate.cost") > 0.0)
        margin = (float(top["ml_score"]) - float(ranked[1]["ml_score"])
                  if len(ranked) > 1 else 0.0)
        threshold = _takeover_gate(model)["min_ml_margin"]
    except (KeyError, TypeError, ValueError):
        return fallback
    if not sane:
        fallback["takeover_reason"] = "abnormal_candidate"
        return fallback
    if not math.isfinite(margin) or margin < threshold:
        fallback["takeover_reason"] = "low_confidence_or_margin"
        fallback["ml_margin"] = margin if math.isfinite(margin) else None
        return fallback
    top = dict(top)
    top.update({"takeover": True, "takeover_reason": "margin_cleared",
                "ml_margin": margin, "deterministic": False})
    return top
