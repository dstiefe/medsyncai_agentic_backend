#!/usr/bin/env python3
"""
Transform v1 MedSync reference files into v2.

Changes are deliberately conservative:
- All existing values are PRESERVED so a human reviewer can compare.
- New structured fields are ADDED alongside (not replacing) original values.
- Known bugs with high confidence (duplicate-self synonyms, ICH↔HT conflict,
  stent-retriever brand mis-categorization) are fixed and logged in a changelog.
- Suspected cross-section leakage is FLAGGED, not deleted, because verification
  requires the 2026 AIS Guideline source text.

Repo-relative paths: reads from and writes to the qa/references directory.
Run from repo root: python3 scripts/transform_refs.py
"""
import json
import re
import copy
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
REFS = REPO_ROOT / "app" / "agents" / "clinical" / "ais_clinical_engine" / "agents" / "qa" / "references"
SRC = REFS
OUT = REFS
OUT.mkdir(parents=True, exist_ok=True)

# =============================================================================
# data_dictionary.v2
# =============================================================================

def parse_bp(val):
    """Parse BP strings like '185/110 mmHg' or '<140 mmHg SBP' into structured form."""
    if not isinstance(val, str):
        return None
    v = val.strip()
    m = re.match(r"([<>]=?)?\s*(\d+)\s*/\s*(\d+)\s*(mmHg)?", v)
    if m:
        op = m.group(1) or "="
        return {"operator": op, "sbp": int(m.group(2)), "dbp": int(m.group(3)), "unit": "mmHg"}
    m = re.match(r"([<>]=?)?\s*(\d+)\s*mmHg\s*(SBP|DBP|MAP)?", v)
    if m:
        op = m.group(1) or "="
        comp = (m.group(3) or "SBP").upper()
        return {"operator": op, comp.lower(): int(m.group(2)), "unit": "mmHg", "component": comp}
    return None

def parse_threshold_pct(val):
    """Parse '93%' -> {value: 93, unit: '%'}."""
    if not isinstance(val, str): return None
    m = re.match(r"([<>]=?)?\s*(\d+(?:\.\d+)?)\s*%", val.strip())
    if m:
        return {"operator": m.group(1) or "=", "value": float(m.group(2)), "unit": "%"}
    return None

def parse_time_window(val):
    """Parse '4.5h', '6-24h', '0-4.5h', '132 min', etc."""
    if not isinstance(val, str): return None
    v = val.strip()
    # range: "6-24h", "0-4.5h", "3-22h"
    m = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*h$", v)
    if m:
        return {"min_h": float(m.group(1)), "max_h": float(m.group(2)), "unit": "h"}
    # single: "4.5h"
    m = re.match(r"(\d+(?:\.\d+)?)\s*h$", v)
    if m:
        return {"value_h": float(m.group(1)), "unit": "h"}
    # minutes: "132 min", "120 min"
    m = re.match(r"(\d+)\s*min$", v)
    if m:
        return {"value_h": int(m.group(1)) / 60, "unit": "min", "original_value": int(m.group(1))}
    # "15 minutes"
    m = re.match(r"(\d+)\s*minutes?$", v)
    if m:
        return {"value_h": int(m.group(1)) / 60, "unit": "min", "original_value": int(m.group(1))}
    return None

def parse_glucose(val):
    """Parse '50 mg/dL' or '<60 mg/dL'."""
    if not isinstance(val, str): return None
    m = re.match(r"([<>]=?)?\s*(\d+)\s*mg/dL", val.strip())
    if m:
        return {"operator": m.group(1) or "=", "value": int(m.group(2)), "unit": "mg/dL"}
    return None

def parse_dose(val):
    """Parse '0.9 mg/kg (max 90 mg)' style doses."""
    if not isinstance(val, str): return None
    out = {"original": val}
    m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", val)
    if m: out["mg_per_kg"] = float(m.group(1))
    m = re.search(r"max\s*(\d+(?:\.\d+)?)\s*mg", val)
    if m: out["max_mg"] = float(m.group(1))
    m = re.search(r"(\d+)\s*%\s*bolus", val)
    if m: out["bolus_pct"] = int(m.group(1))
    m = re.search(r"(\d+)\s*min\s*infusion", val)
    if m: out["infusion_min"] = int(m.group(1))
    return out if len(out) > 1 else None

