# MedSync AI — Engine Map for Non-Developers

> Hand this document to Claude at the start of any session where you need to make changes.
> It tells Claude exactly where everything lives so it can find and edit the right files.

---

## How to Use This Document

Paste the following into your Claude chat before describing what you want to change:

> "Read ENGINE_MAP.md at the project root, then help me with: [describe your task]"

Claude will use this map to find the correct files without exploring the whole codebase.

---

## The Three Engines at a Glance

| Engine | What it does | Root folder |
|---|---|---|
| **Clinical** | AIS stroke decision support for clinicians | `app/agents/clinical/` |
| **Devices** | Equipment lookup, compatibility, specs for device queries | `app/agents/devices/` |
| **Sales** | Sales rep training simulations and meeting prep | `app/agents/sales/` |

Each engine is self-contained inside its folder. Changing one does not affect the others.

---

## How a User Message Gets Routed

```
User message
    │
    ▼
Orchestrator (orchestrator.py)
    │
    ├─ Domain Classifier → "clinical" → redirected to clinical interface
    │                    → "sales"    → redirected to sales interface
    │                    → (other)    → continues in devices pipeline
    │
    ▼
Intent Classifier (for device queries)
    │
    ├─ equipment_compatibility / device_discovery  → Chain Engine
    ├─ specification_lookup / device_search / etc. → Database Engine
    ├─ documentation / knowledge_base              → Vector Engine
    └─ clinical_support                            → Clinical Engine
```

The file that controls all routing decisions:
`app/orchestrator/orchestrator.py`

---

## Clinical Engine

**Purpose:** Stroke (AIS) clinical decision support — IVT and EVT eligibility, BP targets, checklists.

### Entry Point
`app/agents/clinical/ais_clinical_engine/engine.py`

### All Clinical Engine Files

```
app/agents/clinical/
├── ais_clinical_engine/          ← main clinical engine
│   ├── engine.py                 ← ENTRY POINT — starts here
│   ├── routes.py                 ← HTTP route definitions
│   ├── agents/
│   │   ├── ivt_orchestrator.py   ← IVT (tPA) decision logic
│   │   ├── ivt_recs_agent.py     ← IVT recommendation agent
│   │   ├── checklist_agent.py    ← clinical checklist generation
│   │   ├── table4_agent.py       ← Table 4 guideline agent
│   │   └── table8_agent.py       ← Table 8 guideline agent
│   ├── services/
│   │   ├── decision_engine.py    ← core eligibility decision logic
│   │   ├── rule_engine.py        ← rule evaluation
│   │   ├── nlp_service.py        ← natural language parsing
│   │   └── qa_service.py         ← quality assurance checks
│   ├── models/
│   │   ├── rules.py              ← rule data structures
│   │   ├── clinical.py           ← clinical data models
│   │   ├── checklist.py          ← checklist models
│   │   ├── table4.py             ← Table 4 models
│   │   └── table8.py             ← Table 8 models
│   └── data/
│       ├── recommendations.json  ← AIS guideline recommendations
│       ├── evt_rules.json        ← EVT eligibility rules
│       ├── ivt_rules.json        ← IVT eligibility rules
│       ├── guideline_knowledge.json ← full guideline knowledge base
│       └── checklist_templates.json ← checklist templates
│
└── clinical_output_agent/        ← formats clinical responses
    ├── engine.py                 ← output formatting logic
    ├── SKILL.md                  ← agent instructions
    └── references/
        ├── clinical_rules.md     ← output rules (COR/LOE formatting)
        ├── routine_format.md     ← standard response format
        └── edge_case_format.md   ← format for edge cases
```

### What to Change for Common Clinical Tasks

| Task | File(s) to edit |
|---|---|
| Change how a recommendation is worded to the user | `clinical_output_agent/engine.py` |
| Change output formatting rules | `clinical_output_agent/references/clinical_rules.md` |
| Add or update a guideline recommendation | `data/recommendations.json` |
| Change EVT eligibility rules | `data/evt_rules.json` |
| Change IVT eligibility rules | `data/ivt_rules.json` |
| Change how the engine interprets a patient case | `services/decision_engine.py` |
| Change the IVT decision flow | `agents/ivt_orchestrator.py` |
| Change checklist content | `data/checklist_templates.json` |

---

## Devices Engine

**Purpose:** Answer questions about medical devices — compatibility between products, spec lookups, documentation search.

### Entry Point
`app/agents/devices/` — the engine used depends on query type (chain, database, or vector — see routing table above).

### All Devices Engine Files

