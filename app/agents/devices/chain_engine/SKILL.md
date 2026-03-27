# Chain Engine

## Role
Self-contained sub-orchestrator for all device compatibility questions.
Uses a deterministic Python pipeline internally — the LLM classifies the query,
then Python handles all business logic and math.

## Internal Pipeline (executed in order)

1. **query_classifier** (LLM) — Classifies query_mode, response_framing, query_structure
2. **chain_builder** (LLM) — Orders devices into chain configurations
3. **compat_evaluator** (Python) — Checks OD→ID at every junction
4. **decision_logic** (Python) — Business rules: n-1 subsets, discovery, gentle correction
5. **chain_analyzer** (Python) — Rolls up pair results into chain pass/fail
6. **chain_summary** (Python/LLM) — Generates narrative explanation of results
7. **quality_check** (Python) — Validates all devices addressed, all junctions checked

## Return Contract
Returns structured data only — never formatted text:
```json
{
    "status": "complete" | "error" | "needs_clarification",
    "engine": "chain_engine",
    "result_type": "compatibility_check" | "stack_validation" | "device_discovery",
    "data": { ... },
    "classification": { "query_mode": "...", "framing": "...", "structure": "..." },
    "confidence": 0.95
}
```

## Decision Logic Rules
| Condition | Action |
|-----------|--------|
| All junctions pass | Return result as-is |
| Failed + multi_device + exploratory/discovery | Run n-1 subset analysis |
| Failed + two_device + positive framing | Flag for gentle correction |
| Failed + two_device + neutral | Return failure with reason |
| Discovery mode | Search category for all compatible devices |

## Key Principle
If you can write the decision as an if/then with clear conditions, it's Python.
LLMs handle ambiguity: understanding what the user means, classifying tone, generating language.
Python handles determinism: math, combinatorics, business rules, quality checks.
