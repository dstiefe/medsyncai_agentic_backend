# Ask Guideline Findings

Date: 2026-04-04
Area reviewed: `app/agents/clinical/ais_clinical_engine` and `app/agents/clinical/ais_clinical_engine/agents/qa`

## Executive Summary

The current `ask guideline` implementation is already much closer to the proposed AIS Clinical Engine accuracy-upgrade plan than it first appears.

The strongest implemented pieces are:

- 202 discrete recommendation records stored by ID
- hybrid retrieval using deterministic scoring plus semantic embeddings
- explicit scope-gate refusal behavior
- verbatim recommendation response assembly
- clarification / disambiguation behavior
- citation and audit-trail support

The biggest gaps are:

- no true re-ranking stage after retrieval
- no graph/relationship traversal layer
- no mandatory final guardrail validation pass before every answer is shown
- legacy fallback can still reintroduce LLM summarization behavior

## Files Reviewed

- `app/agents/clinical/ais_clinical_engine/engine.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`
- `app/agents/clinical/ais_clinical_engine/data/loader.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/orchestrator.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/intent_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/embedding_store.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/schemas.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/supportive_text_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/knowledge_gap_agent.py`
- `app/agents/clinical/ais_clinical_engine/services/qa_service.py`
- `app/agents/clinical/ais_clinical_engine/services/nlp_service.py`

### Files added by claude audit

- `app/agents/clinical/ais_clinical_engine/agents/ivt_orchestrator.py`
- `app/agents/clinical/ais_clinical_engine/agents/ivt_recs_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/table4_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/table8_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/checklist_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/section_index.py`
- `app/agents/clinical/ais_clinical_engine/models/clinical.py`
- `app/agents/clinical/ais_clinical_engine/models/rules.py`
- `app/agents/clinical/ais_clinical_engine/models/table4.py`
- `app/agents/clinical/ais_clinical_engine/models/table8.py`
- `app/agents/clinical/ais_clinical_engine/models/checklist.py`
- `app/agents/clinical/ais_clinical_engine/services/rule_engine.py`
- `app/agents/clinical/ais_clinical_engine/services/decision_engine.py`
- `app/agents/clinical/ais_clinical_engine/data/evt_rules.json`
- `app/agents/clinical/ais_clinical_engine/data/ivt_rules.json`
- `app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json`
- `app/agents/clinical/ais_clinical_engine/data/checklist_templates.json`
- `app/agents/clinical/clinical_output_agent/engine.py`
- `app/agents/clinical/clinical_output_agent/SKILL.md`
- `app/agents/clinical/clinical_output_agent/references/clinical_rules.md`
- `app/agents/clinical/clinical_output_agent/references/routine_format.md`
- `app/agents/clinical/clinical_output_agent/references/edge_case_format.md`

## Findings

### 1. 202 recommendations stored as discrete, ID-tagged chunks

Status: Done

Evidence:

- `load_recommendations()` returns all 202 recommendations from `recommendations.json`
- `load_recommendations_by_id()` builds the by-ID map
- verified count in local data file is 202

Relevant files:

- `app/agents/clinical/ais_clinical_engine/data/loader.py`
- `app/agents/clinical/ais_clinical_engine/data/recommendations.json`

### 2. Keyword + synonym search across recommendations

Status: Done

Evidence:

- `IntentAgent` extracts search terms, section refs, topic sections, numeric context, and clinical variables
- `RecommendationAgent._deterministic_search()` runs scoring over all recommendations using the existing keyword/topic logic

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/intent_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_agent.py`
- `app/agents/clinical/ais_clinical_engine/services/qa_service.py`

### 3. Semantic search

Status: Done

Evidence:

- `EmbeddingStore` supports offline embeddings for all 202 recommendations
- startup path loads precomputed embeddings if present
- `RecommendationAgent` runs semantic search and merges it with deterministic retrieval
- local embedding artifact exists: `recommendation_embeddings.npz`

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/embedding_store.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_agent.py`
- `app/agents/clinical/ais_clinical_engine/engine.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`

### 4. Re-ranking

Status: Missing

Evidence:

