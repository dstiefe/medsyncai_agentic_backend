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
    "ht": ["hemorrhagic transformation", "hemorrhagic conversion", "ht"],
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
    "sickle cell": ["sickle", "sickle cell", "scd"],
    "scd": ["sickle", "sickle cell", "scd"],
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
    "m1": ["m1", "large vessel", "lvo", "mca", "ica"],
    "m2": ["m2", "medium vessel", "mevo", "mca"],
    "m3": ["m3", "distal", "medium vessel", "mevo", "mca"],
    "lvo": ["lvo", "large vessel", "m1", "ica", "thrombectomy"],
    "ica": ["ica", "internal carotid", "large vessel", "lvo"],
    "aca": ["aca", "anterior cerebral", "a2", "a3", "medium vessel"],
    "distal": ["distal", "m3", "medium vessel", "mevo"],
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
    "door-to-needle": ["door-to-needle", "dtn", "time metric", "quality", "thrombolysis"],
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
    # Broad categories
    "medication": ["medication", "drug", "pharmacotherapy", "treatment"],
    "medications": ["medication", "drug", "pharmacotherapy", "treatment"],
    "drug": ["drug", "medication", "pharmacotherapy"],
    "drugs": ["drug", "medication", "pharmacotherapy"],
    "medicine": ["medication", "drug", "pharmacotherapy"],
    "treatment": ["treatment", "therapy", "intervention", "management"],
    "treatments": ["treatment", "therapy", "intervention"],
    "therapy": ["therapy", "treatment", "intervention"],
    "intervention": ["intervention", "treatment", "therapy", "procedure"],
    "procedure": ["procedure", "surgery", "intervention", "thrombectomy"],
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
    # R5 additions
    "hemodilution": ["hemodilution", "hemodynamic", "volume expansion", "albumin"],
    "hemodynamic": ["hemodynamic", "hemodilution", "volume expansion", "vasodilator", "augmentation"],
    "induced hypertension": ["hemodynamic", "augmentation", "vasopressor", "hypertension"],
    "fluoxetine": ["ssri", "fluoxetine", "motor recovery", "rehabilitation"],
    "steroids": ["corticosteroids", "steroids", "dexamethasone"],
    "corticosteroids": ["corticosteroids", "steroids", "dexamethasone"],
    "mobilized": ["mobilization", "early mobilization", "rehabilitation"],
    "mobilization": ["mobilization", "early mobilization", "rehabilitation"],
    "pes": ["pes", "pharyngeal electrical stimulation", "dysphagia"],
    "pharyngeal electrical stimulation": ["pes", "pharyngeal electrical stimulation", "dysphagia"],
    "eat": ["swallowing", "dysphagia", "oral intake", "food intake", "liquid"],
    "breakfast": ["swallowing", "dysphagia", "oral intake", "food intake"],
    "tirofiban": ["tirofiban", "glycoprotein", "gpiib/iiia", "antiplatelet"],
    "infants": ["pediatric", "neonatal", "neonates", "28 days"],
    "toddlers": ["pediatric", "neonatal", "neonates", "28 days", "young children"],
    "levetiracetam": ["antiseizure", "seizure", "prophylactic", "epilepsy"],
}

# ---------------------------------------------------------------------------
# Topic → Section mapping
# ---------------------------------------------------------------------------
# When a question is about a specific clinical topic, boost the correct
# guideline section(s) so results come from the right part of the document.
# This is the implicit equivalent of the user typing "Section X.Y".
# Boost value is lower than explicit section refs (+20) but still dominant.
TOPIC_SECTION_MAP: Dict[str, List[str]] = {
    # ── Section 2.1 — Stroke Awareness / Public Education ──────────
    "stroke awareness": ["2.1"],
    "stroke education": ["2.1"],
    "stroke recognition": ["2.1"],
    "stroke preparedness": ["2.1"],
    "public education": ["2.1"],
    "warning signs": ["2.1"],
    "stroke warning": ["2.1"],
    "community education": ["2.1"],
    "mass media": ["2.1"],
    "public awareness": ["2.1"],
    "community health worker": ["2.1"],
    "multilingual": ["2.1"],
    "culturally relevant": ["2.1"],
    "diverse communities": ["2.1"],
    "sustained campaign": ["2.1"],
    # ── Section 2.2 — EMS Systems / Regional Organization ────────
    "ems system": ["2.2"],
    "regional stroke system": ["2.2"],
    "stroke screening tool": ["2.2"],
    "prehospital triage protocol": ["2.2"],
    "stroke screening scale": ["2.2"],
    "lvo screening": ["2.2"],
    "field triage": ["2.2"],
    "tiered hospital": ["2.2"],
    # ── Section 2.3 — Prehospital Assessment / Field Management ──
    "prehospital assessment": ["2.3"],
    "field management": ["2.3"],
    "prehospital notification": ["2.3"],
    "prehospital blood glucose": ["2.3"],
    "ems assessment": ["2.3"],
    "rapid transport": ["2.3", "2.4"],
    "ems provider": ["2.3"],
    "stroke assessment protocol": ["2.3"],
    "prehospital blood pressure": ["2.3"],
    "prehospital iv fluid": ["2.3"],
    "prehospital neuroprotect": ["2.3"],
    # ── Section 2.4 — EMS Destination / Transport ────────────────
    "destination": ["2.4"],
    "transport to": ["2.4"],
    "nearest stroke center": ["2.4"],
    "hospital bypass": ["2.4"],
    "bypass": ["2.4"],
    "air transport": ["2.4"],
    "air medical": ["2.4"],
    "helicopter": ["2.4"],
    "transfer from": ["2.4"],
    "psc to csc": ["2.4"],
    "comprehensive stroke center": ["2.4", "2.6"],
    "primary stroke center": ["2.4", "2.6"],
    # ── Section 2.5 — Mobile Stroke Units ────────────────────────
    "mobile stroke unit": ["2.5"],
    "msu": ["2.5"],
    "special ambulance": ["2.5"],
    "ambulance with ct": ["2.5"],
    "brain scanner ambulance": ["2.5"],
    "prehospital ct": ["2.5"],
    "prehospital ivt": ["2.5"],
    # ── Section 2.6 — Hospital Certification ─────────────────────
    "stroke center": ["2.6"],
    "certification": ["2.6"],
    "hospital stroke capabilities": ["2.6"],
    "stroke capabilities": ["2.6"],
    "thrombectomy-capable": ["2.6"],
    "certified stroke": ["2.6"],
    "hospital designation": ["2.6"],
    # ── Section 2.7 — Emergency Department Evaluation ────────────
    "emergency evaluation": ["2.7"],
    "door-to-needle": ["2.7"],
    "door to needle": ["2.7"],
    "dtn time": ["2.7"],
    "rapid evaluation": ["2.7"],
    "door-to-imaging": ["2.7"],
    "door to imaging": ["2.7"],
    "stroke team": ["2.7"],
    "ed evaluation": ["2.7"],
    "rapid triage": ["2.7"],
    "door-to-groin": ["2.7"],
    "door to groin": ["2.7"],
    # ── Section 2.8 — Telestroke / Telemedicine ──────────────────
    "telemedicine": ["2.8"],
    "telestroke": ["2.8"],
    "telehealth": ["2.8"],
    "video-based stroke": ["2.8"],
    "video stroke assessment": ["2.8"],
    "remote stroke assessment": ["2.8"],
    "robot-assisted": ["2.8"],
    "telestroke-guided": ["2.8"],
    "store-and-forward": ["2.8"],
    "credentialing": ["2.8"],
    "telestroke provider": ["2.8"],
    "non-stroke center": ["2.8"],
    # ── Section 2.9 — Systems of Care / Organization ─────────────
    "systems of care": ["2.9"],
    "stroke systems": ["2.9"],
    "stroke network": ["2.9"],
    "referral agreement": ["2.9"],
    "inter-facility": ["2.9"],
    "interhospital": ["2.4", "2.9"],
    "hospital transfer": ["2.4", "2.9"],
    "standardized protocol": ["2.9"],
    "performance improvement": ["2.9", "2.10"],
    "regional stroke": ["2.9"],
    "transfer process": ["2.9"],
    "stroke center certification": ["2.9"],
    "patient perspective": ["2.9"],
    "caregiver perspective": ["2.9"],
    # ── Section 2.10 — Quality Metrics / Registries ──────────────
    "quality improvement": ["2.10"],
    "quality metrics": ["2.10"],
    "stroke registry": ["2.10"],
    "stroke registries": ["2.10"],
    "publicly reported": ["2.10"],
    "risk-standardized mortality": ["2.10"],
    "hospital quality": ["2.10"],
    "performance metric": ["2.10"],
    "data-driven": ["2.10"],
    "quality program": ["2.10"],
    "tracking": ["2.10"],
    # ── Broad prehospital (multi-section — used as fallback) ─────
    "ems": ["2.2", "2.3", "2.4"],
    "ambulance": ["2.2", "2.3", "2.4"],
    "prehospital": ["2.2", "2.3", "2.4"],
    "paramedic": ["2.2", "2.3", "2.4"],
    # ── Section 3.1 — Severity Assessment / NIHSS ────────────────
    "stroke scale": ["3.1"],
    "stroke severity": ["3.1"],
    "nihss": ["3.1"],
    "nihss assessment": ["3.1"],
    "baseline nihss": ["3.1"],
    "severity assessment": ["3.1"],
    # ── Section 3.2 — Imaging ────────────────────────────────────
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
    "brain imaging": ["3.2"],
    "non-contrast ct": ["3.2"],
    "vascular imaging": ["3.2"],
    "mra": ["3.2"],
    "collateral assessment": ["3.2"],
    "multiphase cta": ["3.2"],
    "dynamic cta": ["3.2"],
    "automated perfusion": ["3.2"],
    "hemorrhagic transformation": ["3.2"],
    "carotid duplex": ["3.2"],
    "ultrasonography": ["3.2"],
    # ── Section 3.3 — Lab Tests ──────────────────────────────────
    "diagnostic tests": ["3.3"],
    "blood glucose test": ["3.3"],
    "lab testing": ["3.3"],
    "coagulation testing": ["3.3"],
    "baseline labs": ["3.3"],
    "blood work": ["3.3"],
    "blood test": ["3.3"],
    "laboratory tests": ["3.3"],
    "routine lab": ["3.3"],
    "lab before ivt": ["3.3"],
    "lab before thrombolysis": ["3.3"],
    "blood work before": ["3.3"],
    "laboratory testing before ivt": ["3.3"],
    "laboratory testing before thrombolysis": ["3.3"],
    "routine laboratory": ["3.3"],
    "laboratory tests in stroke": ["3.3"],
    "labs before ivt": ["3.3"],
    "labs before tpa": ["3.3"],
    "cbc before": ["3.3"],
    "inr before": ["3.3"],
    "platelet count before": ["3.3"],
    "required labs": ["3.3"],
    "blood glucose before": ["3.3"],
    "glucose before ivt": ["3.3"],
    "delaying ivt": ["3.3"],
    "wait for lab": ["3.3"],
    # ── Section 5.1 — Stroke Unit ────────────────────────────────
    "organized stroke care": ["5.1"],
    "stroke care protocol": ["5.1"],
    "stroke unit": ["5.1"],
    "inpatient stroke": ["5.1"],
    # General supportive care (Section 4.1-4.5)
    "airway": ["4.1"],
    "oxygenation": ["4.1"],
    "oxygen": ["4.1"],
    "supplemental oxygen": ["4.1"],
    "spo2": ["4.1"],
    "intubation": ["4.1"],
    "ventilatory assistance": ["4.1"],
    "hyperbaric oxygen": ["4.1"],
    "hbo": ["4.1"],
    "air embolism": ["4.1"],
    "general anesthesia": ["4.1", "4.7.4"],
    "procedural sedation": ["4.1", "4.7.4"],
    "head positioning": ["4.2"],
    "head of bed": ["4.2"],
    "flat positioning": ["4.2"],
    "lying flat": ["4.2"],
    "flat after stroke": ["4.2"],
    "patient flat": ["4.2"],
    "temperature": ["4.4"],
    "fever": ["4.4"],
    "hyperthermia": ["4.4"],
    "hypothermia": ["4.4"],
    "normothermia": ["4.4"],
    "brain cooling": ["4.4"],
    "cooling": ["4.4"],
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
    "clevidipine": ["4.3"],
    "bp control": ["4.3"],
    "bp before ivt": ["4.3"],
    "bp before tpa": ["4.3"],
    "bp target": ["4.3"],
    "bp target before": ["4.3"],
    "blood pressure target": ["4.3"],
    "bp during evt": ["4.3"],
    "bp after ivt": ["4.3"],
    "bp after evt": ["4.3"],
    "sbp 185": ["4.3"],
    "185/110": ["4.3"],
    "180/105": ["4.3"],
    "sbp below": ["4.3"],
    "maintain bp": ["4.3"],
    "hypotension": ["4.3"],
    "hypovolemia": ["4.3"],
    "perfusion": ["4.3"],
    "intensive bp": ["4.3"],
    "bp 220": ["4.3"],
    "220/120": ["4.3"],
    "bp lowering": ["4.3"],
    "sbp reduction": ["4.3"],
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
    "woke up with stroke": ["4.6.3"],
    "woke up with symptoms": ["4.6.3"],
    "unknown onset": ["4.6.3"],
    "extended window ivt": ["4.6.3"],
    "late window ivt": ["4.6.3"],
    "late window thrombolysis": ["4.6.3"],
    "late window tpa": ["4.6.3"],
    "imaging-based ivt": ["4.6.3"],
    "imaging based ivt": ["4.6.3"],
    "7 hours": ["4.6.3"],
    "7h from onset": ["4.6.3"],
    "dwi-flair mismatch": ["4.6.3"],
    "dwi flair mismatch": ["4.6.3"],
    "perfusion mismatch": ["4.6.3"],
    "salvageable penumbra": ["4.6.3"],
    "salvageable tissue": ["4.6.3"],
    "salvageable ischemic": ["4.6.3"],
    "4.5 to 9 hour": ["4.6.3"],
    "4.5-9": ["4.6.3"],
    "4.5-9h": ["4.6.3"],
    "4.5 to 24": ["4.6.3"],
    "4.5-24": ["4.6.3"],
    "20 hours": ["4.6.3"],
    "9 hours": ["4.6.3"],
    # Other IV fibrinolytics and sonothrombolysis (Section 4.6.4)
    "sonothrombolysis": ["4.6.4"],
    "ultrasound-enhanced thrombolysis": ["4.6.4"],
    "ultrasound enhanced": ["4.6.4"],
    "streptokinase": ["4.6.4"],
    "desmoteplase": ["4.6.4"],
    "ancrod": ["4.6.4"],
    "reteplase": ["4.6.4"],
    "prourokinase": ["4.6.4"],
    "mutant prourokinase": ["4.6.4"],
    "urokinase": ["4.6.4"],
    "defibrinogenation": ["4.6.4"],
    "defibrinogenating": ["4.6.4"],
    "other iv fibrinolytic": ["4.6.4"],
    "other fibrinolytic": ["4.6.4"],
    "dissolve the clot through": ["4.6.4"],
    "dissolve clot through blood vessel": ["4.6.4"],
    "intra-arterial fibrinolysis": ["4.6.4"],
    "intra-arterial thrombolysis": ["4.6.4"],
    "intra-arterial": ["4.6.4"],
    "ia thrombolysis": ["4.6.4"],
    "ia fibrinolysis": ["4.6.4"],
    "alternative thrombolytic": ["4.6.4"],
    "microcatheter fibrinolysis": ["4.6.4"],
    "fibrinolysis through microcatheter": ["4.6.4"],
    "transcranial doppler": ["4.6.4"],
    "catheter-directed ultrasound": ["4.6.4"],
    "catheter ultrasound": ["4.6.4"],
    # Other specific IVT circumstances (Section 4.6.5)
    "ivt in pregnant": ["4.6.5"],
    "ivt in pediatric": ["4.6.5"],
    "ivt during pregnancy": ["4.6.5"],
    "thrombolysis in pregnant": ["4.6.5"],
    "thrombolysis in pregnancy": ["4.6.5"],
    "alteplase in pregnancy": ["4.6.5"],
    "pregnant patients with ais": ["4.6.5"],
    "pregnant stroke": ["4.6.5"],
    "pediatric patients with ais": ["4.6.5"],
    "thrombolysis in pediatric": ["4.6.5"],
    "alteplase in children": ["4.6.5"],
    "ivt in children": ["4.6.5"],
    "pediatric ivt": ["4.6.5"],
    "children with ais": ["4.6.5"],
    "children with ischemic stroke": ["4.6.5"],
    "sickle cell disease": ["4.6.5"],
    "scd": ["4.6.5"],
    "retinal artery occlusion": ["4.6.5"],
    "retinal artery": ["4.6.5"],
    "central retinal artery": ["4.6.5"],
    "crao": ["4.6.5"],
    "ophthalmic vascular": ["4.6.5"],
    "ophthalmic occlusion": ["4.6.5"],
    "visual loss": ["4.6.5"],
    "procedural stroke": ["4.6.5"],
    "cardiac catheterization": ["4.6.5"],
    "stroke during cardiac": ["4.6.5"],
    "stroke during angiography": ["4.6.5"],
    "ivt during angiography": ["4.6.5"],
    "ivt during cardiac": ["4.6.5"],
    "ivt during catheterization": ["4.6.5"],
    "thrombolysis during angiography": ["4.6.5"],
    "thrombolysis in procedural": ["4.6.5"],
    "ivt in special circumstances": ["4.6.5"],
    "ivt special circumstances": ["4.6.5"],
    "thrombolysis in special": ["4.6.5"],
    "ivt for stroke during": ["4.6.5"],
    # Concomitant IVT+EVT (Section 4.7.1)
    "concomitant": ["4.7.1"],
    "bridging": ["4.7.1"],
    "bridging therapy": ["4.7.1"],
    "thrombolysis plus thrombectomy": ["4.7.1"],
    "ivt plus evt": ["4.7.1"],
    "thrombolysis and thrombectomy": ["4.7.1"],
    "ivt before evt": ["4.7.1"],
    "ivt before thrombectomy": ["4.7.1"],
    "ivt before endovascular": ["4.7.1"],
    "given before evt": ["4.7.1"],
    "given before thrombectomy": ["4.7.1"],
    "giving ivt before": ["4.7.1"],
    "ivt and evt": ["4.7.1"],
    "ivt with evt": ["4.7.1"],
    "administered before evt": ["4.7.1"],
    "delay evt": ["4.7.1"],
    "delayed to assess": ["4.7.1"],
    "delaying evt": ["4.7.1"],
    "observe ivt response": ["4.7.1"],
    "skip ivt": ["4.7.1"],
    "direct thrombectomy": ["4.7.1"],
    "direct to evt": ["4.7.1"],
    "bridging ivt": ["4.7.1"],
    "evt transfer": ["4.7.1"],
    "transferring for evt": ["4.7.1"],
    "spoke hospital": ["4.7.1"],
    "before endovascular treatment": ["4.7.1"],
    "before endovascular thrombectomy": ["4.7.1"],
    "safe to give ivt": ["4.7.1"],
    "ivt is safe": ["4.7.1"],
    # EVT (Section 4.7.x)
    "thrombectomy": ["4.7.2"],
    "evt": ["4.7.2"],
    "endovascular": ["4.7.2"],
    # ── Vessel-specific EVT routing ──────────────────────────────
    # M1 / ICA / large vessel → 4.7.2 (standard EVT eligibility)
    "m1": ["4.7.2"],
    "m1 occlusion": ["4.7.2"],
    "m1 segment": ["4.7.2"],
    "ica": ["4.7.2"],
    "ica occlusion": ["4.7.2"],
    "internal carotid": ["4.7.2"],
    "internal carotid artery": ["4.7.2"],
    "large vessel occlusion": ["4.7.2"],
    "lvo": ["4.7.2"],
    "large vessel": ["4.7.2"],
    # EVT time windows — route to 4.7.2 where eligibility criteria live
    "evt time window": ["4.7.2"],
    "evt within 6": ["4.7.2"],
    "evt within 24": ["4.7.2"],
    "evt 6 hours": ["4.7.2"],
    "evt 6 to 24": ["4.7.2"],
    "evt 6-24": ["4.7.2"],
    "extended window evt": ["4.7.2"],
    "late window evt": ["4.7.2"],
    "late window thrombectomy": ["4.7.2"],
    # ASPECTS for EVT — route to 4.7.2
    "aspects for evt": ["4.7.2"],
    "aspects score for evt": ["4.7.2"],
    "aspects threshold": ["4.7.2"],
    "aspects requirement": ["4.7.2"],
    "aspect score": ["4.7.2"],
    "aspect score for": ["4.7.2"],
    "aspects cutoff": ["4.7.2"],
    "aspects 6": ["4.7.2"],
    "aspects >= 6": ["4.7.2"],
    # M2 dominant/nondominant → 4.7.2 (recs 7-8 for M2)
    "m2": ["4.7.2"],
    "m2 occlusion": ["4.7.2"],
    "m2 segment": ["4.7.2"],
    "dominant m2": ["4.7.2"],
    "nondominant m2": ["4.7.2"],
    "non-dominant m2": ["4.7.2"],
    "codominant m2": ["4.7.2"],
    "proximal m2": ["4.7.2"],
    # M3 / distal / medium vessel → 4.7.4 (rec 5: COR 3 No Benefit)
    "m3": ["4.7.4"],
    "m3 occlusion": ["4.7.4"],
    "m3 segment": ["4.7.4"],
    "distal mca": ["4.7.4"],
    "distal mca occlusion": ["4.7.4"],
    "a2": ["4.7.4"],
    "a3": ["4.7.4"],
    "p2": ["4.7.4"],
    "p3": ["4.7.4"],
    "a2 occlusion": ["4.7.4"],
    "a3 occlusion": ["4.7.4"],
    "p2 occlusion": ["4.7.4"],
    "p3 occlusion": ["4.7.4"],
    "aca occlusion": ["4.7.4"],
    "pca occlusion": ["4.7.4"],
    "anterior cerebral artery": ["4.7.4"],
    "medium vessel": ["4.7.4"],
    "distal vessel occlusion": ["4.7.4"],
    "escape-mevo": ["4.7.4"],
    "distal trial": ["4.7.4"],
    # Posterior circulation → 4.7.3
    "posterior circulation": ["4.7.3"],
    "posterior circulation thrombectomy": ["4.7.3"],
    "posterior circulation evt": ["4.7.3"],
    "basilar": ["4.7.3"],
    "basilar artery": ["4.7.3"],
    "basilar occlusion": ["4.7.3"],
    "basilar thrombectomy": ["4.7.3"],
    "basilar evt": ["4.7.3"],
    "vertebral": ["4.7.3"],
    "vertebrobasilar": ["4.7.3"],
    "pc-aspects": ["4.7.3"],
    # Endovascular techniques (Section 4.7.4)
    "door-to-groin": ["4.7.4"],
    "door to groin": ["4.7.4"],
    "groin puncture": ["4.7.4"],
    "stent retriever": ["4.7.4"],
    "wire basket": ["4.7.4"],
    "suction device": ["4.7.4"],
    "suction catheter": ["4.7.4"],
    "direct aspiration": ["4.7.4"],
    "contact aspiration": ["4.7.4"],
    "aspiration thrombectomy": ["4.7.4"],
    "first-pass": ["4.7.4"],
    "first pass": ["4.7.4"],
    "conscious sedation": ["4.7.4"],
    "general anesthesia": ["4.7.4"],
    "procedural sedation": ["4.7.4"],
    "sedation": ["4.7.4"],
    "anesthesia": ["4.7.4"],
    "intracranial stenting": ["4.7.4"],
    "rescue therapy": ["4.7.4"],
    "rescue stenting": ["4.7.4"],
    "rescue angioplasty": ["4.7.4"],
    "rescue balloon": ["4.7.4"],
    "balloon-guided": ["4.7.4"],
    "balloon guided": ["4.7.4"],
    "balloon catheter": ["4.7.4"],
    "proximal balloon": ["4.7.4"],
    "tici": ["4.7.4"],
    "reperfusion grade": ["4.7.4"],
    "reperfusion target": ["4.7.4"],
    "ia alteplase": ["4.7.4"],
    "ia urokinase": ["4.7.4"],
    "intra-arterial alteplase": ["4.7.4"],
    "intra-arterial urokinase": ["4.7.4"],
    "adjunctive ia": ["4.7.4"],
    "tandem occlusion": ["4.7.4"],
    "tandem lesion": ["4.7.4"],
    "tandem stenting": ["4.7.4"],
    "carotid stenting during evt": ["4.7.4"],
    "aster trial": ["4.7.4"],
    "endovascular techniques": ["4.7.4"],
    "endovascular technique": ["4.7.4"],
    "medium vessel occlusion": ["4.7.4"],
    "mevo": ["4.7.4"],
    "distal vessel": ["4.7.4"],
    # Pediatric EVT (Section 4.7.5)
    "pediatric stroke": ["4.7.5"],
    "pediatric patients with lvo": ["4.7.5"],
    "pediatric lvo": ["4.7.5"],
    "pediatric evt": ["4.7.5"],
    "pediatric thrombectomy": ["4.7.5"],
    "neonatal evt": ["4.7.5"],
    "neonatal thrombectomy": ["4.7.5"],
    "neonatal": ["4.7.5"],
    "neonates": ["4.7.5"],
    "neonate": ["4.7.5"],
    "evt in neonates": ["4.7.5"],
    "neonates": ["4.7.5"],
    "under 28 days": ["4.7.5"],
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
    "volume expansion": ["4.10"],
    "albumin": ["4.10"],
    "high-dose albumin": ["4.10"],
    "albumin infusion": ["4.10"],
    "hypervolemic": ["4.10"],
    "hemodynamic augmentation": ["4.10"],
    "hemodynamic therapies": ["4.10"],
    "hemodynamic": ["4.10"],
    "induced hypertension": ["4.10"],
    "vasodilator": ["4.10"],
    "vasoactive": ["4.10"],
    "pentoxifylline": ["4.10"],
    "counterpulsation": ["4.10"],
    "external counterpulsation": ["4.10"],
    "sphenopalatine ganglion": ["4.10"],
    "mechanical hemodynamic": ["4.10"],
    "neuroprotective": ["4.11"],
    "neuroprotection": ["4.11"],
    "neuroprotectant": ["4.11"],
    "neuroprotective agent": ["4.11"],
    "pharmacological neuroprotection": ["4.11"],
    "nonpharmacological neuroprotection": ["4.11"],
    "nerinetide": ["4.11"],
    "free radical": ["4.11"],
    "magnesium sulfate": ["4.11"],
    "magnesium": ["4.11"],
    "hypothermia neuroprotection": ["4.11"],
    "hypothermia as neuroprotection": ["4.11"],
    "therapeutic hypothermia": ["4.11"],
    "hyperbaric oxygen neuroprotection": ["4.11"],
    "transcranial laser": ["4.11"],
    "remote ischemic conditioning": ["4.11"],
    "stem cell": ["4.11"],
    "cell therapy": ["4.11"],
    "cell-based therapy": ["4.11"],
    "carotid endarterectomy": ["4.12"],
    "cea": ["4.12"],
    "carotid stenting": ["4.12"],
    "cas": ["4.12"],
    "emergent carotid": ["4.12"],
    "urgent carotid": ["4.12"],
    "tandem occlusion": ["4.12"],
    "cervical stenosis": ["4.12"],
    # Inpatient management (Section 5.x)
    "stroke unit": ["5.1"],
    "dedicated stroke unit": ["5.1"],
    "special part of the hospital": ["5.1"],
    "admission": ["5.1"],
    "icu": ["5.1"],
    "intensive care": ["5.1"],
    "dysphagia": ["5.2"],
    "swallowing": ["5.2"],
    "aspiration": ["5.2"],
    "swallow screen": ["5.2"],
    "oral intake": ["5.2"],
    "npo": ["5.2"],
    "pes": ["5.2"],
    "pharyngeal electrical stimulation": ["5.2"],
    "eat breakfast": ["5.2"],
    "eats or drinks": ["5.2"],
    "nutrition": ["5.3"],
    "enteral": ["5.3"],
    "tube feeding": ["5.3"],
    "nasogastric": ["5.3"],
    "peg tube": ["5.3"],
    "malnutrition": ["5.3"],
    "dvt": ["5.4"],
    "deep vein": ["5.4"],
    "dvt prophylaxis": ["5.4"],
    "venous thromboembolism": ["5.4"],
    "vte": ["5.4"],
    "pulmonary embolism": ["5.4"],
    "pneumatic compression": ["5.4"],
    "prophylactic heparin": ["5.4"],
    "prophylactic-dose": ["5.4"],
    "prophylactic dose": ["5.4"],
    "subcutaneous heparin": ["5.4"],
    "compression stockings": ["5.4"],
    "ipc": ["5.4"],
    "intermittent pneumatic": ["5.4"],
    "ipc timing": ["5.4"],
    "pneumatic compression": ["5.4"],
    "elastic compression": ["5.4"],
    "lmwh": ["5.4"],
    "enoxaparin": ["5.4"],
    "depression": ["5.5"],
    "antidepressant": ["5.5"],
    "ssri": ["5.5"],
    "mood": ["5.5"],
    "emotional lability": ["5.5"],
    "post-stroke depression": ["5.5"],
    "feeling sad": ["5.5"],
    "sad after": ["5.5"],
    "palliative": ["5.6"],
    "palliative care": ["5.6"],
    "end of life": ["5.6"],
    "comfort care": ["5.6"],
    "goals of care": ["5.6"],
    "withdrawal of care": ["5.6"],
    "do not resuscitate": ["5.6"],
    "dnr": ["5.6"],
    "hospice": ["5.6"],
    "advance directive": ["5.6"],
    "prophylactic antibiotic": ["5.6"],
    "preventive antibiotic": ["5.6"],
    "prophylactic ceftriaxone": ["5.6"],
    "routine antibiotic": ["5.6"],
    "urinary catheter": ["5.6"],
    "foley catheter": ["5.6"],
    "indwelling catheter": ["5.6"],
    "bladder catheter": ["5.6"],
    "catheterization": ["5.6"],
    "urinary tract infection": ["5.6"],
    "uti screening": ["5.6"],
    "oral hygiene": ["5.2"],
    "oral care": ["5.2"],
    "dental care": ["5.2"],
    "rehabilitation": ["5.7"],
    "early mobilization": ["5.7"],
    "physical therapy": ["5.7"],
    "occupational therapy": ["5.7"],
    "speech therapy": ["5.7"],
    "fluoxetine": ["5.6", "5.7"],
    "motor recovery": ["5.7"],
    "motor function": ["5.7"],
    "mobilized": ["5.7"],
    "mobilization": ["5.7"],
    "aggressively mobilized": ["5.7"],
    # Complications (Section 6.x)
    "large territorial infarction": ["6.1"],
    "large territorial": ["6.1"],
    "large hemisphere infarct": ["6.1"],
    "large hemisphere": ["6.1"],
    "large infarction": ["6.1"],
    "supratentorial infarction": ["6.3"],
    "supratentorial": ["6.3"],
    "surgical management": ["6.3"],
    "brain swelling": ["6.1", "6.2"],
    "cerebral edema": ["6.1", "6.2"],
    "malignant edema": ["6.1", "6.2", "6.3"],
    "herniation": ["6.1", "6.2", "6.3"],
    "midline shift": ["6.1", "6.2"],
    "mass effect": ["6.1", "6.2"],
    "space-occupying": ["6.1", "6.2", "6.3"],
    "osmotic therapy": ["6.2"],
    "mannitol": ["6.2"],
    "hypertonic saline": ["6.2"],
    "glibenclamide": ["6.2"],
    "glyburide": ["6.2"],
    "charm trial": ["6.2"],
    "hyperventilation": ["6.2"],
    "barbiturate": ["6.2"],
    "barbiturates": ["6.2"],
    "corticosteroid": ["6.2"],
    "corticosteroids": ["6.2"],
    "dexamethasone": ["6.2"],
    "steroid for edema": ["6.2"],
    "steroids": ["6.2"],
    "decompressive": ["6.3"],
    "craniectomy": ["6.3"],
    "hemicraniectomy": ["6.3"],
    "suboccipital": ["6.4"],
    "cerebellar infarction": ["6.4"],
    "cerebellar stroke": ["6.4"],
    "posterior fossa": ["6.4"],
    "balance center": ["6.4"],
    "back of the brain": ["6.4"],
    "hydrocephalus": ["6.4"],
    "ventriculostomy": ["6.4"],
    "seizure": ["6.5"],
    "seizures": ["6.5"],
    "antiepileptic": ["6.5"],
    "antiepileptic drug": ["6.5"],
    "antiepileptic drugs": ["6.5"],
    "antiseizure": ["6.5"],
    "antiseizure medication": ["6.5"],
    "prophylactic antiseizure": ["6.5"],
    "convulsion": ["6.5"],
    "status epilepticus": ["6.5"],
    "eeg": ["6.5"],
    "levetiracetam": ["6.5"],
    "seizure prophylaxis": ["6.5"],
    "prophylactic levetiracetam": ["6.5"],
    "unprovoked seizure": ["6.5"],
    # Complications — IVT-specific
    "sich": ["4.6.1"],
    "hemorrhagic transformation": ["4.9"],
    "angioedema": ["4.6.1"],
    "orolingual": ["4.6.1"],
    # IVT door-to-needle time
    "door-to-needle": ["4.6.1"],
    "door to needle": ["4.6.1"],
    "dtn time": ["4.6.1"],
    # Carotid revascularization (Section 4.12)
    "carotid revascularization": ["4.12"],
    "emergent carotid endarterectomy": ["4.12"],
    "emergency carotid": ["4.12"],
    "emergency carotid intervention": ["4.12"],
    "emergent carotid intervention": ["4.12"],
    # Goals of care (Section 6.1)
    "goals-of-care": ["6.1"],
    "goals of care": ["6.1"],
    # Inpatient stroke care (Section 5.1)
    "inpatient stroke care": ["5.1"],
    "organized stroke care": ["5.1"],
    "organized inpatient": ["5.1"],
    # IVT general (Section 4.6.1)
    "ivt": ["4.6.1"],
    "iv thrombolysis": ["4.6.1"],
    "intravenous thrombolysis": ["4.6.1"],
    "iv alteplase": ["4.6.1"],
    "iv tpa": ["4.6.1"],
    # Antiplatelet specifics (Section 4.8)
    "ticagrelor": ["4.8"],
    "dipyridamole": ["4.8"],
    "glycoprotein iib/iiia": ["4.8"],
    "gp iib/iiia": ["4.8"],
    "tirofiban": ["4.8"],
    "eptifibatide": ["4.8"],
    "thales": ["4.8"],
    "socrates": ["4.8"],
    "inspires": ["4.8"],
    "chance-2": ["4.8"],
    "point trial": ["4.8"],
    "cyp2c19": ["4.8"],
    # Anticoagulant specifics (Section 4.9)
    "factor xa": ["4.9"],
    "factor xa inhibitor": ["4.9"],
    "dissection": ["4.9"],
    "carotid dissection": ["4.9"],
    "intraluminal thrombus": ["4.9"],
    "enoxaparin": ["4.9"],
    "fondaparinux": ["4.9"],
    "rivaroxaban": ["4.9"],
    "apixaban": ["4.9"],
    "dabigatran": ["4.9"],
    "edoxaban": ["4.9"],
    "parenteral anticoagulation": ["4.9"],
    # Contraindications (Table 8)
    "contraindication": ["Table 8"],
    "contraindicated": ["Table 8"],
    "absolute contraindication": ["Table 8"],
    "relative contraindication": ["Table 8"],
    "benefit may exceed risk": ["Table 8"],
    "benefit over risk": ["Table 8"],
    "table 8": ["Table 8"],
    # Specific Table 8 contraindication topics — route to Table 8
    "endocarditis": ["Table 8"],
    "coagulopathy": ["Table 8"],
    "aortic dissection": ["Table 8"],
    "aortic arch dissection": ["Table 8"],
    "pericarditis": ["Table 8"],
    "cardiac thrombus": ["Table 8"],
    "lumbar puncture": ["Table 8"],
    "dural puncture": ["Table 8"],
    "arterial puncture": ["Table 8"],
    "stroke mimic": ["Table 8"],
    "recreational drug": ["Table 8"],
    # ── Broad category keywords (multi-section → triggers clarification) ──
    # These intentionally map to many sections so the content breadth
    # system fires cross-section clarification for vague questions like
    # "What medications are used to treat stroke?"
    "medication": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "medications": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "drug": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "drugs": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "medicine": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "pharmacotherapy": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "pharmacological": ["4.3", "4.6.1", "4.6.2", "4.8", "4.9", "4.11", "6.2"],
    "treatment": ["4.6.1", "4.7.2", "4.8"],
    "treatments": ["4.6.1", "4.7.2", "4.8"],
    "therapy": ["4.6.1", "4.7.2", "4.8"],
    "therapies": ["4.6.1", "4.7.2", "4.8"],
    "management": ["4.3", "4.4", "4.5", "6.1"],
    "intervention": ["4.6.1", "4.7.2"],
    "interventions": ["4.6.1", "4.7.2"],
    "procedure": ["4.7.2", "4.7.4", "4.12"],
    "procedures": ["4.7.2", "4.7.4", "4.12"],
    "surgery": ["6.3", "6.4", "4.12"],
    "surgical": ["6.3", "6.4", "4.12"],
}

