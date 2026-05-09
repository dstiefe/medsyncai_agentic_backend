# Full Engine Findings

Date: 2026-04-04
Scope: Full `app/agents/clinical` engine review, including both:

- Q&A guideline path (`/clinical/qa`)
- Scenario evaluation path (`parse -> IVT -> EVT -> decision state -> output`)

## Executive Summary

The original audit of the Q&A pipeline was accurate, but incomplete. It correctly identified the strengths and remaining gaps in the `ask guideline` flow. However, the full clinical engine also contains a separate scenario evaluation pipeline that is much more deterministic and structurally different from the Q&A system.

That second pathway includes:

- LLM-based scenario parsing into structured variables
- a 4-part IVT orchestrator
- a deterministic EVT rule engine loaded from 24 JSON rules
- a 1034-line decision engine that merges IVT, EVT, overrides, and display state
- multiple scenario-focused REST endpoints
- Firebase-backed session persistence for evaluation/re-evaluation flows
- a separate `clinical_output_agent` with its own `SKILL.md` and reference files

The Q&A findings still stand. But they should not be generalized to the scenario engine without qualification.

## Pathways

### Q&A Path

High-level flow:

- `/clinical/qa`
- `IntentAgent`
- `RecommendationAgent + SupportiveTextAgent + KnowledgeGapAgent`
- `AssemblyAgent`

Strengths:

- hybrid retrieval
- scope gate
- verbatim recommendation assembly
- clarification logic
- citations and audit trail

Remaining gaps:

- no reranker
- no graph RAG
- no mandatory final guardrail pass
- legacy fallback can still reintroduce LLM summarization

### Scenario Path

High-level flow:

- `/clinical/scenarios`
- `NLPService.parse_scenario()`
- `IVTOrchestrator.evaluate()`
- `RuleEngine.evaluate()` and `RuleEngine.evaluate_evt_eligibility()`
- `DecisionEngine.compute_effective_state()`
- REST response and/or session persistence

Important distinction:

- this path is primarily deterministic after parsing
- it does not depend on the Q&A retrieval/ranking architecture
- the Q&A-specific risks like missing reranking and legacy summary fallback do not describe this path

## Validated Findings

### 1. Q&A findings from the original audit

Status: Confirmed accurate

The original 12 findings remain valid for the `ask guideline` path:

- 202 recommendations stored as discrete, ID-tagged chunks
- keyword/synonym retrieval
- semantic search
- scope gate
- verbatim recommendation assembly
- clarification logic
- citation/audit-trail support
- partial guardrails
- missing reranking
- missing graph traversal
- validation present but not enforced
- legacy fallback risk

### 2. Scenario pipeline exists as a distinct major engine path

Status: Confirmed

Evidence:

- the engine wrapper explicitly documents `NLPService -> IVTOrchestrator -> RuleEngine -> DecisionEngine`
- REST routes expose a full scenario API family

Relevant files:

- `app/agents/clinical/ais_clinical_engine/engine.py`
- `app/agents/clinical/ais_clinical_engine/routes.py`

### 3. IVT pipeline has 4 sub-agents

Status: Confirmed

Evidence:

`IVTOrchestrator` instantiates and uses:

- `Table8Agent`
- `Table4Agent`
- `IVTRecsAgent`
- `ClinicalChecklistAgent`

Relevant file:

- `app/agents/clinical/ais_clinical_engine/agents/ivt_orchestrator.py`

### 4. Table 8 contraindication engine is deterministic and substantial

Status: Confirmed

Evidence:

- `Table8Agent` defines a large static rule set and evaluates each rule against `ParsedVariables`
- it produces:
  - risk tier
  - absolute/relative/benefit-over-risk groupings
  - notes
  - checklist items
  - unassessed counts

Relevant file:

- `app/agents/clinical/ais_clinical_engine/agents/table8_agent.py`

### 5. Table 4 disabling-deficit assessment exists as its own deterministic agent

Status: Confirmed

Evidence:

- `Table4Agent.evaluate()` resolves disabling vs non-disabling using:
  - explicit scenario flags
  - NIHSS threshold
  - NIHSS item-level checks

Relevant file:

- `app/agents/clinical/ais_clinical_engine/agents/table4_agent.py`

### 6. IVT recommendation firing logic is its own pathway agent

Status: Confirmed

Evidence:

