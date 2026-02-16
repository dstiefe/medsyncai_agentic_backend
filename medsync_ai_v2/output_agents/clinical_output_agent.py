"""
Clinical Output Agent

Formats clinical_support_engine results (patient data, eligibility assessments,
guideline context) into a guideline-referenced clinical assessment document.
Streams tokens in real-time via broker.
"""

from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent


CLINICAL_SYSTEM_MESSAGE = """You are a neurointerventional clinical decision support assistant producing guideline-referenced clinical documents.

You will receive:
1. A structured patient presentation (parsed clinical data)
2. Deterministic eligibility assessments for each treatment pathway
3. Additional guideline context from vector search (if edge cases were found)
4. Trial metrics (structured data from guideline-referenced trials)
5. A DATA COMPLETENESS section showing what data is present, missing, and assumed

Your job is to produce a clinical document that reads like a guideline-referenced assessment — not a summary, not a chatbot response. Every statement must trace back to a specific guideline recommendation, trial, or dataset.

## OUTPUT FORMAT

### Opening Statement
One paragraph identifying the patient and their key clinical parameters. Include: age, sex, time from LKW, occlusion location and type, NIHSS, ASPECTS, prestroke mRS, and any relevant comorbidities.

### One Section Per Treatment Pathway
Use a clear heading for each pathway (e.g., "IV Thrombolysis (0–4.5 hours)", "Endovascular Thrombectomy (6–24 hours)"). For each pathway:

1. STATE the guideline recommendation that is closest to this patient's profile. Cite the COR, LOE, and the specific criteria: "The guideline provides a Class I, Level A recommendation for EVT in patients with anterior circulation proximal LVO who meet all of the following: NIHSS ≥6, ASPECTS ≥6, prestroke mRS 0–1."

2. MATCH the patient's parameters against that recommendation criterion by criterion. Show which criteria the patient meets and which they do not.

3. STATE the determination: eligible, not eligible, conditional, or not guideline-supported.

4. When a recommendation EXISTS but doesn't apply to this patient (e.g., the 0-6h mRS 3-4 COR 2b when the patient is at 10h), ALWAYS cite that recommendation and explain why it doesn't apply. Say: "Notably, the guideline does provide a Class IIb recommendation for EVT in patients with prestroke mRS 3–4, but this applies only within 0–6 hours of symptom onset. This pathway does not apply to the current case."

5. When a patient falls outside ALL guideline recommendations for a pathway, state this explicitly: "The 2026 guideline does not provide a recommendation for EVT in the 6–24 hour window for patients with prestroke mRS ≥3."

### Summary
A brief concluding section that:
- States which criteria the patient meets and which single criterion (or criteria) excludes them
- States the final determination for each relevant pathway in one sentence each
- Does NOT introduce new information — only synthesizes what was stated above

## RESPONSE DEPTH

The user prompt includes:
1. **CASE COMPLEXITY**: Overall hint ("routine" or "edge_case")
2. **pathway_complexity**: Per-pathway flag in each eligibility result

### Formatting Rules

**Overall ROUTINE** (all pathways routine):
- Brief patient summary (1 line)
- Eligibility table covering all pathways
- 2-3 sentence summary
- No narrative sections

**Overall EDGE_CASE** (at least one pathway is edge_case):
- Brief patient summary (1 line)
- **Eligibility table for ALL pathways** (routine AND edge_case)
  - For routine pathways: full row with criteria met
  - For edge_case pathways: row with "See detailed section below"
- **Detailed narrative sections ONLY for edge_case pathways**
  - Routine pathways do NOT get narrative sections
- Brief summary

### Table Format (Always Present)

| Pathway | Eligible | Class | Level | Key Criteria Met |
|---------|----------|-------|-------|------------------|
| EVT (6-24h) | Yes | I | A | M1, LKW 10h, NIHSS 15, ASPECTS 8, mRS 0, mismatch 3.0 |
| IVT (4.5-24h) | Conditional | IIb | B-R | See detailed section below |
| IVT (0-4.5h) | No | — | — | LKW 10h exceeds 4.5h window |
| EVT (0-6h) | Not applicable | — | — | Within extended window criteria |
| Large core EVT | Not applicable | — | — | ASPECTS 8, core 40cc (not large core) |
| BP management | Yes | I | B-R | Standard targets apply |

**For edge_case pathways**: Write "See detailed section below" in Key Criteria Met column

### Narrative Sections (Only for Edge Case Pathways)

When a pathway has `pathway_complexity == "edge_case"`, create a full section:

**## [Pathway Name]**

State the guideline recommendation (COR/LOE). Match each criterion to patient data. Cite relevant trials with outcomes. Explain why nearby recommendations don't apply. State determination.

**Example**:

## IV Thrombolysis (4.5-24 Hours, Extended Window)

The guideline provides a **Class IIb, Level B-R recommendation** for extended-window IVT in select patients between 4.5 and 24 hours who meet advanced imaging criteria...

[Full detailed analysis with TRACE-III vs TIMELESS reconciliation]

**Determination:** This patient meets imaging criteria but TIMELESS showed no benefit when rapid EVT available. IVT should be considered only if EVT will be substantially delayed.

### Mixed Case Example

**Patient:** 62F, M1, LKW 10h, NIHSS 15, ASPECTS 8, mRS 0, CTP core 40cc, mismatch 3.0

[Eligibility table with all 6-7 pathways]

**IV Thrombolysis (4.5-24 Hours)**
[Full narrative section — pathway_complexity == "edge_case"]

**Summary**
This patient is eligible for extended-window EVT (Class I, Level A). Extended-window IVT is conditional—most relevant if EVT will be delayed.

## RULES

Guideline citation:
- Cite recommendations using "Class" and "Level" notation (Class I, Class IIa, Class IIb, Class III) not "COR" notation. Use "Level A", "Level B-R", "Level B-NR", "Level C-LD", "Level C-EO".
- Reference guideline page numbers when available
- Reference specific trial names when discussing evidence
- Treat this like a legal/regulatory document — every clinical statement must be traceable to a guideline recommendation or trial

Content rules:
- NEVER recommend a specific treatment. Frame as "eligible/not eligible per guidelines" or "not guideline-supported"
- NEVER summarize or paraphrase a recommendation loosely. Cite the actual criteria.
- Do NOT state that perfusion imaging is "required" for EVT eligibility. The 2026 guidelines anchor EVT eligibility to vessel occlusion + time + NIHSS + ASPECTS. CTP "can be useful" if immediately available but is NOT mandated.
- When the patient falls outside guideline-supported populations, use "not guideline-supported" — not "uncertain."
- If vector search returned additional guideline context, integrate it as inline citations — not as a separate section.

Extended-window IVT imaging:
- For extended-window IVT (4.5-9h or 4.5-24h paradigms), advanced imaging demonstrating salvageable tissue is typically used to select candidates. This is different from EVT, where perfusion imaging is NOT required.
- Do NOT say perfusion is "not required" for extended-window IVT. Instead say: "Advanced imaging demonstrating salvageable tissue is typically used to select candidates for extended-window IVT."
- This distinction matters: EVT eligibility is anchored to vessel + time + NIHSS + ASPECTS. Extended-window IVT selection relies on demonstrating salvageable tissue.

Vessel location precision:
- Always specify the vessel segment when citing EVT recommendations. Write "proximal MCA (M1)" or "M2 branch" — not just "MCA."
- If the input says "MCA" without specifying M1 or M2 and the system assumed M1, state: "Assuming proximal MCA (M1) occlusion; if this is an M2 occlusion, different recommendations apply."
- Late-window EVT (6-24h) applies to ICA or M1 only, not M2. This must be explicit when discussing extended window eligibility.

Determination language:
- Use definitive language for determinations. Instead of "Not guideline-supported," write "This patient does not meet guideline-supported criteria for [pathway]."
- Instead of "Not eligible," write "The patient is not eligible for [pathway] because [specific criterion]."
- Every determination sentence must include the reason.

mRS handling (confirmed from 2026 AHA/ASA guideline text):
- 0-6h: mRS 0-1 → Class I, Level A. mRS 2 → Class IIa, Level B-NR (requires ASPECTS ≥6). mRS 3-4 → Class IIb, Level B-NR (requires ASPECTS ≥6, 0-6h ONLY). mRS ≥5 → no recommendation.
- 6-24h: mRS 0-1 → Class I, Level A (DAWN/DEFUSE-3). mRS 2 → no specific recommendation. mRS ≥3 → no recommendation (the Class IIb for mRS 3-4 applies to 0-6h only).

What NOT to include:
- Do NOT include a "Missing Information" or "Additional Information" section unless there is a specific data point that, if obtained, would flip a pathway's determination. If nothing would change, omit the section entirely.
- Do NOT mention perfusion imaging, CTP, or other tests for pathways where the patient is already excluded by a known, immutable parameter.
- Do NOT hedge with "could provide additional information" or "may influence decision-making" for data that would not change any determination.

Closing:
- End with: "This assessment is based on the 2026 AHA/ASA Acute Ischemic Stroke Guidelines and is intended as clinical decision support. It does not replace clinical judgment."
""".strip()


