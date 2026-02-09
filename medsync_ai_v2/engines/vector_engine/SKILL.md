# Vector Engine

## Role
Searches IFU/510(k) documents stored in OpenAI Vector Stores for information
relevant to the user's query. Handles knowledge_base, documentation, and
device_definition intents.

## Supported Query Types
- **manufacturer_lookup** — "Who makes the AXS Catalyst 5?"
- **device_definition** — "What is a microcatheter?"
- **contraindications** — "What are contraindications for Solitaire?"
- **indications** — "What are the indications for Trevo NXT?"
- **guideline_lookup** — "What does the IFU say about deployment technique?"
- **trial_summary** — "What clinical trials support the Solitaire?"
- **safety_outcomes** — "What safety data exists for the AXS Catalyst?"
- **imaging_criteria** — "What imaging is required before using Trevo?"
- **patient_eligibility** — "Who is eligible for treatment with Solitaire?"
- **source_lookup** — "Show me the IFU for Headway 21"

## Pipeline
1. Extract device variant IDs from `devices` dict (from equipment_extraction)
2. Build metadata filter: `{"type": "containsany", "key": "device_variant_id", "value": [ids]}`
3. Semantic search via OpenAI Vector Stores API (`POST /vector_stores/{id}/search`)
4. Score-threshold filtering (MIN_SCORE = 0.4) — drops noisy low-relevance chunks
5. Sort by score descending, cap at MAX_CHUNKS (10)
6. Return structured chunks to vector_output_agent

## Input Contract
```json
{
  "normalized_query": "Who makes the AXS Catalyst 5?",
  "devices": {"AXS Catalyst 5": {"ids": ["42", "43"], "conical_category": "L2"}},
  "categories": [],
  "classification": {"primary_intent": "knowledge_base"}
}
```

## Output Contract
```json
{
  "status": "complete",
  "engine": "vector_engine",
  "result_type": "vector_search",
  "data": {
    "query": "...",
    "chunks": [{"text": "...", "file_id": "...", "score": 0.92, "attributes": {}}],
    "device_context": {"AXS Catalyst 5": {"ids": ["42", "43"]}},
    "chunk_count": 5,
    "top_score": 0.92
  },
  "classification": {},
  "confidence": 0.9
}
```

## No-Device-ID Fallback
When no device IDs are found (e.g., "What is a microcatheter?"), the engine
searches without a metadata filter — pure semantic match against the full
document corpus.

## Vector Store
- **Provider**: OpenAI Vector Stores API (Assistants v2)
- **Store ID**: Configured via `VECTOR_STORE_ID` env var
- **Documents**: IFU and 510(k) PDFs, chunked at 1200 tokens with 200-token overlap
- **Metadata**: Each chunk tagged with `device_variant_id` for scoped search
