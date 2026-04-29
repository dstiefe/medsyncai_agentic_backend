# Clinical API Endpoints

Base URL: `http://<host>:8000/clinical`

---

## Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/clinical/health` | Engine health check |
| `GET` | `/clinical/recommendations` | Browse/filter guideline recommendations |
| `POST` | `/clinical/scenarios` | **Main endpoint** — parse scenario → IVT → EVT → DecisionState |
| `POST` | `/clinical/scenarios/parse` | Parse clinical text only (no evaluation) |
| `POST` | `/clinical/scenarios/re-evaluate` | Apply clinician overrides, recompute DecisionState |
| `POST` | `/clinical/scenarios/what-if` | Modify variables and re-run full pipeline |
| `POST` | `/clinical/qa` | Q&A against guideline recommendations |

---

## Request Bodies

### POST `/clinical/scenarios`

Full evaluation pipeline. Send free-text clinical scenario — backend NLP parses it automatically.

```json
{
  "text": "65yo male, NIHSS 18, M1 occlusion, LKW 2 hours ago",
  "uid": "user_123",
  "session_id": "optional_session_id"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | yes | Free-text clinical scenario |
| `uid` | string | yes | User ID |
| `session_id` | string | no | If omitted, a new session is created |

---

### POST `/clinical/scenarios/parse`

Parse only — returns structured variables, no IVT/EVT evaluation.

```json
{
  "text": "65yo male, NIHSS 18, M1 occlusion, LKW 2 hours ago",
  "uid": "user_123"
}
```

**Response:**

```json
{
  "parsedVariables": { ... }
}
```

---

### POST `/clinical/scenarios/re-evaluate`

Recompute DecisionState with clinician overrides. Does **not** re-run IVT/EVT pipelines.

```json
{
  "session_id": "abc123",
  "uid": "user_123",
  "overrides": {
    "table8_overrides": {
      "rule_id_here": "confirmed_present"
    },
    "none_absolute": false,
    "none_relative": false,
    "none_benefit_over_risk": false,
    "table4_override": null,
    "evt_available": null
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | Session from a prior `/scenarios` call |
| `uid` | string | yes | User ID |
| `overrides.table8_overrides` | object | no | Per-rule overrides: `{ruleId: "confirmed_present" \| "confirmed_absent"}` |
| `overrides.none_absolute` | bool | no | Bulk override: no absolute contraindications |
| `overrides.none_relative` | bool | no | Bulk override: no relative contraindications |
| `overrides.none_benefit_over_risk` | bool | no | Bulk override: no benefit-over-risk items |
| `overrides.table4_override` | bool or null | no | `true` = disabling, `false` = non-disabling, `null` = no override |
| `overrides.evt_available` | bool or null | no | `true` = EVT available, `false` = not available, `null` = not answered |

---

### POST `/clinical/scenarios/what-if`

Modify parsed variables and re-run the **full** IVT + EVT pipeline.

```json
{
  "session_id": "abc123",
  "uid": "user_123",
  "modifications": {
    "nihss": 22,
    "aspects": 7,
    "timeHours": 5.0
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | Session from a prior `/scenarios` call |
| `uid` | string | yes | User ID |
| `modifications` | object | yes | Any `ParsedVariables` fields to override (see below) |

---

### POST `/clinical/qa`

Q&A search against guideline recommendations.

```json
{
  "question": "What are BP targets during AIS?",
  "context": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | yes | Natural language question |
| `context` | object | no | Optional context for scoping the search |

**Response:**

```json
{
  "answer": "Based on 3 relevant guideline recommendation(s): ...",
  "citations": ["Section 4 Rec 1: ..."],
  "relatedSections": ["4", "5"]
}
```

---

### GET `/clinical/recommendations`

Query params (all optional):

| Param | Type | Description |
|-------|------|-------------|
| `section` | string | Filter by section number |
| `category` | string | Filter by category |

**Response:**

```json
{
  "count": 203,
  "recommendations": [ ... ]
}
```

---

### GET `/clinical/health`

No parameters.

**Response:**

```json
{
  "status": "ok",
  "engine": "ais_clinical_engine",
  "recommendations_loaded": 203,
  "services": {
    "nlp_service": "ready",
    "ivt_orchestrator": "ready",
    "rule_engine": "ready (42 rules)",
    "decision_engine": "ready"
  }
}
```

---

## Response Shape (scenarios, re-evaluate, what-if)

All three return `FullEvalResponse`:

```json
{
  "session_id": "abc123",
  "parsedVariables": {
    "age": 65,
    "sex": "male",
    "timeHours": 2.0,
    "nihss": 18,
    "vessel": "M1",
    "side": null,
    "aspects": null,
    "prestrokeMRS": null,
    "wakeUp": null,
    "sbp": null,
    "dbp": null,
    "hemorrhage": null,
    "onAntiplatelet": null,
    "onAnticoagulant": null,
    "isAdult": true,
    "isLVO": true,
    "isAnterior": true,
    "timeWindow": "0-4.5"
  },
  "ivtResult": { },
  "evtResult": { },
  "decisionState": {
    "effective_ivt_eligibility": "eligible | contraindicated | caution | pending",
    "effective_is_disabling": true | false | null,
    "primary_therapy": "IVT | EVT | DUAL | NONE | null",
    "verdict": "ELIGIBLE | NOT_ELIGIBLE | CAUTION | PENDING",
    "is_dual_reperfusion": false,
    "bp_at_goal": true | false | null,
    "bp_warning": null,
    "is_extended_window": false,
    "visible_sections": ["ivt", "evt"],
    "headline": "Patient eligible for IV thrombolysis"
  },
  "notes": [
    {
      "severity": "danger | warning | info",
      "text": "Description of the note",
      "source": "ivt_pipeline"
    }
  ],
  "clinicalChecklists": []
}
```

---

## ParsedVariables — All Fields

These are the fields returned in `parsedVariables` and accepted in `what-if` `modifications`.

| Field | Type | Description |
|-------|------|-------------|
| `age` | int (0-120) | Patient age |
| `sex` | string | Patient sex |
| `timeHours` | float | Hours since last known well |
| `wakeUp` | bool | Wake-up stroke |
| `nihss` | int (0-42) | NIHSS total score |
| `nihssItems` | object | Individual NIHSS components (see below) |
| `vessel` | string | Vessel occlusion: M1, M2, ICA, basilar, ACA, PCA, T-ICA |
| `side` | string | left, right, anterior, basilar |
| `aspects` | int (0-10) | ASPECTS score |
| `prestrokeMRS` | int (0-6) | Pre-stroke modified Rankin Scale |
| `sbp` | int | Systolic blood pressure |
| `dbp` | int | Diastolic blood pressure |
| `hemorrhage` | bool | Hemorrhage present |
| `onAntiplatelet` | bool | On antiplatelet medication |
| `onAnticoagulant` | bool | On anticoagulant medication |
| `sickleCell` | bool | Sickle cell disease |
| `dwiFlair` | bool | DWI-FLAIR mismatch |
| `penumbra` | bool | Salvageable penumbra on perfusion |
| `cmbs` | bool | Cerebral microbleeds present |
| `cmbCount` | int | Number of cerebral microbleeds |
| `ivtGiven` | bool | IV thrombolysis already given |
| `ivtNotGiven` | bool | IV thrombolysis explicitly not given |
| `evtUnavailable` | bool | EVT not available at this center |
| `nonDisabling` | bool | Non-disabling symptoms |
| `recentTBI` | bool | Recent traumatic brain injury |
| `tbiDays` | int | Days since TBI |
| `recentNeurosurgery` | bool | Recent neurosurgery |
| `neurosurgeryDays` | int | Days since neurosurgery |
| `acuteSpinalCordInjury` | bool | Acute spinal cord injury |
| `intraAxialNeoplasm` | bool | Intra-axial CNS neoplasm |
| `extraAxialNeoplasm` | bool | Extra-axial CNS neoplasm |
| `infectiveEndocarditis` | bool | Infective endocarditis |
| `aorticArchDissection` | bool | Aortic arch dissection |
| `cervicalDissection` | bool | Cervical artery dissection |
| `platelets` | int | Platelet count |
| `inr` | float | INR value |
| `aptt` | float | aPTT value |
| `pt` | float | PT value |
| `aria` | bool | Amyloid-related imaging abnormalities |
| `amyloidImmunotherapy` | bool | On amyloid immunotherapy |
| `priorICH` | bool | Prior intracerebral hemorrhage |
| `recentStroke3mo` | bool | Stroke within last 3 months |
| `recentNonCNSTrauma` | bool | Recent non-CNS trauma |
| `recentNonCNSSurgery10d` | bool | Non-CNS surgery within 10 days |
| `recentGIGUBleeding21d` | bool | GI/GU bleeding within 21 days |
| `pregnancy` | bool | Currently pregnant |
| `activeMalignancy` | bool | Active malignancy |
| `extensiveHypodensity` | bool | Extensive hypodensity on CT |
| `moyaMoya` | bool | Moyamoya disease |
| `unrupturedAneurysm` | bool | Unruptured aneurysm |
| `recentDOAC` | bool | Recent DOAC use |

### Computed Fields (read-only, returned in response)

| Field | Type | Description |
|-------|------|-------------|
| `isAdult` | bool | `true` if age >= 18 |
| `isLVO` | bool | `true` if vessel is M1, ICA, basilar, or T-ICA |
| `isAnterior` | bool | `true` if vessel is M1, M2, ICA, or ACA |
| `timeWindow` | string | `"0-4.5"`, `"4.5-9"`, `"9-24"`, or `">24"` |

### NIHSS Items (optional, nested in `nihssItems`)

| Field | Type | Range |
|-------|------|-------|
| `vision` | int | 0-3 |
| `bestLanguage` | int | 0-3 |
| `extinction` | int | 0-2 |
| `motorArmL` | int | 0-4 |
| `motorArmR` | int | 0-4 |
| `motorLegL` | int | 0-4 |
| `motorLegR` | int | 0-4 |
| `facialPalsy` | int | 0-3 |
| `sensory` | int | 0-2 |
| `ataxia` | int | 0-2 |
| `limbAtaxia` | int | 0-2 |