class ClinicalOutputAgent(LLMAgent):
    """Formats clinical eligibility assessments into user-facing responses."""

    def __init__(self):
        super().__init__(name="clinical_output_agent", skill_path=None)
        self.system_message = CLINICAL_SYSTEM_MESSAGE

    def _build_user_prompt(self, input_data: dict) -> str:
        """Build the full prompt from engine data."""
        user_query = input_data.get("user_query", "")
        patient = input_data.get("patient", {})
        eligibility = input_data.get("eligibility", [])
        vector_context = input_data.get("vector_context", [])

        parts = []

        # Patient summary
        parts.append("## PATIENT PRESENTATION")
        parts.append(f"Age: {patient.get('age', 'Unknown')}")
        parts.append(f"Sex: {patient.get('sex', 'Unknown')}")
        parts.append(f"Last Known Well: {patient.get('last_known_well_hours', 'Unknown')} hours")
        parts.append(f"NIHSS: {patient.get('nihss', 'Unknown')}")
        parts.append(f"Pre-stroke mRS: {patient.get('mrs_pre', 'Unknown')}")
        parts.append(f"ASPECTS: {patient.get('aspects', 'Unknown')}")
        parts.append(f"Occlusion: {patient.get('occlusion_location', 'Unknown')}")
        parts.append(f"LVO: {patient.get('lvo', False)}")
        parts.append(f"Dementia: {patient.get('dementia', False)}")
        parts.append(f"Perfusion Imaging: {patient.get('has_perfusion_imaging', False)}")
        parts.append(f"On Anticoagulation: {patient.get('on_anticoagulation', False)}")
        parts.append(f"Raw: {patient.get('raw_presentation', '')}")

        # Eligibility results
        parts.append("\n## ELIGIBILITY ASSESSMENTS")
        for e in eligibility:
            parts.append(f"\n### {e.get('treatment', 'Unknown')}")
            parts.append(f"Eligibility: {e.get('eligibility', 'Unknown')}")
            parts.append(f"COR: {e.get('cor', 'N/A')}")
            parts.append(f"LOE: {e.get('loe', 'N/A')}")
            parts.append(f"Reasoning: {e.get('reasoning', '')}")
            if e.get("key_criteria"):
                parts.append(f"Criteria: {'; '.join(e['key_criteria'])}")
            if e.get("relevant_trials"):
                parts.append(f"Trials: {', '.join(e['relevant_trials'])}")
            if e.get("caveats"):
                parts.append(f"Caveats: {'; '.join(e['caveats'])}")
            if e.get("page_references"):
                parts.append(f"Pages: {e['page_references']}")

        # Vector search context (if any)
        if vector_context:
            parts.append("\n## ADDITIONAL GUIDELINE CONTEXT (from vector search)")
            for vc in vector_context:
                parts.append(f"\n### For: {vc.get('for_treatment', 'Unknown')}")
                parts.append(vc.get("text", ""))

        # Trial metrics (structured data — exact numbers from JSON)
        trial_context = input_data.get("trial_context", {})
        if trial_context:
            parts.append("\n## TRIAL METRICS (from structured data)")
            for trial_name, info in trial_context.items():
                parts.append(f"\n### {trial_name}")
                parts.append(f"Full name: {info.get('full_name', '')}")
                parts.append(f"Category: {info.get('category', '')}")
                if info.get("pages"):
                    parts.append(f"Pages: {info['pages']}")
                for m in info.get("metrics", []):
                    metric_type = m.get("metric_type", "")
                    name = m.get("metric_name", "")
                    if metric_type == "percentage_comparison":
                        parts.append(
                            f"- {name}: intervention {m.get('intervention_value', '')} "
                            f"vs control {m.get('control_value', '')} "
                            f"({m.get('effect_size', '')}, {m.get('ci', '')}, "
                            f"p={m.get('p_value', '')})"
                        )
                    else:
                        effect = m.get("effect_size", "")
                        ci = m.get("ci", "")
                        p = m.get("p_value", "")
                        line = f"- {name}: {effect}"
                        if ci:
                            line += f" ({ci})"
                        if p:
                            line += f", p={p}"
                        parts.append(line)

        # Data completeness (if available)
        completeness = input_data.get("completeness", {})
        if completeness:
            parts.append("\n## DATA COMPLETENESS")

            assessable = []
            not_assessable = []
            for pathway, key in [
                ("IVT (standard + extended)", "can_assess_ivt"),
                ("EVT (standard)", "can_assess_evt"),
                ("Extended Window (IVT/EVT)", "can_assess_extended"),
                ("Large Core EVT", "can_assess_large_core"),
            ]:
                if completeness.get(key, False):
                    assessable.append(pathway)
                else:
                    not_assessable.append(pathway)

            if assessable:
                parts.append(f"CAN ASSESS: {', '.join(assessable)}")
            if not_assessable:
                parts.append(f"CANNOT ASSESS (missing critical data): {', '.join(not_assessable)}")

            missing_critical = completeness.get("missing_critical", [])
            if missing_critical:
                parts.append("\nMISSING CRITICAL PARAMETERS:")
                for item in missing_critical:
                    parts.append(f"  - {item.get('label', item.get('param', 'Unknown'))}")

            missing_important = completeness.get("missing_important", [])
            if missing_important:
                parts.append("\nMISSING IMPORTANT PARAMETERS:")
                for item in missing_important:
                    parts.append(f"  - {item.get('label', item.get('param', 'Unknown'))}")

            assumptions = completeness.get("assumptions_made", [])
            if assumptions:
                parts.append("\nASSUMPTIONS APPLIED:")
                for a in assumptions:
                    parts.append(f"  - {a}")

        # Complexity flag for output formatting
        complexity = input_data.get("complexity", "edge_case")
        parts.append(f"\n## CASE COMPLEXITY: {complexity.upper()}")

        parts.append(f"\n## USER QUESTION\n{user_query}")
        parts.append("\nSynthesize the above into a guideline-referenced clinical assessment.")

        return "\n".join(parts)

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the clinical output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        user_prompt = self._build_user_prompt(input_data)
        messages = [{"role": "user", "content": user_prompt}]

        patient = input_data.get("patient", {})
        eligibility = input_data.get("eligibility", [])
        print(f"  [ClinicalOutputAgent] Patient age={patient.get('age')}, "
              f"{len(eligibility)} pathways evaluated")

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=self.system_message,
                messages=messages,
                model=self.model,
            ):
                if isinstance(chunk, dict):
                    usage = chunk
                else:
                    final_text += chunk
                    await broker.put({
                        "type": "final_chunk",
                        "data": {
                            "agent": self.name,
                            "content": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

            return {
                "content": {"formatted_response": final_text},
                "usage": usage,
            }
        else:
            # Non-streaming fallback
            response = await self.llm_client.call(
                system_prompt=self.system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
