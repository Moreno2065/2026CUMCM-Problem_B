"""Scientifically interpretable ablation and sensitivity registry."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

PACKAGE_PARENT = Path(__file__).resolve().parent.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


def effective_parameters(base: dict, overrides: dict) -> dict:
    unknown = set(overrides) - set(base)
    if unknown:
        raise KeyError(f"unknown engine parameter(s): {sorted(unknown)}")
    result = deepcopy(base)
    result.update(deepcopy(overrides))
    return result


def build_registry() -> dict:
    from absorbed.q3_v5.q3_optimizer_v5 import SELECTED_PARAMETERS
    from absorbed.q4_v4.locked import LOCKED_PARAMETERS

    base = {
        "q3": deepcopy(SELECTED_PARAMETERS),
        "q4": deepcopy(LOCKED_PARAMETERS),
    }
    variants = [
        {
            "variant_id": "q3_full",
            "question": "q3",
            "label_zh": "完整 V2",
            "component": "full",
            "overrides": {},
        },
        {
            "variant_id": "q3_no_joint_route",
            "question": "q3",
            "label_zh": "无联合路线",
            "component": "joint_route",
            "overrides": {"route_mode": "scan_first"},
        },
        {
            "variant_id": "q3_no_shared_probe",
            "question": "q3",
            "label_zh": "无共享探点",
            "component": "shared_probe",
            "overrides": {"share_at_search": False},
        },
        {
            "variant_id": "q3_no_site_projection",
            "question": "q3",
            "label_zh": "无连续站点投影",
            "component": "site_projection",
            "overrides": {"planning_radius": 0},
        },
        {
            "variant_id": "q3_no_site_refinement",
            "question": "q3",
            "label_zh": "无站点路线细化",
            "component": "site_refinement",
            "overrides": {"site_passes": 0},
        },
        {
            "variant_id": "q3_no_trial_clear",
            "question": "q3",
            "label_zh": "无试探清除",
            "component": "trial_clear",
            "overrides": {"trial_radius": 0},
        },
        {
            "variant_id": "q4_full",
            "question": "q4",
            "label_zh": "完整 V2",
            "component": "full",
            "overrides": {},
        },
        {
            "variant_id": "q4_no_exact_insertion",
            "question": "q4",
            "label_zh": "无精确源插入",
            "component": "exact_insertion",
            "overrides": {"exact_insert": False},
        },
        {
            "variant_id": "q4_no_rotation",
            "question": "q4",
            "label_zh": "无初始旋转选择",
            "component": "initial_rotation",
            "overrides": {"initial_rotation_steps": 0},
        },
        {
            "variant_id": "q4_no_crossbar",
            "question": "q4",
            "label_zh": "无 crossbar 探点",
            "component": "crossbar",
            "overrides": {"crossbar": False},
        },
        {
            "variant_id": "q4_no_negative_update",
            "question": "q4",
            "label_zh": "无负区域更新",
            "component": "negative_region",
            "overrides": {"negative_regions": False},
        },
        {
            "variant_id": "q4_no_trial_clear",
            "question": "q4",
            "label_zh": "无试探清除",
            "component": "trial_clear",
            "overrides": {"trial_radius": 0},
        },
        {
            "variant_id": "q4_no_count_stop",
            "question": "q4",
            "label_zh": "无 16 源基数停止",
            "component": "count_stop",
            "overrides": {"stop_when_found16": False},
        },
    ]
    tuning = [
        {"question": "q3", "parameter": "probe", "locked_value": 250,
         "values": [150, 250, 350]},
        {"question": "q3", "parameter": "share_ratio", "locked_value": 0.7,
         "values": [0.5, 0.7, 0.9]},
        {"question": "q3", "parameter": "trial_radius", "locked_value": 40,
         "values": [20, 40, 60]},
        {"question": "q3", "parameter": "planning_radius", "locked_value": 1500,
         "values": [1000, 1500, 1800]},
        {"question": "q4", "parameter": "radio_limit", "locked_value": 12,
         "values": [8, 12, 16]},
        {"question": "q4", "parameter": "crossbar_offset", "locked_value": 0.03,
         "values": [0.02, 0.03, 0.05]},
        {"question": "q4", "parameter": "crossbar_fraction", "locked_value": 0.25,
         "values": [0.15, 0.25, 0.4]},
        {"question": "q4", "parameter": "initial_rotation_steps", "locked_value": 12,
         "values": [6, 12, 18]},
        {"question": "q4", "parameter": "trial_radius", "locked_value": 40.0,
         "values": [20.0, 40.0, 60.0]},
    ]
    return {
        "schema_version": 1,
        "base_parameters": base,
        "variants": variants,
        "tuning": tuning,
        "non_identifiable": [
            {
                "question": "q3",
                "component": "count_stop",
                "reason": "Q3 v5 implements the 16-source stop unconditionally and exposes no switch.",
            }
        ],
    }


def write_registry(path: Path | str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_registry(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "paper_evidence" / "variant_registry.json"
    write_registry(default)
