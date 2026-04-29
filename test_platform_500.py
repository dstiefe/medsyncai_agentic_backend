#!/usr/bin/env python3
"""
Test 500+ questions against the LIVE platform (localhost:8000).
Reports COR/LOE accuracy for qa_recommendation,
tier accuracy for qa_table8,
and routing accuracy for qa_evidence/qa_knowledge_gap.
"""

import asyncio
import json
import re
import sys
import time
import httpx

BASE_URL = "http://localhost:8000"
ENDPOINT = "/chat/stream"
CONCURRENCY = 5  # parallel requests
TIMEOUT = 60.0

SUITE_PATH = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"


def parse_sse_response(raw: str) -> dict:
    """Parse SSE stream and extract the final_chunk JSON."""
    result = {
        "summary": "",
        "answer_parts": [],
        "citations": [],
        "cor": "",
        "loe": "",
        "tier": "",
        "raw": raw,
    }

    for line in raw.split("\n"):
        if not line.startswith("data: "):
            continue
        data_str = line[6:].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type", "")

        if event_type == "final_chunk":
            payload = data.get("data", {})
            result["summary"] = payload.get("summary", "")
            result["answer_parts"] = payload.get("answer", []) if isinstance(payload.get("answer"), list) else [str(payload.get("answer", ""))]
            result["citations"] = payload.get("citations", [])

            # Extract COR/LOE from answer parts
            for part in result["answer_parts"]:
                cor_match = re.search(r"COR\s+(\d[ab]?(?::[\w\s]+)?)", part, re.IGNORECASE)
                loe_match = re.search(r"LOE\s+([A-C](?:-[A-Z]{1,3})?)", part, re.IGNORECASE)
                if cor_match and not result["cor"]:
                    result["cor"] = cor_match.group(1)
                if loe_match and not result["loe"]:
                    result["loe"] = loe_match.group(1)

            # Extract tier from answer
            full_answer = " ".join(result["answer_parts"])
            if "absolute" in full_answer.lower():
                result["tier"] = "Absolute"
            elif "benefit may exceed risk" in full_answer.lower() or "benefit-may-exceed" in full_answer.lower():
                result["tier"] = "Benefit May Exceed Risk"
            elif "relative" in full_answer.lower():
                result["tier"] = "Relative"

    return result


async def test_question(client: httpx.AsyncClient, q: dict, sem: asyncio.Semaphore) -> dict:
    """Send a single question and return the result."""
    async with sem:
        qid = q["id"]
        question = q["question"]
        session_id = f"test_{qid}_{int(time.time())}"

        try:
            response = await client.post(
                f"{BASE_URL}{ENDPOINT}",
                json={
                    "message": question,
                    "uid": "test_user",
                    "session_id": session_id,
                },
                timeout=TIMEOUT,
            )
            raw = response.text
            parsed = parse_sse_response(raw)

            return {
                "id": qid,
                "question": question,
                "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": parsed["cor"],
                "actual_loe": parsed["loe"],
                "actual_tier": parsed["tier"],
                "summary": parsed["summary"],
                "answer_preview": " ".join(parsed["answer_parts"])[:300],
                "status": "ok",
                "http_status": response.status_code,
            }
        except Exception as e:
            return {
                "id": qid,
                "question": question,
                "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": "",
                "actual_loe": "",
                "actual_tier": "",
                "summary": "",
                "answer_preview": "",
                "status": f"error: {e}",
                "http_status": 0,
            }


def normalize_cor(cor: str) -> str:
    """Normalize COR value for comparison."""
    cor = cor.strip().lower()
    cor = re.sub(r"\s+", " ", cor)
    # Map variations
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


def normalize_loe(loe: str) -> str:
    """Normalize LOE value for comparison."""
    return loe.strip().upper()


