# -*- coding: utf-8 -*-
"""Addendum F 图形烟雾测试：build_figures 全量重建 + 产物存在性。"""

import json
import os
import sys

import pytest

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODE_ROOT)

from experiment.plotting import EXPECTED_FIGURES, build_figures  # noqa: E402

RESULTS = os.path.join(CODE_ROOT, "results")
FIGURES = os.path.join(CODE_ROOT, "figures")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(os.path.join(RESULTS, "figure_runs")),
    reason="figure_runs 数据未生成（需先跑图处跑局）")


@pytest.fixture(scope="module")
def manifest():
    return build_figures(RESULTS, out_dir=FIGURES)


def test_all_scripts_ok(manifest):
    assert manifest["all_scripts_ok"], \
        [r for r in manifest["plot_scripts"] if not r["ok"]]
    assert len(manifest["plot_scripts"]) == 8


def test_all_figures_present(manifest):
    assert manifest["all_figures_present"]
    for key, v in manifest["produced"].items():
        assert v["pdf"] and v["png"], key


def test_figure_data_files(manifest):
    """每图配套 figure_data（CSV 或 JSON）存在且非空。"""
    for i in range(1, 9):
        candidates = [os.path.join(FIGURES, "fig%d_%s" % (i, suffix))
                      for suffix in ("data.json", "data.csv", "meta.json")]
        assert any(os.path.isfile(c) and os.path.getsize(c) > 0
                   for c in candidates), "fig%d data missing" % i


def test_manifest_on_disk(manifest):
    mp = os.path.join(FIGURES, "figures_manifest.json")
    assert os.path.isfile(mp)
    with open(mp, encoding="utf-8") as f:
        disk = json.load(f)
    assert disk["all_figures_present"]
    assert set(disk["expected_figures"]) == set(EXPECTED_FIGURES)
