# Plan: Merge Clinical Guideline Backend into MedSync AI v2

## Context

**Problem:** The clinical guideline project (`medsyncai_clinical_guideline`) has a solid AIS clinical decision support backend but: (a) no persistence/auth/concurrency, (b) guideline data is embedded in a Python file instead of structured JSON, and (c) critical clinical decisions (contraindication overrides, Table 4 disabling assessment, EVT availability, dual reperfusion logic) happen in frontend JavaScript — the backend never sees clinician selections.

**Solution:** Port the clinical backend into `medsync_ai_v2` which already has Firebase sessions, concurrency, and auth. During the port: extract guideline data to JSON files, and move all 10 frontend decision points into the backend so the backend is the single source of truth for clinical outcomes.

**Work location:** `C:\Users\danie\Documents\gitHub\medsyncai_agentic_version_vs2\medsync_ai_v2`

---

## Phase 1: Extract Guideline Data to JSON

Convert `scripts/seed_ais_2026_complete.py` (2956 lines of Python dicts) into structured JSON files:

```
engines/ais_clinical_engine/data/
├── recommendations.json       ← All AHA/ASA 2026 guideline recommendations
├── ivt_rules.json             ← IVT pathway rules (Table 8 contraindications, Table 4 criteria)
├── evt_rules.json             ← EVT eligibility rules (condition-action pairs)
└── checklist_templates.json   ← 5-domain clinical checklist definitions
```

**Why JSON:** Guideline data is reference data, not logic. JSON makes it reviewable/editable by clinicians (like the brother) without touching Python code. Also easier to version and validate.

**Loader:** Create `data/loader.py` that reads the JSON files at startup and returns the same in-memory structures the agents currently expect.

---

## Phase 2: Port Clinical Logic into v2 (Backend Core)

Create `engines/ais_clinical_engine/` in medsync_ai_v2:

```
engines/ais_clinical_engine/
├── __init__.py
├── engine.py                  ← Core engine: parse → IVT → EVT → decision state
├── models/
│   ├── clinical.py            ← ParsedVariables, ScenarioResponse, Note, etc.
│   ├── table8.py              ← Table8Rule, Table8Item, Table8Result
│   ├── table4.py              ← Table4Result
│   ├── checklist.py           ← ChecklistItem, ChecklistSummary
│   └── rules.py               ← RuleClause, RuleCondition, Rule
├── agents/
│   ├── table8_agent.py        ← 23 contraindication rules (verbatim port)
│   ├── table4_agent.py        ← Disabling deficit assessment (verbatim port)
│   ├── ivt_recs_agent.py      ← Pathway recommendation firing (verbatim port)
│   ├── checklist_agent.py     ← 5-domain clinical checklist (verbatim port)
│   └── ivt_orchestrator.py    ← 4-step pipeline coordinator (verbatim port)
├── services/
│   ├── nlp_service.py         ← Adapted to use v2's LLMClient
│   ├── rule_engine.py         ← EVT deterministic rules (verbatim port)
│   └── decision_engine.py     ← NEW: all frontend decision logic moved here
├── data/
│   ├── loader.py              ← JSON file loader
│   ├── recommendations.json
│   ├── ivt_rules.json
│   ├── evt_rules.json
│   └── checklist_templates.json
└── routes.py                  ← REST endpoint definitions
```

### Source file mapping:
| Source (`medsyncai_clinical_guideline/backend/`) | Destination | Change |
|--------------------------------------------------|-------------|--------|
| `app/models/clinical.py` | `models/*.py` | Split into separate model files |
| `app/agents/table8_agent.py` | `agents/table8_agent.py` | Verbatim |
| `app/agents/table4_agent.py` | `agents/table4_agent.py` | Verbatim |
| `app/agents/ivt_recs_agent.py` | `agents/ivt_recs_agent.py` | Verbatim |
| `app/agents/checklist_agent.py` | `agents/checklist_agent.py` | Verbatim |
| `app/agents/ivt_orchestrator.py` | `agents/ivt_orchestrator.py` | Verbatim |
| `app/services/nlp_service.py` | `services/nlp_service.py` | Adapt to v2's LLMClient |
| `app/services/rule_engine.py` | `services/rule_engine.py` | Verbatim |
| `scripts/seed_ais_2026_complete.py` | `data/*.json` + `data/loader.py` | Extract to JSON |

