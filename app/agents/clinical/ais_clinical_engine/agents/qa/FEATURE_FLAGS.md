# QA Hybrid LLM Feature Flags

The v2 Q&A pipeline is deterministic by default. Three optional LLM
stages can be turned on independently via environment variables.
All three default to **OFF** — flipping them on is additive and
never changes the deterministic path for users who leave them off.

Add these lines to your local `.env` (or export them before starting
uvicorn) to enable each stage:

```bash
# ── Claude Haiku front-door parser ─────────────────────────────────
# When on: LLM parses the user's question against a closed vocabulary
# built from data_dict + synonym_dict + topic_map + intent_catalog.
# The llm_schema_validator airlock rejects any response that names
# an intent, section, or slot outside the scaffolding. On any failure
# the pipeline silently falls through to deterministic_parser.
QA_LLM_PARSER_ENABLED=false

# ── Claude Sonnet back-door summarizer ─────────────────────────────
# When on: after the in-scope pipeline pulls verbatim guideline recs,
# the summarizer writes a 2–3 sentence plain-English reading aid
# that is prepended ABOVE the byte-exact source block. Never rewrites,
# replaces, or edits the verbatim recs.
QA_LLM_SUMMARIZER_ENABLED=false

# ── Claude Sonnet general-knowledge fallback ───────────────────────
# When on: if the parser classifies the question as OUT_OF_SCOPE AND
# the deterministic deny-list does not block it, Claude Sonnet answers
# from general clinical knowledge. The response is always wrapped
# with the mandatory banner and footer, and the structured `scope`
# field on the response is set to "out_of_guideline".
QA_LLM_FALLBACK_ENABLED=false
```

## Response `scope` field

Every Q&A response now includes a structural `scope` key the frontend
can read to decide how to render the answer:

| scope              | When it fires                                            |
| ------------------ | -------------------------------------------------------- |
| `in_guideline`     | Standard in-scope answer from the verbatim guideline     |
| `out_of_guideline` | Fallback answer (general knowledge, off-guideline)       |
| `denied`           | Deny-list blocked a patient-specific treatment decision  |
| `fenced`           | Review-flagged section — routable only under conditions  |

## Deny-list (always on)

`llm_deny_list.check_deny_list()` runs on every out-of-scope question
regardless of feature flags. It is pure Python (no LLM) and uses a
two-signal rule: a decision verb pattern AND a drug/procedure pattern
must both match before the question is blocked. This is the hard
safety gate that prevents the LLM fallback from ever answering
patient-specific treatment decisions.

## Audit trail

Every response has a `v2_llm` step in `auditTrail` with:

- `parser_used` — `"llm"` or `"deterministic"`
- `parser_fallthrough_reason` — populated when LLM parse was rejected
- `summarizer_used` — `true` if the plain-language summary fired
- `fallback_used` — `true` if the general-knowledge responder fired
- `deny_list_blocked` — `true` if the deny-list short-circuited OOS
- Latency and input/output token counts per LLM call

## Models

- Parser: `claude-haiku-4-5-20251001` (cheap, fast, closed-vocab)
- Summarizer: `claude-sonnet-4-5-20250929`
- Fallback: `claude-sonnet-4-5-20250929`

Models are resolved from `app/config.py` (`DEFAULT_MODELS` and
`DEFAULT_FAST_MODELS`) — override per-call by passing `model=` to
the module-level `parse_with_llm`, `summarize_recs`, or
`fallback_answer` entry points.
