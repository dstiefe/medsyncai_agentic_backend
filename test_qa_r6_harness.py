#!/usr/bin/env python3
"""
R6 test harness for Ask MedSync — covers all 3 question types:
  - qa_recommendation: COR/LOE matching (same as R3/R5 harness)
  - qa_evidence: section routing + question type classification
  - qa_knowledge_gap: section routing + deterministic/LLM response

Usage:
    python test_qa_r6_harness.py                        # full run
    python test_qa_r6_harness.py --category qa_evidence  # one category
    python test_qa_r6_harness.py --section 4.6.1         # filter by section
    python test_qa_r6_harness.py --fails-only            # only show failures
    python test_qa_r6_harness.py --question QA-5301      # single question
    python test_qa_r6_harness.py --verbose               # show all results
"""
import json
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations
from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    score_recommendation,
    extract_search_terms,
    extract_section_references,
    extract_topic_sections,
    get_section_discriminators,
    classify_question_type,
    gather_section_content,
)

TEST_SUITE_PATH = (
    "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/"
    "SNIS Abstract/Questions/Claude_Code_Handoff/qa_round6_test_suite.json"
)

# Load guideline knowledge for evidence/KG tests
GK_PATH = os.path.join(
    os.path.dirname(__file__),
    "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json",
)


def load_test_suite():
    with open(TEST_SUITE_PATH, "r") as f:
        data = json.load(f)
    return data.get("questions", data)


def load_guideline_knowledge():
    with open(GK_PATH, "r") as f:
        return json.load(f)


def score_question(question_text: str, recommendations: list) -> list:
    """Score all recommendations for a question, return sorted (score, rec) list."""
    search_terms = extract_search_terms(question_text)
    section_refs = extract_section_references(question_text)
    topic_sections, suppressed = extract_topic_sections(question_text)
    sec_discs = get_section_discriminators(recommendations)

    scored = []
    for rec in recommendations:
        s = score_recommendation(
            rec,
            search_terms,
            question=question_text,
            section_refs=section_refs,
            topic_sections=topic_sections,
            suppressed_sections=suppressed,
            section_discriminators=sec_discs,
        )
        scored.append((s, rec))

    scored.sort(key=lambda x: -x[0])
    return scored


# ═══════════════════════════════════════════════════════════════════════
# TEST RUNNERS FOR EACH CATEGORY
# ═══════════════════════════════════════════════════════════════════════

def test_recommendation(q, recommendations, args):
    """Test a qa_recommendation question. Returns (pass, details)."""
    qid = q["id"]
    qtext = q["question"]
    expected_cor = q["expected_cor"]
    expected_loe = q["expected_loe"]
    section = q["section"]
    expects_clarification = q.get("expected_clarification", False)
    allows_cor_match = q.get("allow_cor_match", False)

    scored = score_question(qtext, recommendations)
    if not scored or scored[0][0] <= 0:
        found_cor = "NONE"
        found_loe = "NONE"
        found_section = "NONE"
        top3_fmt = []
    else:
        top_rec = scored[0][1]
        found_cor = top_rec.get("cor", "?")
        found_loe = top_rec.get("loe", "?")
        found_section = top_rec.get("section", "?")
        top3_fmt = [
            (s, r.get("section"), r.get("recNumber"), r.get("cor"), r.get("loe"), r.get("text", "")[:80])
            for s, r in scored[:3]
        ]

    cor_match = found_cor == expected_cor
    loe_match = found_loe == expected_loe
    section_match = found_section == section

    # Standard pass: exact COR + LOE match
    passed = cor_match and loe_match

    # Clarification pass: correct section but COR conflict → system would
    # present clarification options (CMI pattern). Counts as pass because
    # the user would receive a targeted clarification within the right section.
    if not passed and expects_clarification and section_match:
        passed = True

    # LOE-flexible pass: correct section AND COR, only LOE differs.
    # This happens when the section has multiple recs with the same COR
    # but different LOE. The clinical guidance (COR) is correct.
    if not passed and allows_cor_match and section_match and cor_match:
        passed = True

    details = {
        "cor_match": cor_match,
        "loe_match": loe_match,
        "section_match": section_match,
        "expected_cor": expected_cor,
        "found_cor": found_cor,
        "expected_loe": expected_loe,
        "found_loe": found_loe,
        "found_section": found_section,
        "expects_clarification": expects_clarification,
        "allows_cor_match": allows_cor_match,
        "top3": top3_fmt,
    }

    if not args.fails_only or not passed:
        if args.verbose or not passed:
            status = "\u2713" if passed else "\u2717"
            cor_mark = "\u2713" if cor_match else "\u2717"
            loe_mark = "\u2713" if loe_match else "\u2717"
            extra = ""
            if passed and expects_clarification and not (cor_match and loe_match):
                extra = " [CLARIFY]"
            elif passed and allows_cor_match and not loe_match:
                extra = " [COR-OK]"
            print(f"{status} {qid} [{section}] COR:{cor_mark} {expected_cor}\u2192{found_cor} LOE:{loe_mark} {expected_loe}\u2192{found_loe}{extra}")
            if not passed:
                print(f"  Q: {qtext[:120]}")
                for rank, (s, rsec, rn, rcor, rloe, txt) in enumerate(top3_fmt[:3], 1):
                    print(f"  #{rank} score={s} sec={rsec} rec={rn} COR={rcor} LOE={rloe} | {txt}")
                print()

    return passed, details


