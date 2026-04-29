#!/usr/bin/env python3
"""Generate 500 new test questions across ALL guideline sections."""

import json
import random

random.seed(42)

questions = []
qid = 10000

def add(section, category, question, cor="", loe="", tier="", topic=""):
    global qid
    questions.append({
        "id": f"QA-{qid}",
        "section": section,
        "category": category,
        "question": question,
        "expected_cor": cor,
        "expected_loe": loe,
        "expected_tier": tier,
        "topic": topic,
    })
    qid += 1

# ═══════════════════════════════════════════════════════════
# SECTION 2.1 — Stroke Awareness (4 recs: all COR 1)
# ═══════════════════════════════════════════════════════════
add("2.1", "qa_recommendation", "What is the recommendation for public stroke awareness programs?", "1", "B-R", "", "stroke awareness")
add("2.1", "qa_recommendation", "What COR does the guideline assign to stroke symptom education?", "1", "B-R", "", "stroke symptom education")
add("2.1", "qa_recommendation", "Should community education programs include stroke recognition training?", "1", "B-NR", "", "community stroke education")
add("2.1", "qa_recommendation", "What is the guideline recommendation on educating the public about calling 911 for stroke?", "1", "B-NR", "", "calling 911 stroke")
add("2.1", "qa_recommendation", "Does the 2026 guideline support population-level stroke awareness campaigns?", "1", "B-R", "", "awareness campaigns")
add("2.1", "qa_evidence", "What evidence supports public educational programs for stroke recognition?", "", "", "", "stroke awareness evidence")
add("2.1", "qa_recommendation", "What LOE applies to community stroke awareness education?", "1", "B-NR", "", "awareness LOE")

# ═══════════════════════════════════════════════════════════
# SECTION 2.2 — EMS Systems (3 recs)
# ═══════════════════════════════════════════════════════════
add("2.2", "qa_recommendation", "What is the recommendation for EMS dispatch protocols in suspected stroke?", "1", "B-NR", "", "EMS dispatch")
add("2.2", "qa_recommendation", "Should EMS prioritize stroke calls?", "1", "B-NR", "", "EMS priority")
add("2.2", "qa_recommendation", "What COR does the guideline give for EMS stroke screening tools?", "1", "B-NR", "", "EMS screening")
add("2.2", "qa_recommendation", "Is there a recommendation for prehospital stroke severity scales by EMS?", "2a", "B-NR", "", "EMS severity scales")
add("2.2", "qa_recommendation", "What does the guideline say about EMS notification to receiving hospitals?", "1", "B-NR", "", "EMS notification")

# ═══════════════════════════════════════════════════════════
# SECTION 2.3 — Prehospital Assessment (7 recs)
# ═══════════════════════════════════════════════════════════
add("2.3", "qa_recommendation", "What is the recommendation for prehospital stroke assessment?", "2a", "B-NR", "", "prehospital assessment")
add("2.3", "qa_recommendation", "Should paramedics administer neuroprotective agents in the field?", "3:Harm", "A", "", "prehospital neuroprotection")
add("2.3", "qa_recommendation", "What COR applies to blood glucose testing in the prehospital setting?", "1", "A", "", "prehospital glucose")
add("2.3", "qa_recommendation", "Is prehospital blood pressure lowering recommended for stroke patients?", "3:No Benefit", "B-R", "", "prehospital BP lowering")
add("2.3", "qa_recommendation", "What does the guideline say about prehospital IV access?", "1", "B-NR", "", "prehospital IV")
add("2.3", "qa_recommendation", "Should supplemental oxygen be given to non-hypoxic stroke patients in the field?", "3:No Benefit", "B-R", "", "prehospital oxygen")
add("2.3", "qa_recommendation", "What is the recommendation for prehospital stroke severity assessment tools?", "2a", "B-NR", "", "prehospital severity")
add("2.3", "qa_recommendation", "Is magnesium administration recommended in the prehospital setting?", "3:Harm", "A", "", "prehospital magnesium")

# ═══════════════════════════════════════════════════════════
# SECTION 2.4 — EMS Destination Management (5 recs)
# ═══════════════════════════════════════════════════════════
add("2.4", "qa_recommendation", "Should EMS bypass non-stroke-ready hospitals?", "1", "B-NR", "", "EMS bypass")
add("2.4", "qa_recommendation", "What is the recommendation for transporting suspected LVO patients to a thrombectomy-capable center?", "2a", "B-NR", "", "LVO transport")
add("2.4", "qa_recommendation", "Is drip-and-ship preferred over mothership for EVT-eligible patients?", "2b", "B-NR", "", "drip and ship")
add("2.4", "qa_recommendation", "Should air medical transport be used for stroke patients?", "1", "B-NR", "", "air transport")
add("2.4", "qa_recommendation", "What COR applies to bypassing the closest hospital for a certified stroke center?", "1", "B-NR", "", "bypass for stroke center")
add("2.4", "qa_recommendation", "Is there no benefit to bypassing all hospitals if a stroke-ready center is nearby?", "3:No Benefit", "B-R", "", "bypass no benefit")

# ═══════════════════════════════════════════════════════════
# SECTION 2.5 — Mobile Stroke Units (4 recs)
# ═══════════════════════════════════════════════════════════
add("2.5", "qa_recommendation", "What is the recommendation for mobile stroke units?", "1", "A", "", "MSU recommendation")
add("2.5", "qa_recommendation", "Does the guideline support prehospital CT scanning via mobile stroke units?", "1", "A", "", "MSU CT")
add("2.5", "qa_recommendation", "What COR does the guideline give for IVT administration by MSU?", "1", "A", "", "MSU IVT")
add("2.5", "qa_recommendation", "Is prehospital thrombolysis via MSU recommended?", "1", "A", "", "MSU thrombolysis")
add("2.5", "qa_recommendation", "What LOE supports mobile stroke unit deployment?", "1", "A", "", "MSU LOE")
add("2.5", "qa_recommendation", "Should mobile stroke units be used to reduce time to treatment?", "1", "B-R", "", "MSU time reduction")

# ═══════════════════════════════════════════════════════════
# SECTION 2.6 — Hospital Stroke Capabilities (1 rec)
# ═══════════════════════════════════════════════════════════
add("2.6", "qa_recommendation", "What is the recommendation for hospital stroke certification?", "1", "B-NR", "", "hospital certification")
add("2.6", "qa_recommendation", "Should hospitals maintain stroke-ready status?", "1", "B-NR", "", "stroke ready")

# ═══════════════════════════════════════════════════════════
# SECTION 2.7 — Emergency Evaluation (5 recs)
# ═══════════════════════════════════════════════════════════
add("2.7", "qa_recommendation", "What is the recommendation for emergency evaluation of suspected stroke?", "1", "B-NR", "", "emergency evaluation")
add("2.7", "qa_recommendation", "Should lab tests be obtained before IVT administration?", "1", "A", "", "lab tests before IVT")
add("2.7", "qa_recommendation", "What COR applies to rapid imaging evaluation for acute stroke?", "1", "A", "", "rapid imaging")
add("2.7", "qa_recommendation", "Is immediate neurological assessment recommended for suspected stroke?", "1", "B-NR", "", "neuro assessment")
add("2.7", "qa_recommendation", "Should IVT be delayed for lab results in most patients?", "1", "A", "", "IVT delay labs")
add("2.7", "qa_recommendation", "What does the guideline say about door-to-needle time targets?", "1", "B-NR", "", "door to needle")