def parse_age(val):
    """Parse '80' or '>=6' as age threshold."""
    if isinstance(val, (int, float)): return {"value_years": float(val), "unit": "years"}
    if not isinstance(val, str): return None
    m = re.match(r"([<>]=?)?\s*(\d+)", val.strip())
    if m:
        return {"operator": m.group(1) or "=", "value_years": int(m.group(2)), "unit": "years"}
    return None

def parse_nihss(val):
    if not isinstance(val, str): return None
    v = val.strip()
    m = re.match(r"(\d+)\s*-\s*(\d+)$", v)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2))}
    m = re.match(r"([<>]=?)?\s*(\d+)$", v)
    if m:
        return {"operator": m.group(1) or "=", "value": int(m.group(2))}
    return None

# Sections flagged for cross-section leakage review. These are sections where
# the existing v1 data contains values that look implausibly broad for the
# section's actual clinical scope. Values are NOT deleted — the flag tells
# reviewers to verify against guideline source text.
LEAKAGE_SUSPECTS = {
    "4.1": {
        "concern": "Section is about Airway/Breathing/Oxygenation. v1 has vessel=[LVO] and time_window spanning 2h-72h which look like values leaked from EVT/IVT recommendations that happen to co-occur in the corpus. SpO2 thresholds (93%, 100%) are legitimate.",
        "review_variables": ["time_window", "vessel", "intervention.EVT"]
    },
    "4.2": {
        "concern": "Section is Head Positioning. v1 has vessel=[LVO, MCA], NIHSS=4, premorbid_mRS=0, perfusion imaging — all look like leakage from adjacent recommendations. Only head-of-bed-angle values should be here.",
        "review_variables": ["vessel", "circulation", "NIHSS", "premorbid_mRS", "imaging"]
    },
    "4.4": {
        "concern": "v1 metadata flags duplicated content with 4.5 (glucose values leaked in). Current v1 temperature value 37.5C is legit; verify no glucose values present.",
        "review_variables": ["_all"]
    },
    "4.5": {
        "concern": "v1 metadata flags duplicated content with 4.4 (temperature values leaked in). Current v1 glucose structured_thresholds are legit; verify no temperature values present.",
        "review_variables": ["_all"]
    },
    "4.6.2": {
        "concern": "v1 metadata flags: 0 recs in guideline_knowledge.json but criteria exist in recommendation_criteria.json. Section content is incomplete.",
        "review_variables": ["_all"]
    }
}

# Canonical type taxonomy for v2. v1 had ad-hoc types; v2 normalizes.
V2_TYPE_MAP = {
    "categorical": "categorical",
    "threshold": "threshold",
    "range": "range",
    "onset_hours": "time_window_hours",
    "modality": "modality_enum",
    "qualifier": "qualifier_enum",
    "dose": "dose",
    "structured_doses": "structured_doses",
    "structured_thresholds": "structured_thresholds",
    "reperfusion_grade": "reperfusion_grade_enum",
    "systolic_threshold": "systolic_bp_threshold",
    "process_metric": "process_metric",
    "range_mL": "volume_range_mL",
    "mixed": "mixed_needs_review"
}