# Boost value for topic-inferred section matching (lower than explicit +20)
_TOPIC_SECTION_BOOST = 25


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
# Automatic within-section discriminator
# ---------------------------------------------------------------------------
# When a section has multiple recs (e.g., 4.6.1 has 14, 4.8 has 18), we need
# to differentiate which rec the question targets. Instead of manually curating
# contradiction pairs for every combination, this module automatically detects
# "differentiating phrases" — clinical terms that appear in ONE rec within a
# section but NOT in the other recs of the same section.
#
# At load time, build_section_discriminators() analyzes all recs and produces:
#   { section: { rec_id: { phrase: weight } } }
# At scoring time, if a question contains a differentiating phrase, the rec
# that owns it gets a bonus and sibling recs get a penalty.

# Minimum word length for discriminating tokens
_DISC_MIN_LEN = 4
# Phrases that are too generic to discriminate (appear in many medical contexts)
_DISC_STOPWORDS = {
    "patients", "patient", "with", "ischemic", "stroke", "hours",
    "recommended", "beneficial", "reasonable", "treatment", "eligible",
    "presenting", "within", "symptom", "onset", "last", "known",
    "well", "from", "that", "this", "should", "been", "have",
    "their", "they", "than", "more", "does", "clinical", "outcomes",
    "therapy", "used", "when", "adults", "adult",
}


def _extract_clinical_phrases(text: str) -> set:
    """Extract meaningful clinical phrases from rec text for discrimination."""
    text_lower = text.lower()
    phrases = set()

    # Extract multi-word clinical phrases (2-4 words)
    words = re.findall(r'[a-z][a-z0-9/-]+', text_lower)
    for i in range(len(words)):
        w = words[i]
        if len(w) >= _DISC_MIN_LEN and w not in _DISC_STOPWORDS:
            phrases.add(w)
        # 2-word phrases
        if i + 1 < len(words):
            bigram = f"{words[i]} {words[i+1]}"
            if len(bigram) >= 8:
                phrases.add(bigram)
        # 3-word phrases
        if i + 2 < len(words):
            trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
            if len(trigram) >= 12:
                phrases.add(trigram)

    # Also extract numeric/symbol patterns (>=6, <=60, 0.25 mg, etc.)
    for pat in re.findall(r'[<>=]+\s*\d+', text_lower):
        phrases.add(pat.replace(' ', ''))
    for pat in re.findall(r'\d+\.?\d*\s*(?:mg|hours|days|years|months)', text_lower):
        phrases.add(pat)

    return phrases


def build_section_discriminators(
    recommendations: List[dict],
) -> Dict[str, Dict[str, set]]:
    """Build per-section discriminating phrase sets.

    For each section with >1 rec, find phrases unique to each rec
    (present in that rec but absent from ALL other recs in the same section).

    Returns: { section: { recNumber: set_of_unique_phrases } }
    """
    # Group recs by section
    by_section: Dict[str, List[dict]] = {}
    for rec in recommendations:
        sec = rec.get("section", "")
        if sec not in by_section:
            by_section[sec] = []
        by_section[sec].append(rec)

    discriminators: Dict[str, Dict[str, set]] = {}
    for sec, sec_recs in by_section.items():
        if len(sec_recs) < 2:
            continue

        # Extract phrases for each rec
        rec_phrases: Dict[str, set] = {}
        for rec in sec_recs:
            rn = rec.get("recNumber", "")
            rec_phrases[rn] = _extract_clinical_phrases(rec.get("text", ""))

        # Find unique phrases per rec
        discriminators[sec] = {}
        for rn, phrases in rec_phrases.items():
            # Phrases in this rec but NOT in any other rec in the same section
            other_phrases = set()
            for other_rn, other_p in rec_phrases.items():
                if other_rn != rn:
                    other_phrases |= other_p
            unique = phrases - other_phrases
            if unique:
                discriminators[sec][rn] = unique

    return discriminators


# Module-level cache for discriminators (built lazily on first use)
_section_discriminators: Optional[Dict[str, Dict[str, set]]] = None


def get_section_discriminators(recommendations: List[dict]) -> Dict[str, Dict[str, set]]:
    """Get or build the section discriminator cache."""
    global _section_discriminators
    if _section_discriminators is None:
        _section_discriminators = build_section_discriminators(recommendations)
    return _section_discriminators


def compute_discrimination_score(
    rec: dict,
    question: str,
    section_discriminators: Dict[str, Dict[str, set]],
) -> int:
    """Compute bonus/penalty based on automatic within-section discrimination.

    When the question contains a phrase unique to THIS rec within its section,
    give a bonus. When the question contains a phrase unique to a SIBLING rec,
    give a penalty.
    """
    sec = rec.get("section", "")
    rn = rec.get("recNumber", "")
    sec_discs = section_discriminators.get(sec)
    if not sec_discs:
        return 0

    q_lower = question.lower()
    score = 0

    def _phrase_in_text(phrase: str, text: str) -> bool:
        """Check if phrase appears in text with word-boundary awareness.

        For single words, use word-boundary regex to avoid substring matches
        like 'urokinase' matching inside 'prourokinase'. Multi-word phrases
        use simple substring matching since they're inherently more specific.
        """
        if ' ' in phrase:
            return phrase in text
        # Single word: require word boundary to avoid substring false positives
        return bool(re.search(rf'\b{re.escape(phrase)}\b', text))

    # Bonus for unique phrases of THIS rec found in question
    my_unique = sec_discs.get(rn, set())
    for phrase in my_unique:
        if _phrase_in_text(phrase, q_lower):
            score += 5  # Bonus per unique phrase match

    # Penalty for unique phrases of SIBLING recs found in question
    for sibling_rn, sibling_unique in sec_discs.items():
        if sibling_rn == rn:
            continue
        for phrase in sibling_unique:
            if _phrase_in_text(phrase, q_lower):
                score -= 2  # Light penalty per sibling phrase match

    # Cap the discrimination score to avoid runaway effects
    return max(min(score, 20), -15)


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


