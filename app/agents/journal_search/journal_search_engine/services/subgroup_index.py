"""
subgroup_index.py — Pre-index subgroup analyses from SQLite.

Uses the structured subgroup_analyses table instead of scanning raw text.
Maps subgroup variables to the query field names used by the matcher.
"""

from __future__ import annotations

from typing import Optional
from ..data.loader import load_all_studies


# Map subgroup variable names in DB to matcher field names
VARIABLE_MAP = {
    "aspects": "aspects_range",
    "ASPECTS": "aspects_range",
    "pc-aspects": "pc_aspects_range",
    "PC-ASPECTS": "pc_aspects_range",
    "age": "age_range",
    "nihss": "nihss_range",
    "NIHSS": "nihss_range",
    "time_window": "time_window_hours",
    "time": "time_window_hours",
    "onset_to_treatment": "time_window_hours",
    "vessel": "vessel_occlusion",
    "occlusion_site": "vessel_occlusion",
    "occlusion_location": "vessel_occlusion",
    "ivt_received": "ivt_status",
    "ivt": "ivt_status",
}


def _normalize_variable(var_name):
    """Map a subgroup variable name to a matcher field name."""
    lower = var_name.lower().strip()
    for key, mapped in VARIABLE_MAP.items():
        if key.lower() in lower:
            return mapped
    return None


def build_subgroup_index():
    """
    Build a subgroup index from the SQLite subgroup_analyses table.
    
    Returns:
        {trial_id: {variable_name: {"found": True, "details": "...", "source": "subgroup_analyses"}}}
    """
    studies = load_all_studies()
    index = {}

    for study in studies:
        trial_id = study.get("trial_acronym") or "study_{}".format(study.get("study_id"))
        trial_subgroups = {}

        for sg in study.get("subgroup_analyses", []):
            raw_var = sg.get("subgroup_variable") or ""
            label = sg.get("subgroup_label") or ""
            effect = sg.get("effect_size")
            ci_lower = sg.get("ci_lower")
            ci_upper = sg.get("ci_upper")

            mapped_var = _normalize_variable(raw_var)
            if not mapped_var:
                continue

            ci_str = " ({}-{})".format(ci_lower, ci_upper) if ci_lower and ci_upper else ""
            effect_str = " effect={}{}".format(effect, ci_str) if effect else ""
            detail = "{} {}{}".format(raw_var, label, effect_str).strip()

            if mapped_var not in trial_subgroups:
                trial_subgroups[mapped_var] = {
                    "found": True,
                    "details": detail,
                    "source": "subgroup_analyses",
                    "subgroup_labels": [label],
                }
            else:
                trial_subgroups[mapped_var]["subgroup_labels"].append(label)
                all_labels = trial_subgroups[mapped_var]["subgroup_labels"]
                trial_subgroups[mapped_var]["details"] = "{}: {}".format(raw_var, ", ".join(all_labels))

        if trial_subgroups:
            index[trial_id] = trial_subgroups

    return index


_subgroup_index = None


def get_subgroup_index():
    """Get or build the subgroup index (cached)."""
    global _subgroup_index
    if _subgroup_index is None:
        _subgroup_index = build_subgroup_index()
    return _subgroup_index


def trial_has_subgroup_data(trial_id, variable):
    """Check if a trial has subgroup data for a specific variable."""
    index = get_subgroup_index()
    trial_data = index.get(trial_id, {})
    return trial_data.get(variable)
