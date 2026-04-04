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


def load_all() -> dict[str, Any]:
    """Load all guideline data. Useful for engine initialization."""
    return {
        "recommendations": load_recommendations(),
        "recommendations_by_id": load_recommendations_by_id(),
        "table8_rules": load_table8_rules(),
        "table4_checks": load_table4_checks(),
        "table4_logic": load_table4_logic(),
        "evt_rules": load_evt_rules(),
        "checklist_rules": load_all_checklist_rules(),
        "domain_labels": load_domain_labels(),
        "guideline_knowledge": load_guideline_knowledge(),
    }
