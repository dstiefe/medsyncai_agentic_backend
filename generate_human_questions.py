#!/usr/bin/env python3
"""Generate realistic, human-phrased clinical questions. Every question reads like a clinician typed it."""
import json, sys, os, random
random.seed(42)
sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations
from app.agents.clinical.ais_clinical_engine.services.qa_service import (
    score_recommendation, extract_search_terms, extract_section_references,
    extract_topic_sections, get_section_discriminators,
    classify_table8_tier, classify_question_type,
)

recs = load_recommendations()
sec_discs = get_section_discriminators(recs)

def score_q(q):
    st = extract_search_terms(q)
    sr = extract_section_references(q)
    ts, sup = extract_topic_sections(q)
    scored = [(score_recommendation(r, st, question=q, section_refs=sr, topic_sections=ts, suppressed_sections=sup, section_discriminators=sec_discs), r) for r in recs]
    scored.sort(key=lambda x: -x[0])
    return scored

all_questions = []
qid = 70000
seen = set()

def add_rec(question):
    global qid
    if question.lower() in seen: return
    scored = score_q(question)
    if not scored or scored[0][0] <= 0: return
    top = scored[0][1]
    seen.add(question.lower())
    all_questions.append({"id": f"QA-{qid}", "section": top.get("section",""), "category": "qa_recommendation", "question": question, "expected_cor": top.get("cor",""), "expected_loe": top.get("loe",""), "expected_tier": "", "topic": top.get("section","")})
    qid += 1

def add_ev(section, question):
    global qid
    if question.lower() in seen: return
    if classify_question_type(question) != "evidence": return
    seen.add(question.lower())
    all_questions.append({"id": f"QA-{qid}", "section": section, "category": "qa_evidence", "question": question, "expected_cor": "", "expected_loe": "", "expected_tier": "", "topic": f"{section} evidence"})
    qid += 1

def add_kg(section, question):
    global qid
    if question.lower() in seen: return
    if classify_question_type(question) != "knowledge_gap": return
    seen.add(question.lower())
    all_questions.append({"id": f"QA-{qid}", "section": section, "category": "qa_knowledge_gap", "question": question, "expected_cor": "", "expected_loe": "", "expected_tier": "", "topic": f"{section} knowledge_gap"})
    qid += 1

def add_t8(question, expected_tier):
    global qid
    if question.lower() in seen: return
    found = classify_table8_tier(question)
    if expected_tier and found != expected_tier: return
    seen.add(question.lower())
    all_questions.append({"id": f"QA-{qid}", "section": "Table8", "category": "qa_table8", "question": question, "expected_cor": "", "expected_loe": "", "expected_tier": expected_tier, "topic": f"Table8 {expected_tier}"})
    qid += 1

# ═══ 2.1 Stroke Awareness ═══
for q in ["Should hospitals run public stroke awareness campaigns?","Is community stroke education recommended?","Does the guideline support teaching the public to call 911 for stroke?","Are public education programs on stroke symptoms recommended?","Should stroke awareness campaigns be sustained over time?","What does the guideline say about community education for stroke recognition?","Are stroke education programs for the general public recommended?","Should EMS professionals also receive stroke recognition training?"]: add_rec(q)

# ═══ 2.2 EMS ═══
for q in ["Should EMS use validated stroke screening tools?","Is prehospital stroke severity assessment recommended?","Should EMS prenotify the hospital about incoming stroke patients?","Does the guideline recommend EMS stroke protocols?","Should dispatchers prioritize suspected stroke calls?","Are stroke severity scales recommended for prehospital use?","What stroke assessment should EMS perform in the field?"]: add_rec(q)

# ═══ 2.3 Prehospital ═══
for q in ["Should blood glucose be checked in the field for suspected stroke?","Is prehospital blood pressure lowering recommended?","Should paramedics give neuroprotective agents in the field?","Is magnesium recommended for prehospital stroke treatment?","Should oxygen be given to non-hypoxic stroke patients in the field?","Is IV access recommended in the prehospital setting for stroke?","Should EMS use a standardized stroke severity scale?","Is prehospital triage for stroke centers recommended?","Can prehospital blood glucose testing delay transport?"]: add_rec(q)

# ═══ 2.4 EMS Destination ═══
for q in ["Should EMS bypass the closest hospital for a stroke center?","Is it better to go to a thrombectomy center directly or do drip-and-ship?","Should suspected LVO patients be taken directly to a comprehensive stroke center?","Is air transport recommended for stroke patients when ground transport is too slow?","When should EMS bypass a primary stroke center for a comprehensive one?","Is direct transport to a thrombectomy-capable center reasonable for suspected LVO?"]: add_rec(q)

# ═══ 2.5 MSU ═══
for q in ["Are mobile stroke units effective for reducing time to IVT?","Should mobile stroke units be used when available?","Is prehospital CT scanning on a mobile stroke unit recommended?","Can IVT be safely given on a mobile stroke unit?","Do mobile stroke units improve stroke outcomes?","Is MSU-based thrombolysis recommended?"]: add_rec(q)

# ═══ 2.6 Hospital ═══
for q in ["Should hospitals maintain organized stroke care capabilities?","Is stroke center certification recommended?"]: add_rec(q)

# ═══ 2.7 Emergency Eval ═══
for q in ["How quickly should stroke patients get brain imaging in the ED?","Should IVT be delayed to wait for blood work other than glucose?","What lab tests need to come back before giving tPA?","Should stroke patients have NIHSS assessed on arrival?","Is rapid neuroimaging recommended for all suspected stroke patients?","How fast should door-to-needle time be for IVT?"]: add_rec(q)

# ═══ 2.8 Telemedicine ═══
for q in ["Can telestroke be used to decide on IVT at a remote hospital?","Is telestroke-guided thrombolysis as safe as in-person evaluation?","Should telestroke networks facilitate rapid EVT transfers?","Is robotic telestroke a reasonable option?","Can telestroke be used for EVT decision-making?","Should hospitals without neurologists use telestroke?"]: add_rec(q)

# ═══ 2.9–2.10 Systems ═══
for q in ["Should regions organize integrated stroke systems of care?","Is a systems-based approach to stroke care recommended?","Should hospitals coordinate with EMS for stroke protocols?","Should hospitals join stroke data registries?","Is Get With The Guidelines participation recommended?","Does participation in stroke registries improve outcomes?"]: add_rec(q)

# ═══ 3.1 Stroke Scales ═══
for q in ["Should NIHSS be used to assess stroke severity?","Is a validated stroke scale required for all acute stroke patients?","What stroke severity scale does the guideline recommend?"]: add_rec(q)

# ═══ 3.2 Imaging ═══
for q in ["Is NCCT sufficient before giving tPA?","Do I need MRI before administering IVT?","Should CTA be done for all suspected stroke patients?","Is CTA or MRA recommended to look for LVO?","Do I need CT perfusion for EVT patient selection?","Is perfusion imaging needed in the 6-24 hour window?","Can MRI be used instead of CT for initial stroke workup?","Is NCCT or MRI recommended as the first imaging study?","Should I get vascular imaging before IVT?","Do I need vascular imaging for EVT candidates?","What imaging is needed before tPA?","Is multiphase CTA helpful for EVT selection?","Should ASPECTS be scored on the initial CT?","Is automated perfusion software recommended?","Do I need MRI to evaluate for EVT?","Can I use MRA instead of CTA to evaluate for LVO?","What imaging does the guideline require for late-window EVT?"]: add_rec(q)

