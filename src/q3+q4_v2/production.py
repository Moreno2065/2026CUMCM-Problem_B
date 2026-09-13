"""Single source of truth for the production Q3/Q4 policy configuration.

Both the benchmark entry (``recommended.py`` / ``runtime.run_case``) and the
official entry (``run.py``) build their scheduler and runner configuration from
this module, so a parameter can no longer exist in the scoring path without
also existing in the submitted path.  Every value here is observation-only: it
is a fixed policy constant, never a scenario label, source count or truth
value.

``SCHEDULER_KEYS`` is the exact key set forwarded to the scheduler
constructor; ``RUNNER_KEYS`` is the exact key set forwarded to
``MainlineConfig``.  ``policy_snapshot`` serialises both plus the code/model
hashes for the run artifacts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Runner (MainlineConfig) keys: they shape the executor's stop plan, so the
# scheduler never sees them.
RUNNER_KEYS = (
    "nbv_mode", "opportunistic_reuse", "channel_scan_mode",
    "q4_certificate_layout", "q4_joint_rank", "cert_route_mode",
    "q4_residual_sparsify", "active_scan_margin_m", "max_steps",
)

# Scheduler keys: everything the policy itself reads.
SCHEDULER_KEYS = (
    "q3_observation_adaptive", "q3_dynamic_order", "q3_ring_order",
    "q3_risky_clear_radius", "rolling_enabled", "rolling_horizon",
    "rolling_coverage_period", "q4_no_shrink_limit_high",
    "q4_risky_clear_radius", "q4_point_order", "q4_observed_order",
    "q4_observed_order_fraction", "rolling_enroute_detour_m",
    "q4_cross_angle_gain", "q4_joint_angle_gate_deg",
    "rolling_joint_active_limit", "early_fallback_max_points",
    "early_fallback_max_known", "early_fallback_suppress_failed_scan",
)

MODEL_FILES = {
    "Q3": "learned_search/model_q3.json",
    "Q4": "learned_search/model_q4.json",
}


def scheduler_kwargs(mode, **overrides):
    """Return the scheduler constructor kwargs for one production mode."""
    mode = str(mode).upper()
    common = {
        "nbv_mode": "radius",
        "opportunistic_reuse": True,
        "cert_route_mode": "lookahead2",
        "q4_joint_rank": True,
        "q4_residual_sparsify": True,
        "q4_certificate_layout": "sparse25",
    }
    if mode == "Q3":
        common.update(
            channel_scan_mode="selective_clear",
            active_scan_margin_m=0.0,
            q3_observation_adaptive=True,
            q3_dynamic_order=True,
            q3_ring_order=(4, 5, 0, 1, 2, 3),
            q3_risky_clear_radius=40.0,
            # When no more than ten channels have been confirmed and an
            # ACTIVE feasible region needs at most five exact clear disks,
            # finish it with the finite cover.  Failed lattice shots do not
            # rescan the stop; the successful stop keeps normal reuse.
            early_fallback_max_points=5,
            early_fallback_max_known=10,
            early_fallback_suppress_failed_scan=True,
        )
    else:
        common.update(
            channel_scan_mode="state_aware",
            q4_risky_clear_radius=0.0,
            q4_point_order=(0, 1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3,
                            2, 14, 13, 24, 23, 22, 21, 20, 19,
                            18, 17, 16, 15),
            q4_observed_order=True,
            q4_observed_order_fraction=0.10,
            rolling_enabled=True, rolling_horizon=3,
            rolling_coverage_period=3,
            q4_no_shrink_limit_high=8,
            rolling_enroute_detour_m=500.0,
            q4_cross_angle_gain=True,
            q4_joint_angle_gate_deg=30.0,
            rolling_joint_active_limit=3,
            # Round-5: one-shot optical probe for Q4.  A channel whose MEC is
            # already small has a real chance of being cleared outright, and a
            # failed probe costs only the 3 s failure plus a short approach;
            # the candidate is priced with the branch-weighted clear cost, is
            # attempted at most once per channel, and leaves the finite
            # certificate fallback untouched.
            rolling_probe_radius_m=60.0,
            rolling_probe_max_distance_m=600.0,
        )
    # Round-6: opportunistic stops skip UNKNOWN measurements whose discovery
    # share is negligible (the share is the fraction of the channel's still
    # possible region that the stop's guaranteed reception disk can see).
    # Coverage/certificate missions never pass through this filter, so no
    # absence witness is dropped from the certificate.
    common.update(
        valued_scan_opportunistic=True,
        valued_scan_share=0.15,
    )
    common.update(overrides)
    return common


# Keys that only the runner consumes.  Everything else in RUNNER_KEYS is also
# a scheduler constructor argument and must stay in both configurations,
# otherwise the official entry would silently fall back to scheduler defaults.
RUNNER_ONLY_KEYS = ("channel_scan_mode", "active_scan_margin_m", "max_steps")


def runner_kwargs(mode, max_steps=20000, **overrides):
    """Return the MainlineConfig kwargs implied by the production policy."""
    mode = str(mode).upper()
    config = {
        "nbv_mode": "radius",
        "opportunistic_reuse": True,
        "channel_scan_mode": ("selective_clear" if mode == "Q3"
                              else "state_aware"),
        "q4_certificate_layout": "sparse25",
        "q4_joint_rank": True,
        "cert_route_mode": "lookahead2",
        "q4_residual_sparsify": True,
        "active_scan_margin_m": 0.0,
        "max_steps": int(max_steps),
    }
    config.update(overrides)
    return config


def split_config(mode, **overrides):
    """Split one flat config dict into (scheduler_kwargs, runner_kwargs).

    Keys shared by both components (``nbv_mode``, ``cert_route_mode``, the Q4
    joint switches, ...) are kept in both dicts.  Only the runner-only keys are
    removed from the scheduler dict, so forwarding the flat configuration to
    the scheduler can never silently drop a policy switch.
    """
    flat = scheduler_kwargs(mode, **overrides)
    runner_overrides = {key: flat[key] for key in RUNNER_KEYS if key in flat}
    runner = runner_kwargs(mode, **runner_overrides)
    for key in RUNNER_ONLY_KEYS:
        flat.pop(key, None)
    return flat, runner


def _sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def policy_snapshot(mode, scheduler_cfg, runner_cfg):
    """Serialisable provenance record for one run's policy configuration.

    The record is what makes a stored run reproducible: it carries the full
    scheduler and runner configuration plus the hashes of the code and model
    files that produced the decisions.
    """
    mode = str(mode).upper()
    model_rel = MODEL_FILES.get(mode)
    return {
        "mode": mode,
        "scheduler_kwargs": {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in sorted(scheduler_cfg.items())
        },
        "runner_kwargs": {key: runner_cfg[key]
                          for key in sorted(runner_cfg)},
        "model": {
            "path": model_rel,
            "sha256": _sha256(ROOT / model_rel) if model_rel else None,
        },
        "code_sha256": {
            name: _sha256(ROOT / name) for name in (
                "runtime.py", "rolling.py", "production.py",
                "learned_search/scheduler.py",
                "belief_rollout/scheduler.py", "belief_rollout/worlds.py",
                "constraint_search/state.py", "constraint_search/scheduler.py",
                "constraint_search/macro.py",
                "compact_ring/scheduler.py",
                "compact_ring/tail_rollout.py",
                "compact_ring/coverage_rollout.py",
                "q4_bisect/scheduler.py", "q4_bisect/state.py",
                "q4_shadow/scheduler.py", "q4_shadow/belief.py",
                "baseline/code/experiment/runner.py",
            )
        },
    }


def dump_policy_snapshot(output_dir, mode, scheduler_cfg, runner_cfg):
    path = Path(output_dir) / "policy_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = policy_snapshot(mode, scheduler_cfg, runner_cfg)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return snapshot
