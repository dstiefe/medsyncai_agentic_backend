"""Declarative mapping: category → allowed intent_affinity set.

This is the SOURCE OF TRUTH for atom intent classification. It replaces
lexical/keyword-proximity intent tagging from the LLM classifier with
deterministic lookup by category.

Guiding principle
-----------------
An atom's `intent_affinity` answers the question: "When would a
clinician look this atom up?" — NOT "what words does this atom
contain?" If a rec mentions CTA but is instructing a hospital on
capability tiering, imaging_protocol does NOT belong here — a clinician
asking 'what imaging do I need' wants imaging recs, not transfer
workflow. Same for any keyword-adjacency.

For each category we list the intents that a clinician would actually
be answering when they look up recs in that category. Most categories
need 2-4 intents. More than that is usually a sign the category is too
broad or the intent assignment is too generous.

Intent schema (the 44 intents available)
----------------------------------------
Drawn from `references/intent_content_source_map.json`. Abbreviated
list with clinical framing:

    recommendation_lookup          "what does the guideline say about X"
    cor_loe_query                  "what COR/LOE does X have"
    clinical_overview              "tell me about X"
    full_topic_deep_dive           expansive explanation of a topic
    algorithm_walkthrough          walk me through the decision algorithm
    table_lookup                   "show me the X table"

    eligibility_criteria           "who gets X"
    patient_specific_eligibility   "can THIS patient get X"
    contraindications              "when is X contraindicated"
    harm_query                     "could X cause harm here"
    no_benefit_query               "when is X of no benefit"

    dosing_protocol                "what dose / how to administer X"
    drug_choice                    "which drug for X"
    time_window                    "what time window"
    threshold_target               "what threshold / target for X"
    duration_query                 "how long"
    treatment_modality_choice      "which treatment modality"
    alternative_options            "what alternatives"
    sequencing                     "when in the sequence does X happen"
    reversal_protocol              "how to reverse X"

    imaging_protocol               "what imaging do I order"
    monitoring_protocol            "how do I monitor X"
    screening_protocol             "how do I screen for X"

    complication_management        "how do I manage complication X"
    post_treatment_care            "what happens after X"
    risk_factor_inquiry            "what are the risk factors for X"

    comparison_query               "X vs Y"
    rationale_explanation          "why does the guideline say X"
    rationale_with_uncertainty     rationale when evidence is uncertain

    evidence_for_recommendation    "what evidence supports X"
    evidence_with_confidence       "what does high-confidence evidence say"
    evidence_with_recommendation   "what's the recommendation evidence combo"
    evidence_vs_gaps               "what's established vs still open"
    trial_specific_data            "what did trial X show"
    current_understanding_and_gaps "what do we know and not know"
    knowledge_gap                  "what's an open question in X"
    recommendation_with_confidence a rec paired with confidence language

    setting_of_care                "at what setting / venue"
    systems_of_care                "how are services organized"
    pediatric_specific             "in pediatric patients"

    definition_lookup              "what is X"
    narrative_context              synopsis-level background
    what_changed                   "what's new in the 2026 update"
    out_of_scope                   (flag-only; not used as retrieval target)

Review status per category
--------------------------
Each entry is flagged:
    STABLE    — confident call, maps cleanly to a clinician's lookup intent
    REVIEW    — best guess; clinician should sign off before this ships
    DEFERRED  — single-atom category or narrative summary; keep permissive

Change log
----------
2026-04-17  Initial decl. mapping, replacing LLM free-tag classification.
"""
from __future__ import annotations

from typing import Dict, List, Tuple


# (intent_set, review_status)
Entry = Tuple[List[str], str]