def extract_topic_sections(question: str) -> Tuple[List[str], set]:
    """Infer guideline section(s) from clinical topic keywords in the question.

    Uses TOPIC_SECTION_MAP to map recognized topics to their correct section(s).
    Longer phrases are checked first so "wake-up stroke" matches before "stroke".
    Returns a tuple of (deduplicated section list, suppressed section set).
    The suppressed set contains sections that compound overrides explicitly
    exclude — used by the scorer to penalize off-topic recs.
    """
    q_lower = question.lower()
    matched_sections: List[str] = []

    # Compound topic overrides — when two topics co-occur, the combined meaning
    # points to a specific section that neither individual topic would reach.
    # Compound overrides: (topic_terms, context_terms, target_sections, suppress_sections)
    # When both topic and context match, route to target_sections and
    # SUPPRESS suppress_sections so the generic parent doesn't compete.
    # This prevents e.g. "IVT + pregnancy" from returning 14 recs from
    # 4.6.1 (generic IVT) when it should return 2 recs from 4.6.5 (IVT
    # in special populations).
    _COMPOUND_OVERRIDES = [
        # "blood pressure" + IVT context → 4.6.1 (BP management before IVT rec)
        (["blood pressure", "bp"], ["ivt", "thrombolysis", "alteplase", "thrombolytic"],
         ["4.6.1"], []),
        # "blood pressure" + EVT context → 4.3 (BP management) AND 4.7.4
        # BP targets post-EVT are in Section 4.3 Rec 10 (COR 3:Harm for
        # intensive SBP<140), not just 4.7.4 endovascular techniques.
        (["blood pressure", "bp", "sbp"], ["evt", "recanalization", "thrombectomy", "endovascular", "post-evt", "after evt", "after thrombectomy"],
         ["4.3", "4.7.4"], ["4.7.2"]),
        # "aspirin" + IVT context → 4.8 (rec about not giving aspirin within 90min of IVT)
        # NOTE: "aspirin before IVT" = 4.8. "patient ON aspirin receiving IVT" = 4.6.1.
        # The DAPT+IVT compound below handles "on aspirin"/"taking aspirin" → 4.6.1.
        (["aspirin before", "aspirin within", "aspirin prior to",
          "give aspirin", "administer aspirin", "start aspirin",
          "aspirin be given before", "aspirin given before"],
         ["thrombolysis", "ivt", "alteplase", "90 minutes",
          "before ivt", "before thrombolysis"],
         ["4.8"], ["4.6.1"]),
        # EVT + posterior/basilar → 4.7.3 (suppress generic EVT 4.7.2)
        (["evt", "thrombectomy", "endovascular", "mechanical thrombectomy"],
         ["basilar", "posterior", "vertebral", "posterior circulation", "pca"],
         ["4.7.3"], ["4.7.2"]),
        # EVT + pediatric → 4.7.5 (suppress generic EVT 4.7.2 AND IVT pediatric 4.6.1)
        # When asking about pediatric EVT, suppress 4.6.1 rec 14 (IVT pediatric)
        # which otherwise outscores 4.7.5 rec 1 (EVT pediatric) due to keyword overlap.
        (["evt", "thrombectomy", "endovascular", "mechanical thrombectomy", "lvo"],
         ["pediatric", "children", "child", "neonatal", "neonates", "neonate",
          "pediatric patients", "under 28 days", "28 days",
          # Use "a X-year-old" or "X-year-old" with leading space/boundary
          # to avoid matching "65-year-old" → "5-year-old" substring issue.
          # Safer: use the "aged" pattern or full "X-year-old has/with" phrases.
          "a 1-year-old", "a 2-year-old", "a 3-year-old", "a 4-year-old",
          "a 5-year-old", "a 6-year-old", "a 7-year-old", "a 8-year-old",
          "a 9-year-old",
          "10-year-old", "10 year old", "11-year-old", "12-year-old",
          "12 year old", "13-year-old", "14-year-old", "14 year old",
          "15-year-old", "15 year old", "16-year-old", "16 year old",
          "17-year-old", "teenager", "adolescent"],
         ["4.7.5"], ["4.7.2", "4.6.1", "4.6.3", "4.1"]),
        # IVT + pediatric/children → 4.6.1 (suppress 2.1 EMS training recs)
        # Pediatric IVT is rec 14 in 4.6.1 — route there, not 2.1.
        (["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"],
         ["children", "child", "pediatric", "paediatric", "neonatal", "neonates",
          "15-year-old", "15 year old", "10-year-old", "8-year-old"],
         ["4.6.1"], ["2.1"]),
        # IVT + SCD/CRAO/pregnancy → 4.6.5 (suppress generic IVT 4.6.1)
        # NOTE: pediatric IVT is rec 14 in 4.6.1, NOT 4.6.5 — don't route there
        (["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"],
         ["pregnant", "pregnancy", "postpartum",
          "sickle cell", "sickle", "scd", "crao", "retinal artery", "retinal",
          "ophthalmic", "visual loss", "central retinal"],
         ["4.6.5"], ["4.6.1"]),
        # IVT + streptokinase/desmoteplase/sono → 4.6.4 (suppress generic IVT 4.6.1)
        (["ivt", "thrombolysis", "thrombolytic", "fibrinolysis"],
         ["streptokinase", "desmoteplase", "sonothrombolysis", "ultrasound-enhanced",
          "intra-arterial", "ancrod", "urokinase", "reteplase", "prourokinase"],
         ["4.6.4"], ["4.6.1"]),
        # IVT + extended window → 4.6.3 (suppress generic IVT 4.6.1)
        (["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"],
         ["wake-up", "wake up", "unknown onset", "dwi-flair", "dwi flair",
          "4.5 to 9", "4.5-9", "extended window", "extended time window",
          "perfusion mismatch",
          "salvageable", "penumbra", "4.5 to 24", "4.5-24", "9 hour",
          "beyond 4.5"],
         ["4.6.3"], ["4.6.1"]),
        # EVT + tandem/stenting → 4.7.4 (suppress generic EVT 4.7.2 AND 4.12)
        # Note: also match "stenting" alone as topic since tandem stenting
        # questions often don't explicitly say "EVT"
        (["evt", "thrombectomy", "endovascular", "mechanical thrombectomy",
          "stenting"],
         ["tandem", "tandem lesion", "tandem occlusion",
          "tandem ica", "tandem mca"],
         ["4.7.4"], ["4.7.2", "4.12"]),
        # EVT + tirofiban → 4.7.4 (suppress 4.8 antiplatelet)
        (["evt", "thrombectomy", "endovascular"],
         ["tirofiban", "preoperative tirofiban"],
         ["4.7.4"], ["4.8"]),
        # EVT + rescue/balloon → 4.7.4 (suppress generic EVT 4.7.2)
        (["evt", "thrombectomy", "endovascular"],
         ["rescue", "balloon-guided", "balloon guided", "balloon catheter",
          "proximal balloon", "rescue angioplasty", "rescue stenting",
          "ia alteplase", "ia urokinase", "intra-arterial"],
         ["4.7.4"], ["4.7.2"]),
        # anticoagulation + hemorrhagic transformation → 4.9 (suppress 4.6.1 AND 4.8)
        # "HT anticoagulation" or "hemorrhagic transformation anticoag" should not
        # match aspirin rec in 4.8 or IVT recs in 4.6.1.
        (["anticoagulation", "anticoagulant", "anticoag"],
         ["hemorrhagic transformation", "hemorrhagic conversion", "ht"],
         ["4.9"], ["4.6.1", "4.8"]),
        # anticoagulation + dissection → 4.9 (suppress 4.8)
        (["anticoagulation", "anticoagulant"],
         ["dissection", "intraluminal thrombus"],
         ["4.9"], ["4.8"]),
        # DOAC + AF → 4.9 (suppress 4.8 antiplatelet)
        (["doac", "direct oral anticoagulant", "apixaban", "rivaroxaban",
          "dabigatran", "edoxaban"],
         ["atrial fibrillation", "af ", "afib"],
         ["4.9"], ["4.8"]),
        # Specific alternative thrombolytics → 4.6.4 (suppress generic IVT 4.6.1 AND 4.6.2)
        # Drug names alone + any stroke context is sufficient signal.
        # Also suppress 4.6.2 because "thrombolytic" in the question matches 4.6.2
        # (tenecteplase section), but these drugs belong to 4.6.4.
        (["reteplase", "prourokinase", "mutant prourokinase", "urokinase",
          "desmoteplase", "ancrod", "streptokinase"],
         ["stroke", "ais", "treatment", "recommended", "evidence",
          "guideline", "cor", "benefit", "effective", "thrombolytic",
          "iv ", "presenting"],
         ["4.6.4"], ["4.6.1", "4.6.2"]),
        # Sonothrombolysis / ultrasound adjuncts → 4.6.4 (suppress 4.6.1)
        (["transcranial doppler", "sonothrombolysis", "catheter-directed ultrasound",
          "catheter ultrasound", "ultrasound-enhanced", "ultrasound enhanced"],
         ["thrombolysis", "ivt", "alteplase", "stroke", "ais",
          "treatment", "enhance", "augment", "adjunct", "effective"],
         ["4.6.4"], ["4.6.1"]),
        # DAPT/taking-antiplatelet + IVT eligibility → 4.6.1 (suppress 4.8)
        # "Can alteplase be given to patient ON aspirin+clopidogrel?" is about
        # IVT eligibility (4.6.1 rec 9), not about starting aspirin with IVT (4.8)
        (["taking aspirin", "on aspirin", "currently taking", "dapt",
          "dual antiplatelet", "aspirin and clopidogrel", "aspirin and plavix",
          "antiplatelet therapy a contraindication"],
         ["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa",
          "safely", "eligible", "administered", "contraindication"],
         ["4.6.1"], ["4.8"]),
        # Medium vessel EVT → 4.7.4 rec 5 (suppress generic EVT 4.7.2)
        (["evt", "thrombectomy", "endovascular"],
         ["medium vessel", "mevo", "distal vessel", "medium or distal"],
         ["4.7.4"], ["4.7.2"]),
        # EVT + pre-existing disability / mRS → keep in 4.7.2 (no suppression)
        # but boost by adding specific topic sections
        # Glibenclamide/glyburide → 6.2 (already routed, but suppress 6.1)
        (["glibenclamide", "glyburide"],
         ["edema", "swelling", "cerebral", "stroke", "ais", "outcome",
          "improve", "effective", "recommended"],
         ["6.2"], ["6.1"]),
        # Hemicraniectomy + mortality/<=60 → 6.3 (ensure routing)
        (["hemicraniectomy", "craniectomy", "decompressive surgery",
          "decompressive craniectomy"],
         ["mortality", "death", "survival", "malignant", "mca infarction",
          "deteriorate"],
         ["6.3"], []),
        # Stem cell / cell therapy → 4.11 (suppress common sections)
        (["stem cell", "cell therapy", "cell-based therapy"],
         ["stroke", "ais", "treatment", "recommended", "guideline"],
         ["4.11"], ["4.6.1", "4.8"]),
        # Nicardipine/labetalol + IVT → 4.6.1 (suppress 4.3 generic BP)
        # "nicardipine for pre-IVT blood pressure" should route to 4.6.1 rec 4
        # which covers BP management before IVT, not 4.3 (general BP).
        (["nicardipine", "labetalol"],
         ["ivt", "thrombolysis", "alteplase", "pre-ivt", "before ivt",
          "prior to ivt", "before thrombolysis"],
         ["4.6.1"], ["4.3"]),
        # IVT + withheld/delayed for EVT → 4.7.1 (suppress 4.3)
        (["ivt", "thrombolysis"],
         ["withheld", "withhold", "delay for evt", "skip for evt", "evt is planned"],
         ["4.7.1"], ["4.3"]),
        # IVT + "before EVT/thrombectomy/endovascular" → 4.7.1 (suppress 4.6.1)
        # QA-2124/2126/2132/2134: "give IVT before EVT", "IVT before transfer"
        (["ivt", "thrombolysis", "alteplase", "tpa"],
         ["before evt", "before thrombectomy", "before endovascular",
          "before transfer", "bridging", "spoke hospital",
          "delaying evt", "delay evt", "observe ivt",
          "evt transfer", "evt-eligible", "evt eligible",
          "transferred for evt", "transferred for endovascular",
          "transferred for thrombectomy", "transfer for evt",
          "transfer for endovascular", "transfer for thrombectomy",
          "even if"],
         ["4.7.1"], ["4.6.1", "2.4", "2.9"]),
        # Cerebellar infarction + decompression → 6.4 (suppress 6.1, 6.2, 4.7.2)
        (["cerebellar", "posterior fossa"],
         ["decompression", "craniectomy", "suboccipital", "ventriculostomy",
          "hydrocephalus", "mass effect", "brainstem compression",
          "surgical intervention", "surgery"],
         ["6.4"], ["6.1", "6.2", "4.7.2"]),
        # Abciximab → 4.8 (suppress other sections)
        (["abciximab", "iv abciximab"],
         ["stroke", "ais", "recommended", "acute", "ischemic"],
         ["4.8"], ["2.1"]),
        # DWI-FLAIR mismatch / wake-up stroke → 4.6.3 (suppress 4.1 oxygenation)
        # "DWI-FLAIR mismatch at 6 hours" should route to 4.6.3 (IVT extended),
        # not 4.1 (hyperoxia at 6 hours). The "6 hours" in 4.1 rec causes false match.
        (["dwi-flair", "dwi flair", "flair mismatch", "dwi mismatch"],
         ["hour", "ivt", "thrombolysis", "mismatch", "onset", "stroke",
          "unknown", "wake"],
         ["4.6.3"], ["4.1"]),
        # Hemorrhagic transformation + anticoagulation → 4.9 (suppress 4.8)
        # "HT anticoagulation" should go to 4.9 rec 4, not 4.8 rec 1 (aspirin)
        (["anticoagulation", "anticoagulant", "anticoag"],
         ["ht", "hemorrhagic transformation", "hemorrhagic conversion"],
         ["4.9"], ["4.8"]),
        # "door-to-needle" / "dtn" → 4.6.1 (suppress 3.2 imaging)
        # QA-2006: "minimize door-to-needle time for thrombolysis" → 4.6.1 rec 3
        (["door-to-needle", "door to needle", "dtn"],
         ["thrombolysis", "ivt", "alteplase", "thrombolytic",
          "reduce", "shorten", "time", "target", "minimize"],
         ["4.6.1"], ["3.2"]),
        # Nicardipine/labetalol (standalone, no explicit IVT) → 4.3 + 4.6.1
        # QA-2015: "nicardipine infusion appropriate for pre-IVT blood pressure"
        # The compound override for nicardipine+IVT already exists above.
        # But we also need to suppress 2.3 (prehospital BP, COR 3:NB).
        (["nicardipine", "labetalol"],
         ["blood pressure", "bp", "hypertension", "pre-ivt", "appropriate",
          "infusion", "management", "lower"],
         ["4.3", "4.6.1"], ["2.3"]),
        # "perfusion imaging beyond/after 4.5 hours" → 4.6.3 (suppress 4.6.1)
        # QA-2071: "Can perfusion imaging identify IVT candidates beyond 4.5 hours?"
        (["perfusion imaging", "perfusion mismatch", "penumbra imaging",
          "automated perfusion"],
         ["beyond 4.5", "after 4.5", "4.5 hours", "extended", "candidates",
          "identify", "select"],
         ["4.6.3"], ["4.6.1"]),
        # EVT + 18 hours / extended window → 4.7.2 (suppress 4.6.3)
        # QA-2170: "EVT at 18 hours with salvageable tissue"
        (["evt", "thrombectomy", "endovascular"],
         ["18 hours", "18h", "16 hours", "16h", "12 hours", "12h",
          "late window", "extended window"],
         ["4.7.2"], ["4.6.3"]),
        # "imaging criteria" + EVT + extended window → 4.7.2 (suppress 3.2)
        # QA-2171: "What imaging criteria determine EVT eligibility in 6-24h window?"
        (["imaging criteria", "imaging requirement", "imaging selection"],
         ["evt", "thrombectomy", "endovascular", "6-24", "6 to 24",
          "eligibility"],
         ["4.7.2"], ["3.2"]),
        # "large ischemic core" + EVT → 4.7.2 (suppress 6.3 craniectomy)
        # QA-2466: "Is Level A evidence available for EVT in large ischemic cores?"
        (["large ischemic core", "large core", "large infarct core",
          "low aspects"],
         ["evt", "thrombectomy", "endovascular", "evidence", "level a"],
         ["4.7.2"], ["6.3"]),
        # Dissection + "antiplatelet or anticoag" → 4.8 rec 7 (suppress 4.3, 4.9)
        # QA-2267: "antiplatelet or anticoagulation for cervical artery dissection"
        # 4.8 rec 7 covers both antiplatelet AND anticoag for dissection (COR 2a).
        # When both treatments are mentioned, route to the combined rec in 4.8.
        (["dissection", "cervical artery dissection", "cervical dissection"],
         ["antiplatelet or anticoag", "either antiplatelet",
          "antiplatelet therapy for"],
         ["4.8"], ["4.3", "4.9"]),
        # "heparin" + "acute stroke treatment" → 4.9 (suppress 4.8, 2.1, 4.6.1)
        # QA-2301: "Is heparin recommended for acute stroke treatment?"
        (["heparin"],
         ["acute stroke", "acute ischemic", "stroke treatment", "recommended for"],
         ["4.9"], ["4.8", "2.1", "4.6.1"]),
        # "emergency carotid" / "emergent carotid" → 4.12
        # QA-2338: "Is the evidence for emergency carotid intervention..."
        (["emergency carotid", "emergent carotid", "urgent carotid",
          "emergent endarterectomy", "emergency endarterectomy"],
         ["evidence", "intervention", "outcome", "beneficial", "observational",
          "stroke", "ais"],
         ["4.12"], []),
        # "unknown onset" / "last seen well" + "within 3 hours" / short time →
        # 4.6.1 (suppress 4.6.3). If LKW is <4.5h, it's standard IVT, not extended.
        # QA-2461: "patient with unknown onset who was last seen well 3 hours ago"
        (["last seen well 3 hours", "last seen well 2 hours",
          "last known well 3 hours", "last known well 2 hours",
          "last seen well 1 hour", "last known well 1 hour"],
         ["ivt", "thrombolysis", "alteplase", "recommendation", "unknown"],
         ["4.6.1"], ["4.6.3", "3.2"]),
        # "therapeutic hypothermia" + "neuroprotective" → 4.11 (suppress 4.4)
        # QA-2326: "Is therapeutic hypothermia recommended as a neuroprotective strategy?"
        (["therapeutic hypothermia", "hypothermia"],
         ["neuroprotective", "neuroprotection", "neuroprotective strategy"],
         ["4.11"], ["4.4"]),
        # "comprehensive stroke center" / "stroke center care" → 5.1 (suppress 2.4, 2.6)
        # QA-2345/2470: these are about inpatient care (5.1), not EMS transport (2.4).
        (["comprehensive stroke center", "stroke center care",
          "stroke center associated", "stroke centre"],
         ["mortality", "reduced mortality", "all ais", "all ages",
          "recommended", "care for all"],
         ["5.1"], ["2.4", "2.6"]),
        # "psychotherapy/acupuncture" + depression → 5.5 rec 2 (suppress screening rec)
        (["psychotherapy", "acupuncture", "treatment modality"],
         ["depression", "poststroke depression", "psd"],
         ["5.5"], []),
        # "mixing alteplase" + imaging/CT context → 4.6.1 (suppress 4.6.2)
        # QA-2009: "mixing alteplase during initial CT evaluation"
        (["mixing alteplase", "mixing tpa", "mixing ivt"],
         ["ct", "imaging", "evaluation", "preparing", "during"],
         ["4.6.1"], ["4.6.2"]),
        # "IVT preparation" + "before imaging" → 4.6.1 (suppress 3.2)
        # QA-2048: "Should IVT preparation begin before imaging is complete?"
        (["ivt preparation", "prepare ivt", "preparing ivt", "preparation begin"],
         ["before imaging", "imaging is complete", "imaging complete",
          "during imaging"],
         ["4.6.1"], ["3.2"]),
        # "strongest recommendation against" + thrombolytic → 4.6.4 (streptokinase)
        # QA-2101/2107: "strongest against any thrombolytic", "COR 3:Harm thrombolytic"
        (["strongest recommendation against", "strongest against",
          "cor 3:harm", "3:harm thrombolytic", "rates as cor 3:harm"],
         ["thrombolytic", "fibrinolytic", "agent", "drug"],
         ["4.6.4"], ["4.6.1", "4.6.2"]),
        # "woke up" + short time (2 hours ago, 1 hour ago) → standard IVT 4.6.1
        # NOT wake-up stroke pathway 4.6.3. If the patient woke up and we know
        # it was only 2 hours ago, the standard window applies.
        # QA-2040: "Can IVT be given to a patient who woke up with stroke symptoms 2 hours ago?"
        (["woke up", "woke with", "awakened with"],
         ["2 hours ago", "1 hour ago", "90 minutes ago", "3 hours ago",
          "2 hours from", "1 hour from"],
         ["4.6.1"], ["4.6.3"]),
        # ── R6 compound overrides ────────────────────────────────
        # Transport/transfer + thrombectomy → 2.4 (suppress generic EVT 4.7.2)
        (["transport", "transfer", "air medical", "air transport", "helicopter"],
         ["thrombectomy", "evt", "endovascular"],
         ["2.4"], ["4.7.2"]),
        # Mobile stroke unit + thrombectomy/IVT context → 2.5 (suppress 4.7.2, 2.2, 4.6.x)
        (["mobile stroke unit", "msu"],
         ["thrombectomy", "evt", "ivt", "thrombolysis", "time to", "reduce time",
          "disability", "functional outcome", "symptom onset"],
         ["2.5"], ["4.7.2", "2.2", "4.6.1", "4.6.3"]),
        # Lab testing + IVT → 3.3 (suppress 4.6.1)
        # NOTE: "laboratory" is too generic — it fires on "not delaying IVT
        # to wait for laboratory values" which should stay in 4.6.1.
        (["lab testing", "routine lab", "blood test",
          "coagulation test", "baseline lab"],
         ["ivt", "thrombolysis", "alteplase", "before ivt", "required before"],
         ["3.3"], ["4.6.1"]),
        # IVT + delay/wait for imaging → 4.6.1 (suppress 3.2)
        (["ivt", "thrombolysis", "alteplase"],
         ["delayed for", "wait for", "delay imaging", "cta results",
          "advanced imaging", "wait for cta", "should be delayed"],
         ["4.6.1"], ["3.2"]),
        # IVT + cardiac catheterization/procedural stroke → 4.6.5 (suppress 4.6.1)
        (["ivt", "thrombolysis", "alteplase", "thrombolytic"],
         ["cardiac catheterization", "procedural stroke", "during cardiac",
          "angiographic procedure", "catheterization stroke"],
         ["4.6.5"], ["4.6.1"]),
        # EVT + ASPECTS → 4.7.2 (suppress 3.2)
        (["evt", "thrombectomy", "endovascular"],
         ["aspects", "aspects less than", "aspects score", "low aspects"],
         ["4.7.2"], ["3.2"]),
        # EVT + perfusion imaging/favorable perfusion → 4.7.2 (suppress 3.2)
        (["evt", "thrombectomy", "endovascular"],
         ["perfusion imaging", "favorable perfusion", "perfusion mismatch",
          "favorable imaging"],
         ["4.7.2"], ["3.2"]),
        # Early mobilization + DVT/prevention → 5.4 (suppress 5.7)
        (["early mobilization", "mobilization", "mobilized"],
         ["dvt", "deep vein", "prevention", "prophylaxis", "vte",
          "venous thromboembolism"],
         ["5.4"], ["5.7"]),
        # Tube feeding/PEG + dysphagia/swallow → 5.2 (suppress 5.3)
        (["tube feeding", "enteral tube", "peg tube", "nasogastric"],
         ["dysphagia", "swallow", "cannot safely swallow", "swallowing",
          "oral intake"],
         ["5.2"], ["5.3"]),
        # LMWH/heparin + acute treatment → 4.9 (suppress 5.4, 4.7.4)
        (["lmwh", "low-molecular-weight heparin", "low molecular weight"],
         ["acute treatment", "acute ais", "acute stroke", "recommended for"],
         ["4.9"], ["5.4", "4.7.4"]),
        # Urgent anticoagulation + 24 hours → 4.9 (suppress 5.7)
        (["urgent anticoagulation", "anticoagulation"],
         ["within 24 hours", "early recurrence", "prevent early",
          "prevent recurrence"],
         ["4.9"], ["5.7"]),
        # Glycoprotein/GPIIb/IIIa + EVT → 4.7.4 (suppress 4.8, 4.7.2)
        (["glycoprotein", "gpiib/iiia", "gp iib/iiia", "gpiib",
          "glycoprotein iib/iiia"],
         ["evt", "thrombectomy", "endovascular", "during evt"],
         ["4.7.4"], ["4.8", "4.7.2"]),
        # Intracranial stenting/angioplasty + first-line/EVT → 4.7.4 (suppress 4.7.2)
        (["intracranial stenting", "intracranial angioplasty",
          "angioplasty or stenting", "stenting as first"],
         ["first-line", "first line", "evt", "thrombectomy",
          "recommended", "primary"],
         ["4.7.4"], ["4.7.2"]),
        # Fluoxetine + motor/recovery → 5.6 (suppress 5.7)
        (["fluoxetine"],
         ["motor recovery", "motor function", "improve recovery",
          "routine", "does not improve", "not beneficial"],
         ["5.6"], ["5.7"]),
        # Door-to-needle + minutes/target → 2.7 (suppress 4.6.1)
        (["door-to-needle", "door to needle", "dtn"],
         ["minutes", "target", "60 minutes", "under 60",
          "time target", "achieve"],
         ["2.7"], ["4.6.1", "6.3"]),
        # Door-to-imaging + minutes → 2.7 (suppress 3.2)
        (["door-to-imaging", "door to imaging"],
         ["minutes", "20 minutes", "target", "recommended"],
         ["2.7"], ["3.2"]),
        # Aspiration thrombectomy → 4.7.4 (suppress 4.3, 4.1)
        (["aspiration thrombectomy", "contact aspiration",
          "aspiration technique"],
         ["anterior circulation", "lvo", "recommended", "effective"],
         ["4.7.4"], ["4.3", "4.1"]),
        # Blood glucose + IVT → 3.3 (suppress 4.5, 4.6.1)
        (["blood glucose", "glucose"],
         ["before ivt", "check before", "baseline", "prior to ivt"],
         ["3.3"], ["4.5", "4.6.1"]),
        # Stroke severity scale + validated/NIHSS → 3.1 (suppress 3.2)
        (["stroke severity", "stroke scale", "severity scale",
          "severity rating scale"],
         ["nihss", "validated", "assess", "all ais", "all patients"],
         ["3.1"], ["3.2"]),
        # EVT alone vs EVT+IVT / direct EVT → 4.7.1 (suppress 4.7.2)
        (["evt alone", "evt without ivt", "direct evt",
          "evt versus ivt", "evt plus ivt", "evt vs ivt"],
         ["stroke", "ais", "trial", "tested", "compared"],
         ["4.7.1"], ["4.7.2", "4.6.1"]),
        # Hospital stroke capabilities → 2.6 (suppress 5.1)
        (["hospital stroke", "hospital capabilities", "stroke capabilities"],
         ["capabilities", "certification", "research gap", "knowledge gap",
          "gaps"],
         ["2.6"], ["5.1"]),
        # Prehospital + oxygen → 2.3 (suppress 4.1)
        (["prehospital", "prehospital setting", "ems"],
         ["oxygen", "supplemental oxygen", "non-hypoxic", "hypoxic"],
         ["2.3"], ["4.1"]),
        # "on aspirin" / "taking aspirin" + IVT → 4.6.1 (suppress 4.8)
        # This is the patient-ON-aspirin eligibility question.
        (["on aspirin", "taking aspirin", "currently on aspirin",
          "patient on aspirin", "receive ivt"],
         ["ivt", "thrombolysis", "alteplase", "acute stroke",
          "receive", "eligible"],
         ["4.6.1"], ["4.8", "2.1"]),
        # Stroke center + certification + improve → 2.9 (suppress 2.4)
        (["certification", "stroke center certification"],
         ["improve", "outcomes", "pursued", "benefit"],
         ["2.9"], ["2.4"]),
        # Transporting + stroke + hospital → 2.4
        (["transporting", "transport"],
         ["stroke patient", "stroke-capable", "closest hospital",
          "closest stroke"],
         ["2.4"], []),
        # Lying flat / head positioning → 4.2 (suppress 3.2)
        (["lying flat", "flat position", "head position",
          "0-degree", "zero degree", "head of bed"],
         ["stroke", "ais", "outcome", "improve", "benefit",
          "recommended", "routine"],
         ["4.2"], ["3.2"]),
        # Aggressive BP lowering + after IVT → 4.3 (suppress 6.3, 4.6.1)
        (["aggressive bp", "bp lowering", "bp reduction",
          "aggressive lowering", "aggressively lower"],
         ["ivt", "thrombolysis", "received ivt", "after ivt",
          "received thrombolysis", "after thrombolysis",
          "140 mmhg", "less than 140"],
         ["4.3"], ["6.3", "4.6.1"]),
        # BP reduction + 24-48 hours / hypertensive response → 4.3 (suppress 5.3)
        (["bp reduction", "bp lowering", "blood pressure",
          "hypertensive response", "hypertensive"],
         ["24-48 hours", "24 hours", "48 hours",
          "first 24", "first 48", "140/90"],
         ["4.3"], ["5.3"]),
    ]

    suppressed_sections: set = set()
    for topic_terms, context_terms, target_sections, suppress in _COMPOUND_OVERRIDES:
        has_topic = any(tt in q_lower for tt in topic_terms)
        has_context = any(ct in q_lower for ct in context_terms)
        if has_topic and has_context:
            matched_sections.extend(target_sections)
            suppressed_sections.update(suppress)

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

    # Deduplicate while preserving order, and remove suppressed sections
    seen: set = set()
    result: List[str] = []
    for s in matched_sections:
        if s not in seen and s not in suppressed_sections:
            seen.add(s)
            result.append(s)
    return result, suppressed_sections


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
    suppressed_sections: Optional[set] = None,
    section_discriminators: Optional[Dict[str, Dict[str, set]]] = None,
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
    text_hits = 0
    for term in search_terms:
        if term in text_lower:
            score += 3
            text_hits += 1
        elif term in metadata_lower:
            score += 1

    # Density bonus — when many search terms match the rec text, it's a stronger
    # topical match. This helps distinguish between multiple recs in the same
    # section (e.g., 18 recs in 4.8) where section boost alone can't differentiate.
    if text_hits >= 4:
        score += (text_hits - 3) * 2  # +2 per extra hit beyond 3

    # ── Discriminating criteria matcher ──────────────────────────────
    # Within multi-rec sections, recs differ by specific clinical criteria.
    # When the question mentions one of these discriminating phrases AND the
    # rec text contains it, give a strong bonus.  This is what differentiates
    # "decompressive craniectomy ≤60y" (COR 1) from ">60y" (COR 2b) in 6.3,
    # or "M2 dominant" (COR 2a) from "ICA/M1" (COR 1) in 4.7.2.
    #
    # These are checked as phrase-in-text, not single keywords, so they only
    # fire when both question and rec share the specific criterion.
    _DISCRIMINATING_PHRASES = [
        # Age thresholds (6.3 craniectomy, 4.7.2 EVT)
        "60", "age 60", "<=60", "≤60", ">60", "age >60", "age 80", "<80", ">=80",
        "younger than 60", "older than 60", "60 years", "80 years",
        # Vessel specifics (4.7.2)
        "m2", "m1", "ica", "dominant", "nondominant", "non-dominant", "codominant",
        "proximal", "distal", "medium vessel",
        # NIHSS/ASPECTS thresholds
        "nihss 6", "nihss 10", "nihss score",
        "aspects 0", "aspects 3", "aspects 6",
        "pc-aspects",
        # Time windows
        "0-6", "6-24", "0 to 6", "6 to 24", "within 6", "within 24",
        "within 48", "24 hours", "48 hours",
        # Specific drugs/procedures (4.8, 4.9)
        "aspirin", "clopidogrel", "ticagrelor", "tirofiban", "abciximab",
        "eptifibatide", "dapt", "dual antiplatelet", "triple antiplatelet",
        "warfarin", "doac", "heparin", "argatroban", "enoxaparin",
        # Specific conditions
        "atrial fibrillation", "af ", "dissection", "stenosis",
        "sickle cell", "pediatric", "pregnancy", "pregnant",
        "elastic compression", "ipc", "pneumatic",
        # Specific interventions (6.3)
        "hemicraniectomy", "craniectomy", "ventriculostomy",
        "osmotic", "glibenclamide", "hypothermia", "barbiturate", "corticosteroid",
        # IVT-specific
        "nondisabling", "non-disabling", "disabling", "mild",
        "0.25 mg", "0.4 mg", "0.9 mg", "tenecteplase", "alteplase",
        # Rehab/inpatient
        "mobilization", "ssri", "antidepressant",
        "prophylactic antibiotic", "bladder catheter", "palliative",
        "swallowing", "dysphagia", "enteral", "nasogastric",
        # 4.6.1: IVT within-section — nondisabling vs disabling, CMB, pediatric, labs
        "non-disabling", "nondisabling", "not disabling", "mild stroke",
        "minor stroke", "no functional impairment", "isolated sensory",
        "microbleed", "cerebral microbleed", "cmb", "high burden",
        "low burden", "small number", "extensive microbleed",
        "platelet count", "lab result", "delay for lab",
        "28 days", "18 years", "pediatric patients",
        # 4.9: early anticoag vs DOAC for AF
        "atrial fibrillation", "af ", "doac", "oral anticoagul",
        "early anticoagulation", "within 48 hours", "heparin",
        "lmwh", "enoxaparin", "hemorrhagic transformation",
        "argatroban", "adjunctive", "hemorrhagic transformation",
        # 6.5: prophylactic vs treatment of seizure
        "prophylactic", "prophylaxis", "prevent seizure",
        "unprovoked seizure", "levetiracetam",
        "routine eeg", "eeg monitoring",
        # 4.7.4: EVT technique specifics
        "stent retriever", "contact aspiration", "tici",
        "reperfusion", "anesthesia", "sedation",
        "balloon-guided", "balloon catheter", "proximal balloon",
        "tandem", "rescue", "ia alteplase", "ia urokinase",
        "tirofiban", "preoperative",
        # 4.6.4: alternative thrombolytic agents
        "reteplase", "prourokinase", "mutant prourokinase", "urokinase",
        "desmoteplase", "streptokinase", "ancrod", "sonothrombolysis",
        "transcranial doppler", "catheter-directed",
        "0.25 mg", "not undergoing evt", "in combination",
        # 4.6.2: TNK dose discrimination
        "0.4 mg", "0.25 mg/kg", "0.4 mg/kg",
        # 4.6.5: special populations
        "sickle cell", "scd", "crao", "retinal artery",
        "ophthalmic", "visual loss",
        # 4.8: trial-specific terms
        "thales", "socrates", "inspires", "chance-2",
        "cyp2c19", "noncardioembolic", "triple antiplatelet",
        # 4.9: anticoagulation specifics
        "milder severity", "intraluminal thrombus", "dissection",
        "does not reduce", "not effective", "not beneficial",
        "ica stenosis", "factor xa",
        # 6.2: specific agents
        "glibenclamide", "glyburide", "barbiturate",
        "corticosteroid", "hypothermia",
        # 6.3: age and mortality
        "<=60", ">60", "mortality", "deteriorate",
        "malignant cerebral", "mca infarction",
        # 4.7.5: pediatric age ranges
        ">=6 years", "28 days to 6 years", "neonates",
        "6 to 24 hours",
        # 4.11: neuroprotection
        "stem cell", "neuroprotective", "pharmacological",
    ]

    q_lower_for_disc = question.lower() if question else ""
    if q_lower_for_disc:
        disc_bonus = 0
        for phrase in _DISCRIMINATING_PHRASES:
            if phrase in q_lower_for_disc and phrase in text_lower:
                disc_bonus += 5
        # Cap at +30 to allow specific multi-phrase matches to differentiate
        # within sections that have many similar recs (e.g., 4.6.4, 4.8)
        score += min(disc_bonus, 30)

        # ── Negative discriminator ──────────────────────────────────
        # Penalize recs whose text CONTRADICTS the question's criteria.
        # E.g., question says "dominant M2" but rec says "nondominant" — penalize.
        # E.g., question says "over 60" but rec says "<=60" — penalize.
        _CONTRADICTION_PAIRS = [
            # (question_term, rec_negative_term, penalty)
            # M2 dominant vs nondominant
            ("dominant m2", "nondominant", -10),
            ("dominant proximal m2", "nondominant", -10),
            ("nondominant", "dominant proximal m2", -8),
            ("non-dominant", "dominant proximal m2", -8),
            # Age thresholds
            ("over 60", "<=60", -8),
            ("older than 60", "<=60", -8),
            (">60", "<=60", -8),
            ("under 60", ">60", -8),
            ("younger than 60", ">60", -8),
            ("<=60", ">60", -8),
            # NIHSS direction
            ("low nihss", "nihss score >=10", -5),
            ("nihss 6 to 9", "nihss score >=10", -5),
            ("high nihss", "nihss score 6 to 9", -5),
            # 4.6.1: nondisabling vs disabling — prevent dominant COR 1 rec from
            # outscoring the COR 3:NB "mild non-disabling" rec when question asks
            # about nondisabling. Strengthened penalties to overcome the COR 1 recs'
            # inherent keyword advantage (they match "IVT", "stroke", "AIS" etc.).
            ("non-disabling", "disabling deficits", -10),
            ("non-disabling", "disabling stroke", -10),
            ("non-disabling", "hypoglycemia", -10),
            ("non-disabling", "hyperglycemia", -10),
            ("nondisabling", "disabling deficits", -10),
            ("nondisabling", "disabling stroke", -10),
            ("nondisabling", "hypoglycemia", -10),
            ("nondisabling", "hyperglycemia", -10),
            ("not disabling", "disabling deficits", -10),
            ("not disabling", "disabling stroke", -10),
            ("minor stroke", "disabling deficits", -10),
            ("minor stroke", "disabling stroke", -10),
            ("minor stroke", "regardless of nihss", -8),
            # Penalize rec 7 (about ischemic change, COR 1) for nondisabling queries
            # Rec 7 contains "mild to moderate extent" which matches "mild" in question
            ("nondisabling", "ischemic change of mild", -10),
            ("non-disabling", "ischemic change of mild", -10),
            ("mild nondisabling", "ischemic change of mild", -12),
            ("mild non-disabling", "ischemic change of mild", -12),
            # Penalize rec 9 (COR 1 about anticoagulant/antiplatelet IVT eligibility)
            ("nondisabling", "taking an anticoagulant", -8),
            ("non-disabling", "taking an anticoagulant", -8),
            ("nondisabling", "antiplatelet agents", -8),
            ("non-disabling", "antiplatelet agents", -8),
            ("no functional impairment", "disabling deficits", -10),
            ("no functional impairment", "regardless of nihss", -8),
            ("nihss 2", "disabling deficits", -8),
            # 4.6.1: prevent pediatric rec (2b) from outscoring adult recs
            ("55-year-old", "pediatric patients", -10),
            ("55-year-old", "28 days to 18 years", -10),
            ("70-year-old", "pediatric patients", -10),
            ("70-year-old", "28 days to 18 years", -10),
            ("adult", "pediatric patients", -8),
            ("adult", "28 days to 18 years", -8),
            # 4.6.1: prevent adult IVT recs from outscoring when asking about microbleeds
            ("high burden", "regardless of nihss", -5),
            ("extensive microbleed", "regardless of nihss", -5),
            # 6.5: prophylactic vs treatment — prevent COR 1 treatment rec from
            # outscoring COR 3:NB prophylaxis rec. Strong penalty needed because
            # COR 1 rec has many keyword overlaps (antiseizure, AIS, etc.).
            ("prophylactic", "unprovoked seizure", -12),
            ("prophylaxis", "unprovoked seizure", -12),
            ("prophylactically", "unprovoked seizure", -12),
            ("prevent seizure", "unprovoked seizure", -12),
            ("routine eeg", "unprovoked seizure", -10),
            ("routine eeg", "antiseizure medication is recommended", -10),
            # 4.9: prevent COR 2a DOAC/AF rec from outscoring when asking about
            # routine early anticoag (COR 3:NB)
            ("early anticoagulation", "atrial fibrillation", -8),
            ("heparin", "atrial fibrillation", -6),
            ("lmwh", "atrial fibrillation", -6),
            # 4.9: prevent COR 3:NB early anticoag rec from outscoring when asking
            # about DOAC for AF (COR 2a). Need strong penalty since both recs
            # share "within 48 hours" text and many other terms.
            ("doac", "early anticoagulation (within 48 hours", -10),
            ("atrial fibrillation", "early anticoagulation (within 48 hours", -10),
            ("af ", "early anticoagulation (within 48 hours", -10),
            # 4.9: hemorrhagic transformation → COR 2b rec, not the AF rec (2a)
            ("hemorrhagic transformation", "atrial fibrillation", -8),
            # Cross-section: DOAC questions shouldn't match aspirin recs (4.8)
            ("doac", "aspirin", -8),
            # 4.6.4: "combination" → prourokinase combination (COR 3:NB), not standalone
            ("combination", "not undergoing evt", -5),
            # 4.6.1: additional penalties to separate glucose rec (COR 1, rec 6) from
            # nondisabling rec (COR 3:NB, rec 8). The glucose rec matches many
            # generic terms ("suspected ischemic stroke", "disabling stroke").
            ("minor", "hypoglycemia", -8),
            ("minor", "hyperglycemia", -8),
            ("minor stroke", "hypoglycemia", -8),
            ("nondisabling", "hypoglycemia", -8),
            ("non-disabling", "hypoglycemia", -8),
            ("not disabling", "hypoglycemia", -8),
            ("no functional impairment", "hypoglycemia", -8),
            ("nihss 2", "hypoglycemia", -8),
            ("nihss 2", "disabling deficits", -8),
            ("nihss 2", "regardless of nihss", -8),
            # Questions about IVT benefit with low NIHSS / no impairment should
            # penalize all COR 1 recs that assume disabling deficits
            ("no functional impairment", "hypoglycemia", -8),
            ("no functional impairment", "hyperglycemia", -8),
            ("no functional impairment", "ischemic change of mild", -8),

            # ── 4.6.1: "disabling" questions → penalize non-disabling rec ──
            # Reverse direction: when question explicitly says "disabling" (not
            # "non-disabling"), penalize rec 8 (COR 3:NB) which is about non-disabling.
            # Use multi-word phrases to avoid matching "non-disabling".
            ("disabling stroke", "non-disabling", -10),
            ("disabling ais", "non-disabling", -10),
            ("disabling symptoms", "non-disabling", -10),
            ("disabling deficits", "non-disabling", -10),
            ("regardless of evt", "non-disabling", -10),
            ("regardless of whether evt", "non-disabling", -10),
            ("disabling ais regardless", "non-disabling", -10),

            # ── 4.6.1: CMB recs discrimination ──
            # Rec 11 (COR 1) = unknown burden of CMBs
            # Rec 12 (COR 2a) = small number of CMBs
            # Rec 13 (COR 2b) = high burden / extensive CMBs
            # "small number of CMBs" → rec 12, NOT rec 11 (unknown burden)
            ("small number", "regardless of nihss", -8),
            ("small number", "disabling deficits", -8),
            ("small number", "unknown burden", -10),
            ("small number of cerebral", "unknown burden", -10),
            ("small number of cerebral", "high burden", -8),
            ("small number of cerebral", "previously had extensive", -8),
            # "limited/few CMBs" → rec 12 (small number, COR 2a), NOT rec 11 (unknown, COR 1)
            ("limited cerebral microbleed", "unknown burden", -12),
            ("limited microbleed", "unknown burden", -12),
            ("limited cmb", "unknown burden", -12),
            ("few microbleed", "unknown burden", -10),
            ("limited cerebral microbleed", "high burden", -8),
            # "high burden CMBs" → rec 13, NOT rec 11 (unknown burden)
            ("cerebral microbleed", "disabling deficits", -8),
            ("high burden", "disabling deficits", -8),
            ("high burden", "unknown burden", -10),
            ("high burden", "small number", -8),
            ("high cerebral microbleed", "unknown burden", -10),
            ("extensive microbleed", "unknown burden", -10),
            # Prevent rec 11 (unknown burden) from winning when question is specific
            ("high burden", "regardless of nihss", -5),
            ("extensive microbleed", "regardless of nihss", -5),

            # ── 4.6.1: lab/CBC/platelet before IVT → rec 10 (COR 2a) ──
            # Rec 10 is about starting IVT before lab results.
            # Penalize all OTHER recs when question is about "before platelet/CBC"
            ("before platelet", "disabling deficits", -8),
            ("before platelet", "regardless of nihss", -8),
            ("before platelet", "non-disabling", -8),
            ("before platelet", "blood glucose", -8),
            ("before platelet", "ischemic change", -8),
            ("before platelet", "unknown burden", -8),
            ("before cbc", "disabling deficits", -8),
            ("before cbc", "regardless of nihss", -8),
            ("before cbc", "blood glucose", -8),
            ("before cbc", "ischemic change", -8),
            ("before cbc", "unknown burden", -8),
            ("before obtaining", "disabling deficits", -8),
            ("before obtaining", "non-disabling", -8),
            ("before obtaining", "blood glucose", -8),
            ("before obtaining", "ischemic change", -8),
            ("unknown inr", "disabling deficits", -8),
            ("unknown inr", "regardless of nihss", -8),
            ("unknown inr", "non-disabling", -8),
            ("unknown inr", "blood glucose", -8),
            ("unknown inr", "ischemic change", -8),
            ("unknown inr", "unknown burden", -8),
            ("lab result", "disabling deficits", -8),
            ("lab result", "regardless of nihss", -8),
            ("warfarin with unknown", "disabling deficits", -8),
            ("warfarin with unknown", "regardless of nihss", -8),
            ("warfarin with unknown", "blood glucose", -8),
            ("warfarin with unknown", "ischemic change", -8),

            # ── 4.6.1: pediatric IVT → rec 14 (COR 2b) ──
            # When question explicitly mentions pediatric/child, penalize adult recs
            ("pediatric stroke", "disabling deficits", -8),
            ("pediatric stroke", "regardless of nihss", -8),
            # Note: generic adult IVT questions penalizing pediatric rec 14 is handled
            # by the narrow-scope gate at the end of score_recommendation().

            # ── 4.6.2: high-dose TNK (0.4 mg/kg) → rec 2 (COR 3:NB) ──
            # When question asks about 0.4 mg/kg or "higher dose", penalize rec 1
            # which is about 0.25 mg/kg (COR 1)
            ("0.4 mg", "0.25 mg", -10),
            ("0.4mg", "0.25 mg", -10),
            ("higher dose", "0.25 mg", -8),
            ("higher dose of tenecteplase", "0.25 mg", -10),
            ("recommend against", "0.25 mg", -5),

            # ── 4.6.3: within-section LVO+extended vs wake-up/DWI-FLAIR ──
            # "salvageable tissue 4.5-24h LVO" → rec 3 (COR 2b), not rec 1/2 (COR 2a)
            ("4.5 to 24", "unknown time of onset", -8),
            ("4.5-24", "unknown time of onset", -8),
            ("lvo with salvageable", "unknown time of onset", -8),
            # "DWI-FLAIR mismatch" → rec 1 (COR 2a), not rec 3 (COR 2b)
            ("dwi-flair", "4.5 to 24 hours", -8),
            ("dwi flair", "4.5 to 24 hours", -8),
            ("unknown time of onset", "4.5 to 24 hours", -5),
            # "beyond 9 hours" / "9h+" → rec 3 (COR 2b, 4.5-24h), not rec 2 (4.5-9h)
            ("beyond 9 hours", "9 hours from the midpoint", -10),
            ("beyond 9 hours", "4.5–9 hours", -10),
            ("beyond 9", "4.5–9 hours", -8),
            ("after 9 hours", "4.5–9 hours", -10),
            ("9+ hours", "4.5–9 hours", -10),

            # ── 4.6.4: within-section alternative thrombolytic discrimination ──
            # prourokinase standalone → rec 1-2 (COR 2b), not combination rec 4 (3:NB)
            ("prourokinase", "in combination", -8),
            # prourokinase combination → rec 4 (COR 3:NB), not standalone rec 1-2
            ("combination", "not undergoing evt", -8),
            ("combination therapy", "not undergoing evt", -8),
            # urokinase → rec 5 (COR 3:NB), not reteplase/prourokinase recs 1-2
            ("urokinase", "reteplase", -8),
            ("urokinase", "prourokinase", -8),
            ("iv urokinase", "reteplase", -10),
            # sonothrombolysis/transcranial doppler → rec 7 (COR 3:NB)
            ("sonothrombolysis", "reteplase", -8),
            ("sonothrombolysis", "prourokinase", -8),
            ("sonothrombolysis", "urokinase", -8),
            ("transcranial doppler", "reteplase", -8),
            ("transcranial doppler", "prourokinase", -8),
            ("catheter-directed ultrasound", "reteplase", -8),
            ("catheter-directed ultrasound", "prourokinase", -8),
            # desmoteplase → rec 3 (COR 3:NB, LOE A)
            ("desmoteplase", "reteplase", -8),
            ("desmoteplase", "prourokinase", -8),
            # streptokinase → rec 6 (COR 3:Harm)
            ("streptokinase", "reteplase", -8),
            ("streptokinase", "prourokinase", -8),
            ("streptokinase", "sonothrombolysis", -8),
            # "strongest recommendation against" → rec 6 (3:Harm), not rec 3-5 (3:NB)
            ("strongest recommendation against", "is not beneficial", -5),

            # ── 4.6.5: SCD vs CRAO within-section discrimination ──
            ("crao", "sickle cell", -10),
            ("retinal artery", "sickle cell", -10),
            ("retinal", "sickle cell", -8),
            ("ophthalmic", "sickle cell", -8),
            ("visual loss", "sickle cell", -8),
            ("sickle cell", "retinal artery", -10),
            ("scd", "retinal artery", -10),
            ("scd", "central retinal", -10),

            # ── 4.7.2: within-section discrimination ──
            # moderate disability → rec 6 (COR 2b), not rec 1 (COR 1)
            ("moderate pre-existing disability", "nihss score >=6", -5),
            ("moderate disability", "nihss score >=6", -5),
            ("pre-existing disability", "nihss score >=6", -5),
            # medium vessel → 4.7.4 rec 5 (COR 3:NB), penalize 4.7.2 recs
            ("medium vessel", "ica or m1", -10),
            ("medium vessel", "proximal lvo", -8),

            # ── 4.7.3: NIHSS 6-9 basilar → rec 2 (COR 2b), not rec 1 (COR 1) ──
            ("nihss 6 to 9", "nihss score >=10", -10),
            ("nihss between 6", "nihss score >=10", -10),
            ("nihss 6-9", "nihss score >=10", -10),

            # ── 4.7.4: balloon-guided → rec 4 (COR 2b), not rec 1 (COR 1) ──
            ("balloon-guided", "stent retriever", -8),
            ("balloon guided", "stent retriever", -8),
            ("proximal balloon", "stent retriever", -5),
            ("balloon-guided", "contact aspiration", -8),
            # sedation/anesthesia → rec 3 LOE B-R, not rec 1 LOE A
            # (both have COR 1, but different LOE)

            # ── 4.7.5: >=6 years vs <6 years ──
            ("6 years or older", "28 days to 6 years", -10),
            ("aged 6", "28 days to 6 years", -10),
            ("older than 6", "28 days to 6 years", -10),
            ("6 to 24 hours", "28 days to 6 years", -8),
            ("6+", "28 days to 6 years", -10),
            ("6+ years", "28 days to 6 years", -10),
            ("over 6 years", "28 days to 6 years", -10),
            ("above 6 years", "28 days to 6 years", -10),
            ("neonates", ">=6 years", -10),
            ("under 28 days", ">=6 years", -10),
            ("neonatal", ">=6 years", -10),
            ("28 days to 6 years", ">=6 years", -8),

            # ── 4.8: trial-specific antiplatelet discrimination ──
            # THALES (ticagrelor+aspirin DAPT) → rec 13 (COR 2b)
            ("thales", "clopidogrel", -8),
            ("thales", "oral anticoagul", -8),
            # SOCRATES (ticagrelor monotherapy, no benefit) → rec 9 (COR 3:NB)
            ("socrates", "ticagrelor and aspirin", -8),
            ("socrates", "aspirin and ticagrelor", -8),
            ("ticagrelor over aspirin", "aspirin and ticagrelor", -10),
            ("ticagrelor recommended over aspirin alone", "aspirin and ticagrelor", -10),
            ("ticagrelor monotherapy", "aspirin and ticagrelor", -10),
            # INSPIRES → rec 14 (COR 2a), not rec 12 (COR 1) or rec 15 (COR 2b)
            ("inspires", "nihss score <=3", -5),
            # CHANCE-2 (CYP2C19) → rec 15 (COR 2b), not rec 14 (COR 2a)
            ("chance-2", "nihss score <=5", -5),
            ("cyp2c19", "nihss score <=5", -5),
            # antiplatelet + AF → rec 11 (COR 3:Harm), not rec 1 (COR 1)
            ("antiplatelet to anticoagulation", "within 48 hours", -8),
            ("antiplatelet added to anticoag", "within 48 hours", -8),
            ("af and stroke", "noncardioembolic", -10),

            # ── 4.9: within-section discrimination ──
            # LMWH/heparin early anticoag → rec 6 (COR 3:NB), not rec 1 (COR 2a)
            ("lmwh", "oral anticoagulant", -8),
            ("lmwh", "milder severity", -8),
            ("heparin", "oral anticoagulant", -8),
            ("early anticoagulation", "oral anticoagulant", -8),
            ("early anticoagulation", "milder severity", -8),
            ("reduces death", "oral anticoagulant", -8),
            ("reduces death", "milder severity", -8),
            # Dissection → rec 3 (COR 2b), not rec 1 (COR 2a AF)
            ("dissection", "atrial fibrillation", -10),
            ("carotid dissection", "atrial fibrillation", -10),
            ("intraluminal thrombus", "atrial fibrillation", -10),
            # Warfarin vs DOAC → rec 1 (about DOAC preference)
            ("warfarin instead of doac", "early anticoagulation", -8),
            ("warfarin vs doac", "early anticoagulation", -8),
            ("warfarin instead of a doac", "early anticoagulation", -8),
            # Hemorrhagic transformation → rec 4 (COR 2b)
            ("hemorrhagic transformation", "oral anticoagulant", -8),
            ("hemorrhagic transformation", "argatroban", -8),
            # Factor Xa → rec 1 (COR 2a), about newer anticoag
            ("factor xa", "argatroban", -8),
            ("factor xa", "early anticoagulation", -5),
            # ICA stenosis → rec 2 (COR 2b)
            ("ica stenosis", "atrial fibrillation", -8),
            ("ica stenosis", "early anticoagulation", -8),

            # ── 6.2: glibenclamide → rec 2 (COR 3:NB), not rec 1 (COR 2a) ──
            ("glibenclamide", "osmotic therapy", -10),
            ("glibenclamide", "cerebellar", -5),
            ("glyburide", "osmotic therapy", -10),
            ("iv glibenclamide", "osmotic therapy", -10),

            # ── 6.3: mortality + hemicraniectomy → rec 2 (COR 1 ≤60), not rec 1 (COR 2a) ──
            ("mortality", "high risk for developing", -8),
            ("reducing mortality", "high risk for developing", -8),
            ("death", "high risk for developing", -5),
            ("malignant mca", "high risk for developing", -5),

            # ── 6.5: additional prophylactic/routine EEG contradictions ──
            ("levetiracetam", "unprovoked seizure", -10),
            ("routine prophylaxis", "unprovoked seizure", -12),
            ("routine antiseizure", "unprovoked seizure", -12),
            ("routine eeg monitoring", "unprovoked seizure", -12),
            ("all ais patients", "unprovoked seizure", -10),

            # ── 4.11: stem cell → rec 1 (COR 3:NB) ──
            ("stem cell", "nerinetide", -5),

            # ── 4.6.4: prourokinase vs urokinase (substring fix) ──
            # "prourokinase" contains "urokinase" as substring. When question
            # says "prourokinase", penalize rec 5 (about IV urokinase alone).
            ("prourokinase", "iv urokinase", -12),
            ("mutant prourokinase", "iv urokinase", -12),
            # When question says "urokinase" alone (not "prourokinase"),
            # penalize prourokinase recs
            ("iv urokinase", "mutant prourokinase", -10),

            # ── 4.7.2: moderate pre-existing disability → rec 6 (COR 2b, mRS 3-4) ──
            # NOT M2 rec 7 (COR 2a, mRS 0-1) or rec 5 (COR 2a, mRS 2).
            # "Moderate" disability maps to mRS 3-4, not mRS 0-2.
            ("pre-existing disability", "dominant proximal m2", -10),
            ("pre-existing disability", "mrs score of 0 to 1", -10),
            ("moderate disability", "dominant proximal m2", -10),
            ("moderate disability", "mrs score of 0 to 1", -10),
            ("moderate disability", "mrs score of 2,", -10),
            ("moderate pre-existing", "dominant proximal m2", -10),
            ("moderate pre-existing", "mrs score of 0 to 1", -10),
            ("moderate pre-existing", "mrs score of 2,", -10),
            ("moderate pre-existing disability", "mrs score of 2,", -10),
            ("moderate pre-existing disability", "mrs score of 0 to 1", -10),
            ("disability", "dominant proximal m2", -8),
            ("mrs 3", "dominant proximal m2", -8),
            ("mrs 3", "mrs score of 0 to 1", -10),
            ("mrs 3", "mrs score of 2", -10),
            ("mrs 4", "dominant proximal m2", -8),
            ("mrs 4", "mrs score of 0 to 1", -10),
            ("mrs 4", "mrs score of 2", -10),

            # ── 4.7.3: basilar NIHSS 6-9 (strengthen) ──
            # Already have penalties for "nihss 6 to 9" vs ">=10" but need
            # additional boost for the specific NIHSS 6-9 rec
            ("nihss 6", "nihss score >=10", -12),
            ("low nihss basilar", "nihss score >=10", -10),

            # ── 4.6.1: IVT before CBC/labs (strengthen) ──
            # Rec 10 is about not delaying IVT for labs. Need to overcome rec 5
            # (glucose, COR 1) which matches many generic IVT terms.
            ("started before cbc", "blood glucose", -10),
            ("started before cbc", "hypoglycemia", -10),
            ("started before cbc", "hyperglycemia", -10),
            ("started before cbc", "disabling deficits", -10),
            ("before lab", "blood glucose", -10),
            ("before lab", "hypoglycemia", -10),
            ("before lab", "disabling deficits", -8),
            ("delay for lab", "blood glucose", -10),
            ("delay for lab", "hypoglycemia", -10),
            ("waiting for lab", "blood glucose", -10),
            ("waiting for lab", "hypoglycemia", -10),
            ("waiting for hematologic", "blood glucose", -10),
            ("cbc result", "blood glucose", -10),
            ("cbc result", "hypoglycemia", -10),

            # ── 4.6.1: high CMB burden (strengthen) ──
            # Need rec 13 (>10 CMBs, COR 2b) to beat rec 11 (unknown CMB, COR 1)
            ("high burden of cmb", "unknown burden", -12),
            ("high burden of microbleed", "unknown burden", -12),
            ("high cerebral microbleed burden", "unknown burden", -12),
            (">10 cmb", "unknown burden", -12),
            ("more than 10 cmb", "unknown burden", -10),
            ("more than 10 microbleed", "unknown burden", -10),

            # ── 4.7.5: time window pediatric EVT (within-section) ──
            # "6 to 24 hours" → rec 2 (>=6y extended) or rec 3 (<6y 24h)
            # "<6 years" / "younger than 6" → rec 3, not rec 1
            ("younger than 6", ">=6 years", -10),
            ("under 6 years", ">=6 years", -10),
            ("<6 years", ">=6 years", -10),
            ("2 year old", ">=6 years", -10),
            ("3 year old", ">=6 years", -10),
            ("4 year old", ">=6 years", -10),
            ("5 year old", ">=6 years", -10),

            # ── 4.8: INSPIRES (strengthen) ──
            # INSPIRES → rec 14 (COR 2a). Need stronger penalty on competing recs.
            ("inspires", "aspirin is recommended within 48", -10),
            ("inspires", "aspirin and clopidogrel", -8),
            ("inspires", "tirofiban", -8),
            ("inspires", "ticagrelor", -5),
            ("inspires", "glycoprotein", -8),
            ("inspires", "abciximab", -8),
            ("inspires trial", "aspirin is recommended within 48", -12),

            # ── HT / hemorrhagic transformation → 4.9 rec 4 ──
            # "HT" is an abbreviation. Penalize 4.8 recs.
            ("ht anticoag", "aspirin", -10),
            ("hemorrhagic transformation anticoag", "aspirin", -10),

            # ── 4.6.1: "limited" CMBs → rec 12 (COR 2a), strengthen vs rec 11 ──
            # Rec 11 (unknown burden, COR 1) has advantage from generic IVT terms.
            # "limited" = known burden, not unknown. Penalize rec 11 (unknown) harder.
            ("limited", "unknown burden", -10),
            ("limited burden", "unknown burden", -12),
            ("limited cerebral", "unknown burden", -12),
            # Also penalize rec 11 when "extensive" is mentioned → rec 13
            ("extensive", "unknown burden", -10),
            ("extensive microbleed", "unknown burden", -12),

            # ── 4.6.1: 15-year-old → rec 14 (COR 2b) ──
            # "15-year-old" is pediatric. Penalize glucose rec 5 and generic COR 1 recs.
            ("15-year-old", "blood glucose", -12),
            ("15-year-old", "hypoglycemia", -12),
            ("15-year-old", "hyperglycemia", -12),
            ("15-year-old", "regardless of nihss", -8),
            ("15-year-old", "ischemic change of mild", -8),
            ("15-year-old", "disabling deficits", -8),

            # ── 4.6.1: generic IVT within 4.5h → rec 1/2 (COR 1) ──
            # Rec 8 (non-disabling, COR 3:NB) and rec 12 (CMB, COR 2a) sometimes
            # outscore generic COR 1 recs for generic IVT questions.
            # "still recommended" / "recommended within" = asking about the positive rec.
            ("still recommended", "not recommended", -8),
            ("still recommended", "non-disabling", -10),
            ("still recommended within 4.5", "non-disabling", -12),

            # ── 4.7.2: "proximal MCA" → rec 1 (ICA/M1, COR 1), not M2 rec 7 ──
            # "proximal MCA" means M1 segment, not "proximal M2 division".
            ("proximal mca", "dominant proximal m2", -10),
            ("mca occlusion", "dominant proximal m2", -8),

            # ── 4.7.2: mRS 0-1 + M1 → rec 1 (COR 1), not rec 5/6 (disability) ──
            ("mrs 0-1", "mrs score of 2", -10),
            ("mrs 0-1", "mrs score of 3 to 4", -10),
            ("mrs 0 to 1", "mrs score of 2", -10),
            ("mrs 0 to 1", "mrs score of 3 to 4", -10),
            ("prestroke mrs score of 0", "mrs score of 2", -8),
            ("prestroke mrs score of 0", "mrs score of 3 to 4", -8),

            # ── 4.7.2: mild pre-existing disability → rec 5 (mRS 2, COR 2a) ──
            # "mild" disability = mRS 2, not mRS 3-4 (moderate)
            ("mild pre-existing disability", "mrs score of 3 to 4", -10),
            ("mild disability", "mrs score of 3 to 4", -10),
            ("mild functional impairment", "mrs score of 3 to 4", -10),
            ("prior mild functional", "mrs score of 3 to 4", -10),

            # ── 4.7.2: ASPECTS 0-2 / low ASPECTS → rec 4 (COR 2a) ──
            ("aspects 1", "dominant proximal m2", -10),
            ("aspects 1", "mrs score of 3 to 4", -10),
            ("aspects 0", "dominant proximal m2", -10),
            ("aspects 2", "dominant proximal m2", -10),
            ("low aspects", "dominant proximal m2", -8),

            # ── 4.7.3: basilar NIHSS 6-9 (tiebreaker) ──
            # When tied, the NIHSS 6-9 question should favor rec 2 (COR 2b).
            # Strengthen penalty on rec 1 (>=10) when question specifies low NIHSS.
            ("nihss between 6 and 9", "nihss score >=10", -15),
            ("nihss 7", "nihss score >=10", -12),
            ("nihss 8", "nihss score >=10", -12),
            ("nihss 6 and 9", "nihss score >=10", -12),
            ("nihss is between 6", "nihss score >=10", -15),

            # ── 4.8: "aspirin instead of thrombolysis" → rec 16/17 (COR 3:Harm) ──
            ("instead of thrombolysis", "noncardioembolic", -10),
            ("instead of thrombolysis", "antiplatelet agent", -8),
            ("substitute for", "noncardioembolic", -8),
            ("instead of ivt", "noncardioembolic", -10),

            # ── 4.8: abciximab → rec 4 (COR 3:Harm) ──
            ("abciximab", "noncardioembolic", -10),
            ("abciximab", "antiplatelet agent", -8),
            ("abciximab", "aspirin is recommended", -8),

            # ── 4.8: "noncardioembolic" prevention → rec 5 (COR 1) ──
            ("noncardioembolic", "abciximab", -8),
            ("secondary stroke prevention", "abciximab", -8),
            ("secondary prevention in noncardioembolic", "triple antiplatelet", -10),
            ("secondary prevention in noncardioembolic", "af without", -10),

            # ── 4.8: SOCRATES ticagrelor monotherapy → rec 9 (COR 3:NB) ──
            ("socrates trial", "cyp2c19", -10),
            ("ticagrelor monotherapy", "cyp2c19", -10),

            # ── 4.8: DAPT 21 days minor stroke → rec 12 (COR 1) ──
            # Rec 12 is for NIHSS <=3, rec 15 is for CYP2C19 carriers.
            # Generic "21 days" should go to rec 12 unless CYP2C19 mentioned.
            ("dapt", "cyp2c19", -5),
            ("21 days after minor", "cyp2c19", -8),
            ("clopidogrel and aspirin", "cyp2c19", -5),

            # ── 4.8: "oral antiplatelet adequate for secondary prevention" → rec 5 (COR 1) ──
            # Rec 10 (triple antiplatelet, 3:Harm) shouldn't win for this
            ("adequate for secondary", "triple antiplatelet", -10),
            ("adequate for secondary", "should not be administered", -10),
            ("secondary stroke prevention in noncardioembolic", "triple antiplatelet", -12),

            # ── 6.3: "within 48 hours" + age <=60 → rec 2 (COR 1), not rec 4 (COR 2b) ──
            # Rec 4 is about IVT patients with malignant edema.
            # Rec 2 is about age <=60 with MCA infarction.
            ("under 60", "iv tpa thrombolysis", -10),
            ("<=60", "iv tpa thrombolysis", -10),
            ("patients under 60", "iv tpa thrombolysis", -10),
            ("under 60", "malignant cerebral edema", -8),

            # ── 6.3: age >60 + decompression → rec 3 (COR 2b) ──
            ("older patients", "<=60 years", -10),
            (">60", "<=60 years", -10),
            ("over 60", "<=60 years", -10),

            # ── 6.4: posterior fossa / cerebellar → rec 1/2 (COR 1) ──
            ("posterior fossa", "nondominant", -10),
            ("cerebellar stroke", "nondominant", -10),
            ("cerebellar infarction", "nondominant", -10),

            # ── 4.12: carotid endarterectomy / revascularization ──
            ("carotid revascularization", "antiseizure", -10),
            ("carotid endarterectomy", "antiseizure", -10),
            ("emergency carotid", "antiseizure", -10),

            # ── 4.7.1: IVT withheld for EVT → rec 1 (COR 1) ──
            ("ivt withheld", "antihypertensive", -10),
            ("ivt be withheld", "antihypertensive", -10),

            # ── 5.1: inpatient stroke care → boost correct section ──
            ("inpatient stroke care", "salvageable", -10),
            ("organized inpatient", "salvageable", -10),

            # ── 6.1: goals-of-care → section 6.1 ──
            ("goals-of-care", "decompressive", -8),
            ("goals of care", "decompressive", -8),

            # ── 4.6.1: "within 3 hours" → rec 1 (LOE A), not rec 2 (LOE B-NR) ──
            # QA-2001: "IVT within 3 hours" — rec 1 is the original 3h window (LOE A).
            ("within 3 hours", "4.5 hours of symptom onset", -5),
            ("3 hours of symptom onset", "4.5 hours of symptom onset", -5),
            # QA-2003: "70yo, disabling, 4 hours" — penalize glucose rec (LOE C-LD)
            ("disabling stroke symptoms", "hypoglycemia", -12),
            ("disabling stroke symptoms", "hyperglycemia", -12),
            ("disabling stroke symptoms", "blood glucose", -12),
            ("70-year-old", "hypoglycemia", -10),
            ("70-year-old", "hyperglycemia", -10),
            # QA-2040: "woke up with stroke symptoms 2 hours ago" → rec 1 (LOE A)
            # Rec 6 (glucose, C-LD) wins on text overlap; penalize when no glucose context.
            ("woke up with stroke", "hypoglycemia", -12),
            ("woke up with stroke", "hyperglycemia", -12),
            ("woke up with stroke", "normoglycemia", -10),
            # QA-2461: "unknown time of onset, last seen well 3h" → rec 1 (LOE A)
            # Rec 11 (CMB, B-NR) falsely matches because "unknown" in rec 11 = CMBs.
            ("unknown time of onset", "cerebral microbleeds", -12),
            ("unknown time of onset", "cmbs", -12),
            ("unknown time of onset", "burden of cerebral", -12),
            ("last seen well", "cerebral microbleeds", -10),
            ("last seen well", "cmbs", -10),
            # QA-2014: "lowering BP prior to thrombolysis" → 4.3 rec 5 (LOE B-NR)
            # Penalize rec 6 (EVT BP, COR 2a) when question is about pre-IVT BP.
            ("prior to thrombolysis", "evt is planned", -10),
            ("prior to thrombolysis", "not received ivt", -10),
            ("lowering bp", "evt is planned", -8),
            # QA-2009: "mixing alteplase during CT" → rec 3 (B-NR), not rec 7 (A)
            # Rec 7 is about early ischemic changes on imaging; penalize for "mixing".
            ("mixing alteplase", "early ischemic change", -12),
            ("mixing alteplase", "mild to moderate extent", -10),
            ("mixing alteplase", "frank hypodensity", -10),
            # QA-2025/2027: aspirin+clopidogrel+IVT → 4.6.1 rec 9, not 4.6.2 rec 1
            ("taking aspirin", "tenecteplase", -10),
            ("currently taking", "tenecteplase", -8),
            ("on single antiplatelet", "tenecteplase", -10),
            # QA-2048: "IVT preparation before imaging" → 4.6.1, not 3.2
            ("preparation begin before imaging", "emergent brain imaging", -8),
            ("ivt preparation", "emergent brain imaging", -8),
            # QA-2469: "aspirin monotherapy inferior to DAPT" → rec 12 (LOE A), not rec 6
            ("dapt", "selection of an antiplatelet", -8),
            ("dual antiplatelet", "selection of an antiplatelet", -8),
            ("aspirin monotherapy", "selection of an antiplatelet", -8),
            ("inferior to dapt", "selection of an antiplatelet", -10),
            # QA-2308: "anticoag better than antiplatelet for dissection" → 4.9 rec 2
            ("better than antiplatelet", "carotid or vertebral", -5),
            # QA-2398/2399: cerebellar decompression → penalize 6.1 monitoring recs
            ("posterior fossa decompression", "close monitoring", -10),
            ("cerebellar infarction", "close monitoring", -5),
            ("surgical intervention for cerebellar", "close monitoring", -10),
            # QA-2398: "decompression" within 6.4 → rec 2 (COR 1, LOE B-NR)
            # Rec 2 is about decompressive craniectomy. Rec 1 is about ventriculostomy.
            ("decompression", "obstructive hydrocephalus", -5),
            ("decompression", "ventriculostomy", -5),
            # QA-2326: "therapeutic hypothermia as neuroprotective" → 4.11, not 4.4
            ("neuroprotective", "normothermia", -10),
            ("neuroprotective strategy", "normothermia", -10),
            # QA-2345/2470: "comprehensive stroke center" → 5.1, not 2.4/2.6
            ("stroke center", "ems professionals", -8),
            ("comprehensive stroke center", "ems professionals", -10),
            ("stroke center care for all", "ems professionals", -10),
            # QA-2365/2474: "psychotherapy/acupuncture for poststroke depression" → 5.5 rec 2
            ("psychotherapy", "structured depression inventory", -12),
            ("acupuncture", "structured depression inventory", -12),
            ("treatment modality", "structured depression inventory", -12),
            ("psychotherapy", "administration of a structured", -12),
            ("acupuncture", "administration of a structured", -12),

            # ── 4.6.1: nicardipine/labetalol pre-IVT BP → rec 4/5 (COR 1) ──
            # QA-2015: "Is nicardipine infusion appropriate for pre-IVT BP management?"
            # Penalize 4.3 rec 10 (about post-EVT recanalization BP, COR 3:Harm).
            ("nicardipine", "successfully recanalized", -12),
            ("nicardipine", "recanalization", -10),
            ("labetalol", "successfully recanalized", -12),
            ("pre-ivt", "successfully recanalized", -12),
            ("pre-ivt", "recanalization", -10),
            ("blood pressure management", "successfully recanalized", -10),
            # Also penalize 2.3 rec 4 (ambulance BP, COR 3:NB) for pre-IVT context
            ("pre-ivt", "ambulance", -10),
            ("nicardipine", "ambulance", -10),

            # ── 4.6.1: "door-to-needle time" → rec 3 (COR 1), not rec 8 (3:NB) ──
            # QA-2006: generic IVT timing/speed questions should favor COR 1 recs.
            ("door-to-needle", "non-disabling", -12),
            ("door-to-needle", "mild non-disabling", -12),
            ("door to needle", "non-disabling", -12),
            ("minimize", "non-disabling", -8),
            ("door-to-needle", "small number of cerebral", -10),
            ("door-to-needle", "unknown burden", -10),

            # ── 4.6.1: "prepare IVT during workup" → rec 3 (COR 1), not rec 10 (COR 2a) ──
            # QA-2008: "Should hospitals prepare IVT while completing diagnostic workup?"
            # Rec 3 says "be prepared to administer IVT" (COR 1).
            # Rec 10 says "not be delayed for lab results" (COR 2a) — more specific.
            # When question says "prepare" / "preparation", boost rec 3 and penalize rec 10.
            ("prepare ivt", "not be delayed", -8),
            ("preparation", "not be delayed", -8),
            ("prepare ivt", "hematologic", -8),
            ("preparing", "not be delayed", -8),

            # ── 4.6.1: "IVT window" generic → rec 1/2 (COR 1), not rec 12 (COR 2a) ──
            # QA-2039: "What is the window for IVT administration in eligible patients?"
            # Rec 12 (small number CMBs, COR 2a) matches "within 4.5 hours" plus many terms.
            # But a generic "IVT window" question targets the core COR 1 rec, not CMBs.
            ("window for ivt", "small number", -12),
            ("window for ivt", "cmbs", -12),
            ("window for ivt", "unknown burden", -12),
            ("window for ivt", "non-disabling", -12),
            ("window for ivt", "blood glucose", -12),
            ("window for ivt", "hypoglycemia", -12),
            ("window for ivt", "pediatric patients", -12),
            ("window for ivt", "taking an anticoagulant", -10),
            ("window for ivt", "not be delayed", -10),
            ("window for ivt", "ischemic change of mild", -10),
            ("ivt administration in eligible", "small number", -12),
            ("ivt administration in eligible", "cmbs", -12),
            ("ivt administration in eligible", "non-disabling", -12),
            ("ivt administration in eligible", "unknown burden", -12),
            ("ivt administration in eligible", "blood glucose", -12),
            ("ivt administration in eligible", "hypoglycemia", -12),

            # ── 4.6.3: "IVT at 20 hours" → rec 3 (COR 2b, 4.5-24h LVO), not 4.8 ──
            # QA-2082: "Is IVT at 20 hours from onset with large penumbra COR 2b?"
            # Need to penalize 4.8 rec 14 which matches "noncardioembolic" + time terms.
            ("20 hours", "noncardioembolic", -10),
            ("20 hours", "antiplatelet", -10),
            ("20 hours from onset", "noncardioembolic", -12),

            # ── 4.6.4: "prourokinase evidence" → rec 2 (COR 2b), not rec 4 (3:NB combo) ──
            # QA-2092: "What is the evidence level for prourokinase in acute stroke?"
            # Rec 4 (combo) has more text hits than rec 2 (standalone).
            # Penalize rec 4 (combo) when no "combination" in question.
            ("prourokinase in acute", "in conjunction", -10),
            ("evidence for prourokinase", "in conjunction", -10),
            ("prourokinase in acute", "low-dose alteplase", -10),
            ("evidence for prourokinase", "low-dose alteplase", -10),

            # ── 4.6.4: "strongest against thrombolytic" → rec 6 (3:Harm), not rec 8 ──
            # QA-2101/2107: meta-questions about COR 3:Harm.
            # "strongest recommendation against" = 3:Harm (streptokinase).
            ("strongest recommendation against", "non-disabling", -10),
            ("strongest against", "non-disabling", -10),
            ("cor 3:harm", "non-disabling", -10),
            ("cor 3:harm", "is not beneficial", -8),
            ("cor 3:harm", "is not recommended", -5),
            ("thrombolytic agent that", "non-disabling", -10),
            ("rates as cor 3:harm", "non-disabling", -10),

            # ── 4.7.2: "M2 division" generic → rec 7 (dominant, COR 2a) ──
            # QA-2161: "Can EVT be considered for M2 division MCA occlusions?"
            # Rec 8 (nondominant, COR 3:NB) wins because "M2 division" matches both.
            # For generic "M2" questions without specifying nondominant, default to dominant.
            ("m2 division", "nondominant", -8),
            ("m2 occlusion", "nondominant", -8),
            ("m2 mca", "nondominant", -6),

            # ── 4.8: "early antiplatelet within 24h of IVT" → rec 2 (COR 2b) ──
            # QA-2240: "What COR applies to early antiplatelet use within 24 hours of thrombolysis?"
            # Rec 12 (DAPT minor stroke, COR 1) wins because it matches many terms.
            # Rec 2 is specifically about antiplatelet risk after IVT.
            ("antiplatelet within 24 hours of thrombolysis", "noncardioembolic", -10),
            ("antiplatelet within 24 hours of ivt", "noncardioembolic", -10),
            ("antiplatelet after ivt", "noncardioembolic", -10),
            ("antiplatelet after thrombolysis", "noncardioembolic", -10),
            ("early antiplatelet after ivt", "noncardioembolic", -10),
            ("early antiplatelet use within 24 hours", "noncardioembolic", -10),
            ("after thrombolysis", "noncardioembolic", -8),
            ("after ivt", "noncardioembolic", -8),

            # ── 4.8: "changing antiplatelet agent" → rec 8 (COR 2b), not rec 6 (COR 1) ──
            # QA-2270: "What evidence supports changing the antiplatelet agent after AIS?"
            # Rec 6 (selection of agent, COR 1) matches too broadly.
            # Rec 8 is specifically about changing/increasing dose.
            ("changing the antiplatelet", "selection of an antiplatelet", -8),
            ("changing antiplatelet", "selection of an antiplatelet", -8),
            ("changing agent", "selection of an antiplatelet", -8),
            ("switching antiplatelet", "selection of an antiplatelet", -8),

            # ── 4.8: "POINT trial DAPT" → rec 12 (COR 1), not rec 14 (COR 2a) ──
            # QA-2272: "What is the POINT trial's contribution to DAPT recommendations?"
            # POINT = aspirin+clopidogrel for 21 days in minor stroke → rec 12 (COR 1).
            # Rec 14 is about INSPIRES (atherosclerotic cause, NIHSS <=5).
            ("point trial", "nihss score <=5", -8),
            ("point trial", "atherosclerotic", -8),
            ("point trial", ">=50% stenosis", -8),
            ("point trial", "inspires", -8),

            # ── 4.9: "any COR 1 in section 4.9" → rec 1 (COR 2a), not rec 4 (COR 2b) ──
            # QA-2296: "Per 2026, is there any COR 1 in section 4.9?"
            # This asks about the highest COR in 4.9. Rec 1 (COR 2a) is the highest.
            # But rec 4 (COR 2b) wins because "HT" matches more terms.
            # No COR 1 exists in 4.9, so the answer is COR 2a (highest available).
            ("cor 1 recommendation in section 4.9", "experience ht", -10),
            ("cor 1 in section 4.9", "experience ht", -10),
            ("cor 1 recommendation in section 4.9", "argatroban", -10),
            ("cor 1 in section 4.9", "argatroban", -10),
            ("cor 1 recommendation in section 4.9", "does not reduce", -10),
            ("cor 1 in section 4.9", "does not reduce", -10),

            # ── 4.6.1: "IVT before CBC" → rec 10 (COR 2a), not rec 5 (COR 1) ──
            # QA-2462: "Can IVT be started before obtaining a complete blood count?"
            # Rec 5 (COR 1 about treating glucose) matches "ischemic stroke" terms.
            # Rec 10 is about not delaying for hematologic results.
            ("before obtaining a complete blood", "blood glucose", -12),
            ("before obtaining a complete blood", "hypoglycemia", -12),
            ("before a complete blood", "blood glucose", -12),
            ("complete blood count", "blood glucose", -12),
            ("complete blood count", "hypoglycemia", -12),
            ("complete blood count", "disabling deficits", -10),
            ("complete blood count", "regardless of nihss", -10),
            # ── 4.6.1: "disabling" questions → penalize rec 8 (non-disabling) ──
            # Use specific prefixes ("for disabling", "treating disabling") to avoid
            # matching "non-disabling" questions where "disabling" is a substring.
            ("for disabling", "non-disabling", -15),
            ("ivt for disabling", "non-disabling", -15),
            ("treating disabling", "non-disabling", -15),
            ("disabling ais", "non-disabling", -15),
            ("disabling acute", "non-disabling", -12),
            ("disabling left", "non-disabling", -12),
            ("disabling weakness", "non-disabling", -12),
            ("stroke is disabling", "non-disabling", -15),
            ("presents with disabling", "non-disabling", -15),
            # ── 4.6.1: Known CMB burden → penalize rec 11 (unknown burden) ──
            # Rec 11 is for when CMB status is unknown. When question specifies
            # a count or burden level, rec 11 is the wrong recommendation.
            # Strong penalties (-20) needed to overcome rec 11's generic keyword advantage.
            ("few microbleed", "unknown burden", -20),
            ("few cmb", "unknown burden", -20),
            ("few cerebral microbleed", "unknown burden", -20),
            ("small number of cmb", "unknown burden", -15),
            ("low microbleed", "unknown burden", -20),
            ("low burden", "unknown burden", -15),
            ("3 cerebral microbleed", "unknown burden", -20),
            ("3 microbleed", "unknown burden", -20),
            ("numerous microbleed", "unknown burden", -20),
            ("numerous cerebral microbleed", "unknown burden", -20),
            ("numerous cmb", "unknown burden", -20),
            ("high burden", "unknown burden", -20),
            ("high microbleed", "unknown burden", -15),
            (">10", "unknown burden", -15),
            ("more than 10", "unknown burden", -15),
            ("more than 20", "unknown burden", -20),
            ("significant comorbid cmb", "unknown burden", -15),
            ("significant microbleed", "unknown burden", -15),
            ("high count", "unknown burden", -15),
            ("comorbid cmb", "unknown burden", -15),
            ("1-10", "unknown burden", -15),
            # Also penalize rec 11 when MRI was already obtained
            # (rec 11 says "without first obtaining MRI")
            ("mri shows", "without first obtaining mri", -15),
            ("on mri", "without first obtaining mri", -15),
            ("mri reveals", "without first obtaining mri", -15),
            ("demonstrated on mri", "without first obtaining mri", -12),
            # Knowing the CMB count implies MRI was done → rec 11 wrong
            ("numerous cerebral microbleed", "without first obtaining mri", -12),
            ("few cerebral microbleed", "without first obtaining mri", -12),
            ("3 cerebral microbleed", "without first obtaining mri", -12),
            ("more than 20 cerebral microbleed", "without first obtaining mri", -12),
            ("high burden of cmb", "without first obtaining mri", -10),
            ("low microbleed burden", "without first obtaining mri", -10),
            ("significant comorbid cmb", "without first obtaining mri", -10),
            # ── 4.6.1: coagulation/lab → penalize rec 11 (about CMBs) ──
            ("coagulation test", "unknown burden", -10),
            ("coagulation test", "microbleed", -10),
            ("lab results", "microbleed", -10),
            ("waiting for coagulation", "microbleed", -10),
            ("without waiting for coagulation", "microbleed", -10),
            # ── 4.6.1: time window → penalize rec 6 (glucose) ──
            # Rec 6 contains "disabling stroke persist" which matches broadly.
            # Penalize when question is about time window, not glucose.
            ("3-to-4.5-hour", "hypoglycemia", -12),
            ("3-to-4.5-hour", "hyperglycemia", -12),
            ("3-4.5h", "hypoglycemia", -12),
            ("first three hours", "hypoglycemia", -10),
            ("within the first three", "hypoglycemia", -10),
            ("hour window", "hypoglycemia", -8),
            ("hour window for disabling", "hypoglycemia", -10),
            # ── 4.6.1: antiplatelet → penalize rec 6 (glucose) ──
            ("aspirin and clopidogrel", "hypoglycemia", -10),
            ("aspirin and clopidogrel", "hyperglycemia", -10),
            ("aspirin monotherapy", "hypoglycemia", -10),
            ("antiplatelet use", "hypoglycemia", -10),
            # ── 4.6.1: glucose *correction* → penalize rec 5 (about determining levels, not correction) ──
            ("glucose correction", "determine blood glucose levels", -12),
            ("correcting blood glucose", "determine blood glucose levels", -12),
            ("correcting hypoglycemia", "determine blood glucose levels", -12),
            ("glucose of 45", "determine blood glucose levels", -10),
            # ── 4.6.1: early ischemic changes → penalize rec 11 (CMBs) ──
            ("early signs of ischemia", "unknown burden", -10),
            ("early ischemic change", "unknown burden", -10),
            ("ischemic change", "unknown burden", -10),
            # ── 4.6.1: antiplatelet → penalize rec 8 (non-disabling) ──
            ("antiplatelet use", "non-disabling", -10),
            ("concurrent antiplatelet", "non-disabling", -10),
            ("aspirin monotherapy", "non-disabling", -10),
            # ── 4.6.1: children → penalize non-pediatric recs ──
            ("children with acute ischemic", "disabling deficits, regardless", -10),
            ("treatment for children", "disabling deficits, regardless", -10),
            ("children with acute ischemic", "non-disabling", -10),
            # ── 4.6.1: DAPT/antiplatelet + disabling → penalize rec 1 ──
            # When question mentions both DAPT and disabling, rec 9 (antiplatelet)
            # should win over rec 1 (disabling deficits).
            ("on dapt", "disabling deficits, regardless", -8),
            ("dapt who present", "disabling deficits, regardless", -8),
            ("patients on dapt", "disabling deficits, regardless", -8),
            # ── 4.7.2: pediatric/infant/toddler → penalize adult EVT recs ──
            ("infants", "anterior circulation proximal lvo", -10),
            ("toddlers", "anterior circulation proximal lvo", -10),
            ("infant", "anterior circulation proximal lvo", -10),
            ("toddler", "anterior circulation proximal lvo", -10),
            # ── 4.7.5: pediatric age sub-groups ──
            ("infants", ">=6 years", -10),
            ("toddlers", ">=6 years", -10),
            ("neonates and infants", ">=6 years", -10),
            # ── 4.8: ticagrelor monotherapy → penalize DAPT recs ──
            ("ticagrelor monotherapy", "aspirin and ticagrelor", -12),
            ("ticagrelor monotherapy superior", "aspirin and ticagrelor", -12),
            ("monotherapy superior to aspirin", "aspirin and ticagrelor", -12),
            ("monotherapy superior to aspirin", "aspirin and clopidogrel", -10),
            # ── 4.8: aspirin replacement → penalize non-substitute recs ──
            ("replacement for ivt", "noncardioembolic", -10),
            ("replacement for evt", "noncardioembolic", -10),
            ("replacement for ivt/evt", "noncardioembolic", -12),
            ("replacement for ivt", "minor stroke", -8),
            ("replacement for evt", "minor stroke", -8),
            # ── 4.8: post-IVT antiplatelet → penalize rec 8 (non-disabling) ──
            ("had ivt", "non-disabling", -10),
            ("ivt 6 hours ago", "non-disabling", -10),
            ("after ivt", "non-disabling", -8),
            # ── 4.10: hemodilution/hemodynamic → penalize EMS/generic recs ──
            ("hemodilution", "educational program", -10),
            ("hemodilution", "emergency medical services", -10),
            ("hemodynamic therapies", "emergency medical services", -10),
            ("hemodynamic therapies", "educational program", -10),
            ("induced hypertension", "nutritional screening", -10),
            ("induced hypertension", "nutritional", -8),
            ("induced hypertension", "emergency medical services", -10),
            # ── 4.12: carotid urgently → penalize non-carotid recs ──
            ("carotid intervention urgently", "blood pressure", -8),
            # ── 5.2: bedside screening → penalize endoscopic ──
            ("must bedside dysphagia screening", "endoscopic examination", -10),
            ("before a stroke patient eats", "endoscopic examination", -10),
            ("before eating", "endoscopic examination", -10),
            ("eat breakfast", "regional systems", -10),
            ("wants to eat", "ems", -10),
            ("eat breakfast", "emergency medical services", -10),
            # ── 5.2: PES → penalize endoscopic ──
            ("pes for reducing", "endoscopic examination", -10),
            ("pes for reducing", "bedside swallow screening prior", -8),
            # ── 5.3: enteral feeding timing → penalize nasogastric rec ──
            ("enteral feeding within 7 days", "nasogastric tubes", -8),
            ("what cor does enteral feeding", "nasogastric", -8),
            ("when should enteral nutrition start", "nasogastric tubes", -8),
            # ── 5.4: LMWH vs UFH comparison → penalize "either" rec ──
            ("lmwh superior to ufh", "either prophylactic-dose", -8),
            ("lmwh clearly superior", "either prophylactic-dose", -10),
            # ── 5.4: UFH over nothing → penalize LMWH-vs-UFH comparison rec ──
            ("over no prophylactic heparin", "lmwh over prophylactic-dose ufh", -10),
            ("ufh over no prophylactic", "lmwh over prophylactic-dose ufh", -10),
            # ── 5.5: treatment vs screening for depression ──
            ("treatment of post-stroke depression", "depression inventory", -8),
            ("treatment of post-stroke depression", "screen for poststroke", -8),
            ("treatment of psd", "screen for poststroke", -8),
            # ── 5.7: mobilization → penalize non-rehab recs ──
            ("aggressively mobilized", "salvageable ischemic penumbra", -10),
            ("mobilized 12 hours", "lvo", -10),
            ("aggressively mobilized", "lvo", -10),
            # ── 5.7: fluoxetine → penalize non-rehab recs ──
            ("fluoxetine", "basilar artery", -10),
            ("fluoxetine", "thrombectomy", -10),
            ("fluoxetine", "thrombolysis", -10),
            # ── 6.2: steroids → penalize non-edema recs ──
            ("steroids are ordered", "increased risk for herniation", -8),
            ("steroids for brain swelling", "increased risk for herniation", -8),
            # ── 6.3: age-based craniectomy → penalize post-tPA rec (rec 4) ──
            ("60 or younger", "received iv tpa thrombolysis", -12),
            ("patients 60 or younger", "received iv tpa thrombolysis", -12),
            ("60 or younger", "received iv tpa", -12),
            ("55-year-old", "received iv tpa thrombolysis", -12),
            ("55-year-old", "received iv tpa", -12),
            ("68-year-old", "received iv tpa thrombolysis", -12),
            ("68-year-old", "received iv tpa", -12),
            ("68-year-old", "<=60 years", -10),
            # ── 6.3: age → penalize rec 1 (trigger/high-risk) for age-specific qs ──
            ("60 or younger", "high risk for developing brain swelling", -10),
            ("patients 60 or younger", "high risk for developing brain swelling", -10),
            # ── 6.5: treatment vs prophylaxis ──
            ("unprovoked post-stroke seizures be treated", "prophylactic treatment", -12),
            ("should unprovoked", "prophylactic treatment with antiseizure", -10),
            # ── 6.5: prophylaxis → penalize treatment rec ──
            ("routine seizure prophylaxis", "unprovoked seizure after ais", -12),
            ("prophylactic levetiracetam", "unprovoked seizure after ais", -12),
            ("prophylactic levetiracetam", "hypothermia", -10),
            ("prophylactic levetiracetam", "normothermia", -10),
            # ── 4.6.2 R5: "0.25 or 0.4" dose question → penalize rec 2 (3:NB about 0.4) ──
            # "Should clinicians use 0.25 or 0.4 mg/kg?" → rec 1 (COR 1) is the answer
            ("0.25 or 0.4", "0.4 mg/kg", -8),
            ("use 0.25 or 0.4", "0.4 mg/kg", -10),
            ("should clinicians use 0.25 or 0.4", "0.4 mg/kg", -12),
            # ── 4.6.3 R5: 4.5-9 hours → penalize 4.5-24h rec (rec 3) ──
            ("4.5-9 hours", "4.5 to 24 hours", -8),
            ("4.5 to 9 hours", "4.5 to 24 hours", -8),
            # ── 4.6.3 R5: very late/4.5-24h → penalize rec 2 (automated penumbral) ──
            ("very late window", "unknown time of onset", -8),
            ("4.5-24h", "unknown time of onset", -8),
            ("4.5 to 24", "unknown time of onset", -8),
            # ── 4.6.3 R5: extended window → penalize 4.6.1 recs (standard window) ──
            ("extended-window ivt", "within 4.5 hours of last known well and eligible for ivt", -10),
            ("extended-window ivt", "hematologic or coagulation", -10),
            ("extended-window ivt", "unknown burden of cerebral microbleeds", -10),
            # ── 4.6.4 R5: reteplase → penalize non-4.6.4 recs ──
            ("reteplase", "substitute for acute stroke treatment", -8),
            ("reteplase", "otherwise eligible for ivt or mechanical", -8),
            # ── 4.6.4 R5: "besides alteplase and tenecteplase" → penalize 4.6.2 recs ──
            ("besides alteplase and tenecteplase", "tenecteplase", -15),
            ("besides alteplase and tenecteplase", "mutant prourokinase", -10),
            ("besides alteplase", "alteplase", -5),
            ("alternative thrombolytic besides", "tenecteplase", -12),
            # Specifically penalize rec 4 (mutant prourokinase 3:NB) when "besides" used
            ("besides alteplase and tenecteplase at cor 1", "mutant prourokinase", -8),
            # ── 4.7.1 R5: "giving IVT to patients who will also receive EVT" ──
            ("also receive evt", "salvageable ischemic penumbra", -10),
            ("also receive evt", "unknown time of onset", -8),
            ("giving ivt to patients who will also receive", "lvo with salvageable", -10),
            # ── 4.7.2 R5: ASPECTS in 0-6h → penalize 3.2 imaging recs ──
            ("aspects play in determining evt", "awaken from symptoms", -10),
            ("aspects in the 0-6h", "awaken from symptoms", -10),
            ("aspects in the 0-6h window", "awaken from symptoms", -10),
            ("aspects play in determining", "awaken from symptoms or have unknown", -10),
            # ── 4.7.2 R5: "posterior outside basilar" → boost rec 8 (3:NB) ──
            ("outside the basilar", "nondominant or codominant", -5),
            ("posterior circulation strokes outside the basilar", "basilar artery occlusion, a baseline", -12),
            # ── 4.7.2 R5: moderate disability → boost rec 6 (mRS 3-4, COR 2b) over rec 5 (mRS 2) ──
            ("moderate pre-existing disability", "mrs score of 2", -8),
            ("moderate pre-stroke disability", "mrs score of 2", -8),
            ("moderate disability", "mrs score of 2", -5),
            # ── 4.7.2 R5: generic disability question → penalize rec 6 (3-4) vs rec 5 (2) ──
            # When asking generically about disability and EVT, rec 5 (less severe, 2a)
            # should be first because it's the more inclusive recommendation.
            ("pre-existing disability affect", "mrs score of 3 to 4", -8),
            ("disability affect evt", "mrs score of 3 to 4", -5),
            # ── 4.7.2 R5: ASPECTS cutoff → boost rec 4 (low ASPECTS, COR 2a) ──
            ("aspects cutoff", "aspects 0 to 2", 5),
            # ── 4.7.5 R5: pediatric ages → penalize adult EVT recs (4.7.2) ──
            ("3-year-old", "anterior circulation proximal lvo of the ica", -10),
            ("3 year old", "anterior circulation proximal lvo of the ica", -10),
            # 3-year-old is <6 years → penalize >=6 recs (rec 1/2)
            ("3-year-old", ">=6 years", -15),
            ("3 year old", ">=6 years", -15),
            ("a 3-year-old", ">=6 years", -15),
            ("a 2-year-old", ">=6 years", -15),
            ("a 1-year-old", ">=6 years", -15),
            ("a 4-year-old", ">=6 years", -15),
            ("a 5-year-old", ">=6 years", -15),
            ("neonates with large vessel", "anterior circulation proximal lvo of the ica", -10),
            ("neonates with large vessel", "ica or m1", -8),
            ("minimum age", "anterior circulation proximal lvo", -8),
            # ── 4.8 R5: early antiplatelet within 24h of IVT → penalize minor stroke rec ──
            ("early antiplatelet therapy within 24 hours of ivt", "noncardioembolic", -10),
            ("early antiplatelet within 24 hours of ivt", "noncardioembolic", -10),
            ("early antiplatelet therapy within 24", "noncardioembolic", -8),
            ("24 hours of ivt", "noncardioembolic", -5),
            # ── 4.8 R5: tirofiban → penalize non-tirofiban recs ──
            ("tirofiban", "noncardioembolic ais", -8),
            ("tirofiban", "otherwise eligible for ivt or mechanical", -5),
            # ── 6.3 R5: 68-year-old → penalize rec 4 (post-tPA) more when no tPA ──
            ("malignant edema", "received iv tpa", -5),
        ]
        for q_term, rec_neg, penalty in _CONTRADICTION_PAIRS:
            if q_term in q_lower_for_disc and rec_neg in text_lower:
                score += penalty

        # ── Synonym expansion for age thresholds ────────────────────
        # Map natural-language age expressions to their numeric equivalents
        # so they match the symbols in rec text (e.g., ">60", "<=60").
        _AGE_SYNONYMS = [
            # (question phrase, rec phrase to match, bonus)
            ("over 60", ">60", 8),
            ("older than 60", ">60", 8),
            ("above 60", ">60", 8),
            ("under 60", "<=60", 8),
            ("younger than 60", "<=60", 8),
            ("60 or younger", "<=60", 8),
            ("60 years or younger", "<=60", 8),
            ("over 80", ">80", 8),
            ("under 80", "<80", 8),
            ("younger than 80", "<80", 8),
            # Nondisabling/mild stroke synonyms → map to rec text phrasing
            ("no functional impairment", "non-disabling", 10),
            ("nihss 2", "non-disabling", 10),
            ("minor stroke", "non-disabling", 8),
            ("not disabling", "non-disabling", 8),
            ("minor stroke that is not disabling", "non-disabling", 10),
            # 4.9: DOAC/AF question → boost rec with "atrial fibrillation" (COR 2a)
            # and penalize rec with "early anticoagulation" generic text (COR 3:NB)
            ("doac", "atrial fibrillation", 10),
            ("doac", "oral anticoagul", 8),
            ("af ", "oral anticoagul", 8),
            ("doac", "milder severity", 8),
            ("af and minor", "milder severity", 8),
            ("af minor stroke", "milder severity", 8),
            # 4.9: warfarin vs DOAC → boost rec 1 (DOAC preference)
            ("warfarin instead", "oral anticoagulant", 8),
            ("warfarin vs doac", "oral anticoagulant", 8),
            ("warfarin or doac", "oral anticoagulant", 8),
            # 4.9: LMWH/heparin → boost rec 6 (COR 3:NB about early anticoag)
            ("lmwh", "early anticoagulation", 10),
            ("lmwh", "does not reduce", 8),
            ("reduces death", "early anticoagulation", 8),
            ("reduces death", "does not reduce", 10),
            # 4.9: dissection + anticoag-vs-antiplatelet → boost rec 2 (B-NR)
            # QA-2308: "Is anticoagulation for AIS with carotid dissection better
            # than antiplatelet?" — rec 2 about ICA stenosis benefit uncertain.
            ("dissection", "high-grade ica stenosis", 10),
            ("carotid dissection", "high-grade ica stenosis", 12),
            ("better than antiplatelet", "benefit of urgent anticoagulation", 12),
            ("dissection", "benefit of urgent", 8),
            # Penalize rec 3 (intraluminal thrombus) when comparing treatments
            ("better than antiplatelet", "intraluminal thrombus", -10),
            ("better than antiplatelet", "nonocclusive", -8),
            # 4.9: hemorrhagic transformation → boost rec 4
            ("hemorrhagic transformation", "experience ht", 10),
            # 4.7.5: >=6 years → boost rec 1/2, <6 years → boost rec 3
            ("6 years or older", ">=6 years", 10),
            ("aged 6 or older", ">=6 years", 10),
            ("6+", ">=6 years", 10),
            ("6+ years", ">=6 years", 10),
            ("over 6 years", ">=6 years", 10),
            ("above 6 years", ">=6 years", 10),
            ("6 to 24 hours", "6 to 24 hours", 5),
            ("neonates", "28 days to 6 years", 8),
            ("neonatal", "28 days to 6 years", 8),
            ("under 28 days", "28 days to 6 years", 8),
            ("under 28 days", "28 days", 8),
            # 4.6.2: 0.4 mg/kg (higher dose TNK) → boost rec 2 (COR 3:NB)
            ("0.4 mg", "0.4 mg", 10),
            ("0.4mg", "0.4 mg", 10),
            ("higher dose", "0.4 mg", 8),
            # 4.6.5: SCD → boost SCD rec (COR 2a); CRAO → boost CRAO rec (COR 2b)
            ("sickle cell", "sickle cell", 10),
            ("scd", "sickle cell", 10),
            ("crao", "retinal artery", 10),
            ("retinal artery", "retinal artery", 10),
            ("ophthalmic", "retinal artery", 8),
            ("visual loss", "visual loss", 8),
            ("visual loss", "retinal artery", 8),
            # 4.8: ticagrelor/SOCRATES → boost rec 9 (COR 3:NB, clopidogrel not over aspirin)
            # The SOCRATES finding maps to this rec about single agent not beating aspirin
            ("ticagrelor over aspirin", "not recommended over aspirin", 10),
            ("ticagrelor monotherapy", "not recommended over aspirin", 10),
            ("socrates", "not recommended over aspirin", 8),
            # 4.8: THALES → boost rec 13 (COR 2b)
            ("thales", "ticagrelor", 8),
            ("thales", "24 hours", 5),
            # 4.8: INSPIRES → boost rec 14 (COR 2a)
            ("inspires", "cyp2c19", 8),
            # 4.8: CHANCE-2 → boost rec 15 (COR 2b)
            ("chance-2", "cyp2c19", 8),
            ("cyp2c19", "cyp2c19", 5),
            # 4.8: antiplatelet + AF → boost rec 11 (COR 3:Harm)
            ("af and stroke", "af without active", 10),
            ("af and stroke", "af ", 8),
            # 6.2: glibenclamide → boost rec 2 (COR 3:NB)
            ("glibenclamide", "glibenclamide", 10),
            ("glyburide", "glibenclamide", 10),
            # 6.3: mortality/death + MCA → boost rec 2 (COR 1, <=60)
            ("mortality", "<=60 years", 8),
            ("reducing mortality", "<=60 years", 10),
            ("mortality", "deteriorate neurologically", 8),
            ("malignant mca", "<=60 years", 8),
            ("malignant mca infarction", "mca infarction", 8),
            # 6.5: prophylactic → boost rec 2 (COR 3:NB)
            ("prophylactically", "prophylactic", 10),
            ("routine antiseizure", "prophylactic", 10),
            ("routine eeg monitoring", "prophylactic", 8),
            ("levetiracetam", "prophylactic", 8),
            ("all ais patients", "prophylactic", 8),
            # 4.11: stem cell → boost rec 1 (COR 3:NB)
            ("stem cell", "neuroprotective", 8),
            # 4.11: "therapeutic hypothermia as neuroprotection" → rec 1 (LOE A)
            ("neuroprotective strategy", "neuroprotective", 10),
            ("neuroprotective", "pharmacological or nonpharmacological", 8),
            # 5.1: "comprehensive stroke center" → boost 5.1 rec 1 (LOE B-R)
            ("comprehensive stroke center", "organized inpatient", 10),
            ("stroke center care", "organized inpatient", 10),
            ("comprehensive stroke", "organized inpatient", 8),
            # 5.5: "psychotherapy/acupuncture for depression" → boost rec 2 (LOE B-R)
            ("psychotherapy", "antidepressants and/or nonpharmac", 10),
            ("acupuncture", "antidepressants and/or nonpharmac", 10),
            ("treatment modality", "antidepressants and/or nonpharmac", 8),
            # 4.6.1: lab/platelet before IVT → boost rec 10
            ("before platelet", "not be delayed", 10),
            ("before cbc", "not be delayed", 10),
            ("before obtaining", "not be delayed", 10),
            ("platelet count", "not be delayed", 8),
            ("unknown inr", "not be delayed", 10),
            ("warfarin with unknown", "not be delayed", 10),
            # 4.6.4: prourokinase standalone → boost recs 1-2 (COR 2b)
            ("prourokinase", "0.25 mg", 8),
            ("prourokinase", "not undergoing evt", 5),
            # 4.6.4: urokinase → boost rec 5 (COR 3:NB)
            ("iv urokinase", "urokinase", 8),
            # 4.6.1: CMB small number → boost rec 12 (COR 2a)
            ("small number", "small number", 10),
            ("small number of cerebral", "small number", 10),
            # 4.6.1: CMB high burden → boost rec 13 (COR 2b)
            ("high burden", "extensive", 10),
            ("high cerebral microbleed", "extensive", 10),
            ("high burden", "previously had extensive", 10),
            ("high burden of cmb", "high burden", 10),
            ("high burden of microbleed", "high burden", 10),
            ("high cerebral microbleed burden", "high burden", 10),
            (">10 cmb", ">10", 10),
            ("more than 10 cmb", ">10", 8),
            ("more than 10 microbleed", ">10", 8),
            ("extensive microbleed", "extensive", 10),
            ("extensive microbleed", "high burden", 10),
            # 4.6.1: CMB limited/small → boost rec 12 (COR 2a)
            ("limited cerebral microbleed", "small number", 10),
            ("limited microbleed", "small number", 10),
            ("limited cmb", "small number", 10),
            ("few microbleed", "small number", 8),
            ("few cmb", "small number", 8),
            # 4.6.1: IVT before CBC → boost rec 10 (COR 2a)
            ("started before cbc", "not be delayed", 12),
            ("started before cbc", "hematologic", 10),
            ("before lab", "not be delayed", 10),
            ("before lab", "hematologic", 8),
            ("delay for lab", "not be delayed", 10),
            ("waiting for lab", "not be delayed", 10),
            ("cbc result", "not be delayed", 10),
            ("cbc result", "hematologic", 8),
            ("waiting for hematologic", "hematologic", 10),
            # 4.7.2: pre-existing disability → boost rec 6 (COR 2b)
            ("pre-existing disability", "mrs score of 3 to 4", 10),
            ("moderate disability", "mrs score of 3 to 4", 10),
            ("moderate pre-existing", "mrs score of 3 to 4", 10),
            ("mrs 3", "mrs score of 3 to 4", 10),
            ("mrs 4", "mrs score of 3 to 4", 10),
            ("disability", "accumulated disability", 8),
            # 4.7.3: basilar NIHSS 6-9 → boost rec 2 (COR 2b)
            ("nihss 6 to 9", "nihss score 6 to 9", 10),
            ("nihss 6-9", "nihss score 6 to 9", 10),
            ("nihss between 6", "nihss score 6 to 9", 10),
            ("nihss 6", "nihss score 6 to 9", 8),
            ("low nihss basilar", "nihss score 6 to 9", 10),
            # 4.6.4: prourokinase → boost rec 2 (COR 2b), not rec 5 (urokinase)
            ("prourokinase recommended", "mutant prourokinase", 10),
            ("prourokinase", "mutant prourokinase", 8),
            # 4.7.5: pediatric time windows
            ("younger than 6", "28 days to 6 years", 10),
            ("under 6 years", "28 days to 6 years", 10),
            ("<6 years", "28 days to 6 years", 10),
            # 4.8: INSPIRES → boost rec 14 (COR 2a)
            ("inspires trial", "inspires", 10),
            ("inspires", "nihss score <=5", 8),
            # 4.9: HT anticoagulation → boost rec 4 (COR 2b)
            ("ht anticoag", "experience ht", 10),
            ("ht anticoag", "hemorrhagic transformation", 8),
            ("hemorrhagic transformation anticoag", "experience ht", 10),
            # 4.6.1: 15-year-old → boost rec 14 (pediatric, COR 2b)
            ("15-year-old", "pediatric patients aged 28 days", 12),
            ("15-year-old", "28 days to 18 years", 10),
            # 4.7.2: mild disability → boost rec 5 (mRS 2, COR 2a)
            ("mild pre-existing disability", "mrs score of 2", 10),
            ("mild disability", "mrs score of 2", 10),
            ("mild functional impairment", "mrs score of 2", 10),
            ("prior mild functional", "mrs score of 2", 10),
            # 4.7.2: ASPECTS 0-2 → boost rec 4 (COR 2a)
            ("aspects 1", "aspects 0 to 2", 10),
            ("aspects 0", "aspects 0 to 2", 10),
            ("aspects 2", "aspects 0 to 2", 10),
            # 4.7.3: basilar NIHSS 6-9 → boost rec 2 (COR 2b)
            ("nihss between 6 and 9", "nihss score 6 to 9", 12),
            ("nihss 7", "nihss score 6 to 9", 10),
            ("nihss 8", "nihss score 6 to 9", 10),
            # 4.8: abciximab → boost rec 4 (COR 3:Harm)
            ("abciximab", "abciximab", 10),
            ("iv abciximab", "iv abciximab", 10),
            # 4.8: aspirin substitute → boost rec 16/17 (COR 3:Harm)
            ("instead of thrombolysis", "substitute", 10),
            ("instead of ivt", "substitute", 10),
            # 6.3: under 60 craniectomy → boost rec 2 (COR 1)
            ("under 60", "<=60 years", 10),
            ("patients under 60", "<=60 years", 10),
            ("<=60", "<=60 years", 8),
            # 6.3: over 60 → boost rec 3 (COR 2b)
            ("older patients", ">60 years", 10),
            (">60", ">60 years", 8),
            ("over 60", ">60 years", 10),
            # 6.4: cerebellar → boost section 6.4
            ("posterior fossa", "cerebellar infarction", 10),
            ("cerebellar stroke", "cerebellar infarction", 10),
            ("cerebellar infarction", "cerebellar infarction", 8),
            # 4.6.1: "within 3 hours" → boost rec 1 (COR 1, LOE A)
            # Rec 1 is the core 3-hour IVT rec (NINDS evidence, LOE A).
            # Rec 2 is the 4.5-hour extension (LOE B-NR).
            ("within 3 hours", "disabling deficits", 10),
            ("3 hours of symptom", "disabling deficits", 10),
            ("within 3 hours", "regardless of nihss", 8),
            # 4.6.1: "disabling stroke at 4 hours" → boost rec 1 (LOE A), not rec 6 (glucose)
            # CAREFUL: must not fire for "nondisabling" / "non-disabling" questions.
            # Use phrase with "at X hours" to be more specific.
            ("disabling stroke symptoms at", "disabling deficits", 10),
            ("disabling deficits", "disabling deficits", 5),
            # 4.6.1: "IVT window" / "IVT in eligible" → boost rec 1 (LOE A)
            ("window for ivt", "disabling deficits", 10),
            ("window for ivt", "faster treatment", 8),
            ("ivt administration in eligible", "disabling deficits", 8),
            ("ivt administration in eligible", "faster treatment", 8),
            ("unknown time of onset", "disabling deficits", 10),
            ("last seen well", "disabling deficits", 10),
            # QA-2040: "woke up with stroke symptoms" → rec 1 (A, disabling deficits)
            ("woke up with stroke", "disabling deficits", 12),
            ("woke up with stroke", "faster treatment", 10),
            # 4.6.1: "involving patients in IVT decision" → boost rec 4 (shared decision, COR 1, LOE C-EO)
            ("involving patients", "shared decision", 12),
            ("patient involvement", "shared decision", 12),
            ("treatment decision", "shared decision", 10),
            # 4.6.1: "lowering BP prior to thrombolysis" → boost 4.3 rec 5 (LOE B-NR)
            # Rec 5 is about BP <=185/110 for IVT eligibility. Rec 6 is about EVT BP.
            ("prior to thrombolysis", "eligible for treatment with ivt", 10),
            ("prior to thrombolysis", "185/110", 8),
            # 4.6.1: hyperglycemia before IVT → boost rec 6 (COR 1, LOE C-LD)
            # QA-2016/2017: rec 6 says "hypoglycemia or hyperglycemia should be corrected"
            # Rec 5 says "be prepared" — more generic.
            ("hyperglycemia", "severe hypoglycemia or hyperglycemia", 10),
            ("corrected before", "severe hypoglycemia or hyperglycemia", 10),
            ("glucose management", "severe hypoglycemia or hyperglycemia", 8),
            ("glucose management prior", "severe hypoglycemia or hyperglycemia", 10),
            # 4.6.1: aspirin/clopidogrel + IVT eligibility → boost rec 9 (LOE B-NR)
            ("taking aspirin and clopidogrel", "taking single or dapt", 12),
            ("currently taking aspirin", "taking single or dapt", 10),
            ("on single antiplatelet", "taking single or dapt", 10),
            ("single antiplatelet therapy", "taking single or dapt", 10),
            # 4.7.1: "IVT before EVT" → boost 4.7.1 recs (LOE A)
            ("before evt", "eligible for both ivt and evt", 10),
            ("before thrombectomy", "eligible for both ivt and evt", 10),
            ("before endovascular", "eligible for both ivt and evt", 10),
            ("bridging ivt", "eligible for both ivt and evt", 10),
            ("before transferring for evt", "eligible for both ivt and evt", 10),
            ("spoke hospital", "eligible for both ivt and evt", 8),
            ("delaying evt", "without observation", 10),
            ("observe ivt response", "without observation", 10),
            ("evt-eligible", "eligible for both ivt and evt", 10),
            # 4.6.1: "door-to-needle" → boost rec 3 (COR 1, about readiness/speed)
            ("door-to-needle", "be prepared to administer", 10),
            ("door to needle", "be prepared to administer", 10),
            ("door-to-needle", "should not delay", 8),
            # 4.6.1: "mixing alteplase" / "prepare IVT during CT" → rec 3 (B-NR)
            # QA-2009: "mixing alteplase during initial CT" — this is about preparation
            # during workup, covered by 4.6.1 rec 3 (LOE B-NR), not 4.6.2.
            ("mixing alteplase", "prepared to treat potential", 12),
            ("mixing alteplase", "bleeding complications", 10),
            ("mixing alteplase during", "prepared to treat potential", 12),
            # 4.6.1: "prepare IVT" → boost rec 3 (COR 1)
            ("prepare ivt", "be prepared to administer", 10),
            ("preparation", "be prepared to administer", 8),
            ("preparing", "be prepared to administer", 8),
            # 4.8: "changing antiplatelet" → boost rec 8 (COR 2b)
            ("changing the antiplatelet", "increasing the dose", 10),
            ("changing antiplatelet", "increasing the dose", 10),
            ("changing agent", "changing to another", 10),
            ("switching antiplatelet", "changing to another", 10),
            # 4.8: "POINT trial" → boost rec 12 (COR 1)
            ("point trial", "aspirin and clopidogrel", 8),
            ("point trial", "nihss score <=3", 8),
            ("point trial", "21 days", 5),
            # 4.8: "antiplatelet after IVT" → boost rec 2 (COR 2b)
            ("after thrombolysis", "received ivt", 10),
            ("after ivt", "received ivt", 10),
            ("antiplatelet after ivt", "received ivt", 10),
            ("antiplatelet after thrombolysis", "received ivt", 10),
            ("within 24 hours of thrombolysis", "received ivt", 10),
            ("within 24 hours of ivt", "received ivt", 10),
            # 4.6.4: "strongest against thrombolytic" → boost rec 6 (3:Harm, streptokinase)
            ("strongest recommendation against", "streptokinase", 12),
            ("strongest against", "streptokinase", 12),
            ("cor 3:harm", "streptokinase", 12),
            ("thrombolytic agent that the 2026 guideline rates as cor 3:harm", "streptokinase", 15),
            # 4.6.3: "beyond 9 hours" → boost rec 3 (COR 2b, 4.5-24h LVO)
            ("beyond 9 hours", "4.5 to 24 hours", 10),
            ("beyond 9", "4.5 to 24 hours", 8),
            ("after 9 hours", "4.5 to 24 hours", 10),
            # 4.6.4: "prourokinase evidence" → boost rec 2 (standalone, COR 2b)
            ("evidence for prourokinase", "not undergoing evt", 8),
            ("prourokinase in acute", "not undergoing evt", 8),
            # 4.7.2: "M2 division" generic → boost rec 7 (dominant, COR 2a)
            ("m2 division", "dominant proximal m2", 8),
            ("m2 occlusion", "dominant proximal m2", 6),
            # 4.6.1: "complete blood count" → boost rec 10 (COR 2a)
            ("complete blood count", "not be delayed", 12),
            ("complete blood count", "hematologic", 10),
            ("before obtaining a complete blood", "not be delayed", 12),
            # 4.12: "emergency carotid" → boost rec 1 (COR 3:NB)
            ("emergency carotid", "emergent carotid", 10),
            ("emergent carotid", "emergent carotid", 10),
            ("emergency carotid intervention", "emergent carotid", 10),
            # ── 4.6.1 R5: disabling → boost rec 1 (disabling deficits, COR 1, LOE A) ──
            ("for disabling", "disabling deficits", 12),
            ("treating disabling", "disabling deficits", 12),
            ("disabling ais", "disabling deficits", 12),
            ("disabling acute stroke", "disabling deficits", 10),
            ("disabling left", "disabling deficits", 10),
            ("disabling weakness", "disabling deficits", 10),
            ("stroke is disabling", "disabling deficits", 10),
            ("presents with disabling", "disabling deficits", 10),
            # ── 4.6.1 R5: urgency/preparation → boost rec 2 (speed) ──
            ("urgency of starting", "as quickly as possible", 12),
            ("urgency", "initiated as quickly as possible", 10),
            ("preparation during", "as quickly as possible", 10),
            ("ivt preparation", "as quickly as possible", 8),
            ("preparing ivt", "as quickly as possible", 10),
            ("preparing ivt during", "as quickly as possible", 12),
            # ── 4.6.1 R5: glucose correction → boost rec 6 (LOE C-LD) ──
            # Use rec 6-unique phrases ("correction to normoglycemia", "persist
            # despite correction") since "severe hypoglycemia" appears in both rec 5 and 6.
            ("glucose correction", "correction to normoglycemia", 15),
            ("glucose correction", "persist despite correction", 12),
            ("correcting blood glucose", "correction to normoglycemia", 15),
            ("correcting blood glucose", "persist despite correction", 12),
            ("correcting hypoglycemia", "correction to normoglycemia", 15),
            ("correcting hypoglycemia", "persist despite correction", 12),
            ("correct glucose", "correction to normoglycemia", 12),
            ("glucose of 45", "correction to normoglycemia", 15),
            ("glucose of 45", "severe hypoglycemia", 12),
            ("45 mg/dl", "correction to normoglycemia", 12),
            ("45 mg", "correction to normoglycemia", 10),
            # ── 4.6.1 R5: antiplatelet → boost rec 9 (COR 1) ──
            ("concurrent antiplatelet", "taking single or dapt", 12),
            ("antiplatelet use", "taking single or dapt", 12),
            ("antiplatelet preclude", "taking single or dapt", 12),
            ("on aspirin and clopidogrel", "taking single or dapt", 12),
            ("aspirin monotherapy", "taking single or dapt", 12),
            ("on aspirin mono", "taking single or dapt", 12),
            ("on antiplatelet", "taking single or dapt", 10),
            ("on dapt", "taking single or dapt", 12),
            ("patients on dapt", "taking single or dapt", 12),
            ("dapt who present", "taking single or dapt", 12),
            # ── 4.6.1 R5: coagulation/lab → boost rec 10 (COR 2a) ──
            ("without waiting for coagulation", "not be delayed", 12),
            ("coagulation test results", "coagulation testing", 10),
            ("waiting for coagulation", "not be delayed", 10),
            ("lab results not yet", "not be delayed", 12),
            ("lab results not", "hematologic", 10),
            ("should ivt be delayed", "not be delayed", 12),
            ("ivt be delayed", "not be delayed", 10),
            # ── 4.6.1 R5: early ischemic changes → boost rec 7 (LOE A) ──
            ("early signs of ischemia", "early ischemic change", 12),
            ("signs of ischemia", "ischemic change", 8),
            ("early ischemic change", "ischemic change", 8),
            # ── 4.6.1 R5: time window + disabling → boost rec 1 (LOE A) ──
            ("within the first three hours", "disabling deficits", 12),
            ("first three hours", "disabling deficits", 10),
            ("3-4.5h window", "disabling deficits", 10),
            ("3-to-4.5-hour window", "disabling deficits", 10),
            ("3-to-4.5-hour", "disabling deficits", 10),
            # ── 4.6.1 R5: CMB count → boost rec 12 (small) or rec 13 (high) ──
            ("few cerebral microbleed", "small number", 12),
            ("3 cerebral microbleed", "small number", 12),
            ("3 microbleed", "small number", 10),
            ("low microbleed burden", "small number", 12),
            ("low burden of cmb", "small number", 10),
            ("low burden", "small number", 8),
            ("numerous cerebral microbleed", "high burden", 12),
            ("numerous microbleed", "high burden", 10),
            ("numerous cmb", "high burden", 10),
            ("significant comorbid cmb", "high burden", 10),
            ("significant microbleed", "high burden", 10),
            ("high count", "high burden", 10),
            ("more than 20 cerebral microbleed", "high burden", 12),
            ("more than 20 microbleed", "high burden", 12),
            ("more than 20", "high burden", 10),
            # ── 4.6.1 R5: children → boost rec 14 (pediatric) ──
            ("children with acute ischemic", "pediatric patients aged 28 days", 12),
            ("treatment for children", "pediatric patients", 12),
            ("children with ais", "pediatric patients", 10),
            ("established treatment for children", "pediatric patients", 12),
            # ── 4.6.1 R5: "does not cause disability" → boost rec 8 (non-disabling) ──
            ("does not cause disability", "non-disabling", 12),
            ("minor stroke that does not", "non-disabling", 10),
            # ── 4.7.2 R5: various vessel/population discriminators ──
            # (already have M2/ICA/M1, add more here as needed)
            # ── 4.7.5 R5: infants/toddlers → boost rec 3 (28 days to 6 years) ──
            ("infants and toddlers", "28 days to 6 years", 12),
            ("infants", "28 days to 6 years", 10),
            ("toddlers", "28 days to 6 years", 10),
            ("neonates and infants", "28 days to 6 years", 10),
            # ── 4.8 R5: ticagrelor monotherapy → boost rec 9 (3:NB) ──
            ("ticagrelor monotherapy superior to aspirin", "not recommended over aspirin", 15),
            ("monotherapy superior to aspirin", "not recommended over aspirin", 12),
            # ── 4.8 R5: aspirin replacement for IVT/EVT → boost rec 16 (3:Harm) ──
            ("replacement for ivt", "substitute", 12),
            ("replacement for evt", "substitute", 12),
            ("replacement for ivt/evt", "substitute", 15),
            ("aspirin as a replacement", "not recommended as a substitute", 15),
            # ── 4.8 R5: post-IVT antiplatelet timing → boost rec 2 (COR 2b) ──
            ("had ivt", "received ivt", 12),
            ("ivt 6 hours ago", "received ivt", 12),
            ("starting aspirin now", "antiplatelet therapy in the first 24 hours", 12),
            # ── 4.10 R5: hemodilution/hemodynamic → boost rec 1 (COR 3:NB) ──
            ("hemodilution", "hemodilution", 12),
            ("hemodilution", "hemodynamic augmentation", 12),
            ("hemodynamic therapies", "hemodynamic augmentation", 15),
            ("non-recommendation of hemodynamic", "hemodynamic augmentation", 15),
            ("induced hypertension", "hemodynamic augmentation", 15),
            ("induced hypertension recommended", "hemodynamic augmentation", 15),
            # ── 4.12 R5: carotid urgently → boost rec 1 (COR 3:NB) ──
            ("carotid intervention urgently", "emergent carotid", 12),
            ("urgently after ais", "emergent carotid", 10),
            ("performing carotid intervention urgently", "emergent carotid endarterectomy", 15),
            # ── 5.2 R5: bedside screening before eating → boost rec 1 (COR 1, C-EO) ──
            ("must bedside dysphagia screening", "bedside swallow screening prior to initiation", 15),
            ("before a stroke patient eats", "prior to initiation of liquid or food intake", 15),
            ("before eating", "prior to initiation of liquid or food intake", 12),
            ("eats or drinks", "liquid or food intake", 12),
            ("eat breakfast", "liquid or food intake", 15),
            ("eat breakfast", "bedside swallow screening", 12),
            ("wants to eat", "prior to initiation of liquid or food", 15),
            ("what must happen first", "bedside swallow screening prior to", 12),
            # ── 5.2 R5: PES → boost rec 5 (COR 2a, B-R) ──
            ("pes for reducing dysphagia", "pharyngeal electrical stimulation", 15),
            ("pes", "pharyngeal electrical stimulation", 12),
            # ── 5.3 R5: enteral feeding timing → boost rec 1 (COR 1, B-R) ──
            ("enteral feeding within 7 days", "enteral diet should be started within 7 days", 15),
            ("enteral feeding within 7", "enteral diet", 12),
            ("when should enteral nutrition start", "enteral diet should be started within 7 days", 15),
            ("when should enteral", "enteral diet should be started", 12),
            ("cannot swallow safely", "enteral diet should be started", 10),
            # ── 5.4 R5: LMWH vs UFH → boost rec 4 (COR 2b, B-R) ──
            ("lmwh clearly superior to ufh", "lmwh over prophylactic-dose ufh", 15),
            ("lmwh superior to ufh", "lmwh over prophylactic-dose ufh", 12),
            ("lmwh vs ufh", "lmwh over prophylactic-dose ufh", 10),
            # ── 5.4 R5: UFH over nothing → boost rec 3 (COR 2b, A) ──
            ("ufh over no prophylactic", "over no prophylactic-dose heparin", 15),
            ("over no prophylactic heparin", "over no prophylactic-dose heparin", 12),
            # ── 5.5 R5: treatment of depression → boost rec 2 (COR 1, B-R) ──
            ("treatment of post-stroke depression", "antidepressants and/or nonpharmac", 12),
            ("treatment of psd", "antidepressants and/or nonpharmac", 12),
            ("treating post-stroke depression", "antidepressants and/or nonpharmac", 12),
            # ── 5.7 R5: mobilization → boost rec 3 (COR 3:Harm) ──
            ("aggressively mobilized", "high-dose, very early mobilization", 15),
            ("aggressively mobilized 12 hours", "mobilization within 24 hours", 15),
            ("mobilized 12 hours after onset", "mobilization within 24 hours", 15),
            # ── 5.7 R5: fluoxetine → boost rec 2 (COR 3:NB, LOE A) ──
            ("fluoxetine", "ssris are not effective", 15),
            ("fluoxetine to improve motor", "ssris are not effective for improving motor", 15),
            ("fluoxetine", "motor recovery", 12),
            ("improve motor function after stroke", "motor recovery or functional skills", 12),
            # ── 6.2 R5: steroids → boost rec 3 (COR 3:Harm) ──
            ("steroids", "corticosteroids", 12),
            ("steroids are ordered for", "corticosteroids should not be administered", 15),
            ("steroids for brain swelling", "corticosteroids", 15),
            # ── 6.3 R5: age-based craniectomy ──
            ("60 or younger", "<=60 years of age", 15),
            ("patients 60 or younger", "<=60 years of age", 15),
            ("craniectomy in patients 60 or younger", "<=60 years of age", 15),
            ("55-year-old", "<=60 years of age", 12),
            ("68-year-old", ">60 years of age", 12),
            # ── 6.5 R5: treatment vs prophylaxis ──
            ("unprovoked post-stroke seizures be treated", "unprovoked seizure after ais", 15),
            ("treated with antiseizure", "antiseizure medication is recommended to reduce", 12),
            ("routine seizure prophylaxis", "prophylactic treatment with antiseizure", 15),
            ("routine prophylaxis after stroke", "prophylactic", 12),
            ("prophylactic levetiracetam", "prophylactic treatment with antiseizure medication", 15),
            ("levetiracetam to all stroke", "prophylactic treatment with antiseizure", 15),
            # ── 4.6.2 R5: TNK dosing → boost rec 1 (COR 1, 0.25 mg/kg) ──
            ("0.25 or 0.4", "0.25 mg/kg", 10),
            ("use 0.25 or 0.4", "0.25 mg/kg", 12),
            # ── 4.6.3 R5: 4.5-9 hours → boost rec 1/2 (COR 2a) ──
            ("4.5-9 hours after onset", "within 4.5 hours of last being known well", 10),
            ("4.5 to 9 hours", "unknown time of onset", 8),
            # ── 4.6.3 R5: 4.5-24h → boost rec 3 (COR 2b) ──
            ("very late window", "4.5 to 24 hours", 12),
            ("4.5-24h ivt", "4.5 to 24 hours", 10),
            # ── 4.6.3 R5: extended window → boost 4.6.3 recs ──
            ("extended-window ivt", "unknown time of onset and are within 4.5 hours", 12),
            ("cor 1 recommendation for extended-window", "unknown time of onset", 10),
            # ── 4.6.4 R5: reteplase → boost rec 1 (COR 2b) ──
            ("reteplase", "reteplase", 12),
            ("reteplase for acute stroke", "reteplase", 15),
            # ── 4.6.4 R5: alternative thrombolytic besides alteplase → boost rec 1 (prourokinase) ──
            ("alternative thrombolytic besides alteplase", "prourokinase", 12),
            ("alternative thrombolytic besides alteplase", "reteplase", 10),
            ("besides alteplase and tenecteplase", "prourokinase", 15),
            ("besides alteplase and tenecteplase", "reteplase", 12),
            # ── 4.7.1 R5: IVT + EVT → boost rec 1 (COR 1, LOE A) ──
            ("giving ivt to patients who will also receive evt", "eligible for both ivt and evt", 15),
            ("also receive evt", "eligible for both ivt and evt", 12),
            ("endorse giving ivt", "eligible for both ivt and evt", 10),
            # ── 4.7.2 R5: ASPECTS in early window → boost rec 1 (COR 1) ──
            ("aspects play in determining evt", "aspects score >=6", 12),
            ("aspects in the 0-6h", "aspects score >=6", 10),
            ("aspects cutoff", "aspects score >=6", 10),
            # ── 4.7.2 R5: posterior outside basilar → boost rec 8 (3:NB) ──
            ("posterior circulation strokes outside the basilar", "nondominant or codominant", 12),
            ("outside the basilar", "posterior circulation occlusion", 8),
            # ── 4.7.2 R5: ASPECTS transition → boost rec 4 (COR 2a, low ASPECTS) ──
            ("aspects cutoff does evt transition", "aspects 0 to 2", 12),
            ("transition from cor 1 to cor 2a", "aspects 0 to 2", 10),
            # ── 4.7.2 R5: disability → discriminate mRS 2 vs 3-4 ──
            ("moderate pre-existing disability", "mrs score of 3 to 4", 12),
            ("moderate pre-stroke disability", "mrs score of 3 to 4", 12),
            ("pre-existing disability affect", "accumulated disability", 10),
            # ── 4.7.2 R5: mild pre-existing → boost rec 5 (mRS 2, COR 2a) ──
            ("mild pre-existing functional", "mrs score of 2", 12),
            # ── 4.7.5 R5: 3-year-old → boost rec 3 (28 days to 6 years) ──
            ("3-year-old", "28 days to 6 years", 15),
            ("3 year old", "28 days to 6 years", 15),
            # ── 4.7.5 R5: neonates with LVO → boost rec 3 (COR 2b) ──
            ("neonates with large vessel", "28 days to 6 years", 12),
            ("neonates with lvo", "28 days to 6 years", 12),
            # ── 4.7.5 R5: minimum age → boost rec 3 (28 days) ──
            ("minimum age", "28 days to 6 years", 10),
            ("minimum age", "28 days", 8),
            # ── 4.8 R5: early antiplatelet after IVT → boost rec 2 (COR 2b) ──
            ("early antiplatelet therapy within 24 hours of ivt", "received ivt", 15),
            ("early antiplatelet within 24 hours of ivt", "received ivt", 15),
            ("within 24 hours of ivt well established", "received ivt", 12),
            # ── 4.8 R5: tirofiban → boost rec 5 (COR 2b) ──
            ("tirofiban", "tirofiban", 15),
            ("tirofiban for acute stroke", "tirofiban", 15),
            # ── 6.3 R5: 68-year-old → boost rec 3 (>60, COR 2b, LOE B-R) ──
            ("68-year-old has malignant", ">60 years of age", 15),
            ("68-year-old", "unilateral mca infarctions", 10),
        ]
        for q_phrase, rec_phrase, bonus in _AGE_SYNONYMS:
            if q_phrase in q_lower_for_disc and rec_phrase in text_lower:
                score += bonus

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

    # Penalty for recs from explicitly suppressed sections.
    # When compound overrides say "suppress 4.6.1", recs from 4.6.1 get a
    # penalty to prevent generic high-match recs from outscoring specific ones.
    if suppressed_sections:
        for ss in suppressed_sections:
            if rec_section == ss or rec_section.startswith(ss + "."):
                score -= 15
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

    # ── Automatic within-section discrimination ──────────────────────
    # When the question contains phrases unique to this rec (or a sibling),
    # adjust the score. This handles within-section differentiation without
    # requiring manual contradiction pair enumeration.
    if section_discriminators and question:
        score += compute_discrimination_score(rec, question, section_discriminators)

    # ── Narrow-scope gate ──────────────────────────────────────────
    # Recs about narrow populations (pediatric, pregnancy, etc.) should NOT
    # win generic questions just because they contain common terms.
    # If the rec text mentions a narrow scope keyword but the question doesn't,
    # apply a penalty proportional to how generic the question is.
    if question:
        _NARROW_SCOPE_GATES = [
            # (rec_text_marker, required_question_terms, penalty)
            # If rec contains marker AND question lacks ALL required terms → penalize
            ("pediatric patients aged 28 days", ["pediatric", "child", "children", "15-year", "15 year", "16-year", "16 year", "17-year", "17 year", "teenager", "adolescent", "neonat", "infant", "10-year", "12-year", "14-year", "8-year", "6-year"], -15),
            ("neonates", ["neonat", "infant", "28 days", "newborn", "neonatal"], -12),
            # 4.7.5 rec 3 (<6 years) should not win generic pediatric EVT questions.
            # If the question doesn't mention young-child-specific terms, penalize rec 3.
            ("28 days to 6 years", ["younger than 6", "under 6", "<6", "toddler", "infant", "neonat", "2 year", "3 year", "4 year", "5 year", "28 days", "first-time seizure", "seizure"], -12),
        ]
        for marker, required_terms, penalty in _NARROW_SCOPE_GATES:
            if marker in text_lower:
                if not any(rt in q_lower_for_disc for rt in required_terms):
                    score += penalty

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
        raw = plain_match.group(1).rstrip(".")
        return cast(raw) if raw else None

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
        ("m3", "M3"), ("ica", "ICA"), ("t-ica", "T-ICA"),
        ("aca", "ACA"), ("pca", "PCA"),
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
    for trial in _KNOWN_TRIALS:
        # Use word-boundary matching to avoid false positives
        # (e.g., "AcT" matching inside "practice" or "impact")
        pattern = r'\b' + re.escape(trial) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
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
# Table 8 tier classification (standalone, testable)
# ---------------------------------------------------------------------------