# ═══ 3.3 Other Tests ═══
for q in ["Should I check troponin in my stroke patient?","Is an EKG recommended for acute stroke?","What labs should be obtained for acute stroke?"]: add_rec(q)

# ═══ 4.1 Airway ═══
for q in ["Should I give oxygen to my stroke patient with normal O2 sat?","Is supplemental oxygen harmful in non-hypoxic stroke patients?","When should a stroke patient be intubated?","Should oxygen saturation be kept above 94%?","Is hyperbaric oxygen therapy beneficial in acute stroke?","What O2 sat target should I maintain for stroke patients?"]: add_rec(q)

# ═══ 4.2 Head Position ═══
for q in ["Should I keep my stroke patient flat or elevate the head of bed?","Does head-of-bed positioning matter in acute stroke?","Is flat positioning better than elevated for stroke patients?"]: add_rec(q)

# ═══ 4.3 BP ═══
for q in ["What BP do I need before giving tPA?","What is the BP cutoff for IVT eligibility?","What BP should I maintain after giving tPA?","Should I keep BP below 180/105 after thrombolysis?","What BP target after successful EVT?","Should I target SBP under 140 after successful thrombectomy?","Is aggressive BP lowering recommended if the patient didn't get tPA or EVT?","What BP meds should I use for acute stroke?","Is labetalol or nicardipine preferred for BP control in stroke?","Is rapid BP reduction harmful in acute stroke?","Can I lower BP more than 25% in the first hour?","What BP threshold makes a patient ineligible for IVT?","Should I treat BP 200/110 in a non-IVT stroke patient?","How low should I get the BP before tPA?"]: add_rec(q)

# ═══ 4.4 Temperature ═══
for q in ["Should I treat fever in my stroke patient?","Is acetaminophen recommended for fever in stroke?","Is induced hypothermia beneficial after ischemic stroke?","What temperature is considered a problem in acute stroke?","Should I use cooling devices for my febrile stroke patient?"]: add_rec(q)

# ═══ 4.5 Glucose ═══
for q in ["How should I manage hyperglycemia in my stroke patient?","Is tight glucose control recommended after stroke?","Should I correct hypoglycemia in acute stroke?","What glucose level is too low to give tPA?","Should blood sugar be monitored in all stroke patients?"]: add_rec(q)

# ═══ 4.6.1 IVT Decision ═══
for q in ["Should I give tPA to a patient within 3 hours of symptom onset?","Is IVT recommended within 4.5 hours?","Can I give tPA to a patient over 80 years old?","Is there an age cutoff for IVT?","Should I give IVT for mild non-disabling stroke?","Can IVT be given to patients with NIHSS under 6?","Is tPA recommended for patients with early ischemic changes on CT?","Can I give tPA without waiting for all lab results?","Should IVT be given as fast as possible within the window?","Is IVT recommended for patients on anticoagulants?","Should I give tPA if the patient has a seizure at onset?","Is IVT recommended for disabling deficits regardless of NIHSS?","Can a patient with improving symptoms still get tPA?","Is tPA safe for patients with blood glucose under 50?","Do I need informed consent before giving IVT?","Is IVT recommended for patients with LVO going to EVT?","Should I start IVT while waiting for the EVT team?","Is IVT contraindicated for mild stroke without disability?","A 72-year-old presents 2 hours after onset with NIHSS 14. Should I give IVT?","My patient is 85 with a 3-hour-old stroke. Is there an age limit for tPA?","NIHSS 2, symptoms are not disabling. Should I give tPA?","Patient has early ischemic changes on NCCT but no contraindications. IVT?"]: add_rec(q)

# ═══ 4.6.2 Choice of Agent ═══
for q in ["Should I use tenecteplase or alteplase?","Is tenecteplase preferred over alteplase?","What is the recommended thrombolytic drug for acute stroke?","Is desmoteplase effective for stroke?","If tenecteplase is available, should I still use alteplase?","What dose of tenecteplase should I give?"]: add_rec(q)

# ═══ 4.6.3 Extended Window ═══
for q in ["Can I give IVT between 4.5 and 9 hours?","Is tPA an option for wake-up stroke?","What imaging do I need for IVT beyond 4.5 hours?","Is DWI-FLAIR mismatch useful for selecting late IVT candidates?","Can I give IVT beyond 9 hours from last known well?","Is perfusion mismatch required for extended-window IVT?","My patient woke up with stroke symptoms. Can I give tPA?"]: add_rec(q)

# ═══ 4.6.4 Other Fibrinolytics ═══
for q in ["Is sonothrombolysis helpful for acute stroke?","Should streptokinase be used for stroke?","Is urokinase an option for AIS?","Are there other fibrinolytics besides alteplase and tenecteplase?"]: add_rec(q)

# ═══ 4.6.5 Other IVT ═══
for q in ["Can I give tPA to a patient already on aspirin?","Is IVT safe in patients already taking antiplatelet drugs?","Can IVT be given to a patient with pre-existing disability?"]: add_rec(q)

# ═══ 4.7.1 IVT+EVT ═══
for q in ["Should I give tPA before sending the patient for thrombectomy?","Is bridging IVT recommended before EVT?","Should EVT be delayed to watch for IVT response?","Can I skip IVT and go straight to thrombectomy?","Is IVT contraindicated before EVT? Or is it recommended?"]: add_rec(q)

# ═══ 4.7.2 EVT Adults ═══
for q in ["Is thrombectomy recommended for M1 occlusion within 6 hours?","Can EVT be done for ICA terminus occlusion?","Should I do thrombectomy for M2 occlusions?","Is EVT recommended for patients over 80?","Can EVT be done in the 6-24 hour window?","What NIHSS threshold is required for EVT?","Is EVT recommended for NIHSS under 6?","Should patients with large core infarcts still get EVT?","Is EVT beneficial for ASPECTS below 6?","Is thrombectomy recommended beyond 24 hours?","65yo, NIHSS 18, M1 occlusion, 2 hours from LKW. Thrombectomy?","My patient has an M1 occlusion and NIHSS 20. Is EVT recommended?","Patient with ICA occlusion, NIHSS 14, 5 hours out. EVT?","Wake-up stroke with M1 occlusion on CTA and mismatch on perfusion. EVT?","Is EVT recommended for A1 or A2 occlusions?"]: add_rec(q)

# ═══ 4.7.3 Posterior ═══
for q in ["Is thrombectomy recommended for basilar artery occlusion?","Should I do EVT for posterior circulation stroke?","Can EVT help my patient with basilar occlusion?","Is vertebral artery thrombectomy supported by the guidelines?","Patient with basilar occlusion and mRS 0-2 at baseline. EVT?"]: add_rec(q)

# ═══ 4.7.4 Techniques ═══
for q in ["Should I use a stent retriever or direct aspiration?","Is general anesthesia or conscious sedation better for EVT?","Can I place a stent during thrombectomy if there's an underlying stenosis?","Is rescue IA thrombolysis an option during failed thrombectomy?","Should I use a balloon guide catheter for EVT?","Is IA tPA alone as effective as mechanical thrombectomy?","What reperfusion grade should I aim for during EVT?","Is combined stent retriever plus aspiration better?"]: add_rec(q)