# ═══════════════════════════════════════════════════════════
# SECTION 2.8 — Telemedicine (7 recs)
# ═══════════════════════════════════════════════════════════
add("2.8", "qa_recommendation", "What is the recommendation for telestroke in AIS management?", "1", "B-R", "", "telestroke")
add("2.8", "qa_recommendation", "Should telestroke be used to evaluate IVT eligibility?", "1", "B-R", "", "telestroke IVT")
add("2.8", "qa_recommendation", "What COR applies to telestroke for remote hospitals without neurologists?", "1", "B-NR", "", "telestroke remote")
add("2.8", "qa_recommendation", "Is telestroke-guided IVT administration recommended?", "1", "B-R", "", "telestroke IVT admin")
add("2.8", "qa_recommendation", "What does the guideline say about telestroke for EVT decision-making?", "2a", "B-NR", "", "telestroke EVT")
add("2.8", "qa_recommendation", "Should robotic telestroke be used for acute stroke evaluation?", "2b", "B-NR", "", "robotic telestroke")

# ═══════════════════════════════════════════════════════════
# SECTION 2.9 — Organization/Integration (8 recs)
# ═══════════════════════════════════════════════════════════
add("2.9", "qa_recommendation", "What is the recommendation for organized stroke systems of care?", "1", "C-EO", "", "systems of care")
add("2.9", "qa_recommendation", "Should hospitals participate in stroke registries?", "1", "B-NR", "", "stroke registries")
add("2.9", "qa_recommendation", "What COR applies to quality improvement programs for stroke?", "1", "B-NR", "", "quality improvement")
add("2.9", "qa_recommendation", "Is a standardized stroke protocol recommended for hospitals?", "1", "C-EO", "", "standardized protocol")

# ═══════════════════════════════════════════════════════════
# SECTION 2.10 — Registries and QI (3 recs)
# ═══════════════════════════════════════════════════════════
add("2.10", "qa_recommendation", "What is the recommendation for participation in stroke registries?", "1", "B-R", "", "registry participation")
add("2.10", "qa_recommendation", "Should hospitals use Get With The Guidelines for quality improvement?", "1", "B-NR", "", "GWTG")
add("2.10", "qa_recommendation", "What COR applies to using stroke registry data for quality improvement?", "1", "B-R", "", "registry QI")

# ═══════════════════════════════════════════════════════════
# SECTION 3.1 — Stroke Scales (1 rec)
# ═══════════════════════════════════════════════════════════
add("3.1", "qa_recommendation", "Should a standardized stroke severity scale like NIHSS be used?", "1", "B-NR", "", "NIHSS")
add("3.1", "qa_recommendation", "What is the COR for using the NIHSS in acute stroke assessment?", "1", "B-NR", "", "NIHSS COR")
add("3.1", "qa_recommendation", "Does the guideline recommend a specific stroke severity scale?", "1", "B-NR", "", "stroke scale")

# ═══════════════════════════════════════════════════════════
# SECTION 3.2 — Imaging (11 recs)
# ═══════════════════════════════════════════════════════════
add("3.2", "qa_recommendation", "What is the initial imaging recommendation for acute stroke?", "1", "A", "", "initial imaging")
add("3.2", "qa_recommendation", "Is NCCT sufficient for IVT decision-making?", "1", "A", "", "NCCT for IVT")
add("3.2", "qa_recommendation", "Do I need MRI to evaluate for EVT?", "1", "A", "", "MRI for EVT")
add("3.2", "qa_recommendation", "Should CTA or MRA be performed for suspected LVO?", "1", "A", "", "CTA MRA LVO")
add("3.2", "qa_recommendation", "What is the recommendation for vascular imaging in EVT candidates?", "1", "A", "", "vascular imaging EVT")
add("3.2", "qa_recommendation", "Is CT perfusion recommended for selecting EVT candidates?", "2a", "B-R", "", "CTP for EVT")
add("3.2", "qa_recommendation", "What COR applies to CT perfusion in the 6-24 hour window?", "2a", "B-R", "", "CTP late window")
add("3.2", "qa_recommendation", "Should MRI perfusion be used instead of CT perfusion?", "2b", "B-R", "", "MRI perfusion")
add("3.2", "qa_recommendation", "What imaging is needed before giving tPA?", "1", "A", "", "imaging before tPA")
add("3.2", "qa_recommendation", "Is noninvasive vascular imaging recommended for all suspected stroke patients?", "1", "B-NR", "", "noninvasive vascular")
add("3.2", "qa_recommendation", "What is the recommendation for ASPECTS scoring on imaging?", "2a", "C-LD", "", "ASPECTS")
add("3.2", "qa_recommendation", "Should automated perfusion software be used for stroke imaging?", "2a", "C-LD", "", "automated perfusion")
add("3.2", "qa_recommendation", "What does the guideline say about multiphase CTA?", "2b", "B-NR", "", "multiphase CTA")
add("3.2", "qa_recommendation", "Can MRI be used instead of CT for initial stroke evaluation?", "1", "A", "", "MRI vs CT initial")

# ═══════════════════════════════════════════════════════════
# SECTION 3.3 — Other Diagnostic Tests (2 recs)
# ═══════════════════════════════════════════════════════════
add("3.3", "qa_recommendation", "What diagnostic tests are recommended alongside imaging for acute stroke?", "1", "C-LD", "", "other diagnostics")
add("3.3", "qa_recommendation", "Should troponin be checked in acute stroke patients?", "1", "B-NR", "", "troponin")
add("3.3", "qa_recommendation", "What is the recommendation for EKG in acute stroke?", "1", "B-NR", "", "EKG")

# ═══════════════════════════════════════════════════════════
# SECTION 4.1 — Airway, Breathing, Oxygenation (6 recs)
# ═══════════════════════════════════════════════════════════
add("4.1", "qa_recommendation", "What is the recommendation for airway management in acute stroke?", "1", "C-LD", "", "airway management")
add("4.1", "qa_recommendation", "Should supplemental oxygen be given to non-hypoxic stroke patients?", "3:No Benefit", "B-R", "", "oxygen non-hypoxic")
add("4.1", "qa_recommendation", "When is intubation recommended for acute stroke patients?", "1", "C-LD", "", "intubation")
add("4.1", "qa_recommendation", "Is hyperbaric oxygen recommended for acute ischemic stroke?", "3:No Benefit", "B-R", "", "hyperbaric oxygen")
add("4.1", "qa_recommendation", "What COR applies to high-flow nasal cannula in stroke?", "2b", "B-R", "", "high flow nasal")
add("4.1", "qa_recommendation", "Should oxygen saturation be maintained above 94% in stroke patients?", "1", "C-LD", "", "O2 sat target")

# ═══════════════════════════════════════════════════════════
# SECTION 4.2 — Head Positioning (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.2", "qa_recommendation", "What is the recommendation for head positioning in acute stroke?", "3:No Benefit", "B-R", "", "head positioning")
add("4.2", "qa_recommendation", "Should the head of bed be elevated or flat for stroke patients?", "3:No Benefit", "B-R", "", "HOB elevation")
add("4.2", "qa_recommendation", "Does head-of-bed positioning at 0 degrees improve outcomes?", "3:No Benefit", "B-R", "", "flat positioning")

