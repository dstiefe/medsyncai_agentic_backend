#!/usr/bin/env python3
"""
Round 10 comprehensive harness — tests recommendations, Table 8, evidence, and KG
against the local scoring pipeline (no server needed).

Usage:
    python test_r10_harness.py                # full run
    python test_r10_harness.py --fails-only   # only show failures
    python test_r10_harness.py --section 4.3  # filter by section
    python test_r10_harness.py --category qa_table8  # filter by category
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
    classify_table8_tier,
    classify_question_type,
)

TEST_SUITE_PATH = (
    "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/"
    "SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"
)


def load_test_suite(path=None):
    with open(path or TEST_SUITE_PATH, "r") as f:
        return json.load(f)


def score_question(question_text, recommendations):
    search_terms = extract_search_terms(question_text)
    section_refs = extract_section_references(question_text)
    topic_sections, suppressed = extract_topic_sections(question_text)
    sec_discs = get_section_discriminators(recommendations)

    scored = []
    for rec in recommendations:
        s = score_recommendation(
            rec, search_terms,
            question=question_text,
            section_refs=section_refs,
            topic_sections=topic_sections,
            suppressed_sections=suppressed,
            section_discriminators=sec_discs,
        )
        scored.append((s, rec))
    scored.sort(key=lambda x: -x[0])
    return scored


def run_tests(args):
    test_suite = load_test_suite()
    recommendations = load_recommendations()

    # ── Filter ──
    questions = test_suite
    if args.section:
        questions = [q for q in questions if q["section"] == args.section]
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.question:
        questions = [q for q in questions if q["id"] == args.question]

    rec_qs = [q for q in questions if q["category"] == "qa_recommendation"]
    t8_qs = [q for q in questions if q["category"] == "qa_table8"]
    ev_qs = [q for q in questions if q["category"] == "qa_evidence"]
    kg_qs = [q for q in questions if q["category"] == "qa_knowledge_gap"]

    all_failures = []

    # ═══════════════════════════════════════
    # RECOMMENDATIONS
    # ═══════════════════════════════════════
    cor_correct = 0
    cor_total = 0
    loe_correct = 0
    loe_total = 0
    rec_failures = []

    for q in rec_qs:
        qid = q["id"]
        qtext = q["question"]
        expected_cor = q["expected_cor"]
        expected_loe = q["expected_loe"]
        section = q["section"]

        scored = score_question(qtext, recommendations)
        if not scored or scored[0][0] <= 0:
            found_cor = "NONE"
            found_loe = "NONE"
            top3 = []
        else:
            top_rec = scored[0][1]
            found_cor = top_rec.get("cor", "?")
            found_loe = top_rec.get("loe", "?")
            top3 = [
                (s, r.get("section"), r.get("recNumber"), r.get("cor"), r.get("loe"),
                 r.get("text", r.get("recommendationText", ""))[:80])
                for s, r in scored[:3]
            ]

        cor_match = found_cor == expected_cor
        loe_match = found_loe == expected_loe

        if expected_cor:
            cor_total += 1
            if cor_match:
                cor_correct += 1
        if expected_loe:
            loe_total += 1
            if loe_match:
                loe_correct += 1

        if not cor_match or not loe_match:
            fail = {
                "id": qid, "section": section, "question": qtext,
                "expected_cor": expected_cor, "found_cor": found_cor,
                "cor_ok": cor_match,
                "expected_loe": expected_loe, "found_loe": found_loe,
                "loe_ok": loe_match,
                "top3": top3,
            }
            rec_failures.append(fail)
            all_failures.append(fail)

            if not args.fails_only or True:
                cor_m = "✓" if cor_match else "✗"
                loe_m = "✓" if loe_match else "✗"
                print(f"✗ {qid} [{section}] COR:{cor_m} {expected_cor}→{found_cor} LOE:{loe_m} {expected_loe}→{found_loe}")
                print(f"  Q: {qtext[:120]}")
                for rank, (s, rsec, rn, rcor, rloe, txt) in enumerate(top3[:3], 1):
                    print(f"  #{rank} score={s} sec={rsec} rec={rn} COR={rcor} LOE={rloe} | {txt}")
                print()

    # ═══════════════════════════════════════
    # TABLE 8
    # ═══════════════════════════════════════
    tier_correct = 0
    tier_total = 0
    tier_failures = []
    tier_no_expected = []  # listing questions

    for q in t8_qs:
        qid = q["id"]
        qtext = q["question"]
        expected_tier = q["expected_tier"]

        found_tier = classify_table8_tier(qtext) or "None"

        if not expected_tier:
            tier_no_expected.append(q)
            continue

        tier_total += 1
        match = found_tier == expected_tier
        if match:
            tier_correct += 1
        else:
            fail = {
                "id": qid, "question": qtext,
                "expected_tier": expected_tier, "found_tier": found_tier,
            }
            tier_failures.append(fail)
            all_failures.append(fail)
            print(f"✗ {qid} TIER: {expected_tier}→{found_tier}")
            print(f"  Q: {qtext[:120]}")
            print()

    # ═══════════════════════════════════════
    # EVIDENCE
    # ═══════════════════════════════════════
    ev_correct = 0
    ev_total = len(ev_qs)
    for q in ev_qs:
        qtype = classify_question_type(q["question"])
        if qtype == "evidence":
            ev_correct += 1
        else:
            print(f"✗ {q['id']} EVIDENCE: classified as '{qtype}' instead of 'evidence'")
            print(f"  Q: {q['question'][:120]}")
            print()

    # ═══════════════════════════════════════
    # KNOWLEDGE GAPS
    # ═══════════════════════════════════════
    kg_correct = 0
    kg_total = len(kg_qs)
    for q in kg_qs:
        qtype = classify_question_type(q["question"])
        if qtype == "knowledge_gap":
            kg_correct += 1
        else:
            print(f"✗ {q['id']} KG: classified as '{qtype}' instead of 'knowledge_gap'")
            print(f"  Q: {q['question'][:120]}")
            print()

    # ═══════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════
    print("=" * 70)
    print(f"ROUND 10 TEST RESULTS — {len(questions)} questions total")
    print("=" * 70)

    if rec_qs:
        pct_cor = 100 * cor_correct / max(cor_total, 1)
        pct_loe = 100 * loe_correct / max(loe_total, 1)
        print(f"  RECOMMENDATIONS ({len(rec_qs)}): COR {cor_correct}/{cor_total} ({pct_cor:.1f}%) | LOE {loe_correct}/{loe_total} ({pct_loe:.1f}%)")
        if rec_failures:
            # Group failures by section
            sec_fails = {}
            for f in rec_failures:
                s = f["section"]
                sec_fails[s] = sec_fails.get(s, 0) + 1
            print(f"    Failures by section: {dict(sorted(sec_fails.items()))}")

    if t8_qs:
        pct_tier = 100 * tier_correct / max(tier_total, 1)
        print(f"  TABLE 8 ({len(t8_qs)}): Tier {tier_correct}/{tier_total} ({pct_tier:.1f}%)")
        if tier_no_expected:
            print(f"    Listing questions (no expected tier): {len(tier_no_expected)}")

    if ev_qs:
        print(f"  EVIDENCE ({len(ev_qs)}): Classification {ev_correct}/{ev_total} ({100*ev_correct/max(ev_total,1):.1f}%)")

    if kg_qs:
        print(f"  KNOWLEDGE GAPS ({len(kg_qs)}): Classification {kg_correct}/{kg_total} ({100*kg_correct/max(kg_total,1):.1f}%)")

    print()
    print(f"  TOTAL FAILURES: {len(all_failures)}")

    # Save failures
    fail_path = TEST_SUITE_PATH.replace("_test_suite.json", "_failures.json")
    with open(fail_path, "w") as f:
        json.dump(all_failures, f, indent=2)
    print(f"  Failures saved to {fail_path}")

    return all_failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", help="Filter by section")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--question", help="Filter by question ID")
    parser.add_argument("--fails-only", action="store_true")
    args = parser.parse_args()
    run_tests(args)
