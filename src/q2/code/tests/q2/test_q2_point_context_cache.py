"""Regression coverage for the immutable first-observation context cache."""

from __future__ import annotations

import pytest

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver import q2_point


S1 = Point2(0.0, 0.0)
S2 = Point2(792.3025077759607, -616.4786501226868)


def _configure_cache(*, enabled: bool, max_entries: int) -> None:
    configure = getattr(q2_point, "configure_q2_point_context_cache", None)
    assert configure is not None, "the context-cache control surface is required"
    configure(enabled=enabled, max_entries=max_entries)
    q2_point.clear_q2_point_context_cache()


@pytest.fixture(autouse=True)
def _reset_context_cache() -> None:
    yield
    configure = getattr(q2_point, "configure_q2_point_context_cache", None)
    if configure is not None:
        configure(enabled=True, max_entries=32)
        q2_point.clear_q2_point_context_cache()


def _assert_authoritative_fields_match(
    actual: q2_point.Q2PointResult,
    expected: q2_point.Q2PointResult,
) -> None:
    assert actual.Q == expected.Q
    assert actual.worst_beta == expected.worst_beta
    assert actual.worst_Q1_polygon == expected.worst_Q1_polygon
    assert actual.admissible == expected.admissible
    assert actual.in_crec == expected.in_crec


def test_enabled_cache_builds_one_a1_and_crec_for_repeated_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(enabled=True, max_entries=4)
    calls = {"a1": 0, "crec": 0}
    real_build_a1 = q2_point.build_a1
    real_build_crec = q2_point.build_crec

    def counted_a1(*args, **kwargs):
        calls["a1"] += 1
        return real_build_a1(*args, **kwargs)

    def counted_crec(*args, **kwargs):
        calls["crec"] += 1
        return real_build_crec(*args, **kwargs)

    monkeypatch.setattr(q2_point, "build_a1", counted_a1)
    monkeypatch.setattr(q2_point, "build_crec", counted_crec)

    first = q2_point.evaluate_q2_point(S1, 0.0, S2)
    second = q2_point.evaluate_q2_point(S1, 0.0, S2)

    _assert_authoritative_fields_match(second, first)
    assert calls == {"a1": 1, "crec": 1}


def test_disabled_cache_preserves_authoritative_result_without_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(enabled=False, max_entries=4)
    calls = {"a1": 0, "crec": 0}
    real_build_a1 = q2_point.build_a1
    real_build_crec = q2_point.build_crec

    def counted_a1(*args, **kwargs):
        calls["a1"] += 1
        return real_build_a1(*args, **kwargs)

    def counted_crec(*args, **kwargs):
        calls["crec"] += 1
        return real_build_crec(*args, **kwargs)

    monkeypatch.setattr(q2_point, "build_a1", counted_a1)
    monkeypatch.setattr(q2_point, "build_crec", counted_crec)

    uncached = q2_point.evaluate_q2_point(S1, 0.0, S2)
    repeated = q2_point.evaluate_q2_point(S1, 0.0, S2)

    _assert_authoritative_fields_match(repeated, uncached)
    assert calls == {"a1": 2, "crec": 2}


def test_cache_key_does_not_mix_first_observation_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(enabled=True, max_entries=4)
    calls = {"a1": 0, "crec": 0}
    real_build_a1 = q2_point.build_a1
    real_build_crec = q2_point.build_crec

    def counted_a1(*args, **kwargs):
        calls["a1"] += 1
        return real_build_a1(*args, **kwargs)

    def counted_crec(*args, **kwargs):
        calls["crec"] += 1
        return real_build_crec(*args, **kwargs)

    monkeypatch.setattr(q2_point, "build_a1", counted_a1)
    monkeypatch.setattr(q2_point, "build_crec", counted_crec)

    first = q2_point.evaluate_q2_point(S1, 0.0, S2)
    changed_theta = q2_point.evaluate_q2_point(S1, 1.0, S2)
    changed_station = q2_point.evaluate_q2_point(Point2(1.0, 0.0), 0.0, S2)

    assert first != changed_theta
    assert calls == {"a1": 3, "crec": 3}
    assert changed_station.S2 == S2


def test_cache_capacity_evicts_the_least_recently_used_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(enabled=True, max_entries=1)
    calls = {"a1": 0, "crec": 0}
    real_build_a1 = q2_point.build_a1
    real_build_crec = q2_point.build_crec

    def counted_a1(*args, **kwargs):
        calls["a1"] += 1
        return real_build_a1(*args, **kwargs)

    def counted_crec(*args, **kwargs):
        calls["crec"] += 1
        return real_build_crec(*args, **kwargs)

    monkeypatch.setattr(q2_point, "build_a1", counted_a1)
    monkeypatch.setattr(q2_point, "build_crec", counted_crec)

    q2_point.evaluate_q2_point(S1, 0.0, S2)
    q2_point.evaluate_q2_point(S1, 1.0, S2)
    q2_point.evaluate_q2_point(S1, 0.0, S2)

    assert calls == {"a1": 3, "crec": 3}