# ═══════════════════════════════════════════════════════════
# SECTION 4.3 — Blood Pressure (10 recs)
# ═══════════════════════════════════════════════════════════
add("4.3", "qa_recommendation", "What are the BP targets during acute ischemic stroke?", "1", "C-LD", "", "BP targets")
add("4.3", "qa_recommendation", "What is the BP target before IVT administration?", "1", "C-LD", "", "BP before IVT")
add("4.3", "qa_recommendation", "Should BP be lowered below 185/110 before IVT?", "1", "C-LD", "", "BP 185/110 IVT")
add("4.3", "qa_recommendation", "What is the BP target after IVT administration?", "1", "B-NR", "", "BP after IVT")
add("4.3", "qa_recommendation", "Should BP be maintained below 180/105 during the first 24h post-IVT?", "1", "B-NR", "", "BP 180/105 post-IVT")
add("4.3", "qa_recommendation", "Is labetalol or nicardipine recommended for BP control in AIS?", "2a", "B-NR", "", "labetalol nicardipine")
add("4.3", "qa_recommendation", "What is the recommendation for intensive BP lowering in patients not receiving IVT or EVT?", "3:No Benefit", "A", "", "intensive BP non-IVT")
add("4.3", "qa_recommendation", "Should permissive hypertension be allowed in non-IVT acute stroke?", "2b", "C-EO", "", "permissive hypertension")
add("4.3", "qa_recommendation", "What BP target applies after successful EVT?", "1", "B-R", "", "BP post-EVT")
add("4.3", "qa_recommendation", "Should SBP be kept below 140 after successful EVT reperfusion?", "1", "B-R", "", "SBP 140 post-EVT")
add("4.3", "qa_recommendation", "Is aggressive BP reduction harmful in acute stroke?", "3:Harm", "A", "", "aggressive BP harm")
add("4.3", "qa_recommendation", "What COR applies to rapid BP lowering greater than 25% in AIS?", "3:Harm", "A", "", "rapid BP reduction")

# ═══════════════════════════════════════════════════════════
# SECTION 4.4 — Temperature (3 recs)
# ═══════════════════════════════════════════════════════════
add("4.4", "qa_recommendation", "Should fever be treated in acute stroke patients?", "1", "B-R", "", "fever treatment")
add("4.4", "qa_recommendation", "What is the recommendation for hyperthermia management in AIS?", "1", "B-R", "", "hyperthermia")
add("4.4", "qa_recommendation", "Is induced hypothermia recommended for acute ischemic stroke?", "3:No Benefit", "B-R", "", "hypothermia")
add("4.4", "qa_recommendation", "Should acetaminophen be given for fever in stroke patients?", "1", "C-EO", "", "acetaminophen fever")
add("4.4", "qa_recommendation", "What temperature target does the guideline recommend?", "1", "B-R", "", "temperature target")

# ═══════════════════════════════════════════════════════════
# SECTION 4.5 — Blood Glucose (3 recs)
# ═══════════════════════════════════════════════════════════
add("4.5", "qa_recommendation", "Should blood glucose be monitored in acute stroke?", "1", "C-LD", "", "glucose monitoring")
add("4.5", "qa_recommendation", "What is the recommendation for hyperglycemia treatment in AIS?", "2a", "C-LD", "", "hyperglycemia treatment")
add("4.5", "qa_recommendation", "Is tight glucose control recommended for acute stroke?", "3:No Benefit", "A", "", "tight glucose control")
add("4.5", "qa_recommendation", "Should hypoglycemia be corrected in acute stroke?", "1", "C-LD", "", "hypoglycemia correction")
add("4.5", "qa_recommendation", "What glucose range does the guideline recommend in AIS?", "2a", "C-LD", "", "glucose range")

# ═══════════════════════════════════════════════════════════
# SECTION 4.6.1 — Thrombolysis Decision-Making (14 recs)
# ═══════════════════════════════════════════════════════════
add("4.6.1", "qa_recommendation", "What is the COR for IV alteplase within 3 hours for disabling AIS?", "1", "A", "", "alteplase 3h")
add("4.6.1", "qa_recommendation", "Is IV thrombolysis recommended for patients arriving within 4.5 hours?", "1", "A", "", "IVT 4.5h")
add("4.6.1", "qa_recommendation", "What is the recommendation for IVT in mild non-disabling stroke?", "3:No Benefit", "B-R", "", "IVT mild non-disabling")
add("4.6.1", "qa_recommendation", "Should IVT be given to patients with NIHSS less than 6?", "1", "B-NR", "", "IVT NIHSS<6")
add("4.6.1", "qa_recommendation", "Is IVT recommended for patients over 80 years old?", "1", "A", "", "IVT age>80")
add("4.6.1", "qa_recommendation", "What does the guideline say about IVT for patients with prior stroke within 3 months?", "2a", "B-NR", "", "IVT prior stroke")
add("4.6.1", "qa_recommendation", "Should IVT be given to patients on anticoagulants?", "1", "B-NR", "", "IVT anticoagulants")
add("4.6.1", "qa_recommendation", "What is the recommendation for IVT in patients with large vessel occlusion?", "1", "A", "", "IVT LVO")
add("4.6.1", "qa_recommendation", "Can IVT be given based on NCCT alone?", "1", "A", "", "IVT NCCT alone")
add("4.6.1", "qa_recommendation", "Is IVT recommended for patients with early ischemic changes on CT?", "1", "B-NR", "", "IVT early changes")
add("4.6.1", "qa_recommendation", "What does the guideline say about informed consent for thrombolysis?", "1", "C-EO", "", "IVT consent")
add("4.6.1", "qa_recommendation", "Is there an upper age limit for IVT eligibility?", "1", "A", "", "IVT upper age")
add("4.6.1", "qa_recommendation", "Should IVT be started as quickly as possible within the time window?", "1", "A", "", "IVT speed")
add("4.6.1", "qa_recommendation", "What is the recommendation for IVT in patients with blood glucose under 50?", "1", "B-NR", "", "IVT glucose under 50")
add("4.6.1", "qa_recommendation", "Can IVT be given to stroke patients with seizure at onset?", "2a", "B-NR", "", "IVT seizure onset")

# ═══════════════════════════════════════════════════════════
# SECTION 4.6.2 — Choice of Thrombolytic (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.6.2", "qa_recommendation", "Is tenecteplase recommended over alteplase for IVT?", "1", "A", "", "tenecteplase vs alteplase")
add("4.6.2", "qa_recommendation", "What is the COR for tenecteplase in acute stroke?", "1", "A", "", "tenecteplase COR")
add("4.6.2", "qa_recommendation", "Is desmoteplase recommended for acute stroke?", "3:No Benefit", "A", "", "desmoteplase")
add("4.6.2", "qa_recommendation", "What dose of tenecteplase does the guideline recommend?", "1", "A", "", "tenecteplase dose")
add("4.6.2", "qa_recommendation", "Should alteplase still be used if tenecteplase is available?", "1", "A", "", "alteplase if TNK available")

# ═══════════════════════════════════════════════════════════
# SECTION 4.6.3 — Extended Window IVT (3 recs)
# ═══════════════════════════════════════════════════════════
add("4.6.3", "qa_recommendation", "Is IVT recommended in the 4.5 to 9 hour window?", "2a", "B-R", "", "IVT extended window")
add("4.6.3", "qa_recommendation", "What imaging is required for IVT beyond 4.5 hours?", "2a", "B-R", "", "IVT late imaging")
add("4.6.3", "qa_recommendation", "Can IVT be given to wake-up stroke patients?", "2a", "B-R", "", "IVT wake-up stroke")
add("4.6.3", "qa_recommendation", "What is the COR for IVT between 4.5 and 9 hours with perfusion imaging?", "2a", "B-R", "", "IVT 4.5-9h perfusion")
add("4.6.3", "qa_recommendation", "Is IVT recommended beyond 9 hours from last known well?", "2b", "B-R", "", "IVT beyond 9h")

