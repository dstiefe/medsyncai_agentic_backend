"""
Generate Round 6 (R6) test suite: 500 questions covering recommendations,
evidence/RSS, and knowledge gaps across all guideline sections.

Source of truth: guideline_knowledge.json + recommendations.json

Three question categories:
  - qa_recommendation: COR/LOE matching (existing harness logic)
  - qa_evidence: section routing + LLM extraction from RSS/synopsis
  - qa_knowledge_gap: section routing + deterministic or LLM extraction
"""
import json
import re
import random
from pathlib import Path

random.seed(42)

DATA_DIR = Path("app/agents/clinical/ais_clinical_engine/data")
OUT_DIR = Path("/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff")

with open(DATA_DIR / "recommendations.json") as f:
    recs_data = json.load(f)
with open(DATA_DIR / "guideline_knowledge.json") as f:
    gk_data = json.load(f)

RECS = recs_data["recommendations"]
SECTIONS = gk_data["sections"]

# ═══════════════════════════════════════════════════════════════════════
# SECTION TOPIC MAP — short clinical phrases for each section
# ═══════════════════════════════════════════════════════════════════════

SECTION_TOPICS = {
    "2.1": "stroke awareness and public education",
    "2.2": "EMS systems for stroke care",
    "2.3": "prehospital stroke assessment and triage",
    "2.4": "EMS destination and hospital bypass decisions",
    "2.5": "mobile stroke units",
    "2.6": "hospital stroke capabilities and certification",
    "2.7": "emergency evaluation of suspected stroke",
    "2.8": "telemedicine for stroke",
    "2.9": "stroke systems of care organization",
    "2.10": "stroke registries and quality improvement",
    "3.1": "stroke severity scales",
    "3.2": "imaging in acute ischemic stroke",
    "3.3": "other diagnostic tests for AIS",
    "4.1": "airway, breathing, and oxygenation in AIS",
    "4.2": "head positioning in AIS",
    "4.3": "blood pressure management in AIS",
    "4.4": "temperature management in AIS",
    "4.5": "blood glucose management in AIS",
    "4.6": "IV thrombolytics",
    "4.6.1": "IVT eligibility and decision-making",
    "4.6.2": "choice of thrombolytic agent",
    "4.6.3": "extended time window for IVT",
    "4.6.4": "other IV fibrinolytics and sonothrombolysis",
    "4.6.5": "IVT in other specific circumstances",
    "4.7.1": "EVT concomitant with IVT",
    "4.7.2": "endovascular thrombectomy for adults",
    "4.7.3": "posterior circulation stroke and EVT",
    "4.7.4": "endovascular techniques",
    "4.7.5": "endovascular thrombectomy in pediatric patients",
    "4.8": "antiplatelet treatment in AIS",
    "4.9": "anticoagulants in AIS",
    "4.10": "hemodilution, vasodilators, and hemodynamic augmentation",
    "4.11": "neuroprotective agents",
    "4.12": "emergency carotid endarterectomy and stenting",
    "5.1": "stroke units",
    "5.2": "dysphagia screening and management",
    "5.3": "nutrition after stroke",
    "5.4": "DVT prophylaxis after stroke",
    "5.5": "depression screening after stroke",
    "5.6": "other in-hospital management considerations",
    "5.7": "rehabilitation after stroke",
    "6.1": "brain swelling after stroke",
    "6.2": "medical management of brain swelling",
    "6.3": "surgical management of supratentorial infarction",
    "6.4": "surgical management of cerebellar infarction",
    "6.5": "seizures after stroke",
}

# ═══════════════════════════════════════════════════════════════════════
# HAND-CRAFTED RECOMMENDATION QUESTIONS
# Each entry: (section, recNumber, question, expected_cor, expected_loe)
# ═══════════════════════════════════════════════════════════════════════

# These are clinician-style questions that map to specific recommendations.
# We generate ~250 recommendation questions covering all 45 sections.

