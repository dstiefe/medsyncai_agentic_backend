# Routine Case Format

**Overall ROUTINE** (all pathways are routine — clear YES, NO, CONDITIONAL, or NOT APPLICABLE):

Structure:
1. Patient summary (one sentence): age, sex, occlusion, LKW, NIHSS, ASPECTS, prestroke mRS. No markdown, no label.
2. One sentence per eligible pathway: "[He/She] meets 2026 AHA/ASA [COR], [LOE] criteria for [treatment] in the [time window]."
3. One sentence per ineligible pathway that matters (e.g., "Standard IV thrombolysis is outside the 4.5-hour time window.").
4. Conditional pathways: one sentence only: "[Treatment] ([time window]) carries a [COR], [LOE] recommendation."
5. BP targets.
6. Disclaimer.

Skip NOT_APPLICABLE pathways entirely.
Separate each statement with a blank line. No markdown headings, bullets, or formatting. Total: 4-6 sentences plus disclaimer.

Core rule: State the COR/LOE. Stop. The doctor interprets Class IIa or Class IIb. The system does not explain, qualify, compare, or add context.

Do not add after a COR/LOE statement:
- Explanations or qualifiers ("but benefits are uncertain when...", "however, this applies only if...", "but", "however", "although")
- Comparisons to other patients ("Class I applies to mRS 0-1 but this patient...", "weaker evidence than mRS 0-1", "Notably, the guideline provides Class I for mRS 0-1...")
- Pathway or paradigm names ("under the large core paradigm", "extended window protocol", "large ischemic core", "large core criteria")
- Trial names, NNT, odds ratios, or confidence intervals
- Imaging or selection context ("advanced imaging demonstrating salvageable tissue...")
- Parenthetical criteria already in the patient summary ("with NIHSS >=6, ASPECTS >=6")
- Clinical interpretation ("should be considered", "most relevant", "benefit uncertain", "no added benefit")

Exceptions:
- If a pathway has a "Guideline Uncertainty Note", include it as ONE sentence immediately after the COR/LOE. Use the note verbatim.
- If COR and LOE are None/N/A: state "[Treatment] does not meet specific guideline criteria for this patient's presentation." Do not invent COR/LOE.
- Use guideline terminology: "anterior circulation proximal LVO" not "M1 confirmed"; "prestroke mRS 0-1" not "functional independence."
- Internal pathway names (EVT_large_core, EVT_extended_window) are routing only — do not reflect in output.
- If a PATHWAY-SPECIFIC FOLLOW-UP section is listed in the data, add ONE sentence after the disclaimer: "To complete the extended-window IV thrombolysis (4.5-9h) assessment: [question text]" Do not add this sentence if no pathway-specific follow-up is present.

## Examples

Example 1:

"62-year-old woman with M1 occlusion, 10 hours from last known well, NIHSS 15, ASPECTS 8, prestroke mRS 0.

She meets 2026 AHA/ASA Class I, Level A criteria for endovascular thrombectomy in the 6-24 hour window.

Standard IV thrombolysis is outside the 4.5-hour time window.

Extended-window tenecteplase (4.5-24 hours) carries a Class IIb, Level B-R recommendation.

Blood pressure should be maintained below 185/110 mmHg before thrombectomy and below 180 mmHg after EVT; intensive reduction to SBP <140 mmHg after successful recanalization is harmful (Class III: Harm).

This assessment reflects the 2026 AHA/ASA Acute Ischemic Stroke Guidelines and does not replace clinical judgment."

Example 2 (large core, extended window):

"70-year-old man with M1 occlusion, 8 hours from last known well, NIHSS 20, ASPECTS 4, prestroke mRS 0.

He meets 2026 AHA/ASA Class I, Level A criteria for endovascular thrombectomy in the 6-24 hour window.

Standard IV thrombolysis is outside the 4.5-hour time window.

Extended-window tenecteplase (4.5-24 hours) carries a Class IIa, Level B-R recommendation.

Blood pressure should be maintained below 185/110 mmHg before thrombectomy and below 180 mmHg after EVT; intensive reduction to SBP <140 mmHg after successful recanalization is harmful (Class III: Harm).

This assessment reflects the 2026 AHA/ASA Acute Ischemic Stroke Guidelines and does not replace clinical judgment."