# ═══════════════════════════════════════════════════════════
# SECTION 4.6.4 — Other Fibrinolytics (7 recs)
# ═══════════════════════════════════════════════════════════
add("4.6.4", "qa_recommendation", "What is the recommendation for sonothrombolysis in acute stroke?", "3:No Benefit", "B-R", "", "sonothrombolysis")
add("4.6.4", "qa_recommendation", "Is urokinase recommended for acute ischemic stroke?", "3:No Benefit", "A", "", "urokinase")
add("4.6.4", "qa_recommendation", "What COR does streptokinase have for AIS?", "3:Harm", "A", "", "streptokinase")
add("4.6.4", "qa_recommendation", "Are other IV fibrinolytics besides alteplase and tenecteplase recommended?", "3:No Benefit", "A", "", "other fibrinolytics")
add("4.6.4", "qa_recommendation", "Should reteplase be used for acute ischemic stroke?", "2b", "B-R", "", "reteplase")

# ═══════════════════════════════════════════════════════════
# SECTION 4.6.5 — Other IVT Circumstances (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.6.5", "qa_recommendation", "What is the recommendation for IVT in patients already on antiplatelet therapy?", "2a", "B-NR", "", "IVT antiplatelet")
add("4.6.5", "qa_recommendation", "Can IVT be given to patients with prior disability?", "2b", "C-LD", "", "IVT prior disability")
add("4.6.5", "qa_recommendation", "Is IVT recommended for mild but disabling stroke?", "2a", "B-NR", "", "IVT mild disabling")

# ═══════════════════════════════════════════════════════════
# SECTION 4.7.1 — IVT + EVT (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.7.1", "qa_recommendation", "Should IVT be given before EVT?", "1", "A", "", "IVT before EVT")
add("4.7.1", "qa_recommendation", "Is bridging IVT recommended before mechanical thrombectomy?", "1", "A", "", "bridging IVT EVT")
add("4.7.1", "qa_recommendation", "Should EVT be delayed to wait for IVT response?", "1", "A", "", "EVT delay for IVT")
add("4.7.1", "qa_recommendation", "Can EVT be performed without prior IVT if IVT is contraindicated?", "1", "A", "", "EVT without IVT")

# ═══════════════════════════════════════════════════════════
# SECTION 4.7.2 — EVT for Adults (8 recs)
# ═══════════════════════════════════════════════════════════
add("4.7.2", "qa_recommendation", "What is the COR for EVT in anterior LVO within 6 hours?", "1", "A", "", "EVT LVO 6h")
add("4.7.2", "qa_recommendation", "Is EVT recommended for M1 MCA occlusion?", "1", "A", "", "EVT M1")
add("4.7.2", "qa_recommendation", "What is the recommendation for EVT in ICA occlusion?", "1", "A", "", "EVT ICA")
add("4.7.2", "qa_recommendation", "Should EVT be performed for M2 occlusions?", "2a", "B-R", "", "EVT M2")
add("4.7.2", "qa_recommendation", "Is EVT recommended for patients with NIHSS less than 6?", "2b", "B-NR", "", "EVT NIHSS<6")
add("4.7.2", "qa_recommendation", "What does the guideline say about EVT for patients over 80?", "1", "A", "", "EVT age>80")
add("4.7.2", "qa_recommendation", "Should EVT be performed for ASPECTS less than 6?", "2a", "B-NR", "", "EVT ASPECTS<6")
add("4.7.2", "qa_recommendation", "Is EVT recommended in the 6-24 hour window?", "1", "A", "", "EVT 6-24h")
add("4.7.2", "qa_recommendation", "What are the imaging criteria for EVT in the extended window?", "1", "A", "", "EVT extended imaging")
add("4.7.2", "qa_recommendation", "Can EVT be performed for a 65-year-old with NIHSS 18 and M1 occlusion?", "1", "A", "", "EVT case 65yo")
add("4.7.2", "qa_recommendation", "What is the recommendation for EVT beyond 24 hours?", "3:No Benefit", "A", "", "EVT beyond 24h")
add("4.7.2", "qa_recommendation", "Is EVT recommended for A1 or A2 occlusions?", "2a", "B-NR", "", "EVT A1 A2")

# ═══════════════════════════════════════════════════════════
# SECTION 4.7.3 — Posterior Circulation (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.7.3", "qa_recommendation", "Is EVT recommended for basilar artery occlusion?", "1", "A", "", "EVT basilar")
add("4.7.3", "qa_recommendation", "What is the COR for thrombectomy in posterior circulation stroke?", "1", "A", "", "EVT posterior")
add("4.7.3", "qa_recommendation", "Should EVT be considered for vertebral artery occlusion?", "2b", "B-R", "", "EVT vertebral")
add("4.7.3", "qa_recommendation", "What evidence supports EVT for basilar occlusion?", "1", "A", "", "EVT basilar evidence")

# ═══════════════════════════════════════════════════════════
# SECTION 4.7.4 — Endovascular Techniques (9 recs)
# ═══════════════════════════════════════════════════════════
add("4.7.4", "qa_recommendation", "What is the recommendation for stent retriever use during EVT?", "1", "A", "", "stent retriever")
add("4.7.4", "qa_recommendation", "Is direct aspiration recommended for EVT?", "1", "A", "", "direct aspiration")
add("4.7.4", "qa_recommendation", "Should conscious sedation or general anesthesia be used for EVT?", "1", "B-R", "", "anesthesia EVT")
add("4.7.4", "qa_recommendation", "What does the guideline say about intracranial stenting during EVT?", "2b", "B-NR", "", "intracranial stenting")
add("4.7.4", "qa_recommendation", "Is rescue IA thrombolysis recommended during failed EVT?", "2b", "B-R", "", "rescue IA thrombolysis")
add("4.7.4", "qa_recommendation", "What is the recommendation for combined stent retriever and aspiration?", "2b", "B-R", "", "combined technique")
add("4.7.4", "qa_recommendation", "Should balloon guide catheters be used during EVT?", "2b", "B-NR", "", "balloon guide")
add("4.7.4", "qa_recommendation", "Is IA tPA alone recommended as primary EVT strategy?", "3:No Benefit", "A", "", "IA tPA alone")

# ═══════════════════════════════════════════════════════════
# SECTION 4.7.5 — Pediatric EVT (3 recs)
# ═══════════════════════════════════════════════════════════
add("4.7.5", "qa_recommendation", "Is EVT recommended for pediatric stroke patients?", "2a", "B-NR", "", "pediatric EVT")
add("4.7.5", "qa_recommendation", "What COR does EVT have in children with LVO?", "2a", "B-NR", "", "pediatric EVT COR")
add("4.7.5", "qa_recommendation", "Should adult EVT criteria be applied to pediatric patients?", "2b", "B-NR", "", "pediatric EVT criteria")
add("4.7.5", "qa_recommendation", "What does the guideline say about neonatal stroke and EVT?", "2a", "B-NR", "", "neonatal EVT")

