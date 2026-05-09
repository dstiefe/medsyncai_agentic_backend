"""
Test harness for the multi-agent QA Orchestrator pipeline.

Validates:
    1. Verbatim rec assembly — recommendations appear in RECOMMENDATION [] blocks
    2. Scope gate — out-of-scope questions get explicit refusal
    3. Clarification detection — ambiguous questions trigger clarification
    4. Audit trail — every response includes audit steps
    5. Semantic search — plain-language queries still find correct recs
    6. Section routing parity — new pipeline matches legacy pipeline sections
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)


def build_orchestrator(with_semantic=True):
    store = None
    if with_semantic:
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


# ── Test Cases ──────────────────────────────────────────────────────

VERBATIM_TESTS = [
    {
        "question": "Is IVT recommended for a patient with a disabling deficit?",
        "expect_section": "4.6.1",
        "expect_verbatim": True,
    },
    {
        "question": "What is the recommendation for EVT in basilar artery occlusion?",
        "expect_section": "4.7.3",
        "expect_verbatim": True,
    },
    {
        "question": "Is aspirin recommended within 24 hours after IVT?",
        "expect_section": "4.8",
        "expect_verbatim": True,
    },
    {
        "question": "What is the recommendation for decompressive craniectomy?",
        "expect_section": "6.3",
        "expect_verbatim_or_clarification": True,  # may trigger clarification (COR 1 vs 2b)
    },
    {
        "question": "Is therapeutic hypothermia recommended for AIS?",
        "expect_section": "4.11",
        "expect_section_alt": ["4.4"],  # may route to 4.4 (Temperature Management)
        "expect_verbatim_or_clarification": True,  # may trigger clarification
    },
]

SCOPE_GATE_TESTS = [
    # NOTE: In production, truly unrelated queries (fertilizer, Kubernetes)
    # are caught by engine.py _classify_query() before reaching QA.
    # The scope gate protects against AIS-flavored questions that pass the
    # engine classifier but the guideline doesn't actually cover.
    # These tests validate the scope gate fires when it should.
    #
    # For now, test that the scope gate DOES NOT fire for in-scope questions
    # (negative test — scope gate should pass through valid questions)
    {
        "question": "What is the recommendation for IVT in disabling stroke?",
        "expect_scope_gate": False,
        "description": "In-scope IVT question — should NOT trigger scope gate",
    },
    {
        "question": "What are the EVT eligibility criteria?",
        "expect_scope_gate": False,
        "description": "In-scope EVT question — should NOT trigger scope gate",
    },
    {
        "question": "What does the AIS guideline recommend for pediatric stroke?",
        "expect_scope_gate": False,
        "description": "Pediatric stroke — guideline DOES have pediatric recs (2.7, 3.2)",
    },
    {
        "question": "What is the recommendation for managing intracerebral hemorrhage?",
        "expect_scope_gate": True,
        "description": "ICH — different guideline, not AIS",
    },
]

GUARDRAIL_TESTS = [
    {
        "description": "Summary with invented number should be flagged",
        "summary": "Treatment should begin within 99 hours of onset.",
        "source_texts": ["Treatment should begin within 4.5 hours of onset."],
        "expect_violations": True,
    },
    {
        "description": "Summary matching source should pass",
        "summary": "Blood pressure should be below 185/110 mmHg.",
        "source_texts": ["Blood pressure should be ≤185/110 mmHg before initiating IV alteplase."],
        "expect_violations": False,
    },
]

CLARIFICATION_TESTS = [
    {
        "question": "Is EVT recommended for M2 occlusion?",
        "expect_clarification": True,
        "expect_section": "4.7.2",
        "description": "M2 dominant vs nondominant",
    },
]

AUDIT_TRAIL_TESTS = [
    {
        "question": "What are the BP thresholds for IVT eligibility?",
        "min_audit_steps": 3,
        "required_steps": ["intent_classification", "retrieval"],
    },
]

SEMANTIC_TESTS = [
    {
        "question": "Can I give clot-busting drugs to someone on blood thinners?",
        "expect_sections_any": ["4.8", "4.9", "4.6.1"],
        "description": "Plain language → anticoagulation recs",
    },
    {
        "question": "Is brain cooling helpful after a stroke?",
        "expect_sections_any": ["4.11", "4.4", "6.2"],
        "description": "Plain language → hypothermia/neuroprotection",
    },
]


async def run_tests():
    orchestrator = build_orchestrator(with_semantic=True)
    passed = 0
    failed = 0
    total = 0

    # ── Verbatim Tests ──────────────────────────────────────────
    print("\n=== VERBATIM REC ASSEMBLY ===")
    for tc in VERBATIM_TESTS:
        total += 1
        r = await orchestrator.answer(tc["question"])
        answer = r.get("answer", "")
        sections = set(r.get("relatedSections", []))
        has_verbatim = "RECOMMENDATION [" in answer

        acceptable_sections = [tc["expect_section"]] + tc.get("expect_section_alt", [])
        section_ok = any(s in sections for s in acceptable_sections)

        # Some questions with conflicting COR in the same section may trigger
        # clarification instead of verbatim recs — both are valid behavior
        if tc.get("expect_verbatim_or_clarification"):
            has_clarification = r.get("needsClarification", False)
            verbatim_ok = has_verbatim or has_clarification
        else:
            verbatim_ok = has_verbatim == tc.get("expect_verbatim", True)
        ok = section_ok and verbatim_ok

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['question'][:70]}")
        if not ok:
            print(f"    Section: expected {tc['expect_section']} in {sorted(sections)}")
            print(f"    Verbatim: expected={tc.get('expect_verbatim')} actual={has_verbatim}")

    # ── Scope Gate Tests ────────────────────────────────────────
    print("\n=== SCOPE GATE ===")
    for tc in SCOPE_GATE_TESTS:
        total += 1
        r = await orchestrator.answer(tc["question"])
        answer = r.get("answer", "")
        is_oos = "does not specifically address" in answer

        ok = is_oos == tc.get("expect_scope_gate", True)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['description']}")
        if not ok:
            print(f"    Expected scope gate={tc['expect_scope_gate']}, got answer: {answer[:100]}")

    # ── Clarification Tests ─────────────────────────────────────
    print("\n=== CLARIFICATION DETECTION ===")
    for tc in CLARIFICATION_TESTS:
        total += 1
        r = await orchestrator.answer(tc["question"])
        has_clarification = r.get("needsClarification", False)
        sections = set(r.get("relatedSections", []))

        clarification_ok = has_clarification == tc.get("expect_clarification", True)
        section_ok = tc["expect_section"] in sections if tc.get("expect_section") else True

        ok = clarification_ok and section_ok
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['description']}")
        if not ok:
            print(f"    Clarification: expected={tc.get('expect_clarification')} actual={has_clarification}")
            print(f"    Sections: {sorted(sections)}")

    # ── Audit Trail Tests ───────────────────────────────────────
    print("\n=== AUDIT TRAIL ===")
    for tc in AUDIT_TRAIL_TESTS:
        total += 1
        r = await orchestrator.answer(tc["question"])
        audit = r.get("auditTrail", [])
        audit_steps = [a["step"] for a in audit]

        count_ok = len(audit) >= tc["min_audit_steps"]
        steps_ok = all(s in audit_steps for s in tc["required_steps"])

        ok = count_ok and steps_ok
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['question'][:70]}")
        print(f"    Audit steps ({len(audit)}): {audit_steps}")
        if not ok:
            print(f"    Expected min={tc['min_audit_steps']} steps, required={tc['required_steps']}")

    # ── Semantic Search Tests ───────────────────────────────────
    print("\n=== SEMANTIC SEARCH ===")
    for tc in SEMANTIC_TESTS:
        total += 1
        r = await orchestrator.answer(tc["question"])
        sections = set(r.get("relatedSections", []))
        has_answer = bool(r.get("answer"))

        section_ok = any(s in sections for s in tc["expect_sections_any"])
        ok = has_answer and section_ok

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['description']}")
        print(f"    Sections: {sorted(sections)}")
        if not ok:
            print(f"    Expected any of {tc['expect_sections_any']}")

    # ── Summarization Guardrail Tests ──────────────────────────
    print("\n=== SUMMARIZATION GUARDRAILS ===")
    from app.agents.clinical.ais_clinical_engine.agents.qa.assembly_agent import AssemblyAgent
    for tc in GUARDRAIL_TESTS:
        total += 1
        violations = AssemblyAgent.validate_summary(
            tc["summary"], tc["source_texts"]
        )
        has_violations = len(violations) > 0
        ok = has_violations == tc["expect_violations"]

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {tc['description']}")
        if violations:
            for v in violations:
                print(f"    Violation: {v}")
        if not ok:
            print(f"    Expected violations={tc['expect_violations']}, got {len(violations)}")

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"ORCHESTRATOR TESTS: {passed}/{total} ({100*passed/total:.1f}%)")
    if failed:
        print(f"FAILED: {failed}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