# Mechanical fix list — v1 intervention values that map to a canonical synonym term ID.
# Only includes high-confidence matches. Others left unlinked for the LLM/reviewer.
# NOTE: alteplase -> tPA because in v1 synonym_dictionary.json, tPA is the canonical
# term_id and "alteplase" is listed as one of its synonyms.
INTERVENTION_TO_TERM_ID = {
    "EVT": "EVT",
    "IVT": "IVT",
    "alteplase": "tPA",
    "tenecteplase": "TNK",
    "tPA": "tPA",
    "aspirin": "aspirin",
    "clopidogrel": "clopidogrel",
    "ticagrelor": "ticagrelor",
    "heparin": "heparin",
    "DOAC": "DOAC",
    "LMWH": "LMWH",
    "IPC": "IPC",
    "antiplatelet": "antiplatelet",
    "antihypertensive": "antihypertensive",
    "anticoagulant": "anticoagulant",
    "stent retriever": "stent_retriever",
    "aspiration": "aspiration",
    "stenting": "stenting",
    "carotid endarterectomy": "CEA",
    "craniectomy": "decompressive_hemicraniectomy",
    "decompressive surgery": "decompressive_hemicraniectomy",
    "ventriculostomy": "ventriculostomy",
    "mannitol": "mannitol",
    "hypertonic saline": "hypertonic_saline",
    "pneumatic compression": "IPC",
    "supplemental oxygen": "supplemental_O2"
}


def transform_variable(var_name, var_obj):
    """Transform a single variable entry from v1 shape to v2 shape."""
    if not isinstance(var_obj, dict):
        return var_obj
    out = copy.deepcopy(var_obj)
    v1_type = out.get("type", "unknown")
    out["type"] = V2_TYPE_MAP.get(v1_type, v1_type)
    out.setdefault("source_rec_ids", [])  # empty; for human reviewer to fill
    out.setdefault("synonym_term_ids", [])

    values = out.get("values")
    parsed = None

    if var_name == "BP":
        if isinstance(values, list):
            parsed = [parse_bp(v) for v in values]
        elif isinstance(values, dict):
            parsed = {k: parse_bp(v) if isinstance(v, str) else [parse_bp(x) for x in v] if isinstance(v, list) else v
                      for k, v in values.items()}
    elif var_name == "SpO2":
        if isinstance(values, list):
            parsed = [parse_threshold_pct(v) for v in values]
    elif var_name == "time_window":
        if isinstance(values, list):
            parsed = [parse_time_window(v) for v in values]
    elif var_name == "glucose":
        if isinstance(values, list):
            parsed = [parse_glucose(v) for v in values]
        elif isinstance(values, dict):
            parsed = {k: parse_glucose(v) if isinstance(v, str) else [parse_glucose(x) for x in v] if isinstance(v, list) else v
                      for k, v in values.items()}
    elif var_name in ("drug_dose",):
        if isinstance(values, list):
            parsed = [parse_dose(v) for v in values]
        elif isinstance(values, dict):
            parsed = {k: parse_dose(v) for k, v in values.items()}
    elif var_name == "age":
        if isinstance(values, list):
            parsed = [parse_age(v) for v in values]
    elif var_name == "NIHSS":
        if isinstance(values, list):
            parsed = [parse_nihss(v) for v in values]
    elif var_name == "intervention":
        if isinstance(values, list):
            term_ids = [INTERVENTION_TO_TERM_ID.get(v) for v in values]
            out["synonym_term_ids"] = [t for t in term_ids if t]
            unlinked = [v for v, t in zip(values, term_ids) if not t]
            if unlinked:
                out["unlinked_values"] = unlinked

    if parsed is not None:
        out["parsed_values"] = parsed
    return out