REC_QUESTIONS_MANUAL = [
    # ── 2.1 Stroke Awareness ──
    ("2.1", "1", "Should educational programs on stroke recognition be implemented for the general public?", "1", "B-R"),
    ("2.1", "2", "Should stroke education programs be designed to reach diverse communities?", "1", "B-NR"),
    ("2.1", "3", "Should stroke recognition educational programs be sustained over time?", "1", "B-NR"),
    ("2.1", "4", "Should EMS professionals receive targeted stroke education programs?", "1", "B-NR"),

    # ── 2.2 EMS Systems ──
    ("2.2", "1", "Should regional systems of stroke care be established to increase access to time-sensitive therapies?", "1", "B-NR"),
    ("2.2", "2", "Is monitoring quality metrics for prehospital stroke care useful?", "2a", "B-NR"),
    ("2.2", "3", "Should EMS leaders develop stroke treatment protocols in collaboration with local experts?", "1", "B-NR"),

    # ── 2.3 Prehospital Assessment ──
    ("2.3", "1", "Should standardized stroke screening tools be used by EMS in the field?", "1", "A"),
    ("2.3", "2", "Should prehospital notification be given to the receiving hospital for suspected stroke?", "1", "B-NR"),
    ("2.3", "3", "Is prehospital blood glucose measurement recommended for suspected stroke patients?", "1", "B-NR"),
    ("2.3", "4", "Is prehospital IV access recommended for patients with suspected stroke?", "1", "B-NR"),
    ("2.3", "5", "Should supplemental oxygen be provided to non-hypoxic stroke patients in the prehospital setting?", "3:No Benefit", "B-NR"),
    ("2.3", "6", "Is prehospital use of a large vessel occlusion screening tool recommended?", "2a", "B-NR"),
    ("2.3", "7", "Are prehospital stroke screening tools validated for pediatric patients?", "2b", "B-NR"),

    # ── 2.4 EMS Destination ──
    ("2.4", "1", "Should suspected stroke patients be transported to the closest stroke-capable hospital?", "1", "B-NR"),
    ("2.4", "2", "When should suspected LVO stroke patients bypass a primary stroke center for a comprehensive center?", "2a", "B-NR"),
    ("2.4", "3", "Is direct transport to a thrombectomy-capable center beneficial for suspected LVO patients?", "2b", "B-NR"),
    ("2.4", "4", "Should interhospital transfer processes be established for patients needing higher-level stroke care?", "1", "B-NR"),
    ("2.4", "5", "Is air medical transport useful for transferring stroke patients for thrombectomy?", "2b", "B-R"),

    # ── 2.5 Mobile Stroke Units ──
    ("2.5", "1", "Are mobile stroke units effective for reducing time to IVT?", "1", "A"),
    ("2.5", "2", "Can mobile stroke units reduce time to thrombectomy decisions?", "2a", "B-NR"),
    ("2.5", "3", "Do mobile stroke units improve functional outcomes compared to standard EMS?", "2a", "B-R"),
    ("2.5", "4", "Should mobile stroke units be considered in communities with limited stroke center access?", "1", "B-NR"),

    # ── 2.6 Hospital Stroke Capabilities ──
    ("2.6", "1", "Should hospitals treating stroke patients have organized stroke care protocols?", "1", "B-NR"),

    # ── 2.7 Emergency Evaluation ──
    ("2.7", "1", "Should a targeted history and physical exam be performed rapidly for suspected stroke?", "1", "B-NR"),
    ("2.7", "2", "Should NIHSS or similar validated scale be used to assess stroke severity?", "1", "B-NR"),
    ("2.7", "3", "What is the recommendation for achieving a door-to-needle time under 60 minutes?", "1", "B-NR"),
    ("2.7", "4", "Should a stroke team be activated for rapid evaluation of suspected stroke patients?", "1", "A"),
    ("2.7", "5", "Is a door-to-imaging time of under 20 minutes recommended for suspected stroke?", "1", "C-EO"),

    # ── 2.8 Telemedicine ──
    ("2.8", "1", "Is telestroke recommended for hospitals without on-site stroke expertise?", "1", "B-R"),
    ("2.8", "2", "Can telemedicine be used to support IVT decision-making in remote hospitals?", "1", "B-NR"),
    ("2.8", "3", "Is telemedicine useful for evaluating patients for thrombectomy transfer?", "2a", "B-NR"),
    ("2.8", "4", "Should video-capable telemedicine be used rather than telephone-only consultation?", "1", "B-NR"),
    ("2.8", "5", "Can mobile telemedicine be used in the prehospital setting for stroke triage?", "2b", "C-LD"),
    ("2.8", "6", "Is telemedicine-guided IVT as effective as bedside physician-guided IVT?", "1", "B-R"),
    ("2.8", "7", "Can telestroke be used to determine the appropriateness of interhospital transfer for EVT?", "2a", "C-EO"),

    # ── 2.9 Organization and Integration ──
    ("2.9", "1", "Should stroke center certification be pursued to improve outcomes?", "1", "B-NR"),
    ("2.9", "2", "Is participation in quality improvement programs recommended for stroke centers?", "1", "B-NR"),
    ("2.9", "3", "Should systems of care be developed to link prehospital, hospital, and post-acute stroke care?", "1", "B-NR"),
    ("2.9", "4", "Is standardized data collection recommended for stroke performance measurement?", "1", "B-NR"),
    ("2.9", "5", "Should transfer agreements be established between primary and comprehensive stroke centers?", "1", "B-NR"),
    ("2.9", "6", "Is multidisciplinary team coordination recommended for stroke systems of care?", "2a", "B-NR"),
    ("2.9", "7", "Should stroke systems track and report treatment metrics?", "2a", "B-NR"),
    ("2.9", "8", "Is concurrent quality improvement and systems redesign useful for improving stroke outcomes?", "2b", "B-R"),

    # ── 2.10 Registries ──
    ("2.10", "1", "Should hospitals participate in stroke registries?", "1", "B-NR"),
    ("2.10", "2", "Is risk-standardized mortality useful as a hospital quality metric for stroke?", "1", "B-R"),
    ("2.10", "3", "Should stroke quality improvement data be publicly reported?", "1", "B-NR"),

    # ── 3.1 Stroke Scales ──
    ("3.1", "1", "Should a validated stroke severity scale like the NIHSS be used for all AIS patients?", "1", "B-NR"),

    # ── 3.2 Imaging ──
    ("3.2", "1", "Is emergent brain imaging with CT or MRI required before IVT administration?", "1", "A"),
    ("3.2", "2", "Should CTA be performed to evaluate for LVO in potential thrombectomy candidates?", "1", "A"),
    ("3.2", "3", "Is CTP or MR perfusion recommended for selecting patients in the extended time window?", "1", "A"),
    ("3.2", "4", "Should imaging be obtained as quickly as possible without delaying IVT?", "1", "B-NR"),
    ("3.2", "5", "Is multiphase CTA useful for evaluating collateral circulation?", "2a", "B-NR"),
    ("3.2", "6", "Can MRI with DWI be used as an alternative to CT for initial stroke imaging?", "2a", "B-NR"),
    ("3.2", "7", "Is CT perfusion necessary before IVT in the standard time window (under 4.5 hours)?", "3:No Benefit", "B-R"),
    ("3.2", "8", "Should vascular imaging be performed to identify intracranial arterial occlusion?", "1", "A"),
    ("3.2", "9", "Is noninvasive cervical vascular imaging recommended for AIS patients?", "1", "B-NR"),
    ("3.2", "10", "Is ASPECTS scoring useful for assessing early ischemic changes on CT?", "2b", "B-NR"),
    ("3.2", "11", "Should CTP be obtained before EVT in the standard window (under 6 hours)?", "2b", "C-LD"),

    # ── 3.3 Other Diagnostic Tests ──
    ("3.3", "1", "Should baseline blood glucose be checked before administering IVT?", "1", "B-NR"),
    ("3.3", "2", "Is routine lab testing required before IVT if there is no clinical suspicion of coagulopathy?", "1", "C-LD"),

    # ── 4.1 Airway/Breathing/Oxygenation ──
    ("4.1", "1", "Should airway support be provided for stroke patients with decreased consciousness?", "1", "C-LD"),
    ("4.1", "2", "Is supplemental oxygen recommended for non-hypoxic AIS patients?", "3:No Benefit", "B-R"),
    ("4.1", "3", "Should oxygen saturation be maintained above 94% in AIS patients?", "1", "C-LD"),
    ("4.1", "4", "Is hyperbaric oxygen therapy recommended for AIS?", "3:No Benefit", "B-R"),
    ("4.1", "5", "Should intubation be considered for AIS patients who cannot protect their airway?", "1", "C-LD"),
    ("4.1", "6", "Is high-flow nasal cannula oxygen beneficial in non-hypoxic stroke patients?", "2b", "B-R"),

    # ── 4.2 Head Positioning ──
    ("4.2", "1", "Is flat head positioning (0 degrees) beneficial compared to elevated positioning in AIS?", "3:No Benefit", "B-R"),
    ("4.2", "2", "Does lying flat improve outcomes in acute ischemic stroke?", "3:No Benefit", "B-R"),

    # ── 4.3 Blood Pressure Management ──
    ("4.3", "1", "Should blood pressure be lowered below 185/110 before IVT administration?", "1", "B-NR"),
    ("4.3", "2", "Should BP be maintained below 180/105 for the first 24 hours after IVT?", "1", "B-NR"),
    ("4.3", "3", "Is aggressive BP lowering to less than 140 mmHg systolic safe in AIS patients who received IVT?", "3:Harm", "B-R"),
    ("4.3", "4", "Should hypertension be treated in AIS patients NOT receiving reperfusion therapy?", "2b", "C-LD"),
    ("4.3", "5", "Is permissive hypertension (up to 220/120) acceptable in patients not receiving IVT or EVT?", "1", "C-EO"),
    ("4.3", "6", "What is the BP target during and after endovascular thrombectomy?", "2a", "B-NR"),
    ("4.3", "7", "Should IV labetalol or nicardipine be used for BP management before IVT?", "1", "B-NR"),
    ("4.3", "8", "Is BP reduction below 140/90 within the first 24-48 hours recommended for patients with acute hypertensive response?", "2b", "B-NR"),
    ("4.3", "9", "Should BP be aggressively lowered during EVT?", "3:No Benefit", "B-R"),
    ("4.3", "10", "Is IV antihypertensive therapy recommended for BP above 220/120 in patients not treated with IVT?", "2a", "C-EO"),

    # ── 4.4 Temperature Management ──
    ("4.4", "1", "Should hyperthermia be treated in AIS patients?", "1", "C-EO"),
    ("4.4", "2", "Is therapeutic hypothermia recommended for AIS patients?", "3:No Benefit", "B-R"),
    ("4.4", "3", "Should fever sources be identified and treated in AIS patients?", "1", "C-EO"),

    # ── 4.5 Blood Glucose ──
    ("4.5", "1", "Should hypoglycemia be treated in AIS patients?", "1", "C-LD"),
    ("4.5", "2", "Is intensive insulin therapy to achieve tight glycemic control recommended in AIS?", "3:No Benefit", "A"),
    ("4.5", "3", "Should hyperglycemia be treated to maintain glucose between 140-180 mg/dL in AIS?", "2a", "C-LD"),

    # ── 4.6.1 IVT Decision-Making ──
    ("4.6.1", "1", "Is IVT recommended within 3 hours of symptom onset for eligible patients with disabling deficits?", "1", "A"),
    ("4.6.1", "2", "Is IVT recommended within 3 to 4.5 hours from symptom onset?", "1", "B-R"),
    ("4.6.1", "3", "Should IVT be given as early as possible within the treatment window?", "1", "A"),
    ("4.6.1", "4", "Can IVT be given based on NCCT alone without waiting for lab results in patients without suspected coagulopathy?", "1", "B-NR"),
    ("4.6.1", "5", "Is IVT recommended for patients with mild but disabling symptoms?", "1", "B-NR"),
    ("4.6.1", "6", "Should the decision to administer IVT be delayed for advanced imaging like CTP?", "1", "C-EO"),
    ("4.6.1", "7", "Is IVT safe for patients with cerebral microbleeds on MRI?", "2a", "B-NR"),
    ("4.6.1", "8", "Is IVT recommended for patients with non-disabling mild stroke symptoms (NIHSS 0-5)?", "3:No Benefit", "B-R"),
    ("4.6.1", "9", "Should IVT be administered to patients who are already on antiplatelet therapy?", "2a", "B-NR"),
    ("4.6.1", "10", "Is IVT recommended for patients with an unknown number of cerebral microbleeds who have not had MRI?", "2b", "C-LD"),
    ("4.6.1", "11", "Is IVT safe for patients with a high burden of cerebral microbleeds (more than 10)?", "2b", "B-NR"),
    ("4.6.1", "12", "Is IVT beneficial for patients with both disabling and non-disabling symptoms when NIHSS is 0 to 5?", "3:No Benefit", "B-R"),
    ("4.6.1", "13", "Should IVT be withheld in patients with glucose less than 50 mg/dL?", "1", "C-EO"),
    ("4.6.1", "14", "Should hypoglycemia or hyperglycemia be corrected before deciding on IVT?", "1", "C-EO"),

    # ── 4.6.2 Choice of Thrombolytic ──
    ("4.6.2", "1", "Is alteplase recommended as a thrombolytic for AIS?", "1", "A"),
    ("4.6.2", "2", "Is tenecteplase an acceptable alternative to alteplase for AIS?", "1", "A"),

    # ── 4.6.3 Extended Window IVT ──
    ("4.6.3", "1", "Is IVT reasonable for selected patients in the 4.5 to 9 hour window with perfusion mismatch?", "2a", "B-R"),
    ("4.6.3", "2", "Can IVT be considered for wake-up stroke patients with DWI-FLAIR mismatch?", "2a", "B-R"),
    ("4.6.3", "3", "Is IVT in the extended window (beyond 4.5h) beneficial for unselected patients without imaging selection?", "2b", "B-R"),

    # ── 4.6.4 Other Fibrinolytics ──
    ("4.6.4", "1", "Is sonothrombolysis recommended as an adjunct to IVT?", "3:No Benefit", "B-R"),
    ("4.6.4", "2", "Are defibrinogenating agents like ancrod recommended for AIS?", "3:Harm", "B-R"),
    ("4.6.4", "3", "Is IV streptokinase recommended for AIS?", "3:Harm", "A"),
    ("4.6.4", "4", "Is IV desmoteplase recommended for AIS?", "3:No Benefit", "B-R"),
    ("4.6.4", "5", "Is tirofiban a recommended alternative to IVT for AIS?", "2b", "B-R"),
    ("4.6.4", "6", "Is urokinase recommended as an IV thrombolytic for AIS?", "3:No Benefit", "B-R"),
    ("4.6.4", "7", "Is reteplase recommended for AIS treatment?", "3:No Benefit", "B-R"),

    # ── 4.6.5 Other Specific Circumstances ──
    ("4.6.5", "1", "Is IVT reasonable for patients with sickle cell disease presenting with AIS?", "2a", "B-NR"),
    ("4.6.5", "2", "Can IVT be considered for patients who had a stroke during cardiac catheterization?", "2b", "C-LD"),

    # ── 4.7.1 EVT Concomitant With IVT ──
    ("4.7.1", "1", "Should EVT-eligible patients also receive IVT before thrombectomy?", "1", "A"),
    ("4.7.1", "2", "Should IVT be given even if the patient will be transferred for EVT?", "1", "A"),

    # ── 4.7.2 EVT for Adults ──
    ("4.7.2", "1", "Is EVT recommended for patients with ICA or M1 occlusion within 6 hours?", "1", "A"),
    ("4.7.2", "2", "Should EVT be performed within 6 hours for eligible LVO patients?", "1", "A"),
    ("4.7.2", "3", "Is EVT recommended for patients with LVO and low NIHSS (less than 6)?", "2b", "B-R"),
    ("4.7.2", "4", "Can EVT be performed in the extended window (6-24 hours) with favorable perfusion imaging?", "1", "A"),
    ("4.7.2", "5", "Is EVT beneficial for patients with ASPECTS less than 6?", "2a", "B-R"),
    ("4.7.2", "6", "Is EVT reasonable for patients with pre-stroke mRS of 2 or higher?", "2b", "B-NR"),
    ("4.7.2", "7", "Is EVT recommended for dominant proximal M2 occlusion within 6 hours?", "2a", "B-NR"),
    ("4.7.2", "8", "Is EVT recommended for non-dominant M2 occlusion?", "3:No Benefit", "B-R"),

    # ── 4.7.3 Posterior Circulation ──
    ("4.7.3", "1", "Is EVT recommended for basilar artery occlusion?", "1", "A"),
    ("4.7.3", "2", "Can EVT be considered for posterior circulation LVO in the extended window?", "2b", "B-R"),

    # ── 4.7.4 Endovascular Techniques ──
    ("4.7.4", "1", "Is stent retriever thrombectomy recommended for anterior circulation LVO?", "1", "A"),
    ("4.7.4", "2", "Is aspiration thrombectomy recommended for anterior circulation LVO?", "1", "A"),
    ("4.7.4", "3", "Should conscious sedation be preferred over general anesthesia during EVT?", "2b", "B-R"),
    ("4.7.4", "4", "Is a door-to-groin puncture time of under 90 minutes recommended?", "1", "B-NR"),
    ("4.7.4", "5", "Should complete reperfusion (TICI 2b/3) be the goal of EVT?", "1", "A"),
    ("4.7.4", "6", "Is intracranial angioplasty or stenting recommended as first-line EVT?", "3:No Benefit", "B-R"),
    ("4.7.4", "7", "Should rescue therapy be considered if initial EVT pass is unsuccessful?", "1", "B-NR"),
    ("4.7.4", "8", "Is cervical carotid stenting during EVT for tandem occlusion reasonable?", "2b", "B-NR"),
    ("4.7.4", "9", "Should IV glycoprotein IIb/IIIa inhibitors be used routinely during EVT?", "3:No Benefit", "B-R"),

    # ── 4.7.5 Pediatric EVT ──
    ("4.7.5", "1", "Can EVT be considered for children with AIS and LVO?", "2b", "B-NR"),
    ("4.7.5", "2", "Is EVT reasonable for adolescents with LVO stroke?", "2a", "B-NR"),
    ("4.7.5", "3", "Should pediatric EVT be performed at centers with pediatric stroke expertise?", "2a", "B-NR"),

    # ── 4.8 Antiplatelet Treatment ──
    ("4.8", "1", "Is aspirin recommended within 24-48 hours of AIS onset?", "1", "A"),
    ("4.8", "2", "Should aspirin be delayed for 24 hours after IVT?", "1", "A"),
    ("4.8", "3", "Is dual antiplatelet therapy (DAPT) with aspirin and clopidogrel recommended for minor stroke?", "1", "A"),
    ("4.8", "4", "Should DAPT be continued for 21 days after minor stroke or TIA?", "1", "A"),
    ("4.8", "5", "Is ticagrelor and aspirin recommended over aspirin alone for minor stroke?", "2a", "B-R"),
    ("4.8", "6", "Should DAPT be started within 24 hours for minor stroke (NIHSS under 5)?", "1", "A"),
    ("4.8", "7", "Is long-term DAPT (beyond 21 days) recommended for secondary stroke prevention?", "3:Harm", "A"),
    ("4.8", "8", "Should aspirin be given before IVT?", "3:No Benefit", "C-EO"),
    ("4.8", "9", "Is clopidogrel plus aspirin recommended within 24 hours for patients who received IVT?", "2b", "B-R"),
    ("4.8", "10", "Is tirofiban an alternative to aspirin for acute antiplatelet therapy in AIS?", "2b", "B-R"),
    ("4.8", "11", "Is IV cangrelor recommended for AIS patients who cannot take oral antiplatelet agents?", "2b", "B-NR"),
    ("4.8", "12", "Should cilostazol be used for antiplatelet therapy in AIS?", "2b", "B-R"),
    ("4.8", "13", "Is triple antiplatelet therapy recommended for AIS?", "3:Harm", "B-R"),
    ("4.8", "14", "Should antiplatelet therapy be adjusted based on platelet function testing?", "3:No Benefit", "B-R"),
    ("4.8", "15", "Is GP IIb/IIIa inhibitor monotherapy recommended for AIS?", "3:No Benefit", "B-R"),
    ("4.8", "16", "Should clopidogrel loading dose be given before CYP2C19 genotype is known?", "1", "B-NR"),
    ("4.8", "17", "Is CYP2C19 genotype-guided antiplatelet selection recommended for minor stroke?", "2a", "B-R"),
    ("4.8", "18", "Should DAPT be started early after minor stroke for patients with intracranial atherosclerosis?", "1", "A"),

    # ── 4.9 Anticoagulants ──
    ("4.9", "1", "Should urgent anticoagulation be started within 24 hours of AIS to prevent early recurrence?", "3:No Benefit", "A"),
    ("4.9", "2", "Is urgent heparin anticoagulation recommended for AIS patients?", "3:No Benefit", "A"),
    ("4.9", "3", "Is low-molecular-weight heparin recommended for acute treatment of AIS?", "3:No Benefit", "A"),
    ("4.9", "4", "Is argatroban recommended for acute AIS treatment?", "3:No Benefit", "B-NR"),
    ("4.9", "5", "Can early anticoagulation be considered for stroke patients with mechanical heart valves?", "2b", "C-LD"),
    ("4.9", "6", "Is early therapeutic anticoagulation reasonable for patients with extracranial cervical dissection?", "2a", "B-NR"),

    # ── 4.10 Hemodilution/Vasodilators ──
    ("4.10", "1", "Is hemodilution with volume expansion recommended for AIS?", "3:No Benefit", "A"),
    ("4.10", "2", "Are vasodilators recommended for AIS treatment?", "3:No Benefit", "B-R"),

    # ── 4.11 Neuroprotective Agents ──
    ("4.11", "1", "Are neuroprotective agents recommended for AIS treatment?", "3:No Benefit", "A"),

    # ── 4.12 Emergency CEA/CAS ──
    ("4.12", "1", "Is emergency carotid endarterectomy or stenting recommended for acute stroke patients?", "3:No Benefit", "B-NR"),

    # ── 5.1 Stroke Units ──
    ("5.1", "1", "Should AIS patients be admitted to a dedicated stroke unit?", "1", "B-R"),

    # ── 5.2 Dysphagia ──
    ("5.2", "1", "Should dysphagia screening be performed before oral intake in AIS patients?", "1", "B-NR"),
    ("5.2", "2", "Is a formal swallowing evaluation recommended if the initial screen suggests dysphagia?", "1", "B-NR"),
    ("5.2", "3", "Should enteral tube feeding be started early for patients who cannot safely swallow?", "2a", "C-LD"),
    ("5.2", "4", "Is PEG tube placement recommended within the first 7 days for stroke patients with dysphagia?", "2b", "C-EO"),
    ("5.2", "5", "Should oral hygiene protocols be implemented for stroke patients?", "1", "B-NR"),
    ("5.2", "6", "Is behavioral swallowing therapy recommended for stroke patients with dysphagia?", "2a", "B-R"),

    # ── 5.3 Nutrition ──
    ("5.3", "1", "Should nutritional status be assessed in AIS patients?", "1", "B-NR"),
    ("5.3", "2", "Is early enteral nutrition recommended for malnourished stroke patients?", "1", "B-R"),
    ("5.3", "3", "Are routine nutritional supplements recommended for all AIS patients?", "2a", "B-R"),

    # ── 5.4 DVT Prophylaxis ──
    ("5.4", "1", "Should immobile stroke patients receive DVT prophylaxis?", "1", "A"),
    ("5.4", "2", "Is intermittent pneumatic compression recommended for DVT prevention in immobile AIS patients?", "1", "B-R"),
    ("5.4", "3", "Is subcutaneous heparin or LMWH recommended for DVT prophylaxis in AIS?", "2a", "A"),
    ("5.4", "4", "Are elastic compression stockings recommended for DVT prevention in AIS?", "3:Harm", "A"),
    ("5.4", "5", "Should early mobilization be used for DVT prevention in stroke patients?", "2b", "B-R"),

    # ── 5.5 Depression ──
    ("5.5", "1", "Should AIS patients be screened for depression?", "1", "B-NR"),
    ("5.5", "2", "Is antidepressant treatment recommended for post-stroke depression?", "1", "B-R"),

    # ── 5.6 Other In-Hospital ──
    ("5.6", "1", "Is routine use of fluoxetine for stroke recovery recommended?", "3:No Benefit", "A"),
    ("5.6", "2", "Should indwelling urinary catheters be avoided in AIS patients when possible?", "2a", "C-LD"),
    ("5.6", "3", "Is routine use of corticosteroids recommended for AIS?", "3:Harm", "C-EO"),

    # ── 5.7 Rehabilitation ──
    ("5.7", "1", "Should early rehabilitation be initiated for AIS patients?", "1", "A"),
    ("5.7", "2", "Is very early high-intensity mobilization (within 24 hours) recommended?", "3:Harm", "B-R"),
    ("5.7", "3", "Should a formal rehabilitation assessment be performed before hospital discharge?", "1", "B-R"),

    # ── 6.1 Brain Swelling ──
    ("6.1", "1", "Should patients at risk for brain swelling be monitored closely?", "1", "C-EO"),
    ("6.1", "2", "Should patients with large territorial infarction be identified early for possible decompressive surgery?", "1", "C-LD"),
    ("6.1", "3", "Is early transfer to a neurosurgical center recommended for patients at risk of malignant edema?", "1", "C-LD"),

    # ── 6.2 Medical Management of Brain Swelling ──
    ("6.2", "1", "Is osmotic therapy reasonable for patients with clinical deterioration from brain swelling?", "2a", "C-LD"),
    ("6.2", "2", "Are corticosteroids recommended for managing cerebral edema after stroke?", "3:Harm", "B-R"),
    ("6.2", "3", "Is therapeutic hypothermia recommended for brain swelling after ischemic stroke?", "3:No Benefit", "B-R"),

    # ── 6.3 Supratentorial Surgical Management ──
    ("6.3", "1", "Is decompressive craniectomy recommended for malignant MCA infarction in patients under 60?", "1", "A"),
    ("6.3", "2", "Can decompressive craniectomy be considered for malignant MCA infarction in patients 60 or older?", "2a", "B-R"),
    ("6.3", "3", "Should decompressive craniectomy be performed within 48 hours of symptom onset?", "1", "A"),
    ("6.3", "4", "Is decompressive craniectomy reasonable for patients with additional ipsilateral infarction beyond MCA territory?", "2b", "B-NR"),

    # ── 6.4 Cerebellar Surgical Management ──
    ("6.4", "1", "Should suboccipital decompressive craniectomy be performed for cerebellar infarction with brainstem compression?", "1", "B-NR"),
    ("6.4", "2", "Is ventriculostomy recommended for hydrocephalus from cerebellar infarction?", "1", "C-LD"),

    # ── 6.5 Seizures ──
    ("6.5", "1", "Should clinical seizures after AIS be treated with antiseizure medications?", "1", "C-LD"),
    ("6.5", "2", "Is prophylactic use of antiseizure medications recommended for AIS patients without seizures?", "3:No Benefit", "C-LD"),

    # ── ALTERNATE PHRASINGS (clinical scenario style) ──

    # 4.6.1 IVT — scenario-based
    ("4.6.1", "1", "A 68-year-old with NIHSS 14 and disabling right hemiparesis presents 2 hours after symptom onset. Is IVT recommended?", "1", "A"),
    ("4.6.1", "8", "A patient presents with mild symptoms (NIHSS 3) that are not disabling. Is IVT indicated?", "3:No Benefit", "B-R"),
    ("4.6.1", "2", "A 72-year-old presents 4 hours after symptom onset with disabling deficits. Is IVT still recommended?", "1", "B-R"),
    ("4.6.1", "7", "A patient with 5 cerebral microbleeds on MRI presents within 3 hours. Is IVT safe?", "2a", "B-NR"),
    ("4.6.1", "3", "Should IVT be given immediately or can it wait for CTA results?", "1", "A"),
    ("4.6.1", "9", "Can a patient on aspirin receive IVT for acute stroke?", "2a", "B-NR"),

    # 4.7.2 EVT — scenario-based
    ("4.7.2", "1", "A 55-year-old with M1 occlusion, NIHSS 16, and ASPECTS 8 presents 3 hours after onset. Is EVT indicated?", "1", "A"),
    ("4.7.2", "4", "A patient presents 18 hours after LKW with LVO and favorable perfusion imaging. Is EVT reasonable?", "1", "A"),
    ("4.7.2", "3", "A patient with ICA occlusion and NIHSS 4 presents within 6 hours. Should EVT be performed?", "2b", "B-R"),
    ("4.7.2", "5", "A patient with ASPECTS 4 and M1 occlusion presents within 6 hours. Is EVT reasonable?", "2a", "B-R"),
    ("4.7.2", "8", "A patient has a non-dominant M2 occlusion. Is EVT indicated?", "3:No Benefit", "B-R"),

    # 4.3 BP — scenario-based
    ("4.3", "1", "A patient with BP 200/115 is being considered for IVT. Should BP be lowered first?", "1", "B-NR"),
    ("4.3", "5", "A patient with BP 195/108 did not receive IVT or EVT. Should the BP be treated?", "1", "C-EO"),
    ("4.3", "3", "Should BP be lowered to 130 mmHg systolic after IVT?", "3:Harm", "B-R"),

    # 3.2 Imaging — scenario-based
    ("3.2", "1", "Does a patient need any imaging before IVT can be given?", "1", "A"),
    ("3.2", "7", "Is CT perfusion required before giving IVT within 3 hours of onset?", "3:No Benefit", "B-R"),
    ("3.2", "2", "Should CTA be obtained for a patient with suspected LVO before EVT?", "1", "A"),

    # 4.8 Antiplatelet — scenario-based
    ("4.8", "1", "Should aspirin be started immediately after AIS onset?", "1", "A"),
    ("4.8", "2", "A patient received IVT 6 hours ago. Can aspirin be started now?", "1", "A"),
    ("4.8", "3", "Should dual antiplatelet therapy be started for a patient with minor stroke (NIHSS 3)?", "1", "A"),
    ("4.8", "7", "Is it safe to continue DAPT for 90 days after minor stroke?", "3:Harm", "A"),

    # 5.4 DVT — scenario-based
    ("5.4", "1", "An immobile stroke patient is on bedrest. Should DVT prophylaxis be started?", "1", "A"),
    ("5.4", "4", "Should compression stockings be used for DVT prevention after stroke?", "3:Harm", "A"),

    # 6.3 Decompressive craniectomy — scenario-based
    ("6.3", "1", "A 50-year-old with malignant MCA infarction is deteriorating. Is decompressive craniectomy recommended?", "1", "A"),
    ("6.3", "2", "A 65-year-old has malignant MCA edema. Can decompressive craniectomy still be considered?", "2a", "B-R"),

    # 4.4 Temperature
    ("4.4", "2", "Should induced hypothermia be used to protect the brain after AIS?", "3:No Benefit", "B-R"),

    # 4.9 Anticoagulants
    ("4.9", "1", "Should heparin be started immediately after AIS to prevent early recurrence?", "3:No Benefit", "A"),

    # 5.7 Rehabilitation
    ("5.7", "2", "Should a stroke patient be mobilized aggressively within the first 24 hours?", "3:Harm", "B-R"),
    ("5.7", "1", "When should rehabilitation be started after acute ischemic stroke?", "1", "A"),

    # 4.7.1 EVT + IVT
    ("4.7.1", "1", "A patient qualifies for both IVT and EVT. Should IVT be given first or skipped in favor of EVT?", "1", "A"),

    # 2.5 MSU
    ("2.5", "1", "Do mobile stroke units reduce the time from symptom onset to IVT?", "1", "A"),

    # 4.1 Airway
    ("4.1", "2", "Should all stroke patients receive supplemental oxygen?", "3:No Benefit", "B-R"),

    # 6.2 Brain swelling medical
    ("6.2", "2", "Should steroids be given for brain swelling after large ischemic stroke?", "3:Harm", "B-R"),

    # 4.6.2 Thrombolytic choice
    ("4.6.2", "2", "Is tenecteplase as effective as alteplase for AIS?", "1", "A"),

    # 4.5 Glucose
    ("4.5", "2", "Should strict blood sugar control with an insulin drip be used after stroke?", "3:No Benefit", "A"),

    # 4.11 Neuroprotective
    ("4.11", "1", "Are there any neuroprotective medications recommended for acute stroke treatment?", "3:No Benefit", "A"),

    # 4.2 Head positioning
    ("4.2", "1", "Should the head of bed be kept flat for stroke patients?", "3:No Benefit", "B-R"),

    # 5.2 Dysphagia
    ("5.2", "1", "Should a swallow screen be done before giving a stroke patient food or water?", "1", "B-NR"),

    # 5.1 Stroke units
    ("5.1", "1", "Should stroke patients be admitted to a general medical floor or a stroke unit?", "1", "B-R"),

    # 5.5 Depression
    ("5.5", "1", "Should stroke patients be screened for depression before discharge?", "1", "B-NR"),

    # 2.7 Emergency eval
    ("2.7", "4", "Should a stroke team be activated immediately when a stroke is suspected?", "1", "A"),

    # Additional scenario-based questions
    ("4.6.4", "3", "Is streptokinase an acceptable thrombolytic for acute ischemic stroke?", "3:Harm", "A"),
    ("4.7.3", "1", "A patient has a basilar artery occlusion confirmed on CTA. Is EVT recommended?", "1", "A"),
    ("4.9", "6", "Is early anticoagulation reasonable for a patient with AIS from cervical artery dissection?", "2a", "B-NR"),
    ("5.3", "2", "Should enteral nutrition be started early for a malnourished stroke patient?", "1", "B-R"),
    ("6.1", "2", "Should patients with large hemisphere infarcts be identified early for potential decompressive surgery?", "1", "C-LD"),
    ("6.4", "1", "A patient with cerebellar infarction has brainstem compression. Is decompressive surgery indicated?", "1", "B-NR"),
    ("4.6.3", "1", "Can IVT be given to a patient 7 hours after onset who has perfusion mismatch on CTP?", "2a", "B-R"),
]

