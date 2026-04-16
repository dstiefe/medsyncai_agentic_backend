"""
Create concept section routing entries for every sub-topic within
the 10 sections that have PDF sub-headers. Each sub-topic becomes
its own concept section with a semantic description, routing keywords,
supported intents, and a content_section_id + category_filter that
tells knowledge_loader which rows to return.

This replaces the broad parent concept sections (like
antiplatelet_treatment → all 18 rows of §4.8) with focused
sub-topic concept sections (like antiplatelet_ivt_interaction →
only the 3 rows about aspirin in the setting of IVT).
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references/ais_guideline_section_map.json"

SUBTOPIC_CONCEPT_SECTIONS = {
    # ═══════════════════════════════════════════════════════════
    # §4.8 Antiplatelet Treatment — 4 sub-topics
    # ═══════════════════════════════════════════════════════════
    "antiplatelet_general_principles": {
        "title": "General Principles for Early Antiplatelet Therapy in AIS",
        "description": (
            "Aspirin within 48 hours of stroke onset, tirofiban and "
            "glycoprotein IIb/IIIa inhibitors in AIS, and abciximab "
            "(which is harmful). The foundational evidence for early "
            "antiplatelet use from IST, CAST, and meta-analyses."
        ),
        "when_to_route": [
            "Should I give aspirin for stroke?",
            "Is aspirin recommended within 48 hours?",
            "Is tirofiban useful in acute stroke?",
            "What about abciximab in AIS?",
        ],
        "routing_keywords": [
            "aspirin", "48 hours", "IST", "CAST",
            "tirofiban", "eptifibatide", "abciximab",
            "glycoprotein IIb/IIIa",
        ],
        "supported_intents": [
            "recommendation_lookup", "drug_choice",
            "evidence_for_recommendation", "harm_query",
        ],
        "content_section_id": "4.8",
        "category_filter": "antiplatelet_general_principles",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.8 (General principles)",
    },
    "antiplatelet_secondary_prevention": {
        "title": "Antiplatelet Therapy for Early Secondary Stroke Prevention",
        "description": (
            "Antiplatelet vs anticoagulation for noncardioembolic "
            "stroke secondary prevention. Covers WARSS, aspirin vs "
            "warfarin, cervical artery dissection (CADISS), changing "
            "antiplatelet agents, ticagrelor monotherapy (SOCRATES), "
            "triple antiplatelet therapy (TARDIS — harmful), and "
            "anticoagulation+antiplatelet in AF (harmful)."
        ),
        "when_to_route": [
            "Aspirin or warfarin for secondary prevention?",
            "What antiplatelet for cervical dissection?",
            "Is triple antiplatelet therapy safe?",
            "Should I add aspirin to anticoagulation in AF?",
            "Is ticagrelor better than aspirin for secondary prevention?",
        ],
        "routing_keywords": [
            "secondary prevention", "noncardioembolic",
            "WARSS", "warfarin", "anticoagulation",
            "cervical dissection", "CADISS", "TREAT-CAD",
            "ticagrelor", "SOCRATES",
            "triple antiplatelet", "TARDIS",
            "AF", "atrial fibrillation", "SPORTIF", "GARFIELD-AF",
        ],
        "supported_intents": [
            "drug_choice", "comparison_query",
            "recommendation_lookup", "harm_query",
            "evidence_for_recommendation",
        ],
        "content_section_id": "4.8",
        "category_filter": "antiplatelet_secondary_prevention",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.8 (Early secondary prevention)",
    },
    "antiplatelet_dapt_minor_stroke": {
        "title": "DAPT for Minor AIS and High-Risk TIA",
        "description": (
            "Dual antiplatelet therapy (clopidogrel+aspirin or "
            "ticagrelor+aspirin) for minor noncardioembolic AIS "
            "(NIHSS ≤3 or ≤5) and high-risk TIA (ABCD2 ≥4 or ≥6). "
            "Covers CHANCE, POINT, THALES, INSPIRES, and CHANCE 2 "
            "trial evidence, 21-day vs 30-day vs 90-day durations, "
            "and CYP2C19 genotype-guided selection."
        ),
        "when_to_route": [
            "Should I start DAPT for minor stroke?",
            "What DAPT regimen for minor AIS?",
            "How long should DAPT continue?",
            "Clopidogrel or ticagrelor for minor stroke?",
            "Does CYP2C19 status matter for DAPT?",
        ],
        "routing_keywords": [
            "DAPT", "dual antiplatelet",
            "clopidogrel", "ticagrelor", "aspirin",
            "minor stroke", "minor AIS", "NIHSS 3", "NIHSS 5",
            "high-risk TIA", "ABCD2",
            "CHANCE", "POINT", "THALES", "INSPIRES", "CHANCE 2",
            "CYP2C19", "21 days", "30 days",
            "loading dose", "300 mg", "600 mg",
        ],
        "supported_intents": [
            "drug_choice", "dosing_protocol", "duration_query",
            "eligibility_criteria", "evidence_for_recommendation",
            "trial_specific_data", "comparison_query",
        ],
        "content_section_id": "4.8",
        "category_filter": "antiplatelet_dapt_minor_stroke",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.8 (DAPT for minor AIS)",
    },
    "antiplatelet_ivt_interaction": {
        "title": "Antiplatelet Therapy in the Setting of IV Thrombolysis",
        "description": (
            "Aspirin use during and after IVT. IV aspirin within 90 "
            "minutes of IVT is harmful (ARTIS trial). Oral antiplatelet "
            "within 24 hours after IVT is uncertain — consider only "
            "with compelling competing indication. Aspirin is not a "
            "substitute for IVT. Eptifibatide adjunct not recommended."
        ),
        "when_to_route": [
            "Can I give aspirin after tPA?",
            "Do I give aspirin after IVT?",
            "Is IV aspirin safe during thrombolysis?",
            "When can I start antiplatelet after IVT?",
            "Aspirin within 24 hours of tPA?",
        ],
        "routing_keywords": [
            "aspirin after IVT", "aspirin after tPA",
            "antiplatelet after thrombolysis",
            "IV aspirin", "ARTIS",
            "aspirin substitute for IVT",
            "eptifibatide", "CLEAR stroke", "MOST trial",
            "24 hours after IVT",
        ],
        "supported_intents": [
            "drug_choice", "time_window", "harm_query",
            "recommendation_lookup", "no_benefit_query",
            "eligibility_criteria",
        ],
        "content_section_id": "4.8",
        "category_filter": "antiplatelet_ivt_interaction",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.8 (Antiplatelet in setting of IVT)",
    },

    # ═══════════════════════════════════════════════════════════
    # §4.3 Blood Pressure Management — 4 sub-topics
    # ═══════════════════════════════════════════════════════════
    "bp_general_ais": {
        "title": "General Blood Pressure Recommendations in AIS (Without Reperfusion)",
        "description": (
            "BP management in patients who did NOT receive IVT or EVT. "
            "Correct hypotension; treat severe comorbid hypertension; "
            "initiating BP lowering within 48-72h in patients with "
            "BP <220/120 is not effective (COR 3:No Benefit)."
        ),
        "when_to_route": [
            "What BP is too high in stroke without tPA?",
            "Should I lower BP if the patient didn't get IVT?",
            "Is antihypertensive treatment needed in acute stroke?",
            "When to treat hypertension in AIS?",
        ],
        "routing_keywords": [
            "BP general", "hypertension", "hypotension",
            "220/120", "BP lowering",
            "no reperfusion", "did not receive IVT",
        ],
        "supported_intents": [
            "threshold_target", "recommendation_lookup",
            "monitoring_protocol", "no_benefit_query",
        ],
        "content_section_id": "4.3",
        "category_filter": "bp_general",
        "parentChapter": "4.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.3 (General recommendations)",
    },
    "bp_before_reperfusion": {
        "title": "Blood Pressure Before Reperfusion Treatment (Pre-IVT, Pre-EVT)",
        "description": (
            "BP targets BEFORE administering IVT or EVT. SBP <185 mmHg "
            "and DBP <110 mmHg before IVT. SBP ≤185/110 before EVT. "
            "Based on RCT eligibility criteria from NINDS, ECASS III, "
            "and the major EVT trials."
        ),
        "when_to_route": [
            "What BP do I need before giving tPA?",
            "BP target before thrombolysis?",
            "Is 190 too high for IVT?",
            "BP before EVT?",
        ],
        "routing_keywords": [
            "BP before IVT", "BP before tPA",
            "pre-IVT BP", "pre-thrombolysis BP",
            "185/110", "SBP 185", "DBP 110",
            "BP before EVT", "pre-EVT BP",
        ],
        "supported_intents": [
            "threshold_target", "eligibility_criteria",
            "patient_specific_eligibility",
        ],
        "content_section_id": "4.3",
        "category_filter": "bp_before_reperfusion",
        "parentChapter": "4.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.3 (Before reperfusion treatment)",
        "anchor_thresholds": [
            {"anchor": "SBP", "compare": ">", "value": 185, "unit": "mmHg", "row_hint": "pre_ivt_ceiling"},
            {"anchor": "DBP", "compare": ">", "value": 110, "unit": "mmHg", "row_hint": "pre_ivt_ceiling"},
        ],
    },
    "bp_after_ivt": {
        "title": "Blood Pressure After IV Thrombolysis",
        "description": (
            "BP targets AFTER IVT administration. Maintain <180/105 "
            "mmHg for at least 24 hours after IVT. Intensive SBP "
            "reduction to <140 is NOT recommended (no benefit in "
            "functional outcome)."
        ),
        "when_to_route": [
            "BP target after tPA?",
            "What BP after thrombolysis?",
            "How tight should BP be after IVT?",
            "Should I target SBP 140 after tPA?",
        ],
        "routing_keywords": [
            "BP after IVT", "BP after tPA",
            "post-IVT BP", "post-thrombolysis BP",
            "180/105", "SBP 180",
            "SBP 140 after IVT",
        ],
        "supported_intents": [
            "threshold_target", "monitoring_protocol",
            "post_treatment_care", "no_benefit_query",
        ],
        "content_section_id": "4.3",
        "category_filter": "bp_after_ivt",
        "parentChapter": "4.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.3 (After IVT)",
        "anchor_thresholds": [
            {"anchor": "SBP", "compare": ">", "value": 180, "unit": "mmHg", "row_hint": "post_ivt_ceiling"},
            {"anchor": "DBP", "compare": ">", "value": 105, "unit": "mmHg", "row_hint": "post_ivt_ceiling"},
        ],
    },
    "bp_after_evt": {
        "title": "Blood Pressure After Endovascular Thrombectomy",
        "description": (
            "BP targets AFTER EVT. Maintain ≤180/105 for 24 hours "
            "after EVT. In successfully recanalized anterior LVO "
            "(mTICI 2b/2c/3), intensive SBP <140 for 72 hours is "
            "HARMFUL (COR 3:Harm, LOE A). Two high-quality RCTs "
            "showed lower functional independence and higher mortality."
        ),
        "when_to_route": [
            "What BP after EVT?",
            "BP target after thrombectomy?",
            "Is SBP 140 safe after EVT?",
            "BP after successful recanalization?",
            "What is the blood pressure needed after EVT?",
        ],
        "routing_keywords": [
            "BP after EVT", "BP after thrombectomy",
            "post-EVT BP", "post-thrombectomy BP",
            "180/105 after EVT",
            "mTICI 2b", "mTICI 2c", "mTICI 3",
            "SBP 140 after EVT", "intensive BP after EVT",
            "successful recanalization BP",
            "ENCHANTED2-MT", "BP-TARGET",
        ],
        "supported_intents": [
            "threshold_target", "monitoring_protocol",
            "post_treatment_care", "harm_query",
        ],
        "content_section_id": "4.3",
        "category_filter": "bp_after_evt",
        "parentChapter": "4.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.3 (After endovascular thrombectomy)",
        "anchor_thresholds": [
            {"anchor": "SBP", "compare": ">", "value": 180, "unit": "mmHg", "row_hint": "post_evt_ceiling"},
            {"anchor": "SBP", "compare": "<", "value": 140, "unit": "mmHg", "row_hint": "intensive_bp_harmful"},
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # §4.6.1 Thrombolysis Decision-Making — 5 sub-topics
    # ═══════════════════════════════════════════════════════════
    "ivt_decision_general": {
        "title": "IVT Decision-Making: General Principles",
        "description": (
            "Core principles for thrombolysis eligibility: disabling "
            "deficit assessment, NCCT sufficiency, consent in aphasic "
            "patients, glucose correction, early ischemic changes on "
            "CT, and antiplatelet use before IVT."
        ),
        "when_to_route": [
            "What do I need to check before giving tPA?",
            "Is CT enough before thrombolysis?",
            "Do I need consent for IVT?",
            "Can I give IVT if the patient is on aspirin?",
        ],
        "routing_keywords": [
            "IVT eligibility", "IVT decision",
            "disabling deficit", "NCCT", "CT before IVT",
            "consent", "glucose correction",
            "early ischemic changes", "ASPECTS",
            "antiplatelet before IVT",
        ],
        "supported_intents": [
            "eligibility_criteria", "recommendation_lookup",
            "patient_specific_eligibility", "clinical_overview",
        ],
        "content_section_id": "4.6.1",
        "category_filter": "ivt_general_principles",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1 (General principles)",
    },
    "ivt_mild_nondisabling": {
        "title": "IVT for Mild or Non-Disabling Stroke",
        "description": (
            "IVT in patients with NIHSS 0-5 and mild or non-disabling "
            "deficits. IVT is NOT recommended for non-disabling "
            "deficits (PRISMS trial). Dual antiplatelet is associated "
            "with a small increased risk of sICH but may be considered."
        ),
        "when_to_route": [
            "Should I give tPA for a NIHSS 3?",
            "Is IVT indicated for mild stroke?",
            "What about thrombolysis for non-disabling deficits?",
            "What did PRISMS show?",
        ],
        "routing_keywords": [
            "mild stroke", "minor stroke", "NIHSS 0-5",
            "non-disabling", "nondisabling",
            "PRISMS", "low NIHSS",
        ],
        "supported_intents": [
            "eligibility_criteria", "no_benefit_query",
            "patient_specific_eligibility",
        ],
        "content_section_id": "4.6.1",
        "category_filter": "ivt_mild_nondisabling",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1 (Mild/non-disabling)",
    },
    "ivt_time_sensitive": {
        "title": "Time-Sensitive IVT Administration",
        "description": (
            "The critical importance of minimizing time from symptom "
            "onset to IVT administration. Every minute of delay leads "
            "to incremental loss of salvageable brain tissue. Door-to-"
            "needle time optimization."
        ),
        "when_to_route": [
            "How fast do I need to give tPA?",
            "What's the door-to-needle target?",
            "Does time to treatment matter for IVT?",
        ],
        "routing_keywords": [
            "time to treatment", "door-to-needle", "DTN",
            "time-sensitive", "early IVT",
            "onset-to-treatment", "delay in IVT",
        ],
        "supported_intents": [
            "time_window", "threshold_target",
            "recommendation_lookup",
        ],
        "content_section_id": "4.6.1",
        "category_filter": "ivt_time_sensitive",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1 (Time-sensitive)",
    },
    "ivt_cerebral_microbleeds": {
        "title": "IVT and Cerebral Microbleeds (CMBs)",
        "description": (
            "IVT in patients with cerebral microbleeds on MRI. "
            "Treatment should NOT be delayed to screen for CMBs. "
            "IVT is reasonable with up to 10 CMBs. High CMB burden "
            "(>10) is associated with higher sICH risk; benefit is "
            "uncertain."
        ),
        "when_to_route": [
            "Can I give tPA if the patient has microbleeds?",
            "Should I check MRI for CMBs before IVT?",
            "How many microbleeds are too many for tPA?",
            "Is IVT safe with cerebral microbleeds?",
        ],
        "routing_keywords": [
            "cerebral microbleeds", "CMBs", "microbleed",
            "T2*-weighted MRI", "susceptibility-weighted imaging",
            "SWI", "GRE",
            "high CMB burden", "CMB count",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
            "harm_query", "imaging_protocol",
        ],
        "content_section_id": "4.6.1",
        "category_filter": "ivt_cerebral_microbleeds",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1 (CMBs)",
    },
    "ivt_pediatric": {
        "title": "IVT in Pediatric Patients",
        "description": (
            "IV thrombolysis in children and adolescents with AIS. "
            "Limited evidence; the TIPS trial was halted. Dosing for "
            "pediatric patients has not been determined."
        ),
        "when_to_route": [
            "Can I give tPA to a child with stroke?",
            "Is IVT indicated in pediatric stroke?",
            "What's the evidence for thrombolysis in children?",
        ],
        "routing_keywords": [
            "pediatric IVT", "pediatric thrombolysis",
            "child stroke", "adolescent stroke",
            "TIPS trial", "pediatric tPA dosing",
        ],
        "supported_intents": [
            "pediatric_specific", "eligibility_criteria",
        ],
        "content_section_id": "4.6.1",
        "category_filter": "ivt_pediatric",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.1 (Pediatric)",
    },

    # ═══════════════════════════════════════════════════════════
    # §4.6.4 Other Fibrinolytics — 2 sub-topics
    # ═══════════════════════════════════════════════════════════
    "other_iv_fibrinolytics_ais": {
        "title": "Other IV Fibrinolytic Agents for AIS",
        "description": (
            "Alternative fibrinolytic agents: reteplase (superiority "
            "to alteplase in Chinese trials), mutant prourokinase "
            "(PROST, PROST-2), desmoteplase (no benefit), urokinase, "
            "and streptokinase."
        ),
        "when_to_route": [
            "Is reteplase used for stroke?",
            "What about prourokinase?",
            "What alternatives to alteplase exist?",
        ],
        "routing_keywords": [
            "reteplase", "prourokinase", "PROST",
            "desmoteplase", "DIAS", "urokinase", "streptokinase",
        ],
        "supported_intents": [
            "alternative_options", "drug_choice",
            "evidence_for_recommendation",
        ],
        "content_section_id": "4.6.4",
        "category_filter": "other_iv_fibrinolytics",
        "parentChapter": "4.6.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.4 (Other fibrinolytics)",
    },
    "sonothrombolysis_ais": {
        "title": "Sonothrombolysis as Adjunct to IVT",
        "description": (
            "Sonothrombolysis (ultrasound-based clot lysis) as "
            "adjunctive treatment to IVT. No clinical benefit shown "
            "in RCTs (NOR-SASS, CLOTBUST-ER)."
        ),
        "when_to_route": [
            "Does sonothrombolysis work?",
            "Is ultrasound useful with tPA?",
            "What did CLOTBUST-ER show?",
        ],
        "routing_keywords": [
            "sonothrombolysis", "ultrasound thrombolysis",
            "NOR-SASS", "CLOTBUST-ER",
        ],
        "supported_intents": [
            "no_benefit_query", "evidence_for_recommendation",
        ],
        "content_section_id": "4.6.4",
        "category_filter": "sonothrombolysis",
        "parentChapter": "4.6.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.6.4 (Sonothrombolysis)",
    },

    # ═══════════════════════════════════════════════════════════
    # §4.7.2 EVT Adult — 8 sub-topics (by scenario)
    # ═══════════════════════════════════════════════════════════
    "evt_0_6h_standard": {
        "title": "EVT 0-6 Hours, ASPECTS 3-10 (Standard Window)",
        "description": (
            "Standard-window EVT for anterior LVO (ICA or M1) within "
            "6 hours, NIHSS ≥6, ASPECTS ≥3. Strong evidence from "
            "MR CLEAN, ESCAPE, EXTEND-IA, SWIFT PRIME, REVASCAT."
        ),
        "when_to_route": [
            "EVT for M1 occlusion within 6 hours?",
            "Is EVT indicated with ASPECTS 5?",
            "Standard-window thrombectomy eligibility?",
        ],
        "routing_keywords": [
            "EVT 0-6 hours", "standard window EVT",
            "ASPECTS 3-10", "anterior LVO",
            "MR CLEAN", "ESCAPE", "EXTEND-IA", "SWIFT PRIME", "REVASCAT",
        ],
        "supported_intents": [
            "eligibility_criteria", "evidence_for_recommendation",
            "patient_specific_eligibility",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_0_6h_aspects_3_10",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (0-6h, ASPECTS 3-10)",
    },
    "evt_6_24h_standard": {
        "title": "EVT 6-24 Hours, ASPECTS 6-10 (Extended Window, Imaging Selected)",
        "description": (
            "Extended-window EVT for anterior LVO presenting 6-24 "
            "hours from onset, with imaging selection (DAWN or "
            "DEFUSE-3 criteria). NIHSS ≥6, ASPECTS ≥6."
        ),
        "when_to_route": [
            "EVT at 12 hours?",
            "Can I do thrombectomy at 18 hours?",
            "DAWN or DEFUSE-3 criteria for late EVT?",
        ],
        "routing_keywords": [
            "EVT 6-24 hours", "extended window EVT",
            "DAWN", "DEFUSE-3", "late window",
            "ASPECTS 6-10", "imaging selection",
        ],
        "supported_intents": [
            "eligibility_criteria", "time_window",
            "patient_specific_eligibility", "imaging_protocol",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_6_24h_aspects_6_10",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (6-24h, ASPECTS 6-10)",
    },
    "evt_6_24h_large_core": {
        "title": "EVT 6-24 Hours, ASPECTS 3-5 (Large Core, Extended Window)",
        "description": (
            "Large-core EVT in the extended window (6-24h) for "
            "patients with ASPECTS 3-5, age <80, NIHSS ≥10. Based on "
            "SELECT2, ANGEL-ASPECT trials."
        ),
        "when_to_route": [
            "EVT for large core at 12 hours?",
            "Can I do EVT with ASPECTS 4 at 18 hours?",
            "SELECT2 criteria?",
        ],
        "routing_keywords": [
            "large core EVT extended", "ASPECTS 3-5 late",
            "SELECT2", "ANGEL-ASPECT",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_6_24h_aspects_3_5",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (6-24h, ASPECTS 3-5)",
    },
    "evt_0_6h_large_core": {
        "title": "EVT 0-6 Hours, ASPECTS 0-2 (Very Large Core)",
        "description": (
            "EVT in the standard window (0-6h) with very large core "
            "(ASPECTS 0-2). Based on LASTE trial."
        ),
        "when_to_route": [
            "Can I do EVT with ASPECTS 1?",
            "EVT for very large core?",
            "What did LASTE show?",
        ],
        "routing_keywords": [
            "ASPECTS 0-2", "very large core",
            "LASTE",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_0_6h_aspects_0_2",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (0-6h, ASPECTS 0-2)",
    },
    "evt_preexisting_disability": {
        "title": "EVT with Pre-Existing Disability (Pre-Stroke mRS ≥2)",
        "description": (
            "EVT in patients with pre-stroke functional disability. "
            "Mild disability (mRS 2): EVT reasonable. Moderate "
            "disability (mRS 3-4): benefit uncertain."
        ),
        "when_to_route": [
            "Can I do EVT if pre-stroke mRS is 3?",
            "EVT for a patient already disabled?",
            "Thrombectomy with baseline mRS 2?",
        ],
        "routing_keywords": [
            "pre-stroke mRS", "pre-existing disability",
            "baseline mRS", "mRS 2", "mRS 3", "mRS 4",
            "mild disability EVT", "moderate disability EVT",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_0_6h_mild_disability",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (Pre-existing disability)",
    },
    "evt_m2_distal_vessel": {
        "title": "EVT for M2 and Distal/Medium Vessel Occlusions",
        "description": (
            "EVT for M2 MCA, distal MCA, ACA, and PCA occlusions. "
            "Dominant proximal M2: benefit uncertain (ESCAPE-MeVO, "
            "DISTAL). Distal/medium vessels: no clear benefit."
        ),
        "when_to_route": [
            "Is EVT indicated for M2 occlusion?",
            "Thrombectomy for distal vessel?",
            "EVT for ACA or PCA occlusion?",
            "What about medium vessel occlusion?",
        ],
        "routing_keywords": [
            "M2 occlusion", "M2 MCA", "proximal M2",
            "distal vessel", "medium vessel", "MeVO",
            "ACA occlusion", "PCA occlusion", "M3",
            "ESCAPE-MeVO", "DISTAL",
        ],
        "supported_intents": [
            "eligibility_criteria", "patient_specific_eligibility",
            "evidence_for_recommendation",
        ],
        "content_section_id": "4.7.2",
        "category_filter": "evt_0_6h_proximal_m2",
        "parentChapter": "4.7.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.2 (M2/distal vessel)",
    },

    # ═══════════════════════════════════════════════════════════
    # §4.7.4 Endovascular Techniques — 2 sub-topics
    # ═══════════════════════════════════════════════════════════
    "evt_general_techniques": {
        "title": "Thrombectomy General Techniques",
        "description": (
            "Stent retrievers, contact aspiration, combination "
            "techniques, TICI reperfusion scoring, general anesthesia "
            "vs sedation, and balloon-guide catheters."
        ),
        "when_to_route": [
            "Stent retriever or aspiration?",
            "What TICI score is success?",
            "General anesthesia or sedation for EVT?",
            "Does a balloon-guide catheter help?",
        ],
        "routing_keywords": [
            "stent retriever", "aspiration", "ADAPT",
            "TICI", "mTICI", "reperfusion score",
            "general anesthesia", "conscious sedation",
            "balloon-guide catheter", "BGC",
            "ASTER",
        ],
        "supported_intents": [
            "drug_choice", "comparison_query",
            "evidence_for_recommendation",
        ],
        "content_section_id": "4.7.4",
        "category_filter": "thrombectomy_general_techniques",
        "parentChapter": "4.7.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.4 (General techniques)",
    },
    "evt_adjunctive_techniques": {
        "title": "Thrombectomy Adjunctive Techniques",
        "description": (
            "Tandem occlusion management (emergent carotid stenting), "
            "rescue balloon angioplasty / stenting, intra-arterial "
            "thrombolytics (alteplase, tenecteplase, urokinase), and "
            "tirofiban before EVT."
        ),
        "when_to_route": [
            "How do I manage tandem occlusion?",
            "Is intra-arterial tPA useful after failed EVT?",
            "Rescue stenting for incomplete thrombectomy?",
            "Tirofiban before EVT?",
        ],
        "routing_keywords": [
            "tandem occlusion", "carotid stenting",
            "rescue stenting", "rescue angioplasty",
            "intra-arterial tPA", "intra-arterial alteplase",
            "intra-arterial tenecteplase",
            "tirofiban before EVT",
            "ANGEL-REBOOT", "CHOICE", "RESCUE-BT",
        ],
        "supported_intents": [
            "drug_choice", "sequencing",
            "evidence_for_recommendation", "alternative_options",
        ],
        "content_section_id": "4.7.4",
        "category_filter": "thrombectomy_adjunctive_techniques",
        "parentChapter": "4.7.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §4.7.4 (Adjunctive techniques)",
    },

    # ═══════════════════════════════════════════════════════════
    # §2.4 EMS Destination — 2 sub-topics
    # ═══════════════════════════════════════════════════════════
    "ems_destination_general": {
        "title": "EMS Destination: General Principles",
        "description": (
            "EMS transport destination decisions for suspected stroke: "
            "closest appropriate stroke center, direct transport for "
            "suspected LVO, and bypassing non-stroke-capable hospitals."
        ),
        "when_to_route": [
            "Where should EMS take a stroke patient?",
            "Should I bypass to a comprehensive center?",
            "Direct transport for LVO?",
        ],
        "routing_keywords": [
            "EMS destination", "transport destination",
            "closest stroke center", "bypass",
            "direct transport", "LVO transport",
            "RACECAT",
        ],
        "supported_intents": [
            "recommendation_lookup", "setting_of_care",
        ],
        "content_section_id": "2.4",
        "category_filter": "general_principles",
        "parentChapter": "2.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.4 (General principles)",
    },
    "ems_interhospital_transfer": {
        "title": "Interhospital Transfer for Stroke",
        "description": (
            "Protocols for interhospital transfer of stroke patients "
            "needing a higher level of care. Door-in-door-out (DIDO) "
            "time optimization."
        ),
        "when_to_route": [
            "When should I transfer a stroke patient?",
            "What's the DIDO target?",
            "Transfer protocols for stroke?",
        ],
        "routing_keywords": [
            "interhospital transfer", "DIDO",
            "door-in-door-out", "transfer protocols",
            "drip and ship",
        ],
        "supported_intents": [
            "recommendation_lookup", "time_window",
            "setting_of_care",
        ],
        "content_section_id": "2.4",
        "category_filter": "interhospital_transfer",
        "parentChapter": "2.4",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.4 (Interhospital transfer)",
    },

    # ═══════════════════════════════════════════════════════════
    # §2.8 Telemedicine — 4 sub-topics
    # ═══════════════════════════════════════════════════════════
    "prehospital_telemedicine": {
        "title": "Prehospital Telemedicine for Stroke",
        "description": (
            "Telemedicine use in the ambulance before hospital arrival "
            "for patients with acute neurological deficits."
        ),
        "when_to_route": [
            "Can telemedicine be used in the ambulance?",
            "Prehospital telestroke assessment?",
        ],
        "routing_keywords": [
            "prehospital telemedicine", "ambulance telemedicine",
            "prehospital telestroke",
        ],
        "supported_intents": ["recommendation_lookup", "setting_of_care"],
        "content_section_id": "2.8",
        "category_filter": "prehospital_telemedicine",
        "parentChapter": "2.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.8 (Prehospital telemedicine)",
    },
    "telestroke_ivt_decision": {
        "title": "Telestroke for IVT Decision-Making",
        "description": (
            "Using telestroke for thrombolytic decision-making and "
            "administration at hospitals without on-site stroke "
            "expertise. Teleradiology for brain imaging reads."
        ),
        "when_to_route": [
            "Can telestroke be used for tPA decisions?",
            "Is teleradiology reliable for stroke imaging?",
        ],
        "routing_keywords": [
            "telestroke", "teleradiology",
            "IVT decision telestroke", "tPA decision remote",
            "STRokEDOC",
        ],
        "supported_intents": ["recommendation_lookup", "setting_of_care"],
        "content_section_id": "2.8",
        "category_filter": "telestroke_ivt_decision",
        "parentChapter": "2.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.8 (Telestroke for IVT)",
    },
    "telestroke_systems_of_care": {
        "title": "Telestroke in Stroke Systems of Care",
        "description": (
            "Integration of telestroke networks into stroke systems "
            "of care for triage, patient selection for transfer, and "
            "quality improvement."
        ),
        "when_to_route": [
            "How should telestroke networks be organized?",
            "Telestroke for patient triage?",
        ],
        "routing_keywords": [
            "telestroke network", "telestroke systems",
            "telestroke triage", "hub and spoke",
        ],
        "supported_intents": ["systems_of_care", "setting_of_care"],
        "content_section_id": "2.8",
        "category_filter": "telestroke_systems_of_care",
        "parentChapter": "2.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.8 (Telestroke systems)",
    },

    # ═══════════════════════════════════════════════════════════
    # §2.3 and §3.2 sub-topics kept simpler (fewer clinical
    # decision scenarios that need distinct routing)
    # ═══════════════════════════════════════════════════════════
    "prehospital_stroke_recognition": {
        "title": "Prehospital Stroke Recognition and Assessment",
        "description": (
            "EMS dispatcher recognition, prehospital stroke scales "
            "(LAMS, RACE, CPSS, FAST-ED, VAN), and EMS prenotification."
        ),
        "when_to_route": [
            "What prehospital stroke scale should EMS use?",
            "How does EMS prenotification help?",
        ],
        "routing_keywords": [
            "prehospital stroke scale", "LAMS", "RACE", "CPSS",
            "FAST-ED", "VAN", "dispatcher recognition",
            "EMS prenotification",
        ],
        "supported_intents": ["recommendation_lookup", "screening_protocol"],
        "content_section_id": "2.3",
        "category_filter": "prehospital_stroke_recognition",
        "parentChapter": "2.3",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §2.3 (Stroke recognition)",
    },
    "imaging_evt_selection": {
        "title": "Imaging for EVT Patient Selection",
        "description": (
            "CTA, CTP, MR DWI-PWI for endovascular thrombectomy "
            "patient selection. Includes standard and extended window "
            "imaging approaches and direct-to-angiography suite."
        ),
        "when_to_route": [
            "What imaging before EVT?",
            "CTA or CTP for thrombectomy selection?",
            "Direct to angiography suite?",
        ],
        "routing_keywords": [
            "CTA before EVT", "CTP for EVT",
            "EVT imaging selection", "vascular imaging EVT",
            "direct to angiography", "DTAS",
        ],
        "supported_intents": ["imaging_protocol", "eligibility_criteria"],
        "content_section_id": "3.2",
        "category_filter": "evt_vascular_imaging",
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, §3.2 (EVT imaging selection)",
    },
}


def main():
    with open(MAP_PATH) as f:
        sm = json.load(f)

    if "concept_sections" not in sm:
        sm["concept_sections"] = {}

    # Remove the broad parent concept sections that are now replaced
    # by their sub-topic children
    parents_to_remove = [
        "antiplatelet_treatment",  # replaced by 4 sub-topics
        "bp_management_ais",       # replaced by 4 sub-topics
    ]
    for parent_id in parents_to_remove:
        if parent_id in sm["concept_sections"]:
            del sm["concept_sections"][parent_id]
            print(f"  Removed broad parent: {parent_id}")

    added = 0
    for concept_id, routing in SUBTOPIC_CONCEPT_SECTIONS.items():
        sm["concept_sections"][concept_id] = {"id": concept_id, **routing}
        added += 1

    total = len(sm["concept_sections"])
    print(f"\n  Added: {added} sub-topic concept sections")
    print(f"  Total concept sections: {total}")

    with open(MAP_PATH, "w") as f:
        json.dump(sm, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
