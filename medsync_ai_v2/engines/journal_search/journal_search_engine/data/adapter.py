"""
Adapter: converts SQLite study dicts to the format the TrialMatcher expects.

The matcher was built against the V1 JSON schema. This adapter maps
the V2 SQLite schema to V1 format so the matcher works without rewrite.
Will be removed when the matcher is rewritten for SQLite natively.
"""

from __future__ import annotations
import re
from typing import Optional


def adapt_study(study: dict) -> dict:
    """Convert a SQLite study dict to the V1 trial format for the matcher."""

    # ── Metadata ──
    metadata = {
        "study_type": "RCT" if study.get("is_rct") else "non-RCT",
        "circulation": study.get("circulation_type"),
        "journal": study.get("journal"),
        "year": study.get("pub_year"),
        "page_count": None,
    }

    # ── Inclusion criteria → flat dict of ranges ──
    ic = _build_inclusion_dict(study)

    # ── Intervention ──
    intervention = _build_intervention(study)

    # ── Results ──
    results = _build_results(study)

    # ── Raw text (empty — we use structured data now) ──
    raw_sections = {
        "methods_text": "",
        "results_text": "",
    }

    return {
        "trial_id": study.get("trial_acronym") or study.get("full_title") or f"study_{study.get('study_id')}",
        "study_id": study.get("study_id"),
        "source_pdf": study.get("pdf_filename", ""),
        "metadata": metadata,
        "inclusion_criteria": ic,
        "intervention": intervention,
        "results": results,
        "raw_sections": raw_sections,
        # Pass through the full SQLite data for the response formatter
        "_sqlite_study": study,
    }


def _build_inclusion_dict(study: dict) -> dict:
    """Build the flat inclusion criteria dict from SQLite rows."""
    ic = {
        "aspects_range": None,
        "pc_aspects_range": None,
        "nihss_range": None,
        "age_range": None,
        "premorbid_mrs": None,
        "time_window_hours": None,
        "vessel_occlusion": [],
        "imaging_required": [],
        "core_volume_ml": None,
        "mismatch_ratio": None,
    }

    # Parse criteria rows
    for criterion in study.get("inclusion_criteria", []):
        text = (criterion.get("criterion_text") or "").strip()
        category = (criterion.get("category") or "").lower()

        # ASPECTS
        if "aspects" in text.lower() and "pc-aspects" not in text.lower():
            ic["aspects_range"] = _parse_range_from_text(text)

        # PC-ASPECTS
        if "pc-aspects" in text.lower() or "pc aspects" in text.lower():
            ic["pc_aspects_range"] = _parse_range_from_text(text)

        # NIHSS
        if "nihss" in text.lower():
            ic["nihss_range"] = _parse_range_from_text(text)

        # Age
        if category == "age" or "age" in text.lower():
            ic["age_range"] = _parse_range_from_text(text)

        # mRS (premorbid)
        if "mrs" in text.lower() and ("pre" in text.lower() or "premorbid" in text.lower() or "prior" in text.lower()):
            ic["premorbid_mrs"] = _parse_range_from_text(text)

        # Vessel occlusion
        if category == "vessel" or "vessel" in text.lower() or "occlusion" in text.lower():
            vessels = _extract_vessels(text)
            if vessels:
                ic["vessel_occlusion"] = vessels

        # Core volume
        if "core" in text.lower() and ("ml" in text.lower() or "volume" in text.lower()):
            ic["core_volume_ml"] = _parse_range_from_text(text)

        # Mismatch ratio
        if "mismatch" in text.lower() and "ratio" in text.lower():
            ic["mismatch_ratio"] = _parse_range_from_text(text)

    # Time window from study-level fields
    tw_min = study.get("time_window_min_hours")
    tw_max = study.get("time_window_max_hours")
    tw_ref = study.get("time_window_reference")
    if tw_min is not None or tw_max is not None:
        ic["time_window_hours"] = {
            "min": tw_min,
            "max": tw_max,
            "from": tw_ref or "onset",
        }

    # Imaging from imaging_criteria table
    for img in study.get("imaging_criteria", []):
        modality = img.get("modality")
        if modality:
            ic["imaging_required"].append(modality)

    return ic


def _build_intervention(study: dict) -> dict:
    """Build the intervention dict from treatment arms."""
    result = {"agent": None, "comparator": None, "dose": None}

    arms = study.get("treatment_arms", [])
    for arm in arms:
        arm_type = (arm.get("arm_type") or "").lower()

        if arm_type in ("intervention", "experimental") or arm.get("thrombectomy_allowed"):
            if arm.get("thrombectomy_allowed"):
                result["agent"] = "EVT"
                device = arm.get("thrombectomy_device")
                if device:
                    result["device"] = device
            if arm.get("ivt_required") or (arm.get("ivt_drug") and not arm.get("thrombectomy_allowed")):
                drug = arm.get("ivt_drug") or "IVT"
                result["agent"] = result["agent"] or drug
                result["dose"] = arm.get("ivt_dose")

        elif arm_type in ("control", "comparator"):
            desc = (arm.get("arm_description") or "").lower()
            if "medical" in desc or "standard" in desc or "best medical" in desc:
                result["comparator"] = "medical management"
            elif arm.get("ivt_allowed") or arm.get("ivt_required"):
                result["comparator"] = arm.get("ivt_drug") or "IV tPA"
            elif "placebo" in desc:
                result["comparator"] = "placebo"

    # If no agent found from arms, check study-level
    if not result["agent"]:
        circ = study.get("circulation_type", "")
        if circ == "anterior":
            result["agent"] = "EVT"

    return result