# ═══════════════════════════════════════════════════════════
# SECTION 4.8 — Antiplatelet (18 recs)
# ═══════════════════════════════════════════════════════════
add("4.8", "qa_recommendation", "When should aspirin be started after acute ischemic stroke?", "1", "A", "", "aspirin timing")
add("4.8", "qa_recommendation", "What is the recommendation for dual antiplatelet therapy in minor stroke?", "1", "A", "", "DAPT minor stroke")
add("4.8", "qa_recommendation", "Should aspirin be given within 24 hours of IVT?", "2b", "B-NR", "", "aspirin after IVT")
add("4.8", "qa_recommendation", "Is clopidogrel loading recommended in minor stroke?", "1", "A", "", "clopidogrel loading")
add("4.8", "qa_recommendation", "What is the recommendation for ticagrelor in acute stroke?", "2a", "B-R", "", "ticagrelor")
add("4.8", "qa_recommendation", "Should GP IIb/IIIa inhibitors be used in acute stroke?", "3:Harm", "B-R", "", "GP IIb/IIIa")
add("4.8", "qa_recommendation", "What COR applies to aspirin alone for non-cardioembolic stroke?", "1", "A", "", "aspirin alone")
add("4.8", "qa_recommendation", "Is triple antiplatelet therapy recommended?", "3:Harm", "B-R", "", "triple antiplatelet")
add("4.8", "qa_recommendation", "Should DAPT be continued beyond 21 days for minor stroke?", "3:Harm", "B-R", "", "DAPT duration")
add("4.8", "qa_recommendation", "What is the recommendation for IV antiplatelet agents in AIS?", "3:Harm", "B-NR", "", "IV antiplatelet")
add("4.8", "qa_recommendation", "Can aspirin be given within 24 hours of thrombolysis?", "2b", "B-NR", "", "aspirin 24h post-IVT")
add("4.8", "qa_recommendation", "Is cangrelor recommended for acute stroke?", "3:No Benefit", "B-R", "", "cangrelor")
add("4.8", "qa_recommendation", "What does the guideline say about cilostazol for acute stroke?", "2b", "B-R", "", "cilostazol")

# ═══════════════════════════════════════════════════════════
# SECTION 4.9 — Anticoagulants (6 recs)
# ═══════════════════════════════════════════════════════════
add("4.9", "qa_recommendation", "When should anticoagulation be started after cardioembolic stroke?", "2a", "A", "", "anticoagulation timing")
add("4.9", "qa_recommendation", "Should heparin be used in the acute phase of stroke?", "3:No Benefit", "A", "", "heparin acute")
add("4.9", "qa_recommendation", "What is the recommendation for early anticoagulation in AIS?", "3:No Benefit", "A", "", "early anticoagulation")
add("4.9", "qa_recommendation", "Is DOAC recommended over warfarin for AF-related stroke?", "2a", "A", "", "DOAC vs warfarin AF")
add("4.9", "qa_recommendation", "Should anticoagulation be started within 48 hours of large stroke?", "2b", "B-NR", "", "anticoag large stroke")
add("4.9", "qa_recommendation", "What COR applies to urgent anticoagulation for stroke prevention?", "3:No Benefit", "A", "", "urgent anticoag")

# ═══════════════════════════════════════════════════════════
# SECTION 4.10 — Volume/Vasodilators (2 recs)
# ═══════════════════════════════════════════════════════════
add("4.10", "qa_recommendation", "Is hemodilution recommended for acute ischemic stroke?", "3:No Benefit", "A", "", "hemodilution")
add("4.10", "qa_recommendation", "Should volume expansion be used in acute stroke treatment?", "3:No Benefit", "A", "", "volume expansion")
add("4.10", "qa_recommendation", "Are vasodilators recommended for acute ischemic stroke?", "3:No Benefit", "B-R", "", "vasodilators")

# ═══════════════════════════════════════════════════════════
# SECTION 4.11 — Neuroprotective Agents (1 rec)
# ═══════════════════════════════════════════════════════════
add("4.11", "qa_recommendation", "Are neuroprotective agents recommended for acute stroke?", "3:No Benefit", "A", "", "neuroprotection")
add("4.11", "qa_recommendation", "What is the COR for neuroprotective agents in AIS?", "3:No Benefit", "A", "", "neuroprotection COR")

# ═══════════════════════════════════════════════════════════
# SECTION 4.12 — Emergency CEA/CAS (1 rec)
# ═══════════════════════════════════════════════════════════
add("4.12", "qa_recommendation", "Is emergency carotid endarterectomy recommended during acute stroke?", "3:No Benefit", "B-NR", "", "emergency CEA")
add("4.12", "qa_recommendation", "Should emergency carotid stenting be performed during AIS?", "3:No Benefit", "B-NR", "", "emergency CAS")

# ═══════════════════════════════════════════════════════════
# SECTION 5.1 — Stroke Units (1 rec)
# ═══════════════════════════════════════════════════════════
add("5.1", "qa_recommendation", "Should stroke patients be admitted to a dedicated stroke unit?", "1", "B-R", "", "stroke unit")
add("5.1", "qa_recommendation", "What is the COR for stroke unit admission?", "1", "B-R", "", "stroke unit COR")

# ═══════════════════════════════════════════════════════════
# SECTION 5.2 — Dysphagia (6 recs)
# ═══════════════════════════════════════════════════════════
add("5.2", "qa_recommendation", "Should dysphagia screening be performed before oral intake?", "1", "C-EO", "", "dysphagia screening")
add("5.2", "qa_recommendation", "What is the recommendation for formal swallowing assessment in stroke?", "2a", "C-LD", "", "swallowing assessment")
add("5.2", "qa_recommendation", "Should videofluoroscopic swallowing study be done for all stroke patients?", "2a", "B-NR", "", "VFSS")
add("5.2", "qa_recommendation", "What COR applies to NPO orders for stroke patients with dysphagia risk?", "1", "C-EO", "", "NPO dysphagia")

# ═══════════════════════════════════════════════════════════
# SECTION 5.3 — Nutrition (3 recs)
# ═══════════════════════════════════════════════════════════
add("5.3", "qa_recommendation", "What is the recommendation for nutritional assessment after stroke?", "1", "B-R", "", "nutritional assessment")
add("5.3", "qa_recommendation", "Should enteral nutrition be started early in stroke patients who cannot swallow?", "1", "B-NR", "", "enteral nutrition")
add("5.3", "qa_recommendation", "Is parenteral nutrition recommended for acute stroke?", "2a", "B-NR", "", "parenteral nutrition")

# ═══════════════════════════════════════════════════════════
# SECTION 5.4 — DVT Prophylaxis (5 recs)
# ═══════════════════════════════════════════════════════════
add("5.4", "qa_recommendation", "What is the recommendation for DVT prophylaxis in stroke patients?", "1", "B-R", "", "DVT prophylaxis")
add("5.4", "qa_recommendation", "Should compression stockings be used for DVT prevention in stroke?", "3:Harm", "B-R", "", "compression stockings")
add("5.4", "qa_recommendation", "Is subcutaneous heparin recommended for DVT prevention after stroke?", "1", "B-R", "", "SQ heparin DVT")
add("5.4", "qa_recommendation", "Should intermittent pneumatic compression be used for stroke patients?", "2a", "B-R", "", "IPC")
add("5.4", "qa_recommendation", "Is early mobilization sufficient for DVT prevention in stroke?", "2b", "A", "", "early mobilization DVT")

# ═══════════════════════════════════════════════════════════
# SECTION 5.5 — Depression (2 recs)
# ═══════════════════════════════════════════════════════════
add("5.5", "qa_recommendation", "Should stroke patients be screened for depression?", "1", "B-NR", "", "depression screening")
add("5.5", "qa_recommendation", "What is the recommendation for treating post-stroke depression?", "1", "B-R", "", "depression treatment")
add("5.5", "qa_recommendation", "Are SSRIs recommended for post-stroke depression?", "1", "B-R", "", "SSRIs depression")

# ═══════════════════════════════════════════════════════════
# SECTION 5.6 — Other Hospital Management (3 recs)
# ═══════════════════════════════════════════════════════════
add("5.6", "qa_recommendation", "What is the recommendation for statin therapy in acute stroke?", "2a", "C-EO", "", "statin")
add("5.6", "qa_recommendation", "Are prophylactic antiseizure medications recommended after stroke?", "3:No Benefit", "A", "", "prophylactic antiseizure")
add("5.6", "qa_recommendation", "Should benzodiazepines be used routinely for agitation after stroke?", "3:Harm", "C-LD", "", "benzodiazepines")