CATEGORY_INTENTS: Dict[str, Entry] = {
    # ─── Contraindications (Table 8 subsections) ──────────────────
    "absolute_contraindication": (
        ["contraindications", "harm_query", "no_benefit_query",
         "patient_specific_eligibility"],
        "STABLE",
    ),
    "relative_contraindication": (
        ["contraindications", "harm_query",
         "patient_specific_eligibility"],
        "STABLE",
    ),
    "benefit_greater_than_risk": (
        ["eligibility_criteria", "eligibility_criteria",
         "patient_specific_eligibility",
         "evidence_for_recommendation"],
        "STABLE",
    ),

    # ─── T4 disabling deficit tiers ───────────────────────────────
    # Added definition_lookup + clinical_overview across all three
    # tiers so "What defines a disabling stroke?" / "What counts as
    # non-disabling?" queries route here properly. Earlier these
    # categories only carried eligibility/harm intents, so a
    # `definition_lookup`-intent query scored 0 on intent match for
    # T4 atoms — and the low-confidence path then dropped the query
    # to "insufficient content" despite T4.3 summary scoring 0.695
    # cosine against "non-disabling stroke".
    "disabling_deficit_framing": (
        ["eligibility_criteria", "clinical_overview",
         "definition_lookup"],
        "STABLE",
    ),
    "typically_disabling": (
        ["eligibility_criteria", "definition_lookup",
         "clinical_overview", "harm_query"],
        "STABLE",
    ),
    "may_not_be_disabling": (
        ["no_benefit_query", "eligibility_criteria",
         "definition_lookup", "clinical_overview"],
        "STABLE",
    ),

    # ─── Airway / breathing / oxygenation ─────────────────────────
    "airway": (
        ["complication_management", "post_treatment_care",
         "recommendation_lookup"],
        "REVIEW",
    ),
    "airway_oxygenation_ais": (
        ["recommendation_lookup", "threshold_target",
         "monitoring_protocol"],
        "REVIEW",
    ),

    # ─── Anticoagulation ──────────────────────────────────────────
    "anticoagulant": (
        ["drug_choice", "harm_query", "contraindications",
         "recommendation_lookup"],
        "REVIEW",
    ),
    "anticoagulation_ais": (
        ["drug_choice", "harm_query", "recommendation_lookup"],
        "REVIEW",
    ),

    # ─── Antiplatelet ─────────────────────────────────────────────
    "antiplatelet_general_principles": (
        ["drug_choice", "time_window", "recommendation_lookup"],
        "REVIEW",
    ),
    "antiplatelet_ivt_interaction": (
        ["harm_query", "time_window", "contraindications",
         "recommendation_lookup"],
        "STABLE",
    ),
    "antiplatelet_secondary_prevention": (
        ["drug_choice", "duration_query", "recommendation_lookup"],
        "STABLE",
    ),
    "antiplatelet_dapt_minor_stroke": (
        ["drug_choice", "duration_query", "eligibility_criteria",
         "recommendation_lookup"],
        "STABLE",
    ),
    "dapt_algorithm_minor_stroke": (
        ["algorithm_walkthrough", "drug_choice",
         "recommendation_lookup"],
        "STABLE",
    ),
    "dapt_trial": (
        ["trial_specific_data", "evidence_for_recommendation",
         "comparison_query"],
        "STABLE",
    ),

    # ─── Imaging (everything primarily about what to image) ───────
    "general_brain_imaging": (
        ["imaging_protocol", "recommendation_lookup"],
        "STABLE",
    ),
    "initial_imaging_ais": (
        ["imaging_protocol", "clinical_overview"],
        "STABLE",
    ),
    "evt_advanced_imaging": (
        ["imaging_protocol", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_vascular_imaging": (
        ["imaging_protocol", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_direct_angiography": (
        ["imaging_protocol", "recommendation_lookup"],
        "REVIEW",
    ),
    "evt_transfer_imaging": (
        ["imaging_protocol", "setting_of_care"],
        "STABLE",
    ),
    "extended_window_imaging": (
        ["imaging_protocol", "eligibility_criteria", "time_window"],
        "STABLE",
    ),
    "extended_window_ivt": (
        ["eligibility_criteria", "time_window", "imaging_protocol"],
        "STABLE",
    ),

    # ─── Diagnostic labs / tests (not imaging) ────────────────────
    "diagnostic_tests": (
        ["recommendation_lookup", "screening_protocol"],
        "REVIEW",
    ),
    "other_diagnostic_tests_ais": (
        ["recommendation_lookup", "screening_protocol"],
        "REVIEW",
    ),
    "aspects_scoring": (
        ["definition_lookup", "imaging_protocol",
         "eligibility_criteria"],
        "STABLE",
    ),

    # ─── Blood pressure ───────────────────────────────────────────
    "bp_after_evt": (
        ["threshold_target", "monitoring_protocol",
         "post_treatment_care"],
        "STABLE",
    ),
    "bp_after_ivt": (
        ["threshold_target", "monitoring_protocol",
         "post_treatment_care"],
        "STABLE",
    ),
    "bp_before_reperfusion": (
        ["threshold_target", "eligibility_criteria"],
        "STABLE",
    ),
    "bp_general": (
        ["threshold_target", "recommendation_lookup"],
        "STABLE",
    ),

    # ─── Brain swelling / edema / decompression ───────────────────
    "brain_swelling_general": (
        ["complication_management", "recommendation_lookup"],
        "REVIEW",
    ),
    "brain_swelling_medical": (
        ["complication_management", "drug_choice",
         "harm_query"],
        "REVIEW",
    ),
    "cerebral_edema_general": (
        ["complication_management", "recommendation_lookup"],
        "DEFERRED",
    ),
    "cerebral_edema_medical": (
        ["complication_management", "drug_choice"],
        "DEFERRED",
    ),
    "cerebellar_surgical": (
        ["complication_management", "treatment_modality_choice"],
        "REVIEW",
    ),
    "cerebellar_decompression": (
        ["complication_management", "treatment_modality_choice"],
        "DEFERRED",
    ),
    "supratentorial_decompression": (
        ["complication_management", "treatment_modality_choice"],
        "DEFERRED",
    ),
    "supratentorial_surgical": (
        ["complication_management", "treatment_modality_choice",
         "eligibility_criteria"],
        "REVIEW",
    ),

    # ─── Carotid ──────────────────────────────────────────────────
    "carotid": (
        ["treatment_modality_choice", "recommendation_lookup"],
        "DEFERRED",
    ),
    "emergency_carotid_intervention": (
        ["treatment_modality_choice", "recommendation_lookup"],
        "DEFERRED",
    ),

    # ─── Depression / psych ───────────────────────────────────────
    "depression": (
        ["screening_protocol", "post_treatment_care"],
        "REVIEW",
    ),
    "depression_screening_ais": (
        ["screening_protocol", "post_treatment_care"],
        "DEFERRED",
    ),

    # ─── DVT / dysphagia / nutrition / inpatient care ─────────────
    "dvt_prophylaxis": (
        ["drug_choice", "eligibility_criteria", "contraindications",
         "recommendation_lookup"],
        "STABLE",
    ),
    "dvt_prophylaxis_ais": (
        ["drug_choice", "recommendation_lookup"],
        "DEFERRED",
    ),
    "dysphagia": (
        ["screening_protocol", "complication_management"],
        "STABLE",
    ),
    "dysphagia_screening": (
        ["screening_protocol"],
        "DEFERRED",
    ),
    "nutrition": (
        ["post_treatment_care", "recommendation_lookup"],
        "REVIEW",
    ),
    "nutrition_ais": (
        ["post_treatment_care", "recommendation_lookup"],
        "DEFERRED",
    ),
    "inpatient_other": (
        ["recommendation_lookup", "post_treatment_care"],
        "REVIEW",
    ),
    "other_inhospital_management": (
        ["post_treatment_care", "recommendation_lookup"],
        "DEFERRED",
    ),

    # ─── Emergency evaluation / stroke team activation ────────────
    "emergency_evaluation": (
        ["systems_of_care", "screening_protocol",
         "clinical_overview"],
        "REVIEW",
    ),
    "thrombolysis_decision_making": (
        ["eligibility_criteria", "algorithm_walkthrough",
         "recommendation_lookup"],
        "DEFERRED",
    ),

    # ─── EMS / prehospital ────────────────────────────────────────
    "ems_systems": (
        ["systems_of_care", "setting_of_care"],
        "STABLE",
    ),
    "prehospital_stroke_recognition": (
        ["screening_protocol", "systems_of_care"],
        "STABLE",
    ),
    "prehospital_treatment": (
        ["drug_choice", "harm_query", "no_benefit_query"],
        "STABLE",
    ),
    "prehospital_telemedicine": (
        ["systems_of_care", "setting_of_care"],
        "STABLE",
    ),
    "mobile_stroke_unit": (
        ["systems_of_care", "setting_of_care",
         "treatment_modality_choice"],
        "STABLE",
    ),

    # ─── EVT eligibility (by time / ASPECTS / disability) ─────────
    "evt_0_6h_aspects_0_2": (
        ["eligibility_criteria", "patient_specific_eligibility",
         "time_window"],
        "STABLE",
    ),
    "evt_0_6h_aspects_3_10": (
        ["eligibility_criteria", "patient_specific_eligibility",
         "time_window"],
        "STABLE",
    ),
    "evt_0_6h_mild_disability": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_0_6h_moderate_disability": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_0_6h_proximal_m2": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_6_24h_aspects_3_5": (
        ["eligibility_criteria", "patient_specific_eligibility",
         "time_window"],
        "STABLE",
    ),
    "evt_6_24h_aspects_6_10": (
        ["eligibility_criteria", "patient_specific_eligibility",
         "time_window"],
        "STABLE",
    ),
    "evt_adult_eligibility": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "DEFERRED",
    ),
    "evt_distal_medium_vessel": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_ivt_bridging": (
        ["sequencing", "treatment_modality_choice"],
        "DEFERRED",
    ),
    "evt_pediatric": (
        ["pediatric_specific", "eligibility_criteria"],
        "STABLE",
    ),
    "evt_posterior": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "STABLE",
    ),
    "evt_posterior_circulation": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "DEFERRED",
    ),
    "evt_techniques": (
        ["treatment_modality_choice"],
        "DEFERRED",
    ),
    "eligibility_algorithm_evt": (
        ["algorithm_walkthrough", "eligibility_criteria"],
        "DEFERRED",
    ),
    "thrombectomy_adjunctive_techniques": (
        ["treatment_modality_choice", "alternative_options"],
        "REVIEW",
    ),
    "thrombectomy_general_techniques": (
        ["treatment_modality_choice", "comparison_query"],
        "REVIEW",
    ),

    # ─── IVT (thrombolysis) ───────────────────────────────────────
    "ivt_administration_step": (
        ["monitoring_protocol", "post_treatment_care"],
        "STABLE",
    ),
    "ivt_agent": (
        ["drug_choice", "comparison_query", "dosing_protocol"],
        "STABLE",
    ),
    "ivt_cerebral_microbleeds": (
        ["imaging_protocol", "eligibility_criteria",
         "threshold_target"],
        "STABLE",
    ),
    "ivt_concomitant": (
        ["sequencing", "treatment_modality_choice"],
        "REVIEW",
    ),
    "ivt_dosing": (
        ["dosing_protocol", "drug_choice"],
        "STABLE",
    ),
    "tenecteplase_weight_band": (
        ["dosing_protocol"],
        "STABLE",
    ),
    "ivt_extended": (
        ["eligibility_criteria", "time_window", "imaging_protocol"],
        "STABLE",
    ),
    "ivt_general_principles": (
        ["eligibility_criteria", "rationale_explanation",
         "recommendation_lookup"],
        "REVIEW",
    ),
    "ivt_mild_nondisabling": (
        ["eligibility_criteria", "harm_query", "no_benefit_query"],
        "STABLE",
    ),
    "ivt_pediatric": (
        ["pediatric_specific", "eligibility_criteria"],
        "STABLE",
    ),
    "ivt_special_circumstances": (
        ["patient_specific_eligibility", "eligibility_criteria"],
        "DEFERRED",
    ),
    "ivt_specific": (
        ["eligibility_criteria", "patient_specific_eligibility"],
        "REVIEW",
    ),
    "ivt_time_sensitive": (
        ["time_window", "sequencing"],
        "REVIEW",
    ),
    "thrombolytic_agent_choice": (
        ["drug_choice", "comparison_query"],
        "DEFERRED",
    ),
    "other_iv_fibrinolytics": (
        ["drug_choice", "alternative_options",
         "comparison_query"],
        "STABLE",
    ),
    "alternative_fibrinolytics": (
        ["drug_choice", "alternative_options"],
        "DEFERRED",
    ),
    "sonothrombolysis": (
        ["alternative_options", "no_benefit_query"],
        "STABLE",
    ),

    # ─── Management algorithms (Tables 5/6) ───────────────────────
    "sich_management": (
        ["complication_management", "post_treatment_care",
         "reversal_protocol"],
        "STABLE",
    ),
    "angioedema_management": (
        ["complication_management", "post_treatment_care"],
        "STABLE",
    ),

    # ─── Organization / hospital tiers / transfer / telemedicine ──
    "organization": (
        ["systems_of_care", "setting_of_care",
         "recommendation_lookup"],
        "STABLE",
    ),
    "hospital_capabilities": (
        ["systems_of_care", "setting_of_care"],
        "DEFERRED",
    ),
    "interhospital_transfer": (
        ["systems_of_care", "setting_of_care", "sequencing"],
        "STABLE",
    ),
    "telestroke_ivt_decision": (
        ["systems_of_care", "setting_of_care"],
        "STABLE",
    ),
    "telestroke_ivt_delivery": (
        ["systems_of_care", "setting_of_care"],
        "STABLE",
    ),
    "telestroke_systems_of_care": (
        ["systems_of_care", "setting_of_care"],
        "STABLE",
    ),
    "stroke_unit_care": (
        ["setting_of_care", "systems_of_care"],
        "STABLE",
    ),
    "stroke_units": (
        ["setting_of_care", "systems_of_care"],
        "DEFERRED",
    ),
    "quality_improvement": (
        ["systems_of_care", "monitoring_protocol"],
        "REVIEW",
    ),

    # ─── Awareness / scales / screening / framing ─────────────────
    "stroke_awareness": (
        ["systems_of_care", "clinical_overview"],
        "REVIEW",
    ),
    "stroke_scales": (
        ["screening_protocol", "definition_lookup"],
        "DEFERRED",
    ),
    "stroke_scales_nihss": (
        ["screening_protocol", "definition_lookup"],
        "DEFERRED",
    ),
    "general_principles": (
        ["clinical_overview", "recommendation_lookup"],
        "REVIEW",
    ),
    "overview": (
        ["clinical_overview"],
        "DEFERRED",
    ),

    # ─── Glucose / temperature / neuroprotection / misc medical ───
    "glucose": (
        ["threshold_target", "monitoring_protocol"],
        "STABLE",
    ),
    "glucose_management_ais": (
        ["threshold_target", "monitoring_protocol"],
        "DEFERRED",
    ),
    "temperature": (
        ["threshold_target", "monitoring_protocol",
         "complication_management"],
        "STABLE",
    ),
    "temperature_management_ais": (
        ["threshold_target", "monitoring_protocol"],
        "DEFERRED",
    ),
    "neuroprotection_ais": (
        ["drug_choice", "alternative_options", "no_benefit_query"],
        "DEFERRED",
    ),
    "neuroprotective": (
        ["drug_choice", "no_benefit_query"],
        "DEFERRED",
    ),
    "volume_expansion": (
        ["drug_choice", "no_benefit_query"],
        "REVIEW",
    ),
    "volume_expansion_hemodilution": (
        ["drug_choice", "no_benefit_query"],
        "DEFERRED",
    ),
    "head_positioning": (
        ["recommendation_lookup", "post_treatment_care"],
        "REVIEW",
    ),
    "head_positioning_ais": (
        ["recommendation_lookup"],
        "DEFERRED",
    ),

    # ─── Rehabilitation / post-stroke ─────────────────────────────
    "rehabilitation": (
        ["post_treatment_care", "recommendation_lookup"],
        "STABLE",
    ),
    "rehabilitation_ais": (
        ["post_treatment_care"],
        "DEFERRED",
    ),

    # ─── Seizures ─────────────────────────────────────────────────
    "seizures": (
        ["complication_management", "drug_choice"],
        "STABLE",
    ),
    "seizure_management_ais": (
        ["complication_management", "drug_choice"],
        "DEFERRED",
    ),

    # ─── Pediatric overlay ────────────────────────────────────────
    "pediatric_considerations": (
        ["pediatric_specific", "clinical_overview"],
        "REVIEW",
    ),

    # ─── Table section summaries (auto-generated narrative) ───────
    "table_section_summary": (
        ["clinical_overview", "narrative_context"],
        "STABLE",
    ),
    "absolute_contraindication_summary": (
        ["clinical_overview", "contraindications"],
        "STABLE",
    ),
    "relative_contraindication_summary": (
        ["clinical_overview", "contraindications"],
        "STABLE",
    ),
    "benefit_greater_than_risk_summary": (
        ["clinical_overview", "eligibility_criteria"],
        "STABLE",
    ),
    "disabling_deficit_framing_summary": (
        ["clinical_overview", "definition_lookup"],
        "STABLE",
    ),
    "typically_disabling_summary": (
        ["clinical_overview", "definition_lookup"],
        "STABLE",
    ),
    "may_not_be_disabling_summary": (
        ["clinical_overview", "definition_lookup"],
        "STABLE",
    ),
    "sich_management_summary": (
        ["clinical_overview", "complication_management"],
        "STABLE",
    ),
    "angioedema_management_summary": (
        ["clinical_overview", "complication_management"],
        "STABLE",
    ),
    "ivt_dosing_summary": (
        ["clinical_overview", "dosing_protocol"],
        "STABLE",
    ),
    "tenecteplase_weight_band_summary": (
        ["clinical_overview", "dosing_protocol"],
        "STABLE",
    ),
    "ivt_administration_step_summary": (
        ["clinical_overview", "monitoring_protocol"],
        "STABLE",
    ),
    "dapt_trial_summary": (
        ["clinical_overview", "trial_specific_data"],
        "STABLE",
    ),
}