### NLPService adaptation:
Only file needing real modification — changes from `anthropic.Anthropic().messages.create()` to v2's `LLMClient.call()` with the same tool_use schema.

---

## Phase 3: Move Frontend Decision Logic to Backend

**This is the critical change.** Currently 10 decision points live in frontend JS. All move to a new `services/decision_engine.py` that the backend calls after receiving clinician input.

### Decision points to move:

| # | Decision | Current location | What it does |
|---|----------|-----------------|--------------|
| 1 | **Contraindication overrides** | `useInteractiveGates.ts:42-67` | Clinician confirms/denies each Table 8 item → changes eligibility |
| 2 | **Effective IVT eligibility** | `useInteractiveGates.ts:118-124` | Computes final eligibility from overrides (eligible/contraindicated/caution/pending) |
| 3 | **"None of these" bulk override** | `useInteractiveGates.ts:197-213` | Marks entire tier as non-contraindicated |
| 4 | **Table 4 disabling override** | `Table4DisablingGate.tsx:31-33` | Clinician overrides backend's disabling assessment → changes IVT vs DAPT |
| 5 | **EVT availability** | `EVTAvailabilityGate.tsx:29-48` | Clinician confirms EVT available → determines primary therapy pathway |
| 6 | **Quick answer verdict** | `useScenario.ts:63-90` | Derives YES/NO eligibility from IVT + EVT results |
| 7 | **Dual reperfusion eligibility** | `ClinicalDecisionSummary.tsx:38-42` | LVO + time ≤4.5h + EVT recs → both IVT+EVT recommended |
| 8 | **BP not at goal** | `ClinicalDecisionSummary.tsx:43` | SBP >185 → "LOWER BP BEFORE IVT" warning |
| 9 | **Extended window detection** | `App.tsx:173-174` | Time >4.5h → changes pathway flow and visibility |
| 10 | **IVT pathway visibility** | `App.tsx:177-182` | Determines which sections show based on window + EVT |

### New `decision_engine.py`:

```python
class DecisionEngine:
    def compute_effective_state(
        self,
        parsed_variables: ParsedVariables,
        ivt_result: IVTResult,
        evt_result: EVTResult,
        clinician_overrides: ClinicalOverrides,  # NEW input model
    ) -> ClinicalDecisionState:  # NEW output model
        """
        Single source of truth for all derived clinical decisions.
        Replaces all frontend decision logic.
        """
        return ClinicalDecisionState(
            effective_ivt_eligibility=...,   # from overrides (#1, #2, #3)
            effective_is_disabling=...,       # from Table 4 override (#4)
            primary_therapy=...,             # from EVT availability (#5)
            verdict=...,                     # quick answer (#6)
            is_dual_reperfusion=...,         # LVO + time + EVT (#7)
            bp_at_goal=...,                  # SBP check (#8)
            is_extended_window=...,          # time check (#9)
            visible_sections=...,            # pathway visibility (#10)
            headline=...,                    # CDS banner text
        )
```

### New request model `ClinicalOverrides`:

```python
class ClinicalOverrides(BaseModel):
    table8_overrides: dict[str, str] = {}        # {ruleId: "confirmed_present"|"confirmed_absent"}
    none_absolute: bool = False                   # "None of these" for absolute tier
    none_relative: bool = False
    none_benefit_over_risk: bool = False
    table4_override: Optional[bool] = None        # True=disabling, False=non-disabling, None=no override
    evt_available: Optional[bool] = None           # True/False/None(not yet answered)
```

### How it works:
1. `POST /clinical/scenarios` → returns initial results + `ClinicalDecisionState` (no overrides yet)
2. Frontend renders gates/checkboxes based on response
3. Clinician interacts → frontend sends `POST /clinical/scenarios/re-evaluate` with overrides
4. Backend re-computes `ClinicalDecisionState` with overrides applied → returns updated state
5. Frontend simply renders what backend tells it — no local decision logic