def classify_table8_tier(question: str) -> Optional[str]:
    """Classify a question into a Table 8 tier.

    Returns one of:
        "Absolute"
        "Relative"
        "Benefit May Exceed Risk"
        None  (not a Table 8 question or tier unresolvable)
    """
    q_lower = question.lower()

    # ── Detection: is this a Table 8 question? ──
    _EXPLICIT_CONTRA_TERMS = [
        "contraindication", "contraindicated", "table 8",
        "absolute", "relative",
        "benefit may exceed risk", "benefit over risk", "benefit outweigh",
        "benefit exceed", "benefit likely outweigh",
        "tier of", "tier for", "tier does", "what tier",
        "classified as", "classification",
        "tiers of ivt", "categories of ivt",
        "three categories", "three tiers",
        "distinction between", "important for surgical",
        "ivt risk tier", "ivt contraindication tier",
        "ivt decision-making", "ivt eligibility",
        "risk tier", "what table 8 tier",
        "contraindication tier", "tier applies",
    ]
    _is_explicit = any(ct in q_lower for ct in _EXPLICIT_CONTRA_TERMS)

    _IVT_CONTEXT = ["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"]
    _TABLE8_CONDITIONS = [
        # Benefit May Exceed Risk conditions
        "extra-axial", "extraaxial", "extra-axial intracranial neoplasm",
        "unruptured aneurysm", "unruptured intracranial aneurysm",
        "moya-moya", "moyamoya",
        "procedural stroke", "angiographic procedural",
        "remote gi", "remote gu", "history of gi bleeding",
        "history of myocardial infarction", "remote mi", "history of mi",
        "recreational drug", "cocaine", "methamphetamine", "illicit drug",
        "substance use", "substance abuse",
        "stroke mimic", "mimic",
        "seizure at onset",
        "cerebral microbleed", "microbleed", "cmb",
        "menstruation", "diabetic retinopathy",
        # Absolute conditions
        "intracranial hemorrhage", "active internal bleeding",
        "extensive hypodensity", "hypodensity", "multilobar infarction",
        "traumatic brain injury", "tbi",
        "neurosurgery", "spinal cord injury",
        "intra-axial", "intraaxial", "brain tumor", "glioma",
        "infective endocarditis", "endocarditis",
        "severe coagulopathy", "coagulopathy",
        "aortic dissection", "aortic arch dissection",
        "aria", "amyloid", "lecanemab", "aducanumab",
        "glucose <50", "blood glucose less than 50",
        # Relative conditions
        "doac within 48", "recent doac",
        "prior intracranial hemorrhage", "prior ich",
        "arterial dissection", "cervical dissection",
        "pregnancy", "pregnant", "postpartum", "post-partum",
        "active malignancy", "active cancer",
        "pre-existing disability", "preexisting disability", "prior disability",
        "vascular malformation", "avm", "cavernoma",
        "pericarditis", "cardiac thrombus",
        "dural puncture", "lumbar puncture",
        "arterial puncture", "noncompressible",
        "amyloid angiopathy", "known amyloid",
        "hepatic failure", "liver failure", "hepatic dysfunction",
        "pancreatitis", "septic embolism",
        "dementia", "dialysis",
        "clear hypodensity", "hypodensity responsible",
        "immunotherapy for amyloid", "immunotherapy",
        # R5 additions
        "intracerebral hemorrhage", "prior intracerebral",
        "left atrial", "left ventricular", "ventricular thrombus",
        "atrial thrombus",
        "post-partum", "postpartum period",
        "gi bleed", "gu bleed", "gi/gu bleeding",
        "history of gi", "history of gu",
        "ischemic stroke 2 months", "stroke 2 months",
        "uncertainty about stroke", "uncertainty of stroke diagnosis",
        "craniotomy 10 days", "craniotomy within",
    ]
    _has_ivt = any(t in q_lower for t in _IVT_CONTEXT)
    _has_t8 = any(t in q_lower for t in _TABLE8_CONDITIONS)
    _is_implicit = _has_ivt and _has_t8

    _eligibility = (
        ("can ivt be" in q_lower or "can thrombolysis be" in q_lower or
         "is ivt safe" in q_lower or "eligible for ivt" in q_lower or
         "ivt eligible" in q_lower or "receive ivt" in q_lower or
         "eligible for thrombolysis" in q_lower or
         "eligible for ivt per" in q_lower)
        and _has_t8
    )

    if not (_is_explicit or _is_implicit or _eligibility):
        return None

    # ── Tier classification ──

    _BENEFIT_TERMS = [
        "extracranial cervical", "extracranial dissection",
        "cervical arterial dissection",
        "extra-axial intracranial neoplasm", "extra-axial neoplasm",
        "extra-axial", "extraaxial",
        "unruptured intracranial aneurysm", "unruptured aneurysm",
        "unruptured", "intracranial aneurysm",
        "moya-moya", "moyamoya", "moya moya",
        "angiographic procedural", "procedural stroke",
        "periprocedural stroke", "stroke during angiography",
        "remote gi", "remote gu", "history of gi bleeding",
        "history of gu bleeding", "remote gastrointestinal",
        "remote genitourinary", "previous gi bleeding",
        "old gi bleed", "stable gi",
        "history of mi", "remote mi", "history of myocardial infarction",
        "old myocardial infarction", "prior mi",
        "recreational drug", "drug use", "cocaine",
        "methamphetamine", "amphetamine",
        "illicit drug", "substance use", "substance abuse",
        "stroke mimic", "mimic", "uncertainty of stroke",
        "uncertainty about stroke", "uncertain diagnosis",
        "seizure at onset", "seizure at stroke onset",
        "cerebral microbleed", "microbleeds on mri",
        "microbleed", "cmb",
        "menstruation", "menstrual", "menses",
        "diabetic retinopathy", "diabetic hemorrhagic retinopathy",
        "retinopathy",
        # R5: "history of GI or GU bleeding" (not recent — remote/old)
        "history of gi or gu", "gi/gu bleeding",
        "history of gi/gu", "history of gi bleeding",
    ]

    _ABSOLUTE_TERMS = [
        "intracranial hemorrhage", "ich on ct", "ich on mri",
        "hemorrhage on ct", "hemorrhage on imaging",
        "ct showing hemorrhage", "mri showing hemorrhage",
        "extensive regions", "obvious hypodensity",
        "extensive hypodensity", "large hypodensity",
        "clear hypodensity", "hypodensity responsible",
        "multilobar infarction", "multilobar hypodensity",
        "ct showing multilobar",
        "traumatic brain injury within 14",
        "tbi within 14", "moderate-severe tbi",
        "severe head trauma",
        "intracranial or intraspinal neurosurgery",
        "neurosurgery within 14", "intraspinal surgery within 14",
        "craniotomy within 14",
        "spinal cord injury", "acute spinal cord",
        "intra-axial intracranial neoplasm", "intra-axial neoplasm",
        "intra-axial", "intraaxial neoplasm",
        "brain tumor", "brain neoplasm", "glioma", "glioblastoma",
        "infective endocarditis", "bacterial endocarditis",
        "endocarditis",
        "severe coagulopathy", "coagulopathy",
        "platelets <100,000", "platelet count below 100000",
        "platelets <100000", "platelet <100",
        "inr >1.7", "inr above 1.7", "inr greater than 1.7",
        "pt >15", "pt above 15",
        "aptt >40", "aptt above 40", "aptt greater than 40",
        "aortic arch dissection", "aortic dissection",
        "aria", "amyloid-related imaging",
        "amyloid immunotherapy", "anti-amyloid",
        "lecanemab", "aducanumab", "donanemab",
        "active internal bleeding",
        "blood glucose less than 50", "glucose <50",
        "direct thrombin inhibitor",
    ]

    _RELATIVE_TERMS = [
        "doac within 48", "doac within 48 hours",
        "recent doac", "doac use",
        "ischemic stroke within 3 months", "recent ischemic stroke",
        "stroke within 3 months", "prior stroke within 3",
        "prior intracranial hemorrhage", "history of intracranial hemorrhage",
        "prior intracerebral hemorrhage", "intracerebral hemorrhage",
        "previous ich", "prior ich",
        "recent non-cns trauma", "non-cns trauma",
        "recent non-cns surgery", "non-cns surgery",
        "surgery within 10 days",
        "gi bleeding within 21", "gu bleeding within 21",
        "recent gi bleed", "recent gu bleed",
        "recent gastrointestinal", "recent genitourinary",
        "gastrointestinal hemorrhage", "genitourinary hemorrhage",
        "gi or urinary", "gi or gu",
        "cervical or intracranial arterial dissection",
        "intracranial dissection", "arterial dissection",
        "pregnancy", "pregnant", "postpartum", "post-partum",
        "active systemic malignancy", "active malignancy",
        "active cancer", "metastatic cancer",
        "pre-existing disability", "preexisting disability",
        "premorbid disability", "prior disability", "frailty",
        "intracranial vascular malformation", "vascular malformation",
        "avm", "arteriovenous malformation",
        "cavernous malformation", "cavernoma",
        "recent stemi", "stemi within 3 months",
        "recent myocardial infarction", "mi within 3 months",
        "recent mi", "st elevation mi",
        "acute pericarditis", "pericarditis",
        "left atrial thrombus", "left ventricular thrombus",
        "atrial or ventricular thrombus", "atrial thrombus",
        "ventricular thrombus",
        "cardiac thrombus", "intracardiac thrombus",
        "la thrombus", "lv thrombus",
        "dural puncture", "lumbar puncture",
        "spinal tap", "lumbar dural",
        "arterial puncture", "noncompressible vessel puncture",
        "non-compressible", "noncompressible arterial",
        "traumatic brain injury", "tbi",
        "neurosurgery", "intracranial surgery", "spinal surgery",
        "craniotomy",
        "major surgery within 14", "major surgery",
        "cardiac massage", "cpr",
        "hepatic failure", "liver failure", "hepatic dysfunction",
        "pancreatitis", "acute pancreatitis",
        "septic embolism",
        "dementia",
        "dialysis", "hemodialysis",
        "doac",
    ]

    # 1. Explicit tier hints in question text
    tier = None

    _q_benefit_hints = [
        "benefit may exceed risk", "benefit over risk",
        "benefit outweigh", "benefit exceed",
        "benefit-may-exceed",
    ]
    _q_absolute_hints = ["absolute contraindication"]
    _q_relative_hints = ["relative contraindication"]

    if any(h in q_lower for h in _q_benefit_hints):
        tier = "Benefit May Exceed Risk"
    elif any(h in q_lower for h in _q_absolute_hints):
        tier = "Absolute"
    elif any(h in q_lower for h in _q_relative_hints):
        tier = "Relative"

    # If question asks "is X relative or absolute?" reset BEFORE time-dependent
    # so that specific time rules override the generic explicit hint.
    _asks_which = (
        ("relative" in q_lower and "absolute" in q_lower) or
        "relative or absolute" in q_lower or
        "absolute or relative" in q_lower
    )
    if _asks_which and tier in ("Absolute", "Relative"):
        tier = None

    # If "absolute contraindication" fires but the question contains a known
    # Benefit-tier condition (e.g., "Is Moya-Moya an absolute contraindication?"),
    # the correct answer is "No, it's Benefit" — reset so clinical terms decide.
    if tier == "Absolute":
        _BENEFIT_OVERRIDE_TERMS = [
            "moya-moya", "moyamoya", "moya moya",
            "extra-axial", "extraaxial",
            "unruptured aneurysm", "unruptured intracranial",
            "stroke mimic", "seizure at onset",
            "microbleed", "menstruation", "diabetic retinopathy",
            "recreational drug", "cocaine", "methamphetamine",
            "remote gi", "remote gu", "history of gi bleeding",
            "history of gi or gu", "gi/gu bleeding",
            "history of mi", "remote mi",
            "procedural stroke", "angiographic procedural",
            "uncertainty about stroke", "uncertain diagnosis",
        ]
        if any(bt in q_lower for bt in _BENEFIT_OVERRIDE_TERMS):
            tier = None  # Let clinical terms decide

    # 2. Time-dependent disambiguation
    _TIME_DEPENDENT_TIERS = [
        # "prior ICH" / "history of ICH" → Relative (not Absolute like acute ICH)
        ("prior intracranial hemorrhage", "Relative"),
        ("prior ich", "Relative"),
        ("previous ich", "Relative"),
        ("history of intracranial hemorrhage", "Relative"),
        ("prior ich classified the same", "Relative"),
        # "14 days to 3 months" = Relative — MUST be checked BEFORE
        # "within 14" patterns to avoid false Absolute on "within 14 days to 3 months"
        ("14 days to 3 months", "Relative"),
        ("14-to-3-months", "Relative"),
        ("14 to 3 months", "Relative"),
        # TBI: within 14 days = Absolute (various phrasings)
        ("tbi within 14", "Absolute"),
        ("tbi less than 14", "Absolute"),
        ("traumatic brain injury within 14", "Absolute"),
        ("traumatic brain injury less than 14", "Absolute"),
        ("severe head trauma", "Absolute"),
        ("moderate-severe tbi", "Absolute"),
        ("moderate to severe tbi", "Absolute"),
        ("moderate to severe tbi less than", "Absolute"),
        # Neurosurgery: within 14 days = Absolute (various phrasings)
        ("neurosurgery within 14", "Absolute"),
        ("neurosurgery less than 14", "Absolute"),
        ("craniotomy within 14", "Absolute"),
        ("craniotomy less than 14", "Absolute"),
        ("intraspinal surgery within 14", "Absolute"),
        ("intracranial or spinal surgery within 14", "Absolute"),
        ("intracranial or spinal surgery less than 14", "Absolute"),
        # Neurosurgery/craniotomy "X days ago" where X < 14 → Absolute
        ("craniotomy 1 day", "Absolute"),
        ("craniotomy 2 day", "Absolute"),
        ("craniotomy 3 day", "Absolute"),
        ("craniotomy 4 day", "Absolute"),
        ("craniotomy 5 day", "Absolute"),
        ("craniotomy 6 day", "Absolute"),
        ("craniotomy 7 day", "Absolute"),
        ("craniotomy 8 day", "Absolute"),
        ("craniotomy 9 day", "Absolute"),
        ("craniotomy 10 day", "Absolute"),
        ("craniotomy 11 day", "Absolute"),
        ("craniotomy 12 day", "Absolute"),
        ("craniotomy 13 day", "Absolute"),
        ("neurosurgery 1 day", "Absolute"),
        ("neurosurgery 2 day", "Absolute"),
        ("neurosurgery 3 day", "Absolute"),
        ("neurosurgery 5 day", "Absolute"),
        ("neurosurgery 7 day", "Absolute"),
        ("neurosurgery 10 day", "Absolute"),
        # Spinal cord injury
        ("spinal cord injury within 3", "Absolute"),
        ("spinal cord injury", "Absolute"),
        # "ischemic stroke X months ago" where X <= 3 → Relative
        ("ischemic stroke 1 month", "Relative"),
        ("ischemic stroke 2 month", "Relative"),
        ("ischemic stroke 3 month", "Relative"),
        ("stroke 1 month ago", "Relative"),
        ("stroke 2 months ago", "Relative"),
        ("stroke 3 months ago", "Relative"),
        # "GI bleed X weeks ago" where recent (within 21 days) → Relative
        ("gi bleed 1 week", "Relative"),
        ("gi bleed 2 week", "Relative"),
        ("gi bleed 3 week", "Relative"),
        ("gu bleed 1 week", "Relative"),
        ("gu bleed 2 week", "Relative"),
        # "prior intracerebral hemorrhage" → Relative
        ("prior intracerebral", "Relative"),
        # Amyloid angiopathy (no immunotherapy) → Relative
        ("amyloid angiopathy", "Relative"),
        ("known amyloid angiopathy", "Relative"),
        # Immunotherapy for amyloid → Absolute (ARIA risk)
        ("immunotherapy for amyloid", "Absolute"),
        ("amyloid immunotherapy", "Absolute"),
        ("anti-amyloid", "Absolute"),
        # Recent GI/GU bleeding (within 21 days) → Relative
        # "recent" or "within 21" qualifier distinguishes from remote/history (Benefit)
        ("recent gi/gu bleeding", "Relative"),
        ("gi/gu bleeding within 21", "Relative"),
        ("recent gi/gu bleeding within", "Relative"),
        ("recent gi bleeding", "Relative"),
        ("recent gu bleeding", "Relative"),
        ("gi bleeding within 21", "Relative"),
        ("gu bleeding within 21", "Relative"),
    ]

    if tier is None:
        for pattern, t in _TIME_DEPENDENT_TIERS:
            if pattern in q_lower:
                tier = t
                break

    # 3. Clinical term matching: Benefit → Absolute → Relative
    if tier is None:
        if any(bt in q_lower for bt in _BENEFIT_TERMS):
            tier = "Benefit May Exceed Risk"
        elif any(at in q_lower for at in _ABSOLUTE_TERMS):
            tier = "Absolute"
        elif any(rt in q_lower for rt in _RELATIVE_TERMS):
            tier = "Relative"

    # 4. Fallback: meta-questions about Table 8 structure (tiers, categories)
    # that mention "table 8" but no specific condition → default to Relative.
    if tier is None and "table 8" in q_lower:
        _META_INDICATORS = [
            "how many tiers", "three categories", "three tiers",
            "categories of ivt", "tiers of ivt",
            "distinguish between", "distinction between",
        ]
        if any(mi in q_lower for mi in _META_INDICATORS):
            tier = "Relative"

    return tier


