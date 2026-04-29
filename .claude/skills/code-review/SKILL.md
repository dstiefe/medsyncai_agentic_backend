---
name: code-review
description: Perform a thorough code review against project conventions. Use before opening a PR or when asked to review specific files.
---

# Code Review

Review the files specified (or all changes since branching from main if none specified).

## Check For

### Correctness
- Logic errors or off-by-one mistakes
- Unhandled edge cases (null, empty, zero, large values)
- Race conditions or async issues

### Project Conventions (from .claude/rules/)
- API: all data endpoints POST, `require_auth` on every router, uid + session_id on every request model, session_id in every response
- Code style: Three-Layer Rule respected (no domain knowledge in SKILL.md, no LM calls in scripts/)
- Code style: No LM used for threshold comparisons — those must be in scripts/
- Engine: extends BaseEngine, returns via `_build_return()`, all 5 wiring locations updated
- Errors: fix classification used, errors handled and logged, not swallowed

### Testing
- Tests written for new logic
- Test report includes INTENT CLASSIFIER, ENGINE ROUTING, and RESPONSE

### Security
- No secrets, API keys, or credentials in the code
- Input validated before use (Pydantic models present)
- No hardcoded base URLs — env vars used

### Dev Log
- If work is complete: dev_log entry written and INDEX.md updated

## Output Format

For each issue:
1. File name and line (if applicable)
2. Severity: **Critical** / **Warning** / **Suggestion**
3. What the problem is
4. Recommended fix with short code example if helpful

End with an overall summary and a **GO** / **NEEDS WORK** verdict.
