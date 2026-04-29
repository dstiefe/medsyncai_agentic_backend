"""Authoritative declarative source for guideline tables.

This file is the SOURCE OF TRUTH for every table atom in the v5 atoms
index. The next guideline revision should be applied by editing this
file and re-running `scripts/atomization/build_tables.py` — which will
regenerate all table atoms with correct metadata.

Format
------
Each top-level entry in `TABLES` is a dict describing one guideline
table. Fields:

    table          short id used throughout retrieval ("T3", "T4",
                   "T5", "T6", "T7", "T8", "T9")
    chapter        parent chapter in the guideline ("3.2", "4.6", "4.8")
    master_title   the table's own heading (verbatim from the guideline).
                   Used for operator/audit display; NOT copied onto
                   individual row atoms.
    flat           True if the table has no internal tiers (T3, T5, T6,
                   T9). False if tiered (T4, T7, T8).
    rows           (flat tables only) list of (slug, row_label, text)
                   in the order the guideline prints them.
    subsections    (tiered tables only) list of subsection dicts, each
                   with:
                       tier          integer 1..N
                       title         subsection heading (verbatim)
                       category      slug used as the atomic category
                                     field. Chosen from the original
                                     atomization's categories.
                       intent_affinity list of query intents this
                                      subsection answers
                       rows          list of (slug, row_label, text)
    intent_affinity (flat tables) list of query intents this table
                                  answers

Row slug convention
-------------------
Each row has a short kebab-case slug. The slug is combined with the
table id to produce a deterministic atom_id:

    atom_id = f"atom-{table_id}-{row_slug}"

The slug should be stable across guideline revisions: if a row's
clinical content is the same, keep the slug even if wording is
updated. That way retrieval references and any bookmarks don't break.

Workflow for the next guideline revision
----------------------------------------
1. Open this file. For each table, update row text verbatim from the
   new guideline PDF.
2. Add new rows to `rows` (or to the relevant subsection's `rows`)
   at the correct row order position. Keep old slugs stable when the
   underlying concept is unchanged.
3. Remove rows that no longer appear in the guideline.
4. Run:
       python3 scripts/atomization/build_tables.py
5. Commit the resulting atoms file along with this file.

Text ingested from the 2026 AHA/ASA AIS Guidelines. Content verified
against the clinician's guideline paste during the 2026-04-17 session.
"""
from __future__ import annotations

from typing import Any, Dict, List


