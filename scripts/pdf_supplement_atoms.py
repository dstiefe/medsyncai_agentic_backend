"""
Supplementary atoms that aren't in guideline_knowledge.json but exist
in the PDF. Extracted from /Users/MFS/Desktop/2026 AIS Guidelines.pdf.

Current supplements:
  - Table 1: Associated AHA/ASA Guidelines and Statements
  - Figure 1: Journey of a patient with AIS (title + caption only;
              internal diagram labels would require OCR)
  - Figure 5: Characteristics of an organized specialized inpatient
              care unit (title + caption + characteristic list)

To add more content from the PDF, append to SUPPLEMENT_ATOMS.
"""
from __future__ import annotations

from typing import Any, Dict, List

_CITATION_PREFIX = "2026 AHA/ASA AIS Guideline"


# Table 1 rows — each becomes one atom (9 rows)
_TABLE_1_ROWS = [
    {
        "title": "Prevention of Stroke in Patients With Stroke and Transient Ischemic Attack",
        "organization": "AHA/ASA",
        "year": "2021",
        "category": "guidelines",
    },
    {
        "title": "Guidelines for Adult Stroke Rehabilitation and Recovery",
        "organization": "AHA/ASA",
        "year": "2016",
        "category": "guidelines",
    },
    {
        "title": "Identifying Best Practices for Improving the Evaluation and Management of Stroke in Rural Lower-Resourced Settings",
        "organization": "AHA",
        "year": "2024",
        "category": "scientific_statements",
    },
    {
        "title": "Large-Core Ischemic Stroke Endovascular Treatment",
        "organization": "AHA",
        "year": "2024",
        "category": "scientific_statements",
    },
    {
        "title": "Care of the Patient With AIS (Posthyperacute and Prehospital Discharge)",
        "organization": "AHA",
        "year": "2021",
        "category": "scientific_statements",
    },
    {
        "title": "Care of the Patient With AIS (Prehospital and Acute Phase of Care)",
        "organization": "AHA",
        "year": "2021",
        "category": "scientific_statements",
    },
    {
        "title": "Recommendations for Regional Stroke Destination Plans in Rural, Suburban, and Urban Communities From the Prehospital Stroke System of Care Consensus Conference",
        "organization": "AAN/AHA/ASA/ASN/NAEMSP/NASEMSO/SNIS/SVIN",
        "year": "2021",
        "category": "scientific_statements",
    },
    {
        "title": "Management of Stroke in Neonates and Children",
        "organization": "AHA/ASA",
        "year": "2019",
        "category": "scientific_statements",
    },
    {
        "title": "Comprehensive Overview of Nursing and Interdisciplinary Care of the Acute Ischemic Stroke Patient",
        "organization": "AHA",
        "year": "2009",
        "category": "scientific_statements",
    },
]


def _build_supplement_atoms() -> List[Dict[str, Any]]:
    atoms: List[Dict[str, Any]] = []

    # ── Table 1 rows ──────────────────────────────────────────────
    for i, row in enumerate(_TABLE_1_ROWS, start=1):
        text = (
            f"{row['title']} ({row['organization']}, {row['year']}) — "
            f"Associated guideline/statement for acute ischemic stroke care."
        )
        atoms.append({
            "atom_id": f"atom-table1-row-{i}",
            "atom_type": "table_row",
            "text": text,
            "parent_section": "Table 1",
            "section_title": "Associated AHA/ASA Guidelines and Statements",
            "recNumber": "",
            "cor": "",
            "loe": "",
            "category": row["category"],
            "source_citation": f"{_CITATION_PREFIX}, Table 1 (row {i})",
        })

    # ── Figure 1 ──────────────────────────────────────────────────
    figure_1_caption = (
        "Journey of a patient with AIS. The phases of care and key "
        "management steps and treatments are highlighted to ensure the "
        "most optimal functional outcome. AIS indicates acute ischemic "
        "stroke; EMS, emergency medical services; EVT, endovascular "
        "thrombectomy; MSU, mobile stroke unit; and TNK, tenecteplase."
    )
    atoms.append({
        "atom_id": "atom-figure1",
        "atom_type": "figure",
        "text": f"Figure 1 — Journey of a patient with AIS. {figure_1_caption}",
        "parent_section": "Figure 1",
        "section_title": "Journey of a patient with AIS",
        "recNumber": "",
        "cor": "",
        "loe": "",
        "category": "overview",
        "source_citation": f"{_CITATION_PREFIX}, Figure 1",
    })

    # ── Figure 5 ──────────────────────────────────────────────────
    figure_5_text = (
        "Figure 5 — Characteristics of an organized specialized "
        "inpatient care unit: flow diagram. Characteristics include: "
        "multidisciplinary team (including caregivers) care with "
        "weekly meetings; involvement of caregivers in rehabilitation; "
        "education and training (staff and caregivers); specialization "
        "of staff (interest in stroke and rehabilitation); earlier and "
        "intensive onset of therapy; and medical investigation/treatment "
        "protocols."
    )
    atoms.append({
        "atom_id": "atom-figure5",
        "atom_type": "figure",
        "text": figure_5_text,
        "parent_section": "Figure 5",
        "section_title": "Characteristics of an organized specialized inpatient care unit",
        "recNumber": "",
        "cor": "",
        "loe": "",
        "category": "stroke_unit_care",
        "source_citation": f"{_CITATION_PREFIX}, Figure 5",
    })

    # ── Figure 1 label from PDF earlier report also exists —
    # Figure 2, 3, 4 already atomized in knowledge store, skip.

    return atoms


if __name__ == "__main__":
    import json
    atoms = _build_supplement_atoms()
    print(f"Generated {len(atoms)} supplement atoms")
    for a in atoms:
        print(f"  {a['atom_id']}: {a['section_title']}")
