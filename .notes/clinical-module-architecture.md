# Clinical Module Architecture

How the AIS clinical engine works end-to-end, including guideline search.

---

## High-Level Flow

```
User Query
    │
    ▼
Orchestrator: Domain Classifier
    │
    ▼
Domain = "clinical"?
    ├─ YES → clinical_redirect SSE → Frontend calls /clinical/* REST endpoints
    └─ NO  → Other engine paths
```

The orchestrator does not process clinical queries itself. It detects
the clinical domain and sends a redirect event. The frontend then calls
REST endpoints in `routes.py`, which run the full pipeline.

---

## Two Query Types

The engine classifies every query into one of two pipelines:

| Type | Detection | Pipeline |
|------|-----------|----------|
| **Scenario** (patient case) | Regex on clinical parameters: NIHSS, ASPECTS, LKW, vessel, age, BP | Parse → Evaluate → Decision State |
| **Guideline Q&A** (knowledge question) | Regex on AIS keywords: guideline, IVT, EVT, contraindication, table 4/8 | Search → Summarize → Validate |

---

## Scenario Pipeline

### Phase 1: Parsing (NLPService)

**Service:** `NLPService.parse_scenario()`
**Model:** Claude Sonnet via tool_use (structured JSON extraction)
**Output:** `ParsedVariables` — a Pydantic model with 155+ fields

Extracted fields include:
- **Demographics:** age, sex
- **Timing:** timeHours, lastKnownWellHours, lkwClockTime, wakeUp, timeWindow
- **Severity:** NIHSS (total + 11 itemized scores), ASPECTS, pre-stroke mRS
- **Imaging:** vessel, side, m2Dominant, penumbra, DWI-FLAIR, mass effect, CMB count
- **Vitals:** SBP, DBP
- **Medications:** antiplatelet, anticoagulant status
- **Conditions:** hemorrhage, sickle cell, recent TBI/neurosurgery, coagulopathy, etc.

Post-processing:
- Clock time → hours conversion (in routes.py)
- Side extraction from vessel names ("left M1" → vessel="M1", side="left")
- "No LVO" detection via regex fallback

### Phase 2: Deterministic Evaluation

Three components run in parallel:

```
ParsedVariables
    │
    ├──► IVT Orchestrator
    │       ├── Table8Agent   → contraindication tiers
    │       ├── Table4Agent   → disabling deficit assessment
    │       ├── IVTRecsAgent  → IVT pathway routing + fired recs
    │       └── ChecklistAgent → multi-domain clinical workflows
    │
    ├──► RuleEngine           → EVT eligibility (three-valued logic)
    │
    └──► DecisionEngine       → synthesizes IVT + EVT → final state
```

#### Table8Agent (`agents/table8_agent.py`)

Evaluates 37 contraindication rules across 3 tiers:

| Tier | Count | Examples |
|------|-------|---------|
| **Absolute** | 10 | hemorrhage, extensive hypodensity, recent neurosurgery <14d, ARIA, coagulopathy |
| **Relative** | 18 | recent DOAC, prior ICH, pregnancy, malignancy |
| **Benefit Over Risk** | 9 | cervical dissection, unruptured aneurysm, Moya-Moya |

Three-valued evaluation: if ANY absolute fires, stop immediately.
Output: `Table8Result` with riskTier, checklist (confirmed_present/absent/unassessed), notes.

#### Table4Agent (`agents/table4_agent.py`)

Determines if deficits are disabling using NIHSS thresholds and item analysis.
Implements BATHE criteria (Bathing, Ambulating, Toileting, Hygiene, Eating).
Output: `Table4Result` with isDisabling boolean + detailed assessment.

#### IVTRecsAgent (`agents/ivt_recs_agent.py`)

Routes patients through IVT decision pathways and fires specific recommendations:

