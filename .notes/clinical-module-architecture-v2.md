# Clinical Module Architecture (v2)

Complete technical architecture of `app/agents/clinical/` — both the
Scenario Evaluation pipeline and the Guideline Q&A pipeline.

Last updated: 2026-04-04

---

## 1. High-Level Flow

```
User Query
    |
    v
Orchestrator (app/orchestrator/)
    |
    v
Domain = "clinical"?
    |-- YES --> clinical_redirect SSE --> Frontend calls /clinical/* REST endpoints
    '-- NO  --> Other engine paths
```

The orchestrator does **not** process clinical queries itself. It detects
the clinical domain and sends a redirect event. The frontend then calls
REST endpoints in `routes.py`, which run the full pipeline.

### Query Classification

`engine.py` classifies every query into one of two pipelines using regex:

| Pattern Set | Matches | Route |
|-------------|---------|-------|
| `_CLINICAL_PARAMS` | NIHSS, ASPECTS, LKW, vessel, age, BP patterns | **Scenario** pipeline |
| `_AIS_KEYWORDS` | guideline, IVT, EVT, contraindication, table 4/8, alteplase, tenecteplase | **Guideline Q&A** pipeline |
| Neither | — | Out-of-scope response |

```
          +-- has clinical params? --> _run_scenario()
Query --> |
          +-- has AIS keywords?   --> _run_guideline_qa()
          |
          '-- neither             --> out_of_scope
```

---

## 2. Scenario Pipeline

**Entry:** `engine.py._run_scenario()`

Evaluates a patient case against the 2026 AHA/ASA AIS guideline.
Returns structured clinical decision support with COR/LOE citations.

### 2.1 Phase 1: Parsing

**Service:** `services/nlp_service.py` — `NLPService.parse_scenario()`
**Model:** Claude Sonnet via `tool_use` (structured JSON extraction)
**Output:** `ParsedVariables` — Pydantic model, 60+ clinical fields

Key field categories:

| Category | Fields |
|----------|--------|
| **Demographics** | age, sex, isAdult (derived) |
| **Timing** | timeHours, lastKnownWellHours, lkwClockTime, wakeUp, timeWindow, effectiveTimeHours |
| **Severity** | nihss (total), nihssItems (11 sub-scores), nonDisabling |
| **Imaging** | vessel, side, m2Dominant, isLVO, isM2, isBasilar, aspects, pcAspects, dwiFlair, penumbra, hemorrhage, extensiveHypodensity, cmbBurden |
| **Vitals** | sbp, dbp |
| **Labs** | platelets, inr, aptt, pt, glucose |
| **Medications** | onAntiplatelet, onAnticoagulant, recentDOAC, ivtGiven |
| **History** | priorICH, recentStroke3mo, recentTBI, recentNeurosurgery, sickleCell, pregnancy, activeMalignancy, cervicalDissection, aria, etc. |

Post-processing (in `routes.py`):
- Clock-time LKW → hours-ago conversion
- Sex normalization ("M" → "male")
- Side extraction from vessel names ("left M1" → vessel="M1", side="left")
- "No LVO" detection via regex fallback

### 2.2 Phase 2: Deterministic Evaluation

```
ParsedVariables
    |
    +---> IVT Orchestrator (agents/ivt_orchestrator.py)
    |       |-- Table8Agent    --> contraindication tiers
    |       |-- ChecklistAgent --> multi-domain clinical workflows
    |       |-- Table4Agent    --> disabling deficit assessment
    |       '-- IVTRecsAgent   --> IVT pathway routing + fired recs
    |
    +---> RuleEngine (services/rule_engine.py)
    |       '--> EVT eligibility (three-valued logic)
    |
    '---> DecisionEngine (services/decision_engine.py)
            '--> synthesizes IVT + EVT --> ClinicalDecisionState
```

#### Table8Agent (`agents/table8_agent.py`)

Evaluates 37 contraindication rules across 3 tiers:

| Tier | Count | Examples |
|------|-------|---------|
| **Absolute** | 10 | hemorrhage, extensive hypodensity, recent neurosurgery <14d, ARIA, coagulopathy (platelets <100k, INR >1.7, aPTT >40, PT >15) |
| **Relative** | 18 | recent DOAC, prior ICH, pregnancy, active malignancy, recent stroke <3mo |
| **Benefit Over Risk** | 9 | cervical dissection, unruptured aneurysm, Moya-Moya, remote MI |

