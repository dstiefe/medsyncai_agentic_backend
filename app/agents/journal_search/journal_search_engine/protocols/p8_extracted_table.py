"""P8: Extracted table data retrieval — fallback when structured fields lack the answer."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import resolve_trial_acronym, search_extracted_tables, NOT_REPORTED


async def execute_p8(intent: ClassifiedIntent) -> ProtocolResult:
    """Search extracted_tables by keyword when structured fields don't have the answer."""
    study = resolve_trial_acronym(intent.trial_acronym) if intent.trial_acronym else None
    keyword = intent.field_requested or intent.definition_term or ""

    # Extract meaningful keywords from the original query
    if not keyword and intent.original_query:
        # Use the query itself as search term, minus common stop words
        stop = {"what", "is", "the", "for", "of", "in", "was", "were", "are",
                "how", "did", "does", "do", "a", "an", "show", "me", "tell",
                "about", "from", "with", "trial", "study"}
        words = intent.original_query.lower().split()
        keyword = " ".join(w for w in words if w not in stop)

    study_id = study.get("study_id") if study else None
    tables = search_extracted_tables(study_id, keyword)

    if not tables:
        trial_name = study.get("trial_acronym") if study else intent.trial_acronym
        return ProtocolResult(
            protocol="P8",
            trial_acronym=trial_name,
            query=intent.original_query,
            data={"message": NOT_REPORTED},
            data_found=False,
            source_tables=["extracted_tables"],
        )

    return ProtocolResult(
        protocol="P8",
        trial_acronym=study.get("trial_acronym") if study else None,
        query=intent.original_query,
        data={
            "tables": tables,
            "count": len(tables),
        },
        data_found=True,
        source_tables=["extracted_tables"],
    )
