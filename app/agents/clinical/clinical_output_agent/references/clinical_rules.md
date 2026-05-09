# Clinical Output Rules

## Guideline Citation
- Cite recommendations using "Class" and "Level" notation (Class I, Class IIa, Class IIb, Class III) not "COR" notation. Use "Level A", "Level B-R", "Level B-NR", "Level C-LD", "Level C-EO".
- Reference guideline page numbers when available
- Reference specific trial names when discussing evidence
- Treat this like a legal/regulatory document — every clinical statement must be traceable to a guideline recommendation or trial

## Content Rules
- NEVER recommend a specific treatment. Frame as "eligible/not eligible per guidelines" or "not guideline-supported"
- NEVER summarize or paraphrase a recommendation loosely. Cite the actual criteria.
- Do NOT state that perfusion imaging is "required" for EVT eligibility. The 2026 guidelines anchor EVT eligibility to vessel occlusion + time + NIHSS + ASPECTS. CTP "can be useful" if immediately available but is NOT mandated.
- When the patient falls outside guideline-supported populations, use "not guideline-supported" — not "uncertain."
- If vector search returned additional guideline context, integrate it as inline citations — not as a separate section.

## Extended-Window IVT Imaging
- For extended-window IVT (4.5-9h or 4.5-24h paradigms), advanced imaging demonstrating salvageable tissue is typically used to select candidates. This is different from EVT, where perfusion imaging is NOT required.
- For ROUTINE cases: state ONLY the COR/LOE per the routine format rule. Do NOT add the imaging qualifier sentence.
- For EDGE_CASE responses only (when the patient's perfusion status is uncertain or requires clinical context): you may add: "Advanced imaging demonstrating salvageable tissue is typically used to select candidates for extended-window IVT."
- This distinction matters: EVT eligibility is anchored to vessel + time + NIHSS + ASPECTS. Extended-window IVT selection relies on demonstrating salvageable tissue.

## Blood Pressure Targets
- EVT only (IVT not eligible or outside its window): one sentence: "Blood pressure should be maintained below 185/110 mmHg before thrombectomy and below 180 mmHg after EVT; intensive reduction to SBP <140 mmHg after successful recanalization is harmful (Class III: Harm)."
- IVT only (no LVO / EVT not indicated): one sentence combining pre-thrombolysis and post-IVT targets.
- Both IVT and EVT eligible (BOTH have YES eligibility, e.g., patient is within 0-4.5h for IVT AND has LVO for EVT): state in three consecutive sentences within one paragraph — do NOT put blank lines between them:
  (1) "Blood pressure should be maintained below 185/110 mmHg before treatment."
  (2) "After IV thrombolysis, maintain below 180/105 mmHg for 24 hours; intensive reduction to SBP <140 mmHg provides no benefit (Class III: No Benefit)."
  (3) "After EVT, maintain below 180 mmHg; intensive reduction to SBP <140 mmHg after successful recanalization is harmful (Class III: Harm)."
  IMPORTANT: Only use the three-sentence format when IVT is genuinely eligible (within window, not just a conditional Class IIb option). If IVT is outside the time window or not eligible, use the EVT-only single sentence even if a conditional tenecteplase recommendation exists.

## Vessel Location Precision
- Always specify the vessel segment when citing EVT recommendations. Write "proximal MCA (M1)" or "M2 branch" — not just "MCA."
- If the input says "MCA" without specifying M1 or M2 and the system assumed M1, state: "Assuming proximal MCA (M1) occlusion; if this is an M2 occlusion, different recommendations apply."
- Late-window EVT (6-24h) applies to ICA or M1 only, not M2. This must be explicit when discussing extended window eligibility.

## mRS Handling
FOR REFERENCE ONLY. Do NOT echo this table in output. Do not explain the ladder. Just apply the correct COR/LOE for this patient and state it:
- 0-6h: mRS 0-1 -> Class I, Level A. mRS 2 -> Class IIa, Level B-NR (requires ASPECTS >=6). mRS 3-4 -> Class IIb, Level B-NR (requires ASPECTS >=6, 0-6h ONLY). mRS >=5 -> no recommendation.
- 6-24h: mRS 0-1 -> Class I, Level A (DAWN/DEFUSE-3). mRS 2 -> no specific recommendation. mRS >=3 -> no recommendation (the Class IIb for mRS 3-4 applies to 0-6h only).

## Determination Language
- Use definitive language for determinations. Instead of "Not guideline-supported," write "This patient does not meet guideline-supported criteria for [pathway]."
- Instead of "Not eligible," write "The patient is not eligible for [pathway] because [specific criterion]."
- Every determination sentence must include the reason.

## What NOT to Include
- Do NOT include a "Missing Information" or "Additional Information" section unless there is a specific data point that, if obtained, would flip a pathway's determination. If nothing would change, omit the section entirely.
- Do NOT mention perfusion imaging, CTP, or other tests for pathways where the patient is already excluded by a known, immutable parameter.
- Do NOT hedge with "could provide additional information" or "may influence decision-making" for data that would not change any determination.

## Closing
- End with: "This assessment reflects the 2026 AHA/ASA Acute Ischemic Stroke Guidelines and does not replace clinical judgment."