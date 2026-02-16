"""
Direct test of Clinical Support Engine to extract internal metadata
"""
import asyncio
import sys
import json
sys.path.insert(0, 'c:/Users/danie/Documents/gitHub/medsyncai_agentic_version_vs2')

from medsync_ai_v2.engines.clinical_support_engine.engine import ClinicalSupportEngine, PatientParser
from dotenv import load_dotenv
load_dotenv()

async def test_clinical_case():
    # Test case: 62F, LKW 10h, NIHSS 15, ASPECTS 8, M1 occlusion, perfusion data
    query = "62-year-old female, last known well 10 hours ago, NIHSS 15, mRS 0, ASPECTS 8, CTA shows left M1 occlusion, CTP shows core infarct 40cc, mismatch volume 50cc, mismatch ratio 3"

    # Initialize engine
    engine = ClinicalSupportEngine()

    # Run the engine
    print("=" * 80)
    print("TESTING CLINICAL SUPPORT ENGINE")
    print("=" * 80)
    print(f"\nQuery: {query}\n")

    # Engine expects input_data as dict with 'raw_query' or 'normalized_query' key
    input_data = {"raw_query": query, "normalized_query": query}
    result = await engine.run(input_data, session_state={})

    # Extract key metadata
    print("\n" + "=" * 80)
    print("INTERNAL METADATA")
    print("=" * 80)

    clinical_context = result.get("clinical_context", {})

    # Complexity flag
    complexity = clinical_context.get("complexity", "NOT FOUND")
    print(f"\n✓ COMPLEXITY FLAG: {complexity.upper()}")

    # Edge cases
    edge_cases = clinical_context.get("edge_cases", [])
    print(f"\n✓ EDGE CASES FLAGGED: {len(edge_cases)}")
    if edge_cases:
        for ec in edge_cases:
            print(f"  - {ec}")

    # Vector searches
    vector_context = clinical_context.get("vector_context", [])
    print(f"\n✓ VECTOR SEARCHES FIRED: {len(vector_context)}")
    if vector_context:
        for i, vc in enumerate(vector_context, 1):
            print(f"  {i}. {vc.get('query', 'N/A')[:100]}")

    # Eligibility results summary
    eligibility = clinical_context.get("eligibility", [])
    print(f"\n✓ ELIGIBILITY PATHWAYS EVALUATED: {len(eligibility)}")
    for pathway in eligibility:
        treatment = pathway.get("treatment", "Unknown")
        elig_status = pathway.get("eligibility", "Unknown")
        cor = pathway.get("cor", "N/A")
        loe = pathway.get("loe", "N/A")
        print(f"  - {treatment}: {elig_status} (COR {cor}, LOE {loe})")

    # Trial context
    trial_context = clinical_context.get("trial_context", {})
    print(f"\n✓ TRIAL METRICS RESOLVED: {len(trial_context)} trials")
    if trial_context:
        for trial, data in list(trial_context.items())[:5]:
            print(f"  - {trial}")

    print("\n" + "=" * 80)
    print("FINAL OUTPUT PREVIEW (first 500 chars)")
    print("=" * 80)
    final_text = result.get("final_text", "")
    print(final_text[:500])
    print("...")

    return result

if __name__ == "__main__":
    result = asyncio.run(test_clinical_case())
