from pathlib import Path
import sys


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT.parent))

from paper_pipeline.evidence_manifest import build_source_manifest


REPO_ROOT = Path(__file__).resolve().parents[4]
NARRATIVE = "src/q3+q4_v2/Q3_Q4_Paper_Model_Narrative_v2.0.md"
Q3_ENGINE = "src/q3+q4_v2/absorbed/q3_v5/q3_optimizer_v5.py"
Q4_LOCK = "src/q3+q4_v2/absorbed/q4_v4/locked.py"


def test_narrative_file_is_v1_only():
    manifest = build_source_manifest(REPO_ROOT)
    row = manifest.by_relpath[NARRATIVE]
    assert row["generation"] == "v1"
    assert row["role"] == "guarantee_narrative"


def test_absorbed_engines_are_final_v2():
    manifest = build_source_manifest(REPO_ROOT)
    assert manifest.by_relpath[Q3_ENGINE]["generation"] == "v2"
    assert manifest.by_relpath[Q3_ENGINE]["role"] == "final_engine"
    assert manifest.by_relpath[Q4_LOCK]["generation"] == "v2"
    assert manifest.by_relpath[Q4_LOCK]["role"] == "final_engine_lock"


def test_manifest_hashes_are_complete_and_repeatable():
    first = build_source_manifest(REPO_ROOT)
    second = build_source_manifest(REPO_ROOT)
    assert first.records == second.records
    assert first.records
    for row in first.records:
        assert len(row["sha256"]) == 64
        assert row["size_bytes"] > 0
        assert (REPO_ROOT / row["relpath"]).is_file()
