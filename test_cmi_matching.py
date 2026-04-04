"""
Quick validation of CMI matching for Ask MedSync.

Tests the RecommendationMatcher against known scenarios
to verify tiering, applicability gating, and scope index.

Usage:
    python3 test_cmi_matching.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.schemas import ParsedQAQuery
from app.agents.clinical.ais_clinical_engine.agents.qa.recommendation_matcher import RecommendationMatcher
from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations_by_id


def build_matcher():
    matcher = RecommendationMatcher()
    matcher.set_recommendation_store(load_recommendations_by_id())
    return matcher


def test_m1_at_10h(matcher):
    """M1 occlusion at 10h LKW — should find 6-24h recs, exclude 0-6h recs."""
    print("\n=== TEST: M1 at 10h LKW ===")
    query = ParsedQAQuery(
        is_criterion_specific=True,
        intervention="EVT",
        circulation="anterior",
        vessel_occlusion=["M1"],
        time_window_hours={"min": 10, "max": 10},
        extraction_confidence=0.95,
        clinical_question="What ASPECT score is required for EVT for an M1 occlusion at 10 hrs LKW?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    for r in results:
        print(f"  T{r.tier} | {r.rec_id} | COR {r.rec_data.get('cor','')} | scope={r.scope_index} | {r.tier_reason}")

    # Verify: 0-6h recs should NOT appear
    rec_ids = [r.rec_id for r in results]
    assert "rec-4.7.2-001" not in rec_ids, "FAIL: 0-6h rec should be excluded for 10h patient"
    assert "rec-4.7.2-004" not in rec_ids, "FAIL: 0-6h large-core rec should be excluded"
    assert "rec-4.7.2-005" not in rec_ids, "FAIL: 0-6h mRS 2 rec should be excluded"
    assert "rec-4.7.2-006" not in rec_ids, "FAIL: 0-6h mRS 3-4 rec should be excluded"

    # Verify: 6-24h recs SHOULD appear
    assert "rec-4.7.2-002" in rec_ids, "FAIL: 6-24h COR 1 rec should appear"
    assert "rec-4.7.2-003" in rec_ids, "FAIL: 6-24h ASPECTS 3-5 rec should appear"

    # Verify: basilar recs should NOT appear
    assert "rec-4.7.3-001" not in rec_ids, "FAIL: basilar rec should be excluded for anterior"

    # Verify: M2-only rec should NOT appear
    assert "rec-4.7.2-007" not in rec_ids, "FAIL: M2-only rec should be excluded for M1"

    print("  ✅ PASSED: 0-6h excluded, 6-24h present, basilar excluded, M2 excluded")


def test_basilar(matcher):
    """Basilar occlusion — should find 4.7.3 recs, exclude anterior recs."""
    print("\n=== TEST: Basilar EVT ===")
    query = ParsedQAQuery(
        is_criterion_specific=True,
        intervention="EVT",
        circulation="basilar",
        vessel_occlusion=["basilar"],
        extraction_confidence=0.95,
        clinical_question="Is EVT recommended for basilar artery occlusion?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    for r in results:
        print(f"  T{r.tier} | {r.rec_id} | COR {r.rec_data.get('cor','')} | scope={r.scope_index}")

    rec_ids = [r.rec_id for r in results]
    assert "rec-4.7.3-001" in rec_ids, "FAIL: basilar COR 1 rec should appear"
    assert "rec-4.7.3-002" in rec_ids, "FAIL: basilar COR 2b rec should appear"

    # COR 1 should be before COR 2b
    idx_cor1 = rec_ids.index("rec-4.7.3-001")
    idx_cor2b = rec_ids.index("rec-4.7.3-002")
    assert idx_cor1 < idx_cor2b, f"FAIL: COR 1 should be before COR 2b (got {idx_cor1} vs {idx_cor2b})"

    # Anterior recs should NOT appear
    assert "rec-4.7.2-001" not in rec_ids, "FAIL: anterior rec should be excluded for basilar"

    print("  ✅ PASSED: basilar recs present in COR order, anterior excluded")


def test_m1_at_3h(matcher):
    """M1 at 3h — should find 0-6h recs, exclude 6-24h recs."""
    print("\n=== TEST: M1 at 3h ===")
    query = ParsedQAQuery(
        is_criterion_specific=True,
        intervention="EVT",
        circulation="anterior",
        vessel_occlusion=["M1"],
        time_window_hours={"min": 3, "max": 3},
        extraction_confidence=0.95,
        clinical_question="Is EVT recommended for M1 at 3 hours?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    for r in results:
        print(f"  T{r.tier} | {r.rec_id} | COR {r.rec_data.get('cor','')} | scope={r.scope_index}")

    rec_ids = [r.rec_id for r in results]
    # 0-6h recs should appear
    assert "rec-4.7.2-001" in rec_ids, "FAIL: 0-6h COR 1 rec should appear"
    # 6-24h recs should be excluded
    assert "rec-4.7.2-002" not in rec_ids, "FAIL: 6-24h rec should be excluded for 3h patient"
    assert "rec-4.7.2-003" not in rec_ids, "FAIL: 6-24h large-core rec should be excluded"

    print("  ✅ PASSED: 0-6h recs present, 6-24h excluded")


def test_m3_no_benefit(matcher):
    """M3 occlusion — should find COR 3:No Benefit rec."""
    print("\n=== TEST: M3 occlusion (trick question) ===")
    query = ParsedQAQuery(
        is_criterion_specific=True,
        intervention="EVT",
        circulation="anterior",
        vessel_occlusion=["M3"],
        extraction_confidence=0.95,
        clinical_question="What is the time window for EVT for an M3 occlusion?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    for r in results:
        print(f"  T{r.tier} | {r.rec_id} | COR {r.rec_data.get('cor','')} | scope={r.scope_index}")

    # Should NOT find any ICA/M1 recs
    rec_ids = [r.rec_id for r in results]
    assert "rec-4.7.2-001" not in rec_ids, "FAIL: ICA/M1 rec should be excluded for M3"

    print("  ✅ PASSED: ICA/M1 recs excluded for M3 query")


def test_general_question_no_match(matcher):
    """General question with no criteria — should return empty."""
    print("\n=== TEST: General question (no variables) ===")
    query = ParsedQAQuery(
        is_criterion_specific=False,
        extraction_confidence=0.9,
        clinical_question="What is the tenecteplase dose?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    assert len(results) == 0, "FAIL: general question should return no CMI matches"
    print("  ✅ PASSED: no matches for non-criterion-specific question")


def test_basilar_with_nihss(matcher):
    """Basilar with specific NIHSS — should discriminate COR 1 vs COR 2b."""
    print("\n=== TEST: Basilar with NIHSS 12, PC-ASPECTS 7 ===")
    query = ParsedQAQuery(
        is_criterion_specific=True,
        intervention="EVT",
        circulation="basilar",
        vessel_occlusion=["basilar"],
        nihss_range={"min": 12, "max": 12},
        pc_aspects_range={"min": 7, "max": 7},
        premorbid_mrs={"min": 0, "max": 0},
        extraction_confidence=0.95,
        clinical_question="Is EVT recommended for basilar occlusion, NIHSS 12, PC-ASPECTS 7?",
    )

    results = matcher.match(query)
    print(f"Results: {len(results)} matches")
    for r in results:
        print(f"  T{r.tier} | {r.rec_id} | COR {r.rec_data.get('cor','')} | scope={r.scope_index}")

    rec_ids = [r.rec_id for r in results]
    # COR 1 (NIHSS >=10) should match — NIHSS 12 is >=10
    assert "rec-4.7.3-001" in rec_ids, "FAIL: COR 1 basilar (NIHSS >=10) should match NIHSS 12"
    # COR 2b (NIHSS 6-9) should be EXCLUDED — NIHSS 12 is outside 6-9
    assert "rec-4.7.3-002" not in rec_ids, "FAIL: COR 2b basilar (NIHSS 6-9) should be excluded for NIHSS 12"

    print("  ✅ PASSED: COR 1 matches, COR 2b excluded by NIHSS applicability")


def main():
    print("Loading matcher...")
    matcher = build_matcher()
    print(f"Criteria loaded: {len(matcher._criteria)} recs")
    print(f"Rec store loaded: {len(matcher._rec_store)} recs")

    test_m1_at_10h(matcher)
    test_basilar(matcher)
    test_m1_at_3h(matcher)
    test_m3_no_benefit(matcher)
    test_general_question_no_match(matcher)
    test_basilar_with_nihss(matcher)

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)


if __name__ == "__main__":
    main()
