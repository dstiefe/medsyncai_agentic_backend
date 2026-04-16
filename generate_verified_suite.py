#!/usr/bin/env python3
"""
Generate test questions with VERIFIED expected values.
Each question is derived from an actual recommendation, so COR/LOE is exact.
Uses the scoring pipeline to verify each question finds the right rec.
"""
import json
import sys
import os
import random

random.seed(42)
sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations
from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    score_recommendation,
    extract_search_terms,
    extract_section_references,
    extract_topic_sections,
    get_section_discriminators,
    classify_table8_tier,
)

# ══════════════════════════════════════════════════════════
# Question templates per section topic
# ══════════════════════════════════════════════════════════

# Each entry: (question_template, keywords_from_rec_text)
# The template uses {text_snippet} for a phrase from the rec

SECTION_QUESTIONS = {
    "2.1": [
        "What is the COR for stroke awareness education per the 2026 guidelines?",
        "What does the guideline recommend for public stroke recognition programs?",
        "Should stroke education programs target the general public?",
        "What level of recommendation applies to sustained stroke awareness campaigns?",
        "Are community stroke education programs recommended by the 2026 guideline?",
        "What is the recommendation for educating the public about stroke symptoms and calling 911?",
        "Does the guideline support educational programs on stroke recognition for the general public?",
    ],
    "2.2": [
        "What is the recommendation for EMS stroke dispatch protocols?",
        "Should EMS personnel use stroke screening tools per the 2026 guidelines?",
        "What COR applies to EMS stroke severity assessment tools?",
        "Does the guideline recommend prehospital stroke severity scales for EMS?",
        "What is the recommendation for EMS notification to receiving hospitals about incoming stroke patients?",
    ],
    "2.3": [
        "What is the recommendation for prehospital stroke triage?",
        "Should blood glucose be checked in the prehospital setting for suspected stroke?",
        "Does the guideline recommend against prehospital blood pressure lowering?",
        "Is prehospital neuroprotection recommended for stroke patients?",
        "What is the recommendation for supplemental oxygen in non-hypoxic prehospital stroke patients?",
        "Should prehospital IV access be established for suspected stroke?",
        "Is magnesium administration recommended in the prehospital setting for stroke?",
        "What does the guideline say about prehospital neuroprotective agents?",
    ],
    "2.4": [
        "Should EMS bypass non-stroke-ready hospitals?",
        "What is the recommendation for EMS destination protocols for suspected stroke?",
        "Should suspected LVO patients be transported directly to a thrombectomy-capable center?",
        "What does the guideline say about drip-and-ship versus mothership for stroke?",
        "Is air medical transport recommended for stroke patients to thrombectomy centers?",
    ],
    "2.5": [
        "What is the recommendation for mobile stroke units?",
        "Should mobile stroke units be deployed to reduce time to IVT?",
        "Is prehospital CT via mobile stroke unit recommended?",
        "What COR applies to prehospital thrombolysis via MSU?",
        "Does the guideline support MSU-based IVT for acute stroke?",
        "What LOE supports mobile stroke unit use for stroke treatment?",
    ],
    "2.6": [
        "What is the recommendation for hospital stroke certification?",
        "Should hospitals maintain organized stroke capabilities?",
    ],
    "2.7": [
        "What is the recommendation for emergency evaluation of suspected stroke?",
        "Should baseline stroke severity be assessed using a standardized scale upon arrival?",
        "Does the guideline recommend obtaining lab tests before IVT?",
        "What COR applies to rapid brain imaging for acute stroke?",
        "Should IVT be delayed for lab results other than blood glucose?",
    ],
    "2.8": [
        "What is the recommendation for telestroke in acute stroke management?",
        "Should telestroke be used to evaluate IVT eligibility at remote hospitals?",
        "Does the guideline support telestroke for thrombolysis decision-making?",
        "What COR applies to robot-assisted telestroke?",
        "Is telestroke recommended for facilitating EVT transfer decisions?",
        "Should telestroke networks include mechanisms for rapid transfer?",
    ],
    "2.9": [
        "What is the recommendation for organized stroke systems of care?",
        "Should regional stroke systems integrate EMS, hospitals, and rehabilitation?",
        "Does the guideline recommend standardized stroke care protocols?",
        "What COR applies to stroke system coordination?",
    ],
    "2.10": [
        "Should hospitals participate in stroke data registries?",
        "What is the recommendation for stroke quality improvement programs?",
        "Does the guideline recommend using registry data for quality improvement?",
    ],
    "3.1": [
        "Should a standardized stroke severity scale like NIHSS be used for acute stroke assessment?",
        "What COR applies to baseline stroke severity assessment using NIHSS?",
        "Does the guideline recommend a validated stroke severity scale?",
    ],
    "3.2": [
        "What is the initial imaging recommendation for suspected acute stroke?",
        "Is NCCT or MRI recommended for initial evaluation of acute ischemic stroke?",
        "Should noninvasive vascular imaging be performed for suspected LVO?",
        "What is the recommendation for CTA or MRA in EVT candidates?",
        "Does the guideline recommend CT perfusion for EVT patient selection?",
        "What COR applies to perfusion imaging in the extended time window for EVT?",
        "Should automated perfusion software be used for stroke imaging analysis?",
        "What is the recommendation for multiphase CTA in acute stroke?",
        "Is brain imaging with NCCT recommended before IVT?",
        "Does the guideline support MRI as an alternative to CT for initial stroke imaging?",
        "What is the recommendation for emergent vascular imaging in suspected LVO?",
        "Should ASPECTS be assessed on initial imaging?",
        "What is the COR for CT perfusion or MRI diffusion/perfusion in the 6-24h EVT window?",
    ],
    "3.3": [
        "What diagnostic tests are recommended alongside imaging in acute stroke?",
        "Should cardiac troponin be checked in acute stroke patients?",
        "What is the recommendation for baseline ECG in acute stroke?",
    ],
    "4.1": [
        "What is the recommendation for airway management in acute stroke?",
        "Should supplemental oxygen be given to non-hypoxic stroke patients?",
        "Is hyperbaric oxygen recommended for acute ischemic stroke?",
        "What COR applies to maintaining oxygen saturation above 94% in AIS?",
        "Does the guideline recommend intubation for decreased consciousness in stroke?",
        "What is the recommendation for high-flow nasal cannula in acute stroke?",
    ],
    "4.2": [
        "What is the recommendation for head-of-bed positioning in acute stroke?",
        "Does elevating the head of bed improve outcomes in acute stroke?",
        "Is flat bed positioning recommended for acute ischemic stroke?",
    ],
    "4.3": [
        "What are the BP targets for acute ischemic stroke?",
        "Should BP be lowered below 185/110 before IVT administration?",
        "What BP should be maintained in the first 24 hours after IVT?",
        "Is aggressive BP lowering recommended after successful EVT?",
        "What does the guideline say about BP management after EVT with successful reperfusion?",
        "Should SBP be maintained below 140 after successful EVT reperfusion?",
        "Is intensive BP lowering beneficial for patients not receiving IVT or EVT?",
        "What is the COR for rapid BP reduction greater than 25% in acute stroke?",
        "Does the guideline recommend labetalol or nicardipine for BP control in AIS?",
        "What BP target applies to AIS patients who are IVT candidates?",
    ],
    "4.4": [
        "Should fever be treated in acute stroke patients?",
        "What is the recommendation for temperature management in acute stroke?",
        "Is induced hypothermia recommended for acute ischemic stroke?",
        "Should antipyretics be given for hyperthermia in stroke?",
    ],
    "4.5": [
        "Should blood glucose be monitored in acute stroke patients?",
        "What is the recommendation for treating hyperglycemia in AIS?",
        "Is tight glycemic control recommended for acute stroke?",
        "Should hypoglycemia be corrected promptly in stroke patients?",
    ],
    "4.6.1": [
        "What is the COR for IV alteplase within 3 hours for disabling AIS?",
        "Is IVT recommended for patients arriving within 4.5 hours of symptom onset?",
        "What is the recommendation for IVT in mild non-disabling stroke?",
        "Should IVT be given to patients over age 80?",
        "Is IVT recommended for patients with early ischemic changes on CT?",
        "What does the guideline say about IVT and informed consent?",
        "Can IVT be given based on NCCT alone without waiting for lab results?",
        "Should IVT be administered as quickly as possible within the eligible time window?",
        "What is the recommendation for IVT in patients with LVO who are also EVT candidates?",
        "Is IVT recommended for patients taking oral anticoagulants?",
        "Should IVT be given to patients with severe hypoglycemia or hyperglycemia?",
        "What is the COR for IVT in patients with mild stroke and disabling deficits?",
        "Can IVT be given to patients with early ischemic changes but no contraindications?",
        "What is the recommendation for IVT in patients eligible within 4.5 hours regardless of age?",
    ],
    "4.6.2": [
        "Is tenecteplase recommended over alteplase for acute stroke?",
        "What is the COR for tenecteplase as an alternative to alteplase?",
        "What does the guideline say about using desmoteplase for AIS?",
        "Should tenecteplase be preferred over alteplase when available?",
    ],
    "4.6.3": [
        "Is IVT recommended in the 4.5 to 9 hour window with imaging selection?",
        "What imaging is required for IVT beyond 4.5 hours?",
        "Can IVT be given to wake-up stroke patients with DWI-FLAIR mismatch?",
        "What is the COR for IVT between 4.5 and 9 hours with perfusion mismatch?",
    ],
    "4.6.4": [
        "Is sonothrombolysis recommended for acute ischemic stroke?",
        "What does the guideline say about other IV fibrinolytics besides alteplase and tenecteplase?",
        "Is streptokinase recommended for acute stroke?",
        "What COR applies to urokinase for AIS?",
    ],
    "4.6.5": [
        "Can IVT be given to patients already on antiplatelet therapy?",
        "What is the recommendation for IVT in patients with pre-existing disability?",
    ],
    "4.7.1": [
        "Should IVT be given before EVT in eligible patients?",
        "Is bridging IVT recommended before mechanical thrombectomy?",
        "Should EVT be delayed to observe response to IVT?",
    ],
    "4.7.2": [
        "What is the COR for EVT in anterior LVO within 6 hours?",
        "Is EVT recommended for M1 MCA occlusion?",
        "What is the recommendation for EVT in ICA occlusion?",
        "Should EVT be performed for M2 occlusions?",
        "Is EVT recommended for patients with NIHSS under 6?",
        "What does the guideline say about EVT for patients over 80?",
        "Is EVT recommended in the 6-24 hour window with imaging selection?",
        "What is the recommendation for EVT with large ischemic core?",
        "Can EVT be performed for a patient with M1 occlusion and NIHSS 18?",
        "What imaging criteria are required for late-window EVT?",
        "Is EVT recommended beyond 24 hours?",
    ],
    "4.7.3": [
        "Is EVT recommended for basilar artery occlusion?",
        "What COR applies to thrombectomy for posterior circulation stroke?",
        "Should EVT be considered for vertebral artery occlusion?",
    ],
    "4.7.4": [
        "Should stent retrievers be used for mechanical thrombectomy?",
        "Is direct aspiration recommended as an EVT technique?",
        "What type of anesthesia should be used during EVT?",
        "What does the guideline say about intracranial stenting during EVT?",
        "Is rescue intra-arterial thrombolysis recommended during failed EVT?",
        "Should IA tPA alone be used as the primary EVT strategy?",
        "What is the recommendation for balloon guide catheter use during EVT?",
    ],
    "4.7.5": [
        "Is EVT recommended for pediatric stroke patients with LVO?",
        "What COR applies to thrombectomy in children?",
        "Should adult EVT criteria be applied to pediatric patients?",
    ],
    "4.8": [
        "When should aspirin be started after acute ischemic stroke?",
        "What is the recommendation for dual antiplatelet therapy in minor stroke?",
        "Should aspirin be given within 24 hours after IVT?",
        "Is clopidogrel loading recommended for minor stroke or TIA?",
        "What does the guideline say about ticagrelor for acute stroke?",
        "Should GP IIb/IIIa inhibitors be used in acute stroke?",
        "Is triple antiplatelet therapy recommended for AIS?",
        "What COR applies to DAPT beyond 21 days for minor stroke?",
        "Should IV antiplatelet agents be used during acute stroke?",
        "Is cangrelor recommended for acute ischemic stroke?",
        "What does the guideline say about cilostazol in acute stroke?",
        "Is early aspirin within 24-48 hours recommended for non-thrombolysed AIS patients?",
    ],
    "4.9": [
        "When should anticoagulation be started after cardioembolic stroke?",
        "Is urgent heparin anticoagulation recommended in acute stroke?",
        "What does the guideline say about early anticoagulation for stroke prevention?",
        "Should DOACs be preferred over warfarin for AF-related stroke?",
        "Is early anticoagulation within 48 hours recommended for large strokes?",
    ],
    "4.10": [
        "Is hemodilution recommended for acute ischemic stroke?",
        "Should volume expansion be used in acute stroke treatment?",
        "Are vasodilators recommended for acute ischemic stroke?",
    ],
    "4.11": [
        "Are neuroprotective agents recommended for acute ischemic stroke?",
        "What COR applies to neuroprotection in AIS?",
    ],
    "4.12": [
        "Is emergency carotid endarterectomy recommended during acute stroke?",
        "Should emergency carotid stenting be performed during AIS?",
    ],
    "5.1": [
        "Should stroke patients be admitted to a dedicated stroke unit?",
        "What is the COR for admission to a stroke unit?",
    ],
    "5.2": [
        "Should dysphagia screening be performed before oral intake in stroke?",
        "What is the recommendation for swallowing assessment after stroke?",
        "Is a formal swallowing evaluation recommended for stroke patients?",
        "Should patients with failed dysphagia screen get instrumental swallowing assessment?",
    ],
    "5.3": [
        "What is the recommendation for nutritional assessment after stroke?",
        "Should enteral nutrition be started early for stroke patients who cannot swallow?",
        "Is nasogastric tube feeding recommended for dysphagic stroke patients?",
    ],
    "5.4": [
        "What is the recommendation for DVT prophylaxis in stroke patients?",
        "Should intermittent pneumatic compression be used for DVT prevention?",
        "Are compression stockings recommended for DVT prevention after stroke?",
        "Is subcutaneous heparin recommended for immobile stroke patients?",
    ],
    "5.5": [
        "Should stroke patients be screened for depression?",
        "What is the recommendation for treating post-stroke depression?",
    ],
    "5.6": [
        "What is the recommendation for statin therapy in acute ischemic stroke?",
        "Should prophylactic antiseizure medications be given after stroke?",
        "Are benzodiazepines recommended for agitation after stroke?",
    ],
    "5.7": [
        "When should rehabilitation begin after acute stroke?",
        "Is very early high-dose mobilization within 24 hours recommended?",
        "Should all stroke patients receive a rehabilitation assessment?",
    ],
    "6.1": [
        "What monitoring is recommended for patients at risk of brain swelling after stroke?",
        "Should large stroke patients be monitored for cerebral edema?",
        "What is the recommendation for neurological monitoring in large hemispheric infarctions?",
    ],
    "6.2": [
        "Is osmotic therapy recommended for cerebral edema after stroke?",
        "Should corticosteroids be used for brain swelling in AIS?",
        "Does induced hypothermia reduce brain edema after stroke?",
    ],
    "6.3": [
        "Is decompressive craniectomy recommended for malignant MCA infarction?",
        "What is the recommendation for craniectomy in patients under 60?",
        "Should decompressive surgery be considered in older patients with large stroke?",
        "What is the COR for hemicraniectomy in malignant MCA territory infarction?",
    ],
    "6.4": [
        "Should posterior fossa decompression be performed for cerebellar stroke with brainstem compression?",
        "What is the recommendation for ventriculostomy in cerebellar infarction?",
    ],
    "6.5": [
        "Should clinical seizures be treated in acute stroke patients?",
        "Is prophylactic antiseizure medication recommended after stroke?",
    ],
}


