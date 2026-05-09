"""
Populate anchor_thresholds for each concept section in
ais_guideline_section_map.json. A threshold rule tells the dispatcher
"when the LLM sees this anchor term with a value that crosses this
number in this direction, this concept section is the right answer".

Used by knowledge_loader.dispatch_concept_sections() to route queries
like "INR 2.5" to absolute_contraindications_ivt (because 2.5 > 1.7
crosses the severe coagulopathy threshold).

Only populates thresholds that are literally stated in the source
guideline rows. No invented values.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/agents/qa_v6/references/ais_guideline_section_map.json"


# Each rule: {anchor, compare, value, unit, row_hint}
# compare is one of '<', '<=', '>', '>=', '=='
# The rule FIRES when patient_value compare value is TRUE
# (meaning the clinical alarm / threshold condition is met).
ANCHOR_THRESHOLDS: dict[str, list[dict]] = {
    "absolute_contraindications_ivt": [
        # Severe coagulopathy / thrombocytopenia row
        {"anchor": "platelets", "compare": "<", "value": 100,
         "unit": "x10^3/uL", "row_hint": "severe_coagulopathy_or_thrombocytopenia"},
        {"anchor": "INR", "compare": ">", "value": 1.7,
         "unit": "", "row_hint": "severe_coagulopathy_or_thrombocytopenia"},
        {"anchor": "aPTT", "compare": ">", "value": 40,
         "unit": "seconds", "row_hint": "severe_coagulopathy_or_thrombocytopenia"},
        {"anchor": "PT", "compare": ">", "value": 15,
         "unit": "seconds", "row_hint": "severe_coagulopathy_or_thrombocytopenia"},
        # TBI threshold
        {"anchor": "GCS", "compare": "<", "value": 13,
         "unit": "", "row_hint": "moderate_severe_tbi_14_days"},
        {"anchor": "traumatic brain injury", "compare": "<", "value": 14,
         "unit": "days", "row_hint": "moderate_severe_tbi_14_days"},
        {"anchor": "TBI", "compare": "<", "value": 14,
         "unit": "days", "row_hint": "moderate_severe_tbi_14_days"},
        # Recent neurosurgery
        {"anchor": "neurosurgery", "compare": "<", "value": 14,
         "unit": "days", "row_hint": "neurosurgery_14_days"},
        # Acute spinal cord injury
        {"anchor": "spinal cord injury", "compare": "<", "value": 3,
         "unit": "months", "row_hint": "acute_spinal_cord_injury_3_months"},
    ],

    "relative_contraindications_ivt": [
        # Recent ischemic stroke
        {"anchor": "ischemic stroke", "compare": "<", "value": 3,
         "unit": "months", "row_hint": "ischemic_stroke_3_months"},
        # Recent major non-CNS surgery
        {"anchor": "major surgery", "compare": "<", "value": 10,
         "unit": "days", "row_hint": "recent_major_non_cns_surgery_10_days"},
        {"anchor": "recent surgery", "compare": "<", "value": 10,
         "unit": "days", "row_hint": "recent_major_non_cns_surgery_10_days"},
        # Recent GI/GU bleeding
        {"anchor": "GI bleeding", "compare": "<", "value": 21,
         "unit": "days", "row_hint": "recent_gi_gu_bleeding_21_days"},
        {"anchor": "GU bleeding", "compare": "<", "value": 21,
         "unit": "days", "row_hint": "recent_gi_gu_bleeding_21_days"},
        # Recent STEMI
        {"anchor": "STEMI", "compare": "<", "value": 3,
         "unit": "months", "row_hint": "recent_stemi_3_months"},
        {"anchor": "myocardial infarction", "compare": "<", "value": 3,
         "unit": "months", "row_hint": "recent_stemi_3_months"},
        # Dural / arterial puncture
        {"anchor": "dural puncture", "compare": "<", "value": 7,
         "unit": "days", "row_hint": "dural_puncture_7_days"},
        {"anchor": "arterial puncture", "compare": "<", "value": 7,
         "unit": "days", "row_hint": "arterial_puncture_7_days"},
    ],

    "benefit_outweighs_risk_ivt": [
        # This band is defined by conditions without numeric thresholds
        # (extracranial dissection, unruptured aneurysm, Moya-Moya, etc.)
        # No value-based routing rules apply here. Keeping empty so the
        # schema is uniform.
    ],

    "dosing_administration_ivt": [
        # Tenecteplase weight bands
        {"anchor": "weight", "compare": "<", "value": 60,
         "unit": "kg", "row_hint": "tnk_weight__60_kg"},
        {"anchor": "patient weight", "compare": "<", "value": 60,
         "unit": "kg", "row_hint": "tnk_weight__60_kg"},
        {"anchor": "weight", "compare": ">=", "value": 90,
         "unit": "kg", "row_hint": "tnk_weight__90_kg"},
        # Post-IVT BP thresholds
        {"anchor": "SBP", "compare": ">", "value": 180,
         "unit": "mmHg", "row_hint": "increase_bp_measurement_frequency"},
        {"anchor": "DBP", "compare": ">", "value": 105,
         "unit": "mmHg", "row_hint": "increase_bp_measurement_frequency"},
    ],

    "extended_window_imaging_criteria": [
        # Time from LKW thresholds used by extended-window trials
        {"anchor": "time from onset", "compare": ">", "value": 4.5,
         "unit": "hours", "row_hint": "extended_window_entry"},
        {"anchor": "LKW", "compare": ">", "value": 4.5,
         "unit": "hours", "row_hint": "extended_window_entry"},
        {"anchor": "last known well", "compare": ">", "value": 4.5,
         "unit": "hours", "row_hint": "extended_window_entry"},
    ],

    "disabling_deficits_assessment": [
        # Mild stroke NIHSS range
        {"anchor": "NIHSS", "compare": "<=", "value": 5,
         "unit": "", "row_hint": "mild_stroke_nihss_0_5"},
    ],

    "sich_management_post_ivt": [
        # No numeric thresholds — protocol steps, not value-gated
    ],

    "angioedema_management_post_ivt": [
        # No numeric thresholds — protocol steps
    ],

    "dapt_trials_evidence": [
        # DAPT eligibility NIHSS and ABCD2 thresholds
        {"anchor": "NIHSS", "compare": "<=", "value": 3,
         "unit": "", "row_hint": "chance_point_nihss_3"},
        {"anchor": "NIHSS", "compare": "<=", "value": 5,
         "unit": "", "row_hint": "thales_inspires_nihss_5"},
        {"anchor": "ABCD2", "compare": ">=", "value": 4,
         "unit": "", "row_hint": "chance_point_abcd2_4"},
        {"anchor": "ABCD2", "compare": ">=", "value": 6,
         "unit": "", "row_hint": "thales_abcd2_6"},
    ],

    "aspects_scoring": [
        # ASPECTS score thresholds
        {"anchor": "ASPECTS", "compare": ">=", "value": 6,
         "unit": "", "row_hint": "aspects_evt_standard_threshold"},
        {"anchor": "ASPECTS", "compare": "<", "value": 6,
         "unit": "", "row_hint": "aspects_large_core"},
    ],

    "eligibility_algorithm_evt": [
        # EVT time-window and clinical-severity thresholds
        {"anchor": "time from onset", "compare": "<=", "value": 6,
         "unit": "hours", "row_hint": "evt_standard_window_0_6h"},
        {"anchor": "LKW", "compare": "<=", "value": 24,
         "unit": "hours", "row_hint": "evt_extended_window_6_24h"},
        {"anchor": "NIHSS", "compare": ">=", "value": 6,
         "unit": "", "row_hint": "evt_nihss_6"},
        {"anchor": "ASPECTS", "compare": ">=", "value": 3,
         "unit": "", "row_hint": "evt_aspects_3"},
    ],

    "dapt_algorithm_minor_stroke": [
        # DAPT algorithm thresholds
        {"anchor": "NIHSS", "compare": "<=", "value": 3,
         "unit": "", "row_hint": "dapt_nihss_3"},
        {"anchor": "NIHSS", "compare": "<=", "value": 5,
         "unit": "", "row_hint": "dapt_nihss_5"},
        {"anchor": "ABCD2", "compare": ">=", "value": 4,
         "unit": "", "row_hint": "dapt_abcd2_4"},
        {"anchor": "LKW", "compare": "<=", "value": 24,
         "unit": "hours", "row_hint": "dapt_24h_window"},
        {"anchor": "LKW", "compare": "<=", "value": 72,
         "unit": "hours", "row_hint": "dapt_inspires_72h_window"},
    ],
}


def main():
    with open(MAP_PATH) as f:
        sm = json.load(f)

    catalogue = sm.get("concept_sections", {})
    for concept_id, rules in ANCHOR_THRESHOLDS.items():
        if concept_id not in catalogue:
            print(f"  [{concept_id}] not in catalogue, skipping")
            continue
        catalogue[concept_id]["anchor_thresholds"] = rules
        print(f"  [{concept_id}] anchor_thresholds: {len(rules)} rules")

    with open(MAP_PATH, "w") as f:
        json.dump(sm, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {MAP_PATH}")


if __name__ == "__main__":
    main()