# Fallback when a category isn't mapped: return a conservative set so
# the atom is still reachable via exact intent_lookup, and log the miss
# so curation can happen incrementally.
UNMAPPED_FALLBACK: List[str] = ["recommendation_lookup"]


# Fallback by atom_type for atoms that have no category at all.
# Many RSS / knowledge-gap / synopsis atoms were atomized without a
# category; they had LLM-scanned intent_affinity which drifted
# (e.g. an evidence_summary about stroke awareness got "systems_of_care"
# because it mentioned EMS). These fallbacks assign a clean, tight
# intent set based on the atom's structural role.
ATOM_TYPE_INTENTS: Dict[str, List[str]] = {
    # Knowledge-gap atoms: "what's open / still under study"
    "evidence_gap": [
        "knowledge_gap", "current_understanding_and_gaps",
        "evidence_vs_gaps",
    ],
    # Recommendation-supporting-statement rows: "why the guideline
    # concludes what it does / what trials or reasoning support it"
    "evidence_summary": [
        "evidence_for_recommendation", "rationale_explanation",
    ],
    # Synopsis paragraphs: "tell me about X"
    "narrative_context": [
        "clinical_overview", "narrative_context",
    ],
    # Concept section headers (only still present when not legacy-
    # dropped): general orientation to a clinical concept
    "concept_section": [
        "clinical_overview", "definition_lookup",
    ],
}


def get_intents(category: str) -> List[str]:
    """Return the allowed intents for a category, or fallback.

    Never returns an empty list — every atom deserves at least
    recommendation_lookup so it's reachable by direct lookup queries.
    """
    entry = CATEGORY_INTENTS.get(category)
    if entry is None:
        return list(UNMAPPED_FALLBACK)
    intents, _status = entry
    return list(intents)


def get_intents_by_type(atom_type: str) -> List[str]:
    """Return the clean fallback intent set for an atom without a
    category, based on its structural atom_type. Used for atoms the
    main atomization didn't tag (no-category RSS/KG/synopsis)."""
    return list(ATOM_TYPE_INTENTS.get(atom_type, UNMAPPED_FALLBACK))


def get_status(category: str) -> str:
    """Return review status: STABLE, REVIEW, DEFERRED, or UNMAPPED."""
    entry = CATEGORY_INTENTS.get(category)
    if entry is None:
        return "UNMAPPED"
    return entry[1]