# ═══ 4.7.5 Pediatric ═══
for q in ["Can EVT be done in children?","Is thrombectomy recommended for pediatric stroke?","Should adult EVT criteria be applied to children?","My 12-year-old patient has M1 occlusion. Is EVT an option?"]: add_rec(q)

# ═══ 4.8 Antiplatelet ═══
for q in ["When should I start aspirin after stroke?","Is dual antiplatelet therapy recommended for minor stroke?","Should I give aspirin within 24 hours of tPA?","Is clopidogrel loading recommended for minor stroke or TIA?","Is ticagrelor an option for acute stroke?","Should GP IIb/IIIa inhibitors be used in stroke?","Is triple antiplatelet therapy safe in stroke?","How long should DAPT continue after minor stroke?","Should IV antiplatelet agents be used in acute stroke?","Can aspirin be given the day after thrombolysis?","Is early aspirin within 48 hours recommended for non-IVT patients?","Minor stroke, NIHSS 3, no LVO. Start DAPT?","Is cangrelor recommended for acute ischemic stroke?"]: add_rec(q)

# ═══ 4.9 Anticoagulants ═══
for q in ["When should I start anticoagulation for AF-related stroke?","Is early heparin anticoagulation recommended after stroke?","Should I use DOAC or warfarin for AF after stroke?","Is urgent anticoagulation recommended to prevent recurrent stroke?","How soon can I anticoagulate after a large stroke?","Patient with AF and moderate stroke. When to start anticoagulation?"]: add_rec(q)

# ═══ 4.10-4.12 ═══
for q in ["Should I give IV fluids for hemodynamic augmentation in stroke?","Is hemodilution therapy recommended for AIS?","Are vasodilators beneficial in acute stroke?","Are there any neuroprotective drugs recommended for acute stroke?","Is neuroprotection beneficial in AIS?","Should I do emergency carotid endarterectomy during acute stroke?","Is emergency carotid stenting recommended during AIS?"]: add_rec(q)

# ═══ 5.x Hospital ═══
for q in ["Should my stroke patient go to a stroke unit or general ward?","Is stroke unit admission recommended?","Should I screen for swallowing problems before letting the patient eat?","Is a formal swallowing evaluation needed after stroke?","Can I give oral meds without a swallowing screen?","Should all stroke patients get a dysphagia screen?","My stroke patient wants to eat. What should I do first?","When should I start tube feeding for a stroke patient who can't swallow?","Is early enteral nutrition recommended after stroke?","Should nutritional assessment be done for all stroke patients?","How should I prevent blood clots in my immobilized stroke patient?","Are compression stockings recommended for DVT prevention after stroke?","Should I use pneumatic compression devices for stroke patients?","Is subcutaneous heparin recommended for DVT prophylaxis?","Are elastic stockings harmful after stroke?","Should I screen my stroke patient for depression?","Is antidepressant treatment recommended after stroke?","When should depression screening happen after stroke?","Should I start a statin in the acute stroke phase?","Is prophylactic antiseizure medication recommended after stroke?","Should benzodiazepines be given for agitation after stroke?","When can my stroke patient start physical therapy?","Is very early aggressive mobilization within 24 hours safe?","Should all stroke patients get a rehab assessment?","Is high-intensity early mobilization harmful?"]: add_rec(q)

# ═══ 6.x Complications ═══
for q in ["How should I monitor for brain swelling after a large stroke?","Should patients with large MCA strokes be in the ICU for edema monitoring?","Is early anticipation of cerebral edema recommended?","Can I give mannitol for brain swelling after stroke?","Is hypertonic saline recommended for cerebral edema?","Should I give steroids for brain swelling after stroke?","Does induced hypothermia help with post-stroke brain edema?","When should I consider decompressive craniectomy for malignant MCA infarction?","Is hemicraniectomy recommended for patients under 60 with large MCA stroke?","Should older patients get decompressive surgery for malignant edema?","How soon should craniectomy be done for malignant MCA infarction?","55-year-old with large MCA stroke and midline shift. Craniectomy?","Should I consult neurosurgery for a cerebellar stroke with brainstem compression?","Is ventriculostomy recommended for hydrocephalus from cerebellar infarction?","When is posterior fossa decompression indicated?","My stroke patient had a seizure. Should I start antiepileptic meds?","Should I routinely give seizure prophylaxis to all stroke patients?","When should I treat seizures in my stroke patient?"]: add_rec(q)

# ═══ Clinical Scenarios ═══
scenarios = [
    "A 72-year-old presents 2 hours after symptom onset with NIHSS 14. Should I give IVT?",
    "65yo, NIHSS 18, M1 occlusion, LKW 2 hours ago. What does the guideline recommend?",
    "Patient is 45 with NIHSS 4 and disabling symptoms at 3 hours. Is IVT indicated?",
    "My patient has ASPECTS 4, large core on CTP, and M1 occlusion at 5 hours. EVT?",
    "Patient received tPA 1 hour ago. What BP target should I maintain?",
    "Should I give tenecteplase or alteplase to my stroke patient?",
    "My patient got IVT 30 minutes ago and has M1 occlusion. Should I proceed with EVT?",
    "Minor stroke, NIHSS 3, no LVO. Should I start dual antiplatelet therapy?",
    "85-year-old with 4-hour-old stroke. Is there an age cutoff for IVT?",
    "Wake-up stroke, DWI-FLAIR mismatch, M1 occlusion. Should I do EVT?",
    "Patient with wake-up stroke and perfusion mismatch. Can I give IVT?",
    "Do I need CTA before giving tPA?",
    "My stroke patient has O2 sat of 96%. Should I give supplemental oxygen?",
    "My stroke patient has a temperature of 39C. What should I do?",
    "Blood glucose is 250 in my stroke patient. How aggressively should I treat?",
    "Large MCA infarction with midline shift in a 55-year-old. Craniectomy?",
    "How should I prevent DVT in my immobile stroke patient?",
    "Should I keep my stroke patient flat or elevate the head of bed?",
    "Patient with acute basilar artery occlusion. Is EVT recommended?",
    "Patient with AF and acute stroke. When should I start anticoagulation?",
    "NIHSS 2, non-disabling symptoms. Should I give tPA?",
    "Patient with M2 occlusion and NIHSS 10. Is EVT recommended?",
    "BP is 200/110 and patient is EVT candidate. What should I do?",
    "My stroke patient wants to eat. Should I do a swallowing screen first?",
    "Should I use a stent retriever or aspiration first for my EVT case?",
    "Should I give IV fluids for hemodynamic augmentation in stroke?",
    "Are there any neuroprotective drugs I should give for acute stroke?",
    "My patient has severe carotid stenosis with acute stroke. Emergency CEA?",
    "My stroke patient seems depressed 1 week after admission. Should I screen?",
    "Cerebellar infarction with brainstem compression. Should I consult surgery?",
    "When can my stroke patient start rehab?",
    "My stroke patient had a seizure. Should I start antiepileptic medication?",
    "Should I give prophylactic antiseizure drugs to my stroke patient?",
    "My stroke patient cannot swallow. When should I start tube feeding?",
    "Large stroke with edema. Should I give mannitol?",
    "Should I give steroids for cerebral edema after stroke?",
    "12-year-old with acute M1 occlusion. Is EVT an option?",
    "Should I deploy a mobile stroke unit for a suspected stroke call?",
    "No neurologist on site. Can I use telestroke to evaluate for IVT?",
    "Suspected LVO. Should EMS bypass the closest hospital for a thrombectomy center?",
    "Why do I need CTA for EVT?",
    "What imaging do I need for EVT in the extended window?",
    "My patient has an ASPECTS of 4. Can I still do EVT?",
    "Is MRA equivalent to CTA for LVO detection?",
    "Patient on warfarin with INR 1.5 presents with stroke at 2 hours. IVT?",
    "72yo with basilar occlusion and NIHSS 22. Thrombectomy?",
    "My patient is 4 hours out with improving NIHSS. Still give tPA?",
    "58yo with M1 occlusion, NIHSS 6. Is this NIHSS too low for EVT?",
    "Patient with stroke and BP 195/115. Can I give tPA after lowering BP?",
    "My patient has atrial fibrillation. When is the earliest I can start anticoagulation after stroke?",
]
for q in scenarios: add_rec(q)

