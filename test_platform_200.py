#!/usr/bin/env python3
"""
Test questions against the LIVE clinical QA platform (/clinical/qa).
Uses the same 1298-question suite; tests recommendation COR/LOE,
Table 8 tier classification, evidence routing, and KG routing.
"""
import asyncio
import json
import re
import sys
import time
import random
import httpx
from collections import defaultdict

random.seed(42)

BASE_URL = "http://localhost:8000"
ENDPOINT = "/clinical/qa"
CONCURRENCY = 3
TIMEOUT = 90.0

SUITE_PATH = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"


def in_range(sec):
    if sec in ('2.3', '2.7'):
        return True
    parts = sec.split('.')
    try:
        return int(parts[0]) >= 3
    except:
        return False


def normalize_cor(cor):
    cor = cor.strip().lower()
    cor = re.sub(r"\s+", " ", cor)
    mapping = {
        "1": "1", "class 1": "1", "class i": "1",
        "2a": "2a", "class 2a": "2a", "class iia": "2a",
        "2b": "2b", "class 2b": "2b", "class iib": "2b",
        "3: no benefit": "3:no benefit", "3:no benefit": "3:no benefit",
        "3 no benefit": "3:no benefit", "3-no benefit": "3:no benefit",
        "3: harm": "3:harm", "3:harm": "3:harm",
        "3 harm": "3:harm", "3-harm": "3:harm",
    }
    return mapping.get(cor, cor)


def normalize_loe(loe):
    return loe.strip().upper().replace(" ", "")


def extract_cor_loe(data: dict) -> tuple:
    """Extract COR and LOE from the /clinical/qa response."""
    cor = ""
    loe = ""

    # Method 1: clarificationOptions (when needsClarification is true)
    opts = data.get("clarificationOptions", [])
    if opts and len(opts) >= 1:
        # Take the first option (highest-ranked match)
        cor = opts[0].get("cor", "")
        loe = opts[0].get("loe", "")

    # Method 2: auditTrail → assembly or recommendation data
    if not cor:
        for step in data.get("auditTrail", []):
            detail = step.get("detail", {})
            if "cor" in detail:
                cor = detail["cor"]
            if "loe" in detail:
                loe = detail["loe"]
            # Check top_rec in detail
            if "top_rec" in detail:
                top = detail["top_rec"]
                cor = cor or top.get("cor", "")
                loe = loe or top.get("loe", "")

    # Method 3: Parse from answer text — multiple patterns
    if not cor:
        answer = data.get("answer", "")
        # Try "COR X" pattern
        cor_match = re.search(r"COR\s+(\d[ab]?(?:\s*:\s*[\w\s]+)?)", answer, re.IGNORECASE)
        if not cor_match:
            # Try "Class of Recommendation: X"
            cor_match = re.search(r"Class of Recommendation:\s*(\d[ab]?(?:\s*[:\-]\s*[\w\s]+)?)", answer, re.IGNORECASE)
        if not cor_match:
            # Try "COR X, LOE Y" compact
            cor_match = re.search(r"(?:COR|Class)\s*(\d[ab]?(?:\s*:\s*\w[\w\s]*)?)", answer, re.IGNORECASE)
        if cor_match:
            cor = cor_match.group(1).strip()
            # Clean trailing junk
            cor = re.sub(r'\s*\|.*$', '', cor)

    if not loe:
        answer = data.get("answer", "")
        loe_match = re.search(r"LOE\s+([A-C](?:-[A-Z]{1,3})?)", answer, re.IGNORECASE)
        if not loe_match:
            loe_match = re.search(r"Level of Evidence:\s*([A-C](?:-[A-Z]{1,3})?)", answer, re.IGNORECASE)
        if not loe_match:
            loe_match = re.search(r"LOE\s*([A-C](?:-[A-Z]{1,3})?)", answer, re.IGNORECASE)
        if loe_match:
            loe = loe_match.group(1).strip()

    return cor, loe


