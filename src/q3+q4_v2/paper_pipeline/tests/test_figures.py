from pathlib import Path
import sys

from PIL import Image


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.plot_paper_figures import expected_figure_names


REPO_ROOT = Path(__file__).resolve().parents[4]
FIGURE_ROOT = REPO_ROOT / "src/q3+q4_v2/paper_evidence/figures"


def test_expected_figure_contract_has_nine_unique_jpegs():
    names = expected_figure_names()
    assert len(names) == 9
    assert len(set(names)) == 9
    assert all(name.endswith(".jpg") for name in names)


def test_generated_figure_directory_contains_only_valid_jpegs():
    names = expected_figure_names()
    assert sorted(path.name for path in FIGURE_ROOT.iterdir()) == sorted(names)
    for name in names:
        with Image.open(FIGURE_ROOT / name) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"
            assert min(image.size) >= 1600
