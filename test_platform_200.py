#!/usr/bin/env python3
"""
Test 200 questions (100 rec + 100 evidence) against the LIVE platform.
Sections: 2.3, 2.7, 3.x–6.5
"""
import asyncio
import json
import re
import sys
import time
import random
import httpx

random.seed(42)

BASE_URL = "http://localhost:8000"
ENDPOINT = "/chat/stream"
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


def parse_sse_response(raw: str) -> dict:
    result = {"summary": "", "answer_parts": [], "cor": "", "loe": "", "tier": "", "raw": raw}
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

            for part in result["answer_parts"]:
                cor_match = re.search(r"COR\s+(\d[ab]?(?::[\w\s]+)?)", part, re.IGNORECASE)
                loe_match = re.search(r"LOE\s+([A-C](?:-[A-Z]{1,3})?)", part, re.IGNORECASE)
                if cor_match and not result["cor"]:
                    result["cor"] = cor_match.group(1)
                if loe_match and not result["loe"]:
                    result["loe"] = loe_match.group(1)

            full_answer = " ".join(result["answer_parts"])
            if "absolute" in full_answer.lower():
                result["tier"] = "Absolute"
            elif "benefit may exceed risk" in full_answer.lower() or "benefit-may-exceed" in full_answer.lower():
                result["tier"] = "Benefit May Exceed Risk"
            elif "relative" in full_answer.lower():
                result["tier"] = "Relative"
    return result


async def test_question(client, q, sem):
    async with sem:
        qid = q["id"]
        session_id = f"test_{qid}_{int(time.time())}"
        try:
            response = await client.post(
                f"{BASE_URL}{ENDPOINT}",
                json={"message": q["question"], "uid": "test_user", "session_id": session_id},
                timeout=TIMEOUT,
            )
            parsed = parse_sse_response(response.text)
            return {
                "id": qid, "question": q["question"], "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": parsed["cor"], "actual_loe": parsed["loe"],
                "actual_tier": parsed["tier"],
                "summary": parsed["summary"],
                "answer_preview": " ".join(parsed["answer_parts"])[:400],
                "status": "ok", "http_status": response.status_code,
            }
        except Exception as e:
            return {
                "id": qid, "question": q["question"], "category": q["category"],
                "section": q["section"],
                "expected_cor": q.get("expected_cor", ""),
                "expected_loe": q.get("expected_loe", ""),
                "expected_tier": q.get("expected_tier", ""),
                "actual_cor": "", "actual_loe": "", "actual_tier": "",
                "summary": "", "answer_preview": "",
                "status": f"error: {e}", "http_status": 0,
            }


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
    return loe.strip().upper()


async def run_tests():
    with open(SUITE_PATH) as f:
        suite = json.load(f)

    # Filter to target sections
    recs = [q for q in suite if q["category"] == "qa_recommendation" and in_range(q["section"])]
    evs = [q for q in suite if q["category"] == "qa_evidence" and in_range(q["section"])]

    # Select 100 recs spread across sections
    from collections import defaultdict
    rec_by_sec = defaultdict(list)
    for q in recs:
        rec_by_sec[q["section"]].append(q)
    selected_recs = []
    for sec in sorted(rec_by_sec.keys()):
        selected_recs.append(random.choice(rec_by_sec[sec]))
    remaining = [q for q in recs if q not in selected_recs]
    random.shuffle(remaining)
    while len(selected_recs) < 100 and remaining:
        selected_recs.append(remaining.pop())

    # All 100 evidence
    selected_evs = evs[:100]

    questions = selected_recs + selected_evs
    print(f"Testing {len(questions)} questions ({len(selected_recs)} rec + {len(selected_evs)} ev) against {BASE_URL}")
    print("=" * 70)

    sem = asyncio.Semaphore(CONCURRENCY)
    results = []

    async with httpx.AsyncClient() as client:
        tasks = [test_question(client, q, sem) for q in questions]
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            if completed % 20 == 0 or completed == len(questions):
                print(f"  [{completed}/{len(questions)}]")

    # ── Analysis ──
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    rec_results = [r for r in results if r["category"] == "qa_recommendation"]
    ev_results = [r for r in results if r["category"] == "qa_evidence"]

    # Recommendation accuracy
    cor_correct = cor_total = loe_correct = loe_total = 0
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

    print(f"\nRECOMMENDATIONS ({len(rec_results)} questions)")
    print(f"  COR: {cor_correct}/{cor_total} ({100*cor_correct/max(cor_total,1):.1f}%)")
    print(f"  LOE: {loe_correct}/{loe_total} ({100*loe_correct/max(loe_total,1):.1f}%)")
    print(f"  No COR extracted: {len(no_cor)}")
    print(f"  No answer/error: {len(no_answer)}")

    if cor_failures:
        print(f"\n  COR FAILURES ({len(cor_failures)}):")
        for r in cor_failures:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']} got={r['actual_cor']}")
            print(f"      Q: {r['question'][:120]}")

    if no_cor:
        print(f"\n  NO COR EXTRACTED ({len(no_cor)}):")
        for r in no_cor:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_cor']}")
            print(f"      Q: {r['question'][:120]}")
            print(f"      A: {r['answer_preview'][:200]}")

    if loe_failures:
        print(f"\n  LOE FAILURES ({len(loe_failures)}):")
        for r in loe_failures[:30]:
            print(f"    {r['id']} [{r['section']}] expected={r['expected_loe']} got={r['actual_loe']}")
            print(f"      Q: {r['question'][:120]}")

    # Evidence analysis
    ev_answered = 0
    ev_empty = []
    ev_errors = []
    for r in ev_results:
        if r["status"] != "ok":
            ev_errors.append(r)
        elif r["answer_preview"]:
            ev_answered += 1
        else:
            ev_empty.append(r)

    print(f"\nEVIDENCE ({len(ev_results)} questions)")
    print(f"  Answered: {ev_answered}/{len(ev_results)}")
    print(f"  Empty: {len(ev_empty)}")
    print(f"  Errors: {len(ev_errors)}")

    if ev_empty:
        print(f"\n  EMPTY ANSWERS:")
        for r in ev_empty[:20]:
            print(f"    {r['id']} [{r['section']}] {r['question'][:120]}")

    # Summary
    errors = [r for r in results if r["status"] != "ok"]
    print(f"\n{'='*70}")
    print(f"TOTAL: {len(results)} tested | {len(errors)} errors")

    # Save results
    out_path = SUITE_PATH.replace("_test_suite.json", "_platform200_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {out_path}")

    # Save failures
    all_failures = cor_failures + no_cor + loe_failures + ev_empty + ev_errors + no_answer
    fail_path = SUITE_PATH.replace("_test_suite.json", "_platform200_failures.json")
    with open(fail_path, "w") as f:
        json.dump(all_failures, f, indent=2)
    print(f"Failures saved to {fail_path}")


if __name__ == "__main__":
    asyncio.run(run_tests())
