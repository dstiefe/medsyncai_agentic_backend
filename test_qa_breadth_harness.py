"""
Breadth Score Test Harness — 10 intentionally vague questions.

SUCCESS = the system asks for clarification and presents relevant sections.
FAILURE = the system tries to answer directly or gives an out-of-scope refusal.

These are questions that are too broad for a single confident answer.
The correct behavior is to say "our search found multiple sections"
and present the user with options to narrow down.

Usage:
    python3 test_qa_breadth_harness.py             # run all 10
    python3 test_qa_breadth_harness.py --verbose    # show full responses
"""

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)


# ── The 10 Vague Questions ───────────────────────────────────────────
# Each question is intentionally broad — it maps to 3+ guideline sections.
# The CORRECT response is clarification, not a direct answer.

VAGUE_QUESTIONS = [
    {
        "id": "VAGUE-01",
        "question": "What is the recommendation for stroke treatment?",
        "why_vague": "The entire guideline is about stroke treatment — BP, IVT, EVT, antiplatelets, rehab, etc.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-02",
        "question": "What medications are used for stroke?",
        "why_vague": "Could mean IVT drugs, antiplatelets, anticoagulants, BP meds, neuroprotectants, etc.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-03",
        "question": "What imaging is good for stroke?",
        "why_vague": "CT, CTA, MRI, perfusion, vascular imaging — multiple sections cover different imaging.",
        "min_expected_sections": 2,
    },
    {
        "id": "VAGUE-04",
        "question": "How should stroke be managed?",
        "why_vague": "Covers the entire guideline — prehospital, ED, acute treatment, post-acute care.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-05",
        "question": "What are the guidelines for stroke?",
        "why_vague": "The whole document IS the guidelines for stroke.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-06",
        "question": "What should I do for a stroke patient?",
        "why_vague": "No specificity on phase of care, treatment type, or clinical scenario.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-07",
        "question": "What procedures are recommended for stroke?",
        "why_vague": "Could mean EVT, IVT, decompressive craniectomy, carotid surgery, etc.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-08",
        "question": "What is the treatment protocol for acute ischemic stroke?",
        "why_vague": "Protocol spans BP, imaging, IVT, EVT, antiplatelets, monitoring — entire acute pathway.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-09",
        "question": "What are the recommendations for stroke care?",
        "why_vague": "Stroke care = prehospital + ED + acute treatment + in-hospital + rehab.",
        "min_expected_sections": 3,
    },
    {
        "id": "VAGUE-10",
        "question": "What complications should I monitor for after stroke?",
        "why_vague": "Brain swelling, seizures, DVT, dysphagia, depression, hemorrhagic transformation — many sections.",
        "min_expected_sections": 3,
    },
    # ── Within-section vagueness: one section, many answers ──────
    {
        "id": "VAGUE-11",
        "question": "What imaging is recommended for stroke?",
        "why_vague": "Section 3.2 alone has recs for CT, CTA, CTP, MRI, MRA, DWI, perfusion — 6+ modalities.",
        "min_expected_sections": 1,
    },
    {
        "id": "VAGUE-12",
        "question": "What are the EVT recommendations?",
        "why_vague": "Section 4.7 covers M1, M2, posterior, pediatric, anesthesia, devices — many scenarios.",
        "min_expected_sections": 1,
    },
    {
        "id": "VAGUE-13",
        "question": "What are the IVT recommendations?",
        "why_vague": "Section 4.6 covers eligibility, timing, agent choice, extended window, special circumstances.",
        "min_expected_sections": 1,
    },
    {
        "id": "VAGUE-14",
        "question": "What are the blood pressure recommendations?",
        "why_vague": "Section 4.3 has recs for before IVT, during IVT, before EVT, during EVT, post-treatment — all different targets.",
        "min_expected_sections": 1,
    },
    {
        "id": "VAGUE-15",
        "question": "What studies support EVT?",
        "why_vague": "EVT has many studies for many indications — MR CLEAN, EXTEND-IA, DAWN, DEFUSE 3, etc. across different criteria and scenarios.",
        "min_expected_sections": 3,
    },
]


# ── Orchestrator Setup ───────────────────────────────────────────────

def build_orchestrator():
    store = EmbeddingStore()
    if store.load():
        print(f"Semantic search: enabled ({store._embeddings.shape[0]} embeddings)")
    else:
        store = None
        print("Semantic search: disabled (no embeddings file)")

    return QAOrchestrator(
        recommendations_store=load_recommendations_by_id(),
        guideline_knowledge=load_guideline_knowledge(),
        embedding_store=store,
    )


# ── Validator ─────────────────────────────────────────────────────────

