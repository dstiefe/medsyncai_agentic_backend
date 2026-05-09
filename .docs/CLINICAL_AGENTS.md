# MedSync AI — Clinical Agents Architecture

> A walkthrough of how everything under [app/agents/clinical/](../app/agents/clinical/) is wired together.
> Read this alongside [ENGINE_MAP.md](ENGINE_MAP.md) (high-level file map) and [CLINICAL_API.md](CLINICAL_API.md) (REST contract).

---

## 1. The Big Picture

The clinical engine answers two very different kinds of questions about acute ischemic stroke (AIS):

| Kind of question | Example | Pipeline |
|---|---|---|
| **Patient scenario** ("evaluate this case") | *"65yo, NIHSS 18, M1 occlusion, LKW 2h"* | Deterministic IVT + EVT rule pipeline |
| **Guideline Q&A** ("what does the guideline say about X?") | *"What are the BP targets during AIS?"* | Multi-agent Q&A pipeline (LLM + Python) |

Both pipelines live inside [ais_clinical_engine/](../app/agents/clinical/ais_clinical_engine/). The classifier that decides which one runs is at the top of [engine.py](../app/agents/clinical/ais_clinical_engine/engine.py#L31-L52) — two regexes look at the raw query to tell scenarios apart from guideline questions.

A second engine, [clinical_output_agent/](../app/agents/clinical/clinical_output_agent/), is a separate **LLM formatter** the orchestrator can hand structured eligibility output to when it needs prose. The QA pipeline does its own formatting via its `AssemblyAgent`, so the output agent is reserved for the scenario path.

---

## 2. Folder Layout

```
app/agents/clinical/
├── ais_clinical_engine/          ← all clinical reasoning lives here
│   ├── engine.py                 ← BaseEngine wrapper used by /chat/stream
│   ├── routes.py                 ← REST endpoints under /clinical/*
│   │
│   ├── agents/                   ← reasoning units
│   │   ├── ivt_orchestrator.py   ← IVT decision pipeline (Table 8 → Table 4 → IVT recs)
│   │   ├── ivt_recs_agent.py     ← fires IVT recommendations by pathway
│   │   ├── table8_agent.py       ← Table 8 contraindication evaluation
│   │   ├── table4_agent.py       ← disabling deficit assessment
│   │   ├── checklist_agent.py    ← cross-domain checklist (EVT, BP, imaging, …)
│   │   └── qa/                   ← multi-agent Q&A pipeline (see §5)
│   │       ├── orchestrator.py
│   │       ├── intent_agent.py
│   │       ├── query_parsing_agent.py
│   │       ├── topic_verification_agent.py
│   │       ├── section_router.py
│   │       ├── recommendation_agent.py
│   │       ├── recommendation_matcher.py
│   │       ├── supportive_text_agent.py
│   │       ├── knowledge_gap_agent.py
│   │       ├── assembly_agent.py
│   │       ├── embedding_store.py
│   │       ├── section_index.py
│   │       ├── schemas.py
│   │       └── references/       ← topic maps, schemas, dictionaries
│   │
│   ├── services/                 ← stateful services shared by both pipelines
│   │   ├── nlp_service.py        ← Anthropic client + scenario parsing + LLM Q&A helpers
│   │   ├── rule_engine.py        ← deterministic EVT rule evaluator
│   │   ├── decision_engine.py    ← merges raw IVT/EVT results into final state
│   │   └── qa_service.py         ← legacy monolithic Q&A (still used as fallback + helper lib)
│   │
│   ├── models/                   ← Pydantic data models
│   │   ├── clinical.py           ← ParsedVariables, FiredRecommendation, ClinicalDecisionState…
│   │   ├── rules.py              ← Rule, RuleClause, RuleCondition (EVT)
│   │   ├── table4.py / table8.py ← IVT contraindication + disabling models
│   │   └── checklist.py          ← clinical checklist models
│   │
│   └── data/                     ← guideline content (the things you edit to change behavior)
│       ├── recommendations.json         ← 202 AHA/ASA 2026 recommendations
│       ├── guideline_knowledge.json     ← RSS, synopsis, knowledge gaps per section
│       ├── recommendation_criteria.json ← pre-extracted criteria for CMI matching
│       ├── ivt_rules.json               ← Table 8 contraindications + Table 4 logic
│       ├── evt_rules.json               ← EVT eligibility rules
│       ├── checklist_templates.json     ← cross-domain checklist rules
│       └── loader.py                    ← cached JSON loaders (lru_cache(1))
│
└── clinical_output_agent/        ← LLM formatter for scenario eligibility output
    ├── engine.py
    ├── SKILL.md
    └── references/
        ├── routine_format.md
        ├── edge_case_format.md
        └── clinical_rules.md
```

---

## 3. Two Entry Points

### 3.1 Chat / SSE entry — [engine.py](../app/agents/clinical/ais_clinical_engine/engine.py)

`AisClinicalEngine` is the `BaseEngine` subclass the orchestrator routes to when intent classification picks `clinical_support`.

Constructed once at import time, it wires together:

- `NLPService` (Anthropic Claude wrapper)
- `IVTOrchestrator`
- `RuleEngine` (EVT)
- `DecisionEngine`
- `EmbeddingStore` (pre-computed rec embeddings, optional)
- `QAOrchestrator` (the multi-agent Q&A pipeline)

Its `run()` method classifies the query then dispatches:

```python
query_type = self._classify_query(query)
if query_type == "scenario":      → _run_scenario()
elif query_type == "guideline_qa": → _run_guideline_qa()
else:                              → out_of_scope reply
```

The classifier (`_classify_query`, [engine.py:104-113](../app/agents/clinical/ais_clinical_engine/engine.py#L104-L113)) uses two regexes:

| Regex | Matches | Decision |
|---|---|---|
| `_CLINICAL_PARAMS` | NIHSS, ASPECTS, LKW, vessel names, ages like "65yo", BP patterns | `scenario` |
| `_AIS_KEYWORDS` | "guideline", "IVT", "EVT", "thrombolysis", "table 4/8", "alteplase"… | `guideline_qa` |
| neither | — | `out_of_scope` |

Both pipelines return via `_build_return()` so the orchestrator gets the standard engine contract (`status`, `result_type`, `data`, `classification`, `confidence`).

### 3.2 REST entry — [routes.py](../app/agents/clinical/ais_clinical_engine/routes.py)

Mounted under `/clinical` with `require_auth`. The frontend uses these endpoints directly so it can render structured state instead of parsing markdown.

| Endpoint | Purpose |
|---|---|
| `POST /clinical/scenarios` | Full evaluation: parse → IVT → EVT → DecisionState → persisted to Firebase |
| `POST /clinical/scenarios/parse` | Parse text only (no evaluation) |
| `POST /clinical/scenarios/re-evaluate` | Apply clinician overrides; reuses persisted IVT/EVT results — only DecisionState changes |
| `POST /clinical/scenarios/what-if` | Apply variable modifications; re-runs the full IVT + EVT pipelines |
| `POST /clinical/qa` | Q&A pipeline (delegates to `QAOrchestrator`) |
| `POST /clinical/qa/validate` | Verbatim check + LLM validation when a clinician thumbs-down a Q&A answer |
| `POST /clinical/recommendations` | Browse/filter the 202 recommendations |
| `GET  /clinical/health` | Open health check |

Service instances (`_nlp_service`, `_ivt_orchestrator`, `_rule_engine`, `_decision_engine`, `_qa_orchestrator`) are created **once at module import** and reused. The rule engine is preloaded from `recommendations.json` + `evt_rules.json` at startup ([routes.py:64-67](../app/agents/clinical/ais_clinical_engine/routes.py#L64-L67)).

The `_run_full_evaluation()` helper ([routes.py:244-300](../app/agents/clinical/ais_clinical_engine/routes.py#L244-L300)) is shared by `/scenarios` and `/scenarios/what-if`. It runs the IVT pipeline, the EVT rule engine, the EVT three-valued eligibility check, and gates EVT recommendations on confirmed eligibility (so technique recs don't show before the patient is even confirmed eligible).

---

## 4. The Scenario Pipeline (deterministic IVT + EVT)

Triggered when the user submits a patient case. Pure deterministic pipeline except the very first step (LLM parser).

```
raw text
   │
   ▼
NLPService.parse_scenario()      ← Claude Sonnet, single tool_use call
   │     returns ParsedVariables (NIHSS, ASPECTS, age, vessel, LKW, …)
   ▼
_normalize_parsed_variables()    ← clock-time → hours, sex normalization
   │
   ├──────────────────┬─────────────────────┐
   ▼                  ▼                     ▼
IVTOrchestrator   RuleEngine.evaluate    RuleEngine.evaluate_evt_eligibility
   │                  │                     │
   ▼                  ▼                     ▼
{IVT result}     {EVT recs by category}  {eligible | pending | ineligible}
   │                  │                     │
   └────────┬─────────┴─────────────────────┘
            ▼
   DecisionEngine.compute_effective_state()  ← merges raw + clinician overrides
            │
            ▼
   ClinicalDecisionState (headline, IVT/EVT eligibility, BP, primary therapy)
            │
            ▼
   _format_decision()  (chat path)        OR        FullEvalResponse  (REST path)
```

### 4.1 NLPService (services/nlp_service.py)
Wraps the Anthropic SDK. Initialized with `ANTHROPIC_API_KEY` from settings/env. Its `parse_scenario()` method calls `claude-sonnet-4` with a strict extraction prompt that forbids clinical inferences and walks through clock-time / wake-up / LKW handling rules. It also exposes helper LLM methods used by the QA pipeline (`extract_from_section`, `validate_qa_answer`).

### 4.2 IVTOrchestrator (agents/ivt_orchestrator.py)
Coordinates four sub-agents in order:

1. **`Table8Agent`** — evaluates ~30 hard-coded `Table8Rule`s (absolute / relative / benefit-over-risk contraindications). Returns a `Table8Result` with tier, contraindications, warnings, and a per-rule checklist.
2. **`ClinicalChecklistAgent`** — runs all checklist rules across EVT, imaging, BP, medications, supportive care. Returns `ChecklistSummary` per domain showing assessed vs unassessed variables.
3. **`Table4Agent`** — assesses disabling vs non-disabling deficit. Uses NIHSS thresholds plus per-item disabling checks (vision, language, motor ≥2). Returns a `Table4Result`.
4. **`IVTRecsAgent`** — fires recommendations from `recommendations.json` based on the matched pathway:
   - Standard window (0–4.5h): disabling → 4.6.1 standard IVT; non-disabling → 4.6.1-008 no-benefit
   - Extended window (Section 4.6.3): unknown onset + DWI-FLAIR mismatch (4.6.3-001), penumbra + 4.5–9h or wake-up (4.6.3-002), LVO + penumbra + 4.5–24h + no EVT (4.6.3-003)
   - Imaging recs (Section 3.2) for wake-up / unknown time

If Table 8 fires an absolute contraindication, the orchestrator short-circuits and returns immediately with no recommendations.

### 4.3 RuleEngine (services/rule_engine.py)
Loads `recommendations.json` + `evt_rules.json`. Each rule is a `Rule` with a nested `RuleCondition` tree (`AND`/`OR` of `RuleClause`s). `evaluate(parsed)` walks every enabled rule, fires recommendations for matched ones, and returns `{recommendations: dict[category, list[FiredRecommendation]], notes, trace}`.

`evaluate_evt_eligibility(parsed)` is separate **three-valued logic** (met / failed / unknown per clause) so EVT correctly returns `pending` when required variables (ASPECTS, mRS, etc.) are missing instead of prematurely firing `recommended`. Its result is used by `routes.py` to gate technique/process recs.

### 4.4 DecisionEngine (services/decision_engine.py)
Single source of truth for **derived** state. Takes `parsed`, `ivt_result`, `evt_result`, optional `ClinicalOverrides`, and computes:

- effective IVT eligibility (raw result reconciled with clinician override)
- effective disabling assessment
- EVT status (`recommended` / `pending` / `not_indicated` / `ineligible`)
- BP at-goal flag and warning
- primary therapy pathway (IVT-only / EVT-only / IVT-then-EVT / pending / none)
- a single `headline` string the frontend renders

The `_run_full_evaluation()` helper in `routes.py` calls this. The rule is: **the frontend never re-derives state** — it sends variables + override answers, and the backend returns fully computed state to render.

### 4.5 The data files
| File | What it controls |
|---|---|
| [recommendations.json](../app/agents/clinical/ais_clinical_engine/data/recommendations.json) | All 202 AHA/ASA 2026 recommendations (text, COR, LOE, section, category) |
| [ivt_rules.json](../app/agents/clinical/ais_clinical_engine/data/ivt_rules.json) | Table 8 contraindications + Table 4 disabling logic |
| [evt_rules.json](../app/agents/clinical/ais_clinical_engine/data/evt_rules.json) | EVT eligibility rules consumed by `RuleEngine` |
| [checklist_templates.json](../app/agents/clinical/ais_clinical_engine/data/checklist_templates.json) | Cross-domain checklist rules |

All four are loaded by [data/loader.py](../app/agents/clinical/ais_clinical_engine/data/loader.py) and cached with `lru_cache(maxsize=1)`. To change clinical content, edit the JSON — never the agent code.

### 4.6 Output: scenario formatting
Two paths:

- **Chat (SSE)**: `engine.py::_format_decision()` builds a markdown block (headline → patient summary → IVT block → EVT block → BP warning → notes → disclaimer) and returns it as `formatted_text`.
- **REST**: `routes.py` returns a `FullEvalResponse` with structured `parsedVariables`, `ivtResult`, `evtResult`, `decisionState`, `notes`, `clinicalChecklists`. The frontend renders without prose.
- **Optional LLM prose**: when the orchestrator wants narrative output for a scenario, it can hand the structured eligibility data to [clinical_output_agent/](../app/agents/clinical/clinical_output_agent/), an `LLMAgent` that formats it using `SKILL.md` + `clinical_rules.md` + `routine_format.md` / `edge_case_format.md`. It also strips trial names from routine cases via `_strip_trial_names()`.

---

## 4b. The Scenario Workflow — what the system asks for, and when

The clinical engine is built around a single principle: **the user gives whatever they have, the system tells them what's still needed.** Nothing is required up front. Every parameter on `ParsedVariables` is `Optional`, and the engine returns one of three states for both IVT and EVT: **eligible / contraindicated / pending**. *Pending* means "I can't decide yet — give me X."

### 4b.1 The full universe of variables

[ParsedVariables](../app/agents/clinical/ais_clinical_engine/models/clinical.py#L22-L274) holds ~80 fields the parser may extract. They group into:

| Group | Fields |
|---|---|
| Demographics | `age`, `sex` |
| Timing | `timeHours`, `lastKnownWellHours`, `lkwClockTime`, `wakeUp` |
| Stroke severity | `nihss`, `nihssItems` (per-item: vision, language, motor arm/leg L/R, …), `nonDisabling` |
| Vessel imaging | `vessel` (M1/M2/ICA/basilar/…), `side`, `m2Dominant`, `isLVO`, `isAnteriorLVO`, `isBasilar` (computed) |
| Imaging extent | `aspects`, `pcAspects`, `prestrokeMRS`, `massEffect`, `dwiFlair`, `penumbra`, `earlyIschemicChange` |
| Vitals | `sbp`, `dbp` |
| Coagulation | `platelets`, `inr`, `aptt`, `pt`, `onAntiplatelet`, `onAnticoagulant`, `recentDOAC` |
| Hemorrhage / lesions | `hemorrhage`, `priorICH`, `aria`, `unrupturedAneurysm`, `intracranialVascularMalformation`, `cmbs`, `cmbCount` |
| Recent procedures / trauma | `recentTBI`, `tbiDays`, `recentNeurosurgery`, `neurosurgeryDays`, `recentNonCNSSurgery10d`, `recentDuralPuncture`, `recentArterialPuncture` |
| Cardiac / vascular | `infectiveEndocarditis`, `aorticArchDissection`, `cervicalDissection`, `recentSTEMI`, `stemiDays`, `acutePericarditis`, `cardiacThrombus` |
| Other Table 8 | `intraAxialNeoplasm`, `extraAxialNeoplasm`, `recentStroke3mo`, `recentGIGUBleeding21d`, `pregnancy`, `activeMalignancy`, `extensiveHypodensity`, `moyaMoya`, `sickleCell`, `glucoseCorrected`, `amyloidImmunotherapy`, `strokeMimic`, `historyMI`, `recreationalDrugUse`, `preExistingDisability`, `angiographicProceduralStroke`, `remoteGIGUBleeding` |
| Prior interventions | `ivtGiven`, `ivtNotGiven`, `evtUnavailable` |

Every field is `Optional[...] = None`. Three values for booleans: `True` (confirmed present), `False` (confirmed absent), `None` (not assessed). This three-valued world is what makes the workflow work.

### 4b.2 What is *actually required* to get a decision

There is **no hard required field** — the engine will run on the empty model. But to reach a *non-pending* answer, certain fields must be present:

#### To resolve IVT eligibility (`_compute_ivt_missing`, [decision_engine.py:368](../app/agents/clinical/ais_clinical_engine/services/decision_engine.py#L368))
```
LKW / time from onset    ← only true hard requirement
```
That's it. With just LKW, IVT moves out of `pending`. Everything else (NIHSS, BP, Table 8 items) only sharpens the answer.

#### To resolve EVT eligibility (`_compute_evt_missing`, [decision_engine.py:323](../app/agents/clinical/ais_clinical_engine/services/decision_engine.py#L323))
```
vessel imaging (CTA/MRA)
LKW / time from onset
ASPECTS  (or PC-ASPECTS for posterior circulation)
NIHSS
pre-stroke mRS
age
```
EVT needs **all six** before the rule engine can fire a positive recommendation. Any one missing → status stays `pending` and the missing variable is named in `evt_missing`.

#### To make Table 4 (disabling vs non-disabling) decide
```
NIHSS  (≥6 → disabling)
NIHSS 0-5 + nihssItems → check vision/language/motor arm/leg/extinction ≥2
NIHSS 0-5 + no items   → returns isDisabling=None ("needs assessment")
```
If the scenario explicitly says "non-disabling" or the clinician sets `parsed.nonDisabling = True`, that wins outright. ([table4_agent.py:32-99](../app/agents/clinical/ais_clinical_engine/agents/table4_agent.py#L32-L99))

#### To make Table 8 (contraindications) decide
Each of the ~30 Table 8 rules looks at one or two boolean variables. Because everything starts at `None`, every rule begins as **`unassessed`**. The clinician can resolve them three ways:
1. Explicitly pass `True` / `False` for that rule's trigger variable.
2. Set a per-rule override via `ClinicalOverrides.table8_overrides[ruleId]`.
3. Use a bulk override: `none_absolute=True`, `none_relative=True`, `none_benefit_over_risk=True` — flips every remaining `unassessed` item in that tier to `confirmed_absent`.

The IVT effective eligibility ladder is ([decision_engine.py:154-190](../app/agents/clinical/ais_clinical_engine/services/decision_engine.py#L154-L190)):

```
any absolute confirmed_present  → "contraindicated"   (stop)
any absolute still unassessed   → "pending"           (need answer)
any relative confirmed_present  → "caution"
otherwise                       → "eligible"
```

So the default state of a fresh case with NIHSS+LKW only is `pending` — until the clinician confirms "no absolute contraindications" (one click via `none_absolute`), it cannot move to `eligible`.

### 4b.3 The interactive workflow

The workflow is **request → response → optional gate answers → re-evaluate**, all over REST. The frontend never re-derives state.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1.  Initial submission                                         │
│                                                                     │
│  POST /clinical/scenarios                                           │
│  body: { uid, text: "65yo F, NIHSS 18, M1 occlusion, LKW 2h" }     │
│                                                                     │
│  → NLPService parses text into ParsedVariables                      │
│  → IVTOrchestrator runs Table 8 → checklist → Table 4 → IVT recs    │
│  → RuleEngine.evaluate runs all EVT rules                           │
│  → RuleEngine.evaluate_evt_eligibility runs three-valued check      │
│  → DecisionEngine.compute_effective_state merges everything         │
│  → context persisted to Firebase                                    │
│                                                                     │
│  Returns:                                                           │
│    parsedVariables       — what we extracted                        │
│    ivtResult             — Table 8 result, Table 4, IVT recs        │
│    evtResult             — fired recs, eligibility, missingVariables│
│    decisionState         — headline + ivt_missing + evt_missing +   │
│                            evt_status + ivt_status + bp_warning     │
│    clinicalChecklists    — per-domain checklist (assessed vs not)   │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼  Frontend renders headline + missing-data prompts
                            │
┌─────────────────────────────────────────────────────────────────────┐
│ Step 2.  Clinician answers gates (interactive overrides)            │
│                                                                     │
│  POST /clinical/scenarios/re-evaluate                               │
│  body: { uid, session_id, overrides: ClinicalOverrides }            │
│                                                                     │
│  Override fields:                                                   │
│    table8_overrides         — { "t8-001": "confirmed_absent", … }   │
│    none_absolute            — bulk: "no absolute contraindications" │
│    none_relative            — bulk: "no relative contraindications" │
│    none_benefit_over_risk   — bulk: "none of the BOR conditions"    │
│    table4_override          — disabling vs non-disabling override   │
│    evt_available            — yes/no — is EVT available locally?    │
│    lkw_within_24h           — clinician confirms time anchor        │
│    m2_is_dominant           — for M2: dominant vs nondominant       │
│    imaging_dwi_flair        — DWI-FLAIR mismatch confirmed?         │
│    imaging_penumbra         — salvageable penumbra confirmed?       │
│    symptom_recognition_within_window  — for unknown-onset cases     │
│    wake_up_within_window    — for wake-up strokes                   │
│                                                                     │
│  → Loads persisted ivt_result + evt_result from Firebase            │
│  → DecisionEngine.compute_effective_state re-runs WITH overrides    │
│  → IVT/EVT pipelines do NOT re-run (only the merge changes)         │
│  → New decisionState returned and re-persisted                      │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼  Either resolved or new gates appear
                            │
┌─────────────────────────────────────────────────────────────────────┐
│ Step 3.  Variable change ("what if NIHSS were 12?")                 │
│                                                                     │
│  POST /clinical/scenarios/what-if                                   │
│  body: { uid, session_id, modifications: { nihss: 12 } }            │
│                                                                     │
│  → Loads parsed variables from session                              │
│  → Applies the modifications (with special handling for null time)  │
│  → Re-runs the FULL pipeline (IVT + EVT + DecisionState)            │
│    because clinical inputs themselves changed                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 4b.4 The gating chain in detail

The order of operations inside `IVTOrchestrator.evaluate()` is the workflow:

```
1. Table8Agent.evaluate(parsed)
   ├─ walks all ~30 Table8Rule entries
   ├─ for each: did the trigger variable evaluate True / False / None?
   ├─ produces Table8Result with riskTier ∈ {
   │     absolute_contraindication,
   │     relative_contraindication,
   │     benefit_over_risk,
   │     no_contraindications
   │  }
   └─ also returns unassessedCount → drives "pending" gates upstream

2. ClinicalChecklistAgent.evaluate(parsed)
   └─ assesses 5 domains (EVT eligibility, imaging, BP, meds, supportive)
      Each domain returns ChecklistSummary with assessed/unassessed counts
      → frontend renders progress bars

3. Table4Agent.evaluate(nihss, nihssItems, nonDisabling)
   ├─ explicit nonDisabling → use it
   ├─ NIHSS missing → isDisabling=None ("needs_assessment")
   ├─ NIHSS ≥ 6 → isDisabling=True ("standard_ivt")
   ├─ NIHSS 0-5 + items → check disabling thresholds
   └─ NIHSS 0-5 + no items → isDisabling=None

4. Short-circuit: if Table 8 fired absolute_contraindication
   → return immediately, no IVT recs

5. IVTRecsAgent.evaluate(parsed, table8_result, table4_result)
   └─ matches one of the pathways:
      Path A: standard window + disabling → 4.6.1 standard IVT
      Path B: standard window + non-disabling → 4.6.1-008 (no benefit)
      Path C: unknown onset + DWI-FLAIR mismatch → 4.6.3-001
      Path D: penumbra + 4.5–9h or wake-up → 4.6.3-002
      Path E: LVO + penumbra + 4.5–24h + no EVT → 4.6.3-003
      Path F: wake-up / unknown time → imaging recs (Section 3.2)
```

In parallel, EVT runs **two evaluators** on the same parsed variables:

```
RuleEngine.evaluate(parsed)
   └─ fires recommendations from evt_rules.json that match
      (technique recs, anesthesia, IVT+EVT combinations, …)

RuleEngine.evaluate_evt_eligibility(parsed)
   └─ three-valued logic on each rule clause:
      met       — variable provided and satisfies clause
      failed    — variable provided and violates clause
      unknown   — variable not yet provided
   ├─ rule status:
   │     satisfied → all clauses met       (rule would fire)
   │     possible  → no failures, some unknowns (could still qualify)
   │     excluded  → at least one failure  (cannot qualify)
   └─ aggregate:
         ANY satisfied → eligible
         ANY possible  → pending (collect missing vars)
         ALL excluded  → excluded (collect reasons)
```

`_run_full_evaluation()` then calls `evt_result["eligibility"] = evt_eligibility` and **suppresses the technique recs unless eligibility is `eligible`**, so the user never sees "use a stent retriever" before they've even confirmed the patient qualifies for EVT at all.

### 4b.5 The decision-state outputs the frontend renders

`ClinicalDecisionState` ([clinical.py:401-441](../app/agents/clinical/ais_clinical_engine/models/clinical.py#L401-L441)) is the complete, fully-computed display state. Key fields:

| Field | Meaning |
|---|---|
| `headline` | One-line headline (e.g. *"EVT + IVT RECOMMENDED — LOWER BP BEFORE IVT"*) |
| `effective_ivt_eligibility` | `eligible` / `contraindicated` / `caution` / `pending` / `not_recommended` |
| `evt_status` | `recommended` / `pending` / `not_applicable` |
| `verdict` | `ELIGIBLE` / `NOT_RECOMMENDED` / `CAUTION` / `PENDING` |
| `primary_therapy` | `IVT` / `EVT` / `DUAL` / `NONE` |
| `is_dual_reperfusion` | True if both IVT and EVT recommended |
| `ivt_missing` | List of missing fields blocking IVT decision (e.g. `["LKW / time from onset"]`) |
| `evt_missing` | List of missing fields blocking EVT decision (e.g. `["ASPECTS score", "pre-stroke mRS"]`) |
| `bp_at_goal` / `bp_warning` | BP status — flags SBP > 185 or DBP > 110 |
| `is_extended_window` | True if >4.5h, wake-up, or unknown onset |
| `visible_sections` | Which UI sections to show |
| `ivt_cor` / `ivt_loe` / `ivt_rec_id` | The COR/LOE of the IVT rec that fired |
| `evt_cor` / `evt_loe` | The COR/LOE of the EVT rec that fired |
| `evt_narrowing` | Per-rule summary showing which EVT recs are viable / excluded and why |

The frontend renders prompts directly off `ivt_missing` / `evt_missing`. When those lists are empty, the case is fully evaluated.

### 4b.6 A worked example

```
Initial:  "65yo F, NIHSS 18, M1 occlusion, LKW 2h"

→ Parser extracts: age=65, sex=F, nihss=18, vessel=M1, lastKnownWellHours=2

→ IVT pipeline:
   • Table 8: every rule unassessed → riskTier=no_contraindications
              unassessedCount > 0 → IVT eligibility = "pending"
   • Table 4: NIHSS 18 ≥ 6 → isDisabling=True
   • IVT recs: Path A (standard window, disabling) → fires 4.6.1 standard IVT
   • ivt_missing = []  (LKW present)

→ EVT pipeline:
   • RuleEngine.evaluate: anterior LVO 0–6h rule → fires (but suppressed)
   • evaluate_evt_eligibility:
       — vessel ✓, time ✓, NIHSS ✓
       — ASPECTS unknown, prestrokeMRS unknown
       → state = "possible" → status = "pending"
   • evt_missing = ["ASPECTS score", "pre-stroke mRS"]

→ DecisionState:
   headline:               "EVALUATING IVT & EVT — DATA NEEDED"
   effective_ivt_eligibility: "pending"  (Table 8 unassessed)
   evt_status:             "pending"
   ivt_missing:            []
   evt_missing:            ["ASPECTS score", "pre-stroke mRS"]

Step 2:  clinician clicks "no absolute contraindications"
         and types ASPECTS=8, mRS=0

→ POST /clinical/scenarios/what-if  { modifications: { aspects: 8, prestrokeMRS: 0 } }
   then POST /clinical/scenarios/re-evaluate { overrides: { none_absolute: true } }

→ DecisionState now:
   headline:               "EVT + IVT RECOMMENDED"
   effective_ivt_eligibility: "eligible"
   evt_status:             "recommended"
   evt_cor / evt_loe:      "1" / "A"
   primary_therapy:        "DUAL"
   is_dual_reperfusion:    true
   ivt_missing:            []
   evt_missing:            []
```

### 4b.7 The key invariants of the workflow

1. **Nothing is required up front.** Every variable is `Optional`. The engine runs on whatever it gets.
2. **The engine names what it needs.** `ivt_missing` and `evt_missing` are the source of truth for "what to ask the clinician next."
3. **Three-valued logic everywhere.** `eligible` / `contraindicated` / `pending` for IVT; `recommended` / `not_applicable` / `pending` for EVT; `met` / `failed` / `unknown` per EVT clause.
4. **The frontend never re-derives.** `DecisionEngine.compute_effective_state()` produces every display field. The frontend sends overrides, the backend recomputes.
5. **Re-evaluate is cheap, what-if is expensive.** Re-evaluate only re-runs the merge step. What-if re-runs the full pipeline because clinical inputs themselves changed.
6. **EVT technique recs are gated.** They never display until eligibility is confirmed `eligible`.
7. **Absolute contraindication short-circuits everything.** The IVT pipeline returns immediately and the rest of the workflow is informational only.

---

## 5. The Q&A Pipeline (multi-agent, LLM + Python)

Triggered for guideline questions (no clinical params). Orchestrated by [`QAOrchestrator`](../app/agents/clinical/ais_clinical_engine/agents/qa/orchestrator.py). Replaces the legacy monolithic `answer_question()` in `qa_service.py`, which is kept as a **fallback** when the orchestrator throws.

### 5.1 Pipeline at a glance

```
question
   │
   ▼
IntentAgent (deterministic)             ─── classifies type, extracts terms, scores topic sections
   │
   ▼
QAQueryParsingAgent (Claude, async)     ─── parses topic, qualifier, scenario variables, search keywords
   │
   ▼
TopicVerificationAgent (Claude)         ─── sanity-checks the topic before Python lookup
   │      verdict: confirmed | wrong_topic | not_ais
   ▼
SectionRouter (deterministic lookup)    ─── topic → section IDs, like a calculator
   │
   ├─ if no topic:  fallback → intent.section_refs / topic_sections / content search
   │
   ▼
Retrieval branching:
   ┌────────────────────────────────────────────────────────────────────┐
   │  if question_type ∈ {evidence, knowledge_gap}:                     │
   │      pull RSS/KG from target sections, call NLPService.extract     │
   │      → return assembled answer                                     │
   │                                                                    │
   │  else (recommendation):                                            │
   │     1. CMI path (RecommendationMatcher)                            │
   │        — fires only when ≥2 patient-specific variables and         │
   │          extraction_confidence ≥ 0.6                               │
   │     2. Section-routed retrieval                                    │
   │        — pull all recs from resolved sections                      │
   │     3. Keyword fallback (RecommendationAgent)                      │
   │        — only when no sections resolved                            │
   └────────────────────────────────────────────────────────────────────┘
   │
   ▼
Parallel content fetch:
   SupportiveTextAgent  (RSS + synopsis)
   KnowledgeGapAgent    (knowledge gaps)
   │
   ▼
AssemblyAgent
   ─ verbatim recs (never paraphrased)
   ─ scope gate (refuse if no rec scores high enough)
   ─ clarification detection (conflicting CORs in same section)
   ─ summarization guardrails on RSS/KG
   ─ audit trail
   │
   ▼
AssemblyResult → engine.py wraps it in _build_return()
```

### 5.2 The agents

| Agent | Type | Job |
|---|---|---|
| **`IntentAgent`** ([intent_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/intent_agent.py)) | Deterministic | Classifies `question_type` (`recommendation` / `evidence` / `knowledge_gap`), extracts search terms + section refs, detects contraindication / general / Table 8 questions, builds the `IntentResult` consumed by all downstream agents. Reuses helpers from `qa_service.py` (`classify_question_type`, `extract_search_terms`, etc.). |
| **`QAQueryParsingAgent`** ([query_parsing_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/query_parsing_agent.py)) | LLM (Claude) | Parses the question into a `ParsedQAQuery`: topic + qualifier from the Topic Guide, scenario variables (NIHSS, ASPECTS, vessel, time window, age, mRS, core volume), `is_criterion_specific`, `extraction_confidence`, optional `clarification`, search keywords. Schema lives in [references/qa_query_parsing_schema.md](../app/agents/clinical/ais_clinical_engine/agents/qa/references/qa_query_parsing_schema.md). |
| **`TopicVerificationAgent`** ([topic_verification_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/topic_verification_agent.py)) | LLM (Claude, ~200 input tokens) | Sanity check: is the picked topic the right clinical area? Returns `confirmed`, `wrong_topic`, or `not_ais`. **Does not** redirect or suggest alternatives — downstream code reads section content and decides. `not_ais` returns out-of-scope immediately. |
| **`SectionRouter`** ([section_router.py](../app/agents/clinical/ais_clinical_engine/agents/qa/section_router.py)) | Deterministic | Pure lookup using [guideline_topic_map.json](../app/agents/clinical/ais_clinical_engine/agents/qa/references/guideline_topic_map.json) + [ais_guideline_section_map.json](../app/agents/clinical/ais_clinical_engine/agents/qa/references/ais_guideline_section_map.json). `resolve_topic(topic, qualifier)` → list of section IDs. Also `pull_section_recs()` and `pull_section_content()` for the orchestrator. Like a calculator: no scoring, no keywords. |
| **`RecommendationMatcher`** ([recommendation_matcher.py](../app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_matcher.py)) | Deterministic (CMI) | The Clinical Matching Index — same algorithm as Journal Search's TrialMatcher, adapted for guidelines. Loads pre-extracted [recommendation_criteria.json](../app/agents/clinical/ais_clinical_engine/data/recommendation_criteria.json) and tiers each recommendation by: (1) inverted tiering (how many query vars the rec addresses), (2) applicability gate (does query value fall outside rec criteria?), (3) forward tiering (does rec require vars the query lacks?), (4) scope index (fraction of query vars addressed, threshold ≥ 0.6). Returns `CMIMatchedRecommendation`s with tier 1–4. |
| **`RecommendationAgent`** ([recommendation_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/recommendation_agent.py)) | Deterministic + semantic | Keyword-fallback path: scores all 202 recs against the search query using `score_recommendation()` from `qa_service.py`, plus optional embedding similarity via `EmbeddingStore`. Returns `ScoredRecommendation`s. Used only when section routing fails. |
| **`SupportiveTextAgent`** ([supportive_text_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/supportive_text_agent.py)) | Deterministic | Searches `guideline_knowledge.json` for RSS (Recommendation-Specific Supportive text) entries matching the question. Returns raw text — Assembly may summarize. |
| **`KnowledgeGapAgent`** ([knowledge_gap_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/knowledge_gap_agent.py)) | Deterministic | Searches knowledge gap entries. Returns a deterministic "no gaps documented" reply for the 61/62 sections that have none. |
| **`AssemblyAgent`** ([assembly_agent.py](../app/agents/clinical/ais_clinical_engine/agents/qa/assembly_agent.py)) | Hybrid (Python + LLM) | Final formatter. **Recommendations are emitted verbatim, never paraphrased.** RSS and KG text may be summarized but with strict guardrails: no invented numbers, no dropped qualifiers, no blending across recs. Implements: (1) scope gate (refuse if no rec scores above threshold), (2) clarification detection (conflicting CORs in same section → present options), (3) summarization guardrails, (4) audit trail. Returns an `AssemblyResult`. |

### 5.3 The reference files

Everything that drives the QA pipeline's routing lives in [agents/qa/references/](../app/agents/clinical/ais_clinical_engine/agents/qa/references/):

| File | Used by | Purpose |
|---|---|---|
| `guideline_topic_map.json` | SectionRouter | Maps each clinical topic (and qualifiers) → section IDs |
| `ais_guideline_section_map.json` | SectionRouter | Hierarchy of valid section IDs + titles, used for validation |
| `data_dictionary.json` | SectionRouter, IntentAgent | Section IDs, variables, allowed values |
| `intent_map.json` | IntentAgent | Phrase → intent label mapping |
| `synonym_dictionary.json` | IntentAgent / qa_service | Concept synonyms for keyword scoring |
| `section_variable_matrix.json` | RecommendationMatcher | Which variables apply to which sections |
| `qa_query_parsing_schema.md` | QAQueryParsingAgent | LLM system prompt with the parsed-query schema |
| `topic_verification_schema.md` | TopicVerificationAgent | LLM system prompt for the verifier |

To change how the QA pipeline routes a topic, edit the JSON. To change how the parser extracts variables, edit the schema markdown. **No agent code changes.**

### 5.4 The data contracts

All inter-agent data flows through dataclasses defined in [schemas.py](../app/agents/clinical/ais_clinical_engine/agents/qa/schemas.py):

```
IntentResult                ← IntentAgent output
ParsedQAQuery               ← QAQueryParsingAgent output (LLM)
ScoredRecommendation        ← inside RecommendationResult
RecommendationResult        ← Recommendation* outputs
SupportiveTextEntry         ← inside SupportiveTextResult
SupportiveTextResult        ← SupportiveTextAgent output
KnowledgeGapEntry           ← inside KnowledgeGapResult
KnowledgeGapResult          ← KnowledgeGapAgent output
CMIMatchedRecommendation    ← RecommendationMatcher output
ClarificationOption         ← inside AssemblyResult
AuditEntry                  ← inside AssemblyResult
AssemblyResult              ← AssemblyAgent output
```

`AssemblyResult.to_dict()` is what gets handed back to `engine.py` / `routes.py`. Every field is a typed dataclass — no untyped dicts crossing agent boundaries.

### 5.5 Verbatim guarantee

Recommendation text is **never** modified once it leaves `recommendations.json`:

- `RecommendationMatcher` and `RecommendationAgent` carry rec text by reference into `ScoredRecommendation.text`.
- `AssemblyAgent` emits rec text as a literal block — the LLM is told to frame, not rephrase.
- `routes.py::POST /clinical/qa/validate` runs `verify_verbatim()` against `guideline_knowledge.json` to flag any drift if a clinician thumbs-down the answer.

This is the single most important invariant of the QA pipeline.

---

## 6. The clinical_output_agent

[clinical_output_agent/](../app/agents/clinical/clinical_output_agent/) is an `LLMAgent` (not a `BaseEngine`). It is a pure formatter — the orchestrator hands it structured eligibility data and gets back a guideline-referenced clinical document.

```
clinical_output_agent/
├── engine.py               ← ClinicalOutputAgent (LLMAgent subclass)
├── SKILL.md                ← reasoning instructions
└── references/
    ├── routine_format.md   ← format used when complexity == "routine"
    ├── edge_case_format.md ← format used when complexity == "edge_case"
    └── clinical_rules.md   ← COR/LOE wording rules and guardrails
```

`_load_references()` concatenates all three reference files onto the SKILL.md system message at construction. `_build_user_prompt()` assembles the patient presentation, eligibility blocks, and any vector context into a single user message. `_strip_trial_names()` removes trial names (TRACE-III, DAWN, ESCAPE, MR CLEAN, …) from routine cases — clinicians don't want to see them when the call is straightforward.

It is **not** wired into the QA pipeline — the QA `AssemblyAgent` formats its own output. The clinical output agent is for the scenario path when prose is needed.

---

## 7. Where to make changes

| Want to change… | Edit this |
|---|---|
| A guideline recommendation's text | [data/recommendations.json](../app/agents/clinical/ais_clinical_engine/data/recommendations.json) |
| An EVT eligibility rule | [data/evt_rules.json](../app/agents/clinical/ais_clinical_engine/data/evt_rules.json) |
| An IVT contraindication (Table 8) | [data/ivt_rules.json](../app/agents/clinical/ais_clinical_engine/data/ivt_rules.json) (or `Table8Agent.TABLE_8_RULES`) |
| Disabling-deficit thresholds (Table 4) | `Table4Agent.DISABLING_CHECKS` |
| Pre-extracted CMI criteria for a rec | [data/recommendation_criteria.json](../app/agents/clinical/ais_clinical_engine/data/recommendation_criteria.json) |
| RSS / synopsis / knowledge gap text | [data/guideline_knowledge.json](../app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json) |
| QA topic → section routing | [agents/qa/references/guideline_topic_map.json](../app/agents/clinical/ais_clinical_engine/agents/qa/references/guideline_topic_map.json) |
| QA query parsing schema (LLM prompt) | [agents/qa/references/qa_query_parsing_schema.md](../app/agents/clinical/ais_clinical_engine/agents/qa/references/qa_query_parsing_schema.md) |
| Topic verification rules | [agents/qa/references/topic_verification_schema.md](../app/agents/clinical/ais_clinical_engine/agents/qa/references/topic_verification_schema.md) |
| Synonyms used for keyword scoring | [agents/qa/references/synonym_dictionary.json](../app/agents/clinical/ais_clinical_engine/agents/qa/references/synonym_dictionary.json) and `CONCEPT_SYNONYMS` in [services/qa_service.py](../app/agents/clinical/ais_clinical_engine/services/qa_service.py) |
| The decision merge logic (overrides → state) | [services/decision_engine.py](../app/agents/clinical/ais_clinical_engine/services/decision_engine.py) |
| Scenario parser prompt | [services/nlp_service.py](../app/agents/clinical/ais_clinical_engine/services/nlp_service.py) — `parse_scenario()` system prompt |
| Output prose for scenarios | [clinical_output_agent/SKILL.md](../app/agents/clinical/clinical_output_agent/SKILL.md), `routine_format.md`, `edge_case_format.md`, `clinical_rules.md` |
| Add a new REST endpoint | [routes.py](../app/agents/clinical/ais_clinical_engine/routes.py) (must use `require_auth`, POST only, request model with `uid` + `session_id`) |

---

## 8. Probabilistic vs deterministic boundary

Following the project's three-layer rule:

| Job | Implementation |
|---|---|
| Parse free-text scenario into variables | LLM (`NLPService.parse_scenario`) |
| Parse free-text question into structured query | LLM (`QAQueryParsingAgent`) |
| Verify topic classification | LLM (`TopicVerificationAgent`) |
| Summarize RSS / knowledge gaps | LLM (inside `AssemblyAgent`) |
| Compare a number to a threshold | Python (`Table4Agent`, `RuleEngine`, `RecommendationMatcher`, `DecisionEngine`) |
| Apply a contraindication rule | Python (`Table8Agent`) |
| Match query variables to rec criteria | Python (`RecommendationMatcher`) |
| Map topic → section | Python lookup (`SectionRouter`) |
| Score and rank recommendations by keyword | Python (`score_recommendation()` in `qa_service.py`) |
| Format scenario eligibility output | Python (`engine.py::_format_decision`) and/or LLM (`clinical_output_agent`) |
| Emit recommendation text | **Verbatim, never modified by anything** |

The rule from CLAUDE.md applies absolutely here: **never ask an LM to compare a number to a threshold.** Every threshold and eligibility decision is deterministic Python.

---

## 9. Sequence: a guideline question end-to-end

For *"What are the BP targets during AIS?"*:

1. `engine.py::_classify_query` matches `_AIS_KEYWORDS` ("blood pressure target") → `guideline_qa`
2. `engine.py::_run_guideline_qa` calls `QAOrchestrator.answer(question)`
3. `IntentAgent.run()` → `IntentResult(question_type="recommendation", search_terms=["blood pressure", "target"], …)`
4. `QAQueryParsingAgent.parse()` → `ParsedQAQuery(topic="Blood Pressure Management", qualifier=None, is_criterion_specific=False, extraction_confidence=0.92)`
5. `TopicVerificationAgent.verify()` → `verdict="confirmed"`
6. `SectionRouter.resolve_topic("Blood Pressure Management")` → `["3.5"]` (or similar)
7. CMI gate fails (no patient variables) → falls through to section-routed retrieval
8. `SectionRouter.pull_section_recs(["3.5"], recs_store)` → all recs in §3.5
9. `SectionRouter.pull_section_content(["3.5"], guideline_knowledge)` → RSS + KG for §3.5
10. `AssemblyAgent.run(intent, rec_result, rss_result, kg_result)`:
    - Lays out each rec verbatim with COR/LOE
    - Summarizes RSS into a brief narrative (LLM)
    - Builds citations and audit trail
11. `AssemblyResult.to_dict()` → `engine.py` wraps it in `_build_return(status="complete", result_type="clinical_guidance", …)`
12. Orchestrator streams the response to the user.

For a patient scenario like *"65yo, NIHSS 18, M1 occlusion, LKW 2h"*, the path through `_run_scenario` → `IVTOrchestrator` → `RuleEngine` → `DecisionEngine` → `_format_decision` is fully deterministic after the initial LLM parse.

---

## 10. Testing

See [.claude/rules/testing.md](../.claude/rules/testing.md) for the testing protocol. Standard AIS test queries:

| ID | Query | Expected path |
|---|---|---|
| OOS-1 | *"How do I manage ICH?"* | clinical_support → out_of_scope → decline |
| INS-1 | *"65yo, NIHSS 18, M1 occlusion, LKW 2h"* | clinical_support → scenario → reperfusion path |
| INS-2 | *"What are the BP targets during AIS?"* | clinical_support → guideline_qa → BP section |
| DEV-1 | Any non-AIS query | general / knowledge_base (does NOT reach clinical engine) |

After every test, report intent, routing, and the final response — partial passes are failures.
