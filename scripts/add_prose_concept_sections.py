"""
Add concept section routing entries for every clinically-relevant
prose section in chapters 3, 4, 5, 6.

The content for these already exists as §3.x, §4.x, §5.x, §6.x keys
in guideline_knowledge.json (re-ingested cleanly in commit 340cb92).
This script adds routing metadata to
ais_guideline_section_map.json's concept_sections{} dict, using
content_section_id as a pointer back to the existing §N.M key.
No content duplication.

knowledge_loader.get_section() will resolve content_section_id
indirection so downstream consumers can read concept section content
via the concept section id (e.g. bp_management_ais) just like any
other section.

Covers all §3.x, §4.x (except §4.8 which already has dapt_trials +
dosing concept sections), §5.x, §6.x prose sections. Does NOT cover
§2.x (prehospital systems of care — lower clinical decision priority)
or chapter roots.

Adds:
  bp_management_ais               ← §4.3
  temperature_management_ais      ← §4.4
  glucose_management_ais          ← §4.5
  thrombolysis_decision_making    ← §4.6.1
  thrombolytic_agent_choice       ← §4.6.2
  extended_window_ivt             ← §4.6.3
  alternative_fibrinolytics       ← §4.6.4
  ivt_special_circumstances       ← §4.6.5
  evt_ivt_bridging                ← §4.7.1
  evt_adult_eligibility           ← §4.7.2
  evt_posterior_circulation       ← §4.7.3
  evt_techniques                  ← §4.7.4
  evt_pediatric                   ← §4.7.5
  antiplatelet_treatment          ← §4.8 (prose covering ALL rec rows,
                                          complements the existing
                                          dapt_trials_evidence concept)
  anticoagulation_ais              ← §4.9
  volume_expansion_hemodilution    ← §4.10
  neuroprotection_ais              ← §4.11
  emergency_carotid_intervention   ← §4.12
  airway_oxygenation_ais           ← §4.1
  head_positioning_ais             ← §4.2
  stroke_scales_nihss              ← §3.1
  initial_imaging_ais              ← §3.2 (complements extended_window_imaging_criteria)
  other_diagnostic_tests           ← §3.3
  stroke_unit_care                 ← §5.1
  dysphagia_screening              ← §5.2
  nutrition_ais                    ← §5.3
  dvt_prophylaxis_ais              ← §5.4
  depression_screening_ais         ← §5.5
  other_inhospital_management      ← §5.6
  rehabilitation_ais               ← §5.7
  cerebral_edema_general           ← §6.1
  cerebral_edema_medical           ← §6.2
  supratentorial_decompression     ← §6.3
  cerebellar_decompression         ← §6.4
  seizure_management_ais           ← §6.5
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references/ais_guideline_section_map.json"


PROSE_CONCEPT_SECTIONS = {
    # ─────────── Chapter 3: Emergency Evaluation ───────────
    "stroke_scales_nihss": {
        "title": "Stroke Severity Scales (NIHSS, mRS)",
        "description": (
            "Clinical stroke severity assessment tools. Covers the "
            "National Institutes of Health Stroke Scale (NIHSS), its "
            "limitations, use in treatment decision-making and "
            "prognostication, and the modified Rankin Scale (mRS) for "
            "outcome measurement. Pediatric NIHSS covered for children "
            "2 years and older."
        ),
        "when_to_route": [
            "What is the NIHSS?",
            "How is stroke severity scored?",
            "What's the difference between NIHSS and mRS?",
            "Is there a pediatric NIHSS?",
        ],
        "routing_keywords": [
            "NIHSS", "NIH Stroke Scale", "stroke severity",
            "mRS", "modified Rankin Scale",
            "outcome prediction", "stroke scale",
            "pediatric NIHSS", "PedNIHSS",
            "clinical severity", "baseline severity",
        ],
        "supported_intents": [
            "definition_lookup", "imaging_protocol", "monitoring_protocol",
            "threshold_target",
        ],
        "content_section_id": "3.1",
        "parentChapter": "3.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §3.1",
    },
    "initial_imaging_ais": {
        "title": "Initial and Multimodal Imaging for AIS",
        "description": (
            "Initial brain and vascular imaging protocols for acute "
            "stroke evaluation: non-contrast CT, CT angiography, CT "
            "perfusion, MRI/MRA, and advanced imaging for patient "
            "selection for thrombolysis and thrombectomy. Complements "
            "extended_window_imaging_criteria, which carries the "
            "per-trial imaging inclusion criteria."
        ),
        "when_to_route": [
            "What imaging is needed for AIS?",
            "Should I get a CTA before EVT?",
            "When is CT perfusion indicated?",
            "Is MRI better than CT for acute stroke?",
        ],
        "routing_keywords": [
            "non-contrast CT", "NCCT", "CTA", "CT angiography",
            "CT perfusion", "CTP",
            "MRI", "MRA", "DWI", "FLAIR",
            "multimodal imaging", "vascular imaging",
            "penumbra", "core volume", "mismatch",
            "LVO detection", "perfusion imaging",
        ],
        "supported_intents": [
            "imaging_protocol", "eligibility_criteria",
            "time_window", "sequencing",
        ],
        "content_section_id": "3.2",
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §3.2",
    },
    "other_diagnostic_tests_ais": {
        "title": "Other Diagnostic Tests for AIS",
        "description": (
            "Additional diagnostic workup for acute stroke: blood "
            "glucose, troponin, ECG, coagulation studies, renal "
            "function, CBC, echocardiography, and cardiac monitoring. "
            "These tests should not delay IVT in otherwise eligible "
            "patients."
        ),
        "when_to_route": [
            "What labs do I need before tPA?",
            "Is echocardiography needed before EVT?",
            "When should I get a troponin in stroke?",
            "What cardiac monitoring is recommended?",
        ],
        "routing_keywords": [
            "blood glucose", "troponin", "ECG", "electrocardiogram",
            "coagulation", "INR", "platelet count", "aPTT",
            "CBC", "renal function", "creatinine",
            "echocardiography", "cardiac monitoring",
        ],
        "supported_intents": [
            "imaging_protocol", "monitoring_protocol",
            "eligibility_criteria", "screening_protocol",
        ],
        "content_section_id": "3.3",
        "parentChapter": "3.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §3.3",
    },

    # ─────────── Chapter 4: Supportive Management ───────────
    "airway_oxygenation_ais": {
        "title": "Airway, Breathing, and Oxygenation in AIS",
        "description": (
            "Airway management and supplemental oxygen guidance in "
            "acute ischemic stroke. Supplemental oxygen recommended "
            "only when needed to maintain SpO2 >94%. Routine "
            "supplemental oxygen to non-hypoxic patients is not "
            "recommended."
        ),
        "when_to_route": [
            "When should I give supplemental oxygen in stroke?",
            "What SpO2 target is recommended?",
            "Is routine oxygen indicated in AIS?",
            "When should I intubate a stroke patient?",
        ],
        "routing_keywords": [
            "supplemental oxygen", "SpO2", "oxygen saturation",
            "hypoxia", "hypoxemia",
            "intubation", "airway management",
            "mechanical ventilation",
        ],
        "supported_intents": [
            "threshold_target", "monitoring_protocol",
            "post_treatment_care",
        ],
        "content_section_id": "4.1",
        "parentChapter": "4.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.1",
    },
    "head_positioning_ais": {
        "title": "Head Positioning in AIS",
        "description": (
            "Evidence and guidance on head-of-bed positioning in "
            "acute ischemic stroke. Based on the HeadPoST trial, "
            "there is no routine preference for supine over 30-degree "
            "head elevation. Individualize based on clinical status."
        ),
        "when_to_route": [
            "What head position for a stroke patient?",
            "Should the head of bed be flat or elevated?",
            "Does head positioning affect stroke outcomes?",
        ],
        "routing_keywords": [
            "head positioning", "head of bed", "HOB",
            "supine", "semi-recumbent", "head elevation",
            "HeadPoST",
        ],
        "supported_intents": [
            "post_treatment_care", "monitoring_protocol",
        ],
        "content_section_id": "4.2",
        "parentChapter": "4.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.2",
    },
    "bp_management_ais": {
        "title": "Blood Pressure Management in Acute Ischemic Stroke",
        "description": (
            "Blood pressure management across the acute stroke care "
            "pathway: pre-thrombolysis, during IVT, post-IVT, "
            "post-EVT, and after failed recanalization. The standard "
            "pre-IVT ceiling is 185/110 mmHg; during and after IVT "
            "BP should be maintained below 180/105 mmHg. Different "
            "targets apply post-EVT depending on recanalization "
            "success."
        ),
        "when_to_route": [
            "What is the BP target before tPA?",
            "What BP is too high for IVT?",
            "What BP target after successful EVT?",
            "How should I manage BP during thrombolysis?",
            "BP goal after failed thrombectomy?",
        ],
        "routing_keywords": [
            "blood pressure", "BP", "SBP", "DBP",
            "hypertension", "hypotension",
            "BP target", "BP goal",
            "185/110", "180/105",
            "labetalol", "nicardipine", "clevidipine",
            "pre-IVT BP", "post-IVT BP", "post-EVT BP",
            "failed recanalization",
        ],
        "supported_intents": [
            "threshold_target", "dosing_protocol",
            "monitoring_protocol", "post_treatment_care",
            "patient_specific_eligibility",
        ],
        "content_section_id": "4.3",
        "parentChapter": "4.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.3",
        "anchor_thresholds": [
            {"anchor": "SBP", "compare": ">", "value": 185,
             "unit": "mmHg", "row_hint": "pre_ivt_bp_ceiling"},
            {"anchor": "DBP", "compare": ">", "value": 110,
             "unit": "mmHg", "row_hint": "pre_ivt_bp_ceiling"},
            {"anchor": "SBP", "compare": ">", "value": 180,
             "unit": "mmHg", "row_hint": "post_ivt_bp_ceiling"},
            {"anchor": "DBP", "compare": ">", "value": 105,
             "unit": "mmHg", "row_hint": "post_ivt_bp_ceiling"},
        ],
    },
    "temperature_management_ais": {
        "title": "Temperature Management in AIS",
        "description": (
            "Fever (>38°C) management in acute ischemic stroke. "
            "Identify and treat sources of fever; use antipyretic "
            "medication to lower elevated temperatures. Therapeutic "
            "hypothermia is not recommended outside clinical trials."
        ),
        "when_to_route": [
            "Should I treat fever in stroke?",
            "Is hypothermia indicated for acute stroke?",
            "What temperature target in AIS?",
            "How do I manage fever after stroke?",
        ],
        "routing_keywords": [
            "fever", "hyperthermia", "hypothermia",
            "temperature", "antipyretic", "acetaminophen",
            "cooling",
        ],
        "supported_intents": [
            "threshold_target", "post_treatment_care",
            "monitoring_protocol", "complication_management",
        ],
        "content_section_id": "4.4",
        "parentChapter": "4.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.4",
        "anchor_thresholds": [
            {"anchor": "temperature", "compare": ">", "value": 38,
             "unit": "celsius", "row_hint": "fever_threshold"},
        ],
    },
    "glucose_management_ais": {
        "title": "Blood Glucose Management in AIS",
        "description": (
            "Blood glucose management in acute ischemic stroke. "
            "Both hypoglycemia and hyperglycemia worsen outcomes. "
            "Maintain glucose between 140–180 mg/dL; treat "
            "hypoglycemia <60 mg/dL immediately."
        ),
        "when_to_route": [
            "What glucose target in AIS?",
            "Should I treat hyperglycemia in stroke?",
            "How low is too low for glucose?",
            "Is insulin indicated in acute stroke?",
        ],
        "routing_keywords": [
            "glucose", "blood glucose", "hyperglycemia", "hypoglycemia",
            "insulin", "dextrose",
            "140-180", "glucose target",
        ],
        "supported_intents": [
            "threshold_target", "dosing_protocol",
            "monitoring_protocol", "complication_management",
        ],
        "content_section_id": "4.5",
        "parentChapter": "4.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.5",
        "anchor_thresholds": [
            {"anchor": "glucose", "compare": "<", "value": 60,
             "unit": "mg/dL", "row_hint": "hypoglycemia_threshold"},
            {"anchor": "glucose", "compare": ">", "value": 180,
             "unit": "mg/dL", "row_hint": "hyperglycemia_threshold"},
        ],
    },

    # ─────────── §4.6 IVT subsections ───────────
    "thrombolysis_decision_making": {
        "title": "Thrombolysis Decision-Making",
        "description": (
            "Decision-making framework for IV thrombolysis in acute "
            "ischemic stroke. Covers shared decision-making, informed "
            "consent, time-to-treatment considerations, management of "
            "stroke mimics, and the disabling-deficit determination "
            "(which is also covered by Table 4 / "
            "disabling_deficits_assessment)."
        ),
        "when_to_route": [
            "How fast do I need to give tPA?",
            "Should I get consent for IVT?",
            "What if I'm not sure it's a stroke?",
            "When does the clock start for thrombolysis?",
            "Is a stroke mimic a contraindication to tPA?",
        ],
        "routing_keywords": [
            "thrombolysis decision", "IVT decision",
            "disabling deficit", "shared decision-making",
            "informed consent",
            "stroke mimic", "mild stroke", "minor stroke",
            "time to treatment", "door-to-needle",
            "last known well", "symptom onset",
        ],
        "supported_intents": [
            "recommendation_lookup", "eligibility_criteria",
            "patient_specific_eligibility", "clinical_overview",
            "time_window",
        ],
        "content_section_id": "4.6.1",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1",
    },
    "thrombolytic_agent_choice": {
        "title": "Choice of Thrombolytic Agent (Alteplase vs Tenecteplase)",
        "description": (
            "Guidance on choosing between alteplase and tenecteplase "
            "for IV thrombolysis. Tenecteplase 0.25 mg/kg is now an "
            "acceptable alternative to alteplase 0.9 mg/kg in eligible "
            "patients. Tenecteplase 0.4 mg/kg is NOT recommended — "
            "increases sICH without better outcomes."
        ),
        "when_to_route": [
            "Should I use tenecteplase or alteplase?",
            "Is tenecteplase non-inferior to alteplase?",
            "Why not use 0.4 mg/kg tenecteplase?",
            "What's the difference between TNK and alteplase?",
        ],
        "routing_keywords": [
            "alteplase", "tenecteplase", "TNK", "tPA",
            "choice of agent", "drug choice",
            "NOR-TEST", "ATTEST", "EXTEND-IA", "AcT", "TRACE-II",
            "0.25 mg/kg", "0.4 mg/kg",
        ],
        "supported_intents": [
            "drug_choice", "comparison_query",
            "dosing_protocol", "evidence_for_recommendation",
            "no_benefit_query",
        ],
        "content_section_id": "4.6.2",
        "parentChapter": "4.6.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.2",
    },
    "extended_window_ivt": {
        "title": "Extended Time Windows for IV Thrombolysis",
        "description": (
            "IV thrombolysis beyond the standard 4.5-hour window. "
            "Three scenarios: (a) unknown-onset / wake-up stroke with "
            "DWI/FLAIR mismatch, (b) 4.5–9 hours with perfusion "
            "mismatch on MR or CTP, (c) 4.5–24 hours with LVO and "
            "salvageable penumbra when EVT is not available. "
            "Per-trial imaging criteria in extended_window_imaging_criteria."
        ),
        "when_to_route": [
            "Can I give tPA at 6 hours?",
            "Is IVT indicated in wake-up stroke?",
            "What about thrombolysis beyond 4.5 hours?",
            "Can I treat unknown-onset stroke with tPA?",
            "Does the guideline support tPA at 9 hours?",
        ],
        "routing_keywords": [
            "extended window", "wake-up stroke", "unknown onset",
            "DWI/FLAIR mismatch", "perfusion mismatch",
            "WAKE-UP", "EXTEND", "THAWS", "EPITHET",
            "ECASS-4", "TIMELESS", "TRACE-3",
            "9 hours", "4.5 hours",
            "salvageable penumbra",
        ],
        "supported_intents": [
            "time_window", "eligibility_criteria",
            "imaging_protocol", "extended_window_ivt",
        ],
        "content_section_id": "4.6.3",
        "parentChapter": "4.6.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.3",
        "anchor_thresholds": [
            {"anchor": "time from onset", "compare": ">", "value": 4.5,
             "unit": "hours", "row_hint": "extended_window_entry"},
            {"anchor": "LKW", "compare": ">", "value": 4.5,
             "unit": "hours", "row_hint": "extended_window_entry"},
            {"anchor": "time from onset", "compare": "<=", "value": 24,
             "unit": "hours", "row_hint": "extended_window_24h_cap"},
        ],
    },
    "alternative_fibrinolytics": {
        "title": "Other IV Fibrinolytics and Sonothrombolysis",
        "description": (
            "Alternative fibrinolytic agents (reteplase, mutant "
            "prourokinase) and sonothrombolysis as adjuncts to IVT. "
            "Reteplase has shown superiority to alteplase in Chinese "
            "populations but generalizability is uncertain. "
            "Sonothrombolysis has not improved clinical outcomes."
        ),
        "when_to_route": [
            "Is reteplase used for stroke?",
            "What about mutant prourokinase?",
            "Does sonothrombolysis work?",
            "Are there alternatives to alteplase?",
        ],
        "routing_keywords": [
            "reteplase", "mutant prourokinase", "PROST", "PROST-2",
            "desmoteplase", "DIAS-3", "DIAS-4",
            "sonothrombolysis", "CLOTBUST-ER", "NOR-SASS",
        ],
        "supported_intents": [
            "alternative_options", "evidence_for_recommendation",
            "comparison_query", "knowledge_gap",
        ],
        "content_section_id": "4.6.4",
        "parentChapter": "4.6.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.4",
    },
    "ivt_special_circumstances": {
        "title": "IV Thrombolysis in Special Circumstances",
        "description": (
            "IV thrombolysis in specific populations not covered by "
            "the standard eligibility criteria: sickle cell disease, "
            "central retinal artery occlusion (CRAO), recent DOAC "
            "exposure, and other specific clinical scenarios."
        ),
        "when_to_route": [
            "Can I give tPA in sickle cell disease?",
            "Is IVT indicated for CRAO?",
            "Can I give tPA to someone on a DOAC?",
            "What about thrombolysis in special populations?",
        ],
        "routing_keywords": [
            "sickle cell disease", "CRAO", "central retinal artery occlusion",
            "DOAC exposure", "DOAC within 48 hours",
            "THEIA", "TenCRAOS", "REVISION",
            "special populations",
        ],
        "supported_intents": [
            "patient_specific_eligibility", "pediatric_specific",
            "eligibility_criteria", "alternative_options",
        ],
        "content_section_id": "4.6.5",
        "parentChapter": "4.6.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.5",
    },

    # ─────────── §4.7 EVT subsections ───────────
    "evt_ivt_bridging": {
        "title": "EVT Concomitant With IV Thrombolysis (Bridging Therapy)",
        "description": (
            "Decision to give IV thrombolysis as a bridge to EVT in "
            "eligible patients. Combined IVT + EVT is preferred over "
            "EVT alone for most LVO patients in the standard window. "
            "Chinese RCTs (DIRECT-MT, DEVT, SKIP, MR CLEAN NO-IV) "
            "compared the two approaches with mixed results."
        ),
        "when_to_route": [
            "Should I bridge with tPA before thrombectomy?",
            "Is direct EVT as good as IVT + EVT?",
            "When can I skip IVT before EVT?",
            "What did DIRECT-MT show?",
        ],
        "routing_keywords": [
            "bridging therapy", "bridging IVT", "direct EVT",
            "direct thrombectomy", "skip tPA",
            "DIRECT-MT", "DEVT", "SKIP", "MR CLEAN NO-IV",
            "SWIFT DIRECT", "DIRECT-SAFE",
        ],
        "supported_intents": [
            "sequencing", "drug_choice", "comparison_query",
            "eligibility_criteria",
        ],
        "content_section_id": "4.7.1",
        "parentChapter": "4.7.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.1",
    },
    "evt_adult_eligibility": {
        "title": "EVT Eligibility for Adult Patients",
        "description": (
            "Eligibility for endovascular thrombectomy in adults: "
            "standard 0–6 hour window for anterior LVO with small "
            "core, extended 6–24 hour window with imaging selection "
            "(DAWN, DEFUSE-3 criteria), and large-core EVT (SELECT2, "
            "ANGEL-ASPECT, RESCUE-Japan LIMIT, TENSION, TESLA, LASTE)."
        ),
        "when_to_route": [
            "Is my patient eligible for thrombectomy?",
            "What's the time window for EVT?",
            "Can I do EVT with a large core?",
            "What ASPECTS threshold for EVT?",
            "DAWN vs DEFUSE-3 criteria?",
        ],
        "routing_keywords": [
            "EVT", "endovascular thrombectomy", "mechanical thrombectomy",
            "LVO", "large vessel occlusion",
            "anterior circulation", "ICA", "M1", "M2",
            "DAWN", "DEFUSE-3", "SELECT2",
            "ANGEL-ASPECT", "RESCUE-Japan LIMIT",
            "TENSION", "TESLA", "LASTE",
            "6-24 hours", "late window",
            "large core", "ASPECTS",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
            "time_window", "evidence_for_recommendation",
            "trial_specific_data",
        ],
        "content_section_id": "4.7.2",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2",
        "anchor_thresholds": [
            {"anchor": "time from onset", "compare": "<=", "value": 6,
             "unit": "hours", "row_hint": "evt_standard_window"},
            {"anchor": "time from onset", "compare": "<=", "value": 24,
             "unit": "hours", "row_hint": "evt_extended_window"},
            {"anchor": "NIHSS", "compare": ">=", "value": 6,
             "unit": "", "row_hint": "evt_nihss_threshold"},
            {"anchor": "ASPECTS", "compare": ">=", "value": 3,
             "unit": "", "row_hint": "evt_large_core_min"},
        ],
    },
    "evt_posterior_circulation": {
        "title": "EVT for Posterior Circulation Stroke",
        "description": (
            "EVT for basilar artery occlusion and other posterior "
            "circulation LVO. Based on ATTENTION and BAOCHE trials, "
            "EVT is recommended for basilar occlusion within 24 hours "
            "in selected patients. Posterior circulation EVT has "
            "distinct selection criteria and outcomes compared to "
            "anterior circulation."
        ),
        "when_to_route": [
            "Is EVT indicated for basilar occlusion?",
            "What's the time window for posterior EVT?",
            "What did ATTENTION show?",
            "EVT for vertebrobasilar stroke?",
        ],
        "routing_keywords": [
            "basilar", "basilar artery occlusion", "BAO",
            "vertebrobasilar", "posterior circulation",
            "P1", "P2",
            "ATTENTION", "BAOCHE", "BASICS", "BEST",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
            "time_window", "evidence_for_recommendation",
        ],
        "content_section_id": "4.7.3",
        "parentChapter": "4.7.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.3",
    },
    "evt_techniques": {
        "title": "Endovascular Techniques and Adjuncts",
        "description": (
            "Technical aspects of endovascular thrombectomy: "
            "stent retrievers vs aspiration, balloon-guide catheters, "
            "reperfusion scoring (TICI), first-pass effect, tandem "
            "occlusions, intra-arterial adjuncts (tenecteplase, "
            "alteplase), and rescue therapies."
        ),
        "when_to_route": [
            "Stent retriever or aspiration first?",
            "What TICI score counts as success?",
            "How do I manage tandem occlusion?",
            "Is intra-arterial tPA useful?",
        ],
        "routing_keywords": [
            "stent retriever", "aspiration", "ADAPT", "ASTER",
            "TICI", "modified TICI", "mTICI",
            "first-pass effect", "FPE",
            "balloon-guide catheter", "BGC",
            "tandem occlusion", "carotid stenting",
            "intra-arterial tPA", "intra-arterial alteplase",
            "intra-arterial tenecteplase", "CHOICE",
        ],
        "supported_intents": [
            "drug_choice", "comparison_query",
            "sequencing", "evidence_for_recommendation",
        ],
        "content_section_id": "4.7.4",
        "parentChapter": "4.7.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.4",
    },
    "evt_pediatric": {
        "title": "EVT in Pediatric Patients",
        "description": (
            "Endovascular thrombectomy in children. Observational "
            "evidence suggests EVT can be performed safely in children "
            "between 28 days and 18 years with LVO when done by "
            "experienced neurointerventionalists. Pediatric dosing and "
            "selection criteria are less well established than adult."
        ),
        "when_to_route": [
            "Is EVT indicated in children?",
            "Can I do thrombectomy in a teenager?",
            "Pediatric stroke EVT criteria?",
            "What age range for pediatric EVT?",
        ],
        "routing_keywords": [
            "pediatric EVT", "pediatric thrombectomy",
            "child stroke", "neonate",
            "arteriopathy", "focal cerebral arteriopathy",
        ],
        "supported_intents": [
            "pediatric_specific", "eligibility_criteria",
            "patient_specific_eligibility",
        ],
        "content_section_id": "4.7.5",
        "parentChapter": "4.7.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.5",
    },

    # ─────────── §4.8 Antiplatelet (prose coverage) ───────────
    "antiplatelet_treatment": {
        "title": "Antiplatelet Treatment for AIS",
        "description": (
            "Antiplatelet therapy for acute ischemic stroke: aspirin "
            "within 48 hours, noncardioembolic secondary prevention, "
            "dual antiplatelet therapy (DAPT) for minor stroke and "
            "high-risk TIA, cervical dissection, aspirin after "
            "thrombolysis. Complements dapt_trials_evidence which "
            "covers the specific DAPT trial evidence."
        ),
        "when_to_route": [
            "Should I give aspirin to a stroke patient?",
            "When do I start antiplatelet after stroke?",
            "Is ticagrelor better than aspirin?",
            "Can I give aspirin after tPA?",
            "What antiplatelet for cervical dissection?",
        ],
        "routing_keywords": [
            "aspirin", "clopidogrel", "ticagrelor",
            "antiplatelet therapy", "secondary prevention",
            "tirofiban", "eptifibatide", "abciximab",
            "SaTIS", "TREND", "AbESTT",
            "WARSS", "CADISS", "CARL",
            "ARTIS",
            "48 hours aspirin", "24 hours aspirin after IVT",
        ],
        "supported_intents": [
            "recommendation_lookup", "drug_choice",
            "time_window", "eligibility_criteria",
            "evidence_for_recommendation",
        ],
        "content_section_id": "4.8",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.8",
    },

    # ─────────── §4.9 Anticoagulants ───────────
    "anticoagulation_ais": {
        "title": "Anticoagulation in Acute Ischemic Stroke",
        "description": (
            "Anticoagulation management in acute ischemic stroke: "
            "early anticoagulation is generally NOT recommended "
            "(including in AF), timing of anticoagulation resumption "
            "after cardioembolic stroke, argatroban, LMWH, and "
            "specific circumstances where anticoagulation may be "
            "considered."
        ),
        "when_to_route": [
            "When should I start anticoagulation after stroke?",
            "Is early anticoagulation safe in AF stroke?",
            "When do I restart warfarin?",
            "Is heparin indicated in acute stroke?",
            "Should I use argatroban?",
        ],
        "routing_keywords": [
            "anticoagulation", "anticoagulant",
            "heparin", "LMWH", "enoxaparin",
            "warfarin", "DOAC", "apixaban", "rivaroxaban",
            "dabigatran", "edoxaban",
            "argatroban",
            "atrial fibrillation", "AF", "cardioembolic",
            "anticoagulation timing", "restart anticoagulation",
            "1-3-6-12 rule", "ELAN", "OPTIMAS",
        ],
        "supported_intents": [
            "recommendation_lookup", "time_window", "drug_choice",
            "dosing_protocol", "harm_query", "no_benefit_query",
            "sequencing",
        ],
        "content_section_id": "4.9",
        "parentChapter": "4.9",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.9",
    },

    # ─────────── §4.10-4.12 ───────────
    "volume_expansion_hemodilution": {
        "title": "Volume Expansion, Hemodilution, and Hemodynamic Augmentation",
        "description": (
            "Volume expansion, hemodilution, vasodilators, and "
            "hemodynamic augmentation in AIS. Not recommended for "
            "routine use — no clinical benefit shown."
        ),
        "when_to_route": [
            "Is volume expansion indicated in stroke?",
            "Does hemodilution help?",
            "Should I use vasodilators for stroke?",
        ],
        "routing_keywords": [
            "volume expansion", "hemodilution",
            "vasodilator", "hemodynamic augmentation",
            "albumin", "pentoxifylline",
        ],
        "supported_intents": [
            "no_benefit_query", "harm_query", "recommendation_lookup",
        ],
        "content_section_id": "4.10",
        "parentChapter": "4.10",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.10",
    },
    "neuroprotection_ais": {
        "title": "Neuroprotective Agents for AIS",
        "description": (
            "Neuroprotective agents for acute ischemic stroke. None "
            "have demonstrated clinical benefit in rigorous trials. "
            "Not recommended outside clinical trials."
        ),
        "when_to_route": [
            "Are neuroprotective agents useful in stroke?",
            "What about nerinetide?",
            "Is there a neuroprotectant approved for stroke?",
        ],
        "routing_keywords": [
            "neuroprotection", "neuroprotective", "nerinetide",
            "ESCAPE-NA1", "citicoline", "minocycline",
            "edaravone",
        ],
        "supported_intents": [
            "no_benefit_query", "knowledge_gap",
            "recommendation_lookup",
        ],
        "content_section_id": "4.11",
        "parentChapter": "4.11",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.11",
    },
    "emergency_carotid_intervention": {
        "title": "Emergency Carotid Endarterectomy / Angioplasty",
        "description": (
            "Emergency carotid endarterectomy (CEA) or carotid "
            "stenting / angioplasty in the acute stroke setting. "
            "Limited evidence; most clinicians defer to subacute "
            "intervention after initial medical stabilization."
        ),
        "when_to_route": [
            "Is emergency CEA indicated in acute stroke?",
            "Can I stent a symptomatic carotid acutely?",
            "When is carotid revascularization emergent?",
        ],
        "routing_keywords": [
            "carotid endarterectomy", "CEA",
            "carotid stenting", "CAS",
            "emergency carotid intervention",
            "symptomatic carotid stenosis",
        ],
        "supported_intents": [
            "recommendation_lookup", "eligibility_criteria",
            "alternative_options", "time_window",
        ],
        "content_section_id": "4.12",
        "parentChapter": "4.12",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.12",
    },

    # ─────────── Chapter 5: In-Hospital Care ───────────
    "stroke_unit_care": {
        "title": "Organized Stroke Unit Care",
        "description": (
            "Admission to an organized stroke unit is recommended "
            "for all acute stroke patients. Stroke units reduce "
            "mortality and improve functional outcomes compared to "
            "general medical wards."
        ),
        "when_to_route": [
            "Should my patient go to a stroke unit?",
            "What's special about a stroke unit?",
            "Does stroke unit care improve outcomes?",
        ],
        "routing_keywords": [
            "stroke unit", "organized stroke care",
            "inpatient stroke care", "dedicated stroke unit",
        ],
        "supported_intents": [
            "recommendation_lookup", "setting_of_care",
            "post_treatment_care", "systems_of_care",
        ],
        "content_section_id": "5.1",
        "parentChapter": "5.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.1",
    },
    "dysphagia_screening": {
        "title": "Dysphagia Screening and Management",
        "description": (
            "Formal swallow screening before oral intake for all "
            "acute stroke patients. Failed screens warrant a "
            "detailed dysphagia evaluation by a speech-language "
            "pathologist. Reduces aspiration pneumonia risk."
        ),
        "when_to_route": [
            "When should I screen for dysphagia?",
            "Who should do the swallow evaluation?",
            "Can my stroke patient eat?",
            "How do I prevent aspiration pneumonia?",
        ],
        "routing_keywords": [
            "dysphagia", "swallow screening", "swallowing",
            "aspiration", "aspiration pneumonia",
            "speech-language pathologist", "SLP",
            "NPO", "nil per os",
            "bedside swallow",
        ],
        "supported_intents": [
            "screening_protocol", "recommendation_lookup",
            "post_treatment_care", "monitoring_protocol",
        ],
        "content_section_id": "5.2",
        "parentChapter": "5.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.2",
    },
    "nutrition_ais": {
        "title": "Nutrition in AIS",
        "description": (
            "Early enteral nutrition is recommended for acute stroke "
            "patients who cannot safely eat by mouth. NG tube within "
            "7 days is preferred over PEG. Nutritional supplementation "
            "not routinely indicated in well-nourished patients."
        ),
        "when_to_route": [
            "When should I start tube feeds?",
            "NG tube or PEG for stroke?",
            "Is TPN indicated in acute stroke?",
            "When should nutrition start?",
        ],
        "routing_keywords": [
            "nutrition", "enteral nutrition", "tube feeds",
            "NG tube", "nasogastric", "PEG", "gastrostomy",
            "oral nutritional supplement", "malnutrition",
            "FOOD trial",
        ],
        "supported_intents": [
            "recommendation_lookup", "post_treatment_care",
            "duration_query", "drug_choice",
        ],
        "content_section_id": "5.3",
        "parentChapter": "5.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.3",
    },
    "dvt_prophylaxis_ais": {
        "title": "DVT Prophylaxis in AIS",
        "description": (
            "Deep vein thrombosis prophylaxis in acute ischemic "
            "stroke: intermittent pneumatic compression for all "
            "non-ambulatory patients; low-dose LMWH or unfractionated "
            "heparin may be considered after weighing bleeding risk. "
            "Graduated compression stockings alone are not recommended "
            "(CLOTS trial)."
        ),
        "when_to_route": [
            "DVT prophylaxis for stroke patient?",
            "Should I use heparin for DVT prevention after tPA?",
            "Are compression stockings enough?",
            "When can I start LMWH after stroke?",
        ],
        "routing_keywords": [
            "DVT prophylaxis", "VTE prevention",
            "deep vein thrombosis",
            "intermittent pneumatic compression", "IPC",
            "compression stockings", "TED hose",
            "LMWH", "low molecular weight heparin",
            "enoxaparin", "subcutaneous heparin",
            "CLOTS", "PREVAIL",
        ],
        "supported_intents": [
            "recommendation_lookup", "dosing_protocol",
            "post_treatment_care", "comparison_query",
        ],
        "content_section_id": "5.4",
        "parentChapter": "5.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.4",
    },
    "depression_screening_ais": {
        "title": "Post-Stroke Depression Screening",
        "description": (
            "Depression screening is recommended for all stroke "
            "patients during hospitalization and at follow-up. "
            "Post-stroke depression is common and affects functional "
            "recovery; selective serotonin reuptake inhibitors can be "
            "used when clinically indicated."
        ),
        "when_to_route": [
            "When should I screen for post-stroke depression?",
            "Should I start an SSRI after stroke?",
            "What screening tool for post-stroke depression?",
        ],
        "routing_keywords": [
            "post-stroke depression", "PSD",
            "depression screening",
            "PHQ-9", "Beck Depression Inventory",
            "SSRI", "fluoxetine", "citalopram", "sertraline",
            "FLAME trial", "FOCUS trial",
        ],
        "supported_intents": [
            "screening_protocol", "recommendation_lookup",
            "post_treatment_care", "drug_choice",
        ],
        "content_section_id": "5.5",
        "parentChapter": "5.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.5",
    },
    "other_inhospital_management": {
        "title": "Other In-Hospital Management Considerations",
        "description": (
            "Other in-hospital considerations: fall prevention, "
            "urinary catheter management, skin care, pain management, "
            "and palliative care. Minimize indwelling bladder catheter "
            "use; assess fall risk."
        ),
        "when_to_route": [
            "How do I prevent falls after stroke?",
            "When should I remove the foley?",
            "Pain management in acute stroke?",
            "When is palliative care appropriate?",
        ],
        "routing_keywords": [
            "fall prevention", "fall risk",
            "Foley catheter", "indwelling catheter",
            "skin care", "pressure ulcer",
            "pain management",
            "palliative care",
        ],
        "supported_intents": [
            "post_treatment_care", "recommendation_lookup",
            "complication_management",
        ],
        "content_section_id": "5.6",
        "parentChapter": "5.6",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.6",
    },
    "rehabilitation_ais": {
        "title": "Stroke Rehabilitation",
        "description": (
            "Early mobilization, physical therapy, occupational "
            "therapy, and speech therapy starting within the first "
            "24–48 hours as tolerated. Very early mobilization "
            "(<24h) is NOT recommended based on AVERT. Intensity "
            "of rehabilitation should be individualized."
        ),
        "when_to_route": [
            "When should rehab start after stroke?",
            "Is very early mobilization helpful?",
            "What did AVERT show?",
            "Should I start PT on day 1?",
        ],
        "routing_keywords": [
            "rehabilitation", "rehab",
            "physical therapy", "PT",
            "occupational therapy", "OT",
            "speech therapy", "speech-language",
            "early mobilization", "very early mobilization",
            "AVERT", "VEM",
            "intensity of rehab",
        ],
        "supported_intents": [
            "post_treatment_care", "recommendation_lookup",
            "time_window", "duration_query",
        ],
        "content_section_id": "5.7",
        "parentChapter": "5.7",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §5.7",
    },

    # ─────────── Chapter 6: Complications ───────────
    "cerebral_edema_general": {
        "title": "Cerebral Edema and Brain Swelling (General Principles)",
        "description": (
            "General recommendations for recognition and "
            "monitoring of cerebral edema and malignant stroke "
            "syndromes. Covers risk factors, clinical deterioration "
            "patterns, imaging findings, and escalation pathways."
        ),
        "when_to_route": [
            "How do I recognize malignant MCA stroke?",
            "When does cerebral edema peak?",
            "What are the warning signs of herniation?",
            "Should I monitor ICP?",
        ],
        "routing_keywords": [
            "cerebral edema", "brain swelling",
            "malignant MCA", "malignant stroke",
            "herniation", "ICP", "intracranial pressure",
            "midline shift", "mass effect",
            "clinical deterioration",
        ],
        "supported_intents": [
            "complication_management", "monitoring_protocol",
            "recommendation_lookup", "patient_specific_eligibility",
        ],
        "content_section_id": "6.1",
        "parentChapter": "6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §6.1",
    },
    "cerebral_edema_medical": {
        "title": "Medical Management of Cerebral Edema",
        "description": (
            "Medical management of cerebral edema in acute ischemic "
            "stroke: osmotic therapy (mannitol, hypertonic saline), "
            "head of bed positioning, ventilatory management, and "
            "avoidance of hypotonic fluids. Steroids are NOT "
            "recommended."
        ),
        "when_to_route": [
            "What's the dose of mannitol for cerebral edema?",
            "Should I use hypertonic saline?",
            "Are steroids helpful for stroke edema?",
            "Medical management of brain swelling?",
        ],
        "routing_keywords": [
            "mannitol", "hypertonic saline", "3% saline", "23.4% saline",
            "osmotic therapy", "osmolality",
            "dexamethasone", "corticosteroids",
            "hyperventilation", "PaCO2",
            "hypotonic fluids",
        ],
        "supported_intents": [
            "dosing_protocol", "complication_management",
            "drug_choice", "no_benefit_query", "harm_query",
        ],
        "content_section_id": "6.2",
        "parentChapter": "6.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §6.2",
    },
    "supratentorial_decompression": {
        "title": "Supratentorial Decompressive Surgery",
        "description": (
            "Decompressive hemicraniectomy for malignant MCA "
            "infarction. Reduces mortality and improves functional "
            "outcomes in selected patients, especially those "
            "<=60 years, performed within 48 hours of stroke onset. "
            "Age >60 is not an absolute contraindication but "
            "outcomes are more modest."
        ),
        "when_to_route": [
            "When is hemicraniectomy indicated?",
            "Age cutoff for decompressive surgery?",
            "What's the timing for malignant MCA surgery?",
            "Does hemicraniectomy improve outcomes?",
        ],
        "routing_keywords": [
            "decompressive hemicraniectomy", "hemicraniectomy",
            "decompressive craniectomy", "craniectomy",
            "malignant MCA",
            "DESTINY", "DECIMAL", "HAMLET",
            "DESTINY II",
        ],
        "supported_intents": [
            "recommendation_lookup", "eligibility_criteria",
            "patient_specific_eligibility", "time_window",
            "evidence_for_recommendation",
        ],
        "content_section_id": "6.3",
        "parentChapter": "6.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §6.3",
        "anchor_thresholds": [
            {"anchor": "age", "compare": "<=", "value": 60,
             "unit": "years", "row_hint": "hemicraniectomy_age_threshold"},
            {"anchor": "time from onset", "compare": "<=", "value": 48,
             "unit": "hours", "row_hint": "hemicraniectomy_timing"},
        ],
    },
    "cerebellar_decompression": {
        "title": "Cerebellar Decompressive Surgery",
        "description": (
            "Suboccipital decompressive craniectomy for cerebellar "
            "infarction with mass effect and clinical deterioration. "
            "External ventricular drainage may be added for "
            "hydrocephalus. Urgent neurosurgical consultation."
        ),
        "when_to_route": [
            "When is cerebellar decompression indicated?",
            "Should I do an EVD for cerebellar stroke?",
            "Cerebellar infarct with deterioration?",
        ],
        "routing_keywords": [
            "cerebellar infarction", "cerebellar stroke",
            "suboccipital craniectomy",
            "posterior fossa decompression",
            "external ventricular drainage", "EVD",
            "hydrocephalus",
            "brainstem compression",
        ],
        "supported_intents": [
            "recommendation_lookup", "complication_management",
            "eligibility_criteria",
        ],
        "content_section_id": "6.4",
        "parentChapter": "6.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §6.4",
    },
    "seizure_management_ais": {
        "title": "Seizure Management After Stroke",
        "description": (
            "Management of acute symptomatic seizures and "
            "post-stroke epilepsy. Treat clinical seizures; "
            "prophylactic antiseizure medication is NOT recommended. "
            "Long-term antiepileptic therapy for recurrent seizures "
            "only."
        ),
        "when_to_route": [
            "Should I give antiseizure meds prophylactically?",
            "How do I treat post-stroke seizure?",
            "Is levetiracetam indicated after stroke?",
            "Post-stroke epilepsy management?",
        ],
        "routing_keywords": [
            "seizure", "post-stroke seizure", "status epilepticus",
            "antiseizure medication", "anticonvulsant",
            "levetiracetam", "phenytoin", "valproate",
            "post-stroke epilepsy",
            "prophylactic antiseizure",
        ],
        "supported_intents": [
            "complication_management", "drug_choice",
            "no_benefit_query", "dosing_protocol",
            "recommendation_lookup",
        ],
        "content_section_id": "6.5",
        "parentChapter": "6.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §6.5",
    },
}


def main():
    with open(MAP_PATH) as f:
        sm = json.load(f)

    if "concept_sections" not in sm:
        sm["concept_sections"] = {}

    added = 0
    updated = 0
    for concept_id, routing in PROSE_CONCEPT_SECTIONS.items():
        if concept_id in sm["concept_sections"]:
            updated += 1
        else:
            added += 1
        sm["concept_sections"][concept_id] = {"id": concept_id, **routing}

    total = len(sm["concept_sections"])
    print(f"Added: {added}  Updated: {updated}  Total concept sections: {total}")

    with open(MAP_PATH, "w") as f:
        json.dump(sm, f, indent=2, ensure_ascii=False)
    print(f"Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