def test_evidence(q, guideline_knowledge, args):
    """
    Test a qa_evidence question.

    Checks:
    1. classify_question_type() returns "evidence"
    2. Section routing resolves to expected section
    3. gather_section_content() returns non-empty RSS for that section
    """
    qid = q["id"]
    qtext = q["question"]
    expected_section = q["expected_section"]
    section = q["section"]

    # 1. Question type classification
    q_type = classify_question_type(qtext)
    type_match = q_type == "evidence"

    # 2. Section routing
    section_refs = extract_section_references(qtext)
    topic_sections, _ = extract_topic_sections(qtext)
    resolved_sections = section_refs or topic_sections

    section_match = expected_section in resolved_sections if resolved_sections else False

    # 3. Content availability
    target = [expected_section] if not resolved_sections else resolved_sections
    search_terms = extract_search_terms(qtext)
    content = gather_section_content(guideline_knowledge, target, search_terms)
    has_content = content["total_chars"] > 0

    passed = type_match and section_match and has_content

    details = {
        "type_match": type_match,
        "found_type": q_type,
        "section_match": section_match,
        "resolved_sections": resolved_sections,
        "has_content": has_content,
        "total_chars": content["total_chars"],
        "rss_count": len(content["rss"]),
    }

    if not args.fails_only or not passed:
        if args.verbose or not passed:
            status = "\u2713" if passed else "\u2717"
            type_mark = "\u2713" if type_match else "\u2717"
            sec_mark = "\u2713" if section_match else "\u2717"
            content_mark = "\u2713" if has_content else "\u2717"
            print(
                f"{status} {qid} [{section}] "
                f"Type:{type_mark} {q_type} "
                f"Sec:{sec_mark} {resolved_sections}\u2192{expected_section} "
                f"Content:{content_mark} {content['total_chars']}ch/{len(content['rss'])}rss"
            )
            if not passed:
                print(f"  Q: {qtext[:120]}")
                print()

    return passed, details


def test_knowledge_gap(q, guideline_knowledge, args):
    """
    Test a qa_knowledge_gap question.

    Checks:
    1. classify_question_type() returns "knowledge_gap"
    2. Section routing resolves to expected section
    3. If has_content=True: section has non-empty knowledgeGaps
       If has_content=False: section has empty knowledgeGaps (deterministic response)
    """
    qid = q["id"]
    qtext = q["question"]
    expected_section = q["expected_section"]
    has_expected_content = q["has_content"]
    section = q["section"]

    # 1. Question type classification
    q_type = classify_question_type(qtext)
    type_match = q_type == "knowledge_gap"

    # 2. Section routing
    section_refs = extract_section_references(qtext)
    topic_sections, _ = extract_topic_sections(qtext)
    resolved_sections = section_refs or topic_sections

    section_match = expected_section in resolved_sections if resolved_sections else False

    # 3. Content check
    sections_data = guideline_knowledge.get("sections", {})
    sec_data = sections_data.get(expected_section, {})
    actual_has_content = bool(sec_data.get("knowledgeGaps", "").strip())
    content_match = actual_has_content == has_expected_content

    passed = type_match and section_match and content_match

    details = {
        "type_match": type_match,
        "found_type": q_type,
        "section_match": section_match,
        "resolved_sections": resolved_sections,
        "content_match": content_match,
        "actual_has_content": actual_has_content,
        "expected_has_content": has_expected_content,
    }

    if not args.fails_only or not passed:
        if args.verbose or not passed:
            status = "\u2713" if passed else "\u2717"
            type_mark = "\u2713" if type_match else "\u2717"
            sec_mark = "\u2713" if section_match else "\u2717"
            content_mark = "\u2713" if content_match else "\u2717"
            kg_label = "has_kg" if actual_has_content else "no_kg"
            print(
                f"{status} {qid} [{section}] "
                f"Type:{type_mark} {q_type} "
                f"Sec:{sec_mark} {resolved_sections}\u2192{expected_section} "
                f"KG:{content_mark} {kg_label}"
            )
            if not passed:
                print(f"  Q: {qtext[:120]}")
                print()

    return passed, details


