"""
Shared database access layer for extraction protocols (P1-P8).

Provides trial resolution, field mapping, and SQL helpers.
All functions operate against the cached load_all_studies() data
or direct SQLite queries for extracted_tables.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from ..data.loader import load_all_studies, _get_connection


# ── Trial Resolution ──────────────────────────────────────────

# Common aliases and abbreviations
_TRIAL_ALIASES = {
    "MR CLEAN": "MR CLEAN",
    "MRCLEAN": "MR CLEAN",
    "MR-CLEAN": "MR CLEAN",
    "ESCAPE MEVO": "ESCAPE-MeVO",
    "ESCAPE-MEVO": "ESCAPE-MeVO",
    "ESCAPEMEVO": "ESCAPE-MeVO",
    "RESCUE JAPAN": "RESCUE-Japan LIMIT",
    "RESCUE-JAPAN": "RESCUE-Japan LIMIT",
    "RESCUE JAPAN LIMIT": "RESCUE-Japan LIMIT",
    "DEFUSE3": "DEFUSE 3",
    "DEFUSE-3": "DEFUSE 3",
    "EXTEND IA": "EXTEND-IA",
    "EXTENTIA": "EXTEND-IA",
    "EXTEND-IA TNK": "EXTEND-IA TNK",
    "SELECT 2": "SELECT2",
    "ANGEL ASPECT": "ANGEL-ASPECT",
    "RESCUE-JAPAN": "RESCUE-Japan LIMIT",
}


def resolve_trial_acronym(acronym: str) -> Optional[dict]:
    """
    Fuzzy-match a trial acronym against the studies cache.

    Priority: exact match > alias match > case-insensitive match > partial match.
    Returns the full study dict or None.
    """
    if not acronym:
        return None

    clean = acronym.strip()
    studies = load_all_studies()

    # 1. Exact match
    for s in studies:
        if s.get("trial_acronym") == clean:
            return s

    # 2. Alias lookup
    upper = clean.upper().replace("_", " ").replace("-", " ").strip()
    alias_key = upper.replace(" ", "-") if "-" in clean else upper
    for key, canonical in _TRIAL_ALIASES.items():
        if upper == key.upper() or alias_key == key.upper().replace(" ", "-"):
            for s in studies:
                if s.get("trial_acronym") == canonical:
                    return s

    # 3. Case-insensitive match
    for s in studies:
        if (s.get("trial_acronym") or "").upper() == upper:
            return s

    # 4. Partial match (acronym is substring of trial name)
    # Prefer exact substring over loose match
    partial_matches = []
    for s in studies:
        ta = (s.get("trial_acronym") or "").upper()
        if upper in ta or ta in upper:
            partial_matches.append(s)

    if len(partial_matches) == 1:
        return partial_matches[0]

    # If multiple partials, prefer the shorter name (exact match more likely)
    if partial_matches:
        partial_matches.sort(key=lambda s: len(s.get("trial_acronym", "")))
        return partial_matches[0]

    return None


def resolve_trial_group(group_label: str) -> list[str]:
    """Resolve a descriptive group label to a list of trial acronyms."""
    label = group_label.lower()

    for key, trials in TRIAL_GROUPS.items():
        if key in label:
            return trials

    # Dynamic fallback: query studies by circulation or study type
    if "anterior" in label:
        return [s["trial_acronym"] for s in load_all_studies()
                if s.get("circulation_type") == "anterior" and s.get("is_rct")]
    if "basilar" in label or "posterior" in label:
        return [s["trial_acronym"] for s in load_all_studies()
                if s.get("circulation_type") == "basilar" and s.get("is_rct")]

    return []


# ── Trial Groups ──────────────────────────────────────────────

TRIAL_GROUPS = {
    "large core": ["ANGEL-ASPECT", "SELECT2", "RESCUE-Japan LIMIT", "TENSION", "LASTE"],
    "late window": ["DAWN", "DEFUSE 3"],
    "early window": ["MR CLEAN", "ESCAPE", "EXTEND-IA", "SWIFT PRIME", "REVASCAT"],
    "basilar": ["ATTENTION", "BAOCHE", "BASICS"],
    "tenecteplase": ["EXTEND-IA TNK", "TASTE-A"],
    "distal": ["DISTAL", "ESCAPE-MeVO", "MR CLEAN-MED"],
    "mevo": ["ESCAPE-MeVO", "MR CLEAN-MED", "DISTAL"],
}


# ── Field Mapping ─────────────────────────────────────────────
# Maps natural language field names to (table_key, [columns]) pairs.
# table_key matches the key in the study dict from load_all_studies().

FIELD_MAP = {
    # ── Studies table (direct fields on the study dict) ──
    "time_window": ("_study", ["time_window_min_hours", "time_window_max_hours", "time_window_reference"]),
    "time window": ("_study", ["time_window_min_hours", "time_window_max_hours", "time_window_reference"]),
    "study_design": ("_study", ["study_design"]),
    "design": ("_study", ["study_design"]),
    "sample_size": ("_study", ["num_randomized", "num_analyzed"]),
    "sample size": ("_study", ["num_randomized", "num_analyzed"]),
    "enrollment": ("_study", ["num_screened", "num_randomized", "num_analyzed"]),
    "follow_up": ("_study", ["follow_up_duration"]),
    "follow up": ("_study", ["follow_up_duration"]),
    "blinding": ("_study", ["blinding"]),
    "early_termination": ("_study", ["early_termination", "early_termination_reason"]),
    "early termination": ("_study", ["early_termination", "early_termination_reason"]),
    "funding": ("_study", ["funding_source"]),
    "registration": ("_study", ["registration_number"]),
    "year": ("_study", ["pub_year"]),
    "journal": ("_study", ["journal"]),
    "title": ("_study", ["full_title"]),
    "circulation": ("_study", ["circulation_type"]),
    "key_findings": ("_study", ["key_findings_summary"]),
    "key findings": ("_study", ["key_findings_summary"]),
    "limitations": ("_study", ["limitations"]),
    "crossover": ("_study", ["crossover_n"]),
    "lost_to_followup": ("_study", ["lost_to_followup"]),
    "analysis_type": ("_study", ["analysis_type"]),

    # ── Related tables (lists of dicts stored under study dict keys) ──

    # Primary outcomes
    "primary_outcome": ("primary_outcomes", None),
    "primary_outcomes": ("primary_outcomes", None),
    "primary outcome": ("primary_outcomes", None),
    "efficacy": ("primary_outcomes", None),

    # Secondary outcomes
    "secondary_outcomes": ("secondary_outcomes", None),
    "secondary outcome": ("secondary_outcomes", None),
    "secondary outcomes": ("secondary_outcomes", None),

    # Safety
    "safety": ("safety_outcomes", None),
    "safety_outcomes": ("safety_outcomes", None),
    "safety outcomes": ("safety_outcomes", None),
    "sich": ("safety_outcomes", None),
    "symptomatic ich": ("safety_outcomes", None),
    "symptomatic hemorrhage": ("safety_outcomes", None),
    "hemorrhage": ("safety_outcomes", None),
    "ich": ("safety_outcomes", None),
    "mortality": ("safety_outcomes", None),
    "death": ("safety_outcomes", None),
    "device_complications": ("safety_outcomes", None),
    "device complications": ("safety_outcomes", None),
    "embolization": ("safety_outcomes", None),
    "decompressive_craniectomy": ("safety_outcomes", None),

    # Inclusion/exclusion
    "inclusion_criteria": ("inclusion_criteria", None),
    "inclusion criteria": ("inclusion_criteria", None),
    "inclusion": ("inclusion_criteria", None),
    "eligibility": ("inclusion_criteria", None),
    "exclusion_criteria": ("exclusion_criteria", None),
    "exclusion criteria": ("exclusion_criteria", None),
    "exclusion": ("exclusion_criteria", None),
    "contraindications": ("exclusion_criteria", None),

    # Imaging
    "imaging_criteria": ("imaging_criteria", None),
    "imaging criteria": ("imaging_criteria", None),
    "imaging": ("imaging_criteria", None),
    "imaging requirements": ("imaging_criteria", None),
    "ct": ("imaging_criteria", None),
    "cta": ("imaging_criteria", None),
    "ctp": ("imaging_criteria", None),
    "mri": ("imaging_criteria", None),
    "dwi": ("imaging_criteria", None),
    "perfusion": ("imaging_criteria", None),
    "collateral": ("imaging_criteria", None),
    "collaterals": ("imaging_criteria", None),

    # Treatment arms
    "treatment_arms": ("treatment_arms", None),
    "treatment arms": ("treatment_arms", None),
    "arms": ("treatment_arms", None),
    "intervention": ("treatment_arms", None),
    "treatment": ("treatment_arms", None),
    "device": ("treatment_arms", None),
    "thrombectomy_device": ("treatment_arms", None),
    "ivt_drug": ("treatment_arms", None),
    "ivt_dose": ("treatment_arms", None),
    "anesthesia": ("treatment_arms", None),
    "anesthesia_protocol": ("treatment_arms", None),
    "antiplatelet": ("treatment_arms", None),
    "anticoagulation": ("treatment_arms", None),

    # Subgroup analyses
    "subgroup_analyses": ("subgroup_analyses", None),
    "subgroup analyses": ("subgroup_analyses", None),
    "subgroups": ("subgroup_analyses", None),
    "subgroup": ("subgroup_analyses", None),
    "subgroup analysis": ("subgroup_analyses", None),
    "interaction": ("subgroup_analyses", None),

    # Process metrics (from data dictionary: 28 variables)
    "process_metrics": ("process_metrics", None),
    "process metrics": ("process_metrics", None),
    "times": ("process_metrics", None),
    "time metrics": ("process_metrics", None),
    "door_to_needle": ("process_metrics", None),
    "door to needle": ("process_metrics", None),
    "door_to_groin": ("process_metrics", None),
    "door to groin": ("process_metrics", None),
    "onset_to_groin": ("process_metrics", None),
    "onset to groin": ("process_metrics", None),
    "onset_to_reperfusion": ("process_metrics", None),
    "onset to reperfusion": ("process_metrics", None),
    "onset_to_randomization": ("process_metrics", None),
    "onset to randomization": ("process_metrics", None),
    "puncture_to_reperfusion": ("process_metrics", None),
    "puncture to reperfusion": ("process_metrics", None),
    "groin to reperfusion": ("process_metrics", None),
    "procedure time": ("process_metrics", None),

    # Reperfusion metrics (from data dictionary: 12 trials with TICI data)
    "reperfusion": ("reperfusion_metrics", None),
    "reperfusion_metrics": ("reperfusion_metrics", None),
    "reperfusion metrics": ("reperfusion_metrics", None),
    "tici": ("reperfusion_metrics", None),
    "tici_2b_3": ("reperfusion_metrics", None),
    "tici 2b-3": ("reperfusion_metrics", None),
    "tici_2c_3": ("reperfusion_metrics", None),
    "tici 2c-3": ("reperfusion_metrics", None),
    "first_pass_effect": ("reperfusion_metrics", None),
    "first pass effect": ("reperfusion_metrics", None),
    "first pass": ("reperfusion_metrics", None),
    "recanalization": ("reperfusion_metrics", None),
    "recanalization_rate": ("reperfusion_metrics", None),
    "num_passes": ("reperfusion_metrics", None),
    "number of passes": ("reperfusion_metrics", None),
    "passes": ("reperfusion_metrics", None),

    # Demographics/baseline (from data dictionary: 89 variables)
    "demographics": ("_demographics", None),
    "baseline": ("_demographics", None),
    "baseline characteristics": ("_demographics", None),
    "baseline demographics": ("_demographics", None),
    "age": ("_demographics", None),
    "sex": ("_demographics", None),
    "female": ("_demographics", None),
    "male": ("_demographics", None),
    "nihss": ("_demographics", None),
    "nihss baseline": ("_demographics", None),
    "aspects": ("_demographics", None),
    "aspects baseline": ("_demographics", None),
    "hypertension": ("_demographics", None),
    "diabetes": ("_demographics", None),
    "atrial fibrillation": ("_demographics", None),
    "atrial_fibrillation": ("_demographics", None),
    "prior stroke": ("_demographics", None),
    "previous stroke": ("_demographics", None),
    "prestroke mrs": ("_demographics", None),
    "premorbid mrs": ("_demographics", None),
    "iv tpa": ("_demographics", None),
    "iv alteplase": ("_demographics", None),
    "iv thrombolysis": ("_demographics", None),
    "bridging therapy": ("_demographics", None),
    "ica occlusion": ("_demographics", None),
    "m1 occlusion": ("_demographics", None),
    "m2 occlusion": ("_demographics", None),
    "vessel occlusion": ("_demographics", None),
    "core volume": ("_demographics", None),
    "infarct core": ("_demographics", None),

    # Figures
    "figures": ("_figures", None),
    "forest plot": ("_figures", None),
    "kaplan meier": ("_figures", None),
    "flow diagram": ("_figures", None),
}


# ── SQL Helpers ───────────────────────────────────────────────


def get_study_field(study: dict, field_name: str) -> dict:
    """
    P1: Get specific field(s) from a study dict.

    Returns: {"field": field_name, "values": {col: val, ...}, "found": bool}
    """
    mapping = FIELD_MAP.get(field_name.lower())
    if not mapping:
        return {"field": field_name, "values": {}, "found": False}

    table_key, columns = mapping

    if table_key == "_study" and columns:
        values = {}
        for col in columns:
            val = study.get(col)
            if val is not None:
                values[col] = val
        return {"field": field_name, "values": values, "found": bool(values)}

    # Demographics: query baseline_demographics table
    if table_key == "_demographics":
        rows = get_baseline_demographics(study)
        return {"field": field_name, "values": rows, "found": bool(rows)}

    # Figures: query extracted_figures table
    if table_key == "_figures":
        rows = get_extracted_figures(study)
        return {"field": field_name, "values": rows, "found": bool(rows)}

    # For related tables, return the whole list
    if table_key and table_key != "_study":
        rows = study.get(table_key, [])
        return {"field": field_name, "values": rows, "found": bool(rows)}

    return {"field": field_name, "values": {}, "found": False}


def get_study_table_rows(study: dict, table_key: str) -> list[dict]:
    """
    P2/P3: Get all rows from a related table for a study.

    table_key is the key in the study dict (e.g., "primary_outcomes",
    "inclusion_criteria", "treatment_arms").
    """
    return study.get(table_key, [])


def get_multi_study_data(acronyms: list[str], table_keys: list[str] = None) -> list[dict]:
    """
    P4: Get structured data from multiple studies for comparison.

    Returns list of {trial_id, metadata, ...table_key: rows} dicts.
    """
    if table_keys is None:
        table_keys = ["primary_outcomes", "safety_outcomes", "treatment_arms",
                       "inclusion_criteria", "reperfusion_metrics"]

    results = []
    for acr in acronyms:
        study = resolve_trial_acronym(acr)
        if not study:
            continue
        entry = {
            "trial_id": study.get("trial_acronym"),
            "study_id": study.get("study_id"),
            "metadata": {
                "study_type": study.get("study_type") or ("RCT" if study.get("is_rct") else "non-RCT"),
                "circulation": study.get("circulation_type"),
                "journal": study.get("journal"),
                "year": study.get("pub_year"),
                "sample_size": study.get("num_randomized") or study.get("num_analyzed"),
            },
        }
        for tk in table_keys:
            entry[tk] = study.get(tk, [])
        results.append(entry)

    return results


def search_extracted_tables(study_id: int = None, keyword: str = "") -> list[dict]:
    """
    P8: Search extracted_tables by keyword in headers/data JSON.

    If study_id is given, search within that study only.
    """
    conn = _get_connection()
    kw = f"%{keyword}%"

    if study_id:
        rows = conn.execute(
            """SELECT et.*, s.trial_acronym FROM extracted_tables et
               JOIN studies s ON s.study_id = et.study_id
               WHERE et.study_id = ?
               AND (et.headers_json LIKE ? OR et.data_json LIKE ? OR et.table_title LIKE ?)""",
            (study_id, kw, kw, kw),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT et.*, s.trial_acronym FROM extracted_tables et
               JOIN studies s ON s.study_id = et.study_id
               WHERE et.headers_json LIKE ? OR et.data_json LIKE ? OR et.table_title LIKE ?""",
            (kw, kw, kw),
        ).fetchall()

    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        try:
            r["headers"] = json.loads(r.get("headers_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            r["headers"] = []
        try:
            r["data"] = json.loads(r.get("data_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            r["data"] = []
        results.append(r)

    return results


def get_guideline_studies() -> list[dict]:
    """P5/P6: Get studies classified as guidelines or scientific statements."""
    return [
        s for s in load_all_studies()
        if (s.get("study_type") or "").lower() in ("guideline", "review", "scientific statement")
    ]


def get_baseline_demographics(study: dict) -> list[dict]:
    """Get baseline demographics for a study from SQLite."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM baseline_demographics WHERE study_id = ? ORDER BY variable_name",
        (study.get("study_id"),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_extracted_figures(study: dict) -> list[dict]:
    """Get extracted figures for a study."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM extracted_figures WHERE study_id = ? ORDER BY figure_number",
        (study.get("study_id"),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _strip_nulls(d: dict) -> dict:
    """Remove keys with None values from a dict. Replace with NOT_REPORTED marker."""
    return {k: v for k, v in d.items() if v is not None}


NOT_REPORTED = "Not reported in the provided data"