# ---------------------------------------------------------------------------
# Question type classification (evidence / knowledge_gap / recommendation)
# ---------------------------------------------------------------------------

_KG_TERMS = [
    "knowledge gap", "research gap", "research gaps", "future research",
    "future direction", "unanswered question", "what is unknown",
    "what don't we know", "what do we not know", "gaps in evidence",
    "gaps exist", "areas for future", "areas need",
    "needs further study", "further study", "remains unclear", "unresolved",
    "research is needed", "what further", "optimal timing",
    "further investigation", "need further investigation",
    "future studies are needed", "remain unanswered", "questions remain unanswered",
    "what remains unclear about",
]

_EV_TERMS = [
    "what evidence", "what data", "what studies", "what trial",
    "what trial data", "what case series", "what specific",
    "rationale", "why is", "why are", "why does", "why don't",
    "supporting evidence", "basis for", "what supports", "what justifies",
    "evidence behind", "evidence for", "evidence that",
    "is the evidence", "evidence basis", "evidence shows",
    "what trials", "what's the data", "is there data",
    "data supports", "data shows", "trials inform",
    "trials tested", "trials have tested",
]


def classify_question_type(question: str) -> str:
    """
    Classify question intent: knowledge_gap, evidence, or recommendation.

    Uses narrow keyword lists so that only questions *explicitly* about
    evidence or knowledge gaps divert to the LLM extraction path.
    Generic questions that happen to mention "study" or "data" stay on
    the existing recommendation scoring pipeline.
    """
    q = question.lower()
    if any(t in q for t in _KG_TERMS):
        return "knowledge_gap"
    if any(t in q for t in _EV_TERMS):
        return "evidence"
    return "recommendation"


