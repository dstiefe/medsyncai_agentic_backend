"""Post-retier cleanup and enrichment:

1. Remove 7 concept_section atoms that duplicate content now migrated
   to Table T-sections. (Keep Table 2 atoms — COR/LOE methodology is
   a different reference.)

2. Add one `narrative_context` summary atom per T{N}.{i} section so
   broad queries ("what's in Table 8", "IVT monitoring protocol")
   land on a concise descriptor before drilling into rows. Summaries
   carry the right `intent_affinity` so the scorer steers toward them.

3. Write `references/table_section_intent_map.json` documenting which
   query intents route to which T-section. Read for audit and can be
   consumed later by retrieval as an additional signal.

Usage:
    python3 scripts/finalize_table_retier.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)
INTENT_MAP_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/agents/qa_v6/references/"
    "table_section_intent_map.json"
)

# ─── 1. Concept-section atoms to delete ─────────────────────────────
# Their content has been superseded by the canonical T{N}.{i} atoms.
_CONCEPT_ATOMS_TO_DELETE = {
    "atom-concept-absolute_contraindications_ivt",        # → 4.6.T8.3
    "atom-concept-relative_contraindications_ivt",        # → 4.6.T8.2
    "atom-concept-dapt_trials_evidence",                  # → 4.8.T9
    "atom-concept-disabling_deficits_assessment",         # → 4.6.T4
    "atom-concept-dosing_administration_ivt",             # → 4.6.T7
    "atom-concept-angioedema_management_post_ivt",        # → 4.6.T6
    "atom-concept-sich_management_post_ivt",              # → 4.6.T5
}


# ─── 2. Section summaries (one per T{N}.{i}) ────────────────────────
# Short factual paragraphs. Each becomes a `narrative_context` atom.
# intent_affinity lists the query intents this summary is a strong
# match for — scoring will route relevant questions here.

_SUMMARIES: List[Dict[str, Any]] = [
    {
        "section_id": "4.6.T3",
        "title": "Imaging Criteria Used in the Extended Window Thrombolysis Trials",
        "text": (
            "Imaging inclusion criteria used in the major extended-window IV "
            "thrombolysis trials. WAKE-UP and THAWS used DWI/FLAIR mismatch. "
            "EPITHET and ECASS-4 used PWI/DWI mismatch. EXTEND, TIMELESS, "
            "and TRACE-3 used CTP or DWI/PWI penumbra/core mismatch ratios."
        ),
        "intent_affinity": [
            "time_window", "time_window_query", "extended_window",
            "imaging_approach", "evidence_for_recommendation",
        ],
        "anchor_terms": [
            "extended window", "thrombolysis", "imaging criteria",
            "DWI/FLAIR mismatch", "PWI/DWI mismatch", "CTP perfusion",
            "penumbra", "core volume",
        ],
    },
    {
        "section_id": "4.6.T4",
        "title": "Guidance for Determining Deficits to be Clearly Disabling at Presentation",
        "text": (
            "Framework for deciding whether a minor AIS deficit (NIHSS 0-5) "
            "is clearly disabling. Three tiers: (T4.1) framing question "
            "about basic ADL / BATHE mnemonic, (T4.2) deficits that would "
            "typically be considered clearly disabling, and (T4.3) deficits "
            "that may not be clearly disabling in an individual patient."
        ),
        "intent_affinity": [
            "eligibility_check", "eligibility_criteria",
            "clinical_overview", "overview",
        ],
        "anchor_terms": [
            "disabling deficit", "clearly disabling", "minor stroke",
            "NIHSS 0-5", "deficit assessment",
        ],
    },
    {
        "section_id": "4.6.T4.1",
        "title": "Framing: basic activities of daily living and disabling deficit determination",
        "text": (
            "Among patients with NIHSS scores 0-5 at presentation, if the "
            "observed deficits persist, would they still be able to do "
            "basic activities of daily living (bathing/dressing, ambulating, "
            "toileting, hygiene, eating — the BATHE mnemonic) and/or return "
            "to work? Assess ability to ambulate and swallow independently. "
            "Determination made in consultation with patient and family."
        ),
        "intent_affinity": [
            "eligibility_check", "clinical_overview", "overview",
        ],
        "anchor_terms": [
            "activities of daily living", "ADL", "BATHE",
            "disabling deficit framing",
        ],
    },
    {
        "section_id": "4.6.T4.2",
        "title": "Deficits that would typically be considered clearly disabling",
        "text": (
            "Deficits the guideline considers typically clearly disabling: "
            "complete hemianopsia, severe aphasia, severe hemi-attention or "
            "extinction to more than one modality, and any weakness limiting "
            "sustained effort against gravity. Each maps to an NIHSS item "
            "score of ≥2."
        ),
        "intent_affinity": [
            "eligibility_check", "harm_query", "contraindications",
        ],
        "anchor_terms": [
            "clearly disabling", "hemianopsia", "severe aphasia",
            "hemi-attention", "motor weakness",
        ],
    },
    {
        "section_id": "4.6.T4.3",
        "title": "Deficits that may not be clearly disabling in an individual patient",
        "text": (
            "Deficits generally not considered clearly disabling in an "
            "individual patient: isolated mild aphasia (still able to "
            "communicate meaningfully), isolated facial droop, mild cortical "
            "hand weakness, mild hemimotor loss, hemisensory loss, mild "
            "hemisensorimotor loss, and mild hemiataxia (still able to "
            "ambulate)."
        ),
        "intent_affinity": [
            "no_benefit_query", "eligibility_check", "harm_query",
        ],
        "anchor_terms": [
            "non-disabling", "mild aphasia", "facial droop",
            "mild hand weakness", "hemisensory loss", "hemiataxia",
        ],
    },
    {
        "section_id": "4.6.T5",
        "title": "Management of Symptomatic Intracranial Bleeding Occurring Within 24 Hours After Administration of IV Alteplase or Tenecteplase for Treatment of AIS in Adults",
        "text": (
            "Management algorithm for symptomatic intracranial bleeding "
            "occurring within 24 hours of IV alteplase or tenecteplase. "
            "Stop the thrombolytic infusion, obtain emergent labs (CBC, "
            "PT/INR, aPTT, fibrinogen, type-and-cross) and head CT, give "
            "cryoprecipitate to maintain fibrinogen ≥150 mg/dL, consider "
            "tranexamic acid or e-aminocaproic acid, consult hematology and "
            "neurosurgery, and provide supportive care (BP, ICP, CPP, MAP, "
            "temperature, glucose)."
        ),
        "intent_affinity": [
            "complication_management", "adverse_event_management",
            "post_treatment_care",
        ],
        "anchor_terms": [
            "sICH", "symptomatic intracranial bleeding",
            "post-IVT hemorrhage", "cryoprecipitate", "tranexamic acid",
        ],
    },
    {
        "section_id": "4.6.T6",
        "title": "Management of Orolingual Angioedema Associated With IV Thrombolytic Administration for AIS in Adults",
        "text": (
            "Management algorithm for orolingual angioedema after IV "
            "thrombolytic. Maintain airway (awake fiberoptic intubation "
            "preferred; laryngeal involvement or rapid progression raises "
            "intubation risk). Discontinue alteplase, hold ACE inhibitors, "
            "give IV methylprednisolone 125 mg, IV diphenhydramine 50 mg, "
            "H2 blocker. Escalate to epinephrine if progressing. Consider "
            "icatibant (bradykinin B2 antagonist) and C1 esterase inhibitor."
        ),
        "intent_affinity": [
            "complication_management", "adverse_event_management",
            "post_treatment_care",
        ],
        "anchor_terms": [
            "angioedema", "orolingual angioedema", "airway management",
            "methylprednisolone", "icatibant",
        ],
    },
    {
        "section_id": "4.6.T7",
        "title": "Treatment of AIS in Adults: IVT",
        "text": (
            "Complete IVT administration protocol for AIS in adults. Three "
            "tiers: (T7.1) dosing — alteplase 0.9 mg/kg (max 90 mg, 10% "
            "bolus then 60-min infusion) or tenecteplase 0.25 mg/kg (max "
            "25 mg bolus); (T7.2) tenecteplase weight-based dosing bands; "
            "(T7.3) post-administration monitoring — ICU admit, BP and "
            "neurological checks q15min x2h then q30min x6h then q1h until "
            "24h, delay invasive lines, follow-up CT/MRI at 24h."
        ),
        "intent_affinity": [
            "dosing_regimen", "dosing_protocol", "monitoring_protocol",
            "treatment_protocol",
        ],
        "anchor_terms": [
            "IVT dosing", "IVT administration", "IVT monitoring",
            "alteplase", "tenecteplase",
        ],
    },
    {
        "section_id": "4.6.T7.1",
        "title": "IVT dosing: alteplase and tenecteplase",
        "text": (
            "Alteplase: 0.9 mg/kg (maximum 90 mg) over 60 minutes, with 10% "
            "of the dose given as a bolus over 1 minute. Tenecteplase: "
            "0.25 mg/kg (maximum 25 mg) as a single IV push, dosed by "
            "patient body weight (see T7.2 for weight bands)."
        ),
        "intent_affinity": [
            "dosing_regimen", "dosing_protocol",
        ],
        "anchor_terms": [
            "alteplase dose", "tenecteplase dose", "IVT dosing",
            "0.9 mg/kg", "0.25 mg/kg",
        ],
    },
    {
        "section_id": "4.6.T7.2",
        "title": "Tenecteplase weight-based dosing bands",
        "text": (
            "Tenecteplase weight-band dosing: <60 kg → 15 mg (3 mL); "
            "60 to <70 kg → 17.5 mg (3.5 mL); 70 to <80 kg → 20 mg (4 mL); "
            "80 to <90 kg → 22.5 mg (4.5 mL); ≥90 kg → 25 mg (5 mL). "
            "If <50 kg with accurate weight known, dosing per 1-kg band may "
            "be used. Do not delay thrombolysis to obtain exact weight."
        ),
        "intent_affinity": [
            "dosing_regimen", "dosing_protocol",
        ],
        "anchor_terms": [
            "tenecteplase weight band", "TNK dose", "weight-based dosing",
        ],
    },
    {
        "section_id": "4.6.T7.3",
        "title": "IVT administration and post-treatment monitoring",
        "text": (
            "Post-IVT monitoring protocol. Admit to intensive care or "
            "stroke unit. If severe headache, acute hypertension, nausea, "
            "vomiting, or worsening neurological exam — stop alteplase "
            "infusion and obtain emergent head CT. Measure BP and "
            "neurological assessments every 15 minutes during and after "
            "IVT for 2 hours, then every 30 minutes for 6 hours, then "
            "hourly until 24 hours. Increase BP measurement frequency if "
            "SBP >180 or DBP >105 mm Hg and treat to keep BP at or below "
            "those levels. Delay NG tubes, indwelling catheters, and "
            "intra-arterial pressure lines if safely avoidable. Obtain "
            "follow-up CT or MRI at 24 hours before starting anticoagulants "
            "or antiplatelet agents."
        ),
        "intent_affinity": [
            "monitoring_protocol", "post_treatment_care",
            "complication_management",
        ],
        "anchor_terms": [
            "post-IVT monitoring", "BP monitoring", "neurological checks",
            "24h follow-up imaging",
        ],
    },
    {
        "section_id": "4.6.T8.1",
        "title": "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding",
        "text": (
            "Situations where the benefits of IV thrombolysis generally "
            "outweigh bleeding risks: extracranial cervical dissections, "
            "extra-axial intracranial neoplasms, angiographic procedural "
            "stroke, unruptured intracranial aneurysm, remote history of "
            "GI/GU bleeding, remote history of MI, recreational drug use, "
            "uncertainty of stroke diagnosis / stroke mimics, and Moya-Moya "
            "disease."
        ),
        "intent_affinity": [
            "eligibility_check", "eligibility_criteria",
            "patient_specific_eligibility", "evidence_for_recommendation",
        ],
        "anchor_terms": [
            "benefits greater than risks", "benefit outweighs risk",
            "IVT eligibility",
        ],
    },
    {
        "section_id": "4.6.T8.2",
        "title": "Conditions That are Relative Contraindications (to IVT)",
        "text": (
            "Relative contraindications to IV thrombolysis — conditions "
            "that require individualized benefit/risk assessment before "
            "IVT: pre-existing disability, recent DOAC exposure (<48h), "
            "ischemic stroke within 3 months, prior ICH, recent major "
            "non-CNS trauma (14d-3mo), recent major non-CNS surgery "
            "(<10d), recent GI/GU bleeding (<21d), intracranial arterial "
            "dissection, intracranial vascular malformations, recent STEMI "
            "(<3mo), acute pericarditis, left atrial/ventricular thrombus, "
            "systemic active malignancy, pregnancy/post-partum, dural or "
            "arterial puncture (<7d), moderate-to-severe TBI (14d-3mo), "
            "and neurosurgery (14d-3mo)."
        ),
        "intent_affinity": [
            "contraindications", "harm_query",
            "patient_specific_eligibility",
        ],
        "anchor_terms": [
            "relative contraindications", "individualized assessment",
            "benefit risk analysis",
        ],
    },
    {
        "section_id": "4.6.T8.3",
        "title": "Conditions that are Considered Absolute Contraindications (to IVT)",
        "text": (
            "Absolute contraindications to IV thrombolysis — conditions "
            "where IVT must not be administered: CT with extensive "
            "hypodensity, acute intracranial hemorrhage on CT, moderate-"
            "to-severe TBI within 14 days, neurosurgery within 14 days, "
            "acute spinal cord injury within 3 months, intra-axial "
            "intracranial neoplasm, infective endocarditis, severe "
            "coagulopathy or thrombocytopenia, aortic arch dissection, "
            "and amyloid-related imaging abnormalities (ARIA)."
        ),
        "intent_affinity": [
            "contraindications", "harm_query", "no_benefit_query",
            "patient_specific_eligibility",
        ],
        "anchor_terms": [
            "absolute contraindications", "IVT contraindicated",
            "should not be administered",
        ],
    },
    {
        "section_id": "4.8.T9",
        "title": "DAPT Trials",
        "text": (
            "Dual antiplatelet therapy trials for minor AIS and high-risk "
            "TIA: CHANCE (clopidogrel+ASA 21d, NNT 28), POINT "
            "(clopidogrel+ASA 90d, NNT 67), THALES (ticagrelor+ASA 30d, "
            "NNT 91), CHANCE 2 (ticagrelor+ASA 21d in CYP2C19 "
            "loss-of-function patients, NNT 63), and INSPIRES "
            "(clopidogrel+ASA 21d in presumed athero, NNT 53)."
        ),
        "intent_affinity": [
            "treatment_selection", "dosing_regimen",
            "evidence_for_recommendation", "comparison_query",
        ],
        "anchor_terms": [
            "DAPT", "dual antiplatelet therapy", "CHANCE", "POINT",
            "THALES", "INSPIRES", "minor stroke", "high-risk TIA",
        ],
    },
]


# ─── 3. Intent → section map (for reference / future scoring) ───────
_INTENT_SECTION_MAP = {
    "_doc": (
        "Maps parser query intents to the T{N}.{i} table sections that "
        "most directly answer them. Referenced for audit; retrieval "
        "already reaches these sections via atom.intent_affinity, "
        "atom.category, and the topic-alignment bonus."
    ),
    "version": "1.0",
    "sections": {
        "4.6.T3":   ["time_window_query", "extended_window",
                     "imaging_approach", "evidence_for_recommendation"],
        "4.6.T4":   ["eligibility_check", "eligibility_criteria",
                     "clinical_overview"],
        "4.6.T4.1": ["eligibility_check", "clinical_overview"],
        "4.6.T4.2": ["eligibility_check", "harm_query",
                     "contraindications"],
        "4.6.T4.3": ["no_benefit_query", "eligibility_check",
                     "harm_query"],
        "4.6.T5":   ["complication_management", "adverse_event_management",
                     "post_treatment_care"],
        "4.6.T6":   ["complication_management", "adverse_event_management",
                     "post_treatment_care"],
        "4.6.T7":   ["dosing_regimen", "dosing_protocol",
                     "monitoring_protocol", "treatment_protocol"],
        "4.6.T7.1": ["dosing_regimen", "dosing_protocol"],
        "4.6.T7.2": ["dosing_regimen", "dosing_protocol"],
        "4.6.T7.3": ["monitoring_protocol", "post_treatment_care",
                     "complication_management"],
        "4.6.T8":   ["contraindications", "harm_query",
                     "patient_specific_eligibility"],
        "4.6.T8.1": ["eligibility_check", "eligibility_criteria",
                     "patient_specific_eligibility",
                     "evidence_for_recommendation"],
        "4.6.T8.2": ["contraindications", "harm_query",
                     "patient_specific_eligibility"],
        "4.6.T8.3": ["contraindications", "harm_query",
                     "no_benefit_query", "patient_specific_eligibility"],
        "4.8.T9":   ["treatment_selection", "dosing_regimen",
                     "evidence_for_recommendation", "comparison_query"],
    },
}


def _short_label(section_id: str) -> str:
    """'4.6.T8.3' → 'T8.3'; '4.6.T5' → 'T5'; '4.8.T9' → 'T9'."""
    idx = section_id.find(".T")
    if idx >= 0:
        return section_id[idx + 1:]
    return section_id


def _chapter(section_id: str) -> str:
    """'4.6.T8.3' → '4.6'; '4.8.T9' → '4.8'."""
    idx = section_id.find(".T")
    if idx >= 0:
        return section_id[:idx]
    return section_id


def _embed(text: str):
    """Produce a 384-dim list embedding using the runtime model."""
    # Import lazily so the rest of the script can run even if the
    # package path isn't set up.
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.agents.clinical.ais_clinical_engine.agents.qa_v6 import (
        semantic_service,
    )
    vec = semantic_service.embed_query(text)
    return [float(x) for x in vec]


def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms: List[Dict[str, Any]] = data.get("atoms", [])

    # ── 1. Drop overlapping concept_section atoms ────────────────
    before = len(atoms)
    atoms = [a for a in atoms if a.get("atom_id") not in _CONCEPT_ATOMS_TO_DELETE]
    dropped = before - len(atoms)

    # ── 2. Add / refresh section summary atoms ───────────────────
    added = 0
    for s in _SUMMARIES:
        sid = s["section_id"]
        atom_id = f"atom-tsec-summary-{sid}"
        # Idempotent — remove any prior version, then add fresh
        atoms = [a for a in atoms if a.get("atom_id") != atom_id]
        atoms.append({
            "atom_id": atom_id,
            "atom_type": "narrative_context",
            "parent_section": sid,
            "section_path": [_chapter(sid), _short_label(sid), s["title"]],
            "section_title": s["title"],
            "category": "table_section_summary",
            "text": s["text"],
            "anchor_terms": s.get("anchor_terms", []),
            "intent_affinity": s.get("intent_affinity", []),
            "cor": "",
            "loe": "",
            "value_ranges": {},
            "embedding": _embed(s["text"]),
        })
        added += 1

    data["atoms"] = atoms
    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # ── 3. Write intent → section map ────────────────────────────
    with open(INTENT_MAP_PATH, "w") as f:
        json.dump(_INTENT_SECTION_MAP, f, indent=2, ensure_ascii=False)

    print(f"Dropped {dropped} legacy concept atoms.")
    print(f"Wrote/refreshed {added} section summary atoms with embeddings.")
    print(f"Wrote intent→section map to {INTENT_MAP_PATH.name}.")
    print()
    print(f"Final atom count: {len(atoms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