**Three-valued evaluation** for each rule:
- `confirmed_present` — trigger fires, contraindication active
- `confirmed_absent` — trigger doesn't fire AND all required variables present
- `unassessed` — at least one required variable is None

Supports nested AND/OR logic with operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not_in`, `is_null`, `is_not_null`.

Risk tier priority: absolute > relative > benefit_over_risk > no_contraindications.

**Output:** `Table8Result` — riskTier, checklist (all 37 items), notes, unassessedCount.

#### Table4Agent (`agents/table4_agent.py`)

Determines if deficits are disabling using NIHSS thresholds and item analysis.
Implements BATHE criteria (Bathing, Ambulating, Toileting, Hygiene, Eating).

**Decision logic:**
```
1. Explicit designation?  --> use it directly
2. NIHSS >= 6?           --> disabling
3. NIHSS 0-5 + items?    --> check 7 motor/language/vision items for threshold >= 2
4. No items available?    --> needs_assessment
```

**Output:** `Table4Result` — isDisabling, rationale, disablingDeficits list, recommendation.

#### IVTRecsAgent (`agents/ivt_recs_agent.py`)

Routes patients through IVT decision pathways and fires guideline recommendations:

| Path | Condition | Key Recs |
|------|-----------|----------|
| **A: Standard IVT** | 0-4.5h + disabling + adult | 4.6.1-001 thru 005, 010; 4.6.2-001/002 (tenecteplase) |
| **A (Pediatric)** | 0-4.5h + disabling + age <18 | 4.6.1-014 only (COR 2b, LOE C-LD) |
| **B: Non-disabling** | 0-4.5h + non-disabling | 4.6.1-008 (COR 3: No Benefit) + DAPT recs |
| **C: Extended (DWI-FLAIR)** | wake-up/unknown onset + DWI-FLAIR mismatch | 4.6.3-001 (COR 2a, LOE B-R) |
| **D: Extended (Penumbra)** | 4.5-9h or wake-up + salvageable penumbra | 4.6.3-002 (COR 2a, LOE B-R) |
| **E: Extended (EVT unavail)** | 4.5-24h + LVO + penumbra + EVT unavailable | 4.6.3-003 (COR 2a, LOE B-R) |

Additive recs fired independently: imaging (Section 3.2), antiplatelet (4.6.1-009), sickle cell (4.6.5-001), BP management (4.3-005/007/008), CMB burden (4.6.1-011/012/013), patient discussion (4.6.1-004).

**Output:** `List[FiredRecommendation]` — deduplicated, with rec ID, section, COR, LOE, text, category.

#### ChecklistAgent (`agents/checklist_agent.py`)

Assesses clinical data completeness across 5 domains:

| Domain | Items | Examples |
|--------|-------|---------|
| EVT eligibility | 7 | LVO identified, vessel, time window, ASPECTS, mRS, age, NIHSS |
| Imaging | 6 | hemorrhage excluded, vascular imaging, ASPECTS, perfusion, DWI-FLAIR |
| BP management | 3 | SBP, DBP, IVT threshold assessed |
| Medications | 4 | anticoagulant, antiplatelet, coagulation labs, glucose |
| Supportive care | 4 | airway, mRS, NIHSS, sickle cell screening |

**Output:** `List[ChecklistSummary]` — per domain: totalItems, assessedItems, unassessedItems, reminderText.

#### RuleEngine (`services/rule_engine.py`)

Evaluates EVT eligibility using 24 condition-action rules from `evt_rules.json`.

**Three-valued logic** per clause: met / failed / unknown.
Rule states: satisfied (all met), possible (met + unknown), excluded (any failed).

Covers:
- Standard window EVT (0-6h): anterior LVO, NIHSS >= 6, pre-stroke mRS, ASPECTS thresholds
- Extended window EVT (6-24h): stricter ASPECTS by time bucket
- Posterior circulation EVT: basilar, separate criteria
- Large core exclusion: ASPECTS <3

**Output:** `{recommendations, eligibility, notes, narrowingSummary}` with per-rule breakdown.

#### DecisionEngine (`services/decision_engine.py`)

Synthesizes IVT + EVT results + clinician overrides into `ClinicalDecisionState`.

**Clinician overrides** (`ClinicalOverrides`):
- `table8_overrides`: per-rule status changes
- `none_absolute/relative/benefit_over_risk`: bulk overrides for unassessed items
- `table4_override`: force disabling/non-disabling
- `lkw_within_24h`, `m2_is_dominant`, `evt_available`, `wake_up_within_window`: gate overrides
- `imaging_dwi_flair`, `imaging_penumbra`: imaging gate overrides

**Key computations:**
- Effective IVT eligibility: eligible / contraindicated / caution / pending / not_recommended
- BP status: at-goal check against 185/110 threshold
- Extended window detection: time >4.5h OR wake-up OR unknown onset
- EVT status: recommended / pending / not_applicable (with reason)
- Primary therapy: IVT / EVT / DUAL / NONE
- COR/LOE extraction from fired recs (with extended window and pediatric overrides)
- Headline generation (40+ permutations)
- Visible UI sections based on clinical state

**Output:** `ClinicalDecisionState` — headline, badges, status text, COR/LOE, missing vars, visibility flags.

### 2.3 Phase 3: Persistence & Response

- Full result serialized as JSON
- Session persisted to Firebase for audit trail + re-evaluation + what-if
- Re-evaluate endpoint: applies clinician overrides WITHOUT re-running IVT/EVT pipelines
- What-if endpoint: modifies variables AND re-runs full pipeline

---

## 3. Guideline Q&A Pipeline

**Entry:** `engine.py._run_guideline_qa()` → `QAOrchestrator.answer()`

Multi-agent pipeline that answers knowledge questions about the AIS guideline.
Returns verbatim recommendation text — never paraphrased, never summarized.

### 3.1 Pipeline Architecture

```
User Question
    |
    v
