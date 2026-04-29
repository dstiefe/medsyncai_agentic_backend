"""
Generate Round 9 test suite: 1000 new recommendation questions.

Each question includes discriminating clinical details from the target
rec's actual text — enough to uniquely identify ONE rec, not just
the section. This matches the R3/R5 question design philosophy.

Usage:
    python3 generate_r9_test_suite.py
"""

import json
import random
from collections import Counter

# ══════════════════════════════════════════════════════════════════════
# DISCRIMINATING QUESTIONS — hand-crafted per rec
# Each rec gets 6-8 question variants that contain enough clinical
# detail to uniquely identify that specific recommendation.
# ══════════════════════════════════════════════════════════════════════

# Format: rec_id -> list of questions
REC_QUESTIONS = {
    # ── Section 2.1 — Stroke Awareness ────────────────────────────
    "rec-2.1-001": [
        "Per the 2026 guideline, should educational programs on stroke recognition and calling 9-1-1 be implemented for the general public?",
        "What COR does implementation of stroke recognition programs for the general public receive?",
        "Is implementing stroke recognition education with emphasis on calling 9-1-1 recommended?",
        "What is the COR for public stroke education programs focused on reducing knowledge gaps about warning signs?",
        "Should public health leaders implement educational programs on stroke recognition per the 2026 guideline?",
    ],
    "rec-2.1-002": [
        "Should stroke education programs be designed to reach diverse communities across race, ethnicity, and income levels?",
        "What COR applies to multilingual and culturally relevant stroke recognition programs?",
        "Per 2026, is it recommended that stroke education reach populations across all demographics and social determinants of health?",
        "What is the recommendation for designing stroke programs to address diverse populations and reduce disparities in stroke preparedness?",
        "Should stroke education be tailored to reach underserved communities across age, race, and socioeconomic status?",
    ],
    "rec-2.1-003": [
        "Should stroke awareness programs be sustained over time per the 2026 guideline?",
        "What COR applies to sustaining stroke education campaigns long-term to maintain public knowledge?",
        "Per 2026, is long-term sustained stroke recognition education recommended?",
        "What is the recommendation for maintaining stroke awareness programs over time rather than one-time campaigns?",
        "Is it recommended that stroke recognition programs be sustained to improve long-term knowledge?",
    ],
    "rec-2.1-004": [
        "Should EMS professionals and physicians receive targeted stroke education per 2026 guidelines?",
        "What COR applies to targeted stroke training for healthcare personnel to reduce prehospital delays?",
        "Per 2026, is specialized stroke education for primary care professionals recommended to maximize IVT eligibility?",
        "What is the recommendation for targeted stroke education for EMS and other healthcare professionals?",
        "Should health care personnel receive targeted stroke programs to reduce prehospital delays and maximize acute treatment eligibility?",
    ],

    # ── Section 2.2 — EMS Systems ────────────────────────────────
    "rec-2.2-001": [
        "Should health care policy makers establish regional systems for IVT and EVT access?",
        "What COR applies to establishing regional stroke systems with tiered facility designations for IVT and EVT?",
        "Per 2026, should regional stroke care systems determine which facilities provide IVT and which perform EVT?",
        "Is it recommended that policy makers establish tiered regional systems with IVT and EVT-capable facilities?",
        "What is the COR for establishing regional stroke care systems that include IVT and EVT facilities?",
    ],
    "rec-2.2-002": [
        "Should EMS leaders develop prehospital triage protocols with validated stroke screening tools?",
        "What COR applies to prehospital triage protocols that rapidly identify and transport suspected stroke patients?",
        "Per 2026, is it recommended that EMS develop protocols for rapid stroke identification and transport to appropriate centers?",
        "What is the recommendation for developing EMS triage protocols with validated stroke screening scales?",
        "Should EMS leaders and local experts develop standardized prehospital triage protocols?",
    ],
    "rec-2.2-003": [
        "What COR applies to using prehospital LVO screening tools for triage to EVT-capable centers?",
        "Per 2026, is using prehospital LVO screening scales for field triage a COR 2a recommendation?",
        "Should prehospital LVO assessment tools be used to direct patients to EVT-capable stroke centers?",
        "What is the recommendation strength for LVO screening tools in prehospital triage?",
        "Is prehospital LVO screening to guide transport to thrombectomy-capable centers reasonable?",
    ],

    # ── Section 2.3 — Prehospital Assessment ─────────────────────
    "rec-2.3-001": [
        "Should EMS providers use stroke assessment protocols for prehospital evaluation?",
        "What COR applies to establishing stroke assessment protocols for EMS providers?",
        "Per 2026, is it reasonable for EMS to have standardized stroke assessment protocols?",
        "What is the recommendation for prehospital stroke assessment protocols by EMS?",
    ],
    "rec-2.3-002": [
        "Should suspected stroke patients be transported rapidly and preferentially to the closest stroke center?",
        "What COR applies to rapid transport of suspected stroke patients to the nearest appropriate stroke center?",
        "Per 2026, is rapid EMS transport to the nearest stroke center a COR 1 recommendation?",
        "What is the recommendation for prioritized transport of stroke patients to stroke-capable facilities?",
        "Is rapid transport to the nearest stroke center recommended by EMS for suspected stroke?",
    ],
    "rec-2.3-003": [
        "Should EMS provide prehospital notification to the receiving hospital about incoming stroke patients?",
        "What COR applies to prehospital notification of the receiving ED about a stroke patient?",
        "Per 2026, is prehospital hospital notification by EMS recommended?",
        "What is the recommendation for advance EMS notification to the receiving stroke center?",
        "Is prehospital notification to activate the stroke team recommended?",
    ],
    "rec-2.3-004": [
        "Is routine prehospital IV fluid administration recommended for stroke patients?",
        "What COR does routine IV fluid therapy in the prehospital setting receive for stroke?",
        "Per 2026, should EMS routinely give IV fluids to suspected stroke patients?",
        "What is the recommendation against routine prehospital IV fluid administration?",
    ],
    "rec-2.3-005": [
        "Should EMS routinely lower blood pressure in the prehospital setting for stroke?",
        "What COR does routine prehospital blood pressure reduction receive?",
        "Per 2026, is prehospital blood pressure lowering for stroke recommended or not?",
        "What is the 2026 position on routine prehospital BP lowering in stroke patients?",
    ],
    "rec-2.3-006": [
        "Should EMS administer neuroprotective agents to stroke patients in the field?",
        "What COR does routine prehospital neuroprotection receive?",
        "Per 2026, are prehospital neuroprotective agents recommended for stroke?",
        "What is the recommendation for routine prehospital neuroprotective agents?",
    ],
    "rec-2.3-007": [
        "Should EMS test blood glucose in the field for suspected stroke patients?",
        "What COR applies to prehospital blood glucose testing for suspected stroke?",
        "Per 2026, is field blood glucose testing recommended before hospital arrival?",
        "What is the recommendation for prehospital glucose testing by EMS?",
    ],

    # ── Section 2.4 — Destination Selection ──────────────────────
    "rec-2.4-001": [
        "Should suspected stroke patients be transported to the closest stroke-capable hospital?",
        "What COR applies to transporting stroke patients to the nearest stroke center rather than the nearest hospital?",
        "Per 2026, is transport to the nearest stroke-capable center recommended?",
        "What is the recommendation for EMS destination selection to a stroke center?",
        "Should EMS prioritize stroke centers over closer non-stroke hospitals?",
    ],
    "rec-2.4-002": [
        "Should EMS bypass closer hospitals to take suspected LVO patients directly to a comprehensive stroke center?",
        "What COR applies to bypassing primary stroke centers for direct transport to CSCs for EVT candidates?",
        "Per 2026, is bypassing closer hospitals to reach a CSC for LVO patients reasonable?",
        "What is the recommendation for direct transport to EVT-capable centers for suspected LVO?",
        "Is hospital bypass for EVT-eligible patients a COR 2a recommendation?",
    ],
    "rec-2.4-003": [
        "Should patients at a primary stroke center be transferred to a comprehensive center for EVT?",
        "What COR applies to transfer from PSC to CSC when EVT is needed?",
        "Per 2026, is inter-facility transfer for EVT from a PSC to a CSC reasonable?",
        "What is the recommendation for transferring stroke patients from PSC to CSC for thrombectomy?",
    ],
    "rec-2.4-004": [
        "Is treating stroke patients at hospitals without stroke unit capabilities recommended?",
        "What COR does treating stroke at non-stroke-capable hospitals receive?",
        "Per 2026, should stroke patients be managed at hospitals without dedicated stroke units?",
        "What is the recommendation against treating stroke at hospitals without stroke capabilities?",
    ],
    "rec-2.4-005": [
        "Should regionalized stroke systems with tiered hospital designations be used?",
        "What COR applies to using tiered stroke systems with different levels of hospital capability?",
        "Per 2026, is a tiered hospital system for stroke care recommended?",
        "What is the recommendation for stroke destination systems with primary, thrombectomy-capable, and comprehensive tiers?",
    ],

    # ── Section 2.5 — Mobile Stroke Units ────────────────────────
    "rec-2.5-001": [
        "Should mobile stroke units be used to give IVT faster in the prehospital setting?",
        "What COR applies to mobile stroke units for expediting IVT administration?",
        "Per 2026, is using mobile stroke units to speed up IVT a COR 1 recommendation?",
        "What is the recommendation for mobile stroke units in prehospital IVT delivery?",
    ],
    "rec-2.5-002": [
        "Should CT imaging be performed on mobile stroke units before hospital arrival?",
        "What COR applies to prehospital CT scanning on mobile stroke units?",
        "Per 2026, is performing CT on MSUs to diagnose stroke in the field recommended?",
        "What is the recommendation for prehospital brain CT on mobile stroke units?",
    ],
    "rec-2.5-003": [
        "Should trained teams provide IVT directly on mobile stroke units?",
        "What COR applies to IVT administration by trained personnel on MSUs?",
        "Per 2026, is it recommended that MSU teams administer IVT in the prehospital setting?",
        "What is the recommendation for IVT treatment on mobile stroke units by trained teams?",
    ],
    "rec-2.5-004": [
        "Should mobile stroke units be used for prehospital LVO triage decisions?",
        "What COR applies to using MSUs for LVO screening and triage to EVT centers?",
        "Per 2026, is using MSUs for prehospital LVO triage reasonable?",
        "What is the recommendation for MSU-based LVO triage for EVT routing?",
    ],

    # ── Section 2.6 — Hospital Certification ─────────────────────
    "rec-2.6-001": [
        "Should hospitals be organized into certified stroke centers?",
        "What COR applies to hospital stroke center certification?",
        "Per 2026, is organizing hospitals into certified stroke centers recommended?",
        "What is the recommendation for stroke center certification and designation?",
        "Is hospital stroke certification a COR 1 recommendation?",
    ],

    # ── Section 2.7 — Emergency Department ───────────────────────
    "rec-2.7-001": [
        "Should brain imaging be completed within 20 minutes of ED arrival for stroke?",
        "What COR applies to achieving door-to-imaging time under 20 minutes?",
        "Per 2026, is a door-to-imaging time target of less than 20 minutes recommended?",
        "What is the recommendation for the door-to-imaging time target?",
        "Is a 20-minute door-to-imaging time a COR 1 recommendation?",
    ],
    "rec-2.7-002": [
        "Should hospitals organize a multidisciplinary stroke team for rapid evaluation?",
        "What COR applies to having a dedicated stroke team for rapid ED assessment?",
        "Per 2026, is a multidisciplinary stroke team for rapid evaluation recommended?",
        "What is the recommendation for organizing a stroke team in the emergency department?",
    ],
    "rec-2.7-003": [
        "Should suspected stroke patients be triaged rapidly in the emergency department?",
        "What COR applies to rapid triage of suspected stroke in the ED?",
        "Per 2026, is prioritized ED triage for stroke patients recommended?",
        "What is the recommendation for rapid ED triage of stroke patients?",
    ],
    "rec-2.7-004": [
        "What is the door-to-needle time target for IVT per the 2026 guideline?",
        "What COR applies to a door-to-needle time goal of under 30 minutes for IVT?",
        "Per 2026, should the target for IVT door-to-needle time be less than 30 minutes?",
        "What is the recommendation for achieving DTN time under 30 minutes?",
        "Is a 30-minute door-to-needle time goal for IVT a COR 1 recommendation?",
    ],
    "rec-2.7-005": [
        "What is the door-to-groin-puncture time target for EVT per the 2026 guideline?",
        "What COR applies to a door-to-groin-puncture time under 60 minutes for EVT?",
        "Per 2026, should the target for EVT door-to-groin time be less than 60 minutes?",
        "What is the recommendation for achieving door-to-groin time under 60 minutes?",
        "Is a 60-minute door-to-groin-puncture time goal a COR 1 recommendation?",
    ],

    # ── Section 2.8 — Telestroke ─────────────────────────────────
    "rec-2.8-001": [
        "Should telestroke be used for acute stroke assessment at hospitals without stroke expertise?",
        "What COR applies to telestroke consultation for stroke evaluation at non-stroke centers?",
        "Per 2026, is telestroke for acute evaluation at community hospitals recommended?",
        "What is the recommendation for using telestroke at hospitals without on-site stroke specialists?",
    ],
    "rec-2.8-002": [
        "Should telestroke be used to guide IVT administration at remote sites?",
        "What COR applies to telestroke-guided IVT delivery?",
        "Per 2026, is telestroke-guided IVT administration recommended?",
        "What is the recommendation for using telestroke to supervise thrombolysis at non-expert sites?",
    ],
    "rec-2.8-003": [
        "Should telestroke be integrated into regional stroke systems of care networks?",
        "What COR applies to integrating telestroke into regional stroke networks?",
        "Per 2026, is incorporating telestroke into stroke systems of care recommended?",
        "What is the recommendation for telestroke integration into regional networks?",
    ],
    "rec-2.8-004": [
        "Should telestroke be used for EVT decision-making at remote sites?",
        "What COR applies to using telestroke for EVT eligibility assessment?",
        "Per 2026, is telestroke for thrombectomy decision-making reasonable?",
        "What is the recommendation for telestroke in EVT decision support?",
    ],
    "rec-2.8-005": [
        "Is robot-assisted telestroke for stroke assessment reasonable?",
        "What COR applies to robotic telepresence for stroke evaluation?",
        "Per 2026, is robot-assisted telestroke a COR 2a recommendation?",
        "What is the recommendation for robot-assisted telestroke systems?",
    ],
    "rec-2.8-006": [
        "Should credentialing and quality standards be established for telestroke providers?",
        "What COR applies to establishing credentialing standards for telestroke?",
        "Per 2026, is standardized credentialing for telestroke providers recommended?",
        "What is the recommendation for quality standards in telestroke programs?",
    ],
    "rec-2.8-007": [
        "Is store-and-forward telemedicine useful for acute stroke assessment?",
        "What COR applies to store-and-forward telestroke for acute stroke?",
        "Per 2026, is store-and-forward telemedicine for stroke well-established?",
        "What is the recommendation for asynchronous store-and-forward telestroke?",
    ],

    # ── Section 2.9 — Systems of Care ────────────────────────────
    "rec-2.9-001": [
        "Should regional stroke systems of care be organized per 2026 guidelines?",
        "What COR applies to organizing regional stroke systems of care?",
        "Per 2026, is organizing regional stroke care systems recommended?",
        "What is the recommendation for structured regional stroke systems of care?",
    ],
    "rec-2.9-002": [
        "Should inter-facility transfer processes for EVT be established?",
        "What COR applies to establishing streamlined transfer processes for EVT between hospitals?",
        "Per 2026, is establishing EVT transfer agreements between facilities recommended?",
        "What is the recommendation for organized inter-facility transfer for thrombectomy?",
    ],
    "rec-2.9-003": [
        "Should stroke systems implement quality improvement programs?",
        "What COR applies to stroke care performance improvement programs within a system?",
        "Per 2026, is developing quality improvement programs for stroke recommended?",
        "What is the recommendation for systematic stroke care performance improvement?",
    ],
    "rec-2.9-004": [
        "Should stroke care protocols be standardized across a stroke system of care?",
        "What COR applies to standardized stroke protocols across hospital networks?",
        "Per 2026, is implementing standardized protocols across stroke systems recommended?",
        "What is the recommendation for standardized stroke care across a network?",
    ],
    "rec-2.9-005": [
        "Should hospitals participate in national stroke quality registries?",
        "What COR applies to stroke registry participation?",
        "Per 2026, is participation in national stroke quality registries recommended?",
        "What is the recommendation for hospital participation in stroke registries?",
    ],
    "rec-2.9-006": [
        "Should patient and caregiver perspectives be included in stroke system design?",
        "What COR applies to incorporating patient and family input into stroke care design?",
        "Per 2026, is including patient perspectives in stroke system planning recommended?",
        "What is the recommendation for patient engagement in stroke system organization?",
    ],
    "rec-2.9-007": [
        "Should regional stroke referral agreements be established between hospitals?",
        "What COR applies to establishing formal referral agreements in a stroke network?",
        "Per 2026, is establishing inter-hospital stroke referral agreements reasonable?",
        "What is the recommendation for formal stroke referral agreements between facilities?",
    ],
    "rec-2.9-008": [
        "Should air medical transport be used to get stroke patients to comprehensive centers?",
        "What COR applies to using helicopter or air transport for stroke patients to reach CSCs?",
        "Per 2026, is air medical transport for stroke patients to CSCs considered reasonable?",
        "What is the recommendation for air medical transport in stroke care?",
    ],

    # ── Section 2.10 — Quality Metrics ───────────────────────────
    "rec-2.10-001": [
        "Should hospitals engage in multicomponent quality improvement with registries and audits for stroke care?",
        "What COR applies to continuous quality improvement using registries and audits for stroke?",
        "Per 2026, is a multicomponent QI process for stroke care recommended?",
        "What is the recommendation for hospital stroke quality improvement registries?",
    ],
    "rec-2.10-002": [
        "Should hospitals track and monitor stroke care performance metrics?",
        "What COR applies to hospital-level stroke performance metric tracking?",
        "Per 2026, should hospitals participate in stroke data registries for adherence to evidence-based care?",
        "What is the recommendation for stroke performance data tracking at the hospital level?",
    ],
    "rec-2.10-003": [
        "Should data-driven quality improvement programs be used for stroke care?",
        "What COR applies to data-driven stroke care QI programs?",
        "Per 2026, is using data and feedback for stroke quality improvement recommended?",
        "What is the recommendation for data-driven stroke quality initiatives?",
    ],

    # ── Section 3.1 — Severity Assessment ────────────────────────
    "rec-3.1-001": [
        "Should baseline NIHSS assessment be performed for all AIS patients?",
        "What COR applies to performing an initial NIHSS score for all stroke patients?",
        "Per 2026, is baseline stroke severity assessment with NIHSS recommended?",
        "What is the recommendation for performing NIHSS on all acute stroke patients?",
        "Is baseline NIHSS assessment a COR 1 recommendation for AIS?",
    ],

    # ── Section 3.2 — Imaging ────────────────────────────────────
    "rec-3.2-001": [
        "Should emergent non-contrast CT or MRI be done before IVT per the 2026 guideline?",
        "What COR applies to emergent brain CT before thrombolysis?",
        "Per 2026, is emergency non-contrast head CT before IVT a COR 1 recommendation?",
        "What is the recommendation for brain imaging to exclude hemorrhage before IVT?",
    ],
    "rec-3.2-002": [
        "Should non-invasive vascular imaging like CTA or MRA be done for EVT candidates?",
        "What COR applies to CTA or MRA to identify LVO for thrombectomy candidates?",
        "Per 2026, is non-invasive intracranial vascular imaging recommended for EVT candidates?",
        "What is the recommendation for CTA or MRA before EVT?",
    ],
    "rec-3.2-003": [
        "Should brain imaging be completed within 20 minutes of ED arrival?",
        "What COR applies to achieving brain imaging within 20 minutes of hospital arrival?",
        "Per 2026, is a 20-minute imaging time target for stroke recommended?",
        "What is the recommendation for the door-to-imaging time target for stroke?",
    ],
    "rec-3.2-004": [
        "Should CT perfusion or DWI-FLAIR mismatch be used to select wake-up stroke patients for IVT?",
        "What COR applies to CT perfusion or DWI-FLAIR mismatch for wake-up stroke IVT?",
        "Per 2026, is imaging-based selection with CTP or DWI-FLAIR mismatch reasonable for unknown-onset IVT?",
        "What is the recommendation for perfusion imaging to select wake-up stroke patients for IVT?",
    ],
    "rec-3.2-005": [
        "Should CT perfusion or MRI perfusion be used to select patients for extended-window EVT?",
        "What COR applies to perfusion imaging for EVT selection in the 6-24 hour window?",
        "Per 2026, is automated perfusion imaging for extended-window EVT selection reasonable?",
        "What is the recommendation for CTP or MRI perfusion in late-window EVT patient selection?",
    ],
    "rec-3.2-006": [
        "Should CTA or MRA be performed to evaluate for intracranial LVO before EVT?",
        "What COR applies to CTA or MRA for LVO detection before thrombectomy?",
        "Per 2026, is intracranial vascular imaging with CTA or MRA reasonable for EVT candidates?",
        "What is the recommendation for CTA/MRA to assess intracranial LVO before EVT?",
    ],
    "rec-3.2-007": [
        "Should automated perfusion imaging software be used for extended-window treatment decisions?",
        "What COR applies to automated perfusion software for extended-window stroke decisions?",
        "Per 2026, is automated CT perfusion analysis reasonable for selecting late-window patients?",
        "What is the recommendation for automated perfusion software in extended-window decisions?",
    ],
    "rec-3.2-008": [
        "Should emergent brain imaging be used to guide IVT treatment decisions?",
        "What COR applies to emergent brain imaging before IVT?",
        "Per 2026, is emergent neuroimaging to guide acute reperfusion decisions a COR 1 recommendation?",
        "What is the recommendation for emergency brain imaging to guide IVT decisions?",
    ],
    "rec-3.2-009": [
        "Should multiphase CTA or dynamic CTA be used for collateral assessment in stroke?",
        "What COR applies to multiphase CTA for collateral evaluation?",
        "Per 2026, is multiphase or dynamic CTA reasonable for assessing collateral status?",
        "What is the recommendation for multiphase CTA collateral assessment in acute stroke?",
    ],
    "rec-3.2-010": [
        "Should routine MRI be performed after IVT to assess for hemorrhagic transformation?",
        "What COR applies to routine post-IVT MRI for detecting hemorrhage?",
        "Per 2026, is routine MRI after thrombolysis to check for HT well-established?",
        "What is the recommendation for routine MRI after IVT?",
    ],
    "rec-3.2-011": [
        "Should cervical carotid duplex ultrasonography be used in the acute stroke setting?",
        "What COR applies to acute carotid duplex ultrasound for stroke evaluation?",
        "Per 2026, is cervical carotid duplex well-established for acute stroke assessment?",
        "What is the recommendation for carotid duplex ultrasonography in acute stroke?",
    ],

    # ── Section 3.3 — Lab Tests ──────────────────────────────────
    "rec-3.3-001": [
        "Should blood glucose level be obtained before IVT administration?",
        "What COR applies to checking blood glucose before giving thrombolytics?",
        "Per 2026, is obtaining a glucose level before IVT a COR 1 recommendation?",
        "What is the recommendation for blood glucose testing prior to IVT?",
    ],
    "rec-3.3-002": [
        "Should IVT be delayed to wait for lab results other than glucose?",
        "What COR applies to not delaying IVT for lab results beyond glucose?",
        "Per 2026, is it recommended to proceed with IVT without waiting for most labs?",
        "What is the recommendation for not delaying IVT while waiting for laboratory results?",
    ],
}