- no cross-encoder, reranker, or second-pass relevance scorer found
- current path retrieves, merges, boosts overlap by a fixed rule, then sorts by score

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_agent.py`

### 5. Clarification layer / retrieval-triggered disambiguation

Status: Partial to strong

Evidence:

- hardcoded clarification rules for known ambiguity patterns such as M2 and disabling vs non-disabling IVT questions
- dynamic vague-question handling based on content breadth
- generic same-section ambiguity detection when close recommendations in one section have different COR values
- cross-section ambiguity detection when multiple sections compete with similar scores

What is still missing compared with the proposed plan:

- it does not yet appear to compare retrieved recommendations explicitly along a formal set of clinical axes like time window, modality, or population
- current logic is heuristic and score-pattern based, not a structured clinical divergence model

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/schemas.py`

### 6. Scope gate / explicit refusal when answer is not in the document

Status: Done

Evidence:

- topic-coverage check rejects questions when the retrieved content does not actually cover the asked topic
- score-threshold scope gate rejects weak retrieval when there is no supporting content
- refusal language explicitly says the AIS guideline does not specifically address the question

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py`

### 7. Verbatim recommendation text in responses

Status: Done in the new QA path

Evidence:

- recommendation response assembly builds blocks with recommendation ID, section, COR, LOE, and quoted recommendation text
- comments and schema explicitly state recommendation text is verbatim and never modified
- recommendation questions use deterministic summary generation rather than asking the LLM to rewrite the recommendation text

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/qa/schemas.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`

### 8. Citation tracking / traceability

Status: Done

Evidence:

- citations, related sections, clarification options, and audit trail are part of the response contract
- `/clinical/qa` returns these fields from the orchestrator path

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/schemas.py`
- `app/agents/clinical/ais_clinical_engine/engine.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`

### 9. Guardrails / final safety validation before output reaches clinician

Status: Partial

What exists:

- numeric alerts for platelet count and INR in recommendation assembly
- optional validation endpoint `/clinical/qa/validate`
- deterministic verbatim verification helper
- LLM-based validation helper for flagged responses
- safety rules embedded in the summarization prompt

What is missing:

- no mandatory pre-response guardrail pass on every `/clinical/qa` answer
- no comprehensive always-on check set for contradiction detection, confidence escalation, black-box/high-risk handling, or contraindication cross-reference before response delivery

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`
- `app/agents/clinical/ais_clinical_engine/services/qa_service.py`
- `app/agents/clinical/ais_clinical_engine/services/nlp_service.py`

### 10. Graph RAG / relationship traversal across connected recommendations

Status: Missing

Evidence:

- no graph store, node/edge traversal layer, or recommendation relationship model found in the active QA pipeline
- current architecture remains intent -> retrieval agents -> assembly

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/orchestrator.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`

### 11. Validation step is present but not enforced

Status: Confirmed

Evidence:

- `/clinical/qa/validate` exists and runs only when specifically called
- it is described as validation when a clinician gives thumbs-down feedback
- it does not run automatically inside the main `/clinical/qa` flow

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py`

### 12. Legacy fallback risk

Status: Important risk

Evidence:

- both the chat engine path and the REST `/clinical/qa` path fall back to legacy `answer_question()` if the new orchestrator throws
- legacy `answer_question()` still calls `nlp_service.summarize_qa()` to generate an LLM summary

Impact:

- even though the new orchestrator is aligned with verbatim assembly, an exception can route traffic back into the older summarization-based pattern
- this is probably the single biggest remaining architecture risk for recommendation accuracy

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py`
- `app/agents/clinical/ais_clinical_engine/engine.py`
- `app/agents/clinical/ais_clinical_engine/services/qa_service.py`

## Findings added by claude audit

> The original report reviewed only the Q&A pipeline path. The engine has a second major pathway — full scenario evaluation — plus several supporting components not covered above.

### 13. (claude) Full scenario evaluation pipeline exists alongside Q&A

Status: Not reviewed in original report — fully implemented

Evidence:

- `routes.py` defines two parallel pathways: scenario evaluation (`POST /clinical/scenarios`) and guideline Q&A (`POST /clinical/qa`)
- scenario pipeline: parse text → IVT assessment (Table 8 → Table 4 → IVT recommendations) → EVT rule evaluation (24 rules) → decision state computation → output formatting
- this is the pathway for "65yo, NIHSS 18, M1 occlusion, LKW 2h" type queries — not the Q&A path

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py` (lines 9-16, endpoint definitions)
- `app/agents/clinical/ais_clinical_engine/engine.py` (query classification: scenario vs guideline_qa vs out_of_scope)