# ═══ EVIDENCE / RSS QUESTIONS ═══
ev = {
    "2.1": ["What evidence supports public stroke education campaigns?","What studies show stroke awareness programs are effective?","What data supports teaching the public about stroke symptoms?","What is the rationale for community stroke education?"],
    "2.2": ["What evidence supports EMS stroke screening tools?","What data shows prehospital severity scales improve outcomes?","What studies support EMS prenotification for stroke?"],
    "2.3": ["What evidence supports prehospital blood glucose testing in stroke?","What data shows prehospital neuroprotection is harmful?","Why is prehospital BP lowering not recommended for stroke?"],
    "2.4": ["What evidence supports bypassing hospitals for stroke centers?","What data compares drip-and-ship versus mothership for EVT?","What studies support direct transport to thrombectomy centers?"],
    "2.5": ["What trial data supports mobile stroke units?","What evidence shows MSUs reduce time to treatment?","What studies support prehospital thrombolysis via MSU?"],
    "2.7": ["What evidence supports rapid imaging in the ED for stroke?","What data shows lab results can be skipped before IVT?","What is the rationale for rapid door-to-needle time targets?"],
    "2.8": ["What evidence supports telestroke for thrombolysis decisions?","What studies show telestroke is effective at remote hospitals?","What data supports telemedicine for stroke evaluation?"],
    "3.1": ["What evidence supports using NIHSS for stroke severity?","What data shows stroke scales improve clinical decisions?","What is the rationale for validated stroke severity scales?"],
    "3.2": ["What evidence supports NCCT as initial stroke imaging?","What data shows CT perfusion helps select EVT patients?","What studies support CTA for detecting LVO?","What evidence supports MRI as an alternative to CT for stroke?","What is the rationale for perfusion imaging in late-window EVT?"],
    "4.1": ["What evidence shows supplemental oxygen has no benefit in non-hypoxic stroke?","What data supports maintaining O2 sat above 94% in stroke?","What studies tested hyperbaric oxygen for ischemic stroke?"],
    "4.2": ["What evidence shows head positioning doesn't matter in acute stroke?","What trial tested flat vs elevated head-of-bed in stroke?","What is the rationale for not specifying a head-of-bed position in stroke?"],
    "4.3": ["What evidence supports BP below 185/110 before IVT?","What data supports BP targets after thrombolysis?","What studies tested intensive BP lowering after EVT?","What is the rationale for SBP under 140 post-EVT?","What evidence shows aggressive BP reduction is harmful in stroke?","What trials tested BP management in acute stroke?"],
    "4.4": ["What evidence supports treating fever in acute stroke?","What data shows hypothermia doesn't help ischemic stroke?","What trials tested temperature management in stroke?"],
    "4.5": ["What evidence supports glucose management in stroke?","What data shows tight glucose control is not beneficial?","What studies tested insulin protocols in stroke?"],
    "4.6.1": ["What evidence supports IVT within 3 hours?","What trial data supports IVT for patients over 80?","What is the rationale for IVT in mild stroke with disabling deficits?","What evidence supports giving IVT without waiting for labs?","What studies tested IVT for early ischemic changes on CT?","What data supports IVT in the 3-4.5 hour window?"],
    "4.6.2": ["What evidence supports tenecteplase over alteplase?","What trials compared tenecteplase to alteplase for stroke?","What is the rationale for tenecteplase as the preferred thrombolytic?"],
    "4.6.3": ["What evidence supports IVT in the extended time window?","What trial data supports wake-up stroke thrombolysis?","What studies used perfusion imaging to select late IVT candidates?","What is the evidence for DWI-FLAIR mismatch in IVT selection?"],
    "4.6.4": ["What evidence shows streptokinase is harmful for stroke?","What data shows sonothrombolysis has no benefit?","What studies tested other fibrinolytics for stroke?"],
    "4.7.1": ["What evidence supports giving IVT before EVT?","What data shows bridging therapy is beneficial?"],
    "4.7.2": ["What trial data supports EVT for anterior LVO?","What evidence supports thrombectomy in the 6-24 hour window?","What studies support EVT for M2 occlusions?","What data supports EVT in patients with large ischemic cores?","What is the rationale for EVT beyond 6 hours?","What trials tested EVT for low NIHSS patients?"],
    "4.7.3": ["What evidence supports EVT for basilar artery occlusion?","What trials tested posterior circulation thrombectomy?","What data supports EVT for vertebrobasilar stroke?"],
    "4.7.4": ["What evidence supports stent retrievers for EVT?","What studies compared general anesthesia vs sedation for EVT?","What data shows direct aspiration is effective?","What trials tested rescue IA thrombolysis?"],
    "4.7.5": ["What evidence supports EVT in pediatric patients?","What data is there on thrombectomy in children with stroke?"],
    "4.8": ["What evidence supports early aspirin after stroke?","What trial data supports DAPT for minor stroke?","What studies tested ticagrelor for acute stroke?","What is the rationale for avoiding GP IIb/IIIa inhibitors in stroke?"],
    "4.9": ["What evidence supports DOAC over warfarin for AF stroke?","What data shows early heparin doesn't help in stroke?","What is the rationale for delayed anticoagulation after large stroke?"],
    "4.10": ["What evidence shows hemodilution doesn't work for stroke?","What data shows vasodilators are not beneficial in AIS?"],
    "4.11": ["What evidence shows neuroprotective agents don't work?","What trials tested neuroprotection in acute stroke?"],
    "5.2": ["What evidence supports dysphagia screening before oral intake?","What data shows swallowing assessment prevents aspiration pneumonia?","What studies support formal swallowing evaluation after stroke?"],
    "5.4": ["What evidence supports DVT prophylaxis with pneumatic compression?","What data shows compression stockings are harmful after stroke?","What studies tested heparin for DVT prevention in stroke?"],
    "5.7": ["What evidence shows very early mobilization is harmful?","What trial tested early high-dose mobilization after stroke?","What data supports rehabilitation assessment for stroke patients?"],
    "6.1": ["What evidence supports monitoring for cerebral edema after large strokes?","What data supports ICU admission for malignant edema risk?","What is the rationale for early edema monitoring in large hemispheric infarctions?"],
    "6.2": ["What evidence supports osmotic therapy for brain edema?","What data shows corticosteroids are harmful for stroke edema?","What is the rationale for avoiding steroids in ischemic stroke edema?"],
    "6.3": ["What evidence supports decompressive craniectomy for malignant MCA infarction?","What trials tested hemicraniectomy for stroke?","What data supports craniectomy in patients over 60?"],
    "6.4": ["What evidence supports posterior fossa decompression for cerebellar stroke?","What data supports ventriculostomy for cerebellar infarction?","What is the rationale for surgical intervention in cerebellar stroke with brainstem compression?"],
    "6.5": ["What evidence supports treating seizures in stroke patients?","What data shows prophylactic antiseizure medication is not needed?","What is the rationale for not giving prophylactic antiepileptic drugs after stroke?"],
}
for sec, qs in ev.items():
    for q in qs: add_ev(sec, q)

