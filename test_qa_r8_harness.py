"""
R8 Test Harness — runs 1,000 NEW questions against the multi-agent QA orchestrator.

Uses the same validators as R7 but with the R8 test suite (different question patterns).

Usage:
    python3 test_qa_r8_harness.py                    # run all
    python3 test_qa_r8_harness.py --category qa_recommendation
    python3 test_qa_r8_harness.py --category qa_scope_gate --verbose
    python3 test_qa_r8_harness.py --fail-fast
    python3 test_qa_r8_harness.py --sample 50
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)

# ── Constants ──────────────────────────────────────────────────────

TEST_SUITE_PATH = os.path.join(
    "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff",
    "qa_round8_test_suite.json",
)


# ── Orchestrator Setup ─────────────────────────────────────────────

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


# ── Validators ─────────────────────────────────────────────────────

def validate_recommendation(tc, result):
    errors = []
    answer = result.get("answer", "")
    sections = set(result.get("relatedSections", []))
    audit = result.get("auditTrail", [])

    has_verbatim = "RECOMMENDATION [" in answer
    has_clarification = result.get("needsClarification", False)
    is_section_clarification = "could relate to multiple" in answer.lower()
    if not has_verbatim and not has_clarification and not is_section_clarification:
        errors.append("No RECOMMENDATION block and no clarification")

    expected = tc.get("expected_section", "")
    if expected and expected not in sections:
        clar_sections = set()
        for opt in result.get("clarificationOptions", []):
            clar_sections.add(opt.get("section", ""))
        all_sections = sections | clar_sections
        prefix_match = any(
            s.startswith(expected) or expected.startswith(s)
            for s in all_sections
        )
        if not prefix_match and expected not in all_sections:
            errors.append(f"Expected section {expected} not in {sorted(sections)} or clarification options")

    if not audit:
        errors.append("No audit trail")

    return errors


def validate_evidence(tc, result):
    errors = []
    answer = result.get("answer", "")
    sections = set(result.get("relatedSections", []))

    if not answer.strip():
        errors.append("Empty answer")

    expected = tc.get("expected_section", "")
    if expected and expected not in sections:
        prefix_match = any(
            s.startswith(expected) or expected.startswith(s)
            for s in sections
        )
        if not prefix_match:
            errors.append(f"Expected section {expected} not in {sorted(sections)}")

    has_evidence_content = any(marker in answer for marker in [
        "Evidence for", "Supporting Evidence", "RECOMMENDATION [",
        "Knowledge Gaps",
    ])
    has_clarification = result.get("needsClarification", False)
    has_ambiguity_response = "contains multiple recommendations" in answer
    if not has_evidence_content and not has_clarification and not has_ambiguity_response:
        if "does not specifically address" not in answer:
            errors.append("No evidence content markers in answer")

    return errors


def validate_knowledge_gap(tc, result):
    errors = []
    answer = result.get("answer", "")
    sections = set(result.get("relatedSections", []))
    expected = tc.get("expected_section", "")

    _NON_CLINICAL_SECTIONS = {
        "1", "1.1", "1.2", "1.3", "1.4", "1.5",
        "2", "3", "4", "5", "6",
        "4.6", "4.7",
    }
    if expected in _NON_CLINICAL_SECTIONS:
        return errors

    if not answer.strip():
        errors.append("Empty answer")

    if expected and expected not in sections:
        prefix_match = any(
            s.startswith(expected) or expected.startswith(s)
            for s in sections
        )
        if not prefix_match:
            errors.append(f"Expected section {expected} not in {sorted(sections)}")

    has_kg_content = "Knowledge Gaps" in answer or "knowledge gap" in answer.lower()
    has_no_gaps = any(phrase in answer.lower() for phrase in [
        "no specific knowledge gaps",
        "no knowledge gaps",
        "does not document specific knowledge gaps",
    ])
    has_recs = "RECOMMENDATION [" in answer

    if not has_kg_content and not has_no_gaps and not has_recs:
        if "does not specifically address" not in answer:
            errors.append("No KG content, no 'no gaps' response, and no recs")

    return errors


def validate_semantic(tc, result):
    errors = []
    answer = result.get("answer", "")
    sections = set(result.get("relatedSections", []))

    if not answer.strip():
        errors.append("Empty answer")

    expected = tc.get("expected_section", "")
    if expected and expected not in sections:
        prefix_match = any(
            s.startswith(expected) or expected.startswith(s)
            for s in sections
        )
        is_scope_gate = "does not specifically address" in answer
        has_clarification = result.get("needsClarification", False)

        if not prefix_match and not is_scope_gate and not has_clarification:
            errors.append(f"Expected section {expected} not in {sorted(sections)}")

    return errors


def validate_scope_gate(tc, result):
    errors = []
    answer = result.get("answer", "")

    is_oos = "does not specifically address" in answer
    expected_oos = tc.get("expected_scope_gate", True)

    if expected_oos and not is_oos:
        errors.append(f"Expected scope gate refusal, got answer: {answer[:120]}")

    if not expected_oos and is_oos:
        errors.append("Expected in-scope response, got scope gate refusal")

    return errors


def validate_clarification(tc, result):
    errors = []
    answer = result.get("answer", "")
    sections = set(result.get("relatedSections", []))
    has_clarification = result.get("needsClarification", False)
    has_verbatim = "RECOMMENDATION [" in answer

    if not has_clarification and not has_verbatim:
        if "does not specifically address" not in answer:
            errors.append("No clarification and no verbatim recs")

    expected = tc.get("expected_section", "")
    if expected and expected not in sections:
        clar_sections = set()
        for opt in result.get("clarificationOptions", []):
            clar_sections.add(opt.get("section", ""))
        all_sections = sections | clar_sections
        prefix_match = any(
            s.startswith(expected) or expected.startswith(s)
            for s in all_sections
        )
        if not prefix_match and expected not in all_sections:
            errors.append(f"Expected section {expected} not in {sorted(sections)} or clarification")

    return errors


VALIDATORS = {
    "qa_recommendation": validate_recommendation,
    "qa_evidence": validate_evidence,
    "qa_knowledge_gap": validate_knowledge_gap,
    "qa_semantic": validate_semantic,
    "qa_scope_gate": validate_scope_gate,
    "qa_clarification": validate_clarification,
}


# ── Main Test Runner ───────────────────────────────────────────────

async def run_tests(questions, orchestrator, verbose=False, fail_fast=False):
    results = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "by_category": defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "errors": 0}),
        "failures": [],
        "timing": [],
    }

    for i, tc in enumerate(questions):
        cat = tc["category"]
        qid = tc["id"]
        question = tc["question"]
        results["total"] += 1
        results["by_category"][cat]["total"] += 1

        try:
            t0 = time.time()
            result = await orchestrator.answer(question)
            elapsed = time.time() - t0
            results["timing"].append(elapsed)
        except Exception as e:
            results["errors"] += 1
            results["by_category"][cat]["errors"] += 1
            failure = {
                "id": qid,
                "category": cat,
                "question": question,
                "errors": [f"EXCEPTION: {type(e).__name__}: {e}"],
            }
            results["failures"].append(failure)
            print(f"  ERROR [{qid}] {question[:60]}  ({type(e).__name__})")
            if fail_fast:
                break
            continue

        validator = VALIDATORS.get(cat)
        if not validator:
            print(f"  SKIP [{qid}] No validator for category {cat}")
            continue

        errors = validator(tc, result)

        if errors:
            results["failed"] += 1
            results["by_category"][cat]["failed"] += 1
            failure = {
                "id": qid,
                "category": cat,
                "question": question,
                "errors": errors,
                "sections_returned": sorted(result.get("relatedSections", [])),
                "answer_preview": result.get("answer", "")[:200],
            }
            results["failures"].append(failure)
            if verbose:
                print(f"  FAIL [{qid}] {question[:60]}")
                for err in errors:
                    print(f"         {err}")
                print(f"         sections={sorted(result.get('relatedSections', []))}")
            else:
                print(f"  FAIL [{qid}] {question[:60]}  ({'; '.join(errors[:2])})")
            if fail_fast:
                break
        else:
            results["passed"] += 1
            results["by_category"][cat]["passed"] += 1
            if verbose:
                sections = sorted(result.get("relatedSections", []))
                print(f"  PASS [{qid}] {question[:60]}  sections={sections}  {elapsed:.2f}s")

        if (i + 1) % 50 == 0 and not verbose:
            pct = 100 * results["passed"] / results["total"]
            print(f"  ... {i+1}/{len(questions)} done ({pct:.0f}% passing)")

    return results


def print_report(results):
    print(f"\n{'='*70}")
    print(f"R8 TEST SUITE RESULTS")
    print(f"{'='*70}")

    total = results["total"]
    passed = results["passed"]
    failed = results["failed"]
    errors = results["errors"]
    pct = 100 * passed / total if total else 0

    print(f"\n  TOTAL:   {total}")
    print(f"  PASSED:  {passed} ({pct:.1f}%)")
    print(f"  FAILED:  {failed}")
    print(f"  ERRORS:  {errors}")

    if results["timing"]:
        avg_time = sum(results["timing"]) / len(results["timing"])
        max_time = max(results["timing"])
        total_time = sum(results["timing"])
        print(f"\n  Avg time/question: {avg_time:.2f}s")
        print(f"  Max time/question: {max_time:.2f}s")
        print(f"  Total runtime:     {total_time:.1f}s")

    print(f"\n  {'Category':<25} {'Total':>6} {'Pass':>6} {'Fail':>6} {'Err':>5} {'Rate':>7}")
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*6} {'-'*5} {'-'*7}")
    for cat in sorted(results["by_category"].keys()):
        stats = results["by_category"][cat]
        cat_pct = 100 * stats["passed"] / stats["total"] if stats["total"] else 0
        print(
            f"  {cat:<25} {stats['total']:>6} {stats['passed']:>6} "
            f"{stats['failed']:>6} {stats['errors']:>5} {cat_pct:>6.1f}%"
        )

    if results["failures"]:
        print(f"\n  {'='*70}")
        print(f"  FAILURE DETAILS (first 20)")
        print(f"  {'='*70}")
        for f in results["failures"][:20]:
            print(f"\n  [{f['id']}] {f['category']}")
            print(f"  Q: {f['question'][:80]}")
            for err in f["errors"]:
                print(f"    ✗ {err}")
            if f.get("sections_returned"):
                print(f"    sections: {f['sections_returned']}")

    print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="R8 Test Suite Harness")
    parser.add_argument("--category", "-c", help="Run only this category")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all results")
    parser.add_argument("--fail-fast", "-f", action="store_true", help="Stop on first failure")
    parser.add_argument("--sample", "-s", type=int, help="Random sample of N questions")
    parser.add_argument("--id", help="Run a single question by ID")
    args = parser.parse_args()

    with open(TEST_SUITE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data["questions"]
    print(f"Loaded {len(questions)} questions from R8 test suite")

    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
        print(f"Filtered to {len(questions)} questions in category '{args.category}'")

    if args.id:
        questions = [q for q in questions if q["id"] == args.id]
        print(f"Running single question: {args.id}")
        args.verbose = True

    if args.sample and args.sample < len(questions):
        questions = random.sample(questions, args.sample)
        print(f"Sampled {len(questions)} questions")

    if not questions:
        print("No questions to run!")
        return

    print("\nBuilding orchestrator...")
    orchestrator = build_orchestrator()
    print("Ready.\n")

    results = asyncio.run(run_tests(
        questions, orchestrator,
        verbose=args.verbose,
        fail_fast=args.fail_fast,
    ))

    print_report(results)

    if results["failures"]:
        failures_path = os.path.join(
            os.path.dirname(__file__),
            "r8_failures.json",
        )
        with open(failures_path, "w", encoding="utf-8") as f:
            json.dump(results["failures"], f, indent=2)
        print(f"\nFailure details saved to {failures_path}")

    sys.exit(0 if results["failed"] == 0 and results["errors"] == 0 else 1)


if __name__ == "__main__":
    main()
