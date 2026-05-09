"""
Tag rss rows with their sub-section category based on the PDF's
printed sub-headers. Each mapping was verified by reading the
source PDF pages and matching sub-header text to the rec numbers.

This is the foundational data that lets the concept section
dispatcher route to sub-topics within broad sections like §4.8
(antiplatelet) and §4.3 (BP management).
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GK_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json"

# Mapping: section_id → {recNumber: category}
# Categories are snake_case slugs of the PDF's printed sub-headers.
SUBSECTION_TAGS: dict[str, dict[str, str]] = {
    # ── §2.3 Prehospital Assessment and Management ──────────────
    # Sub-headers from PDF page 13-14:
    #   "Prehospital stroke recognition and assessment" (recs 1-3)
    #   "Prehospital treatment" (recs 4-6)
    #   "Pediatric considerations" (rec 7)
    "2.3": {
        "1": "prehospital_stroke_recognition",
        "2": "prehospital_stroke_recognition",
        "3": "prehospital_stroke_recognition",
        "4": "prehospital_treatment",
        "5": "prehospital_treatment",
        "6": "prehospital_treatment",
        "7": "pediatric_considerations",
    },

    # ── §2.4 EMS Destination Management ─────────────────────────
    # Sub-headers from PDF page 14:
    #   "General principles" (recs 1-4)
    #   "Interhospital transfer" (rec 5)
    "2.4": {
        "1": "general_principles",
        "2": "general_principles",
        "3": "general_principles",
        "4": "general_principles",
        "5": "interhospital_transfer",
    },

    # ── §2.8 Telemedicine ───────────────────────────────────────
    # Sub-headers from PDF pages 18-19:
    #   "Prehospital telemedicine" (rec 1)
    #   "Telestroke for thrombolytic decision-making" (recs 2-3)
    #   "IVT decision-making and optimal thrombolytic" (recs 4-5)
    #   "Telestroke in stroke systems of care" (recs 6-7)
    "2.8": {
        "1": "prehospital_telemedicine",
        "2": "telestroke_ivt_decision",
        "3": "telestroke_ivt_decision",
        "4": "telestroke_ivt_delivery",
        "5": "telestroke_ivt_delivery",
        "6": "telestroke_systems_of_care",
        "7": "telestroke_systems_of_care",
    },

    # ── §3.2 Initial Imaging ────────────────────────────────────
    # Sub-headers from PDF pages 27-29:
    #   "General brain imaging" (recs 1-5)
    #   "Extended window / wake-up stroke imaging" (recs 6-7)
    #   "EVT imaging selection" (recs 8-10)
    "3.2": {
        "1": "general_brain_imaging",
        "2": "general_brain_imaging",
        "3": "general_brain_imaging",
        "4": "general_brain_imaging",
        "5": "general_brain_imaging",
        "6": "extended_window_imaging",
        "7": "evt_vascular_imaging",
        "8": "evt_advanced_imaging",
        "9": "evt_direct_angiography",
        "10": "evt_transfer_imaging",
    },

    # ── §4.3 Blood Pressure Management ──────────────────────────
    # Sub-headers from PDF page 35:
    #   "General recommendations (including without reperfusion therapy)"
    #       (recs 1-4)
    #   "Before reperfusion treatment" (recs 5-6)
    #   "After IVT" (recs 7-8)
    #   "After endovascular thrombectomy" (recs 9-10)
    "4.3": {
        "1": "bp_general",
        "2": "bp_general",
        "3": "bp_general",
        "4": "bp_general",
        "5": "bp_before_reperfusion",
        "6": "bp_before_reperfusion",
        "7": "bp_after_ivt",
        "8": "bp_after_ivt",
        "9": "bp_after_evt",
        "10": "bp_after_evt",
    },

    # ── §4.6.1 Thrombolysis Decision-Making ─────────────────────
    # Sub-headers from PDF pages 38-40:
    #   "General principles" (recs 1-7)
    #   "Mild / non-disabling deficits" (recs 8-9)
    #   "Time-sensitive administration" (rec 10)
    #   "Cerebral microbleeds (CMBs)" (recs 11-13)
    #   "Pediatric patients" (rec 14)
    "4.6.1": {
        "1": "ivt_general_principles",
        "2": "ivt_general_principles",
        "3": "ivt_general_principles",
        "4": "ivt_general_principles",
        "5": "ivt_general_principles",
        "6": "ivt_general_principles",
        "7": "ivt_general_principles",
        "8": "ivt_mild_nondisabling",
        "9": "ivt_mild_nondisabling",
        "10": "ivt_time_sensitive",
        "11": "ivt_cerebral_microbleeds",
        "12": "ivt_cerebral_microbleeds",
        "13": "ivt_cerebral_microbleeds",
        "14": "ivt_pediatric",
    },

    # ── §4.6.4 Other IV Fibrinolytics and Sonothrombolysis ──────
    # Sub-headers from PDF page 46:
    #   "Other IV fibrinolytics" (recs 1-6)
    #   "Sonothrombolysis" (rec 7)
    "4.6.4": {
        "1": "other_iv_fibrinolytics",
        "2": "other_iv_fibrinolytics",
        "3": "other_iv_fibrinolytics",
        "4": "other_iv_fibrinolytics",
        "5": "other_iv_fibrinolytics",
        "6": "other_iv_fibrinolytics",
        "7": "sonothrombolysis",
    },

    # ── §4.7.2 EVT for Adult Patients ───────────────────────────
    # Sub-headers from PDF pages 53-56 (organized by time window,
    # ASPECTS range, vessel type, and pre-stroke disability):
    #   "0-6h, ASPECTS 3-10, anterior LVO" (rec 1)
    #   "6-24h, ASPECTS 6-10, imaging selected" (rec 2)
    #   "6-24h, ASPECTS 3-5, large core" (rec 3)
    #   "0-6h, ASPECTS 0-2" (rec 4)
    #   "0-6h, mild preexisting disability" (rec 5)
    #   "0-6h, moderate preexisting disability" (rec 6)
    #   "0-6h, proximal M2 MCA" (rec 7)
    #   "Distal / medium vessel occlusions" (rec 8)
    "4.7.2": {
        "1": "evt_0_6h_aspects_3_10",
        "2": "evt_6_24h_aspects_6_10",
        "3": "evt_6_24h_aspects_3_5",
        "4": "evt_0_6h_aspects_0_2",
        "5": "evt_0_6h_mild_disability",
        "6": "evt_0_6h_moderate_disability",
        "7": "evt_0_6h_proximal_m2",
        "8": "evt_distal_medium_vessel",
    },

    # ── §4.7.4 Endovascular Techniques ──────────────────────────
    # Sub-headers from PDF pages 57-58:
    #   "Thrombectomy general techniques" (recs 1-5)
    #   "Thrombectomy adjunctive techniques" (recs 6-9)
    "4.7.4": {
        "1": "thrombectomy_general_techniques",
        "2": "thrombectomy_general_techniques",
        "3": "thrombectomy_general_techniques",
        "4": "thrombectomy_general_techniques",
        "5": "thrombectomy_general_techniques",
        "6": "thrombectomy_adjunctive_techniques",
        "7": "thrombectomy_adjunctive_techniques",
        "8": "thrombectomy_adjunctive_techniques",
        "9": "thrombectomy_adjunctive_techniques",
    },

    # ── §4.8 Antiplatelet Treatment ─────────────────────────────
    # Sub-headers from PDF pages 62-63:
    #   "General principles for early antiplatelet therapy" (recs 1-4)
    #   "Early secondary prevention" (recs 5-11)
    #   "Dual antiplatelet therapy for minor AIS and high-risk TIA"
    #       (recs 12-15)
    #   "Antiplatelet therapy in the setting of IVT" (recs 16-18)
    "4.8": {
        "1": "antiplatelet_general_principles",
        "2": "antiplatelet_general_principles",
        "3": "antiplatelet_general_principles",
        "4": "antiplatelet_general_principles",
        "5": "antiplatelet_secondary_prevention",
        "6": "antiplatelet_secondary_prevention",
        "7": "antiplatelet_secondary_prevention",
        "8": "antiplatelet_secondary_prevention",
        "9": "antiplatelet_secondary_prevention",
        "10": "antiplatelet_secondary_prevention",
        "11": "antiplatelet_secondary_prevention",
        "12": "antiplatelet_dapt_minor_stroke",
        "13": "antiplatelet_dapt_minor_stroke",
        "14": "antiplatelet_dapt_minor_stroke",
        "15": "antiplatelet_dapt_minor_stroke",
        "16": "antiplatelet_ivt_interaction",
        "17": "antiplatelet_ivt_interaction",
        "18": "antiplatelet_ivt_interaction",
    },
}


def main():
    with open(GK_PATH) as f:
        gk = json.load(f)

    total_tagged = 0
    for section_id, tag_map in SUBSECTION_TAGS.items():
        sec = gk["sections"].get(section_id)
        if not sec:
            print(f"  [{section_id}] section not found — skipping")
            continue
        rss = sec.get("rss", [])
        tagged = 0
        for row in rss:
            rec_num = row.get("recNumber", "")
            cat = tag_map.get(rec_num, "")
            if cat:
                row["category"] = cat
                tagged += 1
        total_tagged += tagged
        cats = sorted(set(tag_map.values()))
        print(f"  [{section_id}] tagged {tagged}/{len(rss)} rows → {len(cats)} sub-sections: {cats}")

    with open(GK_PATH, "w") as f:
        json.dump(gk, f, indent=2, ensure_ascii=False)
    print(f"\nTotal: {total_tagged} rows tagged across {len(SUBSECTION_TAGS)} sections")
    print(f"Wrote {GK_PATH}")


if __name__ == "__main__":
    main()