def transform_data_dictionary():
    src = json.load(open(SRC / "data_dictionary.json"))
    changelog = []

    v2 = {
        "metadata": {
            "schema_version": "2.0.0",
            "derived_from": "data_dictionary.json v1",
            "purpose": src["metadata"]["purpose"],
            "source": src["metadata"]["source"],
            "v1_known_issues": src["metadata"]["notes"],
            "v2_changes": [],  # filled below
            "changes_needing_human_review": [
                "Cross-section leakage verification for sections flagged in review_flags (see individual sections)",
                "Fill source_rec_ids[] on every variable (currently empty) by tracing back to guideline_knowledge.json",
                "Verify parsed_values block for all threshold/range/dose variables against the original strings",
                "Resolve 4.4/4.5 temperature-glucose leak (v1 metadata issue)",
                "Backfill 4.6.2 content from recommendation_criteria.json"
            ],
            "usage_notes": [
                "Every variable now has source_rec_ids[] and synonym_term_ids[]; populate these during review",
                "parsed_values is present for numeric variables — Python should prefer parsed_values over values for arithmetic comparison",
                "review_flags at section level indicates sections with known or suspected data quality issues; route-around logic should treat these sections with lower confidence until resolved",
                "Section-level synonym_term_ids[] (when present) lists term IDs that anchor the section for routing — used by SectionRouter for term-ID intersection"
            ]
        },
        "sections": {}
    }

    changes = v2["metadata"]["v2_changes"]
    changes.append("Added schema_version field (2.0.0)")
    changes.append(f"Normalized type taxonomy to v2 canonical types: {sorted(set(V2_TYPE_MAP.values()))}")
    changes.append("Added source_rec_ids[] and synonym_term_ids[] to every variable (empty; for human reviewer to populate)")
    changes.append("Added parsed_values for BP, SpO2, time_window, glucose, drug_dose, age, NIHSS variables — structured numeric representation for Python arithmetic")
    changes.append("Linked intervention[] values to synonym_dictionary term IDs where a high-confidence mapping exists; unlinked values flagged in unlinked_values[]")
    changes.append("Added review_flags[] at section level for sections with suspected cross-section leakage (4.1, 4.2) and known v1 data-quality issues (4.4, 4.5, 4.6.2). Original values PRESERVED — values are flagged for review, not deleted.")
    changes.append("Carried through section-level synonym_term_ids[] from v1 (anchor terms for SectionRouter intersection matching).")

    # Keys that live at the section level, not inside a variable.
    SECTION_LEVEL_KEYS = {"title", "subheadings", "note", "data_quality_note", "synonym_term_ids"}

    for sec_id, sec_obj in src["sections"].items():
        new_sec = {"title": sec_obj.get("title", "")}
        # preserve subheadings
        if "subheadings" in sec_obj:
            new_sec["subheadings"] = sec_obj["subheadings"]
        # preserve note
        if "note" in sec_obj:
            new_sec["note"] = sec_obj["note"]
        # preserve data_quality_note
        if "data_quality_note" in sec_obj:
            new_sec["data_quality_note"] = sec_obj["data_quality_note"]
        # preserve section-level synonym_term_ids (fixture-forced anchors for routing)
        if "synonym_term_ids" in sec_obj:
            new_sec["synonym_term_ids"] = list(sec_obj["synonym_term_ids"])

        # transform variables
        for k, v in sec_obj.items():
            if k in SECTION_LEVEL_KEYS:
                continue
            new_sec[k] = transform_variable(k, v)

        # add review_flags if section is in leakage suspect list
        if sec_id in LEAKAGE_SUSPECTS:
            new_sec["review_flags"] = {
                "needs_review": True,
                "concern": LEAKAGE_SUSPECTS[sec_id]["concern"],
                "review_variables": LEAKAGE_SUSPECTS[sec_id]["review_variables"]
            }

        v2["sections"][sec_id] = new_sec

    v2["metadata"]["section_count"] = len(v2["sections"])
    v2["metadata"]["sections_flagged_for_review"] = sorted(LEAKAGE_SUSPECTS.keys())
    return v2, changes


# =============================================================================
# synonym_dictionary.v2
# =============================================================================

# Category consolidation map. Conservative: only collapse cases where the
# boundary is genuinely redundant. Ambiguous cases kept separate with notes.
CATEGORY_CONSOLIDATION = {
    # near-duplicate outcome taxonomy
    "outcome_scale": "outcome_measure",
    # clinical_cardiac is a subdomain of clinical_condition
    "clinical_cardiac": "clinical_condition",
    # imaging_finding and imaging_physiology are subdomains of imaging; keep separate for now
}

