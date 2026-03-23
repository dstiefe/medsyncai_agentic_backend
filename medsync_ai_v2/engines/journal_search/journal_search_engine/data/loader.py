"""
JSON data loader for the Journal Search Engine.

Loads the trial Methods/Results database at startup and caches it.
Follows the same lru_cache pattern as the clinical engine loader.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

# Default: resolve relative to this file up to the shared folder root
_DEFAULT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "..", "..", "..",  # Up to Shared Folders For MedSync/
    "MedSync-Journal-Search", "data",
    "medsync_trial_methods_results.json",
))

# Allow env var override for deployment flexibility
_DATA_PATH = os.getenv("JOURNAL_DB_PATH", _DEFAULT_PATH)


def _load_json() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Trial Database ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_trial_database() -> dict:
    """Return the full trial database (trials + reference docs + summary)."""
    return _load_json()


@lru_cache(maxsize=1)
def load_trials() -> tuple[dict, ...]:
    """Return all structured IMRaD trials (tuple for lru_cache hashability)."""
    return tuple(load_trial_database()["trials"])


@lru_cache(maxsize=1)
def load_reference_documents() -> tuple[dict, ...]:
    """Return all reference documents (protocols, guidelines, etc.)."""
    return tuple(load_trial_database().get("reference_documents", []))


# ── Convenience filters ─────────────────────────────────────────


def get_trials_by_intervention(agent: str) -> list[dict]:
    """Filter trials by intervention agent (EVT, alteplase, tenecteplase)."""
    agent_upper = agent.upper()
    return [
        t for t in load_trials()
        if (t.get("intervention", {}).get("agent") or "").upper() == agent_upper
    ]


def get_trials_by_circulation(circ: str) -> list[dict]:
    """Filter trials by circulation (anterior, basilar, medical)."""
    return [
        t for t in load_trials()
        if t.get("metadata", {}).get("circulation") == circ
    ]


def get_trials_by_study_type(study_type: str) -> list[dict]:
    """Filter trials by study type (RCT, non-RCT)."""
    return [
        t for t in load_trials()
        if t.get("metadata", {}).get("study_type") == study_type
    ]


def get_reference_docs_for_trial(trial_id: str) -> list[dict]:
    """Find reference documents linked to a specific trial."""
    return [
        d for d in load_reference_documents()
        if d.get("parent_trial", "").upper() == trial_id.upper()
    ]


# ── Summary ─────────────────────────────────────────────────────


def get_database_summary() -> dict[str, Any]:
    """Return summary stats about the loaded database."""
    trials = load_trials()
    refs = load_reference_documents()
    return {
        "total_trials": len(trials),
        "total_reference_docs": len(refs),
        "rct_count": sum(1 for t in trials if t.get("metadata", {}).get("study_type") == "RCT"),
        "non_rct_count": sum(1 for t in trials if t.get("metadata", {}).get("study_type") == "non-RCT"),
        "anterior_count": sum(1 for t in trials if t.get("metadata", {}).get("circulation") == "anterior"),
        "basilar_count": sum(1 for t in trials if t.get("metadata", {}).get("circulation") == "basilar"),
    }