| Path | Condition | Key Recommendations |
|------|-----------|-------------------|
| **A: Standard IVT** | 0-4.5h + disabling deficit | 4.6.1-001 through 005, 010, 4.6.2-001/002 |
| **B: Non-disabling** | 0-4.5h + non-disabling | 4.6.1-008 (No IVT), DAPT recs instead |
| **C: Extended (DWI-FLAIR)** | >4.5h + DWI-FLAIR mismatch | 4.6.3-001 |
| **D: Extended (Penumbra)** | >4.5h + salvageable penumbra | 4.6.3-002 |
| **E: Extended (EVT unavail)** | 4.5-24h + LVO + penumbra + no EVT | 4.6.3-003 |

Also fires additive recs: imaging (Section 3.2), antiplatelet, sickle cell, BP management, CMB burden.

#### RuleEngine (`services/rule_engine.py`)

Evaluates EVT eligibility using condition-action rules from `evt_rules.json`.
Three-valued logic per clause: met / failed / unknown.

Rules cover:
- Standard window EVT (0-6h): anterior LVO, age <80, NIHSS >= 6, pre-stroke mRS <= 1, ASPECTS thresholds
- Extended window EVT (6-24h): stricter ASPECTS by time window
- Posterior circulation EVT: basilar artery, separate ASPECTS cutoffs
- Large core exclusion: ASPECTS <3 (Section 4.7.2)

Output: `{recommendations, notes, trace, eligibility}` with per-rule met/failed/unknown breakdown.

#### DecisionEngine (`services/decision_engine.py`)

Synthesizes IVT + EVT results + clinician overrides into a single `ClinicalDecisionState`:
- Effective IVT eligibility (eligible/contraindicated/caution/pending/not_recommended)
- Effective disabling status
- EVT status (recommended/pending/not_applicable)
- Primary therapy (IVT/EVT/DUAL/NONE)
- Display text: headline, description, status lines, badges
- COR/LOE for both IVT and EVT
- Missing variables, BP status, visibility flags

### Phase 3: Response

The full result is serialized and returned as JSON:

```json
{
  "parsedVariables": { ... },
  "ivtResult": {
    "eligible": true,
    "riskTier": "no_contraindications",
    "disablingAssessment": { ... },
    "recommendations": [ ... ],
    "contraindications": [],
    "warnings": [],
    "notes": [],
    "table8Checklist": [ ... ],
    "clinicalChecklists": [ ... ]
  },
  "evtResult": {
    "recommendations": { ... },
    "notes": [],
    "eligibility": { "status": "eligible", ... }
  },
  "decisionState": {
    "headline": "...",
    "primary_therapy": "DUAL",
    "ivt_cor": "1", "ivt_loe": "A",
    "evt_cor": "1", "evt_loe": "A",
    ...
  }
}
```

Session is persisted to Firebase for audit trail and re-evaluation.

---

## Guideline Q&A Pipeline

**Entry:** `engine.py._run_guideline_qa()`

### How Guideline Searching Works

There is **no vector search or embeddings** in the current v2 implementation.
Matching is keyword + synonym + rule-based + LLM summarization.

#### Three-Layer Search

| Layer | Source | Content |
|-------|--------|---------|
| 1. Formal Recommendations | `recommendations.json` (202 recs) | Exact section/category match against guideline recommendations |
| 2. RSS Evidence | `guideline_knowledge.json` | Trial-level data, secondary sources |
| 3. Synopsis & Knowledge Gaps | `guideline_knowledge.json` | Text summaries, known limitations |

#### Search Process

1. **Keyword Extraction:** LLM extracts clinical concepts from the question
2. **Concept Synonym Expansion:** Maps terms to guideline terminology via `CONCEPT_SYNONYMS` dict
   - e.g., "tnk" → ["tenecteplase"], "tpa" → ["alteplase"]
3. **Recommendation Filtering:**
   - By section (e.g., "Section 4.6.1" for IVT)
   - By category (e.g., "ivt_decision", "evt_decision")
   - By applicability conditions (optional RuleCondition gate)
4. **Evidence Ranking:** Formal recommendations > RSS evidence > synopsis
5. **LLM Summarization:** Claude (Sonnet) generates 2-3 sentence answer from retrieved sections
6. **Citation Tracking:** Maintains list of recommendation IDs for UI display

#### Safety Rules (Embedded in LLM Prompt)