# Overloaded abbreviations in a clinical context. We note the alternative
# interpretation so the LLM classifier can flag ambiguity when it appears in
# a question where the stroke-guideline interpretation might not apply.
OVERLOAD_NOTES = {
    "CT": {"alt_interpretations": ["cardiothoracic"], "guideline_context": "computed tomography"},
    "PE": {"alt_interpretations": ["physical exam", "pulmonary edema"], "guideline_context": "pulmonary embolism"},
    "MS": {"alt_interpretations": ["multiple sclerosis", "mitral stenosis"], "guideline_context": "not_in_dictionary"},
    "MR": {"alt_interpretations": ["mitral regurgitation"], "guideline_context": "magnetic resonance"},
    "HT": {"alt_interpretations": ["hypertension"], "guideline_context": "hemorrhagic transformation",
           "critical_note": "HT in this guideline means hemorrhagic transformation, NOT hypertension. Use HTN for hypertension."}
}


def transform_synonym_dictionary():
    src = json.load(open(SRC / "synonym_dictionary.json"))
    changes = []
    bug_fixes = []

    new_terms = {}
    v1_comments = {}
    category_to_terms = defaultdict(list)
    full_term_to_id = {}
    conflicts_resolved = []

    for tid, entry in src["terms"].items():
        if not isinstance(entry, dict):
            # v1 used _comment_* string entries as inline documentation
            v1_comments[tid] = entry
            continue
        e = copy.deepcopy(entry)

        # -------- BUG FIX: ICH should NOT have 'hemorrhagic transformation' as a synonym
        if tid == "ICH" and "hemorrhagic transformation" in (e.get("synonyms") or []):
            e["synonyms"] = [s for s in e["synonyms"] if s != "hemorrhagic transformation"]
            bug_fixes.append({
                "term": "ICH",
                "fix": "removed 'hemorrhagic transformation' from synonyms",
                "reason": "HT is a separate term. HT's own clinical_context explicitly states it is distinct from ICH. Leaving this synonym on ICH caused the same string to collide with two different canonical concepts."
            })

        # -------- BUG FIX: EVT should not claim 'Solitaire' or 'Trevo' as synonyms
        if tid == "EVT":
            if e.get("synonyms"):
                removed = [s for s in e["synonyms"] if s.lower() in ("solitaire", "trevo")]
                if removed:
                    e["synonyms"] = [s for s in e["synonyms"] if s.lower() not in ("solitaire", "trevo")]
                    bug_fixes.append({
                        "term": "EVT",
                        "fix": f"removed brand-name synonyms {removed}",
                        "reason": "Solitaire and Trevo are specific stent-retriever device brands, not EVT procedure synonyms. They remain on the stent_retriever entry."
                    })

        # -------- BUG FIX: self-duplicate synonym (e.g. BP with full_term 'blood pressure' and synonym 'blood pressure')
        ft_lower = (e.get("full_term") or "").lower()
        if e.get("synonyms"):
            original_syns = list(e["synonyms"])
            deduped = [s for s in e["synonyms"] if s.lower() != ft_lower]
            if len(deduped) != len(original_syns):
                removed_dup = [s for s in original_syns if s.lower() == ft_lower]
                e["synonyms"] = deduped
                bug_fixes.append({
                    "term": tid,
                    "fix": f"removed self-duplicate synonym {removed_dup}",
                    "reason": "Synonym entry was identical to the full_term, creating a noise collision."
                })

        # -------- category consolidation
        old_cat = e.get("category")
        if old_cat in CATEGORY_CONSOLIDATION:
            new_cat = CATEGORY_CONSOLIDATION[old_cat]
            e["category"] = new_cat
            e["_v1_category"] = old_cat
            conflicts_resolved.append(f"{tid}: category {old_cat} -> {new_cat}")

        new_terms[tid] = e
        category_to_terms[e.get("category", "uncategorized")].append(tid)
        if ft_lower:
            full_term_to_id.setdefault(ft_lower, []).append(tid)

    # Rebuild category_index from actual terms (v1 had missing categories)
    new_category_index = {
        "_doc": src.get("category_index", {}).get("_doc", "Category → list of term IDs"),
    }
    for cat, ids in sorted(category_to_terms.items()):
        new_category_index[cat] = sorted(ids)

    # Build reverse index (full_term → term_ids, list because some full_terms repeat)
    reverse_index = {ft: ids for ft, ids in sorted(full_term_to_id.items()) if ft}

    # Overload table: only include entries whose ID actually exists in the dict
    overload_table = {k: v for k, v in OVERLOAD_NOTES.items() if k in new_terms}

    # Flag duplicate full_term claims (e.g., DTAS/DTAS_procedure) — documented not deleted
    duplicate_full_terms = {ft: ids for ft, ids in reverse_index.items() if len(ids) > 1}

    v2 = {
        "metadata": {
            "schema_version": "2.0.0",
            "derived_from": "synonym_dictionary.json v1",
            "purpose": src["metadata"]["purpose"],
            "source": src["metadata"]["source"],
            "usage": src["metadata"]["usage"],
            "v2_changes": [
                "Added schema_version field (2.0.0)",
                "Rebuilt category_index from actual terms content. v1 had 12 categories in terms that were missing from category_index (clinical_cardiac, core_term, guideline_framework, imaging_finding, imaging_physiology, organization, quality_program, reference_standard, risk_score, route_of_administration, study_design, systems_process) and 2 categories in category_index with no matching terms (imaging_concept, surgery).",
                "Added reverse_index (full_term -> [term_ids]) for O(1) canonical-form -> abbreviation lookup",
                "Added overload_table for abbreviations with alternate medical meanings, so the QAQueryParsingAgent can flag ambiguity",
                "Added duplicate_full_terms_report so the reviewer can decide whether DTAS/DTAS_procedure and GTN/GTN_drug style splits should be merged or kept distinct",
                "Applied bug_fixes[] (see top-level for details) — removed ICH↔HT synonym collision, removed stent-retriever brand names from EVT, removed self-duplicate synonyms (BP, DOAC, ICP, MSU, SpO2, PC-ASPECTS)",
                "Consolidated category clinical_cardiac -> clinical_condition and outcome_scale -> outcome_measure; original v1 category preserved in _v1_category on each affected entry"
            ],
            "changes_needing_human_review": [
                "Review the overload_table entries and decide whether to add disambiguation prompts to the LLM parser",
                "Review duplicate_full_terms_report and decide whether to merge pairs like DTAS/DTAS_procedure, GTN/GTN_drug",
                "Expand term coverage beyond the current terms — stroke specialty reasonably needs several hundred more terms for edge cases",
                "Review near-duplicate category taxonomy (assessment_scale vs screening_scale, clinical_finding vs clinical_condition) and document the rule or consolidate",
                "Add section mapping for terms currently marked 'all' — some could be narrowed"
            ]
        },
        "bug_fixes": bug_fixes,
        "v1_inline_comments": v1_comments,
        "terms": new_terms,
        "category_index": new_category_index,
        "reverse_index": reverse_index,
        "overload_table": overload_table,
        "duplicate_full_terms_report": duplicate_full_terms,
        "term_count": len(new_terms)
    }

    changes.extend(v2["metadata"]["v2_changes"])
    return v2, changes


# =============================================================================
# main
# =============================================================================

def main():
    dd_v2, dd_changes = transform_data_dictionary()
    sd_v2, sd_changes = transform_synonym_dictionary()

    (OUT / "data_dictionary.v2.json").write_text(json.dumps(dd_v2, indent=2, ensure_ascii=False))
    (OUT / "synonym_dictionary.v2.json").write_text(json.dumps(sd_v2, indent=2, ensure_ascii=False))

    print(f"data_dictionary.v2.json   : {(OUT / 'data_dictionary.v2.json').stat().st_size} bytes, {dd_v2['metadata']['section_count']} sections")
    print(f"synonym_dictionary.v2.json: {(OUT / 'synonym_dictionary.v2.json').stat().st_size} bytes, {sd_v2['term_count']} terms")
    print(f"bug fixes applied to synonyms: {len(sd_v2['bug_fixes'])}")
    for b in sd_v2['bug_fixes']:
        print(f"  - {b['term']}: {b['fix']}")
    print(f"data_dictionary sections flagged for review: {dd_v2['metadata']['sections_flagged_for_review']}")

if __name__ == "__main__":
    main()
