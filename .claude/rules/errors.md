# Error Handling

## Fix Classification
Before implementing any fix, classify it. Never skip this step.

**PATCH** — fixes the symptom for this specific case only. Do not use.
Always identify the root cause and propose a systematic fix instead.

**SYSTEMATIC** — fixes the root cause so the same class of issue cannot recur.
Requires:
- Root cause identified
- Class of problem explained
- Confirmation no similar issues exist elsewhere
- Test that would have caught this

**SOURCE DATA** — the logic was correct, the data was wrong.
Fix is to correct a reference file, JSON source, or ontology entry — not code.
Requires:
- Exact file and field identified
- All similar records checked

## General Rules
- Every function that can fail must handle its failure case explicitly
- Never silently catch and discard errors
- Log errors with enough context to debug (what happened, what inputs caused it)
- User-facing error messages should be helpful and not expose internals

## API Error Handling
- All FastAPI route handlers must be wrapped in try/except
- Always return a structured error response — never let unhandled errors bubble to the client
- Log the full error server-side, return a sanitised message to the client
- Engine errors must return via `_build_return(status="error", ...)`

## Async Errors
- Always await async calls inside try/except
- Unhandled exceptions in async routes are never acceptable

## Validation
- Validate all external input before processing (API requests, user input, env vars)
- Use Pydantic models for all request/response shapes
- Return 422 with a clear message when validation fails

## Environment Variables
- All required env vars must be validated at startup
- If a required env var is missing, fail fast with a clear error message
- Never default to an insecure fallback silently