---

## Phase 4: REST API Endpoints

Add to v2's `main.py` (following v2's `@app.post()` pattern), or create `routes.py` and import:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /clinical/scenarios` | POST | Full evaluation: parse → IVT → EVT → DecisionState |
| `POST /clinical/scenarios/parse` | POST | Parse text only |
| `POST /clinical/scenarios/re-evaluate` | POST | **NEW** — accepts `ClinicalOverrides`, re-runs DecisionEngine with overrides |
| `POST /clinical/scenarios/what-if` | POST | Modify parsed variables and re-evaluate |
| `POST /clinical/qa` | POST | Q&A against recommendations |
| `GET /clinical/recommendations` | GET | Browse/filter guideline recommendations |
| `GET /clinical/health` | GET | Engine health check |

### Key new endpoint — `POST /clinical/scenarios/re-evaluate`:

```python
# Request
{
    "session_id": "abc-123",
    "uid": "user123",
    "overrides": {
        "table8_overrides": {"t8-003": "confirmed_absent", "t8-007": "confirmed_present"},
        "none_absolute": false,
        "table4_override": true,
        "evt_available": true
    }
}

# Response — updated decision state
{
    "decisionState": {
        "effective_ivt_eligibility": "contraindicated",
        "effective_is_disabling": true,
        "primary_therapy": "EVT",
        "is_dual_reperfusion": true,
        "bp_at_goal": false,
        "headline": "EVT + IVT RECOMMENDED — LOWER BP BEFORE IVT",
        "visible_sections": ["evt_results", "ivt_pathway", "table8_gate", "bp_management"],
        "verdict": "ELIGIBLE"
    },
    "ivtResult": {...},    # unchanged from initial eval
    "evtResult": {...}     # unchanged
}
```

Frontend becomes a thin renderer — sends overrides, displays what comes back.

---

## Phase 5: Session State Integration

Clinical context persisted in Firebase via SessionManager (no code changes to session_state.py needed):

```python
session_state["clinical_context"] = {
    "parsed_variables": {...},
    "ivt_result": {...},
    "evt_result": {...},
    "decision_state": {...},         # ClinicalDecisionState
    "clinician_overrides": {...},    # ClinicalOverrides — audit trail
    "last_scenario_text": str,
}
```

### Session flow:
1. `POST /clinical/scenarios` → evaluate + save to session
2. `POST /clinical/scenarios/re-evaluate` → load session, apply overrides, save updated state
3. `POST /clinical/scenarios/what-if` → load baseline from session, modify, re-evaluate, save
4. All override history is persisted → audit trail for clinician decisions

---

## Phase 6: Wire Orchestrator (Optional)

If clinical queries should also work through the chat stream (e.g., "is this patient eligible for IVT?"):
- Update import to new engine location in `orchestrator.py`
- `_run_clinical_path()` calls the same engine, formats result as prose

This is **optional** — REST endpoints are the primary interface.

---

## Verification

1. Start v2 server
2. `POST /clinical/scenarios` with: `{"text": "65-year-old male, NIHSS 14, onset 2h ago, CT no hemorrhage, ASPECTS 8, MCA M1 occlusion"}`
   - Verify response has `parsedVariables`, `ivtResult`, `evtResult`, `decisionState`
   - Verify `decisionState.is_dual_reperfusion == true` (LVO + ≤4.5h)
   - Verify `decisionState.headline` includes "EVT + IVT"
3. `POST /clinical/scenarios/re-evaluate` with Table 8 override marking an absolute contraindication present
   - Verify `decisionState.effective_ivt_eligibility == "contraindicated"`
   - Verify headline changes to "EVT RECOMMENDED — IVT CONTRAINDICATED"
4. `POST /clinical/scenarios/what-if` with `{"modifications": {"nihss": 22}}`
   - Verify re-evaluation reflects higher NIHSS
5. `GET /clinical/recommendations?section=4.6.1` — verify JSON data loads and filters correctly
6. Check Firebase — verify session has `clinical_context` with `clinician_overrides` audit trail
7. Restart server, same `session_id` — verify session restored from Firebase