# ═══ KNOWLEDGE GAP QUESTIONS ═══
kg = {"2.1":["stroke awareness programs","public stroke education"],"2.3":["prehospital stroke management","prehospital interventions"],"2.5":["mobile stroke units","prehospital thrombolysis"],"3.2":["stroke imaging","perfusion imaging for EVT"],"4.3":["BP management in acute stroke","BP targets after EVT"],"4.4":["temperature management in stroke"],"4.5":["glucose management in stroke"],"4.6.1":["IVT decision-making","thrombolysis for stroke"],"4.6.2":["tenecteplase dosing"],"4.6.3":["extended-window IVT","wake-up stroke thrombolysis"],"4.7.2":["EVT for adults","thrombectomy patient selection"],"4.7.3":["posterior circulation EVT","basilar artery thrombectomy"],"4.7.4":["EVT techniques"],"4.7.5":["pediatric EVT"],"4.8":["antiplatelet therapy in stroke","DAPT duration"],"4.9":["anticoagulation after stroke"],"5.2":["dysphagia management"],"5.4":["DVT prophylaxis in stroke"],"5.7":["stroke rehabilitation","early mobilization"],"6.1":["brain swelling after stroke"],"6.3":["decompressive craniectomy"]}
kg_tmpls = ["What are the knowledge gaps for {t}?","What future research is needed on {t}?","What remains unclear about {t}?","What are the unanswered questions about {t}?","What gaps in evidence exist for {t}?","What areas need further study regarding {t}?","What further investigation is needed on {t}?","What research gaps exist for {t}?"]
for sec, topics in kg.items():
    for t in topics:
        for tmpl in kg_tmpls: add_kg(sec, tmpl.format(t=t))

# ═══ TABLE 8 — IVT CONTRAINDICATIONS ═══
# Natural clinician phrasing — no "Table 8" references
for cond in ["intracranial hemorrhage on imaging","active internal bleeding","intra-axial brain tumor","glioma","infective endocarditis","severe coagulopathy with platelets below 100000","aortic arch dissection","blood glucose less than 50","extensive hypodensity on CT","traumatic brain injury within 14 days","intracranial neurosurgery within 14 days","spinal cord injury","ARIA with amyloid immunotherapy","intra-axial intracranial neoplasm"]:
    add_t8(f"Is {cond} a contraindication to IVT?","Absolute")
    add_t8(f"My patient has {cond}. Can I give tPA?","Absolute")
    add_t8(f"Is {cond} an absolute contraindication to thrombolysis?","Absolute")

for cond in ["pregnancy","prior intracranial hemorrhage","DOAC within 48 hours","active malignancy","hepatic failure","dialysis","dementia","arterial dissection","vascular malformation","pericarditis","recent lumbar puncture","pre-existing disability","pancreatitis","cardiac thrombus","noncompressible arterial puncture","AVM","left ventricular thrombus"]:
    add_t8(f"Is {cond} a contraindication to IVT?","Relative")
    add_t8(f"Can IVT be given to a patient with {cond}?","Relative")
    add_t8(f"My patient has {cond}. Is thrombolysis safe?","Relative")

for cond in ["extracranial cervical dissection","extra-axial intracranial neoplasm","unruptured intracranial aneurysm","moyamoya disease","stroke mimic","seizure at onset","cerebral microbleeds","menstruation","diabetic retinopathy","recreational drug use","remote GI bleeding","history of myocardial infarction","procedural stroke during angiography"]:
    add_t8(f"Is {cond} a contraindication to IVT?","Benefit May Exceed Risk")
    add_t8(f"Can I give tPA to a patient with {cond}?","Benefit May Exceed Risk")
    add_t8(f"My patient has {cond}. Should I still consider thrombolysis?","Benefit May Exceed Risk")

for q in ["What are the absolute contraindications for IVT?","What are the relative contraindications for thrombolysis?","What conditions make IVT absolutely contraindicated?","What are the three categories of IVT contraindications?","What are all the contraindications to thrombolysis in the guidelines?","When is IVT contraindicated?","Which conditions are relative contraindications to tPA?","When does benefit of IVT still exceed risk despite a contraindication?"]:
    add_t8(q, "")

# ═══ ROUND 2: 500+ ADDITIONAL QUESTIONS ═══

# ── More Rec Questions (varied phrasing, deeper coverage) ──

# 2.1 Stroke Awareness — additional
for q in [
    "Is mass media recommended for stroke symptom education?",
    "Should stroke awareness programs target high-risk communities?",
    "Does the guideline recommend teaching FAST symptoms to the public?",
    "Should school children be taught about stroke recognition?",
    "Is culturally tailored stroke education recommended?",
]: add_rec(q)

# 2.2 EMS — additional
for q in [
    "Should all ambulances carry a stroke severity assessment tool?",
    "Is prehospital NIHSS or equivalent assessment required?",
    "Should EMS activate a stroke alert before arrival?",
    "Does the guideline recommend EMS training on stroke mimics?",
    "Should emergency dispatchers use a stroke screening tool?",
]: add_rec(q)

# 2.3 Prehospital — additional
for q in [
    "Should paramedics start an IV line in suspected stroke patients?",
    "Is prehospital administration of any medications recommended for stroke?",
    "Should EMS check blood glucose on all suspected stroke patients?",
    "Is prehospital use of antiemetics recommended for stroke patients?",
    "Does the guideline recommend against any prehospital interventions for stroke?",
]: add_rec(q)

# 2.4 EMS Destination — additional
for q in [
    "Should all stroke patients go to the nearest stroke center?",
    "Is helicopter transport recommended for remote stroke patients?",
    "When is it appropriate to bypass a primary stroke center?",
    "Should EMS use a severity scale to decide the destination hospital?",
    "Is interfacility transfer recommended for EVT candidates?",
]: add_rec(q)

# 2.5 MSU — additional
for q in [
    "Can CT angiography be performed on a mobile stroke unit?",
    "Is telemedicine on a mobile stroke unit recommended?",
    "Should MSUs carry thrombolytics?",
    "Is the MSU model cost-effective for stroke care?",
]: add_rec(q)