def extract_tier(data: dict) -> str:
    """Extract Table 8 tier from /clinical/qa response."""
    answer = data.get("answer", "").lower()

    # Check for tier in auditTrail
    for step in data.get("auditTrail", []):
        detail = step.get("detail", {})
        if "tier" in detail:
            return detail["tier"]
        if "table8_tier" in detail:
            return detail["table8_tier"]

    # Parse from answer text
    if "absolute" in answer and "contraindication" in answer:
        return "Absolute"
    if "benefit may exceed risk" in answer or "benefit-may-exceed" in answer:
        return "Benefit May Exceed Risk"
    if "relative" in answer and "contraindication" in answer:
        return "Relative"

    return ""


def check_evidence_routing(data: dict) -> bool:
    """Check if the question was routed through evidence/RSS pathway."""
    # Check auditTrail for evidence-related steps
    for step in data.get("auditTrail", []):
        step_name = step.get("step", "")
        detail = step.get("detail", {})
        qt = detail.get("question_type", "")
        if qt == "evidence":
            return True
        if "rss" in step_name.lower() or "evidence" in step_name.lower():
            return True
        if detail.get("rss_count", 0) > 0:
            return True
    # Check if answer contains evidence-style content
    answer = data.get("answer", "")
    if len(answer) > 100:
        return True  # Got a substantive answer
    return False


def check_kg_routing(data: dict) -> bool:
    """Check if the question was routed through knowledge gap pathway."""
    for step in data.get("auditTrail", []):
        detail = step.get("detail", {})
        qt = detail.get("question_type", "")
        if qt == "knowledge_gap":
            return True
        if detail.get("kg_has_gaps"):
            return True
    answer = data.get("answer", "")
    if "knowledge gap" in answer.lower() or "further research" in answer.lower() or "future study" in answer.lower():
        return True
    if len(answer) > 50:
        return True
    return False


async def test_question(client, q, sem):
    async with sem:
        qid = q["id"]
        session_id = f"test_{qid}_{int(time.time())}"
        try:
            response = await client.post(
                f"{BASE_URL}{ENDPOINT}",
                json={"question": q["question"], "uid": "test_user", "session_id": session_id},
                timeout=TIMEOUT,
            )
            if response.status_code != 200:
                return {
                    "id": qid, "question": q["question"], "category": q["category"],
                    "section": q["section"],
                    "expected_cor": q.get("expected_cor", ""),
                    "expected_loe": q.get("expected_loe", ""),
                    "expected_tier": q.get("expected_tier", ""),
                    "actual_cor": "", "actual_loe": "", "actual_tier": "",
                    "answer_preview": "",
                    "status": f"http_{response.status_code}",
                    "raw": response.text[:500],
                }
            data = response.json()
            cor, loe = extract_cor_loe(data)
            tier = extract_tier(data)
            is_evidence = check_evidence_routing(data)
            is_kg = check_kg_routing(data)

            return {
                "id": qid, "question": q["question"], "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": cor, "actual_loe": loe, "actual_tier": tier,
                "answer_preview": data.get("answer", "")[:400],
                "needs_clarification": data.get("needsClarification", False),
                "clarification_options": data.get("clarificationOptions", []),
                "is_evidence": is_evidence,
                "is_kg": is_kg,
                "status": "ok",
                "raw_data": data,
            }
        except Exception as e:
            return {
                "id": qid, "question": q["question"], "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": "", "actual_loe": "", "actual_tier": "",
                "answer_preview": "",
                "status": f"error: {e}",
            }


