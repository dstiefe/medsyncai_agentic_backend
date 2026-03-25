"""P6: Acute management protocol extraction — BP targets, medication protocols."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import get_guideline_studies, search_extracted_tables, NOT_REPORTED

# Keywords that indicate management protocol queries
_MANAGEMENT_KEYWORDS = [
    "blood pressure", "bp target", "antiplatelet", "anticoagulation",
    "heparin", "aspirin", "statin", "temperature", "glucose",
    "npo", "dvt", "prophylaxis", "swallow", "dysphagia",
    "decompressive", "craniectomy", "icu", "monitoring",
]


async def execute_p6(intent: ClassifiedIntent) -> ProtocolResult:
    """Extract acute management protocol data from guidelines."""
    keyword = intent.field_requested or intent.original_query or ""
    guideline_studies = get_guideline_studies()

    if not guideline_studies:
        return ProtocolResult(
            protocol="P6",
            query=intent.original_query,
            data={"error": "No guideline documents found in the database."},
            data_found=False,
        )

    # Search for management-related tables
    search_terms = [keyword]
    for mk in _MANAGEMENT_KEYWORDS:
        if mk in keyword.lower():
            search_terms.append(mk)

    all_tables = []
    for gs in guideline_studies:
        for term in search_terms:
            tables = search_extracted_tables(gs.get("study_id"), term)
            for t in tables:
                t["source_guideline"] = gs.get("trial_acronym") or gs.get("full_title")
                t["year"] = gs.get("pub_year")
                if t not in all_tables:
                    all_tables.append(t)

    if not all_tables:
        return ProtocolResult(
            protocol="P6",
            query=intent.original_query,
            data={"message": NOT_REPORTED},
            data_found=False,
        )

    return ProtocolResult(
        protocol="P6",
        query=intent.original_query,
        data={
            "tables": all_tables,
            "count": len(all_tables),
        },
        data_found=True,
        source_tables=["extracted_tables"],
    )