# ═══════════════════════════════════════════════════════════════════════
# MAIN TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════

def run_tests(args):
    questions = load_test_suite()
    recommendations = load_recommendations()
    guideline_knowledge = load_guideline_knowledge()

    # Apply filters
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.section:
        questions = [q for q in questions if q["section"] == args.section]
    if args.question:
        questions = [q for q in questions if q["id"] == args.question]

    # Counters per category
    results = {
        "qa_recommendation": {"pass": 0, "fail": 0, "failures": {}},
        "qa_evidence": {"pass": 0, "fail": 0, "failures": {}},
        "qa_knowledge_gap": {"pass": 0, "fail": 0, "failures": {}},
    }

    # Sub-counters for recommendation COR/LOE
    rec_cor_correct = 0
    rec_cor_total = 0
    rec_loe_correct = 0
    rec_loe_total = 0

    for q in questions:
        cat = q["category"]
        section = q["section"]

        if cat == "qa_recommendation":
            passed, details = test_recommendation(q, recommendations, args)
            rec_cor_total += 1
            rec_loe_total += 1
            if details["cor_match"]:
                rec_cor_correct += 1
            if details["loe_match"]:
                rec_loe_correct += 1
        elif cat == "qa_evidence":
            passed, details = test_evidence(q, guideline_knowledge, args)
        elif cat == "qa_knowledge_gap":
            passed, details = test_knowledge_gap(q, guideline_knowledge, args)
        else:
            continue

        if passed:
            results[cat]["pass"] += 1
        else:
            results[cat]["fail"] += 1
            results[cat]["failures"].setdefault(section, []).append({
                "id": q["id"],
                "question": q["question"],
                **details,
            })

    # ── Report ──
    print("=" * 70)

    total_pass = 0
    total_fail = 0

    for cat in ["qa_recommendation", "qa_evidence", "qa_knowledge_gap"]:
        p = results[cat]["pass"]
        f = results[cat]["fail"]
        t = p + f
        if t == 0:
            continue
        total_pass += p
        total_fail += f
        pct = 100 * p / t if t else 0
        label = cat.replace("qa_", "").upper()
        print(f"{label}: {p}/{t} ({pct:.1f}%)")

    # Recommendation sub-metrics
    if rec_cor_total > 0:
        print(f"  COR: {rec_cor_correct}/{rec_cor_total} ({100*rec_cor_correct/rec_cor_total:.1f}%)")
        print(f"  LOE: {rec_loe_correct}/{rec_loe_total} ({100*rec_loe_correct/rec_loe_total:.1f}%)")

    grand_total = total_pass + total_fail
    if grand_total:
        print(f"\nOVERALL: {total_pass}/{grand_total} ({100*total_pass/grand_total:.1f}%)")

    # Failure summary
    any_failures = False
    for cat in ["qa_recommendation", "qa_evidence", "qa_knowledge_gap"]:
        if results[cat]["failures"]:
            if not any_failures:
                print("\nFailures by section:")
                any_failures = True
            label = cat.replace("qa_", "")
            for sec in sorted(results[cat]["failures"].keys()):
                count = len(results[cat]["failures"][sec])
                print(f"  [{label}] {sec}: {count} failures")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R6 Ask MedSync test harness")
    parser.add_argument("--category", choices=["qa_recommendation", "qa_evidence", "qa_knowledge_gap"],
                        help="Filter by question category")
    parser.add_argument("--section", help="Filter by section")
    parser.add_argument("--question", help="Filter by question ID")
    parser.add_argument("--fails-only", action="store_true", help="Only show failures")
    parser.add_argument("--verbose", action="store_true", help="Show all results")
    args = parser.parse_args()
    run_tests(args)