### 14. (claude) IVT pipeline with 4 sub-agents + orchestrator

Status: Not reviewed in original report — fully implemented

Evidence:

- `table8_agent.py` (543 lines): evaluates 40+ contraindication rules (10 absolute, 15+ relative, benefit-over-risk) from `ivt_rules.json`
- `table4_agent.py` (99 lines): assesses disabling deficit per BATHE criteria (Bathing, Ambulating, Toileting, Hygiene, Eating)
- `ivt_recs_agent.py` (310 lines): fires IVT recommendations based on Table 8 risk tier + Table 4 disabling status, outputs COR/LOE
- `checklist_agent.py` (467 lines): generates 5-domain clinical checklists (EVT readiness, imaging, BP management, medications, supportive care)
- `ivt_orchestrator.py` (131 lines): orchestrates all IVT steps sequentially

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/ivt_orchestrator.py`
- `app/agents/clinical/ais_clinical_engine/agents/table8_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/table4_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/ivt_recs_agent.py`
- `app/agents/clinical/ais_clinical_engine/agents/checklist_agent.py`
- `app/agents/clinical/ais_clinical_engine/data/ivt_rules.json`

### 15. (claude) Deterministic EVT rule engine (24 rules, no LLM)

Status: Not reviewed in original report — fully implemented

Evidence:

- `rule_engine.py` (667 lines): evaluates 24 EVT rules from `evt_rules.json` using condition-action pairs (AND/OR boolean logic)
- pure Python, no LLM calls — same input always produces same output
- covers: anterior LVO 0-6h, anterior LVO 6-24h, large core (ASPECTS 3-5), posterior circulation, pediatric, wake-up stroke, post-IVT re-occlusion, EVT technique recommendations
- rule structure: `{id, condition: {logic, clauses}, actions: [{type: "fire", recIds: [...]}]}`

Relevant files:

- `app/agents/clinical/ais_clinical_engine/services/rule_engine.py`
- `app/agents/clinical/ais_clinical_engine/data/evt_rules.json`

### 16. (claude) Decision state computation engine (1034 lines, fully deterministic)

Status: Not reviewed in original report — fully implemented

Evidence:

- `decision_engine.py` (1034 lines) merges IVT and EVT results into a final `ClinicalDecisionState`
- computes: effective_ivt_eligibility, effective_disabling status, evt_status, primary_therapy (IVT/EVT/dual/supportive_only)
- generates BP targets per pathway combination, headline, description, evt_status_text, ivt_status_text
- extracts COR/LOE only when a determination is reached
- fully deterministic — no LLM calls

Relevant files:

- `app/agents/clinical/ais_clinical_engine/services/decision_engine.py`
- `app/agents/clinical/ais_clinical_engine/models/clinical.py` (ClinicalDecisionState model)

### 17. (claude) Clinical output agent (separate agent following three-layer rule)

Status: Not reviewed in original report — fully implemented

Evidence:

- `clinical_output_agent/` is a separate agent that formats eligibility assessments into guideline-referenced clinical documents
- follows three-layer rule correctly:
  - `SKILL.md` — process only (formatting steps, opening statement, section structure, citation requirements, complexity branching)
  - `references/clinical_rules.md` — domain knowledge (citation format, content rules, BP target formatting, vessel precision, determination language)
  - `references/routine_format.md` — format for straightforward cases (4-6 sentences, state COR/LOE and stop)
  - `references/edge_case_format.md` — format for uncertain cases (eligibility table + detailed narrative for UNCERTAIN pathways only)
- uses LLM for narrative synthesis only — all eligibility determinations are computed deterministically upstream

Relevant files:

- `app/agents/clinical/clinical_output_agent/engine.py`
- `app/agents/clinical/clinical_output_agent/SKILL.md`
- `app/agents/clinical/clinical_output_agent/references/clinical_rules.md`
- `app/agents/clinical/clinical_output_agent/references/routine_format.md`
- `app/agents/clinical/clinical_output_agent/references/edge_case_format.md`

### 18. (claude) Pydantic models directory (5 model files, comprehensive type safety)

Status: Not reviewed in original report — fully implemented

Evidence:

- `models/clinical.py` — ParsedVariables (70+ clinical fields), ClinicalDecisionState, FiredRecommendation, ClinicalOverrides, QAValidationRequest/Response
- `models/rules.py` — Rule, RuleClause, RuleCondition, RuleAction (EVT rule structure with AND/OR logic)
- `models/table4.py` — Table4Result (isDisabling, rationale, recommendation)
- `models/table8.py` — Table8Rule, Table8Item, Table8Result (riskTier, contraindication lists)
- `models/checklist.py` — Checklist models for 5 clinical domains

Relevant files:

- `app/agents/clinical/ais_clinical_engine/models/` (all 5 files)

### 19. (claude) Additional REST endpoints not reviewed (5 endpoints beyond /qa)

Status: Not reviewed in original report — fully implemented

Evidence:

- `POST /clinical/scenarios` — full evaluation (parse → IVT → EVT → DecisionState)
- `POST /clinical/scenarios/parse` — parse scenario text only (returns ParsedVariables)
- `POST /clinical/scenarios/re-evaluate` — apply clinician overrides, recompute DecisionState from stored context
- `POST /clinical/scenarios/what-if` — modify parsed variables and re-run full pipeline
- `POST /clinical/recommendations` — browse/filter guideline recommendations by category or section
- `GET /clinical/health` — engine health check (open, no auth)

Impact:

- these endpoints support clinician workflows (override, what-if analysis) and the re-evaluate feature depends on session persistence via Firebase
- the original report's "legacy fallback risk" finding applies only to the `/clinical/qa` path; the scenario path has its own error handling

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py` (lines 1-17 for endpoint list)

