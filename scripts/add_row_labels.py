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
# row_order is the 1-based position in the guideline's Table 8, so
# enumerative "what are the absolute contraindications" answers can
# render in the same order a clinician sees in the PDF rather than
# score order (which is essentially random for similarly-gated rows).
_ROW_META: Dict[str, tuple] = {
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
}


def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms = data.get("atoms", [])
    if not atoms:
        print(f"No atoms found in {ATOMS_PATH}")
        return 1

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

    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Added/refreshed row_label + row_order on {updated} atoms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
