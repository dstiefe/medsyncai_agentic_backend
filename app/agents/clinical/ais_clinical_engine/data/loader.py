from __future__ import annotations
"""
JSON data loader for the AIS Clinical Engine.

Reads guideline data from JSON files at startup and returns
the same in-memory structures the agents expect.
"""

import json
import os
from functools import lru_cache
from typing import Any

_DATA_DIR = os.path.dirname(__file__)


def _load_json(filename: str) -> dict:
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Recommendations ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_recommendations() -> list[dict]:
    """Return flat list of all 202 AHA/ASA 2026 recommendations."""
    data = _load_json("recommendations.json")
    return data["recommendations"]


@lru_cache(maxsize=1)
def load_recommendations_by_id() -> dict[str, dict]:
    """Return recommendations keyed by ID (e.g. 'rec-4.6.1-001')."""
    return {r["id"]: r for r in load_recommendations()}


def get_recommendations_by_section(section: str) -> list[dict]:
    """Filter recommendations by section number (e.g. '4.6.1')."""
    return [r for r in load_recommendations() if r["section"] == section]


def get_recommendations_by_category(category: str) -> list[dict]:
    """Filter recommendations by category (e.g. 'ivt_decision')."""
    return [r for r in load_recommendations() if r["category"] == category]


# ── IVT Rules (Table 8 + Table 4) ───────────────────────────────


@lru_cache(maxsize=1)
def _load_ivt_data() -> dict:
    return _load_json("ivt_rules.json")


def load_table8_rules() -> list[dict]:
    """Return all Table 8 contraindication rules."""
    return _load_ivt_data()["table8_rules"]


def load_table8_rules_by_tier(tier: str) -> list[dict]:
    """Filter Table 8 rules by tier ('absolute', 'relative', 'benefit_over_risk')."""
    return [r for r in load_table8_rules() if r["tier"] == tier]


def load_table4_checks() -> list[dict]:
    """Return Table 4 disabling deficit checks (field, threshold, label)."""
    return _load_ivt_data()["table4_disabling_checks"]


def load_table4_logic() -> dict:
    """Return Table 4 logic parameters (nihss threshold, description)."""
    return _load_ivt_data()["table4_logic"]


# ── Table 3: Imaging Criteria (Extended Window Thrombolysis) ─────


@lru_cache(maxsize=1)
def _load_table3_data() -> dict:
    return _load_json("table3_imaging_criteria.json")


def load_table3_trials() -> list[dict]:
    """Return all extended window thrombolysis imaging criteria by trial."""
    return _load_table3_data()["trials"]


def load_table3_trial(trial_name: str) -> dict | None:
    """Return imaging criteria for a specific trial (e.g. 'EXTEND')."""
    for t in load_table3_trials():
        if t["trial"].upper() == trial_name.upper():
            return t
    return None


# ── Table 5: ICH Management ─────────────────────────────────────


@lru_cache(maxsize=1)
def _load_table5_data() -> dict:
    return _load_json("table5_ich_management.json")


def load_table5_steps() -> list[dict]:
    """Return ICH management protocol steps (post-IVT bleeding)."""
    return _load_table5_data()["steps"]


# ── Table 6: Angioedema Management ──────────────────────────────


@lru_cache(maxsize=1)
def _load_table6_data() -> dict:
    return _load_json("table6_angioedema_management.json")


def load_table6_steps() -> list[dict]:
    """Return angioedema management protocol steps (post-IVT)."""
    return _load_table6_data()["steps"]


# ── Table 7: IVT Treatment Protocol ─────────────────────────────


@lru_cache(maxsize=1)
def _load_table7_data() -> dict:
    return _load_json("table7_ivt_treatment.json")


def load_table7_drugs() -> list[dict]:
    """Return IVT drug protocols (alteplase + tenecteplase dosing)."""
    return _load_table7_data()["drugs"]


def load_table7_monitoring() -> list[dict]:
    """Return post-IVT monitoring protocol steps."""
    return _load_table7_data()["post_treatment_monitoring"]


def load_table7_drug(drug_name: str) -> dict | None:
    """Return protocol for a specific drug ('alteplase' or 'tenecteplase')."""
    for d in load_table7_drugs():
        if d["drug"].lower() == drug_name.lower():
            return d
    return None