# ═══════════════════════════════════════════════════════════════════════
# EVIDENCE QUESTIONS — hand-crafted per section
# ═══════════════════════════════════════════════════════════════════════

EVIDENCE_QUESTIONS = [
    # ── 2.1 Stroke Awareness ──
    ("2.1", "What evidence supports public educational programs for stroke recognition?"),
    ("2.1", "What studies demonstrate that stroke education reduces delays to hospital arrival?"),
    ("2.1", "What is the rationale for culturally tailored stroke awareness programs?"),
    ("2.1", "What evidence shows that stroke awareness declines over time after educational interventions?"),
    ("2.1", "Why does the guideline recommend sustained stroke education programs?"),

    # ── 2.2 EMS Systems ──
    ("2.2", "What evidence supports regional systems of stroke care?"),
    ("2.2", "What data supports monitoring prehospital quality metrics for stroke?"),
    ("2.2", "What is the rationale for EMS-developed stroke treatment protocols?"),

    # ── 2.3 Prehospital Assessment ──
    ("2.3", "What evidence supports prehospital stroke screening tools?"),
    ("2.3", "What data supports prehospital hospital notification for stroke patients?"),
    ("2.3", "Why does the guideline recommend LVO screening tools in the prehospital setting?"),
    ("2.3", "What is the rationale against supplemental oxygen in non-hypoxic prehospital stroke patients?"),
    ("2.3", "What evidence supports prehospital blood glucose measurement for suspected stroke?"),

    # ── 2.4 EMS Destination ──
    ("2.4", "What evidence supports bypassing primary stroke centers for suspected LVO patients?"),
    ("2.4", "What data supports interhospital transfer systems for stroke care?"),
    ("2.4", "What is the rationale for transporting stroke patients to the closest stroke-capable hospital?"),

    # ── 2.5 Mobile Stroke Units ──
    ("2.5", "What evidence shows that mobile stroke units reduce time to treatment?"),
    ("2.5", "What trials support functional outcome improvements with mobile stroke units?"),
    ("2.5", "What is the rationale for mobile stroke units in underserved communities?"),

    # ── 2.6 Hospital Stroke Capabilities ──
    ("2.6", "What evidence supports organized stroke care protocols in hospitals?"),
    ("2.6", "What data supports stroke center certification for improving outcomes?"),

    # ── 2.7 Emergency Evaluation ──
    ("2.7", "What evidence supports rapid evaluation of suspected stroke patients?"),
    ("2.7", "What data supports the door-to-needle time target of under 60 minutes?"),

    # ── 2.8 Telemedicine ──
    ("2.8", "What evidence supports telestroke for IVT decision-making?"),
    ("2.8", "What data shows that telemedicine-guided IVT is as effective as bedside physician-guided IVT?"),
    ("2.8", "What studies support video-based telemedicine over telephone-only consultation for stroke?"),
    ("2.8", "What is the rationale for using telemedicine to evaluate EVT transfer candidates?"),

    # ── 2.9 Organization and Integration ──
    ("2.9", "What evidence supports stroke center certification?"),
    ("2.9", "What data supports quality improvement programs for stroke care?"),
    ("2.9", "What is the rationale for linking prehospital, hospital, and post-acute stroke care systems?"),

    # ── 2.10 Registries ──
    ("2.10", "What evidence supports participation in stroke registries?"),
    ("2.10", "What data supports public reporting of stroke quality metrics?"),

    # ── 3.1 Stroke Scales ──
    ("3.1", "What evidence supports using the NIHSS for AIS severity assessment?"),
    ("3.1", "What data shows that validated stroke scales improve clinical decision-making?"),

    # ── 3.2 Imaging ──
    ("3.2", "What evidence supports CTA for detecting large vessel occlusion?"),
    ("3.2", "What data supports CT perfusion for extended window patient selection?"),
    ("3.2", "Why is CT perfusion not needed before IVT in the standard time window?"),
    ("3.2", "What evidence supports NCCT as sufficient for IVT decisions?"),
    ("3.2", "What is the rationale for ASPECTS scoring in early ischemic change assessment?"),

    # ── 3.3 Other Diagnostic Tests ──
    ("3.3", "What evidence supports checking baseline blood glucose before IVT?"),
    ("3.3", "Why does the guideline say routine lab testing should not delay IVT?"),
    ("3.3", "What data supports the recommendation that coagulation testing is not needed before IVT without suspected coagulopathy?"),

    # ── 4.1 Airway/Breathing ──
    ("4.1", "What evidence shows supplemental oxygen is not beneficial in non-hypoxic stroke patients?"),
    ("4.1", "What data supports maintaining oxygen saturation above 94% in AIS?"),
    ("4.1", "What is the rationale against hyperbaric oxygen for AIS?"),

    # ── 4.2 Head Positioning ──
    ("4.2", "What evidence shows that flat head positioning does not improve outcomes in AIS?"),
    ("4.2", "What trial data supports the recommendation against lying flat for stroke patients?"),

    # ── 4.3 Blood Pressure ──
    ("4.3", "What evidence supports the 185/110 BP threshold before IVT?"),
    ("4.3", "What data shows that aggressive BP lowering below 140 mmHg is harmful after IVT?"),
    ("4.3", "What is the rationale for permissive hypertension in patients not receiving reperfusion therapy?"),
    ("4.3", "What evidence supports the BP target during endovascular thrombectomy?"),
    ("4.3", "What studies inform the recommendation against aggressive BP reduction during EVT?"),
    ("4.3", "What data supports using labetalol or nicardipine for BP management before IVT?"),

    # ── 4.4 Temperature ──
    ("4.4", "What evidence supports treating hyperthermia in AIS patients?"),
    ("4.4", "What data shows that therapeutic hypothermia is not beneficial for AIS?"),
    ("4.4", "What is the rationale for identifying fever sources in stroke patients?"),
    ("4.4", "What studies inform the recommendation against prophylactic hypothermia in AIS?"),

    # ── 4.5 Blood Glucose ──
    ("4.5", "What evidence supports correcting hypoglycemia in AIS patients?"),
    ("4.5", "What data shows that tight glycemic control with insulin is not beneficial in AIS?"),
    ("4.5", "What is the rationale for the 140-180 mg/dL glucose target in AIS?"),
    ("4.5", "What studies inform the recommendation against intensive insulin therapy after stroke?"),

    # ── 4.6 IV Thrombolytics ──
    ("4.6", "What evidence supports the use of IV thrombolytics for AIS?"),
    ("4.6", "What is the rationale for time-sensitive IVT administration?"),

    # ── 4.6.1 IVT Decision-Making ──
    ("4.6.1", "What evidence supports IVT within 3 hours for disabling stroke?"),
    ("4.6.1", "What data supports extending the IVT window to 4.5 hours?"),
    ("4.6.1", "What is the rationale for not delaying IVT for advanced imaging?"),
    ("4.6.1", "What evidence supports IVT safety in patients with cerebral microbleeds?"),
    ("4.6.1", "Why is IVT not recommended for non-disabling mild stroke (NIHSS 0-5)?"),
    ("4.6.1", "What data supports giving IVT without waiting for coagulation results?"),

    # ── 4.6.3 Extended Window IVT ──
    ("4.6.3", "What evidence supports IVT in the 4.5-9 hour window with perfusion mismatch?"),
    ("4.6.3", "What studies support IVT for wake-up stroke with DWI-FLAIR mismatch?"),
    ("4.6.3", "What is the rationale for imaging selection in extended window IVT?"),

    # ── 4.6.4 Other Fibrinolytics ──
    ("4.6.4", "What evidence shows that sonothrombolysis is not beneficial as an adjunct to IVT?"),
    ("4.6.4", "Why are defibrinogenating agents harmful in AIS treatment?"),
    ("4.6.4", "What data supports the recommendation against streptokinase for AIS?"),

    # ── 4.6.5 Other Circumstances ──
    ("4.6.5", "What evidence supports IVT for patients with sickle cell disease and AIS?"),
    ("4.6.5", "What data supports IVT for procedural stroke during cardiac catheterization?"),

    # ── 4.7.1 EVT Concomitant With IVT ──
    ("4.7.1", "What evidence supports giving IVT before EVT rather than EVT alone?"),
    ("4.7.1", "What data shows that IVT should not be skipped even when EVT is planned?"),

    # ── 4.7.2 EVT for Adults ──
    ("4.7.2", "What evidence supports EVT for ICA and M1 occlusion within 6 hours?"),
    ("4.7.2", "What data supports EVT in the extended window (6-24 hours)?"),
    ("4.7.2", "What is the rationale for EVT in patients with low ASPECTS scores?"),
    ("4.7.2", "Why is EVT not recommended for non-dominant M2 occlusion?"),

    # ── 4.7.3 Posterior Circulation ──
    ("4.7.3", "What evidence supports EVT for basilar artery occlusion?"),
    ("4.7.3", "What data supports EVT for posterior circulation stroke in the extended window?"),

    # ── 4.7.4 Endovascular Techniques ──
    ("4.7.4", "What evidence supports stent retriever thrombectomy?"),
    ("4.7.4", "What data supports aspiration thrombectomy as an alternative to stent retrievers?"),
    ("4.7.4", "What is the rationale for the door-to-groin puncture time target?"),
    ("4.7.4", "What evidence supports conscious sedation over general anesthesia during EVT?"),
    ("4.7.4", "What data supports rescue therapy after failed initial EVT pass?"),

    # ── 4.7.5 Pediatric EVT ──
    ("4.7.5", "What evidence supports EVT for children with AIS and LVO?"),
    ("4.7.5", "What data supports performing pediatric EVT at specialized centers?"),

    # ── 4.8 Antiplatelet Treatment ──
    ("4.8", "What evidence supports early aspirin within 24-48 hours of AIS?"),
    ("4.8", "What data supports dual antiplatelet therapy for minor stroke?"),
    ("4.8", "What is the rationale for limiting DAPT to 21 days?"),
    ("4.8", "What evidence supports CYP2C19 genotype-guided antiplatelet selection?"),
    ("4.8", "Why is long-term DAPT beyond 21 days considered harmful?"),

    # ── 4.9 Anticoagulants ──
    ("4.9", "What evidence shows that urgent anticoagulation does not prevent early stroke recurrence?"),
    ("4.9", "What is the rationale for early anticoagulation in cervical dissection?"),
    ("4.9", "What data supports against heparin for acute AIS treatment?"),

    # ── 4.10 Hemodilution ──
    ("4.10", "What evidence shows that hemodilution is not beneficial for AIS?"),
    ("4.10", "What data supports against vasodilator use in AIS?"),

    # ── 4.11 Neuroprotective Agents ──
    ("4.11", "What evidence shows that neuroprotective agents are not beneficial for AIS?"),
    ("4.11", "What trials have tested neuroprotective strategies in AIS?"),

    # ── 4.12 Emergency CEA/CAS ──
    ("4.12", "What evidence supports against emergency carotid endarterectomy in acute stroke?"),
    ("4.12", "What data informs the recommendation against urgent carotid stenting in AIS?"),

    # ── 5.1 Stroke Units ──
    ("5.1", "What evidence supports admission to dedicated stroke units?"),

    # ── 5.2 Dysphagia ──
    ("5.2", "What evidence supports early dysphagia screening in AIS patients?"),
    ("5.2", "What data supports formal swallowing evaluation after positive dysphagia screen?"),
    ("5.2", "What is the rationale for oral hygiene protocols in stroke patients?"),

    # ── 5.3 Nutrition ──
    ("5.3", "What evidence supports nutritional assessment in AIS patients?"),
    ("5.3", "What data supports early enteral nutrition for malnourished stroke patients?"),

    # ── 5.4 DVT Prophylaxis ──
    ("5.4", "What evidence supports intermittent pneumatic compression for DVT prevention in AIS?"),
    ("5.4", "What data shows that elastic compression stockings are harmful after stroke?"),
    ("5.4", "What is the rationale for subcutaneous heparin for DVT prophylaxis in AIS?"),

    # ── 5.5 Depression ──
    ("5.5", "What evidence supports screening for depression after stroke?"),
    ("5.5", "What data supports antidepressant treatment for post-stroke depression?"),

    # ── 5.6 Other In-Hospital ──
    ("5.6", "What evidence shows that routine fluoxetine does not improve stroke recovery?"),
    ("5.6", "What data supports avoiding indwelling urinary catheters in AIS patients?"),

    # ── 5.7 Rehabilitation ──
    ("5.7", "What evidence supports early rehabilitation after AIS?"),
    ("5.7", "What data shows that very early high-intensity mobilization is harmful?"),
    ("5.7", "What is the rationale for formal rehabilitation assessment before discharge?"),

    # ── 6.1 Brain Swelling ──
    ("6.1", "What evidence supports early identification of patients at risk for malignant edema?"),
    ("6.1", "What data supports early transfer to neurosurgical centers for brain swelling risk?"),
    ("6.1", "What is the rationale for close monitoring of patients with large territorial infarction?"),

    # ── 6.2 Medical Management of Brain Swelling ──
    ("6.2", "What evidence supports osmotic therapy for brain swelling after stroke?"),
    ("6.2", "What data shows that corticosteroids are harmful for cerebral edema after stroke?"),

    # ── 6.3 Supratentorial Surgical Management ──
    ("6.3", "What evidence supports decompressive craniectomy for malignant MCA infarction?"),
    ("6.3", "What data supports the 48-hour time window for decompressive craniectomy?"),
    ("6.3", "What is the rationale for decompressive craniectomy in patients 60 or older?"),

    # ── 6.4 Cerebellar Surgical Management ──
    ("6.4", "What evidence supports suboccipital decompressive craniectomy for cerebellar infarction?"),
    ("6.4", "What data supports ventriculostomy for hydrocephalus from cerebellar infarction?"),

    # ── 6.5 Seizures ──
    ("6.5", "What evidence supports treating clinical seizures after AIS?"),
    ("6.5", "What data shows that prophylactic antiseizure medications are not recommended after AIS?"),

    # ── ADDITIONAL EVIDENCE QUESTIONS — deeper clinical detail ──

    # 2.1 More detail
    ("2.1", "What is the evidence that stroke awareness programs reduce prehospital delays?"),

    # 2.3 LVO screening tools
    ("2.3", "What studies have validated large vessel occlusion screening tools in the prehospital setting?"),
    ("2.3", "What is the evidence basis for prehospital IV access in suspected stroke?"),

    # 2.4 Transport decisions
    ("2.4", "What evidence supports air transport for interhospital stroke transfers?"),
    ("2.4", "What data supports the benefit of bypassing closer hospitals for thrombectomy-capable centers?"),

    # 2.5 MSU functional outcomes
    ("2.5", "What trial data demonstrates improved functional outcomes with mobile stroke units?"),
    ("2.5", "What is the evidence that MSUs reduce disability after stroke?"),

    # 2.8 Telestroke evidence
    ("2.8", "What studies compare outcomes of telemedicine-guided versus bedside IVT administration?"),
    ("2.8", "What evidence supports mobile telemedicine in the prehospital setting?"),

    # 2.9 Quality improvement
    ("2.9", "What data supports the relationship between stroke center certification and patient outcomes?"),
    ("2.9", "What evidence supports multidisciplinary team coordination for stroke systems?"),

    # 3.2 More imaging detail
    ("3.2", "What evidence supports DWI-MRI as an alternative to CT for initial stroke imaging?"),
    ("3.2", "What data supports multiphase CTA for assessing collateral circulation?"),
    ("3.2", "What studies inform the recommendation for noninvasive cervical vascular imaging in AIS?"),

    # 4.1 Oxygenation
    ("4.1", "What trials have tested supplemental oxygen in non-hypoxic stroke patients?"),
    ("4.1", "What is the evidence basis for maintaining SpO2 above 94% in AIS?"),

    # 4.3 BP management depth
    ("4.3", "What trials inform the 180/105 BP target after IVT?"),
    ("4.3", "What evidence supports IV nicardipine for BP management in acute stroke?"),

    # 4.4 Temperature depth
    ("4.4", "What trials have tested therapeutic hypothermia in AIS patients?"),

    # 4.5 Glucose depth
    ("4.5", "What studies tested intensive insulin therapy in AIS patients?"),

    # 4.6.1 IVT depth
    ("4.6.1", "What is the evidence for IVT benefit in patients already taking antiplatelet agents?"),
    ("4.6.1", "What data supports the safety of IVT with high cerebral microbleed burden?"),
    ("4.6.1", "What studies inform the recommendation to correct glucose before IVT?"),

    # 4.6.3 Extended window depth
    ("4.6.3", "What specific trials support IVT in the extended time window?"),

    # 4.6.4 Other fibrinolytics depth
    ("4.6.4", "What evidence exists for tirofiban as an alternative to IVT?"),
    ("4.6.4", "What trials have tested desmoteplase for AIS?"),

    # 4.7.2 EVT depth
    ("4.7.2", "What data supports EVT benefit in patients with low NIHSS scores?"),
    ("4.7.2", "What evidence supports EVT for patients with pre-stroke disability?"),
    ("4.7.2", "What trials inform the recommendation for dominant M2 EVT?"),

    # 4.7.3 Posterior circulation
    ("4.7.3", "What specific trials support EVT for basilar artery occlusion?"),

    # 4.7.4 Techniques depth
    ("4.7.4", "What evidence compares stent retriever and aspiration thrombectomy outcomes?"),
    ("4.7.4", "What data supports the 90-minute door-to-groin puncture target?"),
    ("4.7.4", "What evidence supports cervical stenting during EVT for tandem occlusions?"),

    # 4.7.5 Pediatric
    ("4.7.5", "What case series support EVT in pediatric AIS patients?"),

    # 4.8 Antiplatelet depth
    ("4.8", "What trials support the 21-day DAPT duration for minor stroke?"),
    ("4.8", "What evidence supports ticagrelor plus aspirin for minor stroke?"),
    ("4.8", "What data shows harm from long-term dual antiplatelet therapy?"),

    # 4.9 Anticoagulant depth
    ("4.9", "What trials tested urgent heparin anticoagulation for AIS?"),
    ("4.9", "What evidence supports anticoagulation for extracranial cervical dissection?"),

    # 5.2 Dysphagia depth
    ("5.2", "What studies support behavioral swallowing therapy for post-stroke dysphagia?"),
    ("5.2", "What evidence supports oral hygiene protocols for reducing aspiration pneumonia?"),

    # 5.3 Nutrition depth
    ("5.3", "What evidence supports routine nutritional supplements for AIS patients?"),

    # 5.4 DVT depth
    ("5.4", "What trials tested elastic compression stockings for DVT prevention after stroke?"),
    ("5.4", "What data supports early mobilization for DVT prevention?"),

    # 5.5 Depression depth
    ("5.5", "What evidence supports SSRIs for post-stroke depression treatment?"),

    # 5.6 Other management depth
    ("5.6", "What trials tested fluoxetine for motor recovery after stroke?"),
    ("5.6", "What is the evidence basis for avoiding indwelling urinary catheters after stroke?"),

    # 5.7 Rehab depth
    ("5.7", "What trial data shows harm from very early aggressive mobilization?"),

    # 6.1 Brain swelling depth
    ("6.1", "What data supports early identification criteria for malignant cerebral edema?"),

    # 6.2 Medical management depth
    ("6.2", "What trials tested osmotic therapy for stroke-related brain swelling?"),

    # 6.3 Surgery depth
    ("6.3", "What trials support decompressive craniectomy for malignant MCA infarction in older patients?"),
    ("6.3", "What is the evidence basis for the 48-hour surgical window for decompressive craniectomy?"),

    # 6.4 Cerebellar depth
    ("6.4", "What data supports decompressive surgery for cerebellar stroke with mass effect?"),

    # Cross-section clinical questions
    ("4.6.1", "What evidence supports that IVT should not be delayed for laboratory results?"),
    ("4.7.1", "What trials tested EVT alone versus EVT plus IVT?"),
    ("3.2", "What is the evidence basis for using ASPECTS in EVT patient selection?"),
    ("4.8", "What is the rationale for CYP2C19 genotype testing before antiplatelet therapy?"),
    ("4.3", "What evidence supports permissive hypertension in non-reperfused AIS patients?"),

    # Additional evidence to reach 200
    ("2.1", "What is the rationale for targeting stroke education at EMS professionals?"),
    ("2.6", "What evidence supports dedicated stroke care protocol implementation at hospitals?"),
    ("3.1", "What is the rationale for using a standardized stroke scale in all AIS patients?"),
    ("4.12", "What is the evidence basis against emergency carotid intervention in acute stroke?"),
    ("5.1", "What evidence supports better outcomes with dedicated stroke unit care?"),
    ("5.5", "What studies support screening for post-stroke depression?"),
    ("4.10", "What trials tested hemodilution for acute ischemic stroke?"),
    ("4.11", "What specific neuroprotective agents have been tested in AIS trials?"),
]

# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE GAP QUESTIONS
# ═══════════════════════════════════════════════════════════════════════

# Section 2.1 — has actual knowledge gap content
KG_QUESTIONS_WITH_CONTENT = [
    ("2.1", "What are the knowledge gaps for stroke awareness programs?"),
    ("2.1", "What future research is needed regarding stroke education?"),
    ("2.1", "What remains unclear about stroke awareness interventions?"),
    ("2.1", "What areas need further study in public stroke education?"),
    ("2.1", "What are the unanswered questions about stroke preparedness?"),
    ("2.1", "What research gaps exist for stroke recognition programs in diverse communities?"),
    ("2.1", "What is unknown about the long-term retention of stroke awareness education?"),
    ("2.1", "What future research is needed on culturally tailored stroke awareness?"),
    ("2.1", "What knowledge gaps exist about stroke education for minority populations?"),
    ("2.1", "What research is needed on the optimal timing of repeat stroke education?"),
    ("2.1", "What gaps exist in evidence for stroke awareness across different age groups?"),
    ("2.1", "What future directions are identified for stroke preparedness research?"),
    ("2.1", "What remains unclear about the effectiveness of stroke education on EMS utilization?"),
    ("2.1", "What are the research gaps for school-based stroke education programs?"),
    ("2.1", "What further study is needed on inequities in stroke awareness by race and ethnicity?"),
]

