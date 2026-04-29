"""
R9 Test Harness — 1000 new recommendation questions.

Tests COR and LOE accuracy using the same scoring pipeline as R3/R5.

Usage:
    python3 test_qa_r9_harness.py                  # full run
    python3 test_qa_r9_harness.py --fails-only      # show failures only
    python3 test_qa_r9_harness.py --section 4.8     # filter by section
    python3 test_qa_r9_harness.py --verbose          # show all results
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations
from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    score_recommendation,
    extract_search_terms,
    extract_section_references,
    extract_topic_sections,
    get_section_discriminators,
)

TEST_SUITE_PATH = (
    "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project/Datasources/"
    "Shared Folders For MedSync/Claude Questions for testing/Ask MedSync/"
    "qa_round9_test_suite.json"
)

REPORT_PATH = (
    "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project/Datasources/"
    "Shared Folders For MedSync/Claude Questions for testing/Ask MedSync/"
    "qa_round9_report.json"
)


def load_test_suite():
    with open(TEST_SUITE_PATH, "r") as f:
        return json.load(f)


def score_question(question_text, recommendations, sec_discs):
    """Score all recommendations, return sorted list."""
    search_terms = extract_search_terms(question_text)
    section_refs = extract_section_references(question_text)
    topic_sections, suppressed = extract_topic_sections(question_text)

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


def run_harness(section_filter=None, fails_only=False, verbose=False):
    test_suite = load_test_suite()
    recommendations = load_recommendations()
    sec_discs = get_section_discriminators(recommendations)

    print(f"Loaded {len(recommendations)} recommendations, {len(test_suite)} questions")

    cor_pass = 0
    cor_fail = 0
    loe_pass = 0
    loe_fail = 0
    total = 0
    fails_by_section = {}

    for q in test_suite:
        sec = q["section"]
        if section_filter and sec != section_filter:
            continue
        if sec == "Table8":
            continue

        total += 1
        scored = score_question(q["question"], recommendations, sec_discs)
        if not scored:
            continue

        top_score, top_rec = scored[0]
        actual_cor = top_rec.get("cor", "")
        actual_loe = top_rec.get("loe", "")
        expected_cor = q["expected_cor"]
        expected_loe = q["expected_loe"]

        cor_ok = actual_cor == expected_cor
        loe_ok = actual_loe == expected_loe

        if cor_ok:
            cor_pass += 1
        else:
            cor_fail += 1
        if loe_ok:
            loe_pass += 1
        else:
            loe_fail += 1

        is_fail = not cor_ok or not loe_ok

        if is_fail:
            if sec not in fails_by_section:
                fails_by_section[sec] = {"cor": 0, "loe": 0}
            if not cor_ok:
                fails_by_section[sec]["cor"] += 1
            if not loe_ok:
                fails_by_section[sec]["loe"] += 1

        if (fails_only and is_fail) or verbose:
            cor_mark = "\u2713" if cor_ok else "\u2717"
            loe_mark = "\u2713" if loe_ok else "\u2717"
            status = "\u2717" if is_fail else "\u2713"
            print(
                f"{status} {q['id']} [{sec}] "
                f"COR:{cor_mark} {expected_cor}\u2192{actual_cor} "
                f"LOE:{loe_mark} {expected_loe}\u2192{actual_loe}"
            )
            print(f"  Q: {q['question']}")
            for i, (s, rec) in enumerate(scored[:3]):
                print(
                    f"  #{i+1} score={s} sec={rec['section']} "
                    f"rec={rec.get('recNumber','')} "
                    f"COR={rec.get('cor','')} LOE={rec.get('loe','')} "
                    f"| {rec.get('text','')[:80]}"
                )
            print()

    cor_total = cor_pass + cor_fail
    loe_total = loe_pass + loe_fail

    print("=" * 70)
    if cor_total:
        print(f"COR: {cor_pass}/{cor_total} ({100*cor_pass/cor_total:.1f}%)")
    if loe_total:
        print(f"LOE: {loe_pass}/{loe_total} ({100*loe_pass/loe_total:.1f}%)")

    if fails_by_section:
        print(f"\nFailures by section:")
        for sec in sorted(fails_by_section.keys()):
            f = fails_by_section[sec]
            print(f"  {sec}: {f['cor']} COR fails, {f['loe']} LOE fails")

    # Save report
    report = {
        "suite": "R9",
        "total_questions": total,
        "cor_pass": cor_pass,
        "cor_fail": cor_fail,
        "cor_pct": round(100 * cor_pass / cor_total, 1) if cor_total else 0,
        "loe_pass": loe_pass,
        "loe_fail": loe_fail,
        "loe_pct": round(100 * loe_pass / loe_total, 1) if loe_total else 0,
        "fails_by_section": fails_by_section,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to {REPORT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="R9 Test Harness")
    parser.add_argument("--section", help="Filter by section")
    parser.add_argument("--fails-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_harness(
        section_filter=args.section,
        fails_only=args.fails_only,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
