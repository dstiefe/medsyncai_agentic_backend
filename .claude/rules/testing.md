# Testing

## How to Run Tests

### Start the server
```bash
uvicorn app.main:app --reload --port 8000
```

### General test command
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "your test query here"}'
```

### AIS clinical engine test command
```bash
curl -s -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"<query>","uid":"test_user","session_id":"<unique_id>"}'
```

## Required Report Format
After every test, report all three — no exceptions:

```
INTENT CLASSIFIER:   <intent label returned>
ENGINE ROUTING:      <engine selected>
RESPONSE:            <final response text>
```

If any of the three is missing or errored, that is a test failure. Go through the Fix process before proceeding.

## Standard AIS Test Queries

| ID | Query | Expected Path |
|---|---|---|
| OOS-1 | "How do I manage ICH?" | intent→clinical_support → router→out_of_scope → decline |
| INS-1 | "65yo, NIHSS 18, M1 occlusion, LKW 2h" | intent→clinical_support → router→in_scope → reperfusion_agent |
| INS-2 | "What are the BP targets during AIS?" | intent→clinical_support → router→in_scope → bp_metabolic_agent |
| DEV-1 | Any non-AIS query | intent→general or knowledge_base (does NOT reach AIS engine) |

## What to Test
- Happy path (expected input → expected output)
- Edge cases (empty input, null, zero, max values)
- Error cases (invalid input, missing fields, network failure)
- Do not test implementation details — test behavior

## Requirements
- Every new engine or feature needs tests before the dev log is written
- Dev log entry only written after tests pass and human approves
- Intent, routing, and response must all be confirmed — partial passes are failures