# ═══════════════════════════════════════════════════════════
# SECTION 5.7 — Rehabilitation (3 recs)
# ═══════════════════════════════════════════════════════════
add("5.7", "qa_recommendation", "When should rehabilitation begin after acute stroke?", "1", "A", "", "rehab timing")
add("5.7", "qa_recommendation", "Is very early mobilization within 24 hours recommended?", "3:Harm", "B-R", "", "very early mobilization")
add("5.7", "qa_recommendation", "Should formal rehabilitation assessment be done for all stroke patients?", "1", "A", "", "rehab assessment")
add("5.7", "qa_recommendation", "Is high-dose early mobilization harmful after stroke?", "3:Harm", "B-R", "", "high dose mobilization")
add("5.7", "qa_recommendation", "What is the COR for early mobilization within 24 hours of stroke?", "3:No Benefit", "A", "", "early mobilization COR")

# ═══════════════════════════════════════════════════════════
# SECTION 6.1 — Brain Swelling General (3 recs)
# ═══════════════════════════════════════════════════════════
add("6.1", "qa_recommendation", "What is the recommendation for monitoring brain swelling after AIS?", "1", "C-EO", "", "brain swelling monitoring")
add("6.1", "qa_recommendation", "Should clinicians anticipate cerebral edema after large strokes?", "1", "C-EO", "", "cerebral edema anticipation")
add("6.1", "qa_recommendation", "What COR applies to ICU monitoring for malignant edema risk?", "1", "C-LD", "", "ICU malignant edema")

# ═══════════════════════════════════════════════════════════
# SECTION 6.2 — Brain Swelling Medical (3 recs)
# ═══════════════════════════════════════════════════════════
add("6.2", "qa_recommendation", "Is osmotic therapy recommended for cerebral edema after stroke?", "2a", "C-LD", "", "osmotic therapy")
add("6.2", "qa_recommendation", "Should corticosteroids be used for brain swelling after AIS?", "3:Harm", "C-LD", "", "corticosteroids edema")
add("6.2", "qa_recommendation", "Is mannitol or hypertonic saline recommended for brain edema?", "2a", "C-LD", "", "mannitol hypertonic")
add("6.2", "qa_recommendation", "Does induced hypothermia help with brain swelling after stroke?", "3:No Benefit", "B-R", "", "hypothermia edema")

# ═══════════════════════════════════════════════════════════
# SECTION 6.3 — Supratentorial Surgical (4 recs)
# ═══════════════════════════════════════════════════════════
add("6.3", "qa_recommendation", "Is decompressive craniectomy recommended for malignant MCA infarction?", "1", "A", "", "decompressive craniectomy")
add("6.3", "qa_recommendation", "What is the recommendation for decompressive surgery in patients over 60?", "2b", "B-R", "", "craniectomy over 60")
add("6.3", "qa_recommendation", "Should decompressive craniectomy be performed within 48 hours?", "2a", "B-NR", "", "craniectomy timing")
add("6.3", "qa_recommendation", "What is the COR for decompressive hemicraniectomy in AIS?", "1", "A", "", "hemicraniectomy COR")

# ═══════════════════════════════════════════════════════════
# SECTION 6.4 — Cerebellar Surgical (2 recs)
# ═══════════════════════════════════════════════════════════
add("6.4", "qa_recommendation", "Should posterior fossa decompression be performed for cerebellar infarction with mass effect?", "1", "C-LD", "", "cerebellar decompression")
add("6.4", "qa_recommendation", "What is the recommendation for ventriculostomy in cerebellar stroke?", "1", "B-NR", "", "ventriculostomy")
add("6.4", "qa_recommendation", "Is suboccipital craniectomy recommended for cerebellar swelling?", "1", "C-LD", "", "suboccipital craniectomy")

# ═══════════════════════════════════════════════════════════
# SECTION 6.5 — Seizures (2 recs)
# ═══════════════════════════════════════════════════════════
add("6.5", "qa_recommendation", "Should clinical seizures be treated in acute stroke?", "1", "C-LD", "", "seizure treatment")
add("6.5", "qa_recommendation", "Is prophylactic antiseizure medication recommended after stroke?", "3:No Benefit", "C-LD", "", "prophylactic AED")
add("6.5", "qa_recommendation", "What does the guideline say about EEG monitoring after stroke?", "1", "C-LD", "", "EEG monitoring")

# ═══════════════════════════════════════════════════════════
# TABLE 8 — Contraindication Questions
# ═══════════════════════════════════════════════════════════

# Absolute contraindications
absolute_conditions = [
    ("intracranial hemorrhage on imaging", "intracranial hemorrhage"),
    ("active internal bleeding", "active internal bleeding"),
    ("intra-axial brain tumor", "intra-axial neoplasm"),
    ("infective endocarditis", "endocarditis"),
    ("severe coagulopathy", "coagulopathy"),
    ("aortic arch dissection", "aortic dissection"),
    ("blood glucose less than 50", "glucose <50"),
    ("extensive hypodensity on CT", "extensive hypodensity"),
    ("traumatic brain injury within 14 days", "TBI"),
    ("intracranial neurosurgery within 14 days", "neurosurgery"),
    ("spinal cord injury within 14 days", "spinal cord injury"),
    ("ARIA on recent MRI with amyloid immunotherapy", "ARIA"),
]

for cond, topic in absolute_conditions:
    add("Table8", "qa_table8",
        f"Is {cond} a contraindication to IVT per Table 8?",
        "", "", "Absolute", f"Table8 absolute {topic}")

# Relative contraindications
relative_conditions = [
    ("pregnancy", "pregnancy"),
    ("prior intracranial hemorrhage", "prior ICH"),
    ("DOAC within 48 hours", "recent DOAC"),
    ("active malignancy", "active cancer"),
    ("hepatic failure", "liver failure"),
    ("dialysis", "dialysis"),
    ("dementia", "dementia"),
    ("arterial dissection", "arterial dissection"),
    ("vascular malformation", "AVM"),
    ("pericarditis", "pericarditis"),
    ("dural puncture within 7 days", "dural puncture"),
    ("pre-existing disability", "prior disability"),
    ("pancreatitis", "pancreatitis"),
    ("cardiac thrombus", "cardiac thrombus"),
    ("recent non-CNS surgery", "non-CNS surgery"),
]

for cond, topic in relative_conditions:
    add("Table8", "qa_table8",
        f"How does Table 8 classify {cond} for IVT decision-making?",
        "", "", "Relative", f"Table8 relative {topic}")

# Benefit May Exceed Risk
benefit_conditions = [
    ("extracranial cervical dissection", "cervical dissection"),
    ("extra-axial intracranial neoplasm", "extra-axial neoplasm"),
    ("unruptured intracranial aneurysm", "unruptured aneurysm"),
    ("moyamoya disease", "moyamoya"),
    ("stroke mimic", "stroke mimic"),
    ("seizure at onset", "seizure at onset"),
    ("cerebral microbleeds", "microbleeds"),
    ("menstruation", "menstruation"),
    ("diabetic retinopathy", "retinopathy"),
    ("recreational drug use", "recreational drugs"),
    ("remote GI bleeding", "remote GI bleed"),
    ("history of myocardial infarction", "history MI"),
]

for cond, topic in benefit_conditions:
    add("Table8", "qa_table8",
        f"What tier does Table 8 assign to {cond} for IVT?",
        "", "", "Benefit May Exceed Risk", f"Table8 benefit {topic}")