IntentAgent (sync, deterministic)
    |
    v
+-------+-------+-------+
|       |       |       |   asyncio.gather (parallel)
v       v       v       |
Rec   RSS     KG        |
Agent Agent  Agent       |
+-------+-------+-------+
    |
    v
AssemblyAgent (async)
    |-- scope gate
    |-- clarification detection (4 layers)
    |-- content breadth analysis
    |-- ambiguity detection (2 layers)
    |-- score threshold gate
    '-- verbatim response assembly
    |
    v
AssemblyResult
```

### 3.2 IntentAgent (`agents/qa/intent_agent.py`)

**Fully deterministic — no LLM calls.**

Classifies the question and extracts search parameters:

| Step | Method | Output |
|------|--------|--------|
| 1 | `extract_search_terms()` | keyword list (expanded via CONCEPT_SYNONYMS) |
| 2 | `extract_section_references()` | explicit "Section X.X" citations |
| 3 | `extract_topic_sections()` | sections inferred from TOPIC_SECTION_MAP (~400 entries) |
| 4 | `extract_numeric_context()` | platelets, INR, glucose thresholds |
| 5 | `extract_clinical_variables()` | nihss, age, vessel, mRS, aspects, etc. |
| 6 | `classify_question_type()` | "recommendation" / "evidence" / "knowledge_gap" |

**Special detection:**
- **Contraindication questions**: explicit ("table 8", "contraindication") or implicit (IVT context + Table 8 condition). ~45 Table 8 condition terms.
- **General questions**: "in general", "what is the", etc. — skips patient context merge.
- **Evidence questions**: "study", "trial", "data", "why", "evidence".

**Concept index fallback** (`section_index.py`): When TOPIC_SECTION_MAP has no match, auto-generated reverse index of discriminating terms (appear in <= 3 sections) scores the question against all sections. Min score: 10, separation: 70% of best.

**Patient context merge**: For case-specific questions, merges clinical vars into search terms and builds a context summary string (e.g. "25y, M, NIHSS 8, MCA, 2.5h").

**Output:** `IntentResult` — question_type, search_terms, section_refs, topic_sections, numeric_context, clinical_vars, is_general_question, is_evidence_question, is_contraindication_question, contraindication_tier, context_summary.

### 3.3 RecommendationAgent (`agents/qa/recommendation_agent.py`)

**Dual retrieval: deterministic keyword scoring + semantic vector search.**

#### Path 1: Deterministic Search

Scores all 202 recommendations via `qa_service.score_recommendation()`:

| Factor | Points |
|--------|--------|
| Text field match (per term) | +3 |
| Metadata match (per term) | +1 |
| Density bonus (>= 4 text hits) | +2 per extra hit |
| Explicit section ref ("Section X.X") | +20 |
| Topic-inferred section | +15 |
| Rec number match | +10 |
| Discriminating phrase match | +5 each (capped +30) |
| Contradiction penalty | -8 to -12 |
| Off-topic suppression (when TOPIC_SECTION_MAP is specific) | score / 2 |

**Applicability gating**: For case-specific questions, checks each rec against EVT rule conditions and skips non-applicable recs.

#### Path 2: Semantic Search (`agents/qa/embedding_store.py`)

- Model: `all-MiniLM-L6-v2` (sentence-transformers, runs locally)
- Pre-computed embeddings for all 202 recs in `data/recommendation_embeddings.npz`
- Query-time: embed question, cosine similarity (L2-normalized dot product)
- Returns top-K with min similarity threshold 0.25
- Lazy-loaded and cached in memory after first use
- Graceful degradation if embeddings unavailable

#### Hybrid Merge

When both paths fire:
1. Index deterministic results by rec_id
2. For each semantic result:
   - If already in deterministic: keep max(score) + boost +5, source = "both"
   - Else: add as new result
3. Sort by score descending

**Output:** `RecommendationResult` — scored_recs list, search_method ("deterministic"/"semantic"/"hybrid").

### 3.4 SupportiveTextAgent (`agents/qa/supportive_text_agent.py`)

Searches `guideline_knowledge.json` for RSS (Recommendation-Specific Supportive Text) and synopsis entries.

- Max 5 results for recommendation questions, 7 for evidence questions
- Filters to type "rss" or "synopsis" only
- All deterministic — no LLM calls

**Output:** `SupportiveTextResult` — entries list, has_content bool.

### 3.5 KnowledgeGapAgent (`agents/qa/knowledge_gap_agent.py`)

Searches for knowledge gaps and future research content per section.

- For sections with no documented gaps (~61/62 sections): returns deterministic response
- Deterministic text: "No specific knowledge gaps are documented in the 2026 AHA/ASA AIS guideline for Section X."
- Falls back to keyword search when no target sections available
- All deterministic

**Output:** `KnowledgeGapResult` — entries list, has_gaps bool, deterministic_response.

### 3.6 AssemblyAgent (`agents/qa/assembly_agent.py`)

The most sophisticated component. Applies 9 sequential layers before assembling the response.

#### Layer 1: KG Deterministic Response
If question_type == "knowledge_gap" and no gaps documented: return pre-built response immediately.

#### Layer 2: Topic Coverage Scope Gate
`check_topic_coverage()` — checks ~40 out-of-scope markers (pediatric, ICH, TIA, secondary prevention, spasticity, sleep apnea, PFO, CVST, driving, employment, etc.).

If marker found in question but NOT in top-5 recs: return out_of_scope.

Response: "The 2026 AHA/ASA AIS Guideline does not specifically address this question. This may be covered in other guidelines, local institutional protocols, or prescribing information."

#### Layer 3: Hardcoded Clarification Rules
Two rules for known clinical ambiguities:

| Rule | Trigger | Options |
|------|---------|---------|
| **M2 occlusion** | question has "m2" + no "dominant"/"nondominant" in question + no m2Dominant in context + eligibility keyword | A) Dominant proximal (COR 2a, B-NR) / B) Non-dominant (COR 3: No Benefit) |
| **IVT disabling** | question has IVT term + no "disabling"/"non-disabling" + no nonDisabling in context + eligibility keyword | A) Disabling (COR 1) / B) Non-disabling NIHSS 0-5 (COR 3: No Benefit) |

Skipped if question is a contraindication question.

#### Layer 4: Content Breadth Analysis
`_compute_content_breadth()` — measures total content volume:
- Count qualifying recs (score >= REC_INCLUSION_MIN_SCORE)
- Group by section cluster (e.g. "4.6.1" → "4.6")
- Filter noise: only clusters with best_rec.score >= top_score * 33%

#### Layer 5: Vague Question Followup
`_detect_vague_question()` — uses breadth metrics to detect overly broad questions:

| Trigger | Threshold | Action |
|---------|-----------|--------|
| **Cross-section** | 3+ section clusters | "Which area are you asking about?" with section options |
| **Within-section** | >2 qualifying recs in 1-2 clusters | "This section covers multiple scenarios" with rec options |

**TOPIC_SECTION_MAP override**: If map resolved to <= 2 sections AND source == "topic_map":
- Low density (< 6 in-topic recs): trust routing
- High density (>= 6) + narrowing qualifier present ("dose", "target", "threshold", etc.): trust routing
- High density + no qualifier: let breadth trigger fire

#### Layer 6: Generic Ambiguity Detection (CMI Pattern)
`_detect_generic_ambiguity()` — when top recs from the SAME section have conflicting COR values (e.g. COR 1 vs COR 3: No Benefit), presents options instead of guessing.

#### Layer 7: Section-Level Ambiguity
`_detect_section_ambiguity()` — when top recs span 2+ sections with small score gap (< 5 points) and no explicit section reference, asks which clinical area the user means.

#### Layer 8: Score Threshold Scope Gate
If top rec score < SCOPE_GATE_MIN_SCORE (3) AND no RSS AND no KG content: return out_of_scope.

#### Layer 9: Response Assembly

Two assembly paths based on question type:

**Recommendation response** (`_assemble_recommendation_response`):
1. Patient context header (if available)
2. Contraindication tier classification (if Table 8 question)
3. Numeric alerts (platelets < 100k, INR > 1.7)
4. **VERBATIM recommendations** — character-for-character from guideline:
   ```
   **RECOMMENDATION [rec-id]**
   Section X.X -- Section Title
   Class of Recommendation: COR  |  Level of Evidence: LOE

   "[exact guideline text, never modified]"
   ```
5. Supporting text (may be truncated to 500 chars, cleaned of PDF artifacts, deduped by section:recNumber)
6. Knowledge gaps (may be truncated to 400 chars)
7. Referenced trials (deduplicated, extracted from all text)

**Evidence response** (`_assemble_evidence_response`):
1. Evidence content (up to 5 RSS entries, truncated to 500 chars)
2. Knowledge gaps (up to 3 entries)
3. Source citations
4. Verbatim recs for context (top 3)
5. Referenced trials

**Summary generation**: Template-based (no LLM). Maps COR to strength: "1" → "is recommended", "2a" → "is reasonable", "3: Harm" → "is not recommended (causes harm)".

**Guardrails on assembled response:**
- Recommendations are NEVER modified, paraphrased, or blended
- `validate_summary()`: checks for invented numbers, percentages, clinical thresholds, time durations
- `clean_pdf_text()`: removes formatting artifacts
- `strip_rec_prefix_from_rss()`: prevents duplication
- `truncate_text()`: caps RSS at 500 chars, KG at 400 chars

**Audit trail**: Every decision point logged — intent classification, retrieval stats, scope gate results, clarification triggers, breadth metrics, ambiguity detection, final assembly.

**Output:** `AssemblyResult` — status, answer, summary, citations, related_sections, referenced_trials, clarification_options, audit_trail.

---

## 4. Data Contracts

### Scenario Pipeline

```
ParsedVariables (60+ fields)
    |
    +--> Table8Result
    |      riskTier, absoluteContraindications[], relativeContraindications[],
    |      benefitOverRisk[], checklist[], unassessedCount, notes[]
    |
    +--> Table4Result
    |      isDisabling, rationale, disablingDeficits[], recommendation
    |
    +--> FiredRecommendation
    |      id, section, recNumber, cor, loe, category, text, matchedRule
    |
    +--> ClinicalDecisionState
           headline, verdict, primary_therapy, effective_ivt_eligibility,
           effective_is_disabling, bp_at_goal, bp_warning, is_extended_window,
           evt_status, evt_status_reason, ivt_badge, ivt_cor, ivt_loe,
           evt_cor, evt_loe, ivt_missing[], evt_missing[], visible_sections[]