```
app/agents/devices/
├── intent_classifier/            ← classifies what kind of device query it is
│   ├── engine.py
│   ├── SKILL.md
│   └── references/intent_types.md
│
├── query_planner/                ← decides which engines to use
│   ├── engine.py
│   ├── SKILL.md
│   └── references/
│       ├── engines.md
│       └── strategies.md
│
├── equipment_extraction/         ← pulls device names from user message
│   ├── engine.py
│   ├── SKILL.md
│   └── references/manufacturers.md
│
├── generic_prep/                 ← prepares device data before routing
│   ├── engine.py
│   ├── SKILL.md
│   ├── scripts/generic_prep_python.py
│   └── references/
│       ├── field_mapping.md
│       └── resolution_rules.md
│
├── generic_device_structuring/   ← structures device data into standard format
│   ├── engine.py
│   ├── SKILL.md
│   └── references/
│       ├── device_types.md
│       ├── attributes.md
│       └── examples.md
│
├── chain_engine/                 ← compatibility chain queries (A works with B?)
│   ├── engine.py  (see chain_builder.py, chain_analyzer.py, etc.)
│   ├── chain_builder.py
│   ├── chain_analyzer.py
│   ├── chain_text_builder.py
│   ├── chain_summary.py
│   ├── query_classifier.py
│   └── quality_check.py
│
├── database_engine/              ← structured spec/catalog queries
│   ├── engine.py
│   ├── query_spec_agent.py
│   └── query_executor.py
│
├── vector_engine/                ← documentation/knowledge search
│   └── engine.py
│
├── chain_output_agent/           ← formats compatibility responses
│   ├── engine.py
│   ├── SKILL.md
│   └── references/
│       ├── compatibility_check.md
│       ├── device_discovery.md
│       ├── stack_validation.md
│       ├── response_framing.md
│       ├── query_modes.md
│       └── shared_guidelines.md
│
├── database_output_agent/        ← formats spec/catalog responses
│   ├── engine.py
│   ├── SKILL.md
│   └── references/
│       ├── format_rules.md
│       └── shared_guidelines.md
│
├── vector_output_agent/          ← formats documentation responses
│   ├── engine.py
│   ├── SKILL.md
│   └── references/prognosis_rules.md
│
├── synthesis_output_agent/       ← combines results from multiple engines
│   ├── engine.py
│   └── SKILL.md
│
└── clarification_output_agent/   ← asks user for missing device info
    ├── engine.py
    └── SKILL.md
```

### What to Change for Common Devices Tasks

| Task | File(s) to edit |
|---|---|
| Change how compatibility answers are worded | `chain_output_agent/engine.py` |
| Change compatibility response rules | `chain_output_agent/references/compatibility_check.md` |
| Change how spec lookups are formatted | `database_output_agent/references/format_rules.md` |
| Add a new device type or attribute | `generic_device_structuring/references/device_types.md` |
| Change how manufacturers are recognized | `equipment_extraction/references/manufacturers.md` |
| Change how the engine decides which sub-engine to use | `query_planner/engine.py` |
| Change intent classification (what kind of query is this?) | `intent_classifier/engine.py` |

---

## Sales Engine

**Purpose:** Train sales reps through simulated physician conversations, meeting prep, product knowledge quizzes, and scoring.

### Entry Point
`app/agents/sales/sales_training_engine/engine.py`

### All Sales Engine Files

```
app/agents/sales/sales_training_engine/
├── engine.py                     ← ENTRY POINT — starts here
├── SKILL.md                      ← agent reasoning instructions
│
├── routes/                       ← HTTP API endpoints
│   ├── simulations.py            ← simulation start/continue/end endpoints
│   ├── training.py               ← training/quiz endpoints
│   ├── prep.py                   ← meeting prep endpoints
│   └── devices.py                ← device data endpoints
│
├── services/                     ← business logic
│   ├── simulation_orchestrator.py ← drives the simulation conversation loop
│   ├── scoring_service.py        ← scores rep performance
│   ├── assessment_service.py     ← generates performance assessments
│   ├── meeting_prep_service.py   ← builds meeting prep packages
│   ├── dossier_service.py        ← physician dossier lookup
│   ├── device_service.py         ← device data service
│   ├── compatibility_engine.py   ← device compatibility for sales context
│   ├── rag_service.py            ← document retrieval for knowledge questions
│   ├── data_loader.py            ← loads JSON data files
│   ├── persistence_service.py    ← saves/loads simulation state
│   ├── system_prompts.py         ← all LLM system prompts
│   └── llm_adapter.py            ← LLM API wrapper
│
├── models/                       ← data structures
│   ├── simulation_state.py       ← tracks state of an active simulation
│   ├── physician_profile.py      ← physician persona data structure
│   ├── physician_dossier.py      ← physician dossier data structure
│   ├── rep_profile.py            ← sales rep profile
│   ├── device.py                 ← device data structure
│   ├── meeting_prep.py           ← meeting prep data structure
│   └── scoring.py                ← scoring data structure
│
├── rag/                          ← retrieval-augmented generation
│   ├── retrieval.py              ← document chunk retrieval
│   └── citation_manager.py      ← citation tracking
│
├── scripts/
│   ├── score_calculator.py       ← deterministic scoring math
│   └── hybrid_search.py          ← vector + keyword search
│
├── data/                         ← source data files (edit these for content changes)
│   ├── devices.json              ← device catalog for sales
│   ├── physician_dossiers.json   ← physician personas used in simulations
│   ├── competitive_intel.json    ← competitive intelligence data
│   ├── compatibility_matrix.json ← device compatibility data
│   ├── document_chunks.json      ← chunked training documents
│   └── vector_index/
│       ├── faiss_index.bin       ← vector search index (rebuilt from chunks)
│       ├── chunk_metadata.json   ← metadata for each chunk
│       └── index_config.json     ← index configuration
│
├── references/                   ← rules and domain knowledge
│   ├── physician_profiles.md     ← physician persona rules
│   ├── scoring_rubric.md         ← how rep performance is scored
│   ├── objection_patterns.md     ← common physician objections + how to handle
│   ├── competitive_positioning.md ← how to position vs competitors
│   ├── conversational_quiz.md    ← quiz format and rules
│   ├── deep_dive_scenarios.md    ← advanced simulation scenarios
│   ├── meeting_prep_format.md    ← meeting prep output format
│   ├── knowledge_base_rules.md   ← knowledge base query rules
│   └── output_schema.md          ← output data shape
│
└── docs/
    └── QA_TESTING_GUIDE.md       ← testing guide
```

