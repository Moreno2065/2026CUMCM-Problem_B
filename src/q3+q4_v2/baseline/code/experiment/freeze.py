# -*- coding: utf-8 -*-
"""FROZEN_CONFIG 机制（Addendum B.6 / I Gate 5）。

调参结束后由 tune 结果生成 FROZEN_CONFIG.yaml；冻结后正式评估不得
再修改 tau。本阶段只实现机制；数值冻结在下一阶段（pilot 决定 grid 与
选择后调用 freeze_config）。

FROZEN_CONFIG.yaml 字段（Addendum B.6）：
    model_version / spec_version / tau / case_set_version /
    selection_metric / selection_rule / freeze_time / git_commit
另附 frozen_config_hash（被冻结配置文件字节 sha256）与 source 信息，
供 provenance 对账。
"""

import hashlib
import json
import os

from .config import (
    MODEL_VERSION,
    SPEC_VERSION,
    MainlineConfig,
    config_sha256,
    git_commit,
    load_config,
    _HAS_YAML,
)

FROZEN_REQUIRED_FIELDS = ("model_version", "spec_version", "tau",
                          "case_set_version", "selection_metric",
                          "selection_rule", "freeze_time", "git_commit",
                          "case_sets", "case_hashes", "source_hash",
                          "enabled_branches")

# These fields are provenance, not runtime configuration.  They are written
# on every new freeze (with explicit N/A/empty defaults for legacy callers),
# while ``load_config`` continues to discard them from the runtime snapshot.
FROZEN_PROVENANCE_FIELDS = ("case_sets", "case_hashes", "source_hash",
                            "enabled_branches")

DEFAULT_SELECTION_METRIC = (
    "primary: clearance_ratio == 100% (hard constraint), then min "
    "mean_t_per_source_s; secondary: movement distance, measure count, "
    "switch count, certificate completion time (Addendum B.5)")
DEFAULT_SELECTION_RULE = (
    "Robust Good > Fragile Best: among candidates within 2% of the best "
    "mean_t_per_source_s, pick the one with the smallest worst-case "
    "t_per_source_s, then fewer measures (Addendum B.2/B.5)")


def _now_iso():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _load_tune_results(tune_results):
    """tune_results: tune 汇总 JSON 路径或已加载 dict。

    期望形状（cli tune 输出）：{"results": [{tau, ...}, ...],
    "selected_tau": float|None, "case_set": str, ...}
    """
    if isinstance(tune_results, dict):
        return tune_results
    with open(tune_results, "r", encoding="utf-8") as f:
        return json.load(f)


def _selection_value(explicit, selection, names, default):
    """Resolve an optional provenance value without inventing one.

    ``None`` means that the explicit argument was not supplied.  Empty
    mappings/lists and empty strings are retained when explicitly supplied so
    that a caller can represent a known empty provenance value faithfully.
    """
    if explicit is not None:
        return explicit
    for name in names:
        if name in selection and selection[name] is not None:
            return selection[name]
    return default


def _enabled_branch_list(value):
    """Canonicalise a factor mapping while preserving explicit list order."""
    if value is None:
        return []
    if isinstance(value, dict):
        return sorted(str(name) for name, enabled in value.items() if enabled)
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list)):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    # Let the final JSON/YAML serialization report unsupported values rather
    # than silently converting a provenance object into a made-up branch.
    return value


def freeze_config(config_path, tune_results, out_path,
                  selection_metric=None, selection_rule=None,
                  case_set_version=None, case_sets=None, case_hashes=None,
                  source_hash=None, enabled_branches=None):
    """生成 FROZEN_CONFIG.yaml。

    config_path   : 被冻结的配置文件（default_mainline.yaml 等）
    tune_results  : tune 汇总（路径或 dict）；selected_tau 缺省时回退
                    为被冻结配置中的 tau（机制验证路径）
    out_path      : 输出 FROZEN_CONFIG.yaml 路径
    case_sets/case_hashes/source_hash/enabled_branches:
                    optional explicit provenance overrides.  When omitted,
                    values are read from the tune selection dict.  Existing
                    callers remain valid and receive unknown empty defaults;
                    ``source_hash`` is never derived from ``git_commit``.
    """
    cfg = load_config(config_path)
    tr = _load_tune_results(tune_results)
    tau = tr.get("selected_tau")
    if tau is None:
        tau = cfg.tau
    # Rebuild from the complete validated runtime snapshot.  Keeping an
    # explicit legacy field list here silently resets newly added branches
    # (for example E1-E4) when creating FROZEN_CONFIG; tau is the sole value
    # selected by tuning and is the only field intentionally overridden.
    frozen_values = cfg.to_dict()
    frozen_values["tau"] = tau
    frozen_cfg = MainlineConfig(**frozen_values)

    # The e-branch selection report uses ``tune_sha256`` and
    # ``selected_case_factors``; accept those equivalent names so freezing a
    # report does not require a lossy hand-written adapter.  No hash is
    # inferred from git metadata: absent source provenance remains N/A.
    frozen_case_sets = _selection_value(
        case_sets, tr, ("case_sets", "tune_sets", "case_set_paths"), {})
    frozen_case_hashes = _selection_value(
        case_hashes, tr, ("case_hashes", "tune_sha256", "case_sha256"), {})
    frozen_source_hash = _selection_value(
        source_hash, tr, ("source_hash", "source_sha256"), "N/A")
    frozen_enabled_branches = _enabled_branch_list(_selection_value(
        enabled_branches, tr,
        ("enabled_branches", "selected_case_factors", "selected_factors"),
        []))

    payload = frozen_cfg.to_dict()
    payload.update({
        "model_version": MODEL_VERSION,
        "spec_version": SPEC_VERSION,
        "case_set_version": case_set_version or tr.get("case_set") or "N/A",
        "selection_metric": selection_metric or tr.get("selection_metric") \
            or DEFAULT_SELECTION_METRIC,
        "selection_rule": selection_rule or tr.get("selection_rule") \
            or DEFAULT_SELECTION_RULE,
        "freeze_time": _now_iso(),
        "git_commit": git_commit(),
        "frozen_config_hash": config_sha256(config_path),
        "tune_results_hash": hashlib.sha256(
            json.dumps(tr, sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest(),
        "case_sets": frozen_case_sets,
        "case_hashes": frozen_case_hashes,
        "source_hash": frozen_source_hash,
        "enabled_branches": frozen_enabled_branches,
    })
    missing = [k for k in FROZEN_REQUIRED_FIELDS if k not in payload]
    if missing:  # pragma: no cover - 构造上不可能
        raise RuntimeError("frozen config missing fields: %r" % missing)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if _HAS_YAML:
        import yaml
        text = ("# FROZEN_CONFIG (Addendum B.6) — 冻结后正式评估不得修改 tau\n"
                + yaml.safe_dump(payload, allow_unicode=True,
                                 sort_keys=False))
    else:  # pragma: no cover
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return payload
