#!/usr/bin/env python3
"""
Local test harness for qa_service scoring accuracy.
Scores all 436 non-Table8 questions against recommendations.json
using the same scoring pipeline as the live service.

Usage:
    python test_qa_harness.py                    # full run
    python test_qa_harness.py --section 4.6.1    # filter by section
    python test_qa_harness.py --fails-only       # only show failures
    python test_qa_harness.py --question "QA-2005" # single question by ID
"""
import json
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations
from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    score_recommendation,
    extract_search_terms,
    extract_section_references,
    extract_topic_sections,
    get_section_discriminators,
)

TEST_SUITES = {
    "r3": (
        "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/"
        "SNIS Abstract/Questions/Claude_Code_Handoff/qa_round3_test_suite.json"
    ),
    "r5": (
        "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/"
        "SNIS Abstract/Questions/Claude_Code_Handoff/qa_round5_test_suite.json"
    ),
}
TEST_SUITE_PATH = TEST_SUITES["r3"]  # default


def load_test_suite(path=None):
    with open(path or TEST_SUITE_PATH, "r") as f:
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


def run_tests(args, suite_path=None):
    test_suite = load_test_suite(suite_path)
    recommendations = load_recommendations()

    # Filter to non-Table8 only
    questions = [q for q in test_suite if q["category"] == "qa_recommendation"]

    if args.section:
        questions = [q for q in questions if q["section"] == args.section]
    if args.question:
        questions = [q for q in questions if q["id"] == args.question]

    cor_correct = 0
    cor_total = 0
    loe_correct = 0
    loe_total = 0
    failures_by_section = {}

    for q in questions:
        qid = q["id"]
        qtext = q["question"]
        expected_cor = q["expected_cor"]
        expected_loe = q["expected_loe"]
        section = q["section"]

        scored = score_question(qtext, recommendations)
        if not scored or scored[0][0] <= 0:
            found_cor = "NONE"
            found_loe = "NONE"
            top3_fmt = []
        else:
            top_rec = scored[0][1]
            found_cor = top_rec.get("cor", "?")
            found_loe = top_rec.get("loe", "?")
            top3_fmt = [
                (s, r.get("section"), r.get("recNumber"), r.get("cor"), r.get("loe"), r.get("text", "")[:80])
                for s, r in scored[:3]
            ]

        cor_match = found_cor == expected_cor
        loe_match = found_loe == expected_loe

        cor_total += 1
        if cor_match:
            cor_correct += 1
        loe_total += 1
        if loe_match:
            loe_correct += 1

        if not cor_match or not loe_match:
            if section not in failures_by_section:
                failures_by_section[section] = []
            failures_by_section[section].append({
                "id": qid,
                "question": qtext,
                "expected_cor": expected_cor,
                "found_cor": found_cor,
                "cor_ok": cor_match,
                "expected_loe": expected_loe,
                "found_loe": found_loe,
                "loe_ok": loe_match,
                "top3": top3_fmt,
            })

        if not args.fails_only or not cor_match or not loe_match:
            if args.verbose or not cor_match or not loe_match:
                status = "✓" if cor_match and loe_match else "✗"
                cor_mark = "✓" if cor_match else "✗"
                loe_mark = "✓" if loe_match else "✗"
                print(f"{status} {qid} [{section}] COR:{cor_mark} {expected_cor}→{found_cor} LOE:{loe_mark} {expected_loe}→{found_loe}")
                if not cor_match or not loe_match:
                    print(f"  Q: {qtext[:120]}")
                    for rank, (s, rsec, rn, rcor, rloe, txt) in enumerate(top3_fmt[:3], 1):
                        print(f"  #{rank} score={s} sec={rsec} rec={rn} COR={rcor} LOE={rloe} | {txt}")
                    print()

    print("=" * 70)
    print(f"COR: {cor_correct}/{cor_total} ({100*cor_correct/cor_total:.1f}%)")
    print(f"LOE: {loe_correct}/{loe_total} ({100*loe_correct/loe_total:.1f}%)")
    print()

    if failures_by_section:
        print("Failures by section:")
        for sec in sorted(failures_by_section.keys()):
            fails = failures_by_section[sec]
            cor_fails = sum(1 for f in fails if not f["cor_ok"])
            loe_fails = sum(1 for f in fails if not f["loe_ok"])
            print(f"  {sec}: {cor_fails} COR fails, {loe_fails} LOE fails")

    return cor_correct, cor_total, loe_correct, loe_total, failures_by_section


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", help="Filter by section")
    parser.add_argument("--question", help="Filter by question ID")
    parser.add_argument("--fails-only", action="store_true", help="Only show failures")
    parser.add_argument("--verbose", action="store_true", help="Show all results")
    parser.add_argument("--suite", choices=["r3", "r5"], default="r3", help="Test suite to use")
    args = parser.parse_args()
    run_tests(args, suite_path=TEST_SUITES[args.suite])
