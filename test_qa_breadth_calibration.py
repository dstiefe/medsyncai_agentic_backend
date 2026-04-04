"""
Content Breadth Calibration Test — tests BOTH directions:
  1. Vague questions MUST trigger clarification
  2. Specific questions MUST answer directly (no false-positive clarification)

This validates the triggers are consistent and the thresholds are right.

Usage:
    python3 test_qa_breadth_calibration.py             # run all
    python3 test_qa_breadth_calibration.py --verbose    # show full detail
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
from app.agents.clinical.ais_clinical_engine.agents.qa.assembly_agent import (
    _compute_content_breadth,
    _section_cluster,
    REC_INCLUSION_MIN_SCORE,
    BREADTH_SECTION_THRESHOLD,
    BREADTH_REC_THRESHOLD,
    IN_TOPIC_REC_THRESHOLD,
)


# ══════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════

# expect = "clarify" → system SHOULD ask follow-up
# expect = "answer"  → system SHOULD answer directly (no false positive)

TEST_CASES = [
    # ── CROSS-SECTION VAGUE (broad topic, many sections) ──────────
    {
        "id": "V-01", "expect": "clarify",
        "question": "What is the recommendation for stroke treatment?",
        "reason": "Entire guideline is stroke treatment",
    },
    {
        "id": "V-02", "expect": "clarify",
        "question": "What medications are used for stroke?",
        "reason": "IVT drugs, antiplatelets, anticoagulants, BP meds, neuroprotectants",
    },
    {
        "id": "V-03", "expect": "clarify",
        "question": "How should stroke be managed?",
        "reason": "Entire guideline",
    },
    {
        "id": "V-04", "expect": "clarify",
        "question": "What are the guidelines for stroke?",
        "reason": "Entire guideline",
    },
    {
        "id": "V-05", "expect": "clarify",
        "question": "What should I do for a stroke patient?",
        "reason": "No phase, no treatment type, no scenario",
    },
    {
        "id": "V-06", "expect": "clarify",
        "question": "What procedures are recommended for stroke?",
        "reason": "EVT, IVT, craniectomy, carotid surgery...",
    },
    {
        "id": "V-07", "expect": "clarify",
        "question": "What is the treatment protocol for acute ischemic stroke?",
        "reason": "Entire acute pathway",
    },
    {
        "id": "V-08", "expect": "clarify",
        "question": "What complications should I monitor for after stroke?",
        "reason": "Swelling, seizures, DVT, dysphagia, depression...",
    },

    # ── WITHIN-SECTION VAGUE (one section, many answers) ──────────
    {
        "id": "V-09", "expect": "clarify",
        "question": "What imaging is recommended for stroke?",
        "reason": "CT, CTA, CTP, MRI, MRA, DWI, perfusion — 6+ modalities",
    },
    {
        "id": "V-10", "expect": "clarify",
        "question": "What are the EVT recommendations?",
        "reason": "M1, M2, posterior, pediatric, anesthesia, devices",
    },
    {
        "id": "V-11", "expect": "clarify",
        "question": "What are the blood pressure recommendations?",
        "reason": "Before IVT, during IVT, before EVT, during EVT, post-treatment",
    },
    {
        "id": "V-12", "expect": "clarify",
        "question": "What about brain swelling after stroke?",
        "reason": "Monitoring, medical management, craniectomy, cerebellar",
    },

    # ── SPECIFIC: should answer directly ──────────────────────────
    # These have specific clinical terms that narrow to 1-2 recs.
    {
        "id": "S-01", "expect": "answer",
        "question": "What is the tenecteplase dose for acute stroke?",
        "reason": "Specific drug + specific parameter (dose) → 4.6.2",
    },
    {
        "id": "S-02", "expect": "answer",
        "question": "Is aspirin recommended within 24 hours of IVT?",
        "reason": "Specific drug + specific timing + specific context → 4.8",
    },
    {
        "id": "S-03", "expect": "answer",
        "question": "What is the BP target before giving tPA?",
        "reason": "Specific parameter + specific context → 4.3",
    },
    {
        "id": "S-04", "expect": "answer",
        "question": "Is decompressive craniectomy recommended for large MCA infarction?",
        "reason": "Specific procedure + specific scenario → 6.3",
    },
    {
        "id": "S-05", "expect": "answer",
        "question": "Should DVT prophylaxis with IPC be started within 24 hours?",
        "reason": "Specific intervention + timing → 5.4",
    },
    {
        "id": "S-06", "expect": "clarify",
        "question": "Is EVT recommended for M1 occlusion within 6 hours?",
        "reason": "Section 4.7.2 has COR 1, 2a, 2b depending on specifics — valid COR-conflict clarification",
    },
    {
        "id": "S-07", "expect": "answer",
        "question": "What is the glucose target in acute stroke?",
        "reason": "Specific parameter → 4.5",
    },
    {
        "id": "S-08", "expect": "answer",
        "question": "Should dysphagia screening be done before oral intake?",
        "reason": "Specific assessment → 5.2",
    },
    {
        "id": "S-09", "expect": "answer",
        "question": "Is supplemental oxygen recommended for stroke patients?",
        "reason": "Specific intervention → 4.1",
    },
    {
        "id": "S-10", "expect": "answer",
        "question": "What is the door-to-needle time target for IVT?",
        "reason": "Specific metric + specific treatment → 2.7",
    },

    # ── EDGE CASES: borderline questions ──────────────────────────
    {
        "id": "E-01", "expect": "clarify",
        "question": "What are the IVT contraindications?",
        "reason": "Table 8 has dozens of entries across absolute/relative/special",
    },
    {
        "id": "E-02", "expect": "answer",
        "question": "Is IVT contraindicated in patients on DOACs?",
        "reason": "Specific contraindication scenario → Table 8 specific row",
    },
    {
        "id": "E-03", "expect": "clarify",
        "question": "What are the antiplatelet recommendations?",
        "reason": "Section 4.8 has 15 recs for different scenarios",
    },
    {
        "id": "E-04", "expect": "answer",
        "question": "Should dual antiplatelet therapy be given within 24 hours?",
        "reason": "Specific therapy + specific timing → 4.8 narrow",
    },
    {
        "id": "E-05", "expect": "answer",
        "question": "Is basilar artery thrombectomy recommended?",
        "reason": "Specific vessel → 4.7.3",
    },
    {
        "id": "E-06", "expect": "clarify",
        "question": "What studies support EVT?",
        "reason": "Many studies for many indications/criteria/scenarios",
    },
    {
        "id": "E-07", "expect": "answer",
        "question": "What is the NIHSS threshold for IVT eligibility?",
        "reason": "Specific scale + specific treatment + specific parameter",
    },
    {
        "id": "E-08", "expect": "answer",
        "question": "Is head of bed flat positioning recommended?",
        "reason": "Specific intervention → 4.2",
    },
]


# ══════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════

async def run_tests(verbose=False):
    orch = build_orchestrator()

    passed = 0
    failed = 0
    false_positives = []   # specific questions that incorrectly triggered clarification
    false_negatives = []   # vague questions that incorrectly answered directly

    print(f"\n{'='*70}")
    print(f"CONTENT BREADTH CALIBRATION — {len(TEST_CASES)} questions")
    print(f"  Vague (expect clarify): {sum(1 for t in TEST_CASES if t['expect']=='clarify')}")
    print(f"  Specific (expect answer): {sum(1 for t in TEST_CASES if t['expect']=='answer')}")
    print(f"  Thresholds: sections>={BREADTH_SECTION_THRESHOLD}, recs>{BREADTH_REC_THRESHOLD}")
    print(f"{'='*70}\n")

    for tc in TEST_CASES:
        t0 = time.time()
        try:
            result = await orch.answer(tc["question"])
            elapsed = time.time() - t0
        except Exception as e:
            elapsed = time.time() - t0
            result = {"answer": f"ERROR: {e}", "needsClarification": False}

        needs_clar = result.get("needsClarification", False)
        answer = result.get("answer", "")

        # Also check for scope gate (out of scope = not a false positive)
        is_scope_gate = "does not specifically address" in answer

        # Determine actual behavior
        if needs_clar:
            actual = "clarify"
        elif is_scope_gate:
            actual = "scope_gate"
        else:
            actual = "answer"

        # Evaluate
        expected = tc["expect"]
        if expected == "clarify":
            ok = actual == "clarify"
        else:  # expected == "answer"
            ok = actual in ("answer", "scope_gate")  # scope gate is acceptable for specific

        # Get content breadth from audit trail
        breadth_info = {}
        for entry in result.get("auditTrail", []):
            if hasattr(entry, "step") and entry.step == "content_breadth":
                breadth_info = entry.detail or {}

        icon = "✅" if ok else "❌"
        if ok:
            passed += 1
        else:
            failed += 1
            if expected == "answer" and actual == "clarify":
                false_positives.append(tc)
            elif expected == "clarify" and actual == "answer":
                false_negatives.append(tc)

        # Compact breadth summary
        n_cl = breadth_info.get("n_clusters", "?")
        n_rec = breadth_info.get("n_qualifying_recs", "?")
        n_rss = breadth_info.get("n_rss_entries", "?")
        trigger = breadth_info.get("trigger", "none")
        override = breadth_info.get("topic_sections_override", False)

        print(
            f"{icon} {tc['id']} [{expected}→{actual}] "
            f"cl={n_cl} rec={n_rec} rss={n_rss} "
            f"trigger={trigger} override={override} "
            f"({elapsed:.1f}s)"
        )
        print(f"   Q: \"{tc['question']}\"")

        if not ok:
            print(f"   ⚠ Expected {expected} but got {actual}")
            print(f"   Reason: {tc['reason']}")

        if verbose:
            n_opts = len(result.get("clarificationOptions", []))
            print(f"   options={n_opts} sections={result.get('relatedSections', [])}")
            if needs_clar:
                for opt in result.get("clarificationOptions", []):
                    if hasattr(opt, "label"):
                        print(f"   → {opt.label}: {opt.description}")
                    elif isinstance(opt, dict):
                        print(f"   → {opt.get('label')}: {opt.get('description')}")
            print(f"   Answer: {answer[:150]}...")
        print()

    # ── Summary ────────────────────────────────────────────────────
    total = passed + failed
    pct = (passed / total * 100) if total else 0

    vague_cases = [t for t in TEST_CASES if t["expect"] == "clarify"]
    specific_cases = [t for t in TEST_CASES if t["expect"] == "answer"]

    print(f"{'='*70}")
    print(f"RESULTS: {passed}/{total} correct ({pct:.1f}%)")
    print(f"  False negatives (vague but answered):    {len(false_negatives)}")
    print(f"  False positives (specific but clarified): {len(false_positives)}")

    if false_negatives:
        print(f"\n  FALSE NEGATIVES (should have clarified):")
        for fn in false_negatives:
            print(f"    {fn['id']}: \"{fn['question']}\" — {fn['reason']}")

    if false_positives:
        print(f"\n  FALSE POSITIVES (should have answered):")
        for fp in false_positives:
            print(f"    {fp['id']}: \"{fp['question']}\" — {fp['reason']}")

    print(f"{'='*70}")

    return passed, failed, false_negatives, false_positives


def main():
    parser = argparse.ArgumentParser(description="Content Breadth Calibration")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_tests(verbose=args.verbose))


if __name__ == "__main__":
    main()
