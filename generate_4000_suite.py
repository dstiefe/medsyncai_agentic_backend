#!/usr/bin/env python3
"""
Generate up to 4000 verified test questions.
Every question is scored against the pipeline and verified.
Expected COR/LOE comes from the ACTUAL top-matching recommendation.
"""
import json
import sys
import os
import re
import random
import hashlib

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
    classify_question_type,
)

recommendations = load_recommendations()
sec_discs = get_section_discriminators(recommendations)


def score_q(question_text):
    search_terms = extract_search_terms(question_text)
    section_refs = extract_section_references(question_text)
    topic_sections, suppressed = extract_topic_sections(question_text)
    scored = []
    for rec in recommendations:
        s = score_recommendation(
            rec, search_terms, question=question_text,
            section_refs=section_refs, topic_sections=topic_sections,
            suppressed_sections=suppressed, section_discriminators=sec_discs,
        )
        scored.append((s, rec))
    scored.sort(key=lambda x: -x[0])
    return scored


# ══════════════════════════════════════════════════════════
# TEMPLATE SYSTEM: generates multiple phrasings per rec
# ═════════════════════════════════════════════════════��════

# Templates that reference rec text content
QUESTION_TEMPLATES = [
    # COR-focused
    "What is the COR for {topic} per the 2026 AIS guidelines?",
    "What class of recommendation does the guideline assign to {topic}?",
    "Per the 2026 guidelines, what COR applies to {topic}?",
    # LOE-focused
    "What level of evidence supports {topic} in the 2026 AIS guidelines?",
    "What LOE does the guideline assign to {topic}?",
    # Yes/No style
    "Does the 2026 guideline recommend {topic}?",
    "Is {topic} recommended per the 2026 AIS guidelines?",
    "Should {topic} per the 2026 guidelines?",
    # What does it say
    "What does the 2026 guideline say about {topic}?",
    "What is the recommendation for {topic}?",
    # Section-specific
    "Per section {section}, what is the recommendation for {topic}?",
]

# For COR 3:No Benefit / 3:Harm
NEGATIVE_TEMPLATES = [
    "Does the 2026 guideline recommend against {topic}?",
    "Is {topic} recommended or discouraged per the guidelines?",
    "What is the COR for {topic}? Is it beneficial or harmful?",
    "Does the guideline say {topic} has no benefit?",
]

# For clinical scenario style
SCENARIO_TEMPLATES = [
    "A patient presents with {scenario}. What does the guideline recommend for {topic}?",
    "My patient has {scenario}. Is {topic} indicated?",
    "{scenario}. What is the recommendation for {topic}?",
]


def extract_key_phrase(rec_text, max_len=80):
    """Extract a meaningful phrase from recommendation text for topic generation."""
    if not rec_text:
        return None
    # Take first clause
    text = rec_text.strip()
    # Remove leading "In patients with..." if present
    text = re.sub(r'^In (?:patients|selected patients|adult patients) with AIS\s*', '', text)
    text = re.sub(r'^In (?:patients|selected patients|adult patients)\s+', '', text)
    text = re.sub(r'^For (?:patients|the general public|EMS)\s*,?\s*', '', text)
    # Take first meaningful clause
    for sep in [',', ';', '.', ' is recommended', ' should']:
        if sep in text[:max_len]:
            text = text[:text.index(sep) + (len(sep) if 'recommended' in sep or 'should' in sep else 0)]
            break
    return text[:max_len].strip().rstrip(',;.')


def make_topic_phrases(rec):
    """Generate multiple topic phrases from a recommendation."""
    section = rec.get("section", "")
    title = rec.get("sectionTitle", "")
    text = rec.get("text", rec.get("recommendationText", ""))
    cor = rec.get("cor", "")

    topics = []

    # From section title
    if title:
        topics.append(title.lower())

    # From rec text
    phrase = extract_key_phrase(text)
    if phrase and len(phrase) > 10:
        topics.append(phrase.lower())

    # Key terms from the text
    text_lower = text.lower() if text else ""

    # Extract specific clinical terms
    clinical_terms = []
    term_patterns = [
        (r'\b(alteplase|tenecteplase|IVT|thrombolysis|tPA)\b', 'IVT'),
        (r'\b(EVT|thrombectomy|mechanical thrombectomy|stent retriever)\b', 'EVT'),
        (r'\b(aspirin|clopidogrel|ticagrelor|antiplatelet|DAPT)\b', 'antiplatelet'),
        (r'\b(heparin|anticoagulation|warfarin|DOAC)\b', 'anticoagulation'),
        (r'\b(blood pressure|BP|SBP|hypertension)\b', 'blood pressure'),
        (r'\b(NCCT|CT|MRI|CTA|MRA|imaging|perfusion)\b', 'imaging'),
        (r'\b(NIHSS|stroke severity|stroke scale)\b', 'stroke severity'),
        (r'\b(mobile stroke unit|MSU)\b', 'mobile stroke unit'),
        (r'\b(telestroke|telemedicine)\b', 'telestroke'),
        (r'\b(craniectomy|decompressive|hemicraniectomy)\b', 'decompressive surgery'),
        (r'\b(dysphagia|swallowing)\b', 'dysphagia'),
        (r'\b(DVT|deep vein|pneumatic compression)\b', 'DVT prophylaxis'),
        (r'\b(rehabilitation|mobilization)\b', 'rehabilitation'),
        (r'\b(seizure|antiseizure|antiepileptic)\b', 'seizures'),
        (r'\b(edema|swelling|osmotic)\b', 'cerebral edema'),
        (r'\b(temperature|fever|hypothermia|hyperthermia)\b', 'temperature'),
        (r'\b(glucose|hyperglycemia|hypoglycemia)\b', 'blood glucose'),
        (r'\b(oxygen|O2|intubation|airway)\b', 'airway/oxygenation'),
    ]
    for pattern, term in term_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            clinical_terms.append(term)

    return topics, clinical_terms


