"""
Stage 1 EXPAND — add concept section entries to the guideline database
and routing map.

This is the first stage of the concept section migration described in
the handoff doc. EXPAND is additive: new concept section keys are added
alongside the existing legacy keys (Table 8, Figure 3, etc.). The
legacy keys stay live as fallback until Stage 3 POINTER converts them
to _alias_of stubs.

What this script does:

1. Reads guideline_knowledge.json and extracts each legacy table/figure.

2. For Table 8, decomposes the 37 rows by their `category` field into
   three independent concept sections:
     - absolute_contraindications_ivt   (10 rows)
     - relative_contraindications_ivt   (18 rows)
     - benefit_outweighs_risk_ivt        (9 rows)

3. For each other ex-table/figure that has its own clean content
   (Tables 3, 4, 5, 6, 7, 9 and Figures 2, 3, 4), creates a single
   concept section that mirrors the ex-table content under a
   snake_case key.

4. Adds a top-level `concept_sections{}` dict to
   ais_guideline_section_map.json. Each entry carries:
     id, title, description, when_to_route, routing_keywords,
     supported_intents, parentChapter, sourceCitation

5. Does NOT touch the legacy "Table N" / "Figure N" keys in
   guideline_knowledge.json. Those stay live with their current
   content. They become _alias_of stubs in Stage 3.

6. Does NOT touch any retrieval code. That's Stage 2a (build
   knowledge_loader.py + dispatcher) and Stage 2b (flip preference).

Run with --dry-run to preview without writing.

Concept section ID inventory (from handoff doc, locked in Q2):
  absolute_contraindications_ivt     ← Table 8 absolute band
  relative_contraindications_ivt     ← Table 8 relative band
  benefit_outweighs_risk_ivt         ← Table 8 benefit band
  extended_window_imaging_criteria   ← Table 3
  disabling_deficits_assessment      ← Table 4
  sich_management_post_ivt           ← Table 5
  angioedema_management_post_ivt     ← Table 6
  dosing_administration_ivt          ← Table 7
  dapt_trials_evidence               ← Table 9
  aspects_scoring                    ← Figure 2
  eligibility_algorithm_evt          ← Figure 3
  dapt_algorithm_minor_stroke        ← Figure 4

Table 2 (COR/LOE rubric) is NOT assigned a concept section. It's a
universal AHA reference rather than clinical decision content, and
has no direct clinical intent mapping.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
GK_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json"
MAP_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references/ais_guideline_section_map.json"


# ──────────────────────────────────────────────────────────────────
# Concept section definitions
# ──────────────────────────────────────────────────────────────────
#
# Each entry has two parts:
#   content:  the guideline_knowledge.json section entry (sectionTitle,
#             synopsis, rss, knowledgeGaps, parentChapter, sourceCitation)
#   routing:  the ais_guideline_section_map.json concept_sections entry
#             (id, title, description, when_to_route, routing_keywords,
#             supported_intents, parentChapter, sourceCitation)
#
# Content is pulled from existing legacy entries in guideline_knowledge.json
# (Table 8, Table 3, etc.) at build time — no duplication in this file.

CONCEPT_ROUTING: dict[str, dict[str, Any]] = {
    # ── Table 8 band 1: absolute contraindications ──────────────
    "absolute_contraindications_ivt": {
        "id": "absolute_contraindications_ivt",
        "title": "Absolute Contraindications to IV Thrombolysis",
        "description": (
            "Conditions for which IV thrombolysis is deemed harmful and "
            "should not be administered. Hard stops — the guideline uses "
            "language like 'should not be administered', 'potentially "
            "harmful', or 'likely contraindicated' for each row in this "
            "category. Drawn from the pinkish-red tier of the 2026 "
            "guideline's Table 8."
        ),
        "when_to_route": [
            "What are the absolute contraindications to IVT?",
            "When must I not give tPA?",
            "Can I give tPA if the CT shows acute hemorrhage?",
            "Is there a platelet cutoff for thrombolysis?",
            "Is infective endocarditis a contraindication to IVT?",
        ],
        "routing_keywords": [
            "IVT", "thrombolysis", "tPA", "alteplase", "tenecteplase",
            "DOAC", "INR", "aPTT", "platelets", "coagulopathy", "thrombocytopenia",
            "ARIA", "amyloid",
            "aortic arch dissection", "spinal cord injury",
            "intra-axial neoplasm", "infective endocarditis",
            "CT hypodensity", "CT hemorrhage",
            "neurosurgery", "traumatic brain injury", "GCS",
        ],
        "supported_intents": [
            "contraindications",
            "harm_query",
            "eligibility_criteria",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 8 (absolute contraindications band)",
    },

    # ── Table 8 band 2: relative contraindications ──────────────
    "relative_contraindications_ivt": {
        "id": "relative_contraindications_ivt",
        "title": "Relative Contraindications to IV Thrombolysis",
        "description": (
            "Conditions where IV thrombolysis is considered a relative "
            "contraindication — the decision requires individualized "
            "risk/benefit judgment. The guideline's language in this "
            "band is typically 'caution is warranted', 'benefit and "
            "risk should be weighed', or 'individualized decision-"
            "making'. Drawn from the peach tier of the 2026 guideline's "
            "Table 8."
        ),
        "when_to_route": [
            "What are the relative contraindications to IVT?",
            "Can I give tPA to a patient on a DOAC?",
            "Is recent major surgery a contraindication to thrombolysis?",
            "What about IVT in pregnancy?",
            "Is a recent ischemic stroke a contraindication to IVT?",
        ],
        "routing_keywords": [
            "IVT", "thrombolysis", "tPA", "alteplase", "tenecteplase",
            "DOAC", "anticoagulant",
            "pre-existing disability", "pregnancy", "post-partum",
            "recent major surgery", "recent GI bleed", "recent GU bleed",
            "recent STEMI", "recent myocardial infarction",
            "cardiac thrombus", "pericarditis",
            "intracranial aneurysm", "intracranial vascular malformation",
            "intracranial arterial dissection",
            "dural puncture", "arterial puncture",
            "active malignancy",
            "recent ischemic stroke", "prior ICH",
            "traumatic brain injury", "neurosurgery",
        ],
        "supported_intents": [
            "contraindications",
            "harm_query",
            "eligibility_criteria",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 8 (relative contraindications band)",
    },

    # ── Table 8 band 3: benefit outweighs risk ──────────────────
    "benefit_outweighs_risk_ivt": {
        "id": "benefit_outweighs_risk_ivt",
        "title": "Conditions Where the Benefit of IV Thrombolysis Exceeds Bleeding Risk",
        "description": (
            "Specific clinical situations where the 2026 guideline "
            "explicitly states the benefit of IV thrombolysis generally "
            "outweighs bleeding risk — these are NOT contraindications. "
            "The language here is typically 'should be considered', "
            "'benefit likely outweighs risk', or 'probably indicated'. "
            "Drawn from the light-teal tier of the 2026 guideline's "
            "Table 8."
        ),
        "when_to_route": [
            "When does the benefit of IVT outweigh bleeding risk?",
            "Is IVT safe in cervical artery dissection?",
            "Can I give tPA to a patient with an unruptured aneurysm?",
            "Is thrombolysis appropriate after recent angiography?",
            "Can I give tPA to a patient with Moya-Moya disease?",
            "Is IVT reasonable for a patient with a remote history of GI bleeding?",
        ],
        "routing_keywords": [
            "IVT", "thrombolysis", "tPA", "alteplase", "tenecteplase",
            "cervical dissection", "extracranial dissection",
            "extra-axial intracranial neoplasm",
            "angiographic procedural stroke",
            "unruptured intracranial aneurysm",
            "remote GI bleeding", "remote GU bleeding",
            "history of myocardial infarction",
            "recreational drug use",
            "stroke mimic", "uncertain diagnosis",
            "Moya-Moya",
        ],
        "supported_intents": [
            "eligibility_criteria",
            "contraindications",
            "alternative_options",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 8 (benefit > risk band)",
    },

    # ── Table 3 → extended window imaging criteria ──────────────
    "extended_window_imaging_criteria": {
        "id": "extended_window_imaging_criteria",
        "title": "Imaging Criteria for Extended Window IV Thrombolysis",
        "description": (
            "Per-trial imaging inclusion criteria for extended-window IV "
            "thrombolysis trials (WAKE-UP, THAWS, EPITHET, ECASS-4, "
            "EXTEND, TIMELESS, TRACE-3). Each trial used either a "
            "DWI/FLAIR mismatch, PWI/DWI mismatch, or CTP penumbra-core "
            "ratio to identify patients with salvageable tissue beyond "
            "the standard 4.5-hour window. Use when a clinician asks "
            "what imaging criteria qualify a specific extended-window "
            "trial."
        ),
        "when_to_route": [
            "What imaging criteria did WAKE-UP use?",
            "What are the EXTEND inclusion criteria?",
            "What perfusion mismatch did TRACE-3 require?",
            "What imaging does the guideline require for extended window IVT?",
        ],
        "routing_keywords": [
            "WAKE-UP", "THAWS", "EPITHET", "ECASS-4", "EXTEND",
            "TIMELESS", "TRACE-3",
            "DWI/FLAIR mismatch", "PWI/DWI mismatch", "CTP mismatch",
            "perfusion mismatch", "penumbra", "core volume",
            "extended window", "wake-up stroke", "unknown onset",
        ],
        "supported_intents": [
            "imaging_protocol",
            "eligibility_criteria",
            "trial_specific_data",
            "evidence_for_recommendation",
        ],
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 3",
    },

    # ── Table 4 → disabling deficits assessment ─────────────────
    "disabling_deficits_assessment": {
        "id": "disabling_deficits_assessment",
        "title": "Assessment of Disabling Deficits for IV Thrombolysis",
        "description": (
            "Guidance for deciding whether a neurological deficit in a "
            "patient with mild AIS (NIHSS 0–5) should be considered "
            "'clearly disabling' when weighing IV thrombolysis. Based on "
            "whether the deficit would prevent basic activities of daily "
            "living (BATHE mnemonic: bathing, ambulating, toileting, "
            "hygiene, eating) or return to occupation. Includes explicit "
            "lists of deficits that are typically disabling versus those "
            "that may not be."
        ),
        "when_to_route": [
            "Is a deficit of hemianopia considered disabling for tPA?",
            "Does isolated facial droop count as disabling?",
            "Should I give IVT for a NIHSS 3 patient with aphasia?",
            "What does 'disabling' mean in mild stroke?",
            "Is hemisensory loss disabling for thrombolysis?",
        ],
        "routing_keywords": [
            "disabling deficit", "clearly disabling", "mild stroke",
            "NIHSS 0-5", "minor stroke",
            "hemianopsia", "aphasia", "hemineglect", "extinction",
            "motor weakness", "facial droop", "hemisensory loss",
            "hemiataxia", "ambulation",
        ],
        "supported_intents": [
            "definition_lookup",
            "eligibility_criteria",
            "patient_specific_eligibility",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 4",
    },

    # ── Table 5 → sICH management after IVT ─────────────────────
    "sich_management_post_ivt": {
        "id": "sich_management_post_ivt",
        "title": "Management of Symptomatic Intracranial Bleeding After IV Thrombolysis",
        "description": (
            "Step-by-step protocol for managing symptomatic intracranial "
            "bleeding (sICH) occurring within 24 hours after IV "
            "thrombolysis for acute ischemic stroke. Covers stopping the "
            "infusion, emergent imaging, coagulation labs, hemostatic "
            "therapy with cryoprecipitate or antifibrinolytic, and "
            "hematology/neurosurgery consultation."
        ),
        "when_to_route": [
            "How do I manage ICH after tPA?",
            "What's the treatment for sICH after thrombolysis?",
            "What's the cryoprecipitate dose for post-IVT bleeding?",
            "Should I use tranexamic acid for post-tPA hemorrhage?",
        ],
        "routing_keywords": [
            "sICH", "symptomatic ICH", "post-IVT bleeding",
            "post-thrombolysis hemorrhage", "hemorrhagic complication",
            "cryoprecipitate", "tranexamic acid", "aminocaproic acid",
            "fibrinogen", "PT", "INR", "aPTT",
            "stop alteplase", "stop tenecteplase",
            "hematology consult", "neurosurgery consult",
        ],
        "supported_intents": [
            "complication_management",
            "reversal_protocol",
            "monitoring_protocol",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 5",
    },

    # ── Table 6 → angioedema management after IVT ───────────────
    "angioedema_management_post_ivt": {
        "id": "angioedema_management_post_ivt",
        "title": "Management of Orolingual Angioedema After IV Alteplase",
        "description": (
            "Step-by-step protocol for managing orolingual angioedema "
            "complicating IV alteplase administration. Covers airway "
            "assessment, discontinuation of alteplase and ACE "
            "inhibitors, first-line pharmacotherapy (methylprednisolone, "
            "diphenhydramine, H2 blocker), epinephrine and icatibant "
            "for refractory cases, and supportive care."
        ),
        "when_to_route": [
            "How do I manage angioedema after tPA?",
            "What medications treat post-alteplase angioedema?",
            "When should I intubate for thrombolysis-related angioedema?",
            "Is icatibant indicated for post-tPA angioedema?",
        ],
        "routing_keywords": [
            "angioedema", "orolingual angioedema",
            "post-alteplase angioedema", "airway management",
            "fiberoptic intubation",
            "methylprednisolone", "diphenhydramine",
            "ranitidine", "famotidine",
            "epinephrine", "icatibant", "bradykinin",
            "ACE inhibitor",
        ],
        "supported_intents": [
            "complication_management",
            "reversal_protocol",
        ],
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 6",
    },

    # ── Table 7 → IVT dosing and administration ─────────────────
    "dosing_administration_ivt": {
        "id": "dosing_administration_ivt",
        "title": "IV Thrombolysis Dosing and Administration Protocol",
        "description": (
            "Dosing and administration protocol for IV thrombolysis in "
            "adult AIS patients. Alteplase: 0.9 mg/kg (max 90 mg) over "
            "60 minutes with 10% as a 1-minute bolus. Tenecteplase: "
            "0.25 mg/kg (max 25 mg) as a single IV push, dosed by "
            "weight band. Also covers post-infusion monitoring frequency, "
            "BP thresholds for intervention, delay of nasogastric/bladder "
            "catheter placement, and the 24-hour follow-up imaging "
            "requirement before starting anticoagulants or antiplatelets."
        ),
        "when_to_route": [
            "What is the dose of tenecteplase for a 75 kg patient?",
            "How do I administer alteplase for AIS?",
            "What's the maximum dose of tPA?",
            "What monitoring is required after IVT?",
            "When should I start aspirin after tPA?",
            "Can I place an NG tube after thrombolysis?",
        ],
        "routing_keywords": [
            "IVT dose", "alteplase dose", "tenecteplase dose",
            "tPA dosing", "TNK dosing", "weight-based dosing",
            "0.9 mg/kg", "0.25 mg/kg", "max 90 mg", "max 25 mg",
            "bolus", "60 minute infusion", "1 minute bolus",
            "weight band",
            "post-IVT monitoring", "BP monitoring",
            "nasogastric tube delay", "Foley delay",
            "24 hour follow-up imaging",
        ],
        "supported_intents": [
            "dosing_protocol",
            "monitoring_protocol",
            "post_treatment_care",
            "threshold_target",
        ],
        "parentChapter": "4.6.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 7",
    },

    # ── Table 9 → DAPT trials evidence ──────────────────────────
    "dapt_trials_evidence": {
        "id": "dapt_trials_evidence",
        "title": "Dual Antiplatelet Therapy Trial Evidence for Minor Stroke and TIA",
        "description": (
            "The five randomized controlled trials underpinning the "
            "guideline recommendations for short-term dual antiplatelet "
            "therapy (DAPT) in minor AIS and high-risk TIA: CHANCE, "
            "POINT, THALES, CHANCE 2, INSPIRES. Each trial row lists "
            "inclusion criteria, drug regimen, last-known-normal window, "
            "and number-needed-to-treat. Use when a clinician asks what "
            "evidence supports DAPT in minor stroke, what regimen a "
            "specific trial used, or what the NNT is for a given "
            "regimen."
        ),
        "when_to_route": [
            "What did the CHANCE trial show?",
            "What is the DAPT regimen from POINT?",
            "What's the NNT for THALES?",
            "What trials support DAPT in minor stroke?",
            "When was ticagrelor studied in minor stroke?",
        ],
        "routing_keywords": [
            "CHANCE trial", "POINT trial", "THALES trial",
            "CHANCE 2", "INSPIRES trial",
            "DAPT trial", "dual antiplatelet", "minor stroke trial",
            "clopidogrel loading", "ticagrelor loading",
            "aspirin dose",
            "21 days DAPT", "30 days DAPT", "90 days DAPT",
            "NNT", "number needed to treat",
            "CYP2C19", "loss-of-function allele",
            "atherosclerosis", "presumed athero",
        ],
        "supported_intents": [
            "trial_specific_data",
            "evidence_for_recommendation",
            "comparison_query",
        ],
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 9",
    },

    # ── Figure 2 → ASPECTS scoring ──────────────────────────────
    "aspects_scoring": {
        "id": "aspects_scoring",
        "title": "ASPECTS — Alberta Stroke Program Early CT Score",
        "description": (
            "The 10-point topographic scoring system for quantifying "
            "early ischemic changes on non-contrast CT in the middle "
            "cerebral artery (MCA) territory. A normal CT scores 10; "
            "one point is subtracted for each of 10 MCA-territory "
            "regions showing hypoattenuation or focal swelling. "
            "ASPECTS ≥6 is generally required for standard-window "
            "EVT eligibility; large-core trials (SELECT2, ANGEL-ASPECT, "
            "RESCUE-Japan LIMIT, TENSION) have demonstrated EVT "
            "benefit in carefully selected patients with ASPECTS 3-5."
        ),
        "when_to_route": [
            "What is ASPECTS?",
            "How is ASPECTS scored?",
            "What ASPECTS threshold is required for EVT?",
            "Can I do EVT with ASPECTS 4?",
            "What does a score of 5 on ASPECTS mean?",
        ],
        "routing_keywords": [
            "ASPECTS", "Alberta Stroke Program Early CT Score",
            "early ischemic change", "hypoattenuation",
            "MCA territory", "M1 M2 M3", "M4 M5 M6",
            "caudate", "lentiform", "insular ribbon",
            "large core", "low ASPECTS",
            "SELECT2", "ANGEL-ASPECT", "RESCUE-Japan LIMIT", "TENSION",
        ],
        "supported_intents": [
            "definition_lookup",
            "threshold_target",
            "eligibility_criteria",
            "imaging_protocol",
        ],
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 2",
    },

    # ── Figure 3 → EVT eligibility algorithm ────────────────────
    "eligibility_algorithm_evt": {
        "id": "eligibility_algorithm_evt",
        "title": "EVT Eligibility Algorithm",
        "description": (
            "Decision algorithm for endovascular thrombectomy (EVT) "
            "eligibility in AIS. The algorithm branches on time from "
            "last known well, vessel occlusion location (anterior LVO, "
            "posterior LVO, medium/distal vessel), clinical severity "
            "(NIHSS), imaging findings (ASPECTS, core volume, perfusion "
            "mismatch), and pre-stroke functional status (mRS). "
            "Individual decision nodes are visual-only in the PDF; "
            "detailed clinical recommendations live in §4.7.1–§4.7.5."
        ),
        "when_to_route": [
            "Is my patient eligible for EVT at 12 hours?",
            "What's the EVT algorithm for anterior circulation?",
            "Does pre-stroke mRS 3 exclude EVT?",
            "What's the decision tree for LVO?",
        ],
        "routing_keywords": [
            "EVT algorithm", "EVT eligibility",
            "LVO", "anterior circulation LVO", "posterior LVO",
            "medium vessel occlusion", "MeVO", "distal vessel",
            "M1", "M2", "M3",
            "time window", "6 hours", "24 hours",
            "ASPECTS", "core volume", "perfusion mismatch",
            "pre-stroke mRS",
        ],
        "supported_intents": [
            "algorithm_walkthrough",
            "eligibility_criteria",
            "patient_specific_eligibility",
            "time_window",
        ],
        "parentChapter": "4.7",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 3",
    },

    # ── Figure 4 → DAPT algorithm ───────────────────────────────
    "dapt_algorithm_minor_stroke": {
        "id": "dapt_algorithm_minor_stroke",
        "title": "DAPT Algorithm for Minor Stroke and High-Risk TIA",
        "description": (
            "Decision algorithm for initiating dual antiplatelet therapy "
            "(DAPT) in patients with minor noncardioembolic AIS or "
            "high-risk TIA. Branches on clinical severity (NIHSS ≤3 vs "
            "≤5), ABCD2 score, presumed atherosclerotic etiology, "
            "CYP2C19 genotype, last-known-normal window (12, 24, or 72 "
            "hours), and IVT/EVT eligibility. Supporting evidence is in "
            "Table 9 (CHANCE, POINT, THALES, CHANCE 2, INSPIRES). "
            "Individual decision nodes are visual-only in the PDF."
        ),
        "when_to_route": [
            "Should I start DAPT for this minor stroke patient?",
            "When is DAPT indicated in TIA?",
            "What's the DAPT algorithm?",
            "How do I choose between clopidogrel and ticagrelor for minor stroke?",
        ],
        "routing_keywords": [
            "DAPT algorithm", "DAPT eligibility",
            "minor stroke", "high-risk TIA", "ABCD2",
            "NIHSS 3", "NIHSS 5",
            "clopidogrel", "ticagrelor", "aspirin",
            "21 days DAPT", "30 days DAPT",
            "CYP2C19",
            "presumed atherosclerosis",
            "noncardioembolic",
        ],
        "supported_intents": [
            "algorithm_walkthrough",
            "eligibility_criteria",
            "drug_choice",
            "duration_query",
        ],
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 4",
    },
}


# Map concept section id → (source legacy key, category filter or None)
# A category filter is a set of legacy row categories to keep for this
# concept; used to split Table 8 into its three bands.
CONTENT_SOURCE: dict[str, tuple[str, set[str] | None]] = {
    "absolute_contraindications_ivt":  ("Table 8", {"absolute_contraindication"}),
    "relative_contraindications_ivt":  ("Table 8", {"relative_contraindication"}),
    "benefit_outweighs_risk_ivt":      ("Table 8", {"benefit_greater_than_risk"}),
    "extended_window_imaging_criteria": ("Table 3", None),
    "disabling_deficits_assessment":    ("Table 4", None),
    "sich_management_post_ivt":         ("Table 5", None),
    "angioedema_management_post_ivt":   ("Table 6", None),
    "dosing_administration_ivt":        ("Table 7", None),
    "dapt_trials_evidence":             ("Table 9", None),
    "aspects_scoring":                  ("Figure 2", None),
    "eligibility_algorithm_evt":        ("Figure 3", None),
    "dapt_algorithm_minor_stroke":      ("Figure 4", None),
}


def build_content_entry(concept_id: str, gk: dict) -> dict:
    """Build a new sections[concept_id] content entry from a legacy key."""
    legacy_key, cat_filter = CONTENT_SOURCE[concept_id]
    legacy = gk["sections"].get(legacy_key, {})
    if not legacy:
        raise RuntimeError(f"legacy key not found: {legacy_key}")

    rss = legacy.get("rss", []) or []
    if cat_filter is not None:
        rss = [r for r in rss if r.get("category", "") in cat_filter]

    routing = CONCEPT_ROUTING[concept_id]

    # For Table 8 band splits, use a band-specific synopsis from the
    # routing metadata. For single-unit concepts, reuse the legacy
    # synopsis verbatim.
    if cat_filter is not None:
        synopsis = routing["description"]
    else:
        synopsis = legacy.get("synopsis", "")

    return {
        "sectionTitle": routing["title"],
        "parentChapter": routing["parentChapter"],
        "sourceCitation": routing["sourceCitation"],
        "synopsis": synopsis,
        "rss": rss,
        "knowledgeGaps": legacy.get("knowledgeGaps", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(GK_PATH) as f:
        gk = json.load(f)
    with open(MAP_PATH) as f:
        sm = json.load(f)

    # ── Step 1: add content entries to guideline_knowledge.json ──
    print("EXPAND — adding concept section content entries:")
    for concept_id in CONCEPT_ROUTING:
        entry = build_content_entry(concept_id, gk)
        gk["sections"][concept_id] = entry
        syn_len = len(entry["synopsis"])
        rss_count = len(entry["rss"])
        print(f"  {concept_id:<38s} synopsis={syn_len:>5} rss={rss_count:>3}  "
              f"<- {CONTENT_SOURCE[concept_id][0]}")

    # ── Step 2: add routing entries to ais_guideline_section_map.json ──
    if "concept_sections" not in sm:
        sm["concept_sections"] = {}
    for concept_id, routing in CONCEPT_ROUTING.items():
        sm["concept_sections"][concept_id] = routing

    print(f"\nconcept_sections dict: {len(sm['concept_sections'])} entries")

    # ── Step 3: write back (unless dry-run) ─────────────────────
    if args.dry_run:
        print("\n[dry-run] not writing")
        return

    with open(GK_PATH, "w") as f:
        json.dump(gk, f, indent=2, ensure_ascii=False)
    with open(MAP_PATH, "w") as f:
        json.dump(sm, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {GK_PATH}")
    print(f"Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