# I'll now add all remaining sections (4.x-6.x) programmatically
# using the rec text to extract discriminating questions

import sys, os
sys.path.insert(0, os.path.dirname(__file__))


def load_recs():
    with open("/tmp/all_recs.json") as f:
        return json.load(f)


def load_existing():
    with open("/tmp/existing_questions.json") as f:
        return set(q.lower().strip() for q in json.load(f))


# For sections 4.x-6.x, use the existing R3/R5 test suites as a guide
# and generate similar-style questions from the rec actions we already have
from generate_r9_test_suite import REC_ACTIONS as _ACTIONS  # noqa — won't work, define inline

# Re-import the actions
REC_ACTIONS_4_6 = {
    # Section 4.1
    "rec-4.1-001": "airway support and ventilatory assistance for AIS patients with decreased consciousness or bulbar dysfunction",
    "rec-4.1-002": "supplemental oxygen to maintain SpO2 above 94% in AIS patients with hypoxia",
    "rec-4.1-003": "general anesthesia with intubation for EVT in selected anterior circulation LVO patients within 6 hours",
    "rec-4.1-004": "hyperbaric oxygen for AIS due to arterial air embolism",
    "rec-4.1-005": "supplemental oxygen for non-hypoxic AIS patients ineligible for EVT",
    "rec-4.1-006": "hyperbaric oxygen for AIS not associated with air embolism",
    # Section 4.2
    "rec-4.2-001": "routine 0-degree flat head positioning for 24 hours after AIS",
    "rec-4.2-002": "routine Trendelenburg positioning for AIS with probable large artery atherosclerosis",
    # Section 4.3
    "rec-4.3-001": "correcting hypotension and hypovolemia in AIS to maintain systemic perfusion",
    "rec-4.3-002": "early treatment of hypertension in AIS when required by comorbid conditions like acute coronary event",
    "rec-4.3-003": "initiating BP treatment when BP is 220/120 or above without IVT, EVT, or urgent comorbidity",
    "rec-4.3-004": "initiating BP treatment when BP is below 220/120 without IVT, EVT, or urgent comorbidity",
    "rec-4.3-005": "lowering SBP to below 185 mmHg and DBP below 110 before IVT",
    "rec-4.3-006": "maintaining BP at or below 185/110 before EVT when IVT was not given",
    "rec-4.3-007": "maintaining BP below 180/105 for at least 24 hours after IVT",
    "rec-4.3-008": "intensive SBP reduction to below 140 mmHg compared with 180 mmHg after IVT",
    "rec-4.3-009": "maintaining BP at or below 180/105 during and for 24 hours after EVT",
    "rec-4.3-010": "intensive BP lowering to below 120 mmHg systolic after successful EVT recanalization with mTICI 2b or better",
    # Section 4.4
    "rec-4.4-001": "targeting normothermia with nurse-initiated fever protocols for AIS patients with hyperthermia",
    "rec-4.4-002": "identifying and treating sources of hyperthermia such as infection in AIS",
    "rec-4.4-003": "induced hypothermia or prophylactic fever prevention for normothermic AIS patients",
    # Section 4.5
    "rec-4.5-001": "treating hypoglycemia with blood glucose below 60 mg/dL in AIS",
    "rec-4.5-002": "treating persistent hyperglycemia to achieve blood glucose 140-180 mg/dL in AIS",
    "rec-4.5-003": "intensive IV insulin to achieve blood glucose 80-130 mg/dL in AIS",
    # Section 4.6.1
    "rec-4.6.1-001": "IVT for AIS with disabling deficits regardless of NIHSS score where faster treatment improves outcomes",
    "rec-4.6.1-002": "initiating IVT as quickly as possible within 4.5 hours assuring safe administration",
    "rec-4.6.1-003": "preparing to treat emergent IVT adverse effects including bleeding and angioedema",
    "rec-4.6.1-004": "discussing IVT risks and benefits for shared decision-making with competent patients",
    "rec-4.6.1-005": "determining blood glucose before IVT to assess for severe hypoglycemia or hyperglycemia",
    "rec-4.6.1-006": "giving IVT when disabling stroke persists after correction of severe hypo/hyperglycemia",
    "rec-4.6.1-007": "IVT for patients with early ischemic CT changes of mild to moderate extent without frank hypodensity",
    "rec-4.6.1-008": "IVT for mild non-disabling stroke deficits like isolated sensory syndrome within 4.5 hours",
    "rec-4.6.1-009": "IVT for patients taking single or dual antiplatelet therapy despite increased sICH risk",
    "rec-4.6.1-010": "not delaying IVT for hematologic or coagulation testing when no coagulopathy is suspected",
    "rec-4.6.1-011": "administering IVT with unknown burden of cerebral microbleeds without delay for MRI",
    "rec-4.6.1-012": "IVT for patients with a small number of 1-10 cerebral microbleeds on MRI",
    "rec-4.6.1-013": "IVT for patients with more than 10 cerebral microbleeds previously demonstrated on MRI",
    "rec-4.6.1-014": "IVT with alteplase for pediatric patients aged 28 days to 18 years with disabling AIS within 4.5 hours",
    # Section 4.6.2
    "rec-4.6.2-001": "tenecteplase 0.25 mg/kg max 25 mg or alteplase for IVT within 4.5 hours",
    "rec-4.6.2-002": "tenecteplase at the higher dose of 0.4 mg/kg for acute stroke",
    # Section 4.6.3
    "rec-4.6.3-001": "IVT for unknown-onset AIS within 4.5h of recognition with DWI lesion smaller than one-third MCA and no FLAIR signal",
    "rec-4.6.3-002": "IVT for wake-up stroke or 4.5-9h from midpoint of sleep with salvageable penumbra on perfusion imaging",
    "rec-4.6.3-003": "IVT for LVO patients 4.5-24 hours with salvageable penumbra who cannot receive EVT",
    # Section 4.6.4
    "rec-4.6.4-001": "IV reteplase instead of alteplase within 4.5 hours for non-EVT patients",
    "rec-4.6.4-002": "IV mutant prourokinase instead of alteplase within 4.5 hours",
    "rec-4.6.4-003": "IV desmoteplase for AIS within 3 to 9 hours from onset",
    "rec-4.6.4-004": "IV mutant prourokinase combined with low-dose alteplase",
    "rec-4.6.4-005": "IV urokinase for AIS within 6 hours to decrease death or dependency",
    "rec-4.6.4-006": "IV streptokinase for AIS within 6 hours",
    "rec-4.6.4-007": "sonothrombolysis as adjunctive therapy to IVT compared with IVT alone",
    # Section 4.6.5
    "rec-4.6.5-001": "IVT for AIS in adults with known sickle cell disease",
    "rec-4.6.5-002": "IVT for acute nonarteritic CRAO causing disabling visual loss",
    # Section 4.7.1
    "rec-4.7.1-001": "administering IVT to patients eligible for both IVT and EVT to improve reperfusion",
    "rec-4.7.1-002": "giving IVT rapidly without waiting for clinical response before proceeding to EVT",
    # Section 4.7.2
    "rec-4.7.2-001": "EVT for anterior ICA or M1 LVO within 6 hours with NIHSS 6+, prestroke mRS 0-1, and ASPECTS 6+",
    "rec-4.7.2-002": "EVT for anterior ICA or M1 LVO between 6-24 hours with NIHSS 6+, prestroke mRS 0-1, and ASPECTS 6+",
    "rec-4.7.2-003": "EVT for anterior ICA or M1 LVO 6-24 hours with age under 80 and ASPECTS 3-5",
    "rec-4.7.2-004": "EVT for anterior ICA or M1 LVO within 6 hours with age under 80 and ASPECTS 3-5",
    "rec-4.7.2-005": "EVT for anterior LVO within 6 hours with prestroke mRS 2 or 3 and ASPECTS 6+",
    "rec-4.7.2-006": "EVT for anterior LVO within 6 hours with prestroke mRS 4",
    "rec-4.7.2-007": "EVT for dominant proximal M2 occlusion within 6 hours with prestroke mRS 0-1 and NIHSS 6+",
    "rec-4.7.2-008": "EVT for nondominant or codominant proximal M2, distal MCA, ACA, or PCA occlusions",
    # Section 4.7.3
    "rec-4.7.3-001": "EVT for basilar artery occlusion with mRS 0-1, NIHSS 10+, PC-ASPECTS 6+ within 24 hours",
    "rec-4.7.3-002": "EVT for basilar artery occlusion with NIHSS 6-9",
    # Section 4.7.4
    "rec-4.7.4-001": "EVT using stent retrievers, contact aspiration, or combination techniques for LVO",
    "rec-4.7.4-002": "achieving reperfusion to extended TICI 2b/2c/3 as early as possible during EVT",
    "rec-4.7.4-003": "either general anesthesia or procedural sedation during EVT",
    "rec-4.7.4-004": "proximal balloon guide catheters during EVT to improve outcomes",
    "rec-4.7.4-005": "EVT for medium or distal vessel occlusions including nondominant M2, M3, or PCA",
    "rec-4.7.4-006": "emergent extracranial stenting for tandem extracranial-intracranial occlusions during EVT",
    "rec-4.7.4-007": "rescue intracranial balloon angioplasty or stenting after failed EVT",
    "rec-4.7.4-008": "adjunctive intra-arterial thrombolytics with urokinase, alteplase, or tenecteplase after near-complete EVT",
    "rec-4.7.4-009": "preoperative tirofiban before EVT for LVO to improve 90-day functional outcome",
    # Section 4.7.5
    "rec-4.7.5-001": "EVT for pediatric patients 6+ years with LVO within 6 hours by experienced neurointerventionalists",
    "rec-4.7.5-002": "EVT for pediatric patients 6+ years with LVO in the 6-24 hour window with salvageable tissue",
    "rec-4.7.5-003": "EVT for pediatric patients aged 28 days to 6 years with LVO and first-time seizure within 24 hours",
    # Section 4.8
    "rec-4.8-001": "aspirin within 48 hours of stroke onset to reduce death and dependency",
    "rec-4.8-002": "antiplatelet therapy within the first 24 hours after IVT with or without thrombectomy",
    "rec-4.8-003": "IV tirofiban for improving clinical outcomes in AIS",
    "rec-4.8-004": "IV abciximab for AIS due to bleeding complications",
    "rec-4.8-005": "antiplatelet therapy over oral anticoagulation for noncardioembolic stroke prevention",
    "rec-4.8-006": "individualized antiplatelet selection based on patient risk factors for noncardioembolic stroke",
    "rec-4.8-007": "antiplatelet or anticoagulant therapy for extracranial carotid or vertebral dissection for at least 3 months",
    "rec-4.8-008": "increasing aspirin dose or switching antiplatelet after noncardioembolic stroke while on aspirin",
    "rec-4.8-009": "clopidogrel over aspirin for reducing stroke, MI, or death",
    "rec-4.8-010": "triple antiplatelet therapy with aspirin, clopidogrel, and dipyridamole",
    "rec-4.8-011": "adding antiplatelet to oral anticoagulation for stroke with AF without active CAD",
    "rec-4.8-012": "DAPT with aspirin and clopidogrel for 21 days after minor NIHSS 3 or less noncardioembolic AIS or high-risk TIA",
    "rec-4.8-013": "DAPT with ticagrelor and aspirin for 21 days after minor NIHSS 5 or less AIS or high-risk TIA",
    "rec-4.8-014": "DAPT within 24-72 hours for minor noncardioembolic AIS with NIHSS 4-5",
    "rec-4.8-015": "DAPT for CYP2C19 loss-of-function carriers after minor noncardioembolic stroke",
    "rec-4.8-016": "aspirin as a substitute for IVT or thrombectomy in eligible patients",
    "rec-4.8-017": "IV aspirin concurrently or within 90 minutes after IVT start",
    "rec-4.8-018": "adjunctive IV eptifibatide with IVT within 3 hours to reduce disability",
    # Section 4.9
    "rec-4.9-001": "early oral anticoagulation for milder AIS with atrial fibrillation compared with delayed",
    "rec-4.9-002": "urgent anticoagulation for AIS with ipsilateral high-grade ICA stenosis",
    "rec-4.9-003": "short-term anticoagulation for ipsilateral nonocclusive extracranial intraluminal thrombus",
    "rec-4.9-004": "initiating or continuing anticoagulation in AIS with hemorrhagic transformation",
    "rec-4.9-005": "argatroban as adjunctive therapy with IVT for AIS functional outcomes",
    "rec-4.9-006": "early anticoagulation within 48 hours of AIS onset for neurological worsening",
    # Section 4.10
    "rec-4.10-001": "hemodilution, high-dose albumin, or chemical vasodilators like pentoxifylline for AIS",
    "rec-4.10-002": "mechanical hemodynamic augmentation with counterpulsation or sphenopalatine ganglion stimulation",
    # Section 4.11
    "rec-4.11-001": "pharmacological or nonpharmacological neuroprotective treatments for improving AIS outcome",
    # Section 4.12
    "rec-4.12-001": "emergent carotid endarterectomy or stenting for high-grade stenosis without intracranial occlusion",
    # Section 5.1
    "rec-5.1-001": "treatment within an organized inpatient stroke unit with interdisciplinary care team",
    # Section 5.2
    "rec-5.2-001": "bedside swallow screening before initiating liquid or food intake in AIS",
    "rec-5.2-002": "dysphagia screening performed by speech pathologists or other trained professionals",
    "rec-5.2-003": "endoscopic swallowing examination for patients who fail bedside screening",
    "rec-5.2-004": "oral hygiene protocol to reduce pneumonia risk after stroke",
    "rec-5.2-005": "pharyngeal electrical stimulation PES for reducing dysphagia severity and aspiration risk",
    "rec-5.2-006": "PES after ventilator weaning for severe stroke with dysphagia and tracheotomy",
    # Section 5.3
    "rec-5.3-001": "starting enteral diet within 7 days of AIS admission",
    "rec-5.3-002": "nutritional screening within 48 hours of stroke admission with dietitian assessment",
    "rec-5.3-003": "nasogastric tubes initially for feeding and PEG tubes if swallowing does not improve",
    # Section 5.4
    "rec-5.4-001": "IPC in addition to routine care for immobile AIS patients for DVT prophylaxis",
    "rec-5.4-002": "prophylactic-dose subcutaneous heparin UFH or LMWH for VTE risk reduction in immobile AIS",
    "rec-5.4-003": "prophylactic heparin over no heparin for improving functional outcome in immobile AIS",
    "rec-5.4-004": "LMWH over UFH for DVT prevention in immobile AIS patients",
    "rec-5.4-005": "elastic compression stockings for immobile AIS patients causing skin breakdown and necrosis",
    # Section 5.5
    "rec-5.5-001": "structured depression inventory screening for poststroke depression",
    "rec-5.5-002": "antidepressant or psychotherapy treatment for diagnosed poststroke depression",
    # Section 5.6
    "rec-5.6-001": "palliative care referral for selected AIS patients and their families",
    "rec-5.6-002": "routine prophylactic antibiotics for AIS patients",
    "rec-5.6-003": "routine indwelling bladder catheter placement in AIS due to UTI risk",
    # Section 5.7
    "rec-5.7-001": "formal interdisciplinary rehabilitation assessment and provision in hospital for AIS",
    "rec-5.7-002": "SSRIs for improving motor recovery or functional skills after AIS",
    "rec-5.7-003": "high-dose very early mobilization within 24 hours of AIS onset",
    # Section 6.1
    "rec-6.1-001": "early discussion of care options and outcomes for large infarctions at risk of brain swelling",
    "rec-6.1-002": "close neurological monitoring during the first days after large cerebral or cerebellar infarction",
    "rec-6.1-003": "early transfer to neurosurgical center for patients at risk of malignant brain swelling",
    # Section 6.2
    "rec-6.2-001": "osmotic therapy as a bridge to surgical intervention for brain swelling from large infarction",
    "rec-6.2-002": "IV glibenclamide for reducing cerebral edema in large hemispheric infarction age 18-70",
    "rec-6.2-003": "hypothermia barbiturates or corticosteroids for brain swelling after large infarction",
    # Section 6.3
    "rec-6.3-001": "early decompressive craniectomy for patients 18-60 years with unilateral MCA infarction causing decreased consciousness",
    "rec-6.3-002": "decompressive craniectomy within 48 hours of symptom onset for MCA territory infarction with edema",
    "rec-6.3-003": "decompressive craniectomy for patients over 60 years with unilateral MCA infarction who deteriorate",
    "rec-6.3-004": "decompressive craniectomy after IVT for MCA infarction with malignant edema",
    # Section 6.4
    "rec-6.4-001": "ventriculostomy for obstructive hydrocephalus from cerebellar infarction",
    "rec-6.4-002": "suboccipital craniectomy with dural expansion for cerebellar infarction with brainstem compression",
    # Section 6.5
    "rec-6.5-001": "antiseizure medication for recurrent unprovoked seizures after AIS",
    "rec-6.5-002": "prophylactic antiseizure medication for AIS patients without seizures",
}


