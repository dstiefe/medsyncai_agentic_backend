# AIS Guideline Scope

The 2026 AHA/ASA Acute Ischemic Stroke (AIS) Guidelines cover the
acute management of ischemic stroke, from pre-hospital recognition
through inpatient stabilization. Questions within scope include
— but are not limited to — these areas:

## In scope

**Recognition and pre-hospital care**
- Stroke awareness, warning signs, public education
- EMS dispatch, pre-hospital triage, bypass protocols
- Stroke center designation and transfer decisions

**Emergency department evaluation**
- Initial clinical assessment, NIHSS scoring
- Imaging: non-contrast CT, CT angiography, CT perfusion, MRI/MRA/DWI
- Laboratory evaluation, blood glucose, coagulation studies
- Disabling vs non-disabling deficit determination

**Acute treatment — IV thrombolysis (IVT)**
- Eligibility, indications, contraindications
- Alteplase and tenecteplase dosing
- Extended time window (3–4.5h, wake-up, unknown time)
- Management of patients on antiplatelets, anticoagulants, DOACs
- Post-IVT monitoring, blood pressure management
- Complications: symptomatic intracranial hemorrhage (sICH),
  orolingual angioedema

**Acute treatment — endovascular thrombectomy (EVT)**
- Eligibility by time window, imaging, NIHSS, ASPECTS, core volume
- Large vessel occlusion (anterior and posterior circulation)
- Basilar artery occlusion
- Device selection, reperfusion grading (TICI)
- Sedation and anesthesia for EVT

**Adjunctive and supportive care**
- Antiplatelet therapy (aspirin, clopidogrel, DAPT) initiation and
  timing
- Blood pressure targets before, during, after reperfusion
- Glucose management, temperature management
- DVT prophylaxis, dysphagia screening, nutrition

**Complications and post-acute care in the first 48–72 hours**
- Hemorrhagic transformation, malignant edema, hemicraniectomy
- Seizure management
- Recurrent stroke prevention initiation

**Special populations**
- Pediatric AIS
- Pregnancy and peripartum
- Patients with prior disability (baseline mRS)

**Systems of care**
- Stroke center capabilities, transfer networks, telemedicine
- Quality metrics and time-to-treatment benchmarks

## Out of scope

Questions NOT covered by these guidelines include:

- Hemorrhagic stroke (ICH, SAH) management — separate guidelines
- Chronic secondary prevention beyond the acute/subacute period
  (long-term statin dosing, lifestyle modification counseling)
- Rehabilitation protocols beyond initial mobilization
- Non-stroke neurological conditions
- General medical topics unrelated to AIS
- Clinical trial methodology or guideline development process
- Drug pharmacology outside stroke-specific dosing
- Insurance, billing, coding, administrative questions

## Scope judgment rule

**`scope` answers ONE question: is this about acute ischemic stroke?**

It does NOT answer "does the AIS guideline cover this specific
drug/concept/device." That second question is a retrieval concern
(Step 4), not an extraction concern (Step 1).

### in_scope

Mark **in_scope** when the question is about acute or early
subacute management of a suspected or confirmed ischemic stroke
patient. This explicitly INCLUDES:

- Questions about specific drugs asked in the AIS context, even
  drugs the guideline may not directly address. Example:
  *"Are GLP-1 receptor agonists beneficial in acute stroke?"* →
  **in_scope** (the question is about AIS). Retrieval will find
  either relevant recs or nothing; when nothing, the renderer
  returns *"the 2026 AIS guideline does not address GLP-1
  receptor agonists."* That is a valid answer, not a scope
  rejection.
- Questions about newer devices, tests, trials, or techniques not
  yet incorporated into the guideline, asked in an AIS context.
  Same pattern as above.
- Questions about AIS subpopulations (pediatric, pregnancy,
  patients with specific comorbidities) even when those
  subpopulations have thin coverage in the guideline.
- Questions asking *what the guideline says* about a specific
  figure, table, or section — those are meta-questions about the
  guideline itself, which is in-scope content.

### out_of_scope

Mark **out_of_scope** ONLY when the question is about something
that is NOT acute ischemic stroke at all:

- Hemorrhagic stroke (ICH, SAH) management — different guideline.
- Non-stroke medicine (heart failure, COPD, diabetes management
  that is not about AIS).
- Non-medical (general knowledge, weather, politics, etc.).
- Chronic outpatient prevention unrelated to the acute/subacute
  stroke event.
- Administrative/billing/coding questions.

### Rule when uncertain

If you are unsure, prefer **in_scope**. A false-negative (marking
an in-scope question as out_of_scope) terminates the pipeline and
denies the clinician any answer. A false-positive (letting an
out-of-scope question through) costs a retrieval pass, and the
renderer will return a clean "guideline does not address this"
response. The cost asymmetry strongly favors in_scope.

### Explicitly do NOT use out_of_scope to mean

- "the guideline doesn't cover this drug"
- "this isn't discussed in the guideline"
- "the clinician named a concept I don't recognize"

All three of those are retrieval-time findings, not scope. If the
question is AIS-adjacent, let retrieval do its job.