```

### Q&A Pipeline

```
IntentResult
    question_type, search_terms[], section_refs[], topic_sections[],
    numeric_context{}, clinical_vars{}, is_general_question,
    is_evidence_question, is_contraindication_question,
    contraindication_tier, context_summary

ScoredRecommendation
    rec_id, section, section_title, rec_number, cor, loe, text,
    score, source ("deterministic"/"semantic"/"both")

RecommendationResult
    scored_recs[], search_method

SupportiveTextEntry
    section, section_title, rec_number, text, entry_type ("rss"/"synopsis")

KnowledgeGapEntry
    section, section_title, text

AssemblyResult
    status ("complete"/"needs_clarification"/"out_of_scope"),
    answer, summary, citations[], related_sections[],
    referenced_trials[], clarification_options[], audit_trail[]
```

---

## 5. Constants & Thresholds

### Scope Gate
| Constant | Value | Location |
|----------|-------|----------|
| `SCOPE_GATE_MIN_SCORE` | 3 | assembly_agent.py |
| `REC_INCLUSION_MIN_SCORE` | 1 | assembly_agent.py |
| Out-of-scope markers | ~40 terms | assembly_agent.py `check_topic_coverage()` |

### Response Limits
| Constant | Value | Location |
|----------|-------|----------|
| `MAX_RECS_IN_RESPONSE` | 5 | assembly_agent.py |
| `MAX_SUPPORTING_TEXT` | 5 (reduced to 2 if >= 3 formal recs) | assembly_agent.py |
| RSS truncation | 500 chars | qa_service.py |
| KG truncation | 400 chars | qa_service.py |

### Content Breadth
| Constant | Value | Location |
|----------|-------|----------|
| `BREADTH_SECTION_THRESHOLD` | 3 clusters | assembly_agent.py |
| `BREADTH_REC_THRESHOLD` | 2 recs | assembly_agent.py |
| `BREADTH_MIN_SCORE_FRACTION` | 0.33 | assembly_agent.py |
| `IN_TOPIC_REC_THRESHOLD` | 6 recs | assembly_agent.py |

### Section Ambiguity
| Constant | Value | Location |
|----------|-------|----------|
| `_SECTION_AMBIGUITY_THRESHOLD` | 5 points | assembly_agent.py |
| `_SECTION_AMBIGUITY_MIN_SCORE` | 5 | assembly_agent.py |

### Semantic Search
| Constant | Value | Location |
|----------|-------|----------|
| Model | all-MiniLM-L6-v2 | embedding_store.py |
| Min similarity | 0.25 | embedding_store.py |
| Hybrid boost (rec in both paths) | +5 | recommendation_agent.py |

### Concept Index Fallback
| Constant | Value | Location |
|----------|-------|----------|
| Min score | 10 | intent_agent.py |
| Top score separation | 70% of best | intent_agent.py |
| Max sections returned | 3 | intent_agent.py |

### Scoring Weights
| Factor | Points | Location |
|--------|--------|----------|
| Text field match | +3/term | qa_service.py |
| Metadata match | +1/term | qa_service.py |
| Density bonus (>= 4 text hits) | +2/extra | qa_service.py |
| Explicit section ref | +20 | qa_service.py |
| Topic-inferred section | +15 | qa_service.py |
| Rec number match | +10 | qa_service.py |
| Discriminating phrase match | +5 each (cap +30) | qa_service.py |
| Contradiction penalty | -8 to -12 | qa_service.py |
| Off-topic suppression | score / 2 | qa_service.py |

---

## 6. Data Files

All in `ais_clinical_engine/data/`:

| File | Size | Purpose |
|------|------|---------|
| `recommendations.json` | — | 202 AHA/ASA 2026 AIS recommendations (id, section, COR, LOE, category, text, evidenceKey, prerequisites) |
| `guideline_knowledge.json` | 582 KB | Per-section: RSS evidence, synopsis, knowledge gaps |
| `evt_rules.json` | — | 24 EVT eligibility condition-action rules (Sections 4.7.1-4.7.5) |
| `ivt_rules.json` | — | 37 Table 8 contraindication rules + Table 4 disabling criteria |
| `checklist_templates.json` | — | 25 items across 5 clinical domains |
| `recommendation_embeddings.npz` | 624 KB | Pre-computed sentence-transformer embeddings for all 202 recs |
| `loader.py` | — | `@lru_cache` data loading utility |

---

## 7. REST Endpoints

All in `ais_clinical_engine/routes.py`. All require `require_auth` except health.

### Scenario Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/clinical/scenarios` | POST | Full evaluation: parse → IVT → EVT → decision state. Persists to Firebase. |
| `/clinical/scenarios/parse` | POST | Parse text only (no evaluation) |
| `/clinical/scenarios/re-evaluate` | POST | Apply clinician overrides; recompute decision state WITHOUT re-running IVT/EVT |
| `/clinical/scenarios/what-if` | POST | Modify variables + re-run full pipeline (IVT + EVT re-evaluated) |