### What to Change for Common Sales Tasks

| Task | File(s) to edit |
|---|---|
| Change how the physician persona behaves in simulation | `services/system_prompts.py` + `references/physician_profiles.md` |
| Add or edit a physician dossier | `data/physician_dossiers.json` |
| Add or edit a device in the sales catalog | `data/devices.json` |
| Change how a rep's score is calculated | `scripts/score_calculator.py` + `references/scoring_rubric.md` |
| Change objection handling guidance | `references/objection_patterns.md` |
| Change competitive positioning content | `data/competitive_intel.json` + `references/competitive_positioning.md` |
| Change meeting prep format or content | `services/meeting_prep_service.py` + `references/meeting_prep_format.md` |
| Change the quiz format | `references/conversational_quiz.md` |
| Change simulation flow (turn-by-turn logic) | `services/simulation_orchestrator.py` |
| Change scoring rules (qualitative criteria) | `references/scoring_rubric.md` |

---

## Shared / Infrastructure Files

These files are used by all engines. Do not modify unless explicitly asked.

```
app/
├── orchestrator/
│   └── orchestrator.py           ← routes messages to the right engine
├── base_engine.py                ← parent class all engines inherit from
├── base_agent.py                 ← parent class for agents
├── contracts.py                  ← shared helper functions
└── engines/shared/
    ├── domain_classifier/        ← decides: clinical vs sales vs devices
    │   └── engine.py
    ├── input_rewriter/           ← cleans up user input before routing
    │   └── engine.py
    └── general_output_agent/     ← formats general (non-engine) responses
        └── engine.py
```

---

## Quick Reference: "I need to change X — which file?"

| What you want to change | File |
|---|---|
| The wording of a clinical recommendation | `engines/clinical/clinical_output_agent/engine.py` |
| A clinical guideline rule (IVT/EVT eligibility) | `engines/clinical/ais_clinical_engine/data/evt_rules.json` or `ivt_rules.json` |
| A physician persona in a sales simulation | `engines/sales/sales_training_engine/data/physician_dossiers.json` |
| The scoring criteria for a sales rep | `engines/sales/sales_training_engine/references/scoring_rubric.md` |
| Device compatibility answer format | `engines/devices/chain_output_agent/references/compatibility_check.md` |
| How a device is described in the catalog | `engines/devices/` — depends on query type (chain/database/vector) |
| Which engine handles a new type of question | `orchestrator/orchestrator.py` (INTENT_ENGINE_MAP) |
| System prompts (what the AI is told to do) | `engines/sales/sales_training_engine/services/system_prompts.py` (sales) or each engine's `SKILL.md` |

---

## Rules Claude Must Follow When Editing This Codebase

1. **Read the file before editing it.** Never modify a file you haven't seen.
2. **Don't change orchestrator.py, base_engine.py, or base_agent.py** unless the task explicitly requires it.
3. **Data changes go in `data/` or `references/` files** — not in the Python code.
4. **Reasoning/process changes go in `SKILL.md`** — not in data files.
5. **Deterministic logic (math, thresholds, validation) goes in `scripts/`** — not in prompts.
6. After any change, report: what file was changed, what line(s), and why.
