# v3 Scaffolding Usage Audit (2026-04-11)

Verifies that both the LLM parser and the LLM verifier consume the
same four scaffolding files the user asked about in the Q&A v3 design
discussion. Source rule (transcript msg #89):

  "The first LLM should always use the data dictionary, synonym
   dictionary, intent map and guideline map."

And (after sICH incident):

  "The first LLM and the validating LLM should use the same
   supporting resources."

## Scaffolding files on dev

| File | Purpose | Location |
|------|---------|----------|
| `synonym_dictionary.json`      | Canonical term_ids + surface-form synonyms + per-term sections list | `app/agents/clinical/ais_clinical_engine/agents/qa/references/` |
| `data_dictionary.json`         | Per-section field ontology (intervention, BP, NIHSS, age, etc.) + synonym_term_ids | same |
| `guideline_topic_map.json`     | Topic → section map with subtopic qualifiers | same |
| `intent_map.json`              | Concept expansions (36) + concept groups (31) + qualifier rules | same |
| `ais_guideline_section_map.json` | Section tree + routing_keywords (deterministic section validation) | same |

## Consumers

### query_parsing_agent.py — the LLM PARSER (Step 1)

Loads at init (`QAQueryParsingAgent.__init__`, line 326):

```
synonym_data   = _load_json(_SYNONYM_PATH)       # synonym_dictionary.json
data_dict_data = _load_json(_DATA_DICT_PATH)     # data_dictionary.json
topic_map_data = _load_json(_TOPIC_MAP_PATH)     # guideline_topic_map.json
intent_map_data = _load_json(_INTENT_MAP_PATH)   # intent_map.json
```

Injected into the system prompt via `_build_system_prompt` (line 243)
in this order:

1. Primacy directive ("consult all four before classifying")
2. Base JSON schema (`qa_query_parsing_schema.md`)
3. Topic map appendix — `_build_topic_map_appendix`
4. Synonym appendix — `_build_synonym_appendix`
5. Intent map appendix — `_build_intent_map_appendix`
6. Data dictionary appendix — `_build_data_dict_appendix`

**Status: PASS.** All four authoritative sources are loaded and
injected into the prompt. The primacy directive explicitly instructs
the LLM to consult each one before classifying.

`ais_guideline_section_map.json` is NOT consumed by the parser, which
is correct — the parser picks a topic (LLM classification), and
`SectionRouter` translates topic → section using `topic_map` +
`section_map` downstream. Loading `section_map` into the parser
prompt would not change routing behaviour.

### topic_verification_agent.py — the LLM VERIFIER (Step 2)

Imports the parser's path constants directly (line 35–39):

```
from .query_parsing_agent import (
    _build_topic_map_appendix,
    _build_synonym_appendix,
    _build_intent_map_appendix,
    _build_data_dict_appendix,
    _SYNONYM_PATH,
    _DATA_DICT_PATH,
    _TOPIC_MAP_PATH as _QPA_TOPIC_MAP_PATH,
    _INTENT_MAP_PATH,
)
```

Builds the same four appendices (line 83–95) and injects them into
its own system prompt used at verify-call time (line 172).

**Status: PASS.** Parser and verifier read from the same on-disk files
via shared path constants, and use the same `_build_*_appendix`
helpers, so any future edit to one appendix automatically propagates
to the other. This closes the regression that allowed the sICH case
to slip: verifier was rejecting a clarification reply as
`not_coherent` because it was not seeing the same merged context the
parser saw.

### rec_selection_agent.py / rss_summary_agent.py / kg_summary_agent.py

These run later in the pipeline and take already-retrieved content.
They do NOT need the full scaffolding prompt. They consume:

- `synonym_dictionary.json` + `intent_map.json` indirectly via
  `qa_v3_filter.load_anchor_vocab()` (as of commit 9cc9d78) for the
  anchor-survival pre-filter.

This is correct and expected.

### SectionRouter

Loads `ais_guideline_section_map.json`, `guideline_topic_map.json`,
and `data_dictionary.json` at init (`__init__`, line 259) for
deterministic topic → section resolution and section-id validation.
`synonym_dictionary.json` is used indirectly via the private
`_build_synonym_groups` helper.

## Audit result

Both LLM consumers (parser at Step 1 and verifier at Step 2) load
and inject all four required authoritative sources, via shared
imports so they remain in lockstep. No gaps relative to the rule.

No code changes required. This audit is durable documentation —
re-run when `_build_*_appendix` helpers or their call sites change.
