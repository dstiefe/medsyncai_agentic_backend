"""Add `row_label` field to each T8.1/T8.2/T8.3 row atom.

Row labels come verbatim from the 2026 AIS guideline's Table 8 —
each condition is introduced by a short heading (e.g. "Amyloid-related
imaging abnormalities (ARIA)") followed by a colon and the descriptive
sentence. Atomization stored only the sentence; this pass adds the
heading back as `row_label` so the presenter can emit bedside-friendly
"• <label>: <text>" bullets matching the guideline's own formatting.

Idempotent. Extend `_ROW_LABELS` for further tables (T4, T7.2, T9, etc.)
as content is confirmed.

Usage:
    python3 scripts/add_row_labels.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)

# atom_id → (row_order, row_label)
# row_order is the 1-based position in the guideline, so enumerative
# answers render in the same order a clinician sees in the PDF rather
# than score order (essentially random for similarly-gated rows).
_ROW_META: Dict[str, tuple] = {
    # ── T4.1 — Framing (narrative form, 4 items) ─────────────────
    "atom-table4-row-01": (1, "Core question (NIHSS 0-5 disabling deficit determination)"),
    "atom-table4-row-02": (2, "Basic activities of daily living (BATHE mnemonic)"),
    "atom-table4-row-03": (3, "Ambulation and swallow assessment"),
    "atom-table4-row-04": (4, "Clinician determination with patient and family"),

    # ── T4.2 — Typically clearly disabling (4 items) ─────────────
    "atom-rss-Table 4-disabling_1": (1, "Complete hemianopsia (≥2 on the NIHSS \u201cvision\u201d question)"),
    "atom-rss-Table 4-disabling_2": (2, "Severe aphasia (≥2 on the NIHSS \u201cbest language\u201d question)"),
    "atom-rss-Table 4-disabling_3": (3, "Severe hemi-attention or extinction to >1 modality (≥2 on the NIHSS \u201cextinction and inattention\u201d question)"),
    "atom-rss-Table 4-disabling_4": (4, "Any weakness limiting sustained effort against gravity (≥2 on the NIHSS \u201cmotor\u201d questions)"),

    # ── T4.3 — May not be clearly disabling (7 items) ────────────
    "atom-rss-Table 4-not_disabling_1": (1, "Isolated mild aphasia (but still able to communicate meaningfully)"),
    "atom-rss-Table 4-not_disabling_2": (2, "Isolated facial droop"),
    "atom-rss-Table 4-not_disabling_3": (3, "Mild cortical hand weakness (especially nondominant, NIHSS score 0)"),
    "atom-rss-Table 4-not_disabling_4": (4, "Mild hemimotor loss"),
    "atom-rss-Table 4-not_disabling_5": (5, "Hemisensory loss"),
    "atom-rss-Table 4-not_disabling_6": (6, "Mild hemisensorimotor loss"),
    "atom-rss-Table 4-not_disabling_7": (7, "Mild hemiataxia (but can still ambulate)"),

    # ── T5 — sICH management (7 steps) ───────────────────────────
    "atom-rss-Table 5-1": (1, "Stop alteplase infusion or tenecteplase (if still being pushed)"),
    "atom-rss-Table 5-2": (2, "Emergent labs"),
    "atom-rss-Table 5-3": (3, "Emergent nonenhanced head CT"),
    "atom-rss-Table 5-4": (4, "Cryoprecipitate"),
    "atom-rss-Table 5-5": (5, "Tranexamic acid or e-aminocaproic acid"),
    "atom-rss-Table 5-6": (6, "Hematology and neurosurgery consultations"),
    "atom-rss-Table 5-7": (7, "Supportive therapy"),

    # ── T6 — Orolingual angioedema management (9 steps) ──────────
    "atom-rss-Table 6-1": (1, "Endotracheal intubation (indications)"),
    "atom-rss-Table 6-2": (2, "Rapid-progression airway risk"),
    "atom-rss-Table 6-3": (3, "Awake fiberoptic intubation preferred"),
    "atom-rss-Table 6-4": (4, "Discontinue IV thrombolytic and hold ACE inhibitors"),
    "atom-rss-Table 6-5": (5, "IV methylprednisolone 125 mg"),
    "atom-rss-Table 6-6": (6, "IV diphenhydramine 50 mg"),
    "atom-rss-Table 6-7": (7, "Ranitidine or famotidine IV"),
    "atom-rss-Table 6-8": (8, "Epinephrine if progressing"),
    "atom-rss-Table 6-9": (9, "Icatibant and C1 esterase inhibitor"),

    # ── T8.1 — Benefits greater than risks (guideline order) ─────
    "atom-rss-Table 8-extracranial-cervical-dissections":               (1, "Extracranial cervical dissections"),
    "atom-rss-Table 8-extra-axial-intracranial-neoplasms":              (2, "Extra-axial intracranial neoplasms"),
    "atom-rss-Table 8-angiographic-procedural-stroke":                  (3, "Angiographic procedural stroke"),
    "atom-rss-Table 8-unruptured-intracranial-aneurysm":                (4, "Unruptured intracranial aneurysm"),
    "atom-rss-Table 8-history-of-gigu-bleeding":                        (5, "History of GI/GU bleeding"),
    "atom-rss-Table 8-history-of-mi":                                   (6, "History of MI"),
    "atom-rss-Table 8-recreational-drug-use":                           (7, "Recreational drug use"),
    "atom-rss-Table 8-uncertainty-of-stroke-diagnosisstroke-mimics":    (8, "Uncertainty of stroke diagnosis/stroke mimics"),
    "atom-rss-Table 8-moya-moya":                                       (9, "Moya-Moya"),

    # ── T8.2 — Relative contraindications (guideline order) ──────
    "atom-rss-Table 8-pre-existing-disability":                         (1, "Pre-existing disability"),
    "atom-rss-Table 8-doac-exposure":                                   (2, "DOAC exposure"),
    "atom-rss-Table 8-ischemic-stroke-within-3-months":                 (3, "Ischemic stroke w/in 3 months"),
    "atom-rss-Table 8-prior-ich":                                       (4, "Prior ICH"),
    "atom-rss-Table 8-recent-major-non-cns-trauma-between-14-days-and-3-months": (5, "Recent major non-CNS trauma (between 14 days and 3 months)"),
    "atom-rss-Table 8-recent-major-non-cns-surgery-within-10-days":     (6, "Recent major non-CNS surgery w/in 10 days"),
    "atom-rss-Table 8-recent-gigu-bleeding-within-21-days":             (7, "Recent GI/GU bleeding w/in 21 days"),
    "atom-rss-Table 8-intracranial-arterial-dissection":                (8, "Intracranial arterial dissection"),
    "atom-rss-Table 8-intracranial-vascular-malformations":             (9, "Intracranial vascular malformations"),
    "atom-rss-Table 8-recent-stemi-within-3-months":                    (10, "Recent STEMI w/in 3 months"),
    "atom-rss-Table 8-acute-pericarditis":                              (11, "Acute pericarditis"),
    "atom-rss-Table 8-left-atrial-or-ventricular-thrombus":             (12, "Left atrial or ventricular thrombus"),
    "atom-rss-Table 8-systemic-active-malignancy":                      (13, "Systemic active malignancy"),
    "atom-rss-Table 8-pregnancy-and-post-partum-period":                (14, "Pregnancy and post-partum period"),
    "atom-rss-Table 8-dural-puncture-within-7-days":                    (15, "Dural puncture w/in 7 days"),
    "atom-rss-Table 8-arterial-puncture-within-7-days":                 (16, "Arterial puncture w/in 7 days"),
    "atom-rss-Table 8-moderate-to-severe-traumatic-brain-injury-between-14-days-and-3-months": (17, "Moderate to severe traumatic brain injury ≥14 days to 3 months"),
    "atom-rss-Table 8-neurosurgery-between-14-days-and-3-months":       (18, "Neurosurgery ≥14 days to 3 months"),

    # ── T8.3 — Absolute contraindications (guideline order) ──────
    "atom-rss-Table 8-ct-with-extensive-hypodensity":                   (1, "CT with extensive hypodensity"),
    "atom-rss-Table 8-ct-with-hemorrhage":                              (2, "CT with hemorrhage"),
    "atom-rss-Table 8-moderate-to-severe-traumatic-brain-injury-14-days": (3, "Moderate to severe traumatic brain injury <14 days"),
    "atom-rss-Table 8-neurosurgery-14-days":                            (4, "Neurosurgery <14 days"),
    "atom-rss-Table 8-acute-spinal-cord-injury-within-3-months":        (5, "Acute spinal cord injury within 3 months"),
    "atom-rss-Table 8-intra-axial-neoplasm":                            (6, "Intra-axial neoplasm"),
    "atom-rss-Table 8-infective-endocarditis":                          (7, "Infective endocarditis"),
    "atom-rss-Table 8-severe-coagulopathy-or-thrombocytopenia":         (8, "Severe coagulopathy or thrombocytopenia"),
    "atom-rss-Table 8-aortic-arch-dissection":                          (9, "Aortic arch dissection"),
    "atom-rss-Table 8-amyloid-related-imaging-abnormalities-aria":      (10, "Amyloid-related imaging abnormalities (ARIA)"),

    # ── T7.1 — IVT dosing (2 items: alteplase + tenecteplase) ────
    # step_1 and step_2 are moved from T7.3 → T7.1 by _RE_PARENT
    # below, because the atomizer mis-bucketed them.
    "atom-rss-Table 7-step_1": (1, "Alteplase"),
    "atom-rss-Table 7-step_2": (2, "Tenecteplase"),

    # ── T7.2 — Tenecteplase weight bands (5 items) ───────────────
    "atom-rss-Table 7-tnk_weight__60_kg":         (1, "<60 kg"),
    "atom-rss-Table 7-tnk_weight_60_kg_to_70_kg": (2, "60 kg to <70 kg"),
    "atom-rss-Table 7-tnk_weight_70_kg_to_80_kg": (3, "70 kg to <80 kg"),
    "atom-rss-Table 7-tnk_weight_80_kg_to_90_kg": (4, "80 kg to <90 kg"),
    "atom-rss-Table 7-tnk_weight__90_kg":         (5, "≥90 kg"),

    # ── T7.3 — Administration & monitoring (6 items) ─────────────
    "atom-rss-Table 7-step_3": (1, "Admit to ICU or stroke unit"),
    "atom-rss-Table 7-step_4": (2, "Discontinue infusion for deterioration; emergency head CT"),
    "atom-rss-Table 7-step_5": (3, "BP and neurological assessments (q15 min × 2 h, q30 min × 6 h, then hourly until 24 h)"),
    "atom-rss-Table 7-step_6": (4, "Elevated BP management (SBP >180 or DBP >105)"),
    "atom-rss-Table 7-step_7": (5, "Delay NG tubes, bladder catheters, arterial lines when possible"),
    "atom-rss-Table 7-step_8": (6, "Follow-up CT or MRI at 24 h before antithrombotics"),

    # ── T9 — DAPT trials (guideline order: CHANCE, POINT, THALES,
    #        CHANCE 2, INSPIRES) ─────────────────────────────────
    "atom-rss-Table 9-chance":    (1, "CHANCE"),
    "atom-rss-Table 9-point":     (2, "POINT"),
    "atom-rss-Table 9-thales":    (3, "THALES"),
    "atom-rss-Table 9-chance_2":  (4, "CHANCE 2"),
    "atom-rss-Table 9-inspires":  (5, "INSPIRES"),

    # ── T3 — Imaging Criteria for Extended Window Trials ─────────
    # Clinician-confirmed parent chapter is §3.2 (Initial Imaging
    # for AIS), not §4.6.3 as the retier originally placed it.
    # _RE_PARENT below moves them to 3.2.T3.*
    "atom-rss-Table 3-wake_up":  (1, "WAKE-UP"),
    "atom-rss-Table 3-thaws":    (2, "THAWS"),
    "atom-rss-Table 3-epithet":  (3, "EPITHET"),
    "atom-rss-Table 3-ecass_4":  (4, "ECASS-4"),
    "atom-rss-Table 3-extend":   (5, "EXTEND"),
    "atom-rss-Table 3-timeless": (6, "TIMELESS"),
    "atom-rss-Table 3-trace_3":  (7, "TRACE-3"),
}


# Re-parenting: atomizer / earlier migrations placed some atoms under
# the wrong parent_section. Each entry moves the atom to its correct
# section_id with an updated section_path.
#
#  atom_id → (new_parent_section, new_section_path_short_label,
#             new_section_title)
_RE_PARENT: Dict[str, tuple] = {
    # T7 — dose instructions lived under T7.3 Administration
    "atom-rss-Table 7-step_1": (
        "4.6.T7.1", "T7.1", "IVT dosing: alteplase and tenecteplase",
    ),
    "atom-rss-Table 7-step_2": (
        "4.6.T7.1", "T7.1", "IVT dosing: alteplase and tenecteplase",
    ),
    # T3 — clinician-confirmed parent chapter is §3.2 (Initial
    # Imaging for AIS), not §4.6. Move the 7 trial rows + section
    # summary to the correct chapter.
    "atom-rss-Table 3-wake_up":  ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-thaws":    ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-epithet":  ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-ecass_4":  ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-extend":   ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-timeless": ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-rss-Table 3-trace_3":  ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
    "atom-tsec-summary-4.6.T3":  ("3.2.T3", "T3", "Imaging Criteria Used in the Extended Window Thrombolysis Trials"),
}


# Legacy concept_section atoms whose content is now covered by
# the canonical T{N}.{i} row atoms + their subsection summary atoms.
# Drop so enumerative answers don't surface a parallel description.
_LEGACY_CONCEPTS_TO_DROP = {
    "atom-concept-extended_window_imaging_criteria",  # → T3 (rows + summary)
    "atom-concept-benefit_outweighs_risk_ivt",        # → T8.1 (rows + summary)
}


# Narrative duplicate atoms that parallel the clean table-row atoms
# above. Same content in reworded form — drop them so enumerative
# answers return each row once in guideline order.
_NARRATIVE_DUPES_TO_DROP = set(
    # T4.2 narrative duplicates (rows 05-08 of atom-table4-row-*)
    [f"atom-table4-row-{i:02}" for i in range(5, 9)]
    # T4.3 narrative duplicates (rows 09-15)
    + [f"atom-table4-row-{i:02}" for i in range(9, 16)]
    # T5 narrative duplicates
    + [f"atom-table5-row-{i:02}" for i in range(1, 9)]
    # T6 narrative duplicates
    + [f"atom-table6-row-{i:02}" for i in range(1, 12)]
    # T7 narrative duplicates (all 14 — they duplicate either the
    # clean step_* atoms in T7.3 or the tnk_weight_* atoms in T7.2)
    + [f"atom-table7-row-{i:02}" for i in range(1, 15)]
    # T9 narrative duplicates — 5 rewritten versions of each trial
    + [f"atom-table9-row-{i:02}" for i in range(1, 6)]
)

# Extra atoms not in the guideline's printed content
_EXTRA_TO_DROP = {
    "atom-rss-Table 6-10",  # "Provide supportive care." — not in T6 paste
    "atom-rss-Table 7-step_9",  # footnote text (pediatric / weight-band
                                # guidance), not a care step
}


def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms = data.get("atoms", [])
    if not atoms:
        print(f"No atoms found in {ATOMS_PATH}")
        return 1

    # 1. Drop narrative duplicates + extras + legacy concepts
    before = len(atoms)
    drop_ids = _NARRATIVE_DUPES_TO_DROP | _EXTRA_TO_DROP | _LEGACY_CONCEPTS_TO_DROP
    atoms = [a for a in atoms if a.get("atom_id") not in drop_ids]
    dropped = before - len(atoms)

    # 2. Re-parent mis-bucketed atoms
    reparented = 0
    for a in atoms:
        atom_id = a.get("atom_id", "")
        if atom_id in _RE_PARENT:
            new_sid, new_short, new_title = _RE_PARENT[atom_id]
            if a.get("parent_section") != new_sid:
                chapter = new_sid.split(".T", 1)[0]
                a["parent_section"] = new_sid
                a["section_path"] = [chapter, new_short, new_title]
                a["section_title"] = new_title
                reparented += 1

    # 3. Apply row_label + row_order
    updated = 0
    for a in atoms:
        atom_id = a.get("atom_id", "")
        if atom_id in _ROW_META:
            row_order, row_label = _ROW_META[atom_id]
            changed = False
            if a.get("row_label") != row_label:
                a["row_label"] = row_label
                changed = True
            if a.get("row_order") != row_order:
                a["row_order"] = row_order
                changed = True
            if changed:
                updated += 1

    data["atoms"] = atoms
    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Dropped {dropped} narrative-duplicate / extra atoms.")
    print(f"Re-parented {reparented} atoms to correct subsection.")
    print(f"Added/refreshed row_label + row_order on {updated} atoms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