# General/listing Table 8 questions
add("Table8", "qa_table8", "What are the absolute contraindications for IVT?", "", "", "", "Table8 listing absolute")
add("Table8", "qa_table8", "What are the relative contraindications for thrombolysis?", "", "", "", "Table8 listing relative")
add("Table8", "qa_table8", "List the benefit-may-exceed-risk conditions for IVT.", "", "", "", "Table8 listing benefit")
add("Table8", "qa_table8", "What conditions does Table 8 cover?", "", "", "", "Table8 listing general")
add("Table8", "qa_table8", "Show me the Table 8 contraindication categories.", "", "", "", "Table8 listing categories")

# Mixed/specific Table 8 questions
add("Table8", "qa_table8", "Is cocaine use an absolute or relative contraindication to IVT?", "", "", "Benefit May Exceed Risk", "Table8 cocaine tier")
add("Table8", "qa_table8", "Can IVT be given to a patient with moyamoya disease?", "", "", "Benefit May Exceed Risk", "Table8 moyamoya IVT")
add("Table8", "qa_table8", "Is pregnancy an absolute contraindication to thrombolysis?", "", "", "Relative", "Table8 pregnancy tier")
add("Table8", "qa_table8", "A patient has a known unruptured aneurysm. Is IVT contraindicated?", "", "", "Benefit May Exceed Risk", "Table8 aneurysm IVT")
add("Table8", "qa_table8", "Is IVT safe for a patient with cerebral microbleeds on MRI?", "", "", "Benefit May Exceed Risk", "Table8 microbleeds safe")
add("Table8", "qa_table8", "Can a patient on hemodialysis receive IVT?", "", "", "Relative", "Table8 dialysis IVT")
add("Table8", "qa_table8", "My patient has a history of prior ICH. What does Table 8 say about IVT eligibility?", "", "", "Relative", "Table8 prior ICH")
add("Table8", "qa_table8", "Is a patient with INR 2.0 eligible for thrombolysis?", "", "", "Absolute", "Table8 INR IVT")

# ═══════════════════════════════════════════════════════════
# EVIDENCE questions (qa_evidence)
# ═══════════════════════════════════════════════════════════
evidence_topics = [
    ("4.6.1", "What evidence supports IVT within 3 hours for AIS?", "IVT 3h evidence"),
    ("4.6.1", "What studies support IVT for patients over 80?", "IVT elderly evidence"),
    ("4.6.2", "What is the rationale behind the tenecteplase recommendation?", "TNK rationale"),
    ("4.6.3", "What data supports IVT in the extended time window?", "extended IVT evidence"),
    ("4.7.2", "What evidence supports EVT for anterior LVO?", "EVT LVO evidence"),
    ("4.7.2", "What trials support EVT in the 6-24 hour window?", "EVT late window evidence"),
    ("4.7.3", "What evidence supports EVT for basilar artery occlusion?", "EVT basilar evidence"),
    ("4.3", "What data supports BP targets after IVT?", "BP post-IVT evidence"),
    ("4.8", "What is the evidence for dual antiplatelet therapy in minor stroke?", "DAPT evidence"),
    ("4.4", "What studies support fever treatment in acute stroke?", "fever treatment evidence"),
    ("3.2", "What evidence supports perfusion imaging for EVT selection?", "perfusion imaging evidence"),
    ("5.4", "What is the rationale for DVT prophylaxis recommendations?", "DVT prophylaxis rationale"),
    ("6.3", "What evidence supports decompressive craniectomy?", "craniectomy evidence"),
    ("2.5", "What trials support mobile stroke unit deployment?", "MSU trial evidence"),
    ("5.7", "What evidence shows that very early mobilization is harmful?", "early mobilization harm evidence"),
]

for section, question, topic in evidence_topics:
    add(section, "qa_evidence", question, "", "", "", topic)

# ═══════════════════════════════════════════════════════════
# KNOWLEDGE GAP questions
# ═══════════════════════════════════════════════════════════
kg_topics = [
    ("2.1", "What are the knowledge gaps for stroke awareness?", "awareness KG"),
    ("4.6.1", "What future research is needed for IVT decision-making?", "IVT KG"),
    ("4.7.2", "What are the knowledge gaps for EVT in adults?", "EVT KG"),
    ("4.3", "What research gaps exist for BP management in AIS?", "BP KG"),
    ("4.8", "What are the unanswered questions about antiplatelet therapy in stroke?", "antiplatelet KG"),
    ("3.2", "What future research is needed for stroke imaging?", "imaging KG"),
    ("6.3", "What remains unclear about decompressive surgery for stroke?", "craniectomy KG"),
    ("5.7", "What are the knowledge gaps for stroke rehabilitation?", "rehab KG"),
    ("4.6.3", "What is unknown about extended window IVT?", "extended IVT KG"),
    ("4.7.3", "What future directions exist for posterior circulation EVT?", "posterior EVT KG"),
]

for section, question, topic in kg_topics:
    add(section, "qa_knowledge_gap", question, "", "", "", topic)

