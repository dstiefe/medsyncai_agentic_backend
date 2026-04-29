# Archived regex extractors and legacy answer_question() from qa_service.py
# Removed in v4 Step 1 — LLM parser handles all extraction.
# Kept here for reference only.

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