### Q&A Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/clinical/qa` | POST | Q&A against guideline. Falls back to legacy `answer_question()` on error. |
| `/clinical/qa/validate` | POST | Thumbs-down feedback: `verify_verbatim()` + LLM validation |

### Browse & Health

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/clinical/recommendations` | POST | Filter by section or category |
| `/clinical/health` | GET | Health check (no auth) |

### Request Models

```
ScenarioEvalRequest:   uid, text, session_id?
ReEvaluateRequest:     uid, session_id, overrides (ClinicalOverrides)
WhatIfRequest:         uid, session_id?, baseText?, modifications{}
QARequest:             uid, session_id?, question, context?
QAValidationRequest:   uid, feedback, answer, question, summary, citations[], context?
RecommendationsRequest: section?, category?
```

---

## 8. File Map

```
app/agents/clinical/
|
+-- ais_clinical_engine/
|   |-- engine.py                       <-- main entry (AisClinicalEngine)
|   |-- routes.py                       <-- REST endpoints
|   |
|   |-- agents/
|   |   |-- ivt_orchestrator.py         <-- coordinates Table8 + Table4 + IVTRecs + Checklist
|   |   |-- table8_agent.py             <-- 37 contraindication rules, 3 tiers
|   |   |-- table4_agent.py             <-- disabling deficit (NIHSS + BATHE)
|   |   |-- ivt_recs_agent.py           <-- IVT pathway routing, 5 paths (A-E) + additive
|   |   |-- checklist_agent.py          <-- 5-domain clinical workflows
|   |   |
|   |   '-- qa/
|   |       |-- orchestrator.py         <-- QAOrchestrator: Intent -> [3 parallel] -> Assembly
|   |       |-- intent_agent.py         <-- deterministic question classification
|   |       |-- recommendation_agent.py <-- dual retrieval (keyword + semantic), hybrid merge
|   |       |-- supportive_text_agent.py <-- RSS + synopsis search
|   |       |-- knowledge_gap_agent.py  <-- KG search + deterministic responses
|   |       |-- assembly_agent.py       <-- scope gate, clarification, verbatim assembly (~1550 lines)
|   |       |-- embedding_store.py      <-- vector search (all-MiniLM-L6-v2, .npz)
|   |       |-- section_index.py        <-- auto-generated concept index for fallback
|   |       '-- schemas.py              <-- all data contracts (IntentResult, AssemblyResult, etc.)
|   |
|   |-- services/
|   |   |-- nlp_service.py              <-- Claude-based patient data extraction
|   |   |-- rule_engine.py              <-- EVT eligibility (24 condition-action rules)
|   |   |-- decision_engine.py          <-- IVT+EVT synthesis -> ClinicalDecisionState
|   |   '-- qa_service.py              <-- scoring, search, CONCEPT_SYNONYMS, TOPIC_SECTION_MAP (~5000 lines)
|   |
|   |-- models/
|   |   |-- clinical.py                 <-- ParsedVariables, ClinicalDecisionState, ClinicalOverrides
|   |   |-- table8.py                   <-- Table8Result, Table8Item
|   |   |-- table4.py                   <-- Table4Result
|   |   |-- rules.py                    <-- FiredRecommendation, RuleCondition
|   |   '-- checklist.py               <-- ChecklistSummary, ChecklistItem
|   |
|   '-- data/
|       |-- recommendations.json        <-- 202 guideline recommendations
|       |-- guideline_knowledge.json    <-- RSS, synopsis, knowledge gaps (582 KB)
|       |-- evt_rules.json              <-- 24 EVT rules
|       |-- ivt_rules.json              <-- 37 Table 8 + Table 4 data
|       |-- checklist_templates.json    <-- 25 checklist items
|       |-- recommendation_embeddings.npz <-- pre-computed embeddings (624 KB)
|       '-- loader.py                   <-- @lru_cache loading
|
'-- clinical_output_agent/
    |-- engine.py                       <-- LLM-based clinical document formatter
    '-- references/
        |-- clinical_rules.md           <-- output formatting rules
        |-- routine_format.md           <-- routine case format (4-6 sentences)
        '-- edge_case_format.md         <-- edge case format (table + narrative)
```