# Sections WITHOUT knowledge gap content — test deterministic "no gaps" response
KG_SECTIONS_NO_CONTENT = [
    ("2.2", "EMS systems"),
    ("2.3", "prehospital stroke assessment"),
    ("2.4", "EMS destination management"),
    ("2.5", "mobile stroke units"),
    ("2.6", "hospital stroke capabilities"),
    ("2.7", "emergency evaluation of suspected stroke"),
    ("2.8", "telemedicine for stroke"),
    ("2.9", "stroke systems of care organization"),
    ("2.10", "stroke registries and quality improvement"),
    ("3.1", "stroke severity scales"),
    ("3.2", "imaging in acute ischemic stroke"),
    ("3.3", "other diagnostic tests for AIS"),
    ("4.1", "airway and oxygenation in AIS"),
    ("4.3", "blood pressure management in AIS"),
    ("4.4", "temperature management in AIS"),
    ("4.5", "blood glucose management in AIS"),
    ("4.6.1", "IVT eligibility and decision-making"),
    ("4.6.3", "extended time window for IVT"),
    ("4.6.4", "other IV fibrinolytics"),
    ("4.7.2", "endovascular thrombectomy for adults"),
    ("4.7.4", "endovascular techniques"),
    ("4.7.5", "pediatric EVT"),
    ("4.8", "antiplatelet treatment in AIS"),
    ("4.9", "anticoagulants in AIS"),
    ("4.10", "hemodilution and vasodilators"),
    ("4.11", "neuroprotective agents"),
    ("5.2", "dysphagia after stroke"),
    ("5.3", "nutrition after stroke"),
    ("5.4", "DVT prophylaxis after stroke"),
    ("5.7", "rehabilitation after stroke"),
    ("6.1", "brain swelling after stroke"),
    ("6.2", "medical management of brain swelling"),
    ("6.3", "surgical management of supratentorial infarction"),
    ("6.4", "surgical management of cerebellar infarction"),
    ("6.5", "seizures after stroke"),
]

