"""
subgroup_index.py — Pre-index subgroup variables from Results text, tables, and figures.

Scans each trial's Results section for subgroup analyses that report outcomes
by specific clinical variables (ASPECTS, age, NIHSS, time window, etc.).

This enables Tier 2 matching: even if a trial didn't use ASPECTS as an
inclusion criterion, if it reported results BY ASPECTS subgroups, it has
relevant data for ASPECTS-specific queries.
"""

from __future__ import annotations

import re
from typing import Optional
from ..data.loader import load_trials


# Patterns to detect subgroup analyses for each variable
SUBGROUP_PATTERNS = {
    "aspects_range": [
        r"ASPECTS?\s*(?:0|1|2|3|4|5|6|7|8|9|10)\s*(?:to|–|—|-)\s*(?:0|1|2|3|4|5|6|7|8|9|10)",
        r"ASPECTS?\s*(?:≥|>=|≤|<=|>|<)\s*\d+",
        r"ASPECTS?\s*(?:score|value)?\s*(?:subgroup|stratif|analys)",
        r"(?:subgroup|stratif|analys).*?ASPECTS?",
        r"ASPECTS?\s*(?:0\s*to\s*4|5\s*to\s*7|8\s*to\s*10)",  # Common MR CLEAN bins
        r"(?:low|high|favorable|unfavorable)\s*ASPECTS?",
    ],
    "age_range": [
        r"(?:age|aged)\s*(?:≥|>=|≤|<=|>|<)\s*\d+\s*(?:year|yr)",
        r"(?:age|aged)\s*\d+\s*(?:to|–|—|-)\s*\d+",
        r"(?:subgroup|stratif|analys).*?age",
        r"(?:elderly|older|younger)\s*(?:patient|subgroup)",
        r"(?:<|≤|>|≥)\s*(?:65|70|75|80|85)\s*(?:year|yr)",
    ],
    "nihss_range": [
        r"NIHSS\s*(?:≥|>=|≤|<=|>|<)\s*\d+",
        r"NIHSS\s*\d+\s*(?:to|–|—|-)\s*\d+",
        r"(?:subgroup|stratif|analys).*?NIHSS",
        r"(?:mild|moderate|severe)\s*(?:stroke|deficit).*?(?:subgroup|analys)",
    ],
    "time_window_hours": [
        r"(?:\d+\.?\d*)\s*(?:to|–|—|-)\s*(\d+\.?\d*)\s*(?:hour|hr|h)\s*(?:subgroup|window|stratif)",
        r"(?:early|late|extended)\s*(?:window|time).*?(?:subgroup|analys)",
        r"(?:<|≤|>|≥)\s*\d+\s*(?:hour|hr|h)",
        r"(?:0\s*to\s*6|6\s*to\s*12|6\s*to\s*24|12\s*to\s*24)\s*(?:hour|hr|h)",
    ],
    "vessel_occlusion": [
        r"(?:ICA|M1|M2|basilar).*?(?:subgroup|stratif|analys)",
        r"(?:subgroup|stratif|analys).*?(?:ICA|M1|M2|occlusion\s*(?:site|location))",
        r"(?:occlusion\s*(?:site|location)).*?(?:ICA|M1|M2)",
    ],
}


