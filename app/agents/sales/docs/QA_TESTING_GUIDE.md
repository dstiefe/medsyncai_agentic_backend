# QA Testing Guide — MedSync Sales Simulation Engine

## 1. Environment Setup

### Prerequisites
- Python 3.13+
- API key for Anthropic or OpenAI

### Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### Environment Variables
Create `backend/.env`:
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...          # optional, only if using OpenAI
```

### Build Vector Index
```bash
cd backend
python -m data_pipeline.index_vector_db
```
Verify: `data/vector_index/chroma_db/` directory exists and collection contains 2,243 chunks.

### Start Server
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Startup logs should confirm:
- Loaded 224 devices
- Loaded 2,243 document chunks
- Loaded manufacturers
- Loaded physician dossiers

### API Documentation
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

---

## 2. API Endpoints Reference

### Health & System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check with loaded data counts |
| GET | `/api/info` | App info and configuration |
| GET | `/` | Root welcome |

### Devices
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/devices/` | List devices (filter by manufacturer/category) |
| GET | `/api/devices/search?q={query}` | Full-text device search |
| GET | `/api/devices/{device_id}` | Single device with specs |
| GET | `/api/devices/{device_id}/compatible` | Compatible devices |
| GET | `/api/devices/manufacturers` | All manufacturers |
| GET | `/api/devices/categories` | All device categories |

### Simulations
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/simulations/create` | Create new simulation session |
| POST | `/api/simulations/{session_id}/turn` | Process one conversation turn |
| GET | `/api/simulations/{session_id}` | Get session state + turn history |
| GET | `/api/simulations/{session_id}/score` | Aggregated scoring summary |
| POST | `/api/simulations/{session_id}/end` | End session, return final scores |
| GET | `/api/simulations/` | List active sessions |
| GET | `/api/simulations/physicians/available` | Available physician profiles |

### Scoring
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scoring/dimensions` | All 7 scoring dimensions with metadata |
| GET | `/api/scoring/{session_id}/detail` | Per-turn scoring breakdown |

### Knowledge QA
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/qa/ask` | Answer question from knowledge base (RAG) |
| GET | `/api/qa/stats` | Knowledge base statistics |

### Meeting Prep
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/meeting-prep/generate` | Generate intelligence brief |
| GET | `/api/meeting-prep/{prep_id}` | Get meeting prep session |
| POST | `/api/meeting-prep/{prep_id}/rehearse` | Launch rehearsal simulation |

### Assessment
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/assessment/generate` | Generate structured assessment |
| POST | `/api/assessment/{assessment_id}/submit` | Submit answers for scoring |

### Procedure Workflow
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/workflow/stacks` | List procedural stacks |
| GET | `/api/workflow/stacks/{index}` | Get single procedural stack |

### Rep Activity
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reps/register` | Register or update rep profile |
| POST | `/api/reps/{rep_id}/log` | Log activity |
| GET | `/api/reps/{rep_id}` | Get rep profile + history |

---

## 3. Simulation Modes

### Mode 1: Competitive Sales Call (`competitive_sales_call`)
AI plays a physician receiving a sales pitch. Asks probing technical questions, raises objections grounded in device data and trial evidence. References the physician's current device stack.

### Mode 2: Product Knowledge (`product_knowledge`)
Two sub-modes:
- **Conversational Quiz** — natural Q&A, scored after conversation ends
- **Structured Assessment** — category-by-category (Specs, Clinical, IFU, Competitive, Safety, Workflow, Literature, Troubleshooting, Reimbursement, Regulatory)

### Mode 3: Competitor Deep Dive (`competitor_deep_dive`)
AI plays a competitor sales rep using factual competitive claims from actual trials. Challenges the user to counter claims with evidence.

### Mode 4: Objection Handling (`objection_handling`)
AI presents 8-10 realistic objections sequentially across categories: STATUS_QUO, EVIDENCE_CURRENCY, FORMULARY_CONSTRAINT, ADVERSE_EXPERIENCE, CLINICAL_CHALLENGE, COMPETITIVE_PRESSURE, COST_BENEFIT, WORKFLOW_INTEGRATION, TRAINING_SUPPORT, VENDOR_RELATIONSHIP. Pushes back on weak answers.

---

## 4. Physician Profiles

6 built-in profiles with distinct behaviors:

| Profile ID | Name | Specialty | Hospital | Cases/yr | Style |
|------------|------|-----------|----------|----------|-------|
| `dr_chen` | Dr. Chen | Neurointerventional | Academic | 120 | Evidence-driven |
| `dr_rodriguez` | Dr. Rodriguez | Neurointerventional Radiology | Community | 60 | Pragmatic |
| `dr_park` | Dr. Park | Neurosurgery | Community | 90 | Conservative, brand-loyal |
| `dr_okafor` | Dr. Okafor | Neurointerventional | Academic | 150 | Innovative |
| `dr_walsh` | Dr. Walsh | Neurointerventional | Rural | 35 | Learning-oriented |
| `dr_nakamura` | Dr. Nakamura | Stroke Neurology | Academic | 200 referrals | Referral-focused |

---

## 5. Scoring System

### 7 Dimensions (Equal Weight: 1/7 each)

**Deterministic (verified against actual data):**
1. **Clinical Accuracy** — claims checked vs IFU chunks and literature
2. **Specification Accuracy** — device numbers verified vs devices.json
3. **Regulatory Compliance** — on-label/off-label vs IFU indications

**LLM-Evaluated (behavioral assessment):**
4. **Competitive Knowledge** — awareness of competitor products and claims
5. **Objection Handling** — evidence quality and persuasiveness
6. **Procedural Workflow** — device-system interaction understanding
7. **Closing Effectiveness** — conversational progression toward next steps

### Score Scale
- Raw rubric: 0-3 (0 = major errors, 3 = excellent)
- Normalized: 0.0-1.0 (raw / 3)
- Per-turn scores aggregated to session averages
- Trend tracking across turns

---

## 6. Test Procedures

### 6.1 Smoke Test — System Health

```bash
# Health check
curl http://localhost:8000/api/health