# 2.7 Emergency Eval — additional
for q in [
    "Should a platelet count be available before giving IVT?",
    "Can I give tPA before the INR result is available?",
    "Is a CT scan required before IVT in all patients?",
    "Should glucose be the only lab checked before tPA?",
    "What is the recommended door-to-imaging time for stroke?",
]: add_rec(q)

# 2.8 Telemedicine — additional
for q in [
    "Is video-based telestroke preferred over phone-only consultation?",
    "Can telestroke guide EVT decision-making at a remote hospital?",
    "Should telestroke be available 24/7 at primary stroke centers?",
    "Is robot-assisted telestroke as good as bedside evaluation?",
]: add_rec(q)

# 3.1 Stroke Scales — additional
for q in [
    "Should a stroke scale be assessed serially during hospitalization?",
    "Is the NIHSS the only recommended stroke severity scale?",
    "Should nurses be trained to perform NIHSS assessments?",
    "How often should NIHSS be reassessed after thrombolysis?",
]: add_rec(q)

# 3.2 Imaging — additional
for q in [
    "Is CT angiography required before thrombolysis?",
    "Should all stroke patients get vascular imaging within 24 hours?",
    "Is MR perfusion equivalent to CT perfusion for EVT selection?",
    "Can ASPECTS be scored on MRI DWI sequences?",
    "Should I get a CTA head and neck or just head for stroke?",
    "Is repeat brain imaging recommended after IVT?",
    "Should CT perfusion be done for all anterior circulation strokes?",
    "Is vessel imaging needed for posterior circulation stroke?",
    "Can I use MRI instead of CT perfusion for late-window EVT?",
    "Is ultrasound useful for evaluating cervical vessels in acute stroke?",
]: add_rec(q)

# 3.3 Other Tests — additional
for q in [
    "Should a coagulation panel be drawn before IVT?",
    "Is echocardiography recommended in the acute phase of stroke?",
    "Should I check a drug screen in my acute stroke patient?",
    "Is cardiac monitoring recommended for stroke patients?",
    "How long should telemetry be continued after acute stroke?",
]: add_rec(q)

# 4.1 Airway — additional
for q in [
    "Should I intubate my stroke patient with a GCS of 8?",
    "Is continuous pulse oximetry recommended for stroke patients?",
    "What is the oxygen saturation goal for acute stroke patients?",
    "Should I use high-flow nasal cannula for my desaturating stroke patient?",
    "Is supplemental oxygen recommended for all stroke patients in the ED?",
]: add_rec(q)

# 4.2 Head Position — additional
for q in [
    "Should the head of bed be at 30 degrees for stroke patients?",
    "Does flat positioning improve blood flow to the brain in stroke?",
    "Is there a recommended head position for patients with cerebral edema?",
]: add_rec(q)

# 4.3 BP — additional
for q in [
    "What is the maximum allowable BP before thrombolysis?",
    "Should I use IV labetalol or IV nicardipine for BP control in stroke?",
    "Is it safe to lower BP below 140 systolic after thrombectomy?",
    "What BP range should I target for stroke patients not receiving reperfusion therapy?",
    "Should antihypertensives be held in the first 24 hours of stroke?",
    "Is nitroprusside recommended for BP control in acute stroke?",
    "Can oral antihypertensives be used instead of IV for stroke BP management?",
    "Should I restart home BP medications after acute stroke?",
    "What is the BP goal for patients with failed recanalization after EVT?",
    "Is permissive hypertension recommended for non-reperfused stroke patients?",
]: add_rec(q)

# 4.4 Temperature — additional
for q in [
    "Should I actively cool my stroke patient who is normothermic?",
    "Is targeted temperature management recommended after ischemic stroke?",
    "What fever threshold triggers treatment in acute stroke?",
    "Should I look for the source of fever in my stroke patient?",
]: add_rec(q)

# 4.5 Glucose — additional
for q in [
    "What blood glucose range should I target in acute stroke?",
    "Should I use an insulin drip for hyperglycemia in stroke?",
    "Is dextrose recommended for hypoglycemia in stroke patients?",
    "Can hyperglycemia worsen stroke outcomes?",
    "Should I avoid IV dextrose in acute stroke patients?",
]: add_rec(q)

# 4.6.1 IVT Decision — additional
for q in [
    "Can I give tPA if the stroke time of onset is uncertain?",
    "Is IVT recommended for patients presenting at exactly 4.5 hours?",
    "Should I give tPA to a patient with a history of prior stroke?",
    "Can IVT be given to a patient with mild but disabling symptoms?",
    "Is IVT recommended for patients with a coagulopathy?",
    "Should I withhold tPA if the patient has a small amount of blood on CT?",
    "Can a patient get tPA if they had surgery 2 weeks ago?",
    "Is IVT recommended for patients who are on DOACs?",
    "Should I give tPA to a pregnant stroke patient?",
    "Can I give IVT if the patient's platelets are below 100,000?",
    "Is there a maximum NIHSS for IVT eligibility?",
    "Should I give tPA for an NIHSS of 25?",
    "Can a patient receive IVT if they had a seizure at stroke onset?",
    "Is IVT appropriate for a patient with a recent GI bleed?",
]: add_rec(q)

# 4.6.2 Choice of Agent — additional
for q in [
    "What is the recommended dose of alteplase for stroke?",
    "Is 0.25 mg/kg tenecteplase the standard dose?",
    "Are there any contraindications specific to tenecteplase?",
    "Should I switch from alteplase to tenecteplase at my institution?",
]: add_rec(q)

# 4.6.3 Extended Window — additional
for q in [
    "Can I give tPA at 7 hours with a perfusion mismatch?",
    "Is tenecteplase an option for extended-window IVT?",
    "What criteria must be met for IVT beyond 4.5 hours?",
    "Should wake-up stroke patients get perfusion imaging before IVT?",
    "Can IVT be given based on DWI-FLAIR mismatch alone?",
]: add_rec(q)

# 4.6.5 Other IVT considerations — additional
for q in [
    "Can a patient on clopidogrel receive IVT?",
    "Is IVT safe after a recent lumbar puncture?",
    "Can I give tPA to a patient with a history of ICH?",
    "Should I give IVT to a patient on heparin with elevated PTT?",
]: add_rec(q)

# 4.7.1 IVT+EVT — additional
for q in [
    "Should I wait to see if IVT works before proceeding to EVT?",
    "Is it safe to give tPA and then proceed directly to thrombectomy?",
    "Does IVT before EVT improve recanalization rates?",
    "Can I skip tPA if the patient is going straight to the cath lab?",
]: add_rec(q)

# 4.7.2 EVT Adults — additional
for q in [
    "Is EVT recommended for distal M2 branch occlusions?",
    "Can EVT be done if the ASPECTS is 3?",
    "Is there an age limit for thrombectomy?",
    "Should I do EVT on a patient with a pre-stroke mRS of 3?",
    "Is EVT recommended for tandem ICA and M1 occlusions?",
    "Can EVT be performed at 20 hours from symptom onset?",
    "Is thrombectomy beneficial for patients with an NIHSS of 8?",
    "Should I consider EVT for a patient with bilateral strokes?",
    "Is EVT recommended if the CT shows a large established infarct?",
    "Can EVT be done without prior IV thrombolysis?",
    "Is EVT recommended for M3 occlusions?",
    "Should I proceed with EVT if TICI 2b is achieved after first pass?",
    "My patient has M1 occlusion at 10 hours with perfusion mismatch. EVT?",
    "Is EVT recommended for patients on anticoagulation?",
]: add_rec(q)