### 20. (claude) Session persistence via Firebase

Status: Not reviewed in original report — fully implemented

Evidence:

- `routes.py` uses `SessionManager` from `app.shared.session_state` to persist clinical context to Firebase
- stores: parsed variables, IVT/EVT results, decision state, clinician overrides, conversation history, timestamps
- supports audit trail and re-evaluate/what-if workflows (re-evaluate loads stored context, applies overrides, recomputes)
- graceful degradation: if Firebase is unavailable, clinical results are still returned (persistence silently skipped)

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py` (lines 124-178)
- `app/shared/session_state.py`

### 21. (claude) QA pipeline runs search agents in parallel

Status: Minor detail not noted in original report

Evidence:

- QA orchestrator runs `RecommendationAgent`, `SupportiveTextAgent`, and `KnowledgeGapAgent` concurrently (not sequentially)
- this is an efficiency optimization — all three agents are independent and their results are merged in AssemblyAgent

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/orchestrator.py`

### 22. (claude) section_index.py not included in files reviewed

Status: Minor omission

Evidence:

- `agents/qa/section_index.py` builds a section concept index for mapping topics to guideline sections
- used by the intent agent's `TOPIC_SECTION_MAP` to resolve topic references to section numbers

Relevant files:

- `app/agents/clinical/ais_clinical_engine/agents/qa/section_index.py`

### 23. (claude) Additional data files not reviewed (4 JSON files)

Status: Not reviewed in original report — all present

Evidence:

- `evt_rules.json` — 24 EVT eligibility and technique rules (consumed by rule_engine.py)
- `ivt_rules.json` — Table 8 contraindications (40+ rules) + Table 4 disabling deficit thresholds (consumed by table8_agent.py and table4_agent.py)
- `guideline_knowledge.json` — per-section RSS (recommendation-specific supportive text), synopses, knowledge gaps, future research notes (consumed by supportive_text_agent.py and knowledge_gap_agent.py)
- `checklist_templates.json` — 5 clinical checklist domain templates (consumed by checklist_agent.py)