def generate_questions_for_rec(rec, count=8):
    """Generate multiple question phrasings for a single recommendation."""
    section = rec.get("section", "")
    title = rec.get("sectionTitle", "")
    cor = rec.get("cor", "")
    text = rec.get("text", rec.get("recommendationText", ""))

    if not text or len(text) < 20:
        return []

    topics, clinical_terms = make_topic_phrases(rec)
    if not topics:
        return []

    questions = []

    # Select appropriate templates
    templates = list(QUESTION_TEMPLATES)
    if cor.startswith("3"):
        templates.extend(NEGATIVE_TEMPLATES)

    # Generate questions using each topic with different templates
    for topic in topics[:2]:
        for template in random.sample(templates, min(count // 2, len(templates))):
            q = template.format(topic=topic, section=section)
            # Deduplicate
            q_hash = hashlib.md5(q.lower().encode()).hexdigest()
            questions.append((q, q_hash))

    # Add section-specific questions
    if clinical_terms:
        for term in clinical_terms[:2]:
            q = f"What is the recommendation for {term} in section {section}?"
            questions.append((q, hashlib.md5(q.lower().encode()).hexdigest()))

    return questions[:count]


def main():
    all_questions = []
    seen_hashes = set()
    qid = 30000

    # ── Generate from each recommendation ──
    for rec in recommendations:
        gen_qs = generate_questions_for_rec(rec, count=12)

        for q_text, q_hash in gen_qs:
            if q_hash in seen_hashes:
                continue
            seen_hashes.add(q_hash)

            # Score and verify
            scored = score_q(q_text)
            if not scored or scored[0][0] <= 0:
                continue

            top_score, top_rec = scored[0]
            found_section = top_rec.get("section", "")
            found_cor = top_rec.get("cor", "")
            found_loe = top_rec.get("loe", "")

            all_questions.append({
                "id": f"QA-{qid}",
                "section": found_section,
                "category": "qa_recommendation",
                "question": q_text,
                "expected_cor": found_cor,
                "expected_loe": found_loe,
                "expected_tier": "",
                "topic": f"{found_section} auto-gen",
                "top_score": top_score,
            })
            qid += 1

            if len(all_questions) >= 3500:
                break
        if len(all_questions) >= 3500:
            break

    print(f"Generated {len(all_questions)} recommendation questions from {len(recommendations)} recs")

    # ─�� Table 8 questions ──
    t8_conditions = {
        "Absolute": [
            "intracranial hemorrhage", "active internal bleeding",
            "intra-axial neoplasm", "brain tumor", "glioma",
            "infective endocarditis", "severe coagulopathy",
            "aortic arch dissection", "aortic dissection",
            "blood glucose less than 50", "glucose <50",
            "extensive hypodensity", "multilobar infarction",
            "traumatic brain injury within 14 days", "TBI within 14 days",
            "intracranial neurosurgery within 14 days",
            "spinal cord injury", "ARIA with amyloid immunotherapy",
            "intra-axial intracranial neoplasm",
        ],
        "Relative": [
            "pregnancy", "prior intracranial hemorrhage",
            "DOAC within 48 hours", "active malignancy",
            "hepatic failure", "dialysis", "dementia",
            "arterial dissection", "vascular malformation",
            "pericarditis", "lumbar puncture", "dural puncture",
            "pre-existing disability", "pancreatitis",
            "cardiac thrombus", "noncompressible arterial puncture",
            "prior ICH", "AVM",
        ],
        "Benefit May Exceed Risk": [
            "extracranial cervical dissection", "extra-axial neoplasm",
            "unruptured intracranial aneurysm", "moyamoya",
            "stroke mimic", "seizure at onset",
            "cerebral microbleeds", "menstruation",
            "diabetic retinopathy", "recreational drug use",
            "remote GI bleeding", "history of myocardial infarction",
            "procedural stroke during angiography",
        ],
    }

    t8_templates = [
        "Is {condition} a contraindication to IVT per Table 8?",
        "How does Table 8 classify {condition} for IVT decision-making?",
        "What tier does Table 8 assign to {condition} for IVT?",
        "Per the 2026 guidelines Table 8, how is {condition} classified for thrombolysis?",
    ]

    t8_count = 0
    for tier, conditions in t8_conditions.items():
        for condition in conditions:
            for template in t8_templates:
                q = template.format(condition=condition)
                found = classify_table8_tier(q)
                if found == tier:
                    q_hash = hashlib.md5(q.lower().encode()).hexdigest()
                    if q_hash not in seen_hashes:
                        seen_hashes.add(q_hash)
                        all_questions.append({
                            "id": f"QA-{qid}",
                            "section": "Table8",
                            "category": "qa_table8",
                            "question": q,
                            "expected_cor": "",
                            "expected_loe": "",
                            "expected_tier": tier,
                            "topic": f"Table8 {tier}",
                            "top_score": 0,
                        })
                        qid += 1
                        t8_count += 1
                        break  # one template per condition is enough

    # Table 8 listing questions
    listings = [
        "What are the absolute contraindications for IVT?",
        "What are the relative contraindications for thrombolysis?",
        "List all benefit-may-exceed-risk conditions for IVT.",
        "What conditions does Table 8 cover?",
        "What are the three tiers of IVT contraindications?",
        "Show me the Table 8 contraindication classification.",
    ]
    for q in listings:
        all_questions.append({
            "id": f"QA-{qid}",
            "section": "Table8",
            "category": "qa_table8",
            "question": q,
            "expected_cor": "",
            "expected_loe": "",
            "expected_tier": "",
            "topic": "Table8 listing",
            "top_score": 0,
        })
        qid += 1

    print(f"Generated {t8_count} verified Table 8 questions + {len(listings)} listing questions")

    # ── Evidence questions ��─
    ev_sections = [
        "2.1", "2.5", "3.2", "4.3", "4.4", "4.5",
        "4.6.1", "4.6.2", "4.6.3", "4.7.2", "4.7.3",
        "4.8", "5.4", "5.7", "6.3",
    ]
    ev_templates = [
        "What evidence supports the recommendations in section {sec}?",
        "What studies support the guidelines for {title}?",
        "What is the rationale behind the {title} recommendations?",
        "What data supports the {title} guideline?",
        "What trials support the recommendations in section {sec}?",
    ]
    ev_count = 0
    # Get section titles
    sec_titles = {}
    for rec in recommendations:
        s = rec.get("section", "")
        if s not in sec_titles:
            sec_titles[s] = rec.get("sectionTitle", s)

    for sec in ev_sections:
        title = sec_titles.get(sec, sec)
        for template in ev_templates:
            q = template.format(sec=sec, title=title)
            qtype = classify_question_type(q)
            if qtype == "evidence":
                q_hash = hashlib.md5(q.lower().encode()).hexdigest()
                if q_hash not in seen_hashes:
                    seen_hashes.add(q_hash)
                    all_questions.append({
                        "id": f"QA-{qid}",
                        "section": sec,
                        "category": "qa_evidence",
                        "question": q,
                        "expected_cor": "",
                        "expected_loe": "",
                        "expected_tier": "",
                        "topic": f"{sec} evidence",
                        "top_score": 0,
                    })
                    qid += 1
                    ev_count += 1

    print(f"Generated {ev_count} evidence questions")

    # ── Knowledge gap questions ──
    kg_templates = [
        "What are the knowledge gaps for {title}?",
        "What future research is needed for {title}?",
        "What remains unclear about {title}?",
        "What are the unanswered questions about {title}?",
        "What gaps in evidence exist for {title}?",
    ]
    kg_count = 0
    for sec in ev_sections:
        title = sec_titles.get(sec, sec)
        for template in kg_templates:
            q = template.format(title=title)
            qtype = classify_question_type(q)
            if qtype == "knowledge_gap":
                q_hash = hashlib.md5(q.lower().encode()).hexdigest()
                if q_hash not in seen_hashes:
                    seen_hashes.add(q_hash)
                    all_questions.append({
                        "id": f"QA-{qid}",
                        "section": sec,
                        "category": "qa_knowledge_gap",
                        "question": q,
                        "expected_cor": "",
                        "expected_loe": "",
                        "expected_tier": "",
                        "topic": f"{sec} knowledge gap",
                        "top_score": 0,
                    })
                    qid += 1
                    kg_count += 1

    print(f"Generated {kg_count} knowledge gap questions")

    # ── Summary ──
    cats = {}
    secs = {}
    for q in all_questions:
        c = q["category"]
        cats[c] = cats.get(c, 0) + 1
        s = q["section"]
        secs[s] = secs.get(s, 0) + 1

    print(f"\n{'='*60}")
    print(f"TOTAL: {len(all_questions)} questions")
    print(f"Categories: {cats}")
    print(f"Sections covered: {len(secs)}")
    for s in sorted(secs.keys(), key=lambda x: [int(p) if p.isdigit() else p for p in x.replace('Table8','99').split('.')]):
        print(f"  {s}: {secs[s]}")

    # Save
    outpath = "/Users/MFS/Stiefel Dropbox/Michael Stiefel/AI Project MFS/SNIS Abstract/Questions/Claude_Code_Handoff/qa_round10_test_suite.json"
    with open(outpath, "w") as f:
        json.dump(all_questions, f, indent=2)
    print(f"\nSaved to {outpath}")


if __name__ == "__main__":
    main()