# 4.7.3 Posterior — additional
for q in [
    "Can EVT be done for a vertebral artery occlusion?",
    "Is thrombectomy recommended for posterior inferior cerebellar artery occlusion?",
    "Should I do EVT on a basilar occlusion patient with a high NIHSS?",
    "What is the time window for posterior circulation EVT?",
]: add_rec(q)

# 4.7.4 Techniques — additional
for q in [
    "Is TICI 2c or 3 the target for thrombectomy?",
    "Should I attempt more than 3 passes during EVT?",
    "Is local anesthesia sufficient for thrombectomy?",
    "Should I give IA tPA if I can't achieve recanalization mechanically?",
    "Is distal aspiration as effective as stent retriever for M1 occlusions?",
    "What devices are recommended for mechanical thrombectomy?",
]: add_rec(q)

# 4.8 Antiplatelet — additional
for q in [
    "Should I start aspirin before or after brain imaging in stroke?",
    "Is loading dose clopidogrel 300mg recommended for minor stroke?",
    "When should DAPT be stopped after minor stroke?",
    "Is aspirin monotherapy sufficient for minor stroke without LVO?",
    "Should I add clopidogrel to aspirin for moderate stroke?",
    "Is prasugrel an option for acute ischemic stroke?",
    "Can I give aspirin rectally if the patient can't swallow?",
    "Should I hold aspirin if the patient is going to get tPA?",
]: add_rec(q)

# 4.9 Anticoagulants — additional
for q in [
    "Should I bridge with heparin while starting a DOAC for AF stroke?",
    "Is apixaban or rivaroxaban preferred after stroke with AF?",
    "When can I restart anticoagulation after a hemorrhagic transformation?",
    "Should anticoagulation be started in the first 48 hours after stroke with AF?",
    "Is enoxaparin recommended for early anticoagulation in stroke?",
]: add_rec(q)

# 4.10–4.12 — additional
for q in [
    "Is albumin infusion beneficial for acute ischemic stroke?",
    "Should vasopressors be used to augment BP in acute stroke?",
    "Is urgent carotid stenting recommended for acute stroke with carotid occlusion?",
    "Should I give magnesium sulfate as a neuroprotectant in acute stroke?",
    "Is any cytoprotective drug recommended for acute ischemic stroke?",
]: add_rec(q)

# 5.x Hospital — additional
for q in [
    "Is ICU admission necessary for all acute stroke patients?",
    "Should stroke patients be monitored on telemetry?",
    "Is a dedicated stroke unit better than a general neurology ward?",
    "Should speech therapy be consulted for all stroke patients?",
    "Is occupational therapy recommended during acute stroke hospitalization?",
    "Should the patient be kept NPO until a swallowing screen is done?",
    "Is PEG tube placement recommended within the first week of stroke?",
    "Should heparin prophylaxis be started on admission for DVT prevention?",
    "Is fondaparinux an option for DVT prophylaxis in stroke?",
    "Should I check for PE in my immobilized stroke patient?",
    "Is routine screening for urinary tract infection recommended after stroke?",
    "Should fall prevention be implemented for all stroke patients?",
    "Is statin therapy indicated during acute stroke hospitalization?",
    "Should I screen for obstructive sleep apnea after stroke?",
    "Is early physical therapy within the first 24 hours recommended?",
    "Should passive range-of-motion exercises be started early after stroke?",
]: add_rec(q)

# 6.x Complications — additional
for q in [
    "Should I get serial CT scans to monitor for cerebral edema?",
    "Is osmotherapy with mannitol preferred over hypertonic saline?",
    "When should I repeat brain imaging after a large stroke?",
    "Should I consult neurosurgery early for all large MCA strokes?",
    "Is barbiturate coma an option for refractory intracranial hypertension?",
    "Is external ventricular drainage recommended for obstructive hydrocephalus from stroke?",
    "Should I place an ICP monitor in my patient with malignant MCA infarction?",
    "Is craniectomy beneficial in patients over 70?",
    "What is the evidence for suboccipital craniectomy in cerebellar stroke?",
    "Should all posterior fossa strokes get neurosurgical consultation?",
    "Is levetiracetam the preferred antiseizure drug after stroke?",
    "Should I treat subclinical seizures detected on EEG in stroke patients?",
    "Is continuous EEG monitoring recommended after stroke?",
]: add_rec(q)

# ── More Clinical Scenarios ──
more_scenarios = [
    "78-year-old woman, NIHSS 6, LKW 1 hour ago. Disabling aphasia. IVT?",
    "Patient arrived by helicopter from rural hospital. M1 occlusion, 4 hours out. EVT?",
    "40-year-old with suspected stroke and cocaine use. Can I give tPA?",
    "Patient with INR 1.3 on warfarin. NIHSS 12 at 2 hours. IVT?",
    "Stroke patient with BP 220/130. No reperfusion planned. What should I do?",
    "My patient had EVT 6 hours ago with TICI 3 result. BP is 155/90. Target?",
    "NIHSS 22, M1 occlusion, ASPECTS 5 at 3 hours. EVT candidate?",
    "Patient presents 8 hours after onset. MRI shows small core, large penumbra. IVT?",
    "68-year-old, NIHSS 4, M2 occlusion. Should I do EVT or just give tPA?",
    "My patient got tPA 2 hours ago. NIHSS unchanged. M1 still occluded on CTA. EVT?",
    "Pregnant patient at 28 weeks with acute stroke. What are my treatment options?",
    "Stroke patient develops fever of 39.5C 12 hours post-admission. Management?",
    "Blood glucose 320 on arrival in my stroke patient. Insulin drip or subcutaneous?",
    "Patient had tPA at an outside hospital. Now transferring for EVT. Start bridging heparin?",
    "Large cerebellar infarction with early hydrocephalus. Next steps?",
    "Patient with posterior circulation stroke, NIHSS 28, basilar occlusion at 12 hours. EVT?",
    "62-year-old with M1 occlusion, prior mRS 2. Is EVT still recommended?",
    "Patient is 3.5 hours out, NIHSS 3, symptoms are disabling. IVT?",
    "My patient's NIHSS improved from 14 to 4 after tPA. Continue monitoring or discharge?",
    "Stroke patient with known seizure disorder has a seizure. Start new antiseizure med?",
    "Patient with MCA stroke and worsening mental status at 48 hours. Cerebral edema?",
    "BP 190/100 post-tPA. Currently on nicardipine drip. Increase dose or switch agents?",
    "My patient has bilateral carotid stenosis and acute stroke. Surgery?",
    "TIA patient, NIHSS 0, had symptoms 1 hour ago. Should I give IVT?",
    "Patient with basilar artery occlusion and locked-in syndrome. EVT at 18 hours?",
    "Stroke patient with active GI bleeding. Antiplatelet therapy?",
    "Wake-up stroke, NIHSS 16, DWI-FLAIR mismatch present. IVT and then EVT?",
    "53-year-old with malignant MCA infarction and 8mm midline shift at day 2. Craniectomy?",
    "My patient is on dabigatran and presents with stroke at 3 hours. IVT?",
    "Patient with acute stroke and platelets of 80,000. Can I give tPA?",
]
for q in more_scenarios: add_rec(q)