# ── Table 9: DAPT Trials ────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_table9_data() -> dict:
    return _load_json("table9_dapt_trials.json")


def load_table9_trials() -> list[dict]:
    """Return all DAPT trial data (CHANCE, POINT, THALES, etc.)."""
    return _load_table9_data()["trials"]


def load_table9_trial(trial_name: str) -> dict | None:
    """Return data for a specific DAPT trial (e.g. 'CHANCE')."""
    for t in load_table9_trials():
        if t["trial"].upper() == trial_name.upper():
            return t
    return None


# ── Figures Metadata ─────────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_figures_data() -> dict:
    return _load_json("figures_metadata.json")


def load_figures() -> list[dict]:
    """Return metadata for all guideline figures."""
    return _load_figures_data()["figures"]


def load_figure(number: int) -> dict | None:
    """Return metadata for a specific figure by number (1-5)."""
    for f in load_figures():
        if f["number"] == number:
            return f
    return None


# ── EVT Rules ────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_evt_rules() -> list[dict]:
    """Return EVT eligibility rules (condition-action pairs)."""
    data = _load_json("evt_rules.json")
    return data["rules"]


# ── Checklist Templates ──────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_checklist_data() -> dict:
    return _load_json("checklist_templates.json")


def load_checklist_domain(domain: str) -> list[dict]:
    """Return checklist rules for a specific domain."""
    return _load_checklist_data()["domains"].get(domain, [])


def load_all_checklist_rules() -> list[dict]:
    """Return all checklist rules across all domains."""
    domains = _load_checklist_data()["domains"]
    return [rule for rules in domains.values() for rule in rules]


def load_domain_labels() -> dict[str, str]:
    """Return domain ID → display label mapping."""
    return _load_checklist_data()["domain_labels"]


# ── Guideline Knowledge Store ────────────────────────────────────


@lru_cache(maxsize=1)
def load_guideline_knowledge() -> dict:
    """Return guideline knowledge store (RSS, synopsis, knowledge gaps)."""
    return _load_json("guideline_knowledge.json")


# ── Recommendation Criteria (CMI matching) ─────────────────────


@lru_cache(maxsize=1)
def load_recommendation_criteria() -> dict[str, dict]:
    """Return pre-extracted criteria for each recommendation.

    Used by RecommendationMatcher for CMI-style applicability matching.
    Returns empty dict if the criteria file has not been generated yet.
    """
    path = os.path.join(_DATA_DIR, "recommendation_criteria.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ── Convenience: load everything at once ─────────────────────────


def load_table_by_number(number: int) -> dict | None:
    """Return structured content for a guideline table by number (3-9).

    Tables 4 and 8 are in ivt_rules.json; others have dedicated files.
    """
    loaders = {
        3: lambda: _load_table3_data(),
        4: lambda: {"table4_disabling_checks": load_table4_checks(), "table4_logic": load_table4_logic()},
        5: lambda: _load_table5_data(),
        6: lambda: _load_table6_data(),
        7: lambda: _load_table7_data(),
        8: lambda: {"table8_rules": load_table8_rules()},
        9: lambda: _load_table9_data(),
    }
    loader = loaders.get(number)
    return loader() if loader else None


def load_all() -> dict[str, Any]:
    """Load all guideline data. Useful for engine initialization."""
    return {
        "recommendations": load_recommendations(),
        "recommendations_by_id": load_recommendations_by_id(),
        "table3_trials": load_table3_trials(),
        "table4_checks": load_table4_checks(),
        "table4_logic": load_table4_logic(),
        "table5_steps": load_table5_steps(),
        "table6_steps": load_table6_steps(),
        "table7_drugs": load_table7_drugs(),
        "table7_monitoring": load_table7_monitoring(),
        "table8_rules": load_table8_rules(),
        "table9_trials": load_table9_trials(),
        "figures": load_figures(),
        "evt_rules": load_evt_rules(),
        "checklist_rules": load_all_checklist_rules(),
        "domain_labels": load_domain_labels(),
        "guideline_knowledge": load_guideline_knowledge(),
    }
