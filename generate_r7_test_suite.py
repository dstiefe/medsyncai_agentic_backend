"""
Generate R7 test suite: 1,000 questions testing the new multi-agent pipeline.

Categories:
    - qa_recommendation: 400 questions (verbatim rec + section routing)
    - qa_evidence: 300 questions (RSS retrieval + section routing)
    - qa_knowledge_gap: 100 questions (KG retrieval + deterministic response)
    - qa_semantic: 100 questions (plain language → correct section via semantic search)
    - qa_scope_gate: 50 questions (out-of-scope → explicit refusal)
    - qa_clarification: 50 questions (ambiguous → clarification triggered)

Coverage:
    - All 45 sections with recs
    - All COR levels (1, 2a, 2b, 3:No Benefit, 3:Harm)
    - Plain language / clinical shorthand / drug brand names
    - Multi-rec sections with conflicting COR
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations,
    load_guideline_knowledge,
)


def build_recommendation_questions(recs_by_section, target=400):
    """Generate recommendation questions for every section and COR level."""
    questions = []
    qid = 7001

    # Templates per COR level
    templates = {
        "1": [
            "What is recommended for {topic}?",
            "Is {topic} recommended per the guideline?",
            "What does the guideline say about {topic}?",
            "Should {topic} be done according to the AIS guideline?",
        ],
        "2a": [
            "Is {topic} reasonable according to the guideline?",
            "What is the recommendation regarding {topic}?",
            "Does the guideline support {topic}?",
            "Is it reasonable to {topic_verb}?",
        ],
        "2b": [
            "May {topic} be considered per the guideline?",
            "What is the strength of recommendation for {topic}?",
            "Is there a recommendation about {topic}?",
            "How strong is the recommendation for {topic}?",
        ],
        "3:No Benefit": [
            "Is {topic} recommended per the guideline?",
            "Does the guideline recommend against {topic}?",
            "What does the guideline say about {topic}?",
            "Is there benefit to {topic} according to the guideline?",
        ],
        "3:Harm": [
            "Is {topic} harmful according to the guideline?",
            "Does the guideline recommend against {topic}?",
            "What is the guideline position on {topic}?",
            "Is {topic} contraindicated per the AIS guideline?",
        ],
    }

    # Section-specific topic phrases
    section_topics = {
        "2.1": ["public stroke education programs", "stroke awareness campaigns", "stroke recognition education", "public education on stroke warning signs"],
        "2.2": ["EMS activation for stroke", "prehospital stroke triage", "EMS stroke assessment"],
        "2.3": ["prehospital stroke management", "field treatment of stroke", "EMS management of AIS patients", "prehospital blood pressure treatment", "supplemental oxygen in the field", "prehospital notification to receiving hospital", "helicopter transport for stroke"],
        "2.4": ["EMS destination for stroke patients", "bypassing closer hospitals for stroke centers", "direct transport to EVT-capable centers", "EMS routing decisions for stroke", "interhospital transfer for EVT"],
        "2.5": ["mobile stroke units for IVT", "MSU for prehospital thrombolysis", "mobile stroke unit deployment", "prehospital CT scanning"],
        "2.6": ["hospital stroke capabilities", "stroke center requirements"],
        "2.7": ["emergency stroke evaluation", "initial assessment of suspected stroke", "emergency department stroke workup", "rapid neurological assessment", "blood glucose testing in suspected stroke"],
        "2.8": ["telemedicine for stroke", "telestroke consultation", "remote stroke assessment", "video-based stroke evaluation", "telestroke for thrombolysis decisions", "robot-assisted telemedicine for stroke", "telemedicine-guided IVT"],
        "2.9": ["stroke center certification", "stroke care organization", "quality improvement for stroke care", "stroke team coordination", "integration of stroke care components", "stroke registry participation", "stroke center performance metrics", "primary stroke center standards"],
        "2.10": ["stroke registries", "stroke quality improvement", "risk-standardized mortality rates"],
        "3.1": ["stroke severity scales", "NIHSS assessment", "validated stroke scales"],
        "3.2": ["brain imaging for stroke", "CT for acute stroke", "CTA for vessel occlusion", "MRI for stroke", "perfusion imaging", "CT angiography in stroke workup", "imaging for wake-up stroke", "multimodal imaging for extended window", "vascular imaging in suspected LVO", "imaging before thrombolysis", "pediatric stroke imaging"],
        "3.3": ["lab testing before IVT", "blood work before thrombolysis", "routine laboratory tests in stroke"],
        "4.1": ["oxygen supplementation in stroke", "airway management in AIS", "supplemental oxygen for AIS", "hyperbaric oxygen for stroke", "intubation in stroke patients", "high-flow nasal cannula in stroke"],
        "4.2": ["head positioning in stroke", "flat vs elevated head of bed", "lying flat after stroke"],
        "4.3": ["blood pressure management in stroke", "BP targets during IVT", "BP targets during EVT", "permissive hypertension in stroke", "antihypertensive treatment in AIS", "blood pressure lowering before thrombolysis", "BP management 24-48 hours after stroke", "labetalol for stroke BP", "nicardipine for stroke", "clevidipine for stroke BP"],
        "4.4": ["temperature management in stroke", "fever treatment in AIS", "therapeutic hypothermia for stroke"],
        "4.5": ["blood glucose management in stroke", "hyperglycemia treatment in AIS", "hypoglycemia in stroke patients"],
        "4.6.1": ["IVT for acute ischemic stroke", "thrombolysis eligibility", "IVT for disabling stroke", "IVT for non-disabling stroke", "thrombolysis within 3 hours", "IVT within 4.5 hours", "alteplase dosing", "IVT for patients on anticoagulants", "thrombolysis for patients over 80", "IVT for mild stroke", "delaying IVT for lab results", "IVT for patients on aspirin", "thrombolysis blood pressure requirements", "IVT for patients with prior stroke"],
        "4.6.2": ["tenecteplase vs alteplase", "choice of thrombolytic agent", "tenecteplase for AIS"],
        "4.6.3": ["extended window thrombolysis", "IVT beyond 4.5 hours", "imaging-based IVT selection"],
        "4.6.4": ["sonothrombolysis", "other fibrinolytics for stroke", "urokinase for stroke", "streptokinase for stroke", "defibrinogenating agents for stroke", "desmoteplase for stroke", "ancrod for stroke"],
        "4.6.5": ["IVT during cardiac catheterization", "thrombolysis in procedural stroke", "IVT for stroke during angiography"],
        "4.7.1": ["IVT before EVT", "bridging therapy", "thrombolysis plus thrombectomy"],
        "4.7.2": ["EVT eligibility criteria", "thrombectomy for LVO", "EVT for M1 occlusion", "EVT for ICA occlusion", "EVT for M2 occlusion", "thrombectomy time window", "EVT within 6 hours", "EVT 6-24 hours"],
        "4.7.3": ["EVT for basilar artery occlusion", "posterior circulation thrombectomy", "basilar artery thrombectomy"],
        "4.7.4": ["stent retriever thrombectomy", "aspiration thrombectomy", "endovascular techniques for stroke", "anesthesia during EVT", "blood pressure management during EVT", "tenecteplase before EVT", "direct aspiration vs stent retriever", "EVT procedural techniques", "door-to-groin time targets"],
        "4.7.5": ["EVT in pediatric patients", "pediatric thrombectomy", "endovascular treatment in children"],
        "4.8": ["aspirin after stroke", "dual antiplatelet therapy after stroke", "clopidogrel after stroke", "ticagrelor for stroke", "antiplatelet therapy timing", "aspirin plus clopidogrel for minor stroke", "DAPT for TIA", "antiplatelet after IVT", "GP IIb/IIIa inhibitors in stroke", "cangrelor for stroke", "vorapaxar for stroke", "aspirin for all stroke patients", "antiplatelet for cardioembolic stroke", "antiplatelet for arterial dissection", "cilostazol for stroke", "antiplatelet for intracranial stenosis", "triple antiplatelet therapy", "clopidogrel over aspirin for stroke"],
        "4.9": ["anticoagulation after stroke", "heparin for AIS", "early anticoagulation in stroke", "anticoagulation for atrial fibrillation and stroke", "argatroban for stroke", "LMWH for acute stroke"],
        "5.1": ["stroke unit admission", "organized stroke care", "dedicated stroke units"],
        "5.2": ["dysphagia screening after stroke", "swallowing assessment", "oral hygiene in stroke", "tube feeding for stroke patients", "speech pathology assessment", "aspiration prevention"],
        "5.3": ["nutrition after stroke", "enteral nutrition in AIS", "nutritional support for stroke patients"],
        "5.4": ["DVT prophylaxis in stroke", "VTE prevention after stroke", "intermittent pneumatic compression", "graduated compression stockings", "anticoagulation for DVT prevention", "early mobilization for DVT prevention"],
        "5.5": ["depression screening after stroke", "post-stroke depression treatment", "antidepressants for stroke patients"],
        "5.6": ["prophylactic antibiotics in stroke", "indwelling bladder catheter in stroke", "fluoxetine for motor recovery"],
        "5.7": ["early rehabilitation after stroke", "physical therapy after stroke", "very early mobilization"],
        "6.1": ["brain swelling management", "cerebral edema monitoring", "intracranial pressure management"],
        "6.2": ["osmotic therapy for brain swelling", "corticosteroids for cerebral edema", "medical management of brain swelling"],
        "6.3": ["decompressive craniectomy", "surgical decompression for stroke", "hemicraniectomy for malignant MCA infarction", "decompressive surgery after IVT"],
        "6.4": ["cerebellar stroke surgery", "posterior fossa decompression", "ventriculostomy for cerebellar infarction"],
        "6.5": ["seizure management in stroke", "prophylactic antiseizure medication", "antiepileptic drugs after stroke"],
    }

    # First pass: 1-3 questions per rec
    for section, recs_list in recs_by_section.items():
        topics = section_topics.get(section, [f"management in Section {section}"])

        for rec in recs_list:
            cor = rec["cor"]
            cor_key = cor if cor in templates else "1"
            tmpl_list = templates[cor_key]

            num_qs = min(3, max(1, 8 // len(recs_list)))
            for i in range(num_qs):
                topic = topics[i % len(topics)]
                tmpl = tmpl_list[i % len(tmpl_list)]
                q_text = tmpl.format(topic=topic, topic_verb=topic.lower())

                questions.append({
                    "id": f"QA-{qid}",
                    "section": section,
                    "category": "qa_recommendation",
                    "question": q_text,
                    "expected_cor": rec["cor"],
                    "expected_loe": rec["loe"],
                    "expected_section": section,
                    "rec_id": rec["id"],
                    "topic": topic,
                })
                qid += 1

                if len(questions) >= target:
                    return questions

    # Second pass: additional variants to reach target
    extra_prefixes = [
        "According to the AIS guideline, ",
        "Per the 2026 guideline, ",
        "What is the current recommendation for ",
        "In AIS management, is ",
    ]
    pass_idx = 0
    while len(questions) < target:
        for section, recs_list in recs_by_section.items():
            if len(questions) >= target:
                break
            topics = section_topics.get(section, [f"management in Section {section}"])
            rec = recs_list[pass_idx % len(recs_list)]
            topic = topics[(pass_idx + len(questions)) % len(topics)]
            prefix = extra_prefixes[len(questions) % len(extra_prefixes)]
            q_text = f"{prefix}{topic}?"

            questions.append({
                "id": f"QA-{qid}",
                "section": section,
                "category": "qa_recommendation",
                "question": q_text,
                "expected_cor": rec["cor"],
                "expected_loe": rec["loe"],
                "expected_section": section,
                "rec_id": rec["id"],
                "topic": topic,
            })
            qid += 1
        pass_idx += 1

    return questions[:target]


def build_evidence_questions(sections_data, target=300):
    """Generate evidence questions for sections with RSS content."""
    questions = []
    qid = 7501

    templates = [
        "What evidence supports the recommendations in Section {sec} ({title})?",
        "What studies inform the {topic} recommendations?",
        "What is the rationale for the {topic} recommendation?",
        "What trials have been conducted on {topic}?",
        "What data supports {topic}?",
        "Why does the guideline recommend {topic}?",
        "What is the evidence basis for {topic}?",
        "What research informs the recommendation on {topic}?",
    ]

    section_topics = {
        "2.1": "stroke awareness education",
        "2.2": "EMS systems for stroke",
        "2.3": "prehospital stroke management",
        "2.4": "EMS destination management",
        "2.5": "mobile stroke units",
        "2.7": "emergency stroke evaluation",
        "2.8": "telestroke",
        "2.9": "stroke center organization",
        "3.1": "stroke scales",
        "3.2": "stroke imaging",
        "3.3": "laboratory testing before IVT",
        "4.1": "oxygen supplementation",
        "4.2": "head positioning",
        "4.3": "blood pressure management",
        "4.4": "temperature management",
        "4.5": "glucose management",
        "4.6.1": "IVT decision-making",
        "4.6.2": "thrombolytic agent choice",
        "4.6.3": "extended window IVT",
        "4.6.4": "other fibrinolytics",
        "4.6.5": "IVT in special circumstances",
        "4.7.1": "concomitant IVT and EVT",
        "4.7.2": "endovascular thrombectomy",
        "4.7.3": "posterior circulation EVT",
        "4.7.4": "endovascular techniques",
        "4.7.5": "pediatric EVT",
        "4.8": "antiplatelet therapy",
        "4.9": "anticoagulation after stroke",
        "5.1": "stroke units",
        "5.2": "dysphagia management",
        "5.3": "nutrition after stroke",
        "5.4": "DVT prophylaxis",
        "5.5": "post-stroke depression",
        "5.6": "in-hospital management",
        "5.7": "rehabilitation",
        "6.1": "brain swelling management",
        "6.2": "medical management of edema",
        "6.3": "decompressive craniectomy",
        "6.4": "cerebellar stroke surgery",
        "6.5": "seizures after stroke",
    }

    sections_with_rss = []
    for sec_num, sec_data in sections_data.items():
        rss = sec_data.get("rss", [])
        if not rss:
            continue
        topic = section_topics.get(sec_num, sec_data.get("sectionTitle", ""))
        title = sec_data.get("sectionTitle", "")
        keywords = []
        for r in rss[:3]:
            text = r.get("text", "").upper()
            for word in text.split():
                clean = word.strip(".,;:()[]0-9")
                if len(clean) >= 4 and clean.isalpha():
                    keywords.append(clean)
        keywords = list(set(keywords))[:5]
        sections_with_rss.append((sec_num, sec_data, topic, title, keywords, len(rss)))

    # First pass
    for sec_num, sec_data, topic, title, keywords, rss_count in sections_with_rss:
        num_qs = min(8, max(2, rss_count))
        for i in range(num_qs):
            tmpl = templates[i % len(templates)]
            q_text = tmpl.format(sec=sec_num, title=title, topic=topic)
            questions.append({
                "id": f"QA-{qid}",
                "section": sec_num,
                "category": "qa_evidence",
                "question": q_text,
                "expected_section": sec_num,
                "expected_type": "evidence",
                "expected_keywords": keywords[:5] if keywords else ["STROKE"],
                "topic": topic,
            })
            qid += 1
            if len(questions) >= target:
                return questions

    # Second pass: extra variants
    extra_templates = [
        "What is the evidence behind {topic} in the AIS guideline?",
        "What clinical trials support the {topic} recommendation?",
        "What is the scientific basis for {topic}?",
        "What does the literature say about {topic}?",
    ]
    pass_idx = 0
    while len(questions) < target:
        for sec_num, sec_data, topic, title, keywords, _ in sections_with_rss:
            if len(questions) >= target:
                break
            tmpl = extra_templates[(pass_idx + len(questions)) % len(extra_templates)]
            q_text = tmpl.format(sec=sec_num, title=title, topic=topic)
            questions.append({
                "id": f"QA-{qid}",
                "section": sec_num,
                "category": "qa_evidence",
                "question": q_text,
                "expected_section": sec_num,
                "expected_type": "evidence",
                "expected_keywords": keywords[:5] if keywords else ["STROKE"],
                "topic": topic,
            })
            qid += 1
        pass_idx += 1

    return questions[:target]


def build_knowledge_gap_questions(sections_data, target=100):
    """Generate knowledge gap questions for all sections."""
    questions = []
    qid = 7901

    templates = [
        "What are the knowledge gaps for {topic}?",
        "What future research is needed on {topic}?",
        "What remains unclear about {topic}?",
        "What areas need further study regarding {topic}?",
    ]

    for sec_num, sec_data in sections_data.items():
        title = sec_data.get("sectionTitle", "")
        if not title:
            continue
        kg = sec_data.get("knowledgeGaps", "").strip()
        has_content = bool(kg)

        topic = title.lower()
        for i in range(2):
            tmpl = templates[i % len(templates)]
            q_text = tmpl.format(topic=topic, sec=sec_num)

            questions.append({
                "id": f"QA-{qid}",
                "section": sec_num,
                "category": "qa_knowledge_gap",
                "question": q_text,
                "expected_section": sec_num,
                "expected_type": "knowledge_gap",
                "has_content": has_content,
                "topic": topic,
            })
            qid += 1

            if len(questions) >= target:
                return questions

    return questions


def build_semantic_questions(target=100):
    """Generate plain-language questions that require semantic search."""
    questions = []
    qid = 8101

    # Plain language → expected section mapping
    semantic_cases = [
        ("Can I give clot-busting drugs to someone on blood thinners?", "4.8", "anticoagulation with thrombolysis"),
        ("Is brain cooling helpful after a stroke?", "4.4", "hypothermia"),
        ("Should we put the patient flat after a stroke?", "4.2", "head positioning"),
        ("Can we do the clot removal procedure on a child?", "4.7.5", "pediatric EVT"),
        ("What if the patient woke up with stroke symptoms?", "3.2", "wake-up stroke imaging"),
        ("Is it safe to use the newer clot-buster instead of the old one?", "4.6.2", "tenecteplase vs alteplase"),
        ("Can blood thinning medicines be given right after a stroke?", "4.9", "early anticoagulation"),
        ("Should we check for trouble swallowing?", "5.2", "dysphagia screening"),
        ("Is surgery needed for a swollen brain after stroke?", "6.3", "decompressive craniectomy"),
        ("Can the clot be pulled out from the back of the brain?", "4.7.3", "posterior circulation EVT"),
        ("How fast should treatment start?", "4.6.1", "time to treatment"),
        ("Is there a pill to prevent blood clots after a stroke?", "4.8", "antiplatelet therapy"),
        ("Should we worry about the patient getting a blood clot in the leg?", "5.4", "DVT prophylaxis"),
        ("Can a phone call to a specialist help decide treatment?", "2.8", "telestroke"),
        ("Is the patient too old for the clot-busting drug?", "4.6.1", "age and IVT eligibility"),
        ("What if blood sugar is too high during a stroke?", "4.5", "hyperglycemia management"),
        ("Should we lower the blood pressure before treatment?", "4.3", "BP management before IVT"),
        ("Can physical therapy start right away?", "5.7", "early rehabilitation"),
        ("Is the patient feeling sad after the stroke?", "5.5", "post-stroke depression"),
        ("Should we send the patient to a bigger hospital?", "2.4", "EMS destination management"),
        ("Can we use the suction device instead of the wire basket?", "4.7.4", "aspiration vs stent retriever"),
        ("Is there a special ambulance with a brain scanner?", "2.5", "mobile stroke unit"),
        ("What images of the brain do we need?", "3.2", "stroke imaging"),
        ("Do we need blood tests before giving the clot-buster?", "3.3", "lab testing before IVT"),
        ("Should the patient be in a special part of the hospital?", "5.1", "stroke unit"),
        ("Can two blood-thinning pills work better than one?", "4.8", "dual antiplatelet therapy"),
        ("What if the stroke happened during a heart procedure?", "4.6.5", "procedural stroke"),
        ("Is the fever making the stroke worse?", "4.4", "fever management"),
        ("Should we give extra oxygen?", "4.1", "supplemental oxygen"),
        ("Can the community learn to spot stroke symptoms?", "2.1", "stroke awareness"),
        ("Is it too late for the clot-busting drug?", "4.6.3", "extended window IVT"),
        ("Should we use both treatments together?", "4.7.1", "bridging IVT and EVT"),
        ("What if the blockage is in a medium-sized artery?", "4.7.2", "M2 occlusion EVT"),
        ("Can we use a robot to help the doctor see the patient?", "2.8", "telemedicine robots"),
        ("Is the stroke center certified?", "2.9", "stroke center certification"),
        ("Should we prevent seizures after stroke?", "6.5", "prophylactic antiseizure meds"),
        ("How do we keep track of stroke quality?", "2.10", "stroke registries"),
        ("Can the patient eat normally after the stroke?", "5.3", "nutrition assessment"),
        ("Should we give medicine to dissolve the clot through the blood vessel?", "4.6.4", "other fibrinolytics"),
        ("Is the patient's brain swelling dangerous?", "6.1", "brain swelling monitoring"),
        ("Can steroids help with the brain swelling?", "6.2", "corticosteroids for edema"),
        ("What if the stroke is in the back part of the brain near the balance center?", "6.4", "cerebellar infarction"),
        ("Should fluids be given to improve blood flow?", "4.10", "volume expansion"),
        ("Is there a brain-protecting medicine we can give?", "4.11", "neuroprotective agents"),
        ("Should we open the neck artery right away?", "4.12", "emergency carotid endarterectomy"),
        ("Can antibiotics prevent infection after stroke?", "5.6", "prophylactic antibiotics"),
        ("Does the medicine that helps mood also help movement?", "5.6", "fluoxetine for recovery"),
        ("How serious is this stroke on a scale?", "3.1", "NIHSS assessment"),
        ("Should leg-squeezing devices be used?", "5.4", "intermittent pneumatic compression"),
        ("Can a video call replace an in-person doctor visit for stroke?", "2.8", "telestroke consultation"),
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

    # Pad to target with variants
    variant_prefixes = [
        "In plain terms, ", "Simply put, ", "In layman's terms, ",
    ]
    base_idx = 0
    while len(questions) < target:
        base = semantic_cases[base_idx % len(semantic_cases)]
        prefix = variant_prefixes[len(questions) % len(variant_prefixes)]
        q_text = prefix + base[0].lower()
        questions.append({
            "id": f"QA-{qid}",
            "section": base[1],
            "category": "qa_semantic",
            "question": q_text,
            "expected_section": base[1],
            "topic": base[2],
        })
        qid += 1
        base_idx += 1

    return questions[:target]


def build_scope_gate_questions(target=50):
    """Generate questions that should trigger the scope gate."""
    questions = []
    qid = 8301

    out_of_scope = [
        ("What is the best treatment for intracerebral hemorrhage?", "ICH — different guideline"),
        ("How should subarachnoid hemorrhage be managed?", "SAH — different guideline"),
        ("What is the recommendation for carotid stenosis screening in asymptomatic patients?", "Asymptomatic carotid — primary prevention"),
        ("How should chronic post-stroke pain be managed?", "Chronic pain — outpatient management"),
        ("What is the guideline for secondary stroke prevention with statins?", "Statins — secondary prevention guideline"),
        ("How do you manage atrial fibrillation long-term after stroke?", "Long-term AF management — chronic care"),
        ("What is the recommendation for cognitive rehabilitation 6 months after stroke?", "Late rehab — chronic phase"),
        ("How should patent foramen ovale be managed after cryptogenic stroke?", "PFO closure — secondary prevention"),
        ("What is the guideline for managing post-stroke spasticity?", "Spasticity — chronic phase"),
        ("How should sleep apnea be managed in stroke survivors?", "Sleep apnea — chronic care"),
        ("What is the recommendation for driving after stroke?", "Driving — discharge planning"),
        ("How should post-stroke fatigue be treated?", "Fatigue — chronic management"),
        ("What is the guideline for managing post-stroke shoulder pain?", "Shoulder pain — chronic rehab"),
        ("How should vascular dementia be treated after stroke?", "Dementia — chronic care"),
        ("What is the recommendation for returning to work after stroke?", "Return to work — social rehab"),
        ("How should chronic headaches after stroke be managed?", "Post-stroke headache — chronic"),
        ("What is the guideline for managing urinary incontinence months after stroke?", "Chronic incontinence — long-term"),
        ("How should central post-stroke pain be treated?", "Central pain — chronic neuro"),
        ("What is the recommendation for managing post-stroke anxiety long-term?", "Chronic anxiety — outpatient"),
        ("How should hyperlipidemia be managed for secondary stroke prevention?", "Lipids — secondary prevention"),
        ("What is the guideline for anticoagulation in mechanical heart valves after stroke?", "Mechanical valves — specific cardiology"),
        ("How should moyamoya disease be managed in adults?", "Moyamoya — rare vascular"),
        ("What is the recommendation for managing cerebral venous sinus thrombosis?", "CVST — different condition"),
        ("How should reversible cerebral vasoconstriction syndrome be treated?", "RCVS — different condition"),
        ("What is the guideline for managing CNS vasculitis?", "Vasculitis — different condition"),
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

    # Pad with variants
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


def build_clarification_questions(recs_by_section, target=50):
    """Generate questions that should trigger clarification (sections with conflicting COR)."""
    questions = []
    qid = 8401

    templates = [
        "What is the recommendation for {topic}?",
        "Is {topic} recommended?",
        "What does the guideline say about {topic}?",
    ]

    # Sections with multiple COR levels → ambiguity candidates
    ambiguous_sections = {
        "4.6.1": ["IVT eligibility", "thrombolysis recommendation", "IVT for stroke", "IVT for disabling vs non-disabling stroke", "thrombolysis criteria"],
        "4.7.2": ["EVT for M2 occlusion", "thrombectomy eligibility", "EVT for large vessel occlusion", "EVT time window", "mechanical thrombectomy indications"],
        "4.3": ["blood pressure management in stroke", "BP targets during treatment", "antihypertensive therapy in AIS", "blood pressure lowering in AIS", "BP before IVT vs during EVT"],
        "4.8": ["antiplatelet therapy after stroke", "aspirin after AIS", "dual antiplatelet for stroke", "antiplatelet timing after IVT", "clopidogrel versus aspirin"],
        "2.3": ["prehospital stroke treatment", "field management of AIS", "prehospital blood pressure management"],
        "2.4": ["EMS destination for stroke", "transport decisions for stroke", "hospital bypass decisions"],
        "2.9": ["stroke center organization", "stroke care coordination", "stroke system standards"],
        "4.7.4": ["endovascular technique selection", "EVT procedural approach", "anesthesia during EVT", "thrombectomy device choice"],
        "6.3": ["decompressive craniectomy for stroke", "surgical decompression timing", "hemicraniectomy indications", "craniectomy age considerations"],
        "5.4": ["DVT prevention after stroke", "VTE prophylaxis method", "compression devices vs anticoagulation for DVT"],
        "3.2": ["brain imaging for stroke", "CT vs MRI for stroke", "imaging modality selection", "perfusion imaging indications"],
        "5.2": ["dysphagia screening", "swallowing assessment approach", "oral care after stroke"],
        "4.9": ["anticoagulation timing after stroke", "early heparin for stroke", "anticoagulation for AF with stroke"],
        "5.6": ["prophylactic antibiotics", "bladder catheter management", "fluoxetine for stroke recovery"],
        "6.2": ["osmotic therapy for edema", "medical management of brain swelling", "corticosteroids for stroke edema"],
    }

    # First pass: only sections with actual conflicting COR
    for section, topics in ambiguous_sections.items():
        recs = recs_by_section.get(section, [])
        cors = set(r["cor"] for r in recs)
        if len(cors) <= 1:
            continue

        for i, topic in enumerate(topics):
            tmpl = templates[i % len(templates)]
            q_text = tmpl.format(topic=topic)
            questions.append({
                "id": f"QA-{qid}",
                "section": section,
                "category": "qa_clarification",
                "question": q_text,
                "expected_section": section,
                "expected_clarification_possible": True,
                "conflicting_cors": sorted(cors),
                "topic": topic,
            })
            qid += 1
            if len(questions) >= target:
                return questions

    # Second pass: auto-discover all multi-COR sections not in manual list
    for section, recs_list in recs_by_section.items():
        if len(questions) >= target:
            break
        if section in ambiguous_sections:
            continue
        cors = set(r["cor"] for r in recs_list)
        if len(cors) <= 1:
            continue
        # Use generic topic from section title
        titles = set(r.get("sectionTitle", "") for r in recs_list)
        topic = list(titles)[0].lower() if titles else f"Section {section}"
        for tmpl in templates:
            q_text = tmpl.format(topic=topic)
            questions.append({
                "id": f"QA-{qid}",
                "section": section,
                "category": "qa_clarification",
                "question": q_text,
                "expected_section": section,
                "expected_clarification_possible": True,
                "conflicting_cors": sorted(cors),
                "topic": topic,
            })
            qid += 1
            if len(questions) >= target:
                return questions

    # Third pass: variant questions for sections already found
    extra_templates = [
        "Can you clarify the recommendation for {topic}?",
        "Are there different recommendations for {topic}?",
        "What are all the recommendations regarding {topic}?",
    ]
    for q in list(questions):
        if len(questions) >= target:
            break
        for tmpl in extra_templates:
            if len(questions) >= target:
                break
            q_text = tmpl.format(topic=q["topic"])
            questions.append({
                "id": f"QA-{qid}",
                "section": q["section"],
                "category": "qa_clarification",
                "question": q_text,
                "expected_section": q["section"],
                "expected_clarification_possible": True,
                "conflicting_cors": q["conflicting_cors"],
                "topic": q["topic"],
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

    print("Generating R7 test suite...")

    rec_qs = build_recommendation_questions(recs_by_section, target=400)
    print(f"  Recommendation: {len(rec_qs)}")

    ev_qs = build_evidence_questions(sections_data, target=300)
    print(f"  Evidence: {len(ev_qs)}")

    kg_qs = build_knowledge_gap_questions(sections_data, target=100)
    print(f"  Knowledge Gap: {len(kg_qs)}")

    sem_qs = build_semantic_questions(target=100)
    print(f"  Semantic: {len(sem_qs)}")

    scope_qs = build_scope_gate_questions(target=50)
    print(f"  Scope Gate: {len(scope_qs)}")

    clar_qs = build_clarification_questions(recs_by_section, target=50)
    print(f"  Clarification: {len(clar_qs)}")

    all_qs = rec_qs + ev_qs + kg_qs + sem_qs + scope_qs + clar_qs
    print(f"\n  TOTAL: {len(all_qs)}")

    output = {"questions": all_qs}
    out_path = os.path.join(
        "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff",
        "qa_round7_test_suite.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