KG_NO_CONTENT_TEMPLATES = [
    "What are the knowledge gaps for {topic}?",
    "What future research is needed for {topic}?",
    "Are there any research gaps identified for {topic}?",
    "What is unknown about {topic} per the guideline?",
]

# ═══════════════════════════════════════════════════════════════════════
# ASSEMBLE THE SUITE
# ═══════════════════════════════════════════════════════════════════════

questions = []
qid = 5000

# 1. Recommendation questions
for section, rec_num, question_text, expected_cor, expected_loe in REC_QUESTIONS_MANUAL:
    qid += 1
    sec_data = SECTIONS.get(section, {})
    title = sec_data.get("sectionTitle", SECTION_TOPICS.get(section, section))
    questions.append({
        "id": f"QA-{qid}",
        "section": section,
        "category": "qa_recommendation",
        "question": question_text,
        "expected_cor": expected_cor,
        "expected_loe": expected_loe,
        "expected_tier": "",
        "topic": SECTION_TOPICS.get(section, title),
    })

print(f"Recommendation questions: {len(REC_QUESTIONS_MANUAL)}")

# 2. Evidence questions
for section, question_text in EVIDENCE_QUESTIONS:
    qid += 1
    sec_data = SECTIONS.get(section, {})
    title = sec_data.get("sectionTitle", SECTION_TOPICS.get(section, section))
    # Extract expected keywords from RSS
    rss_entries = sec_data.get("rss", [])
    all_rss_text = " ".join(r.get("text", "") for r in rss_entries)
    trial_names = re.findall(r'\b([A-Z]{3,}(?:-[A-Z0-9]+)?)\b', all_rss_text)
    trial_names = list(set(t for t in trial_names if len(t) >= 4 and t not in {
        "AND", "THE", "FOR", "NOT", "COR", "LOE", "RCT", "IVT", "EVT", "EMS",
        "AIS", "THAT", "WITH", "FROM", "THIS", "ALSO", "WERE", "HAVE", "BEEN",
        "SUCH", "BOTH", "MORE", "THAN", "THESE", "THOSE", "AFTER", "BASED",
    }))[:5]
    questions.append({
        "id": f"QA-{qid}",
        "section": section,
        "category": "qa_evidence",
        "question": question_text,
        "expected_section": section,
        "expected_type": "evidence",
        "expected_keywords": trial_names,
        "topic": SECTION_TOPICS.get(section, title),
    })

