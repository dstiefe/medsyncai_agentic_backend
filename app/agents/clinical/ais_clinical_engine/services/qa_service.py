"""
Q&A service for the AIS Clinical Engine.

Ported from PM's backend/app/api/qa.py and adapted to v2's architecture.
Provides sophisticated guideline search with concept synonyms, applicability
gating, three-layer search, evidence-prioritized mode, and LLM summarization.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models.clinical import Recommendation
from ..models.rules import RuleClause, RuleCondition


# ---------------------------------------------------------------------------
# Medical concept synonyms
# ---------------------------------------------------------------------------

CONCEPT_SYNONYMS = {
    # Medications
    "tnk": ["tenecteplase"],
    "tpa": ["alteplase", "thrombolysis", "thrombolytic", "ivt"],
    "alteplase": ["alteplase", "thrombolytic"],
    "tenecteplase": ["tenecteplase", "thrombolytic"],
    "heparin": ["heparin", "anticoagul"],
    "aspirin": ["antiplatelet", "aspirin"],
    "plavix": ["antiplatelet", "clopidogrel"],
    "warfarin": ["anticoagul", "inr"],
    "doac": ["anticoagul", "doac", "direct oral"],
    # Lab values
    "platelet": ["platelet", "coagulopathy", "thrombocytop"],
    "platelets": ["platelet", "coagulopathy", "thrombocytop"],
    "inr": ["inr", "coagulopathy", "anticoagul"],
    "aptt": ["aptt", "coagulopathy"],
    "pt": ["coagulopathy"],
    # Conditions
    "hemorrhage": ["hemorrhage", "bleeding", "intracranial"],
    "bleeding": ["hemorrhage", "bleeding"],
    "blood pressure": ["blood pressure", "hypertens", "sbp"],
    "bp": ["blood pressure", "hypertens", "185"],
    "hypertension": ["blood pressure", "hypertens"],
    "lvo": ["large vessel", "lvo", "thrombectomy"],
    "thrombectomy": ["thrombectomy", "evt", "endovascular"],
    "evt": ["thrombectomy", "evt", "endovascular"],
    "stroke": ["stroke", "ais", "ischemic"],
    "wake up": ["wake", "unknown", "onset"],
    "wake-up": ["wake", "unknown", "onset"],
    "pregnancy": ["pregnan"],
    "sickle cell": ["sickle"],
    "surgery": ["surgery", "neurosurg"],
    "trauma": ["trauma", "tbi"],
    # Contraindications
    "contraindication": ["contraindic", "not recommended", "harm", "table 8"],
    "contraindications": ["contraindic", "not recommended", "harm", "table 8"],
    "absolute": ["absolute", "contraindic", "table 8"],
    "relative": ["relative", "contraindic", "benefit", "table 8"],
    "eligible": ["eligible", "recommended", "indicated"],
    "eligibility": ["eligible", "recommended", "indicated"],
    # Adverse effects / complications
    "sich": ["hemorrhage", "symptomatic", "intracranial", "table 5", "bleeding", "cryoprecipitate", "tranexamic"],
    "angioedema": ["angioedema", "orolingual", "airway", "table 6", "epinephrine", "methylprednisolone", "diphenhydramine"],
    "protocol": ["protocol", "management", "table"],
    "management": ["management", "protocol", "table"],
    # Concepts
    "disabling": ["disabling", "non-disabling", "table 4", "bathe", "hemianopsia", "aphasia", "adl"],
    "non-disabling": ["non-disabling", "mild", "table 4", "prisms", "bathe"],
    "dosing": ["dose", "mg/kg", "0.25", "0.9"],
    "dose": ["dose", "mg/kg", "0.25", "0.9"],
    "imaging": ["imaging", "ct", "mri", "cta", "aspects"],
    "cta": ["cta", "contrast", "vascular", "imaging"],
    "ctp": ["ctp", "perfusion", "penumbra", "ct perfusion", "perfusion-weighted"],
    "ct perfusion": ["ctp", "perfusion", "penumbra", "perfusion-weighted"],
    "perfusion": ["perfusion", "penumbra", "dwi", "flair", "ctp"],
    "window": ["window", "hours", "4.5", "extended"],
    "time": ["hours", "time", "onset", "window"],
    "concomitant": ["concomitant", "ivt.*evt", "delay"],
    # Lab / metabolic
    "lab": ["hematologic", "coagulation", "laboratory", "platelet", "inr"],
    "labs": ["hematologic", "coagulation", "laboratory", "platelet", "inr"],
    "laboratory": ["hematologic", "coagulation", "laboratory"],
    "glucose": ["glucose", "hyperglycemia", "hypoglycemia", "insulin", "blood sugar"],
    "hyperglycemia": ["glucose", "hyperglycemia", "insulin"],
    "hypoglycemia": ["glucose", "hypoglycemia"],
    "creatinine": ["creatinine", "renal", "kidney", "contrast", "aki"],
    "renal": ["renal", "kidney", "creatinine"],
    # Temperature
    "temperature": ["temperature", "hyperthermia", "hypothermia", "fever", "normothermia"],
    "fever": ["temperature", "fever", "hyperthermia", "normothermia"],
    "hypothermia": ["hypothermia", "temperature", "normothermia"],
    "hyperthermia": ["hyperthermia", "temperature", "fever", "normothermia"],
    # Microbleeds
    "microbleed": ["microbleed", "cmb", "cerebral microbleed"],
    "microbleeds": ["microbleed", "cmb", "cerebral microbleed"],
    "cmb": ["microbleed", "cmb", "cerebral microbleed"],
    # Population
    "pediatric": ["pediatric", "child", "neonat", "28 days", "18 years"],
    "child": ["pediatric", "child"],
    "children": ["pediatric", "child"],
    # Vessel/anatomy
    "basilar": ["basilar", "posterior", "vertebral", "posterior circulation"],
    "posterior": ["posterior", "basilar", "posterior circulation", "pca", "vertebral"],
    "pca": ["pca", "posterior", "posterior circulation"],
    "vertebral": ["vertebral", "posterior", "posterior circulation"],
    "anterior": ["anterior", "mca", "ica"],
    "carotid": ["carotid", "ica", "endarterectomy"],
    "m2": ["m2", "medium vessel", "mevo", "mca"],
    # Studies/evidence
    "study": ["trial", "rct", "study", "data"],
    "trial": ["trial", "rct", "study"],
    "evidence": ["evidence", "data", "trial", "rct"],
    "data": ["data", "evidence", "trial"],
    "rct": ["rct", "trial", "randomized"],
    # Functional status
    "mrs": ["mrs", "mRS", "rankin", "prestroke", "disability", "premorbid"],
    "rankin": ["mrs", "mRS", "rankin", "prestroke", "disability"],
    "disability": ["disability", "mrs", "mRS", "prestroke", "premorbid"],
    "premorbid": ["premorbid", "prestroke", "mrs", "mRS", "disability"],
    "functional": ["functional", "outcome", "mrs", "mRS"],
    # Inpatient / post-acute management
    "dvt": ["dvt", "deep venous", "prophylaxis", "heparin", "enoxaparin", "pneumatic"],
    "deep venous": ["dvt", "deep venous", "prophylaxis", "pneumatic"],
    "dysphagia": ["dysphagia", "swallowing", "aspiration", "oral intake", "screening"],
    "swallowing": ["dysphagia", "swallowing", "aspiration", "oral intake"],
    "depression": ["depression", "depressive", "antidepressant", "ssri", "mood"],
    "oxygen": ["oxygen", "supplemental", "hypoxia", "airway"],
    "airway": ["airway", "oxygen", "intubation", "ventilation"],
    "head positioning": ["head", "positioning", "flat", "elevated", "supine"],
    "nutrition": ["nutrition", "enteral", "feeding", "nasogastric", "tube feeding"],
    # Complications (Section 6.x)
    "angioedema": ["angioedema", "orolingual", "airway", "table 6", "epinephrine", "methylprednisolone", "diphenhydramine", "intubation"],
    "edema": ["edema", "cerebral edema", "swelling", "herniation", "craniectomy", "decompressive", "osmotic"],
    "craniectomy": ["craniectomy", "decompressive", "hemicraniectomy", "herniation", "edema"],
    "decompressive": ["decompressive", "craniectomy", "hemicraniectomy", "herniation"],
    "seizure": ["seizure", "epilepsy", "antiepileptic", "antiseizure", "convulsion"],
    "seizures": ["seizure", "epilepsy", "antiepileptic", "antiseizure", "convulsion"],
    # Door-to-treatment times
    "door-to-needle": ["door-to-needle", "dtn", "time metric", "quality"],
    "door-to-puncture": ["door-to-puncture", "dtp", "time metric", "quality"],
    # Stroke systems / organization
    "stroke center": ["stroke center", "certification", "comprehensive", "thrombectomy-capable", "primary"],
    "certification": ["certification", "stroke center", "comprehensive", "primary"],
    "quality": ["quality", "metric", "improvement", "performance", "measure"],
    "telemedicine": ["telemedicine", "telestroke", "telehealth", "remote"],
    "telestroke": ["telemedicine", "telestroke", "telehealth", "remote"],
    "mobile stroke unit": ["mobile stroke unit", "msu", "ambulance", "prehospital"],
    "msu": ["mobile stroke unit", "msu", "ambulance", "prehospital"],
    # IVT agent / concomitant
    "concomitant": ["concomitant", "ivt", "evt", "bridging", "direct", "delay"],
    "bridging": ["bridging", "concomitant", "ivt", "evt"],
    "skip ivt": ["direct", "skip", "ivt", "evt", "concomitant"],
    "direct thrombectomy": ["direct", "skip", "ivt", "evt", "concomitant"],
    # Extended window IVT
    "wake-up stroke": ["wake", "unknown", "onset", "extended", "dwi", "flair", "mismatch"],
    "unknown onset": ["wake", "unknown", "onset", "extended", "dwi", "flair"],
    "extended window": ["extended", "window", "wake", "unknown", "6", "24", "perfusion"],
    # Carotid / vascular
    "endarterectomy": ["endarterectomy", "carotid", "cea", "stenosis"],
    "cea": ["endarterectomy", "carotid", "cea", "stenosis"],
    "carotid stenting": ["carotid", "stenting", "cas", "stenosis"],
}

# ---------------------------------------------------------------------------
# Topic → Section mapping
# ---------------------------------------------------------------------------
# When a question is about a specific clinical topic, boost the correct
# guideline section(s) so results come from the right part of the document.
# This is the implicit equivalent of the user typing "Section X.Y".
# Boost value is lower than explicit section refs (+20) but still dominant.
TOPIC_SECTION_MAP: Dict[str, List[str]] = {
    # Prehospital / EMS (Section 2.x)
    "ems": ["2.2", "2.3", "2.4"],
    "ambulance": ["2.2", "2.3", "2.4"],
    "prehospital": ["2.2", "2.3", "2.4"],
    "paramedic": ["2.2", "2.3", "2.4"],
    "mobile stroke unit": ["2.5"],
    "msu": ["2.5"],
    "stroke center": ["2.6"],
    "certification": ["2.6"],
    "comprehensive stroke": ["2.6"],
    "primary stroke": ["2.6"],
    "thrombectomy-capable": ["2.6"],
    "telemedicine": ["2.8"],
    "telestroke": ["2.8"],
    "telehealth": ["2.8"],
    "quality improvement": ["2.10"],
    "stroke registry": ["2.10"],
    # Imaging (Section 3.x)
    "imaging": ["3.2"],
    "ct angiography": ["3.2"],
    "cta": ["3.2"],
    "ctp": ["3.2"],
    "ct perfusion": ["3.2"],
    "mri": ["3.2"],
    "dwi": ["3.2"],
    "flair": ["3.2"],
    "perfusion imaging": ["3.2"],
    "aspects": ["3.2"],
    "stroke scale": ["3.1"],
    "nihss": ["3.1"],
    # General supportive care (Section 4.1-4.5)
    "airway": ["4.1"],
    "oxygenation": ["4.1"],
    "oxygen": ["4.1"],
    "supplemental oxygen": ["4.1"],
    "intubation": ["4.1"],
    "head positioning": ["4.2"],
    "head of bed": ["4.2"],
    "flat positioning": ["4.2"],
    "temperature": ["4.4"],
    "fever": ["4.4"],
    "hyperthermia": ["4.4"],
    "hypothermia": ["4.4"],
    "normothermia": ["4.4"],
    "glucose": ["4.5"],
    "blood sugar": ["4.5"],
    "hyperglycemia": ["4.5"],
    "hypoglycemia": ["4.5"],
    "insulin": ["4.5"],
    # Blood pressure — context-dependent
    # BP alone → 4.3 (general BP management)
    "blood pressure": ["4.3"],
    "bp management": ["4.3"],
    "hypertension": ["4.3"],
    "antihypertensive": ["4.3"],
    "labetalol": ["4.3"],
    "nicardipine": ["4.3"],
    "185/110": ["4.3"],
    # IVT (Section 4.6.x)
    "thrombolysis": ["4.6.1"],
    "thrombolytic": ["4.6.1", "4.6.2"],
    "alteplase": ["4.6.1", "4.6.2"],
    "tenecteplase": ["4.6.2"],
    "tnk": ["4.6.2"],
    "ivt dose": ["4.6.2"],
    "ivt dosing": ["4.6.2"],
    # Extended time windows for IVT (Section 4.6.3)
    "wake-up stroke": ["4.6.3"],
    "wake up stroke": ["4.6.3"],
    "unknown onset": ["4.6.3"],
    "extended window ivt": ["4.6.3"],
    "dwi-flair mismatch": ["4.6.3"],
    "dwi flair mismatch": ["4.6.3"],
    "perfusion mismatch": ["4.6.3"],
    "4.5 to 9 hour": ["4.6.3"],
    "9 hours": ["4.6.3"],
    # Other IV fibrinolytics and sonothrombolysis (Section 4.6.4)
    "sonothrombolysis": ["4.6.4"],
    "streptokinase": ["4.6.4"],
    "desmoteplase": ["4.6.4"],
    "intra-arterial fibrinolysis": ["4.6.4"],
    "intra-arterial": ["4.6.4"],
    # Other specific IVT circumstances (Section 4.6.5)
    "ivt in pregnant": ["4.6.5"],
    "ivt in pediatric": ["4.6.5"],
    "pregnant patients with ais": ["4.6.5"],
    "pediatric patients with ais": ["4.6.5"],
    # Concomitant IVT+EVT (Section 4.7.1)
    "concomitant": ["4.7.1"],
    "bridging": ["4.7.1"],
    "ivt before evt": ["4.7.1"],
    "ivt before thrombectomy": ["4.7.1"],
    "given before evt": ["4.7.1"],
    "given before thrombectomy": ["4.7.1"],
    "ivt and evt": ["4.7.1"],
    "ivt with evt": ["4.7.1"],
    "administered before evt": ["4.7.1"],
    "delay evt": ["4.7.1"],
    "delayed to assess": ["4.7.1"],
    "skip ivt": ["4.7.1"],
    "direct thrombectomy": ["4.7.1"],
    "direct to evt": ["4.7.1"],
    # EVT (Section 4.7.x)
    "thrombectomy": ["4.7.2"],
    "evt": ["4.7.2"],
    "endovascular": ["4.7.2"],
    "posterior circulation": ["4.7.3"],
    "basilar": ["4.7.3"],
    "vertebral": ["4.7.3"],
    # Endovascular techniques (Section 4.7.4)
    "stent retriever": ["4.7.4"],
    "direct aspiration": ["4.7.4"],
    "first-pass": ["4.7.4"],
    "first pass": ["4.7.4"],
    "conscious sedation": ["4.7.4"],
    "general anesthesia": ["4.7.4"],
    "sedation": ["4.7.4"],
    "intracranial stenting": ["4.7.4"],
    "rescue therapy": ["4.7.4"],
    "rescue stenting": ["4.7.4"],
    # Pediatric EVT (Section 4.7.5)
    "pediatric stroke": ["4.7.5"],
    "pediatric patients with lvo": ["4.7.5"],
    "pediatric lvo": ["4.7.5"],
    # Antithrombotics (Section 4.8-4.9)
    "antiplatelet": ["4.8"],
    "aspirin": ["4.8"],
    "clopidogrel": ["4.8"],
    "dual antiplatelet": ["4.8"],
    "dapt": ["4.8"],
    "anticoagulant": ["4.9"],
    "anticoagulation": ["4.9"],
    "heparin": ["4.9"],
    "doac": ["4.9"],
    "warfarin": ["4.9"],
    "argatroban": ["4.9"],
    # Other acute treatments (Section 4.10-4.12)
    "hemodilution": ["4.10"],
    "neuroprotective": ["4.11"],
    "neuroprotection": ["4.11"],
    "carotid endarterectomy": ["4.12"],
    "cea": ["4.12"],
    "carotid stenting": ["4.12"],
    "cas": ["4.12"],
    # Inpatient management (Section 5.x)
    "stroke unit": ["5.1"],
    "dysphagia": ["5.2"],
    "swallowing": ["5.2"],
    "aspiration": ["5.2"],
    "nutrition": ["5.3"],
    "enteral": ["5.3"],
    "tube feeding": ["5.3"],
    "dvt": ["5.4"],
    "deep vein": ["5.4"],
    "dvt prophylaxis": ["5.4"],
    "venous thromboembolism": ["5.4"],
    "pneumatic compression": ["5.4"],
    "prophylactic heparin": ["5.4"],
    "prophylactic-dose": ["5.4"],
    "prophylactic dose": ["5.4"],
    "subcutaneous heparin": ["5.4"],
    "compression stockings": ["5.4"],
    "elastic compression": ["5.4"],
    "lmwh": ["5.4"],
    "enoxaparin": ["5.4"],
    "depression": ["5.5"],
    "antidepressant": ["5.5"],
    "ssri": ["5.5"],
    "rehabilitation": ["5.7"],
    # Complications (Section 6.x)
    "brain swelling": ["6.1", "6.2"],
    "cerebral edema": ["6.1", "6.2"],
    "herniation": ["6.1", "6.2", "6.3"],
    "osmotic therapy": ["6.2"],
    "mannitol": ["6.2"],
    "hypertonic saline": ["6.2"],
    "decompressive": ["6.3"],
    "craniectomy": ["6.3"],
    "hemicraniectomy": ["6.3"],
    "cerebellar infarction": ["6.4"],
    "seizure": ["6.5"],
    "seizures": ["6.5"],
    "antiepileptic": ["6.5"],
    "antiseizure": ["6.5"],
    # Complications — IVT-specific
    "sich": ["4.6.1"],
    "hemorrhagic transformation": ["4.6.1"],
    "angioedema": ["4.6.1"],
    "orolingual": ["4.6.1"],
    # Contraindications (Table 8)
    "contraindication": ["Table 8"],
    "contraindicated": ["Table 8"],
    "absolute contraindication": ["Table 8"],
    "relative contraindication": ["Table 8"],
    "benefit may exceed risk": ["Table 8"],
    "table 8": ["Table 8"],
}

# Boost value for topic-inferred section matching (lower than explicit +20)
_TOPIC_SECTION_BOOST = 15


STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "can", "could", "should",
    "would", "do", "does", "did", "to", "of", "in", "for", "with", "on",
    "at", "by", "from", "i", "we", "you", "it", "this", "that", "be",
    "have", "has", "had", "will", "not", "no", "or", "and", "but", "if",
    "so", "than", "too", "very", "just", "about", "also", "still",
    "someone", "patient", "person", "give", "get", "use", "take", "don", "need",
    "what", "which", "where", "when", "how", "why", "who",
    "provided", "provide",
}

# Known clinical trial / study names referenced in the AIS guidelines
_KNOWN_TRIALS = {
    "HERMES", "MR CLEAN", "DAWN", "DEFUSE-3", "DEFUSE 3", "AURORA",
    "EXTEND-IA", "ESCAPE", "REVASCAT", "SWIFT PRIME", "THRACE",
    "ANGEL ASPECTS", "ANGEL-ASPECTS", "SELECT2", "SELECT 2", "TESLA",
    "LASTE", "BAOCHE", "BASICS", "ATTENTION", "BEST",
    "ECASS", "ECASS III", "ECASS-III", "NINDS", "IST-3", "IST 3",
    "WAKE-UP", "EXTEND", "ENCHANTED", "TRACE", "TRACE-2", "TRACE 2",
    "TRACE-3", "TRACE 3", "TRACE-III", "TRACE III",
    "AcT", "TASTE", "TIMELESS", "CHABILIS",
    "SITS-MOST", "RACECAT",
    "NOR-TEST", "NOR-TEST 2", "NOR-SASS",
    "RESCUE-JAPAN LIMIT", "RESCUE JAPAN",
    "DIRECT-MT", "DEVT", "MR CLEAN NO IV",
    "SWIFT DIRECT", "SKIP",
    "CHANCE", "POINT", "THALES",
    "INTERACT", "PROACT",
}

# Known variable bounds for operator parsing
_VAR_BOUNDS = {
    "prestrokeMRS": (0, 6),
    "nihss": (0, 42),
    "aspects": (0, 10),
    "age": (0, 120),
    "timeHours": (0, 48),
}


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def extract_section_references(question: str) -> List[str]:
    """Extract explicit section number references from the question.

    Matches patterns like "Section 4.8", "section 4.6.1", "sec 2.3".
    Returns a list of section number strings (e.g., ["4.8", "4.6.1"]).
    """
    pattern = r'\bsect(?:ion)?\s*(\d+(?:\.\d+)*)\b'
    return [m.group(1) for m in re.finditer(pattern, question, re.IGNORECASE)]


def extract_topic_sections(question: str) -> List[str]:
    """Infer guideline section(s) from clinical topic keywords in the question.

    Uses TOPIC_SECTION_MAP to map recognized topics to their correct section(s).
    Longer phrases are checked first so "wake-up stroke" matches before "stroke".
    Returns a deduplicated list of section numbers.
    """
    q_lower = question.lower()
    matched_sections: List[str] = []

    # Compound topic overrides — when two topics co-occur, the combined meaning
    # points to a specific section that neither individual topic would reach.
    _COMPOUND_OVERRIDES = [
        # "blood pressure" + IVT context → 4.6.1 (BP management before IVT rec)
        (["blood pressure", "bp"], ["ivt", "thrombolysis", "alteplase", "thrombolytic"], ["4.6.1"]),
        # "blood pressure" + EVT context → 4.7.4 (post-recanalization BP target)
        (["blood pressure", "bp"], ["evt", "recanalization", "thrombectomy", "endovascular"], ["4.7.4"]),
        # "aspirin" + IVT context → 4.8 (rec about not giving aspirin within 90min of IVT)
        (["aspirin"], ["thrombolysis", "ivt", "alteplase", "90 minutes"], ["4.8"]),
    ]

    for topic_terms, context_terms, sections in _COMPOUND_OVERRIDES:
        has_topic = any(tt in q_lower for tt in topic_terms)
        has_context = any(ct in q_lower for ct in context_terms)
        if has_topic and has_context:
            matched_sections.extend(sections)

    # Sort keys longest-first so multi-word phrases match before single words
    sorted_topics = sorted(TOPIC_SECTION_MAP.keys(), key=len, reverse=True)
    matched_topics: set = set()

    for topic in sorted_topics:
        # Skip if a longer phrase already matched and contains this word
        if any(topic in mt for mt in matched_topics if mt != topic):
            continue
        if topic in q_lower:
            matched_topics.add(topic)
            matched_sections.extend(TOPIC_SECTION_MAP[topic])

    # Deduplicate while preserving order
    seen: set = set()
    result: List[str] = []
    for s in matched_sections:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def extract_search_terms(question: str) -> List[str]:
    """Extract meaningful search terms from question, expanding synonyms."""
    words = re.findall(r'[\w-]+', question.lower())
    terms = set()
    question_lower = question.lower()

    for phrase, expansions in CONCEPT_SYNONYMS.items():
        if phrase in question_lower:
            terms.update(expansions)

    # Preserve COR/LOE values that would otherwise be dropped by length filter.
    # Examples: "2a", "2b", "1", "A", "B-R", "B-NR", "C-LD", "C-EO"
    _COR_LOE_TERMS = {
        "1", "2a", "2b", "3",
        "a", "b-r", "b-nr", "c-ld", "c-eo",
    }

    for word in words:
        if word in STOPWORDS:
            continue
        if len(word) <= 2 and word not in _COR_LOE_TERMS:
            continue
        if word in CONCEPT_SYNONYMS:
            terms.update(CONCEPT_SYNONYMS[word])
        else:
            terms.add(word)

    return list(terms)


def score_recommendation(
    rec: dict,
    search_terms: List[str],
    question: str = "",
    section_refs: Optional[List[str]] = None,
    topic_sections: Optional[List[str]] = None,
) -> int:
    """Score a recommendation dict with weighted field matching.

    Weighting:
    - text (the actual recommendation): 3 points per match
    - metadata (section, sectionTitle, category, evidenceKey): 1 point per match
    - Exact section match: +20 bonus (dominates when user asks about a specific section)
    - Topic-inferred section match: +15 bonus (when topic maps to a known section)
    - Exact recNumber match: +10 bonus
    - Exact COR match: +8 bonus
    - Exact LOE match: +8 bonus
    """
    text_lower = rec.get("text", "").lower()
    metadata_lower = (
        f"{rec.get('section', '')} {rec.get('sectionTitle', '')} "
        f"{rec.get('category', '')} {rec.get('evidenceKey', '')}"
    ).lower()

    score = 0
    for term in search_terms:
        if term in text_lower:
            score += 3
        elif term in metadata_lower:
            score += 1

    # Section number matching — when user explicitly references "Section X.Y",
    # recs from that section get a dominant bonus so they always rank first.
    rec_section = rec.get("section", "")
    if section_refs:
        for ref in section_refs:
            if rec_section == ref or rec_section.startswith(ref + "."):
                score += 20
                break

    # Topic-inferred section matching — when we detect a clinical topic,
    # boost recs from the correct section (lower than explicit refs).
    if topic_sections and not section_refs:
        for ts in topic_sections:
            if rec_section == ts or rec_section.startswith(ts + "."):
                score += _TOPIC_SECTION_BOOST
                break

    # Structured field matching — bonus for explicit COR/LOE/recNumber references
    q_lower = question.lower() if question else ""
    if q_lower:
        rec_number = rec.get("recNumber", "")
        rec_cor = rec.get("cor", "").lower()
        rec_loe = rec.get("loe", "").lower()

        # recNumber matching: "rec 7", "recommendation 7", "rec #7"
        if rec_number:
            rec_num_patterns = [
                rf'\brec(?:ommendation)?\s*#?\s*{re.escape(rec_number)}\b',
            ]
            for pat in rec_num_patterns:
                if re.search(pat, q_lower):
                    score += 10
                    break

        # COR matching: "COR 2a", "COR 1", "class 2a", "class of recommendation 2a"
        if rec_cor:
            cor_patterns = [
                rf'\bcor\s+{re.escape(rec_cor)}\b',
                rf'\bclass\s+(?:of\s+recommendation\s+)?{re.escape(rec_cor)}\b',
            ]
            for pat in cor_patterns:
                if re.search(pat, q_lower):
                    score += 8
                    break

        # LOE matching: "LOE B-NR", "LOE A", "level of evidence B-NR"
        if rec_loe:
            loe_patterns = [
                rf'\bloe\s+{re.escape(rec_loe)}\b',
                rf'\blevel\s+(?:of\s+evidence\s+)?{re.escape(rec_loe)}\b',
            ]
            for pat in loe_patterns:
                if re.search(pat, q_lower):
                    score += 8
                    break

        # Sentiment-COR alignment — when the question asks about harm, benefit,
        # or a specific clinical entity, boost recs whose COR matches that sentiment.
        rec_cor_val = rec.get("cor", "")

        # Negative-sentiment keywords → boost COR 3 recs
        _NEGATIVE_TERMS = {
            "harm", "harmful", "not recommended", "contraindicated",
            "should not", "avoid", "no benefit", "ineffective",
            "substitute for", "instead of",
            "delayed", "should be delayed",
            "without advanced imaging",
            "prophylactic antiseizure",
        }
        _POSITIVE_TERMS = {
            "is recommended", "should be used", "is beneficial",
        }
        has_negative = any(nt in q_lower for nt in _NEGATIVE_TERMS)
        has_positive = any(pt in q_lower for pt in _POSITIVE_TERMS)

        if has_negative and rec_cor_val.startswith("3"):
            score += 6
        elif has_negative and rec_cor_val == "1":
            score -= 3
        elif has_positive and rec_cor_val == "1":
            score += 4

    return score


def score_text(text: str, search_terms: List[str]) -> int:
    """Score a text block by how many search terms match."""
    text_lower = text.lower()
    return sum(1 for term in search_terms if term in text_lower)


def extract_numeric_context(question: str) -> dict:
    """Extract numeric values from the question for context."""
    context = {}
    plt_match = re.search(r'platelet\w*\s+(?:of\s+)?(\d[\d,]*)', question, re.I)
    if plt_match:
        context["platelets"] = int(plt_match.group(1).replace(",", ""))
    inr_match = re.search(r'inr\s+(?:of\s+)?(\d+\.?\d*)', question, re.I)
    if inr_match:
        context["inr"] = float(inr_match.group(1))
    return context


def _parse_value_with_operator(pattern: str, text: str, var_name: str, is_int: bool = True) -> Any:
    """Parse a clinical variable that may include comparison operator, range, or plain value."""
    cast = int if is_int else float

    comp_pattern = (
        pattern + r'\s*(?:score\s*)?(?:of\s*)?'
        r'(?:(<=?|>=?|less\s+than|greater\s+than|under|over|above|below)\s*(\d+\.?\d*))'
    )
    comp_match = re.search(comp_pattern, text, re.I)
    if comp_match:
        op_str = comp_match.group(1).strip().lower()
        val = cast(comp_match.group(2))
        lo_bound, hi_bound = _VAR_BOUNDS.get(var_name, (0, 9999))
        if op_str in ("<", "less than", "under", "below"):
            return (lo_bound, val - (1 if is_int else 0.1))
        elif op_str == "<=":
            return (lo_bound, val)
        elif op_str in (">", "greater than", "over", "above"):
            return (val + (1 if is_int else 0.1), hi_bound)
        elif op_str == ">=":
            return (val, hi_bound)

    range_pattern = (
        pattern + r'\s*(?:score\s*)?(?:of\s*)?(\d+\.?\d*)\s*(?:[-\u2013]|to)\s*(\d+\.?\d*)'
    )
    range_match = re.search(range_pattern, text, re.I)
    if range_match:
        return (cast(range_match.group(1)), cast(range_match.group(2)))

    plain_pattern = pattern + r'\s*(?:score\s*)?(?:of\s*)?(\d+\.?\d*)'
    plain_match = re.search(plain_pattern, text, re.I)
    if plain_match:
        return cast(plain_match.group(1))

    return None


def extract_clinical_variables(question: str) -> Dict[str, Any]:
    """Extract clinical variable-value pairs from a question for applicability gating."""
    variables: Dict[str, Any] = {}
    q = question.lower()

    mrs_val = _parse_value_with_operator(r'(?:mrs|modified\s+rankin)', q, "prestrokeMRS", is_int=True)
    if mrs_val is not None:
        variables["prestrokeMRS"] = mrs_val

    nihss_val = _parse_value_with_operator(r'nihss', q, "nihss", is_int=True)
    if nihss_val is not None:
        variables["nihss"] = nihss_val

    aspects_val = _parse_value_with_operator(r'aspects', q, "aspects", is_int=True)
    if aspects_val is not None:
        variables["aspects"] = aspects_val

    age_val = _parse_value_with_operator(r'age', q, "age", is_int=True)
    if age_val is None:
        # Match "65 year old", "65yo", "65y/o", "65yr"
        age_match = re.search(r'(\d{1,3})\s*[-\s]*(?:y/?o|year|yr)', q, re.I)
        if age_match:
            age_val = int(age_match.group(1))
    if age_val is None:
        # Match "71M", "65F" — age directly followed by gender with no space
        age_gender_match = re.search(r'\b(\d{1,3})\s*(?:m|f)\b', q, re.I)
        if age_gender_match:
            candidate = int(age_gender_match.group(1))
            # Only treat as age if plausible (18-120) to avoid matching NIHSS etc.
            if 18 <= candidate <= 120:
                age_val = candidate
    if age_val is not None:
        variables["age"] = age_val

    time_val = _parse_value_with_operator(r'(?:time|onset|within)', q, "timeHours", is_int=False)
    if time_val is None:
        time_match = re.search(
            r'(\d+\.?\d*)\s*(?:[-\u2013]|to)\s*(\d+\.?\d*)\s*(?:h(?:our)?s?)\b', q, re.I
        )
        if time_match:
            time_val = (float(time_match.group(1)), float(time_match.group(2)))
        else:
            time_match = re.search(r'(\d+\.?\d*)\s*(?:h(?:our)?s?)\b', q, re.I)
            if time_match:
                time_val = float(time_match.group(1))
    if time_val is not None:
        variables["timeHours"] = time_val

    for vessel_term, vessel_val in [
        ("basilar", "basilar"), ("m1", "M1"), ("m2", "M2"),
        ("ica", "ICA"), ("t-ica", "T-ICA"),
    ]:
        if re.search(rf'\b{vessel_term}\b', q, re.I):
            variables["vessel"] = vessel_val
            break

    # Wake-up stroke detection
    if re.search(r'\bwake[\s-]?up\s+stroke\b', q, re.I) or re.search(r'\bwoke\b.*\bsymptom', q, re.I):
        variables["wakeUp"] = True

    return variables


# ---------------------------------------------------------------------------
# Applicability gating (rule-based filtering)
# ---------------------------------------------------------------------------

def build_rec_to_conditions(rule_engine) -> Dict[str, List[Dict]]:
    """Build mapping: rec_id -> list of condition clause dicts from rules that fire that rec."""
    rec_conditions: Dict[str, List[Dict]] = {}
    for rule in rule_engine.rules:
        if not rule.enabled:
            continue
        fired_ids = []
        for action in rule.actions:
            if action.type == "fire" and action.recIds:
                fired_ids.extend(action.recIds)
        if not fired_ids:
            continue
        clauses = _extract_leaf_clauses(rule.condition)
        for rec_id in fired_ids:
            if rec_id not in rec_conditions:
                rec_conditions[rec_id] = []
            rec_conditions[rec_id].extend(clauses)
    return rec_conditions


def _extract_leaf_clauses(condition) -> List[Dict]:
    """Recursively extract {var, op, val} leaf clauses from a condition tree."""
    clauses = []
    if not hasattr(condition, 'clauses'):
        return clauses
    for clause in condition.clauses:
        if isinstance(clause, RuleClause):
            clauses.append({"var": clause.var, "op": clause.op, "val": clause.val})
        elif isinstance(clause, RuleCondition):
            clauses.extend(_extract_leaf_clauses(clause))
        elif isinstance(clause, dict):
            if "var" in clause:
                clauses.append(clause)
            elif "logic" in clause:
                for sub in clause.get("clauses", []):
                    if isinstance(sub, dict) and "var" in sub:
                        clauses.append(sub)
    return clauses


def check_applicability(
    rec_id: str,
    extracted_vars: Dict[str, Any],
    rec_conditions: Dict[str, List[Dict]],
) -> bool:
    """Check if a recommendation's rule conditions overlap with the user's variable values."""
    conditions = rec_conditions.get(rec_id, [])
    if not conditions:
        return True

    for var_name, user_val in extracted_vars.items():
        var_clauses = [c for c in conditions if c["var"] == var_name]
        if not var_clauses:
            continue

        rec_lo = None
        rec_hi = None
        rec_exact = None
        for clause in var_clauses:
            op = clause["op"]
            val = clause["val"]
            if op == "==":
                rec_exact = val
            elif op in (">=", ">"):
                rec_lo = val
            elif op in ("<=", "<"):
                rec_hi = val

        if isinstance(user_val, tuple):
            user_lo, user_hi = user_val
        else:
            user_lo = user_hi = user_val

        if rec_exact is not None:
            if not (user_lo <= rec_exact <= user_hi):
                return False
        else:
            if rec_lo is None:
                rec_lo = -9999
            if rec_hi is None:
                rec_hi = 9999
            if not (user_lo <= rec_hi and user_hi >= rec_lo):
                return False

    return True


# ---------------------------------------------------------------------------
# Knowledge store search
# ---------------------------------------------------------------------------

def search_knowledge_store(
    knowledge: Dict[str, Any],
    search_terms: List[str],
    max_results: int = 5,
    section_refs: Optional[List[str]] = None,
    topic_sections: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Search the guideline knowledge store (RSS, synopsis, knowledge gaps)."""
    sections = knowledge.get("sections", {})
    scored_results: List[Tuple[int, Dict[str, Any]]] = []

    for sec_num, sec_data in sections.items():
        section_title = sec_data.get("sectionTitle", "")
        title_text = f"{sec_num} {section_title}".lower()
        title_boost = sum(2 for term in search_terms if term.lower() in title_text)

        # When user explicitly references a section, boost all content from it
        if section_refs:
            for ref in section_refs:
                if sec_num == ref or sec_num.startswith(ref + "."):
                    title_boost += 20
                    break

        # Topic-inferred section boost (only when no explicit section ref)
        if topic_sections and not section_refs:
            for ts in topic_sections:
                if sec_num == ts or sec_num.startswith(ts + "."):
                    title_boost += _TOPIC_SECTION_BOOST
                    break

        for rss_entry in sec_data.get("rss", []):
            rss_text = rss_entry.get("text", "")
            if not rss_text:
                continue
            s = score_text(rss_text, search_terms) + title_boost
            if s > 0:
                scored_results.append((s, {
                    "type": "rss",
                    "section": sec_num,
                    "sectionTitle": section_title,
                    "recNumber": rss_entry.get("recNumber"),
                    "text": rss_text,
                }))

        synopsis = sec_data.get("synopsis", "")
        if synopsis:
            s = score_text(synopsis, search_terms) + title_boost
            if s > 0:
                scored_results.append((s, {
                    "type": "synopsis",
                    "section": sec_num,
                    "sectionTitle": section_title,
                    "text": synopsis,
                }))

        kg = sec_data.get("knowledgeGaps", "")
        if kg:
            s = score_text(kg, search_terms) + title_boost
            if s > 0:
                scored_results.append((s, {
                    "type": "knowledge_gaps",
                    "section": sec_num,
                    "sectionTitle": section_title,
                    "text": kg,
                }))

    scored_results.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored_results[:max_results]]