TABLES: List[Dict[str, Any]] = [
    # ═════════════════════════════════════════════════════════════
    # T3 — Imaging Criteria Used in the Extended Window Thrombolysis
    # Trials. Sits under §3.2 Initial Imaging for AIS.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T3",
        "chapter": "3.2",
        "master_title": (
            "Imaging Criteria Used in the Extended Window Thrombolysis Trials"
        ),
        "flat": True,
        "category": "extended_window_imaging_criteria",
        "intent_affinity": [
            "time_window_query", "extended_window",
            "imaging_approach", "evidence_for_recommendation",
        ],
        "anchor_terms_shared": [
            "extended window", "IV thrombolysis", "imaging criteria",
            "mismatch", "penumbra", "core volume",
        ],
        "rows": [
            (
                "wake_up", "WAKE-UP",
                "DWI/FLAIR mismatch: presence of an abnormal signal on DWI "
                "and no visible signal change on FLAIR in the region of the "
                "acute stroke",
            ),
            (
                "thaws", "THAWS",
                "DWI/FLAIR mismatch: presence of an abnormal signal on DWI "
                "and no marked signal change on FLAIR in the region of the "
                "acute stroke",
            ),
            (
                "epithet", "EPITHET",
                "PWI/DWI mismatch: PWI/DWI volume ratio >1.2 and PWI\u2013DWI "
                "volume \u226510 mL (PWI volume defined as Tmax >2 s)",
            ),
            (
                "ecass_4", "ECASS-4",
                "PWI/DWI mismatch: PWI/DWI volume ratio of \u22651.2 and PWI "
                "\u226520 mL",
            ),
            (
                "extend", "EXTEND",
                "CTP or DWI/PWI mismatch: ischemic penumbra to core volume "
                "ratio >1.2, penumbra \u2013 core volume >10 mL, and core "
                "volume <70 mL (core defined as <30% of normal regions on CTP "
                "or DWI volume; penumbra defined as Tmax >6 s on CTP or PWI)",
            ),
            (
                "timeless", "TIMELESS",
                "CTP or DWI/PWI mismatch: ischemic penumbra to core volume "
                "ratio >1.8, penumbra volume >15 mL, and core volume <70 mL "
                "(core defined as <30% of normal regions on CTP or DWI volume; "
                "penumbra defined as Tmax >6 s on CTP or PWI using RAPID "
                "automated postprocessing)",
            ),
            (
                "trace_3", "TRACE-3",
                "CTP or DWI/PWI mismatch: ischemic penumbra to core volume "
                "ratio >1.8, penumbra volume >15 mL, and core volume <70 mL "
                "(core defined as <30% of normal regions on CTP or DWI volume; "
                "penumbra defined as Tmax >6 s on CTP or PWI using iStroke "
                "software)",
            ),
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T4 — Guidance for Determining Deficits to be Clearly Disabling
    # at Presentation. Sits under §4.6. Three tiers.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T4",
        "chapter": "4.6",
        "master_title": (
            "Guidance for Determining Deficits to be Clearly Disabling "
            "at Presentation"
        ),
        "flat": False,
        "subsections": [
            {
                "tier": 1,
                "title": (
                    "Framing: basic activities of daily living and "
                    "disabling deficit determination"
                ),
                "category": "disabling_deficit_framing",
                "intent_affinity": [
                    "eligibility_check", "clinical_overview", "overview",
                ],
                "anchor_terms_shared": [
                    "disabling deficit", "NIHSS 0-5", "ADL", "BATHE",
                ],
                "rows": [
                    (
                        "core_question",
                        "Core question (NIHSS 0-5 disabling deficit determination)",
                        "Among patients with NIHSS scores 0\u20135 at "
                        "presentation, if the observed deficits persist, "
                        "would they still be able to do basic activities "
                        "of daily living and/or return to work (if "
                        "applicable)?",
                    ),
                    (
                        "basic_adl_bathe",
                        "Basic activities of daily living (BATHE mnemonic)",
                        "Basic activities of daily living include "
                        "bathing/dressing, ambulating, toileting, hygiene, "
                        "and eating (BATHE mnemonic).",
                    ),
                    (
                        "ambulate_swallow",
                        "Ambulation and swallow assessment",
                        "To fully evaluate the level of deficits, the ability "
                        "to ambulate and swallow independently should be "
                        "assessed.",
                    ),
                    (
                        "clinician_consult",
                        "Clinician determination with patient and family",
                        "The clinician should make this determination in "
                        "consultation with the patient and available family.",
                    ),
                ],
            },
            {
                "tier": 2,
                "title": (
                    "Deficits that would typically be considered clearly "
                    "disabling"
                ),
                "category": "typically_disabling",
                "intent_affinity": [
                    "eligibility_check", "harm_query", "contraindications",
                ],
                "anchor_terms_shared": [
                    "clearly disabling", "NIHSS", "typically disabling",
                ],
                "rows": [
                    (
                        "hemianopsia",
                        "Complete hemianopsia (\u22652 on the NIHSS "
                        "\u201cvision\u201d question)",
                        "Complete hemianopsia (\u22652 on the NIHSS "
                        "\u201cvision\u201d question)",
                    ),
                    (
                        "severe_aphasia",
                        "Severe aphasia (\u22652 on the NIHSS "
                        "\u201cbest language\u201d question)",
                        "Severe aphasia (\u22652 on the NIHSS "
                        "\u201cbest language\u201d question)",
                    ),
                    (
                        "hemi_attention",
                        "Severe hemi-attention or extinction to >1 modality "
                        "(\u22652 on the NIHSS \u201cextinction and "
                        "inattention\u201d question)",
                        "Severe hemi-attention or extinction to >1 modality "
                        "(\u22652 on the NIHSS \u201cextinction and "
                        "inattention\u201d question)",
                    ),
                    (
                        "motor_weakness",
                        "Any weakness limiting sustained effort against "
                        "gravity (\u22652 on the NIHSS \u201cmotor\u201d "
                        "questions)",
                        "Any weakness limiting sustained effort against "
                        "gravity (\u22652 on the NIHSS \u201cmotor\u201d "
                        "questions)",
                    ),
                ],
            },
            {
                "tier": 3,
                "title": (
                    "Deficits that may not be clearly disabling in an "
                    "individual patient"
                ),
                "category": "may_not_be_disabling",
                "intent_affinity": [
                    "no_benefit_query", "eligibility_check", "harm_query",
                ],
                "anchor_terms_shared": [
                    "non-disabling", "mild aphasia", "facial droop",
                ],
                "rows": [
                    ("mild_aphasia",
                     "Isolated mild aphasia (but still able to communicate meaningfully)",
                     "Isolated mild aphasia (but still able to communicate meaningfully)"),
                    ("facial_droop",
                     "Isolated facial droop",
                     "Isolated facial droop"),
                    ("mild_cortical_hand_weakness",
                     "Mild cortical hand weakness (especially nondominant, NIHSS score 0)",
                     "Mild cortical hand weakness (especially nondominant, NIHSS score, 0)"),
                    ("mild_hemimotor_loss",
                     "Mild hemimotor loss",
                     "Mild hemimotor loss"),
                    ("hemisensory_loss",
                     "Hemisensory loss",
                     "Hemisensory loss"),
                    ("mild_hemisensorimotor_loss",
                     "Mild hemisensorimotor loss",
                     "Mild hemisensorimotor loss"),
                    ("mild_hemiataxia",
                     "Mild hemiataxia (but can still ambulate)",
                     "Mild hemiataxia (but can still ambulate)"),
                ],
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T5 — Management of Symptomatic Intracranial Bleeding.
    # §4.6. Flat.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T5",
        "chapter": "4.6",
        "master_title": (
            "Management of Symptomatic Intracranial Bleeding Occurring "
            "Within 24 Hours After Administration of IV Alteplase or "
            "Tenecteplase for Treatment of AIS in Adults"
        ),
        "flat": True,
        "category": "sich_management",
        "intent_affinity": [
            "complication_management", "adverse_event_management",
            "post_treatment_care",
        ],
        "anchor_terms_shared": [
            "sICH", "symptomatic intracranial bleeding", "post-IVT hemorrhage",
            "cryoprecipitate", "tranexamic acid",
        ],
        "rows": [
            ("stop_infusion",
             "Stop alteplase infusion or tenecteplase (if still being pushed)",
             "Stop alteplase infusion or tenecteplase (if still being pushed)"),
            ("emergent_labs",
             "Emergent labs",
             "Emergent CBC, PT (INR), aPTT, fibrinogen level, and type and cross-match"),
            ("emergent_head_ct",
             "Emergent nonenhanced head CT",
             "Emergent nonenhanced head CT if a clinical concern exists"),
            ("cryoprecipitate",
             "Cryoprecipitate",
             "Cryoprecipitate (includes factor VIII): 10 U infused over 10\u201330 min to maintain fibrinogen level of \u2265150 mg/dL; as a rule of thumb 10 U of cryoprecipitate increase fibrinogen level by nearly 50 mg/dL"),
            ("antifibrinolytic",
             "Tranexamic acid or e-aminocaproic acid",
             "Tranexamic acid 1000 mg IV infused over 10 min OR e-aminocaproic acid 4\u20135 g over 1 h, followed by 1 g IV until bleeding is controlled (peak onset in 3 h)"),
            ("consult",
             "Hematology and neurosurgery consultations",
             "Hematology and neurosurgery consultations as necessary"),
            ("supportive",
             "Supportive therapy",
             "Supportive therapy, including BP management, ICP, CPP, MAP, temperature, and glucose control"),
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T6 — Management of Orolingual Angioedema. §4.6. Flat.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T6",
        "chapter": "4.6",
        "master_title": (
            "Management of Orolingual Angioedema Associated With IV "
            "Thrombolytic Administration for AIS in Adults"
        ),
        "flat": True,
        "category": "angioedema_management",
        "intent_affinity": [
            "complication_management", "adverse_event_management",
            "post_treatment_care",
        ],
        "anchor_terms_shared": [
            "angioedema", "orolingual angioedema", "airway management",
            "methylprednisolone", "icatibant",
        ],
        "rows": [
            ("intubation_indications",
             "Endotracheal intubation (indications)",
             "Endotracheal intubation may not be necessary if edema is limited to the anterior tongue and lips."),
            ("rapid_airway_risk",
             "Rapid-progression airway risk",
             "Edema involving the larynx, palate, floor of mouth, or oropharynx with rapid progression (within 30 min) poses a higher risk of requiring intubation."),
            ("awake_fiberoptic",
             "Awake fiberoptic intubation preferred",
             "Awake fiberoptic intubation is optimal. Nasal-tracheal intubation may be required but poses risk of epistaxis after IV thrombolytic use. Cricothyroidotomy is rarely needed and also problematic after IV thrombolytic use."),
            ("stop_thrombolytic_hold_ace",
             "Discontinue IV thrombolytic and hold ACE inhibitors",
             "Discontinue IV thrombolytic infusion (if alteplase) and hold ACE inhibitors."),
            ("methylprednisolone",
             "IV methylprednisolone 125 mg",
             "Administer IV methylprednisolone 125 mg."),
            ("diphenhydramine",
             "IV diphenhydramine 50 mg",
             "Administer IV diphenhydramine 50 mg."),
            ("h2_blocker",
             "Ranitidine or famotidine IV",
             "Administer ranitidine 50 mg IV or famotidine 20 mg IV."),
            ("epinephrine",
             "Epinephrine if progressing",
             "If there is further increase in angioedema, administer 0.1% epinephrine (1 mg/mL concentration) 0.3 mL subcutaneously or by nebulizer 0.5 mg/dL."),
            ("icatibant_c1_inhibitor",
             "Icatibant and C1 esterase inhibitor",
             "Icatibant, a selective bradykinin B2 receptor antagonist, 3 mL (30 mg) subcutaneously in abdominal area; additional injection of 30 mg may be administered at intervals of 6 h not to exceed a total of 3 injections in 24 h; and plasma-derived C1 esterase inhibitor (20 IU/kg) has been successfully used in hereditary angioedema and ACE inhibitor-related angioedema."),
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T7 — Treatment of AIS in Adults: IVT. §4.6. Three tiers.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T7",
        "chapter": "4.6",
        "master_title": "Treatment of AIS in Adults: IVT",
        "flat": False,
        "subsections": [
            {
                "tier": 1,
                "title": "IVT dosing: alteplase and tenecteplase",
                "category": "ivt_dosing",
                "intent_affinity": ["dosing_regimen", "dosing_protocol"],
                "anchor_terms_shared": [
                    "alteplase dose", "tenecteplase dose", "IVT dosing",
                ],
                "rows": [
                    ("alteplase",
                     "Alteplase",
                     "Alteplase: Infuse 0.9 mg/kg (maximum dose 90 mg) over 60 min, with 10% of the dose given as a bolus over 1 min"),
                    ("tenecteplase",
                     "Tenecteplase",
                     "Tenecteplase: Push 0.25 mg/kg (up to maximum 25 mg) based on patient body weight\u2020:"),
                ],
            },
            {
                "tier": 2,
                "title": "Tenecteplase weight-based dosing bands",
                "category": "tenecteplase_weight_band",
                "intent_affinity": ["dosing_regimen", "dosing_protocol"],
                "anchor_terms_shared": [
                    "tenecteplase weight band", "TNK dose", "weight-based dosing",
                ],
                "rows": [
                    ("under_60_kg",  "<60 kg",            "Patient weight <60 kg: tenecteplase 15 mg in 3 mL."),
                    ("60_to_70_kg",  "60 kg to <70 kg",   "Patient weight 60 kg to <70 kg: tenecteplase 17.5 mg in 3.5 mL."),
                    ("70_to_80_kg",  "70 kg to <80 kg",   "Patient weight 70 kg to <80 kg: tenecteplase 20 mg in 4 mL."),
                    ("80_to_90_kg",  "80 kg to <90 kg",   "Patient weight 80 kg to <90 kg: tenecteplase 22.5 mg in 4.5 mL."),
                    ("ge_90_kg",     "\u226590 kg",       "Patient weight \u226590 kg: tenecteplase 25 mg in 5 mL."),
                ],
            },
            {
                "tier": 3,
                "title": "IVT administration and post-treatment monitoring",
                "category": "ivt_administration_step",
                "intent_affinity": [
                    "monitoring_protocol", "post_treatment_care",
                    "complication_management",
                ],
                "anchor_terms_shared": [
                    "post-IVT monitoring", "BP monitoring", "24h follow-up imaging",
                ],
                "rows": [
                    ("admit_icu",
                     "Admit to ICU or stroke unit",
                     "Admit the patient to an intensive care or stroke unit for monitoring"),
                    ("discontinue_deterioration",
                     "Discontinue infusion for deterioration; emergency head CT",
                     "If the patient develops severe headache, acute hypertension, nausea, or vomiting or has a worsening neurological examination, discontinue the infusion (if IV alteplase is being administered) and obtain an emergency head CT scan."),
                    ("bp_neuro_checks",
                     "BP and neurological assessments (q15 min \u00d7 2 h, q30 min \u00d7 6 h, then hourly until 24 h)",
                     "Measure BP and perform neurological assessments every 15 min during and after IVT administration for 2 h, then every 30 min for 6 h, then hourly until 24 h after IV alteplase treatment"),
                    ("elevated_bp_mgmt",
                     "Elevated BP management (SBP >180 or DBP >105)",
                     "Increase the frequency of BP measurements if SBP is >180 mm Hg or if DBP is >105 mm Hg; administer antihypertensive medications to maintain BP at or below these levels"),
                    ("delay_lines",
                     "Delay NG tubes, bladder catheters, arterial lines when possible",
                     "Delay placement of nasogastric tubes, indwelling bladder catheters, or intraarterial pressure catheters if the patient can be safely managed without them"),
                    ("follow_up_imaging",
                     "Follow-up CT or MRI at 24 h before antithrombotics",
                     "Obtain a follow-up CT or MRI scan at 24 h after IVT before starting anticoagulants or antiplatelet agents"),
                ],
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T8 — Other situations wherein thrombolysis is Deemed to be
    # considered. §4.6. Three tiers.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T8",
        "chapter": "4.6",
        "master_title": (
            "Other situations wherein thrombolysis is Deemed to be "
            "considered"
        ),
        "flat": False,
        "subsections": [
            {
                "tier": 1,
                "title": (
                    "Conditions in Which Benefits of Intravenous "
                    "Thrombolysis Generally are Greater Than Risks of "
                    "Bleeding"
                ),
                "category": "benefit_greater_than_risk",
                "intent_affinity": [
                    "eligibility_check", "eligibility_criteria",
                    "patient_specific_eligibility",
                    "evidence_for_recommendation",
                ],
                "anchor_terms_shared": [
                    "benefits greater than risks", "benefit outweighs risk",
                    "IVT eligibility",
                ],
                "rows": [
                    ("extracranial_cervical_dissections",
                     "Extracranial cervical dissections",
                     "IV thrombolysis in AIS known or suspected to be associated with extracranial cervical arterial dissection is reasonably safe within 4.5 h and probably recommended."),
                    ("extra_axial_neoplasms",
                     "Extra-axial intracranial neoplasms",
                     "The risk of harm of IV thrombolysis in patients with AIS and extra-axial intracranial neoplasm is likely low. Benefit likely outweighs risk in this population and IV thrombolysis should be considered."),
                    ("angiographic_procedural_stroke",
                     "Angiographic procedural stroke",
                     "IV thrombolysis in patients with AIS during or immediately post-angiography should be considered as benefit likely outweighs risk in this population."),
                    ("unruptured_aneurysm",
                     "Unruptured intracranial aneurysm",
                     "The risk of harm of IV thrombolysis in patients with AIS and unruptured intracranial aneurysm is likely low. Benefit likely outweighs risk in this population and treatment with IV thrombolysis should be considered."),
                    ("history_gi_gu_bleeding",
                     "History of GI/GU bleeding",
                     "IV thrombolysis in AIS patients with previous remote history of GI or GU bleeding that is stable may be candidates for IV thrombolysis. Consideration of benefit and risk on an individual basis in conjunction with GI or GU consultation is appropriate."),
                    ("history_mi",
                     "History of MI",
                     "IV thrombolysis in AIS patients with remote history of MI probably has greater benefit than risk."),
                    ("recreational_drug_use",
                     "Recreational drug use",
                     "IV thrombolysis in AIS patients with known recreational drug use probably has greater benefit than risk in most patients and should be considered."),
                    ("stroke_mimics",
                     "Uncertainty of stroke diagnosis/stroke mimics",
                     "When uncertain if a patient is presenting with symptoms due to stroke vs a stroke mimic, unless there are absolute contraindications, the risk of harm with IV thrombolysis is low. The benefit of IV thrombolysis likely outweighs risk in these patients."),
                    ("moya_moya",
                     "Moya-Moya",
                     "IV thrombolysis in AIS patients with Moya-Moya disease does not appear to have an increased risk of ICH and likely provides benefit that outweighs risk."),
                ],
            },
            {
                "tier": 2,
                "title": "Conditions That are Relative Contraindications (to IVT)",
                "category": "relative_contraindication",
                "intent_affinity": [
                    "contraindications", "harm_query",
                    "patient_specific_eligibility",
                ],
                "anchor_terms_shared": [
                    "relative contraindications", "individualized assessment",
                ],
                "rows": [
                    ("pre_existing_disability",
                     "Pre-existing disability",
                     "The benefits vs risks of offering IV thrombolysis in patients with pre-existing disability and/or frailty remain uncertain. Treatment should be determined on an individual basis."),
                    ("doac_exposure",
                     "DOAC exposure",
                     "In patients with disabling symptoms and recent DOAC exposure (<48 hours) who are within the window for alteplase/tenecteplase, the safety of IV thrombolysis is unknown. Emerging but limited observational data suggest IV thrombolysis may be considered after a thorough benefit vs risk analysis on an individual basis. Benefit vs risk assessments should include considering the timing of the last DOAC administration, renal function, stroke severity, and availability of endovascular thrombectomy as well as availability of DOAC reversal agents and DOAC-specific anti-factor Xa/thrombin time assays acknowledging the potential for delay in thrombolysis and potential increased thrombotic risk. All aspects of DOAC management (timing, reversal agent use, assay results), should be recorded carefully to facilitate ongoing safety analyses. Definitive clinical trials are needed to establish the safety of IV thrombolysis in DOAC patients."),
                    ("prior_ischemic_stroke_3mo",
                     "Ischemic stroke w/in 3 months",
                     "Use of IV thrombolysis in patients presenting with AIS who have had a prior ischemic stroke within 3 months may be at increased risk of intracranial hemorrhage. Potential increased risk as a result of the timing and size of the stroke should be weighed against the benefits of offering IV thrombolysis in an individualized manner in such patients."),
                    ("prior_ich",
                     "Prior ICH",
                     "IV thrombolysis administration in patients who have a history of ICH may increase the risk of symptomatic hemorrhage. Patients with known amyloid angiopathy may be considered as having higher risk than patients with ICH due to modifiable conditions (e.g. HTN, coagulopathy). IV thrombolysis may have greater treatment benefit than risk in these latter patients. Treatment should be determined on an individual basis."),
                    ("recent_major_trauma_14d_3mo",
                     "Recent major non-CNS trauma (between 14 days and 3 months)",
                     "Patients with recent major trauma between 14 days and 3 months of their AIS may be at increased risk of harm and serious systemic hemorrhage requiring transfusion from IV thrombolysis. Individual consideration of risk vs benefit, involved areas, and consultation with surgical experts are appropriate."),
                    ("recent_major_surgery_10d",
                     "Recent major non-CNS surgery w/in 10 days",
                     "Patients with recent major surgery within 10 days of AIS may be at increased risk of harm from IV thrombolysis. Individual consideration of risk vs benefit, surgical area, and consultation with surgical experts are appropriate."),
                    ("recent_gigu_bleeding_21d",
                     "Recent GI/GU bleeding w/in 21 days",
                     "Patients with recent GI or GU bleeding within 21 days of their AIS may be at increased risk of harm from IV thrombolysis. Individual consideration of risk vs benefit and consultation with GI or GU experts to determine if the GI/GU bleeding has been treated and risk modified/reduced is recommended."),
                    ("intracranial_arterial_dissection",
                     "Intracranial arterial dissection",
                     "The safety of IV thrombolysis in patients with AIS due to intracranial arterial dissection is unknown."),
                    ("intracranial_vascular_malformations",
                     "Intracranial vascular malformations",
                     "The safety of IV thrombolysis for patients presenting with AIS who are known to harbor an unruptured and untreated intracranial vascular malformation is unknown."),
                    ("recent_stemi_3mo",
                     "Recent STEMI w/in 3 months",
                     "Patients with recent STEMI may be at risk for increased harm from IVT. For patients with history of STEMI within 3 months, individual consideration of risk and benefit should be determined in conjunction with an emergent cardiology consultation. For patients with very recent STEMI (previous several days), the risk of hemopericardium should be considered relative to potential benefit. For patients presenting with concurrent AIS and acute STEMI, treatment with IV thrombolysis should be at a dose appropriate for cerebral ischemia and in conjunction with emergent cardiology consultation. Consideration of timing, type and severity of STEMI to determine the risk vs benefit is warranted."),
                    ("acute_pericarditis",
                     "Acute pericarditis",
                     "IV thrombolysis for patients with major AIS likely to produce severe disability and acute pericarditis, may be reasonable in individual cases. Emergent cardiologic consultation is warranted."),
                    ("la_lv_thrombus",
                     "Left atrial or ventricular thrombus",
                     "IV thrombolysis for patients with known left atrial or ventricular thrombus presenting with major AIS likely to produce severe disability may be reasonable in individual cases. Emergent cardiologic consultation is warranted."),
                    ("systemic_active_malignancy",
                     "Systemic active malignancy",
                     "The safety of IV thrombolysis in patients with systemic active malignancy is unknown. Emergent consultation with oncology to assess risk/benefit is warranted. Consideration of type, stage, and active complications of cancer to determine the risk vs benefit is warranted."),
                    ("pregnancy_postpartum",
                     "Pregnancy and post-partum period",
                     "IV thrombolysis may be considered in pregnancy and post-partum period when the benefits of treating moderate or severe stroke outweighs the anticipated risk of uterine bleeding. Emergent obstetrical consultation is warranted."),
                    ("dural_puncture_7d",
                     "Dural puncture w/in 7 days",
                     "IV thrombolysis for patients with AIS post-dural puncture may be considered in individual cases, even in instances when they may have undergone a lumbar dural puncture in the preceding 7 days."),
                    ("arterial_puncture_7d",
                     "Arterial puncture w/in 7 days",
                     "The safety of IV thrombolysis in patients with AIS who have had an arterial puncture of a noncompressible blood vessel (e.g., subclavian artery line) in the 7 days preceding the stroke symptoms is unknown."),
                    ("tbi_14d_3mo",
                     "Moderate to severe traumatic brain injury \u226514 days to 3 months",
                     "IV thrombolysis may be considered in AIS patients with recent moderate to severe traumatic brain injury (between 14 days and 3 months). Careful consideration should be made based on the type and severity of traumatic injury and in consultation with neurosurgical and neurocritical care team members."),
                    ("neurosurgery_14d_3mo",
                     "Neurosurgery \u226514 days to 3 months",
                     "For patients with AIS and a history of intracranial/spinal surgery between 14 days and 3 months, IV thrombolysis may be considered on an individual basis. Consultation with neurosurgical team members is recommended."),
                ],
            },
            {
                "tier": 3,
                "title": (
                    "Conditions that are Considered Absolute "
                    "Contraindications (to IVT)"
                ),
                "category": "absolute_contraindication",
                "intent_affinity": [
                    "contraindications", "harm_query", "no_benefit_query",
                    "patient_specific_eligibility",
                ],
                "anchor_terms_shared": [
                    "absolute contraindications", "IVT contraindicated",
                    "should not be administered",
                ],
                "rows": [
                    ("ct_extensive_hypodensity",
                     "CT with extensive hypodensity",
                     "IV thrombolysis should not be administered to patients whose brain imaging exhibits regions of clear hypodensity that appear to be responsible for the clinical symptoms of stroke. Clear hypodensity is when the degree of hypodensity is greater than the density of contralateral unaffected white matter."),
                    ("ct_hemorrhage",
                     "CT with hemorrhage",
                     "IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage."),
                    ("tbi_lt_14d",
                     "Moderate to severe traumatic brain injury <14 days",
                     "IV thrombolysis is likely contraindicated in AIS patients with recent moderate to severe traumatic brain injury (within 14 days) that incurred >30 minutes of unconsciousness and Glasgow Coma Scale of <13 OR evidence of hemorrhage, contusion, or skull fracture on neuroimaging."),
                    ("neurosurgery_lt_14d",
                     "Neurosurgery <14 days",
                     "For patients with AIS and a history of intracranial/spinal surgery within 14 days, IV thrombolysis is potentially harmful and should not be administered."),
                    ("spinal_cord_injury_3mo",
                     "Acute spinal cord injury within 3 months",
                     "IV thrombolysis is likely contraindicated in AIS patients with spinal cord injury within 3 months."),
                    ("intra_axial_neoplasm",
                     "Intra-axial neoplasm",
                     "For patients with AIS who harbor an intra-axial intracranial neoplasm, treatment with IV thrombolysis is potentially harmful and should not be administered."),
                    ("infective_endocarditis",
                     "Infective endocarditis",
                     "For patients with AIS and symptoms consistent with infective endocarditis, treatment with IV thrombolysis should not be administered."),
                    ("coagulopathy_thrombocytopenia",
                     "Severe coagulopathy or thrombocytopenia",
                     "The safety and efficacy of IV thrombolysis for AIS in patients with platelets <100,000/mm\u00b3, INR>1.7, aPTT>40s, or PT>15s is unknown though may substantially increase risk of harm and should not be administered. In patients without recent use of warfarin or heparin, treatment with IV thrombolysis can be initiated before availability of coagulation test results but should be discontinued if INR >1.7, PT, or PTT is abnormal by local laboratory standards."),
                    ("aortic_arch_dissection",
                     "Aortic arch dissection",
                     "For patients with AIS and known or suspected aortic arch dissection, treatment with IV thrombolysis is potentially harmful and should not be administered"),
                    ("aria",
                     "Amyloid-related imaging abnormalities (ARIA)",
                     "The risk of thrombolysis related ICH in patients on amyloid immunotherapy or with ARIA is unknown and IV thrombolysis should be avoided in such patients."),
                ],
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════
    # T9 — DAPT Trials for Minor AIS and High-Risk TIA. §4.8. Flat.
    # ═════════════════════════════════════════════════════════════
    {
        "table": "T9",
        "chapter": "4.8",
        "master_title": "DAPT Trials",
        "flat": True,
        "category": "dapt_trial",
        "intent_affinity": [
            "treatment_selection", "dosing_regimen",
            "evidence_for_recommendation", "comparison_query",
        ],
        "anchor_terms_shared": [
            "DAPT", "dual antiplatelet therapy", "minor stroke",
            "high-risk TIA",
        ],
        "rows": [
            ("chance",
             "CHANCE",
             "CHANCE \u2014 inclusion: AIS (NIHSS \u22643) or TIA (ABCD \u22654). Regimen: Clopidogrel (300 mg load then 75 mg/d) + ASA (75 mg) x 21 d followed by clopidogrel. LKN 24 h. NNT 28."),
            ("point",
             "POINT",
             "POINT \u2014 inclusion: AIS (NIHSS \u22643) or TIA (ABCD \u22654). Regimen: Clopidogrel (600 mg load then 75 mg/d) + ASA (50\u2013325 mg/d) x 90 d. LKN 12 h. NNT 67."),
            ("thales",
             "THALES",
             "THALES \u2014 inclusion: AIS (NIHSS \u22645) or TIA (ABCD \u22656). Regimen: Ticagrelor (180 mg load then 90 mg twice daily) + ASA (300\u2013325 mg load then 75\u2013100 mg/d) x 30 d. LKN 24 h. NNT 91."),
            ("chance_2",
             "CHANCE 2",
             "CHANCE 2 \u2014 inclusion: AIS (NIHSS \u22645) or TIA (ABCD \u22654) and CYP2C19 loss-of-function allele. Regimen: Ticagrelor (180 mg load then 90 mg twice daily) + ASA (75\u2013300 mg load then 75 mg/d) x 21 d followed by ticagrelor. LKN 24 h. NNT 63."),
            ("inspires",
             "INSPIRES",
             "INSPIRES \u2014 inclusion: AIS (NIHSS \u22645) or TIA (ABCD \u22654), presumed athero. Regimen: Clopidogrel (300 mg load then 75 mg/d) + ASA (100\u2013300 mg load then 100 mg/d) x 21 d followed by clopidogrel. LKN 72 h. NNT 53."),
        ],
    },
]
