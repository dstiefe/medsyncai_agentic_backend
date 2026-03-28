# MedSync AI v2 — Claude Instructions

Every time you are asked to build, modify, or review an agent, engine,
or pipeline in this project, read this file first and follow it exactly.

---

## Project Structure

This file lives at the project root alongside `.env`, `.gitignore`,
and `requirements.txt`. All application code lives inside the
`app/` subfolder.

```
MEDSYNCAI_AGENTIC_VERSION_VS2/   ← project root (this is where CLAUDE.md lives)
├── CLAUDE.md
├── .claude/
│   ├── settings.json
│   └── settings.local.json
├── app/               ← all application code lives here
│   ├── base_agent.py
│   ├── base_engine.py
│   ├── contracts.py
│   ├── orchestrator/
│   │   ├── orchestrator.py
│   │   └── intent_classifier.py
│   └── agents/                 ← all agents/skills live here
│       ├── chain_engine/
│       ├── database_engine/
│       └── vector_engine/
├── dev_log/                     ← session logs, one file per session
│   ├── INDEX.md
│   └── TEMPLATE.md
├── docs/
│   ├── agent-architecture-standards.md
│   └── python-agent-guide.md
├── .env
├── .gitignore
├── medsyncai.json
└── requirements.txt
```

## Key Files

- `app/base_agent.py` — BaseAgent base class
- `app/base_engine.py` — BaseEngine with `_build_return()` contract
- `app/contracts.py` — shared helpers like `find_prior_result()`
- `app/orchestrator/orchestrator.py` — routing and engine registry
- `app/orchestrator/intent_classifier.py` — intent detection

**Do not modify these files unless explicitly asked to.**

---

## Development Workflow

```
1. PLAN   — propose implementation plan before writing any code
2. BUILD  — implement the plan; flag any deviations before making them
3. TEST   — run the live pipeline; report results honestly
4. FIX    — if tests fail, identify root cause before proposing a fix
5. LOG    — after human approval, write dev_log entry
```

### Fix Classification

When a test fails, classify the fix before implementing it:

**PATCH** — fixes the symptom for this specific case only. Do not use.
Always identify the root cause and propose a systematic fix instead.

**SYSTEMATIC** — fixes the root cause so the same class of issue
cannot recur. Requires: root cause identified, class of problem explained,
confirmation no similar issues exist elsewhere, test that would have caught this.

**SOURCE DATA** — the logic was correct, the data was wrong.
Fix is to correct a reference file, JSON source, or ontology entry — not code.
Requires: exact file and field identified, all similar records checked.

Never implement a fix without classifying it first.

---

## Developer Log

A log of every development session lives in `dev_log/`.

### At the START of every session
Read `dev_log/INDEX.md` and the 3 most recent session files.
Note any open issues or "next session" items relevant to current work.

### At the END of every session (after human approval)
1. Create `dev_log/YYYY-MM-DD_brief-description.md` using `dev_log/TEMPLATE.md`
2. Update `dev_log/INDEX.md` with a one-line entry for this session

Do not write the log entry until work is tested and confirmed by the human.
A log entry records completed, verified work — not attempts.

---

## Testing Protocol

"Run the tests" always means this.

### Start the server
```bash
uvicorn app.main:app --reload --port 8000
```

### Run a test
Send a POST request to `/chat/stream` with a JSON body:
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "your test query here"}'
```

### Report format
After every test the Developer must report all three of these — no exceptions:

```
INTENT CLASSIFIER:   <intent label returned>
ENGINE ROUTING:      <engine selected>
RESPONSE:            <final response text>
```

If any of the three is missing or errored, that is a test failure and must go through the Fix process before proceeding.

---

## Naming Convention — agents/ = skills/

This project uses `app/agents/` as the root folder for all agents.
In all architecture standards, substitute `app/agents/` wherever
you see `skills/`. The structure and rules are identical.

```
app/
└── agents/                    ← this is the skills/ folder
    ├── chain_engine/           ← each subfolder is one agent/skill
    ├── database_engine/
    └── vector_engine/
```

---

## Inheritance Chain

Every engine must follow this chain:

```
BaseAgent
  └── BaseEngine
        └── YourNewEngine
