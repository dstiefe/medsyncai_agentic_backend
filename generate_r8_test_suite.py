"""
Generate R8 test suite: 1,000 NEW questions testing the multi-agent pipeline.

R7 focused on breadth (all sections, all COR levels).
R8 focuses on depth — clinical scenarios, edge cases, and the failure
patterns discovered during R7 testing:

    - Clinical scenario questions (patient presentations)
    - Drug-specific questions (brand names, dosing)
    - Time-window questions (eligibility by hours)
    - Negative/contraindication questions
    - Cross-section questions (touches multiple sections)
    - More plain-language / layperson variants
    - Section-routing stress tests (ambiguous terms)

Categories:
    qa_recommendation: 350 (clinical scenario + section routing)
    qa_evidence: 200 (RSS retrieval)
    qa_knowledge_gap: 50 (KG retrieval)
    qa_semantic: 150 (plain language + clinical shorthand)
    qa_scope_gate: 100 (out-of-scope + boundary cases)
    qa_clarification: 150 (ambiguous + section-level ambiguity)
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations,
    load_guideline_knowledge,
)


def build_clinical_scenario_questions(recs_by_section, target=350):
    """Generate questions framed as clinical scenarios."""
    questions = []
    qid = 9001

    # Each entry: (question, expected_section, topic)
    scenarios = [
        # IVT eligibility (4.6.1)
        ("A 72-year-old presents with NIHSS 14 and last known well 2 hours ago. Is IVT indicated?", "4.6.1", "IVT eligibility"),
        ("Patient has mild symptoms, NIHSS 3, no disability. Should we give thrombolysis?", "4.6.1", "IVT non-disabling"),
        ("Can IVT be given to an 85-year-old with a disabling stroke?", "4.6.1", "IVT age"),
        ("The patient is on warfarin but INR is unknown. Can we start IVT?", "4.6.1", "IVT anticoagulation"),
        ("Should we wait for platelet count before giving alteplase?", "4.6.1", "IVT lab delay"),
        ("Patient had a stroke 3 weeks ago. Is repeat thrombolysis safe?", "4.6.1", "IVT prior stroke"),
        ("BP is 190/100. Can we give tPA?", "4.6.1", "IVT BP threshold"),
        ("The patient has a small subdural hematoma. Is IVT contraindicated?", "4.6.1", "IVT contraindication"),
        ("NIHSS 2, isolated hand weakness. Is thrombolysis recommended?", "4.6.1", "IVT mild deficit"),
        ("Patient is 16 years old with acute stroke. Can we give alteplase?", "4.6.1", "IVT pediatric"),

        # Tenecteplase (4.6.2)
        ("Should we use tenecteplase instead of alteplase?", "4.6.2", "TNK vs alteplase"),
        ("What dose of tenecteplase is recommended for stroke?", "4.6.2", "TNK dosing"),
        ("Is 0.4 mg/kg tenecteplase better than 0.25 mg/kg?", "4.6.2", "TNK high dose"),
        ("Can TNK be used as a substitute for tPA?", "4.6.2", "TNK selection"),

        # Extended window IVT (4.6.3)
        ("Patient woke up with stroke symptoms. Can we still give IVT?", "4.6.3", "wake-up stroke IVT"),
        ("It's been 7 hours since onset. Is thrombolysis still an option?", "4.6.3", "extended window IVT"),
        ("The MRI shows DWI-FLAIR mismatch. Can we give alteplase?", "4.6.3", "imaging-based IVT"),
        ("CT perfusion shows salvageable tissue at 20 hours. Is IVT reasonable?", "4.6.3", "late window IVT"),

        # Other fibrinolytics (4.6.4)
        ("Is streptokinase an option for acute stroke?", "4.6.4", "streptokinase"),
        ("Can we use intra-arterial thrombolysis?", "4.6.4", "IA thrombolysis"),
        ("Is sonothrombolysis effective for stroke treatment?", "4.6.4", "sonothrombolysis"),

        # IVT special circumstances (4.6.5)
        ("The stroke occurred during a cardiac catheterization. Can we give IVT?", "4.6.5", "procedural stroke"),
        ("Patient has sickle cell disease and had a stroke. Is alteplase indicated?", "4.6.5", "sickle cell IVT"),
        ("Is IVT recommended for central retinal artery occlusion?", "4.6.5", "CRAO IVT"),

        # Bridging IVT+EVT (4.7.1)
        ("Should we give IVT while arranging transfer for thrombectomy?", "4.7.1", "bridging IVT"),
        ("Can we skip IVT and go directly to EVT?", "4.7.1", "direct to EVT"),
        ("Should IVT be withheld if EVT is immediately available?", "4.7.1", "IVT before EVT"),

        # EVT (4.7.2)
        ("Patient has ICA occlusion, NIHSS 18, 3 hours from onset. Is EVT indicated?", "4.7.2", "EVT ICA"),
        ("M1 occlusion with NIHSS 8. Should we do thrombectomy?", "4.7.2", "EVT M1"),
        ("Is EVT reasonable for a proximal M2 occlusion?", "4.7.2", "EVT M2"),
        ("Can thrombectomy be done 18 hours after onset if perfusion imaging is favorable?", "4.7.2", "EVT extended window"),
        ("Patient has pre-existing disability (mRS 2). Is EVT still appropriate?", "4.7.2", "EVT prior disability"),
        ("ASPECTS score is 4. Is thrombectomy still beneficial?", "4.7.2", "EVT low ASPECTS"),

        # Posterior circulation EVT (4.7.3)
        ("Basilar artery is occluded. Should we do thrombectomy?", "4.7.3", "basilar EVT"),
        ("Patient has posterior circulation stroke with NIHSS 12. Is EVT recommended?", "4.7.3", "posterior EVT"),

        # EVT techniques (4.7.4)
        ("Should we use a stent retriever or aspiration first?", "4.7.4", "EVT technique"),
        ("Is general anesthesia or conscious sedation preferred during EVT?", "4.7.4", "anesthesia EVT"),
        ("What is the target door-to-groin puncture time?", "4.7.4", "door-to-groin"),
        ("Should we attempt rescue angioplasty if thrombectomy fails?", "4.7.4", "rescue therapy"),

        # Pediatric EVT (4.7.5)
        ("A 10-year-old has an M1 occlusion. Can we do thrombectomy?", "4.7.5", "pediatric EVT"),
        ("Is EVT safe in neonates?", "4.7.5", "neonatal EVT"),

        # Antiplatelet (4.8)
        ("When should aspirin be started after IVT?", "4.8", "aspirin timing"),
        ("Is dual antiplatelet therapy recommended for minor stroke?", "4.8", "DAPT minor stroke"),
        ("Should we use clopidogrel or aspirin after non-cardioembolic stroke?", "4.8", "clopidogrel vs aspirin"),
        ("Can ticagrelor be used instead of clopidogrel?", "4.8", "ticagrelor"),
        ("Are GP IIb/IIIa inhibitors recommended for acute stroke?", "4.8", "GP IIb/IIIa"),

        # Anticoagulation (4.9)
        ("Should heparin be started within 48 hours of stroke?", "4.9", "early anticoagulation"),
        ("Patient has AF and had a stroke. When should we start a DOAC?", "4.9", "DOAC AF stroke"),
        ("Is argatroban useful after acute stroke?", "4.9", "argatroban"),

        # BP management (4.3)
        ("BP is 200/110. How should we lower it before giving tPA?", "4.3", "BP before IVT"),
        ("What BP target should we maintain during thrombectomy?", "4.3", "BP during EVT"),
        ("Should we use labetalol or nicardipine for BP control?", "4.3", "BP drug choice"),
        ("Can we use clevidipine for blood pressure management in stroke?", "4.3", "clevidipine"),

        # Temperature (4.4)
        ("The patient has a fever of 39°C after stroke. How should we treat it?", "4.4", "fever management"),
        ("Is induced hypothermia beneficial after ischemic stroke?", "4.4", "hypothermia"),

        # Glucose (4.5)
        ("Blood glucose is 280 mg/dL. How should we manage it?", "4.5", "hyperglycemia"),
        ("Patient became hypoglycemic after stroke. What should we do?", "4.5", "hypoglycemia"),

        # Oxygen (4.1)
        ("SpO2 is 96%. Should we give supplemental oxygen?", "4.1", "supplemental oxygen"),
        ("Is hyperbaric oxygen therapy recommended for stroke?", "4.1", "hyperbaric oxygen"),

        # Head positioning (4.2)
        ("Should the head of bed be flat or elevated after stroke?", "4.2", "head positioning"),
        ("Does lying flat improve outcomes after AIS?", "4.2", "flat positioning"),

        # Imaging (3.2)
        ("Do we need CTA before starting thrombolysis?", "3.2", "CTA before IVT"),
        ("Should we get perfusion imaging for all stroke patients?", "3.2", "perfusion imaging"),
        ("Is MRI better than CT for acute stroke diagnosis?", "3.2", "CT vs MRI"),
        ("What imaging is needed for a wake-up stroke?", "3.2", "wake-up imaging"),

        # Lab testing (3.3)
        ("Do we need to wait for CBC results before giving tPA?", "3.3", "labs before IVT"),
        ("Which blood tests are required before starting thrombolysis?", "3.3", "required labs"),
        ("Can IVT be started before the INR result comes back?", "3.3", "INR before IVT"),

        # Stroke scales (3.1)
        ("Which stroke severity scale should we use?", "3.1", "stroke scale"),
        ("How do we assess stroke severity in the emergency department?", "3.1", "NIHSS assessment"),

        # EMS / prehospital (2.2-2.5)
        ("Should the ambulance take the patient to the nearest hospital or a stroke center?", "2.4", "EMS destination"),
        ("When should helicopter transport be used for stroke patients?", "2.4", "air transport"),
        ("Is a mobile stroke unit better than standard ambulance transport?", "2.5", "MSU vs ambulance"),
        ("How should stroke be identified in the field by EMS?", "2.2", "EMS stroke ID"),
        ("Should EMS prenotify the receiving hospital?", "2.3", "prehospital notification"),

        # Telestroke (2.8)
        ("Can IVT decisions be made via telemedicine?", "2.8", "telestroke IVT"),
        ("Is video-based stroke assessment as reliable as in-person?", "2.8", "telestroke assessment"),

        # Stroke unit (5.1)
        ("Should all stroke patients be admitted to a dedicated stroke unit?", "5.1", "stroke unit"),
        ("Is ICU admission necessary after IVT?", "5.1", "ICU after IVT"),

        # Dysphagia (5.2)
        ("Should all stroke patients be screened for swallowing problems?", "5.2", "dysphagia screening"),
        ("When can the patient start eating after a stroke?", "5.2", "oral intake timing"),

        # DVT prevention (5.4)
        ("Should we use compression stockings for DVT prevention after stroke?", "5.4", "compression stockings"),
        ("Is prophylactic heparin recommended after stroke?", "5.4", "prophylactic heparin"),
        ("When should intermittent pneumatic compression be started?", "5.4", "IPC timing"),

        # Depression (5.5)
        ("Should we screen for depression after stroke?", "5.5", "depression screening"),
        ("Are SSRIs recommended for post-stroke depression?", "5.5", "SSRI treatment"),

        # Rehab (5.7)
        ("How soon after stroke should physical therapy begin?", "5.7", "early rehab"),
        ("Is very early mobilization beneficial or harmful?", "5.7", "early mobilization"),

        # Complications (6.x)
        ("How do we monitor for brain swelling after a large stroke?", "6.1", "brain swelling monitoring"),
        ("Is mannitol recommended for cerebral edema?", "6.2", "osmotic therapy"),
        ("When should decompressive craniectomy be performed?", "6.3", "craniectomy timing"),
        ("Patient under 60 with malignant MCA infarction. Is surgery indicated?", "6.3", "craniectomy young"),
        ("Should we decompress a cerebellar infarction with hydrocephalus?", "6.4", "cerebellar surgery"),
        ("Is prophylactic antiseizure medication recommended after stroke?", "6.5", "seizure prophylaxis"),
        ("Patient had a seizure 3 days after stroke. How should we treat it?", "6.5", "seizure treatment"),

        # Neuroprotection (4.11)
        ("Are there any neuroprotective drugs recommended for AIS?", "4.11", "neuroprotection"),
        ("Is magnesium sulfate beneficial after stroke?", "4.11", "magnesium"),

        # Volume expansion (4.10)
        ("Should albumin infusion be used after stroke?", "4.10", "albumin"),
        ("Is hemodilution beneficial in acute stroke?", "4.10", "hemodilution"),

        # Carotid (4.12)
        ("Should emergency carotid endarterectomy be performed after stroke?", "4.12", "emergency CEA"),

        # Other in-hospital (5.6)
        ("Should prophylactic antibiotics be given after stroke?", "5.6", "prophylactic antibiotics"),
        ("Is fluoxetine recommended for motor recovery after stroke?", "5.6", "fluoxetine recovery"),
        ("Should urinary catheters be avoided in stroke patients?", "5.6", "urinary catheter"),

        # Nutrition (5.3)
        ("When should tube feeding be started for stroke patients who can't swallow?", "5.3", "tube feeding"),
        ("Should nasogastric or PEG tube be used for nutrition?", "5.3", "enteral route"),

        # Quality/registries (2.10)
        ("Should hospitals participate in stroke quality registries?", "2.10", "stroke registries"),

        # Stroke awareness (2.1)
        ("How effective are public stroke education campaigns?", "2.1", "stroke education"),
    ]

    for q_text, expected_section, topic in scenarios:
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_recommendation",
            "question": q_text,
            "expected_section": expected_section,
            "topic": topic,
        })
        qid += 1

    # Generate COR-specific variants for each scenario
    cor_templates = [
        "What is the COR for {topic}?",
        "How strong is the recommendation for {topic}?",
        "What class of recommendation applies to {topic}?",
    ]
    for q_text, expected_section, topic in scenarios:
        if len(questions) >= target:
            break
        tmpl = cor_templates[len(questions) % len(cor_templates)]
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_recommendation",
            "question": tmpl.format(topic=topic),
            "expected_section": expected_section,
            "topic": topic,
        })
        qid += 1

    # Additional clinical variants
    clinical_variants = [
        "A patient presenting with {topic} — what does the guideline recommend?",
        "Per the 2026 AIS guideline, what is recommended for {topic}?",
        "What should be done regarding {topic} in acute ischemic stroke?",
        "Is there a specific guideline recommendation about {topic}?",
        "What is the standard of care for {topic} in AIS?",
    ]
    for q_text, expected_section, topic in scenarios:
        if len(questions) >= target:
            break
        tmpl = clinical_variants[len(questions) % len(clinical_variants)]
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_recommendation",
            "question": tmpl.format(topic=topic),
            "expected_section": expected_section,
            "topic": topic,
        })
        qid += 1

    # Context-specific variants
    context_variants = [
        "For a patient with {topic}, what is the guideline recommendation?",
        "What is the COR and LOE for {topic}?",
        "How does the guideline address {topic} in the acute setting?",
        "Is {topic} considered standard of care per the AIS guideline?",
        "What does the 2026 guideline say about {topic}?",
        "Should {topic} be considered in AIS management?",
    ]
    for q_text, expected_section, topic in scenarios:
        if len(questions) >= target:
            break
        tmpl = context_variants[len(questions) % len(context_variants)]
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_recommendation",
            "question": tmpl.format(topic=topic),
            "expected_section": expected_section,
            "topic": topic,
        })
        qid += 1

    return questions[:target]


def build_evidence_questions_r8(sections_data, target=200):
    """Generate evidence questions with more clinical detail."""
    questions = []
    qid = 9501

    section_topics = {
        "2.1": "stroke awareness", "2.2": "EMS stroke recognition",
        "2.3": "prehospital management", "2.4": "EMS transport decisions",
        "2.5": "mobile stroke units", "2.7": "emergency evaluation",
        "2.8": "telestroke", "2.9": "stroke systems of care",
        "3.1": "stroke severity assessment", "3.2": "stroke imaging",
        "3.3": "laboratory testing", "4.1": "oxygen management",
        "4.2": "head positioning", "4.3": "blood pressure management",
        "4.4": "temperature management", "4.5": "glucose management",
        "4.6.1": "IVT", "4.6.2": "tenecteplase",
        "4.6.3": "extended window IVT", "4.6.4": "other fibrinolytics",
        "4.6.5": "IVT special circumstances", "4.7.1": "bridging IVT and EVT",
        "4.7.2": "EVT", "4.7.3": "posterior circulation EVT",
        "4.7.4": "EVT techniques", "4.7.5": "pediatric EVT",
        "4.8": "antiplatelet therapy", "4.9": "anticoagulation",
        "4.10": "volume expansion", "4.11": "neuroprotection",
        "4.12": "carotid interventions",
        "5.1": "stroke units", "5.2": "dysphagia screening",
        "5.3": "nutrition", "5.4": "DVT prophylaxis",
        "5.5": "post-stroke depression", "5.6": "in-hospital management",
        "5.7": "rehabilitation",
        "6.1": "cerebral edema monitoring", "6.2": "osmotic therapy",
        "6.3": "decompressive craniectomy", "6.4": "cerebellar surgery",
        "6.5": "seizure management",
    }

    templates = [
        "What evidence supports {topic}?",
        "What clinical trials inform the {topic} recommendation?",
        "What is the rationale behind the guideline's position on {topic}?",
        "What data led to the recommendation on {topic}?",
        "Why does the guideline recommend what it does regarding {topic}?",
    ]

    for sec, topic in section_topics.items():
        rss = sections_data.get(sec, {}).get("rss", [])
        if not rss:
            continue
        for i in range(min(5, max(2, len(rss) // 2))):
            if len(questions) >= target:
                break
            tmpl = templates[i % len(templates)]
            questions.append({
                "id": f"QA-{qid}",
                "section": sec,
                "category": "qa_evidence",
                "question": tmpl.format(topic=topic),
                "expected_section": sec,
                "expected_type": "evidence",
                "topic": topic,
            })
            qid += 1

    # Second pass: more templates to hit target
    extra_templates = [
        "What is the scientific basis for the {topic} recommendation?",
        "What RCTs shaped the guideline's stance on {topic}?",
        "What studies underpin the recommendation on {topic}?",
        "Is there strong evidence behind the {topic} guideline?",
        "What level of evidence supports {topic}?",
    ]
    for sec, topic in section_topics.items():
        rss = sections_data.get(sec, {}).get("rss", [])
        if not rss:
            continue
        for i, tmpl in enumerate(extra_templates):
            if len(questions) >= target:
                break
            questions.append({
                "id": f"QA-{qid}",
                "section": sec,
                "category": "qa_evidence",
                "question": tmpl.format(topic=topic),
                "expected_section": sec,
                "expected_type": "evidence",
                "topic": topic,
            })
            qid += 1

    return questions[:target]


def build_knowledge_gap_questions_r8(sections_data, target=50):
    """Generate knowledge gap questions for clinical sections only."""
    questions = []
    qid = 9801

    # Only clinical sections (skip preamble 1.x)
    _CLINICAL_SECTIONS = [
        "2.1", "2.2", "2.3", "2.4", "2.5", "2.7", "2.8", "2.9", "2.10",
        "3.1", "3.2", "3.3",
        "4.1", "4.2", "4.3", "4.4", "4.5",
        "4.6.1", "4.6.2", "4.6.3", "4.6.4", "4.6.5",
        "4.7.1", "4.7.2", "4.7.3", "4.7.4", "4.7.5",
        "4.8", "4.9", "4.10", "4.11", "4.12",
        "5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7",
        "6.1", "6.2", "6.3", "6.4", "6.5",
    ]

    templates = [
        "What research questions remain unanswered about {title}?",
        "What are the gaps in current evidence for {title}?",
        "What future studies are needed regarding {title}?",
        "What remains unclear about {title}?",
        "What aspects of {title} need further investigation?",
    ]

    for sec in _CLINICAL_SECTIONS:
        if len(questions) >= target:
            break
        sec_data = sections_data.get(sec, {})
        title = sec_data.get("sectionTitle", sec).lower()
        if not title or title == sec:
            continue
        tmpl = templates[len(questions) % len(templates)]
        questions.append({
            "id": f"QA-{qid}",
            "section": sec,
            "category": "qa_knowledge_gap",
            "question": tmpl.format(title=title, sec=sec),
            "expected_section": sec,
            "expected_type": "knowledge_gap",
            "topic": title,
        })
        qid += 1

    return questions[:target]


def build_semantic_questions_r8(target=150):
    """Generate more plain-language and clinical shorthand questions."""
    questions = []
    qid = 9901

    # Plain language → expected section
    semantic_cases = [
        # Medical shorthand
        ("tPA for a big stroke?", "4.6.1", "IVT for severe stroke"),
        ("TNK dose for stroke?", "4.6.2", "tenecteplase dosing"),
        ("Can we pull the clot out?", "4.7.2", "mechanical thrombectomy"),
        ("ASA after stroke?", "4.8", "aspirin after stroke"),
        ("DAPT for TIA?", "4.8", "dual antiplatelet TIA"),
        ("BP meds before tPA?", "4.3", "BP before IVT"),
        ("IPC for DVT?", "5.4", "pneumatic compression"),
        ("NPO until swallow eval?", "5.2", "dysphagia screening"),
        ("NG tube or PEG?", "5.3", "enteral feeding route"),
        ("SSRI for mood after stroke?", "5.5", "post-stroke depression"),
        ("Stat CT and CTA?", "3.2", "emergency imaging"),
        ("CBC before tPA?", "3.3", "labs before thrombolysis"),
        ("Door-to-needle under 60 minutes?", "4.6.1", "DTN time"),
        ("Door-to-groin target?", "4.7.4", "DTG time"),

        # Nurse/family plain language
        ("My dad had a stroke, should he lie flat?", "4.2", "head position family"),
        ("Can my mom eat after her stroke?", "5.2", "eating after stroke"),
        ("Does the patient need a breathing tube?", "4.1", "intubation need"),
        ("Why does the patient have a fever after the stroke?", "4.4", "post-stroke fever"),
        ("The blood sugar is very high, is that bad for the stroke?", "4.5", "hyperglycemia concern"),
        ("Can the blood clot come back after treatment?", "4.8", "recurrent stroke prevention"),
        ("Is there a shot that can dissolve the clot?", "4.6.1", "thrombolysis layperson"),
        ("The doctor mentioned removing the clot with a wire. Is that safe?", "4.7.2", "EVT layperson"),
        ("Should we keep the blood pressure high or low?", "4.3", "BP direction"),
        ("When can rehabilitation start?", "5.7", "rehab timing"),
        ("Is there a risk of seizures after stroke?", "6.5", "seizure risk"),
        ("The brain is swelling. Do they need surgery?", "6.3", "craniectomy need"),
        ("Should the patient get blood thinners?", "4.9", "anticoagulation layperson"),
        ("Is there a better hospital we should transfer to?", "2.4", "transfer decision"),
        ("Can a specialist look at the patient over video?", "2.8", "telemedicine"),
        ("Should the ambulance go to the closest hospital?", "2.4", "EMS routing"),

        # Clinical abbreviations
        ("LVO on CTA. EVT candidate?", "4.7.2", "LVO EVT"),
        ("NIHSS 22, M1 occl, LKW 4h. Thrombectomy?", "4.7.2", "EVT clinical"),
        ("ASPECTS 7, ICA-T. EVT within 6h?", "4.7.2", "EVT ASPECTS"),
        ("tPA started at OSH. Transfer for EVT?", "4.7.1", "bridging transfer"),
        ("DWI+ FLAIR- unknown onset. tPA?", "4.6.3", "DWI-FLAIR mismatch"),
        ("BA occlusion NIHSS 14. EVT?", "4.7.3", "basilar EVT"),
        ("SBP 195 pre-tPA. Treat to what target?", "4.3", "BP target pre-IVT"),
        ("HbA1c high, glucose 350. Insulin drip?", "4.5", "glucose management"),
        ("Post-tPA SBP 210. Manage?", "4.3", "post-IVT BP"),
        ("Hemicraniectomy for MCA territory infarct <60y?", "6.3", "craniectomy criteria"),
    ]

    for q_text, expected_section, topic in semantic_cases:
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_semantic",
            "question": q_text,
            "expected_section": expected_section,
            "topic": topic,
        })
        qid += 1

    # Pad with "how would you explain" variants
    explain_prefixes = [
        "In simple terms, ",
        "For a family member: ",
        "Can you explain — ",
    ]
    base_idx = 0
    while len(questions) < target:
        base = semantic_cases[base_idx % len(semantic_cases)]
        prefix = explain_prefixes[len(questions) % len(explain_prefixes)]
        questions.append({
            "id": f"QA-{qid}",
            "section": base[1],
            "category": "qa_semantic",
            "question": prefix + base[0],
            "expected_section": base[1],
            "topic": base[2],
        })
        qid += 1
        base_idx += 1

    return questions[:target]


def build_scope_gate_questions_r8(target=100):
    """Generate out-of-scope and boundary case questions."""
    questions = []
    qid = 10101

    # Clear out-of-scope
    out_of_scope = [
        ("What is the best treatment for hemorrhagic stroke?", "ICH"),
        ("How should subarachnoid hemorrhage be managed?", "SAH"),
        ("What statin dose prevents recurrent stroke?", "secondary prevention statin"),
        ("How to manage post-stroke spasticity at 6 months?", "chronic spasticity"),
        ("When should PFO closure be done after cryptogenic stroke?", "PFO closure"),
        ("What is the recommendation for carotid screening in asymptomatic patients?", "asymptomatic carotid"),
        ("How should post-stroke sleep apnea be managed?", "sleep apnea"),
        ("When can a patient drive after a stroke?", "driving after stroke"),
        ("How to manage central post-stroke pain syndrome?", "central pain"),
        ("What is the recommended long-term antihypertensive regimen after stroke?", "long-term BP"),
        ("How should post-stroke cognitive decline be managed?", "cognitive decline"),
        ("What exercise program is best for stroke recovery at 1 year?", "chronic rehab"),
        ("How to manage post-stroke shoulder subluxation?", "shoulder subluxation"),
        ("Should patients take omega-3 supplements after stroke?", "supplements"),
        ("What is the best diet for secondary stroke prevention?", "dietary prevention"),
        ("How to treat post-stroke erectile dysfunction?", "sexual dysfunction"),
        ("When should anticoagulation resume after hemorrhagic transformation?", "chronic anticoag"),
        ("What is the optimal timing for carotid endarterectomy in stable patients?", "elective CEA"),
        ("How to manage post-stroke bladder dysfunction long-term?", "chronic bladder"),
        ("What vocational rehabilitation is available after stroke?", "vocational rehab"),
        ("How should cerebral amyloid angiopathy be managed?", "CAA management"),
        ("What is the treatment for cerebral venous thrombosis?", "CVT"),
        ("How should Takayasu arteritis be treated?", "vasculitis"),
        ("What is the management of fibromuscular dysplasia?", "FMD"),
        ("How to treat CADASIL?", "CADASIL"),
    ]

    for q_text, topic in out_of_scope:
        questions.append({
            "id": f"QA-{qid}",
            "section": "out_of_scope",
            "category": "qa_scope_gate",
            "question": q_text,
            "expected_scope_gate": True,
            "topic": topic,
        })
        qid += 1

    # Boundary: AIS-flavored but out-of-scope
    boundary = [
        ("What is the guideline for managing moyamoya-related stroke?", "moyamoya"),
        ("How should stroke from infective endocarditis be managed long-term?", "endocarditis chronic"),
        ("What is the recommendation for treating RCVS?", "RCVS"),
        ("How should stroke in the setting of COVID-19 be managed differently?", "COVID stroke"),
        ("What about genetic testing after stroke?", "genetic testing"),
    ]
    for q_text, topic in boundary:
        questions.append({
            "id": f"QA-{qid}",
            "section": "out_of_scope",
            "category": "qa_scope_gate",
            "question": q_text,
            "expected_scope_gate": True,
            "topic": topic,
        })
        qid += 1

    # Pad with "Per the AIS guideline" variants
    while len(questions) < target:
        base = out_of_scope[len(questions) % len(out_of_scope)]
        questions.append({
            "id": f"QA-{qid}",
            "section": "out_of_scope",
            "category": "qa_scope_gate",
            "question": "Per the AIS guideline, " + base[0][0].lower() + base[0][1:],
            "expected_scope_gate": True,
            "topic": base[1],
        })
        qid += 1

    return questions[:target]


def build_clarification_questions_r8(recs_by_section, target=150):
    """Generate questions that should trigger clarification — hardcoded rules,
    generic ambiguity, or section-level ambiguity."""
    questions = []
    qid = 10301

    # Hardcoded rule triggers (should trigger M2 or IVT clarification)
    hardcoded = [
        ("Is EVT recommended for M2 occlusion?", "4.7.2", "M2 clarification"),
        ("Should we do thrombectomy for M2?", "4.7.2", "M2 EVT"),
        ("Is IVT recommended for this patient?", "4.6.1", "IVT eligibility"),
        ("Can we give thrombolysis?", "4.6.1", "IVT general"),
        ("Is tPA indicated?", "4.6.1", "IVT tPA"),
        ("Is alteplase recommended?", "4.6.1", "IVT alteplase"),
    ]

    for q_text, expected_section, topic in hardcoded:
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section,
            "category": "qa_clarification",
            "question": q_text,
            "expected_section": expected_section,
            "expected_clarification_possible": True,
            "topic": topic,
        })
        qid += 1

    # Section-level ambiguity (questions vague enough to span sections)
    ambiguous = [
        ("What does the guideline say about stroke drugs?", None, "vague drugs"),
        ("What is recommended for stroke treatment?", None, "vague treatment"),
        ("How should stroke be managed?", None, "vague management"),
        ("What medications are used for stroke?", None, "vague medications"),
        ("What procedures are recommended for stroke?", None, "vague procedures"),
        ("What is the guideline position on stroke prevention in hospital?", None, "vague inpatient prevention"),
        ("How should complications be managed?", None, "vague complications"),
        ("What monitoring is needed after stroke?", None, "vague monitoring"),
    ]

    for q_text, expected_section, topic in ambiguous:
        questions.append({
            "id": f"QA-{qid}",
            "section": expected_section or "multi",
            "category": "qa_clarification",
            "question": q_text,
            "expected_section": expected_section,
            "expected_clarification_possible": True,
            "topic": topic,
        })
        qid += 1

    # Multi-COR section questions (should trigger generic ambiguity)
    multi_cor_sections = {}
    for section, recs_list in recs_by_section.items():
        cors = set(r["cor"] for r in recs_list)
        if len(cors) >= 2:
            titles = set(r.get("sectionTitle", "") for r in recs_list)
            title = list(titles)[0] if titles else section
            multi_cor_sections[section] = title

    templates = [
        "What is the recommendation for {title}?",
        "What does the guideline say about {title}?",
        "Is {title} recommended?",
        "What are all the recommendations regarding {title}?",
        "Can you summarize the recommendations for {title}?",
    ]

    for section, title in multi_cor_sections.items():
        for i, tmpl in enumerate(templates):
            if len(questions) >= target:
                break
            questions.append({
                "id": f"QA-{qid}",
                "section": section,
                "category": "qa_clarification",
                "question": tmpl.format(title=title.lower()),
                "expected_section": section,
                "expected_clarification_possible": True,
                "topic": title.lower(),
            })
            qid += 1

    return questions[:target]


def main():
    recs = load_recommendations()
    gk = load_guideline_knowledge()
    sections_data = gk.get("sections", {})

    recs_by_section = {}
    for r in recs:
        recs_by_section.setdefault(r["section"], []).append(r)

    print("Generating R8 test suite...")

    rec_qs = build_clinical_scenario_questions(recs_by_section, target=406)
    print(f"  Recommendation: {len(rec_qs)}")

    ev_qs = build_evidence_questions_r8(sections_data, target=200)
    print(f"  Evidence: {len(ev_qs)}")

    kg_qs = build_knowledge_gap_questions_r8(sections_data, target=50)
    print(f"  Knowledge Gap: {len(kg_qs)}")

    sem_qs = build_semantic_questions_r8(target=150)
    print(f"  Semantic: {len(sem_qs)}")

    scope_qs = build_scope_gate_questions_r8(target=100)
    print(f"  Scope Gate: {len(scope_qs)}")

    clar_qs = build_clarification_questions_r8(recs_by_section, target=150)
    print(f"  Clarification: {len(clar_qs)}")

    all_qs = rec_qs + ev_qs + kg_qs + sem_qs + scope_qs + clar_qs
    all_qs = all_qs[:1000]
    print(f"\n  TOTAL: {len(all_qs)}")

    output = {"questions": all_qs}
    out_path = os.path.join(
        "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff",
        "qa_round8_test_suite.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