print(f"Evidence questions: {len(EVIDENCE_QUESTIONS)}")

# 3. Knowledge gap questions — with content (section 2.1)
for section, question_text in KG_QUESTIONS_WITH_CONTENT:
    qid += 1
    questions.append({
        "id": f"QA-{qid}",
        "section": section,
        "category": "qa_knowledge_gap",
        "question": question_text,
        "expected_section": section,
        "expected_type": "knowledge_gap",
        "has_content": True,
        "topic": "stroke awareness knowledge gaps",
    })

# 4. Knowledge gap questions — no content (deterministic "no gaps" response)
for section, topic in KG_SECTIONS_NO_CONTENT:
    qid += 1
    template = KG_NO_CONTENT_TEMPLATES[qid % len(KG_NO_CONTENT_TEMPLATES)]
    question_text = template.format(topic=topic)
    questions.append({
        "id": f"QA-{qid}",
        "section": section,
        "category": "qa_knowledge_gap",
        "question": question_text,
        "expected_section": section,
        "expected_type": "knowledge_gap",
        "has_content": False,
        "topic": f"{SECTION_TOPICS.get(section, section)} (no gaps documented)",
    })

kg_count = len(KG_QUESTIONS_WITH_CONTENT) + len(KG_SECTIONS_NO_CONTENT)
print(f"Knowledge gap questions: {kg_count}")
print(f"\nTotal questions: {len(questions)}")

