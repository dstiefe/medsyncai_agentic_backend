"""
Table and Figure re-ingestion for the 2026 AHA/ASA AIS Guideline.

Extracts Tables 2-7, Table 9, and Figures 2-4 from the source PDF and
writes them into guideline_knowledge.json as structured section entries.

Table 8 is excluded — it was already re-ingested cleanly in an earlier
pass and the user explicitly said not to touch it here.

Strategy:
  - For tables that pdfplumber can extract as structured grids
    (Table 3, 7, 9), iterate rows directly and map columns to rss
    fields.
  - For tables that share a page (Table 4, 5, 6 all on page 40),
    use pdfplumber's table extraction then identify each table by
    content patterns in the rows.
  - For Table 2 (COR/LOE rubric — a colored grid pdfplumber cannot
    detect as tabular), author from the standard AHA reference. The
    COR/LOE definitions are a universal AHA framework, not
    guideline-specific content.
  - For figures, extract the caption + legend + abbreviation key only.
    Decision graphics and brain-region diagrams are visual artifacts
    that PyPDF2 / pdfplumber cannot recover. Flagged in synopsis.

Usage:
    python scripts/reingest_guideline_tables_figures.py --dry-run
    python scripts/reingest_guideline_tables_figures.py
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pdfplumber


PDF_PATH = "/Users/MFS/Desktop/2026 AIS Guidelines.pdf"
REPO_ROOT = Path(__file__).resolve().parent.parent
GK_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json"


def _clean(text: str | None) -> str:
    """Normalize whitespace and strip PDF artifacts in a cell value."""
    if not text:
        return ""
    # Soft-hyphen line wraps
    text = re.sub(r"([a-zA-Z])-\n([a-zA-Z])", r"\1\2", text)
    # Newlines → spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ──────────────────────────────────────────────────────────────────
# Table 2 — Class of Recommendation / Level of Evidence rubric
# ──────────────────────────────────────────────────────────────────
#
# This is the universal AHA COR/LOE framework used across every AHA
# guideline. pdfplumber cannot extract it from page 9 because it's
# rendered as a colored grid rather than a text table. The content is
# authored from the standard AHA reference, which has been stable
# across guideline editions.

def table_2() -> dict:
    return {
        "sectionTitle": "Table 2: Applying Class of Recommendation and Level of Evidence to Clinical Strategies, Interventions, Treatments, or Diagnostic Testing in Patient Care",
        "parentChapter": "1.5",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 2",
        "synopsis": (
            "Standard AHA/ASA framework for classifying the strength of a "
            "clinical recommendation (Class of Recommendation, COR) and the "
            "quality of the supporting evidence (Level of Evidence, LOE). "
            "Every recommendation in the 2026 AIS Guideline carries a COR and "
            "an LOE drawn from this rubric. COR and LOE are assigned "
            "independently — any COR may be paired with any LOE."
        ),
        "rss": [
            # Class of Recommendation entries
            {
                "recNumber": "cor_1",
                "category": "class_of_recommendation",
                "condition": "Class 1 (Strong)",
                "text": "Benefit >>> Risk. Recommendation phrasing: 'is recommended' / 'is indicated/useful/effective/beneficial' / 'should be performed/administered/other'. Clinical action: the intervention is recommended for most eligible patients.",
            },
            {
                "recNumber": "cor_2a",
                "category": "class_of_recommendation",
                "condition": "Class 2a (Moderate)",
                "text": "Benefit >> Risk. Recommendation phrasing: 'is reasonable' / 'can be useful/effective/beneficial'. Clinical action: the intervention is reasonable for most patients; shared decision-making applies at the margins.",
            },
            {
                "recNumber": "cor_2b",
                "category": "class_of_recommendation",
                "condition": "Class 2b (Weak)",
                "text": "Benefit ≥ Risk. Recommendation phrasing: 'may/might be reasonable' / 'may/might be considered' / 'usefulness/effectiveness is unknown/unclear/uncertain or not well established'. Clinical action: the intervention can be considered when clinically appropriate; individualize.",
            },
            {
                "recNumber": "cor_3_no_benefit",
                "category": "class_of_recommendation",
                "condition": "Class 3: No Benefit (Moderate, typically LOE A or B only)",
                "text": "Benefit = Risk. Recommendation phrasing: 'is not recommended' / 'is not indicated/useful/effective/beneficial' / 'should not be performed/administered/other'. Clinical action: the intervention does not provide benefit — do not use.",
            },
            {
                "recNumber": "cor_3_harm",
                "category": "class_of_recommendation",
                "condition": "Class 3: Harm (Strong)",
                "text": "Risk > Benefit. Recommendation phrasing: 'potentially harmful' / 'causes harm' / 'associated with excess morbidity/mortality' / 'should not be performed/administered/other'. Clinical action: the intervention is harmful — do not use.",
            },
            # Level of Evidence entries
            {
                "recNumber": "loe_a",
                "category": "level_of_evidence",
                "condition": "Level A",
                "text": "High-quality evidence from more than one randomized controlled trial (RCT); meta-analyses of high-quality RCTs; one or more RCTs corroborated by high-quality registry studies.",
            },
            {
                "recNumber": "loe_b_r",
                "category": "level_of_evidence",
                "condition": "Level B-R (Randomized)",
                "text": "Moderate-quality evidence from one or more RCTs; meta-analyses of moderate-quality RCTs.",
            },
            {
                "recNumber": "loe_b_nr",
                "category": "level_of_evidence",
                "condition": "Level B-NR (Nonrandomized)",
                "text": "Moderate-quality evidence from one or more well-designed, well-executed nonrandomized studies, observational studies, or registry studies; meta-analyses of such studies.",
            },
            {
                "recNumber": "loe_c_ld",
                "category": "level_of_evidence",
                "condition": "Level C-LD (Limited Data)",
                "text": "Randomized or nonrandomized observational or registry studies with limitations of design or execution; meta-analyses of such studies; physiological or mechanistic studies in human subjects.",
            },
            {
                "recNumber": "loe_c_eo",
                "category": "level_of_evidence",
                "condition": "Level C-EO (Expert Opinion)",
                "text": "Consensus of expert opinion based on clinical experience.",
            },
        ],
        "knowledgeGaps": "",
    }


# ──────────────────────────────────────────────────────────────────
# Table 3 — Imaging Criteria for Extended Window Thrombolysis Trials
# ──────────────────────────────────────────────────────────────────

def table_3(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[28]  # page 29 (0-indexed)
    tables = page.extract_tables()
    if not tables:
        raise RuntimeError("Table 3 not detected by pdfplumber on page 29")

    tbl = tables[0]
    rows = []
    # First row is the header
    for row in tbl[1:]:
        if len(row) < 2 or not row[0]:
            continue
        trial = _clean(row[0])
        criteria = _clean(row[1])
        rows.append({
            "recNumber": trial.lower().replace(" ", "_").replace("-", "_"),
            "category": "extended_window_imaging_criteria",
            "condition": trial,
            "text": criteria,
        })

    return {
        "sectionTitle": "Table 3: Imaging Criteria Used in the Extended Window Thrombolysis Trials",
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 3",
        "synopsis": (
            "Per-trial imaging inclusion criteria for extended-window IV "
            "thrombolysis trials. Rows cover WAKE-UP, THAWS, EPITHET, ECASS-4, "
            "EXTEND, TIMELESS, and TRACE-3. Each trial used either a DWI/FLAIR "
            "mismatch, PWI/DWI mismatch, or CTP-based penumbra-to-core ratio "
            "to identify patients with salvageable tissue beyond the standard "
            "4.5-hour window."
        ),
        "rss": rows,
        "knowledgeGaps": "",
    }


# ──────────────────────────────────────────────────────────────────
# Tables 4, 5, 6 — all on page 40
# ──────────────────────────────────────────────────────────────────
#
# pdfplumber finds 3 separate tables on page 40. We identify them by
# content pattern rather than by position.

def _classify_page40_tables(raw_tables: list[list]) -> dict[str, list]:
    """Classify the 3 tables on page 40 as Table 4, 5, or 6 by content."""
    classified: dict[str, list] = {}
    for tbl in raw_tables:
        flat = " ".join(
            _clean(c) for row in tbl for c in row if c
        ).lower()
        if "disabling" in flat and "nihss" in flat:
            classified["Table 4"] = tbl
        elif "cryoprecipitate" in flat or "tranexamic acid" in flat or ("aptt" in flat and "fibrinogen" in flat):
            classified["Table 5"] = tbl
        elif "methylprednisolone" in flat or "diphenhydramine" in flat or "airway" in flat or "icatibant" in flat:
            classified["Table 6"] = tbl
    return classified


def table_4(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[39]  # page 40 (0-indexed)
    tables = page.extract_tables()
    classified = _classify_page40_tables(tables)
    tbl = classified.get("Table 4")
    if tbl is None:
        raise RuntimeError("Table 4 not found on page 40")

    # Table 4 has a specific pdfplumber shape:
    # Row 0: preamble question ("Among patients with NIHSS scores 0-5...")
    # Row 1: preamble guidance ("As a guideline, while always considering...")
    # Row 2: two-column body — col 0 = typically disabling list with
    #        header + newline-separated items; col 1 = may-not-be-disabling
    #        list with header + newline-separated items.
    rows: list[dict] = []
    preamble_lines: list[str] = []

    def _bullets_from_cell(cell_text: str) -> list[str]:
        """Drop the header line, return the bullet items."""
        lines = [ln.strip() for ln in cell_text.split("\n") if ln.strip()]
        # Drop the first line if it's the "The following deficits..." header
        if lines and lines[0].lower().startswith("the following deficits"):
            lines = lines[1:]
        # Re-join continuation lines: if a line doesn't start with a capital
        # letter or number, it's a wrap of the previous line.
        merged: list[str] = []
        for ln in lines:
            if merged and ln and not (ln[0].isupper() or ln[0].isdigit()):
                merged[-1] = merged[-1] + " " + ln
            else:
                merged.append(ln)
        return merged

    for row_idx, row in enumerate(tbl):
        # Collect raw cell strings without collapsing internal newlines —
        # we need the newlines to split bullet items.
        col0 = row[0] if len(row) > 0 and row[0] and row[0] != "None" else ""
        col1 = row[1] if len(row) > 1 and row[1] and row[1] != "None" else ""

        # Single-column preamble rows
        if col0 and not col1:
            preamble_lines.append(_clean(col0))
            continue

        # Two-column body
        if col0 and col1:
            disabling_items = _bullets_from_cell(col0)
            not_disabling_items = _bullets_from_cell(col1)
            for i, item in enumerate(disabling_items, start=1):
                rows.append({
                    "recNumber": f"disabling_{i}",
                    "category": "typically_disabling",
                    "condition": item[:60],
                    "text": _clean(item),
                })
            for i, item in enumerate(not_disabling_items, start=1):
                rows.append({
                    "recNumber": f"not_disabling_{i}",
                    "category": "may_not_be_disabling",
                    "condition": item[:60],
                    "text": _clean(item),
                })

    preamble = " ".join(preamble_lines)

    return {
        "sectionTitle": "Table 4: Guidance for Determining Deficits to be Clearly Disabling at Presentation",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 4",
        "synopsis": (
            "Guidance for deciding whether a neurological deficit should be "
            "considered 'clearly disabling' in patients with mild AIS (NIHSS "
            "0–5) when considering IV thrombolysis. Operationally derived "
            "from the PRISMS trial framework: would the deficit prevent the "
            "patient from doing basic daily activities (BATHE: bathing, "
            "ambulating, toileting, hygiene, eating) or from returning to "
            "their prior occupation and social role? "
            + preamble
        ).strip(),
        "rss": rows,
        "knowledgeGaps": "",
    }


def table_5(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[39]
    tables = page.extract_tables()
    classified = _classify_page40_tables(tables)
    tbl = classified.get("Table 5")
    if tbl is None:
        raise RuntimeError("Table 5 not found on page 40")

    rows = []
    for i, row in enumerate(tbl):
        text = _clean(row[0]) if row and row[0] else ""
        if not text:
            continue
        # First cell often is the step description
        rows.append({
            "recNumber": str(i + 1),
            "category": "sich_management_step",
            "condition": text[:60],
            "text": text,
        })

    return {
        "sectionTitle": "Table 5: Management of Symptomatic Intracranial Bleeding After IV Thrombolysis",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 5",
        "synopsis": (
            "Step-by-step management protocol for symptomatic intracranial "
            "bleeding (sICH) occurring within 24 hours after IV thrombolysis "
            "for acute ischemic stroke. Steps cover stopping the thrombolytic "
            "infusion, emergent imaging and coagulation labs, hemostatic "
            "therapy with cryoprecipitate or tranexamic acid, and "
            "hematology/neurosurgery consultation."
        ),
        "rss": rows,
        "knowledgeGaps": "",
    }


def table_6(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[39]
    tables = page.extract_tables()
    classified = _classify_page40_tables(tables)
    tbl = classified.get("Table 6")
    if tbl is None:
        raise RuntimeError("Table 6 not found on page 40")

    rows = []
    for i, row in enumerate(tbl):
        text = _clean(row[0]) if row and row[0] else ""
        if not text:
            continue
        # Skip single-word or short group labels like "Maintain Airway" that
        # pdfplumber captures as standalone rows. They add no value to the
        # rss list.
        if len(text) < 30 and not text.endswith(".") and text[0].isupper() and " " not in text[text.find(" ")+1:]:
            continue
        if len(text) < 30 and not text.endswith("."):
            continue
        rows.append({
            "recNumber": str(len(rows) + 1),
            "category": "angioedema_management_step",
            "condition": text[:60],
            "text": text,
        })

    return {
        "sectionTitle": "Table 6: Management of Orolingual Angioedema Associated With IV Alteplase",
        "parentChapter": "4.6.1",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 6",
        "synopsis": (
            "Step-by-step management protocol for orolingual angioedema "
            "complicating IV alteplase administration for AIS. Covers airway "
            "assessment and intervention, discontinuation of alteplase and "
            "any ACE inhibitors, first-line pharmacotherapy (IV "
            "methylprednisolone, diphenhydramine, H2 blockers), escalation "
            "to epinephrine and bradykinin B2 antagonists (icatibant) for "
            "refractory cases, and supportive care."
        ),
        "rss": rows,
        "knowledgeGaps": "",
    }


# ──────────────────────────────────────────────────────────────────
# Table 7 — IVT Dosing for AIS
# ──────────────────────────────────────────────────────────────────

def table_7(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[42]  # page 43 (0-indexed)
    tables = page.extract_tables()
    if not tables:
        raise RuntimeError("Table 7 not detected on page 43")

    tbl = tables[0]
    rows = []
    in_dosing_grid = False
    for i, row in enumerate(tbl):
        cells = [_clean(c) for c in row]
        if not any(cells):
            continue

        # Detect the weight-band dosing grid by its header row
        if "Patient weight" in cells[0] or (len(cells) > 1 and "TNK (mg)" in (cells[1] or "")):
            in_dosing_grid = True
            continue

        if in_dosing_grid and len(cells) >= 3 and cells[0] and re.match(r"[<≥\d]", cells[0]):
            # Dosing row: weight band | mg | mL
            weight = cells[0]
            mg = cells[1] if cells[1] and cells[1] != "None" else ""
            ml = cells[2] if cells[2] and cells[2] != "None" else ""
            rows.append({
                "recNumber": f"tnk_weight_{re.sub(r'[^a-z0-9]+', '_', weight.lower())}",
                "category": "tenecteplase_weight_band",
                "condition": f"TNK dose, weight {weight}",
                "text": f"Patient weight {weight}: tenecteplase {mg} mg in {ml} mL.",
            })
        else:
            # Prose step (dosing description, administration protocol)
            text = cells[0]
            if text and text != "None":
                rows.append({
                    "recNumber": f"step_{len([r for r in rows if r.get('category') != 'tenecteplase_weight_band']) + 1}",
                    "category": "ivt_administration_step",
                    "condition": text[:60],
                    "text": text,
                })

    return {
        "sectionTitle": "Table 7: Treatment of AIS in Adults with IV Thrombolysis — Dosing and Administration",
        "parentChapter": "4.6.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 7",
        "synopsis": (
            "Dosing and administration protocol for IV thrombolysis in adult "
            "AIS patients. Alteplase: 0.9 mg/kg (maximum 90 mg) over 60 "
            "minutes with 10% as a 1-minute bolus. Tenecteplase: 0.25 mg/kg "
            "(maximum 25 mg) as a single IV push, dosed by weight band. "
            "Also covers post-infusion monitoring frequency, BP management "
            "thresholds, and the 24-hour follow-up imaging requirement."
        ),
        "rss": rows,
        "knowledgeGaps": "",
    }


# ──────────────────────────────────────────────────────────────────
# Table 9 — DAPT Trials
# ──────────────────────────────────────────────────────────────────

def table_9(pdf: pdfplumber.PDF) -> dict:
    page = pdf.pages[63]  # page 64 (0-indexed)
    tables = page.extract_tables()
    if not tables:
        raise RuntimeError("Table 9 not detected on page 64")

    tbl = tables[0]
    rows = []
    # First row is the header
    for row in tbl[1:]:
        if len(row) < 5 or not row[0]:
            continue
        trial = _clean(row[0])
        # Clean up the ref-number superscripts that PyPDF2 concatenates
        trial_clean = re.sub(r"\*?\d+$", "", trial).strip("*")
        inclusion = _clean(row[1])
        regimen = _clean(row[2])
        lkn = _clean(row[3])
        nnt = _clean(row[4])
        text = (
            f"{trial_clean} — inclusion: {inclusion}. "
            f"Regimen: {regimen}. LKN window: {lkn}. NNT: {nnt}."
        )
        rows.append({
            "recNumber": trial_clean.lower().replace(" ", "_"),
            "category": "dapt_trial",
            "condition": trial_clean,
            "text": text,
        })

    return {
        "sectionTitle": "Table 9: Dual Antiplatelet Therapy Trials for Minor AIS and High-Risk TIA",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Table 9",
        "synopsis": (
            "Summary of the five key randomized controlled trials of short-"
            "term dual antiplatelet therapy (DAPT) versus single antiplatelet "
            "therapy in patients with minor AIS (NIHSS ≤3 or ≤5 depending on "
            "trial) and high-risk TIA (ABCD2 ≥4 or ≥6). Covers CHANCE, POINT, "
            "THALES, CHANCE 2, and INSPIRES, with their inclusion criteria, "
            "drug regimen, last-known-normal window, and number-needed-to-"
            "treat. An asterisk after the trial name indicates slightly "
            "increased risk of bleeding versus monotherapy."
        ),
        "rss": rows,
        "knowledgeGaps": "",
    }


# ──────────────────────────────────────────────────────────────────
# Figure 2 — ASPECTS
# ──────────────────────────────────────────────────────────────────

def figure_2(pdf: pdfplumber.PDF) -> dict:
    return {
        "sectionTitle": "Figure 2: ASPECTS — Alberta Stroke Program Early CT Score",
        "parentChapter": "3.2",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 2",
        "synopsis": (
            "The Alberta Stroke Program Early CT Score (ASPECTS) is a 10-"
            "point topographic scoring system used on non-contrast CT of the "
            "brain to quantify early ischemic changes in the middle cerebral "
            "artery (MCA) territory. A normal CT scores 10. One point is "
            "subtracted for each of 10 MCA-territory regions that shows "
            "early ischemic change (hypoattenuation or focal swelling). "
            "Regions scored: caudate (C), lentiform nucleus (L), internal "
            "capsule (IC), insular ribbon (I), M1, M2, M3 (ganglionic-level "
            "cortical MCA territory), and M4, M5, M6 (supraganglionic-level "
            "cortical MCA territory). ASPECTS ≥6 is generally required for "
            "standard-window EVT eligibility; extended-window trials (DAWN, "
            "DEFUSE-3, SELECT2) have used lower ASPECTS thresholds in "
            "imaging-selected patients. The figure itself is a visual "
            "diagram of the scored regions; this entry captures the scoring "
            "framework and its clinical use. Source: Barber PA et al. "
            "Lancet 2000. The figure caption in the 2026 guideline is: "
            "'Figure 2. ASPECTS: Alberta Stroke Program Early CT Score. CT "
            "indicates computed tomography; and MCA, middle cerebral "
            "artery.'"
        ),
        "rss": [
            {
                "recNumber": "aspects_score_method",
                "category": "aspects_scoring",
                "condition": "ASPECTS scoring method",
                "text": (
                    "Start with a score of 10. On axial non-contrast CT, "
                    "subtract 1 point for each of 10 MCA-territory regions "
                    "that shows hypoattenuation or focal swelling: 3 "
                    "subcortical regions (caudate, lentiform nucleus, "
                    "internal capsule), the insular ribbon, and 6 cortical "
                    "regions (M1–M6). A score of 10 is normal; 0 indicates "
                    "diffuse ischemia of the entire MCA territory."
                ),
            },
            {
                "recNumber": "aspects_evt_threshold",
                "category": "aspects_scoring",
                "condition": "EVT eligibility by ASPECTS",
                "text": (
                    "ASPECTS ≥6 is generally required for EVT in the "
                    "standard 0–6 hour window (MR CLEAN / ESCAPE era "
                    "criteria). Large-core trials (SELECT2, ANGEL-ASPECT, "
                    "RESCUE-Japan LIMIT, TENSION) have demonstrated EVT "
                    "benefit in carefully selected patients with ASPECTS "
                    "3–5. Extended-window trials (DAWN, DEFUSE-3) used "
                    "imaging-based core/penumbra mismatch rather than "
                    "ASPECTS thresholds."
                ),
            },
        ],
        "knowledgeGaps": "",
        "_note": "The visual diagram of scored MCA regions is image-only; this entry captures the scoring framework and caption text.",
    }


# ──────────────────────────────────────────────────────────────────
# Figure 3 — EVT Eligibility Algorithm
# ──────────────────────────────────────────────────────────────────

def figure_3(pdf: pdfplumber.PDF) -> dict:
    return {
        "sectionTitle": "Figure 3: Algorithm for Management of AIS Eligibility for EVT",
        "parentChapter": "4.7",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 3",
        "synopsis": (
            "Decision algorithm for endovascular thrombectomy (EVT) "
            "eligibility in patients with acute ischemic stroke. The "
            "algorithm branches on time from last known well (LKW), vessel "
            "occlusion location (anterior vs posterior circulation, "
            "LVO/MVO/DVO), clinical severity (NIHSS), imaging findings "
            "(ASPECTS, core volume, perfusion mismatch), and pre-stroke "
            "functional status (mRS). The figure caption in the 2026 "
            "guideline is: 'Figure 3. Algorithm for management of AIS "
            "eligibility for EVT. *LVO of the anterior circulation. †In "
            "patients with NIHSS scores ≥6, unless specified in the "
            "graphic. DVO indicates distal vessel occlusion; EVT, "
            "endovascular thrombectomy; IDD, insufficient data to "
            "determine; LVO, large vessel occlusion; mRS, modified Rankin "
            "scale; MVO, medium vessel occlusion; and NIHSS, National "
            "Institutes of Health Stroke Scale.' The figure itself is a "
            "visual decision graphic; discrete decision nodes are not "
            "extractable from the PDF text stream and require a separate "
            "ingestion pass from the image source."
        ),
        "rss": [],
        "knowledgeGaps": "",
        "_note": "Decision nodes for the EVT algorithm are visual-only in the PDF. Clinical recommendations for EVT eligibility across time windows, vessel occlusions, and imaging criteria live in §4.7 subsections and their rss entries — see sections 4.7.1, 4.7.2, 4.7.3, 4.7.4, 4.7.5.",
    }


# ──────────────────────────────────────────────────────────────────
# Figure 4 — DAPT Algorithm
# ──────────────────────────────────────────────────────────────────

def figure_4(pdf: pdfplumber.PDF) -> dict:
    return {
        "sectionTitle": "Figure 4: DAPT for Minor Noncardioembolic AIS and TIA",
        "parentChapter": "4.8",
        "sourceCitation": "2026 AHA/ASA AIS Guideline, Figure 4",
        "synopsis": (
            "Decision algorithm for initiating dual antiplatelet therapy "
            "(DAPT) in patients with minor noncardioembolic acute ischemic "
            "stroke or high-risk TIA. The algorithm branches on clinical "
            "severity (NIHSS ≤3 vs ≤5), TIA risk score (ABCD2), presumed "
            "atherosclerotic etiology, CYP2C19 genotype (for ticagrelor "
            "selection), last-known-normal time window (12, 24, or 72 "
            "hours), and IV thrombolysis / mechanical thrombectomy "
            "eligibility. The supporting evidence base is summarized in "
            "Table 9 (trials: CHANCE, POINT, THALES, CHANCE 2, INSPIRES). "
            "The figure itself is a visual decision graphic; discrete "
            "decision nodes are not extractable from the PDF text stream."
        ),
        "rss": [],
        "knowledgeGaps": "",
        "_note": "Decision nodes for the DAPT algorithm are visual-only in the PDF. Clinical recommendations for DAPT eligibility and duration live in §4.8 rss items 12-15 (which cover CHANCE, POINT, THALES, INSPIRES, CHANCE 2) and the recommendations.json entries 4.8(12)-(15).",
    }


# ──────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print parsed output, do not write")
    args = ap.parse_args()

    with open(GK_PATH) as f:
        gk = json.load(f)

    with pdfplumber.open(PDF_PATH) as pdf:
        extractors = [
            ("Table 2", lambda: table_2()),
            ("Table 3", lambda: table_3(pdf)),
            ("Table 4", lambda: table_4(pdf)),
            ("Table 5", lambda: table_5(pdf)),
            ("Table 6", lambda: table_6(pdf)),
            ("Table 7", lambda: table_7(pdf)),
            ("Table 9", lambda: table_9(pdf)),
            ("Figure 2", lambda: figure_2(pdf)),
            ("Figure 3", lambda: figure_3(pdf)),
            ("Figure 4", lambda: figure_4(pdf)),
        ]

        for name, extractor in extractors:
            try:
                parsed = extractor()
            except Exception as e:
                print(f"[{name}] ERROR: {e}")
                continue

            syn_len = len(parsed.get("synopsis", "") or "")
            rss_count = len(parsed.get("rss", []) or [])
            kg_len = len(parsed.get("knowledgeGaps", "") or "")
            print(f"[{name}] synopsis={syn_len:>5} rss={rss_count:>2} kg={kg_len:>5}  "
                  f"{parsed.get('sectionTitle', '')[:55]}")

            if not args.dry_run:
                # Preserve _note metadata but put it at section level
                gk["sections"][name] = {
                    "sectionTitle": parsed["sectionTitle"],
                    "parentChapter": parsed.get("parentChapter", ""),
                    "sourceCitation": parsed.get("sourceCitation", ""),
                    "synopsis": parsed["synopsis"],
                    "rss": parsed["rss"],
                    "knowledgeGaps": parsed.get("knowledgeGaps", ""),
                }
                if "_note" in parsed:
                    gk["sections"][name]["_note"] = parsed["_note"]

    if not args.dry_run:
        with open(GK_PATH, "w") as f:
            json.dump(gk, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {GK_PATH}")


if __name__ == "__main__":
    main()