```

---

## Every Engine Folder Has This Structure

```
app/agents/
└── your_engine/
    ├── SKILL.md                ← process only — how the agent reasons
    ├── references/             ← domain knowledge only
    │   ├── field_ontology.md   ← data fields, types, valid values
    │   ├── output_schema.md    ← mirrors _build_return() shape
    │   └── *.md or *.json      ← other domain knowledge files
    └── scripts/                ← deterministic Python only
        └── *.py
```

Sub-agents live inside their parent engine folder:

```
app/agents/
└── chain_engine/
    ├── SKILL.md
    ├── references/
    ├── scripts/
    └── sub_agents/
        ├── query_classifier/
        │   ├── SKILL.md
        │   └── references/
        └── chain_builder/
            ├── SKILL.md
            └── references/
```

---

## The Three-Layer Rule — Always Enforce This

### SKILL.md — Process Only
Contains: agent role, step-by-step reasoning, pointers to reference
files, output format instructions, worked examples.

Does NOT contain: thresholds, criteria, field definitions, valid values,
schemas, or any domain knowledge that would change when rules update.

### references/ — Domain Knowledge Only
Contains: criteria and rules, field ontologies, output schemas,
taxonomies, glossaries, worked examples, JSON lookup tables.

Does NOT contain: reasoning instructions, process steps, or code.

### scripts/ — Deterministic Code Only
Contains: threshold matching, schema validation, score calculation,
data parsing. Always produces the same output for the same input.

Does NOT contain: LM calls or probabilistic logic.

**The test for references/ vs SKILL.md:**
If a clinical guideline, rule, or policy changes — does this content
need to change? If yes → references/. If it's about how to reason → SKILL.md.

**The test for scripts/ vs LM:**
Can this be unit tested with a guaranteed correct output?
If yes → Python script. If it requires language understanding → LM.

---

## Engine Template

When creating a new engine, always use this template:

```python
import os
from pathlib import Path
from app.base_engine import BaseEngine

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")

class NewEngine(BaseEngine):
    def __init__(self):
        super().__init__(name="new_engine", skill_path=SKILL_PATH)

    async def run(self, input_data: dict, session_state: dict) -> dict:

        # Load skill + only the references this engine needs
        system = self.load_skill(refs=["field_ontology", "output_schema"])

        # Pipeline logic here
        # Use self.load_reference("filename") for single reference files
        # Use scripts/ for any deterministic matching or validation

        return self._build_return(
            status="complete",
            result_type="...",
            data={},
            classification={},
            confidence=0.9,
        )
```

---

## _build_return() Output Contract

Every engine must return this shape via `_build_return()`:

```python
{
    "status": "complete" | "error" | "needs_clarification",
    "engine": "engine_name",
    "result_type": "...",
    "data": { ... },
    "classification": { ... },
    "confidence": 0.0–1.0
}
```

Create an `output_schema.md` in every engine's references/ that
documents the specific `data` and `classification` shapes for that engine.
The QC agent for that engine validates against this schema.

---

## Wiring a New Engine

When creating a new engine, these files always need updating:

| File | What to add |
|---|---|
| `app/orchestrator/orchestrator.py` L40-66 | Import engine + add to `_get_tool_registry()` |
| `app/orchestrator/orchestrator.py` L84-99 | Map intent(s) to engine in `INTENT_ENGINE_MAP` |
| `app/orchestrator/intent_classifier.py` | Add new intent label |
| `app/output_agents/` | Create matching output agent if needed |
| Engine `routes.py` | Apply `require_auth` dependency (see API Route Standards below) |

Always check these five locations. Never leave a new engine unwired.

---

## API Route Standards — Always Enforce This

Every engine that exposes REST routes must follow these rules.

### Authentication
All routes must use the shared `require_auth` dependency:

```python
from fastapi import APIRouter, Depends
from app.shared.auth import require_auth

router = APIRouter(prefix="/your-engine", tags=["your-engine"], dependencies=[Depends(require_auth)])
```

`require_auth` validates that every POST/PUT/PATCH request body contains `uid` and
creates a `session_id` if one is not provided. It attaches both to `request.state`.

### POST only — no GET for authenticated data
All data endpoints must be POST. GET is reserved for health checks only.

```python
# WRONG
@router.get("/results")
async def get_results(uid: str = Query(...)):