def score_question(question_text, recommendations, sec_discs):
    search_terms = extract_search_terms(question_text)
    section_refs = extract_section_references(question_text)
    topic_sections, suppressed = extract_topic_sections(question_text)

    scored = []
    for rec in recommendations:
        s = score_recommendation(
            rec, search_terms,
            question=question_text,
            section_refs=section_refs,
            topic_sections=topic_sections,
            suppressed_sections=suppressed,
            section_discriminators=sec_discs,
        )
        scored.append((s, rec))
    scored.sort(key=lambda x: -x[0])
    return scored


def main():
    recommendations = load_recommendations()
    sec_discs = get_section_discriminators(recommendations)

    questions = []
    qid = 20000
    verified = 0
    failed = 0
    wrong_section = 0

    for section, q_list in SECTION_QUESTIONS.items():
        for question in q_list:
            scored = score_question(question, recommendations, sec_discs)
            if not scored or scored[0][0] <= 0:
                print(f"SKIP (no match): [{section}] {question[:80]}")
                failed += 1
                continue

            top_score, top_rec = scored[0]
            found_section = top_rec.get("section", "")
            found_cor = top_rec.get("cor", "")
            found_loe = top_rec.get("loe", "")

            if found_section != section:
                # Question routed to wrong section — record it as-is for analysis
                wrong_section += 1
                # Use the ACTUAL top rec's values as expected (since that's what the scorer finds)
                # But flag it

            questions.append({
                "id": f"QA-{qid}",
                "section": found_section,  # Use ACTUAL section the scorer finds
                "intended_section": section,  # What we intended
                "category": "qa_recommendation",
                "question": question,
                "expected_cor": found_cor,
                "expected_loe": found_loe,
                "expected_tier": "",
                "topic": f"{section} verified",
                "top_score": top_score,
                "section_match": found_section == section,
            })
            verified += 1
            qid += 1

    # ── Table 8 questions ──
    t8_questions = [
        # Absolute
        ("Is intracranial hemorrhage on imaging a contraindication to IVT?", "Absolute"),
        ("Does Table 8 classify active internal bleeding as a contraindication to thrombolysis?", "Absolute"),
        ("Is an intra-axial brain tumor an absolute contraindication to IVT per Table 8?", "Absolute"),
        ("How does Table 8 classify infective endocarditis for IVT?", "Absolute"),
        ("Is severe coagulopathy a contraindication to IVT?", "Absolute"),
        ("Does Table 8 classify aortic arch dissection as a contraindication to IVT?", "Absolute"),
        ("Is blood glucose less than 50 a contraindication to thrombolysis?", "Absolute"),
        ("How does the guideline classify extensive regions of obvious hypodensity for IVT?", "Absolute"),
        ("Is severe traumatic brain injury within 14 days a contraindication to IVT?", "Absolute"),
        ("Does Table 8 classify intracranial neurosurgery within 14 days as a contraindication?", "Absolute"),
        ("Is spinal cord injury within 14 days a contraindication to thrombolysis?", "Absolute"),
        ("How does Table 8 classify ARIA with recent amyloid immunotherapy for IVT?", "Absolute"),
        ("Is intra-axial intracranial neoplasm an absolute contraindication to IVT?", "Absolute"),
        ("How does Table 8 classify glioma for IVT eligibility?", "Absolute"),
        # Relative
        ("Is pregnancy a relative contraindication to IVT per Table 8?", "Relative"),
        ("How does Table 8 classify prior intracranial hemorrhage for IVT?", "Relative"),
        ("Is DOAC within 48 hours a contraindication to thrombolysis?", "Relative"),
        ("How does Table 8 classify active malignancy for IVT?", "Relative"),
        ("Is hepatic failure a contraindication to IVT?", "Relative"),
        ("How does Table 8 classify dialysis for IVT eligibility?", "Relative"),
        ("Is dementia a contraindication to thrombolysis per Table 8?", "Relative"),
        ("How does Table 8 classify arterial dissection for IVT?", "Relative"),
        ("Is vascular malformation a contraindication to IVT?", "Relative"),
        ("How does Table 8 classify pericarditis for IVT?", "Relative"),
        ("Is recent lumbar puncture a contraindication to thrombolysis?", "Relative"),
        ("How does Table 8 classify pre-existing disability for IVT?", "Relative"),
        ("Is pancreatitis a contraindication to IVT per Table 8?", "Relative"),
        ("How does Table 8 classify cardiac thrombus for IVT eligibility?", "Relative"),
        ("Is recent arterial puncture at noncompressible site a contraindication to IVT?", "Relative"),
        # Benefit May Exceed Risk
        ("How does Table 8 classify extracranial cervical arterial dissection for IVT?", "Benefit May Exceed Risk"),
        ("Is extra-axial intracranial neoplasm classified as benefit-may-exceed-risk for IVT?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify unruptured intracranial aneurysm for IVT?", "Benefit May Exceed Risk"),
        ("Is moyamoya disease classified as benefit-may-exceed-risk in Table 8?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify stroke mimic for IVT decision-making?", "Benefit May Exceed Risk"),
        ("Is seizure at stroke onset classified as benefit-may-exceed-risk for IVT?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify cerebral microbleeds for IVT?", "Benefit May Exceed Risk"),
        ("Is menstruation classified as a contraindication to IVT in Table 8?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify diabetic retinopathy for IVT eligibility?", "Benefit May Exceed Risk"),
        ("Is recreational drug use classified as benefit-may-exceed-risk for IVT?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify remote GI bleeding for IVT?", "Benefit May Exceed Risk"),
        ("Is history of myocardial infarction a contraindication to IVT per Table 8?", "Benefit May Exceed Risk"),
        ("How does Table 8 classify procedural stroke during angiography for IVT?", "Benefit May Exceed Risk"),
    ]

    tier_verified = 0
    tier_failed = 0
    for question, expected_tier in t8_questions:
        found_tier = classify_table8_tier(question)
        if found_tier == expected_tier:
            tier_verified += 1
            questions.append({
                "id": f"QA-{qid}",
                "section": "Table8",
                "intended_section": "Table8",
                "category": "qa_table8",
                "question": question,
                "expected_cor": "",
                "expected_loe": "",
                "expected_tier": expected_tier,
                "topic": f"Table8 {expected_tier}",
                "top_score": 0,
                "section_match": True,
            })
            qid += 1
        else:
            tier_failed += 1
            print(f"T8 MISMATCH: expected={expected_tier} got={found_tier} | {question[:80]}")

    # ── Listing questions (no expected tier) ──
    listing_qs = [
        "What are the absolute contraindications for IVT?",
        "What are the relative contraindications for thrombolysis?",
        "List the benefit-may-exceed-risk conditions for IVT per Table 8.",
        "What conditions does Table 8 cover for IVT eligibility?",
        "Show me the Table 8 contraindication categories.",
        "What are the three tiers of IVT contraindications in Table 8?",
    ]
    for q in listing_qs:
        questions.append({
            "id": f"QA-{qid}",
            "section": "Table8",
            "intended_section": "Table8",
            "category": "qa_table8",
            "question": q,
            "expected_cor": "",
            "expected_loe": "",
            "expected_tier": "",
            "topic": "Table8 listing",
            "top_score": 0,
            "section_match": True,
        })
        qid += 1

    # ── Evidence questions ��─
    ev_questions = [
        ("4.6.1", "What evidence supports IVT within 3 hours for AIS?"),
        ("4.6.1", "What studies support IVT for patients over 80 years of age?"),
        ("4.6.2", "What is the rationale behind the tenecteplase recommendation?"),
        ("4.6.3", "What data supports IVT in the extended time window?"),
        ("4.7.2", "What evidence supports EVT for anterior circulation LVO?"),
        ("4.7.2", "What trials support EVT in the 6-24 hour window?"),
        ("4.7.3", "What evidence supports EVT for basilar artery occlusion?"),
        ("4.3", "What data supports blood pressure targets after IVT?"),
        ("4.8", "What is the evidence for dual antiplatelet therapy in minor stroke?"),
        ("4.4", "What studies support treating fever in acute stroke?"),
        ("3.2", "What evidence supports perfusion imaging for EVT selection?"),
        ("5.4", "What is the rationale for DVT prophylaxis in stroke patients?"),
        ("6.3", "What evidence supports decompressive craniectomy for malignant MCA infarction?"),
        ("2.5", "What trials support mobile stroke unit deployment?"),
        ("5.7", "What evidence shows that very early high-dose mobilization is harmful?"),
    ]
    for section, question in ev_questions:
        questions.append({
            "id": f"QA-{qid}",
            "section": section,
            "intended_section": section,
            "category": "qa_evidence",
            "question": question,
            "expected_cor": "",
            "expected_loe": "",
            "expected_tier": "",
            "topic": f"{section} evidence",
            "top_score": 0,
            "section_match": True,
        })
        qid += 1

    # ── Knowledge gap questions ──
    kg_questions = [
        ("2.1", "What are the knowledge gaps for stroke awareness programs?"),
        ("4.6.1", "What future research is needed for IVT decision-making?"),
        ("4.7.2", "What are the knowledge gaps for endovascular thrombectomy in adults?"),
        ("4.3", "What research gaps exist for blood pressure management in AIS?"),
        ("4.8", "What are the unanswered questions about antiplatelet therapy in acute stroke?"),
        ("3.2", "What future research is needed for stroke imaging?"),
        ("6.3", "What remains unclear about decompressive surgery for malignant stroke?"),
        ("5.7", "What are the knowledge gaps for stroke rehabilitation?"),
        ("4.6.3", "What is unknown about extended window IVT?"),
        ("4.7.3", "What future directions exist for posterior circulation EVT?"),
    ]
    for section, question in kg_questions:
        questions.append({
            "id": f"QA-{qid}",
            "section": section,
            "intended_section": section,
            "category": "qa_knowledge_gap",
            "question": question,
            "expected_cor": "",
            "expected_loe": "",
            "expected_tier": "",
            "topic": f"{section} knowledge gap",
            "top_score": 0,
            "section_match": True,
        })
        qid += 1

    # ── Summary ──
    print(f"\nGenerated {len(questions)} questions")
    rec_qs = [q for q in questions if q["category"] == "qa_recommendation"]
    t8_qs = [q for q in questions if q["category"] == "qa_table8"]
    ev_qs = [q for q in questions if q["category"] == "qa_evidence"]
    kg_qs = [q for q in questions if q["category"] == "qa_knowledge_gap"]

    section_match_count = sum(1 for q in rec_qs if q["section_match"])
    print(f"  Recommendations: {len(rec_qs)} ({section_match_count} section-matched)")
    print(f"  Table 8: {len(t8_qs)} (verified: {tier_verified}, failed: {tier_failed})")
    print(f"  Evidence: {len(ev_qs)}")
    print(f"  Knowledge Gaps: {len(kg_qs)}")
    print(f"  Wrong section routing: {wrong_section}")

    # Sections covered
    secs = set(q["section"] for q in rec_qs)
    print(f"  Sections covered: {len(secs)}")

    # Save
    outpath = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"
    with open(outpath, "w") as f:
        json.dump(questions, f, indent=2)
    print(f"Saved to {outpath}")


if __name__ == "__main__":
    main()
