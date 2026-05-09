"""
End-to-end CMI pipeline test for Ask MedSync.

Tests: User question → LLM parse → CMI match → ranked results.

Usage:
    python3 test_cmi_e2e.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.query_parsing_agent import QAQueryParsingAgent
from app.agents.clinical.ais_clinical_engine.agents.qa.recommendation_matcher import RecommendationMatcher
from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations_by_id


TEST_QUESTIONS = [
    {
        "id": "CMI-01",
        "question": "What ASPECT score is required for EVT for an M1 occlusion at 10 hrs LKW?",
        "expect_cmi": True,
        "expect_vars": ["intervention", "vessel_occlusion", "time_window_hours"],
        "expect_top_rec": "rec-4.7.2-002",  # 6-24h COR 1
    },
    {
        "id": "CMI-02",
        "question": "Is EVT recommended for basilar artery occlusion?",
        "expect_cmi": True,
        "expect_vars": ["intervention", "vessel_occlusion"],
        "expect_top_rec": "rec-4.7.3-001",  # basilar COR 1
    },
    {
        "id": "CMI-03",
        "question": "What is the tenecteplase dose for acute stroke?",
        "expect_cmi": False,
        "expect_vars": [],
    },
    {
        "id": "CMI-04",
        "question": "Is EVT recommended for M1 within 6 hours with ASPECTS 8?",
        "expect_cmi": True,
        "expect_vars": ["intervention", "vessel_occlusion", "time_window_hours", "aspects_range"],
        "expect_top_rec": "rec-4.7.2-001",  # 0-6h COR 1
    },
    {
        "id": "CMI-05",
        "question": "What evidence supports late-window EVT?",
        "expect_cmi": False,  # evidence question
        "expect_vars": ["intervention", "time_window_hours"],
    },
    {
        "id": "CMI-06",
        "question": "Can a patient with NIHSS 12 and basilar occlusion get EVT?",
        "expect_cmi": True,
        "expect_vars": ["intervention", "vessel_occlusion", "nihss_range"],
        "expect_top_rec": "rec-4.7.3-001",
    },
]


async def main():
    # Setup
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try loading from .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
                        os.environ["ANTHROPIC_API_KEY"] = api_key
                        break

    if not api_key:
        print("ERROR: No ANTHROPIC_API_KEY found")
        sys.exit(1)

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    parser = QAQueryParsingAgent(nlp_client=client)
    matcher = RecommendationMatcher()
    matcher.set_recommendation_store(load_recommendations_by_id())

    print(f"Parser available: {parser.is_available}")
    print(f"Matcher available: {matcher.is_available}")
    print(f"{'='*70}")

    passed = 0
    failed = 0

    for tc in TEST_QUESTIONS:
        print(f"\n--- {tc['id']}: {tc['question']}")

        # Step 1: LLM parse
        parsed, usage = await parser.parse(tc["question"])
        print(f"  Parse: criterion_specific={parsed.is_criterion_specific} "
              f"confidence={parsed.extraction_confidence:.2f} "
              f"tokens={usage.get('input_tokens',0)}+{usage.get('output_tokens',0)}")
        print(f"  Vars: {parsed.get_scenario_variables()}")
        if parsed.intervention:
            print(f"    intervention={parsed.intervention}")
        if parsed.vessel_occlusion:
            print(f"    vessel={parsed.vessel_occlusion}")
        if parsed.time_window_hours:
            print(f"    time={parsed.time_window_hours}")
        if parsed.aspects_range:
            print(f"    aspects={parsed.aspects_range}")
        if parsed.nihss_range:
            print(f"    nihss={parsed.nihss_range}")
        if parsed.circulation:
            print(f"    circulation={parsed.circulation}")

        # Check criterion_specific flag
        ok = True
        if parsed.is_criterion_specific != tc["expect_cmi"]:
            print(f"  ❌ Expected is_criterion_specific={tc['expect_cmi']} "
                  f"but got {parsed.is_criterion_specific}")
            ok = False

        # Check expected variables were extracted
        actual_vars = parsed.get_scenario_variables()
        for expected_var in tc.get("expect_vars", []):
            if expected_var not in actual_vars:
                print(f"  ❌ Expected variable '{expected_var}' not extracted")
                ok = False

        # Step 2: CMI match (only for criterion-specific)
        if parsed.is_criterion_specific and parsed.get_scenario_variables():
            matches = matcher.match(parsed)
            print(f"  CMI: {len(matches)} matches")
            for m in matches[:5]:
                print(f"    T{m.tier} | {m.rec_id} | COR {m.rec_data.get('cor','')} | scope={m.scope_index}")

            # Check top rec
            if "expect_top_rec" in tc and matches:
                if matches[0].rec_id != tc["expect_top_rec"]:
                    print(f"  ❌ Expected top rec {tc['expect_top_rec']} "
                          f"but got {matches[0].rec_id}")
                    ok = False

        if ok:
            print(f"  ✅ PASSED")
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*70}")
    print(f"Results: {passed}/{passed+failed} passed")
    if failed:
        print(f"  {failed} FAILED")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