async def run_tests():
    with open(SUITE_PATH) as f:
        suite = json.load(f)

    # Optional: limit to first N
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(suite)
    suite = suite[:limit]

    print(f"Testing {len(suite)} questions against {BASE_URL}")
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
            status = "✓" if result["status"] == "ok" else "✗"
            if completed % 10 == 0 or completed == len(suite):
                print(f"  [{completed}/{len(suite)}] {status}")

    # ── Analysis ──
    print("\n" + "=" * 70)
    print("RESULTS ANALYSIS")
    print("=" * 70)

    # Separate by category
    rec_results = [r for r in results if r["category"] == "qa_recommendation"]
    t8_results = [r for r in results if r["category"] == "qa_table8"]
    ev_results = [r for r in results if r["category"] == "qa_evidence"]
    kg_results = [r for r in results if r["category"] == "qa_knowledge_gap"]

    # ── Recommendation accuracy ──
    if rec_results:
        cor_correct = 0
        loe_correct = 0
        cor_total = 0
        loe_total = 0
        cor_failures = []
        loe_failures = []
        no_cor = []
        no_answer = []

        for r in rec_results:
            if r["status"] != "ok" or r["http_status"] != 200:
                no_answer.append(r)
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
                else:
                    loe_failures.append(r)

        print(f"\n📋 RECOMMENDATIONS ({len(rec_results)} questions)")
        print(f"  COR accuracy: {cor_correct}/{cor_total} ({100*cor_correct/max(cor_total,1):.1f}%)")
        print(f"  LOE accuracy: {loe_correct}/{loe_total} ({100*loe_correct/max(loe_total,1):.1f}%)")
        print(f"  No COR found: {len(no_cor)}")
        print(f"  No answer: {len(no_answer)}")

        if cor_failures:
            print(f"\n  COR FAILURES ({len(cor_failures)}):")
            for r in cor_failures[:20]:
                print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']} got={r['actual_cor']}")
                print(f"      Q: {r['question'][:100]}")

        if no_cor:
            print(f"\n  NO COR EXTRACTED ({len(no_cor)}):")
            for r in no_cor[:20]:
                print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']}")
                print(f"      Q: {r['question'][:100]}")
                print(f"      A: {r['answer_preview'][:150]}")

    # ── Table 8 accuracy ──
    if t8_results:
        tier_correct = 0
        tier_total = 0
        tier_failures = []
        tier_listing = []

        for r in t8_results:
            if r["status"] != "ok":
                continue
            if r["expected_tier"]:
                tier_total += 1
                if r["actual_tier"] == r["expected_tier"]:
                    tier_correct += 1
                else:
                    tier_failures.append(r)
            else:
                tier_listing.append(r)  # listing questions

        print(f"\n📋 TABLE 8 ({len(t8_results)} questions)")
        print(f"  Tier accuracy: {tier_correct}/{tier_total} ({100*tier_correct/max(tier_total,1):.1f}%)")
        print(f"  Listing questions: {len(tier_listing)}")

        if tier_failures:
            print(f"\n  TIER FAILURES ({len(tier_failures)}):")
            for r in tier_failures[:20]:
                print(f"    {r['id']} expected={r['expected_tier']} got={r['actual_tier']}")
                print(f"      Q: {r['question'][:100]}")
                print(f"      A: {r['answer_preview'][:150]}")

    # ── Evidence/KG ──
    if ev_results:
        ev_answered = sum(1 for r in ev_results if r["status"] == "ok" and r["answer_preview"])
        print(f"\n📋 EVIDENCE ({len(ev_results)} questions)")
        print(f"  Got answers: {ev_answered}/{len(ev_results)}")
        for r in ev_results:
            if not r["answer_preview"]:
                print(f"    NO ANSWER: {r['id']} {r['question'][:80]}")

    if kg_results:
        kg_answered = sum(1 for r in kg_results if r["status"] == "ok" and r["answer_preview"])
        print(f"\n📋 KNOWLEDGE GAPS ({len(kg_results)} questions)")
        print(f"  Got answers: {kg_answered}/{len(kg_results)}")

    # ── Summary stats ──
    errors = [r for r in results if r["status"] != "ok"]
    empty = [r for r in results if r["status"] == "ok" and not r["answer_preview"]]

    print(f"\n{'='*70}")
    print(f"SUMMARY: {len(results)} tested | {len(errors)} errors | {len(empty)} empty answers")

    # Save full results
    out_path = SUITE_PATH.replace("_test_suite.json", "_test_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results saved to {out_path}")

    # Save failures for analysis
    all_failures = []
    if rec_results:
        all_failures.extend(cor_failures if 'cor_failures' in dir() else [])
        all_failures.extend(no_cor if 'no_cor' in dir() else [])
    if t8_results:
        all_failures.extend(tier_failures if 'tier_failures' in dir() else [])

    fail_path = SUITE_PATH.replace("_test_suite.json", "_failures.json")
    with open(fail_path, "w") as f:
        json.dump(all_failures, f, indent=2)
    print(f"Failures saved to {fail_path}")


if __name__ == "__main__":
    asyncio.run(run_tests())