Relevant files:

- `app/agents/clinical/ais_clinical_engine/data/` (all 4 JSON files)

## Status Matrix

### Q&A Pipeline (original findings)

| Capability | Status | Notes |
|---|---|---|
| 202 recommendations stored as discrete, ID-tagged chunks | Done | Present in loader + recommendations store |
| Keyword + synonym search across recommendations | Done | Deterministic retrieval path exists |
| Citation tracking / rec IDs surfaced | Done | Included in response contract |
| Safety rules hardcoded into LLM prompt | Partial | Present, but mainly impacts legacy/fallback or validation flows |
| Validation step | Partial | Exists, but only on `/qa/validate`, not enforced pre-response |
| Semantic / meaning-based search | Done | Embedding store and hybrid retrieval are active |
| Re-ranking of retrieved results | Missing | No reranker found |
| Scope gate / explicit refusal | Done | Two scope-gate checks exist |
| Verbatim recommendation text in responses | Done | New QA assembly returns recommendations verbatim |
| Clarification layer | Partial to strong | Multiple ambiguity handlers exist, but not yet formal clinical-axis divergence logic |
| Graph RAG | Missing | No graph traversal layer found |
| Guardrails / final safety validation layer | Partial | Some checks exist, but no always-on final gate |

### Scenario Evaluation Pipeline (claude additions)

| Capability | Status | Notes |
|---|---|---|
| Scenario text → structured parsing (NLPService) | Done | Claude tool_use extracts 70+ fields into ParsedVariables |
| IVT contraindication evaluation (Table 8) | Done | 40+ rules (10 absolute, 15+ relative), fully deterministic |
| Disabling deficit assessment (Table 4) | Done | BATHE criteria, NIHSS item-level evaluation |
| IVT recommendation firing | Done | COR/LOE attached per recommendation, based on risk tier + disabling status |
| EVT rule engine (24 rules) | Done | Pure Python, condition-action pairs, no LLM |
| Decision state computation | Done | Merges IVT + EVT, computes eligibility, BP targets, headlines |
| Clinical output formatting agent | Done | Separate agent with SKILL.md + 3 reference files, follows three-layer rule |
| Clinician override / re-evaluate | Done | POST /scenarios/re-evaluate with Firebase session persistence |
| What-if analysis | Done | POST /scenarios/what-if modifies variables and re-runs pipeline |
| 5-domain clinical checklists | Done | EVT readiness, imaging, BP, medications, supportive care |
| Pydantic model validation | Done | 5 model files with comprehensive type safety |
| Session persistence (Firebase) | Done | Audit trail, conversation history, graceful degradation if unavailable |

## Bottom Line

The current `ask guideline` implementation has already completed more of the proposed roadmap than expected:

- semantic search is already built
- scope gate is already built
- verbatim recommendation assembly is already built
- clarification is already built in several forms

The main remaining work is not the foundation. It is tightening the last-mile safety architecture:

1. remove or harden the legacy fallback so it cannot reintroduce paraphrase drift
2. add true re-ranking
3. add an always-on final guardrail pass before response delivery
4. later, add graph-based relationship traversal for multi-hop questions

### (claude) Expanded bottom line

The original report scoped its review to the Q&A pipeline only (`/clinical/qa`). The engine is significantly larger than that review captured:

- a complete **scenario evaluation pipeline** (parse → IVT → EVT → decision state → output) exists with deterministic rule engines, 40+ contraindication rules, 24 EVT rules, and a 1034-line decision engine — all pure Python, no LLM
- a dedicated **clinical output agent** with SKILL.md and 3 reference files correctly follows the three-layer rule
- **clinician override and what-if endpoints** support iterative clinical workflows with Firebase session persistence
- **5-domain clinical checklists** are generated alongside eligibility assessments
- **comprehensive Pydantic models** (5 files) enforce type safety across the entire pipeline

The scenario pipeline is architecturally mature and does not share the Q&A pipeline's "legacy fallback risk" or "missing re-ranking" gaps. The Q&A gaps identified in the original report remain accurate and should still be prioritized.
