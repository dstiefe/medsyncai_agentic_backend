---
title: Sales Training Engine Output Schema
description: Documents the _build_return() data shapes for the sales training engine
---

# Output Schema

## Engine Redirect (from SSE pipeline)

When triggered via the main `/chat/stream` endpoint, the engine returns:

```json
{
  "status": "complete",
  "engine": "sales_training_engine",
  "result_type": "sales_redirect",
  "data": {
    "message": "This query is related to sales training. Redirecting to the Sales Training interface.",
    "redirect": true,
    "original_query": "<the user's query>"
  },
  "classification": {
    "domain": "sales",
    "action": "redirect_to_sales_ui"
  },
  "confidence": 0.95
}
```

## REST API Response Shapes

The REST endpoints return standard FastAPI/Pydantic responses. See each route
file for request/response models. Key shapes:

### Simulation Session
```json
{
  "session_id": "sim_abc12345",
  "mode": "competitive_sales_call",
  "status": "active",
  "physician_profile": { ... },
  "rep_company": "Medtronic",
  "turns": [ ... ],
  "created_at": "2026-03-15T10:00:00Z"
}
```

### Turn Score
```json
{
  "turn_number": 3,
  "dimension_scores": {
    "clinical_accuracy": 0.75,
    "spec_accuracy": 0.85,
    "regulatory_compliance": 0.90,
    "competitive_knowledge": 0.60,
    "objection_handling": 0.70,
    "procedural_workflow": 0.65,
    "closing_effectiveness": 0.55
  },
  "overall": 0.72,
  "feedback": { ... },
  "flags": []
}
```

### Intelligence Brief
```json
{
  "brief_id": "brief_abc12345",
  "physician_name": "Dr. Chen",
  "current_stack_summary": [ ... ],
  "device_comparisons": [ ... ],
  "competitive_claims": [ ... ],
  "compatibility_insights": [ ... ],
  "migration_path": [ ... ],
  "talking_points": [ ... ],
  "objection_playbook": [ ... ]
}
```

### Scoring Dimensions (7)
- `clinical_accuracy` — Clinical knowledge correctness
- `spec_accuracy` — Device specification accuracy
- `regulatory_compliance` — IFU/regulatory adherence
- `competitive_knowledge` — Competitor device awareness
- `objection_handling` — Response to physician concerns
- `procedural_workflow` — Understanding of procedural context
- `closing_effectiveness` — Ability to advance the sale
