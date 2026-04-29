#!/usr/bin/env python3
"""
Local test harness for Table 8 tier classification accuracy.
Scores all 64 Table8 questions against classify_table8_tier().

Usage:
    python test_table8_harness.py                    # full run
    python test_table8_harness.py --fails-only       # only show failures
    python test_table8_harness.py --question QA-2406 # single question
    python test_table8_harness.py --tier Absolute    # filter by expected tier
"""
import json
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    classify_table8_tier,
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


def run_tests(args, suite_path=None):
    test_suite = load_test_suite(suite_path)

    # Filter to Table8 only
    questions = [q for q in test_suite if q["category"] == "qa_table8"]

    if args.question:
        questions = [q for q in questions if q["id"] == args.question]
    if args.tier:
        questions = [q for q in questions if q["expected_tier"] == args.tier]

    correct = 0
    total = 0
    failures_by_tier = {}

    for q in questions:
        qid = q["id"]
        qtext = q["question"]
        expected_tier = q["expected_tier"]

        found_tier = classify_table8_tier(qtext)
        if found_tier is None:
            found_tier = "NOT_DETECTED"

        match = found_tier == expected_tier
        total += 1
        if match:
            correct += 1

        if not match:
            if expected_tier not in failures_by_tier:
                failures_by_tier[expected_tier] = []
            failures_by_tier[expected_tier].append({
                "id": qid,
                "question": qtext,
                "expected": expected_tier,
                "found": found_tier,
            })

        if not args.fails_only or not match:
            if args.verbose or not match:
                status = "✓" if match else "✗"
                print(f"{status} {qid} expected={expected_tier} found={found_tier}")
                if not match:
                    print(f"  Q: {qtext[:140]}")
                    print()

    print("=" * 70)
    print(f"Tier accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    print()

    if failures_by_tier:
        print("Failures by expected tier:")
        for tier in sorted(failures_by_tier.keys()):
            fails = failures_by_tier[tier]
            print(f"  {tier}: {len(fails)} failures")
            for f in fails:
                print(f"    {f['id']}: expected={f['expected']} found={f['found']}")
                print(f"      {f['question'][:120]}")

    return correct, total, failures_by_tier


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", help="Filter by question ID")
    parser.add_argument("--tier", help="Filter by expected tier")
    parser.add_argument("--fails-only", action="store_true", help="Only show failures")
    parser.add_argument("--verbose", action="store_true", help="Show all results")
    parser.add_argument("--suite", choices=["r3", "r5"], default="r3", help="Test suite to use")
    args = parser.parse_args()
    run_tests(args, suite_path=TEST_SUITES[args.suite])