# Expected: 200 with device_count, chunk_count, manufacturer_count
```

```bash
# KB stats
curl http://localhost:8000/api/qa/stats

# Expected: total_chunks=2243, source_types breakdown, manufacturers list
```

```bash
# List physicians
curl http://localhost:8000/api/simulations/physicians/available

# Expected: 6 physician profiles
```

```bash
# List devices
curl "http://localhost:8000/api/devices/?limit=5"

# Expected: 200 with device list
```

### 6.2 Device API Tests

```bash
# Search devices
curl "http://localhost:8000/api/devices/search?q=Trevo"

# Get specific device
curl http://localhost:8000/api/devices/177

# Get compatible devices
curl "http://localhost:8000/api/devices/177/compatible?direction=all"

# List manufacturers
curl http://localhost:8000/api/devices/manufacturers

# List categories
curl http://localhost:8000/api/devices/categories
```

**Verify:**
- [ ] Search returns relevant results (Trevo devices for "Trevo" query)
- [ ] Device detail includes full specifications
- [ ] Compatibility check returns physically compatible devices
- [ ] Manufacturers list is non-empty and sorted
- [ ] Categories list includes expected types (stent_retriever, aspiration_catheter, etc.)

### 6.3 Simulation End-to-End Test

```bash
# Step 1: Create session
curl -X POST http://localhost:8000/api/simulations/create \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "competitive_sales_call",
    "physician_profile_id": "dr_chen",
    "rep_company": "Stryker",
    "rep_name": "Test Rep"
  }'

# Save the session_id from response
```

```bash
# Step 2: Send a turn
curl -X POST http://localhost:8000/api/simulations/{session_id}/turn \
  -H "Content-Type: application/json" \
  -d '{"message": "Dr. Chen, I would like to discuss the Trevo NXT stent retriever and how it compares to your current setup."}'
```

```bash
# Step 3: Check session state
curl http://localhost:8000/api/simulations/{session_id}

# Step 4: Check scores
curl http://localhost:8000/api/simulations/{session_id}/score

# Step 5: End session
curl -X POST http://localhost:8000/api/simulations/{session_id}/end
```

**Verify:**
- [ ] Session creates with valid session_id and ACTIVE status
- [ ] Turn returns AI physician response with citations
- [ ] Session state shows turn history
- [ ] Scores are present for all 7 dimensions (0.0-1.0 range)
- [ ] End returns final aggregated scores and COMPLETED status

### 6.4 All Simulation Modes

Repeat 6.3 for each mode:

| Test | Mode | Physician | Company |
|------|------|-----------|---------|
| SIM-1 | `competitive_sales_call` | `dr_chen` | Stryker |
| SIM-2 | `product_knowledge` | `dr_rodriguez` | Penumbra |
| SIM-3 | `competitor_deep_dive` | `dr_park` | Medtronic |
| SIM-4 | `objection_handling` | `dr_okafor` | Stryker |

### 6.5 Knowledge QA Tests

```bash
# Test 1: Device-specific question
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the specifications of the Trevo NXT stent retriever?"}'

# Test 2: Clinical trial question
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the evidence from the DAWN trial for EVT in the 6-24 hour window?"}'

# Test 3: Filtered question
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the contraindications?",
    "filters": {"manufacturer": "Stryker", "source_type": "ifu"}
  }'

# Test 4: Adverse events
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What adverse events have been reported for aspiration catheters?"}'
```

**Verify:**
- [ ] Answers are grounded in sources (no hallucination)
- [ ] Sources list is non-empty with chunk_id, file_name, score
- [ ] IFU/clinical data is quoted verbatim (not paraphrased)
- [ ] Numbers are exact (no rounding)
- [ ] Filtered queries return only matching source types/manufacturers
- [ ] Sparse hybrid results trigger vector fallback (check server logs)

### 6.6 Meeting Prep Tests

```bash
# Generate brief
curl -X POST http://localhost:8000/api/meeting-prep/generate \
  -H "Content-Type: application/json" \
  -d '{
    "physician_name": "Dr. Smith",
    "physician_specialty": "neurointerventional_surgery",
    "hospital_type": "academic",
    "annual_case_volume": 100,
    "rep_company": "Stryker",
    "physician_device_ids": [177, 178],
    "meeting_context": "First meeting, exploring new stent retrievers"
  }'
