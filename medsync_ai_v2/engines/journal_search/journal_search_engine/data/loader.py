"""
SQLite data loader for the Journal Search Engine.

Loads the trial database from medsync_stroke.db at startup.
Provides structured access to studies, treatment arms, outcomes,
inclusion criteria, safety data, and subgroup analyses.
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from typing import Any, Optional


# Default: resolve relative to this file up to the shared folder root
_DEFAULT_DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "..", "..", "..",  # Up to Shared Folders For MedSync/
    "MedSync-Journal-Search", "data",
    "medsync_stroke.db",
))

# Allow env var override for deployment flexibility
_DB_PATH = os.getenv("JOURNAL_DB_PATH", _DEFAULT_DB_PATH)


def _get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Study loading ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_all_studies() -> tuple[dict, ...]:
    """Load all studies as dicts with their related data."""
    conn = _get_connection()
    studies = []

    rows = conn.execute("""
        SELECT * FROM studies
        WHERE document_type IS NULL OR document_type = 'article'
        ORDER BY pub_year DESC, trial_acronym
    """).fetchall()

    for row in rows:
        study = dict(row)
        sid = study["study_id"]

        # Treatment arms
        study["treatment_arms"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM treatment_arms WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Inclusion criteria
        study["inclusion_criteria"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM inclusion_criteria WHERE study_id=? ORDER BY sort_order", (sid,)
            ).fetchall()
        ]

        # Exclusion criteria
        study["exclusion_criteria"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM exclusion_criteria WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Primary outcomes
        study["primary_outcomes"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM primary_outcomes WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Secondary outcomes
        study["secondary_outcomes"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM secondary_outcomes WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Safety outcomes
        study["safety_outcomes"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM safety_outcomes WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Subgroup analyses
        study["subgroup_analyses"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM subgroup_analyses WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Imaging criteria
        study["imaging_criteria"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM imaging_criteria WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Process metrics
        study["process_metrics"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM process_metrics WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        # Reperfusion metrics
        study["reperfusion_metrics"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM reperfusion_metrics WHERE study_id=?", (sid,)
            ).fetchall()
        ]

        studies.append(study)

    conn.close()
    return tuple(studies)


@lru_cache(maxsize=1)
def load_rcts() -> tuple[dict, ...]:
    """Return only RCT studies."""
    return tuple(s for s in load_all_studies() if s.get("is_rct"))


@lru_cache(maxsize=1)
def load_reference_documents() -> tuple[dict, ...]:
    """Return reference documents (protocols, guidelines, supplements)."""
    conn = _get_connection()
    rows = conn.execute("""
        SELECT * FROM studies
        WHERE document_type IN ('supplement', 'protocol', 'guideline', 'duplicate')
           OR (is_imrad = 0 AND is_rct = 0)
        ORDER BY trial_acronym
    """).fetchall()
    conn.close()
    return tuple(dict(r) for r in rows)


# ── Convenience accessors ──────────────────────────────────────


def get_study_by_acronym(acronym: str) -> Optional[dict]:
    """Get a single study by trial acronym."""
    for s in load_all_studies():
        if (s.get("trial_acronym") or "").upper() == acronym.upper():
            return s
    return None


def get_studies_by_intervention(intervention: str) -> list[dict]:
    """Get studies where a treatment arm matches the intervention."""
    results = []
    intervention_lower = intervention.lower()
    for s in load_all_studies():
        for arm in s.get("treatment_arms", []):
            desc = (arm.get("arm_description") or "").lower()
            arm_type = (arm.get("arm_type") or "").lower()
            # Match EVT
            if intervention_lower in ("evt", "thrombectomy", "endovascular"):
                if arm.get("thrombectomy_allowed"):
                    results.append(s)
                    break
            # Match IVT agents
            elif intervention_lower in ("alteplase", "tenecteplase", "ivt", "thrombolysis"):
                if arm.get("ivt_allowed") or arm.get("ivt_required"):
                    ivt_drug = (arm.get("ivt_drug") or "").lower()
                    if intervention_lower in ("ivt", "thrombolysis") or intervention_lower in ivt_drug:
                        results.append(s)
                        break
            # Generic match on description
            elif intervention_lower in desc:
                results.append(s)
                break
    return results


def get_studies_by_circulation(circulation: str) -> list[dict]:
    """Filter studies by circulation type."""
    return [
        s for s in load_all_studies()
        if (s.get("circulation_type") or "").lower() == circulation.lower()
    ]


def get_subgroups_for_variable(variable: str) -> list[dict]:
    """Find all subgroup analyses across all studies for a given variable."""
    conn = _get_connection()
    rows = conn.execute("""
        SELECT sa.*, s.trial_acronym, s.pub_year, s.study_design
        FROM subgroup_analyses sa
        JOIN studies s ON s.study_id = sa.study_id
        WHERE sa.subgroup_variable LIKE ?
        ORDER BY s.pub_year DESC
    """, (f"%{variable}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_inclusion_criteria(keyword: str) -> list[dict]:
    """Search inclusion criteria text across all studies."""
    conn = _get_connection()
    rows = conn.execute("""
        SELECT ic.*, s.trial_acronym, s.pub_year
        FROM inclusion_criteria ic
        JOIN studies s ON s.study_id = ic.study_id
        WHERE ic.criterion_text LIKE ?
        ORDER BY s.pub_year DESC
    """, (f"%{keyword}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Summary ────────────────────────────────────────────────────


def get_database_summary() -> dict[str, Any]:
    """Return summary stats about the loaded database."""
    conn = _get_connection()
    total = conn.execute("SELECT COUNT(*) FROM studies WHERE document_type IS NULL OR document_type='article'").fetchone()[0]
    rcts = conn.execute("SELECT COUNT(*) FROM studies WHERE is_rct=1 AND (document_type IS NULL OR document_type='article')").fetchone()[0]
    non_rcts = total - rcts
    anterior = conn.execute("SELECT COUNT(*) FROM studies WHERE circulation_type='anterior' AND is_rct=1").fetchone()[0]
    basilar = conn.execute("SELECT COUNT(*) FROM studies WHERE circulation_type='basilar' AND is_rct=1").fetchone()[0]
    subgroups = conn.execute("SELECT COUNT(*) FROM subgroup_analyses").fetchone()[0]
    safety = conn.execute("SELECT COUNT(*) FROM safety_outcomes").fetchone()[0]
    conn.close()

    return {
        "total_trials": total,
        "total_reference_docs": len(load_reference_documents()),
        "rct_count": rcts,
        "non_rct_count": non_rcts,
        "anterior_count": anterior,
        "basilar_count": basilar,
        "subgroup_analyses": subgroups,
        "safety_outcomes": safety,
    }