# ---------------------------------------------------------------------------
# Summary generation (fallback when LLM unavailable)
# ---------------------------------------------------------------------------

def _cor_strength(cor: str) -> str:
    if cor == "1": return "is recommended"
    if cor == "2a": return "is reasonable"
    if cor == "2b": return "may be reasonable"
    if cor.startswith("3") and "Harm" in cor: return "is not recommended (causes harm)"
    if cor.startswith("3"): return "is not recommended (no benefit)"
    return ""


def generate_summary(
    scored_recs: List[Tuple[int, dict]],
    knowledge_results: List[Dict[str, Any]],
    question: str,
) -> str:
    """Generate a concise 1-3 sentence summary from the top-matched results."""
    if not scored_recs and not knowledge_results:
        return ""

    all_sections = set()
    for _, rec in scored_recs[:5]:
        all_sections.add(rec.get("section", ""))
    for entry in knowledge_results:
        all_sections.add(entry["section"])

    cor_order = {"1": 0, "2a": 1, "2b": 2, "3:No Benefit": 3, "3:Harm": 4}
    top_recs = [(s, r) for s, r in scored_recs[:5] if s >= 1]
    if top_recs:
        top_recs.sort(key=lambda x: cor_order.get(x[1].get("cor", ""), 5))

    parts = []
    if top_recs:
        best = top_recs[0][1]
        strength = _cor_strength(best.get("cor", ""))
        section_str = f"Section {best.get('section', '')}"
        if strength:
            parts.append(
                f"The guideline addresses this across {len(all_sections)} "
                f"section{'s' if len(all_sections) > 1 else ''}. "
                f"The strongest recommendation ({section_str}, COR {best.get('cor', '')}) "
                f"indicates this {strength}."
            )
        else:
            parts.append(
                f"Found {len(top_recs)} relevant recommendation{'s' if len(top_recs) > 1 else ''} "
                f"across {len(all_sections)} section{'s' if len(all_sections) > 1 else ''}."
            )
    elif knowledge_results:
        entry = knowledge_results[0]
        sec = entry["section"]
        if entry["type"] == "rss":
            parts.append(
                f"Found supporting evidence in Section {sec}. "
                f"Relevant evidence available across {len(all_sections)} section{'s' if len(all_sections) > 1 else ''}."
            )
        else:
            parts.append(f"Found relevant guideline content across {len(all_sections)} section{'s' if len(all_sections) > 1 else ''}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Trial name extraction
# ---------------------------------------------------------------------------

def extract_trial_names(text: str) -> List[str]:
    """Extract clinical trial/study names mentioned in text."""
    found = []
    text_upper = text.upper()
    for trial in _KNOWN_TRIALS:
        if trial.upper() in text_upper:
            found.append(trial)

    pattern_matches = re.findall(
        r'the\s+([A-Z][A-Z0-9][-A-Z0-9\s]*[A-Z0-9])\s+(?:study|trial|meta-analysis|registry)',
        text
    )
    skip_words = {"THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "ALL"}
    for match in pattern_matches:
        name = match.strip()
        if len(name) >= 3 and name.upper() not in skip_words and name.upper() not in {t.upper() for t in found}:
            found.append(name)

    seen = set()
    result = []
    for t in found:
        key = t.upper().replace("-", " ").replace("  ", " ")
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def clean_pdf_text(text: str) -> str:
    """Remove raw PDF artifacts from extracted text."""
    text = text.replace('\x07', '')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\bCOR\s+LOE\s+Recommendations?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\d+\.\s*', '', text.strip())
    return text.strip()


def strip_rec_prefix_from_rss(rss_text: str, rec_texts: List[str]) -> str:
    """Strip the recommendation text that often prefixes RSS entries."""
    norm_rss = re.sub(r'\s+', ' ', rss_text).strip()

    for rec_text in rec_texts:
        norm_rec = re.sub(r'\s+', ' ', rec_text).strip()

        prefix = norm_rec[:60]
        idx = norm_rss.find(prefix)
        if idx != -1 and idx < 40:
            rec_end = idx + len(norm_rec)
            if rec_end < len(norm_rss):
                remainder = norm_rss[rec_end:].strip()
                remainder = re.sub(r'^[\s,;.\-\u2014\d]+', '', remainder)
                if len(remainder) > 50:
                    return remainder

        rec_words = set(re.findall(r'[a-z]{4,}', norm_rec.lower()))
        if not rec_words:
            continue

        sentences = re.split(r'(?<=[.!?])(?:\d[\d,\-]*)*\s+', norm_rss)
        sent_positions = []
        pos = 0
        for sent in sentences:
            start = norm_rss.find(sent, pos)
            if start == -1:
                start = pos
            sent_positions.append((start, sent))
            pos = start + len(sent)

        overlap_end = 0
        for i, (start, sent) in enumerate(sent_positions):
            sent_words = set(re.findall(r'[a-z]{4,}', sent.lower()))
            if not sent_words:
                continue
            overlap = len(sent_words & rec_words) / len(sent_words)
            if overlap >= 0.5:
                overlap_end = start + len(sent)
            else:
                break

        if overlap_end > 0 and overlap_end < len(norm_rss) - 50:
            remainder = norm_rss[overlap_end:].strip()
            remainder = re.sub(r'^[\s,;.\-\u2014\d]+', '', remainder)
            if len(remainder) > 50:
                return remainder

    return rss_text


def truncate_text(text: str, max_chars: int = 600) -> str:
    """Truncate text to max_chars, ending at a sentence boundary if possible."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind('. ')
    if last_period > max_chars * 0.8:
        return truncated[:last_period + 1]
    last_newline = truncated.rfind('\n')
    if last_newline > max_chars * 0.8:
        return truncated[:last_newline]
    return truncated.rstrip() + "..."


# ---------------------------------------------------------------------------
# Verbatim check
# ---------------------------------------------------------------------------

def verify_verbatim(answer_text: str, guideline_knowledge: Dict[str, Any]) -> List[str]:
    """Check if recommendation text in the answer matches the guideline source verbatim."""
    mismatches = []
    sections = guideline_knowledge.get("sections", {})

    section_blocks = re.findall(
        r'\*\*Section\s+([\d.]+)(?:\s*\[.*?\])?\s*:\*\*\s*(.+?)(?=\n\n\*\*|\n\n$|$)',
        answer_text, re.DOTALL
    )

    for sec_num, block_text in section_blocks:
        sec_data = sections.get(sec_num)
        if not sec_data:
            continue

        clean_block = clean_pdf_text(block_text.strip())
        if len(clean_block) < 30:
            continue

        found_match = False
        for rss_entry in sec_data.get("rss", []):
            rss_text = clean_pdf_text(rss_entry.get("text", ""))
            block_prefix = clean_block[:80].lower()
            source_lower = rss_text.lower()
            if block_prefix in source_lower or source_lower[:80] in clean_block.lower():
                found_match = True
                break

        if not found_match:
            synopsis = clean_pdf_text(sec_data.get("synopsis", ""))
            if synopsis and clean_block[:80].lower() in synopsis.lower():
                found_match = True

        if not found_match:
            mismatches.append(f"Section {sec_num}: Text may not be verbatim from guideline source")

    return mismatches


# ---------------------------------------------------------------------------
# Main Q&A function
# ---------------------------------------------------------------------------

async def answer_question(
    question: str,
    recommendations_store: Dict[str, Any],
    guideline_knowledge: Dict[str, Any],
    rule_engine=None,
    nlp_service=None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Answer a clinical question about AIS management.

    Searches three layers:
    1. Recommendation text (formal guideline recommendations with COR/LOE)
    2. RSS — evidence, studies, rationale
    3. Synopsis and Knowledge Gaps — context and research directions
    """
    context = context or {}
    search_terms = extract_search_terms(question)
    section_refs = extract_section_references(question)
    topic_sections = extract_topic_sections(question)
    numeric_ctx = extract_numeric_context(question)
    clinical_vars = extract_clinical_variables(question)
    context_summary_parts: List[str] = []

    # Detect if the user is asking a general question (not about the active case)
    q_lower = question.lower()
    is_general_question = any(phrase in q_lower for phrase in [
        "in general", "not regarding", "not about this patient",
        "not for this patient", "not this patient",
        "what is the", "what are the", "what's the",
        "when is", "when should", "when can",
        "is there a recommendation", "what does the guideline say",
        "regardless of", "for any patient",
    ])

    # Merge scenario context into search ONLY for case-specific questions
    use_case_context = bool(context) and not is_general_question
    if use_case_context:
        ctx_vessel = context.get("vessel")
        if ctx_vessel:
            vessel_lower = str(ctx_vessel).lower()
            extra = CONCEPT_SYNONYMS.get(vessel_lower, [vessel_lower])
            search_terms = list(set(search_terms + extra))
        if context.get("wakeUp"):
            search_terms = list(set(search_terms + ["wake", "unknown", "onset", "extended"]))
        if context.get("isM2"):
            search_terms = list(set(search_terms + ["m2", "medium vessel", "mevo"]))
        for key in ("nihss", "age", "timeHours", "vessel", "prestrokeMRS", "aspects"):
            if key not in clinical_vars and context.get(key) is not None:
                clinical_vars[key] = context[key]

        parts = []
        if context.get("age"): parts.append(f"{context['age']}y")
        if context.get("sex"): parts.append("M" if str(context["sex"]).lower() == "male" else "F")
        if context.get("nihss") is not None: parts.append(f"NIHSS {context['nihss']}")
        if context.get("vessel"): parts.append(str(context["vessel"]))
        if context.get("wakeUp"): parts.append("wake-up stroke")
        elif context.get("timeHours") is not None: parts.append(f"{context['timeHours']}h from onset")
        if parts:
            context_summary_parts.append(", ".join(parts))
    elif is_general_question:
        # For general questions, don't use patient context for applicability gating
        # but still use search terms from the question itself
        clinical_vars = extract_clinical_variables(question)

    # Build rec-to-conditions mapping for applicability gating
    # Skip gating for general questions — show all matching recommendations
    rec_conditions: Dict[str, List[Dict]] = {}
    if rule_engine and clinical_vars and not is_general_question:
        rec_conditions = build_rec_to_conditions(rule_engine)

    is_evidence_question = any(
        term in question.lower()
        for term in ["study", "studies", "trial", "data", "evidence", "research", "rct", "provided", "why"]
    )

    # Score all recommendations
    scored: List[Tuple[int, dict]] = []
    for rec_id, rec in recommendations_store.items():
        rec_dict = rec if isinstance(rec, dict) else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
        score = score_recommendation(rec_dict, search_terms, question=question, section_refs=section_refs, topic_sections=topic_sections)
        if score > 0:
            if clinical_vars and rec_conditions:
                if not check_applicability(rec_id, clinical_vars, rec_conditions):
                    continue
            scored.append((score, rec_dict))

    scored.sort(key=lambda x: -x[0])

    # ── Clarification Detection ──────────────────────────────
    # If top-scored recommendations have CONFLICTING COR levels for the same
    # topic, and the question doesn't specify the distinguishing variable,
    # ask for clarification instead of guessing.
    CLARIFICATION_RULES = [
        {
            "topic_terms": ["m2"],
            "distinguishing_var": "m2Dominant",
            "question_keywords": ["dominant", "nondominant", "non-dominant", "codominant", "proximal", "m3"],
            "sections": ["4.7.2"],
            "clarification": (
                "The EVT recommendation for M2 occlusions depends on whether the occlusion "
                "is in the **dominant proximal** or **non-dominant/codominant** division:\n\n"
                "- **Dominant proximal M2:** EVT is reasonable within 6 hours "
                "(Section 4.7.2 Rec 7, COR 2a, LOE B-NR)\n"
                "- **Non-dominant or codominant M2:** EVT is NOT recommended "
                "(Section 4.7.2 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
                "Which type of M2 occlusion are you asking about?"
            ),
        },
        {
            "topic_terms": ["ivt", "thrombolysis", "tpa", "alteplase"],
            "distinguishing_var": "nonDisabling",
            "question_keywords": ["disabling", "non-disabling", "nondisabling", "mild"],
            "sections": ["4.6.1"],
            "clarification": (
                "The IVT recommendation depends on whether the deficit is **disabling** "
                "or **non-disabling**:\n\n"
                "- **Disabling deficit:** IVT is recommended regardless of NIHSS score "
                "(Section 4.6.1 Rec 1, COR 1, LOE A)\n"
                "- **Non-disabling deficit (NIHSS 0-5):** IVT is NOT recommended "
                "(Section 4.6.1 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
                "Is the deficit disabling or non-disabling?"
            ),
        },
    ]

    # Check if any clarification rule applies.
    # Only fire when the question is specifically about the topic's recommendation
    # (eligibility / whether to give / indication), not when the topic is merely
    # mentioned as context for a different clinical question.
    # Strategy: require at least one "eligibility intent" keyword alongside the
    # topic term, OR if the topic term is the dominant subject of the question
    # (no other clinical topic detected via TOPIC_SECTION_MAP).

    # If topic_sections resolved to a section OTHER than the clarification rule's
    # sections, the question is about something else — skip clarification.
    _ELIGIBILITY_KEYWORDS = {
        "recommend", "recommended", "indication", "indicated", "eligible",
        "eligibility", "candidate", "appropriate",
        "can i give", "is it safe", "should i give", "should we give",
        "is ivt recommended", "is thrombolysis recommended",
    }

    # Contraindication questions should never trigger clarification — they need
    # Table 8 content, not the disabling/nondisabling distinction.
    _is_contraindication_q = any(ct in q_lower for ct in [
        "contraindication", "contraindicated", "table 8",
        "absolute", "relative",
    ])

    for rule in CLARIFICATION_RULES:
        topic_match = any(t in q_lower for t in rule["topic_terms"])
        already_specified = any(kw in q_lower for kw in rule["question_keywords"])
        var_in_context = clinical_vars.get(rule["distinguishing_var"]) is not None

        # Bypass if topic sections point away from this rule's sections.
        # If the topic map resolved to ANY section not in the rule's sections,
        # the question is about a more specific sub-topic (e.g., tenecteplase
        # → 4.6.2, not the general IVT eligibility question in 4.6.1).
        rule_sections = set(rule.get("sections", []))
        if topic_sections:
            topic_set = set(topic_sections)
            # If ANY topic section is outside the rule's sections, skip
            if topic_set - rule_sections:
                continue

        # Require an eligibility-intent keyword to avoid false triggers
        has_eligibility_intent = any(ek in q_lower for ek in _ELIGIBILITY_KEYWORDS)

        if topic_match and not already_specified and not var_in_context and has_eligibility_intent and not _is_contraindication_q:
            return {
                "answer": rule["clarification"],
                "summary": rule["clarification"].split("\n")[0],
                "citations": [],
                "relatedSections": sorted(rule.get("sections", [])),
                "referencedTrials": [],
                "needsClarification": True,
            }

    knowledge_results = search_knowledge_store(
        guideline_knowledge, search_terms,
        max_results=7 if is_evidence_question else 5,
        section_refs=section_refs,
        topic_sections=topic_sections,
    )

    answer_parts = []
    citations = []
    sections: set = set()
    all_trial_names: List[str] = []

    # ── Contraindication Tier Classification (Table 8) ──────────────
    # When the question asks about a specific contraindication, classify it
    # into the correct tier from Table 8 and include that in the answer.
    if _is_contraindication_q:
        t8_data = guideline_knowledge.get("sections", {}).get("Table 8", {})
        t8_synopsis = t8_data.get("synopsis", "")
        if t8_synopsis:
            # Determine which tier matches the question
            # Table 8 tiers: Absolute, Relative, Benefit Over Risk
            _ABSOLUTE_TERMS = [
                "intracranial hemorrhage", "extensive regions", "obvious hypodensity",
                "traumatic brain injury", "tbi within 14 days",
                "intracranial or intraspinal neurosurgery", "neurosurgery within 14 days",
                "spinal cord injury", "intra-axial", "intra-axial intracranial neoplasm",
                "infective endocarditis", "severe coagulopathy",
                "platelets <100,000", "platelet count below 100000",
                "inr >1.7", "inr above 1.7", "pt >15", "pt above 15",
                "aptt >40", "aptt above 40",
                "aortic arch dissection",
                "amyloid", "aria",
                "active internal bleeding",
                "blood glucose less than 50", "glucose <50",
                "multilobar infarction",
                "direct thrombin inhibitor",
                "history of intracranial hemorrhage",
                "ct showing multilobar",
            ]
            _RELATIVE_TERMS = [
                "doac within 48", "doac",
                "ischemic stroke within 3 months",
                "prior intracranial hemorrhage",
                "recent non-cns trauma",
                "recent non-cns surgery",
                "recent gi", "recent gu", "urinary tract hemorrhage",
                "gastrointestinal", "gi or urinary",
                "cervical or intracranial arterial dissection",
                "pregnancy", "postpartum",
                "active systemic malignancy",
                "major surgery within 14 days",
                "major surgery",
                "recent myocardial infarction", "mi within 3 months",
            ]
            _BENEFIT_TERMS = [
                "extracranial cervical", "cervical arterial dissection",
                "extra-axial intracranial neoplasm", "extra-axial",
                "unruptured intracranial aneurysm", "unruptured aneurysm",
                "moya-moya", "moyamoya",
                "seizure at onset",
                "cerebral microbleed", "microbleeds on mri",
            ]

            tier = None
            if any(at in q_lower for at in _ABSOLUTE_TERMS):
                tier = "Absolute"
            elif any(bt in q_lower for bt in _BENEFIT_TERMS):
                tier = "Benefit May Exceed Risk"
            elif any(rt in q_lower for rt in _RELATIVE_TERMS):
                tier = "Relative"

            if tier:
                answer_parts.append(
                    f"**Table 8 — IVT Contraindication Classification: {tier}**\n\n"
                    f"Per Table 8 of the 2026 AHA/ASA AIS Guidelines, this is classified as "
                    f"an **{tier}** contraindication to IVT."
                )
                citations.append(f"Table 8 -- IVT Contraindications and Special Situations ({tier})")
                sections.add("Table 8")

    # Table 8 numeric alerts
    if numeric_ctx.get("platelets") is not None:
        plt = numeric_ctx["platelets"]
        if plt < 100000:
            answer_parts.append(
                f"**Platelet count {plt:,}/\u00b5L is below the 100,000/\u00b5L threshold.** "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT. "
                "Thresholds: platelets <100,000/\u00b5L, INR >1.7, aPTT >40 s, or PT >15 s."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

    if numeric_ctx.get("inr") is not None:
        inr = numeric_ctx["inr"]
        if inr > 1.7:
            answer_parts.append(
                f"**INR {inr} exceeds the 1.7 threshold.** "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

    if is_evidence_question and knowledge_results:
        evidence_rec_texts = [r.get("text", "") for s, r in scored[:3] if s >= 1]
        seen_evidence_rss: set = set()

        for entry in knowledge_results:
            sec = entry["section"]
            title = entry["sectionTitle"]
            entry_type = entry["type"]
            full_text = entry["text"]
            all_trial_names.extend(extract_trial_names(full_text))
            cleaned_text = clean_pdf_text(full_text)

            if entry_type == "rss":
                rec_num = entry.get("recNumber", "")
                rss_key = f"{sec}:{rec_num}"
                if rss_key in seen_evidence_rss:
                    continue
                seen_evidence_rss.add(rss_key)
                if len(cleaned_text) < 350 and rec_num:
                    if re.search(r'\b[12](?:a|b)?\s*\n?\s*[A-C](?:-[A-Z]{1,3})?\s*$', full_text.strip()):
                        continue
                cleaned_text = strip_rec_prefix_from_rss(cleaned_text, evidence_rec_texts)
                text = truncate_text(cleaned_text, max_chars=500)
                if len(text.strip()) < 40:
                    continue
                label = f"Evidence for Section {sec}"
                if rec_num:
                    label += f", Rec {rec_num}"
                answer_parts.append(f"**{label}:** {text}")
                citations.append(f"Section {sec} -- {title} (Recommendation-Specific Supportive Text)")
            elif entry_type == "synopsis":
                text = truncate_text(cleaned_text, max_chars=600)
                answer_parts.append(f"**Synopsis, Section {sec}:** {text}")
                citations.append(f"Section {sec} -- {title} (Synopsis)")
            elif entry_type == "knowledge_gaps":
                text = truncate_text(cleaned_text, max_chars=400)
                answer_parts.append(f"**Knowledge Gaps, Section {sec}:** {text}")
                citations.append(f"Section {sec} -- {title} (Knowledge Gaps)")
            sections.add(sec)

        for score, rec in scored[:3]:
            if score < 1:
                continue
            cor_badge = f"COR {rec.get('cor', '')}"
            loe_badge = f"LOE {rec.get('loe', '')}"
            badge = f" [{cor_badge}, {loe_badge}]"
            answer_parts.append(f"**Section {rec.get('section', '')}{badge}:** {rec.get('text', '')}")
            citations.append(f"Section {rec.get('section', '')} -- {rec.get('sectionTitle', '')} (COR {rec.get('cor', '')}, LOE {rec.get('loe', '')})")
            all_trial_names.extend(extract_trial_names(rec.get("text", "")))
            sections.add(rec.get("section", ""))
    else:
        included_rec_sections: set = set()
        included_rec_texts: List[str] = []
        for score, rec in scored[:5]:
            if score < 1:
                continue
            cor_badge = f"COR {rec.get('cor', '')}"
            loe_badge = f"LOE {rec.get('loe', '')}"
            badge = f" [{cor_badge}, {loe_badge}]"
            answer_parts.append(f"**Section {rec.get('section', '')}{badge}:** {rec.get('text', '')}")
            citations.append(f"Section {rec.get('section', '')} -- {rec.get('sectionTitle', '')} (COR {rec.get('cor', '')}, LOE {rec.get('loe', '')})")
            all_trial_names.extend(extract_trial_names(rec.get("text", "")))
            sections.add(rec.get("section", ""))
            included_rec_sections.add(rec.get("section", ""))
            included_rec_texts.append(rec.get("text", ""))

        num_formal_recs = len([s for s, r in scored[:5] if s >= 1])
        max_knowledge = 2 if num_formal_recs >= 3 else 5
        seen_rss_keys: set = set()
        knowledge_count = 0

        for entry in knowledge_results:
            if knowledge_count >= max_knowledge:
                break
            sec = entry["section"]
            title = entry["sectionTitle"]
            entry_type = entry["type"]
            full_text = entry["text"]
            all_trial_names.extend(extract_trial_names(full_text))

            if entry_type == "synopsis" and sec in included_rec_sections:
                continue

            if entry_type == "rss":
                rec_num = entry.get("recNumber", "")
                rss_key = f"{sec}:{rec_num}"
                if rss_key in seen_rss_keys:
                    continue
                seen_rss_keys.add(rss_key)

            cleaned_text = clean_pdf_text(full_text)

            if entry_type == "rss":
                rec_num = entry.get("recNumber", "")
                if len(cleaned_text) < 350 and rec_num:
                    if re.search(r'\b[12](?:a|b)?\s*\n?\s*[A-C](?:-[A-Z]{1,3})?\s*$', full_text.strip()):
                        continue
                cleaned_text = strip_rec_prefix_from_rss(cleaned_text, included_rec_texts)
                text = truncate_text(cleaned_text, max_chars=500)
                if len(text.strip()) < 40:
                    continue
                label = f"Supporting Evidence, Section {sec}"
                if rec_num:
                    label += f" Rec {rec_num}"
                answer_parts.append(f"**{label}:** {text}")
                citations.append(f"Section {sec} -- {title} (Recommendation-Specific Supportive Text)")
            elif entry_type == "synopsis":
                text = truncate_text(cleaned_text, max_chars=600)
                answer_parts.append(f"**{title}:** {text}")
                citations.append(f"Section {sec} -- {title} (Synopsis)")
            elif entry_type == "knowledge_gaps":
                text = truncate_text(cleaned_text, max_chars=400)
                answer_parts.append(f"**Knowledge Gaps, Section {sec}:** {text}")
                citations.append(f"Section {sec} -- {title} (Knowledge Gaps)")

            sections.add(sec)
            knowledge_count += 1

    # Deduplicate trial names
    seen_trials: set = set()
    unique_trials: List[str] = []
    for t in all_trial_names:
        key = t.upper().replace("-", " ").replace("  ", " ")
        if key not in seen_trials:
            seen_trials.add(key)
            unique_trials.append(t)

    if unique_trials:
        answer_parts.append("**Referenced Studies/Articles:** " + ", ".join(unique_trials))

    if not answer_parts:
        answer = (
            "I could not find specific guideline recommendations matching your question. "
            "Consider rephrasing or consult the full 2026 AHA/ASA AIS guideline."
        )
        summary = ""
    else:
        if context_summary_parts:
            answer_parts.insert(0, f"**For this patient ({context_summary_parts[0]}):**")
        answer = "\n\n".join(answer_parts)

        # LLM summary or fallback to template
        if nlp_service:
            patient_ctx = context_summary_parts[0] if context_summary_parts else ""
            summary = await nlp_service.summarize_qa(question, answer, citations, patient_context=patient_ctx)
        else:
            summary = generate_summary(scored, knowledge_results, question)

    unique_citations = list(dict.fromkeys(citations))

    return {
        "answer": answer,
        "summary": summary,
        "citations": unique_citations,
        "relatedSections": sorted(s for s in sections if s),
        "referencedTrials": unique_trials,
    }
