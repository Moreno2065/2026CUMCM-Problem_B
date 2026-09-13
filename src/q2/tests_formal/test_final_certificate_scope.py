"""T10: certificate scope and wording discipline (closure spec s.2, s.3,
s.42, s.50-52)."""

import json
from pathlib import Path

ARTIFACTS = Path("src/q2/artifacts/formal")

ALLOWED_STATUS = {
    "CERTIFIED_EXACT_ZERO_ALL_NEAR",
    "CERTIFIED_GLOBAL_EPS_OPTIMUM",
    "CERTIFIED_GLOBAL_OPTIMUM_TO_NUMERICAL_ENCLOSURE",
    "CERTIFIED_GLOBAL_BOUND",
    "GLOBAL_EPS_CERTIFICATE_CANDIDATE",
    "NUMERICALLY_STABLE_NOT_CERTIFIED",
    "INCOMPLETE_CERTIFICATE_TIMEOUT",
    "BLOCKED_PROOF_GAP",
    "BLOCKED_INTERVAL_UNSOUNDNESS",
    "BLOCKED_INNER_MAX_INCOMPLETENESS",
    "BLOCKED_WITNESS_RECOVERY",
    "BLOCKED_MODEL_COUNTEREXAMPLE",
    "BLOCKED_PROOF_TREE_COVERAGE",
    "BLOCKED_RIGOROUS_TREE_REPLAY",
}


def _cert():
    p = ARTIFACTS / "q2_global_optimality_certificate.json"
    if not p.exists():
        import pytest
        pytest.skip("certificate JSON not generated yet")
    return json.loads(p.read_text(encoding="utf-8"))


def test_t10_scope_is_canonical_center_case(certificate_json):
    scope = certificate_json.get("certificate_scope",
                                 certificate_json.get("scope"))
    assert scope == "canonical_center_case"
    assert certificate_json["epsilon_deg"] == "1"


def test_t10_incumbent_symbol_is_s2_hat(certificate_json):
    assert certificate_json.get("incumbent_symbol", "S2_hat") == "S2_hat"
    # the incumbent coordinates are the frozen candidate, never written as
    # an exact argmin
    assert certificate_json["incumbent_S2"] == ["805.1110506884",
                                                "-599.7632926544"]
    assert certificate_json["certified_global_optimum"] is False


def test_t10_status_is_from_the_allowed_vocabulary(certificate_json):
    assert certificate_json["status"] in ALLOWED_STATUS
    text = json.dumps(certificate_json)
    for banned in ("PROBABLY_GLOBAL_OPTIMUM", "ESSENTIALLY_CERTIFIED",
                   "EMPIRICALLY_PROVEN"):
        assert banned not in text


def test_t10_engines_and_roles_recorded(certificate_json):
    d = certificate_json
    if d["status"] == "CERTIFIED_GLOBAL_EPS_OPTIMUM":
        assert d["symmetry_lemma_analytic"] is True
        assert d["half_domain_reduction_certified"] is True
        assert d["proof_tree_complete"] is True
        assert d["proof_tree_coverage_verified"] is True
        assert d["historical_prunes_replayed"] is True
        assert d["unverified_pruned_nodes"] == 0
        assert d["float_batch_engine_used_only_for_search"] is True
        assert d["sampling_used_as_proof"] is False
        assert d["unique_optimizer"] == "NOT_PROVEN"


def test_t10_symmetry_lemma_document_exists():
    doc = Path("src/q2/Q2_CANONICAL_SYMMETRY_LEMMA.md")
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for token in ("Lemma A1", "Lemma A2", "Lemma A3", "Lemma A4",
                  "Lemma A5", "Lemma A6", "Theorem A", "Corollary A",
                  "canonical_center_case"):
        assert token in text, token
    art = json.loads((ARTIFACTS / "canonical_symmetry_lemma.json")
                     .read_text(encoding="utf-8"))
    assert art["status"] == "PROVEN_ANALYTIC"