# ═══════════════════════════════════════════════════════════
# CLINICAL SCENARIO questions (conversational style)
# ═══════════════════════════════════════════════════════════
scenarios = [
    ("4.6.1", "A 72-year-old presents 2 hours after symptom onset with NIHSS 14. Should I give IVT?", "1", "A", "scenario IVT 72yo"),
    ("4.7.2", "65yo, NIHSS 18, M1 occlusion, LKW 2 hours ago. What does the guideline recommend?", "1", "A", "scenario EVT 65yo"),
    ("4.6.1", "Patient is 45 with NIHSS 4 and disabling symptoms at 3 hours. Is IVT indicated?", "1", "B-NR", "scenario IVT NIHSS4"),
    ("4.7.2", "My patient has ASPECTS 4, large core on CTP, and M1 occlusion at 5 hours. EVT?", "2a", "B-NR", "scenario EVT low ASPECTS"),
    ("4.3", "Patient received tPA 1 hour ago. What BP target should I maintain?", "1", "B-NR", "scenario BP post-tPA"),
    ("4.6.2", "Should I give tenecteplase or alteplase to my stroke patient?", "1", "A", "scenario TNK vs alteplase"),
    ("4.7.1", "My patient got IVT 30 minutes ago and has M1 occlusion. Should I proceed with EVT?", "1", "A", "scenario bridging"),
    ("4.8", "Minor stroke, NIHSS 3, no LVO. Should I start dual antiplatelet therapy?", "1", "A", "scenario DAPT minor"),
    ("4.6.1", "85-year-old with 4-hour-old stroke. Is there an age cutoff for IVT?", "1", "A", "scenario IVT 85yo"),
    ("4.7.2", "Wake-up stroke, DWI-FLAIR mismatch, M1 occlusion. Should I do EVT?", "1", "A", "scenario wake-up EVT"),
    ("4.6.3", "Patient with wake-up stroke and perfusion mismatch. Can I give IVT?", "2a", "B-R", "scenario wake-up IVT"),
    ("3.2", "Do I need CTA before giving tPA?", "1", "A", "scenario CTA before tPA"),
    ("4.1", "My stroke patient has O2 sat of 96%. Should I give supplemental oxygen?", "3:No Benefit", "B-R", "scenario O2 96%"),
    ("4.4", "My stroke patient has a temperature of 39°C. What should I do?", "1", "B-R", "scenario fever 39"),
    ("4.5", "Blood glucose is 250 in my stroke patient. How aggressively should I treat?", "2a", "C-LD", "scenario hyperglycemia"),
    ("6.3", "Large MCA infarction with midline shift in a 55-year-old. Should I consult neurosurgery for craniectomy?", "1", "A", "scenario craniectomy 55yo"),
    ("5.4", "How should I prevent DVT in my immobile stroke patient?", "1", "B-R", "scenario DVT immobile"),
    ("4.2", "Should I keep my stroke patient flat or elevate the head of bed?", "3:No Benefit", "B-R", "scenario head position"),
    ("4.7.3", "Patient with acute basilar artery occlusion. Is EVT recommended?", "1", "A", "scenario basilar EVT"),
    ("4.9", "Patient with AF and acute stroke. When should I start anticoagulation?", "2a", "A", "scenario AF anticoag"),
    ("4.6.1", "NIHSS 2, non-disabling symptoms. Should I give tPA?", "3:No Benefit", "B-R", "scenario mild non-disabling"),
    ("4.7.2", "Patient with M2 occlusion and NIHSS 10. Is EVT recommended?", "2a", "B-R", "scenario M2 EVT"),
    ("4.3", "BP is 200/110 and patient is EVT candidate. What should I do?", "1", "C-LD", "scenario BP high EVT"),
    ("5.2", "My stroke patient wants to eat. Should I do a swallowing screen first?", "1", "C-EO", "scenario dysphagia screen"),
    ("4.7.4", "Should I use a stent retriever or aspiration first for my EVT case?", "1", "A", "scenario EVT technique"),
    ("4.10", "Should I give IV fluids for hemodynamic augmentation in stroke?", "3:No Benefit", "A", "scenario volume expansion"),
    ("4.11", "Are there any neuroprotective drugs I should give for acute stroke?", "3:No Benefit", "A", "scenario neuroprotection"),
    ("4.12", "My patient has severe carotid stenosis with acute stroke. Should I do emergency CEA?", "3:No Benefit", "B-NR", "scenario emergency CEA"),
    ("5.5", "My stroke patient seems depressed 1 week after admission. Should I screen?", "1", "B-NR", "scenario depression screen"),
    ("6.4", "Cerebellar infarction with brainstem compression. Should I consult surgery?", "1", "C-LD", "scenario cerebellar surgery"),
    ("5.7", "When can my stroke patient start rehab?", "1", "A", "scenario rehab start"),
    ("6.5", "My stroke patient had a seizure. Should I start antiepileptic medication?", "1", "C-LD", "scenario seizure treatment"),
    ("6.5", "Should I give prophylactic antiseizure drugs to my stroke patient?", "3:No Benefit", "C-LD", "scenario prophylactic AED"),
    ("5.3", "My stroke patient cannot swallow. When should I start tube feeding?", "1", "B-NR", "scenario tube feeding"),
    ("6.2", "Large stroke with edema. Should I give mannitol?", "2a", "C-LD", "scenario mannitol edema"),
    ("6.2", "Should I give steroids for cerebral edema after stroke?", "3:Harm", "C-LD", "scenario steroids edema"),
    ("4.7.5", "12-year-old with acute M1 occlusion. Is EVT an option?", "2a", "B-NR", "scenario pediatric EVT"),
    ("2.5", "Should I deploy a mobile stroke unit for a suspected stroke call?", "1", "A", "scenario MSU deploy"),
    ("2.8", "No neurologist on site. Can I use telestroke to evaluate for IVT?", "1", "B-R", "scenario telestroke eval"),
    ("2.4", "Suspected LVO. Should EMS bypass the closest hospital for a thrombectomy center?", "2a", "B-NR", "scenario EMS bypass LVO"),
]

for section, question, cor, loe, topic in scenarios:
    add(section, "qa_recommendation", question, cor, loe, "", topic)

# ═══════════════════════════════════════════════════════════
# ADDITIONAL — fill to 500
# ═══════════════════════════════════════════════════════════

# More varied phrasing
extras = [
    ("4.6.1", "qa_recommendation", "What level of evidence supports IVT within 3 hours?", "1", "A", "", "IVT 3h LOE"),
    ("4.6.1", "qa_recommendation", "Does the guideline recommend against IVT for mild non-disabling stroke?", "3:No Benefit", "B-R", "", "IVT mild against"),
    ("4.7.2", "qa_recommendation", "What is the time window for EVT in anterior circulation?", "1", "A", "", "EVT time window anterior"),
    ("4.7.2", "qa_recommendation", "What NIHSS threshold is required for EVT eligibility?", "1", "A", "", "EVT NIHSS threshold"),
    ("4.3", "qa_recommendation", "What BP medications are recommended for acute stroke?", "2a", "B-NR", "", "BP medications AIS"),
    ("4.8", "qa_recommendation", "How long should DAPT be continued after minor stroke?", "1", "A", "", "DAPT duration minor"),
    ("4.8", "qa_recommendation", "What is the aspirin dose for acute ischemic stroke?", "1", "A", "", "aspirin dose AIS"),
    ("4.6.1", "qa_recommendation", "Is there a minimum NIHSS for IVT eligibility?", "1", "B-NR", "", "minimum NIHSS IVT"),
    ("4.7.2", "qa_recommendation", "Which vessels are included in the EVT recommendation?", "1", "A", "", "EVT vessels"),
    ("3.2", "qa_recommendation", "What is the recommendation for collateral imaging in EVT candidates?", "2b", "B-NR", "", "collateral imaging"),
    ("4.6.1", "qa_recommendation", "Can IVT be given to a patient already improving?", "1", "B-NR", "", "IVT improving patient"),
    ("4.7.4", "qa_recommendation", "What anesthesia should be used during EVT?", "1", "B-R", "", "EVT anesthesia"),
    ("4.9", "qa_recommendation", "Is warfarin recommended for AF-related stroke prevention?", "2a", "A", "", "warfarin AF"),
    ("5.4", "qa_recommendation", "Are graduated compression stockings harmful after stroke?", "3:Harm", "B-R", "", "compression stockings harm"),
    ("5.7", "qa_recommendation", "Is aggressive early mobilization within 24 hours recommended?", "3:Harm", "B-R", "", "aggressive early mobilization"),
    ("6.1", "qa_recommendation", "What monitoring is needed for large hemispheric infarctions?", "1", "C-EO", "", "large infarction monitoring"),
    ("6.3", "qa_recommendation", "At what age does craniectomy benefit decrease?", "2b", "B-R", "", "craniectomy age cutoff"),
    ("4.6.4", "qa_recommendation", "Is streptokinase harmful for acute stroke?", "3:Harm", "A", "", "streptokinase harmful"),
    ("4.3", "qa_recommendation", "Should SBP be kept below 220 if not receiving IVT or EVT?", "2b", "C-EO", "", "SBP 220 no treatment"),
    ("2.3", "qa_recommendation", "Is prehospital stroke assessment with a validated scale recommended?", "2a", "B-NR", "", "prehospital validated scale"),
    ("3.2", "qa_recommendation", "Should CT angiography be performed for all suspected stroke patients?", "1", "B-NR", "", "CTA all stroke"),
    ("4.7.2", "qa_recommendation", "Can EVT be performed without preceding IVT?", "1", "A", "", "EVT alone"),
    ("4.6.1", "qa_recommendation", "Is there an ASPECTS threshold for IVT eligibility?", "1", "A", "", "ASPECTS threshold IVT"),
    ("4.7.2", "qa_recommendation", "Should patients with large core infarcts be excluded from EVT?", "2a", "B-NR", "", "EVT large core"),
]

for item in extras:
    add(*item)

# Report
print(f"Generated {len(questions)} questions")
cats = {}
secs = {}
for q in questions:
    c = q["category"]
    cats[c] = cats.get(c, 0) + 1
    s = q["section"]
    secs[s] = secs.get(s, 0) + 1
print(f"Categories: {cats}")
print(f"Sections covered: {len(secs)}")
for s in sorted(secs.keys()):
    print(f"  {s}: {secs[s]}")

# Save
outpath = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"
with open(outpath, "w") as f:
    json.dump(questions, f, indent=2)
print(f"\nSaved to {outpath}")
