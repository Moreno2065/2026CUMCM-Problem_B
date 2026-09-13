# -*- coding: utf-8 -*-
"""FROZEN_CONFIG provenance metadata regression tests."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import experiment.freeze as freeze_module
from experiment.config import load_config
from experiment.freeze import freeze_config


def _config(tmp_path):
    path = tmp_path / "candidate.yaml"
    path.write_text(
        "policy: mainline\n"
        "tau: 0.15\n"
        "q4_certificate_layout: sparse25\n"
        "q4_residual_sparsify: true\n",
        encoding="utf-8",
    )
    return path


def test_freeze_writes_explicit_provenance_metadata(tmp_path, monkeypatch):
    cfg_path = _config(tmp_path)
    out = tmp_path / "FROZEN_CONFIG.yaml"
    monkeypatch.setattr(freeze_module, "git_commit", lambda: "N/A")

    selection = {
        "selected_tau": 0.08,
        "case_sets": {
            "q3": "cases/e_branches_v1/tune/tune_q3.json",
            "q4": "cases/e_branches_v1/tune/tune_q4.json",
        },
        "case_hashes": {
            "q3": "sha256:q3-case-set",
            "q4": "sha256:q4-case-set",
        },
        "source_hash": "sha256:source-snapshot",
        "enabled_branches": ["E1", "E4"],
    }

    payload = freeze_config(str(cfg_path), selection, str(out))

    assert payload["case_sets"] == selection["case_sets"]
    assert payload["case_hashes"] == selection["case_hashes"]
    assert payload["source_hash"] == "sha256:source-snapshot"
    assert payload["enabled_branches"] == ["E1", "E4"]
    assert payload["git_commit"] == "N/A"

    # The metadata is part of the frozen artifact, not only the return value.
    if freeze_module._HAS_YAML:
        import yaml
        disk = yaml.safe_load(out.read_text(encoding="utf-8"))
    else:  # pragma: no cover - hosted test environments have PyYAML
        disk = json.loads(out.read_text(encoding="utf-8"))
    for key in ("case_sets", "case_hashes", "source_hash",
                "enabled_branches"):
        assert disk[key] == payload[key]
    # Provenance fields must not become runtime configuration keys.
    frozen = load_config(str(out))
    assert frozen.q4_certificate_layout == "sparse25"
    assert frozen.q4_residual_sparsify is True


def test_freeze_reads_selection_aliases_without_fabricating_git_sha(
        tmp_path, monkeypatch):
    """Existing selection reports can use their current equivalent names."""
    cfg_path = _config(tmp_path)
    out = tmp_path / "FROZEN_CONFIG.yaml"
    monkeypatch.setattr(freeze_module, "git_commit", lambda: "N/A")

    payload = freeze_config(
        str(cfg_path),
        {
            "selected_tau": 0.08,
            "case_sets": {"q3": "q3.json", "q4": "q4.json"},
            "tune_sha256": {"q3": "q3-hash", "q4": "q4-hash"},
            "source_sha256": "source-hash-explicit",
            "selected_case_factors": {
                "E1": True, "E2": False, "E3": False, "E4": True,
            },
        },
        str(out),
    )

    assert payload["case_hashes"] == {"q3": "q3-hash", "q4": "q4-hash"}
    assert payload["source_hash"] == "source-hash-explicit"
    assert payload["enabled_branches"] == ["E1", "E4"]
    assert payload["git_commit"] == "N/A"
    assert payload["source_hash"] != payload["git_commit"]


def test_freeze_explicit_provenance_kwargs_override_selection(tmp_path):
    cfg_path = _config(tmp_path)
    out = tmp_path / "FROZEN_CONFIG.yaml"

    payload = freeze_config(
        str(cfg_path),
        {
            "selected_tau": 0.08,
            "case_sets": {"q3": "selection-q3.json"},
            "case_hashes": {"q3": "selection-q3-hash"},
            "source_hash": "selection-source-hash",
            "enabled_branches": ["E2"],
        },
        str(out),
        case_sets={"q3": "explicit-q3.json", "q4": "explicit-q4.json"},
        case_hashes={"q3": "explicit-q3-hash",
                     "q4": "explicit-q4-hash"},
        source_hash="explicit-source-hash",
        enabled_branches=["E1", "E4"],
    )

    assert payload["case_sets"] == {
        "q3": "explicit-q3.json", "q4": "explicit-q4.json",
    }
    assert payload["case_hashes"] == {
        "q3": "explicit-q3-hash", "q4": "explicit-q4-hash",
    }
    assert payload["source_hash"] == "explicit-source-hash"
    assert payload["enabled_branches"] == ["E1", "E4"]


def test_freeze_old_selection_remains_compatible(tmp_path):
    """Legacy tune output still freezes and gets explicit unknown metadata."""
    cfg_path = _config(tmp_path)
    out = tmp_path / "FROZEN_CONFIG.yaml"

    payload = freeze_config(
        str(cfg_path),
        {"selected_tau": 0.05, "case_set": "tune_q3.json",
         "results": []},
        str(out),
    )

    assert payload["tau"] == 0.05
    assert payload["case_set_version"] == "tune_q3.json"
    assert payload["case_sets"] == {}
    assert payload["case_hashes"] == {}
    assert payload["source_hash"] == "N/A"
    assert payload["enabled_branches"] == []