```

**Verify:**
- [ ] Brief includes device comparisons (spec advantages/disadvantages)
- [ ] Competitive claims are populated
- [ ] Compatibility insights show which devices fit together
- [ ] Migration path is ordered by disruption level
- [ ] Talking points include clinical evidence (if retriever available)
- [ ] Objection playbook has 4+ objections with responses

### 6.7 Scoring Detail Tests

```bash
# After running a simulation with 3+ turns:
curl http://localhost:8000/api/scoring/{session_id}/detail
curl http://localhost:8000/api/scoring/dimensions
```

**Verify:**
- [ ] 7 dimensions returned with names, descriptions, weights
- [ ] Per-turn breakdown shows scores for each dimension
- [ ] Scores are within 0.0-1.0 range
- [ ] Trend data available after 2+ turns

---

## 7. Error Case Tests

### 7.1 Invalid Input

```bash
# Invalid mode
curl -X POST http://localhost:8000/api/simulations/create \
  -H "Content-Type: application/json" \
  -d '{"mode": "invalid_mode", "physician_profile_id": "dr_chen", "rep_company": "Stryker"}'
# Expected: 400 or 422

# Invalid physician
curl -X POST http://localhost:8000/api/simulations/create \
  -H "Content-Type: application/json" \
  -d '{"mode": "competitive_sales_call", "physician_profile_id": "dr_fake", "rep_company": "Stryker"}'
# Expected: 404 or 400

# Empty question
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"question": ""}'
# Expected: 400

# Non-existent session
curl http://localhost:8000/api/simulations/nonexistent_session
# Expected: 404

# Non-existent device
curl http://localhost:8000/api/devices/999999
# Expected: 404
```

### 7.2 Session Lifecycle

```bash
# Turn on ended session (should fail)
# First end a session, then try to send a turn
curl -X POST http://localhost:8000/api/simulations/{session_id}/end
curl -X POST http://localhost:8000/api/simulations/{session_id}/turn \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'
# Expected: 400 (session already ended)
```

---

## 8. RAG Quality Checklist

| Test ID | Query | Expected Behavior |
|---------|-------|-------------------|
| RAG-1 | "Trevo NXT specifications" | Returns Stryker IFU chunks, verbatim specs |
| RAG-2 | "DAWN trial results" | Returns clinical_trial chunks, methods_results section |
| RAG-3 | "ACE 68 contraindications" | Returns Penumbra IFU, contraindications section |
| RAG-4 | "adverse events stent retrievers" | Returns adverse_event chunks from MAUDE/FDA |
| RAG-5 | "balloon guide catheter flow rates" | Returns specification chunks with exact numbers |
| RAG-6 | Generic question with few keyword hits | Triggers vector fallback (< 5 hybrid results) |

---

## 9. Data Integrity Checks

```bash
# Verify ChromaDB collection count
python -c "
import chromadb
client = chromadb.PersistentClient(path='data/vector_index/chroma_db')
col = client.get_collection('document_chunks')
print(f'Collection count: {col.count()}')
# Expected: 2243
"
```

```bash
# Verify device count
python -c "
import json
with open('data/devices.json') as f:
    d = json.load(f)
print(f'Devices: {len(d[\"devices\"])}')
# Expected: 224
"
```

```bash
# Test vector search directly
python -c "
import chromadb
client = chromadb.PersistentClient(path='data/vector_index/chroma_db')
col = client.get_collection('document_chunks')
# Metadata filter test
results = col.get(where={'manufacturer': {'\\$eq': 'Stryker'}}, limit=3, include=['metadatas'])
print(f'Stryker chunks: {len(results[\"ids\"])}')
for m in results['metadatas']:
    print(f'  {m[\"file_name\"]} / {m[\"section_hint\"]}')
"
```

---

## 10. Known Gotchas

1. **Sessions are in-memory only.** Server restart loses all active sessions.
2. **Turn limit is 20.** Sessions block new turns after 20.
3. **Citation format is `[TYPE:reference]`.** Must be exact for parsing.
4. **Device IDs are integers** in devices.json but **strings** in compatibility_matrix.
5. **LLM API key must be valid** before server startup or LLM-dependent endpoints will 500.
6. **CORS allows all origins** (`["*"]`) — not production-ready.
7. **Windows encoding:** Console output may fail on Unicode characters (arrows, checkmarks). Use `encoding="utf-8"` for file I/O.
8. **ChromaDB cosine distance:** Returned as distance (0 = identical), convert to similarity with `1.0 - distance`.
9. **Verbatim rule:** IFU, 510k, recall, MAUDE, and clinical trial data must never be paraphrased or rounded in QA answers.
10. **Score normalization:** Raw 0-3 rubric scores are divided by 3 to produce 0.0-1.0 scale.