- `IVTRecsAgent.evaluate()` routes across:
  - standard-window IVT
  - non-disabling / DAPT logic
  - extended-window imaging-based pathways
  - additive recommendations

Relevant file:

- `app/agents/clinical/ais_clinical_engine/agents/ivt_recs_agent.py`

### 7. Clinical checklist generation is a distinct layer

Status: Confirmed

Evidence:

- `ClinicalChecklistAgent` evaluates structured checklist domains including:
  - EVT eligibility
  - imaging
  - blood pressure
  - medications
  - supportive care

Relevant file:

- `app/agents/clinical/ais_clinical_engine/agents/checklist_agent.py`

### 8. EVT rule engine is deterministic and loaded from 24 rules

Status: Confirmed

Evidence:

- `evt_rules.json` contains 24 rules
- `RuleEngine.load_from_dicts()` loads those rules into typed rule objects
- `RuleEngine.evaluate()` deterministically fires recommendations and notes
- `RuleEngine.evaluate_evt_eligibility()` adds a three-valued eligibility layer

Relevant files:

- `app/agents/clinical/ais_clinical_engine/data/evt_rules.json`
- `app/agents/clinical/ais_clinical_engine/services/rule_engine.py`

### 9. EVT engine includes a three-valued eligibility system

Status: Confirmed

Evidence:

- `evaluate_evt_eligibility()` classifies clauses as:
  - met
  - failed
  - unknown
- aggregate states become:
  - eligible
  - pending
  - excluded

This is an important architectural detail because it prevents premature positive recommendation display when required inputs are missing.

Relevant file:

- `app/agents/clinical/ais_clinical_engine/services/rule_engine.py`

### 10. Decision engine is a major deterministic merge layer

Status: Confirmed

Evidence:

- `decision_engine.py` is 1034 lines
- `compute_effective_state()` merges:
  - parsed variables
  - IVT result
  - EVT result
  - clinician overrides
- it computes:
  - effective IVT eligibility
  - disabling state
  - EVT status and reason
  - missing inputs
  - primary therapy
  - dual reperfusion
  - verdict
  - visible sections
  - headline / description
  - display text
  - COR/LOE extraction

Relevant file:

- `app/agents/clinical/ais_clinical_engine/services/decision_engine.py`

### 11. Frontend-facing clinical display logic has been moved into the backend

Status: Confirmed

Evidence:

- `DecisionEngine` computes display-facing strings and badges such as:
  - headline
  - description
  - EVT status text
  - IVT status text
  - IVT badge

This indicates the backend is acting as the clinical source of truth rather than leaving treatment-state logic in the frontend.

Relevant file:

- `app/agents/clinical/ais_clinical_engine/services/decision_engine.py`

### 12. Scenario endpoints extend well beyond `/clinical/qa`

Status: Confirmed

Additional major endpoints:

- `/clinical/scenarios`
- `/clinical/scenarios/parse`
- `/clinical/scenarios/re-evaluate`
- `/clinical/scenarios/what-if`
- `/clinical/recommendations`

Also present:

- `/clinical/health`

Relevant file:

- `app/agents/clinical/ais_clinical_engine/routes.py`

### 13. Session persistence via Firebase is built into the scenario workflow

Status: Confirmed

Evidence:

- `SessionManager` is imported and instantiated in the clinical routes
- `_save_clinical_context()` persists parsed variables, IVT/EVT results, decision state, overrides, and scenario text
- `_load_clinical_context()` supports re-evaluate / what-if flows
- `SessionManager` uses Firebase-backed async persistence methods

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py`
- `app/shared/session_state.py`

### 14. Clinical output agent is a separate component with its own skill bundle

Status: Confirmed

Evidence:

- `clinical_output_agent/engine.py` points to `SKILL.md`
- it loads three reference files:
  - `routine_format.md`
  - `edge_case_format.md`
  - `clinical_rules.md`
- it is also registered in the main app orchestrator

Nuance:

- this confirms it is a real component, not dead code
- however, the REST scenario endpoints in `ais_clinical_engine/routes.py` return structured scenario-evaluation results directly, so this output agent appears to be part of a separate orchestration/rendering path rather than the formatter used by `/clinical/scenarios` itself

Relevant files:

- `app/agents/clinical/clinical_output_agent/engine.py`
- `app/agents/clinical/clinical_output_agent/SKILL.md`
- `app/agents/clinical/clinical_output_agent/references/routine_format.md`
- `app/agents/clinical/clinical_output_agent/references/edge_case_format.md`
- `app/agents/clinical/clinical_output_agent/references/clinical_rules.md`
- `app/orchestrator/orchestrator.py`

### 15. The scenario pipeline does not share the Q&A legacy fallback risk

Status: Confirmed

Evidence:

- the scenario path does not contain the orchestrator-to-legacy fallback pattern used by `/clinical/qa`
- the specific risk identified in the Q&A audit is tied to `answer_question()` fallback and LLM summary generation, not to `IVTOrchestrator -> RuleEngine -> DecisionEngine`

Important nuance:

- scenario parsing still depends on the LLM parser
- but the core evaluation/decision path after parsing is deterministic

Relevant files:

- `app/agents/clinical/ais_clinical_engine/routes.py`
- `app/agents/clinical/ais_clinical_engine/engine.py`

### 16. Q&A gaps should not be over-applied to the scenario path

Status: Confirmed

Examples:

- missing reranking is a Q&A retrieval issue, not a scenario issue
- graph RAG is a Q&A knowledge-retrieval issue, not a scenario issue
- the legacy summarization fallback risk is a Q&A issue, not a scenario issue

## Status Matrix — Q&A Path

| Capability | Status | Notes |
|---|---|---|
| 202 recommendations stored as discrete, ID-tagged chunks | Done | Present in loader + rec store |
| Keyword + synonym search across recommendations | Done | Deterministic retrieval path exists |
| Citation tracking / rec IDs surfaced | Done | Included in response contract |
| Safety rules hardcoded into LLM prompt | Partial | Present, but mostly affects legacy/fallback or validation flows |
| Validation step | Partial | Exists, but only on `/qa/validate`, not enforced pre-response |
| Semantic / meaning-based search | Done | Embedding store and hybrid retrieval are active |
| Re-ranking of retrieved results | Missing | No reranker found |
| Scope gate / explicit refusal | Done | Two scope-gate checks exist |
| Verbatim recommendation text in responses | Done | New QA assembly returns recommendations verbatim |
| Clarification layer | Partial to strong | Multiple ambiguity handlers exist, but not yet formal clinical-axis divergence logic |
| Graph RAG | Missing | No graph traversal layer found |
| Guardrails / final safety validation layer | Partial | Some checks exist, but no always-on final gate |
| Legacy fallback risk | Present | Legacy `answer_question()` still reachable on orchestrator failure |

## Status Matrix — Scenario Path

| Capability | Status | Notes |
|---|---|---|
| Scenario parsing to structured variables | Done | `NLPService.parse_scenario()` feeds the pipeline |
| IVT orchestrator | Done | 4-agent IVT pipeline is active |
| Table 8 contraindication logic | Done | Deterministic rules + checklist + risk tiers |
| Table 4 disabling assessment | Done | Deterministic NIHSS/item-based assessment |
| IVT recommendation firing | Done | Dedicated pathway agent |
| Clinical checklist generation | Done | Domain-based checklist agent |
| EVT deterministic rule engine | Done | 24 rules loaded from JSON |
| EVT three-valued eligibility | Done | eligible / pending / excluded |
| Decision-state merge engine | Done | 1034-line deterministic merge layer |
| Backend-computed display state | Done | headline, description, badges, status text |
| Re-evaluate workflow | Done | Supported with overrides + persisted context |
| What-if workflow | Done | Full re-run with modified variables |
| Session persistence | Done | Firebase-backed via `SessionManager` |
| Legacy fallback summarization risk | Not applicable | This is a Q&A-path concern |
| Reranking requirement | Not applicable | Scenario path is not retrieval-ranked like Q&A |

## Bottom Line

The original Q&A audit was correct but only covered half the engine.

The full-engine picture is:

- Q&A path: already stronger than expected, but still needs reranking, always-on guardrails, and removal/hardening of the legacy fallback
- Scenario path: already a substantial deterministic clinical engine with separate IVT, EVT, decision-state, override, checklist, and session layers

So the right conclusion is not “the whole engine is missing these things.”
The right conclusion is:

1. The Q&A pathway still has the high-priority safety/architecture gaps previously identified.
2. The scenario pathway is much more mature and does not share those same retrieval-specific weaknesses.
3. Any future audit or roadmap should keep these two pathways separate, because they solve different problems and fail in different ways.