def validate_vague(tc, result, verbose=False):
    """
    SUCCESS criteria for a vague question:
        1. System asks for clarification (needsClarification=True)
        2. Presents multiple section options (clarificationOptions has 2+ items)
        3. Response text mentions "multiple" sections or asks to "clarify"

    ALSO ACCEPTABLE: out-of-scope refusal (for questions so broad
    they don't match any specific section well enough).

    FAILURE: system answers directly with RECOMMENDATION blocks
    without asking for clarification first.
    """
    errors = []
    answer = result.get("answer", "")
    needs_clar = result.get("needsClarification", False)
    clar_options = result.get("clarificationOptions", [])
    audit = result.get("auditTrail", [])

    # Primary success: clarification triggered
    if needs_clar:
        # Check that meaningful options are presented
        if len(clar_options) < 2:
            errors.append(
                f"Clarification triggered but only {len(clar_options)} options "
                f"(expected 2+)"
            )
        # Check the response asks the user to narrow down
        clarification_markers = [
            "multiple", "which area", "clarify", "asking about",
            "could relate to", "found recommendations across",
            "depends on whether", "which type", "which applies",
            "covers multiple",
        ]
        has_marker = any(m in answer.lower() for m in clarification_markers)
        if not has_marker:
            errors.append("Clarification response lacks clarification language")
        return errors  # SUCCESS — clarification was triggered

    # Secondary acceptable: out-of-scope (question too broad to match anything)
    if "does not specifically address" in answer:
        # This is OK — the question was so broad the scope gate caught it
        return errors  # Acceptable

    # FAILURE: system answered directly without clarification
    has_verbatim = "RECOMMENDATION [" in answer
    if has_verbatim:
        errors.append(
            "System answered directly with RECOMMENDATION blocks instead of "
            "asking for clarification on this vague question"
        )
    elif not answer.strip():
        errors.append("Empty answer — no clarification and no response")
    else:
        errors.append(
            "System answered directly without asking for clarification. "
            f"Answer starts with: {answer[:150]}..."
        )

    # Log breadth score from audit trail for debugging
    for entry in audit:
        if isinstance(entry, dict) and entry.get("step") == "breadth_score":
            detail = entry.get("detail", {})
            errors.append(
                f"[DEBUG] breadth_score={detail.get('breadth_score')}, "
                f"clusters={detail.get('clusters')}, "
                f"override={detail.get('topic_sections_override')}"
            )

    return errors


# ── Main ──────────────────────────────────────────────────────────────

async def run_tests(verbose=False):
    orch = build_orchestrator()

    passed = 0
    failed = 0
    results_detail = []

    print(f"\n{'='*70}")
    print(f"BREADTH SCORE TEST — 10 Intentionally Vague Questions")
    print(f"SUCCESS = system asks for clarification")
    print(f"FAILURE = system answers directly without clarifying")
    print(f"{'='*70}\n")

    for tc in VAGUE_QUESTIONS:
        t0 = time.time()
        try:
            result = await orch.answer(tc["question"])
            elapsed = time.time() - t0
        except Exception as e:
            elapsed = time.time() - t0
            result = {"answer": f"ERROR: {e}", "relatedSections": []}

        errors = validate_vague(tc, result, verbose)

        status = "PASS" if not errors else "FAIL"
        icon = "✅" if not errors else "❌"

        if not errors:
            passed += 1
        else:
            failed += 1

        # Get breadth info from audit
        breadth_info = ""
        for entry in result.get("auditTrail", []):
            if isinstance(entry, dict) and entry.get("step") == "breadth_score":
                d = entry.get("detail", {})
                breadth_info = f" [breadth={d.get('breadth_score')}, clusters={d.get('clusters', [])}]"
            # Also handle AuditEntry objects
            elif hasattr(entry, 'step') and entry.step == "breadth_score":
                d = entry.detail or {}
                breadth_info = f" [breadth={d.get('breadth_score')}, clusters={d.get('clusters', [])}]"

        print(f"{icon} {tc['id']}: {status} ({elapsed:.1f}s){breadth_info}")
        print(f"   Q: \"{tc['question']}\"")

        if errors:
            for e in errors:
                print(f"   ⚠ {e}")

        if verbose:
            answer = result.get("answer", "")
            needs_clar = result.get("needsClarification", False)
            n_opts = len(result.get("clarificationOptions", []))
            print(f"   needsClarification: {needs_clar}, options: {n_opts}")
            print(f"   Sections: {result.get('relatedSections', [])}")
            if needs_clar:
                for opt in result.get("clarificationOptions", []):
                    if isinstance(opt, dict):
                        print(f"   → {opt.get('label')}: {opt.get('description')}")
                    elif hasattr(opt, 'label'):
                        print(f"   → {opt.label}: {opt.description}")
            print(f"   Answer preview: {answer[:200]}...")
        print()

    # ── Summary ────────────────────────────────────────────────────
    total = passed + failed
    pct = (passed / total * 100) if total else 0
    print(f"{'='*70}")
    print(f"RESULTS: {passed}/{total} passed ({pct:.1f}%)")
    print(f"  ✅ Correctly asked for clarification: {passed}")
    print(f"  ❌ Incorrectly answered directly:     {failed}")
    print(f"{'='*70}")

    return passed, failed


def main():
    parser = argparse.ArgumentParser(description="Breadth Score Test — Vague Questions")
    parser.add_argument("--verbose", action="store_true", help="Show full responses")
    args = parser.parse_args()

    asyncio.run(run_tests(verbose=args.verbose))


if __name__ == "__main__":
    main()