# Re-number sequentially
for i, q in enumerate(questions):
    q["id"] = f"QA-{5001 + i}"

# Build metadata
suite = {
    "_meta": {
        "name": "R6 - Comprehensive Ask MedSync Test Suite",
        "version": "r6",
        "total_questions": len(questions),
        "categories": {
            "qa_recommendation": len([q for q in questions if q["category"] == "qa_recommendation"]),
            "qa_evidence": len([q for q in questions if q["category"] == "qa_evidence"]),
            "qa_knowledge_gap": len([q for q in questions if q["category"] == "qa_knowledge_gap"]),
        },
        "source": "2026 AHA/ASA AIS Guidelines",
        "generated": "2026-04-02",
    },
    "questions": questions,
}

out_path = OUT_DIR / "qa_round6_test_suite.json"
with open(out_path, "w") as f:
    json.dump(suite, f, indent=2)

print(f"\nWritten to: {out_path}")

# Distribution summary
print("\n=== DISTRIBUTION BY SECTION ===")
by_section: dict = {}
for q in questions:
    sec = q["section"]
    by_section.setdefault(sec, {"rec": 0, "ev": 0, "kg": 0})
    if q["category"] == "qa_recommendation":
        by_section[sec]["rec"] += 1
    elif q["category"] == "qa_evidence":
        by_section[sec]["ev"] += 1
    elif q["category"] == "qa_knowledge_gap":
        by_section[sec]["kg"] += 1

for sec in sorted(by_section.keys()):
    d = by_section[sec]
    total = d["rec"] + d["ev"] + d["kg"]
    print(f"  {sec:8s} | Rec:{d['rec']:3d} Ev:{d['ev']:3d} KG:{d['kg']:3d} | Total:{total:3d}")