# CORRECT
@router.post("/results")
async def get_results(request: ResultsRequest):  # ResultsRequest has uid: str
```

### Every request model includes uid and session_id
```python
class YourRequest(BaseModel):
    uid: str                        # required — 401 if missing
    session_id: Optional[str] = None  # backend creates if blank
    # ... other fields
```

### Every response includes session_id
```python
# Access from request.state (set by require_auth)
@router.post("/results")
async def get_results(request: YourRequest, http_request: Request):
    session_id = http_request.state.session_id
    ...
    return {"session_id": session_id, ...}
```

### Health checks are the only open GET endpoints
```python
@router.get("/health")  # No require_auth — intentionally open
async def health():
    return {"status": "ok"}
```

See `.notes/api-contract-frontend.md` for the full frontend API contract.

---

## Probabilistic vs Deterministic — Always Apply This

**Use Python (scripts/) for:**
- Threshold comparisons (value vs number)
- Boolean logic
- Schema validation
- Score calculation
- Anything that must be auditable and provably correct

**Use the LM for:**
- Extracting structured data from unstructured text
- Parsing ambiguous language
- Judgment calls that cannot be reduced to logic
- Synthesizing findings into narrative

**Never ask an LM to compare a number to a threshold.**

---

## Reference Loading — Two Strategies

### Preload (small reference sets)
```python
system = self.load_skill(refs=["field_ontology", "output_schema"])
```

### On-Demand (large or growing reference sets)
Expose `read_reference` as a tool in the agentic loop.
The agent fetches only what the specific case requires.
See `docs/python-agent-guide.md` for the full loop implementation.

---

## JSON Files in references/

| JSON content | Consumed by |
|---|---|
| Static lookup tables, code mappings | LM — loaded into context via `load_skill()` |
| Criteria / rules database | Python scripts only — LM never sees it directly |

---

## Full Architecture Standards

For complete detail on any of the above, read:

- `docs/agent-architecture-standards.md` — structure rules and checklist
- `docs/python-agent-guide.md` — agentic loop, tools, MCP, QC loop

---

## Checklist Before Submitting Any New Engine

- [ ] Engine extends BaseEngine with `name` and `SKILL_PATH`
- [ ] `async def run()` implemented and returns via `_build_return()`
- [ ] SKILL.md contains process only — no domain knowledge embedded
- [ ] All domain knowledge is in `references/` files
- [ ] `output_schema.md` exists in references/ and mirrors `_build_return()` data shape
- [ ] All deterministic logic is in `scripts/`, not in LM prompts
- [ ] Engine is wired in `app/orchestrator/orchestrator.py` and `intent_classifier.py`
- [ ] Output agent created in `app/output_agents/` if needed
- [ ] Sub-agents (if any) each have their own SKILL.md and references/
- [ ] Routes use `require_auth` dependency — `dependencies=[Depends(require_auth)]` on router
- [ ] All data endpoints are POST — no GET for authenticated data
- [ ] Every POST request model has `uid: str` and `session_id: Optional[str] = None`
- [ ] Every POST response includes `session_id` from `http_request.state.session_id`
- [ ] Dev log entry written and INDEX.md updated

---

## Testing Protocol — AIS Clinical Engine

All AIS clinical engine changes must be tested via the live pipeline.

### Start Server
```
uvicorn app.main:app --port 8000
```

### Test Command
```
curl -s -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"<query>","uid":"test_user","session_id":"<unique_id>"}'
```

### What to Report

For every test query, report:
1. **Intent** — what `intent_classifier` returned (visible in server console)
2. **Routing** — which engine/agent handled it (visible in SSE status events)
3. **Response** — the `final_chunk` content returned to the user

### Standard Test Queries

| ID | Query | Expected Path |
|---|---|---|
| OOS-1 | "How do I manage ICH?" | intent→clinical_support → router→out_of_scope → decline message |
| INS-1 | "65yo, NIHSS 18, M1 occlusion, LKW 2h" | intent→clinical_support → router→in_scope → reperfusion_agent |
| INS-2 | "What are the BP targets during AIS?" | intent→clinical_support → router→in_scope → bp_metabolic_agent |
| DEV-1 | Any non-device query outside AIS | intent→general or knowledge_base (does NOT reach AIS engine) |