async def run_tests(max_questions=None, sections_filter=None):
    with open(SUITE_PATH) as f:
        suite = json.load(f)

    if sections_filter:
        suite = [q for q in suite if sections_filter(q["section"])]

    if max_questions and len(suite) > max_questions:
        # Spread across categories
        by_cat = defaultdict(list)
        for q in suite:
            by_cat[q["category"]].append(q)
        selected = []
        per_cat = max_questions // len(by_cat)
        for cat, qs in by_cat.items():
            random.shuffle(qs)
            selected.extend(qs[:per_cat])
        # Fill remainder
        remaining = [q for q in suite if q not in selected]
        random.shuffle(remaining)
        while len(selected) < max_questions and remaining:
            selected.append(remaining.pop())
        suite = selected

    print(f"Testing {len(suite)} questions against {BASE_URL}{ENDPOINT}")
    cats = defaultdict(int)
    for q in suite:
        cats[q["category"]] += 1
    for cat, cnt in sorted(cats.items()):
        print(f"  {cat}: {cnt}")
    print("=" * 70)

    sem = asyncio.Semaphore(CONCURRENCY)
    results = []

    async with httpx.AsyncClient() as client:
        tasks = [test_question(client, q, sem) for q in suite]
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            status_char = "." if result["status"] == "ok" else "X"
            if completed % 10 == 0 or completed == len(suite):
                print(f"  [{completed}/{len(suite)}]")

    # ── Analysis ──
    print("\n" + "=" * 70)
    print("PLATFORM TEST RESULTS")
    print("=" * 70)

    # -- Recommendations --
    rec_results = [r for r in results if r["category"] == "qa_recommendation"]
    cor_correct = cor_total = loe_correct = loe_total = 0
    cor_failures = []
    loe_failures = []
    no_cor = []
    clarification_recs = []
    errors = []

    for r in rec_results:
        if r["status"] != "ok":
            errors.append(r)
            continue

        # Handle clarification responses
        if r.get("needs_clarification") and r.get("clarification_options"):
            # Check if any clarification option matches expected COR/LOE
            opts = r["clarification_options"]
            found_cor = False
            found_loe = False
            for opt in opts:
                opt_cor = normalize_cor(opt.get("cor", ""))
                opt_loe = normalize_loe(opt.get("loe", ""))
                if r["expected_cor"] and opt_cor == normalize_cor(r["expected_cor"]):
                    found_cor = True
                if r["expected_loe"] and opt_loe == normalize_loe(r["expected_loe"]):
                    found_loe = True
            if r["expected_cor"]:
                cor_total += 1
                if found_cor:
                    cor_correct += 1
                else:
                    cor_failures.append(r)
            if r["expected_loe"]:
                loe_total += 1
                if found_loe:
                    loe_correct += 1
                else:
                    loe_failures.append(r)
            clarification_recs.append(r)
            continue

        if r["expected_cor"]:
            cor_total += 1
            if not r["actual_cor"]:
                no_cor.append(r)
            elif normalize_cor(r["actual_cor"]) == normalize_cor(r["expected_cor"]):
                cor_correct += 1
            else:
                cor_failures.append(r)

        if r["expected_loe"]:
            loe_total += 1
            if r["actual_loe"] and normalize_loe(r["actual_loe"]) == normalize_loe(r["expected_loe"]):
                loe_correct += 1
            elif not r.get("actual_loe"):
                loe_failures.append(r)
            else:
                loe_failures.append(r)

    print(f"\nRECOMMENDATIONS ({len(rec_results)} questions)")
    print(f"  COR: {cor_correct}/{cor_total} ({100*cor_correct/max(cor_total,1):.1f}%)")
    print(f"  LOE: {loe_correct}/{loe_total} ({100*loe_correct/max(loe_total,1):.1f}%)")
    print(f"  Clarifications: {len(clarification_recs)}")
    print(f"  No COR extracted: {len(no_cor)}")
    print(f"  Errors: {len(errors)}")

    if cor_failures:
        print(f"\n  COR FAILURES ({len(cor_failures)}):")
        for r in cor_failures[:20]:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']} got={r['actual_cor']}")
            print(f"      Q: {r['question'][:120]}")
            if r.get("needs_clarification"):
                for opt in r.get("clarification_options", []):
                    print(f"        opt: COR={opt.get('cor','')} LOE={opt.get('loe','')} — {opt.get('description','')[:80]}")

    if no_cor[:15]:
        print(f"\n  NO COR EXTRACTED ({len(no_cor)}):")
        for r in no_cor[:15]:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']}")
            print(f"      Q: {r['question'][:120]}")
            print(f"      A: {r['answer_preview'][:200]}")

    if loe_failures[:15]:
        print(f"\n  LOE FAILURES (showing 15 of {len(loe_failures)}):")
        for r in loe_failures[:15]:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_loe']} got={r.get('actual_loe','')}")
            print(f"      Q: {r['question'][:120]}")

    # -- Table 8 --
    t8_results = [r for r in results if r["category"] == "qa_table8"]
    tier_correct = tier_total = 0
    tier_failures = []
    for r in t8_results:
        if r["status"] != "ok":
            continue
        if r["expected_tier"]:
            tier_total += 1
            if r["actual_tier"] == r["expected_tier"]:
                tier_correct += 1
            else:
                tier_failures.append(r)
    print(f"\nTABLE 8 ({len(t8_results)} questions)")
    print(f"  Tier: {tier_correct}/{tier_total} ({100*tier_correct/max(tier_total,1):.1f}%)")
    if tier_failures:
        print(f"  FAILURES ({len(tier_failures)}):")
        for r in tier_failures[:10]:
            print(f"    {r['id']} expected={r['expected_tier']} got={r['actual_tier']}")
            print(f"      Q: {r['question'][:120]}")
            print(f"      A: {r['answer_preview'][:200]}")

    # -- Evidence --
    ev_results = [r for r in results if r["category"] == "qa_evidence"]
    ev_routed = sum(1 for r in ev_results if r.get("is_evidence") and r["status"] == "ok")
    ev_answered = sum(1 for r in ev_results if r["status"] == "ok" and r.get("answer_preview"))
    print(f"\nEVIDENCE ({len(ev_results)} questions)")
    print(f"  Routed correctly: {ev_routed}/{len(ev_results)}")
    print(f"  With answer: {ev_answered}/{len(ev_results)}")
    ev_empty = [r for r in ev_results if r["status"] == "ok" and not r.get("answer_preview")]
    if ev_empty:
        print(f"  EMPTY ({len(ev_empty)}):")
        for r in ev_empty[:10]:
            print(f"    {r['id']} [{r['section']}] {r['question'][:100]}")

    # -- Knowledge Gaps --
    kg_results = [r for r in results if r["category"] == "qa_knowledge_gap"]
    kg_routed = sum(1 for r in kg_results if r.get("is_kg") and r["status"] == "ok")
    kg_answered = sum(1 for r in kg_results if r["status"] == "ok" and r.get("answer_preview"))
    print(f"\nKNOWLEDGE GAPS ({len(kg_results)} questions)")
    print(f"  Routed correctly: {kg_routed}/{len(kg_results)}")
    print(f"  With answer: {kg_answered}/{len(kg_results)}")

    # -- Summary --
    all_errors = [r for r in results if r["status"] != "ok"]
    print(f"\n{'='*70}")
    print(f"TOTAL: {len(results)} tested | {len(all_errors)} errors")
    print(f"{'='*70}")

    # Save results
    out_path = SUITE_PATH.replace("_test_suite.json", "_platform_results.json")
    # Strip raw_data for size
    save_results = []
    for r in results:
        r2 = {k: v for k, v in r.items() if k != "raw_data"}
        save_results.append(r2)
    with open(out_path, "w") as f:
        json.dump(save_results, f, indent=2)
    print(f"Results saved to {out_path}")

    # Save failures
    all_failures = cor_failures + no_cor + loe_failures + tier_failures + ev_empty + all_errors
    fail_path = SUITE_PATH.replace("_test_suite.json", "_platform_failures.json")
    save_failures = []
    for r in all_failures:
        r2 = {k: v for k, v in r.items() if k != "raw_data"}
        save_failures.append(r2)
    with open(fail_path, "w") as f:
        json.dump(save_failures, f, indent=2)
    print(f"Failures saved to {fail_path}")


if __name__ == "__main__":
    # Default: test 200 questions from sections 2.3, 2.7, 3.x-6.5
    max_q = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    asyncio.run(run_tests(max_questions=max_q, sections_filter=in_range))