- Never delay IVT for imaging
- CTA in parallel but doesn't delay IVT
- CTP not required in standard window
- IVT is time-critical

#### Q&A Validation

Optional validation step: checks intentCorrect, recommendationsRelevant, summaryAccurate.
Thumbs-down feedback loop available for continuous improvement.

---

## Data Files

All in `ais_clinical_engine/data/`:

| File | Purpose |
|------|---------|
| `recommendations.json` | 202 AHA/ASA 2026 AIS recommendations (id, section, COR, LOE, category, text) |
| `evt_rules.json` | EVT eligibility condition-action rules |
| `ivt_rules.json` | Table 8 (37 contraindication rules) + Table 4 (disabling deficit checks) |
| `checklist_templates.json` | Multi-domain workflow templates (EVT, imaging, BP, medications, supportive care) |
| `guideline_knowledge.json` | RSS evidence + synopsis + knowledge gaps for Q&A |
| `loader.py` | `@lru_cache` data loading utility for all JSON files |

---

## REST Endpoints

All in `ais_clinical_engine/routes.py`, all require auth.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/clinical/scenarios` | POST | Full evaluation: parse → IVT → EVT → decision state |
| `/clinical/scenarios/parse` | POST | Parse text only (no evaluation) |
| `/clinical/scenarios/re-evaluate` | POST | Apply clinician overrides, recompute decision state |
| `/clinical/scenarios/what-if` | POST | Modify variables + re-run full pipeline |
| `/clinical/qa` | POST | Q&A against guideline |
| `/clinical/qa/validate` | POST | Validate Q&A answer (feedback) |
| `/clinical/recommendations` | POST | Browse/filter 202 recommendations |
| `/clinical/health` | GET | Health check (no auth) |

---

## Key Clinical Logic

### IVT Eligibility
- No absolute contraindications (Table 8)
- Disabling deficit OR extended window with imaging evidence
- Time window gates specific recommendations (0-4.5h vs extended)
- Pediatric patients (age <18) → COR 2b, LOE C-LD

### EVT Eligibility (Three-Valued)
- Anterior LVO required (ICA or M1)
- Age <80, pre-stroke mRS <= 1, NIHSS >= 6
- ASPECTS gated by time window and age
- Large core (ASPECTS <3) excluded unless specific trial criteria met
- Posterior (basilar) has separate rules
- M2 dominant eligible, nondominant not recommended

### Extended Window
- Time >4.5h, wake-up stroke, or unknown onset
- IVT requires imaging: DWI-FLAIR mismatch or salvageable penumbra
- EVT: different ASPECTS thresholds by time bucket

---

## File Map

```
app/agents/clinical/ais_clinical_engine/
├── engine.py                  ← main entry point (AisClinicalEngine)
├── routes.py                  ← REST endpoints
├── agents/
│   ├── table8_agent.py        ← contraindication evaluation (37 rules, 3 tiers)
│   ├── table4_agent.py        ← disabling deficit assessment (NIHSS + BATHE)
│   ├── ivt_recs_agent.py      ← IVT pathway routing + recommendation firing
│   ├── ivt_orchestrator.py    ← runs Table8 → Table4 → IVTRecs → Checklist
│   └── checklist_agent.py     ← multi-domain clinical workflows
├── services/
│   ├── nlp_service.py         ← Claude-based patient data extraction
│   ├── rule_engine.py         ← EVT eligibility (condition-action rules)
│   ├── decision_engine.py     ← synthesizes IVT + EVT → ClinicalDecisionState
│   └── qa_service.py          ← guideline Q&A (search + summarize)
├── models/
│   ├── parsed_variables.py    ← ParsedVariables (155+ fields)
│   └── ...                    ← Table8Result, Table4Result, FiredRecommendation, etc.
├── data/
│   ├── recommendations.json   ← 202 guideline recommendations
│   ├── evt_rules.json         ← EVT eligibility rules
│   ├── ivt_rules.json         ← Table 8 + Table 4 data
│   ├── checklist_templates.json
│   ├── guideline_knowledge.json
│   └── loader.py              ← cached data loading
```