def _build_results(study: dict) -> dict:
    """Build the results dict from outcome tables."""
    results = {
        "primary_outcome": {},
        "secondary_outcomes": [],
        "safety": {},
        "subgroups": [],
    }

    # Primary outcomes
    for po in study.get("primary_outcomes", []):
        results["primary_outcome"] = {
            "metric": po.get("outcome_name"),
            "definition": po.get("outcome_definition"),
            "intervention_value": po.get("intervention_result"),
            "control_value": po.get("control_result"),
            "effect_size": po.get("effect_size"),
            "effect_type": po.get("effect_measure"),
            "ci_95": [po.get("ci_lower"), po.get("ci_upper")] if po.get("ci_lower") else None,
            "p_value": po.get("p_value"),
            "nnt": po.get("nnt"),
        }
        break  # Take first primary outcome

    # Secondary outcomes
    for so in study.get("secondary_outcomes", []):
        results["secondary_outcomes"].append({
            "metric": so.get("outcome_name"),
            "intervention_value": so.get("intervention_result"),
            "control_value": so.get("control_result"),
            "effect_size": so.get("effect_size"),
            "effect_type": so.get("effect_measure"),
            "p_value": so.get("p_value"),
        })

    # Safety
    for sf in study.get("safety_outcomes", []):
        results["safety"] = {
            "sich_definition": sf.get("sich_definition"),
            "sich_intervention": sf.get("sich_intervention_pct"),
            "sich_control": sf.get("sich_control_pct"),
            "sich_p_value": sf.get("sich_p_value"),
            "any_ich_intervention": sf.get("any_ich_intervention_pct"),
            "any_ich_control": sf.get("any_ich_control_pct"),
            "mortality_90d_intervention": sf.get("mortality_intervention_pct"),
            "mortality_90d_control": sf.get("mortality_control_pct"),
            "mortality_p_value": sf.get("mortality_p_value"),
            "device_complications": sf.get("device_complications"),
        }
        break  # Take first safety row

    # Subgroups
    for sg in study.get("subgroup_analyses", []):
        results["subgroups"].append({
            "variable": sg.get("subgroup_variable"),
            "label": sg.get("subgroup_label"),
            "pre_specified": sg.get("pre_specified"),
            "effect_size": sg.get("effect_size"),
            "ci_lower": sg.get("ci_lower"),
            "ci_upper": sg.get("ci_upper"),
            "p_interaction": sg.get("p_interaction"),
            "favors": sg.get("favors"),
        })

    return results


# ── Parsing helpers ──────────────────────────────────────────


def _parse_range_from_text(text: str) -> Optional[dict]:
    """Parse a range like 'NIHSS 6-30' or 'ASPECTS 3 to 5' or 'Age 18-None' from criterion text."""
    # "X-Y" or "X to Y" pattern
    m = re.search(r'(\d+\.?\d*)\s*(?:to|–|—|-)\s*(\d+\.?\d*)', text)
    if m:
        return {"min": float(m.group(1)), "max": float(m.group(2))}

    # "X-None" pattern (open-ended)
    m = re.search(r'(\d+\.?\d*)\s*(?:to|–|—|-)\s*None', text)
    if m:
        return {"min": float(m.group(1)), "max": None}

    # "None-X" pattern
    m = re.search(r'None\s*(?:to|–|—|-)\s*(\d+\.?\d*)', text)
    if m:
        return {"min": None, "max": float(m.group(1))}

    # "≥X" or ">=X"
    m = re.search(r'(?:≥|>=)\s*(\d+\.?\d*)', text)
    if m:
        return {"min": float(m.group(1)), "max": None}

    # "≤X" or "<=X"
    m = re.search(r'(?:≤|<=)\s*(\d+\.?\d*)', text)
    if m:
        return {"min": None, "max": float(m.group(1))}

    # Single number
    m = re.search(r'(\d+\.?\d*)', text)
    if m:
        val = float(m.group(1))
        return {"min": val, "max": val}

    return None


def _extract_vessels(text: str) -> list[str]:
    """Extract vessel names from criterion text."""
    vessels = []
    vessel_map = {
        "ICA": r'\bICA\b',
        "M1": r'\bM1\b',
        "M2": r'\bM2\b',
        "M3": r'\bM3\b',
        "basilar": r'\bbasilar\b',
        "vertebral": r'\bvertebral\b',
        "ACA": r'\bACA\b',
        "PCA": r'\bPCA\b',
    }
    for name, pattern in vessel_map.items():
        if re.search(pattern, text, re.IGNORECASE):
            vessels.append(name)
    return vessels