# ---------------------------------------------------------------------------
# Ambiguity detection for within-section COR conflicts
# ---------------------------------------------------------------------------

def detect_ambiguity(
    scored_recs: List[Tuple[int, dict]],
    question: str,
    ambiguity_threshold: int = 3,
) -> Optional[str]:
    """
    Detect when top-scored recommendations have conflicting COR levels
    within the same section, indicating the question is ambiguous.

    Returns a clarification string if ambiguity is detected, None otherwise.
    This implements the generic CMI-pattern clarification: when the system
    cannot determine which specific recommendation the user is asking about,
    it presents the options and asks the user to clarify.
    """
    if not scored_recs or scored_recs[0][0] <= 0:
        return None

    top_score = scored_recs[0][0]
    top_section = scored_recs[0][1].get("section")

    # Get all recs from the same section that score within threshold of top
    close_recs = [
        (s, r) for s, r in scored_recs
        if r.get("section") == top_section
        and s >= top_score - ambiguity_threshold
        and s > 0
    ]

    # Get unique COR values among close recs
    cors = set(r.get("cor") for _, r in close_recs)

    if len(cors) <= 1:
        return None  # All same COR — no COR-level ambiguity

    # Ambiguity detected: multiple COR levels in the same section
    section_title = close_recs[0][1].get("sectionTitle", "")

    # Group best rec per COR
    by_cor: Dict[str, dict] = {}
    for _s, r in close_recs:
        cor = r.get("cor", "")
        if cor not in by_cor:
            by_cor[cor] = r

    parts = [
        f"Section {top_section} ({section_title}) contains multiple "
        f"recommendations with different strength levels depending on the "
        f"clinical scenario:\n"
    ]
    for cor in sorted(by_cor.keys()):
        r = by_cor[cor]
        loe = r.get("loe", "")
        rec_num = r.get("recNumber", "")
        text = r.get("text", "")[:200]
        parts.append(
            f"- **Rec {rec_num} [COR {cor}, LOE {loe}]:** {text}"
        )
    parts.append(
        "\nCould you provide more detail about the specific clinical "
        "scenario you're asking about?"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section content gatherer for LLM extraction
# ---------------------------------------------------------------------------

def gather_section_content(
    knowledge: Dict[str, Any],
    target_sections: List[str],
    search_terms: List[str],
    max_chars: int = 8000,
    skip_filter: bool = False,
) -> Dict[str, Any]:
    """
    Pull RSS, synopsis, and knowledgeGaps from guideline_knowledge.json
    for the given section numbers.

    Returns:
        {
            "rss": [{"section": ..., "recNumber": ..., "text": ...}, ...],
            "synopsis": [{"section": ..., "text": ...}, ...],
            "knowledge_gaps": [{"section": ..., "text": ...}, ...],
            "has_knowledge_gaps": bool,
            "total_chars": int,
        }
    """
    sections_data = knowledge.get("sections", {})
    rss_entries: List[Dict[str, Any]] = []
    synopses: List[Dict[str, Any]] = []
    kg_entries: List[Dict[str, Any]] = []
    total_chars = 0

    for sec_num in target_sections:
        sec = sections_data.get(sec_num)
        if not sec:
            continue

        # RSS entries
        for rss in sec.get("rss", []):
            text = rss.get("text", "").strip()
            if not text:
                continue
            rss_entries.append({
                "section": sec_num,
                "recNumber": rss.get("recNumber", ""),
                "text": text,
            })
            total_chars += len(text)

        # Synopsis
        synopsis = sec.get("synopsis", "").strip()
        if synopsis:
            synopses.append({"section": sec_num, "text": synopsis})
            total_chars += len(synopsis)

        # Knowledge gaps
        kg = sec.get("knowledgeGaps", "").strip()
        if kg:
            kg_entries.append({"section": sec_num, "text": kg})
            total_chars += len(kg)

    # Pre-filter RSS by keyword relevance when total content is too large
    # skip_filter=True for evidence questions: LLM needs ALL RSS from the
    # target section to avoid dropping critical subgroup/trial data.
    MAX_CHARS = max_chars
    if not skip_filter and total_chars > MAX_CHARS and rss_entries and search_terms:
        scored_rss = []
        for entry in rss_entries:
            relevance = score_text(entry["text"], search_terms)
            scored_rss.append((relevance, entry))
        scored_rss.sort(key=lambda x: -x[0])
        # Keep top entries within char budget
        kept: List[Dict[str, Any]] = []
        chars_used = sum(len(s["text"]) for s in synopses) + sum(len(k["text"]) for k in kg_entries)
        for _, entry in scored_rss:
            if chars_used + len(entry["text"]) > MAX_CHARS:
                break
            kept.append(entry)
            chars_used += len(entry["text"])
        rss_entries = kept
        total_chars = chars_used

    return {
        "rss": rss_entries,
        "synopsis": synopses,
        "knowledge_gaps": kg_entries,
        "has_knowledge_gaps": bool(kg_entries),
        "total_chars": total_chars,
    }


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
    topic_sections, suppressed_sections = extract_topic_sections(question)
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
        elif context.get("lastKnownWellHours") is not None: parts.append(f"LKW {context['lastKnownWellHours']}h")
        elif context.get("timeHours") is not None: parts.append(f"{context['timeHours']}h from symptom recognition")
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

    # ── Evidence / Knowledge Gap LLM extraction branch ──────────────
    # If the question is explicitly about evidence or knowledge gaps,
    # use deterministic section routing + LLM extraction from RSS/synopsis.
    question_type = classify_question_type(question)
    target_sections = section_refs or topic_sections

    if question_type in ("evidence", "knowledge_gap") and target_sections and nlp_service:
        section_content = gather_section_content(
            guideline_knowledge, target_sections, search_terms
        )

        # Knowledge gaps: deterministic response when section has none (61/62 sections)
        if question_type == "knowledge_gap" and not section_content["has_knowledge_gaps"]:
            sec_titles = []
            sections_data = guideline_knowledge.get("sections", {})
            for s in target_sections:
                sd = sections_data.get(s, {})
                if sd.get("sectionTitle"):
                    sec_titles.append(f"{s} ({sd['sectionTitle']})")
            sec_label = ", ".join(sec_titles) if sec_titles else ", ".join(target_sections)
            return {
                "answer": (
                    f"No specific knowledge gaps are documented in the 2026 AHA/ASA AIS "
                    f"guideline for Section {sec_label}. The guideline does not identify "
                    f"explicit areas of uncertainty or future research needs for this topic."
                ),
                "summary": (
                    f"No knowledge gaps are documented for Section {sec_label} in the "
                    f"2026 guideline."
                ),
                "citations": [f"Section {s} -- Knowledge Gaps (none documented)" for s in target_sections],
                "relatedSections": sorted(target_sections),
                "referencedTrials": [],
            }

        # LLM extraction from section content
        llm_answer = await nlp_service.extract_from_section(
            question, section_content, question_type
        )

        if llm_answer:
            # Also run rec scoring for context — include top matching recs
            all_recs_list_for_branch = []
            for rec_id, rec in recommendations_store.items():
                rec_dict = rec if isinstance(rec, dict) else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
                all_recs_list_for_branch.append(rec_dict)
            sec_disc = get_section_discriminators(all_recs_list_for_branch)

            scored_for_context: List[Tuple[int, dict]] = []
            for rec_id, rec in recommendations_store.items():
                rec_dict = rec if isinstance(rec, dict) else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
                score = score_recommendation(
                    rec_dict, search_terms, question=question,
                    section_refs=section_refs, topic_sections=topic_sections,
                    suppressed_sections=suppressed_sections,
                    section_discriminators=sec_disc,
                )
                if score > 0:
                    scored_for_context.append((score, rec_dict))
            scored_for_context.sort(key=lambda x: -x[0])

            # Build combined answer
            answer_parts_branch: List[str] = []
            citations_branch: List[str] = []
            sections_branch: set = set(target_sections)
            type_label = "Evidence" if question_type == "evidence" else "Knowledge Gaps"
            answer_parts_branch.append(f"**{type_label}:**\n{llm_answer}")

            # Add source citations
            for s in target_sections:
                sd = guideline_knowledge.get("sections", {}).get(s, {})
                title = sd.get("sectionTitle", "")
                if question_type == "evidence":
                    citations_branch.append(
                        f"Section {s} -- {title} (Recommendation-Specific Supportive Text)"
                    )
                else:
                    citations_branch.append(
                        f"Section {s} -- {title} (Knowledge Gaps)"
                    )

            # Append top recs for context
            for score, rec in scored_for_context[:3]:
                if score < 1:
                    continue
                cor_badge = f"COR {rec.get('cor', '')}"
                loe_badge = f"LOE {rec.get('loe', '')}"
                badge = f" [{cor_badge}, {loe_badge}]"
                answer_parts_branch.append(
                    f"**Section {rec.get('section', '')}{badge}:** {rec.get('text', '')}"
                )
                citations_branch.append(
                    f"Section {rec.get('section', '')} -- {rec.get('sectionTitle', '')} "
                    f"(COR {rec.get('cor', '')}, LOE {rec.get('loe', '')})"
                )
                sections_branch.add(rec.get("section", ""))

            answer = "\n\n".join(answer_parts_branch)
            unique_citations = list(dict.fromkeys(citations_branch))

            return {
                "answer": answer,
                "summary": llm_answer,
                "citations": unique_citations,
                "relatedSections": sorted(s for s in sections_branch if s),
                "referencedTrials": [],
            }

        # If LLM extraction failed, fall through to existing pipeline

    # Build section discriminators for automatic within-section differentiation
    all_recs_list = []
    for rec_id, rec in recommendations_store.items():
        rec_dict = rec if isinstance(rec, dict) else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
        all_recs_list.append(rec_dict)
    sec_discriminators = get_section_discriminators(all_recs_list)

    # Score all recommendations
    scored: List[Tuple[int, dict]] = []
    for rec_id, rec in recommendations_store.items():
        rec_dict = rec if isinstance(rec, dict) else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
        score = score_recommendation(rec_dict, search_terms, question=question, section_refs=section_refs, topic_sections=topic_sections, suppressed_sections=suppressed_sections, section_discriminators=sec_discriminators)
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
    # Gate for Table 8 contraindication pathway.
    # Must catch BOTH explicit ("is X a contraindication") AND implicit
    # ("can IVT be given to a patient with X") contraindication questions.
    # Implicit detection: check if the question mentions a known Table 8 term
    # in a context that asks about IVT eligibility with that condition.
    _EXPLICIT_CONTRA_TERMS = [
        "contraindication", "contraindicated", "table 8",
        "absolute", "relative",
        "benefit may exceed risk", "benefit over risk", "benefit outweigh",
        "benefit exceed", "benefit likely outweigh",
        "tier of", "tier for", "tier does", "what tier",
        "classified as", "classification",
    ]
    _is_contraindication_q_explicit = any(ct in q_lower for ct in _EXPLICIT_CONTRA_TERMS)

    # Implicit contraindication detection: question asks about IVT eligibility
    # for a condition that is a known Table 8 item. We combine IVT-context
    # keywords with Table 8 condition terms.
    _IVT_CONTEXT = ["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"]
    _TABLE8_CONDITIONS = [
        # Benefit May Exceed Risk conditions
        "extra-axial", "extraaxial", "extra-axial intracranial neoplasm",
        "unruptured aneurysm", "unruptured intracranial aneurysm",
        "moya-moya", "moyamoya",
        "procedural stroke", "angiographic procedural",
        "remote gi", "remote gu", "history of gi bleeding",
        "history of myocardial infarction", "remote mi", "history of mi",
        "recreational drug", "cocaine", "methamphetamine", "illicit drug",
        "substance use", "substance abuse",
        "stroke mimic", "mimic",
        "seizure at onset",
        "cerebral microbleed", "microbleed", "cmb",
        "menstruation", "diabetic retinopathy",
        # Absolute conditions
        "intracranial hemorrhage", "active internal bleeding",
        "extensive hypodensity", "hypodensity", "multilobar infarction",
        "traumatic brain injury", "tbi",
        "neurosurgery", "spinal cord injury",
        "intra-axial", "intraaxial", "brain tumor", "glioma",
        "infective endocarditis", "endocarditis",
        "severe coagulopathy", "coagulopathy",
        "aortic dissection", "aortic arch dissection",
        "aria", "amyloid", "lecanemab", "aducanumab",
        "glucose <50", "blood glucose less than 50",
        # Relative conditions
        "doac within 48", "recent doac",
        "prior intracranial hemorrhage", "prior ich",
        "arterial dissection", "cervical dissection",
        "pregnancy", "pregnant", "postpartum", "post-partum",
        "active malignancy", "active cancer",
        "pre-existing disability", "preexisting disability", "prior disability",
        "vascular malformation", "avm", "cavernoma",
        "pericarditis", "cardiac thrombus",
        "dural puncture", "lumbar puncture",
        "arterial puncture", "noncompressible",
        "amyloid angiopathy",
        "hepatic failure", "liver failure",
        "pancreatitis", "septic embolism",
        "dementia", "dialysis",
    ]
    _has_ivt_context = any(t in q_lower for t in _IVT_CONTEXT)
    _has_t8_condition = any(t in q_lower for t in _TABLE8_CONDITIONS)
    _is_contraindication_q_implicit = _has_ivt_context and _has_t8_condition

    # Also detect: "Can IVT be given to a patient with X?" pattern
    _ELIGIBILITY_WITH_CONDITION = (
        ("can ivt be" in q_lower or "can thrombolysis be" in q_lower or
         "is ivt safe" in q_lower or "eligible for ivt" in q_lower or
         "ivt eligible" in q_lower)
        and _has_t8_condition
    )

    _is_contraindication_q = (
        _is_contraindication_q_explicit or
        _is_contraindication_q_implicit or
        _ELIGIBILITY_WITH_CONDITION
    )

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
        tier = classify_table8_tier(question)
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
            llm_result = await nlp_service.summarize_qa(question, answer, citations, patient_context=patient_ctx)
            # summarize_qa returns {"summary": str, "cited_recs": list}
            summary = llm_result.get("summary", "") if isinstance(llm_result, dict) else str(llm_result)
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