def build_subgroup_index() -> dict[str, dict]:
    """
    Build a subgroup index for all trials.

    Returns:
        {trial_id: {variable_name: {"found": True, "details": "ASPECTS 0-4, 5-7, 8-10", "source": "figure_3"}}}
    """
    trials = load_trials()
    index = {}

    for trial in trials:
        trial_id = trial.get("trial_id", "unknown")
        trial_subgroups = {}

        # Combine all searchable text — include Methods for pre-specified subgroup definitions
        results_text = trial.get("raw_sections", {}).get("results_text", "")
        methods_text = trial.get("raw_sections", {}).get("methods_text", "")
        results_norm = re.sub(r"\s+", " ", results_text)
        methods_norm = re.sub(r"\s+", " ", methods_text)

        # Table text
        table_text = ""
        for tbl in trial.get("tables", []):
            caption = tbl.get("caption") or ""
            rows = tbl.get("rows") or []
            table_text += caption + " " + " ".join(" ".join(r) for r in rows) + " "
        table_norm = re.sub(r"\s+", " ", table_text)

        # Figure descriptions
        figure_text = ""
        figure_sources = {}
        for fig in trial.get("figures", []):
            desc = (fig.get("description") or "") + " " + (fig.get("caption") or "")
            figure_text += desc + " "
            # Track which figure has which variable
            for var_name, patterns in SUBGROUP_PATTERNS.items():
                for pat in patterns:
                    if re.search(pat, desc, re.IGNORECASE):
                        figure_sources[var_name] = f"Figure {fig.get('figure_number', '?')}"

        figure_norm = re.sub(r"\s+", " ", figure_text)

        # Search all text for each variable (Methods for definitions, Results for data)
        all_text = methods_norm + " " + results_norm + " " + table_norm + " " + figure_norm

        for var_name, patterns in SUBGROUP_PATTERNS.items():
            # Skip if trial already has this as inclusion criteria
            ic = trial.get("inclusion_criteria", {})
            if ic.get(var_name) is not None:
                continue  # Already Tier 1 matchable, no need for subgroup

            for pat in patterns:
                match = re.search(pat, all_text, re.IGNORECASE)
                if match:
                    # Extract the specific subgroup details
                    details = _extract_subgroup_details(var_name, all_text)
                    source = figure_sources.get(var_name, "Results text")

                    trial_subgroups[var_name] = {
                        "found": True,
                        "details": details,
                        "source": source,
                        "match_text": match.group()[:100],
                    }
                    break

        if trial_subgroups:
            index[trial_id] = trial_subgroups

    return index


def _extract_subgroup_details(var_name: str, text: str) -> str:
    """Extract specific subgroup breakpoints from text."""
    if var_name == "aspects_range":
        # Look for ASPECTS groupings
        patterns = [
            r"ASPECTS?\s*((?:\d+\s*(?:to|–|—|-)\s*\d+\s*(?:,|and|or)\s*)+\d+\s*(?:to|–|—|-)\s*\d+)",
            r"ASPECTS?\s*(?:0\s*(?:to|–|-)\s*4|5\s*(?:to|–|-)\s*7|8\s*(?:to|–|-)\s*10)",
            r"ASPECTS?\s*(?:≥|>=|<|≤)\s*\d+",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group()[:80]
        return "ASPECTS subgroups reported"

    elif var_name == "age_range":
        m = re.search(r"(?:age|aged)\s*(?:≥|>=|<|≤|>)?\s*(\d+)\s*(?:to|–|—|-)?\s*(\d+)?", text, re.IGNORECASE)
        if m:
            return m.group()[:60]
        return "Age subgroups reported"

    elif var_name == "nihss_range":
        m = re.search(r"NIHSS\s*(?:≥|>=|<|≤|>)?\s*(\d+)\s*(?:to|–|—|-)?\s*(\d+)?", text, re.IGNORECASE)
        if m:
            return m.group()[:60]
        return "NIHSS subgroups reported"

    elif var_name == "time_window_hours":
        m = re.search(r"(\d+\.?\d*)\s*(?:to|–|—|-)\s*(\d+\.?\d*)\s*(?:hour|hr|h)", text, re.IGNORECASE)
        if m:
            return m.group()[:60]
        return "Time window subgroups reported"

    return "Subgroup data reported"


# Module-level cache
_subgroup_index: dict | None = None


def get_subgroup_index() -> dict[str, dict]:
    """Get or build the subgroup index (cached)."""
    global _subgroup_index
    if _subgroup_index is None:
        _subgroup_index = build_subgroup_index()
    return _subgroup_index


def trial_has_subgroup_data(trial_id: str, variable: str) -> dict | None:
    """
    Check if a trial has subgroup data for a specific variable.

    Returns subgroup info dict or None.
    """
    index = get_subgroup_index()
    trial_data = index.get(trial_id, {})
    return trial_data.get(variable)
