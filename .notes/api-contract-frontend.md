# API Contract — Frontend Developer Brief
Last updated: 2026-03-28

---

## What Changed

### 1. Three endpoints converted from GET → POST

| Old | New | Body |
|---|---|---|
| `GET /clinical/recommendations?section=X` | `POST /clinical/recommendations` | `{ uid, session_id?, section?, category? }` |
| `GET /journal/trials` | `POST /journal/trials` | `{ uid, session_id? }` |
| `GET /journal/figures/{filename}` | `POST /journal/figures` | `{ uid, session_id?, filename }` |

### 2. `/journal/trials` response shape changed

Was an array. Now:
```json
{ "session_id": "...", "trials": [ ... ] }
```

---

## Universal Rules

### uid — required on every POST request, never on GET
Every POST body must include `uid`. The backend returns **401** if missing.

The only GET requests in the entire API are health checks (`/health`, `/checker`).
Health checks are intentionally open — no auth needed, used by monitoring/load balancers.

**apiClient update required:** stop injecting uid on GET requests. Inject it on POST only.
All data endpoints are POST — this means uid is effectively required on every real call.

### session_id — always include it after the first call
`session_id` is optional on the first call. If omitted, the backend creates one (UUID)
and returns it in the response. **From that point on, every follow-up call in the same
session must include that session_id.**

---

## session_id Lifecycle — This Is Critical

The session_id is what ties a conversation together on the backend. It is used for:
- Loading prior clinical context for re-evaluate and what-if calls
- Persisting the audit trail to Firebase
- Associating QA answers with the patient scenario they were asked about

### When to KEEP the same session_id
- All calls within the same patient scenario (scenarios → what-if → re-evaluate → QA)
- Follow-up questions in the same clinical conversation
- Any call the user makes without explicitly starting something new

### When to CREATE a new session_id (i.e. send blank or omit it)
- User clicks "New Patient" / "New Scenario" / "New Conversation"
- User explicitly navigates away to start a fresh case
- A new sales simulation session begins for a different physician

**If you reuse a session_id from a previous patient, the backend will load the wrong
clinical context for re-evaluate and what-if calls — this is a patient safety issue.**

---

## The Full Pattern (mirrors /chat/stream)

```
Step 1 — First call, no session yet
  POST /clinical/scenarios
  { "uid": "firebase-uid", "text": "72yo male, NIHSS 14..." }

  ← 200 { "session_id": "550e8400-e29b-41d4-a716-446655440000", "parsedVariables": {...}, ... }

  → Store session_id. Associate it with this patient/conversation in your local state.

Step 2 — Follow-up call, same patient
  POST /clinical/scenarios/what-if
  { "uid": "firebase-uid", "session_id": "550e8400-e29b-41d4-a716-446655440000", "modifications": {"nihss": 22} }

  ← 200 { "session_id": "550e8400-e29b-41d4-a716-446655440000", ... }

Step 3 — User asks a clinical question about the same patient
  POST /clinical/qa
  { "uid": "firebase-uid", "session_id": "550e8400-e29b-41d4-a716-446655440000", "question": "What BP targets apply?" }

  ← 200 { "session_id": "550e8400-e29b-41d4-a716-446655440000", ... }

Step 4 — User starts a NEW patient case
  POST /clinical/scenarios
  { "uid": "firebase-uid", "text": "55yo female, NIHSS 8..." }
  ← NO session_id in body — backend creates a new one

  ← 200 { "session_id": "a3f8c120-...", ... }  ← new session, store it
```

---

## Endpoint Reference

### Clinical (`/clinical`)
| Endpoint | Body fields | Returns `session_id` |
|---|---|---|
| `POST /clinical/scenarios` | `uid`, `session_id?`, `text` | ✓ |
| `POST /clinical/scenarios/parse` | `uid`, `session_id?`, `text` | ✓ |
| `POST /clinical/scenarios/re-evaluate` | `uid`, `session_id` (required), `overrides` | ✓ |
| `POST /clinical/scenarios/what-if` | `uid`, `session_id?`, `modifications`, `baseText?` | ✓ |
| `POST /clinical/qa` | `uid`, `session_id?`, `question`, `context?` | ✓ |
| `POST /clinical/qa/validate` | `uid`, `session_id?`, `question`, `answer`, `feedback` | ✓ |
| `POST /clinical/recommendations` | `uid`, `session_id?`, `section?`, `category?` | ✓ |
| `GET /clinical/health` | — | open, no auth |

### Journal Search (`/journal`)
| Endpoint | Body fields | Returns `session_id` |
|---|---|---|
| `POST /journal/search` | `uid`, `session_id?`, `query` | ✓ |
| `POST /journal/search/fast` | `uid`, `session_id?`, `query` | ✓ |
| `POST /journal/search/deep` | `uid`, `session_id?`, `query` | ✓ |
| `POST /journal/search/related` | `uid`, `session_id?`, `query` | ✓ |
| `POST /journal/search/structured` | `uid`, `session_id?`, + filter fields | ✓ |
| `POST /journal/trials` | `uid`, `session_id?` | ✓ (in `{ session_id, trials: [...] }`) |
| `POST /journal/figures` | `uid`, `session_id?`, `filename` | — (FileResponse) |
| `GET /journal/health` | — | open, no auth |

### Sales (`/api/`)
| Endpoint | Body fields |
|---|---|
| All POST endpoints | `uid` required — backend validates. `session_id` accepted if included. |
| `GET /sales/health` | open, no auth |

### Devices (orchestrator)
| Endpoint | Body fields |
|---|---|
| `POST /chat/stream` | `uid`, `session_id?`, `message`, `starting_agent?` — unchanged |

---

## Health Checks — Always Open
These are intentionally unauthenticated (used by load balancers and monitoring):
- `GET /clinical/health`
- `GET /journal/health`
- `GET /sales/health`
- `GET /checker`