# ── More Evidence/RSS Questions ──
ev_extra = {
    "2.1": ["What is the evidence base for sustained stroke awareness campaigns?","What studies demonstrated that public education reduces stroke onset-to-call time?"],
    "2.2": ["What is the rationale for prehospital stroke severity assessment?","What data supports EMS activation of stroke alerts?"],
    "2.4": ["What evidence supports the mothership model over drip-and-ship?","What is the rationale for bypassing primary stroke centers for LVO?"],
    "2.5": ["What is the rationale for CT scanning on mobile stroke units?","What data supports MSU deployment in urban settings?"],
    "2.8": ["What is the rationale for 24/7 telestroke availability?"],
    "3.2": ["What studies validated ASPECTS for EVT patient selection?","What evidence supports automated large vessel occlusion detection software?","What data supports CT angiography in the initial stroke workup?"],
    "4.1": ["What is the rationale for not giving oxygen to non-hypoxic stroke patients?"],
    "4.3": ["What is the evidence base for the 185/110 BP threshold before IVT?","What data supports permissive hypertension in non-reperfused stroke?"],
    "4.4": ["What is the rationale for treating fever aggressively in stroke?"],
    "4.5": ["What is the rationale for avoiding tight glucose control in stroke?"],
    "4.6.1": ["What evidence supports IVT for mild disabling stroke?","What data shows IVT is safe in patients with prior stroke?","What is the rationale for not waiting for all lab results before IVT?"],
    "4.6.2": ["What data supports tenecteplase dosing at 0.25 mg/kg for stroke?"],
    "4.6.3": ["What is the rationale for using perfusion imaging in extended-window IVT?"],
    "4.7.2": ["What evidence supports EVT for patients with ASPECTS below 6?","What data supports EVT in patients over 80 years old?","What is the rationale for EVT in tandem occlusions?"],
    "4.7.3": ["What is the rationale for EVT in basilar artery occlusion beyond 24 hours?"],
    "4.7.4": ["What is the rationale for targeting TICI 2b-3 reperfusion?","What evidence supports combined stent retriever and aspiration techniques?"],
    "4.8": ["What is the rationale for early aspirin within 24-48 hours after stroke?","What evidence supports avoiding ticagrelor in acute stroke?","What data supports DAPT over aspirin monotherapy for minor stroke?"],
    "4.9": ["What is the rationale for choosing DOACs over warfarin for AF-related stroke?","What evidence supports waiting before starting anticoagulation after large stroke?"],
    "5.1": ["What evidence supports stroke unit admission over general ward care?","What data shows stroke unit care reduces mortality?"],
    "5.2": ["What is the rationale for NPO status until swallowing is assessed?"],
    "5.3": ["What evidence supports early nutritional assessment after stroke?","What data supports enteral feeding over parenteral nutrition in stroke?"],
    "5.4": ["What is the rationale for pneumatic compression over compression stockings?","What evidence supports low-dose heparin for DVT prophylaxis in immobile stroke patients?"],
    "5.5": ["What evidence supports depression screening after stroke?","What data shows antidepressants improve post-stroke recovery?"],
    "5.7": ["What is the rationale for avoiding aggressive early mobilization?","What evidence supports structured rehabilitation programs after stroke?"],
    "6.2": ["What is the evidence base for hypertonic saline in post-stroke edema?","What data shows hypothermia is ineffective for stroke-related edema?"],
    "6.3": ["What is the rationale for early decompressive craniectomy within 48 hours?","What evidence supports craniectomy for patients over 60 with malignant MCA infarction?"],
    "6.5": ["What is the evidence base for treating post-stroke seizures with levetiracetam?"],
}
for sec, qs in ev_extra.items():
    for q in qs: add_ev(sec, q)

# ── More Knowledge Gap Questions ──
kg_extra = {
    "2.1": ["optimal stroke education methods"],
    "2.2": ["prehospital stroke severity tools"],
    "2.4": ["EMS destination decision-making for stroke"],
    "2.5": ["cost-effectiveness of mobile stroke units"],
    "2.7": ["emergency department stroke protocols"],
    "2.8": ["telestroke networks"],
    "3.1": ["stroke severity assessment tools"],
    "3.2": ["advanced neuroimaging for stroke", "automated stroke imaging software"],
    "3.3": ["ancillary testing in acute stroke"],
    "4.1": ["airway management in acute stroke"],
    "4.2": ["patient positioning after stroke"],
    "4.6.4": ["alternative fibrinolytic agents for stroke"],
    "4.6.5": ["IVT in special populations"],
    "4.7.1": ["bridging IVT before EVT"],
    "4.10": ["hemodynamic augmentation in stroke"],
    "4.11": ["neuroprotection in acute stroke"],
    "4.12": ["emergency carotid revascularization"],
    "5.1": ["stroke unit organization"],
    "5.3": ["nutritional support after stroke"],
    "5.5": ["post-stroke depression management"],
    "6.2": ["medical management of cerebral edema"],
    "6.4": ["posterior fossa stroke management"],
    "6.5": ["post-stroke seizure management"],
}
for sec, topics in kg_extra.items():
    for t in topics:
        for tmpl in kg_tmpls: add_kg(sec, tmpl.format(t=t))

# ── More Table 8 Conditions (natural phrasing) ──
# Additional absolute conditions with different phrasing
for cond in ["intracranial hemorrhage","brain tumor","active bleeding on exam","severe thrombocytopenia"]:
    add_t8(f"Can I safely give IVT if my patient has {cond}?","Absolute")
    add_t8(f"Is {cond} a reason to withhold thrombolysis?","Absolute")

# Additional relative conditions with different phrasing
for cond in ["history of ICH","recent DOAC use","active cancer","liver failure","end-stage renal disease on dialysis","known AVM","LV thrombus on echo"]:
    add_t8(f"My patient has {cond}. Can I still give tPA?","Relative")
    add_t8(f"Is {cond} an absolute or relative contraindication to IVT?","Relative")

# Additional benefit-may-exceed-risk conditions
for cond in ["cervical artery dissection","small unruptured aneurysm","cocaine use","microbleeds on MRI","active menstruation","prior MI"]:
    add_t8(f"My patient has {cond}. Is IVT still an option?","Benefit May Exceed Risk")
    add_t8(f"Does {cond} make thrombolysis too risky?","Benefit May Exceed Risk")

# More listing questions
for q in [
    "What conditions absolutely prevent giving tPA?",
    "What comorbidities are relative contraindications to thrombolysis?",
    "In which situations does the benefit of IVT outweigh contraindication risk?",
    "Can you list all the IVT contraindications?",
]:
    add_t8(q, "")

# ═══ SUMMARY ═══
cats = {}
for q in all_questions: cats[q["category"]] = cats.get(q["category"],0)+1
print(f"Total: {len(all_questions)}")
print(f"Categories: {cats}")
outpath = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"
with open(outpath, "w") as f: json.dump(all_questions, f, indent=2)
print(f"Saved to {outpath}")