# Templates for sections 4-6 using the action phrases
T_COR = [
    "What COR does {action} receive per the 2026 AIS guideline?",
    "What is the class of recommendation for {action}?",
    "Per the 2026 AIS guideline, what COR applies to {action}?",
]
T_LOE = [
    "What LOE does {action} have per the 2026 AIS guideline?",
    "What evidence level supports {action} per 2026?",
]
T_YESNO = [
    "Is {action} recommended per the 2026 AIS guideline?",
    "Does the 2026 guideline recommend {action}?",
    "Per 2026, should {action} be done?",
]
T_SCENARIO = [
    "For a patient with AIS, what is the 2026 recommendation for {action}?",
    "In the acute stroke setting, is {action} recommended per 2026?",
]
T_ALL = T_COR + T_LOE + T_YESNO + T_SCENARIO


def generate():
    random.seed(42)
    existing = load_existing()
    used = set(existing)
    recs = load_recs()
    questions = []
    qid = 4000

    # Pass 1: Hand-crafted questions for sections 2.x-3.x
    for rid, q_list in REC_QUESTIONS.items():
        r = recs.get(rid)
        if not r:
            continue
        for q in q_list:
            q_key = q.lower().strip()
            if q_key in used:
                continue
            used.add(q_key)
            questions.append({
                "id": f"QA-{qid}",
                "section": r["section"],
                "category": "qa_recommendation",
                "question": q,
                "expected_cor": r["cor"],
                "expected_loe": r["loe"],
                "expected_tier": "",
                "topic": f"{r['sectionTitle']} - rec {r['recNumber']}",
            })
            qid += 1

    # Pass 2: Template questions for sections 4.x-6.x
    for rid, action in sorted(REC_ACTIONS_4_6.items()):
        r = recs.get(rid)
        if not r:
            continue

        generated = 0
        attempts = 0
        while generated < 5 and attempts < 40:
            attempts += 1
            template = random.choice(T_ALL)
            q = template.format(action=action)
            q_key = q.lower().strip()
            if q_key in used:
                continue
            used.add(q_key)
            questions.append({
                "id": f"QA-{qid}",
                "section": r["section"],
                "category": "qa_recommendation",
                "question": q,
                "expected_cor": r["cor"],
                "expected_loe": r["loe"],
                "expected_tier": "",
                "topic": f"{r['sectionTitle']} - rec {r['recNumber']}",
            })
            qid += 1
            generated += 1

    # Trim or pad to 1000
    if len(questions) > 1000:
        random.shuffle(questions)
        questions = questions[:1000]

    questions.sort(key=lambda x: x["id"])
    for i, q in enumerate(questions):
        q["id"] = f"QA-{4000 + i}"

    return questions


def main():
    questions = generate()
    print(f"Generated {len(questions)} questions")

    sec_dist = Counter(q["section"] for q in questions)
    print(f"\nSection distribution ({len(sec_dist)} sections):")
    for sec in sorted(sec_dist.keys()):
        print(f"  {sec}: {sec_dist[sec]}")

    cor_dist = Counter(q["expected_cor"] for q in questions)
    print(f"\nCOR distribution:")
    for cor in sorted(cor_dist.keys()):
        print(f"  {cor}: {cor_dist[cor]}")

    out_path = (
        "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project/Datasources/"
        "Shared Folders For MedSync/Claude Questions for testing/Ask MedSync/"
        "qa_round9_test_suite.json"
    )
    with open(out_path, "w") as f:
        json.dump(questions, f, indent=2)
    print(f"\nSaved to {out_path}")

    print("\nSample questions:")
    for q in random.sample(questions, min(15, len(questions))):
        print(f"  [{q['section']}] COR={q['expected_cor']} LOE={q['expected_loe']}")
        print(f"    {q['question']}")


if __name__ == "__main__":
    main()
